import time
from datetime import datetime, timedelta, timezone
from queue import Empty, Full, Queue
from threading import Lock, Thread
from typing import Any, Dict, List, Optional, Set, Tuple, Union

Filter = Optional[Set[str]]  # None ⇒ “no filter”


class ListenerRegistry:
    """
    Keeps a ≤100-message queue per (listenerId, topic) and removes it when
    it hasn’t been polled for `idle_sec` seconds (default 200 s).
    """

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _norm(v: Union[str, List[str], None]) -> Filter:
        if v is None:
            return None
        if isinstance(v, str):
            return {v}
        return set(v)

    def __init__(self, incoming, idle_sec: int = 45, sweep_sec: int = 10):
        self._incoming = incoming
        self._idle = timedelta(seconds=idle_sec)
        self._lock = Lock()
        # key → {"queue": Queue, "ts": datetime}
        self._entries: Dict[Tuple[str, str], Dict[str, Any]] = {}

        Thread(target=self._sweeper, args=(sweep_sec,), daemon=True).start()

    def start_listener(
        self,
        listener_id: str,
        topic: str,
        *,
        user: Union[str, List[str], None] = None,
        dealtype: Union[str, List[str], None] = None,
    ) -> None:
        key = (listener_id, topic)
        with self._lock:
            if key in self._entries:  # already exists → just “touch”
                self._entries[key]["ts"] = self._now()
                return

            q: Queue[dict[str, Any]] = Queue(maxsize=100)
            for rec in self._incoming.snapshot():  # initial dump
                try:
                    q.put_nowait(rec)
                except Full:
                    break

            self._incoming.subscribe(q)
            self._entries[key] = {
                "queue": q,
                "ts": self._now(),
                "user": self._norm(user),  # NEW
                "dealtype": self._norm(dealtype),  # NEW
            }

    def poll(self, listener_id: str, topic: str) -> List[dict[str, str]]:
        key = (listener_id, topic)
        with self._lock:
            entry = self._entries.get(key)
        if not entry:
            return []

        q = entry["queue"]
        entry["ts"] = self._now()

        u_filter: Filter = entry["user"]
        d_filter: Filter = entry["dealtype"]

        out: List[dict[str, str]] = []
        while True:
            try:
                rec = q.get_nowait()
            except Empty:
                break

            if rec["topic"] != topic:
                continue
            if u_filter and rec.get("user") not in u_filter:
                continue
            if d_filter and rec.get("dealtype") not in d_filter:
                continue
            out.append(rec)

        return out

    def _sweeper(self, every: int) -> None:
        """Background task – drop queues idle for longer than self._idle."""
        while True:
            now = self._now()
            stale: List[Tuple[str, str]] = []

            with self._lock:
                for key, entry in list(self._entries.items()):
                    if now - entry["ts"] > self._idle:
                        stale.append(key)

                for key in stale:
                    q = self._entries.pop(key)["queue"]
                    print(f"Unsubscribed {key}")
                    self._incoming.unsubscribe(q)  # detach from fan-out

            time.sleep(every)
