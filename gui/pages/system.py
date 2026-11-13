import os
import threading
import time

import customtkinter as ctk

from config import TRAFFIC_PROFILES, TIME_SCALE_OPTIONS
from gui import theme as T
from gui.icons import icon
from gui.pages.base import Page
from gui.theme import font
from gui.widgets import Card, Pill, button, card_title, option, switch, field_label

STATE_COL = {"RUNNING": T.GREEN, "STARTING": T.AMBER, "STOPPED": T.MUTED, "ERROR": T.RED}


class SystemPage(Page):
    key, title = "system", "System Monitoring"
    subtitle = "Worker threads, message queues, lock contention and runtime controls - all live values"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        left = ctk.CTkScrollableFrame(self, fg_color=T.PANEL, corner_radius=14, border_width=1, border_color=T.LINE,
                                      scrollbar_button_color="#1E2A44", scrollbar_button_hover_color="#34476E")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        head = ctk.CTkFrame(left, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(16, 6))
        card_title(head, "Worker threads", "threading.Thread + threading.Event shutdown").pack(side="left")
        button(head, "Stop all", self._stop_all, "danger", icon("stop", 14, "#FF9AA3"), width=100, height=32).pack(side="right")
        button(head, "Start all", self._start_all, "success", icon("play", 14, "#7BE8B2"), width=100, height=32).pack(side="right", padx=6)
        self.rows = {}
        for i, t in enumerate(app.threads.threads, 1):
            row = ctk.CTkFrame(left, fg_color="#0F1829", corner_radius=12)
            row.pack(fill="x", padx=14, pady=5)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=f"Thread {i}", font=font(10, "bold"), text_color=T.DIM).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 0))
            ctk.CTkLabel(row, text=t.name, font=font(14, "bold"), text_color=T.TEXT).grid(row=1, column=0, sticky="w", padx=14)
            pill = Pill(row, "", T.MUTED)
            pill.grid(row=0, column=1, rowspan=2, sticky="e", padx=(0, 6))
            btn = button(row, "", None, "secondary", width=74, height=30)
            btn.grid(row=0, column=2, rowspan=2, padx=(0, 12))
            ctk.CTkLabel(row, text=t.role, font=font(11), text_color=T.MUTED, anchor="w", wraplength=520, justify="left").grid(
                row=2, column=0, columnspan=3, sticky="w", padx=14)
            info = ctk.CTkLabel(row, text="", font=font(11), text_color="#B7C4DA", anchor="w")
            info.grid(row=3, column=0, columnspan=3, sticky="w", padx=14, pady=(2, 10))
            self.rows[t.name] = (pill, btn, info)

        right = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color="#1E2A44",
                                       scrollbar_button_hover_color="#34476E")
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        c = Card(right)
        c.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        card_title(c, "Runtime controls").pack(anchor="w", padx=18, pady=(16, 8))
        g = ctk.CTkFrame(c, fg_color="transparent")
        g.pack(fill="x", padx=18, pady=(0, 16))
        self.auto = switch(g, "Automatic gate traffic", self._toggle_auto)
        self.auto.pack(anchor="w", pady=(0, 10))
        field_label(g, "Traffic profile").pack(anchor="w")
        self.profile = option(g, list(TRAFFIC_PROFILES), 300, command=app.set_profile)
        self.profile.set(app.traffic.profile)
        self.profile.pack(anchor="w", pady=(3, 10))
        field_label(g, "Demo billing time-scale (1 real second = N billed seconds)").pack(anchor="w")
        self.scale = option(g, [f"x{v}" + ("  (real time)" if v == 1 else "") for v in TIME_SCALE_OPTIONS], 300, command=self._scale)
        self.scale.set(next(o for o in self.scale.cget("values") if o.split()[0] == f"x{int(app.manager.time_scale)}") if any(o.split()[0] == f"x{int(app.manager.time_scale)}" for o in self.scale.cget("values")) else self.scale.cget("values")[0])
        self.scale.pack(anchor="w", pady=(3, 10))
        r = ctk.CTkFrame(g, fg_color="transparent")
        r.pack(fill="x")
        button(r, "Stress test: 12 vehicles", lambda: app.burst(12), "secondary").pack(side="left", fill="x", expand=True, padx=(0, 4))
        button(r, "Reset all data", self._reset, "danger").pack(side="left", fill="x", expand=True, padx=(4, 0))

        self.stat_labels = {}
        for title, keys in (("Message queues", ["Gate A inbox", "Gate B inbox", "Exit inbox", "Billing queue"]),
                            ("Lock contention (ParkingManager)", ["Acquisitions", "Contended", "Max wait"]),
                            ("Simulation & database", ["Vehicles in simulation", "Simulation steps", "Active Python threads", "Database file", "Integrity check", "Uptime"])):
            card = Card(right)
            card.grid(sticky="ew", pady=(0, 12), column=0)
            card_title(card, title).pack(anchor="w", padx=18, pady=(14, 4))
            grid = ctk.CTkFrame(card, fg_color="transparent")
            grid.pack(fill="x", padx=18, pady=(0, 12))
            grid.grid_columnconfigure(1, weight=1)
            for i, k in enumerate(keys):
                ctk.CTkLabel(grid, text=k, font=font(11), text_color=T.MUTED, anchor="w").grid(row=i, column=0, sticky="w", pady=2)
                v = ctk.CTkLabel(grid, text="-", font=font(12, "bold"), text_color=T.TEXT, anchor="e")
                v.grid(row=i, column=1, sticky="e", pady=2)
                self.stat_labels[k] = v

    # ---- actions -----------------------------------------------------------------------------------
    def _toggle(self, name):
        t = self.app.threads.by_name(name)
        if t.alive:
            if t.stop(2.5):
                self.app.manager.log("SYSTEM", f"Thread {name} stopped by operator")
        else:
            t.start()
            self.app.manager.log("SYSTEM", f"Thread {name} started by operator")

    def _start_all(self):
        for t in self.app.threads.threads:
            t.start()
        self.app.manager.log("SYSTEM", "All worker threads started by operator")

    def _stop_all(self):
        if self.app.confirm("Stop all threads", "Vehicles will stop moving and gates will go offline until the threads are restarted.", "Stop all", True):
            alive = self.app.threads.stop_all(3.0)
            self.app.manager.log("SYSTEM", "All worker threads stopped by operator" + (f" (still alive: {alive})" if alive else ""))

    def _toggle_auto(self):
        self.app.traffic.auto = bool(self.auto.get())
        self.app.db.set_setting("auto_traffic", int(self.app.traffic.auto))
        self.app.sync_auto_switch()

    def _scale(self, v):
        self.app.manager.set_time_scale(float(v.split()[0][1:]))

    def _reset(self):
        if self.app.confirm("Reset all data", "This permanently deletes all sessions, tickets, bills, reservations and logs and clears the garage.", "Reset everything", True):
            self.app.sim.clear()
            self.app.manager.reset_all()
            self.app.toast("All parking data was reset.", "success")

    # ---- refresh --------------------------------------------------------------------------------------------
    def update_data(self, snap):
        app = self.app
        for st in app.threads.stats():
            pill, btn, info = self.rows[st["name"]]
            state = st["state"]
            pill.set(state, STATE_COL.get(state, T.MUTED))
            btn.configure(text="Stop" if st["alive"] else "Start", command=lambda n=st["name"]: self._toggle(n))
            hb = f"{st['heartbeat_age']:.1f}s ago" if st["alive"] and st["heartbeat_age"] is not None else "-"
            info.configure(text=f"id {st['ident'] or '-'}   |   loops {st['iterations']:,}   |   handled {st['processed']:,}   |   errors {st['errors']}   |   heartbeat {hb}   |   {st['detail']}"
                                + (f"\nlast error: {st['last_error']}" if st["last_error"] else ""))
        for k, v in app.threads.queue_sizes().items():
            self.stat_labels[k].configure(text=str(v))
        ls = app.manager.lock.stats()
        self.stat_labels["Acquisitions"].configure(text=f"{ls['acquisitions']:,}")
        self.stat_labels["Contended"].configure(text=f"{ls['contended']:,}")
        self.stat_labels["Max wait"].configure(text=f"{ls['max_wait_ms']} ms")
        ss = app.sim.snapshot()
        self.stat_labels["Vehicles in simulation"].configure(text=f"{len(ss['vehicles'])}  ({ss['moving']} moving)")
        self.stat_labels["Simulation steps"].configure(text=f"{ss['steps']:,}")
        self.stat_labels["Active Python threads"].configure(text=str(threading.active_count()))
        try:
            size = os.path.getsize(app.db.path) / 1024
            self.stat_labels["Database file"].configure(text=f"{os.path.basename(app.db.path)}  ({size:,.0f} KB)")
        except OSError:
            self.stat_labels["Database file"].configure(text=os.path.basename(app.db.path))
        problems = app.manager.verify_integrity()
        self.stat_labels["Integrity check"].configure(text="OK" if not problems else problems[0], text_color=T.GREEN if not problems else T.RED)
        up = int(time.time() - app.t_start)
        self.stat_labels["Uptime"].configure(text=f"{up // 3600:02d}:{up % 3600 // 60:02d}:{up % 60:02d}")
        if bool(self.auto.get()) != app.traffic.auto:
            (self.auto.select if app.traffic.auto else self.auto.deselect)()
