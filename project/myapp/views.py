from collections import defaultdict
import json
from django.db import transaction
import logging
from google_auth_oauthlib.flow import InstalledAppFlow
import os
import pickle
from datetime import datetime, timedelta
import hashlib
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.db.models import Q, Prefetch
from django.db.models import Avg
from .utils import create_google_calendar_event
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.http import JsonResponse
from django.conf import settings
from django.http import HttpResponse,  JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout  # เพิ่มบรรทัดนี้
from django.contrib import messages
import csv
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import send_mail
from .models import  Project, Appointment, AvailableTime,Teacher,Score, Member,Student
from .forms import NewsForm, AppointmentForm, ScoreForm,ProjectForm, FileForm 
from django.utils import timezone
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import *
from .forms import *
from .utils import get_role_from_email

def login_view(request):
    if request.user.is_authenticated:
        if request.user.is_student():
            return redirect('student_dashboard')
        elif request.user.is_teacher():
            return redirect('teacher_dashboard')
        elif request.user.is_manager():
            return redirect('manager_home')
        return redirect('login')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        if not email:
            messages.error(request, "กรุณากรอกอีเมล")
            return redirect('login')
        
        role = get_role_from_email(email)
        if role is None:
            messages.error(request, "อีเมลนี้ไม่ได้รับอนุญาต")
            return redirect('login')
        
        try:
            user = Member.objects.get(email=email)
            user.role = role
            user.save()
            
            from django.contrib.auth import login
            login(request, user)
            
            if user.is_student():
                return redirect('student_dashboard')
            elif user.is_teacher():
                return redirect('teacher_dashboard')
            elif user.is_manager():
                return redirect('manager_home')
            
        except Member.DoesNotExist:
            messages.error(request, "ไม่พบบัญชีผู้ใช้")
            return redirect('login')
        
    return render(request, 'registration/login.html')

@login_required
def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def student_dashboard(request):
    if not request.user.is_student():
        return redirect('login')
  
    current_date = timezone.now()
    
    two_days_ago = current_date - timedelta(days=2)
    
    news = News.objects.filter(created_at__gte=two_days_ago).order_by('-created_at')
    projects = Project.objects.filter(students=request.user)

    show_modal = False
    try:
        student = request.user.student  
        if not student.student_id:  
            show_modal = True
    except Student.DoesNotExist:
        show_modal = True  

    context = {
        'user': request.user,
        'news': news,
        'show_modal': show_modal,  
        'projects': projects
    }
    return render(request, 'student/dashboard.html', context)


def teacher_dashboard(request):
    if not (request.user.role == 2 or request.user.role == 3):
        messages.error(request, "กรุณาล็อกอินก่อนเข้าหน้านี้")
        return redirect('login')

    # ดึงข้อมูลอาจารย์
    teacher = request.user.teacher
    
    # ดึงการนัดหมายที่เกี่ยวข้องกับอาจารย์
    appointments = Appointment.objects.filter(
        teachers=teacher
    ).select_related('project', 'project__advisor').prefetch_related(
        'project__committee', 'project__students', 'students'
    )
    
    # แยกการนัดหมายตามสถานะ
    pending_appointments = appointments.filter(status='pending')
    confirmed_appointments = appointments.filter(status='accepted')
    
    return render(request, 'teacher/dashboard.html', {
        'appointments': appointments,
        'pending_appointments': pending_appointments,
        'confirmed_appointments': confirmed_appointments
    })



@login_required
def manager_dashboard(request):
    if not request.user.is_manager():
        return redirect('login')
    
    # Count users
    total_users = Member.objects.count()
    total_students = Member.objects.filter(role=1).count()
    total_teachers = Member.objects.filter(role=2).count()
    
    # Appointment calculations
    appointments = Appointment.objects.all()
    
    total_appointments = appointments.count()
    
    # Flexible status counting
    status_counts = {
        'confirmed': appointments.filter(Q(status='accepted') | Q(status='confirmed')).count(),
        'pending': appointments.filter(status='pending').count(),
        'cancelled': appointments.filter(Q(status='cancelled') | Q(status='rejected')).count()
    }
    
    # Fetch only accepted appointments for calendar
    calendar_appointments = appointments.filter(status='accepted').select_related(
        'project', 
        'project__advisor'
    ).prefetch_related(
        'project__students'
    )
    
    return render(request, 'manager/dashboard.html', {
        'total_users': total_users,
        'total_students': total_students,
        'total_teachers': total_teachers,
        'total_appointments': total_appointments,
        'confirmed_appointments': status_counts['confirmed'],
        'pending_appointments': status_counts['pending'],
        'cancelled_appointments': status_counts['cancelled'],
        'appointments': calendar_appointments,
    })

def teacher_appointments(request):
    if not request.user.is_teacher():
        return redirect('login')
    
    teacher = request.user.teacher
    appointments = Appointment.objects.filter(project__advisor=teacher) | Appointment.objects.filter(project__committee=teacher)
    
    pending_appointments = appointments.filter(status='pending')
    confirmed_appointments = appointments.exclude(status='pending')
    
    for appointment in pending_appointments:
        if timezone.now() > appointment.created_at + timezone.timedelta(minutes=1):
            appointment.status = 'accepted'
            appointment.save()
    
    return render(request, 'teacher/appointments.html', {
        'pending_appointments': pending_appointments,
        'confirmed_appointments': confirmed_appointments,
    })
