from .models import UserProfile, Notification, auto_expire_old_requests
from django.utils import timezone
from datetime import timedelta
from django.db import models

def user_profile(request):
    """Context processor to safely expose user profile & active notifications in all templates."""
    if hasattr(request, 'user') and request.user.is_authenticated:
        try:
            profile = getattr(request.user, 'profile', None)
            auto_expire_old_requests()

            user_notifs = Notification.objects.filter(
                recipient=request.user
            ).select_related('sender', 'related_request').order_by('-created_at')[:30]
            unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()

            return {
                'profile': profile,
                'user_notifications': user_notifs,
                'unread_notifications_count': unread_count
            }
        except Exception:
            pass
    return {'profile': None, 'user_notifications': [], 'unread_notifications_count': 0}

