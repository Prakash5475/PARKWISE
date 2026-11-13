"""Thread lifecycle management for PARKWISE.

Six worker threads (all ``threading.Thread`` subclasses of ManagedThread):

  1  EntryGate-A        detects vehicles at Gate A, asks the allocator for a bay, opens the barrier
  2  EntryGate-B        same for Gate B
  3  ExitGate           opens the exit barrier, dispatches paid vehicles, schedules automatic checkouts
  4  OccupancyMonitor   samples occupancy, expires reservations, serves the waiting queue, checks integrity
  5  VehicleMovement    steps the vehicle simulation (~60 Hz)
  6  Billing            computes bills, records the simulated payment, writes PDF receipts

Shutdown / lifecycle
--------------------
* ``shutdown_event`` (global) + a per-thread ``stop_event`` are ``threading.Event`` objects.
  Every loop waits on them (``wait()``/``queue.get(timeout)``), so threads exit within a tick
  instead of sleeping through a long ``time.sleep``.
* A Python thread cannot be restarted, so ``start()`` creates a fresh Thread object.
* Tkinter is never touched here.  The GUI polls ``stats()`` from the main thread via ``after()``.
* Cross-thread messages travel through ``queue.Queue`` objects (thread-safe).
"""
import queue
import random
import threading
import time

from config import TRAFFIC_PROFILES, WAITING_CAPACITY
from core import documents
from simulation.traffic import random_spec


class TrafficControl:
    """Shared, tiny, lock-protected settings for automatic traffic."""
    def __init__(self, auto=True, profile="Normal"):
        self._lock = threading.Lock()
        self._auto, self._profile = auto, profile

    @property
    def auto(self):
        with self._lock:
            return self._auto

    @auto.setter
    def auto(self, v):
        with self._lock:
            self._auto = bool(v)

    @property
    def profile(self):
        with self._lock:
            return self._profile

    @profile.setter
    def profile(self, v):
        with self._lock:
            self._profile = v if v in TRAFFIC_PROFILES else "Normal"


class ManagedThread:
    role = ""
    tick_timeout = 0.2

    def __init__(self, name, shutdown_event):
        self.name = name
        self.shutdown = shutdown_event
        self._stop = threading.Event()
        self._thread = None
        self.state = "STOPPED"
        self.iterations = self.processed = self.errors = 0
        self.last_error = ""
        self.heartbeat = 0.0
        self.started_at = 0.0
        self.detail = ""

    # ---- lifecycle ----------------------------------------------------------
    def start(self):
        if self.alive:
            return False
        self._stop = threading.Event()               # a stopped thread cannot be restarted
        self._thread = threading.Thread(target=self._main, name=self.name, daemon=True)
        self.state, self.started_at = "STARTING", time.time()
        self._thread.start()
        return True

    def stop(self, timeout=2.5):
        self._stop.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout)
        if not (t and t.is_alive()):
            self.state = "STOPPED"
        return not self.alive

    @property
    def alive(self):
        return bool(self._thread and self._thread.is_alive())

    def should_stop(self):
        return self._stop.is_set() or self.shutdown.is_set()

    def wait(self, seconds):
        """Interruptible sleep. Returns True when the thread has been asked to stop."""
        self._stop.wait(seconds) if not self.shutdown.is_set() else None
        return self.should_stop()

    # ---- main loop --------------------------------------------------------------
    def _main(self):
        self.state = "RUNNING"
        try:
            self.setup()
            while not self.should_stop():
                self.heartbeat = time.time()
                try:
                    self.tick()
                except Exception as e:               # keep the worker alive, but report it
                    self.errors += 1
                    self.last_error = f"{type(e).__name__}: {e}"
                    self.on_error(e)
                    self.wait(0.2)
                self.iterations += 1
        finally:
            self.state = "STOPPED"

    def setup(self): ...
    def tick(self): raise NotImplementedError
    def on_error(self, exc): ...

    def stats(self):
        hb = time.time() - self.heartbeat if self.heartbeat else None
        return {"name": self.name, "role": self.role, "state": self.state if self.alive else "STOPPED",
                "alive": self.alive, "ident": self._thread.ident if self._thread else None,
                "iterations": self.iterations, "processed": self.processed, "errors": self.errors,
                "last_error": self.last_error, "heartbeat_age": hb, "detail": self.detail,
                "uptime": (time.time() - self.started_at) if self.alive else 0.0}


