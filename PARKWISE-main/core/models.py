"""Plain data objects shared by the core, simulation and GUI layers."""
from dataclasses import dataclass, asdict
from typing import Optional

# Slot statuses
AVAILABLE, OCCUPIED, RESERVED, INCOMING = "AVAILABLE", "OCCUPIED", "RESERVED", "INCOMING"
# Session statuses
S_ASSIGNED, S_PARKED, S_CHECKOUT, S_EXITING = "ASSIGNED", "PARKED", "CHECKOUT", "EXITING"
S_COMPLETED, S_CANCELLED = "COMPLETED", "CANCELLED"
ACTIVE_STATUSES = (S_ASSIGNED, S_PARKED, S_CHECKOUT, S_EXITING)


@dataclass
class VehicleSpec:
    """A vehicle that has been registered and is driving towards an entry gate."""
    reg: str
    vtype: str = "CAR"
    color: str = "#3B7DDD"
    permit: bool = False                # holds an accessible-parking permit
    preferred_slot: Optional[str] = None  # manual bay selection (optional)
    gate: str = "A"
    planned_stay: Optional[float] = None  # seconds; used by automatic traffic only
    source: str = "MANUAL"

    @property
    def priority(self) -> bool:
        return self.vtype == "VIP"


@dataclass
class SlotInfo:
    slot_id: str
    floor: str
    number: int
    category: str
    status: str = AVAILABLE
    vehicle_number: str = ""
    session_id: Optional[int] = None
    reserved_for: str = ""
    reserved_until: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class Session:
    session_id: int
    ticket_id: str
    vehicle_number: str
    vehicle_type: str
    color: str
    permit: bool
    slot_id: str
    gate: str
    entry_time: str
    entered_time: Optional[str] = None
    parked_time: Optional[str] = None
    checkout_time: Optional[str] = None
    bay_released_time: Optional[str] = None
    exit_time: Optional[str] = None
    planned_exit_time: Optional[str] = None
    status: str = S_ASSIGNED
    payment_status: str = "UNPAID"
    payment_method: Optional[str] = None
    amount: float = 0.0
    priority: bool = False
    holds_slot: bool = True

    def to_dict(self):
        return asdict(self)


@dataclass
class EntryResult:
    status: str                       # ASSIGNED | QUEUED
    session: Optional[Session] = None
    position: int = 0
    reason: str = ""
