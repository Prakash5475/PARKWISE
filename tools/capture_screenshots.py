"""Run PARKWISE against a throw-away database, drive it through a realistic demo session
and save a screenshot of every page.   Linux:  xvfb-run -a -s "-screen 0 1920x1080x24" python tools/capture_screenshots.py
(on Windows/macOS just run it - it uses the real screen)."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import ImageGrab
from gui.app import SmartParkingApp

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
app = SmartParkingApp(db_path=tempfile.mkdtemp() + "/demo.db")
app.geometry("1500x920+0+0")
app.traffic.profile = "Rush hour"
app.traffic.auto = True
W, H = 1500, 920


def shot(name):
    app.update_idletasks()
    app.update()
    kw = {"xdisplay": os.environ["DISPLAY"]} if os.environ.get("DISPLAY") else {}
    ImageGrab.grab(**kw).crop((0, 0, W, H)).save(OUT / f"{name}.png")
    print("saved", name)


def select_row():
    tk = app.pages["tickets"]
    kids = tk.table.tree.get_children()
    if kids:
        tk.table.tree.selection_set(kids[min(2, len(kids) - 1)])


def reserve():
    try:
        app.manager.reserve("1-08", "VIPGUEST01", "CAR", False, 120)
        app.manager.reserve("2-12", "CORP0007", "CAR", False, None)
    except ValueError:
        pass


t0 = time.time()
plan = [
    (4, lambda: app.burst(10, (60, 110))),
    (20, reserve),
    (75, lambda: app.show("overview")), (78, lambda: shot("01_overview")),
    (80, lambda: app.show("monitor")), (84, lambda: app.pages["monitor"].focus_bay("G-05")), (88, lambda: shot("02_live_monitor_ground")),
    (89, lambda: app.pages["monitor"]._set_floor("1")), (92, lambda: app.pages["monitor"].focus_bay("1-08")), (95, lambda: shot("03_live_monitor_first_floor")),
    (96, lambda: app.show("manage")), (99, lambda: shot("04_parking_management")),
    (100, lambda: app.show("tickets")), (102, select_row), (104, lambda: shot("05_vehicles_tickets")),
    (150, lambda: app.show("analytics")), (156, lambda: shot("06_analytics")),
    (157, lambda: app.show("logs")), (160, lambda: shot("07_activity_logs")),
    (161, lambda: app.show("system")), (164, lambda: shot("08_system_monitoring")),
]
i = 0


def step():
    global i
    el = time.time() - t0
    while i < len(plan) and el >= plan[i][0]:
        plan[i][1]()
        i += 1
    if i >= len(plan):
        app.after(1500, app.on_close)
        return
    app.after(150, step)


app.after(100, step)
app.mainloop()
print("done")
