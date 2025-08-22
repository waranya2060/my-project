# ===== Standard library =====
import csv
import json
import os
import pickle
import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timedelta

# ===== Third-party =====
import pandas as pd
from google_auth_oauthlib.flow import InstalledAppFlow
from urllib.parse import urlparse
# ===== Django =====
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q, Prefetch, Avg
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.html import strip_tags
from django.views.decorators.csrf import csrf_exempt

# ===== Local apps =====
from .utils import (
    get_role_from_email,
    has_google_token,
    create_google_calendar_event,
)
from .forms import (
    NewsForm,
    ScoreForm,
    ProjectForm,
    FileForm,
    RejectAppointmentForm,
    EditProfileForm,
)
from .models import (
    Project,
    Appointment,
    AvailableTime,
    Teacher,
    Score,
    Member,
    Student,
    Manager,
    File,
    News,
)


logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Auth / Session
# ----------------------------------------------------------------------------

@login_required(login_url='login')
def logout_view(request):
    logout(request)
    return redirect('login')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('redirect_after_login')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        if not email:
            messages.error(request, 'กรุณากรอกอีเมล')
            return redirect('login')

        role = get_role_from_email(email)
        if role is None:
            messages.error(request, 'อีเมลนี้ไม่ได้รับอนุญาต')
            return redirect('login')

        try:
            user = Member.objects.get(email=email)
            user.role = role
            user.save()

            login(request, user)
            return redirect('redirect_after_login')
        except Member.DoesNotExist:
            messages.error(request, 'ไม่พบบัญชีผู้ใช้')
            return redirect('login')

    return render(request, 'registration/login.html')


@login_required
def redirect_after_login(request):
    user = request.user
    logger.info(
        "[redirect_after_login] User: %s | Role: %s | Authenticated: %s",
        getattr(user, 'email', None), getattr(user, 'role', None), user.is_authenticated,
    )

    role = getattr(user, 'role', None)
    try:
        if role == 'student':
            Student.objects.get_or_create(member_ptr=user)
            return redirect('student_dashboard')
        elif role == 'teacher':
            Teacher.objects.get_or_create(member_ptr=user)
            return redirect('teacher_dashboard')
        elif role == 'manager':
            Manager.objects.get_or_create(member_ptr=user)
            return redirect('manager_dashboard')
    except Exception as e:
        logout(request)
        messages.error(request, f"บัญชีไม่สมบูรณ์: {str(e)}")
        return redirect('login')

    logout(request)
    messages.error(request, "บัญชีนี้ยังไม่มีบทบาทที่รองรับ")
    return redirect('login')


# ----------------------------------------------------------------------------
# Dashboards
# ----------------------------------------------------------------------------

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
        'projects': projects,
    }
    return render(request, 'student/dashboard.html', context)


@login_required
def teacher_dashboard(request):
    if not (request.user.is_teacher() or request.user.is_manager()):
        messages.error(request, "กรุณาล็อกอินก่อนเข้าหน้านี้")
        return redirect('login')

    teacher = getattr(request.user, 'teacher', None)
    has_token = has_google_token(request.user)

    appointments = (
        Appointment.objects.filter(teachers=teacher)
        .select_related('project', 'project__advisor')
        .prefetch_related('project__committee', 'project__students', 'students')
    )

    context = {
        'appointments': appointments,
        'pending_appointments': appointments.filter(status='pending'),
        'confirmed_appointments': appointments.filter(status='accepted'),
        'has_google_token': has_token,
    }
    return render(request, 'teacher/dashboard.html', context)


@login_required
def manager_dashboard(request):
    if not request.user.is_manager():
        return redirect('login')

    total_users = Member.objects.count()
    total_students = Member.objects.filter(role='student').count()
    total_teachers = Member.objects.filter(role__in=['teacher', 'manager']).count()

    appointments = Appointment.objects.all()
    total_appointments = appointments.count()

    status_counts = {
        'confirmed': appointments.filter(Q(status='accepted') | Q(status='confirmed')).count(),
        'pending': appointments.filter(status='pending').count(),
        'cancelled': appointments.filter(Q(status='cancelled') | Q(status='rejected')).count(),
    }

    calendar_appointments = (
        appointments.filter(status='accepted')
        .select_related('project', 'project__advisor')
        .prefetch_related('project__students')
    )

    context = {
        'total_users': total_users,
        'total_students': total_students,
        'total_teachers': total_teachers,
        'total_appointments': total_appointments,
        'confirmed_appointments': status_counts['confirmed'],
        'pending_appointments': status_counts['pending'],
        'cancelled_appointments': status_counts['cancelled'],
        'appointments': calendar_appointments,
    }
    return render(request, 'manager/dashboard.html', context)


