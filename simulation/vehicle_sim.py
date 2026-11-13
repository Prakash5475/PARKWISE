"""Vehicle movement simulation (headless - no Tkinter).

The simulation owns the *kinematics* of every vehicle.  It is stepped by the
"Vehicle Movement" thread (thread 5) at ~60 Hz, and the GUI only ever reads
copies of the vehicle positions (``snapshot``) from the Tk main thread.

Vehicle movement is *driven by* the parking backend, never decorative:

  spawn_arrival  -> vehicle drives to the ticket point and fires  ``at_ticket``
  (gate thread asks ParkingManager for a bay)
  assign         -> vehicle follows its route to the allocated bay
                    fires ``entered`` at the gate line and ``parked`` at the bay
  dispatch_exit  -> (after payment) vehicle reverses out, fires ``bay_cleared``,
                    drives to the exit gate and fires ``departed``

Callbacks are collected during a step and fired AFTER the simulation lock is released,
so a callback can freely call into the ParkingManager without lock-order problems.
"""
import math
import threading

from config import WAITING_CAPACITY
from simulation import layout as L
from simulation.vehicle_art import SIZE

CRUISE = {"CAR": 150.0, "EV": 150.0, "VIP": 158.0, "BIKE": 178.0}
ACCEL, DECEL = 330.0, 760.0
BARRIER_OPEN_DEG = 40.0


class SimVehicle:
    def __init__(self, vid, reg, vtype, color, permit, gate):
        self.vid, self.reg, self.vtype, self.color = vid, reg, vtype, color
        self.permit, self.gate = permit, gate
        self.length, self.width = SIZE[vtype]
        self.state = "APPROACH"        # APPROACH AT_TICKET ENTERING TO_WAIT WAITING PARKED EXITING GONE
        self.floor = "G"
        self.x, self.y, self.heading = float(L.SPAWN_X), float(L.LANE_Y[gate]), 0.0
        self.speed = 0.0
        self.legs, self.leg_i, self.s = [L.approach_leg(gate)], 0, 0.0
        self.session_id = None
        self.slot_id = None
        self.cell = None
        self.ramp = None               # [t, duration, to_floor, switched]
        self.scale = 1.0
        self.dir = (1.0, 0.0)
        self.blocked_for = 0.0
        self.ignore_until = 0.0
        self.vanish = None


