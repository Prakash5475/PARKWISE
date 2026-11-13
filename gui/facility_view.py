"""Top-down parking facility renderer (tkinter Canvas).

Three drawing layers keep the animation smooth:
  * static   - floor, lanes, bays, parked/waiting vehicles. Redrawn only when the backend
               version, the simulation's parked-set, the floor, the size or the selection changes.
  * dynamic  - moving vehicles, barrier arms, hover/selection outlines. Redrawn every frame.
All data comes from ParkingManager.snapshot() and VehicleSimulation.snapshot() copies,
so this widget never touches shared state directly and only runs on the Tk main thread.
"""
import math
import tkinter as tk

from config import FLOOR_NAMES, SLOTS_PER_FLOOR
from gui import theme as T
from gui.widgets import tint
from simulation import layout as L
from simulation.vehicle_art import draw_vehicle, BOLT, GOLD, shade

STATUS_FILL = {"AVAILABLE": "#0F2A26", "OCCUPIED": "#2B1620", "RESERVED": "#2E2612", "INCOMING": "#0F2A3A"}
STATUS_EDGE = {"AVAILABLE": "#23A06B", "OCCUPIED": T.RED, "RESERVED": T.AMBER, "INCOMING": T.CYAN}
CAT_STRIPE = {"EV": T.GREEN, "VIP": GOLD, "ACCESSIBLE": T.BLUE, "MOTO": T.PURPLE, "GENERAL": "#3A4A68"}
FLOOR_BG, AISLE, ROAD, WALL, MARK = "#0E1624", "#141E30", "#111B2D", "#2A3857", "#34476E"


