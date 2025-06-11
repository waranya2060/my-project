from datetime import datetime
import hashlib
import re
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
import os
import pickle

def get_role_from_email(email):
    if not email:
        return None

    email = email.lower().strip()

    # อีเมลอาจารย์
    teacher_emails = [
        'wiw12waranya@gmail.com', 
        'win12waranya@gmail.com',
        # เพิ่มอีเมลอาจารย์อื่นๆ
    ]

    # อีเมลผู้ดูแล
    manager_emails = [
        'waranyaph30@gmail.com',
        # เพิ่มอีเมลผู้ดูแลอื่นๆ
    ]

    # รูปแบบอีเมลนักศึกษา
    student_patterns = [
        r'^[a-z]+\.[a-z]{2,3}\.\d{2}@ubu\.ac\.th$',
       
    ]

    # ตรวจสอบอีเมลอาจารย์
    if email in teacher_emails:
        return 2

    # ตรวจสอบอีเมลผู้ดูแล
    if email in manager_emails:
        return 3

    # ตรวจสอบอีเมลนักศึกษา
    if '@ubu.ac.th' in email:
        for pattern in student_patterns:
            if re.match(pattern, email):
                return 1
        return 3  # Default เป็นผู้ดูแลระบบ

    return None




SCOPES = ['https://www.googleapis.com/auth/calendar']

def authenticate_google():
    """Authenticate and return the Google Calendar API service."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('calendar', 'v3', credentials=creds)

def create_google_calendar_event(appointment, teacher_email):
    """
    สร้างกิจกรรมใน Google Calendar สำหรับการนัดหมาย
    
    Parameters:
    - appointment: ออบเจกต์ Appointment ที่มีข้อมูลการนัดหมาย
    - teacher_email: อีเมลของอาจารย์ที่จะเพิ่มกิจกรรมในปฏิทิน
    
    Returns:
    - event_id: ID ของกิจกรรมที่สร้างขึ้น หรือ None ถ้าสร้างไม่สำเร็จ
    """
    # กำหนด Scopes สำหรับ Google Calendar
    SCOPES = ['https://www.googleapis.com/auth/calendar']
    creds = None
    
    # สร้างชื่อไฟล์ token โดยใช้ MD5 hash ของอีเมลอาจารย์
    token_path = f'token_{hashlib.md5(teacher_email.encode()).hexdigest()}.pickle'
    
    # ตรวจสอบว่ามี token อยู่แล้วหรือไม่
    if os.path.exists(token_path):
        try:
            with open(token_path, 'rb') as token:
                creds = pickle.load(token)
        except Exception as e:
            print(f"เกิดข้อผิดพลาดในการโหลด token: {e}")
            return None
    
    # ตรวจสอบความถูกต้องของ token
    if not creds or not creds.valid:
        try:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # ถ้าไม่มี token หรือไม่สามารถรีเฟรชได้ ให้คืนค่า None
                print("ไม่พบ token หรือ token หมดอายุและไม่สามารถรีเฟรชได้")
                return None
        except Exception as e:
            print(f"เกิดข้อผิดพลาดในการรีเฟรช token: {e}")
            return None
    
    try:
        # สร้าง service ของ Google Calendar API
        service = build('calendar', 'v3', credentials=creds)
        
        # จัดเตรียมข้อมูลสำหรับสร้างกิจกรรม
        project = appointment.project
        student_names = ', '.join([s.get_full_name() for s in project.students.all()])
        committee_names = ', '.join([t.get_full_name() for t in project.committee.all()])
        
        # สร้างรายละเอียดกิจกรรม
        event = {
            'summary': f'การนัดหมายโครงงาน: {project.topic}',
            'location': appointment.location or 'ไม่ระบุสถานที่',
            'description': f"""
            โครงงาน: {project.topic}
            นักศึกษา: {student_names}
            อาจารย์ที่ปรึกษา: {project.advisor.get_full_name()}
            คณะกรรมการ: {committee_names}
            สถานที่: {appointment.location or 'ไม่ระบุ'}
            ลิงก์ประชุม: {appointment.meeting_link or 'ไม่มี'}
            """,
            'start': {
                'dateTime': datetime.combine(appointment.date, appointment.time_start).isoformat(),
                'timeZone': 'Asia/Bangkok',
            },
            'end': {
                'dateTime': datetime.combine(appointment.date, appointment.time_finish).isoformat(),
                'timeZone': 'Asia/Bangkok',
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 24 * 60},  # แจ้งเตือนล่วงหน้า 1 วัน
                    {'method': 'popup', 'minutes': 60},       # แจ้งเตือนล่วงหน้า 1 ชั่วโมง
                ],
            },
            'attendees': [
                {'email': teacher_email}
            ],
        }
        
        # เพิ่มอีเมลนักศึกษาเข้าไปใน attendees (ถ้ามี)
        for student in project.students.all():
            if student.email:
                event['attendees'].append({'email': student.email})
        
        # สร้างกิจกรรมใน Calendar
        event = service.events().insert(calendarId='primary', body=event, sendUpdates='all').execute()
        print(f'กิจกรรมถูกสร้างแล้ว: {event.get("htmlLink")}')
        
        return event.get('id')
    
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการสร้างกิจกรรม Google Calendar: {e}")
        return None