# ----------------------------------------------------------------------------
# Projects (CRUD + listing)
# ----------------------------------------------------------------------------

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
                    project.save()

                    # เพิ่มผู้ใช้ปัจจุบัน
                    current_user = request.user.student
                    project.students.add(current_user)

                    # เพิ่มนักศึกษาที่เลือก
                    selected_students = project_form.cleaned_data.get('students', [])
                    for student in selected_students:
                        if student != current_user:
                            project.students.add(student)

                    # บันทึกไฟล์
                    if file_form.cleaned_data.get('file') or file_form.cleaned_data.get('url'):
                        fobj = file_form.save(commit=False)
                        fobj.project = project
                        fobj.save()

                    total_students = project.students.count()

                messages.success(request, f"อัปโหลดโครงงานสำเร็จ มีนักศึกษา {total_students} คน")
                return redirect('student_dashboard')
            else:
                # จัดการข้อผิดพลาดแบบละเอียด
                for field, errors in project_form.errors.items():
                    for error in errors:
                        messages.error(request, f"ข้อผิดพลาดใน {field}: {error}")
                for field, errors in file_form.errors.items():
                    for error in errors:
                        messages.error(request, f"ข้อผิดพลาดใน {field}: {error}")
        else:
            # กรณี GET request
            project_form = ProjectForm()
            file_form = FileForm()

    except Exception as e:
        logger.exception("เกิดข้อผิดพลาดในการอัปโหลดโปรเจค: %s", e)
        messages.error(request, f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {str(e)}")
        return redirect('student_dashboard')

    return render(
        request,
        'student/upload_project.html',
        {
            'project_form': project_form,
            'file_form': file_form,
        },
    )


@login_required
def search_students(request):
    term = request.GET.get('term', '').strip()
    print(f"Search term: '{term}'")
    
    if not term:
        return JsonResponse([], safe=False)

    try:
        # ใช้ Q objects อย่างถูกต้อง
        from django.db.models import Q
        
        students = Student.objects.filter(
            Q(student_id__icontains=term) |
            Q(first_name__icontains=term) |
            Q(last_name__icontains=term) |
            Q(first_name_th__icontains=term) |  # ถ้ามี field ภาษาไทย
            Q(last_name_th__icontains=term)     # ถ้ามี field ภาษาไทย
        )[:10]
        
        # ตรวจสอบการ exclude
        current_student_id = getattr(request.user.student, 'id', None) if hasattr(request.user, 'student') else None
        if current_student_id:
            students = students.exclude(id=current_student_id)

        results = []
        for s in students:
            results.append({
                'id': s.id,
                'student_id': s.student_id or '',
                'first_name': s.first_name or '',
                'last_name': s.last_name or '',
                'full_name': f"{s.first_name or ''} {s.last_name or ''}".strip(),
            })
        
        print(f"Returning {len(results)} results")
        return JsonResponse(results, safe=False)
        
    except Exception as e:
        print(f"Error in search_students: {e}")
        return JsonResponse([], safe=False)


@login_required
def my_projects(request):
    try:
        projects = (
            Project.objects.filter(students=request.user.student)
            .prefetch_related('students', 'committee', 'files')
            .select_related('advisor')
            .distinct()
        )

        for p in projects:
            logger.debug("Project %s (%s)", p.id, p.topic)
            p.other_students = p.students.exclude(id=request.user.student.id)
            p.has_other_students = p.other_students.exists()

        return render(request, 'student/my_projects.html', {'projects': projects})
    except Exception as e:
        messages.error(request, f"เกิดข้อผิดพลาดในการแสดงโครงงาน: {str(e)}")
        return redirect('student_dashboard')


@login_required
def delete_project(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    is_owner = request.user.is_student() and project.students.filter(member_ptr=request.user).exists()
    is_manager = request.user.is_manager()
    if not (is_owner or is_manager):
        messages.error(request, 'คุณไม่มีสิทธิ์ลบโครงงานนี้')
        return redirect('my_projects')

    project.delete()
    messages.success(request, 'ลบโครงงานเรียบร้อยแล้ว')
    return redirect('my_projects')


@login_required
def edit_project(request, project_id):
    try:
        student = request.user.student
        project = get_object_or_404(
            Project.objects.filter(students=student)
            .select_related('advisor')
            .prefetch_related('students', 'committee', 'files'),
            id=project_id,
        )

        if request.method == 'POST':
            project_form = ProjectForm(request.POST, instance=project)
            file_form = FileForm(request.POST, request.FILES)

            if project_form.is_valid() and file_form.is_valid():
                try:
                    updated = project_form.save()
                    if not updated.students.filter(id=student.id).exists():
                        updated.students.add(student)

                    if file_form.cleaned_data.get('file') or file_form.cleaned_data.get('url'):
                        fobj = file_form.save(commit=False)
                        fobj.project = updated
                        fobj.save()

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

        context = {
            'project_form': project_form,
            'file_form': file_form,
            'project': project,
            'advisor': project.advisor,
            'committee_members': project.committee.all(),
            'project_files': project.files.all(),
            'other_students': project.students.exclude(id=student.id),
            'has_other_students': project.students.exclude(id=student.id).exists(),
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


# ----------------------------------------------------------------------------
# Availability / Scheduling
# ----------------------------------------------------------------------------

@login_required
def check_time(request):
    if request.user.is_student():
        template = 'student/check_available.html'
    elif request.user.is_teacher() or request.user.is_manager():
        template = 'teacher/check_available.html'
    else:
        return redirect('login')

    teachers = Teacher.objects.all()
    selected_teacher_ids = request.GET.getlist('teacher')

    date_str = request.GET.get('date', '')
    date = parse_date(date_str) if date_str else None

    available_times = AvailableTime.objects.none()
    common_times = []
    booked_times = []
    pending_times = []

    if selected_teacher_ids and date is not None:
        selected_qs = Teacher.objects.filter(id__in=selected_teacher_ids)

        available_times = AvailableTime.objects.filter(
            teacher__in=selected_qs, date=date
        )

        booked_appointments = Appointment.objects.filter(
            date=date,
            status__in=['pending', 'accepted'],
            project__advisor__in=selected_qs,
        )

        booked_times = [
            (appt.time_start, appt.time_finish)
            for appt in booked_appointments
            if appt.status == 'accepted'
        ]
        pending_times = [
            (appt.time_start, appt.time_finish)
            for appt in booked_appointments
            if appt.status == 'pending'
        ]

        time_slots = defaultdict(list)
        for t in available_times:
            key = (t.start_time, t.end_time)
            time_slots[key].append(t.teacher)

        selected_set = set(selected_qs)
        for slot, teachers_in_slot in time_slots.items():
            if set(teachers_in_slot) == selected_set:
                is_booked = slot in booked_times
                is_pending = slot in pending_times
                common_times.append(
                    {
                        'start_time': slot[0],
                        'end_time': slot[1],
                        'teachers': teachers_in_slot,
                        'is_booked': is_booked,
                        'is_pending': is_pending,
                    }
                )

    no_teachers_available = not common_times

    student_projects = (
        Project.objects.filter(students=request.user) if request.user.is_student() else None
    )

    return render(
        request,
        template,
        {
            'teachers': teachers,
            'available_times': common_times,
            'no_teachers_available': no_teachers_available,
            'hours': range(8, 18),
            'selected_teachers': selected_teacher_ids,
            'date': date.strftime('%Y-%m-%d') if date else '',
            'student_projects': student_projects,
        },
    )


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
            teachers = ", ".join([s.teacher.get_full_name() for s in scores])
            project_scores.append(
                {
                    'project': project,
                    'average_score': round(average_score, 2),
                    'teachers': teachers,
                    'comments': ", ".join([s.comment for s in scores if s.comment]),
                }
            )

    return render(request, 'student/my_point.html', {'project_scores': project_scores})


@login_required
def edit_profile(request):
    if not request.user.is_student():
        messages.error(request, "คุณไม่มีสิทธิ์เข้าถึงหน้านี้")
        return redirect('login')

    try:
        student = Student.objects.get(member_ptr_id=request.user.id)
    except Student.DoesNotExist:
        Student.objects.create(
            member_ptr_id=request.user.id,
            student_id=None,
            role=1,
        )
        student = Student.objects.get(member_ptr_id=request.user.id)

    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        if student_id:
            Student.objects.filter(member_ptr_id=request.user.id).update(student_id=student_id)
            messages.success(request, 'แก้ไขโปรไฟล์เรียบร้อยแล้ว!')
            return redirect('student_dashboard')
        else:
            messages.error(request, "กรุณากรอกรหัสนักศึกษา")

    context = {'student': student, 'form': EditProfileForm(instance=student)}
    return render(request, 'student/edit_profile.html', context)


@login_required
def my_appointments(request):
    # อนุญาตให้นศ.แก้ลิงก์/สถานที่ของนัดที่ตัวเองอยู่
    if request.method == 'POST':
        appointment_id = request.POST.get('appointment_id')
        if appointment_id:
            try:
                appointment = Appointment.objects.get(id=appointment_id, students=request.user)
                meeting_link = request.POST.get('meeting_link') or ''
                location = request.POST.get('location') or ''
                if meeting_link:
                    appointment.meeting_link = meeting_link
                if location:
                    appointment.location = location
                appointment.save()
                messages.success(request, 'บันทึกข้อมูลการประชุมเรียบร้อยแล้ว')
            except Appointment.DoesNotExist:
                messages.error(request, 'ไม่พบการนัดหมาย')
            except Exception as e:
                messages.error(request, f'เกิดข้อผิดพลาด: {str(e)}')

    now = timezone.localtime()
    today = now.date()
    now_time = now.time()

    appointments = (
        Appointment.objects.filter(students=request.user)
        .filter(
            Q(date__gt=today)
            | Q(date=today, time_finish__gte=now_time)
            | Q(date=today, time_finish__isnull=True, time_start__gte=now_time)
        )
        .select_related('project')
        .prefetch_related('project__students')
        .order_by('date', 'time_start')
    )

    context = {
        'pending_appointments': appointments.filter(status='pending'),
        'accepted_appointments': appointments.filter(status='accepted'),
        'rejected_appointments': appointments.filter(status='rejected'),
    }
    return render(request, 'student/my_appointments.html', context)


# ----------------------------------------------------------------------------
# Google Calendar (OAuth + callback)
# ----------------------------------------------------------------------------

@login_required
def connect_google_calendar(request):
    if not (request.user.is_teacher() or request.user.is_manager()):
        messages.error(request, 'คุณไม่มีสิทธิ์เข้าถึงหน้านี้')
        return redirect('login')

    # สำหรับการพัฒนาเท่านั้น - อนุญาตให้ใช้ HTTP แทน HTTPS
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

    try:
        callback_url = request.build_absolute_uri(reverse('google_calendar_callback'))
        flow = InstalledAppFlow.from_client_secrets_file(
            'credentials.json',
            scopes=[
                'https://www.googleapis.com/auth/calendar',
                'https://www.googleapis.com/auth/userinfo.profile',
                'https://www.googleapis.com/auth/userinfo.email',
                'openid',
            ],
            redirect_uri=callback_url,
        )
        authorization_url, state = flow.authorization_url(
            access_type='offline', include_granted_scopes='true', prompt='consent'
        )
        request.session['google_auth_state'] = state

        logger.info('Starting Google Calendar authorization for %s', request.user.email)
        logger.info('Redirect URI: %s', callback_url)

        return redirect(authorization_url)
    except Exception as e:
        logger.exception('เกิดข้อผิดพลาดในการเริ่มต้นการเชื่อมต่อ Google Calendar: %s', e)
        messages.error(request, f'เกิดข้อผิดพลาด: {str(e)}')
        return redirect('teacher_dashboard')


def get_token_file_path(email: str) -> str:
    hashed_email = hashlib.md5(email.encode()).hexdigest()
    return os.path.join('tokens', f'token_{hashed_email}.pickle')


@login_required
def google_calendar_callback(request):
    if not (request.user.is_teacher() or request.user.is_manager()):
        messages.error(request, 'คุณไม่มีสิทธิ์เข้าถึงหน้านี้')
        return redirect('login')

    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

    try:
        logger.info('✅ Received callback for %s', request.user.email)
        logger.info('✅ Full URL: %s', request.build_absolute_uri())

        state = request.session.pop('google_auth_state', None)
        if not state:
            raise ValueError('ไม่พบ state ใน session')

        callback_url = request.build_absolute_uri(reverse('google_calendar_callback'))
        flow = InstalledAppFlow.from_client_secrets_file(
            'credentials.json',
            scopes=[
                'https://www.googleapis.com/auth/calendar',
                'https://www.googleapis.com/auth/userinfo.profile',
                'https://www.googleapis.com/auth/userinfo.email',
                'openid',
            ],
            redirect_uri=callback_url,
        )
        flow.state = state
        flow.fetch_token(authorization_response=request.build_absolute_uri())

        creds = flow.credentials

        token_path = get_token_file_path(request.user.email)
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, 'wb') as token_file:
            pickle.dump(creds, token_file)

        logger.info('🎉 Token saved to: %s', token_path)
        messages.success(request, 'เชื่อมต่อกับ Google Calendar สำเร็จแล้ว')
        return redirect('teacher_dashboard')
    except Exception as e:
        logger.exception('❌ เกิดข้อผิดพลาดในการรับ token: %s', e)
        messages.error(request, f'เกิดข้อผิดพลาด: {str(e)}')
        return redirect('teacher_dashboard')


# ----------------------------------------------------------------------------
# Booking / Appointments (student side + teacher side)
# ----------------------------------------------------------------------------

@login_required
def book_appointment(request):
    if request.method != 'POST':
        return redirect('student_check_time')

    try:
        teacher_ids_str = request.POST.get('teacher_ids', '')
        project_id = request.POST.get('project_id')
        date_str = request.POST.get('date')
        start_time = request.POST.get('start_time')
        end_time = request.POST.get('end_time')

        teacher_ids = [int(tid) for tid in teacher_ids_str.split(',') if tid]
        if not teacher_ids:
            messages.error(request, 'กรุณาเลือกอาจารย์อย่างน้อย 1 คน')
            return redirect('student_check_time')

        if not project_id:
            messages.error(request, 'กรุณาเลือกโครงงาน')
            return redirect('student_check_time')

        project = get_object_or_404(Project, id=project_id)
        if not project.students.filter(member_ptr=request.user).exists():
            messages.error(request, 'คุณไม่ได้เป็นส่วนหนึ่งของโครงงานนี้')
            return redirect('student_check_time')

        appointment = Appointment.objects.create(
            date=date_str,
            time_start=start_time,
            time_finish=end_time,
            project=project,
            status='pending',
        )

        for student in project.students.all():
            appointment.students.add(student)
            logger.debug('Added student %s to appointment', student.member_ptr.email)

        teacher_emails = []
        for teacher_id in teacher_ids:
            try:
                teacher = Teacher.objects.get(id=teacher_id)
                appointment.teachers.add(teacher)
                teacher_emails.append(teacher.email)

                try:
                    create_google_calendar_event(appointment, teacher.email)
                except Exception as e:
                    logger.warning('ไม่สามารถสร้างกิจกรรมใน Google Calendar: %s', e)
            except Teacher.DoesNotExist:
                logger.warning('Teacher with ID %s not found', teacher_id)

        if teacher_emails:
            try:
                formatted_date = appointment.date.strftime('%d/%m/%Y') if appointment.date else 'ไม่ระบุ'
                formatted_time_start = (
                    appointment.time_start.strftime('%H:%M')
                    if hasattr(appointment.time_start, 'strftime')
                    else (str(appointment.time_start) if appointment.time_start else 'ไม่ระบุ')
                )
                formatted_time_finish = (
                    appointment.time_finish.strftime('%H:%M')
                    if hasattr(appointment.time_finish, 'strftime')
                    else (str(appointment.time_finish) if appointment.time_finish else 'ไม่ระบุ')
                )

                subject = f"แจ้งเตือนการนัดหมายโครงงาน: {project.topic}"
                html_message = render_to_string(
                    'email/appointment_notification.html',
                    {
                        'appointment': appointment,
                        'project': project,
                        'students': project.students.all(),
                        'formatted_date': formatted_date,
                        'formatted_time_start': formatted_time_start,
                        'formatted_time_finish': formatted_time_finish,
                    },
                )
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
                logger.exception('เกิดข้อผิดพลาดในการส่งอีเมล: %s', e)

        appointment.save()
        messages.success(request, 'สร้างการนัดหมายเรียบร้อย รอการอนุมัติจากอาจารย์')
        return redirect('my_appointments')

    except Exception as e:
        logger.exception('Error creating appointment: %s', e)
        messages.error(request, f'เกิดข้อผิดพลาดในการสร้างการนัดหมาย: {str(e)}')
        return redirect('student_check_time')


@login_required
def teacher_appointments(request):
    if not (request.user.is_teacher() or request.user.is_manager()):
        return redirect('login')

    teacher = request.user.teacher

    now = timezone.localtime()
    today = now.date()
    now_time = now.time()

    appointments = Appointment.objects.filter(teachers=teacher)
    appointments = appointments.filter(
        Q(date__gt=today)
        | Q(date=today, time_finish__gte=now_time)
        | Q(date=today, time_finish__isnull=True, time_start__gte=now_time)
    )

    appointments = (
        appointments.distinct()
        .select_related('project', 'project__advisor')
        .prefetch_related('project__committee', 'teachers', Prefetch('students', queryset=Student.objects.select_related('member_ptr')))
        .order_by('date', 'time_start')
    )

    return render(
        request,
        'teacher/appointments.html',
        {
            'pending_appointments': appointments.filter(status='pending'),
            'confirmed_appointments': appointments.filter(status='accepted'),
            'rejected_appointments': appointments.filter(status='rejected'),
        },
    )


@login_required
def accept_appointment(request, appointment_id):
    try:
        appointment = get_object_or_404(Appointment, id=appointment_id)
        teacher = request.user.teacher

        if teacher not in appointment.teachers.all():
            messages.error(request, 'คุณไม่มีสิทธิ์อนุมัติการนัดหมายนี้')
            return redirect('teacher_appointments')

        accepted_teachers = json.loads(appointment.accepted_teachers) if appointment.accepted_teachers else []
        teacher_id_str = str(teacher.id)

        if teacher_id_str in accepted_teachers:
            messages.info(request, 'คุณได้อนุมัติการนัดหมายนี้แล้ว')
            return redirect('teacher_appointments')

        accepted_teachers.append(teacher_id_str)
        appointment.accepted_teachers = json.dumps(accepted_teachers)

        all_teacher_ids = [str(t.id) for t in appointment.teachers.all()]

        if set(accepted_teachers) == set(all_teacher_ids):
            appointment.status = 'accepted'

            calendar_events = []
            for tid in all_teacher_ids:
                try:
                    t_obj = Teacher.objects.get(id=int(tid))
                    token_path = get_token_file_path(t_obj.email)
                    if os.path.exists(token_path):
                        event_id = create_google_calendar_event(appointment, t_obj.email)
                        if event_id:
                            calendar_events.append(
                                {
                                    'teacher_id': tid,
                                    'teacher_name': t_obj.get_full_name(),
                                    'event_id': event_id,
                                }
                            )
                            logger.info('สร้างกิจกรรม Calendar สำหรับ %s สำเร็จ', t_obj.email)
                        else:
                            logger.warning('ไม่สามารถสร้างกิจกรรม Calendar สำหรับ %s', t_obj.email)
                    else:
                        logger.info('ไม่พบไฟล์ token สำหรับ %s', t_obj.email)
                except Exception as e:
                    logger.exception('เกิดข้อผิดพลาดกับอาจารย์ %s: %s', tid, e)

            if calendar_events:
                appointment.calendar_events = json.dumps(calendar_events)

            student_emails = [s.email for s in appointment.students.all() if s.email]
            if student_emails:
                try:
                    formatted_date = appointment.date.strftime('%d/%m/%Y') if appointment.date else 'ไม่ระบุ'
                    formatted_time_start = (
                        appointment.time_start.strftime('%H:%M')
                        if hasattr(appointment.time_start, 'strftime')
                        else str(appointment.time_start)
                    )
                    formatted_time_finish = (
                        appointment.time_finish.strftime('%H:%M')
                        if hasattr(appointment.time_finish, 'strftime')
                        else str(appointment.time_finish)
                    )

                    subject = f"การนัดหมายโครงงานได้รับการอนุมัติแล้ว: {appointment.project.topic}"
                    html_message = render_to_string(
                        'email/appointment_confirmed.html',
                        {
                            'appointment': appointment,
                            'project': appointment.project,
                            'formatted_date': formatted_date,
                            'formatted_time_start': formatted_time_start,
                            'formatted_time_finish': formatted_time_finish,
                            'calendar_events': bool(calendar_events),
                        },
                    )
                    plain_message = strip_tags(html_message)

                    send_mail(
                        subject=subject,
                        message=plain_message,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=student_emails,
                        html_message=html_message,
                        fail_silently=False,
                    )
                    logger.info('ส่งอีเมลยืนยันการนัดหมายให้นักศึกษาสำเร็จ')
                except Exception as e:
                    logger.exception('เกิดข้อผิดพลาดในการส่งอีเมล: %s', e)

            messages.success(request, '✅ การนัดหมายได้รับการอนุมัติจากอาจารย์ทุกท่านแล้ว')
        else:
            remaining = len(set(all_teacher_ids)) - len(set(accepted_teachers))
            messages.success(request, f'✅ คุณได้อนุมัติการนัดหมายแล้ว (รออีก {remaining} ท่าน)')

        appointment.save()
        return redirect('teacher_appointments')

    except Exception as e:
        logger.exception('เกิดข้อผิดพลาดในการอนุมัติการนัดหมาย: %s', e)
        messages.error(request, f'เกิดข้อผิดพลาด: {str(e)}')
        return redirect('teacher_appointments')


@login_required
def reject_appointment(request, appointment_id):
    try:
        appointment = get_object_or_404(Appointment, id=appointment_id)
        teacher = request.user.teacher

        if teacher not in appointment.teachers.all():
            messages.error(request, 'คุณไม่มีสิทธิ์ปฏิเสธการนัดหมายนี้')
            return redirect('teacher_appointments')

        if request.method == 'POST':
            form = RejectAppointmentForm(request.POST)
            if form.is_valid():
                appointment.rejection_reason = form.cleaned_data['rejection_reason']
                appointment.status = 'rejected'

                rejected_by = {'teacher_id': teacher.id, 'teacher_name': teacher.get_full_name()}
                appointment.rejected_by = json.dumps(rejected_by)

                appointment.save()
                logger.info('ปฏิเสธการนัดหมาย ID: %s สถานะใหม่: %s', appointment.id, appointment.status)
                messages.success(request, 'คุณได้ปฏิเสธการนัดหมายเรียบร้อยแล้ว')
                return redirect('teacher_appointments')
        else:
            form = RejectAppointmentForm()
            return render(request, 'teacher/reject_appointment.html', {'form': form, 'appointment': appointment})

    except Exception as e:
        logger.exception('เกิดข้อผิดพลาดในการปฏิเสธการนัดหมาย: %s', e)
        messages.error(request, f'เกิดข้อผิดพลาด: {str(e)}')
        return redirect('teacher_appointments')


# ----------------------------------------------------------------------------
# AvailableTime (list/create/update/delete)
# ----------------------------------------------------------------------------

@login_required
def available_time(request):
    if not (request.user.is_teacher() or request.user.is_manager()):
        return redirect('login')

    try:
        teacher = request.user.teacher
    except Teacher.DoesNotExist:
        teacher = Teacher.objects.create(member_ptr=request.user)
        teacher.save()

    current_datetime = timezone.now()

    # ลบเวลาที่เป็นวันก่อนหน้า
    AvailableTime.objects.filter(teacher=teacher, date__lt=current_datetime.date()).delete()

    # ลบเวลาที่เป็นวันนี้แต่เวลาสิ้นสุดผ่านไปแล้ว
    today_times = AvailableTime.objects.filter(teacher=teacher, date=current_datetime.date())
    for t in today_times:
        try:
            end_dt = timezone.make_aware(datetime.combine(t.date, t.end_time))
            if end_dt < current_datetime:
                t.delete()
        except Exception as e:
            logger.warning('Error checking expired time: %s', e)

    available_times = AvailableTime.objects.filter(teacher=teacher)

    for t in available_times:
        t.can_edit = timezone.now() <= (t.created_at + timedelta(minutes=1))

    return render(request, 'teacher/available_time.html', {'available_times': available_times, 'hours': range(8, 18)})


@csrf_exempt
@login_required
def delete_available_time(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

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


@csrf_exempt
@login_required
def save_available_time(request):
    if not (request.user.is_teacher() or request.user.is_manager()):
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)

    date = request.POST.get('date')
    start_time = request.POST.get('start_time')
    end_time = request.POST.get('end_time')
    time_id = request.POST.get('id')

    try:
        teacher = request.user.teacher
    except Teacher.DoesNotExist:
        teacher = Teacher.objects.create(member_ptr=request.user)

    try:
        date_obj = datetime.strptime(date, '%Y-%m-%d').date()
        start_time_obj = datetime.strptime(start_time, '%H:%M').time()
        end_time_obj = datetime.strptime(end_time, '%H:%M').time()
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'message': 'ข้อมูลไม่ถูกต้อง'}, status=400)

    if end_time_obj <= start_time_obj:
        return JsonResponse({'success': False, 'message': 'เวลาไม่ถูกต้อง: เวลาสิ้นสุดต้องมากกว่าเวลาเริ่ม'}, status=400)

    now = timezone.localtime()
    start_dt = timezone.make_aware(datetime.combine(date_obj, start_time_obj))
    if start_dt < now:
        return JsonResponse({'success': False, 'message': 'ไม่สามารถบันทึกเวลาที่ย้อนอดีตได้'}, status=400)

    if time_id:
        try:
            available_time = AvailableTime.objects.get(id=time_id, teacher=teacher)
        except AvailableTime.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'ไม่พบรายการเวลาว่าง'}, status=404)

        available_time.date = date_obj
        available_time.start_time = start_time_obj
        available_time.end_time = end_time_obj
        available_time.save()
    else:
        overlap = (
            AvailableTime.objects.filter(teacher=teacher, date=date_obj)
            .filter(Q(start_time__lt=end_time_obj) & Q(end_time__gt=start_time_obj))
            .exists()
        )
        if overlap:
            return JsonResponse({'success': False, 'message': 'ช่วงเวลาซ้อนทับกับรายการเดิม'}, status=400)

        AvailableTime.objects.create(
            teacher=teacher, date=date_obj, start_time=start_time_obj, end_time=end_time_obj
        )

    return JsonResponse({'success': True, 'message': 'บันทึกเวลาสำเร็จ'})


