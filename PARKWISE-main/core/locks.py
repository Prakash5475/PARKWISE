"""An RLock wrapper that records contention statistics for the System Monitor page."""
import threading
import time


class TrackedRLock:
    """Re-entrant lock + counters.  Counters are only mutated while the lock is held,
    so they need no extra synchronisation."""

    def __init__(self, name="lock"):
        self.name = name
        self._lock = threading.RLock()
        self.acquisitions = 0
        self.contended = 0
        self.max_wait_ms = 0.0

    def acquire(self, blocking=True, timeout=-1):
        if self._lock.acquire(False):          # fast path - no contention
            self.acquisitions += 1
            return True
        if not blocking:
            return False
        t0 = time.perf_counter()
        ok = self._lock.acquire(True, timeout)
        if ok:
            self.acquisitions += 1
            self.contended += 1
            self.max_wait_ms = max(self.max_wait_ms, (time.perf_counter() - t0) * 1000)
        return ok

    def release(self):
        self._lock.release()

    __enter__ = acquire

    def __exit__(self, *exc):
        self._lock.release()

    def stats(self):
        return {"name": self.name, "acquisitions": self.acquisitions,
                "contended": self.contended, "max_wait_ms": round(self.max_wait_ms, 2)}
