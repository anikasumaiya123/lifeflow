import json
from datetime import timedelta
from django.db import models, transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.contrib.auth.models import User

from .models import UserProfile, DonationHistory, BloodRequest, BloodRequestResponse, HospitalInventory, Notification, haversine_distance, get_user_full_name, BLOOD_GROUP_CHOICES, is_blood_compatible, get_compatible_donor_groups, calculate_donor_suitability_score, auto_expire_old_requests
from .forms import UserRegistrationForm, UserLoginForm, DonationHistoryForm, BloodRequestForm
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.utils.safestring import mark_safe
from django.contrib.auth.tokens import default_token_generator

def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        role = request.POST.get('role', 'donor')
        division = request.POST.get('division', '')
        district = request.POST.get('district', '')
        if role != 'donor':
            blood_group = ''
        else:
            blood_group = request.POST.get('blood_group', 'O+').strip()
        emergency_available = request.POST.get('emergency_available') == 'true' or request.POST.get('emergency_available') == 'on'

        if not full_name or not email or not password:
            messages.error(request, "Please fill in all required fields (Full Name, Email Address, and Password).")
            return render(request, 'register.html')

        if password != confirm_password:
            messages.error(request, "Passwords do not match. Please try again.")
            return render(request, 'register.html')

        username = email.lower()

        if User.objects.filter(username__iexact=username).exists() or User.objects.filter(email__iexact=email).exists():
            messages.error(request, "An account with this email address already exists.")
            return render(request, 'register.html')

        if phone_number and UserProfile.objects.filter(phone_number=phone_number).exists():
            messages.error(request, "An account with this phone number already exists.")
            return render(request, 'register.html')

        user = User.objects.create_user(
            username=username,
            email=email.lower(),
            password=password,
            first_name=full_name.split(' ')[0] if full_name else '',
            last_name=' '.join(full_name.split(' ')[1:]) if full_name and ' ' in full_name else ''
        )

        UserProfile.objects.create(
            user=user,
            role=role,
            phone_number=phone_number,
            division=division,
            district=district,
            blood_group=blood_group,
            emergency_available=emergency_available,
            is_approved=False
        )

        messages.info(request, f"Registration submitted successfully for {full_name}! Your account is pending Admin approval. You will be able to log in once an administrator approves your account.")
        return redirect('login')

    return render(request, 'register.html')

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username_or_phone = request.POST.get('username_or_phone', '').strip()
        password = request.POST.get('password', '')

        if not username_or_phone or not password:
            messages.error(request, "Please enter your phone number/email/username and password.")
            return render(request, 'login.html')

        user_obj = None
        if UserProfile.objects.filter(phone_number=username_or_phone).exists():
            profile_obj = UserProfile.objects.filter(phone_number=username_or_phone).first()
            if profile_obj and profile_obj.user:
                user_obj = profile_obj.user
        elif User.objects.filter(username=username_or_phone).exists():
            user_obj = User.objects.filter(username=username_or_phone).first()
        elif User.objects.filter(email=username_or_phone).exists():
            user_obj = User.objects.filter(email=username_or_phone).first()

        if user_obj:
            authenticated_user = authenticate(request, username=user_obj.username, password=password)
            if authenticated_user:
                profile = getattr(authenticated_user, 'profile', None)
                is_superuser = getattr(authenticated_user, 'is_superuser', False)
                if not is_superuser and profile and not profile.is_approved:
                    messages.error(request, "Your account is pending Admin approval. Please wait for an administrator to verify and approve your account before logging in.")
                    return render(request, 'login.html')

                login(request, authenticated_user)
                messages.success(request, f"Welcome back, {get_user_full_name(authenticated_user)}!")
                return redirect('dashboard')

        messages.error(request, "Invalid credentials. Please check your phone/email and password.")

    return render(request, 'login.html')

def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out safely.")
    return redirect('login')

@login_required
def dashboard_view(request):
    user = request.user
    if user.is_superuser:
        return admin_dashboard_view(request)

    auto_expire_old_requests()
    profile, _ = UserProfile.objects.get_or_create(user=user)

    # Mark unread notifications as read upon dashboard view
    Notification.objects.filter(recipient=user, is_read=False).update(is_read=True)

    if profile.role == 'seeker':
        return seeker_dashboard_view(request)
    elif profile.role == 'hospital':
        return hospital_dashboard_view(request)

    filter_type = request.GET.get('filter', '6months')

    all_donations = DonationHistory.objects.filter(donor=user).order_by('-donation_date')
    donations_6_months = DonationHistory.objects.last_6_months(user)

    displayed_donations = all_donations if filter_type == 'all' else donations_6_months

    completed_6mo = donations_6_months.filter(status='completed')
    donations_6mo_count = completed_6mo.count()
    units_6mo_count = sum((d.units_donated or 0) for d in completed_6mo)

    latest_donation = profile.get_last_donation()
    days_until_eligible = 0
    if latest_donation and latest_donation.donation_date:
        don_date = latest_donation.donation_date
        if hasattr(don_date, 'date') and callable(getattr(don_date, 'date')):
            don_date = don_date.date()
        next_eligible_date = don_date + timedelta(days=90)
        today = timezone.now().date()
        if next_eligible_date > today:
            days_until_eligible = (next_eligible_date - today).days

    # Active Emergency Blood Requests for donor overview (targeted requests first)
    active_requests_qs = BloodRequest.objects.filter(status='active').order_by(
        models.Case(
            models.When(target_donor=user, then=0),
            default=1
        ),
        '-created_at'
    )[:10]
    user_responses = set(BloodRequestResponse.objects.filter(donor=user).values_list('request_id', flat=True))
    
    emergency_requests = []
    for req in active_requests_qs:
        emergency_requests.append({
            'object': req,
            'has_responded': req.id in user_responses,
            'is_compatible': is_blood_compatible(profile.blood_group, req.blood_group),
            'is_targeted': req.target_donor_id == user.id
        })

    user_notifications = Notification.objects.filter(recipient=user).select_related('sender', 'related_request')[:10]

    context = {
        'profile': profile,
        'donations': displayed_donations,
        'filter_type': filter_type,
        'donations_6mo_count': donations_6mo_count,
        'units_6mo_count': units_6mo_count,
        'total_donations_count': all_donations.count(),
        'days_until_eligible': days_until_eligible,
        'is_eligible': days_until_eligible == 0,
        'recent_donation_info': profile.recent_donation_info,
        'emergency_requests': emergency_requests,
        'donation_form': DonationHistoryForm(),
        'user_notifications': user_notifications,
    }
    return render(request, 'dashboard.html', context)

@login_required
def seeker_dashboard_view(request):
    user = request.user
    auto_expire_old_requests()
    profile, _ = UserProfile.objects.get_or_create(user=user)

    my_requests = BloodRequest.objects.filter(seeker=user)
    active_requests = my_requests.filter(status='active')
    fulfilled_requests = my_requests.filter(status='fulfilled')

    nearby_donors_count = UserProfile.objects.filter(
        role='donor',
        is_approved=True,
        emergency_available=True,
        division=profile.division
    ).count()

    user_notifications = Notification.objects.filter(recipient=user).select_related('sender', 'related_request')[:10]

    context = {
        'profile': profile,
        'my_requests': my_requests[:5],
        'active_count': active_requests.count(),
        'fulfilled_count': fulfilled_requests.count(),
        'total_requests_count': my_requests.count(),
        'nearby_donors_count': nearby_donors_count,
        'user_notifications': user_notifications,
    }
    return render(request, 'seeker_dashboard.html', context)

