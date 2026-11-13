"""Facility geometry shared by the simulation (movement) and the GUI (drawing).

Logical canvas: 1200 x 470 units.  The facility interior starts at GATE_X; to the left
is the public road with two entry lanes (A, B), the exit lane, ticket points and the
waiting area.  Every floor uses the same plan; floors 1 and 2 are reached by the ramp.

        Top bay row   (bays  1- 9)   y 52..158      nose-up parking
 L1 --> lane A / traffic lane 1 (flows right)       y = 196
 L2 --> lane B (outside) / median inside            y = 235
 L3 <-- exit lane (flows left)                      y = 274
        Bottom bay row (bays 10-18)  y 312..418     nose-down parking
"""
import bisect
import math

LW, LH = 1200, 470
GATE_X = 200
TICKET_X = 60
LANE_Y = {"A": 196, "B": 235, "X": 274}
BAY_W, BAY_H = 92, 106
TOP_Y, BOT_Y = 52, 312
BAY_X0, PITCH = 250, 100
RAMP_UP = (236, 196)
RAMP_DOWN = (236, 274)
WAIT_CELLS = [(88, 105), (134, 105), (180, 105)]       # waiting area (centres)
WAIT_W = 44
SPAWN_X = -130
EXIT_X = -150
UTURN_X = 1165


def bay_row(number):
    return "top" if number <= 9 else "bottom"


def bay_col(number):
    return (number - 1) if number <= 9 else (number - 10)


def bay_rect(number):
    x = BAY_X0 + bay_col(number) * PITCH
    y = TOP_Y if bay_row(number) == "top" else BOT_Y
    return x, y, x + BAY_W, y + BAY_H


def bay_center(number):
    x1, y1, x2, y2 = bay_rect(number)
    return (x1 + x2) / 2, (y1 + y2) / 2


def park_heading(number):
    """Parked nose towards the back wall: up for the top row, down for the bottom row."""
    return -90.0 if bay_row(number) == "top" else 90.0


# --------------------------------------------------------------------- paths
class Path:
    def __init__(self, pts):
        self.pts = pts
        self.cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.length = self.cum[-1]

    def at(self, s):
        """Return (x, y, tangent_degrees) at distance *s* along the path."""
        s = max(0.0, min(self.length, s))
        i = min(bisect.bisect_right(self.cum, s) - 1, len(self.pts) - 2)
        a, b = self.pts[i], self.pts[i + 1]
        seg = self.cum[i + 1] - self.cum[i] or 1e-9
        t = (s - self.cum[i]) / seg
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
                math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])))


def fillet(points, radius=30, steps=8):
    """Round every interior corner of a polyline with a quadratic Bezier arc."""
    if len(points) < 3:
        return list(points)
    out = [points[0]]
    for i in range(1, len(points) - 1):
        a, p, b = points[i - 1], points[i], points[i + 1]
        da, db = math.hypot(a[0] - p[0], a[1] - p[1]), math.hypot(b[0] - p[0], b[1] - p[1])
        r = min(radius, da / 2, db / 2)
        if r < 1:
            out.append(p)
            continue
        t1 = (p[0] + (a[0] - p[0]) / da * r, p[1] + (a[1] - p[1]) / da * r)
        t2 = (p[0] + (b[0] - p[0]) / db * r, p[1] + (b[1] - p[1]) / db * r)
        for k in range(steps + 1):
            u = k / steps
            out.append(((1 - u) ** 2 * t1[0] + 2 * u * (1 - u) * p[0] + u * u * t2[0],
                        (1 - u) ** 2 * t1[1] + 2 * u * (1 - u) * p[1] + u * u * t2[1]))
    out.append(points[-1])
    return out


class Leg:
    """One continuous stretch of a vehicle's journey on a single floor."""
    def __init__(self, floor, pts, kind, reverse=False, barrier=None, radius=30):
        self.floor, self.kind, self.reverse, self.barrier = floor, kind, reverse, barrier
        self.path = Path(fillet(pts, radius))
        self.fired = set()


# --------------------------------------------------------------------- routes
def _to_bay_pts(start_x, start_y, number):
    """Waypoints from a point on lane 1 (or lane 3 after the U-turn) into bay *number*."""
    cx, cy = bay_center(number)
    if bay_row(number) == "top":
        return [(start_x, start_y), (cx, LANE_Y["A"]), (cx, cy)]
    return [(start_x, start_y), (UTURN_X, LANE_Y["A"]), (UTURN_X, LANE_Y["X"]),
            (cx, LANE_Y["X"]), (cx, cy)]


