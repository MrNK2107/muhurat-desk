"""Trader: fills what Compliance approved into the governed book, and fills the
analyst's raw proposal into a shadow "unchecked" book, so the desk can measure
exactly what governance changed. Also produces the year-end scorecard."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from desk.config import BENCHMARK, STARTING_CAPITAL
from desk.portfolio import Order, Portfolio, Verdict


@dataclass
class Fill:
    ticker: str
    side: str
    qty: int
    price: float
    cost: float


def execute(port: Portfolio, orders: list[Order], verdicts: list[Verdict] | None) -> list[Fill]:
    """Fill orders at their price. With verdicts, use each approved quantity."""
    fills = []
    approved = {(v.ticker, v.side): v.approved_qty for v in verdicts} if verdicts is not None else None
    for o in orders:
        qty = o.qty if approved is None else approved.get((o.ticker, o.side), 0)
        if qty <= 0:
            continue
        order = Order(o.ticker, o.side, qty, o.price)
        cost = port.apply(order)
        if order.qty > 0:
            fills.append(Fill(o.ticker, o.side, order.qty, o.price, round(cost, 2)))
    return fills


def blocked_exposure(orders: list[Order], verdicts: list[Verdict]) -> list[dict]:
    """The part of each BUY that Compliance cut: what the analyst wanted minus
    what was approved. Used to measure whether the cuts helped."""
    by_key = {(v.ticker, v.side): v for v in verdicts}
    out = []
    for o in orders:
        v = by_key.get((o.ticker, o.side))
        if o.side == "BUY" and v and v.approved_qty < o.qty:
            out.append({"ticker": o.ticker, "qty": o.qty - v.approved_qty, "price": o.price, "decision": v.decision, "rules": v.rules})
    return out


def max_drawdown(series: pd.Series) -> float:
    peak = series.cummax()
    return float((series / peak - 1).min())


def stats(series: pd.Series) -> dict:
    rets = series.pct_change().dropna()
    vol = float(rets.std() * math.sqrt(252))
    total = float(series.iloc[-1] / series.iloc[0] - 1)
    years = max((series.index[-1] - series.index[0]).days / 365.25, 1e-9)
    cagr = (1 + total) ** (1 / years) - 1
    rf = 0.065  # Indian T-bill, approx.
    sharpe = (cagr - rf) / vol if vol > 0 else 0.0
    return {
        "total_return": round(total, 4),
        "max_drawdown": round(max_drawdown(series), 4),
        "volatility": round(vol, 4),
        "sharpe": round(sharpe, 2),
        "final_value": round(float(series.iloc[-1])),
    }


def nav_series(history: list[tuple[pd.Timestamp, dict]], prices: pd.DataFrame, end: pd.Timestamp) -> pd.Series:
    """Daily mark-to-market NAV from a list of (checkpoint date, book snapshot)."""
    values = {}
    for i, (start, snap) in enumerate(history):
        stop = history[i + 1][0] if i + 1 < len(history) else end + pd.Timedelta(days=1)
        port = Portfolio.from_dict(snap)
        window = prices.loc[(prices.index >= start) & (prices.index < stop)]
        for day, row in window.iterrows():
            values[day] = port.cash + sum(h.qty * float(row[t]) for t, h in port.holdings.items())
    return pd.Series(values).sort_index()


def benchmark_series(prices: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    s = prices.loc[(prices.index >= start) & (prices.index <= end), BENCHMARK]
    return s / s.iloc[0] * STARTING_CAPITAL
