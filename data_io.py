import csv
import io
import json

import activity
import emergency_requests as er
import inventory
import settings
from inventory import InventoryError, csv_safe, read_csv
from storage import to_iso, utcnow

IMPORT_KINDS = ("supplies", "shelters", "requests")
EXPORT_KINDS = ("supplies", "requests", "shelters", "activity", "medical_dispatches")


def import_shelters_csv(store, text):
    rows = read_csv(text, ("name", "area", "lat", "lng"))
    seen = set()
    parsed = []
    for line_no, row in rows:
        try:
            name = inventory.clean_name(row.get("name"), "Shelter name")
            lat = er.parse_coordinate(row.get("lat"), -90, 90, "Latitude")
            lng = er.parse_coordinate(row.get("lng"), -180, 180, "Longitude")
        except (InventoryError, er.RequestError) as exc:
            raise InventoryError(f"Line {line_no}: {exc}") from None
        key = name.lower()
        if key in seen or store.query_one("SELECT id FROM shelters WHERE LOWER(name) = ?", (key,)):
            raise InventoryError(f"Line {line_no}: shelter '{name}' already exists.")
        seen.add(key)
        area = " ".join(row.get("area", "").split())[: settings.MAX_NAME_LENGTH]
        parsed.append((name, area, lat, lng))
    for name, area, lat, lng in parsed:
        store.insert(
            "INSERT INTO shelters (name, area, latitude, longitude, capacity) VALUES (?, ?, ?, ?, 0)",
            (name, area, lat, lng),
        )
    return len(parsed)


def import_requests_csv(store, user, text):
    rows = read_csv(text, ("shelter", "item", "quantity", "priority"))
    parsed = []
    for line_no, row in rows:
        shelter = store.query_one("SELECT id FROM shelters WHERE LOWER(name) = LOWER(?)", (row.get("shelter", ""),))
        supply = inventory.get_supply_by_name(store, row.get("item", ""))
        try:
            if not shelter:
                raise er.RequestError(f"unknown shelter '{row.get('shelter', '')}'.")
            if not supply:
                raise er.RequestError(f"unknown supply '{row.get('item', '')}'.")
            values = er.validate_request(store, shelter["id"], supply["id"], row.get("quantity"),
                                         row.get("priority") or "medium")
        except er.RequestError as exc:
            raise InventoryError(f"Line {line_no}: {exc}") from None
        parsed.append(values)
    for shelter_id, supply_id, quantity, priority in parsed:
        er.create_request(store, user["id"], shelter_id, supply_id, quantity, priority)
    return len(parsed)


def import_csv(store, user, kind, text):
    if kind == "supplies":
        created, updated = inventory.import_supplies_csv(store, text)
        return f"{created} new and {updated} existing supplies"
    if kind == "shelters":
        return f"{import_shelters_csv(store, text)} shelters"
    if kind == "requests":
        return f"{import_requests_csv(store, user, text)} requests"
    raise InventoryError("Choose what to import.")


def _write(header, rows):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    for row in rows:
        writer.writerow([csv_safe(v) if isinstance(v, str) else v for v in row])
    return out.getvalue()


def export_csv(store, kind):
    if kind == "supplies":
        return _write(("item", "unit", "quantity", "low_stock_level"),
                      [(s["name"], s["unit"], s["quantity"], s["threshold"]) for s in inventory.list_supplies(store)])
    if kind == "shelters":
        return _write(("name", "area", "lat", "lng"),
                      [(s["name"], s["area"], s["latitude"], s["longitude"]) for s in er.list_shelters(store)])
    if kind == "requests":
        return _write(
            ("id", "shelter", "item", "quantity", "delivered", "priority", "current_priority", "status", "sos",
             "created_by", "created_at"),
            [(r["id"], r["shelter_name"], r["supply_name"], r["quantity"], r["delivered"],
              er.priority_name(r["priority"]), r["priority_label"], r["status"], "yes" if r["is_sos"] else "no",
              r["created_by_name"] or "", r["created_at"]) for r in er.list_requests(store)])
    if kind == "activity":
        return _write(("time_uae", "user", "action"),
                      [(a["uae_time"], a["user_name"], a["action"]) for a in activity.recent(store, 10_000)])
    if kind == "medical_dispatches":
        rows = store.query(
            """SELECT mr.id AS request_id, s.name AS shelter, mr.required_specialty,
                      mr.urgency, mr.status, d.id AS doctor_id, d.specialty AS doctor_specialty,
                      h.name AS hospital_name, mr.distance, mr.created_at
               FROM medical_requests mr JOIN shelters s ON s.id = mr.shelter_id
               LEFT JOIN doctors d ON d.id = mr.assigned_doctor_id
               LEFT JOIN hospitals h ON h.id = mr.hospital_id ORDER BY mr.id DESC"""
        )
        return _write(("request_id", "shelter", "required_specialty", "urgency", "status",
                       "doctor_id", "doctor_specialty", "hospital_name", "distance",
                       "distance_unit", "created_at"),
                      [(r["request_id"], r["shelter"], r["required_specialty"], r["urgency"],
                        r["status"], r["doctor_id"] or "", r["doctor_specialty"] or "",
                        r["hospital_name"] or "", r["distance"] if r["distance"] is not None else "",
                        "coordinate units" if r["distance"] is not None else "", r["created_at"])
                       for r in rows])
    raise InventoryError("Unknown export.")


def export_filename(kind):
    return f"trf-{kind}-{to_iso(utcnow())[:10]}.csv"


def export_json(store, kind):
    if kind != "medical_dispatches":
        raise InventoryError("JSON export is available for medical dispatch records.")
    rows = store.query(
        """SELECT mr.id AS request_id, s.name AS shelter, mr.required_specialty,
                  mr.urgency, mr.status, d.id AS doctor_id, d.specialty AS doctor_specialty,
                  h.name AS hospital_name, mr.distance, mr.created_at
           FROM medical_requests mr JOIN shelters s ON s.id = mr.shelter_id
           LEFT JOIN doctors d ON d.id = mr.assigned_doctor_id
           LEFT JOIN hospitals h ON h.id = mr.hospital_id ORDER BY mr.id DESC"""
    )
    return json.dumps(rows, ensure_ascii=False, indent=2)


def export_json_filename(kind):
    return f"trf-{kind}-{to_iso(utcnow())[:10]}.json"
