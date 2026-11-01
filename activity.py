from datetime import timedelta, timezone

import settings
from storage import from_iso, to_iso, utcnow

UAE = timezone(timedelta(hours=settings.UAE_UTC_OFFSET_HOURS), name="UAE")
MAX_ACTION_LENGTH = 300


def log(store, user, action, now=None):
    text = " ".join(str(action).split())[:MAX_ACTION_LENGTH]
    store.insert(
        "INSERT INTO activity (user_id, user_name, action, created_at) VALUES (?, ?, ?, ?)",
        (user["id"] if user else None, user["display_name"] if user else "System", text,
         to_iso(now or utcnow())),
    )


def recent(store, limit=30):
    rows = store.query("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (int(limit),))
    for row in rows:
        row["uae_time"] = uae_time(row["created_at"])
        row["initials"] = initials(row["user_name"])
    return rows


def uae_time(iso_text):
    dt = from_iso(iso_text)
    if dt is None:
        return ""
    local = dt.astimezone(UAE)
    return f"{local.day} {local.strftime('%b')}, {local.strftime('%I:%M %p').lstrip('0')}"


def initials(name):
    parts = [p for p in str(name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()
