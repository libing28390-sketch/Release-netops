import logging
import asyncio
import functools
from datetime import datetime, timedelta, timezone
from database import get_db_connection

logger = logging.getLogger(__name__)

def acquire_scheduler_lock(lock_name: str, expire_seconds: int = 60) -> bool:
    """Acquire a lightweight database lock for a scheduled task to prevent duplicate executions."""
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        # Clean up expired locks first to avoid accumulation
        conn.execute("DELETE FROM scheduler_locks WHERE expires_at < ?", (now,))
        
        # Try to insert lock
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expire_seconds)).replace(microsecond=0).isoformat()
        try:
            conn.execute(
                "INSERT INTO scheduler_locks (lock_name, locked_at, expires_at) VALUES (?, ?, ?)",
                (lock_name, now, expires_at)
            )
            conn.commit()
            return True
        except Exception:
            # Lock already exists and is active (duplicate execution blocked)
            return False
    finally:
        conn.close()

def synchronized_scheduler_job(lock_name: str, expire_seconds: int = 55):
    """Decorator to ensure a scheduler job runs on only one instance at a time."""
    def decorator(func):
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                if acquire_scheduler_lock(lock_name, expire_seconds):
                    try:
                        return await func(*args, **kwargs)
                    except Exception as e:
                        logger.error(f"Error executing synchronized scheduler job {lock_name}: {e}", exc_info=True)
                else:
                    logger.debug(f"Scheduler lock {lock_name} is already held. Skipping execution.")
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                if acquire_scheduler_lock(lock_name, expire_seconds):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        logger.error(f"Error executing synchronized scheduler job {lock_name}: {e}", exc_info=True)
                else:
                    logger.debug(f"Scheduler lock {lock_name} is already held. Skipping execution.")
            return sync_wrapper
    return decorator