class EntryGateThread(ManagedThread):
    def __init__(self, gate, manager, sim, traffic, shutdown):
        super().__init__(f"EntryGate-{gate}", shutdown)
        self.role = f"Entry gate {gate}: vehicle detection, bay allocation, barrier control"
        self.gate, self.manager, self.sim, self.traffic = gate, manager, sim, traffic
        self.inbox = queue.Queue()
        self.next_arrival = time.time() + random.uniform(1.0, 3.0 if gate == "A" else 5.0)

    def tick(self):
        try:
            kind, payload = self.inbox.get(timeout=0.15)
        except queue.Empty:
            kind = None
        if kind == "at_ticket":
            self._handle_arrival(payload)
        elif kind == "queue_assigned":
            self._handle_promotion(payload)
        self.detail = f"inbox={self.inbox.qsize()}"
        self._maybe_generate()

    def _handle_arrival(self, reg):
        m = self.manager
        spec = m.pending.get(reg)
        vt = spec.vtype if spec else "?"
        m.log("DETECT", f"Vehicle detected at Gate {self.gate}: {reg} ({vt})")
        try:
            res = m.request_entry(reg, self.gate)
        except KeyError:                               # vehicle cancelled meanwhile
            self.sim.remove(reg)
            return
        if res.status == "ASSIGNED":
            self.sim.assign(reg, res.session.session_id, res.session.slot_id)
            self.sim.set_barrier(self.gate, True)
            m.log("GATE", f"Gate {self.gate} barrier opened for {reg} -> bay {res.session.slot_id}")
        else:
            self.sim.send_to_waiting(reg)
        self.processed += 1

    def _handle_promotion(self, session):
        if self.sim.promote(session.vehicle_number, session.session_id, session.slot_id):
            self.sim.set_barrier(self.gate, True)
            self.manager.log("GATE", f"Gate {self.gate} barrier opened for queued vehicle "
                                     f"{session.vehicle_number} -> bay {session.slot_id}")
            self.processed += 1

    def _maybe_generate(self):
        if not self.traffic.auto or time.time() < self.next_arrival:
            return
        (lo, hi), stay = TRAFFIC_PROFILES[self.traffic.profile]
        self.next_arrival = time.time() + random.uniform(lo, hi)
        m = self.manager
        if m.waiting_count() + m.pending_count() >= WAITING_CAPACITY or self.sim.snapshot()["spawn_backlog"] > 1:
            return                                     # entry road congested: skip this arrival
        spec = random_spec(m._known_regs(), self.gate, stay_range=stay)
        try:
            m.register_arrival(spec)
        except ValueError:
            return
        self.sim.spawn_arrival(spec)


class ExitGateThread(ManagedThread):
    role = "Exit gate: barrier control, exit dispatch, automatic checkout scheduling"

    def __init__(self, manager, sim, billing_queue, shutdown):
        super().__init__("ExitGate", shutdown)
        self.manager, self.sim, self.billing_queue = manager, sim, billing_queue
        self.inbox = queue.Queue()
        self._last_scan = 0.0

    def tick(self):
        try:
            kind, payload = self.inbox.get(timeout=0.15)
        except queue.Empty:
            kind = None
        if kind == "exit_ready":
            if not self.sim.dispatch_exit(payload):               # vehicle not in the simulation
                self.manager.release_bay(payload)
                self.manager.confirm_departed(payload)
            self.processed += 1
        elif kind == "exit_near":
            self.sim.set_barrier("X", True)
            self.manager.log("GATE", "Exit gate barrier opened")
        now = time.time()
        if now - self._last_scan > 0.5:                            # automatic checkouts
            self._last_scan = now
            for sid in self.manager.due_checkouts():
                try:
                    self.manager.request_checkout(sid, random.choice(["UPI", "CARD", "CASH"]))
                except ValueError:
                    pass
        self.detail = f"inbox={self.inbox.qsize()}"


class BillingThread(ManagedThread):
    role = "Billing & tickets: bill calculation, simulated payment, PDF receipts"

    def __init__(self, manager, billing_queue, shutdown, make_receipts=True):
        super().__init__("Billing", shutdown)
        self.manager, self.inbox, self.make_receipts = manager, billing_queue, make_receipts

    def tick(self):
        try:
            sid = self.inbox.get(timeout=0.2)
        except queue.Empty:
            self.detail = "idle"
            return
        self.detail = f"processing session {sid}"
        if self.wait(0.6):                       # simulated card/UPI processing time
            self.inbox.put(sid)                  # shutting down: leave it for the next run
            return
        m = self.manager
        bill = m.process_checkout(sid)
        self.processed += 1
        if self.make_receipts:
            try:
                row = m.db.query("SELECT * FROM bills WHERE session_id=?", (sid,))[0]
                srow = m.db.query("SELECT * FROM sessions WHERE session_id=?", (sid,))[0]
                path = documents.receipt_pdf(srow, row)
                m.attach_receipt(srow["ticket_id"], path)
            except Exception as e:
                m.log("ERROR", f"Receipt PDF failed: {e}")


