# Architecture

```
                        +-------------------- GUI (Tk main thread only) --------------------+
                        |  pages/*  facility_view  charts  -- poll snapshots with after() -- |
                        +---------------------+-------------------------+--------------------+
                                              | snapshot()              | snapshot()
                                              v                         v
+-----------------+  events   +--------------------------+      +------------------------+
|  ThreadManager  | <-------> |      ParkingManager      |      |   VehicleSimulation    |
|  6 worker       |  calls    |  RLock-protected state   |      |  vehicles, barriers,   |
|  threads +      |---------> |  slots / sessions /      | <----|  ramps, collisions     |
|  queues         |           |  queue / reservations    | evts |  (stepped by thread 5) |
+-----------------+           +------------+-------------+      +------------------------+
                                           |
                       AllocationEngine    |  Billing      Analytics      Documents (PDF)
                                           v
                                  SQLite  (WAL, unique indexes)
```

## Layers and rules
| Layer | Knows about | Must NOT |
|---|---|---|
| `core/` | SQLite, threading, ReportLab | import Tkinter or `simulation` |
| `simulation/` | geometry, kinematics | import Tkinter, touch the database |
| `gui/` | everything above (read-only snapshots) | mutate shared state directly; be called from worker threads |

## The life of one vehicle
1. **Arrive** - an entry-gate thread (auto) or the UI registers the vehicle (`register_arrival`: validation + duplicate check) and the simulation spawns it on the road.
2. **Detect** - the vehicle stops at the ticket point; the simulation emits `at_ticket`; the Gate thread logs *Vehicle detected* and calls `request_entry`.
3. **Allocate** - inside one critical section the engine chooses a bay and the manager assigns it (`slot INCOMING`, ticket issued, DB transaction). Otherwise the vehicle joins the waiting queue.
4. **Gate** - the Gate thread opens the barrier; the vehicle drives in (`entered` event), follows the lane (ramp for floors 1-2) and enters the bay.
5. **Park** - the simulation emits `parked`; the manager sets the bay `OCCUPIED`.
6. **Checkout** - UI or the Exit thread's scheduler calls `request_checkout`; the Billing thread bills, records the simulated payment and writes the receipt PDF.
7. **Exit** - Exit thread dispatches the vehicle: it reverses out (`bay_cleared` -> bay `AVAILABLE`, waiting queue served), opens the exit barrier, leaves (`departed` -> session `COMPLETED`).

Every arrow above is a real state change in `ParkingManager` / SQLite; the simulation never moves a vehicle on its own initiative.

## Session states
`ASSIGNED -> PARKED -> CHECKOUT -> EXITING -> COMPLETED`; bay states `AVAILABLE | INCOMING | OCCUPIED | RESERVED`.

## Persistence and recovery
Slots, sessions, queue, reservations, settings, events and occupancy samples are written through in the same transaction as the change.
At start `ParkingManager._load()` rebuilds memory from the DB and repairs slot rows from live sessions; `VehicleSimulation.restore()` puts
vehicles back (parked in bays, waiting, or re-entering); the ThreadManager re-queues payments that were in flight.

## Frame pipeline (Live Monitor)
Thread 5 steps physics at ~60 Hz. The Tk main thread runs a 30 fps `after()` loop that copies `sim.snapshot()`; a *static* canvas layer
(floor, bays, parked vehicles) is redrawn only when the backend version, parked set, floor, size or selection changes, and a *dynamic* layer
(moving vehicles, barriers, highlights) every frame.
