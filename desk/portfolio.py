"""Paper portfolio and order types shared by all three agents. Plain data,
serialisable to JSON so the state can travel between agents in Band messages."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from desk.config import COST_RATE, STARTING_CAPITAL, UNIVERSE


@dataclass
class Holding:
    qty: int
    avg_cost: float


@dataclass
class Order:
    ticker: str
    side: str  # BUY or SELL
    qty: int
    price: float
    reason: str = ""  # the rationale, in the requester's own words
    origin: str = "analyst"  # analyst, client, appeal or compliance (a forced trim)

    @property
    def value(self) -> float:
        return self.qty * self.price


@dataclass
class Verdict:
    ticker: str
    side: str
    decision: str  # APPROVE, MODIFY or VETO
    approved_qty: int
    rules: list[str] = field(default_factory=list)
    reason: str = ""
    source: str = "lyzr"  # lyzr, local-policy, backstop or policy-trim
    escalate: bool = False  # R8: someone tried to override the policy


@dataclass
class Portfolio:
    cash: float = STARTING_CAPITAL
    holdings: dict[str, Holding] = field(default_factory=dict)
    pinned: list[str] = field(default_factory=list)  # client long-term picks the analyst won't rotate out of

    def nav(self, prices: dict[str, float]) -> float:
        return self.cash + sum(h.qty * prices[t] for t, h in self.holdings.items())

    def weights(self, prices: dict[str, float]) -> dict[str, float]:
        total = self.nav(prices)
        return {t: h.qty * prices[t] / total for t, h in self.holdings.items()}

    def sector_weights(self, prices: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for t, w in self.weights(prices).items():
            out[UNIVERSE[t]] = out.get(UNIVERSE[t], 0.0) + w
        return out

    def apply(self, order: Order) -> float:
        """Fill an order at its price. Returns the cost charged. SELLs are
        capped at the quantity held; BUYs are capped at available cash."""
        if order.qty <= 0:
            return 0.0
        if order.side == "SELL":
            held = self.holdings.get(order.ticker)
            qty = min(order.qty, held.qty if held else 0)
            if qty == 0:
                return 0.0
            gross = qty * order.price
            cost = gross * COST_RATE
            self.cash += gross - cost
            held.qty -= qty
            if held.qty == 0:
                del self.holdings[order.ticker]
            order.qty = qty
            return cost
        affordable = int(self.cash / (order.price * (1 + COST_RATE)))
        qty = min(order.qty, affordable)
        if qty == 0:
            return 0.0
        gross = qty * order.price
        cost = gross * COST_RATE
        self.cash -= gross + cost
        held = self.holdings.get(order.ticker)
        if held:
            held.avg_cost = (held.avg_cost * held.qty + gross) / (held.qty + qty)
            held.qty += qty
        else:
            self.holdings[order.ticker] = Holding(qty=qty, avg_cost=order.price)
        order.qty = qty
        return cost

    def to_dict(self) -> dict:
        return {
            "cash": round(self.cash, 2),
            "holdings": {t: {"qty": h.qty, "avg_cost": round(h.avg_cost, 4)} for t, h in self.holdings.items()},
            "pinned": sorted(t for t in self.pinned if t in self.holdings),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Portfolio:
        return cls(
            cash=float(d["cash"]),
            holdings={t: Holding(qty=int(h["qty"]), avg_cost=float(h["avg_cost"])) for t, h in d["holdings"].items()},
            pinned=list(d.get("pinned", [])),
        )


def order_to_dict(o: Order) -> dict:
    return asdict(o)


def order_from_dict(d: dict) -> Order:
    return Order(ticker=d["ticker"], side=d["side"], qty=int(d["qty"]), price=float(d["price"]), reason=d.get("reason", ""), origin=d.get("origin", "analyst"))


def verdict_from_dict(d: dict) -> Verdict:
    return Verdict(
        ticker=d["ticker"],
        side=d["side"],
        decision=d["decision"],
        approved_qty=int(d["approved_qty"]),
        rules=list(d.get("rules", [])),
        reason=d.get("reason", ""),
        source=d.get("source", "lyzr"),
        escalate=bool(d.get("escalate", False)),
    )
