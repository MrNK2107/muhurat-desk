"""Desk Analyst (Band agent).

- A human says "open the desk" -> it starts the Samvat 2082 year.
- The Trader reports round-1 fills -> it reads the verdicts and answers with a
  revision (redeploy what was cut, or an appeal), or moves to the next checkpoint.
- A human asks for a trade in plain words ("put 5% in HDFC Bank, long term")
  -> it turns that into an order on the current book and sends it to
  Compliance, quoting the human's words as the rationale.
"""

from __future__ import annotations

import asyncio
import logging
import re

from band import Agent, configure_logging
from dotenv import load_dotenv

from agents.common import DeskAdapter, short, strip_mentions
from desk.engine import analyst_step, revision_step
from desk.market import checkpoints, load_prices
from desk.narrate import analyst_note
from desk.portfolio import Portfolio
from desk.room import understand

PRICES = load_prices()
POINTS = checkpoints(PRICES)
OPEN = re.compile(r"\bopen\b.*\bdesk\b", re.I)
LATEST: dict[str, dict] = {}  # per room: the last book seen, so a live request trades on the real book
ACTIVE: set[str] = set()  # rooms with a year in progress


def _order_lines(orders: list[dict]) -> list[str]:
    out = []
    for o in orders:
        tag = {"client": "client request", "appeal": "APPEAL"}.get(o.get("origin"), "")
        why = f'"{o["reason"]}"' if o.get("origin") in ("client", "appeal") else o["reason"]
        out.append(f"- {o['side']} {o['qty']} {short(o['ticker'])}" + (f" · {tag}" if tag else "") + f" ({why})")
    return out


class AnalystAdapter(DeskAdapter):
    async def handle(self, msg, payload):
        if payload is None:
            text = strip_mentions(msg.content)
            room = self.__dict__.get("room_id", "")
            if OPEN.search(text):
                ACTIVE.add(room)
                return await self.checkpoint(msg.id[:8], 0, Portfolio().to_dict(), Portfolio().to_dict(), msg.sender_id)
            req, ask = understand(text)
            if req is None and ask == "Which stock do you mean?":
                return None  # small talk, not a trade request
            if room in ACTIVE:
                return "The desk is in the middle of the Samvat 2082 replay. Ask me again once the Trader closes the books.", None, f"id:{msg.sender_id}"
            if req is None:
                return ask, None, f"id:{msg.sender_id}"
            return await self.live_request(text, msg.sender_id, msg.id[:8])
        stage = payload.get("stage")
        if stage == "filled" and self.once(payload, "filled"):
            LATEST[self.__dict__.get("room_id", "")] = {"book": payload["book"], "shadow": payload["shadow"], "i": payload["i"]}
            if payload.get("live"):
                return None
            if payload["round"] == 1:
                rev = await asyncio.to_thread(revision_step, PRICES, payload["review"], payload["book"], payload["i"])
                if rev:
                    cut = ", ".join(f"{short(c['ticker'])} ({'/'.join(c['rules']) or 'cut'})" for c in rev["cut"])
                    note = (f"**Revision · {rev['date']}** Compliance cut {cut}. "
                            + ("I'm appealing, and offering the rest to my next-strongest names:" if rev["requests"] else "Offering that money to my next-strongest names:"))
                    body = {**payload, "stage": "proposal", "round": 2, "proposal": rev}
                    return note + "\n" + "\n".join(_order_lines(rev["orders"])), body, "compliance_agent"
            nxt = payload["i"] + 1
            if nxt < len(POINTS):
                return await self.checkpoint(payload["run"], nxt, payload["book"], payload["shadow"], payload["human"])
            ACTIVE.discard(self.__dict__.get("room_id", ""))
            body = {"stage": "close", "run": payload["run"], "i": payload["i"], "round": 3, "human": payload["human"]}
            return "That was the last checkpoint of Samvat 2082. Trader, please close the books.", body, "trader_agent"
        return None

    async def checkpoint(self, run: str, i: int, book: dict, shadow: dict, human: str):
        proposal = await asyncio.to_thread(analyst_step, PRICES, POINTS[i], book, shadow, i)
        note = await asyncio.to_thread(analyst_note, proposal)
        header = f"**Checkpoint {i + 1}/{len(POINTS)} · {proposal['date']}**" + (" · Muhurat trading, Samvat 2082 opens" if i == 0 else "")
        client = [r for r in proposal["requests"] if r.get("ticker")]
        relay = "".join(f'\nThe client asked: "{r["text"]}" Passing it to Compliance with my orders.' for r in client)
        lines = _order_lines(proposal["orders"]) or ["- no trades: book already on target"]
        shadow_orders = proposal.pop("shadow_orders")
        body = {"stage": "proposal", "run": run, "i": i, "round": 1, "human": human, "proposal": proposal, "shadow_orders": shadow_orders, "book": book, "shadow": shadow}
        return f"{header}\n{note}{relay}\n" + "\n".join(lines), body, "compliance_agent"

    async def live_request(self, text: str, human: str, rid: str):
        last = LATEST.get(self.__dict__.get("room_id", ""), {})
        book = last.get("book") or Portfolio().to_dict()
        shadow = last.get("shadow") or book
        i = last.get("i", len(POINTS) - 1)
        proposal = await asyncio.to_thread(analyst_step, PRICES, POINTS[i], book, None, None, [text])
        proposal["orders"] = [o for o in proposal["orders"] if o.get("origin") == "client"]
        if not proposal["orders"]:
            return f"I couldn't turn that into an order on the current book (do you hold it, or is the size zero?): \"{text}\"", None, f"id:{human}"
        body = {"stage": "proposal", "run": f"live-{rid}", "i": i, "round": 1, "live": True, "human": human, "proposal": proposal, "shadow_orders": [], "book": book, "shadow": shadow}
        return f"**Client request · on the book as of {proposal['date']}**\n" + "\n".join(_order_lines(proposal["orders"])) + "\nSending to Compliance.", body, "compliance_agent"


async def main() -> None:
    load_dotenv()
    configure_logging(logging.INFO)
    async with Agent.from_config("analyst_agent", adapter=AnalystAdapter()) as agent:
        await agent.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
