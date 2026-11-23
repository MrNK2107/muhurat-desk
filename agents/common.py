"""Shared plumbing for the three Band agents.

Each agent is a Band SimpleAdapter. A message between agents is a short
human-readable note followed by a fenced JSON payload; the payload carries the
desk state (proposal, verdicts, books), so the agents share nothing but the
Band room. The deciding logic lives in ``desk.engine``; the agents only route.
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


class DeskAdapter(SimpleAdapter[Any]):
    """Routes one stage of the desk. Subclasses implement ``handle``, which
    returns (note, payload, next_agent_slot) or None to stay silent."""

    stage_in: tuple[str, ...] = ()

    async def on_message(self, msg: PlatformMessage, tools, history, participants_msg, contacts_msg, *, is_session_bootstrap: bool, room_id: str) -> None:
        payload = parse_payload(msg.content)
        try:
            out = await self.handle(msg, payload)
        except Exception as exc:  # report, never crash the agent loop
            log.exception("stage failed")
            await tools.send_message(f"{type(self).__name__} hit an error: {type(exc).__name__}: {exc}", mentions=[msg.sender_id])
            return
        if out is None:
            await tools.no_reply("not addressed to this stage")
            return
        note, body, nxt = out
        mentions = [nxt[3:]] if nxt and nxt.startswith("id:") else [agent_ids()[nxt]] if nxt else [msg.sender_id]
        await tools.send_message(render(note, body) if body is not None else note, mentions=mentions)

    async def handle(self, msg: PlatformMessage, payload: dict | None):
        raise NotImplementedError
