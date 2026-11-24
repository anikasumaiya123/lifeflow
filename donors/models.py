import math
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from django.core.exceptions import ValidationError

ROLE_CHOICES = [
    ('donor', 'Blood Donor (Individual)'),
    ('seeker', 'Blood Seeker (Patient / Family)'),
    ('hospital', 'Hospital / Medical Center'),
]

BLOOD_GROUP_CHOICES = [
    ('A+', 'A+'),
    ('A-', 'A-'),
    ('B+', 'B+'),
    ('B-', 'B-'),
    ('O+', 'O+'),
    ('O-', 'O-'),
    ('AB+', 'AB+'),
    ('AB-', 'AB-'),
]

BLOOD_COMPATIBILITY = {
    'O-': {'O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+'},
    'O+': {'O+', 'A+', 'B+', 'AB+'},
    'A-': {'A-', 'A+', 'AB-', 'AB+'},
    'A+': {'A+', 'AB+'},
    'B-': {'B-', 'B+', 'AB-', 'AB+'},
    'B+': {'B+', 'AB+'},
    'AB-': {'AB-', 'AB+'},
    'AB+': {'AB+'},
}

COMPATIBLE_DONOR_GROUPS = {}
for _donor_bg, _recipient_bgs in BLOOD_COMPATIBILITY.items():
    for _rec_bg in _recipient_bgs:
        COMPATIBLE_DONOR_GROUPS.setdefault(_rec_bg, set()).add(_donor_bg)

def is_blood_compatible(donor_group, recipient_group):
    """Returns True if donor_group can donate to recipient_group."""
    if not donor_group or not recipient_group:
        return False
    return recipient_group in BLOOD_COMPATIBILITY.get(donor_group, set())

def get_compatible_donor_groups(recipient_group):
    """Returns set of donor blood groups that can donate to recipient_group."""
    if not recipient_group:
        return set()
    return COMPATIBLE_DONOR_GROUPS.get(recipient_group, set())

def calculate_donor_suitability_score(donor_profile, recipient_bg=None, distance_km=None):
    """
    Calculates a 0-100 AI Donor Suitability Score based on 5 weighted criteria:
    1. Compatibility       - Max 40 points
    2. Availability        - Max 25 points
    3. Distance            - Max 20 points
    4. Eligibility         - Max 10 points
    5. Location Freshness  - Max 5 points
    --------------------------------------
    Total                  - Max 100 points
    Returns dict with score, label, color, and list of bullet explanations.
    """
    score = 0
    reasons = []

    # 1. Compatibility (Max 40 pts) - Absolute Medical Disqualifier
    donor_bg = getattr(donor_profile, 'blood_group', '')
    if recipient_bg:
        if not is_blood_compatible(donor_bg, recipient_bg):
            return {
                'score': 0,
                'label': 'Incompatible Blood Group',
                'color': '#EF4444',
                'badge_bg': '#FEF2F2',
                'badge_color': '#B91C1C',
                'reasons': [f"Incompatible blood group ({donor_bg} cannot donate to {recipient_bg})"],
                'display_text': f"0/100 — Incompatible ({donor_bg} → {recipient_bg})"
            }
        if donor_bg == recipient_bg:
            score += 40
            reasons.append(f"Compatible exact match ({donor_bg})")
        else:
            score += 30
            reasons.append(f"Compatible donor ({donor_bg} for {recipient_bg})")
    else:
        score += 35
        reasons.append(f"Verified blood group ({donor_bg})")

    # 2. Availability (Max 25 pts)
    is_avail = getattr(donor_profile, 'emergency_available', False)
    if is_avail:
        score += 25
        reasons.append("Available now")
    else:
        reasons.append("Currently unavailable")

    # 3. Distance (Max 20 pts)
    if distance_km is not None:
        try:
            d_val = float(distance_km)
            if d_val <= 5.0:
                score += 20
                reasons.append(f"{d_val:.1f} km away")
            elif d_val <= 15.0:
                score += 15
                reasons.append(f"{d_val:.1f} km away")
            elif d_val <= 30.0:
                score += 10
                reasons.append(f"{d_val:.1f} km away")
            else:
                score += 5
                reasons.append(f"{d_val:.1f} km away")
        except (ValueError, TypeError):
            score += 10
            reasons.append("Nearby location match")
    else:
        score += 10
        reasons.append("District location match")

    # 4. Eligibility (Max 10 pts)
    recently_donated = getattr(donor_profile, 'is_recently_donated', False)
    if not recently_donated:
        score += 10
        reasons.append("Eligible based on recorded donation history")
    else:
        score += 3
        reasons.append("Recent donation recorded within 90 days")

    # 5. Location Freshness (Max 5 pts)
    last_update = getattr(donor_profile, 'last_location_update', None)
    if last_update:
        diff_seconds = (timezone.now() - last_update).total_seconds()
        diff_hours = max(0, diff_seconds / 3600.0)
        if diff_hours <= 24:
            score += 5
            if diff_hours < 1:
                reasons.append("Location updated less than an hour ago")
            else:
                reasons.append(f"Location updated {int(diff_hours)} hours ago")
        elif diff_hours <= 168:
            score += 3
            reasons.append(f"Location updated {int(diff_hours / 24)} days ago")
        else:
            score += 1
            reasons.append("Location profile on record")
    else:
        score += 2
        reasons.append("Location profile recorded")

    score = min(100, max(0, score))

    if score >= 85:
        label = "Highly Suitable"
        badge_color = "#10B981"
        badge_bg = "rgba(16, 185, 129, 0.2)"
    elif score >= 65:
        label = "Suitable"
        badge_color = "#3B82F6"
        badge_bg = "rgba(59, 130, 246, 0.2)"
    elif score >= 40:
        label = "Moderately Suitable"
        badge_color = "#F59E0B"
        badge_bg = "rgba(245, 158, 11, 0.2)"
    else:
        label = "Low Match"
        badge_color = "#9CA3AF"
        badge_bg = "rgba(156, 163, 175, 0.2)"

    return {
        'score': score,
        'label': label,
        'badge_color': badge_color,
        'badge_bg': badge_bg,
        'reasons': reasons,
        'display_text': f"{score}/100 — {label}"
    }

