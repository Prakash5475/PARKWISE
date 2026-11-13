"""PARKWISE - Smart Parking Management System (entry point).

Run:  python main.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gui.app import SmartParkingApp


def main():
    app = SmartParkingApp()
    app.mainloop()


if __name__ == "__main__":
    main()
