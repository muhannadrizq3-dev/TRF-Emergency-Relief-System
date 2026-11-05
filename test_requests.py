import unittest
from datetime import timedelta

import emergency_requests as er
import inventory
import settings
from storage import to_iso
from tests.helpers import NOW, add_user, hours_ago, make_store


class PriorityTests(unittest.TestCase):
    def test_parse_names_and_numbers(self):
        self.assertEqual(er.parse_priority("HIGH"), settings.HIGH)
        self.assertEqual(er.parse_priority("2"), settings.MEDIUM)
        self.assertEqual(er.parse_priority(4), settings.CRITICAL)

    def test_parse_rejects_unknown(self):
        for bad in ("urgent", "0", "5", "", None, True):
            with self.assertRaises(er.RequestError):
                er.parse_priority(bad)

    def test_no_escalation_before_24_hours(self):
        self.assertEqual(er.effective_priority(1, hours_ago(23.9), NOW), 1)

    def test_one_level_after_24_hours(self):
        self.assertEqual(er.effective_priority(1, hours_ago(24), NOW), 2)

    def test_two_levels_after_48_hours(self):
        self.assertEqual(er.effective_priority(1, hours_ago(50), NOW), 3)

    def test_escalation_capped_at_critical(self):
        self.assertEqual(er.effective_priority(2, hours_ago(24 * 30), NOW), settings.CRITICAL)

    def test_closed_requests_do_not_escalate(self):
        self.assertEqual(er.effective_priority(1, hours_ago(100), NOW, settings.FULFILLED), 1)

    def test_future_timestamp_counts_as_zero_wait(self):
        future = to_iso(NOW + timedelta(hours=5))
        self.assertEqual(er.hours_waiting(future, NOW), 0.0)

    def test_sort_key_orders_priority_then_sos_then_age(self):
        reqs = [
            {"id": 1, "priority": 3, "created_at": hours_ago(1), "status": "pending", "is_sos": 0},
            {"id": 2, "priority": 4, "created_at": hours_ago(1), "status": "pending", "is_sos": 0},
            {"id": 3, "priority": 4, "created_at": hours_ago(1), "status": "pending", "is_sos": 1},
            {"id": 4, "priority": 3, "created_at": hours_ago(5), "status": "pending", "is_sos": 0},
        ]
        order = [r["id"] for r in sorted(reqs, key=lambda r: er.sort_key(r, NOW))]
        self.assertEqual(order, [3, 2, 4, 1])


class RequestLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.coord = self.user(add_user(self.store, "coord", "coordinator"))
        self.staff = self.user(add_user(self.store, "staff1", "shelter_staff"))
        self.other = self.user(add_user(self.store, "staff2", "shelter_staff"))
        self.vol = self.user(add_user(self.store, "vol", "volunteer"))
        self.food = inventory.get_supply_by_name(self.store, "food")["id"]

    def user(self, uid):
        return self.store.query_one("SELECT * FROM users WHERE id = ?", (uid,))

    def make(self, user=None, **kw):
        args = dict(shelter_id=2, supply_type_id=self.food, quantity=60, priority="high")
        args.update(kw)
        return er.create_request(self.store, (user or self.staff)["id"], **args)

    def test_create_request(self):
        req = er.get_request(self.store, self.make())
        self.assertEqual((req["quantity"], req["priority"], req["status"]), (60, settings.HIGH, settings.PENDING))

    def test_sos_is_always_critical(self):
        req = er.get_request(self.store, self.make(priority="low", is_sos=True))
        self.assertEqual(req["priority"], settings.CRITICAL)
        self.assertEqual(req["is_sos"], 1)

    def test_rejects_zero_quantity(self):
        with self.assertRaises(er.RequestError):
            self.make(quantity="0")

    def test_rejects_negative_quantity(self):
        with self.assertRaises(er.RequestError):
            self.make(quantity="-5")

    def test_rejects_huge_quantity(self):
        with self.assertRaises(er.RequestError):
            self.make(quantity=str(settings.MAX_REQUEST_QUANTITY + 1))

    def test_rejects_unknown_shelter(self):
        with self.assertRaises(er.RequestError):
            self.make(shelter_id=999)

    def test_rejects_unknown_supply(self):
        with self.assertRaises(er.RequestError):
            self.make(supply_type_id="abc")

    def test_rejects_long_note(self):
        with self.assertRaises(er.RequestError):
            self.make(note="x" * (settings.MAX_NOTE_LENGTH + 1))

    def test_note_control_characters_removed(self):
        req = er.get_request(self.store, self.make(note="hello\x00\x07 world"))
        self.assertEqual(req["note"], "hello world")

    def test_owner_can_edit(self):
        rid = self.make()
        er.edit_request(self.store, self.staff, rid, "80", "critical", "more people arrived")
        req = er.get_request(self.store, rid)
        self.assertEqual((req["quantity"], req["priority"]), (80, settings.CRITICAL))

    def test_other_staff_cannot_edit(self):
        rid = self.make()
        with self.assertRaises(er.RequestError):
            er.edit_request(self.store, self.other, rid, "80", "low")

    def test_volunteer_cannot_cancel(self):
        rid = self.make()
        with self.assertRaises(er.RequestError):
            er.cancel_request(self.store, self.vol, rid)

    def test_coordinator_can_cancel_any(self):
        rid = self.make()
        er.cancel_request(self.store, self.coord, rid)
        self.assertEqual(er.get_request(self.store, rid)["status"], settings.CANCELLED)

    def test_cannot_edit_cancelled(self):
        rid = self.make()
        er.cancel_request(self.store, self.staff, rid)
        with self.assertRaises(er.RequestError):
            er.edit_request(self.store, self.staff, rid, "10", "low")

    def test_list_requests_sorted_and_enriched(self):
        self.make(priority="low")
        self.make(priority="critical")
        rows = er.list_requests(self.store)
        self.assertEqual(rows[0]["priority_label"], "critical")
        self.assertIn("shelter_name", rows[0])
        self.assertEqual(rows[0]["remaining"], 60)

    def test_summary_counts(self):
        rid = self.make()
        self.make()
        er.cancel_request(self.store, self.staff, rid)
        counts = er.summary(self.store)
        self.assertEqual((counts["open"], counts["cancelled"], counts["total"]), (1, 1, 2))


class ShelterTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()

    def test_add_shelter(self):
        sid = er.add_shelter(self.store, "Shelter E", "Al Qasimia", "25.35", "55.39", "100")
        self.assertEqual(er.get_shelter(self.store, sid)["capacity"], 100)

    def test_rejects_bad_coordinates(self):
        with self.assertRaises(er.RequestError):
            er.add_shelter(self.store, "Shelter E", "", "95", "55")
        with self.assertRaises(er.RequestError):
            er.add_shelter(self.store, "Shelter F", "", "nan", "55")

    def test_rejects_duplicate_name(self):
        with self.assertRaises(er.RequestError):
            er.add_shelter(self.store, "shelter a", "", "25", "55")

    def test_cannot_delete_shelter_with_open_requests(self):
        uid = add_user(self.store)
        er.create_request(self.store, uid, 1, 1, 5, "low")
        with self.assertRaises(er.RequestError):
            er.delete_shelter(self.store, 1)


if __name__ == "__main__":
    unittest.main()
