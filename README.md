# realtime-rooms

A real-time WebSocket rooms hub built with **FastAPI**. Connect to a named
room, chat instantly with everyone in it, see who's online, and catch up on
recent history when you join — plus an HTTP API for health checks, room
stats, history replay, and admin broadcasts.

## Stack

- **FastAPI** — async web framework (both the HTTP API and the WebSocket endpoint)
- **Uvicorn** — ASGI server
- **Pydantic** — validation for every client frame and config value
- **pytest + httpx + Starlette TestClient** — real WebSocket/HTTP integration tests

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# run the server (defaults are fine for local dev)
python -m app.main
# or: uvicorn app.main:app --reload

# in another terminal, join the "general" room as alice
python demo_client.py --room general --name alice
# and in a third terminal, join as bob and watch messages flow both ways
python demo_client.py --room general --name bob
```

To use custom secrets, copy `.env.example` to `.env` and set `HUB_TOKEN` /
`ADMIN_TOKEN` — or just export them. Clients pass the hub token as
`?token=...`.

Run the test suite:

```bash
pytest -q
```

## Using the API

**WebSocket** — `ws://localhost:8000/ws/{room_id}?token=<HUB_TOKEN>&name=<you>`

Server pushes frames shaped like `{"type": ..., ...}`:

| type | meaning |
|---|---|
| `history` | last N messages, sent immediately on join |
| `presence` | current member list, sent on every join/leave |
| `message` | a chat message (`id`, `from`, `text`, `ts`) |
| `user_joined` / `user_left` | membership changes |
| `typing` | someone is typing |
| `announcement` | admin broadcast |
| `pong` | reply to `ping` |
| `error` | e.g. malformed frame or rate-limit hit |

Clients send `{"type": "chat", "text": "..."}`, `{"type": "typing"}`,
or `{"type": "ping"}`.

**HTTP**

| method | path | notes |
|---|---|---|
| `GET` | `/health` | liveness probe |
| `GET` | `/rooms` | `{room_id: member_count}` |
| `GET` | `/rooms/{id}/history?limit=50` | message replay over HTTP |
| `POST` | `/rooms/{id}/broadcast` | admin announcement; needs `X-Admin-Token` header |

```bash
# admin broadcast example
curl -X POST localhost:8000/rooms/general/broadcast \
  -H 'X-Admin-Token: dev-admin-change-me' \
  -H 'Content-Type: application/json' \
  -d '{"text": "Deploying in 5 minutes"}'
```

## Architecture

```
demo_client.py ──ws──▶  app/main.py (FastAPI app factory)
                            │
                            ▼
                       app/routes.py ──▶ WebSocket /ws/{room_id} + HTTP endpoints
                            │
                ┌────────────┴────────────┐
                ▼                         ▼
         app/rooms.py               app/schemas.py
      (RoomManager: members,     (Pydantic models for
       history, presence)         every wire frame)
                │
                ▼
         app/broker.py
      (Broker protocol +
       InMemoryBroker fan-out;
       swap in Redis later)
```

**Design notes**

- **All fan-out goes through the broker.** `RoomManager` never touches
  sockets directly; it publishes events and each room's subscription
  delivers them to member websockets. Swapping `InMemoryBroker` for a Redis
  pub/sub backend would make the hub work across multiple uvicorn workers
  without changing any room logic.
- **History replay.** Each room keeps a bounded deque of recent messages
  (`MAX_HISTORY`), so new joiners get context instantly and late HTTP
  consumers can call `/rooms/{id}/history`.
- **Defense in depth for a demo service:** token auth on every socket,
  admin token on broadcast, per-connection sliding-window rate limiting,
  and strict Pydantic validation of inbound frames (malformed frames get an
  `error` frame instead of killing the connection).
- **Rooms are ephemeral:** a room with no members is torn down and its
  broker subscription freed, so idle rooms cost nothing.

## Configuration

| variable | default | meaning |
|---|---|---|
| `HUB_TOKEN` | `dev-token-change-me` | required `?token=` for WS clients |
| `ADMIN_TOKEN` | `dev-admin-change-me` | `X-Admin-Token` for broadcasts |
| `MAX_HISTORY` | `50` | messages replayed to new joiners |
| `RATE_LIMIT_MESSAGES` / `RATE_LIMIT_WINDOW` | `20` / `10.0` | per-connection chat throttle |
| `PORT` | `8000` | server port |

## License

MIT — see [LICENSE](LICENSE).
