"""Core back-end tests: allocation rules, billing, persistence, concurrency, queue, reservations."""
import sqlite3
import threading
import unittest
from datetime import datetime, timedelta

from tests.helpers import (FakeClock, make_manager, park, checkout_and_leave, tmp_db_path, reg)
from core import billing
from core.analytics import Analytics
from core.allocation import AllocationEngine, tiers
from core.database import ParkingDatabase
from core.models import VehicleSpec, AVAILABLE, OCCUPIED, RESERVED, INCOMING
from core.parking_manager import ParkingManager, normalize_reg


class AllocationRules(unittest.TestCase):
    def setUp(self):
        self.m = make_manager()

    def test_capacity_is_three_floors_of_eighteen(self):
        s = self.m.snapshot()
        self.assertEqual(s["total"], 54)
        for f in ("G", "1", "2"):
            self.assertEqual(s["floors"][f]["total"], 18)

    def test_ev_prefers_ev_bay(self):
        s = park(self.m, "EV")
        self.assertEqual(self.m.slots[s.slot_id].category, "EV")

    def test_ev_falls_back_to_general_when_ev_bays_full(self):
        for _ in range(9):
            park(self.m, "EV")
        s = park(self.m, "EV")
        self.assertEqual(self.m.slots[s.slot_id].category, "GENERAL")

    def test_car_never_takes_ev_vip_or_accessible_bay(self):
        cats = set()
        for _ in range(27):
            s = park(self.m, "CAR")
            cats.add(self.m.slots[s.slot_id].category)
        self.assertEqual(cats, {"GENERAL"})
        self.assertIsNone(park(self.m, "CAR"))          # 28th car must wait

    def test_vip_gets_vip_bay(self):
        s = park(self.m, "VIP")
        self.assertEqual(self.m.slots[s.slot_id].category, "VIP")

    def test_bike_prefers_moto_bay(self):
        s = park(self.m, "BIKE")
        self.assertEqual(self.m.slots[s.slot_id].category, "MOTO")

    def test_accessible_requires_permit(self):
        s = park(self.m, "CAR", permit=True)
        self.assertEqual(self.m.slots[s.slot_id].category, "ACCESSIBLE")
        with self.assertRaises(ValueError):
            self.m.register_arrival(VehicleSpec(reg(), "CAR", preferred_slot="G-02"))
        s2 = park(self.m, "CAR")
        self.assertNotEqual(self.m.slots[s2.slot_id].category, "ACCESSIBLE")

    def test_nearest_bay_first(self):
        a = park(self.m, "CAR")
        b = park(self.m, "CAR")
        self.assertEqual((a.slot_id, b.slot_id), ("G-08", "G-09"))

    def test_manual_bay_selection_and_validation(self):
        s = park(self.m, "CAR", preferred="G-15")
        self.assertEqual(s.slot_id, "G-15")
        with self.assertRaises(ValueError):
            self.m.register_arrival(VehicleSpec(reg(), "CAR", preferred_slot="G-05"))   # EV bay
        with self.assertRaises(ValueError):
            self.m.register_arrival(VehicleSpec(reg(), "CAR", preferred_slot="G-15"))   # occupied

    def test_tier_table(self):
        self.assertEqual(tiers("EV"), ["EV", "GENERAL"])
        self.assertEqual(tiers("CAR", True), ["ACCESSIBLE", "GENERAL"])


