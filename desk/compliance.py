"""Compliance: every proposed trade is checked against the desk risk policy.

Three layers, in order:
1. ``risk_facts`` computes the numbers a compliance officer needs (weights after
   the trade, sector exposure, volatility, headroom under each rule).
2. A Lyzr agent reads the policy and the facts and returns a structured verdict
   per order: APPROVE, MODIFY (with a new quantity) or VETO, citing rule ids.
3. ``backstop`` re-checks Lyzr's verdicts against the hard limits in code. If an
   approved quantity would still breach a limit it is clamped and the verdict is
   marked ``backstop``, so an LLM mistake can never put the book out of policy.

If Lyzr is unavailable, ``local_verdicts`` applies the same policy in code."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

import httpx

from desk.config import LYZR_CACHE, POLICY, UNIVERSE, RiskPolicy
from desk.market import Signal
from desk.portfolio import Order, Portfolio, Verdict

LYZR_BASE = "https://agent-prod.studio.lyzr.ai"
MIN_TRADE_VALUE = 5_000.0

VERDICT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "ComplianceReview",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["verdicts", "summary"],
            "properties": {
                "summary": {"type": "string"},
                "verdicts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["ticker", "side", "decision", "approved_qty", "rules", "reason"],
                        "properties": {
                            "ticker": {"type": "string"},
                            "side": {"type": "string", "enum": ["BUY", "SELL"]},
                            "decision": {"type": "string", "enum": ["APPROVE", "MODIFY", "VETO"]},
                            "approved_qty": {"type": "integer"},
                            "rules": {"type": "array", "items": {"type": "string"}},
                            "reason": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
}

INSTRUCTIONS = f"""You are the compliance officer of Muhurat Desk, an educational paper-trading desk.
An aggressive momentum analyst proposes trades. Your job is to protect the book.

{POLICY.as_text()}

You receive a JSON review packet: the portfolio NAV and cash, and for every proposed order the
risk facts computed by the desk's risk system. Percentages are already computed; quote them as given.
"max_qty_by_rule" is the largest quantity each rule allows, "max_allowed_qty" is the smallest of
them, and "binding_rules" lists the rules that are tighter than the request. Earlier orders in the
list are assumed filled as the policy allows.

For EVERY order return exactly one verdict:
- SELL orders reduce risk: APPROVE them at the requested quantity.
- BUY orders:
  - requested_qty <= max_allowed_qty: APPROVE at requested_qty, rules = [].
  - max_allowed_qty * price >= {MIN_TRADE_VALUE:.0f} INR and R5 is not binding: MODIFY, approved_qty = max_allowed_qty, rules = binding_rules.
  - otherwise: VETO, approved_qty = 0, rules = binding_rules.
  You may be stricter than the numbers (VETO or a smaller MODIFY) only with a clear policy reason, never looser.
- The decision label must match the quantity: approved_qty == requested_qty is APPROVE, 0 is VETO, anything in between is MODIFY.
- reason: one plain sentence a retail investor understands, with the actual numbers. Good examples:
  "MODIFY: 837 shares would make ETERNAL 28% of the book; R1 caps one stock at 15%, so 443 shares."
  "VETO: Financials are already 34% of the book and R2 caps a sector at 35%."
  "APPROVE: lands at 9% of NAV, inside every limit."