@login_required
def hospital_dashboard_view(request):
    """Hospital Blood Bank Inventory & Verification Dashboard."""
    user = request.user
    auto_expire_old_requests()
    profile, _ = UserProfile.objects.get_or_create(user=user)
    if profile.role != 'hospital':
        messages.error(request, "Access denied. Hospital role required.")
        return redirect('dashboard')

    valid_bg_codes = [bg[0] for bg in BLOOD_GROUP_CHOICES]

    # Initialize standard blood groups in inventory if not present
    for bg_code in valid_bg_codes:
        HospitalInventory.objects.get_or_create(hospital=user, blood_group=bg_code)

    inventory_qs = HospitalInventory.objects.filter(hospital=user, blood_group__in=valid_bg_codes).order_by('blood_group')
    inventory_stock_dict = {inv.blood_group: inv.units for inv in inventory_qs}

    total_units_in_stock = sum(inv.units for inv in inventory_qs)
    
    # Requests posted by this hospital
    my_hospital_requests = BloodRequest.objects.filter(seeker=user)
    
    # All active emergency blood requests across the system (targeted requests to this hospital first)
    all_active_requests_qs = BloodRequest.objects.filter(status='active').select_related('seeker').order_by(
        models.Case(
            models.When(target_donor=user, then=0),
            default=1
        ),
        '-created_at'
    )[:15]
    
    all_active_requests = []
    for req in all_active_requests_qs:
        stock_count = inventory_stock_dict.get(req.blood_group, 0)
        all_active_requests.append({
            'object': req,
            'stock_units': stock_count,
            'has_stock': stock_count >= req.units_required,
            'is_own': req.seeker == user,
            'is_targeted': req.target_donor_id == user.id,
        })

    user_notifications = Notification.objects.filter(recipient=user).select_related('sender', 'related_request')[:10]

    context = {
        'profile': profile,
        'inventory': inventory_qs,
        'total_units_in_stock': total_units_in_stock,
        'hospital_requests': my_hospital_requests[:5],
        'my_requests_count': my_hospital_requests.filter(status='active').count(),
        'all_active_requests': all_active_requests,
        'active_requests_count': BloodRequest.objects.filter(status='active').count(),
        'user_notifications': user_notifications,
    }
    return render(request, 'hospital_dashboard.html', context)

@login_required
def update_hospital_inventory_view(request):
    """Updates blood bank unit stock for a blood group."""
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'hospital':
        messages.error(request, "Access denied. Hospital role required.")
        return redirect('dashboard')

    if request.method == 'POST':
        blood_group = request.POST.get('blood_group')
        try:
            units = max(0, int(request.POST.get('units', 0)))
            with transaction.atomic():
                inv = HospitalInventory.objects.select_for_update().filter(hospital=request.user, blood_group=blood_group).first()
                if not inv:
                    inv = HospitalInventory.objects.create(hospital=request.user, blood_group=blood_group, units=units)
                else:
                    inv.units = units
                    inv.save()
            messages.success(request, f"Updated {blood_group} stock to {units} unit(s).")
        except ValueError:
            messages.error(request, "Invalid unit quantity.")
    return redirect('dashboard')

@login_required
def hospital_verify_donation_view(request):
    """Allows hospital to record and verify a donor's blood donation."""
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'hospital':
        messages.error(request, "Access denied. Hospital role required.")
        return redirect('dashboard')

    if request.method == 'POST':
        donor_phone = request.POST.get('donor_phone', '').strip()
        try:
            units = max(1, int(request.POST.get('units_donated', 1)))
        except (ValueError, TypeError):
            units = 1
        recipient = request.POST.get('recipient_name', '').strip()
        notes = request.POST.get('notes', '').strip()

        # Find donor user
        donor_profile = UserProfile.objects.filter(phone_number=donor_phone, role='donor').first()
        if not donor_profile:
            messages.error(request, f"No registered blood donor found with phone number '{donor_phone}'.")
        else:
            hospital_name = get_user_full_name(request.user)
            with transaction.atomic():
                DonationHistory.objects.create(
                    donor=donor_profile.user,
                    donation_date=timezone.now().date(),
                    location_hospital=hospital_name,
                    recipient_name=recipient or "Hospital Stock",
                    units_donated=units,
                    status='completed',
                    notes=notes or "Verified by Hospital"
                )
                # Update hospital stock inventory upon donation verification with row locking
                inv = HospitalInventory.objects.select_for_update().filter(hospital=request.user, blood_group=donor_profile.blood_group).first()
                if not inv:
                    inv = HospitalInventory.objects.create(hospital=request.user, blood_group=donor_profile.blood_group, units=units)
                else:
                    inv.units += units
                    inv.save()

            messages.success(request, f"Successfully verified donation of {units} unit(s) from {get_user_full_name(donor_profile.user)} ({donor_profile.blood_group})! Stock inventory updated (+{units}).")

    return redirect('dashboard')

@login_required
def fulfill_request_with_stock_view(request, request_id):
    """Allows hospital to fulfill an active emergency blood request using its inventory stock."""
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'hospital':
        messages.error(request, "Only registered hospitals can supply blood stock for emergency requests.")
        return redirect('dashboard')

    if request.method == 'POST':
        with transaction.atomic():
            req = BloodRequest.objects.select_for_update().filter(id=request_id, status='active').first()
            if not req:
                messages.error(request, "This request is no longer active or has already been fulfilled.")
                return redirect('dashboard')

            inv = HospitalInventory.objects.select_for_update().filter(hospital=request.user, blood_group=req.blood_group).first()

            if not inv or inv.units < req.units_required:
                avail_units = inv.units if inv else 0
                messages.error(request, f"Insufficient {req.blood_group} stock! You have {avail_units} unit(s), but request requires {req.units_required} unit(s).")
            else:
                inv.units -= req.units_required
                inv.save()
                req.status = 'fulfilled'
                req.save()

                hospital_name = get_user_full_name(request.user)
                BloodRequestResponse.objects.create(
                    request=req,
                    donor=request.user,
                    donor_message=f"{hospital_name} is supplying {req.units_required} bag(s) of {req.blood_group} blood stock from their inventory for your request.",
                    has_recent_donation=False
                )

                # Send notification to seeker
                from django.urls import reverse
                Notification.objects.create(
                    recipient=req.seeker,
                    sender=request.user,
                    title="Hospital Blood Stock Supplied!",
                    message=f"{hospital_name} is supplying {req.units_required} unit(s) of {req.blood_group} stock from their inventory for your request.",
                    notification_type='stock_supplied',
                    related_request=req,
                    link=f"{reverse('my_requests')}#request-{req.id}"
                )

                messages.success(request, f"Supplied {req.units_required} bag(s) of {req.blood_group} stock for {req.patient_name}! Request marked as Fulfilled.")

    return redirect('dashboard')

