import json
from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
from donors.models import UserProfile, DonationHistory, BloodRequest, BloodRequestResponse, HospitalInventory, Notification, haversine_distance, is_blood_compatible, get_compatible_donor_groups, calculate_donor_suitability_score, auto_expire_old_requests

class LifeFlowModelsAndUtilsTestCase(TestCase):
    def test_haversine_distance(self):
        # Distance between Dhaka (23.8103, 90.4125) and Chattogram (22.3569, 91.7832) is ~216 km
        dist = haversine_distance(23.8103, 90.4125, 22.3569, 91.7832)
        self.assertIsNotNone(dist)
        self.assertGreater(dist, 200)
        self.assertLess(dist, 250)

    def test_blood_compatibility(self):
        # O- can donate to A+
        self.assertTrue(is_blood_compatible('O-', 'A+'))
        # A+ cannot donate to O-
        self.assertFalse(is_blood_compatible('A+', 'O-'))
        # Compatible donors for A+ include O-, O+, A-, A+
        comp_bgs = get_compatible_donor_groups('A+')
        self.assertIn('O-', comp_bgs)
        self.assertIn('A+', comp_bgs)
        self.assertNotIn('B+', comp_bgs)

class LifeFlowAuthenticationTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(username='admin@lifeflow.bd', email='admin@lifeflow.bd', password='adminpassword')
        UserProfile.objects.create(user=self.admin, role='admin', is_approved=True)

    def test_registration_and_admin_approval_workflow(self):
        # 1. User Registration
        response = self.client.post(reverse('register'), {
            'full_name': 'Test Donor',
            'email': 'donor@test.com',
            'phone_number': '+8801711111111',
            'password': 'Password123!',
            'confirm_password': 'Password123!',
            'role': 'donor',
            'division': 'Dhaka',
            'district': 'Mirpur',
            'blood_group': 'O+',
            'emergency_available': 'true'
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email='donor@test.com')
        self.assertFalse(user.profile.is_approved)

        # 2. Attempt login before admin approval -> should fail
        login_res = self.client.post(reverse('login'), {
            'username_or_phone': 'donor@test.com',
            'password': 'Password123!'
        })
        self.assertEqual(login_res.status_code, 200)
        self.assertIn('Your account is pending Admin approval', login_res.content.decode())

        # 3. Admin logs in and approves donor
        self.client.force_login(self.admin)
        approve_res = self.client.post(reverse('approve_user', args=[user.profile.id]))
        self.assertEqual(approve_res.status_code, 302)
        user.profile.refresh_from_db()
        self.assertTrue(user.profile.is_approved)
        self.client.logout()

        # 4. Login after approval -> success
        login_res_2 = self.client.post(reverse('login'), {
            'username_or_phone': 'donor@test.com',
            'password': 'Password123!'
        })
        self.assertEqual(login_res_2.status_code, 302)

class LifeFlowDonorPortalTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.donor_user = User.objects.create_user(username='donor@lifeflow.bd', email='donor@lifeflow.bd', password='password123')
        self.donor_profile = UserProfile.objects.create(
            user=self.donor_user,
            role='donor',
            blood_group='A+',
            division='Dhaka',
            district='Uttara',
            phone_number='+8801722222222',
            emergency_available=True,
            is_approved=True,
            latitude=23.8759,
            longitude=90.3795
        )
        self.client.force_login(self.donor_user)

    def test_toggle_availability_api(self):
        res = self.client.post(reverse('toggle_availability'))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        self.assertFalse(data['is_available'])
        self.donor_profile.refresh_from_db()
        self.assertFalse(self.donor_profile.emergency_available)

    def test_update_location_api(self):
        res = self.client.post(
            reverse('update_location'),
            data=json.dumps({'latitude': 23.8103, 'longitude': 90.4125}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        self.donor_profile.refresh_from_db()
        self.assertEqual(float(self.donor_profile.latitude), 23.8103)

    def test_add_donation_and_90_day_restriction(self):
        # 1. Log a donation
        res1 = self.client.post(reverse('add_donation'), {
            'donation_date': timezone.now().date(),
            'location_hospital': 'Dhaka Medical College Hospital',
            'recipient_name': 'Emergency Patient',
            'units_donated': 1,
            'notes': 'First donation'
        })
        self.assertEqual(res1.status_code, 302)
        self.assertEqual(DonationHistory.objects.filter(donor=self.donor_user).count(), 1)
        self.assertTrue(self.donor_profile.is_recently_donated)

        # 2. Attempt to log a second donation within 90 days -> Warning & blocked
        res2 = self.client.post(reverse('add_donation'), {
            'donation_date': timezone.now().date(),
            'location_hospital': 'Square Hospital',
            'units_donated': 1
        })
        self.assertEqual(res2.status_code, 302)
        self.assertEqual(DonationHistory.objects.filter(donor=self.donor_user).count(), 1)

class LifeFlowHospitalPortalTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        # Create Hospital user
        self.hospital_user = User.objects.create_user(username='hospital@square.com', email='hospital@square.com', password='password123', first_name='Square Hospital')
        self.hospital_profile = UserProfile.objects.create(
            user=self.hospital_user,
            role='hospital',
            division='Dhaka',
            district='Dhanmondi',
            phone_number='+8801733333333',
            is_approved=True
        )
        # Create Donor user
        self.donor_user = User.objects.create_user(username='donor2@lifeflow.bd', email='donor2@lifeflow.bd', password='password123')
        self.donor_profile = UserProfile.objects.create(
            user=self.donor_user,
            role='donor',
            blood_group='B+',
            phone_number='+8801744444444',
            is_approved=True
        )
        # Create Seeker user & Blood Request
        self.seeker_user = User.objects.create_user(username='seeker@lifeflow.bd', email='seeker@lifeflow.bd', password='password123')
        UserProfile.objects.create(user=self.seeker_user, role='seeker', is_approved=True)
        self.request_obj = BloodRequest.objects.create(
            seeker=self.seeker_user,
            patient_name='Emergency Patient 1',
            blood_group='B+',
            units_required=2,
            hospital_name='Square Hospital',
            division='Dhaka',
            district='Dhanmondi',
            urgency='immediate',
            contact_phone='+8801755555555'
        )
        self.client.force_login(self.hospital_user)

    def test_update_hospital_inventory(self):
        res = self.client.post(reverse('update_hospital_inventory'), {
            'blood_group': 'B+',
            'units': 5
        })
        self.assertEqual(res.status_code, 302)
        inv = HospitalInventory.objects.get(hospital=self.hospital_user, blood_group='B+')
        self.assertEqual(inv.units, 5)

    def test_hospital_verify_donation(self):
        res = self.client.post(reverse('hospital_verify_donation'), {
            'donor_phone': '+8801744444444',
            'units_donated': 2,
            'recipient_name': 'Hospital Blood Bank Stock',
            'notes': 'Verified blood drive donation'
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(DonationHistory.objects.filter(donor=self.donor_user).count(), 1)
        inv = HospitalInventory.objects.get(hospital=self.hospital_user, blood_group='B+')
        self.assertEqual(inv.units, 2)

    def test_fulfill_request_with_stock(self):
        # Stock 3 units of B+
        HospitalInventory.objects.create(hospital=self.hospital_user, blood_group='B+', units=3)
        res = self.client.post(reverse('fulfill_request_with_stock', args=[self.request_obj.id]))
        self.assertEqual(res.status_code, 302)
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, 'fulfilled')
        inv = HospitalInventory.objects.get(hospital=self.hospital_user, blood_group='B+')
        self.assertEqual(inv.units, 1)

    def test_direct_request_to_hospital_stock_and_fulfillment(self):
        # 1. Seeker directly requests hospital stock for B+
        self.client.force_login(self.seeker_user)
        HospitalInventory.objects.create(hospital=self.hospital_user, blood_group='B+', units=5)
        res = self.client.post(reverse('post_request'), {
            'direct_request': 'true',
            'target_donor_id': self.hospital_user.id,
            'blood_group': 'B+'
        })
        self.assertEqual(res.status_code, 302)

        req = BloodRequest.objects.filter(target_donor=self.hospital_user).first()
        self.assertIsNotNone(req)
        self.assertEqual(req.blood_group, 'B+')

        # Seeker checks my_requests view -> requested_target_ids includes hospital
        res_seeker = self.client.get(reverse('my_requests'))
        self.assertEqual(res_seeker.status_code, 200)

        # 2. Hospital views dashboard and sees targeted request
        self.client.force_login(self.hospital_user)
        dash_res = self.client.get(reverse('dashboard'))
        self.assertEqual(dash_res.status_code, 200)
        active_reqs = dash_res.context['all_active_requests']
        targeted_req = next((r for r in active_reqs if r['object'].id == req.id), None)
        self.assertIsNotNone(targeted_req)
        self.assertTrue(targeted_req['is_targeted'])

        # 3. Hospital accepts & fulfills request with stock
        ful_res = self.client.post(reverse('fulfill_request_with_stock', args=[req.id]))
        self.assertEqual(ful_res.status_code, 302)

        req.refresh_from_db()
        self.assertEqual(req.status, 'fulfilled')
        resp = BloodRequestResponse.objects.filter(request=req, donor=self.hospital_user).first()
        self.assertIsNotNone(resp)
        self.assertTrue(resp.is_hospital)

        # 4. Seeker sees fulfilled hospital response in my_requests
        self.client.force_login(self.seeker_user)
        my_req_res = self.client.get(reverse('my_requests'))
        self.assertEqual(my_req_res.status_code, 200)
        self.assertIn('Hospital Supply Notice', my_req_res.content.decode())

class LifeFlowFindDonorsSearchTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        # Create available donors
        self.donor_o_minus = User.objects.create_user(username='o_minus@test.com', password='password123', first_name='O Minus Donor')
        UserProfile.objects.create(
            user=self.donor_o_minus,
            role='donor',
            blood_group='O-',
            division='Dhaka',
            district='Mirpur',
            emergency_available=True,
            is_approved=True,
            latitude=23.805,
            longitude=90.365
        )
        self.donor_ab_plus = User.objects.create_user(username='ab_plus@test.com', password='password123', first_name='AB Plus Donor')
        UserProfile.objects.create(
            user=self.donor_ab_plus,
            role='donor',
            blood_group='AB+',
            division='Chattogram',
            district='Feni',
            emergency_available=True,
            is_approved=True
        )

    def test_find_donors_compatible_search(self):
        # Search for A+ with compatible match mode (should find O- donor, but not AB+)
        res = self.client.get(reverse('find_donors'), {'blood_group': 'A+', 'match_type': 'compatible'})
        self.assertEqual(res.status_code, 200)
        donors = res.context['donors']
        donor_names = [d['name'] for d in donors]
        self.assertIn('O-, Donor', donor_names)
        self.assertNotIn('AB+, Donor', donor_names)

    def test_find_donors_exact_search(self):
        # Search for A+ with exact match mode (should find neither O- nor AB+)
        res = self.client.get(reverse('find_donors'), {'blood_group': 'A+', 'match_type': 'exact'})
        self.assertEqual(res.status_code, 200)
        donors = res.context['donors']
        self.assertEqual(len(donors), 0)

    def test_pdf_report_view(self):
        self.client.force_login(self.donor_o_minus)
        res = self.client.get(reverse('print_donation_history_pdf') + '?print=1')
        self.assertEqual(res.status_code, 200)
        self.assertIn('LifeFlow BD', res.content.decode())

    def test_one_click_direct_request(self):
        self.client.force_login(self.donor_ab_plus)
        res = self.client.post(reverse('post_request'), {
            'direct_request': 'true',
            'target_donor_id': self.donor_o_minus.id
        })
        self.assertEqual(res.status_code, 302)
        req = BloodRequest.objects.filter(target_donor=self.donor_o_minus).first()
        self.assertIsNotNone(req)
        self.assertEqual(req.status, 'active')
        self.assertEqual(req.target_donor, self.donor_o_minus)

        # Verify notification created for target donor
        notif = Notification.objects.filter(recipient=self.donor_o_minus).first()
        self.assertIsNotNone(notif)
        self.assertIn("Direct Blood Request", notif.title)

    def test_notifications_workflow_on_response(self):
        # 1. Seeker posts request
        seeker = User.objects.create_user(username='seeker_notif@test.com', password='password123')
        UserProfile.objects.create(user=seeker, role='seeker', is_approved=True)
        self.client.force_login(seeker)
        req = BloodRequest.objects.create(
            seeker=seeker,
            patient_name='Emergency Patient',
            blood_group='O-',
            units_required=1,
            hospital_name='Dhaka Hospital',
            division='Dhaka',
            district='Mirpur'
        )

        # 2. Donor responds to request
        self.client.force_login(self.donor_o_minus)
        res = self.client.post(reverse('respond_to_request', args=[req.id]), {'donor_message': 'I can donate.'})
        self.assertEqual(res.status_code, 302)

        # 3. Check seeker received notification
        notif = Notification.objects.filter(recipient=seeker).first()
        self.assertIsNotNone(notif)
        self.assertIn("Someone responded to your blood request", notif.title)

    def test_strict_blood_compatibility_rules(self):
        # A+ donor for B- recipient
        donor_a_plus = User.objects.create_user(username='a_plus_donor@test.com', password='password123')
        a_profile = UserProfile.objects.create(user=donor_a_plus, role='donor', blood_group='A+', is_approved=True)

        # 1. Check AI suitability score is 0 / Incompatible for B-
        score_res = calculate_donor_suitability_score(a_profile, recipient_bg='B-')
        self.assertEqual(score_res['score'], 0)
        self.assertEqual(score_res['label'], 'Incompatible Blood Group')

        # 2. Direct request to A+ donor for B- patient should be blocked
        seeker = User.objects.create_user(username='seeker_b_minus@test.com', password='password123')
        UserProfile.objects.create(user=seeker, role='seeker', is_approved=True)
        self.client.force_login(seeker)

        res = self.client.post(reverse('post_request'), {
            'direct_request': 'true',
            'target_donor_id': donor_a_plus.id,
            'blood_group': 'B-'
        })
        self.assertEqual(res.status_code, 302)
        self.assertFalse(BloodRequest.objects.filter(target_donor=donor_a_plus, blood_group='B-').exists())

class LifeFlowRoleProtectionTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # Donor User
        self.donor_user = User.objects.create_user(username='donor_role_test@test.com', password='password123')
        self.donor_profile = UserProfile.objects.create(user=self.donor_user, role='donor', blood_group='O+', is_approved=True)

        # Seeker User
        self.seeker_user = User.objects.create_user(username='seeker_role_test@test.com', password='password123')
        self.seeker_profile = UserProfile.objects.create(user=self.seeker_user, role='seeker', is_approved=True)

        # Hospital User
        self.hospital_user = User.objects.create_user(username='hospital_role_test@test.com', password='password123')
        self.hospital_profile = UserProfile.objects.create(user=self.hospital_user, role='hospital', is_approved=True)

        # Active Blood Request
        self.blood_request = BloodRequest.objects.create(
            seeker=self.seeker_user,
            patient_name='Test Patient',
            blood_group='O+',
            units_required=1,
            hospital_name='Test Hospital',
            division='Dhaka',
            district='Mirpur'
        )

    def test_non_hospital_cannot_update_inventory(self):
        self.client.force_login(self.donor_user)
        res = self.client.post(reverse('update_hospital_inventory'), {'blood_group': 'O+', 'units': 100})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(HospitalInventory.objects.filter(hospital=self.donor_user).count(), 0)

    def test_non_hospital_cannot_verify_donation(self):
        self.client.force_login(self.seeker_user)
        res = self.client.post(reverse('hospital_verify_donation'), {
            'donor_phone': self.donor_profile.phone_number,
            'units_donated': 1
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(DonationHistory.objects.filter(donor=self.donor_user).count(), 0)

    def test_non_hospital_cannot_fulfill_request_with_stock(self):
        self.client.force_login(self.donor_user)
        res = self.client.post(reverse('fulfill_request_with_stock', args=[self.blood_request.id]))
        self.assertEqual(res.status_code, 302)
        self.blood_request.refresh_from_db()
        self.assertNotEqual(self.blood_request.status, 'fulfilled')

    def test_non_donor_cannot_add_donation_history(self):
        self.client.force_login(self.hospital_user)
        res = self.client.post(reverse('add_donation'), {
            'donation_date': timezone.now().date(),
            'location_hospital': 'Fake Hospital',
            'units_donated': 1
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(DonationHistory.objects.filter(donor=self.hospital_user).count(), 0)

    def test_non_donor_cannot_toggle_availability(self):
        self.client.force_login(self.hospital_user)
        res = self.client.post(reverse('toggle_availability'))
        self.assertEqual(res.status_code, 403)

    def test_non_donor_cannot_respond_to_request(self):
        self.client.force_login(self.hospital_user)
        res = self.client.post(reverse('respond_to_request', args=[self.blood_request.id]), {'donor_message': 'Hospital offering'})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(BloodRequestResponse.objects.filter(request=self.blood_request, donor=self.hospital_user).count(), 0)

    def test_future_donation_date_is_rejected(self):
        self.client.force_login(self.donor_user)
        future_date = timezone.now().date() + timedelta(days=30)
        res = self.client.post(reverse('add_donation'), {
            'donation_date': future_date,
            'location_hospital': 'Future Hospital',
            'units_donated': 1
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(DonationHistory.objects.filter(donor=self.donor_user).count(), 0)

    def test_donor_contact_info_is_masked_on_search(self):
        res = self.client.get(reverse('find_donors'), {'blood_group': 'O+'})
        self.assertEqual(res.status_code, 200)
        donors = res.context['donors']
        self.assertGreater(len(donors), 0)
        for d in donors:
            self.assertEqual(d['name'], 'O+, Donor')
            self.assertEqual(d['phone'], '')

    def test_calculate_donor_suitability_score(self):
        res = calculate_donor_suitability_score(self.donor_profile, recipient_bg='O+', distance_km=3.5)
        self.assertIsInstance(res['score'], int)
        self.assertGreaterEqual(res['score'], 80)
        self.assertEqual(res['label'], 'Highly Suitable')
        self.assertIn("3.5 km away", " ".join(res['reasons']))

    def test_atomic_transaction_stock_fulfillment(self):
        HospitalInventory.objects.create(hospital=self.hospital_user, blood_group='O+', units=2)
        self.client.force_login(self.hospital_user)
        res = self.client.post(reverse('fulfill_request_with_stock', args=[self.blood_request.id]))
        self.assertEqual(res.status_code, 302)
        self.blood_request.refresh_from_db()
        self.assertEqual(self.blood_request.status, 'fulfilled')
        inv = HospitalInventory.objects.get(hospital=self.hospital_user, blood_group='O+')
        self.assertEqual(inv.units, 1)

    def test_auto_expire_old_requests(self):
        old_req = BloodRequest.objects.create(
            seeker=self.seeker_user,
            patient_name='Old Patient',
            blood_group='O+',
            units_required=1,
            hospital_name='Old Hospital',
            division='Dhaka',
            district='Mirpur',
            urgency='immediate',
            created_at=timezone.now() - timedelta(hours=30)
        )
        # Manually backdate created_at timestamp
        BloodRequest.objects.filter(id=old_req.id).update(created_at=timezone.now() - timedelta(hours=30))
        auto_expire_old_requests()
        old_req.refresh_from_db()
        self.assertEqual(old_req.status, 'expired')
        self.assertTrue(old_req.is_expired)

    def test_notification_schema_and_types(self):
        notif = Notification.objects.create(
            recipient=self.donor_user,
            sender=self.seeker_user,
            title='Emergency Blood Request',
            message='A+ blood required at Square Hospital. Approximately 3.2 km away.',
            notification_type='emergency_request',
            related_request=self.blood_request
        )
        self.assertEqual(notif.notification_type, 'emergency_request')
        self.assertEqual(notif.related_request, self.blood_request)

    def test_password_reset_workflow(self):
        # 1. Request password reset
        res = self.client.post(reverse('password_reset'), {'email_or_phone': self.donor_user.email})
        self.assertEqual(res.status_code, 302)

        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        from django.contrib.auth.tokens import default_token_generator
        uid = urlsafe_base64_encode(force_bytes(self.donor_user.pk))
        token = default_token_generator.make_token(self.donor_user)

        # 2. Confirm password reset
        confirm_url = reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
        res_confirm = self.client.post(confirm_url, {
            'new_password': 'NewPassword123!',
            'confirm_password': 'NewPassword123!'
        })
        self.assertEqual(res_confirm.status_code, 302)

        # 3. Verify user can log in with new password
        self.donor_user.refresh_from_db()
        self.assertTrue(self.donor_user.check_password('NewPassword123!'))

    def test_admin_dashboard_kpis_and_charts(self):
        admin = User.objects.create_superuser(username='admin_test@lifeflow.bd', email='admin_test@lifeflow.bd', password='password123')
        UserProfile.objects.create(user=admin, role='admin', is_approved=True)
        self.client.force_login(admin)

        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertIn('total_donors', res.context)
        self.assertIn('active_donors', res.context)
        self.assertIn('emergency_requests_count', res.context)
        self.assertIn('requests_fulfilled_count', res.context)
        self.assertIn('verified_hospitals_count', res.context)
        self.assertIn('blood_demand_data', res.context)
        self.assertIn('requests_by_division_data', res.context)

    def test_direct_request_form_prefilling(self):
        self.client.force_login(self.seeker_user)
        url = reverse('post_request') + f"?target_donor_id={self.donor_user.id}&blood_group=A%2B&division=Dhaka&district=Mirpur"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['target_donor'], self.donor_user)
        self.assertEqual(res.context['form']['blood_group'].value(), 'A+')

    def test_unapproved_hospital_cannot_verify_donation(self):
        unapproved_hospital = User.objects.create_user(username='unapproved_hosp@test.com', password='password123')
        UserProfile.objects.create(user=unapproved_hospital, role='hospital', is_approved=False)
        self.client.force_login(unapproved_hospital)

        res = self.client.post(reverse('hospital_verify_donation'), {
            'donor_phone': self.donor_profile.phone_number,
            'units_donated': 1
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(DonationHistory.objects.filter(donor=self.donor_user).count(), 0)

    def test_hospital_verification_certificate_generation(self):
        self.client.force_login(self.hospital_user)
        res = self.client.post(reverse('hospital_verify_donation'), {
            'donor_phone': self.donor_profile.phone_number,
            'units_donated': 2,
            'recipient_name': 'Emergency Patient',
            'notes': 'Verified blood drive donation'
        })
        self.assertEqual(res.status_code, 302)

        donation = DonationHistory.objects.filter(donor=self.donor_user).first()
        self.assertIsNotNone(donation)
        self.assertIsNotNone(donation.verification_id)
        self.assertTrue(donation.verification_id.startswith('LIFE-CERT-'))
        self.assertEqual(donation.verified_by_hospital, self.hospital_user)

    def test_ai_chatbot_api_response(self):
        self.client.force_login(self.donor_user)
        res = self.client.post(
            reverse('chatbot_api'),
            data=json.dumps({'query': 'Am I eligible to donate blood?'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('Eligibility', data['reply'])






