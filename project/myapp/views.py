from collections import defaultdict
from datetime import datetime, timedelta
import hashlib
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.db.models import Q
import json
from django.db.models import Avg
import requests
from .utils import generate_meeting_link 
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
from django.contrib.auth import  login
from django.core.mail import send_mail
from .models import  Project, Appointment, AvailableTime,Teacher,Score, Member,Student
from .forms import NewsForm, AppointmentForm, ScoreForm,ProjectForm, FileForm 
from .utils import  send_email_notification
from django.utils import timezone
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import *
from .forms import *
from allauth.socialaccount.models import SocialAccount
from .utils import get_role_from_email


'''def get_role_from_email(email):
    if not email:
        return None  # หากไม่มีอีเมล คืนค่า None
    
    allowed_teacher_emails = [
        'wiw12waranya@gmail.com',  # เพิ่มอีเมลนี้เพื่อให้เป็นอาจารย์
    ]
    allowed_manager_emails = [
        'waranyaph30@gmail.com',  # อีเมลที่ได้รับอนุญาตสำหรับ manager
    ]
    #teacher_pattern = r'^[A-Za-z]+\.[A-Za-z]@ubu\.ac\.th$'
    student_pattern = r'^[A-Za-z]+\.[A-Za-z]{2,3}\.\d{2}@ubu\.ac\.th$'


    #if re.match(teacher_pattern, email):
       # return 2  # อาจารย์
    if email.lower() in allowed_teacher_emails:
        print("Email matches teacher list")
        return 2  # อาจารย์
    elif re.match(student_pattern, email):
        return 1  # นักศึกษา
    elif email.lower() in allowed_manager_emails:
        return 3  # ผู้จัดการ
    else:
        return None  # ไม่ตรงกับอีเมลที่กำหนด'''

def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email', '')
        
        if email:
            role = get_role_from_email(email)
            
            if role is not None:
                try:
                    user = Member.objects.get(email=email)
                    
            
                    if not user.username:
                        user.username = user.email  
                    if not user.first_name:
                        user.first_name = 'Default'  
                    if not user.last_name:
                        user.last_name = 'Default'  
                    if not user.email:
                        user.email = email  
                    user.role = role 
                    user.save()  
                    
                    login(request, user)

                except Member.DoesNotExist:
                    messages.error(request, "ไม่พบผู้ใช้ที่มีอีเมลนี้ในระบบ")
                    return redirect('login')

    if request.user.is_authenticated:
        print(f"User ID: {request.user.id}, Email: '{request.user.email}'")
        
        if not request.user.email:
            messages.error(request, "ไม่พบอีเมลของคุณ กรุณาใช้บัญชีที่มีอีเมลที่ถูกต้อง")
            logout(request)
            return redirect('login')
        
        role = get_role_from_email(request.user.email)
        print(f"User Role: {role}")
        
        if role == 1: 
            try:
                student = request.user.student
            except Student.DoesNotExist:
                student = Student.objects.create(member_ptr=request.user)
                student.save()
            return redirect('student_dashboard')
        elif role == 2: 
            try:
                teacher = request.user.teacher
            except Teacher.DoesNotExist:
                teacher = Teacher.objects.create(member_ptr=request.user)
                teacher.save()
            return redirect('teacher_dashboard')
        elif role == 3:  
            return redirect('manager_home')
        else:
            return HttpResponse("Role not defined correctly.")
    
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

    appointments = Appointment.objects.filter(status="accepted")
    return render(request, 'teacher/dashboard.html', {'appointments': appointments})

@login_required
def manager_home(request):
  
    if not request.user.is_manager():
        return redirect('login')  
    return render(request, 'manager/manager_home.html')

