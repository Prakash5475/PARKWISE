import tkinter as tk
import customtkinter as ctk

from config import FLOORS, FLOOR_NAMES, SLOTS_PER_FLOOR
from gui import theme as T
from gui.icons import icon
from gui.pages.base import Page
from gui.parking_map import ParkingMap
from gui.theme import font
from gui.widgets import Card, KPI, Gauge, StatusBar, button, card_title


class EventList(tk.Text):
    """Read-only coloured event list shared by Overview and Live Monitor."""
    def __init__(self, master, lines=12, **kw):
        super().__init__(master, bg=T.PANEL, fg=T.MUTED, relief="flat", highlightthickness=0, wrap="word",
                         font=T.tkfont_tuple(9), cursor="arrow", height=lines, padx=4, pady=2,
                         spacing1=3, spacing3=3, **kw)
        for cat, col in T.EVENT_COLORS.items():
            self.tag_configure(cat, foreground=col, font=T.tkfont_tuple(8, "bold"))
        self.tag_configure("ts", foreground=T.DIM, font=T.tkfont_tuple(8))
        self.tag_configure("msg", foreground="#C3CEE0")
        self.configure(state="disabled")
        self._last = None

    def set_events(self, events, limit=40):
        key = tuple((e["ts"], e["message"]) for e in events[:3])
        if key == self._last:
            return
        self._last = key
        self.configure(state="normal")
        self.delete("1.0", "end")
        if not events:
            self.insert("end", "No activity yet.", "ts")
        for e in events[:limit]:
            self.insert("end", e["ts"][11:] + "  ", "ts")
            self.insert("end", f"{e['category']:<10}", e["category"] if e["category"] in T.EVENT_COLORS else "msg")
            self.insert("end", e["message"] + "\n", "msg")
        self.configure(state="disabled")