- summary: two sentences for the trading room: what you approved, what you cut and why.
Cite rules only as R1..R6. Never invent rules or numbers. Output JSON only."""


# ---------------------------------------------------------------- risk facts


def _max_qty(order: Order, port: Portfolio, prices: dict[str, float], sigs: dict[str, Signal], nav: float, policy: RiskPolicy) -> dict[str, int]:
    """Largest BUY quantity each rule allows on the current (simulated) book."""
    price = order.price
    held = port.holdings.get(order.ticker)
    held_value = held.qty * prices[order.ticker] if held else 0.0
    sector = UNIVERSE[order.ticker]
    sector_value = sum(h.qty * prices[t] for t, h in port.holdings.items() if UNIVERSE[t] == sector)
    vol = sigs[order.ticker].vol_20d if order.ticker in sigs else 0.0
    cap = policy.high_vol_cap if vol > policy.high_vol_threshold else policy.max_position
    unit = price * 1.001

    def q(value: float) -> int:
        return max(int(value / unit), 0)

    out = {
        "R1" if cap == policy.max_position else "R3": q(cap * nav - held_value),
        "R2": q(policy.max_sector * nav - sector_value),
        "R4": q(port.cash - policy.min_cash * nav),
    }
    if held and price / held.avg_cost - 1 < policy.no_average_down:
        out["R5"] = 0
    return out


def risk_facts(orders: list[Order], port: Portfolio, prices: dict[str, float], sigs: dict[str, Signal], policy: RiskPolicy = POLICY) -> list[dict]:
    """Facts per order, computed on a simulated book where every earlier order
    is filled at the quantity the policy allows (sells first)."""
    sim = copy.deepcopy(port)
    nav = port.nav(prices)
    facts = []
    for o in orders:
        held = sim.holdings.get(o.ticker)
        f = {
            "ticker": o.ticker,
            "side": o.side,
            "requested_qty": o.qty,
            "price": round(o.price, 2),
            "requested_value": round(o.value),
            "sector": UNIVERSE[o.ticker],
            "vol_20d_annualised": round(sigs[o.ticker].vol_20d, 3) if o.ticker in sigs else None,
            "current_weight": round((held.qty * prices[o.ticker] / nav) if held else 0.0, 4),
            "weight_if_filled_in_full": round(((held.qty if held else 0) * prices[o.ticker] + (o.value if o.side == "BUY" else -o.value)) / nav, 4),
            "vs_avg_cost": round(o.price / held.avg_cost - 1, 4) if held else None,
            "analyst_reason": o.reason,
        }
        sector_now = sum(h.qty * prices[t] for t, h in sim.holdings.items() if UNIVERSE[t] == UNIVERSE[o.ticker]) / nav
        if o.side == "BUY":
            caps = _max_qty(o, sim, prices, sigs, nav, policy)
            f["max_qty_by_rule"] = caps
            allowed = min([o.qty, *caps.values()])
            f["binding_rules"] = sorted(r for r, q in caps.items() if q < o.qty)
            f["sector_weight_if_filled_in_full"] = f"{sector_now + o.value / nav:.1%}"
        else:
            allowed = min(o.qty, held.qty if held else 0)
            f["binding_rules"] = []
        f["max_allowed_qty"] = allowed
        f["policy_allowed_qty"] = allowed
        f["current_weight"] = f"{f['current_weight']:.1%}"
        f["weight_if_filled_in_full"] = f"{f['weight_if_filled_in_full']:.1%}"
        f["weight_at_max_allowed_qty"] = f"{((held.qty if held else 0) + (allowed if o.side == 'BUY' else -allowed)) * prices[o.ticker] / nav:.1%}"
        if f["vol_20d_annualised"] is not None:
            f["vol_20d_annualised"] = f"{f['vol_20d_annualised']:.0%}"
        if f["vs_avg_cost"] is not None:
            f["vs_avg_cost"] = f"{f['vs_avg_cost']:+.1%}"
        facts.append(f)
        sim.apply(Order(o.ticker, o.side, allowed, o.price))
    return facts


def local_verdicts(orders: list[Order], facts: list[dict]) -> list[Verdict]:
    """The same policy in deterministic code. Used when Lyzr is unreachable and
    as the reference the backstop checks Lyzr against."""
    out = []
    for o, f in zip(orders, facts):
        allowed = f["policy_allowed_qty"]
        if o.side == "SELL":
            out.append(Verdict(o.ticker, o.side, "APPROVE", allowed, [], "Selling reduces risk.", "local-policy"))
            continue
        binding = sorted(r for r, q in f.get("max_qty_by_rule", {}).items() if q < o.qty)
        if allowed >= o.qty:
            out.append(Verdict(o.ticker, o.side, "APPROVE", o.qty, [], "Within every limit.", "local-policy"))
        elif allowed * o.price >= MIN_TRADE_VALUE and "R5" not in binding:
            out.append(Verdict(o.ticker, o.side, "MODIFY", allowed, binding, f"Resized to stay inside {', '.join(binding)}.", "local-policy"))
        else:
            out.append(Verdict(o.ticker, o.side, "VETO", 0, binding, f"Blocked by {', '.join(binding)}.", "local-policy"))
    return out


def backstop(verdicts: list[Verdict], orders: list[Order], facts: list[dict]) -> list[Verdict]:
    """Align Lyzr's verdicts to the orders and clamp anything over the limit."""
    by_key = {(v.ticker, v.side): v for v in verdicts}
    reference = local_verdicts(orders, facts)
    out = []
    for o, f, ref in zip(orders, facts, reference):
        v = by_key.get((o.ticker, o.side))
        if v is None:
            ref.source = "backstop"
            ref.reason = "Lyzr returned no verdict for this order; desk policy applied. " + ref.reason
            out.append(ref)
            continue
        limit = f["policy_allowed_qty"]
        if v.approved_qty > limit:
            v = Verdict(
                o.ticker, o.side,
                "VETO" if ref.decision == "VETO" else "MODIFY",
                ref.approved_qty, sorted(set(v.rules) | set(ref.rules)),
                f"Backstop: Lyzr approved {v.approved_qty}, policy allows {ref.approved_qty}. " + v.reason,
                "backstop",
            )
        else:
            v.approved_qty = max(v.approved_qty, 0)
        out.append(_normalise(v, o, ref))
    return out