logger = logging.getLogger(__name__)
@login_required
def upload_project(request):
    if not request.user.is_student():
        messages.error(request, "คุณไม่มีสิทธิ์อัปโหลดโปรเจค")
        return redirect('login')
    
    try:
        if request.method == 'POST':
            project_form = ProjectForm(request.POST)
            file_form = FileForm(request.POST, request.FILES)

            if project_form.is_valid() and file_form.is_valid():
                with transaction.atomic():
                    project = project_form.save(commit=False)
                    project.save()  # บันทึกโครงงานก่อน
                    
                    # เพิ่มผู้ใช้ปัจจุบัน
                    current_user = request.user.student
                    project.students.add(current_user)

                    # เพิ่มนักศึกษาที่เลือก
                    selected_students = project_form.cleaned_data.get('students', [])
                    for student in selected_students:
                        if student != current_user:
                            project.students.add(student)

                    # บันทึกไฟล์
                    if file_form.cleaned_data['file'] or file_form.cleaned_data['url']:
                        file = file_form.save(commit=False)
                        file.project = project
                        file.save()
                
                total_students = project.students.count()
                messages.success(request, f"อัปโหลดโครงงานสำเร็จ มีนักศึกษา {total_students} คน")
                return redirect('student_dashboard')
            
            else:
                # จัดการข้อผิดพลาดแบบละเอียด
                for field, errors in project_form.errors.items():
                    for error in errors:
                        messages.error(request, f"ข้อผิดพลาดใน {field}: {error}")
        
        else:
            # กรณี GET request
            initial_data = {}
            project_form = ProjectForm(initial=initial_data)
            file_form = FileForm()

    except Exception as e:
        logger.error(f"เกิดข้อผิดพลาดในการอัปโหลดโปรเจค: {e}")
        messages.error(request, f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {str(e)}")
        return redirect('student_dashboard')

    return render(request, 'student/upload_project.html', {
        'project_form': project_form,
        'file_form': file_form,
    })
# API สำหรับค้นหานักศึกษา
def search_students(request):
    search_term = request.GET.get('term', '')
    
    if not search_term:
        return JsonResponse([], safe=False)
    
    # ค้นหานักศึกษาจากรหัสนักศึกษาหรือชื่อ-นามสกุล
    students = Student.objects.filter(
        Q(student_id__icontains=search_term) | 
        Q(first_name__icontains=search_term) | 
        Q(last_name__icontains=search_term)
    ).exclude(id=request.user.student.id)[:10]  # ไม่แสดงตัวเอง และจำกัดผลลัพธ์ไม่เกิน 10 คน
    
    # สร้างรายการนักศึกษาในรูปแบบ JSON
    results = []
    for student in students:
        if student.student_id:  # แสดงเฉพาะนักศึกษาที่มีรหัสนักศึกษา
            results.append({
                'id': student.id,
                'student_id': student.student_id,
                'first_name': student.first_name or '',
                'last_name': student.last_name or ''
            })
    
    return JsonResponse(results, safe=False)

@login_required
def my_projects(request):
    try:
        # ดึงเฉพาะโครงงานที่มีผู้ใช้ปัจจุบันเป็นนักศึกษาในโครงงาน
        projects = Project.objects.filter(students=request.user.student).prefetch_related(
            'students', 'committee', 'files'
        ).select_related('advisor').distinct()

        # พิมพ์ข้อมูลโครงงาน
        for project in projects:
            print(f"Project ID: {project.id}")
            print(f"Project Topic: {project.topic}")
            print(f"Students: {list(project.students.values_list('id', 'first_name', 'last_name'))}")

        # สร้างข้อมูลเพิ่มเติมสำหรับแต่ละโครงงาน
        for project in projects:
            project.other_students = project.students.exclude(id=request.user.student.id)
            project.has_other_students = project.other_students.exists()

        return render(request, 'student/my_projects.html', {
            'projects': projects
        })
    except Exception as e:
        messages.error(request, f"เกิดข้อผิดพลาดในการแสดงโครงงาน: {str(e)}")
        return redirect('student_dashboard')
    
@login_required
def delete_project(request, project_id):
    # ดึงโครงงานที่ต้องการลบ
    project = get_object_or_404(Project, id=project_id)
    
    # ลบโครงงานโดยไม่ตรวจสอบสิทธิ์
    project.delete()
    
    # แสดงข้อความสำเร็จ
    messages.success(request, 'ลบโครงงานเรียบร้อยแล้ว')
    
    # Redirect กลับไปที่หน้า my_projects
    return redirect('my_projects')



logger = logging.getLogger(__name__)

@login_required
def edit_project(request, project_id):
    try:
        student = request.user.student
        
        # ดึงโปรเจคพร้อมข้อมูลที่เกี่ยวข้อง
        project = get_object_or_404(
            Project.objects.filter(students=student)
            .select_related('advisor')
            .prefetch_related('students', 'committee', 'files'), 
            id=project_id
        )

        if request.method == 'POST':
            project_form = ProjectForm(request.POST, instance=project)
            file_form = FileForm(request.POST, request.FILES)

            if project_form.is_valid() and file_form.is_valid():
                try:
                    # บันทึกโครงงาน
                    updated_project = project_form.save()
                    
                    # ตรวจสอบและเพิ่มนักศึกษา
                    if not updated_project.students.filter(id=student.id).exists():
                        updated_project.students.add(student)
                    
                    # บันทึกไฟล์
                    if file_form.cleaned_data.get('file') or file_form.cleaned_data.get('url'):
                        file = file_form.save(commit=False)
                        file.project = updated_project
                        file.save()

                    messages.success(request, "แก้ไขโปรเจคเรียบร้อยแล้ว")
                    return redirect('my_projects')

                except Exception as e:
                    messages.error(request, f"เกิดข้อผิดพลาดในการบันทึก: {str(e)}")
            else:
                for field, errors in list(project_form.errors.items()) + list(file_form.errors.items()):
                    for error in errors:
                        messages.error(request, f"{field}: {error}")

        else:
            project_form = ProjectForm(instance=project)
            file_form = FileForm()

        # เตรียมข้อมูลเพิ่มเติมสำหรับ template
        context = {
            'project_form': project_form,
            'file_form': file_form,
            'project': project,
            'advisor': project.advisor,  # ส่งข้อมูลอาจารย์ที่ปรึกษา
            'committee_members': project.committee.all(),  # ส่งข้อมูลคณะกรรมการ
            'project_files': project.files.all(),  # ส่งข้อมูลไฟล์
            'other_students': project.students.exclude(id=student.id),
            'has_other_students': project.students.exclude(id=student.id).exists()
        }

        return render(request, 'student/edit_project.html', context)

    except Student.DoesNotExist:
        messages.error(request, "ไม่พบข้อมูลนักศึกษาสำหรับบัญชีนี้")
        return redirect('my_projects')
    except Exception as e:
        messages.error(request, f"เกิดข้อผิดพลาด: {str(e)}")
        return redirect('my_projects')
    
@login_required
def add_project_member(request, project_id):
    if not request.user.is_student():
        return redirect('login')
    
    project = get_object_or_404(Project, id=project_id, students=request.user.student)
    
    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        try:
            student = Student.objects.get(id=student_id)
            project.students.add(student)
            messages.success(request, 'เพิ่มสมาชิกเรียบร้อยแล้ว')
        except Student.DoesNotExist:
            messages.error(request, 'ไม่พบนักศึกษาที่ระบุ')
    
    return redirect('edit_project', project_id=project_id)    

@login_required
def check_time(request):
    if request.user.is_student():
        template = 'student/check_available.html'
    elif request.user.is_teacher():
        template = 'teacher/check_available.html'
    elif request.user.is_manager():
        template = 'manager/check_available.html'
    else:
        return redirect('login')

    teachers = Teacher.objects.all()
    selected_teachers = request.GET.getlist('teacher')  

    date_str = request.GET.get('date', '')
    date = parse_date(date_str) if date_str else None

    available_times = AvailableTime.objects.none()
    common_times = []
    booked_times = []


    if selected_teachers and date is not None:
    
        available_times = AvailableTime.objects.filter(teacher__id__in=selected_teachers, date=date)

        booked_appointments = Appointment.objects.filter(
            date=date, 
            status__in=['pending', 'accepted'],  
            project__advisor__id__in=selected_teachers
        )

        booked_times = [(appt.time_start, appt.time_finish) for appt in booked_appointments if appt.status == "accepted"]
        pending_times = [(appt.time_start, appt.time_finish) for appt in booked_appointments if appt.status == "pending"]

        time_slots = defaultdict(list)
        for time in available_times:
            key = (time.start_time, time.end_time)
            time_slots[key].append(time.teacher)

        common_times = []
        for slot, teachers_in_slot in time_slots.items():
            if set(teachers_in_slot) == set(Teacher.objects.filter(id__in=selected_teachers)):  
                is_booked = slot in booked_times  
                is_pending = slot in pending_times  

                common_times.append({
                    'start_time': slot[0],
                    'end_time': slot[1],
                    'teachers': teachers_in_slot,
                    'is_booked': is_booked,
                    'is_pending': is_pending
                })

    no_teachers_available = not common_times  

    if request.user.is_student():
        student_projects = Project.objects.filter(students=request.user)
    else:
        student_projects = None

    return render(request, template, {
        'teachers': teachers,
        'available_times': common_times,
        'no_teachers_available': no_teachers_available,
        'hours': range(8, 18),
        'selected_teachers': selected_teachers,
        'date': date.strftime('%Y-%m-%d') if date else '',  
        'student_projects': student_projects,  
    })


@login_required
def my_point(request):
    if not request.user.is_student():
        return redirect('login')
    
  
    projects = Project.objects.filter(students=request.user)
 
    scores = Score.objects.filter(project__in=projects)
    
    return render(request, 'student/my_point.html', {
        'projects': projects,
        'scores': scores,
    })


@login_required
def my_point(request):
    if not request.user.is_student():
        return redirect('login')
    
    projects = Project.objects.filter(students=request.user)
    project_scores = []
    
    for project in projects:
 
        scores = Score.objects.filter(project=project)
        
        if scores.exists():
   
            average_score = scores.aggregate(Avg('score'))['score__avg']
            teachers = ", ".join([score.teacher.get_full_name() for score in scores])
            

            project_scores.append({
                'project': project,
                'average_score': round(average_score, 2),  
                'teachers': teachers,
                'comments': ", ".join([score.comment for score in scores if score.comment]),  
            })
    
    return render(request, 'student/my_point.html', {
        'project_scores': project_scores,
    })


@login_required
def edit_profile(request):
    if not request.user.is_student():
        messages.error(request, "คุณไม่มีสิทธิ์เข้าถึงหน้านี้")
        return redirect('login')  

    try:
        # หา Student ที่เชื่อมกับ User ปัจจุบัน
        student = Student.objects.get(member_ptr_id=request.user.id)
    except Student.DoesNotExist:
        # สร้าง Student ใหม่ด้วยข้อมูลจาก User ปัจจุบัน
        Student.objects.create(
            member_ptr_id=request.user.id,
            student_id=None,
            role=1
        )
        # ดึงข้อมูล student อีกครั้งหลังจากสร้าง
        student = Student.objects.get(member_ptr_id=request.user.id)

    # แสดงฟอร์มหรือประมวลผลการส่งข้อมูลฟอร์ม
    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        if student_id:
            # อัปเดตเฉพาะ student_id โดยใช้ raw SQL หรือ update
            Student.objects.filter(member_ptr_id=request.user.id).update(student_id=student_id)
            messages.success(request, 'แก้ไขโปรไฟล์เรียบร้อยแล้ว!')
            return redirect('student_dashboard')
        else:
            messages.error(request, "กรุณากรอกรหัสนักศึกษา")
    
    # ถ้าเป็น GET หรือการ POST ไม่สำเร็จ แสดงฟอร์ม
    context = {
        'student': student,
        'form': EditProfileForm(instance=student)
    }
    return render(request, 'student/edit_profile.html', context)

@login_required
def my_appointments(request):
    print(f"User: {request.user.id} - {request.user.email}")
    
    # จัดการคำขอ POST สำหรับบันทึกลิงก์ประชุมและสถานที่
    if request.method == "POST":
        print("POST data received:", request.POST)
        appointment_id = request.POST.get("appointment_id")
        
        if appointment_id:
            try:
                appointment = Appointment.objects.get(id=appointment_id, students=request.user)
                
                # บันทึกลิงก์ประชุมและสถานที่
                meeting_link = request.POST.get("meeting_link")
                location = request.POST.get("location")
                
                if meeting_link:
                    appointment.meeting_link = meeting_link
                
                if location:
                    appointment.location = location
                
                appointment.save()
                print(f"Updated appointment {appointment_id}: meeting_link={meeting_link}, location={location}")
                messages.success(request, "บันทึกข้อมูลการประชุมเรียบร้อยแล้ว")
                
            except Appointment.DoesNotExist:
                print(f"Appointment {appointment_id} not found or user not allowed")
                messages.error(request, "ไม่พบการนัดหมาย")
            except Exception as e:
                print(f"Error updating appointment: {str(e)}")
                messages.error(request, f"เกิดข้อผิดพลาด: {str(e)}")
    
    # ดึงการนัดหมายทั้งหมดที่ผู้ใช้ปัจจุบันเกี่ยวข้อง
    appointments = Appointment.objects.filter(
        students=request.user
    ).select_related('project').prefetch_related('project__students')
    
    print(f"Found {appointments.count()} appointments for this user")
    
    for app in appointments:
        print(f"Appointment ID: {app.id}, Project: {app.project.topic}")
        print(f"Students: {list(app.students.all().values_list('email', flat=True))}")
    
    # แยกตามสถานะ
    pending_appointments = appointments.filter(status="pending")
    accepted_appointments = appointments.filter(status="accepted")
    rejected_appointments = appointments.filter(status="rejected")

    context = {
        "pending_appointments": pending_appointments,
        "accepted_appointments": accepted_appointments,
        "rejected_appointments": rejected_appointments,
    }
    return render(request, "student/my_appointments.html", context)

@login_required
def connect_google_calendar(request):
    """
    เริ่มต้นกระบวนการเชื่อมต่อกับ Google Calendar
    """
    if not request.user.is_teacher():
        messages.error(request, "คุณไม่มีสิทธิ์เข้าถึงหน้านี้")
        return redirect('login')
    
    # สำหรับการพัฒนาเท่านั้น - อนุญาตให้ใช้ HTTP แทน HTTPS
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    try:
        # ใช้ URL ที่ตรงกับที่ลงทะเบียนไว้ใน Google Cloud Console
        callback_url = request.build_absolute_uri(reverse('google_calendar_callback'))
        
        # สร้าง OAuth flow จากไฟล์ credentials พร้อมกำหนด scopes ให้ครบ
        flow = InstalledAppFlow.from_client_secrets_file(
            'credentials.json',
            scopes=['https://www.googleapis.com/auth/calendar',
                   'https://www.googleapis.com/auth/userinfo.profile',
                   'https://www.googleapis.com/auth/userinfo.email',
                   'openid'],
            redirect_uri=callback_url
        )
        
        # สร้าง URL สำหรับการขอสิทธิ์
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        # เก็บ state ไว้ใน session เพื่อตรวจสอบ CSRF
        request.session['google_auth_state'] = state
        
        # Log สำหรับการตรวจสอบ
        logger.info(f"Starting Google Calendar authorization for {request.user.email}")
        logger.info(f"Redirect URI: {callback_url}")
        
        # ส่งผู้ใช้ไปยังหน้าจอยินยอมของ Google
        return redirect(authorization_url)
    
    except Exception as e:
        logger.error(f"เกิดข้อผิดพลาดในการเริ่มต้นการเชื่อมต่อ Google Calendar: {str(e)}")
        messages.error(request, f"เกิดข้อผิดพลาด: {str(e)}")
        return redirect('teacher_dashboard')
    
def google_calendar_callback(request):
    """
    รับและประมวลผลการตอบกลับจาก Google OAuth
    """
    if not request.user.is_teacher():
        messages.error(request, "คุณไม่มีสิทธิ์เข้าถึงหน้านี้")
        return redirect('login')
    
    # สำหรับการพัฒนาเท่านั้น - อนุญาตให้ใช้ HTTP แทน HTTPS
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    try:
        # บันทึกข้อมูลสำหรับการตรวจสอบ
        logger.info(f"Received callback for {request.user.email}")
        logger.info(f"Full URL: {request.build_absolute_uri()}")
        
        # ดึง state จาก session เพื่อป้องกัน CSRF
        state = request.session.pop('google_auth_state', None)
        if not state:
            raise ValueError("ไม่พบ state ใน session")
        
        # ใช้ URL callback ที่ตรงกัน
        callback_url = request.build_absolute_uri(reverse('google_calendar_callback'))
        
        # สร้าง flow เช่นเดียวกับในฟังก์ชัน connect_google_calendar ด้วย scopes เดียวกัน
        flow = InstalledAppFlow.from_client_secrets_file(
            'credentials.json',
            scopes=['https://www.googleapis.com/auth/calendar',
                   'https://www.googleapis.com/auth/userinfo.profile',
                   'https://www.googleapis.com/auth/userinfo.email',
                   'openid'],
            redirect_uri=callback_url
        )
        
        # กำหนด state ที่ได้จาก session
        flow.state = state
        
        # แลกเปลี่ยนโค้ดเพื่อรับ token
        flow.fetch_token(authorization_response=request.build_absolute_uri())
        
        # รับ credentials จาก flow
        creds = flow.credentials
        
        # บันทึก credentials ลงไฟล์ โดยใช้ hash ของอีเมลเป็นชื่อไฟล์
        token_path = f'token_{hashlib.md5(request.user.email.encode()).hexdigest()}.pickle'
        with open(token_path, 'wb') as token_file:
            pickle.dump(creds, token_file)
        
        logger.info(f"Token saved successfully for {request.user.email}")
        messages.success(request, "เชื่อมต่อกับ Google Calendar สำเร็จแล้ว")
        
        return redirect('teacher_dashboard')
    
    except Exception as e:
        # บันทึกข้อผิดพลาดในรายละเอียด
        logger.error(f"เกิดข้อผิดพลาดในการรับ token: {str(e)}")
        messages.error(request, f"เกิดข้อผิดพลาด: {str(e)}")
        return redirect('teacher_dashboard')
    
@login_required
def book_appointment(request):
    if request.method == "POST":
        try:
            # รับข้อมูลจาก form (ส่วนที่มีอยู่แล้ว)
            teacher_ids_str = request.POST.get("teacher_ids", "")
            project_id = request.POST.get("project_id")
            date_str = request.POST.get("date")
            start_time = request.POST.get("start_time")
            end_time = request.POST.get("end_time")
            
            # แปลง teacher_ids เป็น list ของ int และตรวจสอบความถูกต้อง (ส่วนที่มีอยู่แล้ว)
            teacher_ids = []
            if teacher_ids_str:
                teacher_ids = [int(id) for id in teacher_ids_str.split(",") if id]
            
            if not teacher_ids:
                messages.error(request, "กรุณาเลือกอาจารย์อย่างน้อย 1 คน")
                return redirect("student_check_time")
                
            if not project_id:
                messages.error(request, "กรุณาเลือกโครงงาน")
                return redirect("student_check_time")
                
            # ดึงข้อมูลโครงงานและอาจารย์ที่เกี่ยวข้อง (ส่วนที่มีอยู่แล้ว)
            project = get_object_or_404(Project, id=project_id)
            
            # ตรวจสอบว่าผู้ใช้เป็นส่วนหนึ่งของโครงงาน (ส่วนที่มีอยู่แล้ว)
            if not project.students.filter(member_ptr=request.user).exists():
                messages.error(request, "คุณไม่ได้เป็นส่วนหนึ่งของโครงงานนี้")
                return redirect("student_check_time")
            
            # สร้างการนัดหมาย (ส่วนที่มีอยู่แล้ว)
            appointment = Appointment.objects.create(
                date=date_str,
                time_start=start_time,
                time_finish=end_time,
                project=project,
                status="pending",
            )
            
            # เพิ่มนักศึกษาทั้งหมด (ส่วนที่มีอยู่แล้ว)
            for student in project.students.all():
                appointment.students.add(student)
                print(f"Added student {student.member_ptr.email} to appointment")
            
            # เพิ่มอาจารย์และส่งอีเมลแจ้งเตือน
            teacher_emails = []
            for teacher_id in teacher_ids:
                try:
                    teacher = Teacher.objects.get(id=teacher_id)
                    appointment.teachers.add(teacher)
                    teacher_emails.append(teacher.email)
                    print(f"Added teacher {teacher.get_full_name()} to appointment")
                    
                    # สร้างกิจกรรมใน Google Calendar (ถ้าอาจารย์ได้เชื่อมต่อแล้ว)
                    try:
                        create_google_calendar_event(appointment, teacher.email)
                    except Exception as e:
                        print(f"ไม่สามารถสร้างกิจกรรมใน Google Calendar: {str(e)}")
                        
                except Teacher.DoesNotExist:
                    print(f"Teacher with ID {teacher_id} not found")
            
            # ส่งอีเมลแจ้งเตือนอาจารย์
            if teacher_emails:
                try:
                    formatted_date = appointment.date.strftime('%d/%m/%Y') if appointment.date else 'ไม่ระบุ'
                    formatted_time_start = appointment.time_start.strftime('%H:%M') if hasattr(appointment.time_start, 'strftime') else str(appointment.time_start) if appointment.time_start else 'ไม่ระบุ'
                    formatted_time_finish = appointment.time_finish.strftime('%H:%M') if hasattr(appointment.time_finish, 'strftime') else str(appointment.time_finish) if appointment.time_finish else 'ไม่ระบุ'
                except AttributeError as e:
                    logger.error(f"Error formatting date/time: {str(e)}")
                    formatted_date = str(appointment.date) if appointment.date else 'ไม่ระบุ'
                    formatted_time_start = str(appointment.time_start) if appointment.time_start else 'ไม่ระบุ'
                    formatted_time_finish = str(appointment.time_finish) if appointment.time_finish else 'ไม่ระบุ'
                    subject = f"แจ้งเตือนการนัดหมายโครงงาน: {project.topic}"
                    html_message = render_to_string('email/appointment_notification.html', {
                        'appointment': appointment,
                        'project': project,
                        'students': project.students.all(),
                        'formatted_date': formatted_date,
                        'formatted_time_start': formatted_time_start,
                        'formatted_time_finish': formatted_time_finish,
                    })
                    plain_message = strip_tags(html_message)
                    
                    send_mail(
                        subject=subject,
                        message=plain_message,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=teacher_emails,
                        html_message=html_message,
                        fail_silently=False,
                    )
                except Exception as e:
                    print(f"เกิดข้อผิดพลาดในการส่งอีเมล: {str(e)}")

            # บันทึกการนัดหมาย
            appointment.save()
            
            messages.success(request, "สร้างการนัดหมายเรียบร้อย รอการอนุมัติจากอาจารย์")
            return redirect("my_appointments")
            
        except Exception as e:
            logger.error(f"Error creating appointment: {str(e)}")
            messages.error(request, f"เกิดข้อผิดพลาดในการสร้างการนัดหมาย: {str(e)}")
            return redirect("student_check_time")
    
    return redirect("student_check_time")

@login_required
def teacher_appointments(request):
    if not request.user.is_teacher():
        return redirect('login')

    teacher = request.user.teacher
    
    # ดึงการนัดหมายทั้งหมดที่อาจารย์เกี่ยวข้อง
    appointments = Appointment.objects.filter(
        teachers=teacher
    ).distinct().select_related(
        'project',
        'project__advisor'
    ).prefetch_related(
        'project__committee',
        'teachers',
        Prefetch('students', queryset=Student.objects.select_related('member_ptr'))
    ).order_by('date', 'time_start')
    
    # กรองการนัดหมายที่ไม่ใช่สถานะ 'rejected'
    pending_appointments = appointments.filter(status='pending')
    
    # ดึงการนัดหมายที่อนุมัติแล้ว
    confirmed_appointments = appointments.filter(status='accepted')
    
    # ดึงการนัดหมายที่ถูกปฏิเสธ
    rejected_appointments = appointments.filter(status='rejected')

    
    return render(request, 'teacher/appointments.html', {
        'pending_appointments': pending_appointments,
        'confirmed_appointments': confirmed_appointments,
        'rejected_appointments': rejected_appointments,
    })

@login_required
def accept_appointment(request, appointment_id):
    try:
        appointment = get_object_or_404(Appointment, id=appointment_id)
        teacher = request.user.teacher
        
        # ตรวจสอบว่าอาจารย์มีสิทธิ์อนุมัติการนัดหมายหรือไม่
        if teacher not in appointment.teachers.all():
            messages.error(request, "คุณไม่มีสิทธิ์อนุมัติการนัดหมายนี้")
            return redirect('teacher_appointments')
        
        # อัปเดตรายชื่ออาจารย์ที่ยอมรับการนัดหมาย
        accepted_teachers = json.loads(appointment.accepted_teachers) if appointment.accepted_teachers else []
        teacher_id_str = str(teacher.id)
        
        if teacher_id_str in accepted_teachers:
            messages.info(request, "คุณได้อนุมัติการนัดหมายนี้แล้ว")
            return redirect('teacher_appointments')
        
        # เพิ่มอาจารย์ปัจจุบันเข้าไปในรายชื่อผู้อนุมัติ
        accepted_teachers.append(teacher_id_str)
        appointment.accepted_teachers = json.dumps(accepted_teachers)
        
        # ตรวจสอบว่าอาจารย์ทุกคนได้อนุมัติหรือยัง
        all_teacher_ids = [str(t.id) for t in appointment.teachers.all()]
        
        if set(accepted_teachers) == set(all_teacher_ids):
            # อาจารย์ทุกคนได้อนุมัติแล้ว
            appointment.status = "accepted"
            
            # ลองสร้างกิจกรรมใน Google Calendar สำหรับอาจารย์ทุกคน
            calendar_events = []
            
            for teacher_id in all_teacher_ids:
                try:
                    teacher_obj = Teacher.objects.get(id=int(teacher_id))
                    
                    # ตรวจสอบว่ามีไฟล์ token สำหรับอาจารย์คนนี้หรือไม่
                    token_path = f'token_{hashlib.md5(teacher_obj.email.encode()).hexdigest()}.pickle'
                    
                    if os.path.exists(token_path):
                        # สร้างกิจกรรมใน Google Calendar
                        event_id = create_google_calendar_event(appointment, teacher_obj.email)
                        
                        if event_id:
                            # เก็บข้อมูลกิจกรรมที่สร้างสำเร็จ
                            calendar_events.append({
                                'teacher_id': teacher_id,
                                'teacher_name': teacher_obj.get_full_name(),
                                'event_id': event_id
                            })
                            logger.info(f"สร้างกิจกรรม Calendar สำหรับ {teacher_obj.email} สำเร็จ")
                        else:
                            logger.warning(f"ไม่สามารถสร้างกิจกรรม Calendar สำหรับ {teacher_obj.email}")
                    else:
                        logger.info(f"ไม่พบไฟล์ token สำหรับ {teacher_obj.email}")
                
                except Exception as e:
                    logger.error(f"เกิดข้อผิดพลาดกับอาจารย์ {teacher_id}: {str(e)}")
            
            # บันทึกข้อมูลกิจกรรม Calendar ลงในการนัดหมาย
            if calendar_events:
                appointment.calendar_events = json.dumps(calendar_events)
            
            # ส่งอีเมลยืนยันการนัดหมายให้นักศึกษา
            student_emails = [student.email for student in appointment.students.all() if student.email]
            
            if student_emails:
                try:
                    # จัดรูปแบบวันที่และเวลา
                    formatted_date = appointment.date.strftime('%d/%m/%Y') if appointment.date else 'ไม่ระบุ'
                    formatted_time_start = appointment.time_start.strftime('%H:%M') if hasattr(appointment.time_start, 'strftime') else str(appointment.time_start)
                    formatted_time_finish = appointment.time_finish.strftime('%H:%M') if hasattr(appointment.time_finish, 'strftime') else str(appointment.time_finish)
                    
                    # สร้างและส่งอีเมล
                    subject = f"การนัดหมายโครงงานได้รับการอนุมัติแล้ว: {appointment.project.topic}"
                    html_message = render_to_string('email/appointment_confirmed.html', {
                        'appointment': appointment,
                        'project': appointment.project,
                        'formatted_date': formatted_date,
                        'formatted_time_start': formatted_time_start,
                        'formatted_time_finish': formatted_time_finish,
                        'calendar_events': bool(calendar_events)
                    })
                    plain_message = strip_tags(html_message)
                    
                    send_mail(
                        subject=subject,
                        message=plain_message,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=student_emails,
                        html_message=html_message,
                        fail_silently=False,
                    )
                    
                    logger.info(f"ส่งอีเมลยืนยันการนัดหมายให้นักศึกษาสำเร็จ")
                except Exception as e:
                    logger.error(f"เกิดข้อผิดพลาดในการส่งอีเมล: {str(e)}")
            
            messages.success(request, "✅ การนัดหมายได้รับการอนุมัติจากอาจารย์ทุกท่านแล้ว")
        else:
            remaining = len(set(all_teacher_ids)) - len(set(accepted_teachers))
            messages.success(request, f"✅ คุณได้อนุมัติการนัดหมายแล้ว (รออีก {remaining} ท่าน)")
        
        # บันทึกการเปลี่ยนแปลง
        appointment.save()
        return redirect('teacher_appointments')

    except Exception as e:
        logger.error(f"เกิดข้อผิดพลาดในการอนุมัติการนัดหมาย: {str(e)}")
        messages.error(request, f"เกิดข้อผิดพลาด: {str(e)}")
        return redirect('teacher_appointments')
    
@login_required
def reject_appointment(request, appointment_id):
    try:
        appointment = get_object_or_404(Appointment, id=appointment_id)
        teacher = request.user.teacher
        
        # ตรวจสอบว่าอาจารย์มีสิทธิ์ปฏิเสธการนัดหมายหรือไม่
        if teacher not in appointment.teachers.all():
            messages.error(request, "คุณไม่มีสิทธิ์ปฏิเสธการนัดหมายนี้")
            return redirect('teacher_appointments')
        
        if request.method == 'POST':
            form = RejectAppointmentForm(request.POST)
            if form.is_valid():
                # บันทึกเหตุผลการปฏิเสธ
                appointment.rejection_reason = form.cleaned_data['rejection_reason']
                appointment.status = 'rejected'
                
                # บันทึกว่าใครเป็นผู้ปฏิเสธ
                rejected_by = {
                    'teacher_id': teacher.id,
                    'teacher_name': teacher.get_full_name()
                }
                appointment.rejected_by = json.dumps(rejected_by)
                
                # บันทึกการเปลี่ยนแปลง
                appointment.save()
                
                print(f"ปฏิเสธการนัดหมาย ID: {appointment.id} สถานะใหม่: {appointment.status}")
                
                messages.success(request, "คุณได้ปฏิเสธการนัดหมายเรียบร้อยแล้ว")
                return redirect('teacher_appointments')
        else:
            form = RejectAppointmentForm()
            return render(request, 'teacher/reject_appointment.html', {
                'form': form,
                'appointment': appointment
            })
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการปฏิเสธการนัดหมาย: {e}")
        messages.error(request, f"เกิดข้อผิดพลาด: {str(e)}")
        return redirect('teacher_appointments')
@login_required
def available_time(request):
    if not request.user.is_teacher():
        return redirect('login')
  
    try:
        teacher = request.user.teacher
    except Teacher.DoesNotExist:
        teacher = Teacher.objects.create(member_ptr=request.user)
        teacher.save()
    
    # ลบเวลาว่างที่ผ่านมาแล้ว
    current_datetime = timezone.now()
    
    # ลบเวลาที่เป็นวันก่อนหน้า
    AvailableTime.objects.filter(
        teacher=teacher,
        date__lt=current_datetime.date()
    ).delete()
    
    # ลบเวลาที่เป็นวันนี้แต่เวลาสิ้นสุดผ่านไปแล้ว
    today_times = AvailableTime.objects.filter(
        teacher=teacher,
        date=current_datetime.date()
    )
    
    for time in today_times:
        try:
            # สร้าง datetime object จากวันที่และเวลาสิ้นสุด
            end_datetime = timezone.make_aware(
                datetime.combine(time.date, time.end_time)
            )
            if end_datetime < current_datetime:
                time.delete()
        except Exception as e:
            print(f"Error checking expired time: {e}")
    
    # ดึงเวลาว่างที่เหลือ
    available_times = AvailableTime.objects.filter(teacher=teacher)
    
    # ตรวจสอบสถานะการแก้ไขได้
    for time in available_times:
        if timezone.now() > time.created_at + timedelta(minutes=1):
            time.can_edit = False
        else:
            time.can_edit = True
    
    hours = range(8, 18)
    return render(request, 'teacher/available_time.html', {
        'available_times': available_times,
        'hours': hours
    })

@csrf_exempt
def delete_available_time(request):
    if request.method == 'POST':
    
        if not request.user.is_authenticated or not request.user.is_teacher():
            return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)

        try:
            data = json.loads(request.body)
            time_id = data.get('id')

            available_time = AvailableTime.objects.get(id=time_id)
            available_time.delete()

            return JsonResponse({'success': True, 'message': 'ลบเวลาสำเร็จ'})
        except AvailableTime.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'ไม่พบเวลาที่ต้องการลบ'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
    
    return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)


