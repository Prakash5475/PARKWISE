"""Backward-compatibility shim.

The v1 prototype kept its gate threads here.  They now live in ``core.thread_manager``
(EntryGateThread, ExitGateThread, OccupancyMonitorThread, ...), managed by ThreadManager.
"""
from core.thread_manager import ThreadManager as GateWorkers   # noqa: F401