def find_donors_view(request):
    blood_group = request.GET.get('blood_group', '').replace(' ', '+').strip()
    division = request.GET.get('division', '').strip()
    district = request.GET.get('district', '').strip()
    availability = request.GET.get('availability', 'available')
    match_type = request.GET.get('match_type', 'compatible').strip()
    radius_str = request.GET.get('radius', 'all')
    seeker_lat = request.GET.get('lat')
    seeker_lng = request.GET.get('lng')

    donors_qs = UserProfile.objects.filter(role='donor', is_approved=True).select_related('user')

    if availability == 'available':
        donors_qs = donors_qs.filter(emergency_available=True)
    if blood_group:
        if match_type == 'exact':
            donors_qs = donors_qs.filter(blood_group=blood_group)
        else:
            comp_bgs = get_compatible_donor_groups(blood_group)
            if comp_bgs:
                donors_qs = donors_qs.filter(blood_group__in=comp_bgs)
            else:
                donors_qs = donors_qs.filter(blood_group=blood_group)
    if division:
        donors_qs = donors_qs.filter(division=division)
    if district:
        donors_qs = donors_qs.filter(district__icontains=district)

    s_lat, s_lng = None, None
    if seeker_lat:
        try:
            s_lat = float(seeker_lat)
        except (ValueError, TypeError):
            s_lat = None
    if seeker_lng:
        try:
            s_lng = float(seeker_lng)
        except (ValueError, TypeError):
            s_lng = None

    donors_list = []
    map_markers = []

    requested_target_ids = set()
    if request.user.is_authenticated:
        requested_target_ids = set(
            BloodRequest.objects.filter(seeker=request.user, target_donor__isnull=False)
            .values_list('target_donor_id', flat=True)
        )

    for d in donors_qs:
        dist = None
        d_lat, d_lng = None, None
        if d.latitude is not None:
            try:
                d_lat = float(d.latitude)
            except (ValueError, TypeError):
                d_lat = None
        if d.longitude is not None:
            try:
                d_lng = float(d.longitude)
            except (ValueError, TypeError):
                d_lng = None

        if s_lat is not None and s_lng is not None and d_lat is not None and d_lng is not None:
            dist = haversine_distance(s_lat, s_lng, d_lat, d_lng)

        if radius_str != 'all' and dist is not None:
            try:
                if dist > float(radius_str):
                    continue
            except (ValueError, TypeError):
                pass

        recent_info = d.recent_donation_info
        don_dt = recent_info['donation_date']
        if hasattr(don_dt, 'date') and callable(getattr(don_dt, 'date')):
            don_dt = don_dt.date()
        due_dt = recent_info['due_date']
        if hasattr(due_dt, 'date') and callable(getattr(due_dt, 'date')):
            due_dt = due_dt.date()

        recent_dict = {
            'recently_donated': recent_info['recently_donated'],
            'donation_date': don_dt.strftime('%b %d, %Y') if (don_dt and hasattr(don_dt, 'strftime')) else None,
            'due_date': due_dt.strftime('%b %d, %Y') if (due_dt and hasattr(due_dt, 'strftime')) else None,
            'days_remaining': recent_info['days_remaining'],
            'message': recent_info['message'],
        }

        has_been_requested = d.user.id in requested_target_ids
        suitability = calculate_donor_suitability_score(d, blood_group, dist)

        donor_data = {
            'id': d.id,
            'user_id': d.user.id,
            'name': f"{d.blood_group}, Donor",
            'blood_group': d.blood_group,
            'phone': '',
            'division': d.division,
            'district': d.district,
            'is_available': d.emergency_available,
            'distance_km': dist,
            'lat': d_lat,
            'lng': d_lng,
            'last_update': d.last_location_update.strftime('%b %d, %Y') if d.last_location_update else None,
            'recent_info': recent_dict,
            'has_been_requested': has_been_requested,
            'suitability': suitability,
        }
        donors_list.append(donor_data)

        if d_lat is not None and d_lng is not None:
            map_markers.append({
                'user_id': d.user.id,
                'name': f"{d.blood_group}, Donor",
                'blood_group': d.blood_group,
                'phone': '',
                'location': f"{d.district}, {d.division}",
                'lat': d_lat,
                'lng': d_lng,
                'distance': f"Approximately {dist} km away" if dist is not None else "Distance N/A",
                'available': d.emergency_available,
                'recently_donated': recent_dict['recently_donated'],
                'recent_donation_date': recent_dict['donation_date'],
                'next_due_date': recent_dict['due_date'],
                'has_been_requested': has_been_requested,
                'suitability_score': suitability['score'],
                'suitability_label': suitability['label'],
                'suitability_color': suitability['badge_color'],
                'suitability_text': suitability['display_text'],
                'suitability_reasons': suitability['reasons'],
            })

    # Sort donors list by AI suitability score descending
    donors_list.sort(key=lambda x: (-x['suitability']['score'], x['distance_km'] if x['distance_km'] is not None else 999999))

    hospital_stock_qs = HospitalInventory.objects.filter(units__gt=0, hospital__profile__is_approved=True).select_related('hospital', 'hospital__profile')
    if blood_group:
        hospital_stock_qs = hospital_stock_qs.filter(blood_group=blood_group)
    if division:
        hospital_stock_qs = hospital_stock_qs.filter(hospital__profile__division=division)

    matched_hospital_stocks = []
    from django.utils.timesince import timesince

    for hs in hospital_stock_qs:
        h_profile = getattr(hs.hospital, 'profile', None)
        h_dist = None
        h_lat, h_lng = None, None
        if h_profile and h_profile.latitude is not None and h_profile.longitude is not None:
            try:
                h_lat = float(h_profile.latitude)
                h_lng = float(h_profile.longitude)
                if s_lat is not None and s_lng is not None:
                    h_dist = haversine_distance(s_lat, s_lng, h_lat, h_lng)
            except (ValueError, TypeError):
                pass

        timesince_str = timesince(hs.updated_at) if hs.updated_at else 'recently'

        matched_hospital_stocks.append({
            'object': hs,
            'hospital_id': hs.hospital.id,
            'hospital_name': get_user_full_name(hs.hospital),
            'blood_group': hs.blood_group,
            'units': hs.units,
            'is_approved': h_profile.is_approved if h_profile else False,
            'district': h_profile.district if h_profile else '',
            'division': h_profile.division if h_profile else '',
            'distance_km': h_dist,
            'distance_str': f"{h_dist} km away" if h_dist is not None else f"{h_profile.district if h_profile else 'Bangladesh'}",
            'updated_at': hs.updated_at,
            'timesince_update': timesince_str,
            'is_requested': hs.hospital.id in requested_target_ids,
        })

        if h_lat is not None and h_lng is not None:
            map_markers.append({
                'user_id': hs.hospital.id,
                'name': f"{get_user_full_name(hs.hospital)} (Stock Available)",
                'blood_group': hs.blood_group,
                'phone': h_profile.phone_number if h_profile else '',
                'location': f"{h_profile.district}, {h_profile.division}" if h_profile else "Bangladesh",
                'lat': h_lat,
                'lng': h_lng,
                'distance': f"{h_dist} km away" if h_dist is not None else "N/A",
                'available': True,
                'is_hospital': True,
                'units': hs.units,
                'recently_donated': False,
                'recent_donation_date': None,
                'next_due_date': None,
                'has_been_requested': hs.hospital.id in requested_target_ids,
            })

    context = {
        'donors': donors_list,
        'matched_hospital_stocks': matched_hospital_stocks,
        'map_markers_json': json.dumps(map_markers),
        'requested_target_ids': requested_target_ids,
        'blood_group': blood_group,
        'division': division,
        'district': district,
        'availability': availability,
        'match_type': match_type,
        'radius': radius_str,
        'seeker_lat': seeker_lat or '',
        'seeker_lng': seeker_lng or '',
        'blood_groups': [bg[0] for bg in BLOOD_GROUP_CHOICES],
        'total_results': len(donors_list),
    }
    return render(request, 'find_donors.html', context)

