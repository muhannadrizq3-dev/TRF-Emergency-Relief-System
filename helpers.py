import re
from datetime import datetime, timedelta, timezone

import storage

NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)


def make_store(seed=True):
    store = storage.Storage(database_url="", sqlite_path=":memory:")
    if seed:
        storage.seed_demo_data(store)
    return store


def hours_ago(hours, now=NOW):
    return storage.to_iso(now - timedelta(hours=hours))


def fake_request(rid, supply=1, quantity=10, delivered=0, priority=2, hours=0, status="pending", sos=0):
    return {
        "id": rid, "supply_type_id": supply, "quantity": quantity, "delivered": delivered,
        "priority": priority, "created_at": hours_ago(hours), "status": status, "is_sos": sos,
    }


def add_user(store, username="coord", role="coordinator", password="Passw0rd!"):
    from werkzeug.security import generate_password_hash
    return store.insert(
        """INSERT INTO users (username, email, display_name, password_hash, role, shelter_id,
                              failed_attempts, locked_until, created_at)
           VALUES (?, ?, ?, ?, ?, NULL, 0, NULL, ?)""",
        (username, f"{username}@example.com", username.title(), generate_password_hash(password), role,
         storage.to_iso(NOW)),
    )


def get_user(store, uid):
    return store.query_one("SELECT * FROM users WHERE id = ?", (uid,))


class FakeSender:

    def __init__(self, ok=True, error=None):
        self.ok, self.error, self.calls = ok, error, []

    def __call__(self, cfg, text):
        self.calls.append((cfg, text))
        if self.error:
            raise self.error
        return self.ok


CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def csrf(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    match = CSRF_RE.search(html)
    assert match, f"no csrf token on {path}"
    return match.group(1)
