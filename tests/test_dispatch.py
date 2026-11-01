import unittest

import dispatch
import emergency_requests as er
import inventory
import settings
from tests.helpers import NOW, add_user, fake_request, make_store


class FairSharesTests(unittest.TestCase):
    def test_enough_stock_gives_everyone_full_amount(self):
        self.assertEqual(dispatch.fair_shares(100, [10, 20, 30]), [10, 20, 30])

    def test_exact_stock(self):
        self.assertEqual(dispatch.fair_shares(60, [10, 20, 30]), [10, 20, 30])

    def test_equal_split(self):
        self.assertEqual(dispatch.fair_shares(10, [6, 6]), [5, 5])

    def test_proportional_split(self):
        self.assertEqual(dispatch.fair_shares(50, [20, 80]), [10, 40])

    def test_largest_remainder_gets_extra_unit(self):
        self.assertEqual(dispatch.fair_shares(7, [4, 4, 4]), [3, 2, 2])

    def test_largest_remainder_prefers_bigger_fraction(self):
        self.assertEqual(dispatch.fair_shares(8, [3, 6]), [3, 5])

    def test_shares_always_sum_to_available(self):
        for available in range(0, 40):
            shares = dispatch.fair_shares(available, [7, 13, 5, 9])
            self.assertEqual(sum(shares), min(available, 34))

    def test_never_more_than_demand(self):
        shares = dispatch.fair_shares(99, [1, 50, 2])
        for share, demand in zip(shares, [1, 50, 2]):
            self.assertLessEqual(share, demand)

    def test_zero_stock(self):
        self.assertEqual(dispatch.fair_shares(0, [5, 5]), [0, 0])

    def test_zero_demand(self):
        self.assertEqual(dispatch.fair_shares(10, [0, 0]), [0, 0])

    def test_empty_list(self):
        self.assertEqual(dispatch.fair_shares(10, []), [])

    def test_negative_values_treated_as_zero(self):
        self.assertEqual(dispatch.fair_shares(-5, [3, -2]), [0, 0])


class PlanDispatchTests(unittest.TestCase):
    def test_higher_priority_served_first(self):
        reqs = [fake_request(1, priority=1, quantity=10), fake_request(2, priority=4, quantity=10)]
        plan = dispatch.plan_dispatch(reqs, {1: 10}, NOW)
        self.assertEqual(plan, {2: 10})

    def test_shortage_shared_inside_tier(self):
        reqs = [fake_request(1, priority=3, quantity=60), fake_request(2, priority=3, quantity=40)]
        plan = dispatch.plan_dispatch(reqs, {1: 50}, NOW)
        self.assertEqual(plan, {1: 30, 2: 20})

    def test_lower_tier_gets_leftover(self):
        reqs = [fake_request(1, priority=4, quantity=30), fake_request(2, priority=2, quantity=30)]
        plan = dispatch.plan_dispatch(reqs, {1: 50}, NOW)
        self.assertEqual(plan, {1: 30, 2: 20})

    def test_escalated_request_joins_higher_tier(self):
        reqs = [fake_request(1, priority=1, quantity=10, hours=48), fake_request(2, priority=3, quantity=10)]
        plan = dispatch.plan_dispatch(reqs, {1: 10}, NOW)
        self.assertEqual(plan, {1: 5, 2: 5})

    def test_partial_requests_only_get_remaining(self):
        reqs = [fake_request(1, quantity=10, delivered=7, status="partial")]
        self.assertEqual(dispatch.plan_dispatch(reqs, {1: 100}, NOW), {1: 3})

    def test_closed_requests_ignored(self):
        reqs = [fake_request(1, status="fulfilled"), fake_request(2, status="cancelled")]
        self.assertEqual(dispatch.plan_dispatch(reqs, {1: 100}, NOW), {})

    def test_supplies_are_independent(self):
        reqs = [fake_request(1, supply=1, quantity=5), fake_request(2, supply=2, quantity=5)]
        self.assertEqual(dispatch.plan_dispatch(reqs, {1: 5, 2: 0}, NOW), {1: 5})


class DispatchDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.uid = add_user(self.store)
        self.water = inventory.get_supply_by_name(self.store, "water")["id"]

    def make(self, qty, priority="medium"):
        return er.create_request(self.store, self.uid, 1, self.water, qty, priority, now=NOW)

    def test_auto_dispatch_updates_stock_and_status(self):
        rid = self.make(60)
        plan = dispatch.run_auto_dispatch(self.store, self.uid, now=NOW)
        self.assertEqual(plan, {rid: 60})
        self.assertEqual(er.get_request(self.store, rid)["status"], settings.FULFILLED)
        self.assertEqual(inventory.get_supply(self.store, self.water)["quantity"], 40)

    def test_auto_dispatch_partial_when_short(self):
        inventory.set_stock(self.store, self.water, 30)
        rid = self.make(100)
        dispatch.run_auto_dispatch(self.store, self.uid, now=NOW)
        req = er.get_request(self.store, rid)
        self.assertEqual((req["delivered"], req["status"]), (30, settings.PARTIAL))

    def test_auto_dispatch_records_history(self):
        self.make(10)
        dispatch.run_auto_dispatch(self.store, self.uid, now=NOW)
        history = dispatch.dispatch_history(self.store)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["quantity"], 10)

    def test_manual_dispatch_default_amount(self):
        rid = self.make(25)
        self.assertEqual(dispatch.dispatch_request(self.store, self.uid, rid), 25)

    def test_manual_dispatch_rejects_too_much(self):
        rid = self.make(5)
        with self.assertRaises(er.RequestError):
            dispatch.dispatch_request(self.store, self.uid, rid, "6")

    def test_manual_dispatch_rejects_more_than_stock(self):
        inventory.set_stock(self.store, self.water, 3)
        rid = self.make(5)
        with self.assertRaises(er.RequestError):
            dispatch.dispatch_request(self.store, self.uid, rid, "4")

    def test_competition_example_50_food_split_30_20(self):
        food = inventory.get_supply_by_name(self.store, "food")["id"]
        inventory.set_stock(self.store, food, 50)
        a = er.create_request(self.store, self.uid, 1, food, 60, "high", now=NOW)
        b = er.create_request(self.store, self.uid, 2, food, 40, "high", now=NOW)
        self.assertEqual(dispatch.run_auto_dispatch(self.store, self.uid, now=NOW), {a: 30, b: 20})
        self.assertEqual(inventory.get_supply(self.store, food)["quantity"], 0)

    def test_manual_dispatch_on_closed_request_fails(self):
        rid = self.make(5)
        er.set_status(self.store, rid, settings.CANCELLED)
        with self.assertRaises(er.RequestError):
            dispatch.dispatch_request(self.store, self.uid, rid)


if __name__ == "__main__":
    unittest.main()
