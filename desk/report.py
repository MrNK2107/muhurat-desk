"""Self-contained HTML report for a desk run: scorecards, equity curves (inline
SVG, no external assets) and the full compliance audit trail."""

from __future__ import annotations

import html
import math
from pathlib import Path

from jinja2 import Template

SERIES = [("governed", "Governed desk", "var(--gov)"), ("unchecked", "Unchecked analyst", "var(--raw)"), ("nifty", "Nifty 50", "var(--nifty)")]


def _svg(curves: dict, w: int = 960, h: int = 320, pad: int = 48) -> str:
    vals = [v for k, _, _ in SERIES for v in curves[k] if v is not None and not math.isnan(v)]
    lo, hi = min(vals) * 0.98, max(vals) * 1.02
    n = len(curves["dates"])

    def xy(i: int, v: float) -> str:
        x = pad + (w - 2 * pad) * i / max(n - 1, 1)
        y = h - pad - (h - 2 * pad) * (v - lo) / (hi - lo)
        return f"{x:.1f},{y:.1f}"

    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Equity curves">']
    for frac in (0, 0.25, 0.5, 0.75, 1):
        v = lo + (hi - lo) * frac
        y = h - pad - (h - 2 * pad) * frac
        parts.append(f'<line x1="{pad}" x2="{w - pad}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/><text x="{pad - 6}" y="{y + 4:.1f}" class="tick" text-anchor="end">{v / 1e5:.1f}L</text>')
    for i in range(0, n, max(n // 6, 1)):
        x = pad + (w - 2 * pad) * i / max(n - 1, 1)
        parts.append(f'<text x="{x:.1f}" y="{h - pad + 18}" class="tick" text-anchor="middle">{curves["dates"][i][:7]}</text>')
    base_y = h - pad - (h - 2 * pad) * (1_000_000 - lo) / (hi - lo)
    parts.append(f'<line x1="{pad}" x2="{w - pad}" y1="{base_y:.1f}" y2="{base_y:.1f}" class="base"/>')
    for key, _, color in SERIES:
        pts = " ".join(xy(i, v) for i, v in enumerate(curves[key]) if v is not None and not math.isnan(v))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{3 if key == "governed" else 2}" stroke-linejoin="round"/>')
    parts.append("</svg>")
    return "".join(parts)


TEMPLATE = Template(
    """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Muhurat Desk · Samvat 2082</title>
<style>
:root{--bg:#fbf7f0;--card:#fff;--ink:#1f1a14;--mute:#6b6257;--line:#e8dfd2;--gov:#c2410c;--raw:#7c3aed;--nifty:#64748b;--ok:#15803d;--mod:#b45309;--veto:#b91c1c}
@media (prefers-color-scheme:dark){:root{--bg:#14110d;--card:#1d1914;--ink:#f3ece2;--mute:#a69b8c;--line:#3a3229;--gov:#fb923c;--raw:#a78bfa;--nifty:#94a3b8;--ok:#4ade80;--mod:#fbbf24;--veto:#f87171}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:30px;margin:0 0 4px;letter-spacing:-.01em}h2{font-size:18px;margin:36px 0 12px}
.sub{color:var(--mute);margin:0 0 24px}.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.card h3{margin:0 0 8px;font-size:14px;color:var(--mute);font-weight:600;display:flex;gap:8px;align-items:center}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block}
.big{font-size:28px;font-weight:700}.kv{display:grid;grid-template-columns:1fr auto;gap:2px 12px;color:var(--mute);font-size:13px;margin-top:6px}.kv b{color:var(--ink);font-weight:600}
.hero{border-left:4px solid var(--gov)}svg{width:100%;height:auto}svg .grid{stroke:var(--line)}svg .base{stroke:var(--mute);stroke-dasharray:4 4}svg .tick{fill:var(--mute);font-size:11px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mute);font-weight:600}
.b{font-weight:700;font-size:11px;padding:2px 6px;border-radius:6px;border:1px solid currentColor}.APPROVE{color:var(--ok)}.MODIFY{color:var(--mod)}.VETO{color:var(--veto)}
details{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:8px 0}summary{cursor:pointer;font-weight:600}
.note{color:var(--mute);font-size:13px;margin-top:40px}.legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--mute);font-size:13px;margin:8px 0}
.scroll{overflow-x:auto}
</style></head><body><main>
<h1>Muhurat Desk</h1>
<p class="sub">Samvat 2082 replay · {{ start }} (Muhurat trading) → {{ end }} · ₹10,00,000 paper capital · 3 agents on Band, compliance by a Lyzr agent</p>
<div class="card hero"><div class="big">₹{{ kept }} kept</div>
<div>The unchecked analyst book ended at ₹{{ fmt(u.final_value) }}. With every trade passing Compliance, the same analyst ended at ₹{{ fmt(g.final_value) }}, and the worst fall from a peak shrank from {{ pct(u.max_drawdown) }} to {{ pct(g.max_drawdown) }}.</div></div>
<h2>Scorecard</h2>
<div class="grid3">{% for key, label, color in series %}{% set s = stats[key] %}
<div class="card"><h3><span class="dot" style="background:{{ color }}"></span>{{ label }}</h3><div class="big">{{ pct(s.total_return, sign=True) }}</div>
<div class="kv"><span>Final value</span><b>₹{{ fmt(s.final_value) }}</b><span>Max drawdown</span><b>{{ pct(s.max_drawdown) }}</b><span>Volatility</span><b>{{ pct(s.volatility) }}</b><span>Sharpe (rf 6.5%)</span><b>{{ s.sharpe }}</b></div></div>{% endfor %}</div>
<h2>Equity curves</h2>
<div class="card"><div class="legend">{% for key, label, color in series %}<span><span class="dot" style="background:{{ color }}"></span> {{ label }}</span>{% endfor %}</div>{{ svg }}</div>
<h2>Compliance decisions</h2>
<div class="grid3"><div class="card"><h3>Approved</h3><div class="big APPROVE">{{ counts.APPROVE }}</div></div><div class="card"><h3>Resized</h3><div class="big MODIFY">{{ counts.MODIFY }}</div></div><div class="card"><h3>Vetoed</h3><div class="big VETO">{{ counts.VETO }}</div></div></div>
<h2>Audit trail</h2>
{% for c in cycles %}<details{% if loop.first %} open{% endif %}><summary>{{ c.proposal.date }}{% if loop.first %} · Muhurat trading{% endif %} — {{ c.review.verdicts|length }} orders, {{ c.review.verdicts|selectattr('decision','ne','APPROVE')|list|length }} cut</summary>
<p>{{ c.review.summary }}</p><div class="scroll"><table><tr><th>Order</th><th>Asked</th><th>Decision</th><th>Filled</th><th>Reason</th><th>By</th></tr>
{% for o, v in zip(c.proposal.orders, c.review.verdicts) %}<tr><td>{{ o.side }} {{ o.ticker|replace('.NS','') }}</td><td>{{ o.qty }}</td><td><span class="b {{ v.decision }}">{{ v.decision }}</span>{% if v.rules %} {{ v.rules|join(', ') }}{% endif %}</td><td>{{ v.approved_qty }}</td><td>{{ v.reason }}</td><td>{{ v.source }}</td></tr>{% endfor %}
</table></div></details>{% endfor %}
<p class="note">Educational paper-trading simulation on historical NSE daily closes (adjusted, via Yahoo Finance). Fills at the checkpoint close with 0.1% costs. The risk policy is the desk's own and is not a SEBI rulebook. Nothing here is investment advice.</p>
</main></body></html>"""
)


def write_report(card: dict, path: Path) -> Path:
    from collections import Counter

    counts = Counter(v["decision"] for c in card["cycles"] for v in c["review"]["verdicts"])
    g, u = card["governed"], card["unchecked"]
    out = TEMPLATE.render(
        start=card["curves"]["dates"][0],
        end=card["curves"]["dates"][-1],
        kept=f"{g['final_value'] - u['final_value']:,}",
        g=g,
        u=u,
        stats={k: card[k] for k, _, _ in SERIES},
        series=SERIES,
        svg=_svg(card["curves"]),
        counts={k: counts.get(k, 0) for k in ("APPROVE", "MODIFY", "VETO")},
        cycles=card["cycles"],
        zip=zip,
        fmt=lambda v: f"{v:,}",
        pct=lambda v, sign=False: f"{v:+.1%}" if sign else f"{v:.1%}",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out, encoding="utf-8")
    return path


def escape(s: str) -> str:
    return html.escape(s)
