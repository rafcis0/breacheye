from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class AsyncEventBus:
    """Small in-process pub/sub boundary that can later be swapped for Redis/NATS."""

    def __init__(self, max_queue_size: int = 256) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[Any]]] = defaultdict(set)
        self._max_queue_size = max_queue_size
        self._lock = asyncio.Lock()

    async def publish(self, topic: str, message: Any) -> None:
        async with self._lock:
            subscribers = list(self._subscribers.get(topic, set()))

        for queue in subscribers:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(message)

    async def subscribe(self, topic: str) -> asyncio.Queue[Any]:
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=self._max_queue_size)
        async with self._lock:
            self._subscribers[topic].add(queue)
        return queue

    async def unsubscribe(self, topic: str, queue: asyncio.Queue[Any]) -> None:
        async with self._lock:
            self._subscribers.get(topic, set()).discard(queue)