STATUS_CHOICES = [
    ('completed', 'Completed'),
    ('scheduled', 'Scheduled'),
    ('cancelled', 'Cancelled'),
]

URGENCY_CHOICES = [
    ('immediate', 'Immediate / Emergency'),
    ('24h', 'Within 24 Hours'),
    ('3d', 'Within 3 Days'),
]

REQUEST_STATUS_CHOICES = [
    ('active', 'Active Request'),
    ('fulfilled', 'Fulfilled'),
    ('cancelled', 'Cancelled'),
    ('expired', 'Expired'),
]

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculates the great circle distance between two points on the Earth in kilometers."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    try:
        R = 6371.0  # Radius of Earth in km
        dlat = math.radians(float(lat2) - float(lat1))
        dlon = math.radians(float(lon2) - float(lon1))
        a = (math.sin(dlat / 2.0) ** 2 +
             math.cos(math.radians(float(lat1))) * math.cos(math.radians(float(lat2))) * (math.sin(dlon / 2.0) ** 2))
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return round(R * c, 2)
    except (ValueError, TypeError):
        return None

def get_user_full_name(user):
    """Safely return user full name or fallback to username."""
    if not user:
        return ""
    return user.get_full_name() or user.username

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='donor')
    phone_number = models.CharField(max_length=25, blank=True)
    division = models.CharField(max_length=50, blank=True)
    district = models.CharField(max_length=100, blank=True)
    blood_group = models.CharField(max_length=5, choices=BLOOD_GROUP_CHOICES, default='', blank=True)
    emergency_available = models.BooleanField(default=True, help_text="Available for emergency blood requests")
    is_approved = models.BooleanField(default=False, help_text="Approved by administrator before login is permitted")
    
    # Geolocation fields
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    last_location_update = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{get_user_full_name(self.user)} ({self.get_role_display()}) - {'Approved' if self.is_approved else 'Pending Approval'}"

    @property
    def is_available(self):
        return self.emergency_available

    @property
    def has_shared_location(self):
        return self.latitude is not None and self.longitude is not None

    def get_last_donation(self):
        """Returns the latest completed donation for this user on or before today."""
        today = timezone.now().date()
        return DonationHistory.objects.filter(
            donor=self.user,
            status='completed',
            donation_date__lte=today
        ).order_by('-donation_date').first()

    @property
    def is_recently_donated(self):
        """True if the donor donated blood within the standard 90-day waiting period."""
        last_donation = self.get_last_donation()
        if not last_donation or not last_donation.donation_date:
            return False
        today = timezone.now().date()
        don_date = last_donation.donation_date
        if hasattr(don_date, 'date') and callable(getattr(don_date, 'date')):
            don_date = don_date.date()
        return (today - don_date).days < 90

    @property
    def next_regular_due_date(self):
        """Calculates standard 90-day next eligible date after last donation."""
        last_donation = self.get_last_donation()
        if not last_donation or not last_donation.donation_date:
            return None
        don_date = last_donation.donation_date
        if hasattr(don_date, 'date') and callable(getattr(don_date, 'date')):
            don_date = don_date.date()
        return don_date + timedelta(days=90)

    @property
    def recent_donation_info(self):
        """Returns dictionary containing recent donation date, due date, and display message for seekers."""
        last_donation = self.get_last_donation()
        if not last_donation or not self.is_recently_donated:
            return {
                'recently_donated': False,
                'donation_date': None,
                'due_date': None,
                'days_remaining': 0,
                'message': ''
            }

        due_date = self.next_regular_due_date
        today = timezone.now().date()
        don_date = last_donation.donation_date
        if hasattr(don_date, 'date') and callable(getattr(don_date, 'date')):
            don_date = don_date.date()

        days_remaining = (due_date - today).days if due_date else 0

        return {
            'recently_donated': True,
            'donation_date': don_date,
            'due_date': due_date,
            'days_remaining': days_remaining,
            'message': f"Donor already donated blood on {don_date.strftime('%b %d, %Y')}. Regular next due date is {due_date.strftime('%b %d, %Y')}."
        }

