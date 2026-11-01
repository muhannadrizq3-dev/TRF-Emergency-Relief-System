import re
from datetime import datetime

import settings
from inventory import InventoryError, clean_name, get_supply, parse_quantity
from storage import from_iso, to_iso, utcnow


class RequestError(ValueError):
    pass


def parse_priority(value):
    if isinstance(value, int) and not isinstance(value, bool) and value in settings.PRIORITY_NAMES:
        return value
    text = str(value or "").strip().lower()
    if text in settings.PRIORITY_BY_NAME:
        return settings.PRIORITY_BY_NAME[text]
    if text.isdigit() and int(text) in settings.PRIORITY_NAMES:
        return int(text)
    raise RequestError("Priority must be low, medium, high or critical.")


def priority_name(level):
    return settings.PRIORITY_NAMES.get(int(level), "low")


def hours_waiting(created_at, now=None):
    now = now or utcnow()
    if isinstance(created_at, str):
        created_at = from_iso(created_at)
    seconds = (now - created_at).total_seconds()
    return max(0.0, seconds / 3600.0)


def effective_priority(base_priority, created_at, now=None, status=settings.PENDING):
    base = int(base_priority)
    if status not in settings.OPEN_STATUSES:
        return base
    bumps = int(hours_waiting(created_at, now) // settings.ESCALATION_HOURS)
    return min(settings.CRITICAL, base + bumps)


def sort_key(request, now=None):
    eff = effective_priority(request["priority"], request["created_at"], now, request.get("status", settings.PENDING))
    return (-eff, -int(request.get("is_sos") or 0), request["created_at"], request["id"])


def list_shelters(store):
    return store.query("SELECT * FROM shelters ORDER BY name")


def get_shelter(store, shelter_id):
    return store.query_one("SELECT * FROM shelters WHERE id = ?", (shelter_id,))


def parse_coordinate(value, low, high, label):
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        raise RequestError(f"{label} must be a number.") from None
    if number != number or not (low <= number <= high):
        raise RequestError(f"{label} must be between {low} and {high}.")
    return round(number, 6)


def add_shelter(store, name, area, latitude, longitude, capacity=0):
    try:
        name = clean_name(name, "Shelter name")
        capacity = parse_quantity(capacity, maximum=1_000_000)
    except InventoryError as exc:
        raise RequestError(str(exc)) from None
    area = " ".join(str(area or "").split())[: settings.MAX_NAME_LENGTH]
    lat = parse_coordinate(latitude, -90, 90, "Latitude")
    lng = parse_coordinate(longitude, -180, 180, "Longitude")
    if store.query_one("SELECT id FROM shelters WHERE LOWER(name) = LOWER(?)", (name,)):
        raise RequestError(f"Shelter '{name}' already exists.")
    return store.insert(
        "INSERT INTO shelters (name, area, latitude, longitude, capacity) VALUES (?, ?, ?, ?, ?)",
        (name, area, lat, lng, capacity),
    )


def delete_shelter(store, shelter_id):
    row = store.query_one(
        "SELECT COUNT(*) AS n FROM requests WHERE shelter_id = ? AND status IN ('pending', 'partial')",
        (shelter_id,),
    )
    if row and int(row["n"]) > 0:
        raise RequestError("This shelter still has open requests.")
    store.execute("UPDATE users SET shelter_id = NULL WHERE shelter_id = ?", (shelter_id,))
    return store.execute("DELETE FROM shelters WHERE id = ?", (shelter_id,)) > 0


def clean_note(note):
    text = str(note or "").replace("\r", "").strip()
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    if len(text) > settings.MAX_NOTE_LENGTH:
        raise RequestError(f"Note must be at most {settings.MAX_NOTE_LENGTH} characters.")
    return text


def validate_request(store, shelter_id, supply_type_id, quantity, priority):
    try:
        shelter_id = int(shelter_id)
        supply_type_id = int(supply_type_id)
    except (TypeError, ValueError):
        raise RequestError("Choose a shelter and a supply type.") from None
    if not get_shelter(store, shelter_id):
        raise RequestError("Unknown shelter.")
    if not get_supply(store, supply_type_id):
        raise RequestError("Unknown supply type.")
    try:
        quantity = parse_quantity(quantity, allow_zero=False, maximum=settings.MAX_REQUEST_QUANTITY)
    except InventoryError as exc:
        raise RequestError(str(exc)) from None
    return shelter_id, supply_type_id, quantity, parse_priority(priority)


def create_request(store, user_id, shelter_id, supply_type_id, quantity, priority,
                   note="", is_sos=False, now=None):
    shelter_id, supply_type_id, quantity, priority = validate_request(
        store, shelter_id, supply_type_id, quantity, priority
    )
    if is_sos:
        priority = settings.CRITICAL
    stamp = to_iso(now or utcnow())
    return store.insert(
        """INSERT INTO requests (shelter_id, supply_type_id, quantity, delivered, priority, status,
                                 is_sos, note, created_by, created_at, updated_at)
           VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)""",
        (shelter_id, supply_type_id, quantity, priority, settings.PENDING,
         1 if is_sos else 0, clean_note(note), int(user_id), stamp, stamp),
    )


def get_request(store, request_id):
    return store.query_one("SELECT * FROM requests WHERE id = ?", (request_id,))


def can_modify(user, request):
    if request is None or user is None:
        return False
    if request["status"] not in settings.OPEN_STATUSES:
        return False
    if settings.can(user["role"], "edit_any_request"):
        return True
    return settings.can(user["role"], "edit_own_request") and int(request["created_by"]) == int(user["id"])


def edit_request(store, user, request_id, quantity, priority, note=""):
    request = get_request(store, request_id)
    if not can_modify(user, request):
        raise RequestError("You cannot edit this request.")
    try:
        quantity = parse_quantity(quantity, allow_zero=False, maximum=settings.MAX_REQUEST_QUANTITY)
    except InventoryError as exc:
        raise RequestError(str(exc)) from None
    if quantity < int(request["delivered"]):
        raise RequestError("Quantity cannot be less than what was already delivered.")
    priority = settings.CRITICAL if request["is_sos"] else parse_priority(priority)
    store.execute(
        "UPDATE requests SET quantity = ?, priority = ?, note = ?, updated_at = ? WHERE id = ?",
        (quantity, priority, clean_note(note), to_iso(utcnow()), request_id),
    )
    if quantity == int(request["delivered"]):
        set_status(store, request_id, settings.FULFILLED)


def cancel_request(store, user, request_id):
    request = get_request(store, request_id)
    if not can_modify(user, request):
        raise RequestError("You cannot cancel this request.")
    set_status(store, request_id, settings.CANCELLED)


def set_status(store, request_id, status):
    if status not in settings.STATUSES:
        raise RequestError("Unknown status.")
    store.execute(
        "UPDATE requests SET status = ?, updated_at = ? WHERE id = ?",
        (status, to_iso(utcnow()), request_id),
    )


def list_requests(store, only_open=False, shelter_id=None, now=None):
    sql = """SELECT r.*, s.name AS shelter_name, s.latitude, s.longitude,
                    t.name AS supply_name, t.unit AS supply_unit,
                    u.display_name AS created_by_name
             FROM requests r
             JOIN shelters s ON s.id = r.shelter_id
             JOIN supply_types t ON t.id = r.supply_type_id
             LEFT JOIN users u ON u.id = r.created_by"""
    clauses, params = [], []
    if only_open:
        clauses.append("r.status IN ('pending', 'partial')")
    if shelter_id is not None:
        clauses.append("r.shelter_id = ?")
        params.append(shelter_id)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    rows = store.query(sql, params)
    for row in rows:
        row["effective_priority"] = effective_priority(row["priority"], row["created_at"], now, row["status"])
        row["priority_label"] = priority_name(row["effective_priority"])
        row["escalated"] = row["effective_priority"] > int(row["priority"])
        row["remaining"] = int(row["quantity"]) - int(row["delivered"])
        row["hours_waiting"] = round(hours_waiting(row["created_at"], now), 1)
    rows.sort(key=lambda r: sort_key(r, now))
    return rows


def summary(store):
    rows = store.query("SELECT status, COUNT(*) AS n FROM requests GROUP BY status")
    counts = {s: 0 for s in settings.STATUSES}
    for row in rows:
        counts[row["status"]] = int(row["n"])
    counts["open"] = counts[settings.PENDING] + counts[settings.PARTIAL]
    counts["total"] = sum(counts[s] for s in settings.STATUSES)
    return counts


def format_time(iso_text):
    dt = from_iso(iso_text) if isinstance(iso_text, str) else iso_text
    if not isinstance(dt, datetime):
        return ""
    return dt.strftime("%d %b %Y, %H:%M UTC")