@csrf_exempt
def save_available_time(request):
    if request.method == 'POST':
     
        if not request.user.is_authenticated or not request.user.is_teacher():
            return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)

        # รับข้อมูลจากฟอร์ม
        date = request.POST.get('date')
        start_time = request.POST.get('start_time')
        end_time = request.POST.get('end_time')
        time_id = request.POST.get('id')  

        try:
            date_obj = datetime.strptime(date, '%Y-%m-%d').date()
            start_time_obj = datetime.strptime(start_time, '%H:%M').time()
            end_time_obj = datetime.strptime(end_time, '%H:%M').time()

            if time_id:  
                available_time = AvailableTime.objects.get(id=time_id)
                available_time.date = date_obj
                available_time.start_time = start_time_obj
                available_time.end_time = end_time_obj
                available_time.save()
            else:
             
                available_time = AvailableTime.objects.create(
                    teacher=request.user.teacher,
                    date=date_obj,
                    start_time=start_time_obj,
                    end_time=end_time_obj
                )
                available_time.save()

            return JsonResponse({'success': True, 'message': 'บันทึกเวลาสำเร็จ'})

        except ValueError:
            return JsonResponse({'success': False, 'message': 'ข้อมูลไม่ถูกต้อง'}, status=400)
    
    return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)


