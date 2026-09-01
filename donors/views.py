import json
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.contrib.auth.models import User

from .models import UserProfile, DonationHistory, BloodRequest, BloodRequestResponse, HospitalInventory, haversine_distance, get_user_full_name, BLOOD_GROUP_CHOICES, is_blood_compatible, get_compatible_donor_groups
from .forms import UserRegistrationForm, UserLoginForm, DonationHistoryForm, BloodRequestForm

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

    profile, _ = UserProfile.objects.get_or_create(user=user)

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

    # Active Emergency Blood Requests for donor overview
    active_requests_qs = BloodRequest.objects.filter(status='active').order_by('-created_at')[:10]
    user_responses = set(BloodRequestResponse.objects.filter(donor=user).values_list('request_id', flat=True))
    
    emergency_requests = []
    for req in active_requests_qs:
        emergency_requests.append({
            'object': req,
            'has_responded': req.id in user_responses,
            'is_compatible': is_blood_compatible(profile.blood_group, req.blood_group)
        })

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
    }
    return render(request, 'dashboard.html', context)

@login_required
def seeker_dashboard_view(request):
    user = request.user
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

    context = {
        'profile': profile,
        'my_requests': my_requests[:5],
        'active_count': active_requests.count(),
        'fulfilled_count': fulfilled_requests.count(),
        'total_requests_count': my_requests.count(),
        'nearby_donors_count': nearby_donors_count,
    }
    return render(request, 'seeker_dashboard.html', context)

@login_required
def hospital_dashboard_view(request):
    """Hospital Blood Bank Inventory & Verification Dashboard."""
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)

    valid_bg_codes = [bg[0] for bg in BLOOD_GROUP_CHOICES]

    # Initialize standard blood groups in inventory if not present
    for bg_code in valid_bg_codes:
        HospitalInventory.objects.get_or_create(hospital=user, blood_group=bg_code)

    inventory_qs = HospitalInventory.objects.filter(hospital=user, blood_group__in=valid_bg_codes).order_by('blood_group')
    inventory_stock_dict = {inv.blood_group: inv.units for inv in inventory_qs}

    total_units_in_stock = sum(inv.units for inv in inventory_qs)
    
    # Requests posted by this hospital
    my_hospital_requests = BloodRequest.objects.filter(seeker=user)
    
    # All active emergency blood requests across the system
    all_active_requests_qs = BloodRequest.objects.filter(status='active').order_by('-created_at')[:10]
    
    all_active_requests = []
    for req in all_active_requests_qs:
        stock_count = inventory_stock_dict.get(req.blood_group, 0)
        all_active_requests.append({
            'object': req,
            'stock_units': stock_count,
            'has_stock': stock_count >= req.units_required,
            'is_own': req.seeker == user
        })

    context = {
        'profile': profile,
        'inventory': inventory_qs,
        'total_units_in_stock': total_units_in_stock,
        'hospital_requests': my_hospital_requests[:5],
        'my_requests_count': my_hospital_requests.filter(status='active').count(),
        'all_active_requests': all_active_requests,
        'active_requests_count': BloodRequest.objects.filter(status='active').count(),
    }
    return render(request, 'hospital_dashboard.html', context)

@login_required
def update_hospital_inventory_view(request):
    """Updates blood bank unit stock for a blood group."""
    if request.method == 'POST':
        blood_group = request.POST.get('blood_group')
        try:
            units = max(0, int(request.POST.get('units', 0)))
            inv, _ = HospitalInventory.objects.get_or_create(hospital=request.user, blood_group=blood_group)
            inv.units = units
            inv.save()
            messages.success(request, f"Updated {blood_group} stock to {units} unit(s).")
        except ValueError:
            messages.error(request, "Invalid unit quantity.")
    return redirect('dashboard')

@login_required
def hospital_verify_donation_view(request):
    """Allows hospital to record and verify a donor's blood donation."""
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
            DonationHistory.objects.create(
                donor=donor_profile.user,
                donation_date=timezone.now().date(),
                location_hospital=hospital_name,
                recipient_name=recipient or "Hospital Stock",
                units_donated=units,
                status='completed',
                notes=notes or "Verified by Hospital"
            )
            # Update hospital stock inventory upon donation verification
            inv, _ = HospitalInventory.objects.get_or_create(hospital=request.user, blood_group=donor_profile.blood_group)
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
        req = get_object_or_404(BloodRequest, id=request_id, status='active')
        inv, _ = HospitalInventory.objects.get_or_create(hospital=request.user, blood_group=req.blood_group)

        if inv.units < req.units_required:
            messages.error(request, f"Insufficient {req.blood_group} stock! You have {inv.units} unit(s), but request requires {req.units_required} unit(s).")
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

            messages.success(request, f"Supplied {req.units_required} bag(s) of {req.blood_group} stock for {req.patient_name}! Request marked as Fulfilled.")

    return redirect('dashboard')