class DuplicatesAndValidation(unittest.TestCase):
    def setUp(self):
        self.m = make_manager()

    def test_reg_normalisation(self):
        self.assertEqual(normalize_reg(" mh15 ab-1234 "), "MH15AB1234")
        for bad in ("", "AB", "A!B@C#D$", "X" * 13):
            with self.assertRaises(ValueError):
                normalize_reg(bad)

    def test_duplicate_while_arriving(self):
        self.m.register_arrival(VehicleSpec("MH15AB1234", "CAR"))
        with self.assertRaises(ValueError):
            self.m.register_arrival(VehicleSpec("mh15-ab-1234", "BIKE"))

    def test_duplicate_while_parked(self):
        park(self.m, "CAR", r="MH15AB1234")
        with self.assertRaises(ValueError):
            self.m.register_arrival(VehicleSpec("MH15AB1234", "CAR"))

    def test_can_return_after_leaving(self):
        s = park(self.m, "CAR", r="MH15AB1234")
        checkout_and_leave(self.m, s.session_id)
        self.m.register_arrival(VehicleSpec("MH15AB1234", "CAR"))

    def test_database_blocks_duplicate_slot_even_if_python_is_bypassed(self):
        s = park(self.m, "CAR")
        with self.assertRaises(sqlite3.IntegrityError):
            self.m.db.insert("sessions", {"ticket_id": "X1", "vehicle_number": "ZZ999999", "slot_id": s.slot_id,
                                          "status": "ASSIGNED", "holds_slot": 1})

    def test_database_blocks_duplicate_active_vehicle(self):
        s = park(self.m, "CAR", r="MH15AB1234")
        with self.assertRaises(sqlite3.IntegrityError):
            self.m.db.insert("sessions", {"ticket_id": "X2", "vehicle_number": "MH15AB1234", "slot_id": "G-15",
                                          "status": "PARKED", "holds_slot": 1})


class ConcurrentAllocation(unittest.TestCase):
    def test_no_duplicate_slots_under_contention(self):
        m = make_manager()
        results, errors = [], []

        def worker(gate, n):
            for i in range(n):
                try:
                    spec = m.register_arrival(VehicleSpec(reg("KA"), ["CAR", "EV", "VIP", "BIKE"][i % 4], gate=gate))
                    r = m.request_entry(spec.reg, gate)
                    results.append(r)
                except ValueError:
                    pass                                    # waiting area / road congestion
                except Exception as e:                      # anything else is a bug
                    errors.append(repr(e))
        ts = [threading.Thread(target=worker, args=("AB"[i % 2], 25)) for i in range(5)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errors, [])
        slots = [r.session.slot_id for r in results if r.status == "ASSIGNED"]
        self.assertEqual(len(slots), len(set(slots)), "a bay was allocated twice")
        self.assertEqual(m.verify_integrity(), [])
        held = m.db.scalar("SELECT COUNT(DISTINCT slot_id) FROM sessions WHERE holds_slot=1")
        self.assertEqual(held, len(slots))

    def test_two_threads_race_for_the_last_bay(self):
        m = make_manager()
        for _ in range(26):
            park(m, "CAR")
        specs = [m.register_arrival(VehicleSpec(reg(), "CAR")) for _ in range(2)]
        out = []
        bar = threading.Barrier(2)

        def go(sp):
            bar.wait()
            out.append(m.request_entry(sp.reg))
        ts = [threading.Thread(target=go, args=(s,)) for s in specs]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(r.status for r in out), ["ASSIGNED", "QUEUED"])


