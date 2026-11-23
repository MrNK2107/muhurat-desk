"""Offline tests: no network, no Band, no Lyzr. They pin down the guarantees
the desk makes: no lookahead, the book never leaves policy, the backstop
catches an over-generous LLM verdict, and messages round-trip."""

from __future__ import annotations

import copy

import pandas as pd
import pytest

from agents.common import parse_payload, render
from desk import analyst, compliance
from desk.config import POLICY, UNIVERSE
from desk.engine import analyst_step, compliance_step, replay, trader_step
from desk.market import checkpoints, load_prices, price_on, signals
from desk.portfolio import Order, Portfolio, Verdict


@pytest.fixture(scope="module")
def prices() -> pd.DataFrame:
    return load_prices()


@pytest.fixture(scope="module")
def year(prices):
    return replay(prices, None)


def test_signals_never_see_the_future(prices):
    asof = checkpoints(prices)[3]
    future = prices.copy()
    future.loc[future.index > asof] *= 5  # wildly different future
    assert signals(prices, asof) == signals(future, asof)


def test_checkpoints_start_on_muhurat_day(prices):
    points = checkpoints(prices)
    assert str(points[0].date()) == "2025-10-21"
    assert len(points) == 14


def test_portfolio_never_overspends():
    p = Portfolio(cash=10_000)
    p.apply(Order("TCS.NS", "BUY", 100, 3_000))
    assert p.cash >= 0 and p.holdings["TCS.NS"].qty == 3


def test_sell_is_capped_at_holding():
    p = Portfolio(cash=0)
    p.apply(Order("TCS.NS", "BUY", 0, 1))
    p.holdings = {"TCS.NS": __import__("desk.portfolio", fromlist=["Holding"]).Holding(qty=5, avg_cost=100)}
    o = Order("TCS.NS", "SELL", 50, 100)
    p.apply(o)
    assert o.qty == 5 and "TCS.NS" not in p.holdings


def test_analyst_alone_breaks_the_policy(prices):
    """The analyst is meant to be aggressive: on Muhurat day its raw target
    puts more than R1 allows into one stock. Otherwise the demo is hollow."""
    sigs = signals(prices, checkpoints(prices)[0])
    assert max(analyst.target_weights(sigs).values()) > POLICY.max_position


def test_every_buy_lands_inside_policy(prices, year):
    """The policy limits the book right after a trade. A holding may drift
    above a limit as its price rises, but no BUY may take it (or its sector)
    over one, and cash never drops below the buffer through buying."""
    for c in year["cycles"]:
        asof = pd.Timestamp(c["proposal"]["date"])
        px = price_on(prices, asof)
        book = Portfolio.from_dict(c["result"]["book"])
        nav = book.nav(px)
        sigs = signals(prices, asof)
        weights, sectors = book.weights(px), book.sector_weights(px)
        bought = {f["ticker"] for f in c["result"]["fills"] if f["side"] == "BUY"}
        for t in bought:
            cap = POLICY.high_vol_cap if sigs[t].vol_20d > POLICY.high_vol_threshold else POLICY.max_position
            assert weights[t] <= cap + 0.005, (asof, t, weights[t])
            assert sectors[UNIVERSE[t]] <= POLICY.max_sector + 0.005, (asof, t, sectors[UNIVERSE[t]])
        if bought:
            assert book.cash >= POLICY.min_cash * nav - 1


def test_unchecked_book_does_break_policy(prices, year):
    breaches = 0
    for c in year["cycles"]:
        px = price_on(prices, pd.Timestamp(c["proposal"]["date"]))
        shadow = Portfolio.from_dict(c["result"]["shadow"])
        breaches += any(w > POLICY.max_position + 0.005 for w in shadow.weights(px).values())
    assert breaches > 0


def test_backstop_clamps_an_overgenerous_llm(prices):
    asof = checkpoints(prices)[0]
    port = Portfolio()
    px, sigs = price_on(prices, asof), signals(prices, asof)
    orders = analyst.propose(port, sigs, px)
    facts = compliance.risk_facts(orders, port, px, sigs)
    reckless = [Verdict(o.ticker, o.side, "APPROVE", o.qty, [], "looks fine") for o in orders]
    fixed = compliance.backstop(reckless, orders, facts)
    for v, f in zip(fixed, facts):
        assert v.approved_qty <= f["policy_allowed_qty"]
    assert any(v.source == "backstop" for v in fixed)


def test_label_follows_quantity():
    o = Order("TCS.NS", "BUY", 100, 3_000)
    ref = Verdict("TCS.NS", "BUY", "MODIFY", 40, ["R1"])
    v = compliance._normalise(Verdict("TCS.NS", "BUY", "APPROVE", 40, []), o, ref)
    assert v.decision == "MODIFY" and v.rules == ["R1"]


def test_missing_lyzr_verdict_falls_back_to_policy(prices):
    asof = checkpoints(prices)[0]
    port = Portfolio()
    px, sigs = price_on(prices, asof), signals(prices, asof)
    orders = analyst.propose(port, sigs, px)
    facts = compliance.risk_facts(orders, port, px, sigs)
    fixed = compliance.backstop([], orders, facts)
    assert len(fixed) == len(orders) and all(v.source == "backstop" for v in fixed)


def test_one_cycle_through_the_stage_functions(prices):
    book = Portfolio().to_dict()
    proposal = analyst_step(prices, checkpoints(prices)[0], book)
    review = compliance_step(prices, proposal, book, None)
    result = trader_step(proposal, review, book, copy.deepcopy(book))
    assert result["fills"] and result["book"]["cash"] < 1_000_000
    assert set(result["book"]["holdings"]) <= set(UNIVERSE)


def test_message_round_trip():
    payload = {"stage": "proposal", "orders": [{"ticker": "TCS.NS", "qty": 3}]}
    assert parse_payload(render("note with **markdown**", payload)) == payload
    assert parse_payload("plain human message") is None


def test_governance_reduces_drawdown(year):
    assert year["governed"]["max_drawdown"] > year["unchecked"]["max_drawdown"]
