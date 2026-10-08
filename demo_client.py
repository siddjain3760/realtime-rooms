#!/usr/bin/env python3
"""Interactive terminal client for the realtime-rooms hub.

Usage:
    python demo_client.py --room general --name alice --token dev-token-change-me

Type messages and hit enter. Type /quit to leave. Incoming frames print as
they arrive thanks to a background receiver task.
"""

from __future__ import annotations

import argparse
import asyncio
import json

import websockets


async def receive_loop(ws) -> None:
    async for raw in ws:
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            print(f"<raw> {raw}")
            continue
        kind = frame.get("type")
        if kind == "message":
            print(f"[{frame['from']}] {frame['text']}")
        elif kind == "presence":
            print(f"--- online: {', '.join(frame['members'])} ---")
        elif kind == "user_joined":
            print(f"--- {frame['user']} joined ---")
        elif kind == "user_left":
            print(f"--- {frame['user']} left ---")
        elif kind == "history":
            for m in frame["messages"]:
                print(f"[{m['from']}] {m['text']}")
            if frame["messages"]:
                print("--- caught up on history ---")
        elif kind == "announcement":
            print(f"!!! ANNOUNCEMENT: {frame['text']} !!!")
        elif kind == "typing":
            print(f"--- {frame['user']} is typing... ---")
        elif kind == "error":
            print(f"!!! error: {frame['detail']} !!!")
        # pong and unknown frames are intentionally quiet


async def send_loop(ws) -> None:
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, input)
        if line.strip() == "/quit":
            await ws.close()
            return
        await ws.send(json.dumps({"type": "chat", "text": line}))


async def main() -> None:
    parser = argparse.ArgumentParser(description="realtime-rooms terminal client")
    parser.add_argument("--host", default="localhost:8000")
    parser.add_argument("--room", default="general")
    parser.add_argument("--name", default="anon")
    parser.add_argument("--token", default="dev-token-change-me")
    args = parser.parse_args()

    url = f"ws://{args.host}/ws/{args.room}?token={args.token}&name={args.name}"
    print(f"connecting to {url} ...")
    async with websockets.connect(url) as ws:
        print(f"joined #{args.room} as {args.name} (type /quit to leave)")
        await asyncio.gather(receive_loop(ws), send_loop(ws))


if __name__ == "__main__":
    asyncio.run(main())