@login_required
def add_news(request):
    if request.user.is_teacher():
        template = 'teacher/teacher_news.html'
        redirect_url = 'teacher_news'
    elif request.user.is_manager():
        template = 'manager/manager_news.html'
        redirect_url = 'manager_dashboard'
    else:
        messages.error(request, "คุณไม่มีสิทธิ์เข้าถึงหน้านี้")
        return redirect('login')
    
    if request.method == 'POST':
        form = NewsForm(request.POST)
        
        if form.is_valid():
            news = form.save(commit=False)
            
            if request.user.is_teacher():
                try:
                    teacher = request.user.teacher
                    news.teacher = teacher
                except Teacher.DoesNotExist:
                    messages.error(request, "ไม่พบข้อมูลอาจารย์สำหรับผู้ใช้นี้")
                    return redirect('teacher_dashboard')
            elif request.user.is_manager():
                try:
                    teacher = Teacher.objects.first()
                    if not teacher:
                        messages.error(request, "ไม่พบข้อมูลอาจารย์ในระบบ")
                        return redirect('manager_dashboard')
                    news.teacher = teacher
                except Exception as e:
                    messages.error(request, f"เกิดข้อผิดพลาด: {str(e)}")
                    return redirect('manager_dashboard')
            
            news.save()
            messages.success(request, 'เพิ่มข่าวสารเรียบร้อยแล้ว!')
            
            send_news_notification(news)
            
            return redirect(redirect_url)
        else:
            messages.error(request, f'ข้อผิดพลาด: {form.errors}')
    else:
        form = NewsForm()
  
    context = {
        'form': form,
        'is_add_mode': True
    }
    
    return render(request, template, context)

