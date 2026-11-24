"""Shared plumbing for the three Band agents.

Each agent is a Band SimpleAdapter. A message between agents is a short
human-readable note followed by a fenced JSON payload; the payload carries the
desk state (proposal, verdicts, books), so the agents share nothing but the
Band room. The deciding logic lives in ``desk.engine``; the agents route.

Robustness rules every stage follows:
- a message from another desk agent without a payload is ignored (so an error
  report can never be mistaken for a human opening the desk);
- each (run, checkpoint, round, stage) is handled once, so a duplicated
  message can't fork the run or fill a book twice.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import yaml
from band.core.simple_adapter import SimpleAdapter
from band.core.types import PlatformMessage

log = logging.getLogger("desk")

JSON_BLOCK = re.compile(r"```json\s*(\{.*\})\s*```", re.S)


def agent_ids() -> dict[str, str]:
    with open("agent_config.yaml", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    return {slot: v["agent_id"] for slot, v in cfg.items()}


def parse_payload(content: str) -> dict | None:
    m = JSON_BLOCK.search(content or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def render(note: str, payload: dict) -> str:
    return f"{note}\n\n```json\n{json.dumps(payload, separators=(',', ':'))}\n```"


def strip_mentions(text: str) -> str:
    """Band puts mentions in the text as @[[id]] or @Name; drop them."""
    return re.sub(r"@\[\[[^\]]+\]\]|@Desk \w+", "", text or "").strip()


class DeskAdapter(SimpleAdapter[Any]):
    """Routes one stage of the desk. Subclasses implement ``handle``, which
    returns (note, payload, targets) or None to stay silent. ``targets`` is a
    slot name ("trader_agent"), "id:<participant id>", or a list of those."""

    def once(self, payload: dict, stage: str) -> bool:
        seen = self.__dict__.setdefault("_desk_seen", set())
        key = (payload.get("run"), payload.get("i"), payload.get("round"), stage)
        if key in seen:
            return False
        seen.add(key)
        return True

    async def on_message(self, msg: PlatformMessage, tools, history, participants_msg, contacts_msg, *, is_session_bootstrap: bool, room_id: str) -> None:
        self.__dict__["room_id"] = room_id
        payload = parse_payload(msg.content)
        if payload is None and msg.sender_id in set(agent_ids().values()):
            await tools.no_reply("agent message without a payload")
            return
        try:
            out = await self.handle(msg, payload)
        except Exception as exc:  # report to the room, never crash the agent loop
            log.exception("stage failed")
            await tools.send_message(f"{type(self).__name__} hit an error: {type(exc).__name__}: {exc}", mentions=[msg.sender_id])
            return
        if out is None:
            await tools.no_reply("not addressed to this stage")
            return
        note, body, targets = out
        ids = agent_ids()
        mentions = []
        for t in targets if isinstance(targets, list) else [targets]:
            if t and t.startswith("id:"):
                mentions.append(t[3:])
            elif t:
                mentions.append(ids[t])
        await tools.send_message(render(note, body) if body is not None else note, mentions=mentions or [msg.sender_id])

    async def handle(self, msg: PlatformMessage, payload: dict | None):
        raise NotImplementedError


def short(ticker: str) -> str:
    return ticker.replace(".NS", "")
