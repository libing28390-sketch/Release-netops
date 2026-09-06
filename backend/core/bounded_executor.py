"""Small bounded daemon worker pool for best-effort isolated work.

The pool is deliberately finite and fail-fast.  It is used for optional
shadow integrations where a dependency may hang, so a timed-out task must not
create an unbounded number of threads or hold up the request thread.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future
from queue import Full, Queue
from typing import Any, Callable


class BoundedExecutorSaturated(RuntimeError):
    """Raised when no worker/queue capacity is available."""


class BoundedDaemonExecutor:
    """A fixed-size daemon executor with a bounded submission queue."""

    def __init__(self, *, max_workers: int, max_queue: int, thread_name_prefix: str) -> None:
        self.max_workers = max(1, int(max_workers))
        self.max_queue = max(1, int(max_queue))
        self.thread_name_prefix = str(thread_name_prefix or "bounded-worker")[:48]
        self._queue: Queue[tuple[Future[Any], Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = Queue(
            maxsize=self.max_queue
        )
        self._workers: list[threading.Thread] = []
        self._lock = threading.Lock()

    def _ensure_workers(self) -> None:
        with self._lock:
            while len(self._workers) < self.max_workers:
                worker = threading.Thread(
                    target=self._worker_loop,
                    daemon=True,
                    name=f"{self.thread_name_prefix}-{len(self._workers) + 1}",
                )
                self._workers.append(worker)
                worker.start()

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future[Any]:
        self._ensure_workers()
        future: Future[Any] = Future()
        try:
            self._queue.put_nowait((future, fn, args, kwargs))
        except Full as exc:
            raise BoundedExecutorSaturated("bounded worker capacity is exhausted") from exc
        return future

    def _worker_loop(self) -> None:
        while True:
            future, fn, args, kwargs = self._queue.get()
            try:
                if future.set_running_or_notify_cancel():
                    try:
                        future.set_result(fn(*args, **kwargs))
                    except BaseException as exc:  # Future owns the exception.
                        future.set_exception(exc)
            finally:
                self._queue.task_done()


__all__ = ["BoundedDaemonExecutor", "BoundedExecutorSaturated"]
