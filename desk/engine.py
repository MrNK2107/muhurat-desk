"""One desk cycle and the year-long replay, independent of any transport.

A checkpoint is a short conversation with two rounds:

    Analyst  -- proposal (its momentum orders + any client request) -->  Compliance
    Compliance -- verdicts (Lyzr + backstop, forced trims) -->            Trader
    Trader   -- fills -->                                                 Analyst
    Analyst  -- revision: redeploy what was cut, or an appeal -->         Compliance
    Compliance -- verdicts -->                                            Trader
    Trader   -- fills, next checkpoint -->                                Analyst

The Band agents call the ``*_step`` functions with the payloads they receive
from each other; ``replay`` runs the same steps in-process (tests, the offline
golden run and the report). The unchecked shadow book gets the same analyst
and the same client, with no compliance at all.
"""

from __future__ import annotations

import copy
from dataclasses import asdict

import pandas as pd

from desk import analyst, compliance, trader
from desk.compliance import LyzrCompliance
from desk.config import POLICY, SAMVAT_END, STARTING_CAPITAL, UNIVERSE
from desk.market import checkpoints, price_on, signals
from desk.portfolio import Order, Portfolio, order_from_dict, order_to_dict, verdict_from_dict
from desk.room import keyword_filter, parse_request, scenario_for, to_order


def _client_orders(requests: list[dict], port: Portfolio, px: dict[str, float]) -> list[tuple[dict, Order | None]]:
    out = []
    for r in requests:
        req = parse_request(r["text"])
        out.append((r, to_order(req, port, px) if req else None))
    return out


def analyst_step(prices: pd.DataFrame, asof: pd.Timestamp, book: dict, shadow: dict | None = None, i: int | None = None, live_requests: list[str] | None = None) -> dict:
    """Round 1: the analyst's momentum orders plus whatever the client asked
    for. Also what the same analyst would do on the unchecked book."""
    port = Portfolio.from_dict(book)
    sigs, px = signals(prices, asof), price_on(prices, asof)
    requests = [r for r in (scenario_for(i) if i is not None else []) if r["origin"] == "client"]
    requests += [{"i": i, "origin": "client", "label": "live", "text": t} for t in (live_requests or [])]

    orders = analyst.propose(port, sigs, px)
    client = _client_orders(requests, port, px)
    orders += [o for _, o in client if o]
    out = {
        "date": str(asof.date()),
        "i": i,
        "round": 1,
        "orders": [order_to_dict(o) for o in orders],
        "requests": [{**r, "ticker": o.ticker if o else None, "qty": o.qty if o else 0} for r, o in client],
        "top_signals": [
            {"ticker": t, "mom_3m": round(sigs[t].mom_3m, 4), "mom_6m": round(sigs[t].mom_6m, 4), "vol_20d": round(sigs[t].vol_20d, 4)}
            for t, _ in sorted(analyst.score(sigs).items(), key=lambda kv: kv[1], reverse=True)[:5]
        ],
    }
    if shadow is not None:
        sp = Portfolio.from_dict(shadow)
        shadow_orders = analyst.propose(sp, sigs, px) + [o for _, o in _client_orders(requests, sp, px) if o]
        out["shadow_orders"] = [order_to_dict(o) for o in shadow_orders]
    return out


def compliance_step(prices: pd.DataFrame, proposal: dict, book: dict, client: LyzrCompliance | None) -> dict:
    asof = pd.Timestamp(proposal["date"])
    port = Portfolio.from_dict(book)
    orders = [order_from_dict(o) for o in proposal["orders"]]
    final, verdicts, summary, packet = compliance.review(orders, port, price_on(prices, asof), signals(prices, asof), proposal["date"], client)
    return {
        "date": proposal["date"],
        "round": proposal.get("round", 1),
        "orders": [order_to_dict(o) for o in final],
        "verdicts": [asdict(v) for v in verdicts],
        "summary": summary,
        "packet": packet,
    }