@login_required
def hospital_verify_donation_view(request):
    """Allows approved hospitals to record and verify a donor's blood donation with unique Certificate IDs."""
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'hospital' or not profile.is_approved:
        messages.error(request, "Access denied. Only approved hospital accounts can perform donation verifications.")
        return redirect('dashboard')

    if request.method == 'POST':
        donor_phone = request.POST.get('donor_phone', '').strip()
        try:
            units = max(1, int(request.POST.get('units_donated', 1)))
        except (ValueError, TypeError):
            units = 1
        recipient = request.POST.get('recipient_name', '').strip()
        notes = request.POST.get('notes', '').strip()

        # Find donor user
        donor_profile = UserProfile.objects.filter(phone_number=donor_phone, role='donor').first()
        if not donor_profile:
            messages.error(request, f"No registered blood donor found with phone number '{donor_phone}'.")
        else:
            hospital_name = get_user_full_name(request.user)
            import uuid
            v_id = f"LIFE-CERT-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

            with transaction.atomic():
                donation_record = DonationHistory.objects.create(
                    donor=donor_profile.user,
                    donation_date=timezone.now().date(),
                    location_hospital=hospital_name,
                    recipient_name=recipient or "Hospital Blood Bank Stock",
                    units_donated=units,
                    status='completed',
                    verification_id=v_id,
                    verified_by_hospital=request.user,
                    notes=notes or "Verified by Hospital"
                )
                # Update hospital stock inventory upon donation verification with row locking
                inv = HospitalInventory.objects.select_for_update().filter(hospital=request.user, blood_group=donor_profile.blood_group).first()
                if not inv:
                    inv = HospitalInventory.objects.create(hospital=request.user, blood_group=donor_profile.blood_group, units=units)
                else:
                    inv.units += units
                    inv.save()

                # Notify donor of hospital verification and certificate ID
                from django.urls import reverse
                Notification.objects.create(
                    recipient=donor_profile.user,
                    sender=request.user,
                    title="Donation Verified by Hospital",
                    message=f"Your donation of {units} unit(s) of {donor_profile.blood_group} blood at {hospital_name} has been officially verified.\nVerification Certificate ID: {v_id}",
                    notification_type='stock_supplied',
                    link=reverse('dashboard')
                )

            messages.success(request, f"Successfully verified donation of {units} unit(s) from {get_user_full_name(donor_profile.user)} ({donor_profile.blood_group})! Verification Certificate ID: {v_id}. Stock inventory updated (+{units}).")

    return redirect('dashboard')

@login_required
def fulfill_request_with_stock_view(request, request_id):
    """Allows hospital to fulfill an active emergency blood request using its inventory stock."""
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'hospital' or not profile.is_approved:
        messages.error(request, "Access denied. Only approved hospitals can supply blood stock for emergency requests.")
        return redirect('dashboard')

    if request.method == 'POST':
        with transaction.atomic():
            req = BloodRequest.objects.select_for_update().get(id=request_id, status='active')
            inv = HospitalInventory.objects.select_for_update().filter(hospital=request.user, blood_group=req.blood_group).first()

            if not inv or inv.units < req.units_required:
                messages.error(request, f"Insufficient stock of {req.blood_group}. Hospital currently has {inv.units if inv else 0} unit(s), but request requires {req.units_required} unit(s).")
                return redirect('dashboard')

            inv.units -= req.units_required
            inv.save()

            req.status = 'fulfilled'
            req.save()

            # Record response
            BloodRequestResponse.objects.create(
                request=req,
                donor=request.user,
                donor_message=f"Hospital Blood Bank supply fulfilled from stock inventory ({req.units_required} unit(s))."
            )

            # Send Notification to Seeker
            from django.urls import reverse
            Notification.objects.create(
                recipient=req.seeker,
                sender=request.user,
                title="Hospital Blood Supply Reserved",
                message=f"{get_user_full_name(request.user)} has reserved {req.units_required} unit(s) of {req.blood_group} blood stock from their hospital inventory for patient {req.clean_patient_name}.",
                notification_type='stock_supplied',
                related_request=req,
                link=f"{reverse('my_requests')}#request-{req.id}"
            )

            messages.success(request, f"Successfully fulfilled request for {req.patient_name}! Reserved {req.units_required} unit(s) of {req.blood_group} stock.")

    return redirect('dashboard')

def notify_request_creation(sender_user, req):
    """Broadcasts in-app notifications to all compatible donors and hospitals the moment a request is posted."""
    from django.urls import reverse
    req_hash = f"#request-{req.id}"
    target_link = f"{reverse('dashboard')}{req_hash}"

    comp_bgs = get_compatible_donor_groups(req.blood_group)
    matching_donors = UserProfile.objects.filter(
        role='donor',
        blood_group__in=comp_bgs
    ).exclude(user=sender_user).select_related('user')

    matching_hospitals = UserProfile.objects.filter(
        role='hospital'
    ).exclude(user=sender_user).select_related('user')

    notifications_to_create = []

    # Direct request notification if targeted
    if req.target_donor:
        notifications_to_create.append(Notification(
            recipient=req.target_donor,
            sender=sender_user,
            title=f"Direct Blood Request ({req.blood_group})",
            message=f"{req.blood_group} blood required at {req.hospital_name}.\nRequested by {get_user_full_name(sender_user)} for patient {req.clean_patient_name}.",
            notification_type='direct_request',
            related_request=req,
            link=target_link
        ))

    # Broadcast in-app notifications to matching compatible donors
    for p in matching_donors:
        if req.target_donor and p.user == req.target_donor:
            continue
        dist_str = f"Location: {req.district}, {req.division}"
        if req.latitude is not None and req.longitude is not None and p.latitude is not None and p.longitude is not None:
            dist = haversine_distance(p.latitude, p.longitude, req.latitude, req.longitude)
            if dist is not None:
                dist_str = f"Approximately {dist} km away ({req.district}, {req.division})"
        notifications_to_create.append(Notification(
            recipient=p.user,
            sender=sender_user,
            title="Emergency Blood Request",
            message=f"{req.blood_group} blood required at {req.hospital_name}.\n{dist_str}.",
            notification_type='emergency_request',
            related_request=req,
            link=target_link
        ))

    # Broadcast in-app notifications to approved hospitals
    for h in matching_hospitals:
        if req.target_donor and h.user == req.target_donor:
            continue
        notifications_to_create.append(Notification(
            recipient=h.user,
            sender=sender_user,
            title="Emergency Blood Request",
            message=f"{req.blood_group} blood required at {req.hospital_name}.\nLocation: {req.district}, {req.division}.",
            notification_type='emergency_request',
            related_request=req,
            link=target_link
        ))

    if notifications_to_create:
        Notification.objects.bulk_create(notifications_to_create, batch_size=500)

