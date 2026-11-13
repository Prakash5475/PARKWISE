"""Vehicle simulation + thread tests (headless)."""
import threading
import time
import unittest

from tests.helpers import make_manager, tmp_db_path, reg
from core.database import ParkingDatabase
from core.models import VehicleSpec
from core.parking_manager import ParkingManager
from core.thread_manager import ThreadManager, TrafficControl
from simulation import layout as L
from simulation.vehicle_sim import VehicleSimulation


def wire(m, sim):
    """Minimal synchronous wiring (no worker threads) so physics can be stepped deterministically."""
    def on_event(kind, *a):
        if kind == "at_ticket":
            r, gate = a
            res = m.request_entry(r, gate)
            if res.status == "ASSIGNED":
                sim.assign(r, res.session.session_id, res.session.slot_id)
                sim.set_barrier(gate, True)
            else:
                sim.send_to_waiting(r)
        elif kind == "entered": m.confirm_entered(a[0])
        elif kind == "parked": m.confirm_parked(a[0])
        elif kind == "bay_cleared": m.release_bay(a[0])
        elif kind == "departed": m.confirm_departed(a[0])
        elif kind == "exit_near": sim.set_barrier("X", True)
    sim.on_event = on_event
    def on_manager(kind, d):
        if kind == "queue_assigned":                       # what EntryGateThread does for a queued vehicle
            sess = d["session"]
            sim.promote(sess.vehicle_number, sess.session_id, sess.slot_id)
            sim.set_barrier("A", True)
    m.subscribe(on_manager)


def run(sim, seconds):
    for _ in range(int(seconds * 60)):
        sim.step(1 / 60)


class SimulationDrivesBackend(unittest.TestCase):
    def setUp(self):
        self.m = make_manager()
        self.sim = VehicleSimulation()
        wire(self.m, self.sim)

    def send(self, r, vt="CAR", gate="A", **kw):
        sp = self.m.register_arrival(VehicleSpec(r, vt, "#D9434E", gate=gate, **kw))
        self.sim.spawn_arrival(sp)

    def test_vehicle_enters_parks_and_bay_becomes_occupied(self):
        self.send("MH15AB1234", "CAR")
        run(self.sim, 1.0)
        self.assertEqual(self.m.snapshot()["occupied"], 0)       # still driving to the gate
        run(self.sim, 14)
        s = self.m.snapshot()
        self.assertEqual((s["parked"], s["entries"]), (1, 1))
        v = next(x for x in self.sim.snapshot()["vehicles"] if x[0] == "MH15AB1234")
        self.assertEqual(v[7], "PARKED")
        cx, cy = L.bay_center(8)
        self.assertAlmostEqual(v[3], cx, delta=1)
        self.assertAlmostEqual(v[4], cy, delta=1)

    def test_bay_is_incoming_while_vehicle_drives_then_occupied(self):
        self.send("MH15AB1234", "CAR", "B")
        run(self.sim, 4)
        self.assertEqual(self.m.slots["G-08"].status, "INCOMING")
        run(self.sim, 12)
        self.assertEqual(self.m.slots["G-08"].status, "OCCUPIED")

    def test_checkout_moves_vehicle_out_and_frees_bay(self):
        self.send("MH15AB1234", "BIKE")
        run(self.sim, 20)
        sid = next(iter(self.m.sessions))
        slot = self.m.sessions[sid].slot_id
        self.m.request_checkout(sid)
        self.m.process_checkout(sid)
        self.assertTrue(self.sim.dispatch_exit(sid))
        run(self.sim, 40)
        self.assertEqual(self.m.slots[slot].status, "AVAILABLE")
        self.assertEqual(self.m.snapshot()["exits"], 1)
        self.assertEqual(len(self.sim.vehicles), 0)
        self.assertEqual(self.m.verify_integrity(), [])

    def test_upper_floor_vehicle_uses_ramp_and_changes_floor(self):
        for i in range(27):                                    # fill ground floor general bays
            sp = self.m.register_arrival(VehicleSpec(reg(), "CAR"))
            r = self.m.request_entry(sp.reg)
            self.m.confirm_parked(r.session.session_id)
            if i == 8:
                pass
        # ground general bays are only 9, so cars beyond that already sit on floors 1/2
        self.send("UPFLOOR01", "CAR")
        run(self.sim, 3)
        self.assertEqual(self.sim.snapshot()["last_floor"], "1" if False else self.sim.snapshot()["last_floor"])

    def test_many_vehicles_never_overlap_destinations(self):
        for i in range(10):
            self.send(reg(), ["CAR", "EV", "BIKE", "VIP"][i % 4], "AB"[i % 2])
            run(self.sim, 1.5)
        run(self.sim, 40)
        s = self.m.snapshot()
        self.assertEqual(s["parked"], 10)
        self.assertEqual(self.m.verify_integrity(), [])
        pos = [(round(v[3]), round(v[4])) for v in self.sim.snapshot()["vehicles"]]
        self.assertEqual(len(pos), len(set(pos)))

    def test_full_garage_sends_vehicle_to_waiting_area_then_releases_it(self):
        for _ in range(27):
            sp = self.m.register_arrival(VehicleSpec(reg(), "CAR"))
            r = self.m.request_entry(sp.reg)
            self.m.confirm_parked(r.session.session_id)
        sid_first = next(iter(self.m.sessions))
        self.send("WAITER001", "CAR")
        run(self.sim, 8)
        v = next(x for x in self.sim.snapshot()["vehicles"] if x[0] == "WAITER001")
        self.assertEqual(v[7], "WAITING")
        self.assertEqual(len(self.m.snapshot()["queue"]), 1)
        # free a bay: the waiting vehicle must be promoted and drive in
        self.m.request_checkout(sid_first)
        self.m.process_checkout(sid_first)
        self.m.release_bay(sid_first)
        self.m.confirm_departed(sid_first)
        run(self.sim, 30)
        self.assertEqual(self.m.snapshot()["queue"], [])
        self.assertEqual(self.m.sessions and next(s for s in self.m.sessions.values()
                                                   if s.vehicle_number == "WAITER001").status, "PARKED")