# ----------------------------------------------------------------------------
# News
# ----------------------------------------------------------------------------

@login_required
def add_news(request):
    user = request.user
    if not (user.is_teacher() or user.is_manager()):
        messages.error(request, 'คุณไม่มีสิทธิ์เข้าถึงหน้านี้')
        return redirect('login')

    if request.method == 'POST':
        form = NewsForm(request.POST)
        if form.is_valid():
            news = form.save(commit=False)
            news.created_by = user
            news.save()
            messages.success(request, 'เพิ่มข่าวสารเรียบร้อยแล้ว!')
            send_news_notification(news)
            return redirect('teacher_news')
        else:
            messages.error(request, f'ข้อผิดพลาด: {form.errors}')
    else:
        form = NewsForm()

    return render(request, 'teacher/teacher_news.html', {'form': form, 'is_add_mode': True})



def send_news_notification(news):
    try:
        student_members = Member.objects.filter(role='student')
        recipient_list = [m.email for m in student_members if m.email]

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
                fail_silently=True,  # เปลี่ยนเป็น True เพื่อไม่ให้เกิด error
            )
            logger.info(f"Sent news notification to {len(recipient_list)} recipients")

    except Exception as e:
        logger.error(f"Error sending news notification: {e}")
        # ไม่ต้อง raise error เพื่อไม่ให้กระทบการทำงานหลัก

    
    current_date = timezone.now()
    two_days_ago = current_date - timedelta(days=2)
    News.objects.filter(created_at__lt=two_days_ago).delete()

