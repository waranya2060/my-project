import re
from django.core.mail import send_mail
from django.conf import settings

def send_email_notification(subject, message, recipient_list):
    """ ส่งอีเมลแจ้งเตือน """
    send_mail(
        subject,
        message,
        settings.EMAIL_HOST_USER,  # อีเมลผู้ส่ง
        recipient_list,  # รายการอีเมลผู้รับ
        fail_silently=False,
    )


def get_role_from_email(email):
    if not email:
        return None  # If no email is provided, return None
    
    # List of specific emails for Teachers and Managers
    allowed_teacher_emails = [
        'wiw12waranya@gmail.com',  # Add this email to be considered a teacher
    ]
    allowed_manager_emails = [
        'waranyaph30@gmail.com',  # Email for manager
    ]
    
    # Regex pattern for students
    student_pattern = r'^[A-Za-z]+\.[A-Za-z]{2,3}\.\d{2}@ubu\.ac\.th$'

    # Check if email matches allowed teacher emails
    if email.lower() in allowed_teacher_emails:
        print("Email matches teacher list")
        return 2  # Teacher
    
    # Check if email matches student pattern
    elif re.match(student_pattern, email):
        return 1  # Student
    
    # Check if email matches allowed manager emails
    elif email.lower() in allowed_manager_emails:
        return 3  # Manager
    
    # If email doesn't match any of the allowed categories
    else:
        return None  # No role found for this email
    

import os
import random
import string
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


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

def generate_meeting_link(start_time, end_time, summary="Meeting"):
    """Generate a Google Meet link by creating a calendar event."""
    try:
        service = authenticate_google()

        event = {
            'summary': summary,
            'start': {
                'dateTime': start_time,
                'timeZone': 'Asia/Bangkok',
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'Asia/Bangkok',
            },
            'conferenceData': {
                'createRequest': {
                    'requestId': ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(10)),
                    'conferenceSolutionKey': {
                        'type': 'hangoutsMeet'
                    }
                }
            }
        }

        # Try creating the event
        event = service.events().insert(calendarId='primary', body=event, conferenceDataVersion=1).execute()

        # Debugging the response
        print(f"Event created: {event}")

        # Returning the Google Meet link
        return event.get('hangoutLink')
    except Exception as e:
        print(f"Error generating meeting link: {e}")
        return None