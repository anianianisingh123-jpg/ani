"""Query-type routing (Phase 4).

Deterministic keyword rules first; default to full_underwrite when ambiguous.
Log decisions so a quiet missing section is never invisible.
"""

from __future__ import annotations

import re
from typing import Any, Optional

QUERY_TYPES = (
    "full_underwrite",
    "valuation_only",
    "risk_assessment",
    "business_understanding",
    "specific_question",
    "screener",
)

# (query_type, compiled patterns, reason template)
_RULES: list[tuple[str, list[re.Pattern[str]], str]] = [
    (
        "screener",
        [
            re.compile(r"\bscreen\b", re.I),
            re.compile(r"\bshortlist\b", re.I),
            re.compile(r"\brank\b.+\b(stocks?|names?|tickers?)\b", re.I),
            re.compile(r"\btop\s+\d+\b.+\b(in|stocks?)\b", re.I),
        ],
        "keyword suggests sector screen / ranking",
    ),
    (
        "valuation_only",
        [
            re.compile(r"\b(dcf|fair value|intrinsic value|undervalued|overvalued)\b", re.I),
            re.compile(r"\b(valuation|worth|price target|multiples?|comps?)\b", re.I),
            re.compile(r"\bhow much is\b.+\bworth\b", re.I),
        ],
        "keyword suggests valuation-focused ask",
    ),
    (
        "risk_assessment",
        [
            re.compile(r"\b(risks?|bear case|downside|what could go wrong)\b", re.I),
            re.compile(r"\b(headwind|threats?|red flags?)\b", re.I),
        ],
        "keyword suggests risk / bear assessment",
    ),
    (
        "business_understanding",
        [
            re.compile(r"\bwhat does\b.+\bdo\b", re.I),
            re.compile(r"\bbusiness model\b", re.I),
            re.compile(r"\bexplain the (company|business)\b", re.I),
            re.compile(r"\bhow does\b.+\bmake money\b", re.I),
        ],
        "keyword suggests business-description ask",
    ),
    (
        "specific_question",
        [
            re.compile(r"\bchina exposure\b", re.I),
            re.compile(r"\b(who is|who are)\b.+\b(ceo|cfo|management)\b", re.I),
            re.compile(r"\b(only|just)\b.+\b(question|about)\b", re.I),
            re.compile(r"\bexposure to\b", re.I),
            re.compile(r"\bwhat is .+('s|s) .+\?$", re.I),
        ],
        "keyword suggests narrow factual question",
    ),
]


def classify_query(
    user_query: str,
    *,
    mode: Optional[str] = None,
    sector: Optional[str] = None,
    ticker: Optional[str] = None,
) -> dict[str, Any]:
    """Classify query type. Defaults to full_underwrite when ambiguous."""
    q = (user_query or "").strip()
    mode_l = (mode or "").strip().lower()

    if mode_l == "screener":
        return {
            "query_type": "screener",
            "confidence": "high",
            "reason": "mode=screener",
            "defaulted": False,
        }

    if not q:
        return {
            "query_type": "full_underwrite",
            "confidence": "low",
            "reason": "empty query — default full_underwrite",
            "defaulted": True,
        }

    hits: list[tuple[str, str]] = []
    for qtype, patterns, reason in _RULES:
        for pat in patterns:
            if pat.search(q):
                hits.append((qtype, reason))
                break

    if not hits:
        return {
            "query_type": "full_underwrite",
            "confidence": "low",
            "reason": (
                "no strong keyword match — default full_underwrite "
                "(unnecessary agents cost cents; missing bear case costs more)"
            ),
            "defaulted": True,
        }

    # If multiple types matched, prefer full_underwrite when "buy" framing present
    types = {h[0] for h in hits}
    if "buy" in q.lower() or "invest" in q.lower() or "still a buy" in q.lower():
        return {
            "query_type": "full_underwrite",
            "confidence": "moderate",
            "reason": (
                f"matched {sorted(types)} but investment/buy framing → full_underwrite"
            ),
            "defaulted": False,
            "also_matched": sorted(types),
        }

    # Prefer more specific non-screener types; if conflict, full_underwrite
    if len(types) > 1 and "screener" not in types:
        return {
            "query_type": "full_underwrite",
            "confidence": "low",
            "reason": f"ambiguous matches {sorted(types)} — default full_underwrite",
            "defaulted": True,
            "also_matched": sorted(types),
        }

    qtype, reason = hits[0]
    return {
        "query_type": qtype,
        "confidence": "moderate",
        "reason": reason,
        "defaulted": False,
        "also_matched": [h[0] for h in hits],
    }


def log_routing_decision(decision: dict[str, Any]) -> None:
    print(
        f"[route] query_type={decision.get('query_type')} "
        f"confidence={decision.get('confidence')} "
        f"defaulted={decision.get('defaulted')} "
        f"reason={decision.get('reason')}",
        flush=True,
    )


def agents_for_query_type(query_type: str) -> dict[str, bool]:
    """Which analytical branches to run after foundation."""
    qt = query_type or "full_underwrite"
    flags = {
        "business_overview": True,
        "macro_regime": True,
        "management_track_record": True,
        "data_gatherer": True,
        "metrics": True,
        "capital_allocation": True,
        "bull": True,
        "bear": True,
        "fundamental": True,
        "relative": True,
        "synthesis": True,
        "qc": True,
    }
    if qt == "screener":
        return {k: False for k in flags}  # separate path
    if qt == "valuation_only":
        flags.update(
            {
                "business_overview": False,
                "macro_regime": False,
                "management_track_record": False,
                "capital_allocation": False,
                "bull": False,
                "bear": False,
            }
        )
    elif qt == "risk_assessment":
        flags.update(
            {
                "bull": False,
                "fundamental": False,
                "relative": False,
                "capital_allocation": True,
            }
        )
    elif qt == "business_understanding":
        flags.update(
            {
                "data_gatherer": False,
                "metrics": False,
                "macro_regime": False,
                "management_track_record": False,
                "capital_allocation": False,
                "bull": False,
                "bear": False,
                "fundamental": False,
                "relative": False,
                "qc": False,
            }
        )
    elif qt == "specific_question":
        flags.update(
            {
                "macro_regime": False,
                "management_track_record": False,
                "capital_allocation": False,
                "bull": False,
                "bear": False,
                "fundamental": False,
                "relative": False,
                "business_overview": True,
            }
        )
    return flags


def synthesis_mode_for_query_type(query_type: str) -> str:
    """Controls synthesis prompt shape."""
    if query_type == "specific_question":
        return "direct_answer"
    if query_type == "business_understanding":
        return "business_brief"
    if query_type == "valuation_only":
        return "valuation_note"
    if query_type == "risk_assessment":
        return "risk_memo"
    return "full_memo"