# ----------------------------------------------------------------------------
# Scoring / Evaluation
# ----------------------------------------------------------------------------

@login_required
def assign_score(request):
    user = request.user
    if not (user.is_teacher() or user.is_manager()):
        return redirect('login')

    try:
        teacher = user.teacher
    except Teacher.DoesNotExist:
        teacher = Teacher.objects.create(member_ptr=user)
        teacher.save()

    related_projects = Project.objects.filter(Q(advisor=teacher) | Q(committee=teacher)).distinct()

    scored_project_ids = Score.objects.filter(teacher=teacher).values_list('project_id', flat=True)
    projects = related_projects.exclude(id__in=scored_project_ids).prefetch_related('students')

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

    return render(request, 'teacher/assign_score.html', {'projects': projects, 'form': form})


@login_required
def all_projects(request):
    selected_year = request.GET.get('year', '')
    projects = (
        Project.objects.all()
        .prefetch_related(
            Prefetch('students', queryset=Student.objects.all()),
            Prefetch('committee', queryset=Teacher.objects.all()),
            Prefetch('files', queryset=File.objects.all()),
        )
        .select_related('advisor')
        
    )

    if selected_year:
        projects = projects.filter(year=selected_year)

    project_data = []
    for project in projects:
        uploaded_files = []
        external_links = []
        for f in project.files.all():
            if f.file:
                uploaded_files.append({'name': os.path.basename(f.file.name), 'url': f.file.url})
            if f.url:
                from urllib.parse import urlparse

                domain = urlparse(f.url).netloc
                external_links.append({'url': f.url, 'domain': domain})
        a = project.appointment_set.last()
        if not a: d= timezone.now().date()
        else: d = a.date
        project_data.append(
            {
                'date': d,
                'project_id': project.id,
                'project_topic': project.topic,
                'student_ids': ", ".join([s.student_id for s in project.students.all() if s.student_id]),
                'student_names': ", ".join([s.get_full_name() for s in project.students.all()]),
                'year': project.year,
                'advisor': project.advisor.get_full_name(),
                'committee': ", ".join([t.get_full_name() for t in project.committee.all()]),
                'uploaded_files': uploaded_files,
                'external_links': external_links,
            }
        )

    years = Project.objects.values_list('year', flat=True).distinct().order_by('-year')

    return render(
        request,
        'manager/all_projects.html',
        {

            'project_data': project_data,
            'years': years,
            'selected_year': selected_year,
            'all_teachers': Teacher.objects.all(),
            
        },
    )



