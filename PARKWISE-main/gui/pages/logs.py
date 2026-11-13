from tkinter import filedialog

import customtkinter as ctk

from gui import theme as T
from gui.icons import icon
from gui.pages.base import Page
from gui.theme import font
from gui.widgets import Table, button, entry, option, switch

CATS = ["ALL", "DETECT", "GATE", "ALLOC", "ENTRY", "PARKED", "FULL", "QUEUE", "CHECKOUT", "PAYMENT",
        "RELEASE", "EXIT", "RESERVE", "SYSTEM", "ERROR"]


class LogsPage(Page):
    key, title = "logs", "Activity Logs"
    subtitle = "Every system event, stored in SQLite and tagged with the thread that raised it"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.cat = option(bar, CATS, 150, command=lambda v: self.update_data(None))
        self.cat.pack(side="left")
        self.search = entry(bar, "Search messages", 280)
        self.search.pack(side="left", padx=10)
        self.search.bind("<KeyRelease>", lambda e: self.update_data(None))
        self.live = switch(bar, "Live updates")
        self.live.select()
        self.live.pack(side="left", padx=10)
        self.count = ctk.CTkLabel(bar, text="", font=font(11), text_color=T.MUTED)
        self.count.pack(side="left", padx=10)
        button(bar, "Export CSV", self._export, "secondary", icon("download", 16, T.TEXT)).pack(side="right")
        self.table = Table(self, [("time", "Time", 150, "w"), ("cat", "Event", 90, "w"), ("src", "Thread", 120, "w"), ("msg", "Message", 700, "w")],
                           "No events recorded yet")
        for k, c in T.EVENT_COLORS.items():
            self.table.tag_color(k, c)
        self.table.tree.column("msg", stretch=True)
        self.table.grid(row=1, column=0, sticky="nsew")

    def update_data(self, snap):
        if snap is not None and not self.live.get():
            return
        rows = self.app.manager.recent_events(400, self.cat.get(), self.search.get().strip())
        self.table.set_rows([(str(r["id"]), (r["ts"], r["category"], r["source"] or "", r["message"]), r["category"] if r["category"] in T.EVENT_COLORS else None) for r in rows])
        self.count.configure(text=f"{len(rows)} events shown")

    def _export(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="parkwise_events.csv")
        if path:
            try:
                self.app.manager.export_events_csv(path, self.cat.get(), self.search.get().strip())
                self.app.toast(f"Exported to {path}", "success")
            except OSError as e:
                self.app.toast(f"Export failed: {e}", "error")