def send_news_notification(news):
    # ดึงเฉพาะเมมเบอร์ที่เป็นนักศึกษา
    student_members = Member.objects.filter(role=1)  # role == 1 หมายถึงนักศึกษา
    recipient_list = [member.email for member in student_members if member.email]

    if recipient_list:
        subject = f"แจ้งเตือนข่าวสารใหม่: {news.topic}"
        html_message = render_to_string('email/news_notification.html', {'news': news})
        plain_message = strip_tags(html_message) 

        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            html_message=html_message,
            fail_silently=False,
        )

    
    current_date = timezone.now()
    two_days_ago = current_date - timedelta(days=2)
    News.objects.filter(created_at__lt=two_days_ago).delete()


@login_required
def assign_score(request):
    if not request.user.is_teacher():
        return redirect('login')
    
    try:
        teacher = request.user.teacher
    except Teacher.DoesNotExist:
        teacher = Teacher.objects.create(member_ptr=request.user)
        teacher.save()
    
    # ดึงโปรเจคที่อาจารย์เกี่ยวข้อง (เป็นที่ปรึกษาหรือกรรมการ)
    projects = Project.objects.filter(
        Q(advisor=teacher) | Q(committee__in=[teacher])
    ).distinct().prefetch_related('students')

    if request.method == 'POST':
        form = ScoreForm(request.POST, project_id=request.POST.get('project'))
        if form.is_valid():
            score = form.save(commit=False)
            score.teacher = teacher
            score.save()
            messages.success(request, 'บันทึกคะแนนเรียบร้อยแล้ว')
            return redirect('assign_score')
        else:
            messages.error(request, 'มีข้อผิดพลาดในการบันทึกคะแนน')
    else:
        form = ScoreForm()

    return render(request, 'teacher/assign_score.html', {
        'projects': projects,
        'form': form,
    })

