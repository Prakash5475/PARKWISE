import customtkinter as ctk

from config import FLOORS, FLOOR_NAMES, VEHICLE_TYPES, WAITING_CAPACITY
from core.models import VehicleSpec
from gui import theme as T
from gui.pages.base import Page
from gui.theme import font
from gui.widgets import (Card, Table, button, card_title, entry, option, segmented, field_label)
from simulation.traffic import pick_color
from simulation.vehicle_art import CAR_PALETTE

COLOR_NAMES = {"Red": "#D9434E", "Blue": "#3B7DDD", "White": "#E8EDF2", "Silver": "#AAB4C0",
               "Graphite": "#4B5563", "Yellow": "#E5B83A", "Teal": "#2FB7A6", "Orange": "#E0782F",
               "Green": "#3AA56A", "Purple": "#8B5CF6"}
DURATIONS = {"30 minutes": 30, "1 hour": 60, "2 hours": 120, "4 hours": 240, "No expiry": None}
AUTO = "Automatic (best match)"
_CATN = {"GENERAL": "General", "EV": "EV", "VIP": "VIP", "ACCESSIBLE": "Accessible", "MOTO": "Motorcycle"}


def _cat(c):
    return _CATN[c]


class ManagementPage(Page):
    key, title = "manage", "Parking Management"
    subtitle = "Register vehicles, assign or reserve bays, release bays and review availability"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._bay_sig = None

        col = ctk.CTkScrollableFrame(self, width=410, fg_color="transparent", scrollbar_button_color="#1E2A44",
                                     scrollbar_button_hover_color="#34476E")
        col.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        # ---------------- register & allocate
        c1 = Card(col)
        c1.pack(fill="x", pady=(0, 12))
        card_title(c1, "Register vehicle & allocate parking", "The vehicle drives to the gate and is allocated by the engine").pack(anchor="w", padx=18, pady=(16, 8))
        f = ctk.CTkFrame(c1, fg_color="transparent")
        f.pack(fill="x", padx=18)
        field_label(f, "Registration number").pack(anchor="w")
        self.reg = entry(f, "e.g. MH15AB1234", 370)
        self.reg.pack(anchor="w", pady=(3, 8))
        field_label(f, "Vehicle category").pack(anchor="w")
        self.vtype = segmented(f, list(VEHICLE_TYPES), command=lambda v: self._refresh_bay_options())
        self.vtype.set("CAR")
        self.vtype.pack(anchor="w", pady=(3, 8), fill="x")
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x")
        a = ctk.CTkFrame(row, fg_color="transparent")
        a.pack(side="left")
        field_label(a, "Colour").pack(anchor="w")
        self.color = option(a, ["Auto"] + list(COLOR_NAMES), 175)
        self.color.pack(pady=(3, 8))
        b = ctk.CTkFrame(row, fg_color="transparent")
        b.pack(side="right")
        field_label(b, "Entry gate").pack(anchor="w")
        self.gate = option(b, ["Gate A", "Gate B"], 175)
        self.gate.pack(pady=(3, 8))
        field_label(f, "Parking bay").pack(anchor="w")
        self.bay = option(f, [AUTO], 370)
        self.bay.pack(anchor="w", pady=(3, 8))
        self.permit = ctk.CTkCheckBox(f, text="Accessible parking permit holder", font=font(12), text_color=T.TEXT,
                                      fg_color=T.CYAN, hover_color="#5FE3F5", border_color=T.LINE,
                                      command=self._refresh_bay_options)
        self.permit.pack(anchor="w", pady=(2, 8))
        self.msg1 = ctk.CTkLabel(f, text="", font=font(11), text_color=T.RED, wraplength=370, justify="left")
        self.msg1.pack(anchor="w")
        button(f, "Register & send to gate", self._register_vehicle, "primary").pack(fill="x", pady=(4, 18))

        # ---------------- reserve
        c2 = Card(col)
        c2.pack(fill="x", pady=(0, 12))
        card_title(c2, "Reserve a bay", "Reserved bays are protected from other vehicles").pack(anchor="w", padx=18, pady=(16, 8))
        g = ctk.CTkFrame(c2, fg_color="transparent")
        g.pack(fill="x", padx=18)
        field_label(g, "Registration number").pack(anchor="w")
        self.r_reg = entry(g, "Vehicle that will use the bay", 370)
        self.r_reg.pack(anchor="w", pady=(3, 8))
        field_label(g, "Vehicle category").pack(anchor="w")
        self.r_type = segmented(g, list(VEHICLE_TYPES), command=lambda v: self._refresh_bay_options())
        self.r_type.set("CAR")
        self.r_type.pack(anchor="w", pady=(3, 8), fill="x")
        row = ctk.CTkFrame(g, fg_color="transparent")
        row.pack(fill="x")
        a = ctk.CTkFrame(row, fg_color="transparent")
        a.pack(side="left")
        field_label(a, "Bay").pack(anchor="w")
        self.r_bay = option(a, ["-"], 175)
        self.r_bay.pack(pady=(3, 8))
        b = ctk.CTkFrame(row, fg_color="transparent")
        b.pack(side="right")
        field_label(b, "Hold for").pack(anchor="w")
        self.r_dur = option(b, list(DURATIONS), 175)
        self.r_dur.set("1 hour")
        self.r_dur.pack(pady=(3, 8))
        self.r_permit = ctk.CTkCheckBox(g, text="Accessible parking permit holder", font=font(12), text_color=T.TEXT,
                                        fg_color=T.CYAN, hover_color="#5FE3F5", border_color=T.LINE,
                                        command=self._refresh_bay_options)
        self.r_permit.pack(anchor="w", pady=(2, 8))
        self.msg2 = ctk.CTkLabel(g, text="", font=font(11), text_color=T.RED, wraplength=370, justify="left")
        self.msg2.pack(anchor="w")
        button(g, "Reserve bay", self._reserve, "secondary").pack(fill="x", pady=(4, 18))

        # ---------------- release
        c3 = Card(col)
        c3.pack(fill="x")
        card_title(c3, "Release a bay", "Cancel a reservation or check out a parked vehicle").pack(anchor="w", padx=18, pady=(16, 8))
        h = ctk.CTkFrame(c3, fg_color="transparent")
        h.pack(fill="x", padx=18, pady=(0, 18))
        self.rel_bay = option(h, ["-"], 370)
        self.rel_bay.pack(anchor="w", pady=(0, 8))
        button(h, "Release bay", self._release, "danger").pack(fill="x")

        # ---------------- right: tabs
        right = Card(self)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(right, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        self.view = segmented(top, ["Parking bays", "Waiting queue"], command=lambda v: self._switch(v))
        self.view.set("Parking bays")
        self.view.pack(side="left")
        self.f_floor = option(top, ["All floors"] + [FLOOR_NAMES[f] for f in FLOORS], 150, command=lambda v: self._update_bays(force=True))
        self.f_status = option(top, ["All status", "AVAILABLE", "OCCUPIED", "RESERVED", "INCOMING"], 140, command=lambda v: self._update_bays(force=True))
        self.f_cat = option(top, ["All types", "GENERAL", "EV", "VIP", "ACCESSIBLE", "MOTO"], 140, command=lambda v: self._update_bays(force=True))
        for w in (self.f_cat, self.f_status, self.f_floor):
            w.pack(side="right", padx=4)
        self.summary = ctk.CTkLabel(right, text="", font=font(11), text_color=T.MUTED)
        self.summary.grid(row=2, column=0, sticky="w", padx=20, pady=(0, 12))
        body = ctk.CTkFrame(right, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=12)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        self.bays = Table(body, [("bay", "Bay", 80, "center"), ("floor", "Floor", 130, "w"), ("cat", "Category", 110, "w"),
                                 ("status", "Status", 110, "center"), ("veh", "Vehicle / reserved for", 190, "w"),
                                 ("detail", "Notes", 160, "w")], "No bays match the filters")
        for st, col_ in T.STATUS_COLORS.items():
            self.bays.tag_color(st, col_)
        self.bays.grid(row=0, column=0, sticky="nsew")
        self.queue_wrap = ctk.CTkFrame(body, fg_color="transparent")
        self.queue_wrap.grid_rowconfigure(0, weight=1)
        self.queue_wrap.grid_columnconfigure(0, weight=1)
        self.queue = Table(self.queue_wrap, [("pos", "#", 50, "center"), ("reg", "Vehicle", 160, "w"), ("type", "Type", 90, "center"),
                                              ("prio", "Priority", 90, "center"), ("since", "Waiting since", 160, "w")],
                           "The waiting queue is empty")
        self.queue.grid(row=0, column=0, sticky="nsew")
        qb = ctk.CTkFrame(self.queue_wrap, fg_color="transparent")
        qb.grid(row=1, column=0, sticky="ew", pady=(10, 4))
        button(qb, "Remove selected from queue", self._remove_queue, "danger").pack(side="left")
        ctk.CTkLabel(qb, text=f"Waiting area holds {WAITING_CAPACITY} vehicles. VIPs are served first, then first-come first-served.",
                     font=font(11), text_color=T.MUTED).pack(side="left", padx=14)
        self._refresh_bay_options()

    # ---- helpers ---------------------------------------------------------------------------------
    def _switch(self, v):
        if v == "Parking bays":
            self.queue_wrap.grid_forget()
            self.bays.grid(row=0, column=0, sticky="nsew")
        else:
            self.bays.grid_forget()
            self.queue_wrap.grid(row=0, column=0, sticky="nsew")

    def prefill_reserve(self, slot_id):
        self._refresh_bay_options()
        for opt in self.r_bay.cget("values"):
            if opt.startswith(slot_id):
                self.r_bay.set(opt)
        self.r_reg.focus_set()

    def _eligible(self, vtype, permit, reg=""):
        m = self.app.manager
        with m.lock:
            return m.engine.eligible_free_slots(vtype, permit, m.slots, reg)

    def _refresh_bay_options(self):
        cur = self.bay.get()
        slots = self._eligible(self.vtype.get(), bool(self.permit.get()))
        vals = [AUTO] + [f"{s.slot_id} - {_cat(s.category)}" for s in slots]
        self.bay.configure(values=vals)
        self.bay.set(cur if cur in vals else AUTO)
        cur = self.r_bay.get()
        free = [s for s in self._eligible(self.r_type.get(), bool(self.r_permit.get())) if s.status == "AVAILABLE"]
        vals = [f"{s.slot_id} - {_cat(s.category)}" for s in free] or ["No suitable bay free"]
        self.r_bay.configure(values=vals)
        self.r_bay.set(cur if cur in vals else vals[0])

    def _refresh_release_options(self, snap):
        vals = []
        for sid, d in sorted(snap["slots"].items()):
            if d["status"] == "RESERVED":
                vals.append(f"{sid} - reserved for {d['reserved_for']}")
            elif d["status"] == "OCCUPIED":
                vals.append(f"{sid} - occupied by {d['vehicle_number']}")
        vals = vals or ["Nothing to release"]
        cur = self.rel_bay.get()
        if tuple(vals) != tuple(self.rel_bay.cget("values")):
            self.rel_bay.configure(values=vals)
            self.rel_bay.set(cur if cur in vals else vals[0])

    # ---- actions ----------------------------------------------------------------------------------------
    def _register_vehicle(self):
        self.msg1.configure(text="")
        vt = self.vtype.get()
        color = COLOR_NAMES.get(self.color.get()) or pick_color(vt)
        pref = None if self.bay.get() == AUTO else self.bay.get().split(" ")[0]
        spec = VehicleSpec(self.reg.get(), vt, color, bool(self.permit.get()), pref,
                           self.gate.get().split()[-1], None, "MANUAL")
        try:
            self.app.submit_vehicle(spec)
        except ValueError as e:
            self.msg1.configure(text=str(e))
            return
        self.app.toast(f"{spec.reg} registered - driving to Gate {spec.gate}", "success")
        self.reg.delete(0, "end")
        self._refresh_bay_options()

    def _reserve(self):
        self.msg2.configure(text="")
        bay = self.r_bay.get()
        if bay.startswith("No suitable"):
            self.msg2.configure(text="No suitable bay is free for this vehicle category.")
            return
        try:
            self.app.manager.reserve(bay.split(" ")[0], self.r_reg.get(), self.r_type.get(),
                                     bool(self.r_permit.get()), DURATIONS[self.r_dur.get()])
        except ValueError as e:
            self.msg2.configure(text=str(e))
            return
        self.app.toast(f"Bay {bay.split(' ')[0]} reserved", "success")
        self.r_reg.delete(0, "end")
        self.app.refresh_now()
        self._refresh_bay_options()

    def _release(self):
        v = self.rel_bay.get()
        if v.startswith("Nothing"):
            self.app.toast("There is no reserved or occupied bay to release.", "warning")
            return
        sid = v.split(" ")[0]
        occupied = "occupied by" in v
        msg = (f"Check out the vehicle in bay {sid} and bill it now?" if occupied
               else f"Cancel the reservation on bay {sid}?")
        if not self.app.confirm("Release bay", msg, "Release", True):
            return
        try:
            what = self.app.manager.release_slot(sid)
        except ValueError as e:
            self.app.toast(str(e), "warning")
            return
        self.app.toast(f"Bay {sid}: {what}", "success")
        self.app.refresh_now()

    def _remove_queue(self):
        reg = self.queue.selected()
        if not reg:
            self.app.toast("Select a vehicle in the queue first.", "warning")
            return
        if self.app.confirm("Remove from queue", f"Remove {reg} from the waiting queue?", "Remove", True):
            try:
                self.app.manager.cancel_queue(reg)
            except ValueError as e:
                self.app.toast(str(e), "warning")

    # ---- refresh ----------------------------------------------------------------------------------------------
    def update_data(self, snap):
        self._update_bays(snap)
        rows = [(q["reg"], (i + 1, q["reg"], q["vtype"], "VIP" if q["priority"] else "Normal", q["enqueued_at"][11:]), None)
                for i, q in enumerate(snap["queue"])]
        self.queue.set_rows(rows)
        self._refresh_release_options(snap)
        sig = (snap["available"], snap["reserved"], snap["occupied"])
        if sig != self._bay_sig:
            self._bay_sig = sig
            self._refresh_bay_options()

    def _update_bays(self, snap=None, force=False):
        snap = snap or self.app.get_snapshot()
        ff, fs, fc = self.f_floor.get(), self.f_status.get(), self.f_cat.get()
        rows = []
        for sid, d in sorted(snap["slots"].items(), key=lambda kv: (FLOORS.index(kv[1]["floor"]), kv[1]["number"])):
            if ff != "All floors" and FLOOR_NAMES[d["floor"]] != ff:
                continue
            if fs != "All status" and d["status"] != fs:
                continue
            if fc != "All types" and d["category"] != fc:
                continue
            note = {"RESERVED": f"until {d['reserved_until'][11:]}" if d["reserved_until"] else "no expiry",
                    "INCOMING": "vehicle arriving"}.get(d["status"], "")
            CAT = {"GENERAL": "General", "EV": "EV", "VIP": "VIP", "ACCESSIBLE": "Accessible", "MOTO": "Motorcycle"}
            rows.append((sid, (sid, FLOOR_NAMES[d["floor"]], CAT[d["category"]], d["status"],
                               d["vehicle_number"] or d["reserved_for"] or "-", note), None if d["status"] == "AVAILABLE" else d["status"]))
        self.bays.set_rows(rows)
        self.summary.configure(text=f"{len(rows)} bays shown  |  {snap['available']} available, {snap['occupied']} occupied, {snap['reserved']} reserved")
