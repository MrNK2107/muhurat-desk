"""Collect the published results into data/results/ and site/data/.

The year replay and the development and held-out red teams were produced
with compliance prompt v2 (git tag ``results-prompt-v2``); the blind red team
with the current prompt v3. Lyzr's free credits ran out before the year could
be replayed on v3, so the v2 results are kept as they were produced and the
keyword-filter column is recomputed with the current (stronger) word list, which
is deterministic code.

    uv run python scripts/publish_results.py <scorecard_v2.json> <heldout_v2.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from desk.config import DATA_DIR, OUTPUT_DIR, ROOT  # noqa: E402
from desk.room import keyword_filter  # noqa: E402


def rescore_keyword(rows: list[dict]) -> dict:
    for r in rows:
        if "correct" not in r or r["correct"].get("desk") is None:
            continue
        kw = "VETO" if keyword_filter(r["text"]) else r["code_only"]
        r["keyword"] = kw
        want = "VETO" if r["label"] == "manipulative" else r["code_only"]
        r["correct"]["keyword"] = kw == want
    judged = [r for r in rows if "correct" in r and r["correct"].get("desk") is not None]
    return {
        "correct": sum(r["correct"]["keyword"] for r in judged), "total": len(judged),
        "manipulative_blocked": sum(r["correct"]["keyword"] for r in judged if r["label"] == "manipulative"),
        "manipulative_total": sum(r["label"] == "manipulative" for r in judged),
        "legit_served": sum(r["correct"]["keyword"] for r in judged if r["label"] == "legitimate"),
        "legit_total": sum(r["label"] == "legitimate" for r in judged),
    }


def main() -> None:
    card = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    held = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    card["redteam_score"]["keyword"] = rescore_keyword(card["redteam"])
    held["score"]["keyword"] = rescore_keyword(held["rows"])
    card["prompt_version"] = held["prompt_version"] = "v2 (git tag results-prompt-v2)"
    blind = json.loads((OUTPUT_DIR / "offline" / "blind.json").read_text(encoding="utf-8"))
    blind["prompt_version"] = "v3 (current)"
    out = DATA_DIR / "results"
    out.mkdir(parents=True, exist_ok=True)
    site = ROOT / "site" / "data"
    site.mkdir(parents=True, exist_ok=True)
    for name, obj in (("scorecard", card), ("heldout", held), ("blind", blind)):
        (out / f"{name}.json").write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
        (site / f"{name}.json").write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        print(name, json.dumps(obj.get("redteam_score", obj.get("score"))))


if __name__ == "__main__":
    main()
