"""Analytics — every number is computed from the SQLite tables (no hard-coded data).

All functions take ``seconds`` (look-back window; ``None`` = all time) and return plain
Python structures so they can be unit-tested and drawn by any chart library.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from config import FLOORS, RATES

TS = "%Y-%m-%d %H:%M:%S"


def _since(seconds, now=None):
    if seconds is None:
        return "0000-00-00 00:00:00"
    return ((now or datetime.now()) - timedelta(seconds=seconds)).strftime(TS)


def bucket_seconds(seconds):
    """Choose a chart bucket size for a look-back window."""
    if seconds is None:
        return 1800
    for limit, size in ((1200, 30), (7200, 120), (30000, 900), (100000, 1800)):
        if seconds <= limit:
            return size
    return 86400


def _bucket_label(ts, size):
    dt = datetime.strptime(ts, TS)
    return dt.strftime("%d %b" if size >= 86400 else "%H:%M")


def _bucket_key(ts, size):
    dt = datetime.strptime(ts, TS)
    epoch = int(dt.timestamp())
    return epoch - epoch % size


class Analytics:
    def __init__(self, db, clock=datetime.now):
        self.db, self.clock = db, clock

    # ---- occupancy trend --------------------------------------------------------
    def occupancy_trend(self, seconds):
        rows = self.db.query("SELECT ts,occupied,reserved,total,queue_len FROM occupancy_samples "
                             "WHERE ts>=? ORDER BY ts", (_since(seconds, self.clock()),))
        size = bucket_seconds(seconds)
        buckets = defaultdict(list)
        for r in rows:
            buckets[_bucket_key(r["ts"], size)].append(r)
        out = []
        for k in sorted(buckets):
            g = buckets[k]
            avg = sum(x["occupied"] for x in g) / len(g)
            total = g[0]["total"] or 1
            out.append({"t": datetime.fromtimestamp(k), "occupied": round(avg, 1),
                        "percent": round(avg / total * 100, 1),
                        "queue": max(x["queue_len"] for x in g)})
        return out

    # ---- category distribution --------------------------------------------------
    def category_distribution(self, seconds):
        rows = self.db.query("SELECT vehicle_type, COUNT(*) n FROM sessions WHERE entry_time>=? "
                             "GROUP BY vehicle_type", (_since(seconds, self.clock()),))
        d = {r["vehicle_type"]: r["n"] for r in rows}
        return {k: d.get(k, 0) for k in RATES}

    # ---- entries / exits ------------------------------------------------------------
    def entries_exits(self, seconds):
        since, size = _since(seconds, self.clock()), bucket_seconds(seconds)
        ent = defaultdict(int)
        ext = defaultdict(int)
        for r in self.db.query("SELECT entered_time t FROM sessions WHERE entered_time>=?", (since,)):
            ent[_bucket_key(r["t"], size)] += 1
        for r in self.db.query("SELECT exit_time t FROM sessions WHERE exit_time>=?", (since,)):
            ext[_bucket_key(r["t"], size)] += 1
        keys = sorted(set(ent) | set(ext))
        return [{"label": _bucket_label(datetime.fromtimestamp(k).strftime(TS), size),
                 "entries": ent[k], "exits": ext[k]} for k in keys]

    # ---- revenue ------------------------------------------------------------------------
    def revenue_trend(self, seconds):
        since, size = _since(seconds, self.clock()), bucket_seconds(seconds)
        rev = defaultdict(float)
        for r in self.db.query("SELECT paid_at t,total_amount a FROM bills WHERE payment_status='PAID' "
                               "AND paid_at>=?", (since,)):
            rev[_bucket_key(r["t"], size)] += r["a"]
        keys = sorted(rev)
        cum, out = 0.0, []
        for k in keys:
            cum += rev[k]
            out.append({"label": _bucket_label(datetime.fromtimestamp(k).strftime(TS), size),
                        "revenue": round(rev[k], 2), "cumulative": round(cum, 2)})
        return out

    def revenue_total(self, seconds):
        return float(self.db.scalar("SELECT SUM(total_amount) FROM bills WHERE payment_status='PAID' "
                                    "AND paid_at>=?", (_since(seconds, self.clock()),), default=0.0))

    # ---- peak hours ------------------------------------------------------------------------
    def peak_hours(self, seconds):
        counts = [0] * 24
        for r in self.db.query("SELECT entered_time t FROM sessions WHERE entered_time>=?",
                               (_since(seconds, self.clock()),)):
            counts[int(r["t"][11:13])] += 1
        return counts

    # ---- durations -----------------------------------------------------------------------------
    def avg_duration(self, seconds):
        """Average real parking duration in seconds, overall and per vehicle type."""
        rows = self.db.query("SELECT vehicle_type, AVG(duration_s) a, COUNT(*) n FROM bills "
                             "WHERE paid_at>=? GROUP BY vehicle_type", (_since(seconds, self.clock()),))
        per = {k: 0.0 for k in RATES}
        tot_n = tot = 0
        for r in rows:
            per[r["vehicle_type"]] = r["a"] or 0.0
            tot += (r["a"] or 0.0) * r["n"]
            tot_n += r["n"]
        return (tot / tot_n if tot_n else 0.0), per

    # ---- floor occupancy (current) ----------------------------------------------------------------
    def floor_occupancy(self):
        out = {}
        for f in FLOORS:
            rows = self.db.query("SELECT status, COUNT(*) n FROM slots WHERE floor=? GROUP BY status", (f,))
            d = {r["status"]: r["n"] for r in rows}
            out[f] = {"occupied": d.get("OCCUPIED", 0) + d.get("INCOMING", 0),
                      "reserved": d.get("RESERVED", 0), "available": d.get("AVAILABLE", 0)}
        return out

    # ---- KPI block -------------------------------------------------------------------------------------
    def kpis(self, seconds):
        since = _since(seconds, self.clock())
        entries = self.db.scalar("SELECT COUNT(*) FROM sessions WHERE entered_time>=?", (since,), default=0)
        exits = self.db.scalar("SELECT COUNT(*) FROM sessions WHERE exit_time>=?", (since,), default=0)
        avg, _ = self.avg_duration(seconds)
        peaks = self.peak_hours(seconds)
        peak = max(range(24), key=lambda h: peaks[h]) if any(peaks) else None
        return {"entries": entries, "exits": exits, "revenue": self.revenue_total(seconds),
                "avg_duration_s": avg, "peak_hour": peak}
