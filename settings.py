import os

APP_NAME = "TRF Emergency Relief"
TEAM_NAME = "TRF-Emergency-Relief"
SCHOOL = "Al Maarifa International Private School, Sharjah"
TEAM_MEMBERS = ["Muhannad Rizq", "Toka Ahmed", "Reima Aboamir", "Fatyma Iskhakova"]

TEAM_ACCOUNTS = [
    ("muhannad", "Muhannad Rizq", "muhannadrizq3@gmail.com",
     "scrypt:32768:8:1$rkRBSpjPI1piJw2o$09c958725d4f75a06388c3f5de919a5d939026521246ff948f3811bfc8554de925f0a04874b7c1119646fb96c68df8d5905f65f378e0928043c458382bdd3184"),
    ("toka", "Toka Ahmed", "toka82439@gmail.com",
     "scrypt:32768:8:1$Ujx1T9o0h3eBIZC1$c58e4f49b26d4902e1af52dff0931b264aeb7456bdb67d34af5023fdac9437999c75520ecedf4dc58890e62b99a821c8bcc8053086be9c0176cfba3ed762deb7"),
    ("reima", "Reima Aboamir", "abomir.reima@gmail.com",
     "scrypt:32768:8:1$mwE03bqvkWgZV3bp$9e814fa15039e873fc50593ecfd6d6c3e26b702b9358863caf1786fcc4fdb16cc16313bd13e79dd44fb1b8c25b3607853af7bdfb9627df848ac30d58e020e7f3"),
    ("fatyma", "Fatyma Iskhakova", "fatyma.isk@gmail.com",
     "scrypt:32768:8:1$5Tr3dAnFvFfPF48n$9aeaf4943dbc0e33d786de496f74e5c9320f9229b991ec1053f90a3279419f460bf9cc511360a52a6e351367fb72c054678544ac50700153f390ffd642120f72"),
]

COORDINATOR = "coordinator"
SHELTER_STAFF = "shelter_staff"
VOLUNTEER = "volunteer"

ROLES = (COORDINATOR, SHELTER_STAFF, VOLUNTEER)
SELF_SIGNUP_ROLES = (SHELTER_STAFF, VOLUNTEER)

PERMISSIONS = {
    COORDINATOR: {
        "view_dashboard", "view_map", "view_reports",
        "create_request", "send_sos", "edit_any_request", "cancel_any_request",
        "dispatch", "manage_stock", "manage_supply_types", "manage_shelters",
        "manage_users", "import_csv", "reset_demo", "view_activity",
    },
    SHELTER_STAFF: {
        "view_dashboard", "view_map", "view_reports",
        "create_request", "send_sos", "edit_own_request", "cancel_own_request", "view_activity",
    },
    VOLUNTEER: {"view_dashboard", "view_map", "view_reports", "view_activity"},
}


def can(role, action):
    return action in PERMISSIONS.get(role, set())


LOW, MEDIUM, HIGH, CRITICAL = 1, 2, 3, 4
PRIORITY_NAMES = {LOW: "low", MEDIUM: "medium", HIGH: "high", CRITICAL: "critical"}
PRIORITY_BY_NAME = {name: level for level, name in PRIORITY_NAMES.items()}

ESCALATION_HOURS = 24

PENDING = "pending"
PARTIAL = "partial"
FULFILLED = "fulfilled"
CANCELLED = "cancelled"
STATUSES = (PENDING, PARTIAL, FULFILLED, CANCELLED)
OPEN_STATUSES = (PENDING, PARTIAL)

MAX_REQUEST_QUANTITY = 100_000
MAX_STOCK_QUANTITY = 10_000_000
MAX_NOTE_LENGTH = 500
MAX_NAME_LENGTH = 80
MIN_PASSWORD_LENGTH = 8
USERNAME_PATTERN = r"^[A-Za-z0-9_.-]{3,30}$"
EMAIL_PATTERN = r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$"
REMEMBER_ME_DAYS = 30

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15

COMPETITION = "RIT Dubai Software Engineering Competition 2026"
SCHOOL_NAME = "Al Maarifa International Private School"
SCHOOL_PLACE = "Sharjah, UAE"

DEFAULT_THRESHOLD = 20
HEALTHY_FACTOR = 5
GETTING_LOW_FACTOR = 2

DEFAULT_SUPPLY_TYPES = [
    ("water", "bottles", 100, 20),
    ("food", "meal packs", 80, 20),
    ("first aid kits", "kits", 30, 20),
]

DEMO_SHELTERS = [
    ("Shelter A", "Al Majaz, Sharjah", 25.3247, 55.3836, 250),
    ("Shelter B", "Al Nahda, Sharjah", 25.3006, 55.3733, 180),
    ("Shelter C", "Muwaileh, Sharjah", 25.3010, 55.4100, 300),
]

UAE_UTC_OFFSET_HOURS = 4

EMERGENCY_NUMBERS = [
    ("999", "Police"),
    ("998", "Ambulance"),
    ("997", "Civil Defence"),
]

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
WHATSAPP_PHONE = os.environ.get("WHATSAPP_PHONE", "").strip()
WHATSAPP_APIKEY = os.environ.get("WHATSAPP_APIKEY", "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or 587)
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
ALERT_EMAIL_TO = os.environ.get("ALERT_EMAIL_TO", "").strip()
ON_VERCEL = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
