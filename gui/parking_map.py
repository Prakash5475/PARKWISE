"""Compact live bay map (3 floors x 18 bays) used on the Overview page.

Replaces the v1 emoji map with a clean, status-coloured grid; clicking a bay opens it
in the Live Monitor.
"""
import tkinter as tk
from config import FLOORS, FLOOR_NAMES, SLOTS_PER_FLOOR
from gui import theme as T

FILL = {"AVAILABLE": "#1F7A52", "OCCUPIED": T.RED, "RESERVED": T.AMBER, "INCOMING": T.CYAN}


class ParkingMap(tk.Canvas):
    def __init__(self, master, on_click=None, **kw):
        kw.setdefault("height", 118)
        super().__init__(master, bg=T.PANEL, highlightthickness=0, **kw)
        self.on_click, self.slots, self.boxes, self._sig = on_click, {}, {}, None
        self.bind("<Configure>", lambda e: self.draw(force=True))
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", lambda e: self.configure(cursor="hand2" if self._at(e) else ""))

    def set_data(self, slots):
        self.slots = slots
        self.draw()

    def draw(self, force=False):
        sig = tuple((k, v["status"]) for k, v in sorted(self.slots.items())) + (self.winfo_width(),)
        if sig == self._sig and not force:
            return
        self._sig = sig
        self.delete("all")
        w = max(self.winfo_width(), 300)
        left, gap = 112, 4
        cw = (w - left - 8 - gap * (SLOTS_PER_FLOOR - 1)) / SLOTS_PER_FLOOR
        ch, rowgap = 24, 14
        self.boxes = {}
        for fi, f in enumerate(FLOORS):
            y = 6 + fi * (ch + rowgap)
            self.create_text(0, y + ch / 2, text=FLOOR_NAMES[f], anchor="w", fill=T.MUTED, font=T.tkfont_tuple(9, "bold"))
            for i in range(SLOTS_PER_FLOOR):
                sid = f"{f}-{i + 1:02d}"
                d = self.slots.get(sid)
                x = left + i * (cw + gap)
                col = FILL.get(d["status"], "#1A2540") if d else "#1A2540"
                self.create_rectangle(x, y, x + cw, y + ch, fill=col, outline="", width=0)
                cat = d["category"] if d else ""
                if cat in ("EV", "VIP", "ACCESSIBLE", "MOTO"):
                    mark = {"EV": T.GREEN, "VIP": "#D4AF37", "ACCESSIBLE": T.BLUE, "MOTO": T.PURPLE}[cat]
                    self.create_rectangle(x, y + ch - 4, x + cw, y + ch, fill=mark, outline="")
                self.boxes[sid] = (x, y, x + cw, y + ch)

    def _at(self, e):
        for sid, (x1, y1, x2, y2) in self.boxes.items():
            if x1 <= e.x <= x2 and y1 <= e.y <= y2:
                return sid

    def _click(self, e):
        sid = self._at(e)
        if sid and self.on_click:
            self.on_click(sid)
