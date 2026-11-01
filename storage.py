import os
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone

import settings

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        shelter_id INTEGER,
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        locked_until TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS shelters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        area TEXT NOT NULL DEFAULT '',
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        capacity INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS supply_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        unit TEXT NOT NULL DEFAULT 'units',
        quantity INTEGER NOT NULL DEFAULT 0,
        threshold INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shelter_id INTEGER NOT NULL,
        supply_type_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        delivered INTEGER NOT NULL DEFAULT 0,
        priority INTEGER NOT NULL,
        status TEXT NOT NULL,
        is_sos INTEGER NOT NULL DEFAULT 0,
        note TEXT NOT NULL DEFAULT '',
        created_by INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS dispatches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        dispatched_by INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        user_name TEXT NOT NULL,
        action TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message TEXT NOT NULL,
        channel TEXT NOT NULL,
        delivered INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
]

TABLES = ["users", "shelters", "supply_types", "requests", "dispatches", "alerts", "activity", "meta"]


def utcnow():
    return datetime.now(timezone.utc)


def to_iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_iso(text):
    if not text:
        return None
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def default_sqlite_path():
    if settings.ON_VERCEL:
        return os.path.join(tempfile.gettempdir(), "trf_relief.db")
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "instance", "trf_relief.db")


def open_sqlite(path):
    if path == ":memory:":
        return sqlite3.connect(path, check_same_thread=False)
    candidates = [path, os.path.join(tempfile.gettempdir(), "trf_relief.db")]
    for candidate in candidates:
        try:
            os.makedirs(os.path.dirname(candidate), exist_ok=True)
            conn = sqlite3.connect(candidate, check_same_thread=False)
            conn.execute("CREATE TABLE IF NOT EXISTS _write_check (x INTEGER)")
            conn.commit()
            return conn
        except (OSError, sqlite3.Error):
            continue
    return sqlite3.connect(":memory:", check_same_thread=False)


class Storage:

    def __init__(self, sqlite_path=None):
        self._lock = threading.RLock()
        self._conn = open_sqlite(sqlite_path or default_sqlite_path())
        self._conn.row_factory = sqlite3.Row
        self.create_schema()

    def _run(self, sql, params=()):
        cur = self._conn.cursor()
        cur.execute(sql, tuple(params))
        return cur

    def _rows(self, cur):
        if cur.description is None:
            return []
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]

    def query(self, sql, params=()):
        with self._lock:
            return self._rows(self._run(sql, params))

    def query_one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql, params=()):
        with self._lock:
            cur = self._run(sql, params)
            self._conn.commit()
            return cur.rowcount

    def insert(self, sql, params=()):
        with self._lock:
            cur = self._run(sql, params)
            self._conn.commit()
            return cur.lastrowid

    def create_schema(self):
        for statement in SCHEMA:
            self.execute(statement)
        try:
            self.query("SELECT email FROM users LIMIT 1")
        except Exception:
            self.execute("ALTER TABLE users ADD COLUMN email TEXT")

    def get_meta(self, key):
        row = self.query_one("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else None

    def set_meta(self, key, value):
        if self.get_meta(key) is None:
            self.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (key, str(value)))
        else:
            self.execute("UPDATE meta SET value = ? WHERE key = ?", (str(value), key))

    def count(self, table):
        if table not in TABLES:
            raise ValueError("unknown table")
        row = self.query_one(f"SELECT COUNT(*) AS n FROM {table}")
        return int(row["n"])

    def clear(self, table):
        if table not in TABLES:
            raise ValueError("unknown table")
        self.execute(f"DELETE FROM {table}")

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def __del__(self):
        self.close()

    @property
    def backend_name(self):
        return "SQLite"


def seed_demo_data(store, force=False):
    if store.get_meta("seeded") and not force:
        return
    store.set_meta("seeded", "1")
    if store.count("supply_types") == 0:
        for name, unit, qty, threshold in settings.DEFAULT_SUPPLY_TYPES:
            store.insert(
                "INSERT INTO supply_types (name, unit, quantity, threshold) VALUES (?, ?, ?, ?)",
                (name, unit, qty, threshold),
            )
    if store.count("shelters") == 0:
        for name, area, lat, lng, cap in settings.DEMO_SHELTERS:
            store.insert(
                "INSERT INTO shelters (name, area, latitude, longitude, capacity) VALUES (?, ?, ?, ?, ?)",
                (name, area, lat, lng, cap),
            )


def seed_team_accounts(store):
    for username, name, email, password_hash in settings.TEAM_ACCOUNTS:
        existing = store.query_one("SELECT id, email FROM users WHERE LOWER(username) = LOWER(?)", (username,))
        if existing:
            if not existing["email"] and email:
                store.execute("UPDATE users SET email = ? WHERE id = ?", (email, existing["id"]))
            continue
        store.insert(
            """INSERT INTO users (username, email, display_name, password_hash, role, shelter_id,
                                  failed_attempts, locked_until, created_at)
               VALUES (?, ?, ?, ?, ?, NULL, 0, NULL, ?)""",
            (username, email, name, password_hash, settings.COORDINATOR, to_iso(utcnow())),
        )


def clear_data(store):
    for table in ("dispatches", "requests", "alerts", "supply_types", "shelters"):
        store.clear(table)
    store.execute("UPDATE users SET shelter_id = NULL")


def reset_demo(store):
    clear_data(store)
    seed_demo_data(store, force=True)


def start_empty(store):
    clear_data(store)
    store.set_meta("seeded", "1")
