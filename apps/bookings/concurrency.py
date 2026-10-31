"""
Run a function in many threads that all start at the same instant.

Used by the concurrency tests and the compare_locking command. Each thread gets its own
database connection (Django keeps one per thread), so these really are concurrent
Postgres transactions, not just interleaved Python.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from django.db import connection


@dataclass
class Outcome:
    value: Any = None
    error: BaseException | None = None
    seconds: float = 0.0


def run_in_parallel(func, args_list, *, start_timeout: float = 30.0) -> list[Outcome]:
    """
    Call func(*args) once per item in args_list, all in separate threads, released
    together by a barrier. Returns one Outcome per call, in input order. Exceptions are
    captured rather than raised, so one failing call can't hide the others' results.
    """
    barrier = threading.Barrier(len(args_list))

    def worker(args) -> Outcome:
        try:
            barrier.wait(timeout=start_timeout)  # nobody starts until everyone is ready
            started = time.perf_counter()
            try:
                return Outcome(value=func(*args), seconds=time.perf_counter() - started)
            except Exception as exc:  # noqa: BLE001 - captured on purpose, see docstring
                return Outcome(error=exc, seconds=time.perf_counter() - started)
        finally:
            # Each thread opened its own connection; close it or Postgres runs out.
            connection.close()

    # max_workers == number of calls, so every call has a thread waiting at the barrier.
    with ThreadPoolExecutor(max_workers=len(args_list)) as pool:
        return list(pool.map(worker, args_list))