class QueueAndPriority(unittest.TestCase):
    def fill_everything(self, m):
        sessions = []
        for vt, n in (("CAR", 27), ("EV", 9), ("VIP", 6), ("BIKE", 6)):
            for _ in range(n):
                sessions.append(park(m, vt))
        for _ in range(6):
            sessions.append(park(m, "CAR", permit=True))
        return sessions

    def test_full_facility_queues_and_releases_in_order(self):
        m = make_manager()
        sessions = self.fill_everything(m)
        self.assertEqual(m.snapshot()["available"], 0)
        s = m.register_arrival(VehicleSpec(reg(), "CAR"))
        r = m.request_entry(s.reg)
        self.assertEqual(r.status, "QUEUED")
        self.assertTrue(any(e["category"] == "FULL" for e in m.events))
        self.assertEqual(len(m.snapshot()["queue"]), 1)
        assigned = []
        m.subscribe(lambda k, d: assigned.append(d["session"].vehicle_number) if k == "queue_assigned" else None)
        general = next(x for x in sessions if m.slots[x.slot_id].category == "GENERAL")
        checkout_and_leave(m, general.session_id)
        self.assertEqual(assigned, [s.reg])
        self.assertEqual(m.snapshot()["queue"], [])
        self.assertEqual(m.verify_integrity(), [])

    def test_vip_jumps_the_queue(self):
        m = make_manager()
        sessions = self.fill_everything(m)
        car = m.register_arrival(VehicleSpec(reg(), "CAR"))
        m.request_entry(car.reg)
        vip = m.register_arrival(VehicleSpec(reg(), "VIP"))
        m.request_entry(vip.reg)
        self.assertEqual(m.snapshot()["queue"][0]["reg"], vip.reg)
        got = []
        m.subscribe(lambda k, d: got.append(d["session"].vehicle_number) if k == "queue_assigned" else None)
        general = next(x for x in sessions if m.slots[x.slot_id].category == "GENERAL")
        checkout_and_leave(m, general.session_id)
        self.assertEqual(got, [vip.reg])                 # VIP served first; car still waits
        self.assertEqual([q["reg"] for q in m.snapshot()["queue"]], [car.reg])

    def test_waiting_car_does_not_block_a_bike_that_fits(self):
        m = make_manager()
        for _ in range(27):
            park(m, "CAR")
        car = m.register_arrival(VehicleSpec(reg(), "CAR"))
        self.assertEqual(m.request_entry(car.reg).status, "QUEUED")
        bike = park(m, "BIKE")
        self.assertIsNotNone(bike)

    def test_waiting_area_capacity(self):
        m = make_manager()
        for _ in range(27):
            park(m, "CAR")
        for _ in range(3):
            s = m.register_arrival(VehicleSpec(reg(), "CAR"))
            m.request_entry(s.reg)
        with self.assertRaises(ValueError):
            m.register_arrival(VehicleSpec(reg(), "CAR"))

    def test_cancel_queue(self):
        m = make_manager()
        for _ in range(27):
            park(m, "CAR")
        s = m.register_arrival(VehicleSpec(reg(), "CAR"))
        m.request_entry(s.reg)
        m.cancel_queue(s.reg)
        self.assertEqual(m.snapshot()["queue"], [])


class Reservations(unittest.TestCase):
    def test_reserved_bay_is_protected_and_used_by_owner(self):
        clock = FakeClock()
        m = make_manager(clock=clock)
        m.reserve("G-08", "VIPGUEST1", "CAR", False, 60)
        self.assertEqual(m.slots["G-08"].status, RESERVED)
        first = park(m, "CAR")
        self.assertNotEqual(first.slot_id, "G-08")        # skips the reserved bay
        owner = park(m, "CAR", r="VIPGUEST1")
        self.assertEqual(owner.slot_id, "G-08")
        self.assertEqual(m.db.scalar("SELECT status FROM reservations WHERE vehicle_number='VIPGUEST1'"), "FULFILLED")

    def test_reservation_validation(self):
        m = make_manager()
        with self.assertRaises(ValueError):
            m.reserve("G-05", "ABCD1234", "CAR")           # EV bay, not for a car
        with self.assertRaises(ValueError):
            m.reserve("G-01", "ABCD1234", "CAR")           # accessible needs a permit
        m.reserve("G-08", "ABCD1234", "CAR")
        with self.assertRaises(ValueError):
            m.reserve("G-09", "ABCD1234", "CAR")           # one reservation per vehicle
        with self.assertRaises(ValueError):
            m.reserve("G-08", "WXYZ1234", "CAR")           # already reserved

    def test_expiry_and_release(self):
        clock = FakeClock()
        m = make_manager(clock=clock)
        m.reserve("G-08", "ABCD1234", "CAR", False, 30)
        clock.advance(minutes=31)
        self.assertEqual(m.expire_reservations(), ["G-08"])
        self.assertEqual(m.slots["G-08"].status, AVAILABLE)
        m.reserve("G-09", "EFGH1234", "CAR")
        self.assertEqual(m.release_slot("G-09"), "reservation cancelled")
        self.assertEqual(m.slots["G-09"].status, AVAILABLE)

    def test_release_occupied_starts_checkout(self):
        m = make_manager()
        s = park(m, "CAR")
        self.assertEqual(m.release_slot(s.slot_id), "checkout started")
        with self.assertRaises(ValueError):
            m.release_slot("G-16")                            # already available


