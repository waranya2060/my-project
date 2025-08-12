from django.utils.cache import patch_cache_control
from django.shortcuts import redirect
from django.urls import resolve
import logging

class NoCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        patch_cache_control(response, no_cache=True, no_store=True, must_revalidate=True)
        return response


logger = logging.getLogger(__name__)

class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        allowed_names = [
            'login', 'logout', 'redirect_after_login',
            'google_calendar_callback',
        ]
        allowed_paths = [
            '/favicon.ico',
            '/accounts/google/login/',
            '/accounts/google/login/callback/',
            '/accounts/login/',
            '/favicon.ico',
        ]

        try:
            match = resolve(request.path)
            print(f"[MIDDLEWARE] path: {request.path} → resolved to: {match.url_name}")
            if match.url_name in allowed_names or request.path in allowed_paths:
                return self.get_response(request)
        except Exception as e:
            print(f"[MIDDLEWARE] Cannot resolve path: {request.path} — {e}")

        print(f"[MIDDLEWARE] User: {request.user} | Auth: {request.user.is_authenticated}")

        if not request.user.is_authenticated:
            print(f"[MIDDLEWARE] ❌ Unauthenticated — redirecting to login from {request.path}")
            return redirect('login')

        return self.get_response(request)