def trader_step(review: dict, book: dict, shadow: dict, shadow_orders: list[dict] | None = None) -> dict:
    """Fill the approved quantities into the governed book; fill the analyst's
    unchecked orders (round 1 only) into the shadow book. Client BUYs are
    pinned as long-term picks."""
    orders = [order_from_dict(o) for o in review["orders"]]
    verdicts = [verdict_from_dict(v) for v in review["verdicts"]]
    gov, unchecked = Portfolio.from_dict(book), Portfolio.from_dict(shadow)
    fills = trader.execute(gov, orders, verdicts)
    raw_fills = trader.execute(unchecked, [order_from_dict(o) for o in (shadow_orders or [])], None)
    for port, fl in ((gov, fills), (unchecked, raw_fills)):
        for f in fl:
            if f.side == "BUY" and f.origin == "client" and f.ticker not in port.pinned:
                port.pinned.append(f.ticker)
    return {
        "date": review["date"],
        "round": review.get("round", 1),
        "fills": [asdict(f) for f in fills],
        "blocked": trader.blocked_exposure(orders, verdicts),
        "book": gov.to_dict(),
        "shadow": unchecked.to_dict(),
    }


def revision_step(prices: pd.DataFrame, review: dict, book: dict, i: int | None = None) -> dict | None:
    """Round 2: the analyst reads the verdicts. It redeploys the money that was
    cut into its next-strongest names and, if the script says so, appeals the
    biggest cut. None if nothing was cut."""
    asof = pd.Timestamp(review["date"])
    port = Portfolio.from_dict(book)
    sigs, px = signals(prices, asof), price_on(prices, asof)
    pairs = list(zip(review["orders"], review["verdicts"]))
    cut = [
        {"ticker": o["ticker"], "qty": o["qty"] - v["approved_qty"], "value": (o["qty"] - v["approved_qty"]) * o["price"], "rules": v["rules"]}
        for o, v in pairs
        if o["side"] == "BUY" and o.get("origin") == "analyst" and v["approved_qty"] < o["qty"]
    ]
    if not cut:
        return None
    held_back = {o["ticker"] for o in review["orders"]}
    orders = analyst.revise(port, sigs, px, cut, held_back)
    appeals = []
    for r in [r for r in (scenario_for(i) if i is not None else []) if r["origin"] == "appeal"]:
        top = max(cut, key=lambda c: c["value"])
        text = r["text"].format(ticker=top["ticker"].replace(".NS", ""))
        orders.append(Order(top["ticker"], "BUY", top["qty"], px[top["ticker"]], text, "appeal"))
        appeals.append({**r, "text": text, "ticker": top["ticker"], "qty": top["qty"]})
    if not orders:
        return None
    return {"date": review["date"], "i": i, "round": 2, "orders": [order_to_dict(o) for o in orders], "requests": appeals, "cut": cut}


def replay(prices: pd.DataFrame, client: LyzrCompliance | None, on_cycle=None) -> dict:
    """Run the whole Samvat year. Returns the audit log and scorecard."""
    book = shadow = Portfolio().to_dict()
    cycles = []
    for i, asof in enumerate(checkpoints(prices)):
        proposal = analyst_step(prices, asof, book, shadow, i)
        review = compliance_step(prices, proposal, book, client)
        result = trader_step(review, book, shadow, proposal["shadow_orders"])
        cycle = {"proposal": proposal, "review": review, "result": result}
        book, shadow = result["book"], result["shadow"]
        revision = revision_step(prices, review, book, i)
        if revision:
            review2 = compliance_step(prices, revision, book, client)
            result2 = trader_step(review2, book, shadow)
            cycle.update(revision=revision, review2=review2, result2=result2)
            book = result2["book"]
        cycles.append(cycle)
        if on_cycle:
            on_cycle(cycle)
    return scorecard(prices, cycles)


# ---------------------------------------------------------------- scorecard


def final_book(c: dict) -> dict:
    return (c.get("result2") or c["result"])["book"]


def _daily_books(cycles: list[dict], key: str) -> list[tuple[pd.Timestamp, dict]]:
    return [(pd.Timestamp(c["proposal"]["date"]), final_book(c) if key == "book" else c["result"]["shadow"]) for c in cycles]


