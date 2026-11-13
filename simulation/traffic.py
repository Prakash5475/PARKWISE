"""Random vehicle generation for the automatic gate traffic."""
import random
import string

from config import TRAFFIC_MIX
from core.models import VehicleSpec
from simulation.vehicle_art import CAR_PALETTE, VIP_PALETTE, BIKE_PALETTE

STATES = ["MH", "MH", "MH", "KA", "DL", "GJ", "TN", "RJ", "UP", "WB"]


def random_plate(rng=random):
    return "%s%02d%s%04d" % (rng.choice(STATES), rng.randint(1, 49),
                             "".join(rng.choices(string.ascii_uppercase, k=2)), rng.randint(1, 9999))


def pick_color(vtype, rng=random):
    return rng.choice({"VIP": VIP_PALETTE, "BIKE": BIKE_PALETTE}.get(vtype, CAR_PALETTE))


def random_spec(known_regs, gate="A", vtype=None, stay_range=(30, 80), rng=random, source="AUTO"):
    """Build a VehicleSpec with a registration that is not in *known_regs*."""
    vtype = vtype or rng.choices(list(TRAFFIC_MIX), list(TRAFFIC_MIX.values()))[0]
    for _ in range(50):
        reg = random_plate(rng)
        if reg not in known_regs:
            break
    permit = vtype in ("CAR", "EV") and rng.random() < 0.07
    return VehicleSpec(reg, vtype, pick_color(vtype, rng), permit, None, gate,
                       rng.uniform(*stay_range), source)
