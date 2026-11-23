"""Short human-readable notes for the trading room. The LLM only writes prose
from numbers the code already computed; if it is slow or fails, a template is
used, so the desk never depends on a model to make or describe a decision."""

from __future__ import annotations

import os
import re

from dotenv import load_dotenv

load_dotenv()

_TIMEOUT = float(os.getenv("NARRATE_TIMEOUT", "45"))


def _llm(prompt: str) -> str | None:
    if os.getenv("NARRATE", "1") == "0":
        return None
    try:
        backend = os.getenv("LLM_BACKEND", "ollama").lower()
        if backend == "ollama":
            from langchain_ollama import ChatOllama

            llm = ChatOllama(
                model=os.getenv("OLLAMA_MODEL", "gemma4:e4b"),
                base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
                temperature=0.3,
                num_predict=160,
                reasoning=False,  # gemma4 otherwise spends the budget thinking and returns nothing
                client_kwargs={"timeout": _TIMEOUT},
            )
        else:
            from langchain_google_genai import ChatGoogleGenerativeAI

            llm = ChatGoogleGenerativeAI(model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"), temperature=0.3, timeout=_TIMEOUT)
        text = llm.invoke(prompt).content
        if isinstance(text, list):
            text = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in text)
        text = re.sub(r"\s+", " ", str(text)).strip().strip('"')
        return text or None
    except Exception:  # model down, timeout, quota: fall back to the template
        return None


def _name(t: str) -> str:
    return t.replace(".NS", "")


def analyst_note(proposal: dict) -> str:
    sig = proposal["top_signals"]
    buys = [o for o in proposal["orders"] if o["side"] == "BUY"]
    sells = [o for o in proposal["orders"] if o["side"] == "SELL"]
    facts = "; ".join(f"{_name(s['ticker'])} 3m {s['mom_3m']:+.1%}, 6m {s['mom_6m']:+.1%}, vol {s['vol_20d']:.0%}" for s in sig)
    template = (
        f"Strongest momentum today: {', '.join(_name(s['ticker']) for s in sig[:3])}. "
        f"Proposing {len(buys)} buys and {len(sells)} sells to rotate into strength."
    )
    prose = _llm(
        "You are an aggressive momentum analyst on an Indian equity paper-trading desk. "
        f"Date {proposal['date']}. Top signals: {facts}. You are proposing {len(buys)} buys and {len(sells)} sells. "
        "Write exactly two short sentences for the trading room explaining your view. Use only these numbers. No disclaimers, no markdown."
    )
    return prose or template


def trader_note(result: dict) -> str:
    fills = result["fills"]
    if not fills:
        return "No fills this cycle; the book is unchanged."
    parts = [f"{f['side']} {f['qty']} {_name(f['ticker'])} @ {f['price']:.2f}" for f in fills]
    return "Filled: " + "; ".join(parts) + "."
