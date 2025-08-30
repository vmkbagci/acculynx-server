import datetime
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from queue import Queue, Full, Empty
from typing import Deque, Dict, List, Any


class IncomingQueue:
    """Fan-out buffer that keeps the last `ttl` seconds of traffic."""

    def __init__(self, ttl_sec: int = 30, sweep_interval: int = 10) -> None:
        self._ttl = timedelta(seconds=ttl_sec)
        self._buf: Deque[Dict[str, Any]] = deque()
        self._subs: List[Queue] = []
        self._lock = threading.Lock()

        t = threading.Thread(target=self._sweeper, args=(sweep_interval,), daemon=True)
        t.start()

    # producer side ----------------------------------------------------
    def publish(self, msg: Dict[str, Any]) -> None:
        rec = {"ts": datetime.now(timezone.utc), **msg}
        with self._lock:
            self._buf.append(rec)
        # fan-out (no lock: individual queues are thread-safe)
        for q in self._subs:
            try:
                q.put_nowait(rec)  # fast path
            except Full:
                try:
                    q.get_nowait()  # drop one oldest
                except Empty:
                    pass  # (shouldn’t happen)
                try:
                    q.put_nowait(rec)  # retry – don’t block
                except Full:
                    pass

    def unsubscribe(self, q: Queue) -> None:
        try:
            self._subs.remove(q)
        except ValueError:
            pass

    # consumer side ----------------------------------------------------
    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._buf)

    def subscribe(self, q: Queue) -> None:
        self._subs.append(q)

    # housekeeping -----------------------------------------------------
    def _sweeper(self, every: int) -> None:
        while True:
            cutoff = datetime.now(timezone.utc) - self._ttl
            with self._lock:
                while self._buf and self._buf[0]["ts"] < cutoff:
                    self._buf.popleft()
            time.sleep(every)