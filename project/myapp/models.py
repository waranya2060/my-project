
from django.conf import settings
from django.db import models
from django.contrib.auth.models import AbstractUser



class Member(AbstractUser):
    ROLE_CHOICES = [
        ('student',  'นักเรียน'),
        ('teacher',  'อาจารย์'),
        ('manager',  'อาจารย์ประจำวิชา'),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='student')

   
    def is_student(self):
        return self.role == 'student'

    def is_teacher(self):
        return self.role in 'teacher'

    def is_manager(self):
        return self.role == 'manager'


class Student(Member):
    student_id = models.CharField(max_length=13, unique=True, null=True, blank=True)

    def save(self, *args, **kwargs):
        self.role = 'student'
        super().save(*args, **kwargs)

    member_ptr = models.OneToOneField(
        Member, on_delete=models.CASCADE,
        related_name='student', parent_link=True
    )


class Teacher(Member):
    def save(self, *args, **kwargs):
        self.role = 'teacher'
        super().save(*args, **kwargs)

    member_ptr = models.OneToOneField(
        Member, on_delete=models.CASCADE,
        related_name='teacher', parent_link=True
    )

    def __str__(self):
        return f'{self.first_name} {self.last_name}'


class Manager(Member):
    def save(self, *args, **kwargs):
        self.role = 'manager'
        super().save(*args, **kwargs)


class News(models.Model):
    topic = models.CharField(max_length=255)
    detail = models.TextField()
    url = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    def get_author_name(self):
        return f"{self.created_by.first_name} {self.created_by.last_name}"


class Project(models.Model):
    topic = models.CharField(max_length=255)
    year = models.CharField(max_length=4)
    students = models.ManyToManyField(Student, related_name='projects')
    advisor = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='advised_projects')
    committee = models.ManyToManyField(Teacher, related_name='committee_projects')
    def add_student(self, student):
        """เพิ่มนักศึกษาเข้าโปรเจค"""
        if student not in self.students.all():
            self.students.add(student)
            return True
        return False

    def remove_student(self, student):
        """ลบนักศึกษาออกจากโปรเจค"""
        if student in self.students.all():
            self.students.remove(student)
            return True
        return False

class Appointment(models.Model):
    date = models.DateField()
    time_start = models.TimeField()
    time_finish = models.TimeField()
    url = models.URLField(blank=True, null=True)
    meeting_link = models.URLField(blank=True, null=True)
    location = models.CharField(max_length=255)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    students = models.ManyToManyField(Member)
    teachers = models.ManyToManyField(Teacher, related_name='teacher_appointments', blank=True)
    status = models.CharField(max_length=20, choices=[('pending', 'Pending'), ('accepted', 'Accepted'), ('rejected', 'Rejected')], default='pending')
    rejection_reason = models.TextField(blank=True, null=True) 
    accepted_teachers = models.TextField(blank=True, null=True) 
    def __str__(self):
        return f"Appointment for {self.project.topic} on {self.date} at {self.time_start}"
    
    
    
class AvailableTime(models.Model):
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    created_at = models.DateTimeField(auto_now_add=True)  

    def __str__(self):
        return f"{self.teacher.get_full_name()} - {self.date} {self.start_time} to {self.end_time}"

class File(models.Model):
    file = models.FileField(upload_to='uploads/files/', blank=True, null=True) 
    url = models.URLField(blank=True, null=True) 
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='files')

    def __str__(self):
        return f"File for {self.project.title}"


class Score(models.Model):
    project = models.ForeignKey('Project', on_delete=models.CASCADE, related_name='scores')
    student = models.ForeignKey('Student', on_delete=models.CASCADE)  # เปลี่ยนจาก ManyToManyField เป็น ForeignKey
    teacher = models.ForeignKey('Teacher', on_delete=models.CASCADE)  # อาจารย์ที่ให้คะแนน
    score = models.IntegerField()
    comment = models.TextField()
    grade = models.CharField(max_length=2, blank=True, null=True) 

    def __str__(self):
        return f"Score for {self.project.topic} - {self.student.get_full_name}"


