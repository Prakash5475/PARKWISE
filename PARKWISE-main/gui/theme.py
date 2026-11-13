"""Design tokens + font selection for the PARKWISE UI."""
import tkinter.font as tkfont
import customtkinter as ctk
from config import COLORS as C

BG, SIDEBAR, PANEL, PANEL2, LINE = C["bg"], C["sidebar"], C["panel"], C["panel2"], C["line"]
TEXT, MUTED, DIM = C["text"], C["muted"], C["dim"]
CYAN, BLUE, GREEN, RED, AMBER, PURPLE = C["cyan"], C["blue"], C["green"], C["red"], C["amber"], C["purple"]

STATUS_COLORS = {"AVAILABLE": GREEN, "OCCUPIED": RED, "RESERVED": AMBER, "INCOMING": CYAN}
TYPE_COLORS = {"CAR": BLUE, "BIKE": PURPLE, "EV": GREEN, "VIP": AMBER}
CATEGORY_COLORS = {"GENERAL": "#6B7A94", "EV": GREEN, "VIP": AMBER, "ACCESSIBLE": BLUE, "MOTO": PURPLE}
EVENT_COLORS = {"DETECT": CYAN, "GATE": BLUE, "ALLOC": GREEN, "ENTRY": CYAN, "PARKED": GREEN, "FULL": RED,
                "QUEUE": AMBER, "EXIT": MUTED, "PAYMENT": PURPLE, "CHECKOUT": AMBER, "RELEASE": GREEN,
                "RESERVE": AMBER, "SYSTEM": MUTED, "ERROR": RED}

_FONT_CACHE = {}
FAMILY = "Segoe UI"


def init_fonts():
    """Pick the best installed UI font (call after the root window exists)."""
    global FAMILY
    _FONT_CACHE.clear()                      # caches belong to one Tk root
    from gui import icons
    icons._CACHE.clear()
    have = set(tkfont.families())
    for fam in ("Inter", "SF Pro Display", "Segoe UI Variable Display", "Segoe UI", "Helvetica Neue",
                "Noto Sans", "DejaVu Sans", "Arial"):
        if fam in have:
            FAMILY = fam
            break


def font(size=13, weight="normal"):
    key = (FAMILY, size, weight)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ctk.CTkFont(family=FAMILY, size=size, weight=weight)
    return _FONT_CACHE[key]


def tkfont_tuple(size=10, weight="normal"):
    return (FAMILY, size, weight)


def fmt_duration(seconds):
    if seconds is None:
        return "-"
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def inr(v):
    return f"\u20b9{v:,.2f}"
