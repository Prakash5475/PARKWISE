"""SQLite persistence layer.

One shared connection protected by an RLock (SQLite connections are cheap to share
when serialised).  Multi-statement operations use ``with db.tx():`` so that a bay
allocation, its ticket and its log line are committed atomically.

Integrity is enforced *in the database* as well as in Python:
  * ``ux_active_slot``     - at most one live session may hold a bay
  * ``ux_active_vehicle``  - a registration can have only one live session
  * ``ux_active_reservation_slot`` - a bay can have only one active reservation
"""
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from config import DB_PATH

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS vehicles(
  vehicle_number TEXT PRIMARY KEY, vehicle_type TEXT, color TEXT,
  accessible_permit INTEGER DEFAULT 0, first_seen TEXT, last_seen TEXT, visits INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS slots(
  slot_id TEXT PRIMARY KEY, floor TEXT, number INTEGER, category TEXT, status TEXT,
  vehicle_number TEXT DEFAULT '', session_id INTEGER, updated_at TEXT);
CREATE TABLE IF NOT EXISTS sessions(
  session_id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT UNIQUE NOT NULL,
  vehicle_number TEXT NOT NULL, vehicle_type TEXT, color TEXT, permit INTEGER DEFAULT 0,
  slot_id TEXT, gate TEXT, entry_time TEXT, entered_time TEXT, parked_time TEXT,
  checkout_time TEXT, bay_released_time TEXT, exit_time TEXT, planned_exit_time TEXT,
  status TEXT, payment_status TEXT DEFAULT 'UNPAID', payment_method TEXT,
  amount REAL DEFAULT 0, priority INTEGER DEFAULT 0, holds_slot INTEGER DEFAULT 1);
CREATE UNIQUE INDEX IF NOT EXISTS ux_active_slot ON sessions(slot_id) WHERE holds_slot=1;
CREATE UNIQUE INDEX IF NOT EXISTS ux_active_vehicle ON sessions(vehicle_number)
  WHERE status IN ('ASSIGNED','PARKED','CHECKOUT','EXITING');
CREATE INDEX IF NOT EXISTS ix_sessions_entry ON sessions(entry_time);
CREATE TABLE IF NOT EXISTS tickets(
  ticket_id TEXT PRIMARY KEY, session_id INTEGER, vehicle_number TEXT, slot_id TEXT,
  issued_at TEXT, gate TEXT, pdf_path TEXT);
CREATE TABLE IF NOT EXISTS bills(
  bill_id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT UNIQUE, session_id INTEGER,
  vehicle_number TEXT, vehicle_type TEXT, duration_s REAL, billed_minutes INTEGER,
  billed_hours INTEGER, rate REAL, time_scale REAL, base_amount REAL, tax_amount REAL,
  total_amount REAL, payment_method TEXT, payment_status TEXT, created_at TEXT,
  paid_at TEXT, receipt_path TEXT);
CREATE TABLE IF NOT EXISTS reservations(
  id INTEGER PRIMARY KEY AUTOINCREMENT, slot_id TEXT, vehicle_number TEXT, vehicle_type TEXT,
  permit INTEGER DEFAULT 0, created_at TEXT, expires_at TEXT, status TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_active_reservation_slot ON reservations(slot_id)
  WHERE status='ACTIVE';
CREATE TABLE IF NOT EXISTS queue(
  id INTEGER PRIMARY KEY AUTOINCREMENT, vehicle_number TEXT UNIQUE, vehicle_type TEXT,
  color TEXT, permit INTEGER DEFAULT 0, priority INTEGER DEFAULT 0, gate TEXT,
  planned_stay REAL, source TEXT, enqueued_at TEXT);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, category TEXT, message TEXT, source TEXT);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS occupancy_samples(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, occupied INTEGER, incoming INTEGER,
  reserved INTEGER, total INTEGER, floor_g INTEGER, floor_1 INTEGER, floor_2 INTEGER,
  queue_len INTEGER);
CREATE INDEX IF NOT EXISTS ix_samples_ts ON occupancy_samples(ts);
"""


class ParkingDatabase:
    def __init__(self, path=DB_PATH):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._depth = 0
        self.conn = sqlite3.connect(self.path, check_same_thread=False,
                                    isolation_level=None, timeout=15)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self._migrate_legacy()
            self.conn.executescript(SCHEMA)
            self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    # ---- low level ---------------------------------------------------------
    def execute(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params)

    def query(self, sql, params=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def scalar(self, sql, params=(), default=None):
        with self.lock:
            row = self.conn.execute(sql, params).fetchone()
            return default if row is None or row[0] is None else row[0]

    @contextmanager
    def tx(self):
        """Atomic transaction; nested use joins the outer transaction."""
        with self.lock:
            outer = self._depth == 0
            if outer:
                self.conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self.conn
            except BaseException:
                self._depth -= 1
                if outer:
                    self.conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outer:
                    self.conn.execute("COMMIT")

    def insert(self, table, row):
        cols = ",".join(row)
        marks = ",".join("?" * len(row))
        with self.lock:
            return self.conn.execute(f"INSERT INTO {table}({cols}) VALUES({marks})",
                                     tuple(row.values())).lastrowid

    def update(self, table, row, where, wparams=()):
        sets = ",".join(f"{k}=?" for k in row)
        with self.lock:
            self.conn.execute(f"UPDATE {table} SET {sets} WHERE {where}",
                              tuple(row.values()) + tuple(wparams))

    # ---- settings ------------------------------------------------------------
    def get_setting(self, key, default=None):
        return self.scalar("SELECT value FROM settings WHERE key=?", (key,), default)

    def set_setting(self, key, value):
        self.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    # ---- migration from the v1 prototype ---------------------------------------
    def _columns(self, table):
        return [r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")]

    def _migrate_legacy(self):
        """The v1 prototype used 'tickets'/'events' tables with a different layout.
        Rename them aside (never delete) and import finished tickets as history."""
        legacy_tickets = None
        cols = self._columns("tickets")
        if cols and "session_id" not in cols:
            self.conn.execute("ALTER TABLE tickets RENAME TO legacy_tickets_v1")
            legacy_tickets = "legacy_tickets_v1"
        cols = self._columns("events")
        if cols and "ts" not in cols:
            self.conn.execute("ALTER TABLE events RENAME TO legacy_events_v1")
        if legacy_tickets:
            self._legacy_import = legacy_tickets

    def finish_legacy_import(self):
        """Called once after the schema exists: copy completed v1 tickets into sessions."""
        name = getattr(self, "_legacy_import", None)
        if not name:
            return 0
        n = 0
        with self.tx():
            for r in self.query(f"SELECT * FROM {name} WHERE exit_time IS NOT NULL AND exit_time!=''"):
                try:
                    sid = self.insert("sessions", {
                        "ticket_id": r["ticket_id"], "vehicle_number": r["vehicle_number"],
                        "vehicle_type": r["vehicle_type"], "slot_id": r["slot_id"], "gate": "A",
                        "entry_time": str(r["entry_time"]).replace("T", " "),
                        "exit_time": str(r["exit_time"]).replace("T", " "),
                        "status": "COMPLETED", "payment_status": "PAID",
                        "amount": r["amount"] or 0, "priority": r.get("priority") or 0,
                        "holds_slot": 0})
                    self.insert("bills", {
                        "ticket_id": r["ticket_id"], "session_id": sid,
                        "vehicle_number": r["vehicle_number"], "vehicle_type": r["vehicle_type"],
                        "total_amount": r["amount"] or 0, "base_amount": r["amount"] or 0,
                        "tax_amount": 0, "payment_status": "PAID",
                        "created_at": str(r["exit_time"]).replace("T", " "),
                        "paid_at": str(r["exit_time"]).replace("T", " ")})
                    n += 1
                except sqlite3.IntegrityError:
                    pass
        self._legacy_import = None
        return n

    def close(self):
        with self.lock:
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self.conn.close()