def _normalise(v: Verdict, o: Order, ref: Verdict) -> Verdict:
    """Make the label agree with the quantity (an LLM sometimes says APPROVE
    while cutting the size) and make sure every cut cites a rule."""
    if v.approved_qty >= o.qty:
        v.decision, v.approved_qty = "APPROVE", o.qty
    elif v.approved_qty == 0:
        v.decision = "VETO"
    else:
        v.decision = "MODIFY"
    if v.decision != "APPROVE" and not v.rules:
        v.rules = list(ref.rules)
    if v.decision == "APPROVE":
        v.rules = []
    return v


# ---------------------------------------------------------------- Lyzr client


def lyzr_key() -> str | None:
    key = os.environ.get("LYZR_API_KEY")
    if key:
        return key.strip()
    path = Path.home() / ".secrets" / "lyzr.key"
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


def lyzr_agent_id() -> str | None:
    if os.environ.get("LYZR_AGENT_ID"):
        return os.environ["LYZR_AGENT_ID"]
    path = LYZR_CACHE.parent / "lyzr_agent.json"
    return json.loads(path.read_text())["agent_id"] if path.exists() else None


def lyzr_model() -> str:
    path = LYZR_CACHE.parent / "lyzr_agent.json"
    return json.loads(path.read_text()).get("model", "") if path.exists() else ""


class LyzrCompliance:
    """Calls the Lyzr compliance agent. Responses are cached on disk by a hash
    of the review packet, so a rehearsal replay costs zero credits."""

    def __init__(self, cache_path: Path = LYZR_CACHE, offline: bool = False):
        self.cache_path = cache_path
        self.cache: dict = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        self.offline = offline or os.environ.get("LYZR_OFFLINE") == "1"
        self.calls = 0

    def review(self, packet: dict) -> dict | None:
        message = json.dumps(packet, sort_keys=True)
        key = hashlib.sha256(f"{lyzr_model()}|{message}".encode()).hexdigest()[:24]
        if key in self.cache:
            return self.cache[key]
        if self.offline:
            return None
        api_key, agent_id = lyzr_key(), lyzr_agent_id()
        if not api_key or not agent_id:
            return None
        resp = httpx.post(
            f"{LYZR_BASE}/v3/inference/chat/",
            headers={"x-api-key": api_key},
            json={"agent_id": agent_id, "user_id": "muhurat-desk", "session_id": f"review-{key}", "message": message},
            timeout=90,
        )
        resp.raise_for_status()
        self.calls += 1
        text = resp.json().get("response", "")
        parsed = json.loads(text[text.find("{"): text.rfind("}") + 1])
        self.cache[key] = parsed
        self.cache_path.write_text(json.dumps(self.cache, indent=1, sort_keys=True))
        return parsed


def review(orders: list[Order], port: Portfolio, prices: dict[str, float], sigs: dict[str, Signal], asof: str, client: LyzrCompliance | None) -> tuple[list[Verdict], str, dict]:
    """Full compliance pass. Returns verdicts, a summary for the room, and the
    review packet (kept in the audit log)."""
    facts = risk_facts(orders, port, prices, sigs)
    nav = port.nav(prices)
    packet = {
        "date": asof,
        "nav": round(nav),
        "cash": round(port.cash),
        "sector_weights": {k: round(v, 4) for k, v in port.sector_weights(prices).items()},
        "orders": [{k: v for k, v in f.items() if k != "policy_allowed_qty"} for f in facts],
    }
    result = None
    if client is not None and orders:
        try:
            result = client.review(packet)
        except (httpx.HTTPError, ValueError) as exc:  # network, quota, or malformed JSON
            print(f"[compliance] Lyzr unavailable ({type(exc).__name__}); applying desk policy locally")
    if result:
        raw = [Verdict(source="lyzr", **{k: v[k] for k in ("ticker", "side", "decision", "approved_qty", "rules", "reason")}) for v in result.get("verdicts", [])]
        return backstop(raw, orders, facts), result.get("summary", ""), packet
    verdicts = local_verdicts(orders, facts)
    cut = [v for v in verdicts if v.decision != "APPROVE"]
    summary = f"Local policy engine reviewed {len(orders)} orders; {len(cut)} resized or vetoed."
    return verdicts, summary, packet


def verdict_dict(v: Verdict) -> dict:
    return asdict(v)
