from collections import defaultdict

import settings
from emergency_requests import RequestError, effective_priority, get_request, sort_key
from inventory import InventoryError, get_supply, parse_quantity
from storage import to_iso, utcnow


def fair_shares(available, demands):
    demands = [max(0, int(d)) for d in demands]
    available = max(0, int(available))
    total = sum(demands)
    if total == 0:
        return [0] * len(demands)
    if available >= total:
        return list(demands)

    exact = [available * d / total for d in demands]
    shares = [int(x) for x in exact]
    leftover = available - sum(shares)
    order = sorted(range(len(demands)), key=lambda i: (-(exact[i] - shares[i]), i))
    for i in order:
        if leftover == 0:
            break
        if shares[i] < demands[i]:
            shares[i] += 1
            leftover -= 1
    return shares


def plan_dispatch(open_requests, stock_by_supply, now=None):
    by_supply = defaultdict(list)
    for req in open_requests:
        if req["status"] in settings.OPEN_STATUSES:
            by_supply[int(req["supply_type_id"])].append(req)

    allocations = {}
    for supply_id, reqs in by_supply.items():
        stock = max(0, int(stock_by_supply.get(supply_id, 0)))
        reqs.sort(key=lambda r: sort_key(r, now))
        tiers = defaultdict(list)
        for req in reqs:
            eff = effective_priority(req["priority"], req["created_at"], now, req["status"])
            tiers[eff].append(req)
        for level in sorted(tiers, reverse=True):
            if stock <= 0:
                break
            tier = tiers[level]
            needs = [int(r["quantity"]) - int(r["delivered"]) for r in tier]
            shares = fair_shares(stock, needs)
            for req, share in zip(tier, shares):
                if share > 0:
                    allocations[req["id"]] = share
            stock -= sum(shares)
    return allocations


def _record(store, request, amount, user_id):
    store.insert(
        "INSERT INTO dispatches (request_id, quantity, dispatched_by, created_at) VALUES (?, ?, ?, ?)",
        (request["id"], amount, int(user_id), to_iso(utcnow())),
    )
    delivered = int(request["delivered"]) + amount
    status = settings.FULFILLED if delivered >= int(request["quantity"]) else settings.PARTIAL
    store.execute(
        "UPDATE requests SET delivered = ?, status = ?, updated_at = ? WHERE id = ?",
        (delivered, status, to_iso(utcnow()), request["id"]),
    )
    store.execute(
        "UPDATE supply_types SET quantity = quantity - ? WHERE id = ?",
        (amount, request["supply_type_id"]),
    )


def run_auto_dispatch(store, user_id, supply_type_id=None, now=None):
    sql = "SELECT * FROM requests WHERE status IN ('pending', 'partial')"
    params = ()
    if supply_type_id is not None:
        sql += " AND supply_type_id = ?"
        params = (int(supply_type_id),)
    open_requests = store.query(sql, params)
    stock = {int(s["id"]): int(s["quantity"]) for s in store.query("SELECT id, quantity FROM supply_types")}
    plan = plan_dispatch(open_requests, stock, now)
    by_id = {r["id"]: r for r in open_requests}
    for request_id, amount in plan.items():
        _record(store, by_id[request_id], amount, user_id)
    return plan


def dispatch_request(store, user_id, request_id, amount=None):
    request = get_request(store, request_id)
    if request is None or request["status"] not in settings.OPEN_STATUSES:
        raise RequestError("This request is not open.")
    supply = get_supply(store, request["supply_type_id"])
    remaining = int(request["quantity"]) - int(request["delivered"])
    if amount in (None, ""):
        amount = min(remaining, int(supply["quantity"]))
        if amount <= 0:
            raise RequestError("No stock available for this supply.")
    else:
        try:
            amount = parse_quantity(amount, allow_zero=False)
        except InventoryError as exc:
            raise RequestError(str(exc)) from None
    if amount > remaining:
        raise RequestError(f"Only {remaining} still needed.")
    if amount > int(supply["quantity"]):
        raise RequestError("Not enough stock.")
    _record(store, request, amount, user_id)
    return amount


def dispatch_history(store, limit=50):
    return store.query(
        """SELECT d.*, s.name AS shelter_name, t.name AS supply_name, u.display_name AS by_name
           FROM dispatches d
           JOIN requests r ON r.id = d.request_id
           JOIN shelters s ON s.id = r.shelter_id
           JOIN supply_types t ON t.id = r.supply_type_id
           LEFT JOIN users u ON u.id = d.dispatched_by
           ORDER BY d.id DESC LIMIT ?""",
        (int(limit),),
    )