class DonationHistoryQuerySet(models.QuerySet):
    def last_6_months(self, user=None):
        """Returns completed or recorded donations within the last 180 days (6 months)."""
        six_months_ago = timezone.now().date() - timedelta(days=180)
        qs = self.filter(donation_date__gte=six_months_ago)
        if user is not None:
            qs = qs.filter(donor=user)
        return qs.order_by('-donation_date')

class DonationHistoryManager(models.Manager):
    def get_queryset(self):
        return DonationHistoryQuerySet(self.model, using=self._db)

    def last_6_months(self, user=None):
        return self.get_queryset().last_6_months(user)

class DonationHistory(models.Model):
    donor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='donations')
    donation_date = models.DateField(default=timezone.now)
    location_hospital = models.CharField(max_length=255, help_text="Hospital or clinic name")
    recipient_name = models.CharField(max_length=150, blank=True, help_text="Patient or recipient name")
    units_donated = models.PositiveIntegerField(default=1, help_text="Bags / Units of blood donated")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='completed')
    notes = models.TextField(blank=True)
    verification_id = models.CharField(max_length=50, blank=True, null=True, unique=True, help_text="Unique Verification Certificate ID")
    verified_by_hospital = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_donations', help_text="Hospital user account that verified this donation")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = DonationHistoryManager()

    class Meta:
        verbose_name = "Donation History"
        verbose_name_plural = "Donation Histories"
        ordering = ['-donation_date']

    def clean(self):
        super().clean()
        if self.donation_date:
            don_date = self.donation_date
            if hasattr(don_date, 'date') and callable(getattr(don_date, 'date')):
                don_date = don_date.date()
            if don_date > timezone.now().date():
                raise ValidationError({'donation_date': "Donation date cannot be in the future."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.donor.username} - {self.location_hospital} ({self.donation_date})"

class BloodRequest(models.Model):
    seeker = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blood_requests')
    target_donor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='targeted_blood_requests', help_text="Specific donor or hospital requested directly by seeker")
    patient_name = models.CharField(max_length=150)
    blood_group = models.CharField(max_length=5, choices=BLOOD_GROUP_CHOICES)
    units_required = models.PositiveIntegerField(default=1)
    hospital_name = models.CharField(max_length=255)
    division = models.CharField(max_length=50)
    district = models.CharField(max_length=100)
    urgency = models.CharField(max_length=20, choices=URGENCY_CHOICES, default='immediate')
    contact_phone = models.CharField(max_length=25)
    notes = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=20, choices=REQUEST_STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Blood Request"
        verbose_name_plural = "Blood Requests"
        ordering = ['-created_at']

    @property
    def is_expired(self):
        """Returns True if the request exceeds its urgency time limit."""
        if self.status != 'active':
            return self.status == 'expired'
        now = timezone.now()
        created = self.created_at
        if not created:
            return False
        limit_hours = 24 if self.urgency in ('immediate', '24h') else (72 if self.urgency == '3d' else 48)
        return (now - created).total_seconds() > (limit_hours * 3600)

    @property
    def clean_patient_name(self):
        """Returns patient name stripped of redundant trailing blood group in parentheses."""
        name = (self.patient_name or "").strip()
        if '(' in name and name.endswith(')'):
            bg_suffix = f"({self.blood_group})"
            if name.endswith(bg_suffix):
                return name[:-len(bg_suffix)].strip()
        return name

    def __str__(self):
        return f"{self.clean_patient_name} ({self.blood_group}) - {self.hospital_name} [{self.get_status_display()}]"