@login_required
def export_projects_csv(request):
    selected_year = request.GET.get('year', '')

    if selected_year:
        filename = f"projects_{selected_year}.csv"
        projects = Project.objects.filter(year=selected_year)
    else:
        filename = 'projects_all_years.csv'
        projects = Project.objects.all()

    response = HttpResponse(
        content_type='text/csv; charset=utf-8-sig',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
    writer = csv.writer(response, lineterminator='\n')

    # หัวตาราง
    writer.writerow([
        'วันที่นัดล่าสุด', 'หัวข้อโครงงาน', 'รหัสนักศึกษา', 'ชื่อนักศึกษา', 'ปี',
        'อาจารย์ที่ปรึกษา', 'กรรมการ', 'ไฟล์', 'ลิงก์'
    ])

    projects = projects.prefetch_related('students', 'committee', 'files', 'appointment_set').select_related('advisor')

    for project in projects:
        uploaded_files, external_links = [], []

        # ดึงวันที่ล่าสุดแบบง่ายๆ เหมือนใน all_projects
        a = project.appointment_set.last()
        if not a: 
            d = timezone.now().date()
        else: 
            d = a.date
        
        appt_date_str = d.strftime('%Y-%m-%d') if d else ''

        for f in project.files.all():
            # ไฟล์อัปโหลด
            if getattr(f, 'file', None) and hasattr(f.file, 'url'):
                file_name = os.path.basename(getattr(f.file, 'name', '') or '').replace('"', '”')
                absolute_url = request.build_absolute_uri(f.file.url)
                uploaded_files.append(f'=HYPERLINK("{absolute_url}","{file_name or "ไฟล์"}")')

            # ลิงก์ภายนอก
            url_raw = (getattr(f, 'url', '') or '').strip()
            if url_raw:
                url = url_raw
                parsed = urlparse(url)
                if not parsed.scheme:
                    url = 'https://' + url
                    parsed = urlparse(url)
                domain = (parsed.netloc or parsed.path.split('/')[0] or url).replace('"', '”')
                external_links.append(f'=HYPERLINK("{url}","{domain}")')

        student_ids = ", ".join([str(s.student_id) for s in project.students.all() if getattr(s, 'student_id', None)])
        student_names = ", ".join([s.get_full_name() for s in project.students.all()])
        advisor_name = getattr(project.advisor, 'get_full_name', lambda: '')() if getattr(project, 'advisor', None) else ''
        committee_names = ", ".join([t.get_full_name() for t in project.committee.all()])

        writer.writerow([
            appt_date_str,
            project.topic,
            student_ids,
            student_names,
            project.year,
            advisor_name,
            committee_names,
            "\n".join(uploaded_files) if uploaded_files else 'ไม่มีไฟล์',
            "\n".join(external_links) if external_links else 'ไม่มีลิงก์',
        ])

    return response

@login_required
def update_project_committee(request):
    if request.method != 'POST':
        return redirect('all_projects')

    project_id = request.POST.get('project_id')
    committee_ids = request.POST.getlist('committee')

    try:
        project = Project.objects.get(id=project_id)
        project.committee.clear()
        for tid in committee_ids:
            try:
                teacher = Teacher.objects.get(id=tid)
                project.committee.add(teacher)
            except Teacher.DoesNotExist:
                pass
        messages.success(request, 'อัปเดตกรรมการโครงงานเรียบร้อยแล้ว')
    except Project.DoesNotExist:
        messages.error(request, 'ไม่พบโครงงานที่ระบุ')

    redirect_url = reverse('all_projects')
    selected_year = request.GET.get('year')
    if selected_year:
        redirect_url += f'?year={selected_year}'

    return redirect(redirect_url)


@login_required
def get_project_committees(request, project_id):
    try:
        project = Project.objects.get(id=project_id)
        committee_ids = list(project.committee.values_list('id', flat=True))
        return JsonResponse({'committee_ids': committee_ids})
    except Project.DoesNotExist:
        return JsonResponse({'error': 'Project not found'}, status=404)


@login_required
def all_student_scores(request):
    if not request.user.is_manager():
        messages.error(request, 'คุณไม่มีสิทธิ์เข้าถึงหน้านี้')
        return redirect('login')

    selected_year = request.GET.get('year', '')

    projects = (
        Project.objects.all()
        .prefetch_related(
            Prefetch('students', queryset=Student.objects.all()),
            Prefetch('scores', queryset=Score.objects.select_related('teacher')),
        )
        .select_related('advisor')
    )

    if selected_year:
        projects = projects.filter(year=selected_year)

    project_data = []
    for project in projects:
        students = project.students.all()
        scores = project.scores.all()

        student_info = []
        for s in students:
            student_scores = scores.filter(student=s)
            avg_score = (
                student_scores.aggregate(Avg('score'))['score__avg'] if student_scores.exists() else None
            )
            evaluations = [
                {
                    'teacher': sc.teacher.get_full_name(),
                    'score': sc.score,
                    'grade': sc.grade,
                }
                for sc in student_scores
            ]
            student_info.append(
                {
                    'id': s.student_id,
                    'name': f"{s.first_name} {s.last_name}",
                    'average': round(avg_score, 2) if avg_score else '-',
                    'evaluations': evaluations,
                }
            )

        project_data.append(
            {
                'topic': project.topic,
                'year': project.year,
                'advisor': project.advisor.get_full_name(),
                'students': student_info,
            }
        )

    years = Project.objects.values_list('year', flat=True).distinct().order_by('-year')

    return render(
        request,
        'manager/all_student_scores.html',
        {'project_data': project_data, 'years': years, 'selected_year': selected_year},
    )


@login_required
def import_members(request):
    if request.user.role != 'manager':
        messages.error(request, 'คุณไม่มีสิทธิ์เข้าถึงหน้านี้')
        return redirect('manager_dashboard')

    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']
        selected_role = request.POST.get('selected_role', '').strip().lower()

        if selected_role not in ['student', 'teacher', 'manager']:
            messages.error(request, 'กรุณาเลือกบทบาทที่ต้องการก่อนนำเข้า')
            return redirect('import_members')

        try:
            df = pd.read_excel(excel_file)
            if 'email' not in df.columns:
                messages.error(request, 'ไฟล์ต้องมีคอลัมน์ชื่อ email เท่านั้น')
                return redirect('import_members')

            created_count = 0
            for _, row in df.iterrows():
                email = str(row['email']).strip().lower()
                if not email or Member.objects.filter(email=email).exists():
                    continue

                Member.objects.create_user(
                    username=email.split('@')[0],
                    email=email,
                    password='default12345',
                    role=selected_role,
                )
                created_count += 1

            messages.success(request, f'เพิ่มสมาชิกใหม่แล้ว {created_count} คน (บทบาท: {selected_role})')
            return redirect('import_members')
        except Exception as e:
            messages.error(request, f'เกิดข้อผิดพลาดในการนำเข้า: {e}')
            return redirect('import_members')

    return render(request, 'manager/import_members.html')


@login_required
def export_scores_csv(request):
    if not request.user.is_manager():
        messages.error(request, 'คุณไม่มีสิทธิ์เข้าถึงหน้านี้')
        return redirect('login')

    selected_year = request.GET.get('year', '')

    if selected_year:
        filename = f"คะแนนโครงงานนักศึกษา_ปีการศึกษา_{selected_year}.csv"
    else:
        filename = 'คะแนนโครงงานนักศึกษา_ทั้งหมด.csv'

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
        'ผู้ให้คะแนน',
    ]

    writer = csv.DictWriter(response, fieldnames=fieldnames)
    writer.writeheader()

    projects = (
        Project.objects.all()
        .prefetch_related(
            Prefetch('students', queryset=Student.objects.all()),
            Prefetch('scores', queryset=Score.objects.select_related('teacher')),
        )
        .select_related('advisor')
    )

    if selected_year:
        projects = projects.filter(year=selected_year)

    for project in projects:
        for student in project.students.all():
            student_scores = project.scores.filter(student=student)
            avg_score = (
                student_scores.aggregate(Avg('score'))['score__avg'] if student_scores.exists() else None
            )

            evaluations = []
            for score in student_scores:
                grade_text = ''
                if getattr(score, 'grade', None):
                    try:
                        grade_text = f" ({score.get_grade_display()})"
                    except Exception:
                        grade_text = f" ({score.grade})"
                evaluations.append(f"{score.teacher.get_full_name()}: {score.score}{grade_text}")

            student_id = f"'{student.student_id}" if student.student_id else ''

            writer.writerow(
                {
                    'ชื่อโครงงาน': project.topic,
                    'รหัสนักศึกษา': student_id,
                    'ชื่อนักศึกษา': f"{student.first_name} {student.last_name}",
                    'ปีการศึกษา': project.year,
                    'อาจารย์ที่ปรึกษา': project.advisor.get_full_name(),
                    'คะแนนเฉลี่ย': round(avg_score, 2) if avg_score is not None else '-',
                    'ผู้ให้คะแนน': ", ".join(evaluations) if evaluations else '-',
                }
            )

    return response