@login_required
def all_projects(request):
    selected_year = request.GET.get('year', '')
    
    projects = Project.objects.all().prefetch_related(
        Prefetch('students', queryset=Student.objects.all()),
        Prefetch('committee', queryset=Teacher.objects.all()),
        Prefetch('files', queryset=File.objects.all())
    ).select_related('advisor')
    
    if selected_year:
        projects = projects.filter(year=selected_year)
    
    project_data = []
    for project in projects:
        # แยกไฟล์และลิงก์
        uploaded_files = []
        external_links = []
        
        for file in project.files.all():
            if file.file:
                uploaded_files.append({
                    'name': file.file.name.split('/')[-1],
                    'url': file.file.url
                })
            if file.url:
                from urllib.parse import urlparse
                domain = urlparse(file.url).netloc
                external_links.append({
                    'url': file.url,
                    'domain': domain
                })
        
        project_data.append({
            'project_id': project.id,
            'project_topic': project.topic,
            'student_ids': ", ".join([s.student_id for s in project.students.all() if s.student_id]),
            'student_names': ", ".join([s.get_full_name() for s in project.students.all()]),
            'year': project.year,
            'advisor': project.advisor.get_full_name(),
            'committee': ", ".join([t.get_full_name() for t in project.committee.all()]),
            'uploaded_files': uploaded_files,  # ไฟล์ที่อัปโหลด
            'external_links': external_links   # ลิงก์ภายนอก
        })
    
    years = Project.objects.values_list('year', flat=True).distinct().order_by('-year')
    
    return render(request, 'manager/all_projects.html', {
        'project_data': project_data,
        'years': years,
        'selected_year': selected_year,
        'all_teachers': Teacher.objects.all(),
    })


