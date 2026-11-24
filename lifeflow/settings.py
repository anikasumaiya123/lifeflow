import os
import sys
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env
load_dotenv(BASE_DIR / '.env')

IS_TESTING = 'test' in sys.argv or 'pytest' in sys.argv[0]

# DEBUG Mode
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 't')

# SECRET_KEY Configuration & Production Safety Check
SECRET_KEY = os.getenv('SECRET_KEY', '').strip()
DEFAULT_DEV_SECRET = 'django-insecure-lifeflow-bd-secret-key-change-in-production-2026'

if not SECRET_KEY or SECRET_KEY.startswith('django-insecure-'):
    if not DEBUG and not IS_TESTING:
        raise ImproperlyConfigured(
            "CRITICAL: A secure, unique SECRET_KEY environment variable must be set in production when DEBUG=False!"
        )
    SECRET_KEY = SECRET_KEY or DEFAULT_DEV_SECRET

# ALLOWED_HOSTS Configuration & Production Safety Check
RAW_HOSTS = os.getenv('ALLOWED_HOSTS', '').strip()
if RAW_HOSTS:
    ALLOWED_HOSTS = [h.strip() for h in RAW_HOSTS.split(',') if h.strip()]
elif DEBUG or IS_TESTING:
    ALLOWED_HOSTS = ['*']
else:
    raise ImproperlyConfigured(
        "CRITICAL: ALLOWED_HOSTS environment variable must be set to specific domain names when DEBUG=False!"
    )

# CSRF Trusted Origins
RAW_CSRF_ORIGINS = os.getenv('CSRF_TRUSTED_ORIGINS', '').strip()
if RAW_CSRF_ORIGINS:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in RAW_CSRF_ORIGINS.split(',') if o.strip()]

# PRODUCTION SECURITY HEADERS & COOKIE FLAGS
if not DEBUG and not IS_TESTING:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    
    # SSL / HTTPS Redirect & Proxy Header
    SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'True').lower() in ('true', '1', 't')
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    
    # Secure Cookies
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'True').lower() in ('true', '1', 't')
    CSRF_COOKIE_SECURE = os.getenv('CSRF_COOKIE_SECURE', 'True').lower() in ('true', '1', 't')
    
    # HTTP Strict Transport Security (HSTS)
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'True').lower() in ('true', '1', 't')
    SECURE_HSTS_PRELOAD = os.getenv('SECURE_HSTS_PRELOAD', 'True').lower() in ('true', '1', 't')
else:
    SECURE_BROWSER_XSS_FILTER = False
    SECURE_CONTENT_TYPE_NOSNIFF = False
    X_FRAME_OPTIONS = 'SAMEORIGIN'
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_HSTS_SECONDS = 0

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'donors.apps.DonorsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'lifeflow.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'donors.context_processors.user_profile',
            ],
        },
    },
]

WSGI_APPLICATION = 'lifeflow.wsgi.application'

# DATABASE CONFIGURATION (NeonDB PostgreSQL or Local SQLite fallback)
# Reads DATABASE_URL from .env file
DATABASE_URL_ENV = os.getenv('DATABASE_URL', '').strip()

if not DATABASE_URL_ENV or os.getenv('USE_LOCAL_DB', 'False').lower() in ('true', '1', 't'):
    DATABASE_URL_ENV = f"sqlite:///{BASE_DIR / 'db.sqlite3'}"

DATABASES = {
    'default': dj_database_url.config(
        default=DATABASE_URL_ENV,
        conn_max_age=0,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 6},
    },
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Dhaka'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'