class OverviewPage(Page):
    key, title = "overview", "Overview"
    subtitle = "Facility status at a glance"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure(tuple(range(5)), weight=1, uniform="k")
        specs = [("Total capacity", T.BLUE), ("Occupied", T.RED), ("Available", T.GREEN),
                 ("Occupancy", T.CYAN), ("Active sessions", T.PURPLE),
                 ("Vehicles entered", T.CYAN), ("Vehicles exited", T.MUTED), ("Revenue", T.AMBER),
                 ("Waiting queue", T.AMBER), ("Reserved bays", T.AMBER)]
        self.k = {}
        for i, (name, col) in enumerate(specs):
            kp = KPI(self, name, col)
            kp.grid(row=i // 5, column=i % 5, sticky="nsew", padx=(0 if i % 5 == 0 else 6, 0), pady=(0, 8))
            self.k[name] = kp

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=2, column=0, columnspan=5, sticky="nsew", pady=(4, 0))
        self.grid_rowconfigure(2, weight=1)
        body.grid_columnconfigure(0, weight=5, uniform="b")
        body.grid_columnconfigure(1, weight=4, uniform="b")
        body.grid_rowconfigure(0, weight=1)

        # ---- occupancy card
        occ = Card(body)
        occ.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        card_title(occ, "Parking occupancy", "Live utilisation by floor").pack(anchor="w", padx=18, pady=(16, 6))
        top = ctk.CTkFrame(occ, fg_color="transparent")
        top.pack(fill="x", padx=18)
        self.gauge = Gauge(top, 150)
        self.gauge.pack(side="left")
        leg = ctk.CTkFrame(top, fg_color="transparent")
        leg.pack(side="left", padx=22, fill="x", expand=True)
        self.legend = {}
        for name, col in (("Occupied", T.RED), ("Arriving", T.CYAN), ("Reserved", T.AMBER), ("Available", "#1F7A52")):
            row = ctk.CTkFrame(leg, fg_color="transparent")
            row.pack(fill="x", pady=4)
            ctk.CTkFrame(row, width=10, height=10, corner_radius=3, fg_color=col).pack(side="left")
            ctk.CTkLabel(row, text=name, font=font(12), text_color=T.MUTED).pack(side="left", padx=10)
            v = ctk.CTkLabel(row, text="0", font=font(13, "bold"), text_color=T.TEXT)
            v.pack(side="right")
            self.legend[name] = v
        self.floor_bars = {}
        for f in FLOORS:
            row = ctk.CTkFrame(occ, fg_color="transparent")
            row.pack(fill="x", padx=18, pady=(12, 0))
            ctk.CTkLabel(row, text=FLOOR_NAMES[f], font=font(12, "bold"), text_color=T.TEXT).pack(side="left")
            lab = ctk.CTkLabel(row, text="0 / 18", font=font(12), text_color=T.MUTED)
            lab.pack(side="right")
            bar = StatusBar(occ, height=10)
            bar.pack(fill="x", padx=18, pady=(5, 0))
            self.floor_bars[f] = (bar, lab)
        self.mini = ParkingMap(occ, on_click=self._open_bay, height=118)
        self.mini.pack(fill="x", padx=18, pady=(14, 6))
        ctk.CTkLabel(occ, text="Click a bay to inspect it in the Live Monitor", font=font(10), text_color=T.DIM).pack(anchor="w", padx=18, pady=(0, 10))

        # ---- right column
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)
        act = Card(right)
        act.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        card_title(act, "Quick actions").pack(anchor="w", padx=18, pady=(16, 8))
        r = ctk.CTkFrame(act, fg_color="transparent")
        r.pack(fill="x", padx=18, pady=(0, 16))
        button(r, "Open live monitor", lambda: app.show("monitor"), "primary", icon("monitor", 16, "#06222A")).pack(side="left", padx=(0, 8))
        button(r, "Register vehicle", lambda: app.show("manage"), "secondary", icon("plus", 16, T.TEXT)).pack(side="left", padx=(0, 8))
        button(r, "Tickets", lambda: app.show("tickets"), "secondary", icon("tickets", 16, T.TEXT)).pack(side="left")
        ev = Card(right)
        ev.grid(row=1, column=0, sticky="nsew")
        card_title(ev, "Recent activity", "Live event stream from all threads").pack(anchor="w", padx=18, pady=(16, 6))
        self.events = EventList(ev, lines=10)
        self.events.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    def _open_bay(self, sid):
        self.app.open_bay_in_monitor(sid)

    def update_data(self, s):
        k = self.k
        k["Total capacity"].set(s["total"], "bays on 3 floors")
        k["Occupied"].set(s["occupied"], f"{s['incoming']} arriving" if s["incoming"] else "parked now")
        k["Available"].set(s["available"], "ready to allocate")
        k["Occupancy"].set(f"{s['percent']:.0f}%", "of capacity")
        k["Active sessions"].set(s["active_sessions"], "open tickets")
        k["Vehicles entered"].set(s["entries"], "since reset")
        k["Vehicles exited"].set(s["exits"], "completed visits")
        k["Revenue"].set(f"\u20b9{s['revenue']:,.0f}", f"billing x{s['time_scale']:g}")
        k["Waiting queue"].set(len(s["queue"]), "vehicles waiting" if s["queue"] else "no queue")
        k["Reserved bays"].set(s["reserved"], "held for drivers")
        self.gauge.set(s["percent"])
        self.legend["Occupied"].configure(text=str(s["parked"]))
        self.legend["Arriving"].configure(text=str(s["incoming"]))
        self.legend["Reserved"].configure(text=str(s["reserved"]))
        self.legend["Available"].configure(text=str(s["available"]))
        for f, (bar, lab) in self.floor_bars.items():
            fl = s["floors"][f]
            bar.set(fl["occupied"], fl["incoming"], fl["reserved"], fl["available"])
            lab.configure(text=f"{fl['occupied'] + fl['incoming']} / {fl['total']}")
        self.mini.set_data(s["slots"])
        self.events.set_events(s["events"], 14)