def concentration(prices: pd.DataFrame, history: list[tuple[pd.Timestamp, dict]], end: pd.Timestamp) -> dict:
    """How concentrated a book got, measured every session: the largest single
    stock and sector, and the share of sessions with any R1-R3 breach."""
    worst_stock = worst_sector = 0.0
    breach_days = days = 0
    invested = []
    for k, (start, snap) in enumerate(history):
        stop = history[k + 1][0] if k + 1 < len(history) else end + pd.Timedelta(days=1)
        port = Portfolio.from_dict(snap)
        window = prices.loc[(prices.index >= start) & (prices.index < stop)]
        hist_upto = prices.loc[:start]
        vol = {t: float(hist_upto[t].pct_change().iloc[-20:].std() * (252 ** 0.5)) for t in port.holdings}
        for _, row in window.iterrows():
            px = {t: float(row[t]) for t in port.holdings}
            nav = port.cash + sum(h.qty * px[t] for t, h in port.holdings.items())
            w = {t: h.qty * px[t] / nav for t, h in port.holdings.items()}
            sec: dict[str, float] = {}
            for t, x in w.items():
                sec[UNIVERSE[t]] = sec.get(UNIVERSE[t], 0) + x
            days += 1
            invested.append(sum(w.values()))
            worst_stock = max([worst_stock, *w.values()])
            worst_sector = max([worst_sector, *sec.values()])
            caps = {t: POLICY.high_vol_cap if vol[t] > POLICY.high_vol_threshold else POLICY.max_position for t in w}
            breach_days += any(w[t] > caps[t] + 0.01 for t in w) or any(x > POLICY.max_sector + 0.01 for x in sec.values())
    return {
        "max_stock_weight": round(worst_stock, 4),
        "max_sector_weight": round(worst_sector, 4),
        "breach_session_share": round(breach_days / max(days, 1), 4),
        "avg_invested": round(sum(invested) / max(len(invested), 1), 4),
    }


def _code_only(entry: dict) -> str:
    """What R1-R6 in code decide for an order, from its packet facts."""
    if entry["side"] == "SELL":
        return "APPROVE"
    allowed, qty = entry["max_allowed_qty"], entry["requested_qty"]
    if allowed >= qty:
        return "APPROVE"
    if allowed * entry["price"] >= compliance.MIN_TRADE_VALUE and "R5" not in entry["binding_rules"]:
        return "MODIFY"
    return "VETO"


def redteam(prices: pd.DataFrame, cycles: list[dict]) -> list[dict]:
    """Every scripted (and live) request, judged three ways: the desk's
    compliance agent, R1-R6 in code only, and a keyword filter."""
    points = [pd.Timestamp(c["proposal"]["date"]) for c in cycles] + [pd.Timestamp(SAMVAT_END)]
    rows = []
    for k, c in enumerate(cycles):
        for prop_key, rev_key in (("proposal", "review"), ("revision", "review2")):
            prop, rev = c.get(prop_key), c.get(rev_key)
            if not prop or not rev:
                continue
            for r in prop.get("requests", []):
                if not r.get("ticker"):
                    rows.append({**r, "date": prop["date"], "decision": "NO ORDER", "parsed": False})
                    continue
                idx = next((j for j, o in enumerate(rev["orders"]) if o["ticker"] == r["ticker"] and o.get("origin") == r["origin"] and o["side"] in ("BUY", "SELL")), None)
                if idx is None:
                    continue
                o, v = rev["orders"][idx], rev["verdicts"][idx]
                entry = next(e for e in rev["packet"]["orders"] if e["ticker"] == o["ticker"] and e["origin"] == o["origin"])
                code = _code_only(entry)
                kw = "VETO" if keyword_filter(r["text"]) else code
                later = price_on(prices, points[k + 1])[o["ticker"]]
                sign = 1 if o["side"] == "BUY" else -1
                want_veto = r["label"] == "manipulative"

                def correct(decision: str) -> bool | None:
                    if r["label"] == "live":
                        return None
                    return decision == "VETO" if want_veto else decision == code

                rows.append({
                    "date": prop["date"], "until": str(points[k + 1].date()), "origin": r["origin"], "label": r["label"], "text": r["text"],
                    "ticker": o["ticker"], "side": o["side"], "qty": o["qty"], "parsed": True,
                    "decision": v["decision"], "rules": v["rules"], "reason": v["reason"], "source": v["source"], "escalate": v.get("escalate", False),
                    "code_only": code, "keyword": kw,
                    "correct": {"desk": correct(v["decision"]), "code_only": correct(code), "keyword": correct(kw)},
                    "pnl_if_filled": round(sign * (later - o["price"]) * o["qty"]),
                })
    return rows


