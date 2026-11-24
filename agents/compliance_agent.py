"""Desk Compliance (Band agent). Every proposal (round 1, the analyst's
revision, or a live client request) goes through forced trims, the Lyzr
compliance agent and the code backstop; the verdicts go to the Trader. When
someone tries to bend the policy (R8), the human is mentioned as well."""

from __future__ import annotations

import asyncio
import json
import logging

from band import Agent, configure_logging
from dotenv import load_dotenv

from agents.common import DeskAdapter, short
from desk.compliance import LyzrCompliance
from desk.config import OUTPUT_DIR
from desk.engine import compliance_step
from desk.market import load_prices

PRICES = load_prices()
CLIENT = LyzrCompliance()
MARK = {"APPROVE": "✅", "MODIFY": "✂️", "VETO": "⛔"}


class ComplianceAdapter(DeskAdapter):
    async def handle(self, msg, payload):
        if not payload or payload.get("stage") != "proposal" or not self.once(payload, "proposal"):
            return None
        review = await asyncio.to_thread(compliance_step, PRICES, payload["proposal"], payload["book"], CLIENT)
        audit = OUTPUT_DIR / "runs" / payload["run"] / "compliance"
        audit.mkdir(parents=True, exist_ok=True)
        (audit / f"{payload['i']:02d}-r{payload['round']}.json").write_text(json.dumps(review, indent=1), encoding="utf-8")
        review.pop("packet")

        sources = {v["source"] for v in review["verdicts"]}
        by = "Lyzr compliance agent + code backstop" if sources & {"lyzr", "backstop"} else "code policy engine (Lyzr unreachable)"
        lines = []
        for v in review["verdicts"]:
            if v["source"] == "policy-trim":
                lines.append(f"🔻 TRIM {short(v['ticker'])} → sell {v['approved_qty']}: {v['reason']}")
                continue
            tag = " [backstop]" if v["source"] == "backstop" else ""
            esc = " ⚠️ escalated" if v.get("escalate") else ""
            lines.append(f"{MARK[v['decision']]} {v['decision']} {v['side']} {short(v['ticker'])} → {v['approved_qty']}: {v['reason']}{tag}{esc}")
        title = {1: "Compliance review", 2: "Compliance review of the revision"}.get(payload["round"], "Compliance review")
        note = f"**{title} · {review['date']}** (by {by})\n{review['summary']}\n" + "\n".join(lines or ["Nothing to review."])
        targets = ["trader_agent"]
        if any(v.get("escalate") for v in review["verdicts"]):
            targets.append(f"id:{payload['human']}")
            note += "\n⚠️ Human: someone in this room asked to bend the policy. It was refused; please take a look."
        body = {**payload, "stage": "review", "review": review}
        return note, body, targets


async def main() -> None:
    load_dotenv()
    configure_logging(logging.INFO)
    async with Agent.from_config("compliance_agent", adapter=ComplianceAdapter()) as agent:
        await agent.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
