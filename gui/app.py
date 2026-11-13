"""PARKWISE main window: shell (sidebar + top bar), page routing, backend wiring.

Threading rule: worker threads never touch Tkinter. This window polls backend snapshots
with ``after()`` on the main thread only.
"""
import random
import time
from datetime import datetime

import customtkinter as ctk

from config import APP_NAME, DB_PATH, TRAFFIC_PROFILES, FLOOR_NAMES
from core.database import ParkingDatabase
from core.parking_manager import ParkingManager
from core.thread_manager import ThreadManager, TrafficControl
from gui import theme as T
from gui.icons import icon
from gui.theme import font
from gui.widgets import Toast, Pill, setup_tree_style, confirm
from simulation.traffic import random_spec
from simulation.vehicle_sim import VehicleSimulation

NAV = [("overview", "Overview", "dashboard"), ("monitor", "Live Monitor", "monitor"),
       ("manage", "Parking Management", "manage"), ("tickets", "Vehicles & Tickets", "tickets"),
       ("analytics", "Analytics", "analytics"), ("logs", "Activity Logs", "logs"),
       ("system", "System Monitor", "system")]


class SmartParkingApp(ctk.CTk):
    def __init__(self, db_path=DB_PATH, autostart=True):
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=T.BG)
        T.init_fonts()
        self.title(APP_NAME)
        self.geometry("1500x920")
        self.minsize(1240, 780)
        setup_tree_style(self)

        # ---- backend ----------------------------------------------------------------
        self.db = ParkingDatabase(db_path)
        self.manager = ParkingManager(self.db)
        self.traffic = TrafficControl(self.db.get_setting("auto_traffic", "1") == "1",
                                      self.db.get_setting("traffic_profile", "Normal"))
        self.sim = VehicleSimulation()
        self.threads = ThreadManager(self.manager, self.sim, self.traffic)
        snap = self.manager.snapshot()
        self.sim.restore([s.to_dict() for s in self.manager.sessions.values()], snap["queue"])
        self._snap, self._snap_t = snap, time.time()
        self.t_start = time.time()
        self.closing = False

        # ---- shell ------------------------------------------------------------------------
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        self._build_topbar(main)
        self.content = ctk.CTkFrame(main, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew", padx=26, pady=(8, 22))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.toast_box = Toast(self)

        from gui.pages.overview import OverviewPage
        from gui.pages.monitor import MonitorPage
        from gui.pages.management import ManagementPage
        from gui.pages.tickets import TicketsPage
        from gui.pages.analytics import AnalyticsPage
        from gui.pages.logs import LogsPage
        from gui.pages.system import SystemPage
        self.pages = {}
        for cls in (OverviewPage, MonitorPage, ManagementPage, TicketsPage, AnalyticsPage, LogsPage, SystemPage):
            pg = cls(self.content, self)
            pg.grid(row=0, column=0, sticky="nsew")
            self.pages[cls.key] = pg
        self.current = None
        self.show("overview")
        if autostart:
            self.threads.start_all()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._tick_id = self.after(500, self._tick)

    # ================================================================ shell
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=246, corner_radius=0, fg_color=T.SIDEBAR)
        sb.grid(row=0, column=0, sticky="ns")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(20, weight=1)
        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w", padx=22, pady=(26, 26))
        ctk.CTkLabel(brand, text="", image=icon("logo", 34, T.CYAN)).pack(side="left")
        col = ctk.CTkFrame(brand, fg_color="transparent")
        col.pack(side="left", padx=12)
        ctk.CTkLabel(col, text="PARKWISE", font=font(17, "bold"), text_color=T.TEXT).pack(anchor="w")
        ctk.CTkLabel(col, text="Smart parking platform", font=font(10), text_color=T.MUTED).pack(anchor="w")
        ctk.CTkLabel(sb, text="WORKSPACE", font=font(10, "bold"), text_color=T.DIM).grid(row=1, column=0, sticky="w", padx=26, pady=(0, 8))
        self.nav = {}
        for i, (key, label, ic) in enumerate(NAV):
            b = ctk.CTkButton(sb, text=label, image=icon(ic, 20, T.MUTED), compound="left", anchor="w",
                              height=44, corner_radius=10, fg_color="transparent", hover_color=T.C_HOVER if hasattr(T, "C_HOVER") else "#1A2640",
                              text_color=T.MUTED, font=font(13, "bold"), command=lambda k=key: self.show(k))
            b.grid(row=2 + i, column=0, sticky="ew", padx=14, pady=2)
            self.nav[key] = (b, ic)
        box = ctk.CTkFrame(sb, fg_color=T.PANEL, corner_radius=12, border_width=1, border_color=T.LINE)
        box.grid(row=21, column=0, sticky="ew", padx=14, pady=18)
        ctk.CTkLabel(box, text="SYSTEM STATUS", font=font(10, "bold"), text_color=T.DIM).pack(anchor="w", padx=14, pady=(12, 2))
        self.sys_pill = Pill(box, "STARTING", T.AMBER)
        self.sys_pill.pack(anchor="w", padx=12, pady=(2, 4))
        self.sys_label = ctk.CTkLabel(box, text="", font=font(11), text_color=T.MUTED, justify="left")
        self.sys_label.pack(anchor="w", padx=14, pady=(0, 12))

    def _build_topbar(self, parent):
        bar = ctk.CTkFrame(parent, height=78, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=26, pady=(18, 0))
        bar.grid_columnconfigure(0, weight=1)
        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")
        self.title_lbl = ctk.CTkLabel(left, text="", font=font(24, "bold"), text_color=T.TEXT)
        self.title_lbl.pack(anchor="w")
        self.sub_lbl = ctk.CTkLabel(left, text="", font=font(12), text_color=T.MUTED)
        self.sub_lbl.pack(anchor="w")
        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e")
        self.scale_pill = Pill(right, "", T.AMBER)
        self.scale_pill.pack(side="left", padx=(0, 16))
        from gui.widgets import switch
        self.auto_sw = switch(right, "Auto traffic", self._toggle_auto)
        self.auto_sw.pack(side="left", padx=(0, 20))
        if self.traffic.auto:
            self.auto_sw.select()
        self.clock = ctk.CTkLabel(right, text="", font=font(13, "bold"), text_color=T.TEXT, justify="right")
        self.clock.pack(side="left")

    # ================================================================ navigation
    def show(self, key):
        if self.current == key:
            return
        if self.current:
            self.pages[self.current].on_hide()
        self.current = key
        pg = self.pages[key]
        pg.tkraise()
        pg.on_show()
        self.title_lbl.configure(text=pg.title)
        self.sub_lbl.configure(text=pg.subtitle)
        for k, (b, ic) in self.nav.items():
            on = k == key
            b.configure(fg_color="#16325A" if on else "transparent", text_color=T.TEXT if on else T.MUTED,
                        image=icon(ic, 20, T.CYAN if on else T.MUTED))

    def open_bay_in_monitor(self, slot_id):
        self.show("monitor")
        self.pages["monitor"].focus_bay(slot_id)

    def open_reserve(self, slot_id):
        self.show("manage")
        self.pages["manage"].prefill_reserve(slot_id)

    # ================================================================ shared helpers
    def get_snapshot(self, max_age=0.0):
        """Cached backend snapshot (rebuilt when stale or the backend version changed)."""
        if (time.time() - self._snap_t > max_age and self._snap["version"] != self.manager.version) \
                or time.time() - self._snap_t > max(max_age, 1.0):
            self._snap, self._snap_t = self.manager.snapshot(), time.time()
        return self._snap

    def refresh_now(self):
        self._snap, self._snap_t = self.manager.snapshot(), time.time()
        if self.current:
            self.pages[self.current].update_data(self._snap)

    def toast(self, msg, kind="info"):
        self.toast_box.show(msg, kind)

    def confirm(self, title, message, confirm_text="Confirm", danger=False):
        return confirm(self, title, message, confirm_text, danger)

    def submit_vehicle(self, spec):
        """Register a vehicle with the backend and send it driving to its entry gate."""
        self.manager.register_arrival(spec)
        self.sim.spawn_arrival(spec)
        return spec

    def spawn_quick(self, vtype, stay=(35, 80)):
        spec = random_spec(self.manager._known_regs(), random.choice("AB"), vtype, stay, source="QUICK")
        self.submit_vehicle(spec)
        return spec

    def burst(self, n=12, stay=(100, 160)):
        """Stress test: send *n* vehicles to the gates a moment apart."""
        def go(i):
            if i >= n or self.closing:
                return
            try:
                spec = random_spec(self.manager._known_regs(), "AB"[i % 2], None, stay, source="QUICK")
                self.submit_vehicle(spec)
            except ValueError:
                pass
            self.after(900, lambda: go(i + 1))
        go(0)

    def _toggle_auto(self):
        self.traffic.auto = bool(self.auto_sw.get())
        self.db.set_setting("auto_traffic", int(self.traffic.auto))
        self.manager.log("SYSTEM", f"Automatic gate traffic {'enabled' if self.traffic.auto else 'disabled'}")

    def set_profile(self, name):
        self.traffic.profile = name
        self.db.set_setting("traffic_profile", name)
        self.manager.log("SYSTEM", f"Traffic profile set to {name}")

    def sync_auto_switch(self):
        (self.auto_sw.select if self.traffic.auto else self.auto_sw.deselect)()

    # ================================================================ periodic refresh (main thread)
    def _tick(self):
        if self.closing:
            return
        now = datetime.now()
        self.clock.configure(text=now.strftime("%I:%M:%S %p") + "\n" + now.strftime("%a, %d %b %Y"))
        snap = self.get_snapshot(0.0)
        self.scale_pill.set(f"Demo billing x{snap['time_scale']:g}" if snap["time_scale"] != 1 else "Real-time billing",
                            T.AMBER if snap["time_scale"] != 1 else T.GREEN)
        stats = self.threads.stats()
        running = sum(1 for t in stats if t["alive"])
        errs = sum(t["errors"] for t in stats)
        if running == len(stats) and not errs:
            self.sys_pill.set("ALL SYSTEMS OK", T.GREEN)
        elif running == 0:
            self.sys_pill.set("THREADS STOPPED", T.AMBER)
        else:
            self.sys_pill.set("DEGRADED" if errs else "PARTIAL", T.AMBER if not errs else T.RED)
        self.sys_label.configure(text=f"{running}/{len(stats)} threads running\n{snap['occupied']}/{snap['total']} bays in use")
        if self.current:
            try:
                self.pages[self.current].update_data(snap)
            except Exception as e:                      # a page bug must never kill the refresh loop
                self.manager.log("ERROR", f"UI refresh failed on {self.current}: {type(e).__name__}: {e}")
        self._tick_id = self.after(1000, self._tick)

    # ================================================================ shutdown
    def on_close(self):
        self.closing = True
        for job in (getattr(self, "_tick_id", None), getattr(self.toast_box, "_after", None)):
            if job:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
        if self.current:
            self.pages[self.current].on_hide()              # stops the monitor's animation timer
        survivors = self.threads.shutdown(3.0)          # signal events, join workers
        try:
            self.db.close()
        except Exception:
            pass
        self.destroy()
        self.survivors = survivors
