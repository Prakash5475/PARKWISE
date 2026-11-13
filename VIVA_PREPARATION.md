# PARKWISE - B.Tech Viva Preparation

## 45-second explanation
PARKWISE is a smart-parking control system for a three-floor, 54-bay garage. Six cooperating threads - two entry gates, an exit gate,
an occupancy monitor, a vehicle-movement simulator and a billing thread - share one lock-protected `ParkingManager`.
An allocation engine applies rules for cars, bikes, EVs, VIPs, accessible bays and reservations; when the garage is full vehicles wait in a
priority queue. Every state change is written to SQLite, so the system survives a restart. The CustomTkinter UI shows a live top-down garage in which
real vehicles drive to the bays the backend allocated, plus tickets, PDF receipts, analytics and a system-monitoring page.

## Demonstration script (6-8 minutes)
1. **Overview** - 54 bays, KPIs, gauge; click a minimap bay.
2. **Live Monitor** - watch automatic traffic; point at a barrier opening, a car taking an EV bay, a vehicle using the ramp (switch floors); click a bay for the details panel.
3. **Management** - register `MH15AB1234` as an **EV**: it takes an EV bay. Register the same plate again -> duplicate error. Reserve a bay and release it.
4. **Stress** - System Monitor -> *Stress test* (or Rush hour): garage fills, vehicles park in the **waiting area**, then are served when bays free up (VIPs first).
5. **Tickets** - select a parked vehicle, show live fee, *Checkout & pay*, watch it leave; open **Ticket PDF** and **Receipt PDF**.
6. **Analytics + Logs** - charts from real data; log lines show which thread raised each event.
7. **System Monitor** - stop one thread (gate goes OFFLINE), restart it; show lock statistics; close and reopen the app to prove persistence.

## Questions and answers

### Concurrency
1. **What is multithreading and why here?** Several threads run inside one process. Gates, movement, billing and monitoring are independent activities, so threads keep the UI responsive and model the real system.
2. **List the six threads.** EntryGate-A, EntryGate-B, ExitGate, OccupancyMonitor, VehicleMovement, Billing (+ Tk main thread).
3. **What is a race condition? Give an example from this project.** The outcome depends on thread timing. Two gates choosing the same last free bay - prevented by choosing and assigning inside one lock hold.
4. **Why `RLock` and not `Lock`?** Public manager methods call each other (`release_bay` -> `_process_queue_locked` -> `_assign`); an RLock lets the same thread re-enter without deadlocking itself.
5. **What is a critical section here?** Anything that reads/modifies slots, sessions, queue or reservations - all guarded by `ParkingManager.lock`.
6. **How do you prevent deadlock?** One global lock order (manager -> database), the DB never calls back, and the simulation fires callbacks only after releasing its own lock.
7. **Why `queue.Queue`?** It is already thread-safe; producers never block and each worker owns a mailbox (gate inboxes, billing queue).
8. **How do threads stop gracefully?** `threading.Event`: each thread loops `while not should_stop()` and waits on the event or `queue.get(timeout)`, so `shutdown()` joins them within milliseconds. Tests assert no survivors.
9. **Why not `time.sleep` in loops?** It cannot be interrupted; `Event.wait(timeout)` returns immediately when stop is requested.
10. **Why must Tkinter be updated only from the main thread?** Tk is not thread-safe. Workers never touch widgets; the UI polls snapshots with `after()`.
11. **What is the GIL and does it matter?** CPython runs one bytecode thread at a time. Our threads mostly wait (queues, timers, I/O), so threading is still the right tool; the lock is needed because switching can happen between any two bytecodes.
12. **Daemon threads?** Background threads that don't block process exit; we still join them explicitly for a clean shutdown.
13. **What if a worker throws?** The base class catches it, increments an error counter, shows it on System Monitor and keeps the thread alive.
14. **Can a stopped thread be restarted?** Python threads can't, so `ManagedThread.start()` builds a new `Thread` object each time.
15. **How do you measure contention?** `TrackedRLock` tries a non-blocking acquire first and records contended acquisitions and maximum wait - visible on the System page.

