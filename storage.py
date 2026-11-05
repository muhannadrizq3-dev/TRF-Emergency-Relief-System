import os
import sqlite3
import ssl
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse, unquote, parse_qs

import settings

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id {pk},
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
        id {pk},
        name TEXT UNIQUE NOT NULL,
        area TEXT NOT NULL DEFAULT '',
        latitude DOUBLE PRECISION NOT NULL,
        longitude DOUBLE PRECISION NOT NULL,
        capacity INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS supply_types (
        id {pk},
        name TEXT UNIQUE NOT NULL,
        unit TEXT NOT NULL DEFAULT 'units',
        quantity INTEGER NOT NULL DEFAULT 0,
        threshold INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS requests (
        id {pk},
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
        id {pk},
        request_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        dispatched_by INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS activity (
        id {pk},
        user_id INTEGER,
        user_name TEXT NOT NULL,
        action TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS hospitals (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        latitude DOUBLE PRECISION NOT NULL,
        longitude DOUBLE PRECISION NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS doctors (
        id TEXT PRIMARY KEY,
        hospital_id TEXT NOT NULL,
        specialty TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Available'
    )""",
    """CREATE TABLE IF NOT EXISTS medical_requests (
        id {pk},
        shelter_id INTEGER NOT NULL,
        required_specialty TEXT NOT NULL,
        urgency TEXT NOT NULL DEFAULT 'High',
        status TEXT NOT NULL DEFAULT 'Pending Medical Dispatch - High Urgency',
        assigned_doctor_id TEXT,
        hospital_id TEXT,
        distance DOUBLE PRECISION,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS medical_dispatches (
        id {pk},
        medical_request_id INTEGER NOT NULL,
        doctor_id TEXT NOT NULL,
        hospital_id TEXT NOT NULL,
        distance DOUBLE PRECISION NOT NULL,
        dispatched_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS alerts (
        id {pk},
        message TEXT NOT NULL,
        channel TEXT NOT NULL,
        delivered INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
]

TABLES = ["users", "shelters", "supply_types", "requests", "dispatches", "alerts", "activity", "meta",
          "hospitals", "doctors", "medical_requests", "medical_dispatches"]


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
        return "/tmp/trf_relief.db"
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "instance", "trf_relief.db")


class Storage:

    def __init__(self, database_url=None, sqlite_path=None):
        url = settings.DATABASE_URL if database_url is None else database_url
        self.is_postgres = bool(url) and url.startswith(("postgres://", "postgresql://"))
        self._lock = threading.RLock()
        if self.is_postgres:
            self._url = url
            self._conn = self._connect_postgres(url)
        else:
            path = sqlite_path or default_sqlite_path()
            if path != ":memory:":
                os.makedirs(os.path.dirname(path), exist_ok=True)
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        self.create_schema()

    @staticmethod
    def _connect_postgres(url):
        import pg8000.dbapi

        parts = urlparse(url)
        query = parse_qs(parts.query)
        sslmode = (query.get("sslmode") or ["require"])[0]
        ssl_context = None
        if sslmode != "disable":
            ssl_context = ssl.create_default_context()
        conn = pg8000.dbapi.connect(
            user=unquote(parts.username or ""),
            password=unquote(parts.password or ""),
            host=parts.hostname,
            port=parts.port or 5432,
            database=(parts.path or "/").lstrip("/") or "postgres",
            ssl_context=ssl_context,
            timeout=10,
        )
        conn.autocommit = True
        return conn

    def _reconnect(self):
        if self.is_postgres:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = self._connect_postgres(self._url)

    def _sql(self, sql):
        return sql.replace("?", "%s") if self.is_postgres else sql

    def _run(self, sql, params=()):
        with self._lock:
            try:
                cur = self._conn.cursor()
                cur.execute(self._sql(sql), tuple(params))
                return cur
            except Exception as exc:
                if self.is_postgres and "network" in str(exc).lower():
                    self._reconnect()
                    cur = self._conn.cursor()
                    cur.execute(self._sql(sql), tuple(params))
                    return cur
                if self.is_postgres:
                    self._conn.rollback()
                raise

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
            if self.is_postgres:
                cur = self._run(sql + " RETURNING id", params)
                new_id = cur.fetchone()[0]
            else:
                cur = self._run(sql, params)
                new_id = cur.lastrowid
            self._conn.commit()
            return new_id

    def create_schema(self):
        pk = "SERIAL PRIMARY KEY" if self.is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
        for statement in SCHEMA:
            self.execute(statement.format(pk=pk))
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
        return "PostgreSQL" if self.is_postgres else "SQLite"


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


def clear_data(store):
    for table in ("medical_dispatches", "medical_requests", "dispatches", "requests", "alerts", "supply_types", "shelters"):
        store.clear(table)
    store.execute("UPDATE users SET shelter_id = NULL")
    store.execute("UPDATE doctors SET status = 'Available'")


def reset_demo(store):
    clear_data(store)
    seed_demo_data(store, force=True)


def start_empty(store):
    clear_data(store)
    store.set_meta("seeded", "1")
