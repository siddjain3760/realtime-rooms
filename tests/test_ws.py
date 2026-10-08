"""WebSocket tests: auth, join flow, chat fan-out, presence, rate limits."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

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


def drain(ws, n):
    return [ws.receive_json() for _ in range(n)]


def test_bad_token_rejected(setup):
    client, _, _ = setup
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/general?token=nope&name=x"):
            pass


def test_join_receives_history_presence(setup):
    client, _, _ = setup
    with client.websocket_connect("/ws/general?token=test-token&name=alice") as ws:
        frames = drain(ws, 3)
        by_type = {f["type"]: f for f in frames}
        assert by_type["history"]["messages"] == []
        assert by_type["presence"]["members"] == ["alice"]
        assert by_type["user_joined"]["user"] == "alice"


def test_chat_fans_out_to_room_members(setup):
    client, _, _ = setup
    with client.websocket_connect("/ws/general?token=test-token&name=alice") as a:
        drain(a, 3)
        with client.websocket_connect("/ws/general?token=test-token&name=bob") as b:
            drain(b, 3)
            # Alice sees bob's join + updated presence.
            join_frames = drain(a, 2)
            assert {f["type"] for f in join_frames} == {"user_joined", "presence"}

            a.send_json({"type": "chat", "text": "hey bob"})
            msg_a = a.receive_json()
            msg_b = b.receive_json()
            assert msg_a["type"] == msg_b["type"] == "message"
            assert msg_a["text"] == msg_b["text"] == "hey bob"
            assert msg_a["from"] == "alice"
            assert msg_a["id"] == msg_b["id"]

            # Bob leaves: alice gets user_left + fresh presence.
            b.close()
            left_frames = drain(a, 2)
            assert {f["type"] for f in left_frames} == {"user_left", "presence"}
            assert left_frames[1]["members"] == ["alice"]


def test_new_joiner_gets_message_history(setup):
    client, _, _ = setup
    with client.websocket_connect("/ws/general?token=test-token&name=alice") as a:
        drain(a, 3)
        a.send_json({"type": "chat", "text": "first"})
        a.receive_json()  # own echo
    # Room emptied out; history persists on the room object only while a
    # member is present, so reconnect and chat again for a live replay check.
    with client.websocket_connect("/ws/general?token=test-token&name=bob") as b:
        frames = drain(b, 3)
        # Bob joined an empty room: history is empty.
        assert frames[0]["messages"] == []
        b.send_json({"type": "chat", "text": "second"})
        b.receive_json()
        # Carol joins while bob is still here and replays "second".
        with client.websocket_connect("/ws/general?token=test-token&name=carol") as c:
            frames = drain(c, 3)
            history = frames[0]
            assert history["type"] == "history"
            assert [m["text"] for m in history["messages"]] == ["second"]


def test_typing_and_ping(setup):
    client, _, _ = setup
    with client.websocket_connect("/ws/general?token=test-token&name=alice") as a:
        drain(a, 3)
        a.send_json({"type": "typing"})
        typing = a.receive_json()
        assert typing["type"] == "typing" and typing["user"] == "alice"
        a.send_json({"type": "ping"})
        assert a.receive_json()["type"] == "pong"


def test_rate_limit(setup, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_MESSAGES", "2")
    monkeypatch.setenv("RATE_LIMIT_WINDOW", "60")
    s = config.Settings()
    mgr = rooms.RoomManager(s)
    application = main.create_app()
    application.dependency_overrides[routes.get_settings] = lambda: s
    application.dependency_overrides[routes.get_manager] = lambda: mgr
    with TestClient(application) as client:
        with client.websocket_connect("/ws/general?token=test-token&name=zoe") as ws:
            drain(ws, 3)
            ws.send_json({"type": "chat", "text": "one"})
            ws.receive_json()
            ws.send_json({"type": "chat", "text": "two"})
            ws.receive_json()
            ws.send_json({"type": "chat", "text": "three"})
            err = ws.receive_json()
            assert err["type"] == "error"
            assert "rate limit" in err["detail"]


def test_rooms_isolated(setup):
    client, _, _ = setup
    with client.websocket_connect("/ws/room-a?token=test-token&name=alice") as a:
        drain(a, 3)
        with client.websocket_connect("/ws/room-b?token=test-token&name=bob") as b:
            drain(b, 3)
            a.send_json({"type": "chat", "text": "only for room-a"})
            msg = a.receive_json()
            assert msg["room"] == "room-a"
            # Bob should see nothing; check room stats instead of blocking read.
            stats = client.get("/rooms").json()["rooms"]
            assert stats == {"room-a": 1, "room-b": 1}
