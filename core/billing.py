"""Billing rules: hourly rate per vehicle type, grace period, GST, demo time-scale."""
import math
from dataclasses import dataclass, asdict
from config import RATES, GRACE_MINUTES, GST_PERCENT


@dataclass
class Bill:
    vehicle_type: str
    duration_s: float          # real elapsed seconds
    billed_minutes: int        # elapsed minutes after applying the demo time-scale
    billed_hours: int          # chargeable hours (0 inside the grace period)
    rate: float                # INR per hour
    time_scale: float
    base_amount: float
    tax_amount: float
    total_amount: float
    grace_applied: bool

    def to_dict(self):
        return asdict(self)


def calculate(vehicle_type, entry, exit_, time_scale=1.0, grace=GRACE_MINUTES,
              gst=GST_PERCENT, rates=None):
    """Compute the bill for a stay.

    * duration is (exit - entry) multiplied by *time_scale* (1 = real time)
    * stays up to *grace* minutes are free
    * otherwise: hours = max(1, ceil((minutes - grace) / 60)), amount = hours * rate
    * GST is added on top and everything is rounded to paise.
    """
    rates = rates or RATES
    if vehicle_type not in rates:
        raise ValueError(f"Unknown vehicle type: {vehicle_type}")
    real = max(0.0, (exit_ - entry).total_seconds())
    minutes = math.ceil(real * float(time_scale) / 60.0) if real > 0 else 0
    rate = float(rates[vehicle_type])
    if minutes <= grace:
        return Bill(vehicle_type, real, minutes, 0, rate, time_scale, 0.0, 0.0, 0.0, True)
    hours = max(1, math.ceil((minutes - grace) / 60.0))
    base = round(hours * rate, 2)
    tax = round(base * gst / 100.0, 2)
    return Bill(vehicle_type, real, minutes, hours, rate, time_scale, base, tax,
                round(base + tax, 2), False)
