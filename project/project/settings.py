

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "django-insecure-f_bq%r)blwdeteq(%m$6*m14$yx4ids-bg1v$$^z=uzv&%k^g&"

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    'tailwind',
    'theme',
    'django.contrib.sites', 
    'allauth',
    'allauth.account',  # สำหรับบัญชีผู้ใช้
    'allauth.socialaccount',  # สำหรับการเข้าสู่ระบบ
    'allauth.socialaccount.providers.google',  # สำหรับเข้าสู่ระบบผ่าน Google
    'myapp.apps.MyappConfig', 
    'django_extensions', 
    'social_django',
    'widget_tweaks',

    
]
TAILWIND_APP_NAME = 'theme'
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    
    "django.contrib.auth.middleware.AuthenticationMiddleware",  # ✅ ต้องมาก่อน
    "allauth.account.middleware.AccountMiddleware",              # ✅ อันนี้ก็ตาม
    "myapp.middleware.LoginRequiredMiddleware",                  # ✅ แล้วค่อย Middleware ของคุณ
    
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / 'theme' / 'templates'],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]



WSGI_APPLICATION = "project.wsgi.application"

STATIC_URL = '/static/'

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'theme', 'static'),  # เส้นทางที่ไฟล์ CSS อยู่
]
# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql', 
        'NAME': 'myweb',
        'USER': 'root',
        'PASSWORD': 'Wiw30122546',
        'HOST': 'localhost',
        'PORT': '3306',
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

AUTHENTICATION_BACKENDS = (
    'allauth.account.auth_backends.AuthenticationBackend',
    'django.contrib.auth.backends.ModelBackend',
    'social_core.backends.google.GoogleOAuth2',
      
)

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['email', 'profile'],
        'AUTH_PARAMS': {
            'access_type': 'online',
            'prompt': 'select_account',   # ✅ เพิ่มบรรทัดนี้
        },
        'OAUTH_PKCE_ENABLED': True,
    }
}
SOCIALACCOUNT_LOGIN_ON_GET = True  

# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = "en-us"


USE_I18N = True

USE_TZ = True

SITE_ID = 2
# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/

STATIC_URL = "static/"

# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field
MEDIA_URL = '/uploads/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'uploads')
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "myapp.Member"  
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'  # ใช้ใน local development
SOCIAL_AUTH_GOOGLE_CLIENT_ID = '841831766925-di1tbo665fs3o930i27026ih1bc0osqq.apps.googleusercontent.com'
SOCIAL_AUTH_GOOGLE_SECRET = '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'
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'  # ใช้ backend SMTP ในการส่งอีเมล
EMAIL_HOST = 'smtp.gmail.com'  # ใช้ Gmail SMTP server
EMAIL_PORT = 587  # Port 587 ใช้สำหรับการเชื่อมต่อแบบ TLS
EMAIL_USE_TLS = True  # เปิดใช้งานการเชื่อมต่อแบบ TLS (ความปลอดภัย)
EMAIL_HOST_USER = 'appointmentx9@gmail.com'  # ใช้อีเมลของคุณในการส่ง
EMAIL_HOST_PASSWORD = 'uvzx ejpp qaih jyhp'  # รหัสผ่านของอีเมลของคุณ
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER  # กำหนดค่าให้เป็นอีเมลเดียวกันกับที่ใช้ส่ง
LOGIN_REDIRECT_URL = '/redirect-after-login/'
LOGOUT_REDIRECT_URL = '/login/'
SOCIALACCOUNT_AUTO_SIGNUP = True
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
ALLOWED_HOSTS = ['*']  
# เพิ่ม/แก้ไขการตั้งค่าเหล่านี้
SESSION_COOKIE_NAME = 'myapp_session'
SESSION_COOKIE_AGE = 86400  # 1 วัน (หน่วยวินาที)
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True
USE_I18N = True
USE_L10N = True
LANGUAGE_CODE = 'th'  # หรือ 'th-th'
TIME_ZONE = 'Asia/Bangkok'
SESSION_ENGINE = "django.contrib.sessions.backends.db"