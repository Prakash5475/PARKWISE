import customtkinter as ctk

from config import FLOORS, FLOOR_NAMES
from core.documents import ticket_pdf, open_file
from gui import theme as T
from gui.facility_view import FacilityCanvas
from gui.pages.base import Page
from gui.pages.overview import EventList
from gui.theme import font, fmt_duration
from gui.widgets import Card, Pill, button, card_title, segmented, switch, field_label


class MonitorPage(Page):
    key, title = "monitor", "Live Parking Monitor"
    subtitle = "Real-time top-down view of the facility - vehicles, gates and bays"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._anim_id = None
        self._last_floor_seen = "G"
        self._detail_slot = None

        left = ctk.CTkFrame(self, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(left, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.floor_seg = segmented(head, [FLOOR_NAMES[f] for f in FLOORS], command=self._floor_changed)
        self.floor_seg.set(FLOOR_NAMES["G"])
        self.floor_seg.pack(side="left")
        self.floor_info = ctk.CTkLabel(head, text="", font=font(11), text_color=T.MUTED)
        self.floor_info.pack(side="left", padx=14)
        self.follow = switch(head, "Follow traffic")
        self.follow.pack(side="right", padx=(10, 0))
        for vt in ("VIP", "EV", "BIKE", "CAR"):
            button(head, f"+ {vt.title() if vt in ('CAR', 'BIKE') else vt}", lambda v=vt: self._quick(v), "secondary",
                   width=70, height=32).pack(side="right", padx=3)
        ctk.CTkLabel(head, text="Send vehicle:", font=font(11), text_color=T.MUTED).pack(side="right", padx=6)

        wrap = Card(left)
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        self.canvas = FacilityCanvas(wrap, on_select=self._bay_selected)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        foot = ctk.CTkFrame(wrap, fg_color="transparent")
        foot.grid(row=1, column=0, sticky="ew", padx=16, pady=(2, 12))
        for name, col in (("Available", "#23A06B"), ("Occupied", T.RED), ("Reserved", T.AMBER), ("Arriving", T.CYAN)):
            ctk.CTkFrame(foot, width=10, height=10, corner_radius=3, fg_color=col).pack(side="left", padx=(0, 5))
            ctk.CTkLabel(foot, text=name, font=font(11), text_color=T.MUTED).pack(side="left", padx=(0, 14))
        for name, col in (("EV", T.GREEN), ("VIP", "#D4AF37"), ("Accessible", T.BLUE), ("Motorcycle", T.PURPLE)):
            ctk.CTkFrame(foot, width=14, height=4, corner_radius=2, fg_color=col).pack(side="left", padx=(0, 5))
            ctk.CTkLabel(foot, text=name, font=font(11), text_color=T.MUTED).pack(side="left", padx=(0, 12))
        self.gate_pills = {}
        for g in ("X", "B", "A"):
            p = Pill(foot, "", T.MUTED)
            p.pack(side="right", padx=3)
            self.gate_pills[g] = p

        # ---- bottom row: bay details + live event stream (canvas gets the full width above)
        bottom = ctk.CTkFrame(left, fg_color="transparent", height=232)
        bottom.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        bottom.grid_propagate(False)
        bottom.grid_columnconfigure(0, weight=5, uniform="m")
        bottom.grid_columnconfigure(1, weight=4, uniform="m")
        bottom.grid_rowconfigure(0, weight=1)
        self.detail = Card(bottom)
        self.detail.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        h = ctk.CTkFrame(self.detail, fg_color="transparent")
        h.pack(fill="x", padx=18, pady=(14, 0))
        self.d_title = ctk.CTkLabel(h, text="Select a bay", font=font(22, "bold"), text_color=T.TEXT)
        self.d_title.pack(side="left")
        self.d_status = Pill(h, "", T.MUTED)
        self.d_status.pack(side="left", padx=12)
        ctk.CTkLabel(h, text="click any bay on the map", font=font(11), text_color=T.DIM).pack(side="right")
        self.d_rows = {}
        grid = ctk.CTkFrame(self.detail, fg_color="transparent")
        grid.pack(fill="x", padx=18, pady=(6, 0))
        for c in (1, 3):
            grid.grid_columnconfigure(c, weight=1, uniform="v")
        names = ("Slot ID", "Vehicle", "Floor", "Vehicle type", "Category", "Entry time", "Ticket ID", "Duration")
        for i, name in enumerate(names):
            r, c = i % 4, (i // 4) * 2
            ctk.CTkLabel(grid, text=name, font=font(11), text_color=T.MUTED, anchor="w").grid(row=r, column=c, sticky="w", pady=2, padx=(0, 10))
            v = ctk.CTkLabel(grid, text="-", font=font(12, "bold"), text_color=T.TEXT, anchor="w")
            v.grid(row=r, column=c + 1, sticky="w", pady=2, padx=(0, 20))
            self.d_rows[name] = v
        self.d_actions = ctk.CTkFrame(self.detail, fg_color="transparent")
        self.d_actions.pack(fill="x", padx=18, pady=(6, 12))
        self.d_btn1 = button(self.d_actions, "", None, "primary", height=32)
        self.d_btn2 = button(self.d_actions, "Ticket PDF", None, "secondary", height=32)

        ev = Card(bottom)
        ev.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        card_title(ev, "Live event stream", "Events from all threads").pack(anchor="w", padx=18, pady=(14, 2))
        self.events = EventList(ev, lines=8)
        self.events.pack(fill="both", expand=True, padx=12, pady=(0, 10))

    # ---- lifecycle -------------------------------------------------------------------------
    def on_show(self):
        super().on_show()
        self.canvas._invalidate()
        self._animate()

    def on_hide(self):
        super().on_hide()
        if self._anim_id:
            self.after_cancel(self._anim_id)
            self._anim_id = None

    def _animate(self):
        """~30 fps render loop; runs only while the page is visible (main thread)."""
        if not self.visible:
            return
        snap = self.app.get_snapshot(0.3)
        sim = self.app.sim.snapshot()
        if self.follow.get() and sim["last_floor"] != self._last_floor_seen:
            self._last_floor_seen = sim["last_floor"]
            self._set_floor(sim["last_floor"])
        self.canvas.render(snap, sim)
        for g, p in self.gate_pills.items():
            name = {"A": "Entry A", "B": "Entry B", "X": "Exit"}[g]
            t = {"A": self.app.threads.gate_a, "B": self.app.threads.gate_b, "X": self.app.threads.exit_gate}[g]
            if not t.alive:
                p.set(f"{name}: OFFLINE", T.RED)
            else:
                opened = sim["barriers"][g] < 45
                p.set(f"{name}: {'OPEN' if opened else 'CLOSED'}", T.GREEN if opened else T.MUTED)
        self._anim_id = self.after(33, self._animate)

    def update_data(self, snap):
        self.events.set_events(snap["events"], 40)
        fl = snap["floors"]
        pf = self.app.sim.snapshot()["per_floor"]
        self.floor_info.configure(text="   ".join(f"{f}: {fl[f]['occupied'] + fl[f]['incoming']}/18" for f in FLOORS)
                                  + f"    waiting: {len(snap['queue'])}")
        self._refresh_detail()

    # ---- floor / bay ------------------------------------------------------------------------------
    def _floor_changed(self, name):
        f = next(k for k, v in FLOOR_NAMES.items() if v == name)
        self.canvas.set_floor(f)

    def _set_floor(self, f):
        self.floor_seg.set(FLOOR_NAMES[f])
        self.canvas.set_floor(f)

    def focus_bay(self, slot_id):
        self._set_floor(slot_id.split("-")[0])
        self.canvas.select(slot_id)
        self._bay_selected(slot_id)

    def _bay_selected(self, sid):
        self._detail_slot = sid
        self._refresh_detail()

    def _quick(self, vtype):
        try:
            spec = self.app.spawn_quick(vtype)
            self.app.toast(f"{spec.reg} ({vtype}) is approaching Gate {spec.gate}", "info")
        except ValueError as e:
            self.app.toast(str(e), "warning")

    def _refresh_detail(self):
        sid = self._detail_slot
        if not sid:
            return
        d = self.app.manager.slot_detail(sid)
        self.d_title.configure(text=sid)
        self.d_status.set(d["status"], T.STATUS_COLORS[d["status"]])
        vals = {"Slot ID": sid, "Floor": FLOOR_NAMES[d["floor"]], "Category": {"GENERAL": "General", "EV": "EV", "VIP": "VIP", "ACCESSIBLE": "Accessible", "MOTO": "Motorcycle"}[d["category"]],
                "Vehicle": d["vehicle_number"] or d["reserved_for"] or "-", "Vehicle type": d["vehicle_type"] or "-",
                "Entry time": d["entry_time"][11:] if d["entry_time"] else "-", "Ticket ID": d["ticket_id"] or "-",
                "Duration": fmt_duration(d["duration_s"]) if d["duration_s"] is not None else "-"}
        for k, v in vals.items():
            if self.d_rows[k].cget("text") != v:
                self.d_rows[k].configure(text=v)
        for b in (self.d_btn1, self.d_btn2):
            b.pack_forget()
        if d["status"] == "OCCUPIED" and d["session_status"] == "PARKED":
            self.d_btn1.configure(text="Checkout vehicle", command=lambda: self._checkout(d["session_id"], d["vehicle_number"]), fg_color=T.CYAN)
            self.d_btn1.pack(side="left", padx=(0, 8))
        elif d["status"] == "RESERVED":
            self.d_btn1.configure(text="Release reservation", command=lambda: self._release(sid), fg_color="#3A1C25", text_color="#FF9AA3")
            self.d_btn1.pack(side="left", padx=(0, 8))
        elif d["status"] == "AVAILABLE":
            self.d_btn1.configure(text="Reserve this bay", command=lambda: self.app.open_reserve(sid), fg_color=T.CYAN, text_color="#06222A")
            self.d_btn1.pack(side="left", padx=(0, 8))
        if d["ticket_id"]:
            self.d_btn2.configure(command=lambda: self._ticket(d["ticket_id"]))
            self.d_btn2.pack(side="left")

    def _checkout(self, session_id, reg):
        if self.app.confirm("Check out vehicle", f"Process payment and send {reg} to the exit?", "Checkout"):
            try:
                self.app.manager.request_checkout(session_id, "UPI")
                self.app.toast(f"Checkout started for {reg}", "success")
            except ValueError as e:
                self.app.toast(str(e), "warning")

    def _release(self, sid):
        if self.app.confirm("Release reservation", f"Cancel the reservation on bay {sid}?", "Release", True):
            try:
                self.app.manager.release_slot(sid)
                self.app.toast(f"Bay {sid} released", "success")
            except ValueError as e:
                self.app.toast(str(e), "warning")

    def _ticket(self, ticket_id):
        rows = self.app.db.query("SELECT * FROM sessions WHERE ticket_id=?", (ticket_id,))
        if rows:
            open_file(ticket_pdf(rows[0]))
