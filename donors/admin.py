from django.contrib import admin
from .models import UserProfile, DonationHistory, BloodRequest, HospitalInventory

@admin.action(description="Approve selected user accounts")
def approve_users(modeladmin, request, queryset):
    updated = queryset.update(is_approved=True)
    modeladmin.message_user(request, f"Successfully approved {updated} user account(s).")

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'phone_number', 'blood_group', 'division', 'district', 'is_approved', 'emergency_available', 'last_location_update')
    list_filter = ('is_approved', 'role', 'blood_group', 'division', 'emergency_available')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'phone_number', 'district')
    list_editable = ('is_approved', 'emergency_available')
    actions = [approve_users]

@admin.register(DonationHistory)
class DonationHistoryAdmin(admin.ModelAdmin):
    list_display = ('donor', 'donation_date', 'location_hospital', 'recipient_name', 'units_donated', 'status')
    list_filter = ('status', 'donation_date')
    search_fields = ('donor__username', 'location_hospital', 'recipient_name')

@admin.register(BloodRequest)
class BloodRequestAdmin(admin.ModelAdmin):
    list_display = ('patient_name', 'seeker', 'blood_group', 'units_required', 'hospital_name', 'division', 'district', 'urgency', 'status', 'created_at')
    list_filter = ('status', 'urgency', 'blood_group', 'division')
    search_fields = ('patient_name', 'hospital_name', 'contact_phone', 'notes')
    list_editable = ('status',)

@admin.register(HospitalInventory)
class HospitalInventoryAdmin(admin.ModelAdmin):
    list_display = ('hospital', 'blood_group', 'units', 'updated_at')
    list_filter = ('blood_group',)
    search_fields = ('hospital__username', 'hospital__first_name')
    list_editable = ('units',)
