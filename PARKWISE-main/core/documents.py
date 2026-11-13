"""Printable PDF tickets and receipts (ReportLab).  Payment is simulated."""
import os
import subprocess
import sys
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A6
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from config import TICKET_DIR, RECEIPT_DIR, FLOOR_NAMES

NAVY, CYAN, INK, MUTED = HexColor("#0C1322"), HexColor("#17B6D0"), HexColor("#1B2333"), HexColor("#6B7A94")


def _dur(seconds):
    s = int(seconds or 0)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _frame(c, title, subtitle):
    w, h = A6
    c.setFillColor(NAVY)
    c.rect(0, h - 28 * mm, w, 28 * mm, stroke=0, fill=1)
    c.setFillColor(CYAN)
    c.roundRect(8 * mm, h - 19 * mm, 9 * mm, 9 * mm, 2 * mm, stroke=0, fill=1)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(12.5 * mm, h - 16.2 * mm, "P")
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, h - 14 * mm, "PARKWISE")
    c.setFont("Helvetica", 7.5)
    c.setFillColor(HexColor("#9FB0CC"))
    c.drawString(20 * mm, h - 19 * mm, "Smart Parking Management")
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(8 * mm, h - 37 * mm, title)
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTED)
    c.drawString(8 * mm, h - 42 * mm, subtitle)


def _rows(c, y, rows, w):
    for k, v in rows:
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 8)
        c.drawString(8 * mm, y, k)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawRightString(w - 8 * mm, y, str(v))
        c.setStrokeColor(HexColor("#E3E8F0"))
        c.line(8 * mm, y - 2 * mm, w - 8 * mm, y - 2 * mm)
        y -= 7 * mm
    return y


def _qr(c, text, x, y, size):
    widget = QrCodeWidget(text)
    b = widget.getBounds()
    d = Drawing(size, size, transform=[size / (b[2] - b[0]), 0, 0, size / (b[3] - b[1]), 0, 0])
    d.add(widget)
    renderPDF.draw(d, c, x, y)


def ticket_pdf(session, out_dir=TICKET_DIR):
    """Entry ticket. *session* is a dict from ParkingManager.list_sessions / Session.to_dict()."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    path = Path(out_dir) / f"{session['ticket_id']}.pdf"
    w, h = A6
    c = canvas.Canvas(str(path), pagesize=A6)
    c.setTitle(f"Parking ticket {session['ticket_id']}")
    _frame(c, "PARKING TICKET", "Keep this ticket until you leave the facility")
    floor = FLOOR_NAMES.get(session["slot_id"].split("-")[0], "")
    y = h - 52 * mm
    c.setFont("Helvetica-Bold", 22)
    c.setFillColor(INK)
    c.drawString(8 * mm, y, session["vehicle_number"])
    y -= 9 * mm
    y = _rows(c, y, [("Ticket ID", session["ticket_id"]), ("Vehicle type", session["vehicle_type"]),
                     ("Parking bay", f"{session['slot_id']}  ({floor})"),
                     ("Entry gate", f"Gate {session['gate']}"), ("Entry time", session["entry_time"]),
                     ("Rate", f"INR {session.get('rate', '')} / hour"), ("Grace period", "5 minutes")], w)
    _qr(c, session["ticket_id"], w / 2 - 14 * mm, 14 * mm, 28 * mm)
    c.setFont("Helvetica", 6.5)
    c.setFillColor(MUTED)
    c.drawCentredString(w / 2, 9 * mm, "Simulated ticket - educational project, not a legal receipt")
    c.save()
    return str(path)


def receipt_pdf(session, bill, out_dir=RECEIPT_DIR):
    """Payment receipt. *bill* is a row from the ``bills`` table."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    path = Path(out_dir) / f"{session['ticket_id']}.pdf"
    w, h = A6
    c = canvas.Canvas(str(path), pagesize=A6)
    c.setTitle(f"Receipt {session['ticket_id']}")
    _frame(c, "PAYMENT RECEIPT", "Simulated payment - no real money was charged")
    y = h - 52 * mm
    c.setFont("Helvetica-Bold", 18)
    c.setFillColor(INK)
    c.drawString(8 * mm, y, session["vehicle_number"])
    y -= 8 * mm
    scale = bill.get("time_scale") or 1
    rows = [("Ticket ID", session["ticket_id"]), ("Bay", session["slot_id"]),
            ("Entry", session["entry_time"]), ("Checkout", session.get("checkout_time") or ""),
            ("Parked (real)", _dur(bill["duration_s"])),
            ("Billed duration", f"{bill['billed_minutes']} min" + (f"  (demo x{scale:g})" if scale != 1 else "")),
            ("Billable hours", bill["billed_hours"]), ("Hourly rate", f"INR {bill['rate']:.2f}"),
            ("Amount", f"INR {bill['base_amount']:.2f}"), ("GST", f"INR {bill['tax_amount']:.2f}")]
    y = _rows(c, y, rows, w)
    c.setFillColor(NAVY)
    c.roundRect(8 * mm, y - 9 * mm, w - 16 * mm, 11 * mm, 2 * mm, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(11 * mm, y - 5.4 * mm, "TOTAL PAID")
    c.drawRightString(w - 11 * mm, y - 5.4 * mm, f"INR {bill['total_amount']:.2f}")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7)
    c.drawCentredString(w / 2, y - 16 * mm, f"Paid via {bill.get('payment_method') or '-'}  |  {bill.get('paid_at') or ''}")
    c.save()
    return str(path)


def open_file(path):
    """Open a file with the OS default application (lets the user print it)."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)                                  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False
