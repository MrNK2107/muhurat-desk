"""Analyst: an aggressive momentum strategy. It ranks the universe by recent
strength, sizes positions by conviction and proposes the trades needed to reach
that target. It knows nothing about the risk policy; that is Compliance's job."""

from __future__ import annotations

import statistics

from desk.market import Signal
from desk.portfolio import Order, Portfolio

TOP_N = 5
MIN_TRADE_VALUE = 5_000.0  # ignore tiny rebalancing trades


def _z(values: dict[str, float]) -> dict[str, float]:
    mu = statistics.fmean(values.values())
    sd = statistics.pstdev(values.values()) or 1.0
    return {k: (v - mu) / sd for k, v in values.items()}


def score(sigs: dict[str, Signal]) -> dict[str, float]:
    """Momentum composite: 3m and 6m strength, rewarded for trading above the
    50-day average. Volatility is deliberately NOT penalised: this desk's
    analyst chases strength, and the risk policy has to catch the excess."""
    m3 = _z({t: s.mom_3m for t, s in sigs.items()})
    m6 = _z({t: s.mom_6m for t, s in sigs.items()})
    trend = _z({t: s.above_50dma for t, s in sigs.items()})
    return {t: 0.5 * m3[t] + 0.3 * m6[t] + 0.2 * trend[t] for t in sigs}


def target_weights(sigs: dict[str, Signal], invest: float = 1.0) -> dict[str, float]:
    """Top-N names, weighted by conviction (score above the cut line)."""
    ranked = sorted(score(sigs).items(), key=lambda kv: kv[1], reverse=True)
    picks = [(t, s) for t, s in ranked[:TOP_N] if sigs[t].mom_3m > 0]
    if not picks:
        return {}
    floor = ranked[TOP_N][1] if len(ranked) > TOP_N else 0.0
    conv = {t: max(s - floor, 0.05) for t, s in picks}
    total = sum(conv.values())
    return {t: invest * c / total for t, c in conv.items()}


def propose(port: Portfolio, sigs: dict[str, Signal], prices: dict[str, float]) -> list[Order]:
    """Orders that move the book to the analyst's target. Sells first, so the
    trader frees cash before buying. Holdings the client pinned as long-term
    picks are left alone and the target is scaled to the rest of the book."""
    nav = port.nav(prices)
    current = port.weights(prices)
    pinned = {t for t in port.pinned if t in current}
    target = {t: w for t, w in target_weights(sigs, 1.0 - sum(current[t] for t in pinned)).items() if t not in pinned}
    ranks = {t: k for k, (t, _) in enumerate(sorted(score(sigs).items(), key=lambda kv: kv[1], reverse=True), start=1)}
    sells, buys = [], []
    for t in sorted((set(target) | set(current)) - pinned):
        delta_value = (target.get(t, 0.0) - current.get(t, 0.0)) * nav
        if abs(delta_value) < MIN_TRADE_VALUE:
            continue
        qty = int(abs(delta_value) / prices[t])
        if qty == 0:
            continue
        s = sigs.get(t)
        if delta_value < 0:
            why = "dropped out of the top momentum names" if t not in target else "trim to target weight"
            sells.append(Order(t, "SELL", qty, prices[t], why))
        else:
            why = f"momentum rank #{ranks[t]} of {len(ranks)}: 3m {s.mom_3m:+.1%}, 6m {s.mom_6m:+.1%}; target {target[t]:.0%} of NAV"
            buys.append(Order(t, "BUY", qty, prices[t], why))
    return sells + buys


def revise(port: Portfolio, sigs: dict[str, Signal], prices: dict[str, float], cut: list[dict], held_back: set[str]) -> list[Order]:
    """The analyst's answer to a review. Compliance cut some BUYs; the analyst
    still wants the money at work, so it offers the cut amount to its
    next-strongest names (it doesn't know the policy, so Compliance will
    resize these too). ``cut`` lists {ticker, value} of what was cut,
    ``held_back`` the names it won't add to (already proposed or vetoed)."""
    value = sum(c["value"] for c in cut)
    if value < 2 * MIN_TRADE_VALUE:
        return []
    ranked = [t for t, _ in sorted(score(sigs).items(), key=lambda kv: kv[1], reverse=True)]
    ranks = {t: k for k, t in enumerate(ranked, start=1)}
    names = [t for t in ranked if t not in held_back and sigs[t].mom_3m > 0][:3]
    if not names:
        return []
    each = value / len(names)
    cut_names = ", ".join(c["ticker"].replace(".NS", "") for c in cut)
    out = []
    for t in names:
        qty = int(each / prices[t])
        if qty * prices[t] >= MIN_TRADE_VALUE:
            s = sigs[t]
            out.append(Order(t, "BUY", qty, prices[t], f"redeploying money cut from {cut_names}: next-strongest name, rank #{ranks[t]}, 3m {s.mom_3m:+.1%}, 6m {s.mom_6m:+.1%}"))
    return out
