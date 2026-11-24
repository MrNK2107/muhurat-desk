"""Desk Trader (Band agent). Fills approved orders into the governed book and
the analyst's unchecked orders into the shadow book, keeps the ledger, and
closes the year with a scorecard and an HTML report."""

from __future__ import annotations

import asyncio
import json
import logging

from band import Agent, configure_logging
from dotenv import load_dotenv

from agents.common import DeskAdapter
from desk.config import OUTPUT_DIR
from desk.engine import scorecard, trader_step
from desk.market import load_prices
from desk.narrate import trader_note
from desk.report import write_report

PRICES = load_prices()


def _ledger_path(run: str):
    d = OUTPUT_DIR / "runs" / run
    d.mkdir(parents=True, exist_ok=True)
    return d / "ledger.json"


class TraderAdapter(DeskAdapter):
    async def handle(self, msg, payload):
        if not payload:
            return None
        if payload.get("stage") == "close" and self.once(payload, "close"):
            return await self.close(payload)
        if payload.get("stage") != "review" or not self.once(payload, "review"):
            return None
        rnd = payload["round"]
        result = trader_step(payload["review"], payload["book"], payload["shadow"], payload.get("shadow_orders") if rnd == 1 else None)

        path = _ledger_path(payload["run"])
        ledger = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        cycle = ledger.setdefault(str(payload["i"]), {})
        if rnd == 1:
            cycle.update(proposal={**payload["proposal"], "shadow_orders": payload.get("shadow_orders", [])}, review=payload["review"], result=result)
        else:
            cycle.update(revision=payload["proposal"], review2=payload["review"], result2=result)
        path.write_text(json.dumps(ledger, indent=1), encoding="utf-8")

        note = f"**Execution · {result['date']}**{' (revision)' if rnd == 2 else ''}\n{trader_note(result)}"
        body = {"stage": "filled", "run": payload["run"], "i": payload["i"], "round": rnd, "human": payload["human"],
                "live": payload.get("live", False), "review": payload["review"], "book": result["book"], "shadow": result["shadow"]}
        if payload.get("live"):
            return note + "\nDone: this was a one-off client request on the current book.", body, [f"id:{payload['human']}", "analyst_agent"]
        return note, body, "analyst_agent"

    async def close(self, payload):
        path = _ledger_path(payload["run"])
        ledger = json.loads(path.read_text(encoding="utf-8"))
        cycles = [ledger[k] for k in sorted(ledger, key=int)]
        audit = path.parent / "compliance"
        for k, c in zip(sorted(ledger, key=int), cycles):  # packets stay out of Band messages; take them from the audit files
            for key, rnd in (("review", 1), ("review2", 2)):
                f = audit / f"{int(k):02d}-r{rnd}.json"
                if c.get(key) and "packet" not in c[key] and f.exists():
                    c[key]["packet"] = json.loads(f.read_text(encoding="utf-8"))["packet"]
        card = await asyncio.to_thread(scorecard, PRICES, cycles)
        report = await asyncio.to_thread(write_report, card, path.parent / "report.html")
        (path.parent / "scorecard.json").write_text(json.dumps(card, indent=1), encoding="utf-8")
        g, u, n = card["governed"], card["unchecked"], card["nifty"]
        rt = card.get("redteam_score", {}).get("desk")
        lines = [
            "**Samvat 2082 closed.**",
            f"Governed book {g['total_return']:+.1%} (max drawdown {g['max_drawdown']:.1%}, largest single stock {g['max_stock_weight']:.0%}) · "
            f"unchecked analyst {u['total_return']:+.1%} (max drawdown {u['max_drawdown']:.1%}, largest single stock {u['max_stock_weight']:.0%}) · Nifty 50 {n['total_return']:+.1%}.",
        ]
        if rt:
            lines.append(f"Requests that tried to get around the policy: {rt['manipulative_blocked']}/{rt['manipulative_total']} stopped. Sound client requests: {rt['legit_served']}/{rt['legit_total']} served.")
        lines.append(f"Report: {report.name} in {path.parent.relative_to(OUTPUT_DIR.parent)}")
        return "\n".join(lines), None, f"id:{payload['human']}"


async def main() -> None:
    load_dotenv()
    configure_logging(logging.INFO)
    async with Agent.from_config("trader_agent", adapter=TraderAdapter()) as agent:
        await agent.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
