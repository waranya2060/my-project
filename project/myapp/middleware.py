from django.utils.cache import patch_cache_control
from django.shortcuts import redirect
from django.urls import reverse


class NoCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        patch_cache_control(response, no_cache=True, no_store=True, must_revalidate=True)
        return response

class LoginRequiredMiddleware:
    """
    Middleware บังคับให้ผู้ใช้ล็อกอินก่อนเข้าถึงทุกหน้า ยกเว้นหน้าล็อกอินและ OAuth URL
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # รายการ URL ที่ยกเว้น
        excluded_paths = [
            reverse('login'),  # หน้า Login
            reverse('logout'),  # หน้า Logout
            '/accounts/google/login/',  # Google OAuth Login
            '/accounts/google/login/callback/',  # Callback หลังจากยืนยัน Google OAuth
            '/accounts/login/',  # allauth login page
        ]
        
        # ตรวจสอบว่า URL ปัจจุบันอยู่ใน excluded_paths หรือไม่
        if not request.user.is_authenticated and not any(request.path.startswith(path) for path in excluded_paths):
            return redirect(reverse('login'))  # Redirect ไปหน้า login

        response = self.get_response(request)
        return response