class VehicleSimulation:
    def __init__(self, on_event=None):
        self.lock = threading.RLock()
        self.on_event = on_event or (lambda *a, **k: None)
        self.vehicles = {}                  # reg -> SimVehicle
        self.spawn_queue = []               # (vid, spec) waiting for a clear spawn point
        self.barriers = {n: {"target": 0, "angle": 90.0, "idle": 0.0} for n in ("A", "B", "X")}
        self.next_vid = 1
        self.t = 0.0
        self.version = 0                    # bumps when a vehicle parks / leaves a bay
        self.steps = 0
        self.last_floor = "G"

    # ================================================================ commands
    def spawn_arrival(self, spec):
        with self.lock:
            self.spawn_queue.append((self.next_vid, spec))
            self.next_vid += 1

    def _make(self, vid, spec):
        return SimVehicle(vid, spec.reg, spec.vtype, spec.color, spec.permit, spec.gate)

    def assign(self, reg, session_id, slot_id):
        with self.lock:
            v = self.vehicles.get(reg)
            if v is None:
                return False
            v.session_id, v.slot_id = session_id, slot_id
            v.legs, v.leg_i, v.s, v.state = L.entry_legs(v.gate, slot_id), 0, 0.0, "ENTERING"
            self.last_floor = slot_id.split("-")[0]
            return True

    def send_to_waiting(self, reg):
        with self.lock:
            v = self.vehicles.get(reg)
            if v is None:
                return False
            used = {o.cell for o in self.vehicles.values() if o.cell is not None}
            cell = next((i for i in range(WAITING_CAPACITY) if i not in used), WAITING_CAPACITY - 1)
            v.cell, v.legs, v.leg_i, v.s, v.state = cell, L.wait_legs(v.gate, cell), 0, 0.0, "TO_WAIT"
            return True

    def promote(self, reg, session_id, slot_id):
        with self.lock:
            v = self.vehicles.get(reg)
            if v is None or v.cell is None:
                return False
            v.session_id, v.slot_id, v.gate = session_id, slot_id, "A"
            v.legs, v.leg_i, v.s, v.state = L.release_legs(v.cell, slot_id), 0, 0.0, "ENTERING"
            v.cell = None
            self.version += 1
            self.last_floor = slot_id.split("-")[0]
            return True

    def dispatch_exit(self, session_id):
        """Send a parked vehicle to the exit.  Returns False if it is not in the simulation."""
        with self.lock:
            v = next((x for x in self.vehicles.values() if x.session_id == session_id), None)
            if v is None or v.state != "PARKED":
                return False
            v.legs, v.leg_i, v.s, v.state = L.exit_legs(v.slot_id), 0, 0.0, "EXITING"
            self.last_floor = v.floor
            return True

    def remove(self, reg):
        with self.lock:
            v = self.vehicles.get(reg)
            if v:
                v.vanish = 0.6
                v.cell = None
                v.state = "WAITING"

    def set_barrier(self, name, is_open):
        with self.lock:
            self.barriers[name]["target"] = 1 if is_open else 0
            self.barriers[name]["idle"] = 0.0

    def clear(self):
        with self.lock:
            self.vehicles.clear()
            self.spawn_queue.clear()
            self.version += 1

    def has_vehicle(self, reg):
        with self.lock:
            return reg in self.vehicles

    def restore(self, sessions, queue):
        """Rebuild vehicles after an application restart from persisted backend state."""
        with self.lock:
            for s in sessions:
                spec = _Spec(s["vehicle_number"], s["vehicle_type"], s["color"] or "#3B7DDD",
                             bool(s["permit"]), s["gate"])
                v = self._make(self.next_vid, spec)
                self.next_vid += 1
                v.session_id, v.slot_id = s["session_id"], s["slot_id"]
                floor, num = s["slot_id"].split("-")[0], int(s["slot_id"].split("-")[1])
                if s["status"] == "ASSIGNED":
                    y = L.LANE_Y[v.gate]
                    v.x, v.y, v.heading, v.state = float(L.TICKET_X), float(y), 0.0, "ENTERING"
                    v.legs, v.leg_i, v.s = L.entry_legs(v.gate, s["slot_id"]), 0, 0.0
                    self.barriers[v.gate]["target"] = 1
                elif s["status"] in ("PARKED", "CHECKOUT") or (s["status"] == "EXITING" and s["holds_slot"]):
                    v.floor = floor
                    v.x, v.y = L.bay_center(num)
                    v.heading, v.state, v.legs, v.leg_i = L.park_heading(num), "PARKED", [], 0
                    if s["status"] == "EXITING":
                        self.vehicles[v.reg] = v
                        self.dispatch_exit(v.session_id)
                        continue
                else:                                  # EXITING, bay already released
                    v.floor = floor
                    v.legs, v.leg_i, v.s, v.state = L.restore_exit_legs(s["slot_id"], True), 0, 0.0, "EXITING"
                    v.floor = v.legs[0].floor
                    v.x, v.y, v.heading = v.legs[0].path.at(0)
                self.vehicles[v.reg] = v
            for i, q in enumerate(queue[:WAITING_CAPACITY]):
                spec = _Spec(q["reg"], q["vtype"], q["color"] or "#3B7DDD", q["permit"], q["gate"])
                v = self._make(self.next_vid, spec)
                self.next_vid += 1
                v.cell, v.state, v.heading = i, "WAITING", -90.0
                v.x, v.y = L.WAIT_CELLS[i]
                v.legs = []
                self.vehicles[v.reg] = v
            self.version += 1

    # ================================================================ stepping
    def step(self, dt):
        dt = min(max(dt, 0.0), 0.08)
        events = []
        with self.lock:
            self.t += dt
            self.steps += 1
            self._try_spawn()
            self._update_barriers(dt)
            vs = list(self.vehicles.values())
            for v in vs:
                self._move(v, dt, vs, events)
            for v in vs:
                if v.state == "GONE":
                    self.vehicles.pop(v.reg, None)
                    self.version += 1
        for ev in events:                    # outside the lock
            try:
                self.on_event(*ev)
            except Exception:
                pass

    def _try_spawn(self):
        keep = []
        for vid, spec in self.spawn_queue:
            y = L.LANE_Y[spec.gate]
            clear = all(not (o.floor == "G" and abs(o.y - y) < 22 and abs(o.x - L.SPAWN_X) < 100)
                        for o in self.vehicles.values())
            if clear and spec.reg not in self.vehicles:
                self.vehicles[spec.reg] = self._make(vid, spec)
            elif spec.reg in self.vehicles:
                pass
            else:
                keep.append((vid, spec))
        self.spawn_queue = keep

    def _update_barriers(self, dt):
        for name, b in self.barriers.items():
            if b["target"] and not self._near_barrier(name):
                b["idle"] += dt
                if b["idle"] > 1.2:                      # auto-close after the vehicle has passed
                    b["target"] = 0
            elif b["target"]:
                b["idle"] = 0.0
            goal = 0.0 if b["target"] else 90.0
            step = 210.0 * dt
            b["angle"] += max(-step, min(step, goal - b["angle"]))

    def _near_barrier(self, name):
        """True while any vehicle is at the gate OR still on its way to pass it.
        (A barrier must not auto-close on a vehicle that is still reversing out of the waiting
        area or driving towards the exit - that would leave it stuck behind a closed gate.)"""
        y = L.LANE_Y[name]
        for o in self.vehicles.values():
            if o.floor == "G" and abs(o.y - y) < 26 and abs(o.x - L.GATE_X) < 75:
                return True
            if o.ramp is None and o.state in ("ENTERING", "EXITING") and \
                    any(lg.barrier == name for lg in o.legs[o.leg_i:]):
                if (name != "X" and o.x < L.GATE_X + 60) or (name == "X" and o.x > L.GATE_X - 60):
                    return True
        return False

    # ---- per vehicle ----------------------------------------------------------------
    def _move(self, v, dt, vs, events):
        if v.vanish is not None:
            v.vanish -= dt
            v.scale = max(0.05, v.vanish / 0.6)
            if v.vanish <= 0:
                v.state = "GONE"
            return
        if v.state in ("AT_TICKET", "WAITING", "PARKED", "GONE"):
            v.speed = 0.0
            return
        if v.ramp is not None:
            self._ramp(v, dt, vs)
            return
        leg = v.legs[v.leg_i]
        remaining = leg.path.length - v.s
        tgt = self._target_speed(v, leg, remaining)
        limit = float("inf")

        # barrier gate (entry: stop before the gate line, exit: before the gate line)
        if leg.barrier and v.floor == "G":
            b = self.barriers[leg.barrier]
            if leg.barrier in ("A", "B") and v.x + v.length / 2 < L.GATE_X and b["angle"] > BARRIER_OPEN_DEG:
                limit = max(0.0, L.GATE_X - 8 - (v.x + v.length / 2))
            if leg.barrier == "X" and v.x - v.length / 2 > L.GATE_X and b["angle"] > BARRIER_OPEN_DEG:
                limit = max(0.0, (v.x - v.length / 2) - (L.GATE_X + 8))
            if leg.kind == "exit_run" and "near" not in leg.fired and v.x < L.GATE_X + 260 \
                    and v.session_id is not None:
                leg.fired.add("near")
                events.append(("exit_near", v.session_id))
        if limit < 14:
            tgt = min(tgt, 0.0 if limit < 2 else limit * 2.2)

        # collision avoidance
        if self.t >= v.ignore_until:
            gap = self._gap_ahead(v, vs)
            if gap is not None:
                if gap < 10:
                    tgt = 0.0
                elif gap < 10 + v.speed * 0.6 + 14:
                    tgt = min(tgt, max(0.0, (gap - 10) * 1.6))
        if tgt <= 1.0 and v.speed < 3.0:
            v.blocked_for += dt
            if v.blocked_for > 7.0:                      # deadlock breaker
                v.ignore_until, v.blocked_for = self.t + 1.8, 0.0
        else:
            v.blocked_for = 0.0

        if v.speed < tgt:
            v.speed = min(tgt, v.speed + ACCEL * dt)
        else:
            v.speed = max(tgt, v.speed - DECEL * dt)
        step = min(v.speed * dt, limit, max(0.0, remaining))
        v.s += step
        x, y, ang = leg.path.at(v.s)
        v.x, v.y = x, y
        v.dir = (math.cos(math.radians(ang)), math.sin(math.radians(ang)))
        desired = ang + (180.0 if leg.reverse else 0.0)
        diff = (desired - v.heading + 180.0) % 360.0 - 180.0
        v.heading += diff * (1.0 - math.exp(-10.0 * dt))

        # physical events
        if leg.kind in ("to_bay", "ramp_up") and leg.barrier in ("A", "B") and "entered" not in leg.fired \
                and v.x >= L.GATE_X and v.session_id is not None:
            leg.fired.add("entered")
            events.append(("entered", v.session_id))
        if leg.kind == "exit_run" and "dep" not in leg.fired and v.x <= L.GATE_X - 4 and v.session_id is not None:
            leg.fired.add("dep")
            events.append(("departed", v.session_id))

        if v.s >= leg.path.length - 1e-6:
            self._finish_leg(v, leg, events)

    def _target_speed(self, v, leg, remaining):
        t = CRUISE[v.vtype]
        if leg.reverse:
            return 58.0
        if leg.kind == "exit_run":
            t *= 1.35
        if leg.kind in ("to_bay", "to_wait"):
            t = min(t, 34 + remaining * 0.9)
        elif leg.kind == "approach":
            t = min(t, 30 + remaining * 1.6)
        elif leg.kind in ("ramp_up", "ramp_down"):
            t = min(t, 40 + remaining * 1.3)
        return t

    def _finish_leg(self, v, leg, events):
        kind = leg.kind
        v.speed = 0.0 if kind in ("approach", "to_bay", "to_wait") else v.speed
        if kind == "approach":
            v.state = "AT_TICKET"
            events.append(("at_ticket", v.reg, v.gate))
        elif kind == "to_bay":
            v.state = "PARKED"
            v.heading = L.park_heading(int(v.slot_id.split("-")[1]))
            self.version += 1
            events.append(("parked", v.session_id))
        elif kind == "to_wait":
            v.state = "WAITING"
            v.heading = -90.0
            self.version += 1
        elif kind in ("ramp_up", "ramp_down"):
            v.ramp = [0.0, 1.0, v.legs[v.leg_i + 1].floor, False]
        elif kind == "unpark":
            self.version += 1
            events.append(("bay_cleared", v.session_id))
            v.leg_i, v.s = v.leg_i + 1, 0.0
        elif kind == "wait_release":
            v.leg_i, v.s = v.leg_i + 1, 0.0
        elif kind == "exit_run":
            v.state = "GONE"

    def _ramp(self, v, dt, vs):
        r = v.ramp
        v.speed = 0.0
        half = r[1] / 2
        if not r[3] and r[0] >= half:
            nxt = v.legs[v.leg_i + 1]
            ax, ay, _ = nxt.path.at(0)
            if any(o is not v and o.floor == nxt.floor and o.ramp is None and
                   math.hypot(o.x - ax, o.y - ay) < 62 for o in vs):
                return                                     # arrival point busy - hold
            v.floor, r[3] = r[2], True
        r[0] += dt
        k = r[0] / r[1]
        v.scale = 1.0 - 0.45 * (k / 0.5) if k < 0.5 else 0.55 + 0.45 * ((k - 0.5) / 0.5)
        if r[0] >= r[1]:
            v.ramp, v.scale = None, 1.0
            v.leg_i, v.s = v.leg_i + 1, 0.0

    # ---- collision geometry ---------------------------------------------------------------
    @staticmethod
    def _prio(v):
        leg_rev = bool(v.legs and v.leg_i < len(v.legs) and v.legs[v.leg_i].reverse)
        return (1 if leg_rev else 0, v.vid)

    def _ahead(self, v, u):
        """Gap (bumper to bumper) if *u* is in front of *v* along v's direction of motion."""
        dx, dy = u.x - v.x, u.y - v.y
        fwd = dx * v.dir[0] + dy * v.dir[1]
        if fwd <= 0:
            return None
        lat = abs(dx * v.dir[1] - dy * v.dir[0])
        reach = (v.width + u.width) / 2 + 4
        if lat > reach:
            return None
        gap = fwd - (v.length + u.length) / 2
        return gap if gap < 120 else None

    def _gap_ahead(self, v, vs):
        best = None
        for u in vs:
            if u is v or u.floor != v.floor or u.ramp is not None or u.state == "GONE":
                continue
            g = self._ahead(v, u)
            if g is None:
                continue
            if self._ahead(u, v) is not None and u.state not in ("PARKED", "WAITING", "AT_TICKET") \
                    and self._prio(v) < self._prio(u):
                continue                              # mutual block: higher priority proceeds
            best = g if best is None else min(best, g)
        return best

    # ================================================================ snapshot for the GUI
    def snapshot(self):
        with self.lock:
            vehicles = [(v.reg, v.vtype, v.color, v.x, v.y, v.heading, v.scale, v.state, v.floor,
                         v.session_id, v.slot_id) for v in self.vehicles.values()]
            per_floor = {}
            for v in self.vehicles.values():
                per_floor[v.floor] = per_floor.get(v.floor, 0) + 1
            return {"vehicles": vehicles,
                    "barriers": {n: b["angle"] for n, b in self.barriers.items()},
                    "version": self.version, "per_floor": per_floor,
                    "waiting": sum(1 for v in self.vehicles.values() if v.state == "WAITING" and v.vanish is None),
                    "moving": sum(1 for v in self.vehicles.values() if v.state not in ("PARKED", "WAITING")),
                    "last_floor": self.last_floor, "steps": self.steps,
                    "spawn_backlog": len(self.spawn_queue)}


class _Spec:
    """Minimal spec used when restoring vehicles."""
    def __init__(self, reg, vtype, color, permit, gate):
        self.reg, self.vtype, self.color, self.permit, self.gate = reg, vtype, color, permit, gate
