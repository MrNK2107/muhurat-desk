"""Start the three desk agents as child processes and keep them running.

    uv run python scripts/run_agents.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ["agents.analyst_agent", "agents.compliance_agent", "agents.trader_agent"]


def main() -> None:
    procs = {m: subprocess.Popen([sys.executable, "-m", m], cwd=ROOT) for m in AGENTS}
    print("started:", ", ".join(procs))
    try:
        while True:
            time.sleep(5)
            for m, p in list(procs.items()):
                if p.poll() is not None:
                    print(f"{m} exited with {p.returncode}; restarting")
                    procs[m] = subprocess.Popen([sys.executable, "-m", m], cwd=ROOT)
    except KeyboardInterrupt:
        for p in procs.values():
            p.terminate()


if __name__ == "__main__":
    main()
