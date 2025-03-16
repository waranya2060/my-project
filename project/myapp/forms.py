from django import forms
from .models import *


class EditProfileForm(forms.ModelForm):
    first_name = forms.CharField(label="ชื่อจริง", max_length=100, required=True)
    last_name = forms.CharField(label="นามสกุล", max_length=100, required=True)
    student_id = forms.CharField(label="รหัสนักศึกษา", max_length=13, required=True)

    class Meta:
        model = Student
        fields = ['student_id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # ดึงข้อมูลจาก Member (superclass)
        if self.instance and self.instance.member_ptr:
            self.fields['first_name'].initial = self.instance.member_ptr.first_name
            self.fields['last_name'].initial = self.instance.member_ptr.last_name



class StudentProfileForm(forms.Form):
    """ ฟอร์มสำหรับแก้ไขข้อมูลโปรไฟล์นักศึกษา """
    student_id = forms.CharField(label="รหัสนักศึกษา", max_length=10, required=True)
    full_name = forms.CharField(label="ชื่อ-นามสกุล", max_length=100, required=True, disabled=True)
    email = forms.EmailField(label="อีเมล", required=True, disabled=True)

class AppointmentForm(forms.ModelForm):


    class Meta:
        model = Appointment
        fields = ['date', 'time_start', 'time_finish', 'project', 'students', 'location', 'meeting_link']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'required': True}),  # กำหนดให้ date ต้องกรอก
            'time_start': forms.TimeInput(attrs={'type': 'time'}),
            'time_finish': forms.TimeInput(attrs={'type': 'time'}),
            'location': forms.TextInput(attrs={'required': False}),
            'meeting_link': forms.URLInput(attrs={'required': False}),
        }

    def __init__(self, *args, **kwargs):
        student = kwargs.pop('student', None)  # รับ student จาก kwargs
        super().__init__(*args, **kwargs)

        # กำหนด queryset สำหรับฟิลด์ project
        if student:
            self.fields['project'].queryset = Project.objects.filter(students=student)

class ProjectForm(forms.ModelForm):
    committee = forms.ModelMultipleChoiceField(
        queryset=Teacher.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,  # ใช้ checkbox สำหรับเลือกกรรมการ
        label='Committee Members',
    )
    class Meta:
        model = Project
        fields = ['topic', 'year', 'advisor', 'committee']
        widgets = {
            'topic': forms.TextInput(attrs={'class': 'mt-1 p-3 w-full border rounded-md'}),
            'year': forms.TextInput(attrs={'class': 'mt-1 p-3 w-full border rounded-md'}),
            'advisor': forms.Select(attrs={'class': 'mt-1 p-3 w-full border rounded-md'}),
          
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make sure the queryset for both fields is correctly set
        self.fields['advisor'].queryset = Teacher.objects.all()  # Set the queryset for advisor field
        self.fields['committee'].queryset = Teacher.objects.all()  # Set the queryset for committee field
        self.fields['committee'].required = False  # Committee members are optional

        # This will ensure the names are displayed in the dropdown and checkboxes
        self.fields['advisor'].label_from_instance = lambda obj: f"{obj.first_name} {obj.last_name}"
        self.fields['committee'].label_from_instance = lambda obj: f"{obj.first_name} {obj.last_name}"

        
class FileForm(forms.ModelForm):
    class Meta:
        model = File
        fields = ['file', 'url']
        widgets = {
            'file': forms.ClearableFileInput(attrs={'class': 'mt-1 p-3 w-full border rounded-md'}),
            'url': forms.URLInput(attrs={'class': 'mt-1 p-3 w-full border rounded-md'}),
        }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make 'url' field optional
        self.fields['url'].required = False

class NewsForm(forms.ModelForm):
    """ ฟอร์มสำหรับอาจารย์เพิ่มข่าวสาร """
    class Meta:
        model = News
        fields = ['topic', 'detail', 'url']  # ใช้เฉพาะฟิลด์ที่มีในโมเดล
        widgets = {
            'topic': forms.TextInput(attrs={'class': 'p-2 border rounded-md w-full'}),
            'detail': forms.Textarea(attrs={'class': 'p-2 border rounded-md w-full'}),
            'url': forms.URLInput(attrs={'placeholder': 'ใส่ลิงก์ข่าวสาร (ถ้ามี)', 'class': 'p-2 border rounded-md w-full'}),
        }
        # กำหนด url ให้เป็นไม่บังคับกรอกใน Meta
        url = forms.URLField(required=False, widget=forms.URLInput(attrs={'placeholder': 'ใส่ลิงก์ข่าวสาร (ถ้ามี)', 'class': 'p-2 border rounded-md w-full'}))


class AvailableTimeForm(forms.ModelForm):
    """ ฟอร์มสำหรับจัดการเวลาว่างของอาจารย์ """
    teacher = forms.ModelChoiceField(
        queryset=Teacher.objects.all(),
        widget=forms.Select(attrs={'class': 'p-2 border rounded-md w-full'})
    )

    class Meta:
        model = AvailableTime
        fields = ['date', 'start_time', 'end_time', 'teacher']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'p-2 border rounded-md w-full'}),
            'start_time': forms.TimeInput(attrs={'type': 'time', 'class': 'p-2 border rounded-md w-full'}),
            'end_time': forms.TimeInput(attrs={'type': 'time', 'class': 'p-2 border rounded-md w-full'}),
        }

class ScoreForm(forms.ModelForm):
    class Meta:
        model = Score
        fields = ['project', 'student', 'score', 'comment']
        
    project = forms.ModelChoiceField(queryset=Project.objects.all(), label="เลือกโปรเจค")
    student = forms.ModelChoiceField(queryset=Student.objects.all(), label="เลือกนักศึกษา")