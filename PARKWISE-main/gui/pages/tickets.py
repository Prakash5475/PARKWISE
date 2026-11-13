import os
from tkinter import filedialog

import customtkinter as ctk

from config import FLOOR_NAMES, RATES, GRACE_MINUTES, GST_PERCENT
from core import billing, documents
from core.parking_manager import parse
from gui import theme as T
from gui.icons import icon
from gui.pages.base import Page
from gui.theme import font, fmt_duration, inr
from gui.widgets import Card, Pill, Table, button, card_title, entry, option, segmented

PAY_COLORS = {"PAID": T.GREEN, "PROCESSING": T.AMBER, "UNPAID": T.MUTED}


class TicketsPage(Page):
    key, title = "tickets", "Vehicles & Tickets"
    subtitle = "Parking sessions, live fees, checkout, tickets and receipts"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._rows = {}
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self.search = entry(bar, "Search registration, ticket or bay", 290)
        self.search.pack(side="left")
        self.search.bind("<KeyRelease>", lambda e: self.update_data(None))
        self.status = segmented(bar, ["Active", "Completed", "All"], command=lambda v: self.update_data(None))
        self.status.set("Active")
        self.status.pack(side="left", padx=10)
        button(bar, "Export CSV", self._export, "secondary", icon("download", 16, T.TEXT)).pack(side="right")
        button(bar, "Refresh", lambda: self.update_data(None), "ghost", icon("refresh", 16, T.MUTED)).pack(side="right", padx=6)

        self.table = Table(self, [("ticket", "Ticket ID", 125, "w"), ("reg", "Registration", 120, "w"), ("type", "Type", 60, "center"),
                                  ("bay", "Bay", 56, "center"), ("entry", "Entry", 150, "w"), ("dur", "Duration", 92, "center"),
                                  ("state", "Status", 90, "center"), ("pay", "Payment", 100, "center"), ("fee", "Fee", 92, "e")],
                           "No sessions match - register a vehicle or wait for traffic")
        for k, c in PAY_COLORS.items():
            self.table.tag_color(k, c)
        self.table.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        self.table.tree.bind("<<TreeviewSelect>>", lambda e: self._show_detail())

        side = Card(self, width=350)
        side.grid(row=1, column=1, sticky="ns")
        side.grid_propagate(False)
        card_title(side, "Ticket & billing", "Select a session from the table").pack(anchor="w", padx=18, pady=(16, 8))
        self.d_reg = ctk.CTkLabel(side, text="-", font=font(24, "bold"), text_color=T.TEXT)
        self.d_reg.pack(anchor="w", padx=18)
        self.d_pill = Pill(side, "", T.MUTED)
        self.d_pill.pack(anchor="w", padx=16, pady=(4, 6))
        self.rows = {}
        grid = ctk.CTkFrame(side, fg_color="transparent")
        grid.pack(fill="x", padx=18)
        grid.grid_columnconfigure(1, weight=1)
        names = ["Ticket ID", "Vehicle type", "Bay", "Entry", "Parked for", "Billed duration", "Hourly rate",
                 "Billable hours", "Amount", f"GST ({GST_PERCENT:g}%)", "Total"]
        for i, n in enumerate(names):
            bold = n == "Total"
            ctk.CTkLabel(grid, text=n, font=font(12 if bold else 11, "bold" if bold else "normal"),
                         text_color=T.TEXT if bold else T.MUTED, anchor="w").grid(row=i, column=0, sticky="w", pady=3)
            v = ctk.CTkLabel(grid, text="-", font=font(15 if bold else 12, "bold"), text_color=T.CYAN if bold else T.TEXT, anchor="e")
            v.grid(row=i, column=1, sticky="e", pady=3)
            self.rows[n] = v
        self.note = ctk.CTkLabel(side, text="", font=font(10), text_color=T.DIM, wraplength=310, justify="left")
        self.note.pack(anchor="w", padx=18, pady=(8, 4))
        pr = ctk.CTkFrame(side, fg_color="transparent")
        pr.pack(fill="x", padx=18, pady=(4, 0))
        ctk.CTkLabel(pr, text="Payment method (simulated)", font=font(11), text_color=T.MUTED).pack(anchor="w")
        self.method = option(pr, ["UPI", "CARD", "CASH"], 310)
        self.method.pack(anchor="w", pady=(3, 8))
        self.btn_pay = button(pr, "Checkout & pay", self._checkout, "primary")
        self.btn_pay.pack(fill="x", pady=(0, 6))
        r2 = ctk.CTkFrame(pr, fg_color="transparent")
        r2.pack(fill="x")
        button(r2, "Ticket PDF", self._ticket, "secondary", icon("pdf", 16, T.TEXT)).pack(side="left", fill="x", expand=True, padx=(0, 4))
        button(r2, "Receipt PDF", self._receipt, "secondary", icon("pdf", 16, T.TEXT)).pack(side="left", fill="x", expand=True, padx=(4, 0))

    # ---- data --------------------------------------------------------------------------------------
    def update_data(self, snap):
        m = self.app.manager
        st = {"Active": "ACTIVE", "Completed": "COMPLETED", "All": "ALL"}[self.status.get()]
        sessions = m.list_sessions(st, self.search.get().strip(), 400)
        self._rows = {r["ticket_id"]: r for r in sessions}
        rows = []
        for r in sessions:
            if r["status"] == "COMPLETED" or r["payment_status"] == "PAID":
                fee = r["bill_total"] if r["bill_total"] is not None else r["amount"]
                fee_txt = inr(fee or 0)
            else:
                b = self._estimate(r)
                fee_txt = f"~{inr(b.total_amount)}"
            rows.append((r["ticket_id"], (r["ticket_id"], r["vehicle_number"], r["vehicle_type"], r["slot_id"],
                                           r["entry_time"], fmt_duration(r["duration_s"]), r["status"].title(),
                                           r["payment_status"], fee_txt), r["payment_status"]))
        self.table.set_rows(rows)
        self._show_detail()

    def _estimate(self, r):
        end = parse(r["checkout_time"]) if r["checkout_time"] else self.app.manager.now()
        return billing.calculate(r["vehicle_type"], parse(r["entry_time"]), end, self.app.manager.time_scale)

    def _selected(self):
        tid = self.table.selected()
        return self._rows.get(tid) if tid else None

    def _show_detail(self):
        r = self._selected()
        if not r:
            self.d_reg.configure(text="No selection")
            self.d_pill.set("SELECT A ROW", T.MUTED)
            for v in self.rows.values():
                v.configure(text="-")
            self.note.configure(text="")
            self.btn_pay.configure(state="disabled")
            return
        done = r["status"] == "COMPLETED" or r["payment_status"] == "PAID"
        if done and r["bill_total"] is not None:
            b = self.app.db.query("SELECT * FROM bills WHERE ticket_id=?", (r["ticket_id"],))[0]
            hrs, mins, base, tax, tot, rate, scale = (b["billed_hours"], b["billed_minutes"], b["base_amount"],
                                                       b["tax_amount"], b["total_amount"], b["rate"], b["time_scale"] or 1)
        else:
            bb = self._estimate(r)
            hrs, mins, base, tax, tot, rate, scale = (bb.billed_hours, bb.billed_minutes, bb.base_amount,
                                                      bb.tax_amount, bb.total_amount, bb.rate, bb.time_scale)
        self.d_reg.configure(text=r["vehicle_number"])
        self.d_pill.set(r["status"] if r["payment_status"] != "PAID" or r["status"] == "COMPLETED" else f"{r['status']} - PAID",
                        T.GREEN if done else T.AMBER)
        vals = {"Ticket ID": r["ticket_id"], "Vehicle type": r["vehicle_type"],
                "Bay": f"{r['slot_id']} ({FLOOR_NAMES[r['slot_id'].split('-')[0]]})", "Entry": r["entry_time"],
                "Parked for": fmt_duration(r["duration_s"]), "Billed duration": f"{mins} min",
                "Hourly rate": inr(rate), "Billable hours": str(hrs), "Amount": inr(base),
                f"GST ({GST_PERCENT:g}%)": inr(tax), "Total": inr(tot)}
        for k, v in vals.items():
            self.rows[k].configure(text=v)
        self.note.configure(text=(f"Grace period: {GRACE_MINUTES} min free. " +
                                  (f"Demo billing x{scale:g}: 1 real second counts as {scale:g} seconds." if scale != 1 else "Billed in real time.")
                                  + ("" if done else " Fee is a live estimate until checkout.")))
        self.btn_pay.configure(state="normal" if r["status"] == "PARKED" else "disabled")

    # ---- actions ---------------------------------------------------------------------------------------
    def _checkout(self):
        r = self._selected()
        if not r:
            return
        b = self._estimate(r)
        if not self.app.confirm("Checkout & pay", f"{r['vehicle_number']} - bay {r['slot_id']}\nAmount due: {inr(b.total_amount)} via {self.method.get()}\n"
                                "Payment is simulated; the vehicle will then drive to the exit.", "Pay & release"):
            return
        try:
            self.app.manager.request_checkout(r["session_id"], self.method.get())
            self.app.toast(f"Payment processing for {r['vehicle_number']}...", "info")
        except ValueError as e:
            self.app.toast(str(e), "warning")
        self.update_data(None)

    def _ticket(self):
        r = self._selected()
        if not r:
            self.app.toast("Select a session first.", "warning")
            return
        path = documents.ticket_pdf(r)
        self._opened(path)

    def _receipt(self):
        r = self._selected()
        if not r:
            self.app.toast("Select a session first.", "warning")
            return
        rows = self.app.db.query("SELECT * FROM bills WHERE ticket_id=? AND payment_status='PAID'", (r["ticket_id"],))
        if not rows:
            self.app.toast("No receipt yet - the session has not been paid.", "warning")
            return
        path = rows[0]["receipt_path"]
        if not path or not os.path.exists(path):
            path = documents.receipt_pdf(r, rows[0])
            self.app.manager.attach_receipt(r["ticket_id"], path)
        self._opened(path)

    def _opened(self, path):
        ok = documents.open_file(path)
        self.app.toast(("Opened " if ok else "Saved ") + os.path.basename(path) + f"  ({os.path.dirname(path)})", "success")

    def _export(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="parkwise_sessions.csv")
        if path:
            try:
                self.app.manager.export_csv(path)
                self.app.toast(f"Exported to {path}", "success")
            except OSError as e:
                self.app.toast(f"Export failed: {e}", "error")
