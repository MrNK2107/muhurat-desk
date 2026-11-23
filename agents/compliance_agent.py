"""Desk Compliance (Band agent). Every proposal goes through the Lyzr compliance
agent, then the code backstop; the verdicts go to the Trader."""

from __future__ import annotations

import asyncio
import json
import logging

from dotenv import load_dotenv

from band import Agent, configure_logging

from agents.common import DeskAdapter
from desk.compliance import LyzrCompliance
from desk.config import OUTPUT_DIR
from desk.engine import compliance_step
from desk.market import load_prices

PRICES = load_prices()
CLIENT = LyzrCompliance()


class ComplianceAdapter(DeskAdapter):
    async def handle(self, msg, payload):
        if not payload or payload.get("stage") != "proposal":
            return None
        review = await asyncio.to_thread(compliance_step, PRICES, payload["proposal"], payload["book"], CLIENT)
        audit = OUTPUT_DIR / "runs" / payload["run"] / "compliance"
        audit.mkdir(parents=True, exist_ok=True)
        (audit / f"{payload['i']:02d}.json").write_text(json.dumps(review, indent=1))
        review.pop("packet")

        source = {v["source"] for v in review["verdicts"]}
        by = "Lyzr compliance agent" if "lyzr" in source or "backstop" in source else "local policy engine (Lyzr unreachable)"
        lines = []
        for v in review["verdicts"]:
            mark = {"APPROVE": "✅", "MODIFY": "✂️", "VETO": "⛔"}[v["decision"]]
            tag = " [backstop]" if v["source"] == "backstop" else ""
            lines.append(f"{mark} {v['decision']} {v['side']} {v['ticker'].replace('.NS', '')} → {v['approved_qty']}: {v['reason']}{tag}")
        note = f"**Compliance review · {review['date']}** (by {by})\n{review['summary']}\n" + "\n".join(lines or ["Nothing to review."])
        body = {**payload, "stage": "review", "review": review}
        return note + "\nTrader, fill the approved quantities.", body, "trader_agent"


async def main() -> None:
    load_dotenv()
    configure_logging(logging.INFO)
    async with Agent.from_config("compliance_agent", adapter=ComplianceAdapter()) as agent:
        await agent.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