### Allocation, queue, billing
16. **Allocation rules?** CAR->general; BIKE->moto then general; EV->EV then general; VIP->VIP then general; accessible only with permit; reserved bays only for their owner; nearest bay first.
17. **What happens when the garage is full?** The vehicle goes to the waiting area (max 3) and a DB queue row; VIPs sort first, then FIFO. When a bay is freed `_process_queue_locked` assigns every vehicle that now fits - a waiting car doesn't block a bike.
18. **How are duplicate registrations prevented?** Check under the lock across arriving + waiting + parked vehicles, and unique partial indexes in SQLite.
19. **What does INCOMING mean?** The bay is held for a vehicle that is still driving there. It becomes OCCUPIED only when the simulation reports the car is in the bay.
20. **Billing formula?** minutes = ceil(real seconds x time-scale / 60); <= 5 min free; else hours = max(1, ceil((minutes-5)/60)); amount = hours x rate; + 18 % GST.
21. **Why a time-scale?** A demo lasts minutes, not hours; x60 makes revenue meaningful. It is displayed everywhere and can be set to x1.
22. **Where is payment handled?** Simulated in the Billing thread (processing delay, status PROCESSING -> PAID). No real gateway.

### Database
23. **Why SQLite?** Zero-config, file-based, ACID, part of Python.
24. **What is persisted?** vehicles, slots, sessions, tickets, bills, reservations, queue, events, settings and occupancy samples.
25. **How is atomicity kept?** `with db.tx():` - an allocation's session, ticket, slot and log row commit together or not at all.
26. **What does WAL mode give?** Readers (GUI queries) don't block the writer threads.
27. **How is restart recovery done?** Load slots/sessions/queue/reservations, repair slot rows from live sessions, restore vehicle sprites, re-queue unpaid checkouts.
28. **What happens to an old v1 database?** Old tables are renamed to `legacy_*`, finished tickets imported as history - nothing is deleted.

### Simulation and UI
29. **How is the vehicle movement connected to the backend?** The backend decides (bay, gate, exit); the simulation only follows and *reports* (`at_ticket`, `entered`, `parked`, `bay_cleared`, `departed`), which change the state. Nothing moves decoratively.
30. **How do vehicles follow lanes?** Routes are polylines with Bezier-rounded corners; a vehicle advances by arc length, heading follows the path tangent with smoothing; reversing legs keep the heading.
31. **How do you avoid collisions/deadlocks?** Each vehicle checks for a vehicle ahead in its direction of motion and slows/stops; mutual blocking is resolved by priority (forward over reversing, older first); a watchdog breaks a block lasting > 7 s.
32. **How is it drawn so smoothly?** Static layer (floor, bays, parked cars) redrawn only on change; dynamic layer (moving cars, barriers) each frame at ~30 fps via `after()`.
33. **How are the cars drawn?** Rotated vector polygons (body, glass, wheels, lights, mirrors); EV has a cyan glow and bolt, VIP gold stripes, motorcycles have a rider and different proportions.
34. **How do you handle floors?** Same plan on every floor; a ramp transition moves a vehicle between floors; the monitor shows one floor, with "Follow traffic" optional.
35. **Why CustomTkinter?** Modern rounded widgets, dark theme and DPI scaling on top of Tkinter; custom visuals use Canvas.

### Testing, limits, future
36. **How did you test concurrency?** 5 threads hammering the allocator, 2 threads racing for the last bay, a 150 s rush-hour run comparing bay states with vehicle sprites, plus DB-level constraint tests.
37. **A bug testing found?** A queued vehicle got stuck because the entry barrier auto-closed before it reached the gate; fixed by keeping the barrier open while any vehicle still has that gate on its route.
38. **Limitations?** Simulated sensors/gates/payments, 2-D kinematics not physics, single machine.
39. **Future scope?** ANPR cameras, real payment gateway, QR scan at gates, IoT bay sensors, web/mobile app, role-based login, PostgreSQL for multi-site.
40. **Concurrency vs parallelism?** Concurrency = overlapping progress (our threads); parallelism = executing at the same instant on several cores (would need `multiprocessing`).

## Source files to know
`core/parking_manager.py` (state + lock), `core/allocation.py` (rules), `core/thread_manager.py` (threads), `core/database.py` (schema),
`simulation/vehicle_sim.py` (movement), `gui/facility_view.py` (drawing), `core/billing.py` (fees).
