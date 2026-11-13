import time
from tkinter import filedialog

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from core.analytics import Analytics
from gui import charts
from gui import theme as T
from gui.icons import icon
from gui.pages.base import Page
from gui.theme import font, fmt_duration, inr
from gui.widgets import Card, KPI, button, option

RANGES = {"Last 15 minutes": 900, "Last hour": 3600, "Last 6 hours": 21600, "Last 24 hours": 86400,
          "Last 7 days": 604800, "All time": None}


class AnalyticsPage(Page):
    key, title = "analytics", "Traffic & Parking Analytics"
    subtitle = "Computed from the SQLite database - occupancy, traffic, revenue and durations"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.analytics = Analytics(app.db, app.manager.clock)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._last_draw = 0.0
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(bar, text="Time range", font=font(12), text_color=T.MUTED).pack(side="left", padx=(0, 8))
        self.range = option(bar, list(RANGES), 170, command=lambda v: self.draw(True))
        self.range.set("Last hour")
        self.range.pack(side="left")
        self.stamp = ctk.CTkLabel(bar, text="", font=font(11), text_color=T.DIM)
        self.stamp.pack(side="left", padx=14)
        button(bar, "Export CSV", self._export, "secondary", icon("download", 16, T.TEXT)).pack(side="right")
        button(bar, "Refresh", lambda: self.draw(True), "ghost", icon("refresh", 16, T.MUTED)).pack(side="right", padx=6)

        k = ctk.CTkFrame(self, fg_color="transparent")
        k.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        k.grid_columnconfigure(tuple(range(5)), weight=1, uniform="a")
        self.k = {}
        for i, (n, c) in enumerate((("Entries", T.CYAN), ("Exits", T.AMBER), ("Revenue", T.PURPLE),
                                    ("Avg. duration", T.GREEN), ("Peak hour", T.BLUE))):
            w = KPI(k, n, c)
            w.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0))
            self.k[n] = w

        card = Card(self)
        card.grid(row=2, column=0, sticky="nsew")
        self.fig = charts.new_figure()
        self.canvas = FigureCanvasTkAgg(self.fig, master=card)
        self.canvas.get_tk_widget().configure(bg=T.BG, highlightthickness=0)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=6)

    def on_show(self):
        self.visible = True
        self.draw(True)

    def update_data(self, snap):
        if time.time() - self._last_draw > 5:       # charts are re-queried every 5 s while visible
            self.draw()

    def draw(self, force=False):
        if not self.visible:
            return
        self._last_draw = time.time()
        sec = RANGES[self.range.get()]
        a = self.analytics
        k = a.kpis(sec)
        avg, per = a.avg_duration(sec)
        data = {"trend": a.occupancy_trend(sec), "dist": a.category_distribution(sec), "floors": a.floor_occupancy(),
                "flow": a.entries_exits(sec), "revenue": a.revenue_trend(sec), "peaks": a.peak_hours(sec),
                "avgdur": per, "span": sec}
        self.k["Entries"].set(k["entries"], self.range.get().lower())
        self.k["Exits"].set(k["exits"], "vehicles left")
        self.k["Revenue"].set(inr(k["revenue"]), "incl. GST")
        self.k["Avg. duration"].set(fmt_duration(avg) if avg else "-", "real parking time")
        self.k["Peak hour"].set(f"{k['peak_hour']:02d}:00" if k["peak_hour"] is not None else "-", "most entries")
        charts.draw_dashboard(self.fig, data)
        self.canvas.draw_idle()
        self.stamp.configure(text="updated " + time.strftime("%H:%M:%S"))

    def _export(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="parkwise_history.csv")
        if path:
            try:
                self.app.manager.export_csv(path)
                self.app.toast(f"Exported to {path}", "success")
            except OSError as e:
                self.app.toast(f"Export failed: {e}", "error")
