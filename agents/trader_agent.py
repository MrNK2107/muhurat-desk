"""Desk Trader (Band agent). Fills approved orders into the governed book and the
raw proposal into the unchecked shadow book, keeps the ledger, and closes the
year with a scorecard and an HTML report."""

from __future__ import annotations

import asyncio
import json
import logging

from dotenv import load_dotenv

from band import Agent, configure_logging

from agents.common import DeskAdapter
from desk.config import OUTPUT_DIR
from desk.engine import scorecard, trader_step
from desk.market import checkpoints, load_prices
from desk.narrate import trader_note
from desk.report import write_report

PRICES = load_prices()
POINTS = checkpoints(PRICES)


class TraderAdapter(DeskAdapter):
    async def handle(self, msg, payload):
        if not payload or payload.get("stage") != "review":
            return None
        result = trader_step(payload["proposal"], payload["review"], payload["book"], payload["shadow"])
        run_dir = OUTPUT_DIR / "runs" / payload["run"]
        run_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = run_dir / "ledger.json"
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []
        ledger = [c for c in ledger if c["proposal"]["date"] != payload["proposal"]["date"]]
        ledger.append({"proposal": payload["proposal"], "review": payload["review"], "result": result})
        ledger_path.write_text(json.dumps(ledger, indent=1))

        note = f"**Execution · {result['date']}**\n{trader_note(result)}"
        nxt = payload["i"] + 1
        if nxt < len(POINTS):
            body = {"stage": "filled", "run": payload["run"], "next": nxt, "human": payload["human"], "book": result["book"], "shadow": result["shadow"]}
            return note + f"\nAnalyst, next checkpoint is {POINTS[nxt].date()}.", body, "analyst_agent"

        card = await asyncio.to_thread(scorecard, PRICES, ledger)
        report = await asyncio.to_thread(write_report, card, run_dir / "report.html")
        g, u, n = card["governed"], card["unchecked"], card["nifty"]
        summary = (
            f"{note}\n\n**Samvat 2082 closed.** Governed book {g['total_return']:+.1%} (max drawdown {g['max_drawdown']:.1%}) · "
            f"unchecked analyst {u['total_return']:+.1%} (max drawdown {u['max_drawdown']:.1%}) · Nifty 50 {n['total_return']:+.1%}.\n"
            f"Governance kept ₹{g['final_value'] - u['final_value']:,} that the unchecked book lost. Report: {report.name} in {run_dir.relative_to(OUTPUT_DIR.parent)}"
        )
        return summary, None, f"id:{payload['human']}"


async def main() -> None:
    load_dotenv()
    configure_logging(logging.INFO)
    async with Agent.from_config("trader_agent", adapter=TraderAdapter()) as agent:
        await agent.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
