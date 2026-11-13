"""Smart allocation engine — pure logic, no I/O, no locks (the caller holds the lock).

Rules
-----
* CAR   : GENERAL bays only.
* BIKE  : MOTO bays first, then GENERAL.
* EV    : EV charging bays first, then GENERAL.
* VIP   : VIP bays first, then GENERAL (and VIPs jump the waiting queue).
* ACCESSIBLE bays are only ever given to vehicles flagged as permit holders
  (and permit holders try them first, being closest to the entrance).
* A bay in RESERVED state is protected: only the vehicle it is reserved for may use it.
* Within a tier the nearest bay wins (lowest floor, then lowest bay number).
"""
from config import FLOORS
from core.models import AVAILABLE, RESERVED


def tiers(vtype, permit=False):
    base = {"CAR": ["GENERAL"], "BIKE": ["MOTO", "GENERAL"],
            "EV": ["EV", "GENERAL"], "VIP": ["VIP", "GENERAL"]}[vtype]
    if permit and vtype in ("CAR", "VIP"):
        return ["ACCESSIBLE"] + base
    if permit and vtype == "EV":
        return ["EV", "ACCESSIBLE", "GENERAL"]
    return list(base)


def distance_key(slot):
    return (FLOORS.index(slot.floor), slot.number)


class AllocationEngine:
    def is_eligible(self, vtype, permit, category):
        return category in tiers(vtype, permit)

    def choose(self, spec, slots):
        """Return the best slot_id for *spec*, or None if no suitable bay is free."""
        ordered = sorted(slots.values(), key=distance_key)
        # 1. a bay reserved for this very vehicle always wins
        for s in ordered:
            if s.status == RESERVED and s.reserved_for == spec.reg:
                return s.slot_id
        # 2. walk the preference tiers
        for cat in tiers(spec.vtype, spec.permit):
            for s in ordered:
                if s.category == cat and s.status == AVAILABLE:
                    return s.slot_id
        return None

    def eligible_free_slots(self, vtype, permit, slots, reg=""):
        """Slots a vehicle could be placed in right now (used by the manual-assign UI)."""
        cats = tiers(vtype, permit)
        out = [s for s in slots.values() if s.category in cats and
               (s.status == AVAILABLE or (s.status == RESERVED and s.reserved_for == reg))]
        return sorted(out, key=distance_key)

    def validate_preferred(self, spec, slot):
        """Raise ValueError explaining why *slot* cannot be used for *spec*."""
        if slot is None:
            raise ValueError(f"Bay {spec.preferred_slot} does not exist.")
        if slot.category not in tiers(spec.vtype, spec.permit):
            if slot.category == "ACCESSIBLE":
                raise ValueError(f"Bay {slot.slot_id} is accessible parking and requires a permit.")
            raise ValueError(f"Bay {slot.slot_id} ({slot.category}) is not suitable for a {spec.vtype}.")
        if slot.status == RESERVED and slot.reserved_for != spec.reg:
            raise ValueError(f"Bay {slot.slot_id} is reserved for another vehicle.")
        if slot.status not in (AVAILABLE, RESERVED):
            raise ValueError(f"Bay {slot.slot_id} is not available ({slot.status.lower()}).")