def find_donors_view(request):
    blood_group = request.GET.get('blood_group', '').strip()
    division = request.GET.get('division', '').strip()
    district = request.GET.get('district', '').strip()
    availability = request.GET.get('availability', 'available')
    radius_str = request.GET.get('radius', 'all')
    seeker_lat = request.GET.get('lat')
    seeker_lng = request.GET.get('lng')

    donors_qs = UserProfile.objects.filter(role='donor', is_approved=True).select_related('user')

    if availability == 'available':
        donors_qs = donors_qs.filter(emergency_available=True)
    if blood_group:
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

        donor_data = {
            'id': d.id,
            'name': get_user_full_name(d.user),
            'blood_group': d.blood_group,
            'phone': d.phone_number,
            'division': d.division,
            'district': d.district,
            'is_available': d.emergency_available,
            'distance_km': dist,
            'lat': d_lat,
            'lng': d_lng,
            'last_update': d.last_location_update.strftime('%b %d, %Y') if d.last_location_update else None,
            'recent_info': recent_dict
        }
        donors_list.append(donor_data)

        if d_lat is not None and d_lng is not None:
            map_markers.append({
                'name': donor_data['name'],
                'blood_group': donor_data['blood_group'],
                'phone': donor_data['phone'],
                'location': f"{d.district}, {d.division}",
                'lat': d_lat,
                'lng': d_lng,
                'distance': f"{dist} km" if dist else "N/A",
                'available': d.emergency_available,
                'recently_donated': recent_dict['recently_donated'],
                'recent_donation_date': recent_dict['donation_date'],
                'next_due_date': recent_dict['due_date'],
            })

    if s_lat is not None and s_lng is not None:
        donors_list.sort(key=lambda x: (x['distance_km'] if x['distance_km'] is not None else 999999))
    else:
        donors_list.sort(key=lambda x: not x['is_available'])

    hospital_stock_qs = HospitalInventory.objects.filter(units__gt=0).select_related('hospital', 'hospital__profile')
    if blood_group:
        hospital_stock_qs = hospital_stock_qs.filter(blood_group=blood_group)
    if division:
        hospital_stock_qs = hospital_stock_qs.filter(hospital__profile__division=division)

    context = {
        'donors': donors_list,
        'matched_hospital_stocks': hospital_stock_qs,
        'map_markers_json': json.dumps(map_markers),
        'blood_group': blood_group,
        'division': division,
        'district': district,
        'availability': availability,
        'radius': radius_str,
        'seeker_lat': seeker_lat or '',
        'seeker_lng': seeker_lng or '',
        'blood_groups': [bg[0] for bg in BLOOD_GROUP_CHOICES],
        'total_results': len(donors_list),
    }
    return render(request, 'find_donors.html', context)

@login_required
def post_request_view(request):
    if request.method == 'POST':
        form = BloodRequestForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.seeker = request.user
            req.save()
            messages.success(request, f"Emergency Blood Request for {req.patient_name} ({req.blood_group}) posted successfully!")
            return redirect('my_requests')
        else:
            messages.error(request, "Failed to post blood request. Please check required fields.")
    else:
        profile = getattr(request.user, 'profile', None)
        form = BloodRequestForm(initial={
            'contact_phone': profile.phone_number if profile else '',
            'division': profile.division if profile else '',
            'district': profile.district if profile else '',
        })

    hospital_stocks = HospitalInventory.objects.filter(units__gt=0).select_related('hospital').order_by('blood_group')
    return render(request, 'post_request.html', {
        'form': form,
        'hospital_stocks': hospital_stocks
    })

@login_required
def my_requests_view(request):
    requests_qs = BloodRequest.objects.filter(seeker=request.user)
    active_requests = []
    for req in requests_qs:
        responses_qs = req.responses.all().select_related('donor', 'donor__profile')
        if req.status == 'active':
            matched_donors = UserProfile.objects.filter(
                role='donor',
                is_approved=True,
                emergency_available=True,
                blood_group=req.blood_group,
                division=req.division
            )[:5]
            h_stocks = HospitalInventory.objects.filter(
                blood_group=req.blood_group,
                units__gt=0
            ).select_related('hospital')
        else:
            matched_donors = UserProfile.objects.none()
            h_stocks = HospitalInventory.objects.none()

        active_requests.append({
            'object': req,
            'responses': responses_qs,
            'matched_donors': matched_donors,
            'hospital_stocks': h_stocks
        })

    context = {
        'requests_with_donors': active_requests,
        'total_count': requests_qs.count(),
    }
    return render(request, 'my_requests.html', context)

@login_required
def respond_to_request_view(request, request_id):
    req = get_object_or_404(BloodRequest, id=request_id, status='active')
    profile = getattr(request.user, 'profile', None)

    if profile and profile.role != 'donor':
        messages.error(request, "Only registered blood donors can respond to emergency blood requests.")
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
    if request.method == 'POST':
        form = DonationHistoryForm(request.POST)
        if form.is_valid():
            donation = form.save(commit=False)
            donation.donor = request.user
            donation.save()
            messages.success(request, f"Donation at {donation.location_hospital} successfully logged!")
        else:
            messages.error(request, "Failed to record donation. Please verify input fields.")
    return redirect('dashboard')

@login_required
def toggle_availability_view(request):
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

    six_months_ago = timezone.now().date() - timedelta(days=180)
    donations_6mo_count = DonationHistory.objects.filter(donation_date__gte=six_months_ago, status='completed').count()

    context = {
        'pending_users': pending_users,
        'approved_users': approved_users,
        'role_filter': role_filter,
        'total_pending': pending_users.count(),
        'total_approved': approved_users.count(),
        'donations_6mo_count': donations_6mo_count,
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

