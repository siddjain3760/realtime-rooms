"""Publish/subscribe plumbing between the hub's processes.

A ``Broker`` moves room events from any publisher to every subscriber of that
room. In this build :class:`InMemoryBroker` is the real implementation and
covers a single process, which is how most people run it. The interface is
deliberately small so a ``RedisBroker`` (pub/sub across gunicorn/uvicorn
workers) can be dropped in without touching the room logic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol


class Broker(Protocol):
    """The contract every broker backend must satisfy."""

    async def publish(self, room_id: str, payload: dict) -> None:
        """Deliver ``payload`` to every subscriber of ``room_id``."""
        ...  # pragma: no cover - interface

    async def subscribe(
        self, room_id: str, handler: Callable[[dict], Awaitable[None]]
    ) -> Callable[[], None]:
        """Register ``handler`` for a room; returns an unsubscribe callable."""
        ...  # pragma: no cover - interface


class InMemoryBroker:
    """Single-process broker backed by plain asyncio structures.

    Fast enough for thousands of concurrent connections on one worker and
    trivially correct: subscribers are just a set of callbacks per room.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, set[Callable[[dict], Awaitable[None]]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, room_id: str, payload: dict) -> None:
        async with self._lock:
            handlers = list(self._handlers.get(room_id, ()))
        # Fan out outside the lock so a slow consumer can't block publishers.
        for handler in handlers:
            await handler(payload)

    async def subscribe(
        self, room_id: str, handler: Callable[[dict], Awaitable[None]]
    ) -> Callable[[], None]:
        async with self._lock:
            self._handlers.setdefault(room_id, set()).add(handler)

        def unsubscribe() -> None:
            self._handlers.get(room_id, set()).discard(handler)
            if not self._handlers.get(room_id):
                self._handlers.pop(room_id, None)

        return unsubscribe
