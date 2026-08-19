from django import forms
from django.contrib.auth.models import User
from .models import UserProfile, DonationHistory, BloodRequest, ROLE_CHOICES, BLOOD_GROUP_CHOICES, URGENCY_CHOICES
from django.utils import timezone

DIVISION_CHOICES = [
    ('', 'Select Division'),
    ('Dhaka', 'Dhaka'),
    ('Chattogram', 'Chattogram'),
    ('Sylhet', 'Sylhet'),
    ('Rajshahi', 'Rajshahi'),
    ('Khulna', 'Khulna'),
    ('Barishal', 'Barishal'),
    ('Rangpur', 'Rangpur'),
    ('Mymensingh', 'Mymensingh'),
]

class UserRegistrationForm(forms.ModelForm):
    full_name = forms.CharField(max_length=150, required=True, widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': 'Enter your full name'
    }))
    phone_number = forms.CharField(max_length=25, required=True, widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': '+880 1712-345678'
    }))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={
        'class': 'form-control',
        'placeholder': 'name@example.com (optional)'
    }))
    role = forms.ChoiceField(choices=ROLE_CHOICES, widget=forms.Select(attrs={
        'class': 'form-control form-select',
        'id': 'regRole',
        'onchange': 'toggleDonorFields(this.value)'
    }))
    division = forms.ChoiceField(choices=DIVISION_CHOICES, widget=forms.Select(attrs={
        'class': 'form-control form-select',
        'id': 'regDivision',
        'onchange': 'updateDistricts(this.value)'
    }))
    district = forms.CharField(max_length=100, required=True, widget=forms.Select(attrs={
        'class': 'form-control form-select',
        'id': 'regDistrict'
    }))
    blood_group = forms.ChoiceField(choices=BLOOD_GROUP_CHOICES, required=False, initial='O+')
    emergency_available = forms.BooleanField(required=False, initial=True)
    
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': '••••••••••••',
        'id': 'regPassword'
    }))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': '••••••••••••',
        'id': 'regConfirmPassword'
    }))

    class Meta:
        model = User
        fields = ['full_name', 'phone_number', 'email', 'password']

class UserLoginForm(forms.Form):
    username_or_phone = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': 'Enter your contact number or username/email',
        'id': 'loginEmail'
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': '••••••••••••',
        'id': 'loginPassword'
    }))
    role = forms.CharField(widget=forms.HiddenInput(attrs={
        'id': 'selectedRole',
        'value': 'donor'
    }))

class DonationHistoryForm(forms.ModelForm):
    donation_date = forms.DateField(
        initial=timezone.now,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    location_hospital = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Dhaka Medical College Hospital'})
    )
    recipient_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Rahat Khan (Optional)'})
    )
    units_donated = forms.IntegerField(
        initial=1,
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 1})
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Additional details or notes...'})
    )

    class Meta:
        model = DonationHistory
        fields = ['donation_date', 'location_hospital', 'recipient_name', 'units_donated', 'notes']

class BloodRequestForm(forms.ModelForm):
    patient_name = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': 'Enter patient full name'
    }))
    blood_group = forms.ChoiceField(choices=BLOOD_GROUP_CHOICES, widget=forms.Select(attrs={
        'class': 'form-control form-select'
    }))
    units_required = forms.IntegerField(initial=1, min_value=1, widget=forms.NumberInput(attrs={
        'class': 'form-control',
        'min': 1
    }))
    hospital_name = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': 'e.g. Square Hospital, Dhanmondi, Dhaka'
    }))
    division = forms.ChoiceField(choices=DIVISION_CHOICES, widget=forms.Select(attrs={
        'class': 'form-control form-select',
        'id': 'reqDivision',
        'onchange': 'updateRequestDistricts(this.value)'
    }))
    district = forms.CharField(widget=forms.Select(attrs={
        'class': 'form-control form-select',
        'id': 'reqDistrict'
    }))
    urgency = forms.ChoiceField(choices=URGENCY_CHOICES, widget=forms.Select(attrs={
        'class': 'form-control form-select'
    }))
    contact_phone = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': '+880 1712-345678'
    }))
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={
        'class': 'form-control',
        'rows': 3,
        'placeholder': 'Medical urgency details, hospital bed/room number, instructions...'
    }))
    latitude = forms.DecimalField(required=False, widget=forms.HiddenInput(attrs={'id': 'reqLatitude'}))
    longitude = forms.DecimalField(required=False, widget=forms.HiddenInput(attrs={'id': 'reqLongitude'}))

    class Meta:
        model = BloodRequest
        fields = ['patient_name', 'blood_group', 'units_required', 'hospital_name', 'division', 'district', 'urgency', 'contact_phone', 'notes', 'latitude', 'longitude']
