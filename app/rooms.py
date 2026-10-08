"""Room state: who is connected, what was said, and how events fan out.

:class:`RoomManager` is the single owner of all in-process room state. It does
not send bytes itself — it publishes events through the broker, and each
room's broker subscription delivers them to member websockets. That keeps the
state machine testable without sockets and the fan-out path swappable.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from uuid import uuid4

from .broker import Broker, InMemoryBroker
from .config import Settings
from .schemas import chat_message, history_event, notice_event, presence_event


@dataclass
class Member:
    """One connected client inside a room."""

    name: str
    send: object  # async callable taking a dict; kept loose for test doubles
    connection_id: str = field(default_factory=lambda: uuid4().hex)


@dataclass
class Room:
    """Membership + message history for one named room."""

    room_id: str
    members: dict[str, Member] = field(default_factory=dict)
    history: deque = field(default_factory=lambda: deque(maxlen=200))
    _unsubscribe: object = field(default=None, repr=False)

    def member_names(self) -> list[str]:
        return [m.name for m in self.members.values()]


class RoomManager:
    def __init__(self, settings: Settings, broker: Broker | None = None) -> None:
        self.settings = settings
        self.broker: Broker = broker or InMemoryBroker()
        self.rooms: dict[str, Room] = {}
        self._lock = asyncio.Lock()

    async def _get_or_create(self, room_id: str) -> Room:
        room = self.rooms.get(room_id)
        if room is None:
            room = Room(room_id=room_id)
            room.history = deque(maxlen=self.settings.max_history)
            room._unsubscribe = await self.broker.subscribe(
                room_id, self._make_handler(room)
            )
            self.rooms[room_id] = room
        return room

    def _make_handler(self, room: Room):
        async def _handle(payload: dict) -> None:
            dead: list[str] = []
            for conn_id, member in room.members.items():
                try:
                    await member.send(payload)  # type: ignore[operator]
                except Exception:
                    dead.append(conn_id)
            for conn_id in dead:
                room.members.pop(conn_id, None)

        return _handle

    async def join(self, room_id: str, name: str, send) -> Member:
        """Add a member, replay history, and announce presence to the room."""
        async with self._lock:
            room = await self._get_or_create(room_id)
            member = Member(name=name, send=send)
            room.members[member.connection_id] = member

        # New joiner first catches up, then everyone sees the updated roster.
        await member.send(history_event(list(room.history)))  # type: ignore[operator]
        await self.broker.publish(
            room_id, notice_event("user_joined", user=name)
        )
        await self.broker.publish(room_id, presence_event(room.member_names()))
        return member

    async def leave(self, room_id: str, member: Member) -> None:
        """Remove a member and tell the room who is left."""
        async with self._lock:
            room = self.rooms.get(room_id)
            if room is None:
                return
            room.members.pop(member.connection_id, None)
            remaining = room.member_names()
            if not room.members:
                # Last one out closes the room and frees its subscription.
                unsubscribe = room._unsubscribe
                self.rooms.pop(room_id, None)
                if callable(unsubscribe):
                    unsubscribe()
                return
        await self.broker.publish(room_id, notice_event("user_left", user=member.name))
        await self.broker.publish(room_id, presence_event(remaining))

    async def publish_chat(self, room_id: str, sender: str, text: str) -> dict:
        """Record a chat message in history and broadcast it."""
        room = await self._get_or_create(room_id)
        message = chat_message(room_id, sender, text)
        async with self._lock:
            room.history.append(message)
        await self.broker.publish(room_id, message)
        return message

    async def publish_event(self, room_id: str, payload: dict) -> None:
        """Broadcast an arbitrary server event (typing indicators, admin msgs)."""
        await self._get_or_create(room_id)
        await self.broker.publish(room_id, payload)

    def stats(self) -> dict[str, int]:
        """room_id -> connected member count, for the HTTP admin API."""
        return {room_id: len(room.members) for room_id, room in self.rooms.items()}

    def get_history(self, room_id: str, limit: int = 50) -> list[dict]:
        room = self.rooms.get(room_id)
        if room is None:
            return []
        return list(room.history)[-limit:]