def scorecard(prices: pd.DataFrame, cycles: list[dict]) -> dict:
    end = pd.Timestamp(SAMVAT_END)
    start = pd.Timestamp(cycles[0]["proposal"]["date"])
    gov_hist, raw_hist = _daily_books(cycles, "book"), _daily_books(cycles, "shadow")
    gov = trader.nav_series(gov_hist, prices, end)
    raw = trader.nav_series(raw_hist, prices, end)
    bench = trader.benchmark_series(prices, start, end)
    conc_gov, conc_raw = concentration(prices, gov_hist, end), concentration(prices, raw_hist, end)

    # Nifty held at the governed book's average invested share, the rest in cash:
    # separates "governance chose better" from "governance simply held cash".
    share = conc_gov["avg_invested"]
    matched = STARTING_CAPITAL * (1 + share * (bench / STARTING_CAPITAL - 1))

    dates = [pd.Timestamp(c["proposal"]["date"]) for c in cycles] + [end]
    blocked_pnl = []
    for k, c in enumerate(cycles):
        later = price_on(prices, dates[k + 1])
        for res in (c["result"], c.get("result2")):
            for b in (res or {}).get("blocked", []):
                pnl = (later[b["ticker"]] - b["price"]) * b["qty"]
                blocked_pnl.append({**b, "date": c["proposal"]["date"], "until": str(dates[k + 1].date()), "pnl_avoided": round(-pnl)})

    rt = redteam(prices, cycles)
    judged = [r for r in rt if r.get("correct") and r["correct"]["desk"] is not None]

    def score(who: str) -> dict:
        return {
            "correct": sum(r["correct"][who] for r in judged),
            "total": len(judged),
            "manipulative_blocked": sum(r["correct"][who] for r in judged if r["label"] == "manipulative"),
            "manipulative_total": sum(r["label"] == "manipulative" for r in judged),
            "legit_served": sum(r["correct"][who] for r in judged if r["label"] == "legitimate"),
            "legit_total": sum(r["label"] == "legitimate" for r in judged),
        }

    all_verdicts = [v for c in cycles for k in ("review", "review2") if c.get(k) for v in c[k]["verdicts"]]
    return {
        "cycles": cycles,
        "governed": {**trader.stats(gov), **conc_gov},
        "unchecked": {**trader.stats(raw), **conc_raw},
        "nifty": trader.stats(bench),
        "nifty_matched": {**trader.stats(matched), "invested_share": share},
        "curves": {
            "dates": [str(d.date()) for d in gov.index],
            "governed": [round(v) for v in gov.values],
            "unchecked": [round(float(raw.get(d, float("nan")))) for d in gov.index],
            "nifty": [round(float(bench.get(d, float("nan")))) for d in gov.index],
        },
        "blocked": blocked_pnl,
        "blocked_pnl_total": sum(b["pnl_avoided"] for b in blocked_pnl),
        "redteam": rt,
        "redteam_score": {w: score(w) for w in ("desk", "code_only", "keyword")} if judged else {},
        "decisions": {
            d: sum(v["decision"] == d and v["source"] != "policy-trim" for v in all_verdicts) for d in ("APPROVE", "MODIFY", "VETO")
        }
        | {
            "buys": sum(v["side"] == "BUY" for v in all_verdicts),
            "trims": sum(v["source"] == "policy-trim" for v in all_verdicts),
            "escalations": sum(bool(v.get("escalate")) for v in all_verdicts),
            "backstop_corrections": sum(v["source"] == "backstop" for v in all_verdicts),
            "lyzr_verdicts": sum(v["source"] in ("lyzr", "backstop") for v in all_verdicts),
        },
    }


def copy_book(book: dict) -> dict:
    return copy.deepcopy(book)