@login_required
def export_projects_csv(request):
    selected_year = request.GET.get('year', '')
    
    if selected_year:
        filename = f"projects_{selected_year}.csv"
        projects = Project.objects.filter(year=selected_year)
    else:
        filename = "projects_all_years.csv"
        projects = Project.objects.all()
    
    response = HttpResponse(
        content_type='text/csv; charset=utf-8-sig',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
    
    writer = csv.writer(response)
    # เขียนหัวตาราง
    writer.writerow([
        'หัวข้อโครงงาน', 
        'รหัสนักศึกษา', 
        'ชื่อนักศึกษา', 
        'ปี', 
        'อาจารย์ที่ปรึกษา', 
        'กรรมการ', 
        'ไฟล์', 
        'ลิงก์'
    ])
    
    projects = projects.prefetch_related('students', 'committee', 'files').select_related('advisor')
    
    for project in projects:
        uploaded_files = []
        external_links = []
        
        for file in project.files.all():
            if file.file:
                # สำหรับไฟล์ที่อัปโหลด
                file_name = file.file.name.split('/')[-1]  # ดึงชื่อไฟล์
                uploaded_files.append(
                    f'=HYPERLINK("{request.build_absolute_uri(file.file.url)}","{file_name}")'
                )
            elif file.url:
                # สำหรับลิงก์ภายนอก
                from urllib.parse import urlparse
                domain = urlparse(file.url).netloc
                external_links.append(
                    f'=HYPERLINK("{file.url}","{domain}")'
                )
        
        writer.writerow([
            project.topic,
            ", ".join([str(s.student_id) for s in project.students.all() if s.student_id]),
            ", ".join([s.get_full_name() for s in project.students.all()]),
            project.year,
            project.advisor.get_full_name(),
            ", ".join([t.get_full_name() for t in project.committee.all()]),
            "\n".join(uploaded_files) if uploaded_files else "ไม่มีไฟล์",
            "\n".join(external_links) if external_links else "ไม่มีลิงก์"
        ])
    
    return response

@login_required
def update_project_committee(request):
    if request.method == 'POST':
        project_id = request.POST.get('project_id')
        committee_ids = request.POST.getlist('committee')
        
        try:
            project = Project.objects.get(id=project_id)
            
            # ล้างกรรมการทั้งหมดและเพิ่มใหม่
            project.committee.clear()
            
            for teacher_id in committee_ids:
                try:
                    teacher = Teacher.objects.get(id=teacher_id)
                    project.committee.add(teacher)
                except Teacher.DoesNotExist:
                    pass
            
            messages.success(request, 'อัปเดตกรรมการโครงงานเรียบร้อยแล้ว')
        except Project.DoesNotExist:
            messages.error(request, 'ไม่พบโครงงานที่ระบุ')
        
        # ส่งพารามิเตอร์การค้นหากลับไปด้วย (ถ้ามี)
        redirect_url = reverse('all_projects')
        selected_year = request.GET.get('year')
        if selected_year:
            redirect_url += f'?year={selected_year}'
        
        return redirect(redirect_url)
    
    return redirect('all_projects')

@login_required
def get_project_committees(request, project_id):
    try:
        project = Project.objects.get(id=project_id)
        committee_ids = list(project.committee.values_list('id', flat=True))
        
        return JsonResponse({
            'committee_ids': committee_ids
        })
    except Project.DoesNotExist:
        return JsonResponse({'error': 'Project not found'}, status=404)

@login_required
def all_student_scores(request):
    if not request.user.is_manager():
        messages.error(request, "คุณไม่มีสิทธิ์เข้าถึงหน้านี้")
        return redirect('login')
    
    selected_year = request.GET.get('year', '')
    
    projects = Project.objects.all().prefetch_related(
        Prefetch('students', queryset=Student.objects.all()),
        Prefetch('scores', queryset=Score.objects.select_related('teacher'))
    ).select_related('advisor')
    
    if selected_year:
        projects = projects.filter(year=selected_year)
    
    project_data = []
    
    for project in projects:
        students = project.students.all()
        scores = project.scores.all()
        
        student_info = []
        for student in students:
            student_scores = scores.filter(student=student)
            avg_score = student_scores.aggregate(Avg('score'))['score__avg'] if student_scores.exists() else None
            evaluations = [f"{score.teacher.get_full_name()}: {score.score}" for score in student_scores]
            
            student_info.append({
                'id': student.student_id,
                'name': f"{student.first_name} {student.last_name}",
                'average': round(avg_score, 2) if avg_score else '-',
                'evaluations': ", ".join(evaluations) if evaluations else '-'
            })
        
        project_data.append({
            'topic': project.topic,
            'year': project.year,
            'advisor': project.advisor.get_full_name(),
            'students': student_info
        })
    
    years = Project.objects.values_list('year', flat=True).distinct().order_by('-year')
    
    return render(request, 'manager/all_student_scores.html', {
        'project_data': project_data,
        'years': years,
        'selected_year': selected_year
    })

@login_required
def export_scores_csv(request):
    if not request.user.is_manager():
        messages.error(request, "คุณไม่มีสิทธิ์เข้าถึงหน้านี้")
        return redirect('login')
    
    selected_year = request.GET.get('year', '')
    
    # กำหนดชื่อไฟล์ภาษาไทยอย่างชัดเจน
    if selected_year:
        filename = f"คะแนนโครงงานนักศึกษา_ปีการศึกษา_{selected_year}.csv"
    else:
        filename = "คะแนนโครงงานนักศึกษา_ทั้งหมด.csv"
    
    # ใช้ quote เพื่อป้องกันปัญหาชื่อไฟล์ในบางเบราว์เซอร์
    from urllib.parse import quote
    response = HttpResponse(
        content_type='text/csv; charset=utf-8-sig',
        headers={'Content-Disposition': f'attachment; filename="{quote(filename)}"'},
    )
    
    fieldnames = [
        'ชื่อโครงงาน', 
        'รหัสนักศึกษา', 
        'ชื่อนักศึกษา', 
        'ปีการศึกษา', 
        'อาจารย์ที่ปรึกษา', 
        'คะแนนเฉลี่ย', 
        'ผู้ให้คะแนน'
    ]
    
    writer = csv.DictWriter(response, fieldnames=fieldnames)
    writer.writeheader()
    
    projects = Project.objects.all().prefetch_related(
        Prefetch('students', queryset=Student.objects.all()),
        Prefetch('scores', queryset=Score.objects.select_related('teacher'))
    ).select_related('advisor')
    
    if selected_year:
        projects = projects.filter(year=selected_year)
    
    for project in projects:
        for student in project.students.all():
            student_scores = project.scores.filter(student=student)
            avg_score = student_scores.aggregate(Avg('score'))['score__avg'] if student_scores.exists() else None
            evaluations = [f"{score.teacher.get_full_name()}: {score.score}" for score in student_scores]
            
            # แก้ไขให้แสดงรหัสนักศึกษาเป็นข้อความเต็มรูปแบบ
            student_id = f"'{student.student_id}" if student.student_id else ''
            
            writer.writerow({
                'ชื่อโครงงาน': project.topic,
                'รหัสนักศึกษา': student_id,
                'ชื่อนักศึกษา': f"{student.first_name} {student.last_name}",
                'ปีการศึกษา': project.year,
                'อาจารย์ที่ปรึกษา': project.advisor.get_full_name(),
                'คะแนนเฉลี่ย': round(avg_score, 2) if avg_score else '-',
                'ผู้ให้คะแนน': ", ".join(evaluations) if evaluations else '-'
            })
    
    return response