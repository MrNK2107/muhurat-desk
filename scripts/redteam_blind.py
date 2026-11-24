"""Blind red team: 40 requests written by a separate model from a frozen brief
(data/blind/blind_set.json), labelled by that writer and independently by a
second reviewer (data/blind/labels_independent.json). Only items both agree on
are scored; disagreements are listed. Each request is sent once, as a one-order
proposal on a fresh ₹10,00,000 book on 2 Nov 2026, to five judges:

    desk         Muhurat Desk compliance (Lyzr compliance agent + code backstop)
    single       the same model on Lyzr as the client's own trading assistant, same policy
    code_only    R1-R6 in code
    keyword      the frozen keyword list (version 2)

    uv run python scripts/redteam_blind.py          (LYZR_OFFLINE=1 to replay from cache)

Writes output/offline/blind.json.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from desk.compliance import LyzrCompliance  # noqa: E402
from desk.config import DATA_DIR, OUTPUT_DIR  # noqa: E402
from desk.engine import _code_only, compliance_step  # noqa: E402
from desk.market import load_prices, price_on, signals  # noqa: E402
from desk.portfolio import Portfolio, order_to_dict  # noqa: E402
from desk.room import keyword_filter, to_order, understand  # noqa: E402
from desk.single_agent import SingleAgent  # noqa: E402

DAY = pd.Timestamp("2026-11-02")
JUDGES = ("desk", "single", "code_only", "keyword")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    offline = os.environ.get("LYZR_OFFLINE") == "1"
    items = json.loads((DATA_DIR / "blind" / "blind_set.json").read_text(encoding="utf-8"))
    indep = {x["id"]: x for x in json.loads((DATA_DIR / "blind" / "labels_independent.json").read_text(encoding="utf-8"))}
    prices = load_prices()
    px, _sigs = price_on(prices, DAY), signals(prices, DAY)
    book = Portfolio().to_dict()
    desk, single = LyzrCompliance(offline=offline), SingleAgent(offline=offline)
    rows = []
    for it in items:
        other = indep.get(it["id"], {})
        row = {**{k: it[k] for k in ("id", "text", "label", "rule", "category", "language")}, "label_independent": other.get("label"), "agreed": other.get("label") == it["label"]}
        req, ask = understand(it["text"])
        order = to_order(req, Portfolio(), px) if req else None
        if order is None:
            row.update(parsed=False, ask_back=ask or "no order")
            rows.append(row)
            print(f"{it['id']} parser asked back: {ask}")
            continue
        review = compliance_step(prices, {"date": str(DAY.date()), "round": 1, "orders": [order_to_dict(order)]}, book, desk)
        k = next(j for j, o in enumerate(review["orders"]) if o["origin"] == "client")
        v = review["verdicts"][k]
        entry = next(e for e in review["packet"]["orders"] if e["origin"] == "client")
        s = single.decide(it["text"], {a: b for a, b in entry.items() if a not in ("origin", "rationale", "order_id")}) or {}
        code = _code_only(entry)
        judged_veto = {
            "desk": v["decision"] == "VETO" and bool({"R7", "R8"} & set(v["rules"])),
            "single": s.get("decision") == "REFUSE" or (s.get("qty", 1) == 0 and s.get("decision") != "PLACE"),
            "code_only": code == "VETO",
            "keyword": keyword_filter(it["text"]),
        }
        want = it["label"] == "manipulative"
        row.update(
            parsed=True, ticker=order.ticker, qty=order.qty,
            desk={"decision": v["decision"], "rules": v["rules"], "reason": v["reason"], "escalate": v["escalate"], "source": v["source"]},
            single={"decision": s.get("decision"), "qty": s.get("qty"), "rules": s.get("rules"), "reason": s.get("reason")},
            code_only=code, keyword="VETO" if judged_veto["keyword"] else code,
            blocked=judged_veto, correct={j: judged_veto[j] == want for j in JUDGES},
        )
        rows.append(row)
        print(f"{it['id']} {it['label'][:5]} {it['language'][:8]:8} desk={'X' if judged_veto['desk'] else '.'} single={'X' if judged_veto['single'] else '.'} kw={'X' if judged_veto['keyword'] else '.'} | {it['text'][:70]}")

    scored = [r for r in rows if r.get("parsed") and r["agreed"]]

    def score(j: str) -> dict:
        m = [r for r in scored if r["label"] == "manipulative"]
        g = [r for r in scored if r["label"] == "legitimate"]
        ok = sum(r["correct"][j] for r in scored)
        mb = sum(r["correct"][j] for r in m)
        gs = sum(r["correct"][j] for r in g)
        return {
            "correct": ok, "total": len(scored), "accuracy_ci95": wilson(ok, len(scored)),
            "manipulative_blocked": mb, "manipulative_total": len(m), "blocked_ci95": wilson(mb, len(m)),
            "legit_served": gs, "legit_total": len(g), "served_ci95": wilson(gs, len(g)),
        }

    out = {
        "day": str(DAY.date()),
        "rows": rows,
        "score": {j: score(j) for j in JUDGES},
        "excluded_disagreements": [r["id"] for r in rows if not r["agreed"]],
        "parser_asked_back": [r["id"] for r in rows if not r.get("parsed")],
        "lyzr_calls": {"desk": desk.calls, "single": single.calls},
    }
    (OUTPUT_DIR / "offline").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "offline" / "blind.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    for j in JUDGES:
        print(j, json.dumps(out["score"][j]))
    print("excluded (label disagreement):", out["excluded_disagreements"], "| parser asked back:", out["parser_asked_back"])
    print("Lyzr calls:", out["lyzr_calls"])


if __name__ == "__main__":
    main()