@login_required
def manager_dashboard(request):
    if not request.user.is_manager():
        return redirect('login')
        
    total_users = Member.objects.count()
    total_students = Member.objects.filter(role=1).count()
    total_teachers = Member.objects.filter(role=2).count()
    
    total_appointments = Appointment.objects.count()
    confirmed_appointments = Appointment.objects.filter(status='accepted').count()
    pending_appointments = Appointment.objects.filter(status='pending').count()
    cancelled_appointments = Appointment.objects.filter(status='cancelled').count()
    
    appointments = Appointment.objects.all().select_related('project', 'project__advisor')
    return render(request, 'manager/dashboard.html', {
        'total_users': total_users,
        'total_students': total_students,
        'total_teachers': total_teachers,
        'total_appointments': total_appointments,
        'confirmed_appointments': confirmed_appointments,
        'pending_appointments': pending_appointments,
        'cancelled_appointments': cancelled_appointments,
        'appointments': appointments,
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

@login_required
def upload_project(request):
    if request.method == 'POST':
        project_form = ProjectForm(request.POST)
        file_form = FileForm(request.POST, request.FILES)

        if project_form.is_valid() and file_form.is_valid():
           
            project = project_form.save(commit=False)
            project.save()
            project_form.save_m2m()  

           
            project.students.add(request.user.student)  

            file = file_form.save(commit=False)
            file.project = project  
            file.save()

           
            messages.success(request, "อัปโหลดสำเร็จ!")
            return redirect('student_dashboard')  
        else:
            messages.error(request, "ลองอีกครั้ง")
    else:
        project_form = ProjectForm()
        file_form = FileForm()

    return render(request, 'student/upload_project.html', {
        'project_form': project_form,
        'file_form': file_form,
    })

@login_required
def my_projects(request):
   
    projects = Project.objects.filter(students=request.user)
    
    return render(request, 'student/my_projects.html', {
        'projects': projects
    })

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

@login_required
def edit_project(request, project_id):
    # ดึงข้อมูลโครงงานและตรวจสอบว่าเป็นนักเรียนที่สมัครโครงงานนี้หรือไม่
    project = get_object_or_404(Project, id=project_id, students=request.user)
    
    if request.method == 'POST':
        project_form = ProjectForm(request.POST, instance=project)
        file_form = FileForm(request.POST, request.FILES)

        if project_form.is_valid() and file_form.is_valid():
            # บันทึกรายละเอียดของโครงงาน
            project = project_form.save(commit=False)
            project.save()

            # บันทึกการเชื่อมโยง many-to-many สำหรับกรรมการ
            project_form.save_m2m()

            # บันทึกไฟล์
            file = file_form.save(commit=False)
            file.project = project
            file.save()

            messages.success(request, "โครงงานของคุณได้รับการแก้ไขเรียบร้อยแล้ว!")
            return redirect('my_projects')  # เปลี่ยนเส้นทางไปที่หน้าหลักของนักเรียน
        else:
            messages.error(request, "เกิดข้อผิดพลาดในการกรอกข้อมูล กรุณาลองใหม่อีกครั้ง.")
    else:
        project_form = ProjectForm(instance=project)
        file_form = FileForm()

    # ดึงข้อมูลครูทั้งหมดเพื่อแสดงในฟอร์ม
    all_teachers = Teacher.objects.all()

    return render(request, 'student/edit_project.html', {
        'project_form': project_form,
        'file_form': file_form,
        'project': project,
        'all_teachers': all_teachers
    })

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
        student = request.user.student 
    except Student.DoesNotExist:

        student = Student.objects.create(member_ptr=request.user)  
        student.save()

    if not request.user.username:
        request.user.username = request.user.email.split('@')[0]  # ใช้อีเมลเพื่อสร้าง username
        request.user.save()

    # ถ้ามีการโพสต์ข้อมูล ให้ใช้ฟอร์ม EditProfileForm
    if request.method == 'POST':
        form = EditProfileForm(request.POST, instance=student)
        if form.is_valid():
            form.save()
            messages.success(request, 'แก้ไขโปรไฟล์เรียบร้อยแล้ว!')
            return redirect('student_dashboard')  # หรือ redirect ไปยังหน้าที่เหมาะสม
    else:
        form = EditProfileForm(instance=student)

    return render(request, 'student/edit_profile.html', {'form': form})


@login_required
def my_appointments(request):

    now = timezone.now().date()


    Appointment.objects.filter(status="rejected", date__lt=now - timedelta(days=1)).delete()
    Appointment.objects.filter(status="accepted", date__lt=now).delete()

 
    for appointment in Appointment.objects.filter(status="pending"):
        related_teachers = [appointment.project.advisor] 
        related_teachers += list(appointment.project.committee.all()) 

        teacher_ids = [teacher.id for teacher in related_teachers]
        approved_count = Appointment.objects.filter(id=appointment.id, project__advisor__id__in=teacher_ids, status="accepted").count()
        rejected_count = Appointment.objects.filter(id=appointment.id, project__advisor__id__in=teacher_ids, status="rejected").count()

        if rejected_count > 0:
            appointment.status = "rejected"

        elif approved_count == len(related_teachers):
            appointment.status = "accepted"

        appointment.save()

    appointments = Appointment.objects.filter(students=request.user)
    pending_appointments = appointments.filter(status="pending")
    accepted_appointments = appointments.filter(status="accepted")
    rejected_appointments = appointments.filter(status="rejected")

    if request.method == "POST":
        appointment_id = request.POST.get("appointment_id")
        meeting_link = request.POST.get("meeting_link")
        location = request.POST.get("location")

        appointment = get_object_or_404(Appointment, id=appointment_id, students=request.user)

        if meeting_link:
            appointment.meeting_link = meeting_link
        if location:
            appointment.location = location
        
        appointment.save()
        messages.success(request, "ข้อมูลการนัดหมายของคุณถูกบันทึกแล้ว")
        return redirect("my_appointments")

    return render(request, "student/my_appointments.html", {
        "pending_appointments": pending_appointments,
        "accepted_appointments": accepted_appointments,
        "rejected_appointments": rejected_appointments,
    })


@login_required
def book_appointment(request):
    if request.method == "POST":
        print("\n🟢 POST Data Received:", json.dumps(request.POST.dict(), indent=4, ensure_ascii=False))

        teacher_ids = request.POST.get("teacher_ids", "").split(",")  
        date = request.POST.get("date")
        start_time_str = request.POST.get("start_time")
        end_time_str = request.POST.get("end_time")
        project_id = request.POST.get("project_id")

        if not project_id:
            messages.error(request, "ไม่พบโปรเจคของคุณ กรุณาตรวจสอบอีกครั้ง")
            return redirect("student_check_time")

        project = get_object_or_404(Project, id=project_id)

        try:
            start_time = datetime.strptime(start_time_str, "%H:%M").time()
            end_time = datetime.strptime(end_time_str, "%H:%M").time()
        except ValueError:
            messages.error(request, "รูปแบบเวลาผิดพลาด กรุณาเลือกเวลาที่ถูกต้อง (HH:MM)")
            return redirect("student_check_time")

        appointment = Appointment.objects.create(
            date=date,
            time_start=start_time,
            time_finish=end_time,
            location="", 
            project=project,
            status="pending",
        )

        for teacher_id in teacher_ids:
            if teacher_id.strip():
                teacher = get_object_or_404(Teacher, id=int(teacher_id))
                appointment.students.add(request.user)

        appointment.save()
        print("\n✅ Appointment Saved:", appointment)

        messages.success(request, "นัดหมายของคุณถูกบันทึกแล้ว รอการอนุมัติจากอาจารย์")
        return redirect("my_appointments")

    return redirect("my_appointments")

def teacher_appointments(request):
    if not (request.user.role == 2 or request.user.role == 3):
        messages.error(request, "กรุณาล็อกอินก่อนเข้าหน้านี้")
        return redirect('login')

    teacher = request.user.teacher
    appointments = Appointment.objects.filter(
        Q(project__advisor=teacher) | Q(project__committee=teacher)
    ).distinct()

    pending_appointments = appointments.filter(status="pending").distinct()
    confirmed_appointments = appointments.filter(status="accepted").distinct()
    rejected_appointments = appointments.filter(status="rejected").distinct()

    return render(request, 'teacher/appointments.html', {
        'pending_appointments': pending_appointments,
        'confirmed_appointments': confirmed_appointments,
        'rejected_appointments': rejected_appointments,
    })
@login_required
def accept_appointment(request, appointment_id):
    try:
        # ค้นหาการนัดหมาย
        appointment = get_object_or_404(Appointment, id=appointment_id)
        print(f"🔹 ก่อนอัปเดต: Appointment ID: {appointment.id}, Status: {appointment.status}")

        # อัปเดตสถานะ
        appointment.status = "accepted"
        appointment.save()

        # ตรวจสอบหลังอัปเดต
        updated = Appointment.objects.get(id=appointment_id)
        print(f"✅ หลังอัปเดต: Appointment ID: {updated.id}, Status: {updated.status}")

        messages.success(request, "✅ คุณได้อนุมัติการนัดหมายแล้ว")
    except Exception as e:
        print(f"❌ Error updating appointment: {e}")
        messages.error(request, f"เกิดข้อผิดพลาด: {str(e)}")

    return redirect('teacher_appointments')

@login_required
def reject_appointment(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id)
    if request.user == appointment.project.advisor or request.user in appointment.project.committee.all():
        appointment.status = 'rejected'
        appointment.save()
        messages.success(request, 'คุณได้ปฏิเสธการนัดหมายแล้ว')
    return redirect('teacher_appointments')  # แก้ไขจาก 'teacher:teacher_appointments'

@login_required
def available_time(request):
    if not request.user.is_teacher():
        return redirect('login')
  
    try:
        teacher = request.user.teacher
    except Teacher.DoesNotExist:
      
        teacher = Teacher.objects.create(member_ptr=request.user)
        teacher.save()
    
    available_times = AvailableTime.objects.filter(teacher=teacher)
    

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
    
    projects = Project.objects.filter(
        Q(advisor=teacher) | Q(committee__in=[teacher])
    ).distinct()

    if request.method == 'POST':
        project_id = request.POST.get('project_id')
        score_value = request.POST.get('score')
        comment = request.POST.get('comment')

        try:
            project = Project.objects.get(id=project_id)
            student = project.students.first()  
            if student:
                score = Score.objects.create(
                    project=project,
                    student=student,
                    teacher=teacher,
                    score=score_value,
                    comment=comment
                )
                messages.success(request, 'ให้คะแนนเรียบร้อยแล้ว!')
            else:
                messages.error(request, 'ไม่พบนักศึกษาในโปรเจคนี้')
        except Project.DoesNotExist:
            messages.error(request, 'ไม่พบโปรเจคที่เลือก')
        return redirect('assign_score')

    form = ScoreForm()
    return render(request, 'teacher/assign_score.html', {
        'projects': projects,
        'form': form,
    })



@login_required
def manager_appointment(request):
    if not request.user.is_manager():
        messages.error(request, "คุณไม่มีสิทธิ์เข้าถึงหน้านี้")
        return redirect('login')
        
    if request.method == 'POST':
        form = AppointmentForm(request.POST)
        
        if form.is_valid():
            # สร้างโครงงานชั่วคราวสำหรับการนัดหมาย
            topic = request.POST.get('topic', 'การนัดหมายสอบโครงงาน')
            
            # หาอาจารย์แรกที่ถูกเลือกเพื่อเป็นที่ปรึกษา
            selected_teachers = request.POST.getlist('teachers')
            
            if not selected_teachers:
                messages.error(request, 'กรุณาเลือกอาจารย์อย่างน้อย 1 คน')
                teachers = Teacher.objects.all()
                students = Member.objects.filter(role=1).select_related('student')
                return render(request, 'manager/appointments.html', {'form': form, 'teachers': teachers, 'students': students})
            
            try:
                advisor = Teacher.objects.get(id=selected_teachers[0])
                
                # สร้างโครงงานชั่วคราว
                temp_project = Project.objects.create(
                    topic=topic,
                    year=datetime.now().year,
                    advisor=advisor
                )
                
                # เพิ่มคณะกรรมการ
                for teacher_id in selected_teachers[1:]:
                    try:
                        teacher = Teacher.objects.get(id=teacher_id)
                        temp_project.committee.add(teacher)
                    except Teacher.DoesNotExist:
                        pass
                
                # สร้างการนัดหมาย
                appointment = Appointment.objects.create(
                    date=form.cleaned_data['date'],
                    time_start=form.cleaned_data['time_start'],
                    time_finish=form.cleaned_data['time_finish'],
                    location=form.cleaned_data['location'],
                    meeting_link=form.cleaned_data['meeting_link'],
                    project=temp_project,
                    status='pending'
                )
                
                # เพิ่มนักศึกษา
                selected_students = request.POST.getlist('students')
                for student_id in selected_students:
                    try:
                        student = Member.objects.get(id=student_id)
                        appointment.students.add(student)
                        
                        # เพิ่มนักศึกษาเข้าโครงงานด้วย
                        student_obj = Student.objects.filter(member_ptr=student).first()
                        if student_obj:
                            temp_project.students.add(student_obj)
                    except Member.DoesNotExist:
                        pass
                
                messages.success(request, 'นัดหมายการสอบถูกสร้างเรียบร้อยแล้ว!')
                return redirect('manager_dashboard')
            
            except Exception as e:
                messages.error(request, f'เกิดข้อผิดพลาด: {str(e)}')
        else:
            messages.error(request, 'กรุณาตรวจสอบข้อมูลที่กรอก')
    else:
        form = AppointmentForm()
    
    # ดึงข้อมูลอาจารย์และนักศึกษาทั้งหมด
    teachers = Teacher.objects.all()
    students = Member.objects.filter(role=1).select_related('student')
    
    context = {
        'form': form,
        'teachers': teachers,
        'students': students,
    }
    
    return render(request, 'manager/appointments.html', context)

@login_required
def all_projects(request):

    selected_year = request.GET.get('year', '')
    
    projects = Project.objects.all()
    
    if selected_year:
        projects = projects.filter(year=selected_year)

    project_data = []
    for project in projects:

        committee_names = ", ".join([teacher.get_full_name() for teacher in project.committee.all()])
        
        for student in project.students.all():
            project_data.append({
                'project_id': project.id,
                'project_topic': project.topic,
                'student_id': student.student_id,
                'student_name': student.get_full_name(),
                'year': project.year,
                'advisor': project.advisor.get_full_name(),
                'committee': committee_names,
            })
    years = Project.objects.values_list('year', flat=True).distinct().order_by('-year')
    all_teachers = Teacher.objects.all()
    
    return render(request, 'manager/all_projects.html', {
        'project_data': project_data,
        'years': years,
        'selected_year': selected_year,
        'all_teachers': all_teachers,
    })

@login_required
def export_projects_csv(request):
    selected_year = request.GET.get('year', '')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="projects.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['รหัสโครงงาน', 'หัวข้อโครงงาน', 'รหัสนักศึกษา', 'ชื่อนักศึกษา', 'ปี', 'อาจารย์ที่ปรึกษา', 'กรรมการ'])
    
    projects = Project.objects.all()
    
    # กรองตามปีที่เลือก
    if selected_year:
        projects = projects.filter(year=selected_year)
    
    for project in projects:
        committee_names = ", ".join([teacher.get_full_name() for teacher in project.committee.all()])
        
        for student in project.students.all():
            writer.writerow([
                project.id,
                project.topic,
                student.student_id,
                student.get_full_name(),
                project.year,
                project.advisor.get_full_name(),
                committee_names,
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

def all_student_scores(request):
    if not request.user.is_manager():
        messages.error(request, "คุณไม่มีสิทธิ์เข้าถึงหน้านี้")
        return redirect('login')
    
    selected_year = request.GET.get('year', '')
    search_query = request.GET.get('search', '')
    
    projects = Project.objects.all().select_related('advisor').prefetch_related('committee', 'students')
    

    if selected_year:
        projects = projects.filter(year=selected_year)
    

    if search_query:
        projects = projects.filter(
            Q(topic__icontains=search_query) |  
            Q(students__first_name__icontains=search_query) |  
            Q(students__last_name__icontains=search_query) | 
            Q(students__student_id__icontains=search_query)  
        ).distinct()
    
 
    project_scores = []
    
    for project in projects:
    
        scores = Score.objects.filter(project=project).select_related('student', 'teacher')
        
        if scores.exists():
            average_score = scores.aggregate(Avg('score'))['score__avg']
        
            committee_members = [teacher.get_full_name() for teacher in project.committee.all()]
        
            for student in project.students.all():
                student_scores = scores.filter(student=student)
                
                if student_scores.exists():
                    student_avg = student_scores.aggregate(Avg('score'))['score__avg']
                    teacher_evaluations = []
                    

                    for score in student_scores:
                        teacher_evaluations.append({
                            'teacher_name': score.teacher.get_full_name(),
                            'score': score.score,
                            'comment': score.comment
                        })
                    
                    project_scores.append({
                        'project_id': project.id,
                        'project_topic': project.topic,
                        'year': project.year,
                        'student_id': student.student_id,
                        'student_name': f"{student.first_name} {student.last_name}",
                        'advisor': project.advisor.get_full_name(),
                        'committee': committee_members,  
                        'average_score': round(student_avg, 2),
                        'project_average': round(average_score, 2),
                        'teacher_evaluations': teacher_evaluations
                    })
    
    years = Project.objects.values_list('year', flat=True).distinct().order_by('-year')
    
    return render(request, 'manager/all_student_scores.html', {
        'project_scores': project_scores,
        'years': years,
        'selected_year': selected_year,
        'search_query': search_query
    })

@login_required
def export_scores_csv(request):
    if not request.user.is_manager():
        messages.error(request, "คุณไม่มีสิทธิ์เข้าถึงหน้านี้")
        return redirect('login')
    
    selected_year = request.GET.get('year', '')
    search_query = request.GET.get('search', '')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="student_scores.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['รหัสนักศึกษา', 'ชื่อ-สกุล', 'ชื่อโครงงาน', 'ปีการศึกษา', 'อาจารย์ที่ปรึกษา', 'คะแนนเฉลี่ย', 'คะแนนเฉลี่ยโครงงาน', 'รายละเอียดคะแนน'])
    
    # ดึงข้อมูลโครงงานทั้งหมด
    projects = Project.objects.all().select_related('advisor')
    
    # กรองตามปีที่เลือก
    if selected_year:
        projects = projects.filter(year=selected_year)
    
    # กรองตามการค้นหา
    if search_query:
        projects = projects.filter(
            Q(topic__icontains=search_query) |
            Q(students__first_name__icontains=search_query) |
            Q(students__last_name__icontains=search_query) |
            Q(students__student_id__icontains=search_query)
        ).distinct()
    
    for project in projects:
        scores = Score.objects.filter(project=project).select_related('student', 'teacher')
        
        if scores.exists():
            average_score = scores.aggregate(Avg('score'))['score__avg']
            
            for student in project.students.all():
                student_scores = scores.filter(student=student)
                
                if student_scores.exists():
                    student_avg = student_scores.aggregate(Avg('score'))['score__avg']
                    
                    # รวบรวมคะแนนจากอาจารย์แต่ละคนในรูปแบบข้อความ
                    teacher_scores = []
                    for score in student_scores:
                        teacher_scores.append(f"{score.teacher.get_full_name()}: {score.score}")
                    
                    teacher_scores_str = "; ".join(teacher_scores)
                    
                    writer.writerow([
                        student.student_id,
                        f"{student.first_name} {student.last_name}",
                        project.topic,
                        project.year,
                        project.advisor.get_full_name(),
                        round(student_avg, 2),
                        round(average_score, 2),
                        teacher_scores_str
                    ])
    
    return response