class FacilityCanvas(tk.Canvas):
    def __init__(self, master, on_select=None, **kw):
        super().__init__(master, bg=T.BG, highlightthickness=0, **kw)
        self.on_select = on_select
        self.floor = "G"
        self.k, self.ox, self.oy = 1.0, 0.0, 0.0
        self.selected = None
        self.hover = None
        self._sig = None
        self._snap = None
        self._sim = None
        self.bay_boxes = {}
        self.bind("<Configure>", lambda e: self._invalidate())
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<Button-1>", self._click)

    # ---- geometry helpers -------------------------------------------------------
    def _fit(self):
        w, h = max(self.winfo_width(), 300), max(self.winfo_height(), 200)
        self.k = min(w / L.LW, h / L.LH)
        self.ox, self.oy = (w - L.LW * self.k) / 2, (h - L.LH * self.k) / 2

    def p(self, x, y):
        return self.ox + x * self.k, self.oy + y * self.k

    def r(self, x1, y1, x2, y2, **kw):
        a, b = self.p(x1, y1)
        c, d = self.p(x2, y2)
        return self.create_rectangle(a, b, c, d, **kw)

    def fnt(self, size, weight="bold"):
        return T.tkfont_tuple(max(6, int(round(size * self.k * 0.9))), weight)

    def txt(self, x, y, text, size=9, color=T.MUTED, anchor="center", tags="static", weight="bold"):
        a, b = self.p(x, y)
        return self.create_text(a, b, text=text, fill=color, font=self.fnt(size, weight), anchor=anchor, tags=tags)

    def poly(self, pts, **kw):
        flat = []
        for x, y in pts:
            flat += list(self.p(x, y))
        return self.create_polygon(flat, **kw)

    def line(self, pts, **kw):
        flat = []
        for x, y in pts:
            flat += list(self.p(x, y))
        return self.create_line(flat, **kw)

    # ---- public --------------------------------------------------------------------
    def set_floor(self, floor):
        if floor != self.floor:
            self.floor = floor
            self.selected = None
            self._invalidate()

    def select(self, slot_id):
        self.selected = slot_id
        self._invalidate()

    def _invalidate(self):
        self._sig = None

    def render(self, snap, sim):
        self._snap, self._sim = snap, sim
        w, h = self.winfo_width(), self.winfo_height()
        parked = tuple(sorted((v[0], v[7]) for v in sim["vehicles"] if v[8] == self.floor and v[7] in ("PARKED", "WAITING")))
        sig = (self.floor, w, h, snap["version"], sim["version"], self.selected, parked)
        if sig != self._sig:
            self._sig = sig
            self._fit()
            self.delete("static")
            self._draw_static(snap, sim)
        self.delete("dyn")
        self._draw_dynamic(snap, sim)
        self.tag_raise("dyn")

    # ---- static layer -----------------------------------------------------------------
    def _draw_static(self, snap, sim):
        floor = self.floor
        S = "static"
        # ground: public road + facility slab
        self.r(0, 28, L.GATE_X, 440, fill=ROAD, outline="", tags=S)
        self.r(L.GATE_X, 10, L.LW, 456, fill=FLOOR_BG, outline=WALL, width=2, tags=S)
        self.r(L.GATE_X, 158, L.LW, 312, fill=AISLE, outline="", tags=S)
        self.r(0, 176, L.GATE_X, 294, fill="#152036", outline="", tags=S)
        for y in (215.5, 254.5):                                   # lane dividers on the public road
            self.line([(0, y), (L.GATE_X - 4, y)], fill="#2B3C5C", dash=(8, 7), width=max(1, self.k), tags=S)
        self.line([(0, 176), (L.GATE_X - 4, 176)], fill="#3A4D74", width=max(1, 1.5 * self.k), tags=S)
        self.line([(0, 294), (L.GATE_X - 4, 294)], fill="#3A4D74", width=max(1, 1.5 * self.k), tags=S)
        # median between the two circulation lanes
        self.r(L.GATE_X + 70, 216, L.UTURN_X - 40, 254, fill="#0D1522", outline="#1C2942", tags=S)
        # lane arrows
        for x in range(L.GATE_X + 90, L.UTURN_X - 60, 110):
            self.line([(x - 6, L.LANE_Y["A"] - 6), (x + 4, L.LANE_Y["A"]), (x - 6, L.LANE_Y["A"] + 6)], fill=MARK, width=max(1, 2 * self.k), tags=S)
            self.line([(x + 6, L.LANE_Y["X"] - 6), (x - 4, L.LANE_Y["X"]), (x + 6, L.LANE_Y["X"] + 6)], fill=MARK, width=max(1, 2 * self.k), tags=S)
        for x in (24, 112, 152):
            for y in (L.LANE_Y["A"], L.LANE_Y["B"]):
                self.line([(x - 5, y - 5), (x + 3, y), (x - 5, y + 5)], fill=MARK, width=max(1, 2 * self.k), tags=S)
        self.line([(40, L.LANE_Y["X"]), (30, L.LANE_Y["X"] - 5)], fill=MARK, tags=S)
        for x in (150, 100, 50, 10):
            self.line([(x + 5, L.LANE_Y["X"] - 5), (x - 3, L.LANE_Y["X"]), (x + 5, L.LANE_Y["X"] + 5)], fill=MARK, width=max(1, 2 * self.k), tags=S)
        # U-turn arrows
        self.txt(L.UTURN_X + 2, 235, "U", 8, MARK)
        # entrance wall segments with gate booths
        self.r(L.GATE_X - 3, 12, L.GATE_X + 3, 176, fill=WALL, outline="", tags=S)
        self.r(L.GATE_X - 3, 294, L.GATE_X + 3, 454, fill=WALL, outline="", tags=S)
        for name in ("A", "B", "X"):
            y = L.LANE_Y[name]
            self.r(L.GATE_X - 9, y - 26, L.GATE_X + 9, y - 14, fill="#1C2A47", outline="#32456C", tags=S)
        # labels
        self.txt(10, 186, "ENTRY A", 7, T.CYAN, "w")
        self.txt(10, 245, "ENTRY B", 7, T.CYAN, "w")
        self.txt(10, 284, "EXIT", 7, T.AMBER, "w")
        for name, y in (("A", L.LANE_Y["A"]), ("B", L.LANE_Y["B"])):
            self.r(L.TICKET_X - 6, y - 26, L.TICKET_X + 6, y - 15, fill="#16325A", outline=T.BLUE, tags=S)
        self.txt(L.TICKET_X, L.LANE_Y["A"] - 33, "TICKET", 6, T.DIM)
        self.txt(L.TICKET_X, L.LANE_Y["B"] - 33 + 40, "", 6, T.DIM)
        # ramp zones
        up_txt, down_txt = ("TO F1/F2", "FROM F1/F2") if floor == "G" else ("FROM G", "TO G")
        self._ramp(L.RAMP_UP, up=True, label=up_txt)
        self._ramp(L.RAMP_DOWN, up=False, label=down_txt)
        # waiting area
        self.txt(134, 40, "WAITING AREA", 7, T.DIM)
        for i, (cx, cy) in enumerate(L.WAIT_CELLS):
            self.r(cx - 22, 52, cx + 22, 158, outline="#34476E", dash=(4, 3), fill="", tags=S)
            self.txt(cx, 150, f"W{i + 1}", 6, T.DIM)
        # bays
        self.bay_boxes = {}
        for n in range(1, SLOTS_PER_FLOOR + 1):
            self._bay(snap, f"{floor}-{n:02d}", n)
        # facility title
        self.txt(L.GATE_X + 14, 28, FLOOR_NAMES[floor].upper(), 12, T.TEXT, "w", weight="bold")
        occ = sum(1 for v in snap["slots"].values() if v["floor"] == floor and v["status"] in ("OCCUPIED", "INCOMING"))
        self.txt(L.GATE_X + 14 + 190, 28, f"{occ} / {SLOTS_PER_FLOOR} occupied", 9, T.MUTED, "w")
        # parked + waiting vehicles
        for reg, vt, color, x, y, hd, sc, st, fl, sid, slot in sim["vehicles"]:
            if fl == floor and st in ("PARKED", "WAITING"):
                px, py = self.p(x, y)
                draw_vehicle(self, px, py, hd, vt, color, self.k * sc, S)
                self._plate(reg, x, (y + 42 if hd < 0 else y - 42) if st == "PARKED" else y + 50, S)
        if floor == "G" and sim["waiting"] > 3:
            self.txt(134, 170, f"+{sim['waiting'] - 3} more", 7, T.AMBER)

    def _ramp(self, pos, up, label):
        x, y = pos
        S = "static"
        self.r(x - 24, y - 20, x + 24, y + 20, fill="#2A2412", outline=T.AMBER, tags=S)
        for i in range(-2, 3):
            self.line([(x + i * 10 - 6, y + 20), (x + i * 10 + 6, y - 20)], fill="#5A4A1E", width=max(1, self.k), tags=S)
        arrow = [(x - 6, y + 4), (x, y - 4), (x + 6, y + 4)] if up else [(x - 6, y - 4), (x, y + 4), (x + 6, y - 4)]
        self.line(arrow, fill=T.AMBER, width=max(1.5, 2 * self.k), tags=S)
        self.txt(x, y + (30 if up else -30), label, 6, T.AMBER)

    def _bay(self, snap, sid, n):
        d = snap["slots"][sid]
        x1, y1, x2, y2 = L.bay_rect(n)
        top = L.bay_row(n) == "top"
        st, cat = d["status"], d["category"]
        S = "static"
        self.r(x1, y1, x2, y2, fill=STATUS_FILL[st], outline=STATUS_EDGE[st], width=max(1, 1.8 * self.k),
               dash=(5, 3) if st == "INCOMING" else (), tags=S)
        if st == "RESERVED":
            self.r(x1 + 3, y1 + 3, x2 - 3, y2 - 3, outline="", fill="#5A4A1E", stipple="gray12", tags=S)
        # category stripe on the bay mouth
        my = y2 - 5 if top else y1
        self.r(x1 + 6, my, x2 - 6, my + 5, fill=CAT_STRIPE[cat], outline="", tags=S)
        # slot id (back wall side)
        self.txt(x1 + 8, y1 + 12 if top else y2 - 12, sid, 7, T.TEXT if st != "AVAILABLE" else T.MUTED, "w", weight="bold")
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if st in ("AVAILABLE", "RESERVED"):
            self._glyph(cat, cx, cy - 4, st)
            if st == "RESERVED":
                self.txt(cx, y2 - 22 if top else y1 + 22, d["reserved_for"], 6, T.AMBER)
                self.txt(cx, cy + 22, "RESERVED", 6, T.AMBER)
            else:
                self.txt(cx, cy + 22, {"GENERAL": "AVAILABLE", "ACCESSIBLE": "ACCESSIBLE"}.get(cat, cat), 6, "#3FBF8A")
        elif st == "INCOMING":
            self.txt(cx, cy, "INCOMING", 6, T.CYAN)
        self.bay_boxes[sid] = (x1, y1, x2, y2)

    def _glyph(self, cat, cx, cy, st):
        S = "static"
        col = {"EV": T.GREEN, "VIP": GOLD, "ACCESSIBLE": T.BLUE, "MOTO": T.PURPLE}.get(cat, "#2E4A56")
        if cat == "EV":
            self.poly([(cx + bx * 1.7, cy + by * 1.7) for bx, by in BOLT], fill=col, outline="", tags=S)
        elif cat == "VIP":
            pts = []
            for i in range(10):
                rr = 11 if i % 2 == 0 else 5
                a = -math.pi / 2 + i * math.pi / 5
                pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
            self.poly(pts, fill=col, outline="", tags=S)
        elif cat == "ACCESSIBLE":
            self.r(cx - 12, cy - 12, cx + 12, cy + 12, fill=col, outline="", tags=S)
            a, b = self.p(cx - 1, cy - 6)
            rr = 2.2 * self.k
            self.create_oval(a - rr, b - rr, a + rr, b + rr, fill="white", outline="", tags=S)
            self.line([(cx - 1, cy - 3), (cx - 1, cy + 2), (cx + 4, cy + 2)], fill="white", width=max(1, 1.8 * self.k), tags=S)
            a0, b0 = self.p(cx - 4, cy - 1)
            a1, b1 = self.p(cx + 5, cy + 9)
            self.create_arc(a0, b0, a1, b1, start=100, extent=210, style="arc", outline="white", width=max(1, 1.6 * self.k), tags=S)
        elif cat == "MOTO":
            for dx in (-7, 7):
                a, b = self.p(cx + dx, cy + 3)
                rr = 4.2 * self.k
                self.create_oval(a - rr, b - rr, a + rr, b + rr, outline=col, width=max(1, 1.8 * self.k), tags=S)
            self.line([(cx - 7, cy + 3), (cx - 1, cy - 4), (cx + 4, cy - 4), (cx + 7, cy + 3)], fill=col, width=max(1, 1.8 * self.k), tags=S)
        else:
            self.txt(cx, cy, "P", 14, "#2B4650")

    def _plate(self, text, x, y, tag):
        a, b = self.p(x, y)
        w = (len(text) * 4.6 + 8) * self.k
        h = 11 * self.k
        self.create_rectangle(a - w / 2, b - h / 2, a + w / 2, b + h / 2, fill="#0A101C", outline="#34476E", tags=tag)
        self.create_text(a, b, text=text, fill="#DCE6F5", font=self.fnt(6.5), tags=tag)

    # ---- dynamic layer -------------------------------------------------------------------------
    def _draw_dynamic(self, snap, sim):
        D = "dyn"
        # barriers
        for name, ang in sim["barriers"].items():
            y = L.LANE_Y[name]
            px, py = L.GATE_X, y - 19
            rad = math.radians(ang)
            ex, ey = px + 38 * math.cos(rad), py + 38 * math.sin(rad)
            self.line([(px, py), (ex, ey)], fill="#F2F4F8", width=max(2, 5 * self.k), capstyle="round", tags=D)
            self.line([(px, py), (ex, ey)], fill="#E5484D", width=max(2, 5 * self.k), dash=(5, 6), tags=D)
            opened = ang < 45
            a, b = self.p(px, py)
            rr = 3.6 * self.k
            self.create_oval(a - rr, b - rr, a + rr, b + rr, fill=T.GREEN if opened else T.RED, outline="#0A101C", tags=D)
        # moving vehicles
        n_floor = 0
        for reg, vt, color, x, y, hd, sc, st, fl, sid, slot in sim["vehicles"]:
            if fl != self.floor:
                continue
            n_floor += 1
            if st in ("PARKED", "WAITING"):
                continue
            px, py = self.p(x, y)
            draw_vehicle(self, px, py, hd, vt, color, self.k * sc, D)
            self._plate(reg, x, y - 28, D)
        # hover / selection outlines
        for sid, col, w in ((self.hover, "#9FB0CC", 2), (self.selected, T.CYAN, 3)):
            if sid and sid in self.bay_boxes:
                x1, y1, x2, y2 = self.bay_boxes[sid]
                self.r(x1 - 2, y1 - 2, x2 + 2, y2 + 2, outline=col, width=w * max(.8, self.k), tags=D)
        self.txt(L.LW - 16, 28, f"{n_floor} vehicles on this floor", 8, T.MUTED, "e", D)

    # ---- interaction --------------------------------------------------------------------------------
    def _bay_at(self, ex, ey):
        lx, ly = (ex - self.ox) / self.k, (ey - self.oy) / self.k
        for sid, (x1, y1, x2, y2) in self.bay_boxes.items():
            if x1 <= lx <= x2 and y1 <= ly <= y2:
                return sid
        return None

    def _motion(self, e):
        self._set_hover(self._bay_at(e.x, e.y))

    def _set_hover(self, sid):
        if sid != self.hover:
            self.hover = sid
            self.configure(cursor="hand2" if sid else "")

    def _click(self, e):
        sid = self._bay_at(e.x, e.y)
        if sid:
            self.selected = sid
            self._invalidate()
            if self.on_select:
                self.on_select(sid)
