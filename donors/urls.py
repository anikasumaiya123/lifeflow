from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_view, name='root_login'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('find-donors/', views.find_donors_view, name='find_donors'),
    path('post-request/', views.post_request_view, name='post_request'),
    path('my-requests/', views.my_requests_view, name='my_requests'),
    path('update-request-status/<int:request_id>/', views.update_request_status_view, name='update_request_status'),
    path('respond-request/<int:request_id>/', views.respond_to_request_view, name='respond_to_request'),
    path('update-hospital-inventory/', views.update_hospital_inventory_view, name='update_hospital_inventory'),
    path('hospital-verify-donation/', views.hospital_verify_donation_view, name='hospital_verify_donation'),
    path('add-donation/', views.add_donation_view, name='add_donation'),
    path('toggle-availability/', views.toggle_availability_view, name='toggle_availability'),
    path('update-location/', views.update_location_view, name='update_location'),
]
