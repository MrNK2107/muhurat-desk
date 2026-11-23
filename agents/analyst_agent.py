"""Desk Analyst (Band agent). Opens the year when a human asks, then proposes
trades at every checkpoint and hands them to Compliance."""

from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv

from band import Agent, configure_logging

from agents.common import DeskAdapter
from desk.engine import analyst_step
from desk.market import checkpoints, load_prices
from desk.narrate import analyst_note
from desk.portfolio import Portfolio

PRICES = load_prices()
POINTS = checkpoints(PRICES)


class AnalystAdapter(DeskAdapter):
    async def handle(self, msg, payload):
        if payload is None:  # a human opening the desk
            run = msg.id[:8]
            book = shadow = Portfolio().to_dict()
            i, human = 0, msg.sender_id
        elif payload.get("stage") == "filled" and payload.get("next") is not None:
            run, i, human = payload["run"], payload["next"], payload["human"]
            book, shadow = payload["book"], payload["shadow"]
        else:
            return None
        proposal = await asyncio.to_thread(analyst_step, PRICES, POINTS[i], book)
        note = await asyncio.to_thread(analyst_note, proposal)
        header = f"**Checkpoint {i + 1}/{len(POINTS)} · {proposal['date']}**" + (" · Muhurat trading, Samvat 2082 opens" if i == 0 else "")
        lines = [f"- {o['side']} {o['qty']} {o['ticker'].replace('.NS', '')} ({o['reason']})" for o in proposal["orders"]] or ["- no trades: book already on target"]
        body = {"stage": "proposal", "run": run, "i": i, "human": human, "proposal": proposal, "book": book, "shadow": shadow}
        return f"{header}\n{note}\n" + "\n".join(lines) + "\nSending to Compliance for review.", body, "compliance_agent"


async def main() -> None:
    load_dotenv()
    configure_logging(logging.INFO)
    async with Agent.from_config("analyst_agent", adapter=AnalystAdapter()) as agent:
        await agent.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