class HospitalInventory(models.Model):
    hospital = models.ForeignKey(User, on_delete=models.CASCADE, related_name='hospital_inventories')
    blood_group = models.CharField(max_length=5, choices=BLOOD_GROUP_CHOICES)
    units = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hospital Inventory"
        verbose_name_plural = "Hospital Inventories"
        unique_together = ('hospital', 'blood_group')

    def __str__(self):
        return f"{self.hospital.username} - {self.blood_group}: {self.units} units"

RESPONSE_STATUS_CHOICES = [
    ('pending', 'Pending Response'),
    ('accepted', 'Accepted by Donor'),
    ('declined', 'Declined'),
]

class BloodRequestResponse(models.Model):
    request = models.ForeignKey(BloodRequest, on_delete=models.CASCADE, related_name='responses')
    donor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blood_request_responses')
    status = models.CharField(max_length=20, choices=RESPONSE_STATUS_CHOICES, default='pending')
    donor_message = models.TextField(blank=True, help_text="Message or availability note from donor")
    has_recent_donation = models.BooleanField(default=False)
    recent_donation_date = models.DateField(null=True, blank=True)
    next_due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Blood Request Response"
        verbose_name_plural = "Blood Request Responses"
        ordering = ['-created_at']
        unique_together = ('request', 'donor')

    @property
    def is_hospital(self):
        try:
            return hasattr(self.donor, 'profile') and self.donor.profile and self.donor.profile.role == 'hospital'
        except Exception:
            return False

    @property
    def donor_phone(self):
        try:
            return self.donor.profile.phone_number if (hasattr(self.donor, 'profile') and self.donor.profile) else ''
        except Exception:
            return ''

    def __str__(self):
        return f"{self.donor.username} -> Request #{self.request.id} ({self.status})"

def auto_expire_old_requests():
    """Automatically updates status of outdated active requests to 'expired' and purges old/obsolete notifications."""
    now = timezone.now()
    limit_24h = now - timedelta(hours=24)
    # Mark any active request older than 24h as expired
    BloodRequest.objects.filter(status='active', created_at__lt=limit_24h).update(status='expired')
    # Purge notifications for expired, cancelled, or deleted requests, or notifications older than 24h
    Notification.objects.filter(
        models.Q(related_request__status__in=['expired', 'cancelled']) |
        models.Q(related_request__isnull=True) |
        models.Q(created_at__lt=limit_24h)
    ).delete()

NOTIFICATION_TYPES = [
    ('emergency_request', 'Emergency Blood Request'),
    ('response_received', 'Request Response Received'),
    ('stock_supplied', 'Hospital Stock Supplied'),
    ('direct_request', 'Direct Request Received'),
    ('status_update', 'Request Status Update'),
]

class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES, default='emergency_request')
    related_request = models.ForeignKey(BloodRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')
    link = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.recipient.username} - [{self.get_notification_type_display()}] {self.title}"



