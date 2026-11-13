# Multithreading design

## The six threads
| # | Name | Class | Job |
|---|------|-------|-----|
| 1 | `EntryGate-A` | `EntryGateThread` | handles vehicles detected at Gate A: log, `request_entry`, barrier, promotes queued vehicles; generates automatic arrivals |
| 2 | `EntryGate-B` | `EntryGateThread` | same for Gate B (races with thread 1 for bays) |
| 3 | `ExitGate` | `ExitGateThread` | opens the exit barrier, dispatches paid vehicles, schedules automatic checkouts |
| 4 | `OccupancyMonitor` | `OccupancyMonitorThread` | samples occupancy to the DB, expires reservations, serves the queue, logs FULL / available, **integrity check** |
| 5 | `VehicleMovement` | `VehicleMovementThread` | steps the vehicle simulation ~60 times/s and reports physical events |
| 6 | `Billing` | `BillingThread` | computes bills, simulated payment, writes receipt PDFs |
Plus the Tk main thread (UI only).

## Synchronisation tools
* **`threading.RLock`** (`TrackedRLock`) - one lock guards all shared parking state. Choosing a bay *and* assigning it happen in **one** critical section, so two gates can never allocate the same bay. Re-entrant because public methods call each other (`release_bay` -> `_process_queue_locked` -> `_assign`).
* **Lock ordering** - always `manager.lock -> db.lock`; the DB never calls back, the simulation never takes the manager lock while holding its own (callbacks run after its lock is released) -> no deadlock.
* **`queue.Queue`** - thread-safe mailboxes: Gate A/B inboxes, Exit inbox, Billing queue. Producers never block.
* **`threading.Event`** - one global `shutdown_event` plus a `stop_event` per thread. Loops wait on events / `queue.get(timeout)` instead of `time.sleep`, so shutdown takes milliseconds.
* **DB defence in depth** - unique partial indexes forbid two live sessions on one bay or one vehicle even if Python logic had a bug.
* **Tkinter rule** - workers never touch widgets. The UI polls `snapshot()` copies using `after()`.

## Lifecycle
`ManagedThread.start()` creates a fresh `Thread` (a Python thread cannot be restarted); `stop()` sets the event and joins; `ThreadManager.shutdown()` sets the global event, joins every thread with a timeout and returns survivors (the tests assert `[]`). A worker that raises is **not** killed: the exception is counted and shown on the System Monitor.

## Race conditions and how they are prevented
| Race | Prevention |
|---|---|
| Gate A and B pick the same last bay | choose + assign inside one lock hold; DB unique index |
| Same registration entered twice at once | duplicate check + insert inside the lock; DB unique index |
| Double checkout click | state check `PARKED -> CHECKOUT` under the lock |
| Bay released while queue is processed | `release_bay` frees the bay and serves the queue in the same transaction |
| UI reads half-updated state | `snapshot()` copies under the lock |
| Barrier closing on a vehicle that is still on its way | barrier stays open while any vehicle still has that gate on its route (found and fixed by a test) |

Proof: `tests/test_parking.py::ConcurrentAllocation` (5 threads hammer the allocator; 2 threads race for the last bay) and the 150 s rush-hour consistency run.
