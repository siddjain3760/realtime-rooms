"""Pydantic models for every message that crosses the wire.

Client -> server frames are validated into :class:`ClientFrame`.
Server -> client frames are built with :class:`ServerEvent` helpers so every
consumer sees a consistent ``{"type": ..., ...}`` envelope.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

ClientFrameType = Literal["chat", "typing", "ping"]


class ClientFrame(BaseModel):
    """One JSON frame sent by a WebSocket client."""

    type: ClientFrameType
    text: str = Field(default="", max_length=2000)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ServerEvent(BaseModel):
    """Envelope for everything the server pushes to clients."""

    type: str
    data: dict[str, Any] = Field(default_factory=dict)


def chat_message(room_id: str, sender: str, text: str) -> dict:
    return {
        "type": "message",
        "id": str(uuid4()),
        "room": room_id,
        "from": sender,
        "text": text,
        "ts": utcnow_iso(),
    }


def presence_event(members: list[str]) -> dict:
    return {"type": "presence", "members": sorted(members), "count": len(members)}


def history_event(messages: list[dict]) -> dict:
    return {"type": "history", "messages": messages}


def notice_event(kind: str, **fields: Any) -> dict:
    return {"type": kind, **fields}


def error_event(detail: str) -> dict:
    return {"type": "error", "detail": detail}
