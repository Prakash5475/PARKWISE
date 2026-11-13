"""PARKWISE configuration — single source of truth for layout, pricing and theme.

Keys that existed in the original project (APP_NAME, COLORS, FLOORS, SLOTS_PER_FLOOR,
RATES, GRACE_MINUTES) are preserved; new settings are added below them.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "parking.db"
TICKET_DIR = DATA_DIR / "tickets"
RECEIPT_DIR = DATA_DIR / "receipts"
EXPORT_DIR = DATA_DIR / "exports"

APP_NAME = "PARKWISE | SMART PARKING CONTROL"
PRODUCT_NAME = "Parkwise"

# ---- Theme ---------------------------------------------------------------
COLORS = {
    # original keys (kept for backward compatibility)
    "bg": "#0A0F1A", "panel": "#111827", "panel2": "#161F31", "panel3": "#1C2740",
    "line": "#243049", "text": "#EEF3FA", "muted": "#8A9AB3", "cyan": "#29D3EC",
    "blue": "#3B82F6", "green": "#2FD27F", "yellow": "#F5B544", "red": "#F0616D",
    "purple": "#A78BFA",
    # new keys
    "sidebar": "#0C1322", "topbar": "#0C1322", "hover": "#1A2640", "active": "#16325A",
    "asphalt": "#0F1624", "lane": "#151E2F", "marking": "#3A4A68", "amber": "#F5B544",
    "dim": "#5C6B85",
}

# ---- Facility --------------------------------------------------------------
FLOORS = ("G", "1", "2")
FLOOR_NAMES = {"G": "Ground Floor", "1": "First Floor", "2": "Second Floor"}
SLOTS_PER_FLOOR = 18
# Bay number -> category. Bays 1-9 are the top row, 10-18 the bottom row.
SLOT_LAYOUT = {
    1: "ACCESSIBLE", 2: "ACCESSIBLE", 3: "VIP", 4: "VIP", 5: "EV", 6: "EV", 7: "EV",
    8: "GENERAL", 9: "GENERAL", 10: "MOTO", 11: "MOTO",
    12: "GENERAL", 13: "GENERAL", 14: "GENERAL", 15: "GENERAL", 16: "GENERAL",
    17: "GENERAL", 18: "GENERAL",
}
VEHICLE_TYPES = ("CAR", "BIKE", "EV", "VIP")
WAITING_CAPACITY = 3          # physical waiting-area cells outside the entry gate

# ---- Billing ---------------------------------------------------------------
RATES = {"CAR": 40, "BIKE": 20, "EV": 50, "VIP": 60}   # INR per hour
GRACE_MINUTES = 5            # parking up to this long is free
GST_PERCENT = 18.0
# Demo billing acceleration: 1 real second is billed as DEFAULT_TIME_SCALE seconds.
# 1 = real time. Changeable at runtime from System Monitor; persisted in the DB.
DEFAULT_TIME_SCALE = 60
TIME_SCALE_OPTIONS = (1, 10, 60, 240)

# ---- Traffic simulation ------------------------------------------------------
# profile -> (arrival interval range per gate [s], parking duration range [s])
TRAFFIC_PROFILES = {
    "Light": ((9.0, 15.0), (45, 110)),
    "Normal": ((5.0, 9.0), (30, 80)),
    "Rush hour": ((2.2, 4.0), (45, 120)),
}
TRAFFIC_MIX = {"CAR": 52, "BIKE": 20, "EV": 18, "VIP": 10}
