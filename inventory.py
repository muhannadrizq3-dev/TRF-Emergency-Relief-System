import csv
import io
import re

import settings


class InventoryError(ValueError):
    pass


NAME_RE = re.compile(r"^[A-Za-z0-9؀-ۿ][A-Za-z0-9؀-ۿ _\-]{0,%d}$" % (settings.MAX_NAME_LENGTH - 1))


def parse_quantity(value, allow_zero=True, maximum=settings.MAX_STOCK_QUANTITY):
    if isinstance(value, bool):
        raise InventoryError("Quantity must be a whole number.")
    if isinstance(value, int):
        number = value
    else:
        text = str(value or "").strip()
        if not re.fullmatch(r"\d+", text):
            raise InventoryError("Quantity must be a whole number (no negatives or decimals).")
        number = int(text)
    if number < 0:
        raise InventoryError("Quantity cannot be negative.")
    if number == 0 and not allow_zero:
        raise InventoryError("Quantity must be at least 1.")
    if number > maximum:
        raise InventoryError(f"Quantity cannot be more than {maximum:,}.")
    return number


def clean_name(value, label="Name"):
    text = " ".join(str(value or "").split())
    if not text:
        raise InventoryError(f"{label} is required.")
    if not NAME_RE.match(text):
        raise InventoryError(f"{label} may only contain letters, numbers, spaces, '-' and '_'.")
    return text


def list_supplies(store):
    rows = store.query("SELECT * FROM supply_types ORDER BY id")
    for row in rows:
        row["low"] = is_low(row)
        row["level"] = stock_level(row)
        row["percent"] = healthy_percent(row)
        row["label"] = row["name"].title()
    return rows


def stock_level(supply):
    qty, threshold = int(supply["quantity"]), int(supply["threshold"])
    if qty <= threshold:
        return "low"
    if qty <= threshold * settings.GETTING_LOW_FACTOR:
        return "getting_low"
    return "good"


def healthy_percent(supply):
    healthy = max(1, int(supply["threshold"]) * settings.HEALTHY_FACTOR)
    return max(0, min(100, round(100 * int(supply["quantity"]) / healthy)))


def get_supply(store, supply_id):
    return store.query_one("SELECT * FROM supply_types WHERE id = ?", (supply_id,))


def get_supply_by_name(store, name):
    return store.query_one("SELECT * FROM supply_types WHERE LOWER(name) = LOWER(?)", (name,))


def is_low(supply):
    return int(supply["quantity"]) <= int(supply["threshold"])


def low_stock(store):
    return [s for s in list_supplies(store) if s["low"]]


def add_supply_type(store, name, unit="units", quantity=0, threshold=settings.DEFAULT_THRESHOLD):
    name = clean_name(name, "Supply name").lower()
    unit = clean_name(unit or "units", "Unit")
    quantity = parse_quantity(quantity)
    threshold = parse_quantity(threshold)
    if get_supply_by_name(store, name):
        raise InventoryError(f"Supply type '{name}' already exists.")
    return store.insert(
        "INSERT INTO supply_types (name, unit, quantity, threshold) VALUES (?, ?, ?, ?)",
        (name, unit, quantity, threshold),
    )


def delete_supply_type(store, supply_id):
    in_use = store.query_one(
        "SELECT COUNT(*) AS n FROM requests WHERE supply_type_id = ? AND status IN ('pending', 'partial')",
        (supply_id,),
    )
    if in_use and int(in_use["n"]) > 0:
        raise InventoryError("This supply type still has open requests.")
    return store.execute("DELETE FROM supply_types WHERE id = ?", (supply_id,)) > 0


def set_stock(store, supply_id, quantity, threshold=None):
    quantity = parse_quantity(quantity)
    if not get_supply(store, supply_id):
        raise InventoryError("Unknown supply type.")
    if threshold is None:
        store.execute("UPDATE supply_types SET quantity = ? WHERE id = ?", (quantity, supply_id))
    else:
        threshold = parse_quantity(threshold)
        store.execute(
            "UPDATE supply_types SET quantity = ?, threshold = ? WHERE id = ?",
            (quantity, threshold, supply_id),
        )


def add_stock(store, supply_id, amount):
    amount = parse_quantity(amount, allow_zero=False)
    supply = get_supply(store, supply_id)
    if not supply:
        raise InventoryError("Unknown supply type.")
    new_total = int(supply["quantity"]) + amount
    if new_total > settings.MAX_STOCK_QUANTITY:
        raise InventoryError("Stock would exceed the maximum allowed.")
    store.execute("UPDATE supply_types SET quantity = ? WHERE id = ?", (new_total, supply_id))
    return new_total


def remove_stock(store, supply_id, amount):
    amount = parse_quantity(amount, allow_zero=False)
    supply = get_supply(store, supply_id)
    if not supply:
        raise InventoryError("Unknown supply type.")
    if amount > int(supply["quantity"]):
        raise InventoryError("Not enough stock.")
    new_total = int(supply["quantity"]) - amount
    store.execute("UPDATE supply_types SET quantity = ? WHERE id = ?", (new_total, supply_id))
    return new_total


CSV_COLUMNS = ("name", "unit", "quantity", "threshold")
MAX_CSV_ROWS = 500


def read_csv(text, required):
    reader = csv.DictReader(io.StringIO((text or "").lstrip("\ufeff")))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in required if c not in headers]
    if missing:
        raise InventoryError("The first row must hold the column names: " + ",".join(required))
    rows = []
    for line_no, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k is not None}
        if not any(row.values()):
            continue
        rows.append((line_no, row))
        if len(rows) > MAX_CSV_ROWS:
            raise InventoryError(f"CSV is limited to {MAX_CSV_ROWS} rows.")
    if not rows:
        raise InventoryError("The CSV file has no data rows.")
    return rows


def import_supplies_csv(store, text):
    parsed = {}
    for line_no, row in read_csv(text, ("item", "quantity")):
        try:
            name = clean_name(row.get("item"), "Item").lower()
            qty = parse_quantity(row.get("quantity"))
            unit = clean_name(row.get("unit") or "units", "Unit")
        except InventoryError as exc:
            raise InventoryError(f"Line {line_no}: {exc}") from None
        total, first_unit = parsed.get(name, (0, unit))
        parsed[name] = (total + qty, first_unit)

    for name, (qty, _) in parsed.items():
        existing = get_supply_by_name(store, name)
        if existing and int(existing["quantity"]) + qty > settings.MAX_STOCK_QUANTITY:
            raise InventoryError(f"Stock of {name} would exceed the maximum allowed.")

    created = updated = 0
    for name, (qty, unit) in parsed.items():
        existing = get_supply_by_name(store, name)
        if existing:
            store.execute("UPDATE supply_types SET quantity = quantity + ? WHERE id = ?", (qty, existing["id"]))
            updated += 1
        else:
            store.insert(
                "INSERT INTO supply_types (name, unit, quantity, threshold) VALUES (?, ?, ?, ?)",
                (name, unit, qty, settings.DEFAULT_THRESHOLD),
            )
            created += 1
    return created, updated


def csv_safe(value):
    text = str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def export_stock_csv(store):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for s in list_supplies(store):
        writer.writerow([csv_safe(s["name"]), csv_safe(s["unit"]), s["quantity"], s["threshold"]])
    return out.getvalue()
