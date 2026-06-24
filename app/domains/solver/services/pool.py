"""Solver thread pool.

Lazy-initialized ThreadPoolExecutor shared across all synchronous solve
paths.  The pool size is read from DB (platform_settings) on first use.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

_solver_pool: ThreadPoolExecutor | None = None
_solver_pool_lock = threading.Lock()


def get_solver_pool() -> ThreadPoolExecutor:
    """Return the shared solver thread pool, creating it on first call.

    Reads ``SOLVER_POOL_SIZE`` from the ``platform_settings`` table via
    ``PlatformSettingsService``.
    """
    global _solver_pool
    if _solver_pool is not None:
        return _solver_pool

    with _solver_pool_lock:
        # Double-checked locking
        if _solver_pool is None:
            from app.services.platform_settings_service import (
                PlatformSettingsService as PSS,
            )
            from app.shared.db.session import SessionLocal

            db = SessionLocal()
            try:
                pool_size = PSS.get_int(db, "SOLVER_POOL_SIZE")
            finally:
                db.close()
            _solver_pool = ThreadPoolExecutor(
                max_workers=pool_size,
                thread_name_prefix="solver",
            )
    return _solver_pool
