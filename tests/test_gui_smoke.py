"""GUI smoke tests. Need a display (on Linux CI run:  xvfb-run -a python -m unittest tests.test_gui_smoke)."""
import os
import time
import traceback
import unittest

from tests.helpers import tmp_db_path

HAS_DISPLAY = bool(os.environ.get("DISPLAY")) or os.name == "nt" or os.uname().sysname == "Darwin"


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.update_idletasks()
        app.update()
        time.sleep(0.02)


@unittest.skipUnless(HAS_DISPLAY, "no display available")
class GuiSmoke(unittest.TestCase):
    def make_app(self, path=None, autostart=True):
        from gui.app import SmartParkingApp
        app = SmartParkingApp(db_path=path or tmp_db_path(), autostart=autostart)
        self.errors = []
        app.report_callback_exception = lambda e, v, tb: self.errors.append("".join(traceback.format_exception(e, v, tb)))
        app.traffic.auto = False
        return app

    def test_every_page_opens_and_refreshes(self):
        app = self.make_app()
        try:
            for key in ("overview", "monitor", "manage", "tickets", "analytics", "logs", "system", "overview"):
                app.show(key)
                pump(app, 1.2)
                self.assertTrue(app.pages[key].visible)
            self.assertEqual(self.errors, [])
        finally:
            app.on_close()
        self.assertEqual(app.survivors, [])

    def test_register_vehicle_through_the_ui_and_checkout(self):
        app = self.make_app()
        try:
            app.show("manage")
            mg = app.pages["manage"]
            mg.reg.insert(0, "mh15 zz 4321")
            mg.vtype.set("EV")
            mg._register_vehicle()
            self.assertEqual(mg.msg1.cget("text"), "")
            mg.reg.insert(0, "MH15ZZ4321")
            mg._register_vehicle()                                   # duplicate -> inline error
            self.assertIn("already registered", mg.msg1.cget("text"))
            mg.reg.delete(0, "end")
            mg.reg.insert(0, "x")
            mg._register_vehicle()                                   # invalid -> inline error
            self.assertIn("4-12", mg.msg1.cget("text"))
            deadline = time.time() + 30
            while time.time() < deadline and app.manager.snapshot()["parked"] < 1:
                pump(app, 0.5)
            snap = app.manager.snapshot()
            self.assertEqual(snap["parked"], 1)
            slot = next(s for s in snap["slots"].values() if s["vehicle_number"] == "MH15ZZ4321")
            self.assertEqual(slot["category"], "EV")
            # reserve through the UI
            mg.r_reg.insert(0, "RESERVE001")
            mg.r_type.set("CAR")
            mg._refresh_bay_options()
            mg._reserve()
            self.assertEqual(mg.msg2.cget("text"), "")
            self.assertEqual(app.manager.snapshot()["reserved"], 1)
            # tickets page: select the session, show detail, generate PDFs, check out
            app.show("tickets")
            pump(app, 1.5)
            tk = app.pages["tickets"]
            tk.table.tree.selection_set(tk.table.tree.get_children()[0])
            pump(app, 0.5)
            self.assertNotEqual(tk.d_reg.cget("text"), "No selection")
            sess = tk._selected()
            from core import documents
            pdf = documents.ticket_pdf(sess)
            self.assertTrue(os.path.getsize(pdf) > 1000)
            app.confirm = lambda *a, **k: True                         # auto-accept dialogs in tests
            tk._checkout()
            deadline = time.time() + 60
            while time.time() < deadline and app.manager.snapshot()["exits"] < 1:
                pump(app, 0.5)
            snap = app.manager.snapshot()
            self.assertEqual((snap["exits"], snap["occupied"]), (1, 0))
            row = app.db.query("SELECT * FROM bills")[0]
            self.assertEqual(row["payment_status"], "PAID")
            self.assertTrue(os.path.exists(row["receipt_path"]))      # billing thread wrote the receipt PDF
            # release the reservation via the UI
            mg.rel_bay.configure(values=[f"{next(iter(app.manager.reservations))} - reserved for RESERVE001"])
            mg.rel_bay.set(mg.rel_bay.cget("values")[0])
            mg._release()
            self.assertEqual(app.manager.snapshot()["reserved"], 0)
            self.assertEqual(self.errors, [])
        finally:
            app.on_close()

    def test_live_monitor_bay_click_and_floor_switch(self):
        app = self.make_app()
        try:
            app.show("monitor")
            mon = app.pages["monitor"]
            pump(app, 1)
            mon.focus_bay("1-05")
            pump(app, 0.5)
            self.assertEqual(mon.floor_seg.get(), "First Floor")
            self.assertEqual(mon.d_title.cget("text"), "1-05")
            self.assertEqual(mon.d_status.cget("text").strip(), "AVAILABLE")
            self.assertEqual(self.errors, [])
        finally:
            app.on_close()

    def test_restart_keeps_data(self):
        path = tmp_db_path()
        app = self.make_app(path)
        app.submit_vehicle(__import__("core.models", fromlist=["VehicleSpec"]).VehicleSpec("RESTART0001", "VIP", "#15171C", gate="A"))
        deadline = time.time() + 30
        while time.time() < deadline and app.manager.snapshot()["parked"] < 1:
            pump(app, 0.5)
        entries = app.manager.snapshot()["entries"]
        events_before = len(app.manager.recent_events())
        app.on_close()
        self.assertEqual(app.survivors, [])
        app2 = self.make_app(path)
        try:
            pump(app2, 1.5)
            snap = app2.manager.snapshot()
            self.assertEqual((snap["parked"], snap["entries"]), (1, entries))
            self.assertGreaterEqual(len(app2.manager.recent_events()), events_before)
            veh = [v for v in app2.sim.snapshot()["vehicles"] if v[0] == "RESTART0001"]
            self.assertEqual(veh[0][7], "PARKED")                      # vehicle sprite is back in its bay
            self.assertEqual(self.errors, [])
        finally:
            app2.on_close()


if __name__ == "__main__":
    unittest.main()
