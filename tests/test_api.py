"""HTTP API tests: health, room stats, history replay, admin broadcast."""

import pytest
from fastapi.testclient import TestClient

from app import config, main, rooms, routes


@pytest.fixture()
def setup(monkeypatch):
    monkeypatch.setenv("HUB_TOKEN", "test-token")
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin")
    s = config.Settings()
    mgr = rooms.RoomManager(s)
    application = main.create_app()
    application.dependency_overrides[routes.get_settings] = lambda: s
    application.dependency_overrides[routes.get_manager] = lambda: mgr
    with TestClient(application) as client:
        yield client, s, mgr


def test_health(setup):
    client, _, _ = setup
    assert client.get("/health").json() == {"status": "ok"}


def test_rooms_empty(setup):
    client, _, _ = setup
    assert client.get("/rooms").json() == {"rooms": {}}


def test_history_empty_room(setup):
    client, _, _ = setup
    body = client.get("/rooms/nowhere/history").json()
    assert body == {"room": "nowhere", "messages": []}


def test_broadcast_rejects_bad_admin_token(setup):
    client, _, _ = setup
    r = client.post(
        "/rooms/general/broadcast",
        json={"text": "hello"},
        headers={"x-admin-token": "wrong"},
    )
    assert r.status_code == 403


def test_broadcast_reaches_websocket_client(setup):
    client, _, _ = setup
    with client.websocket_connect("/ws/general?token=test-token&name=alice") as ws:
        # Drain join frames: history, user_joined, presence.
        for _ in range(3):
            ws.receive_json()

        r = client.post(
            "/rooms/general/broadcast",
            json={"text": "server restart soon"},
            headers={"x-admin-token": "test-admin"},
        )
        assert r.status_code == 202

        frame = ws.receive_json()
        assert frame["type"] == "announcement"
        assert frame["text"] == "server restart soon"


def test_http_history_replays_chat(setup):
    client, _, _ = setup
    with client.websocket_connect("/ws/general?token=test-token&name=bob") as ws:
        for _ in range(3):
            ws.receive_json()
        ws.send_json({"type": "chat", "text": "hello from bob"})
        msg = ws.receive_json()
        assert msg["type"] == "message" and msg["text"] == "hello from bob"

        # Rooms are ephemeral: history lives while a member is connected,
        # so the HTTP replay must be checked before the socket closes.
        body = client.get("/rooms/general/history").json()
        assert len(body["messages"]) == 1
        assert body["messages"][0]["from"] == "bob"
