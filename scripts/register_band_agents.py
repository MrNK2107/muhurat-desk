"""Register the three desk agents on Band and write their credentials to
agent_config.yaml (gitignored). Agent API keys are shown only once by Band.

The Band user key is read from ~/.secrets/band.key (or BAND_USER_API_KEY) and is
never printed or written anywhere.

Usage:
    uv run python scripts/register_band_agents.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import yaml
from band_rest import AgentRegisterRequest, AsyncRestClient

AGENTS = {
    "analyst_agent": (
        "Desk Analyst",
        "Muhurat Desk research analyst: scores NSE large caps from price data and proposes trades.",
    ),
    "compliance_agent": (
        "Desk Compliance",
        "Muhurat Desk compliance officer, backed by a Lyzr agent: approves, resizes or vetoes every proposed trade against the desk risk policy.",
    ),
    "trader_agent": (
        "Desk Trader",
        "Muhurat Desk execution trader: fills approved orders in the paper book and keeps the ledger.",
    ),
}

CONFIG_PATH = Path(__file__).resolve().parent.parent / "agent_config.yaml"


def user_key() -> str:
    key = os.environ.get("BAND_USER_API_KEY")
    if key:
        return key.strip()
    return (Path.home() / ".secrets" / "band.key").read_text(encoding="utf-8").strip()


async def main() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    config = config or {}
    client = AsyncRestClient(api_key=user_key())
    for slot, (name, description) in AGENTS.items():
        if slot in config:
            print(f"{name}: already registered ({config[slot]['agent_id']}), skipping")
            continue
        resp = await client.human_api_agents.register_my_agent(
            agent=AgentRegisterRequest(name=name, description=description)
        )
        data = resp.data
        config[slot] = {"agent_id": str(data.agent.id), "api_key": data.credentials.api_key}
        agent_id = data.agent.id
        CONFIG_PATH.write_text(yaml.safe_dump(config, sort_keys=True))
        print(f"{name}: registered {agent_id}")
    print(f"credentials saved to {CONFIG_PATH.name} (gitignored)")


if __name__ == "__main__":
    asyncio.run(main())