def approach_leg(gate):
    y = LANE_Y[gate]
    return Leg("G", [(SPAWN_X, y), (TICKET_X, y)], "approach", radius=1)


def entry_legs(gate, slot_id, start=None):
    """Legs from the ticket point to the allocated bay (ground floor + ramp if needed)."""
    floor, number = slot_id.split("-")[0], int(slot_id.split("-")[1])
    y = LANE_Y[gate]
    sx, sy = start or (TICKET_X, y)
    if gate == "B" and sy == y:
        head = [(sx, sy), (GATE_X + 14, y), (GATE_X + 46, LANE_Y["A"])]
    else:
        head = [(sx, sy)]
    if floor == "G":
        body = _to_bay_pts(head[-1][0], head[-1][1], number)[1:]
        return [Leg("G", head + body, "to_bay", barrier=gate, radius=26)]
    legs = [Leg("G", head + [RAMP_UP], "ramp_up", barrier=gate, radius=26)]
    legs.append(Leg(floor, _to_bay_pts(RAMP_UP[0], RAMP_UP[1], number), "to_bay", radius=26))
    return legs


def exit_legs(slot_id):
    """Legs from a parked bay to the exit road (reverse out, circulate, leave)."""
    floor, number = slot_id.split("-")[0], int(slot_id.split("-")[1])
    cx, cy = bay_center(number)
    top = bay_row(number) == "top"
    lane_y = LANE_Y["A"] if top else LANE_Y["X"]
    unpark = Leg(floor, [(cx, cy), (cx, lane_y)], "unpark", reverse=True, radius=1)
    if top:
        run = [(cx, lane_y), (UTURN_X, LANE_Y["A"]), (UTURN_X, LANE_Y["X"])]
        run += [RAMP_DOWN] if floor != "G" else [(EXIT_X, LANE_Y["X"])]
    else:
        run = [(cx, lane_y), RAMP_DOWN] if floor != "G" else [(cx, lane_y), (EXIT_X, LANE_Y["X"])]
    legs = [unpark]
    if floor == "G":
        legs.append(Leg("G", run, "exit_run", barrier="X", radius=40))
    else:
        legs.append(Leg(floor, run, "ramp_down", radius=40))
        legs.append(Leg("G", [RAMP_DOWN, (EXIT_X, LANE_Y["X"])], "exit_run", barrier="X", radius=10))
    return legs


def wait_legs(gate, cell):
    """From the ticket point forward into a waiting-area cell (never reverses)."""
    cx, cy = WAIT_CELLS[cell]
    y = LANE_Y[gate]
    pts = [(TICKET_X, y), (cx, y), (cx, cy)] if gate == "A" else \
          [(TICKET_X, y), (cx - 24, y), (cx - 6, LANE_Y["A"]), (cx, LANE_Y["A"] - 24), (cx, cy)]
    return [Leg("G", pts, "to_wait", radius=24)]


def release_legs(cell, slot_id):
    """Waiting cell -> reverse onto lane A -> normal entry route to *slot_id*."""
    cx, cy = WAIT_CELLS[cell]
    back = Leg("G", [(cx, cy), (cx, LANE_Y["A"])], "wait_release", reverse=True, radius=1)
    return [back] + entry_legs("A", slot_id, start=(cx, LANE_Y["A"]))


def restore_exit_legs(slot_id, released):
    """Exit route for a vehicle recovered after a restart."""
    if not released:
        return exit_legs(slot_id)
    floor, number = slot_id.split("-")[0], int(slot_id.split("-")[1])
    cx = min(bay_center(number)[0], 1000)
    if floor == "G":
        return [Leg("G", [(cx, LANE_Y["X"]), (EXIT_X, LANE_Y["X"])], "exit_run", barrier="X", radius=10)]
    return [Leg(floor, [(cx, LANE_Y["X"]), RAMP_DOWN], "ramp_down", radius=10),
            Leg("G", [RAMP_DOWN, (EXIT_X, LANE_Y["X"])], "exit_run", barrier="X", radius=10)]
