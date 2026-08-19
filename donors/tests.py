from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from donors.models import UserProfile, DonationHistory, BloodRequest, BloodRequestResponse, HospitalInventory, haversine_distance

class DonorSeekerAndHospitalModuleTests(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Approved Donor User
        self.donor_user = User.objects.create_user(
            username='+8801712345678',
            email='donor@lifeflow.bd',
            password='password123',
            first_name='Rahim',
            last_name='Uddin'
        )
        self.donor_profile = UserProfile.objects.create(
            user=self.donor_user,
            role='donor',
            phone_number='+8801712345678',
            division='Dhaka',
            district='Dhaka City',
            blood_group='O+',
            emergency_available=True,
            is_approved=True,
            latitude=23.8103,
            longitude=90.4125
        )

        # Approved Seeker User
        self.seeker_user = User.objects.create_user(
            username='+8801812345678',
            email='seeker@lifeflow.bd',
            password='password123',
            first_name='Karim',
            last_name='Hassan'
        )
        self.seeker_profile = UserProfile.objects.create(
            user=self.seeker_user,
            role='seeker',
            phone_number='+8801812345678',
            division='Dhaka',
            district='Dhaka City',
            is_approved=True
        )

        # Approved Hospital User
        self.hospital_user = User.objects.create_user(
            username='+8801912345678',
            email='hospital@dmc.bd',
            password='password123',
            first_name='Dhaka Medical College',
            last_name='Hospital'
        )
        self.hospital_profile = UserProfile.objects.create(
            user=self.hospital_user,
            role='hospital',
            phone_number='+8801912345678',
            division='Dhaka',
            district='Dhaka City',
            is_approved=True
        )

    def test_haversine_distance_calculation(self):
        dist = haversine_distance(23.7461, 90.3742, 23.7925, 90.4078)
        self.assertIsNotNone(dist)
        self.assertGreater(dist, 3.0)
        self.assertLess(dist, 8.0)

    def test_hospital_dashboard_and_inventory_initialization(self):
        self.client.login(username='+8801912345678', password='password123')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'hospital_dashboard.html')
        self.assertEqual(HospitalInventory.objects.filter(hospital=self.hospital_user).count(), 8)

    def test_update_hospital_inventory(self):
        self.client.login(username='+8801912345678', password='password123')
        response = self.client.post(reverse('update_hospital_inventory'), {
            'blood_group': 'O+',
            'units': 15
        })
        self.assertEqual(response.status_code, 302)
        inv = HospitalInventory.objects.get(hospital=self.hospital_user, blood_group='O+')
        self.assertEqual(inv.units, 15)

    def test_hospital_verify_donor_donation(self):
        self.client.login(username='+8801912345678', password='password123')
        response = self.client.post(reverse('hospital_verify_donation'), {
            'donor_phone': '+8801712345678',
            'units_donated': 2,
            'recipient_name': 'Emergency Patient',
            'notes': 'Verified at DMC Hospital'
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(DonationHistory.objects.filter(donor=self.donor_user, units_donated=2).exists())
        inv = HospitalInventory.objects.get(hospital=self.hospital_user, blood_group='O+')
        self.assertEqual(inv.units, 2)

    def test_recent_donor_emergency_response_and_seeker_due_date_notice(self):
        # 1. Record recent donation 10 days ago for donor
        recent_date = timezone.now().date() - timedelta(days=10)
        DonationHistory.objects.create(
            donor=self.donor_user,
            donation_date=recent_date,
            location_hospital='Square Hospital',
            units_donated=1,
            status='completed'
        )

        # Check donor profile properties
        self.assertTrue(self.donor_profile.is_recently_donated)
        expected_due_date = recent_date + timedelta(days=90)
        self.assertEqual(self.donor_profile.next_regular_due_date, expected_due_date)

        # 2. Seeker posts an emergency blood request
        blood_request = BloodRequest.objects.create(
            seeker=self.seeker_user,
            patient_name='Critical Patient',
            blood_group='O+',
            units_required=2,
            hospital_name='Central Hospital',
            division='Dhaka',
            district='Dhaka City',
            urgency='immediate',
            contact_phone='+8801812345678',
            status='active'
        )

        # 3. Donor responds/volunteers for the emergency blood request
        self.client.login(username='+8801712345678', password='password123')
        response = self.client.post(reverse('respond_to_request', kwargs={'request_id': blood_request.id}), {
            'donor_message': 'I am ready to donate for this emergency!'
        })
        self.assertEqual(response.status_code, 302)

        # Verify BloodRequestResponse was recorded with recent donation details
        resp_obj = BloodRequestResponse.objects.get(request=blood_request, donor=self.donor_user)
        self.assertTrue(resp_obj.has_recent_donation)
        self.assertEqual(resp_obj.recent_donation_date, recent_date)
        self.assertEqual(resp_obj.next_due_date, expected_due_date)

        # 4. Seeker views my-requests and sees donor response with due date notification message
        self.client.login(username='+8801812345678', password='password123')
        seeker_resp = self.client.get(reverse('my_requests'))
        self.assertEqual(seeker_resp.status_code, 200)
        self.assertContains(seeker_resp, 'Emergency Override Message:')
        self.assertContains(seeker_resp, recent_date.strftime('%b %d, %Y'))
        self.assertContains(seeker_resp, expected_due_date.strftime('%b %d, %Y'))

