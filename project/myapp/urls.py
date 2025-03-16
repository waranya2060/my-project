from django.urls import path
from .views import *

urlpatterns = [
    path('', login_view, name='login'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),

 # Dashboard
    path('student/dashboard/', student_dashboard, name='student_dashboard'),
    path('teacher/dashboard/', teacher_dashboard, name='teacher_dashboard'),
    path('manager/dashboard/', manager_dashboard, name='manager_dashboard'),
    path('manager/', manager_home, name='manager_home'),

  # ตรวจสอบเวลาว่างของอาจารย์ (แยกตาม role)
    path('student/check-time/', check_time, name='student_check_time'),
    path('teacher/check-time/', check_time, name='teacher_check_time'),
    path('manager/check-time/', check_time, name='manager_check_time'),
    path("my-appointments/", my_appointments, name="my_appointments"),
      # นัดหมาย (แยกตาม role)
    path('book-appointment/', book_appointment, name='book_appointment'),

    path('appointments/', teacher_appointments, name='teacher_appointments'),
    path('appointments/accept/<int:appointment_id>/', accept_appointment, name='accept_appointment'),
    path('appointments/reject/<int:appointment_id>/', reject_appointment, name='reject_appointment'),
    path('manager/appointment/', manager_appointment, name='manager_appointment'),

    path('student/upload-project/', upload_project, name='upload_project'),
    path('student/edit-project/<int:project_id>/', edit_project, name='edit_project'),
    path('delete_project/<int:project_id>/', delete_project, name='delete_project'),
    path('student/my-projects/', my_projects, name='my_projects'),
    path('student/my_point/', my_point, name='my_point'),
    path('student/edit-profile/', edit_profile, name='edit_profile'),
    path('teacher/available-time/', available_time, name='available_time'),
    path('save_available_time/', save_available_time, name='save_available_time'),
    path('delete-available-time/', delete_available_time, name='delete_available_time'),
    path('teacher/assign-score/', assign_score, name='assign_score'),
    path('teacher/add-news/', add_news, name='teacher_news'),  # สำหรับ teacher
    path('manager/add-news/', add_news, name='manager_news'),  # สำหรับ manager
    path('projects/', all_projects, name='all_projects'),
    path('projects/export-csv/', export_projects_csv, name='export_projects_csv'),
    path('projects/update-committee/', update_project_committee, name='update_project_committee'),
    path('api/projects/<int:project_id>/committees/', get_project_committees, name='get_project_committees'),
    path('manager/all-student-scores/', all_student_scores, name='all_student_scores'),
    path('manager/export-scores-csv/', export_scores_csv, name='export_scores_csv'),
    path('manager/all-projects/', all_projects, name='all_projects'),
    path('manager/export-projects-csv/',export_projects_csv, name='export_projects_csv'),
]
