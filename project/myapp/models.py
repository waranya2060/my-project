
from django.db import models
from django.contrib.auth.models import AbstractUser



class Member(AbstractUser):
    role = models.IntegerField(default=1)  # Add default role as 1 for students or another as needed.
    
    def is_student(self):
        return self.role == 1
    
    def is_teacher(self):
        return self.role in [2, 3]
    
    def is_manager(self):
        return self.role == 3

    
class Student(Member):
    student_id = models.CharField(max_length=13, unique=True, null=True, blank=True)
    def save(self, *args, **kwargs):
        self.role = 1  # นักศึกษา
        super().save(*args, **kwargs)
    member_ptr = models.OneToOneField(Member, on_delete=models.CASCADE, related_name="student", parent_link=True)

class Teacher(Member):
    def save(self, *args, **kwargs):
        self.role = 2  # อาจารย์
        super().save(*args, **kwargs)

    member_ptr = models.OneToOneField(Member, on_delete=models.CASCADE, related_name="teacher", parent_link=True)
    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    
class Manager(Member):
     def save(self, *args, **kwargs):
        self.role = 3  # อาจารย์
        super().save(*args, **kwargs)

class News(models.Model):
    topic = models.CharField(max_length=255)
    detail = models.TextField()
    url = models.URLField(blank=True, null=True) 
    created_at = models.DateTimeField(auto_now_add=True)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)


class Project(models.Model):
    topic = models.CharField(max_length=255)
    year = models.CharField(max_length=4)
    students = models.ManyToManyField(Student)
    advisor = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='advised_projects')
    committee = models.ManyToManyField(Teacher, related_name='committee_projects')

class Appointment(models.Model):
    date = models.DateField()
    time_start = models.TimeField()
    time_finish = models.TimeField()
    url = models.URLField(blank=True, null=True)
    meeting_link = models.URLField(blank=True, null=True)
    location = models.CharField(max_length=255)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    students = models.ManyToManyField(Member)
    status = models.CharField(max_length=20, choices=[('pending', 'Pending'), ('accepted', 'Accepted'), ('rejected', 'Rejected')], default='pending')

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

    def __str__(self):
        return f"Score for {self.project.topic} - {self.student.get_full_name}"