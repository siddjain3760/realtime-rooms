"""HTTP + WebSocket surface of the hub.

- ``GET /health`` — liveness probe.
- ``GET /rooms`` — every active room with its member count.
- ``GET /rooms/{room_id}/history`` — recent messages (HTTP replay).
- ``POST /rooms/{room_id}/broadcast`` — admin-only server announcement.
- ``WS  /ws/{room_id}`` — the real-time channel clients live on.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket
from fastapi import WebSocketDisconnect
from pydantic import BaseModel, Field

from .config import Settings, settings as default_settings
from .rooms import RoomManager
from .schemas import (
    ClientFrame,
    error_event,
    notice_event,
    presence_event,
)

router = APIRouter()


def get_settings() -> Settings:
    return default_settings


_manager: RoomManager | None = None


def get_manager(s: Settings = Depends(get_settings)) -> RoomManager:
    """One manager per process; tests can override this dependency."""
    global _manager
    if _manager is None:
        _manager = RoomManager(s)
    return _manager


class BroadcastBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def _require_admin(x_admin_token: str | None, s: Settings) -> None:
    if x_admin_token != s.admin_token:
        raise HTTPException(status_code=403, detail="bad admin token")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/rooms")
async def list_rooms(manager: RoomManager = Depends(get_manager)) -> dict[str, Any]:
    return {"rooms": manager.stats()}


@router.get("/rooms/{room_id}/history")
async def room_history(
    room_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    manager: RoomManager = Depends(get_manager),
) -> dict[str, Any]:
    return {"room": room_id, "messages": manager.get_history(room_id, limit)}


@router.post("/rooms/{room_id}/broadcast", status_code=202)
async def admin_broadcast(
    room_id: str,
    body: BroadcastBody,
    x_admin_token: str | None = Header(default=None),
    s: Settings = Depends(get_settings),
    manager: RoomManager = Depends(get_manager),
) -> dict[str, str]:
    _require_admin(x_admin_token, s)
    await manager.publish_event(
        room_id, notice_event("announcement", room=room_id, text=body.text.strip())
    )
    return {"status": "broadcast queued", "room": room_id}


@router.websocket("/ws/{room_id}")
async def ws_room(
    websocket: WebSocket,
    room_id: str,
    s: Settings = Depends(get_settings),
    manager: RoomManager = Depends(get_manager),
) -> None:
    """Join ``room_id`` and relay chat in real time.

    Clients connect with ``?token=<HUB_TOKEN>&name=<display name>``.
    The server pushes ``history`` and ``presence`` first, then streams
    ``message`` / ``user_joined`` / ``user_left`` / ``typing`` /
    ``announcement`` frames. Clients send ``{"type": "chat", "text": ...}``,
    ``{"type": "typing"}`` or ``{"type": "ping"}``.
    """
    token = websocket.query_params.get("token")
    if token != s.hub_token:
        await websocket.close(code=4401)  # 4401: unauthorized, app-defined
        return

    name = (websocket.query_params.get("name") or "anon").strip()[:32] or "anon"
    room_id = room_id.strip()[:64] or "lobby"

    await websocket.accept()
    member = await manager.join(room_id, name, websocket.send_json)

    # Sliding-window rate limiter, per connection.
    recent: deque[float] = deque()

    def allowed() -> bool:
        now = time.monotonic()
        while recent and now - recent[0] > s.rate_limit_window:
            recent.popleft()
        if len(recent) >= s.rate_limit_messages:
            return False
        recent.append(now)
        return True

    try:
        while True:
            raw = await websocket.receive_json()
            try:
                frame = ClientFrame.model_validate(raw)
            except Exception:
                await websocket.send_json(error_event("malformed frame"))
                continue

            if not allowed():
                await websocket.send_json(
                    error_event(
                        f"rate limit: max {s.rate_limit_messages} "
                        f"messages per {s.rate_limit_window:g}s"
                    )
                )
                continue

            if frame.type == "chat":
                if not frame.text:
                    await websocket.send_json(error_event("empty message"))
                    continue
                await manager.publish_chat(room_id, name, frame.text)
            elif frame.type == "typing":
                await manager.publish_event(
                    room_id, notice_event("typing", user=name)
                )
            elif frame.type == "ping":
                await websocket.send_json(notice_event("pong"))
    except WebSocketDisconnect:
        pass
    finally:
        await manager.leave(room_id, member)
