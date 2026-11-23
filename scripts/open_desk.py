"""Open the desk on Band as the human: create a room, add the three agents, ask
the Analyst to open Samvat 2082, then follow the room until the Trader posts
the year-end scorecard.

The three agents must already be running (scripts/run_agents.py). The Band user
key is read from ~/.secrets/band.key (or BAND_USER_API_KEY) and never printed.

    uv run python scripts/open_desk.py [--timeout 1800]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import yaml
from band_rest import (
    AsyncRestClient,
    ChatMessageRequest,
    ChatMessageRequestMentionsItem,
    CreateMyChatRoomRequestChat,
    ParticipantRequest,
)

ROOT = Path(__file__).resolve().parent.parent


def user_key() -> str:
    return (os.environ.get("BAND_USER_API_KEY") or (Path.home() / ".secrets" / "band.key").read_text(encoding="utf-8")).strip()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--room", help="follow an existing room instead of opening a new one")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    ids = {k: v["agent_id"] for k, v in yaml.safe_load((ROOT / "agent_config.yaml").read_text()).items()}
    client = AsyncRestClient(api_key=user_key())

    if args.room:
        await follow(client, args.room, args.timeout)
        return
    room = (await client.human_api_chats.create_my_chat_room(chat=CreateMyChatRoomRequestChat())).data
    for slot in ("analyst_agent", "compliance_agent", "trader_agent"):
        await client.human_api_participants.add_my_chat_participant(chat_id=room.id, participant=ParticipantRequest(participant_id=ids[slot]))
    print(f"room {room.id}: desk agents added")

    await client.human_api_messages.send_my_chat_message(
        chat_id=room.id,
        message=ChatMessageRequest(
            content="@Desk Analyst Shubh Deepavali! Open the desk for Samvat 2082 and run the year, checkpoint by checkpoint.",
            mentions=[ChatMessageRequestMentionsItem(id=ids["analyst_agent"], handle="Desk Analyst", name="Desk Analyst")],
        ),
    )
    print("kickoff sent")
    await follow(client, room.id, args.timeout)


async def follow(client: AsyncRestClient, room_id: str, timeout: int) -> None:
    seen: set[str] = set()
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        await asyncio.sleep(5)
        try:
            resp = await client.human_api_messages.list_my_chat_messages(chat_id=room_id, limit=100)
        except Exception as exc:  # transient disconnects during long polls
            print(f"(poll retry: {type(exc).__name__})")
            continue
        for m in sorted(resp.data, key=lambda m: m.inserted_at or m.id):
            if m.id in seen or m.message_type != "text":
                continue
            seen.add(m.id)
            head = str(m.content).split("```json")[0].strip()
            print(f"--- {m.sender_name or m.sender_id}:\n{head[:900]}\n")
            if "Samvat 2082 closed" in head:
                print(f"done. room id: {room_id}")
                return
    print(f"timed out; room id: {room_id}")


if __name__ == "__main__":
    asyncio.run(main())
