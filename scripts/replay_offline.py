"""Run the whole Samvat 2082 year in-process (no Band) with the Lyzr compliance
agent, and the same year with R1-R6 in code only, for comparison. Lyzr replies
are cached by a hash of the review packet and the agent's instructions, so a
rerun costs no credits.

    uv run python scripts/replay_offline.py            # Lyzr (+ cache) and code-only
    uv run python scripts/replay_offline.py --local    # code-only only, no Lyzr at all

Writes output/offline/{scorecard.json,report.html}. (scripts/publish_results.py copies published results to site/data.)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from desk.compliance import LyzrCompliance  # noqa: E402
from desk.config import OUTPUT_DIR  # noqa: E402
from desk.engine import replay  # noqa: E402
from desk.market import load_prices  # noqa: E402
from desk.report import write_report  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true", help="skip Lyzr, use R1-R6 in code only")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    prices = load_prices()

    def show(cycle: dict) -> None:
        rounds = [cycle["review"]] + ([cycle["review2"]] if cycle.get("review2") else [])
        cut = sum(v["decision"] != "APPROVE" for r in rounds for v in r["verdicts"])
        print(f"{cycle['proposal']['date']}: {sum(len(r['orders']) for r in rounds)} orders in {len(rounds)} round(s), {cut} cut")

    code_only = replay(prices, None)
    if args.local:
        card, out = code_only, OUTPUT_DIR / "offline-local"
    else:
        client = LyzrCompliance()
        card = replay(prices, client, on_cycle=show)
        out = OUTPUT_DIR / "offline"
        lyzr_calls = client.calls
    card["code_only"] = {k: code_only[k] for k in ("governed", "decisions")}
    out.mkdir(parents=True, exist_ok=True)
    (out / "scorecard.json").write_text(json.dumps(card, indent=1), encoding="utf-8")
    write_report(card, out / "report.html")
    for k in ("governed", "unchecked", "nifty", "nifty_matched"):
        print(k, card[k])
    print("code-only governed", code_only["governed"])
    print("decisions", card["decisions"])
    print("red team", json.dumps(card["redteam_score"]))
    if not args.local:
        print(f"Lyzr calls this run: {lyzr_calls} (the rest came from the cache)")
    print(f"report: {out / 'report.html'}")


if __name__ == "__main__":
    main()
