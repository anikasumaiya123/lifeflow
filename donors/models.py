import math
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

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
    blood_group = models.CharField(max_length=5, choices=BLOOD_GROUP_CHOICES, default='O+', blank=True)
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
        """Returns the latest completed donation for this user."""
        return DonationHistory.objects.filter(donor=self.user, status='completed').order_by('-donation_date').first()

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
    created_at = models.DateTimeField(auto_now_add=True)

    objects = DonationHistoryManager()

    class Meta:
        verbose_name = "Donation History"
        verbose_name_plural = "Donation Histories"
        ordering = ['-donation_date']

    def __str__(self):
        return f"{self.donor.username} - {self.location_hospital} ({self.donation_date})"

class BloodRequest(models.Model):
    seeker = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blood_requests')
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

    def __str__(self):
        return f"{self.patient_name} ({self.blood_group}) - {self.hospital_name} [{self.get_status_display()}]"

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
    ('accepted', 'Accepted by Seeker'),
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

    def __str__(self):
        return f"{self.donor.username} -> Request #{self.request.id} ({self.status})"


