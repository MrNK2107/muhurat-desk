"""Run the whole Samvat 2082 year in-process (no Band), using the Lyzr
compliance agent (cached responses are reused, so a rerun costs no credits).

    uv run python scripts/replay_offline.py            # Lyzr + cache
    uv run python scripts/replay_offline.py --local    # local policy engine only

Writes output/offline/report.html and output/offline/scorecard.json.
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
    ap.add_argument("--local", action="store_true", help="skip Lyzr, use the local policy engine")
    args = ap.parse_args()
    client = None if args.local else LyzrCompliance()

    def show(cycle: dict) -> None:
        cut = [v for v in cycle["review"]["verdicts"] if v["decision"] != "APPROVE"]
        print(f"{cycle['proposal']['date']}: {len(cycle['proposal']['orders'])} orders, {len(cut)} cut")

    card = replay(load_prices(), client, on_cycle=show)
    out = OUTPUT_DIR / ("offline-local" if args.local else "offline")
    out.mkdir(parents=True, exist_ok=True)
    (out / "scorecard.json").write_text(json.dumps(card, indent=1))
    write_report(card, out / "report.html")
    for k in ("governed", "unchecked", "nifty"):
        print(k, card[k])
    if client:
        print(f"Lyzr calls this run: {client.calls} (rest served from cache)")
    print(f"report: {out / 'report.html'}")


if __name__ == "__main__":
    main()