class Billing(unittest.TestCase):
    T0 = datetime(2026, 1, 1, 10, 0, 0)

    def bill(self, vt, minutes, scale=1):
        return billing.calculate(vt, self.T0, self.T0 + timedelta(minutes=minutes), scale)

    def test_grace_period_is_free(self):
        self.assertEqual(self.bill("CAR", 5).total_amount, 0)
        self.assertTrue(self.bill("CAR", 5).grace_applied)

    def test_first_hour_and_rounding_up(self):
        self.assertEqual(self.bill("CAR", 6).base_amount, 40)
        self.assertEqual(self.bill("CAR", 65).base_amount, 40)
        self.assertEqual(self.bill("CAR", 66).base_amount, 80)

    def test_vehicle_specific_rates_and_gst(self):
        self.assertEqual(self.bill("BIKE", 30).base_amount, 20)
        self.assertEqual(self.bill("EV", 30).base_amount, 50)
        self.assertEqual(self.bill("VIP", 30).base_amount, 60)
        b = self.bill("VIP", 30)
        self.assertEqual((b.tax_amount, b.total_amount), (10.8, 70.8))

    def test_demo_time_scale(self):
        b = billing.calculate("CAR", self.T0, self.T0 + timedelta(minutes=2), 60)   # 2 real min = 2 h
        self.assertEqual(b.billed_hours, 2)

    def test_unknown_type(self):
        with self.assertRaises(ValueError):
            self.bill("TRUCK", 10)


class Lifecycle(unittest.TestCase):
    def test_full_entry_to_exit_with_bill(self):
        clock = FakeClock()
        m = make_manager(clock=clock)
        s = park(m, "EV", r="MH15AB1234")
        snap = m.snapshot()
        self.assertEqual((snap["parked"], snap["entries"], snap["exits"]), (1, 1, 0))
        self.assertEqual(m.slots[s.slot_id].status, OCCUPIED)
        clock.advance(hours=2)
        m.request_checkout(s.session_id, "CARD")
        with self.assertRaises(ValueError):
            m.request_checkout(s.session_id)                    # no double checkout
        b = m.process_checkout(s.session_id)
        self.assertEqual(b.total_amount, 118.0)                 # 2 h * 50 + 18 % GST
        self.assertEqual(m.slots[s.slot_id].status, OCCUPIED)   # still there until it pulls out
        m.release_bay(s.session_id)
        self.assertEqual(m.slots[s.slot_id].status, AVAILABLE)
        m.confirm_departed(s.session_id)
        snap = m.snapshot()
        self.assertEqual((snap["occupied"], snap["exits"], snap["revenue"]), (0, 1, 118.0))
        row = m.db.query("SELECT * FROM sessions WHERE session_id=?", (s.session_id,))[0]
        self.assertEqual((row["status"], row["payment_status"], row["amount"]), ("COMPLETED", "PAID", 118.0))
        self.assertIsNotNone(row["exit_time"])

    def test_cannot_checkout_before_parked(self):
        m = make_manager()
        sp = m.register_arrival(VehicleSpec(reg(), "CAR"))
        r = m.request_entry(sp.reg)
        with self.assertRaises(ValueError):
            m.request_checkout(r.session.session_id)

    def test_tickets_are_unique(self):
        m = make_manager()
        ids = {park(m, "CAR").ticket_id for _ in range(20)}
        self.assertEqual(len(ids), 20)

    def test_slot_detail(self):
        m = make_manager()
        s = park(m, "CAR", r="MH15AB1234")
        d = m.slot_detail(s.slot_id)
        self.assertEqual((d["vehicle_number"], d["ticket_id"], d["vehicle_type"]), ("MH15AB1234", s.ticket_id, "CAR"))
        self.assertIsNotNone(d["duration_s"])