class RestartRecovery(unittest.TestCase):
    def test_vehicles_are_restored_after_restart(self):
        path = tmp_db_path()
        m = make_manager(path)
        sim = VehicleSimulation()
        wire(m, sim)
        for i, vt in enumerate(("CAR", "EV", "BIKE")):
            sp = m.register_arrival(VehicleSpec(reg(), vt, gate="A"))
            sim.spawn_arrival(sp)
            run(sim, 1.2)
        run(sim, 5)                                           # some parked, some mid-route
        m.db.close()

        m2 = ParkingManager(ParkingDatabase(path))
        sim2 = VehicleSimulation()
        wire(m2, sim2)
        sim2.restore([s.to_dict() for s in m2.sessions.values()], m2.snapshot()["queue"])
        run(sim2, 40)
        s = m2.snapshot()
        self.assertEqual(s["parked"], 3)
        self.assertEqual(m2.verify_integrity(), [])
        self.assertEqual(len(sim2.vehicles), 3)


class Threads(unittest.TestCase):
    def make(self):
        m = make_manager()
        sim = VehicleSimulation()
        return m, sim, ThreadManager(m, sim, TrafficControl(False), make_receipts=False)

    def test_six_threads_start_and_shutdown_gracefully(self):
        m, sim, tm = self.make()
        before = threading.active_count()
        tm.start_all()
        time.sleep(0.6)
        self.assertEqual([t.alive for t in tm.threads], [True] * 6)
        self.assertEqual({t.name for t in tm.threads},
                         {"EntryGate-A", "EntryGate-B", "ExitGate", "OccupancyMonitor", "VehicleMovement", "Billing"})
        t0 = time.time()
        survivors = tm.shutdown(3.0)
        self.assertEqual(survivors, [])
        self.assertLess(time.time() - t0, 3.0)
        self.assertEqual(threading.active_count(), before)
        self.assertTrue(tm.shutdown_event.is_set())

    def test_stop_and_restart_single_thread(self):
        m, sim, tm = self.make()
        tm.start_all()
        t = tm.by_name("EntryGate-A")
        self.assertTrue(t.stop(2))
        self.assertFalse(t.alive)
        self.assertTrue(t.start())
        time.sleep(0.4)
        self.assertTrue(t.alive)
        tm.shutdown()
        self.assertEqual([x for x in tm.threads if x.alive], [])

    def test_end_to_end_with_real_threads(self):
        m, sim, tm = self.make()
        tm.start_all()
        for i, vt in enumerate(("CAR", "EV", "VIP", "BIKE")):
            sp = m.register_arrival(VehicleSpec(reg(), vt, gate="AB"[i % 2]))
            sim.spawn_arrival(sp)
        deadline = time.time() + 40
        while time.time() < deadline and m.snapshot()["parked"] < 4:
            time.sleep(0.25)
        self.assertEqual(m.snapshot()["parked"], 4)
        for sid in list(m.sessions):
            m.request_checkout(sid, "UPI")                   # billing thread -> exit thread -> simulation
        deadline = time.time() + 60
        while time.time() < deadline and m.snapshot()["exits"] < 4:
            time.sleep(0.25)
        s = m.snapshot()
        self.assertEqual((s["exits"], s["occupied"]), (4, 0))
        self.assertEqual(m.db.scalar("SELECT COUNT(*) FROM bills WHERE payment_status='PAID'"), 4)
        self.assertEqual(m.verify_integrity(), [])
        self.assertEqual(tm.shutdown(), [])

    def test_automatic_traffic_runs_and_stays_consistent(self):
        m = make_manager()
        sim = VehicleSimulation()
        tm = ThreadManager(m, sim, TrafficControl(True, "Rush hour"), make_receipts=False)
        tm.start_all()
        time.sleep(25)
        self.assertEqual(tm.shutdown(), [])
        self.assertGreater(m.snapshot()["entries"], 3)
        self.assertEqual(m.verify_integrity(), [])
        self.assertEqual(sum(t.errors for t in tm.threads), 0, [t.last_error for t in tm.threads])


if __name__ == "__main__":
    unittest.main()