class OccupancyMonitorThread(ManagedThread):
    role = "Occupancy monitor: sampling, reservation expiry, queue service, integrity checks"

    def __init__(self, manager, shutdown, sample_every=5.0):
        super().__init__("OccupancyMonitor", shutdown)
        self.manager, self.sample_every = manager, sample_every
        self._last_sample = 0.0
        self.health = "OK"

    def tick(self):
        m = self.manager
        m.expire_reservations()
        m.process_queue()                         # safety net for bays freed by manual actions
        m.check_capacity_state()
        problems = m.verify_integrity()
        if problems:
            self.health = "; ".join(problems[:2])
            m.log("ERROR", f"Integrity check failed: {self.health}")
        else:
            self.health = "OK"
        if time.time() - self._last_sample >= self.sample_every:
            self._last_sample = time.time()
            snap = m.record_sample()
            self.detail = f"{snap['occupied']}/{snap['total']} occupied"
        self.processed += 1
        self.wait(1.0)


class VehicleMovementThread(ManagedThread):
    role = "Vehicle movement: steps the 2D simulation and reports parked / departed events"

    def __init__(self, sim, shutdown):
        super().__init__("VehicleMovement", shutdown)
        self.sim, self.fps = sim, 0.0
        self._last = None

    def setup(self):
        self._last = time.perf_counter()

    def tick(self):
        now = time.perf_counter()
        dt = now - self._last
        self._last = now
        self.sim.step(dt)
        self.processed += 1
        if dt > 0:
            self.fps = 0.9 * self.fps + 0.1 / dt
        self.detail = f"{self.fps:.0f} steps/s"
        self.wait(0.012)


class ThreadManager:
    """Creates, wires, starts, monitors and shuts down the six workers."""

    def __init__(self, manager, sim, traffic=None, make_receipts=True):
        self.manager, self.sim = manager, sim
        self.traffic = traffic or TrafficControl()
        self.shutdown_event = threading.Event()
        self.billing_queue = queue.Queue()
        sd = self.shutdown_event
        self.gate_a = EntryGateThread("A", manager, sim, self.traffic, sd)
        self.gate_b = EntryGateThread("B", manager, sim, self.traffic, sd)
        self.exit_gate = ExitGateThread(manager, sim, self.billing_queue, sd)
        self.monitor = OccupancyMonitorThread(manager, sd)
        self.movement = VehicleMovementThread(sim, sd)
        self.billing = BillingThread(manager, self.billing_queue, sd, make_receipts)
        self.threads = [self.gate_a, self.gate_b, self.exit_gate, self.monitor, self.movement, self.billing]
        # simulation -> backend / workers
        sim.on_event = self._on_sim_event
        # backend -> workers
        manager.subscribe(self._on_manager_event)

    # ---- message routing ---------------------------------------------------------
    def _on_sim_event(self, kind, *a):
        m = self.manager
        if kind == "at_ticket":
            reg, gate = a
            (self.gate_a if gate == "A" else self.gate_b).inbox.put(("at_ticket", reg))
        elif kind == "entered":
            m.confirm_entered(a[0])
        elif kind == "parked":
            m.confirm_parked(a[0])
        elif kind == "bay_cleared":
            m.release_bay(a[0])
        elif kind == "departed":
            m.confirm_departed(a[0])
        elif kind == "exit_near":
            self.exit_gate.inbox.put(("exit_near", a[0]))

    def _on_manager_event(self, kind, data):
        if kind == "checkout":
            self.billing_queue.put(data["sid"])
        elif kind == "exit_ready":
            self.exit_gate.inbox.put(("exit_ready", data["sid"]))
        elif kind == "queue_assigned":
            self.gate_a.inbox.put(("queue_assigned", data["session"]))
        elif kind == "queue_cancelled":
            self.sim.remove(data["reg"])

    # ---- lifecycle ------------------------------------------------------------------
    def start_all(self):
        # recover work that was in flight when the app was closed
        for sid in self.manager.checkout_in_progress():
            self.billing_queue.put(sid)
        for t in self.threads:
            t.start()
        self.manager.log("SYSTEM", "All 6 worker threads started")

    def stop_all(self, timeout=3.0):
        for t in self.threads:
            t._stop.set()
        for t in self.threads:
            t.stop(timeout)
        return [t.name for t in self.threads if t.alive]

    def shutdown(self, timeout=3.0):
        """Graceful application shutdown: signal everything, join, return survivors."""
        self.shutdown_event.set()
        return self.stop_all(timeout)

    def by_name(self, name):
        return next(t for t in self.threads if t.name == name)

    def stats(self):
        return [t.stats() for t in self.threads]

    def queue_sizes(self):
        return {"Gate A inbox": self.gate_a.inbox.qsize(), "Gate B inbox": self.gate_b.inbox.qsize(),
                "Exit inbox": self.exit_gate.inbox.qsize(), "Billing queue": self.billing_queue.qsize()}