@login_required
def post_request_view(request):
    """Processes emergency blood requests with authentic seeker-supplied details."""
    target_donor_obj = None

    if request.method == 'POST':
        target_donor_id = request.POST.get('target_donor_id')
        if target_donor_id:
            target_donor_obj = User.objects.filter(id=target_donor_id).first()

        if request.POST.get('direct_request') == 'true':
            target_id = request.POST.get('target_donor_id')
            target_user = get_object_or_404(User, id=target_id)
            t_profile = getattr(target_user, 'profile', None)
            s_profile = getattr(request.user, 'profile', None)

            requested_bg = request.POST.get('blood_group', '').replace(' ', '+').strip()
            bg = requested_bg or (t_profile.blood_group if (t_profile and t_profile.blood_group) else getattr(s_profile, 'blood_group', 'O+')) or 'O+'
            div = (t_profile.division if (t_profile and t_profile.division) else getattr(s_profile, 'division', 'Dhaka')) or 'Dhaka'
            dist = (t_profile.district if (t_profile and t_profile.district) else getattr(s_profile, 'district', 'Mirpur')) or 'Mirpur'

            if t_profile and t_profile.blood_group and not is_blood_compatible(t_profile.blood_group, bg):
                messages.error(request, f"Incompatible Blood Group: Target donor {get_user_full_name(target_user)} ({t_profile.blood_group}) cannot donate to patient blood group ({bg}).")
                return redirect('post_request')

            req = BloodRequest.objects.create(
                seeker=request.user,
                target_donor=target_user,
                patient_name="Emergency Patient",
                blood_group=bg,
                units_required=1,
                hospital_name=f"{dist} Medical Center",
                division=div,
                district=dist,
                urgency='immediate',
                contact_phone=getattr(s_profile, 'phone_number', '') or 'Emergency Contact',
                notes=f"Direct emergency request sent to {get_user_full_name(target_user)}."
            )
            notify_request_creation(request.user, req)
            messages.success(request, f"Emergency Blood Request sent directly to {get_user_full_name(target_user)}!")
            return redirect('my_requests')

        form = BloodRequestForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.seeker = request.user
            if target_donor_id:
                try:
                    target_user = User.objects.get(id=target_donor_id)
                    t_profile = getattr(target_user, 'profile', None)
                    if t_profile and t_profile.blood_group and not is_blood_compatible(t_profile.blood_group, req.blood_group):
                        messages.error(request, f"Incompatible Blood Group: Target donor {get_user_full_name(target_user)} ({t_profile.blood_group}) cannot donate to patient blood group ({req.blood_group}).")
                        hospital_stocks = HospitalInventory.objects.filter(units__gt=0).select_related('hospital').order_by('blood_group')
                        return render(request, 'post_request.html', {
                            'form': form,
                            'hospital_stocks': hospital_stocks,
                            'target_donor': target_donor_obj,
                        })
                    req.target_donor = target_user
                except User.DoesNotExist:
                    pass
            req.save()
            notify_request_creation(request.user, req)
            if req.target_donor:
                messages.success(request, f"Emergency Blood Request for {req.patient_name} ({req.blood_group}) posted & sent directly to {get_user_full_name(req.target_donor)}!")
            else:
                messages.success(request, f"Emergency Blood Request for {req.patient_name} ({req.blood_group}) posted successfully!")
            return redirect('my_requests')
        else:
            messages.error(request, "Failed to post blood request. Please check required fields.")
    else:
        profile = getattr(request.user, 'profile', None)
        target_donor_id = request.GET.get('target_donor_id') or request.GET.get('donor_id')
        req_blood_group = request.GET.get('blood_group')
        req_division = request.GET.get('division')
        req_district = request.GET.get('district')
        initial_data = {
            'contact_phone': profile.phone_number if profile else '',
            'division': req_division or (profile.division if profile else ''),
            'district': req_district or (profile.district if profile else ''),
        }
        if req_blood_group:
            initial_data['blood_group'] = req_blood_group

        if target_donor_id:
            try:
                target_user = User.objects.get(id=target_donor_id)
                t_profile = getattr(target_user, 'profile', None)
                if t_profile and t_profile.blood_group and not req_blood_group:
                    initial_data['blood_group'] = t_profile.blood_group
                if t_profile and t_profile.division and not req_division:
                    initial_data['division'] = t_profile.division
                if t_profile and t_profile.district and not req_district:
                    initial_data['district'] = t_profile.district
                target_donor_obj = target_user
            except User.DoesNotExist:
                pass

        form = BloodRequestForm(initial=initial_data)

    hospital_stocks = HospitalInventory.objects.filter(units__gt=0).select_related('hospital').order_by('blood_group')
    return render(request, 'post_request.html', {
        'form': form,
        'hospital_stocks': hospital_stocks,
        'target_donor': target_donor_obj,
    })

