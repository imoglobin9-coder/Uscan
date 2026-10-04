"""Abuse controls for a public deployment: rate windows, a cap on simultaneous heavy work, disk guard."""
import shutil
import threading
import time
from collections import deque
from contextlib import contextmanager
from .. import config


class LimitError(Exception):
    """A limit was hit. The message is written for the visitor and is shown to them as-is."""
    def __init__(self, message: str, status: int = 429):
        super().__init__(message)
        self.status = status


class Window:
    """Sliding window: allow(key, limit) is True while `key` has made fewer than `limit` hits in the last `seconds`."""
    def __init__(self, seconds: int):
        self.seconds, self.hits, self._lock, self._pruned = seconds, {}, threading.Lock(), 0.0

    def allow(self, key: str, limit: int) -> bool:
        if limit <= 0:
            return True
        now = time.time()
        with self._lock:
            q = self.hits.setdefault(key, deque())
            while q and now - q[0] > self.seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if now - self._pruned > 60:  # keep memory bounded
                self._pruned = now
                for k in [k for k, v in self.hits.items() if not v or now - v[-1] > self.seconds]:
                    del self.hits[k]
            return True


GENERAL, HEAVY, NEW_WORKSPACE = Window(60), Window(60), Window(3600)
_slots = threading.BoundedSemaphore(max(1, config.HEAVY_CONCURRENCY))


@contextmanager
def heavy(wait: float = 15):
    """Only a few OCR / PDF-building jobs may run at once; the others wait briefly, then get a friendly 'busy'."""
    if not _slots.acquire(timeout=wait):
        raise LimitError("uscan is busy right now. Please try again in a minute.", 503)
    try:
        yield
    finally:
        _slots.release()


def require_disk():
    if config.MIN_FREE_MB and shutil.disk_usage(config.DATA).free < config.MIN_FREE_MB * 1048576:
        raise LimitError("uscan is out of storage space right now. Please try again later.", 503)


def client_ip(request) -> str:
    return request.client.host if request.client else "unknown"
