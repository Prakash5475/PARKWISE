"""ParkingManager — the single owner of all shared parking state.

Concurrency model
-----------------
Every public method that reads or writes shared state takes ``self.lock`` (a
re-entrant lock).  Slot selection and slot assignment happen inside ONE critical
section, which is what makes duplicate bay allocation impossible even with two
entry-gate threads racing.  The database adds a second line of defence through
unique partial indexes (see core/database.py).

Lock ordering is always  manager.lock -> db.lock  (the DB never calls back into the
manager), so the two cannot deadlock.

The manager never touches Tkinter or the vehicle simulation.  It publishes domain
events (``subscribe``) which the ThreadManager routes to the worker queues.

Session life-cycle
------------------
ASSIGNED  ticket issued, bay held (slot INCOMING) while the vehicle drives in
PARKED    vehicle is in its bay (slot OCCUPIED)
CHECKOUT  checkout requested, billing thread is processing the payment
EXITING   paid; the vehicle is driving out (bay released when it pulls out)
COMPLETED vehicle has left through the exit gate
"""
import csv
import re
import threading
import uuid
from collections import deque
from datetime import datetime, timedelta

from config import (FLOORS, SLOTS_PER_FLOOR, SLOT_LAYOUT, RATES, DEFAULT_TIME_SCALE,
                    VEHICLE_TYPES, WAITING_CAPACITY)
from core import billing
from core.allocation import AllocationEngine, tiers
from core.locks import TrackedRLock
from core.models import (AVAILABLE, OCCUPIED, RESERVED, INCOMING, SlotInfo, Session,
                         VehicleSpec, EntryResult, ACTIVE_STATUSES, S_ASSIGNED, S_PARKED,
                         S_CHECKOUT, S_EXITING, S_COMPLETED)

TS_FMT = "%Y-%m-%d %H:%M:%S"
REG_RE = re.compile(r"^[A-Z0-9]{4,12}$")


def fmt(dt):
    return dt.strftime(TS_FMT)


def parse(ts):
    return datetime.strptime(ts, TS_FMT) if ts else None


def normalize_reg(text):
    reg = re.sub(r"[\s\-]", "", (text or "").upper())
    if not reg:
        raise ValueError("Enter a vehicle registration number.")
    if not REG_RE.match(reg):
        raise ValueError("Registration must be 4-12 letters or digits (e.g. MH15AB1234).")
    return reg


