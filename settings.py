import os

APP_NAME = "TRF Emergency Relief"
TEAM_NAME = "TRF-Emergency-Relief"
SCHOOL = "Al Maarifa International Private School, Sharjah"
TEAM_MEMBERS = ["Muhannad Rizq", "Toka Ahmed", "Reima Aboamir", "Fatyma Iskhakova"]

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

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
WHATSAPP_PHONE = os.environ.get("WHATSAPP_PHONE", "").strip()
WHATSAPP_APIKEY = os.environ.get("WHATSAPP_APIKEY", "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or 587)
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
ALERT_EMAIL_TO = os.environ.get("ALERT_EMAIL_TO", "").strip()
ON_VERCEL = bool(os.environ.get("VERCEL"))
