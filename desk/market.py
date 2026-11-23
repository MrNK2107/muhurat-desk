"""Market data: a frozen daily close panel for Samvat 2082, plus point-in-time
signals. Every function that takes an ``asof`` date only reads rows on or before
it, so no agent can see the future."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from desk.config import BENCHMARK, DATA_START, PRICES_CSV, SAMVAT_END, SAMVAT_START, UNIVERSE


def fetch_prices(path=PRICES_CSV) -> pd.DataFrame:
    """Download adjusted daily closes once and freeze them to CSV."""
    import yfinance as yf

    tickers = [*UNIVERSE, BENCHMARK]
    end = (pd.Timestamp(SAMVAT_END) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    raw = yf.download(tickers, start=DATA_START, end=end, progress=False, auto_adjust=True)
    closes = raw["Close"][tickers].dropna(how="all").ffill()
    path.parent.mkdir(parents=True, exist_ok=True)
    closes.round(4).to_csv(path)
    return closes


def load_prices(path=PRICES_CSV) -> pd.DataFrame:
    if not path.exists():
        return fetch_prices(path)
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return df.sort_index()


def trading_days(prices: pd.DataFrame) -> pd.DatetimeIndex:
    idx = prices.index
    return idx[(idx >= SAMVAT_START) & (idx <= SAMVAT_END)]


def checkpoints(prices: pd.DataFrame) -> list[pd.Timestamp]:
    """Muhurat day, then the first session of every following month."""
    days = trading_days(prices)
    points = [days[0]]
    seen = {(days[0].year, days[0].month)}
    for d in days[1:]:
        key = (d.year, d.month)
        if key not in seen:
            seen.add(key)
            points.append(d)
    return points


@dataclass(frozen=True)
class Signal:
    ticker: str
    price: float
    mom_3m: float  # 63-session return
    mom_6m: float  # 126-session return (or what history allows)
    vol_20d: float  # annualised
    above_50dma: float  # price / 50-day mean - 1


def signals(prices: pd.DataFrame, asof: pd.Timestamp) -> dict[str, Signal]:
    hist = prices.loc[:asof]
    out: dict[str, Signal] = {}
    for t in UNIVERSE:
        s = hist[t].dropna()
        if len(s) < 60:
            continue
        rets = s.pct_change().dropna()
        lb6 = min(126, len(s) - 1)
        out[t] = Signal(
            ticker=t,
            price=float(s.iloc[-1]),
            mom_3m=float(s.iloc[-1] / s.iloc[-64] - 1),
            mom_6m=float(s.iloc[-1] / s.iloc[-1 - lb6] - 1),
            vol_20d=float(rets.iloc[-20:].std() * math.sqrt(252)),
            above_50dma=float(s.iloc[-1] / s.iloc[-50:].mean() - 1),
        )
    return out


def price_on(prices: pd.DataFrame, asof: pd.Timestamp) -> dict[str, float]:
    row = prices.loc[:asof].iloc[-1]
    return {t: float(row[t]) for t in prices.columns if not math.isnan(row[t])}
