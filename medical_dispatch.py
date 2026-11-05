"""Medical dispatch for the RIT Phase 2 demonstration.

The competition's Cartesian distance formula is used: sqrt((x2-x1)^2+(y2-y1)^2).
For this demo, shelter/hospital x is longitude and y is latitude. These are
demo coordinate units, not a road/travel-time estimate.
"""
import math
from datetime import datetime, timezone


def calculate_distance(shelter, hospital):
    x1 = float(shelter.get("x", shelter.get("longitude", shelter.get("lng"))))
    y1 = float(shelter.get("y", shelter.get("latitude", shelter.get("lat"))))
    x2 = float(hospital.get("x", hospital.get("longitude", hospital.get("lng"))))
    y2 = float(hospital.get("y", hospital.get("latitude", hospital.get("lat"))))
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def dispatch_medical_request(store, request_id):
    req = store.query_one(
        """SELECT mr.*, s.latitude, s.longitude FROM medical_requests mr
           JOIN shelters s ON s.id = mr.shelter_id WHERE mr.id = ?""", (request_id,))
    if not req:
        raise ValueError("Medical request not found.")

    hospitals = store.query("SELECT * FROM hospitals")
    doctors = store.query(
        "SELECT * FROM doctors WHERE LOWER(status) = 'available' AND LOWER(specialty) = LOWER(?)",
        (req["required_specialty"],))
    candidates = []
    shelter = {"x": req["longitude"], "y": req["latitude"]}
    for doctor in doctors:
        hospital = next((h for h in hospitals if str(h["id"]) == str(doctor["hospital_id"])), None)
        if not hospital:
            continue
        distance = calculate_distance(shelter, {"x": hospital["longitude"], "y": hospital["latitude"]})
        candidates.append((distance, doctor, hospital))

    candidates.sort(key=lambda item: item[0])
    for distance, doctor, hospital in candidates:
        # Conditional update prevents assigning a doctor who became busy meanwhile.
        changed = store.execute(
            """UPDATE doctors SET status = 'Dispatched/Busy'
               WHERE id = ? AND LOWER(status) = 'available'""", (doctor["id"],))
        if changed != 1:
            continue
        distance = round(distance, 6)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        store.execute(
            """UPDATE medical_requests SET status = 'Dispatched', assigned_doctor_id = ?,
               hospital_id = ?, distance = ?, updated_at = ? WHERE id = ?""",
            (doctor["id"], hospital["id"], distance, now, request_id))
        store.insert(
            """INSERT INTO medical_dispatches
               (medical_request_id, doctor_id, hospital_id, distance, dispatched_at)
               VALUES (?, ?, ?, ?, ?)""",
            (request_id, doctor["id"], hospital["id"], distance, now))
        return {"status": "Dispatched", "doctor_id": doctor["id"],
                "specialty": doctor["specialty"], "hospital_id": hospital["id"],
                "hospital_name": hospital["name"], "distance": distance,
                "distance_unit": "coordinate units"}

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.execute(
        """UPDATE medical_requests SET status = 'Pending Medical Dispatch - High Urgency',
           urgency = 'High', assigned_doctor_id = NULL, hospital_id = NULL,
           distance = NULL, updated_at = ? WHERE id = ?""", (now, request_id))
    return {"status": "Pending Medical Dispatch - High Urgency",
            "message": "No available doctor with the required specialty."}


def list_medical_requests(store):
    return store.query(
        """SELECT mr.id, mr.required_specialty, mr.urgency, mr.status,
                  mr.assigned_doctor_id, mr.distance, mr.created_at,
                  s.name AS shelter_name, h.name AS hospital_name,
                  d.specialty AS doctor_specialty
           FROM medical_requests mr
           JOIN shelters s ON s.id = mr.shelter_id
           LEFT JOIN hospitals h ON h.id = mr.hospital_id
           LEFT JOIN doctors d ON d.id = mr.assigned_doctor_id
           ORDER BY mr.id DESC"""
    )


def seed_medical_demo_data(store):
    if store.count("hospitals") == 0:
        # Fictional demonstration centers and coordinates; not official RIT/UAE data.
        for row in [
            ("DEMO-H01", "Demo Medical Center A", 25.3240, 55.3820),
            ("DEMO-H02", "Demo Medical Center B", 25.3020, 55.3740),
            ("DEMO-H03", "Demo Medical Center C", 25.3050, 55.4080),
        ]:
            store.execute("INSERT INTO hospitals (id, name, latitude, longitude) VALUES (?, ?, ?, ?)", row)
    if store.count("doctors") == 0:
        for row in [
            ("DEMO-D01", "DEMO-H01", "General Medicine", "Available"),
            ("DEMO-D02", "DEMO-H02", "Pediatrics", "Available"),
            ("DEMO-D03", "DEMO-H03", "Cardiology", "Available"),
            ("DEMO-D04", "DEMO-H02", "General Medicine", "Available"),
        ]:
            store.execute("INSERT INTO doctors (id, hospital_id, specialty, status) VALUES (?, ?, ?, ?)", row)
