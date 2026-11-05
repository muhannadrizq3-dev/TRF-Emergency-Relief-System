import csv
import io
import unittest
from datetime import datetime, timezone

import activity
import data_io
import emergency_requests as er
import inventory
from inventory import InventoryError
from tests.helpers import add_user, get_user, make_store
from web_app import build_overview


class ShelterImportTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()

    def test_import_shelters(self):
        n = data_io.import_shelters_csv(self.store, "name,area,lat,lng\nShelter D,Al Khan,25.32,55.36\nShelter E,,25.35,55.39\n")
        self.assertEqual(n, 2)
        self.assertEqual(self.store.count("shelters"), 5)

    def test_existing_shelter_name_rejected(self):
        with self.assertRaises(InventoryError) as ctx:
            data_io.import_shelters_csv(self.store, "name,area,lat,lng\nshelter a,x,25,55\n")
        self.assertIn("Line 2", str(ctx.exception))

    def test_duplicate_inside_file_rejected(self):
        with self.assertRaises(InventoryError):
            data_io.import_shelters_csv(self.store, "name,area,lat,lng\nNew,x,25,55\nnew,y,25,55\n")
        self.assertEqual(self.store.count("shelters"), 3)

    def test_bad_coordinates_rejected(self):
        with self.assertRaises(InventoryError):
            data_io.import_shelters_csv(self.store, "name,area,lat,lng\nNew,x,200,55\n")


class RequestImportTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.user = get_user(self.store, add_user(self.store))

    def test_import_requests(self):
        text = "shelter,item,quantity,priority\nShelter B,food,60,high\nshelter a,Water,10,\n"
        self.assertEqual(data_io.import_requests_csv(self.store, self.user, text), 2)
        rows = er.list_requests(self.store)
        self.assertEqual([r["priority_label"] for r in rows], ["high", "medium"])

    def test_unknown_shelter_or_item_rejected(self):
        for text in ("shelter,item,quantity,priority\nNowhere,food,5,low\n",
                     "shelter,item,quantity,priority\nShelter A,gold,5,low\n"):
            with self.assertRaises(InventoryError):
                data_io.import_requests_csv(self.store, self.user, text)
        self.assertEqual(self.store.count("requests"), 0)

    def test_import_csv_dispatcher(self):
        self.assertIn("supplies", data_io.import_csv(self.store, self.user, "supplies", "item,quantity\nwater,1\n"))
        with self.assertRaises(InventoryError):
            data_io.import_csv(self.store, self.user, "users", "x")


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.user = get_user(self.store, add_user(self.store))
        er.create_request(self.store, self.user["id"], 1, 1, 5, "low", note="=cmd()")
        activity.log(self.store, self.user, "did a thing")

    def rows(self, kind):
        return list(csv.reader(io.StringIO(data_io.export_csv(self.store, kind))))

    def test_each_export_has_header_and_rows(self):
        self.assertEqual(self.rows("supplies")[0], ["item", "unit", "quantity", "low_stock_level"])
        self.assertEqual(len(self.rows("supplies")), 4)
        self.assertEqual(self.rows("shelters")[0], ["name", "area", "lat", "lng"])
        self.assertEqual(len(self.rows("requests")), 2)
        self.assertEqual(self.rows("activity")[1][1:], ["Coord", "did a thing"])

    def test_unknown_export(self):
        with self.assertRaises(InventoryError):
            data_io.export_csv(self.store, "passwords")

    def test_exported_shelters_can_be_imported_again(self):
        text = data_io.export_csv(self.store, "shelters")
        fresh = make_store(seed=False)
        self.assertEqual(data_io.import_shelters_csv(fresh, text), 3)


class ActivityTests(unittest.TestCase):
    def test_log_and_read(self):
        store = make_store()
        user = get_user(store, add_user(store, "muhannad"))
        activity.log(store, user, "added   20 water")
        activity.log(store, None, "system check")
        rows = activity.recent(store)
        self.assertEqual(rows[0]["user_name"], "System")
        self.assertEqual(rows[1]["action"], "added 20 water")
        self.assertEqual(rows[1]["initials"], "MU")

    def test_uae_time(self):
        when = datetime(2026, 10, 26, 7, 31, tzinfo=timezone.utc)
        self.assertEqual(activity.uae_time("2026-10-26T07:31:00Z"), "26 Oct, 11:31 AM")
        self.assertEqual(activity.uae_time(None), "")
        self.assertTrue(when)

    def test_initials(self):
        self.assertEqual(activity.initials("Muhannad Osama Rizq"), "MR")
        self.assertEqual(activity.initials(""), "?")


class OverviewTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.uid = add_user(self.store)

    def test_empty_overview(self):
        o = build_overview(self.store)
        self.assertEqual((o["stock_total"], o["request_total"], o["waiting"], len(o["shortages"])), (210, 0, 0, 0))
        self.assertEqual(o["fulfilment_pct"], 0)
        self.assertEqual([s["label"] for s in o["low_supplies"]], ["First Aid Kits"])

    def test_shortage_and_counts(self):
        kits = inventory.get_supply_by_name(self.store, "first aid kits")["id"]
        er.create_request(self.store, self.uid, 1, kits, 40, "critical")
        er.create_request(self.store, self.uid, 2, 2, 10, "low")
        o = build_overview(self.store)
        self.assertEqual([x["label"] for x in o["shortages"]], ["First Aid Kits"])
        self.assertEqual(o["by_priority"]["critical"], 1)
        self.assertEqual(dict(o["by_shelter"]), {"Shelter A": 1, "Shelter B": 1})
        waiting = {s["name"]: s["waiting"] for s in o["shelters"]}
        self.assertEqual(waiting, {"Shelter A": 1, "Shelter B": 1, "Shelter C": 0})


if __name__ == "__main__":
    unittest.main()
