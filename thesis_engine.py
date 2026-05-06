"""Thesis scoring engine — fetch news, ask Claude to score each pillar."""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional

import anthropic
import streamlit as st

from data_fetcher import news_search


def get_secret(key):
    try:
        val = st.secrets.get(key)
        if val:
            return val
    except Exception:
        pass
    return os.getenv(key)


FRED_API_KEY = get_secret("FRED_API_KEY")
NEWS_API_KEY = get_secret("NEWS_API_KEY")
ANTHROPIC_API_KEY = get_secret("ANTHROPIC_API_KEY")

MODEL = "claude-sonnet-4-20250514"


def get_client():
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def has_anthropic():
    return bool(ANTHROPIC_API_KEY)


POSITIONS = {
    "QCOM": {
        "name": "Qualcomm",
        "ticker": "QCOM",
        "thesis": (
            "The AI inference transition shifts competitive advantage away from "
            "training (Nvidia GPU dominance) toward heterogeneous compute. "
            "Qualcomm's decade of building power-efficient, heterogeneous compute "
            "architectures for mobile — driven by hardware constraints — positions "
            "it as the primary beneficiary of on-device and edge AI inference. The "
            "company is simultaneously diversifying into automotive ($45B design-win "
            "pipeline) and custom silicon for hyperscalers. The market is mispricing "
            "QCOM as a handset company when it is becoming a heterogeneous compute "
            "platform."
        ),
        "pillars": [
            "Edge AI inference adoption accelerating",
            "Hyperscaler custom silicon deal progressing",
            "Automotive revenue growth continuing",
            "Handset market stabilizing (not collapsing)",
            "Market re-rating QCOM away from handset multiple",
        ],
        "news_query": (
            '"Qualcomm" AND ("edge AI" OR "inference" OR "automotive" OR '
            '"hyperscaler" OR "custom silicon" OR "Snapdragon")'
        ),
    },
    "XIACY": {
        "name": "Xiaomi",
        "ticker": "XIACY",
        "thesis": (
            "Xiaomi is executing a vertically integrated AI mesh strategy — "
            "connecting its EV expansion (SU7 and pipeline) with its smart home "
            "ecosystem and on-device AI. As Chinese consumers increasingly adopt a "
            "single-brand connected life (phone, home, car, AI assistant), Xiaomi's "
            "ecosystem lock-in creates a compounding moat. The EV business validates "
            "the hardware premium and expands the addressable market. This is the "
            "Chinese version of Apple's ecosystem play but with EVs at the center."
        ),
        "pillars": [
            "EV delivery numbers growing",
            "Smart home / IoT ecosystem expanding",
            "AI integration across devices progressing",
            "Chinese consumer sentiment / domestic demand holding",
            "Competition from BYD/Huawei manageable",
        ],
        "news_query": (
            '"Xiaomi" AND ("EV" OR "electric vehicle" OR "SU7" OR "smart home" '
            'OR "AI" OR "ecosystem")'
        ),
    },
    "CRM": {
        "name": "Salesforce",
        "ticker": "CRM",
        "thesis": (
            "Salesforce is the primary enterprise infrastructure beneficiary of the "
            "agentic AI transition. As AI agents replace human workflows in sales, "
            "service, and marketing, Salesforce's data layer (Customer 360) becomes "
            "the operating system for enterprise AI agents. The shift to usage-based "
            "pricing (Agentforce consumption model) unlocks a new revenue "
            "architecture — moving from seat licenses to outcome-based billing — "
            "which is both more scalable and more defensible. Enterprises will not "
            "rebuild their CRM data layer; they will extend it with agents."
        ),
        "pillars": [
            "Agentforce adoption and revenue contribution growing",
            "Usage-based pricing model gaining traction",
            "Enterprise AI agent deployments accelerating",
            "Data Cloud / Customer 360 remaining sticky",
            "Competitive moat vs Microsoft Dynamics / ServiceNow holding",
        ],
        "news_query": (
            '"Salesforce" AND ("Agentforce" OR "AI agent" OR "usage pricing" '
            'OR "agentic" OR "enterprise AI")'
        ),
    },
}


SYSTEM_PROMPT = (
    "You are a rigorous investment analyst. You will be given a thesis with "
    "specific pillars, and a list of recent news headlines. Score each pillar "
    "from 1-10 based on how well the current news supports or contradicts it. "
    "10 = thesis strongly confirmed. 1 = thesis clearly broken. 5 = "
    "neutral/inconclusive. Return ONLY a JSON object with this structure: "
    '{"pillar_scores": [{"pillar": "name", "score": X, "reasoning": "one '
    'sentence"}], "overall_score": X, "overall_verdict": "one sentence", '
    '"confirming_headlines": ["headline1", "headline2"], '
    '"contradicting_headlines": ["headline1"]}'
)


@st.cache_data(ttl=1800, show_spinner=False)
def score_position(key):
    pos = POSITIONS[key]
    articles = news_search(pos["news_query"], page_size=10)
    result = {
        "ticker": pos["ticker"],
        "name": pos["name"],
        "thesis": pos["thesis"],
        "pillars": pos["pillars"],
        "articles": articles,
        "scores": None,
        "error": None,
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    if not articles:
        result["error"] = "No news articles available (NewsAPI key missing or empty result)."
        return result

    user_prompt = _build_user_prompt(pos, articles)
    try:
        client = get_client()
        msg = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(
            block.text for block in msg.content
            if getattr(block, "type", "") == "text"
        )
        result["scores"] = _parse_json(text)
    except Exception as exc:
        result["error"] = f"Claude API error: {exc}"
    return result


def _build_user_prompt(pos, articles):
    headlines = "\n".join(
        f"- [{a.get('publishedAt', '')[:10]}] {a['title']}"
        + (f" — {a['description']}" if a.get("description") else "")
        for a in articles
    )
    pillars_text = "\n".join(f"- {p}" for p in pos["pillars"])
    return (
        f"Company: {pos['name']} ({pos['ticker']})\n\n"
        f"Thesis:\n{pos['thesis']}\n\n"
        f"Pillars to score:\n{pillars_text}\n\n"
        f"Recent headlines:\n{headlines}\n\n"
        "Return ONLY the JSON object specified by the system prompt."
    )


def _parse_json(text):
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