class ParkingManager:
    def __init__(self, db, engine=None, clock=None):
        self.db = db
        self.engine = engine or AllocationEngine()
        self.lock = TrackedRLock("ParkingManager.lock")
        self.clock = clock or datetime.now          # injectable for tests
        self.slots = {}          # slot_id -> SlotInfo
        self.sessions = {}       # session_id -> Session (live sessions only)
        self.queue = []          # waiting vehicles (dicts), see _queue_entry()
        self.pending = {}        # reg -> VehicleSpec (registered, still driving to a gate)
        self.reservations = {}   # slot_id -> dict (active reservations)
        self.counters = {"entered": 0, "exited": 0, "revenue": 0.0}
        self.events = deque(maxlen=300)
        self.version = 0
        self.full_flag = False
        self._listeners = []
        self.time_scale = float(db.get_setting("time_scale", DEFAULT_TIME_SCALE))
        db.finish_legacy_import()
        self._load()

    # ================================================================= infra
    def subscribe(self, fn):
        self._listeners.append(fn)

    def _emit(self, kind, **data):
        for fn in list(self._listeners):
            try:
                fn(kind, data)
            except Exception:                       # a listener must never break the core
                pass

    def _touch(self):
        self.version += 1

    def now(self):
        return self.clock().replace(microsecond=0)

    def _log(self, category, message):
        ts = fmt(self.now())
        src = threading.current_thread().name
        self.events.appendleft({"ts": ts, "category": category, "message": message, "source": src})
        try:
            self.db.execute("INSERT INTO events(ts,category,message,source) VALUES(?,?,?,?)",
                            (ts, category, message, src))
        except Exception:
            pass

    def log(self, category, message):
        with self.lock:
            self._log(category, message)
            self._touch()

    # ================================================================= load
    def _load(self):
        with self.lock, self.db.tx():
            rows = {r["slot_id"]: r for r in self.db.query("SELECT * FROM slots")}
            for f in FLOORS:
                for n in range(1, SLOTS_PER_FLOOR + 1):
                    sid = f"{f}-{n:02d}"
                    s = SlotInfo(sid, f, n, SLOT_LAYOUT[n])
                    r = rows.get(sid)
                    if r:
                        s.status, s.vehicle_number = r["status"], r["vehicle_number"] or ""
                        s.session_id = r["session_id"]
                    else:
                        self.db.insert("slots", {"slot_id": sid, "floor": f, "number": n,
                                                 "category": s.category, "status": AVAILABLE,
                                                 "vehicle_number": "", "session_id": None,
                                                 "updated_at": fmt(self.now())})
                    self.slots[sid] = s
            for r in self.db.query("SELECT * FROM sessions WHERE status IN (?,?,?,?)", ACTIVE_STATUSES):
                r["permit"], r["priority"] = bool(r["permit"]), bool(r["priority"])
                r["holds_slot"] = bool(r["holds_slot"])
                self.sessions[r["session_id"]] = Session(**r)
            for r in self.db.query("SELECT * FROM reservations WHERE status='ACTIVE'"):
                self.reservations[r["slot_id"]] = r
            self.queue = [self._row_to_queue(r) for r in
                          self.db.query("SELECT * FROM queue ORDER BY id")]
            self._repair_slots()
            self.counters["entered"] = self.db.scalar(
                "SELECT COUNT(*) FROM sessions WHERE entered_time IS NOT NULL", default=0)
            self.counters["exited"] = self.db.scalar(
                "SELECT COUNT(*) FROM sessions WHERE status='COMPLETED'", default=0)
            self.counters["revenue"] = float(self.db.scalar(
                "SELECT SUM(total_amount) FROM bills WHERE payment_status='PAID'", default=0.0))
            self._touch()

    def _repair_slots(self):
        """Make slot rows consistent with the live sessions/reservations after a restart."""
        for s in self.slots.values():
            s.status, s.vehicle_number, s.session_id = AVAILABLE, "", None
            s.reserved_for = s.reserved_until = ""
        for sess in self.sessions.values():
            if sess.holds_slot and sess.slot_id in self.slots:
                s = self.slots[sess.slot_id]
                s.status = INCOMING if sess.status == S_ASSIGNED else OCCUPIED
                s.vehicle_number, s.session_id = sess.vehicle_number, sess.session_id
        for sid, r in list(self.reservations.items()):
            s = self.slots.get(sid)
            if s is None or s.status != AVAILABLE:
                self.db.update("reservations", {"status": "CANCELLED"}, "id=?", (r["id"],))
                del self.reservations[sid]
                continue
            s.status, s.reserved_for, s.reserved_until = RESERVED, r["vehicle_number"], r["expires_at"] or ""
        for s in self.slots.values():
            self._save_slot(s)

    # ================================================================= helpers
    def _save_slot(self, s):
        self.db.update("slots", {"status": s.status, "vehicle_number": s.vehicle_number,
                                 "session_id": s.session_id, "updated_at": fmt(self.now())},
                       "slot_id=?", (s.slot_id,))

    def _save_session(self, sess):
        d = sess.to_dict()
        sid = d.pop("session_id")
        d["permit"], d["priority"], d["holds_slot"] = int(d["permit"]), int(d["priority"]), int(d["holds_slot"])
        self.db.update("sessions", d, "session_id=?", (sid,))

    def _row_to_queue(self, r):
        return {"reg": r["vehicle_number"], "vtype": r["vehicle_type"], "color": r["color"],
                "permit": bool(r["permit"]), "priority": bool(r["priority"]), "gate": r["gate"],
                "planned_stay": r["planned_stay"], "source": r["source"],
                "enqueued_at": r["enqueued_at"]}

    def _spec_from_queue(self, q):
        return VehicleSpec(q["reg"], q["vtype"], q["color"], q["permit"], None, q["gate"],
                           q["planned_stay"], q["source"])

    def _known_regs(self):
        regs = set(self.pending) | {q["reg"] for q in self.queue}
        regs |= {s.vehicle_number for s in self.sessions.values()}
        return regs

    def _ordered_queue(self):
        return sorted(self.queue, key=lambda q: (not q["priority"], q["enqueued_at"], q["reg"]))

    def waiting_count(self):
        with self.lock:
            return len(self.queue)

    def pending_count(self):
        with self.lock:
            return len(self.pending)

    # ================================================================= registration
    def register_arrival(self, spec):
        """Validate and register a vehicle that is about to drive to an entry gate.
        Raises ValueError for invalid / duplicate input."""
        spec.reg = normalize_reg(spec.reg)
        if spec.vtype not in VEHICLE_TYPES:
            raise ValueError("Select a valid vehicle category.")
        if spec.gate not in ("A", "B"):
            raise ValueError("Select entry gate A or B.")
        with self.lock:
            if spec.reg in self._known_regs():
                raise ValueError(f"{spec.reg} is already registered (parked, waiting or arriving).")
            if len(self.queue) >= WAITING_CAPACITY:
                raise ValueError(f"The waiting area is full ({WAITING_CAPACITY} vehicles). "
                                 "Try again after a bay is released.")
            if len(self.pending) >= 6:
                raise ValueError("Entry roads are congested - wait for vehicles to clear the gates.")
            if spec.preferred_slot:
                self.engine.validate_preferred(spec, self.slots.get(spec.preferred_slot))
            if any(r["vehicle_number"] == spec.reg for r in self.reservations.values()) \
                    and spec.preferred_slot and self.slots[spec.preferred_slot].reserved_for != spec.reg:
                raise ValueError(f"{spec.reg} holds a reservation; leave bay selection on Auto.")
            self.pending[spec.reg] = spec
            self._touch()
        return spec

    def cancel_arrival(self, reg):
        with self.lock:
            self.pending.pop(reg, None)
            self._touch()

    # ================================================================= entry / allocation
    def request_entry(self, reg, gate=None):
        """Called by an entry-gate thread when a vehicle is detected at the ticket point.
        Atomically chooses a bay and assigns it, or places the vehicle in the waiting queue."""
        with self.lock:
            spec = self.pending.get(reg)
            if spec is None:
                raise KeyError(f"{reg} is not registered as arriving.")
            gate = gate or spec.gate
            slot_id = None
            if spec.preferred_slot:
                s = self.slots.get(spec.preferred_slot)
                try:
                    self.engine.validate_preferred(spec, s)
                    slot_id = s.slot_id
                except ValueError as e:
                    self._log("ALLOC", f"{spec.reg}: {e} Falling back to automatic allocation.")
            if slot_id is None:
                slot_id = self.engine.choose(spec, self.slots)
            if slot_id is not None:
                del self.pending[reg]
                sess = self._assign(spec, slot_id, gate)
                return EntryResult("ASSIGNED", sess)
            # nothing suitable: wait in the queue
            del self.pending[reg]
            q = {"reg": spec.reg, "vtype": spec.vtype, "color": spec.color, "permit": spec.permit,
                 "priority": spec.priority, "gate": gate, "planned_stay": spec.planned_stay,
                 "source": spec.source, "enqueued_at": fmt(self.now())}
            self.queue.append(q)
            self.db.insert("queue", {"vehicle_number": q["reg"], "vehicle_type": q["vtype"],
                                     "color": q["color"], "permit": int(q["permit"]),
                                     "priority": int(q["priority"]), "gate": gate,
                                     "planned_stay": q["planned_stay"], "source": q["source"],
                                     "enqueued_at": q["enqueued_at"]})
            free = sum(s.status == AVAILABLE for s in self.slots.values())
            if free == 0:
                self._log("FULL", f"Parking full - {spec.reg} ({spec.vtype}) added to the waiting queue")
            else:
                self._log("QUEUE", f"No suitable bay for {spec.reg} ({spec.vtype}) - added to the waiting queue")
            self._touch()
            pos = self._ordered_queue().index(q) + 1
            return EntryResult("QUEUED", None, pos, "no suitable bay")

    def _assign(self, spec, slot_id, gate):
        """Assign *slot_id* to *spec*. Caller holds the lock."""
        slot = self.slots[slot_id]
        if not (slot.status == AVAILABLE or (slot.status == RESERVED and slot.reserved_for == spec.reg)):
            raise RuntimeError(f"Refusing to double-allocate {slot_id} ({slot.status})")
        now = self.now()
        ticket = "PW-" + uuid.uuid4().hex[:8].upper()
        planned = fmt(now + timedelta(seconds=spec.planned_stay)) if spec.planned_stay else None
        with self.db.tx():
            was_reserved = slot.status == RESERVED
            sess = Session(0, ticket, spec.reg, spec.vtype, spec.color, spec.permit, slot_id, gate,
                           fmt(now), planned_exit_time=planned, status=S_ASSIGNED,
                           priority=spec.priority)
            row = sess.to_dict()
            row.pop("session_id")
            row["permit"], row["priority"], row["holds_slot"] = int(row["permit"]), int(row["priority"]), 1
            sess.session_id = self.db.insert("sessions", row)
            self.db.insert("tickets", {"ticket_id": ticket, "session_id": sess.session_id,
                                       "vehicle_number": spec.reg, "slot_id": slot_id,
                                       "issued_at": fmt(now), "gate": gate})
            if was_reserved:
                r = self.reservations.pop(slot_id)
                self.db.update("reservations", {"status": "FULFILLED"}, "id=?", (r["id"],))
            slot.status, slot.vehicle_number, slot.session_id = INCOMING, spec.reg, sess.session_id
            slot.reserved_for = slot.reserved_until = ""
            self._save_slot(slot)
            self.db.execute(
                "INSERT INTO vehicles(vehicle_number,vehicle_type,color,accessible_permit,first_seen,last_seen,visits)"
                " VALUES(?,?,?,?,?,?,1) ON CONFLICT(vehicle_number) DO UPDATE SET "
                "vehicle_type=excluded.vehicle_type,color=excluded.color,"
                "accessible_permit=excluded.accessible_permit,last_seen=excluded.last_seen,visits=visits+1",
                (spec.reg, spec.vtype, spec.color, int(spec.permit), fmt(now), fmt(now)))
            self._log("ALLOC", f"Bay {slot_id} allocated to {spec.reg} ({spec.vtype}) - ticket {ticket}")
        self.sessions[sess.session_id] = sess
        self._touch()
        return sess

    def _process_queue_locked(self):
        """Assign any waiting vehicle that now has a suitable bay. VIPs first, then FIFO.
        A vehicle that still has no suitable bay does not block the ones behind it."""
        assigned = []
        for q in self._ordered_queue():
            spec = self._spec_from_queue(q)
            slot_id = self.engine.choose(spec, self.slots)
            if slot_id is None:
                continue
            self.queue.remove(q)
            self.db.execute("DELETE FROM queue WHERE vehicle_number=?", (q["reg"],))
            sess = self._assign(spec, slot_id, "A")
            self._log("QUEUE", f"{spec.reg} released from the waiting queue to bay {slot_id}")
            assigned.append(sess)
            self._emit("queue_assigned", session=sess)
        return assigned

    def process_queue(self):
        with self.lock:
            return self._process_queue_locked()

    def cancel_queue(self, reg):
        with self.lock:
            q = next((x for x in self.queue if x["reg"] == reg), None)
            if not q:
                raise ValueError(f"{reg} is not in the waiting queue.")
            self.queue.remove(q)
            self.db.execute("DELETE FROM queue WHERE vehicle_number=?", (reg,))
            self._log("QUEUE", f"{reg} left the waiting queue")
            self._touch()
            self._emit("queue_cancelled", reg=reg)

    # ================================================================= physical progress
    def confirm_entered(self, sid):
        with self.lock:
            s = self.sessions.get(sid)
            if not s or s.entered_time:
                return
            s.entered_time = fmt(self.now())
            self.counters["entered"] += 1
            self._save_session(s)
            self._log("ENTRY", f"{s.vehicle_number} entered the facility through Gate {s.gate}")
            self._touch()

    def confirm_parked(self, sid):
        with self.lock:
            s = self.sessions.get(sid)
            if not s or s.status != S_ASSIGNED:
                return
            slot = self.slots[s.slot_id]
            with self.db.tx():
                s.status, s.parked_time = S_PARKED, fmt(self.now())
                if not s.entered_time:
                    s.entered_time = s.parked_time
                    self.counters["entered"] += 1
                slot.status = OCCUPIED
                self._save_session(s)
                self._save_slot(slot)
                self._log("PARKED", f"{s.vehicle_number} parked in bay {s.slot_id} - bay now OCCUPIED")
            self._touch()

    # ================================================================= checkout & billing
    def estimate_bill(self, sid):
        with self.lock:
            s = self.sessions.get(sid)
            if not s:
                raise ValueError("Active session not found.")
            end = parse(s.checkout_time) if s.checkout_time else self.now()
            return billing.calculate(s.vehicle_type, parse(s.entry_time), end, self.time_scale)

    def request_checkout(self, sid, method="UPI"):
        with self.lock:
            s = self.sessions.get(sid)
            if not s:
                raise ValueError("Active ticket not found.")
            if s.status == S_ASSIGNED:
                raise ValueError(f"{s.vehicle_number} is still entering - wait until it is parked.")
            if s.status != S_PARKED:
                raise ValueError(f"Checkout for {s.vehicle_number} is already in progress.")
            s.status, s.payment_status, s.payment_method = S_CHECKOUT, "PROCESSING", method
            s.checkout_time = fmt(self.now())
            self._save_session(s)
            self._log("CHECKOUT", f"Checkout requested for {s.vehicle_number} (ticket {s.ticket_id}, {method})")
            self._touch()
            self._emit("checkout", sid=sid)
            return s

    def process_checkout(self, sid):
        """Billing-thread work: compute the bill, record the (simulated) payment."""
        with self.lock:
            s = self.sessions.get(sid)
            if not s or s.status != S_CHECKOUT:
                raise ValueError("Session is not awaiting payment.")
            b = billing.calculate(s.vehicle_type, parse(s.entry_time), parse(s.checkout_time), self.time_scale)
            now = fmt(self.now())
            with self.db.tx():
                self.db.insert("bills", {
                    "ticket_id": s.ticket_id, "session_id": sid, "vehicle_number": s.vehicle_number,
                    "vehicle_type": s.vehicle_type, "duration_s": b.duration_s,
                    "billed_minutes": b.billed_minutes, "billed_hours": b.billed_hours, "rate": b.rate,
                    "time_scale": b.time_scale, "base_amount": b.base_amount, "tax_amount": b.tax_amount,
                    "total_amount": b.total_amount, "payment_method": s.payment_method,
                    "payment_status": "PAID", "created_at": s.checkout_time, "paid_at": now})
                s.status, s.payment_status, s.amount = S_EXITING, "PAID", b.total_amount
                self._save_session(s)
                self.counters["revenue"] += b.total_amount
                self._log("PAYMENT", f"Payment completed: {s.vehicle_number} paid INR {b.total_amount:.2f} "
                                     f"via {s.payment_method} ({b.billed_hours} h billed)")
            self._touch()
            self._emit("exit_ready", sid=sid)
            return b

    def attach_receipt(self, sid_or_ticket, path):
        self.db.execute("UPDATE bills SET receipt_path=? WHERE ticket_id=?", (str(path), sid_or_ticket))

    def release_bay(self, sid):
        """The exiting vehicle has pulled out of its bay: free it and serve the queue."""
        with self.lock:
            s = self.sessions.get(sid)
            if not s or not s.holds_slot:
                return
            slot = self.slots[s.slot_id]
            with self.db.tx():
                slot.status, slot.vehicle_number, slot.session_id = AVAILABLE, "", None
                s.holds_slot, s.bay_released_time = False, fmt(self.now())
                self._save_slot(slot)
                self._save_session(s)
                self._log("RELEASE", f"Bay {s.slot_id} released - now AVAILABLE")
                self._process_queue_locked()
            self._touch()

    def confirm_departed(self, sid):
        with self.lock:
            s = self.sessions.get(sid)
            if not s or s.status != S_EXITING:
                return
            if s.holds_slot:               # safety: never leave a bay stuck
                self.release_bay(sid)
            with self.db.tx():
                s.status, s.exit_time = S_COMPLETED, fmt(self.now())
                self._save_session(s)
                self.counters["exited"] += 1
                self._log("EXIT", f"{s.vehicle_number} exited through the exit gate")
            del self.sessions[sid]
            self._touch()

    def due_checkouts(self):
        """Sessions whose planned stay (automatic traffic) is over."""
        now = fmt(self.now())
        with self.lock:
            return [s.session_id for s in self.sessions.values()
                    if s.status == S_PARKED and s.planned_exit_time and s.planned_exit_time <= now]

    def checkout_in_progress(self):
        with self.lock:
            return [s.session_id for s in self.sessions.values() if s.status == S_CHECKOUT]

    # ================================================================= reservations
    def reserve(self, slot_id, reg, vtype, permit=False, minutes=None):
        reg = normalize_reg(reg)
        if vtype not in VEHICLE_TYPES:
            raise ValueError("Select a valid vehicle category.")
        with self.lock:
            slot = self.slots.get(slot_id)
            if slot is None:
                raise ValueError("Select a parking bay.")
            if slot.status != AVAILABLE:
                raise ValueError(f"Bay {slot_id} is {slot.status.lower()} and cannot be reserved.")
            if not self.engine.is_eligible(vtype, permit, slot.category):
                raise ValueError(f"Bay {slot_id} ({slot.category}) is not suitable for a {vtype}"
                                 + (" without an accessible permit." if slot.category == "ACCESSIBLE" else "."))
            if reg in self._known_regs():
                raise ValueError(f"{reg} is already parked, waiting or arriving.")
            if any(r["vehicle_number"] == reg for r in self.reservations.values()):
                raise ValueError(f"{reg} already has an active reservation.")
            now = self.now()
            exp = fmt(now + timedelta(minutes=minutes)) if minutes else None
            with self.db.tx():
                rid = self.db.insert("reservations", {"slot_id": slot_id, "vehicle_number": reg,
                                                       "vehicle_type": vtype, "permit": int(permit),
                                                       "created_at": fmt(now), "expires_at": exp,
                                                       "status": "ACTIVE"})
                self.reservations[slot_id] = {"id": rid, "slot_id": slot_id, "vehicle_number": reg,
                                              "vehicle_type": vtype, "permit": int(permit),
                                              "created_at": fmt(now), "expires_at": exp, "status": "ACTIVE"}
                slot.status, slot.reserved_for, slot.reserved_until = RESERVED, reg, exp or ""
                self._save_slot(slot)
                self._log("RESERVE", f"Bay {slot_id} reserved for {reg} ({vtype})"
                                     + (f" until {exp}" if exp else ""))
            self._touch()

    def cancel_reservation(self, slot_id, reason="released"):
        with self.lock:
            r = self.reservations.pop(slot_id, None)
            slot = self.slots.get(slot_id)
            if not r or slot is None:
                raise ValueError(f"Bay {slot_id} has no active reservation.")
            with self.db.tx():
                self.db.update("reservations", {"status": "EXPIRED" if reason == "expired" else "CANCELLED"},
                               "id=?", (r["id"],))
                slot.status, slot.reserved_for, slot.reserved_until = AVAILABLE, "", ""
                self._save_slot(slot)
                self._log("RESERVE", f"Reservation on bay {slot_id} for {r['vehicle_number']} {reason}")
                self._process_queue_locked()
            self._touch()

    def expire_reservations(self):
        now = fmt(self.now())
        with self.lock:
            due = [sid for sid, r in self.reservations.items() if r["expires_at"] and r["expires_at"] <= now]
            for sid in due:
                self.cancel_reservation(sid, "expired")
            return due

    def release_slot(self, slot_id):
        """Operator 'Release bay' action. Returns a short description of what happened."""
        with self.lock:
            slot = self.slots.get(slot_id)
            if slot is None:
                raise ValueError("Select a parking bay.")
            if slot.status == RESERVED:
                self.cancel_reservation(slot_id)
                return "reservation cancelled"
            if slot.status == OCCUPIED:
                self.request_checkout(slot.session_id, "CASH")
                return "checkout started"
            if slot.status == INCOMING:
                raise ValueError("A vehicle is driving to this bay - it cannot be released yet.")
            raise ValueError(f"Bay {slot_id} is already available.")

    # ================================================================= reporting
    def set_time_scale(self, value):
        with self.lock:
            self.time_scale = float(value)
            self.db.set_setting("time_scale", value)
            self._log("SYSTEM", f"Demo billing time-scale set to x{value:g}")
            self._touch()

    def snapshot(self):
        """A consistent, lock-free-to-use copy of everything the GUI needs."""
        with self.lock:
            now = self.now()
            slots = {sid: s.to_dict() for sid, s in self.slots.items()}
            by = {st: 0 for st in (AVAILABLE, OCCUPIED, RESERVED, INCOMING)}
            floors = {f: {"occupied": 0, "incoming": 0, "reserved": 0, "available": 0, "total": 0} for f in FLOORS}
            for s in self.slots.values():
                by[s.status] += 1
                key = {"OCCUPIED": "occupied", "INCOMING": "incoming", "RESERVED": "reserved",
                       "AVAILABLE": "available"}[s.status]
                floors[s.floor][key] += 1
                floors[s.floor]["total"] += 1
            total = len(self.slots)
            occ = by[OCCUPIED] + by[INCOMING]
            mix = {v: 0 for v in RATES}
            active = []
            for s in self.sessions.values():
                mix[s.vehicle_type] += 1
                d = s.to_dict()
                d["duration_s"] = max(0, int((now - parse(s.entry_time)).total_seconds()))
                active.append(d)
            snap = {
                "version": self.version, "slots": slots, "total": total, "occupied": occ,
                "parked": by[OCCUPIED], "incoming": by[INCOMING], "reserved": by[RESERVED],
                "available": by[AVAILABLE], "percent": round(occ / total * 100, 1) if total else 0.0,
                "floors": floors, "mix": mix, "active": active,
                "queue": [dict(q) for q in self._ordered_queue()], "pending": len(self.pending),
                "entries": self.counters["entered"], "exits": self.counters["exited"],
                "revenue": self.counters["revenue"], "active_sessions": len(self.sessions),
                "events": list(self.events)[:60], "time_scale": self.time_scale,
                "reservations": [dict(r) for r in self.reservations.values()],
            }
            return snap

    def slot_detail(self, slot_id):
        with self.lock:
            s = self.slots.get(slot_id)
            if s is None:
                raise KeyError(slot_id)
            d = s.to_dict()
            d.update({"ticket_id": "", "vehicle_type": "", "entry_time": "", "duration_s": None,
                      "payment_status": "", "session_status": ""})
            sess = self.sessions.get(s.session_id) if s.session_id else None
            if sess:
                d.update({"ticket_id": sess.ticket_id, "vehicle_type": sess.vehicle_type,
                          "entry_time": sess.entry_time, "payment_status": sess.payment_status,
                          "session_status": sess.status,
                          "duration_s": int((self.now() - parse(sess.entry_time)).total_seconds())})
            elif s.status == RESERVED:
                r = self.reservations.get(slot_id, {})
                d["vehicle_type"] = r.get("vehicle_type", "")
                d["entry_time"] = r.get("created_at", "")
            return d

    def list_sessions(self, status="ALL", search="", limit=500):
        """Sessions (with bill info) straight from the database."""
        sql = ("SELECT s.*, b.total_amount AS bill_total, b.billed_hours, b.duration_s AS bill_duration "
               "FROM sessions s LEFT JOIN bills b ON b.ticket_id=s.ticket_id WHERE 1=1")
        p = []
        if status == "ACTIVE":
            sql += " AND s.status IN ('ASSIGNED','PARKED','CHECKOUT','EXITING')"
        elif status == "COMPLETED":
            sql += " AND s.status='COMPLETED'"
        if search:
            sql += " AND (s.vehicle_number LIKE ? OR s.ticket_id LIKE ? OR s.slot_id LIKE ?)"
            p += [f"%{search.upper()}%"] * 3
        sql += " ORDER BY s.session_id DESC LIMIT ?"
        p.append(limit)
        rows = self.db.query(sql, p)
        now = self.now()
        for r in rows:
            end = parse(r["exit_time"]) or parse(r["checkout_time"]) or now
            r["duration_s"] = max(0, int((end - parse(r["entry_time"])).total_seconds())) if r["entry_time"] else 0
        return rows

    def recent_events(self, limit=300, category=None, search=""):
        sql, p = "SELECT * FROM events WHERE 1=1", []
        if category and category != "ALL":
            sql += " AND category=?"
            p.append(category)
        if search:
            sql += " AND message LIKE ?"
            p.append(f"%{search}%")
        sql += " ORDER BY id DESC LIMIT ?"
        p.append(limit)
        return self.db.query(sql, p)

    def record_sample(self):
        with self.lock:
            snap = self.snapshot()
        f = snap["floors"]
        self.db.insert("occupancy_samples", {
            "ts": fmt(self.now()), "occupied": snap["occupied"], "incoming": snap["incoming"],
            "reserved": snap["reserved"], "total": snap["total"],
            "floor_g": f["G"]["occupied"] + f["G"]["incoming"],
            "floor_1": f["1"]["occupied"] + f["1"]["incoming"],
            "floor_2": f["2"]["occupied"] + f["2"]["incoming"], "queue_len": len(snap["queue"])})
        return snap

    def check_capacity_state(self):
        """Log a single FULL / capacity-restored event on state changes. Returns is_full."""
        with self.lock:
            free = sum(s.status == AVAILABLE for s in self.slots.values())
            full = free == 0
            if full and not self.full_flag:
                self._log("FULL", "Parking facility is FULL - new vehicles will wait in the queue")
                self._touch()
            elif not full and self.full_flag:
                self._log("SYSTEM", "Parking capacity available again")
                self._touch()
            self.full_flag = full
            return full

    def verify_integrity(self):
        """Cross-check slots against sessions. Returns a list of problems (empty = healthy)."""
        problems = []
        with self.lock:
            held = {}
            for s in self.sessions.values():
                if s.holds_slot:
                    if s.slot_id in held:
                        problems.append(f"bay {s.slot_id} held by two sessions")
                    held[s.slot_id] = s
            for sid, slot in self.slots.items():
                if slot.status in (OCCUPIED, INCOMING) and sid not in held:
                    problems.append(f"bay {sid} marked {slot.status} but has no session")
                if slot.status == AVAILABLE and sid in held:
                    problems.append(f"bay {sid} AVAILABLE but held by {held[sid].vehicle_number}")
        return problems

    # ================================================================= export / reset
    def export_csv(self, path):
        rows = self.db.query(
            "SELECT s.ticket_id, s.vehicle_number, s.vehicle_type, s.slot_id, s.entry_time, s.exit_time,"
            " s.status, s.payment_status, s.payment_method, b.duration_s, b.billed_hours, b.base_amount,"
            " b.tax_amount, b.total_amount FROM sessions s LEFT JOIN bills b ON b.ticket_id=s.ticket_id"
            " ORDER BY s.session_id")
        return self._write_csv(path, rows)

    def export_events_csv(self, path, category=None, search=""):
        rows = self.recent_events(100000, category, search)[::-1]
        return self._write_csv(path, rows)

    @staticmethod
    def _write_csv(path, rows):
        with open(path, "w", newline="", encoding="utf-8") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            else:
                f.write("no data\n")
        return path

    def reset_all(self):
        """Wipe all operational data (used by the 'Reset demo data' action)."""
        with self.lock, self.db.tx():
            for t in ("sessions", "tickets", "bills", "reservations", "queue", "events",
                      "occupancy_samples", "vehicles"):
                self.db.execute(f"DELETE FROM {t}")
            self.sessions.clear(); self.queue.clear(); self.pending.clear(); self.reservations.clear()
            self.events.clear()
            self.counters.update(entered=0, exited=0, revenue=0.0)
            for s in self.slots.values():
                s.status, s.vehicle_number, s.session_id, s.reserved_for, s.reserved_until = AVAILABLE, "", None, "", ""
                self._save_slot(s)
            self.full_flag = False
            self._log("SYSTEM", "All parking data was reset")
            self._touch()
            self._emit("reset")
