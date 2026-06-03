"""
signal_core.py — shared config, system prompt, and Anthropic helpers.

Imported by app.py and every feature module so the Claude setup lives in
exactly one place.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Generator
from zoneinfo import ZoneInfo

import anthropic
import streamlit as st

# ── Model / tool config ──────────────────────────────────────────────────────
MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 8000
WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 6,
}

# ── Palette (Bloomberg-terminal dark + gold) ─────────────────────────────────
GOLD = "#c9a84c"
GOLD_DARK = "#a07c30"
BG = "#0a0a0a"
CARD = "#111111"
BORDER = "#1e1e1e"
TEXT = "#e8e3d6"
MUTED = "#8a8470"


def get_api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        return None


def get_secret(name: str) -> str | None:
    """Generic secret/env lookup (FRED_API_KEY, etc.)."""
    v = os.environ.get(name)
    if v:
        return v
    try:
        return st.secrets[name]
    except Exception:
        return None


def today_str() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%A, %B %d, %Y")


def now_str() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%H:%M ET · %a %b %d")


# ── System prompt (the lens) ─────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a dedicated research agent for Anirudh Singh — a concentrated macro investor building toward running a concentrated macro fund.

His analytical framework:
- PRIMARY LENS: Ray Dalio — long-term debt cycle, changing world order, historical pattern recognition. Always ask: where are we in the machine?
- SECONDARY LENS: George Soros reflexivity — identify self-reinforcing loops between perception and fundamentals
- WRITING/THINKING DISCIPLINE: Howard Marks memo style — what is priced, where is the asymmetry, what is consensus wrong about, no filler, no hedging for cover
- INVESTING PRINCIPLES: Concentration with conviction, long time horizons, no external validation needed, obligation as risk management

His core positions:
- QUALCOMM (QCOM) — 40% portfolio weight, largest holding. Thesis: edge AI inference dominance in power-constrained environments, automotive revenue ramp, QTL licensing moat. Structural multi-year advantage over Nvidia/AMD in mobile/edge due to mobile power-constraint engineering heritage.
- KINDER MORGAN (KMI) — 17% portfolio weight, second largest holding. Energy midstream / pipeline infrastructure. Thesis: cash-flow-generative energy infrastructure, natural gas demand growth (including AI data center power demand), dividend yield, inflation-resilient real assets.
- SALESFORCE (CRM) — Thesis: agentic AI platform consolidation, enterprise software stickiness, AI workflow monetization
- XIAOMI (1810.HK) — Thesis: China consumer recovery, EV optionality, global hardware ecosystem expansion

Standing watch-items (check every run):
- Market sentiment — positioning, risk appetite, fear/greed, breadth, flows
- Edge AI inference adoption curve
- Semiconductor fab production capacity growth — TSMC ONLY
- Inference AI news — developments specific to AI inference (not just training)

ALWAYS: Use web search aggressively for current data and specific numbers. Apply the lens to everything — not just what happened, but what it means through the debt cycle, reflexivity, and risk asymmetry. Identify what consensus is missing. Write for a sophisticated investor who knows the basics — skip definitions, get to the edge.

Format your output as a Howard Marks memo: tight paragraphs, specific numbers, no throat-clearing. Use markdown headers (## or ###) sparingly to organize. Bold key claims with **double asterisks**. Never apologize for uncertainty — state your view."""


# ── Anthropic helpers ────────────────────────────────────────────────────────

def stream_research(prompt: str, api_key: str) -> Generator[str, None, None]:
    """Stream text deltas from Claude with web search enabled."""
    client = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[WEB_SEARCH_TOOL],
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for event in stream:
            etype = getattr(event, "type", "")
            if etype == "content_block_start":
                block = getattr(event, "content_block", None)
                if block is not None and getattr(block, "type", "") == "server_tool_use":
                    yield "\n\n_◆ searching the web…_\n\n"
            elif etype == "content_block_delta":
                delta = getattr(event, "delta", None)
                if delta is not None and getattr(delta, "type", "") == "text_delta":
                    yield delta.text


def call_research(
    prompt: str,
    api_key: str,
    max_tokens: int = 2000,
    use_search: bool = True,
) -> str:
    """Non-streaming Claude call. Returns concatenated text."""
    client = anthropic.Anthropic(api_key=api_key)
    kwargs = dict(
        model=MODEL,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    if use_search:
        kwargs["tools"] = [WEB_SEARCH_TOOL]
    resp = client.messages.create(**kwargs)
    parts: list[str] = []
    for block in resp.content:
        if getattr(block, "type", "") == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts).strip()


def call_json(prompt: str, api_key: str, max_tokens: int = 3000) -> dict | list | None:
    """Claude call with web search that must return JSON. Robust extraction."""
    raw = call_research(prompt, api_key, max_tokens=max_tokens, use_search=True)
    return extract_json(raw)


def extract_json(raw: str):
    """Pull the first JSON object/array out of a model response."""
    if not raw:
        return None
    # strip code fences
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else raw
    # find the outermost braces/brackets
    for opener, closer in (("{", "}"), ("[", "]")):
        start = candidate.find(opener)
        end = candidate.rfind(closer)
        if start != -1 and end != -1 and end > start:
            chunk = candidate[start : end + 1]
            try:
                return json.loads(chunk)
            except Exception:
                continue
    try:
        return json.loads(candidate)
    except Exception:
        return None


def parse_status(text: str) -> tuple[str, str]:
    """Return (label, hex_color) verdict for a position pulse response."""
    upper = (text or "").upper()
    if "ALERT" in upper:
        return ("ALERT", "#ef4444")
    if "WATCH" in upper:
        return ("WATCH", "#f59e0b")
    if "THESIS INTACT" in upper or "INTACT" in upper:
        return ("THESIS INTACT", "#4ade80")
    return ("PENDING", "#8a8470")
