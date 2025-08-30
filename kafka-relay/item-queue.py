import asyncio
import contextlib
import time
from typing import Generic, TypeVar, Optional, Callable, Awaitable, List, Protocol

T = TypeVar("T")

class BatchHandler(Protocol[T]):
    async def __call__(self, items: list[T]) -> None:
        ...

class ItemQueue(Generic[T]):
    """
    - Accept items via `put`.
    - Flush when `batch_size` reached OR idle for `idle_seconds`.
    - On flush, await `on_flush(items)`.
    """
    def __init__(
        self,
        *,
        on_flush: BatchHandler[T],
        batch_size: int = 20,
        idle_seconds: float = 5.0,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be > 0")
        if idle_seconds <= 0:
            raise ValueError("idle_seconds must be > 0")
        self._on_flush = on_flush
        self._batch_size = batch_size
        self._idle_seconds = idle_seconds
        self._buf: list[T] = []
        self._last_arrival: Optional[float] = None
        self._idle_task: Optional[asyncio.Task] = None
        self._flush_lock = asyncio.Lock()
        self._closed = False

    async def put(self, item: T) -> None:
        if self._closed:
            raise RuntimeError("ItemQueue is closed; cannot accept items.")
        self._buf.append(item)
        self._last_arrival = time.time()
        if len(self._buf) >= self._batch_size:
            await self._flush()
            self._arm_idle_timer()
        else:
            self._arm_idle_timer()

    def _arm_idle_timer(self) -> None:
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = asyncio.create_task(self._idle_waiter())

    async def _idle_waiter(self) -> None:
        try:
            await asyncio.sleep(self._idle_seconds)
            now = time.time()
            if self._last_arrival is None or (now - self._last_arrival) >= self._idle_seconds:
                await self._flush()
        except asyncio.CancelledError:
            pass

    async def _flush(self) -> None:
        async with self._flush_lock:
            if not self._buf:
                return
            snapshot, self._buf = self._buf, []
            # Enforce strict "N at a time" delivery
            for i in range(0, len(snapshot), self._batch_size):
                await self._on_flush(snapshot[i:i + self._batch_size])

    async def close(self) -> None:
        self._closed = True
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._idle_task
        await self._flush()
