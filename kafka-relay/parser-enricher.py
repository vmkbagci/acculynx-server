import asyncio
import json
import time
import contextlib
from .item-queue import ItemQueue
from dataclasses import dataclass
from typing import Any, Dict, Generic, Optional, TypeVar, Union, Protocol
from collections.abc import Awaitable
from xml.etree import ElementTree as ET

try:
    import aiohttp
except ImportError:
    aiohttp = None


T = TypeVar("T")  # generic item type for batching
JSONLike = Dict[str, Any]
IncomingItem = Union[str, JSONLike]  # JSON str, XML str, or already-parsed dict


# ---------------------------
# Protocol: async batch handler
# ---------------------------

class BatchHandler(Protocol[T]):
    async def __call__(self, items: list[T]) -> None: ...
    # Meaning: an async callable taking `list[T]` and returning None.


# # ---------------------------
# # 1) Reusable batching queue
# # ---------------------------

# class ItemQueue(Generic[T]):
#     """
#     - Accept items via `put`.
#     - Flush when `batch_size` reached OR idle for `idle_seconds`.
#     - On flush, await `on_flush(items)`.
#     """

#     def __init__(
#         self,
#         *,
#         on_flush: BatchHandler[T],
#         batch_size: int = 20,
#         idle_seconds: float = 5.0,
#     ) -> None:
#         if batch_size <= 0:
#             raise ValueError("batch_size must be > 0")
#         if idle_seconds <= 0:
#             raise ValueError("idle_seconds must be > 0")

#         self._on_flush = on_flush
#         self._batch_size = batch_size
#         self._idle_seconds = idle_seconds

#         self._buf: list[T] = []
#         self._last_arrival: Optional[float] = None
#         self._idle_task: Optional[asyncio.Task] = None
#         self._flush_lock = asyncio.Lock()
#         self._closed = False

#     async def put(self, item: T) -> None:
#         if self._closed:
#             raise RuntimeError("ItemQueue is closed; cannot accept items.")
#         self._buf.append(item)
#         self._last_arrival = time.time()

#         if len(self._buf) >= self._batch_size:
#             await self._flush()
#             self._arm_idle_timer()
#         else:
#             self._arm_idle_timer()

#     def _arm_idle_timer(self) -> None:
#         if self._idle_task and not self._idle_task.done():
#             self._idle_task.cancel()
#         self._idle_task = asyncio.create_task(self._idle_waiter())

#     async def _idle_waiter(self) -> None:
#         try:
#             await asyncio.sleep(self._idle_seconds)
#             now = time.time()
#             if self._last_arrival is None or (now - self._last_arrival) >= self._idle_seconds:
#                 await self._flush()
#         except asyncio.CancelledError:
#             pass

#     async def _flush(self) -> None:
#         async with self._flush_lock:
#             if not self._buf:
#                 return
#             snapshot, self._buf = self._buf, []
#         # Call outside the lock so producers can continue
#         # Enforce strict "N at a time" delivery
#         for i in range(0, len(snapshot), self._batch_size):
#             await self._on_flush(snapshot[i:i + self._batch_size])

#     async def close(self) -> None:
#         self._closed = True
#         if self._idle_task and not self._idle_task.done():
#             self._idle_task.cancel()
#             with contextlib.suppress(asyncio.CancelledError):
#                 await self._idle_task
#         await self._flush()


# ---------------------------
# 2) Enrichment worker using ItemQueue
# ---------------------------

@dataclass
class _BufferedItem:
    raw: IncomingItem
    fmt: str              # "json" | "xml"
    deal_number: str


