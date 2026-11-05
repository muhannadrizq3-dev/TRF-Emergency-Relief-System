import unittest

import emergency_requests as er
import inventory
from tests.helpers import add_user, make_store


class ParseQuantityTests(unittest.TestCase):
    def test_accepts_whole_numbers(self):
        self.assertEqual(inventory.parse_quantity(" 42 "), 42)
        self.assertEqual(inventory.parse_quantity(7), 7)

    def test_rejects_negative_decimal_and_text(self):
        for bad in ("-1", "1.5", "ten", "", "1e3", " ", True):
            with self.assertRaises(inventory.InventoryError):
                inventory.parse_quantity(bad)

    def test_zero_allowed_unless_disabled(self):
        self.assertEqual(inventory.parse_quantity("0"), 0)
        with self.assertRaises(inventory.InventoryError):
            inventory.parse_quantity("0", allow_zero=False)

    def test_maximum(self):
        with self.assertRaises(inventory.InventoryError):
            inventory.parse_quantity("11", maximum=10)


class StockLevelTests(unittest.TestCase):
    def level(self, qty, threshold=20):
        return inventory.stock_level({"quantity": qty, "threshold": threshold})

    def test_levels(self):
        self.assertEqual(self.level(100), "good")
        self.assertEqual(self.level(41), "good")
        self.assertEqual(self.level(40), "getting_low")
        self.assertEqual(self.level(30), "getting_low")
        self.assertEqual(self.level(20), "low")
        self.assertEqual(self.level(0), "low")

    def test_bar_is_measured_against_five_times_low_level(self):
        self.assertEqual(inventory.healthy_percent({"quantity": 80, "threshold": 20}), 80)
        self.assertEqual(inventory.healthy_percent({"quantity": 500, "threshold": 20}), 100)
        self.assertEqual(inventory.healthy_percent({"quantity": 5, "threshold": 0}), 100)


class StockTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.water = inventory.get_supply_by_name(self.store, "water")

    def test_seeded_supplies_match_demo(self):
        rows = inventory.list_supplies(self.store)
        self.assertEqual([(s["label"], s["quantity"], s["level"]) for s in rows],
                         [("Water", 100, "good"), ("Food", 80, "good"), ("First Aid Kits", 30, "getting_low")])

    def test_add_stock(self):
        self.assertEqual(inventory.add_stock(self.store, self.water["id"], "50"), 150)

    def test_remove_stock(self):
        self.assertEqual(inventory.remove_stock(self.store, self.water["id"], 40), 60)

    def test_cannot_remove_more_than_available(self):
        with self.assertRaises(inventory.InventoryError):
            inventory.remove_stock(self.store, self.water["id"], 101)

    def test_add_stock_rejects_zero(self):
        with self.assertRaises(inventory.InventoryError):
            inventory.add_stock(self.store, self.water["id"], 0)

    def test_set_stock_and_threshold(self):
        inventory.set_stock(self.store, self.water["id"], "20", "30")
        water = inventory.get_supply(self.store, self.water["id"])
        self.assertEqual((water["quantity"], water["threshold"]), (20, 30))

    def test_low_stock_detection(self):
        inventory.set_stock(self.store, self.water["id"], 20)
        self.assertEqual([s["name"] for s in inventory.low_stock(self.store)], ["water"])

    def test_unknown_supply(self):
        with self.assertRaises(inventory.InventoryError):
            inventory.add_stock(self.store, 999, 5)

    def test_add_supply_type_gets_default_low_level(self):
        inventory.add_supply_type(self.store, "Blankets", "pieces", "40")
        blankets = inventory.get_supply_by_name(self.store, "blankets")
        self.assertEqual((blankets["quantity"], blankets["threshold"]), (40, 20))

    def test_duplicate_supply_type_rejected(self):
        with self.assertRaises(inventory.InventoryError):
            inventory.add_supply_type(self.store, "WATER")

    def test_supply_name_rejects_markup(self):
        with self.assertRaises(inventory.InventoryError):
            inventory.add_supply_type(self.store, "<script>alert(1)</script>")

    def test_arabic_supply_name_allowed(self):
        inventory.add_supply_type(self.store, "بطانيات", "قطعة")
        self.assertIsNotNone(inventory.get_supply_by_name(self.store, "بطانيات"))

    def test_cannot_delete_supply_with_open_requests(self):
        uid = add_user(self.store)
        er.create_request(self.store, uid, 1, self.water["id"], 5, "low")
        with self.assertRaises(inventory.InventoryError):
            inventory.delete_supply_type(self.store, self.water["id"])

    def test_delete_unused_supply(self):
        sid = inventory.add_supply_type(self.store, "tents")
        self.assertTrue(inventory.delete_supply_type(self.store, sid))


class SupplyCsvTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()

    def test_import_adds_to_stock_and_creates_new(self):
        text = "item,quantity\nwater,50\nblankets,40\n"
        self.assertEqual(inventory.import_supplies_csv(self.store, text), (1, 1))
        self.assertEqual(inventory.get_supply_by_name(self.store, "water")["quantity"], 150)
        self.assertEqual(inventory.get_supply_by_name(self.store, "blankets")["quantity"], 40)

    def test_repeated_items_are_added_together(self):
        inventory.import_supplies_csv(self.store, "item,quantity\nWater,10\nwater,5\n")
        self.assertEqual(inventory.get_supply_by_name(self.store, "water")["quantity"], 115)

    def test_import_handles_bom_and_blank_lines(self):
        text = "﻿item,quantity\n\ntents,5\n"
        self.assertEqual(inventory.import_supplies_csv(self.store, text), (1, 0))

    def test_import_is_all_or_nothing(self):
        text = "item,quantity\nblankets,40\nwater,-5\n"
        with self.assertRaises(inventory.InventoryError) as ctx:
            inventory.import_supplies_csv(self.store, text)
        self.assertIn("Line 3", str(ctx.exception))
        self.assertIsNone(inventory.get_supply_by_name(self.store, "blankets"))

    def test_import_requires_header(self):
        with self.assertRaises(inventory.InventoryError):
            inventory.import_supplies_csv(self.store, "water,5\n")

    def test_import_requires_rows(self):
        with self.assertRaises(inventory.InventoryError):
            inventory.import_supplies_csv(self.store, "item,quantity\n")

    def test_csv_safe_blocks_formulas(self):
        self.assertEqual(inventory.csv_safe("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(inventory.csv_safe("water"), "water")


if __name__ == "__main__":
    unittest.main()
