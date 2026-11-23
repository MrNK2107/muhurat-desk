"""One desk cycle and the year-long replay, independent of any transport.

The Band agents call ``analyst_step`` / ``compliance_step`` / ``trader_step``
with the payloads they receive from each other; ``replay`` runs the same three
steps in-process (used for tests, the offline golden run and the report)."""

from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from desk import analyst, compliance, trader
from desk.compliance import LyzrCompliance
from desk.market import checkpoints, price_on, signals
from desk.portfolio import Portfolio, order_from_dict, order_to_dict, verdict_from_dict


def analyst_step(prices: pd.DataFrame, asof: pd.Timestamp, book: dict) -> dict:
    port = Portfolio.from_dict(book)
    sigs = signals(prices, asof)
    px = price_on(prices, asof)
    orders = analyst.propose(port, sigs, px)
    top = sorted(analyst.score(sigs).items(), key=lambda kv: kv[1], reverse=True)[:5]
    return {
        "date": str(asof.date()),
        "orders": [order_to_dict(o) for o in orders],
        "top_signals": [
            {"ticker": t, "mom_3m": round(sigs[t].mom_3m, 4), "mom_6m": round(sigs[t].mom_6m, 4), "vol_20d": round(sigs[t].vol_20d, 4)}
            for t, _ in top
        ],
    }


def compliance_step(prices: pd.DataFrame, proposal: dict, book: dict, client: LyzrCompliance | None) -> dict:
    asof = pd.Timestamp(proposal["date"])
    port = Portfolio.from_dict(book)
    orders = [order_from_dict(o) for o in proposal["orders"]]
    verdicts, summary, packet = compliance.review(orders, port, price_on(prices, asof), signals(prices, asof), proposal["date"], client)
    return {"date": proposal["date"], "verdicts": [asdict(v) for v in verdicts], "summary": summary, "packet": packet}


def trader_step(proposal: dict, review: dict, book: dict, shadow: dict) -> dict:
    orders = [order_from_dict(o) for o in proposal["orders"]]
    verdicts = [verdict_from_dict(v) for v in review["verdicts"]]
    gov, unchecked = Portfolio.from_dict(book), Portfolio.from_dict(shadow)
    fills = trader.execute(gov, orders, verdicts)
    trader.execute(unchecked, [order_from_dict(o) for o in proposal["orders"]], None)
    return {
        "date": proposal["date"],
        "fills": [asdict(f) for f in fills],
        "blocked": trader.blocked_exposure(orders, verdicts),
        "book": gov.to_dict(),
        "shadow": unchecked.to_dict(),
    }


def replay(prices: pd.DataFrame, client: LyzrCompliance | None, on_cycle=None) -> dict:
    """Run the whole Samvat year. Returns the audit log and scorecard."""
    book = shadow = Portfolio().to_dict()
    cycles = []
    points = checkpoints(prices)
    for asof in points:
        proposal = analyst_step(prices, asof, book)
        review = compliance_step(prices, proposal, book, client)
        result = trader_step(proposal, review, book, shadow)
        book, shadow = result["book"], result["shadow"]
        cycle = {"proposal": proposal, "review": review, "result": result}
        cycles.append(cycle)
        if on_cycle:
            on_cycle(cycle)
    return scorecard(prices, cycles)


def scorecard(prices: pd.DataFrame, cycles: list[dict]) -> dict:
    from desk.config import SAMVAT_END

    end = pd.Timestamp(SAMVAT_END)
    start = pd.Timestamp(cycles[0]["proposal"]["date"])
    gov = trader.nav_series([(pd.Timestamp(c["proposal"]["date"]), c["result"]["book"]) for c in cycles], prices, end)
    raw = trader.nav_series([(pd.Timestamp(c["proposal"]["date"]), c["result"]["shadow"]) for c in cycles], prices, end)
    bench = trader.benchmark_series(prices, start, end)

    # Did the cuts help? Value each blocked slice from its checkpoint to the next.
    dates = [pd.Timestamp(c["proposal"]["date"]) for c in cycles] + [end]
    blocked_pnl = []
    for i, c in enumerate(cycles):
        later = price_on(prices, dates[i + 1])
        for b in c["result"]["blocked"]:
            pnl = (later[b["ticker"]] - b["price"]) * b["qty"]
            blocked_pnl.append({**b, "date": c["proposal"]["date"], "until": str(dates[i + 1].date()), "pnl_avoided": round(-pnl)})
    return {
        "cycles": cycles,
        "governed": trader.stats(gov),
        "unchecked": trader.stats(raw),
        "nifty": trader.stats(bench),
        "curves": {
            "dates": [str(d.date()) for d in gov.index],
            "governed": [round(v) for v in gov.values],
            "unchecked": [round(float(raw.get(d, float("nan")))) for d in gov.index],
            "nifty": [round(float(bench.get(d, float("nan")))) for d in gov.index],
        },
        "blocked": blocked_pnl,
    }
