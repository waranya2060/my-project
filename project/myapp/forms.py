from django import forms
from .models import *


class EditProfileForm(forms.ModelForm):
    student_id = forms.CharField(
        label="รหัสนักศึกษา", 
        max_length=13, 
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = Student
        fields = ['student_id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # เพิ่มฟิลด์ display-only สำหรับชื่อจริงและนามสกุล
        self.fields['display_first_name'] = forms.CharField(
            label="ชื่อจริง",
            required=False,
            widget=forms.TextInput(attrs={
                'readonly': True,
                'class': 'form-control bg-light'
            })
        )
        
        self.fields['display_last_name'] = forms.CharField(
            label="นามสกุล",
            required=False,
            widget=forms.TextInput(attrs={
                'readonly': True,
                'class': 'form-control bg-light'
            })
        )
        
        # ตั้งค่าชื่อจาก User model
        if self.instance and hasattr(self.instance, 'member_ptr'):
            self.fields['display_first_name'].initial = self.instance.member_ptr.first_name
            self.fields['display_last_name'].initial = self.instance.member_ptr.last_name

class RejectAppointmentForm(forms.Form):
    rejection_reason = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4, 'class': 'w-full rounded-md border-gray-300'}),
        label="เหตุผลในการปฏิเสธ",
        required=True
    )

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
    students = forms.ModelMultipleChoiceField(
        queryset=Student.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'hidden-select'}),
        label='นักศึกษาในโครงงาน'
    )
    class Meta:
        model = Project
        fields = ['topic', 'year', 'advisor', 'students']
        widgets = {
            'topic': forms.TextInput(attrs={'class': 'w-full pl-10 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500', 'placeholder': 'กรอกหัวข้อโครงงาน'}),
            'year': forms.TextInput(attrs={'class': 'w-full pl-10 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500', 'placeholder': 'กรอกปี'}),
            'advisor': forms.Select(attrs={'class': 'w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make sure the queryset is correctly set
        self.fields['advisor'].queryset = Teacher.objects.all()
        
        # ให้ queryset ของ students แสดงเฉพาะนักศึกษา
        self.fields['students'].queryset = Student.objects.all()
        
        # This will ensure the names are displayed in the dropdown
        self.fields['advisor'].label_from_instance = lambda obj: f"{obj.first_name} {obj.last_name}"
        self.fields['students'].label_from_instance = lambda obj: f"{obj.student_id} - {obj.first_name} {obj.last_name}"

    def clean_students(self):
        """ตรวจสอบความถูกต้องของนักศึกษา"""
        students = self.cleaned_data.get('students', [])
        
        if len(students) > 5:
            raise forms.ValidationError("เลือกนักศึกษาได้ไม่เกิน 5 คน")
        
        # ตรวจสอบความซ้ำซ้อน
        if len(set(students)) != len(students):
            raise forms.ValidationError("มีนักศึกษาซ้ำกัน")
        
        return students

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
        widgets = {
            'score': forms.NumberInput(attrs={'min': 0, 'max': 100}),
            'comment': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        project_id = kwargs.pop('project_id', None)
        super().__init__(*args, **kwargs)
        
        if project_id:
            try:
                project = Project.objects.get(id=project_id)
                self.fields['project'].initial = project
                self.fields['project'].widget = forms.HiddenInput()
                self.fields['student'].queryset = project.students.all()
                self.fields['student'].label_from_instance = lambda obj: f"{obj.student_id} - {obj.get_full_name()}"
            except Project.DoesNotExist:
                pass