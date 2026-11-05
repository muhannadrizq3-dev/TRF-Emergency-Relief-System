import os
import tempfile
import unittest

import medical_dispatch
import storage


class MedicalDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = storage.Storage(sqlite_path=os.path.join(self.tmp.name, "test.db"))
        storage.seed_demo_data(self.store)
        medical_dispatch.seed_medical_demo_data(self.store)
        self.shelter = self.store.query_one("SELECT id FROM shelters ORDER BY id LIMIT 1")
        self.now = storage.to_iso(storage.utcnow())

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def make_request(self, specialty):
        return self.store.insert(
            """INSERT INTO medical_requests
               (shelter_id, required_specialty, urgency, status, created_at, updated_at)
               VALUES (?, ?, 'High', 'Pending Medical Dispatch - High Urgency', ?, ?)""",
            (self.shelter["id"], specialty, self.now, self.now),
        )

    def test_euclidean_distance(self):
        self.assertEqual(
            medical_dispatch.calculate_distance({"x": 0, "y": 0}, {"x": 3, "y": 4}),
            5.0,
        )

    def test_nearest_available_doctor_is_assigned_and_marked_busy(self):
        request_id = self.make_request("General Medicine")
        result = medical_dispatch.dispatch_medical_request(self.store, request_id)
        self.assertEqual(result["status"], "Dispatched")
        doctor = self.store.query_one(
            "SELECT status FROM doctors WHERE id = ?", (result["doctor_id"],)
        )
        self.assertEqual(doctor["status"], "Dispatched/Busy")

    def test_missing_specialty_stays_high_urgency_pending(self):
        request_id = self.make_request("Neurology")
        result = medical_dispatch.dispatch_medical_request(self.store, request_id)
        self.assertEqual(result["status"], "Pending Medical Dispatch - High Urgency")
        saved = self.store.query_one(
            "SELECT status, urgency FROM medical_requests WHERE id = ?", (request_id,)
        )
        self.assertEqual(saved["urgency"], "High")
        self.assertIsNone(saved.get("assigned_doctor_id"))

    def test_next_available_doctor_is_used_on_later_request(self):
        first = self.make_request("General Medicine")
        first_result = medical_dispatch.dispatch_medical_request(self.store, first)
        second = self.make_request("General Medicine")
        second_result = medical_dispatch.dispatch_medical_request(self.store, second)
        self.assertEqual(first_result["status"], "Dispatched")
        self.assertEqual(second_result["status"], "Dispatched")
        self.assertNotEqual(first_result["doctor_id"], second_result["doctor_id"])


if __name__ == "__main__":
    unittest.main()
