import unittest

import settings
import storage
from tests.helpers import NOW, add_user, make_store


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()

    def test_uses_sqlite(self):
        self.assertEqual(self.store.backend_name, "SQLite")

    def test_data_is_saved_to_a_file(self):
        import os, tempfile
        path = os.path.join(tempfile.mkdtemp(), "trf.db")
        first = storage.Storage(sqlite_path=path)
        storage.seed_demo_data(first)
        add_user(first, "toka")
        first.close()
        second = storage.Storage(sqlite_path=path)
        self.assertEqual(second.count("users"), 1)
        self.assertEqual(second.count("shelters"), 3)
        second.close()

    def test_seed_is_idempotent(self):
        storage.seed_demo_data(self.store)
        self.assertEqual(self.store.count("supply_types"), len(settings.DEFAULT_SUPPLY_TYPES))
        self.assertEqual(self.store.count("shelters"), len(settings.DEMO_SHELTERS))

    def test_insert_returns_id_and_query_one(self):
        uid = add_user(self.store, "reima")
        self.assertEqual(self.store.query_one("SELECT username FROM users WHERE id = ?", (uid,))["username"], "reima")

    def test_parameters_prevent_sql_injection(self):
        add_user(self.store, "fatyma")
        rows = self.store.query("SELECT * FROM users WHERE username = ?", ("x' OR '1'='1",))
        self.assertEqual(rows, [])

    def test_count_rejects_unknown_table(self):
        with self.assertRaises(ValueError):
            self.store.count("users; DROP TABLE users")

    def test_reset_demo_keeps_users(self):
        add_user(self.store)
        self.store.execute("UPDATE supply_types SET quantity = 0")
        storage.reset_demo(self.store)
        self.assertEqual(self.store.count("users"), 1)
        water = self.store.query_one("SELECT quantity FROM supply_types WHERE name = 'water'")
        self.assertEqual(water["quantity"], 100)

    def test_start_empty_is_not_refilled_on_restart(self):
        storage.start_empty(self.store)
        storage.seed_demo_data(self.store)
        self.assertEqual(self.store.count("supply_types"), 0)
        self.assertEqual(self.store.count("shelters"), 0)

    def test_meta_values(self):
        self.store.set_meta("k", "1")
        self.store.set_meta("k", "2")
        self.assertEqual(self.store.get_meta("k"), "2")
        self.assertIsNone(self.store.get_meta("missing"))

    def test_iso_round_trip(self):
        self.assertEqual(storage.from_iso(storage.to_iso(NOW)), NOW)
        self.assertIsNone(storage.from_iso(None))


class SettingsTests(unittest.TestCase):
    def test_coordinator_has_all_admin_rights(self):
        for action in ("dispatch", "manage_stock", "manage_users", "import_csv", "reset_demo"):
            self.assertTrue(settings.can(settings.COORDINATOR, action))

    def test_staff_can_request_but_not_dispatch(self):
        self.assertTrue(settings.can(settings.SHELTER_STAFF, "create_request"))
        self.assertTrue(settings.can(settings.SHELTER_STAFF, "send_sos"))
        self.assertFalse(settings.can(settings.SHELTER_STAFF, "dispatch"))

    def test_volunteer_is_view_only(self):
        self.assertTrue(settings.can(settings.VOLUNTEER, "view_map"))
        self.assertFalse(settings.can(settings.VOLUNTEER, "create_request"))

    def test_unknown_role_has_no_rights(self):
        self.assertFalse(settings.can("hacker", "view_dashboard"))

    def test_coordinator_not_self_signup_role(self):
        self.assertNotIn(settings.COORDINATOR, settings.SELF_SIGNUP_ROLES)

    def test_uae_emergency_numbers(self):
        self.assertEqual([n for n, _ in settings.EMERGENCY_NUMBERS], ["999", "998", "997"])


if __name__ == "__main__":
    unittest.main()
