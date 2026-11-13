import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.database import ParkingDatabase
from core.parking_manager import ParkingManager
from core.models import VehicleSpec


class FakeClock:
    def __init__(self):
        self.t = datetime(2026, 11, 13, 9, 0, 0)

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


def make_manager(path=":memory:", clock=None):
    db = ParkingDatabase(path)
    m = ParkingManager(db, clock=clock)
    m.set_time_scale(1)
    return m


def tmp_db_path():
    return str(Path(tempfile.mkdtemp()) / "t.db")


_n = [0]


def reg(prefix="MH"):
    _n[0] += 1
    return f"{prefix}{_n[0]:06d}"


def park(m, vtype="CAR", permit=False, preferred=None, gate="A", r=None):
    """Register + allocate + physically park. Returns the Session (or None if queued)."""
    spec = m.register_arrival(VehicleSpec(r or reg(), vtype, "#3B7DDD", permit, preferred, gate))
    res = m.request_entry(spec.reg, gate)
    if res.status != "ASSIGNED":
        return None
    m.confirm_entered(res.session.session_id)
    m.confirm_parked(res.session.session_id)
    return res.session


def checkout_and_leave(m, sid, method="UPI"):
    m.request_checkout(sid, method)
    bill = m.process_checkout(sid)
    m.release_bay(sid)
    m.confirm_departed(sid)
    return bill
