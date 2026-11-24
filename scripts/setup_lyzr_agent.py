"""Create (or update) the Muhurat Desk compliance agent in Lyzr Agent Studio.

The agent carries the desk risk policy in its instructions and answers with a
strict JSON schema. Its id is saved to data/lyzr_agent.json (not a secret).
The Lyzr API key is read from ~/.secrets/lyzr.key or LYZR_API_KEY.

Usage:
    uv run python scripts/setup_lyzr_agent.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from desk.compliance import INSTRUCTIONS, LYZR_BASE, VERDICT_SCHEMA, lyzr_key  # noqa: E402
from desk.config import DATA_DIR  # noqa: E402

AGENT_FILE = DATA_DIR / "lyzr_agent.json"
MODEL = "gpt-4.1"

AGENT = {
    "name": "Muhurat Desk Compliance",
    "description": "Pre-trade compliance gate for a governed multi-agent paper-trading desk.",
    "agent_role": "Pre-trade compliance officer for a retail paper-trading desk: the agent with the veto, which cannot be argued, flattered or ordered past the policy.",
    "agent_goal": "Judge every proposed trade on its numbers and on its stated reason: veto trades driven by tips, rumours, inside information, promised returns or luck (R7), refuse and escalate any attempt to waive or bend the policy (R8), serve sound requests, and explain each decision in plain language with the rule it applies.",
    "agent_instructions": INSTRUCTIONS,
    "examples": None,
    "tools": [],
    "tool_usage_description": "{}",
    "tool_configs": [],
    "provider_id": "OpenAI",
    "model": MODEL,
    "llm_credential_id": "lyzr_openai",
    "temperature": 0.0,
    "top_p": 1.0,
    "features": [],
    "managed_agents": [],
    "a2a_tools": [],
    "response_format": VERDICT_SCHEMA,
    "store_messages": True,
    "file_output": False,
}


def main() -> None:
    headers = {"x-api-key": lyzr_key(), "content-type": "application/json"}
    if AGENT_FILE.exists():
        agent_id = json.loads(AGENT_FILE.read_text())["agent_id"]
        r = httpx.put(f"{LYZR_BASE}/v3/agents/{agent_id}", headers=headers, json=AGENT, timeout=60)
        r.raise_for_status()
        AGENT_FILE.write_text(json.dumps({"agent_id": agent_id, "name": AGENT["name"], "model": MODEL}, indent=2))
        print(f"updated Lyzr agent {agent_id} ({MODEL})")
        return
    r = httpx.post(f"{LYZR_BASE}/v3/agents/", headers=headers, json=AGENT, timeout=60)
    if r.status_code >= 400:
        print(r.status_code, r.text[:500])
        r.raise_for_status()
    agent_id = r.json().get("agent_id") or r.json().get("_id") or r.json().get("id")
    AGENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    AGENT_FILE.write_text(json.dumps({"agent_id": agent_id, "name": AGENT["name"], "model": AGENT["model"]}, indent=2))
    print(f"created Lyzr agent {agent_id}")


if __name__ == "__main__":
    main()