class BatchEnricher:
    """
    - Submit items via `submit`.
    - Internally uses ItemQueue[_BufferedItem] with a BatchHandler-based flush.
    - For each batch, fetches {deal_number -> trader}, enriches, and pushes to `out_queue`.
    """

    def __init__(
        self,
        out_queue: asyncio.Queue[IncomingItem],
        *,
        batch_size: int = 20,
        idle_seconds: float = 5.0,
        api_url: Optional[str] = None,
        fetch_traders: Optional[BatchHandler[str] | None] = None,  # see note below
        http_timeout: float = 10.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.75,
    ) -> None:
        # NOTE: fetch_traders here is *not* a BatchHandler; it’s an async function
        #       taking list[str] and returning dict[str, str]. Define a dedicated
        #       Protocol for clarity:
        #
        # class TraderLookup(Protocol):
        #     async def __call__(self, deals: list[str]) -> Dict[str, str]: ...
        #
        # Then annotate: fetch_traders: TraderLookup | None = None
        #
        # Kept inline for brevity below.

        self.out_queue = out_queue
        self.http_timeout = http_timeout
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds

        if fetch_traders is None:
            if api_url is None:
                raise ValueError("Provide `api_url` or a custom `fetch_traders`.")
            if aiohttp is None:
                raise ImportError("Install aiohttp or inject a custom fetcher.")
            self._api_url = api_url
            self._fetch_traders = self._default_fetch_traders
        else:
            self._api_url = api_url
            self._fetch_traders = fetch_traders  # type: ignore[assignment]

        # Wire ItemQueue with a Protocol-typed handler
        async def on_flush(items: list[_BufferedItem]) -> None:
            await self._process_batch(items)

        self._queue = ItemQueue[_BufferedItem](
            on_flush=on_flush,
            batch_size=batch_size,
            idle_seconds=idle_seconds,
        )

    # ---- Public API

    async def submit(self, item: IncomingItem) -> None:
        buf = self._normalize(item)
        await self._queue.put(buf)

    async def close(self) -> None:
        await self._queue.close()

    # ---- Internals

    def _normalize(self, item: IncomingItem) -> _BufferedItem:
        if isinstance(item, dict):
            deal = self._deal_from_json(item)
            return _BufferedItem(raw=item, fmt="json", deal_number=deal)

        if isinstance(item, str):
            # Try JSON then XML
            try:
                parsed = json.loads(item)
                if not isinstance(parsed, dict):
                    raise ValueError("JSON must be an object")
                deal = self._deal_from_json(parsed)
                return _BufferedItem(raw=parsed, fmt="json", deal_number=deal)
            except json.JSONDecodeError:
                pass

            try:
                root = ET.fromstring(item)
            except ET.ParseError as e:
                raise ValueError(f"Invalid JSON/XML: {e}") from e
            deal = self._deal_from_xml(root)
            return _BufferedItem(raw=root, fmt="xml", deal_number=deal)

        raise TypeError(f"Unsupported item type: {type(item)!r}")

    @staticmethod
    def _deal_from_json(obj: JSONLike) -> str:
        if "deal_number" not in obj:
            raise KeyError("JSON missing 'deal_number'")
        v = obj["deal_number"]
        if not isinstance(v, (str, int)):
            raise TypeError("'deal_number' must be str or int")
        return str(v)

    @staticmethod
    def _deal_from_xml(root: ET.Element) -> str:
        node = root.find(".//deal_number")
        if node is None or (node.text or "").strip() == "":
            raise KeyError("XML missing <deal_number>")
        return node.text.strip()  # type: ignore[return-value]

    async def _process_batch(self, items: list[_BufferedItem]) -> None:
        deals = [it.deal_number for it in items]
        mapping = await self._with_retries(self._fetch_traders, deals)

        # Enrich and emit
        for it in items:
            trader = mapping.get(it.deal_number)
            if it.fmt == "json":
                assert isinstance(it.raw, dict)
                obj = dict(it.raw)
                obj["trader"] = trader
                await self.out_queue.put(obj)
            else:
                # xml
                assert isinstance(it.raw, ET.Element)
                root = it.raw
                node = root.find(".//trader") or ET.SubElement(root, "trader")
                node.text = "" if trader is None else str(trader)
                await self.out_queue.put(ET.tostring(root, encoding="unicode"))

    async def _with_retries(
        self,
        func,  # see TraderLookup note above
        deals: list[str],
    ) -> dict[str, str]:
        attempt = 0
        last_exc: Optional[BaseException] = None
        while attempt <= self.max_retries:
            try:
                return await func(deals)
            except Exception as e:
                last_exc = e
                if attempt == self.max_retries:
                    break
                await asyncio.sleep(self.retry_backoff_seconds * (2**attempt))
                attempt += 1
        raise RuntimeError(f"Failed to fetch traders after {self.max_retries+1} attempts") from last_exc

    async def _default_fetch_traders(self, deals: list[str]) -> dict[str, str]:
        assert self._api_url is not None
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.http_timeout)) as session:
            async with session.post(self._api_url, json={"deal_numbers": deals}) as resp:
                resp.raise_for_status()
                payload = await resp.json()
        if isinstance(payload, dict) and "results" in payload and isinstance(payload["results"], list):
            return {str(x["deal_number"]): (None if x.get("trader") is None else str(x["trader"]))
                    for x in payload["results"]}
        if isinstance(payload, dict):
            return {str(k): (None if v is None else str(v)) for k, v in payload.items()}
        raise ValueError("Unexpected API response shape for trader lookup.")
