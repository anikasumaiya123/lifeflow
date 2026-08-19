# Prompt: Build a Complete Blood Donation & Emergency Donor Finder Web Application using Python Django

## Tech Stack

-   Python 3
-   Django
-   **NeonDB PostgreSQL** (configured via `DATABASE_URL` from `.env` environment variable)
-   **Tailwind CSS** (no Bootstrap)
-   HTML5, JavaScript
-   Chart.js
-   **OpenStreetMap with Leaflet.js** (Open-source mapping, no Google Maps API dependency)

## Requirements

Build a production-ready Blood Donation & Emergency Donor Finder System.

### Authentication & Admin Approval Workflow

-   Registration for all roles (Donor, Blood Seeker, Hospital)
-   Login / Logout / Password Reset
-   Role-based access control (Admin, Donor, Seeker, Hospital)
-   **Mandatory Admin Approval**: Admin must verify and approve newly registered **Donors**, **Blood Seekers**, and **Hospitals** before their accounts become active in public searches and blood request workflows.

### Roles & Access Levels

-   **Admin**: Platform oversight, user verification & approval, analytics, system management.
-   **Donor**: Profile management, availability toggle, donation history, nearby request alerts.
-   **Blood Seeker**: Search nearby donors, post emergency blood requests, track response status.
-   **Hospital**: Manage hospital blood bank inventory, verify donations, organize blood camps, request emergency blood units.

### Hospital Responsibilities & Features

1.  **Blood Bank Inventory Management**: Real-time logging and tracking of available blood units per blood group (A+, A-, B+, B-, O+, O-, AB+, AB-).
2.  **Emergency Blood Request Dispatch**: Create and broadcast urgent hospital-level blood requests to nearby verified & available donors.
3.  **Donation Verification & Record Logging**: Official verification and logging of blood donations completed at the hospital to update donor histories and issue digital certificates.
4.  **Blood Camp Organization**: Schedule, publish, and manage community blood donation drives and blood camps.
5.  **Hospital Profile & Credentials**: Maintain official contact details, emergency hotline, bed capacity, and hospital location coordinates on OpenStreetMap.

### UI Design System

Use **Tailwind CSS** throughout. - Modern medical theme - Responsive -
Sidebar dashboard - Dark/light mode - Charts - Cards - Notifications -
Mobile friendly

### Database (NeonDB PostgreSQL via .env)

Configured dynamically via `DATABASE_URL` environment variable in `.env`.

Models: - CustomUser (with `is_approved`, `is_available`, `latitude`, `longitude` fields) - BloodRequest - DonationHistory - Hospital -
Notification - BloodCamp - Favourite - Review - EmergencyAlert

### Features

-   **Donor Availability Control**: Donors can toggle their availability (`Available` / `Unavailable`) directly from their portal dashboard. Unavailable donors are hidden from search queries, while available donors are displayed.
-   **Location-Based Nearby Donor Search**: Blood seekers and hospitals can search for donors near their location using OpenStreetMap / Leaflet.js and the Haversine formula. Nearby donors are plotted and sorted by distance.
-   **Multi-Param Donor Filters**: Filter search results using various parameters (e.g., Blood Group, Division/District, Distance Radius in km, Availability Status, Last Donation Date).
-   **OpenStreetMap with Leaflet.js**: Interactive maps for finding donors, hospitals, and blood camps.
-   Blood compatibility checker
-   Emergency alerts & SMS/Email notification system
-   Donation eligibility & reminder timers
-   AI chatbot (OpenAI/Gemini)
-   PDF donation certificates
-   CSV/PDF/Excel reports
-   Admin analytics dashboard & pending user approval queue
-   Tailwind dashboards for each role

### Django Apps

``` text
accounts/
dashboard/
donors/
seekers/
hospitals/
requests/
notifications/
bloodcamp/
ai_chatbot/
reports/
maps/
core/
```

### Pages

Home, About, Find Donor, Become Donor, Blood Requests, Hospitals, Blood
Camps, FAQ, Contact, Register, Login, Dashboard, Profile, Settings,
Notifications, Reports, Admin Approvals.

### Deliverables

1.  Create Django project and apps.
2.  Configure NeonDB PostgreSQL (via `DATABASE_URL` in `.env`).
3.  Build models and migrations (with approval status flags).
4.  Authentication & Admin Approval workflow.
5.  Tailwind templates.
6.  Dashboards for Admin, Donor, Seeker, Hospital.
7.  Nearby donor search with OpenStreetMap & multi-param filters.
8.  Donor portal availability toggle.
9.  Hospital blood bank & request management module.
10. Blood request workflow.
11. AI chatbot.
12. Testing and documentation.

Follow Django best practices with modular, well-commented code.