def chatbot_api_view(request):
    """AI-powered assistant endpoint providing context-aware guidance for blood donation, eligibility, matching, and system workflows."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required.'}, status=405)

    try:
        data = json.loads(request.body)
        user_query = data.get('query', '').strip().lower()
    except (json.JSONDecodeError, AttributeError):
        user_query = request.POST.get('query', '').strip().lower()

    if not user_query:
        return JsonResponse({'status': 'error', 'message': 'Empty query provided.'}, status=400)

    user = request.user if request.user.is_authenticated else None
    profile = getattr(user, 'profile', None) if user else None

    # Context variables
    user_name = get_user_full_name(user) if user else "Friend"
    user_bg = profile.blood_group if profile else None
    user_role = profile.role if profile else "guest"
    
    # 1. Eligibility Check
    if any(k in user_query for k in ['eligible', 'eligibility', 'can i donate', 'who can donate', '90 day', 'recovery']):
        if profile and profile.role == 'donor':
            recent_info = profile.recent_donation_info
            if recent_info['recently_donated']:
                due_str = recent_info['due_date'].strftime('%b %d, %Y') if recent_info['due_date'] else 'due date'
                reply = f"Hello <strong>{user_name}</strong>!<br><br>⚠️ <strong>Eligibility Status: Restricted</strong><br>You recorded a donation on <strong>{recent_info['donation_date']}</strong>. Standard medical guidelines require a 90-day recovery window.<br><br><strong>Next Regular Due Date:</strong> {due_str} ({recent_info['days_remaining']} days remaining).<br><br><em>Note: You remain available for emergency alert overrides if urgently needed!</em>"
            else:
                reply = f"Hello <strong>{user_name}</strong>!<br><br>✓ <strong>Eligibility Status: Eligible Now!</strong><br>You have no active 90-day donation restriction recorded.<br><br><strong>Donation Requirements:</strong><br>• Age: 18 – 60 years<br>• Weight: &ge; 45 kg<br>• Interval: 90 days since last donation<br>• Hemoglobin: &ge; 12.5 g/dL"
        else:
            reply = "<strong>General Blood Donation Eligibility:</strong><br>• <strong>Frequency:</strong> Once every 90 days (3 months)<br>• <strong>Age:</strong> 18 – 60 years old<br>• <strong>Weight:</strong> Minimum 45 kg (100 lbs)<br>• <strong>Condition:</strong> Normal blood pressure, no fever.<br><br><em>Create a Donor Account on LifeFlow BD to track your 90-day recovery counter!</em>"

    # 2. Blood Group Compatibility & Matching
    elif any(k in user_query for k in ['match', 'group', 'compatible', 'compatibility', 'universal', 'who can get', 'receive']):
        if user_bg:
            comp_donors = get_compatible_donor_groups(user_bg)
            reply = f"<strong>Blood Group Compatibility for {user_bg}:</strong><br><br>"
            if user_role == 'donor':
                reply += f"As an <strong>{user_bg}</strong> donor, you can donate to: <strong>{', '.join(comp_donors)}</strong>.<br><br>"
            else:
                reply += f"For an <strong>{user_bg}</strong> patient, compatible donor blood groups are: <strong>{', '.join(comp_donors)}</strong>.<br><br>"
            reply += "<strong>Universal Donor:</strong> O- (can donate to all)<br><strong>Universal Recipient:</strong> AB+ (can receive from all)."
        else:
            reply = "<strong>Blood Compatibility Rules:</strong><br>• <strong>O-</strong>: Donates to ALL (Universal Donor)<br>• <strong>O+</strong>: Donates to O+, A+, B+, AB+<br>• <strong>A-</strong>: Donates to A-, A+, AB-, AB+<br>• <strong>A+</strong>: Donates to A+, AB+<br>• <strong>B-</strong>: Donates to B-, B+, AB-, AB+<br>• <strong>B+</strong>: Donates to B+, AB+<br>• <strong>AB-</strong>: Donates to AB-, AB+<br>• <strong>AB+</strong>: Donates to AB+ only."

    # 3. Emergency Request Guidance
    elif any(k in user_query for k in ['request', 'emergency', 'post', 'need blood', 'patient', 'create request']):
        active_req_cnt = BloodRequest.objects.filter(status='active').count()
        reply = f" <strong>Emergency Request Assistant:</strong><br>There are currently <strong>{active_req_cnt} active emergency blood requests</strong> in the LifeFlow BD network.<br><br>👉 <strong>How to Post an Emergency Request:</strong><br>1. Click <a href='/post-request/' style='color:#60A5FA; text-decoration:underline;'>Post Emergency Request</a>.<br>2. Fill in authentic patient details, hospital name, units required, and contact phone.<br>3. Alerts will be broadcast immediately to all compatible donors and hospitals nearby!"

    # 4. Hospital Inventory & Verification
    elif any(k in user_query for k in ['hospital', 'stock', 'inventory', 'bank', 'verify', 'certificate']):
        approved_hospitals = UserProfile.objects.filter(role='hospital', is_approved=True).count()
        reply = f"<strong>Hospital Stock & Verification System:</strong><br>There are currently <strong>{approved_hospitals} verified hospitals</strong> connected to LifeFlow BD.<br><br>✓ <strong>Real-time Stock Inventory:</strong> View verified hospital stock units on the <a href='/find-donors/' style='color:#34D399; text-decoration:underline;'>Find Donors</a> page.<br>📜 <strong>Official Verification Certificates:</strong> Approved hospitals issue unique Verification Certificate IDs (e.g. <code>LIFE-CERT-2026-XXXXXX</code>) to verify blood drive donations."

    # 5. Location / Nearby Donors Search
    elif any(k in user_query for k in ['location', 'dhaka', 'chattogram', 'sylhet', 'distance', 'near', 'map', 'district', 'division']):
        reply = f"<strong>GPS Proximity & Division Search:</strong><br>LifeFlow BD covers all 8 divisions and 64 districts across Bangladesh.<br><br>• Use OpenStreetMap location pinning on your dashboard to share GPS coordinates.<br>• Search for donors within 5 km, 10 km, 25 km, or 50 km radii on the <a href='/find-donors/' style='color:#60A5FA; text-decoration:underline;'>Find Donors Search Map</a>."

    # Default AI Greeting / Capabilities Overview
    else:
        reply = f"<strong>Hello {user_name}! I am your LifeFlow AI Assistant.</strong><br><br>How can I help you today? You can ask me about:<br>• <strong>Eligibility:</strong> <em>'Am I eligible to donate blood?'</em><br>• <strong>Blood Matching:</strong> <em>'Who can A+ blood donate to?'</em><br>• <strong>Emergency Requests:</strong> <em>'How do I post a blood request?'</em><br>• <strong>Hospital Stock:</strong> <em>'Show verified hospital inventories'</em><br>• <strong>Certificates:</strong> <em>'How do hospital verification IDs work?'</em>"

    return JsonResponse({
        'status': 'success',
        'reply': reply,
        'user_name': user_name
    })

@login_required
def my_requests_view(request):
    requests_qs = BloodRequest.objects.filter(seeker=request.user)
    requested_target_ids = set(
        requests_qs.filter(target_donor__isnull=False).values_list('target_donor_id', flat=True)
    )
    active_requests = []
    for req in requests_qs:
        responses_qs = req.responses.all().select_related('donor', 'donor__profile')
        if req.status == 'active':
            comp_bgs = get_compatible_donor_groups(req.blood_group)
            matched_qs = UserProfile.objects.filter(
                role='donor',
                is_approved=True,
                emergency_available=True,
                blood_group__in=comp_bgs,
                division=req.division
            ).select_related('user')

            matched_donors_list = []
            for donor in matched_qs:
                suitability = calculate_donor_suitability_score(donor, req.blood_group)
                matched_donors_list.append({
                    'profile': donor,
                    'user': donor.user,
                    'blood_group': donor.blood_group,
                    'district': donor.district,
                    'division': donor.division,
                    'is_recently_donated': donor.is_recently_donated,
                    'recent_donation_info': donor.recent_donation_info,
                    'suitability': suitability,
                })
            matched_donors_list.sort(key=lambda x: -x['suitability']['score'])
            matched_donors = matched_donors_list[:5]
            h_stocks = HospitalInventory.objects.filter(
                blood_group=req.blood_group,
                units__gt=0
            ).select_related('hospital')
        else:
            matched_donors = []
            h_stocks = HospitalInventory.objects.none()

        active_requests.append({
            'object': req,
            'responses': responses_qs,
            'matched_donors': matched_donors,
            'hospital_stocks': h_stocks
        })

    context = {
        'requests_with_donors': active_requests,
        'requested_target_ids': requested_target_ids,
        'total_count': requests_qs.count(),
    }
    return render(request, 'my_requests.html', context)

@login_required
def respond_to_request_view(request, request_id):
    req = get_object_or_404(BloodRequest, id=request_id, status='active')
    profile = getattr(request.user, 'profile', None)

    if not profile or profile.role != 'donor':
        messages.error(request, "Only registered blood donors can respond to emergency blood requests.")
        return redirect('dashboard')

    if profile and profile.is_recently_donated:
        due_str = profile.next_regular_due_date.strftime('%b %d, %Y') if profile.next_regular_due_date else 'due date'
        messages.error(request, f"Donation Restricted: You cannot volunteer to donate blood before your due date on {due_str}.")
        return redirect('dashboard')

    if profile and not is_blood_compatible(profile.blood_group, req.blood_group):
        messages.error(request, f"Your blood group ({profile.blood_group}) is not compatible with the patient's requested blood group ({req.blood_group}).")
        return redirect('dashboard')

    if request.method == 'POST':
        donor_message = request.POST.get('donor_message', '').strip()
        recent_info = profile.recent_donation_info if profile else {'recently_donated': False, 'donation_date': None, 'due_date': None}

        don_dt = recent_info['donation_date']
        if hasattr(don_dt, 'date') and callable(getattr(don_dt, 'date')):
            don_dt = don_dt.date()
        due_dt = recent_info['due_date']
        if hasattr(due_dt, 'date') and callable(getattr(due_dt, 'date')):
            due_dt = due_dt.date()

        response_obj, created = BloodRequestResponse.objects.get_or_create(
            request=req,
            donor=request.user
        )
        response_obj.donor_message = donor_message
        response_obj.has_recent_donation = recent_info['recently_donated']
        response_obj.recent_donation_date = don_dt
        response_obj.next_due_date = due_dt
        response_obj.save()

        # Send notification to seeker
        from django.urls import reverse
        Notification.objects.create(
            recipient=req.seeker,
            sender=request.user,
            title="Someone responded to your blood request",
            message=f"{get_user_full_name(request.user)} ({profile.blood_group}) responded & offered to donate blood for your request for {req.clean_patient_name} at {req.hospital_name}.",
            notification_type='response_received',
            related_request=req,
            link=f"{reverse('my_requests')}#request-{req.id}"
        )

        if recent_info['recently_donated'] and don_dt and due_dt:
            don_str = don_dt.strftime('%b %d, %Y') if hasattr(don_dt, 'strftime') else str(don_dt)
            due_str = due_dt.strftime('%b %d, %Y') if hasattr(due_dt, 'strftime') else str(due_dt)
            messages.success(
                request,
                f"Your offer to donate for {req.patient_name}'s emergency request has been sent! "
                f"Note: Since you recently donated blood on {don_str}, the seeker has been informed that your standard next due date is {due_str}."
            )
        else:
            messages.success(request, f"Your offer to donate for {req.patient_name}'s emergency request has been sent to the seeker!")

    return redirect('dashboard')

@login_required
def update_request_status_view(request, request_id):
    if request.method == 'POST':
        req = get_object_or_404(BloodRequest, id=request_id, seeker=request.user)
        new_status = request.POST.get('status')
        if new_status in ('fulfilled', 'cancelled', 'active'):
            req.status = new_status
            req.save()
            messages.success(request, f"Request status updated to {req.get_status_display()}.")
    return redirect('my_requests')

@login_required
def add_donation_view(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'donor':
        messages.error(request, "Only registered blood donors can log donation history.")
        return redirect('dashboard')

    if request.method == 'POST':
        profile = getattr(request.user, 'profile', None)
        if profile and profile.is_recently_donated:
            recent_info = profile.recent_donation_info
            don_dt = recent_info['donation_date']
            due_dt = recent_info['due_date']
            days_rem = recent_info['days_remaining']

            don_str = don_dt.strftime('%b %d, %Y') if (don_dt and hasattr(don_dt, 'strftime')) else str(don_dt)
            due_str = due_dt.strftime('%b %d, %Y') if (due_dt and hasattr(due_dt, 'strftime')) else str(due_dt)

            messages.warning(
                request,
                f"⚠️ Donation Restricted: You have already donated blood on {don_str}. "
                f"Standard 90-day medical recovery period applies. You cannot donate blood again until your due date on {due_str} ({days_rem} days remaining)."
            )
            return redirect('dashboard')

        form = DonationHistoryForm(request.POST)
        if form.is_valid():
            donation = form.save(commit=False)
            donation.donor = request.user
            donation.save()
            messages.success(request, f"Donation at {donation.location_hospital} successfully logged!")
        else:
            err_msgs = []
            for field, field_errs in form.errors.items():
                for err in field_errs:
                    err_msgs.append(f"{err}")
            messages.error(request, f"Failed to record donation: {'; '.join(err_msgs)}")
    return redirect('dashboard')

@login_required
def toggle_availability_view(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'donor':
        return JsonResponse({'status': 'error', 'message': 'Only blood donors can update emergency availability status.'}, status=403)

    if request.method == 'POST':
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.emergency_available = not profile.emergency_available
        profile.save()
        return JsonResponse({
            'status': 'success',
            'is_available': profile.emergency_available,
            'message': f"Status updated to {'Available' if profile.emergency_available else 'Unavailable'}."
        })
    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=400)

@login_required
def update_location_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            lat = data.get('latitude')
            lng = data.get('longitude')
        except (json.JSONDecodeError, AttributeError):
            lat = request.POST.get('latitude')
            lng = request.POST.get('longitude')

        if lat is not None and lng is not None:
            try:
                lat_val = float(lat)
                lng_val = float(lng)
                profile, _ = UserProfile.objects.get_or_create(user=request.user)
                profile.latitude = lat_val
                profile.longitude = lng_val
                profile.last_location_update = timezone.now()
                profile.save()
                return JsonResponse({
                    'status': 'success',
                    'message': 'Location coordinates updated on OpenStreetMap!',
                    'latitude': str(profile.latitude),
                    'longitude': str(profile.longitude),
                    'updated_at': profile.last_location_update.strftime('%b %d, %Y %I:%M %p')
                })
            except (ValueError, TypeError):
                return JsonResponse({'status': 'error', 'message': 'Invalid latitude or longitude values.'}, status=400)
        return JsonResponse({'status': 'error', 'message': 'Invalid latitude or longitude.'}, status=400)

    return JsonResponse({'status': 'error', 'message': 'POST method required.'}, status=405)

def password_reset_request_view(request):
    """Handles password reset requests by generating a secure token reset link."""
    if request.method == 'POST':
        email_or_phone = request.POST.get('email_or_phone', '').strip()
        user_target = User.objects.filter(
            models.Q(email__iexact=email_or_phone) |
            models.Q(username__iexact=email_or_phone) |
            models.Q(profile__phone_number__iexact=email_or_phone)
        ).first()

        if user_target:
            uid = urlsafe_base64_encode(force_bytes(user_target.pk))
            token = default_token_generator.make_token(user_target)
            from django.urls import reverse
            reset_url = reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
            messages.success(request, mark_safe(f"Password reset link generated! <a href='{reset_url}' style='color: #047857; font-weight: 800; text-decoration: underline; margin-left: 6px;'>Click here to reset your password now</a>."))
            return redirect('password_reset')
        else:
            messages.error(request, "No registered account found matching that email address or phone number.")
    return render(request, 'password_reset.html')

def password_reset_confirm_view(request, uidb64, token):
    """Verifies password reset token and allows setting a new password."""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        target_user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        target_user = None

    if target_user is not None and default_token_generator.check_token(target_user, token):
        if request.method == 'POST':
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')
            if not new_password or len(new_password) < 6:
                messages.error(request, "Password must be at least 6 characters long.")
            elif new_password != confirm_password:
                messages.error(request, "Passwords do not match.")
            else:
                target_user.set_password(new_password)
                target_user.save()
                messages.success(request, "Your password has been updated successfully! You can now sign in with your new password.")
                return redirect('login')
        return render(request, 'password_reset_confirm.html', {'target_user': target_user, 'uidb64': uidb64, 'token': token})
    else:
        messages.error(request, "The password reset link is invalid or has expired.")
        return redirect('password_reset')

@login_required
def admin_dashboard_view(request):
    if not request.user.is_superuser:
        messages.error(request, "Access restricted to administrators.")
        return redirect('dashboard')

    pending_users = UserProfile.objects.filter(is_approved=False).select_related('user')
    approved_users = UserProfile.objects.filter(is_approved=True).select_related('user')
    
    role_filter = request.GET.get('role', 'all')
    if role_filter != 'all':
        approved_users = approved_users.filter(role=role_filter)

    today = timezone.now().date()
    first_day_this_month = today.replace(day=1)

    # 6 KPI Summary Metrics
    total_donors = UserProfile.objects.filter(role='donor').count()
    active_donors = UserProfile.objects.filter(role='donor', is_approved=True, emergency_available=True).count()
    emergency_requests_count = BloodRequest.objects.count()
    requests_fulfilled_count = BloodRequest.objects.filter(status='fulfilled').count()
    verified_hospitals_count = UserProfile.objects.filter(role='hospital', is_approved=True).count()
    donations_this_month_count = DonationHistory.objects.filter(donation_date__gte=first_day_this_month, status='completed').count()

    # Chart 1: Blood Demand by Group
    bg_list = ['A+', 'O+', 'B+', 'AB+', 'A-', 'O-', 'B-', 'AB-']
    blood_demand_data = []
    total_req_all = max(1, emergency_requests_count)
    max_bg_req = 1
    
    bg_counts = {}
    for bg in bg_list:
        cnt = BloodRequest.objects.filter(blood_group=bg).count()
        bg_counts[bg] = cnt
        if cnt > max_bg_req:
            max_bg_req = cnt

    for bg in bg_list:
        cnt = bg_counts[bg]
        pct = round((cnt / total_req_all) * 100, 1) if emergency_requests_count > 0 else 0
        bar_pct = round((cnt / max_bg_req) * 100, 1) if max_bg_req > 0 else 0
        blood_demand_data.append({
            'blood_group': bg,
            'count': cnt,
            'percentage': pct,
            'bar_width': max(bar_pct, 6 if cnt > 0 else 0)
        })

    # Chart 2: Requests by Division
    div_list = ['Dhaka', 'Chattogram', 'Sylhet', 'Rajshahi', 'Khulna', 'Barishal', 'Rangpur', 'Mymensingh']
    requests_by_division_data = []
    max_div_req = 1

    div_counts = {}
    for div in div_list:
        cnt = BloodRequest.objects.filter(division=div).count()
        div_counts[div] = cnt
        if cnt > max_div_req:
            max_div_req = cnt

    for div in div_list:
        cnt = div_counts[div]
        pct = round((cnt / total_req_all) * 100, 1) if emergency_requests_count > 0 else 0
        bar_pct = round((cnt / max_div_req) * 100, 1) if max_div_req > 0 else 0
        requests_by_division_data.append({
            'division': div,
            'count': cnt,
            'percentage': pct,
            'bar_width': max(bar_pct, 6 if cnt > 0 else 0)
        })

    context = {
        'pending_users': pending_users,
        'approved_users': approved_users,
        'role_filter': role_filter,
        'total_pending': pending_users.count(),
        'total_approved': approved_users.count(),
        'total_donors': total_donors,
        'active_donors': active_donors,
        'emergency_requests_count': emergency_requests_count,
        'requests_fulfilled_count': requests_fulfilled_count,
        'verified_hospitals_count': verified_hospitals_count,
        'donations_this_month_count': donations_this_month_count,
        'blood_demand_data': blood_demand_data,
        'requests_by_division_data': requests_by_division_data,
    }
    return render(request, 'admin_dashboard.html', context)

@login_required
def approve_user_view(request, user_id):
    if not request.user.is_superuser:
        messages.error(request, "Access restricted to administrators.")
        return redirect('dashboard')

    profile = get_object_or_404(UserProfile, id=user_id)
    profile.is_approved = True
    profile.save()
    messages.success(request, f"Approved account for {get_user_full_name(profile.user)} ({profile.get_role_display()})!")
    return redirect('dashboard')

@login_required
def print_donation_history_pdf_view(request):
    """Generates printable PDF reports for donors, seekers, hospitals, or admin 6-month reports."""
    user = request.user
    target_user_id = request.GET.get('target_user_id')
    report_type = request.GET.get('report_type')

    if user.is_superuser and target_user_id:
        target_profile = get_object_or_404(UserProfile, id=target_user_id)
        user = target_profile.user
        profile = target_profile
    else:
        profile, _ = UserProfile.objects.get_or_create(user=user)

    six_months_ago = timezone.now().date() - timedelta(days=180)

    if request.user.is_superuser and report_type == '6months':
        donations = DonationHistory.objects.filter(donation_date__gte=six_months_ago).order_by('-donation_date')
        requests = BloodRequest.objects.filter(created_at__gte=six_months_ago).order_by('-created_at')
        is_6mo_report = True
    else:
        donations = DonationHistory.objects.filter(donor=user).order_by('-donation_date')
        requests = BloodRequest.objects.filter(seeker=user).order_by('-created_at')
        is_6mo_report = False

    hospital_verified = []
    if profile.role == 'hospital' and not is_6mo_report:
        hospital_name = get_user_full_name(user)
        hospital_verified = DonationHistory.objects.filter(location_hospital__icontains=hospital_name).order_by('-donation_date')

    context = {
        'user': user,
        'profile': profile,
        'donations': donations,
        'requests': requests,
        'hospital_verified': hospital_verified,
        'is_6mo_report': is_6mo_report,
        'generated_at': timezone.now(),
    }
    return render(request, 'donation_history_pdf.html', context)

@login_required
def mark_notifications_read_view(request):
    if request.method == 'POST':
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        return JsonResponse({'status': 'success', 'message': 'Notifications marked as read.'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=400)