class Persistence(unittest.TestCase):
    def test_everything_survives_a_restart(self):
        path = tmp_db_path()
        m = make_manager(path)
        a = park(m, "CAR", r="MH15AB1234")
        b = park(m, "EV", r="KA01EV0001")
        m.reserve("G-12", "RESV0001", "CAR", False, 120)
        for _ in range(25):                                   # fills every remaining general bay
            self.assertIsNotNone(park(m, "CAR"))
        q = m.register_arrival(VehicleSpec("WAIT0001", "CAR"))
        m.request_entry(q.reg)
        checkout_and_leave(m, b.session_id)
        before = m.snapshot()
        m.db.close()

        m2 = ParkingManager(ParkingDatabase(path))
        after = m2.snapshot()
        self.assertEqual({k: v["status"] for k, v in before["slots"].items()},
                         {k: v["status"] for k, v in after["slots"].items()})
        self.assertEqual((before["entries"], before["exits"], before["revenue"]),
                         (after["entries"], after["exits"], after["revenue"]))
        self.assertEqual(after["slots"][a.slot_id]["vehicle_number"], "MH15AB1234")
        self.assertEqual([x["reg"] for x in after["queue"]], ["WAIT0001"])
        self.assertEqual(m2.reservations["G-12"]["vehicle_number"], "RESV0001")
        self.assertEqual(m2.verify_integrity(), [])
        self.assertGreater(len(m2.recent_events()), 5)
        # the restored vehicle can still be checked out normally
        checkout_and_leave(m2, a.session_id)
        self.assertEqual(m2.snapshot()["exits"], before["exits"] + 1)

    def test_legacy_v1_database_is_migrated_not_destroyed(self):
        path = tmp_db_path()
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE tickets(ticket_id TEXT PRIMARY KEY, vehicle_number TEXT, vehicle_type TEXT, priority INTEGER, "
                    "slot_id TEXT, entry_time TEXT, exit_time TEXT, amount REAL)")
        con.execute("INSERT INTO tickets VALUES('OLD1','MH01OLD001','CAR',0,'G-01','2025-01-01T10:00:00','2025-01-01T11:00:00',40)")
        con.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, event_time TEXT, category TEXT, message TEXT)")
        con.commit()
        con.close()
        m = ParkingManager(ParkingDatabase(path))
        self.assertEqual(m.db.scalar("SELECT COUNT(*) FROM legacy_tickets_v1"), 1)
        self.assertEqual(m.snapshot()["exits"], 1)
        self.assertEqual(m.snapshot()["revenue"], 40.0)


class AnalyticsTests(unittest.TestCase):
    def test_all_numbers_come_from_the_database(self):
        clock = FakeClock()
        m = make_manager(clock=clock)
        a = Analytics(m.db, clock)
        self.assertEqual(a.kpis(3600)["entries"], 0)           # empty state
        self.assertEqual(a.avg_duration(None)[0], 0.0)
        sessions = [park(m, vt) for vt in ("CAR", "CAR", "EV", "BIKE", "VIP")]
        m.record_sample()
        clock.advance(minutes=90)
        for s in sessions[:3]:
            checkout_and_leave(m, s.session_id)
        k = a.kpis(None)
        self.assertEqual((k["entries"], k["exits"]), (5, 3))
        self.assertEqual(k["revenue"], round(2 * 94.4 + 118.0, 2))    # 2 cars (2 h) + 1 EV (2 h), incl. GST
        self.assertEqual(a.category_distribution(None), {"CAR": 2, "BIKE": 1, "EV": 1, "VIP": 1})
        self.assertEqual(sum(a.peak_hours(None)), 5)
        self.assertEqual(a.peak_hours(None)[9], 5)
        self.assertGreater(a.avg_duration(None)[0], 0)
        self.assertEqual(a.floor_occupancy()["G"]["occupied"], 2)
        self.assertEqual(sum(p["entries"] for p in a.entries_exits(None)), 5)
        self.assertGreater(a.revenue_trend(None)[-1]["cumulative"], 0)
        self.assertTrue(a.occupancy_trend(None))


if __name__ == "__main__":
    unittest.main()
