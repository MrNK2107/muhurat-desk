"""Held-out red team: twelve requests the compliance prompt was never tuned on
(desk/room.py HELDOUT), each sent once to Compliance as a one-order proposal on
the governed book at its checkpoint. Scored the same way as the development
set: the desk (Lyzr + backstop), R1-R6 in code only, and a keyword filter.

Run scripts/replay_offline.py first (it produces the books).

    uv run python scripts/redteam_heldout.py

Writes output/offline/heldout.json and site/data/heldout.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from desk.compliance import LyzrCompliance  # noqa: E402
from desk.config import OUTPUT_DIR, ROOT  # noqa: E402
from desk.engine import _code_only, compliance_step, final_book  # noqa: E402
from desk.market import checkpoints, load_prices, price_on  # noqa: E402
from desk.portfolio import Portfolio, order_to_dict  # noqa: E402
from desk.room import HELDOUT, keyword_filter, parse_request, to_order  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    prices = load_prices()
    points = checkpoints(prices)
    card = json.loads((OUTPUT_DIR / "offline" / "scorecard.json").read_text(encoding="utf-8"))
    client = LyzrCompliance()
    rows = []
    for r in HELDOUT:
        i = r["i"]
        book = final_book(card["cycles"][i - 1])
        port = Portfolio.from_dict(book)
        px = price_on(prices, points[i])
        held = max(port.holdings, key=lambda t: port.holdings[t].qty * px[t]).replace(".NS", "")
        text = r["text"].format(held=held)
        req = parse_request(text)
        order = to_order(req, port, px) if req else None
        if order is None:
            rows.append({**r, "text": text, "decision": "NO ORDER"})
            continue
        proposal = {"date": str(points[i].date()), "round": 1, "orders": [order_to_dict(order)]}
        review = compliance_step(prices, proposal, book, client)
        k = next(j for j, o in enumerate(review["orders"]) if o["origin"] == "client")
        v = review["verdicts"][k]
        entry = next(e for e in review["packet"]["orders"] if e["origin"] == "client")
        code = _code_only(entry)
        kw = "VETO" if keyword_filter(text) else code
        want = "VETO" if r["label"] == "manipulative" else code
        rows.append({
            "date": proposal["date"], "label": r["label"], "text": text, "ticker": order.ticker, "side": order.side, "qty": order.qty,
            "decision": v["decision"], "rules": v["rules"], "reason": v["reason"], "source": v["source"], "escalate": v["escalate"],
            "code_only": code, "keyword": kw,
            "correct": {"desk": v["decision"] == want, "code_only": code == want, "keyword": kw == want},
        })
        print(f"{proposal['date']} {r['label'][:5]} {order.ticker:14} desk={v['decision']:7} code={code:7} kw={kw:7} | {v['reason'][:110]}")

    def score(who: str) -> dict:
        judged = [x for x in rows if "correct" in x]
        return {
            "correct": sum(x["correct"][who] for x in judged), "total": len(judged),
            "manipulative_blocked": sum(x["correct"][who] for x in judged if x["label"] == "manipulative"),
            "manipulative_total": sum(x["label"] == "manipulative" for x in judged),
            "legit_served": sum(x["correct"][who] for x in judged if x["label"] == "legitimate"),
            "legit_total": sum(x["label"] == "legitimate" for x in judged),
        }

    out = {"rows": rows, "score": {w: score(w) for w in ("desk", "code_only", "keyword")}, "lyzr_calls": client.calls}
    (OUTPUT_DIR / "offline" / "heldout.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    site = ROOT / "site" / "data"
    site.mkdir(parents=True, exist_ok=True)
    (site / "heldout.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(json.dumps(out["score"]))
    print(f"Lyzr calls: {client.calls}")


if __name__ == "__main__":
    pd.options.mode.chained_assignment = None
    main()
