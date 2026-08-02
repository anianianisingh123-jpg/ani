"""Valuation quality rubric and grader (VAL-02 / Track C).

Implements the 11 binary criteria in ``VALUATION_ICL_DESIGN.md`` §10.1 and the
Track C API in §12:

    RUBRIC: list[dict]
    grade_valuation(state) -> dict
    format_rubric_for_prompt() -> str

**Determinism policy (Track C constraints):**

- Criteria **3, 5, 7, 9, 11** are mechanically checkable from state + text.
- Criteria **2, 4, 6, 10** are also mechanical against critique / engine fields
  (vacuous-pass when the ICL objects are not yet present, so pre-VAL baseline
  runs still produce a complete scorecard).
- Criteria **1 and 8** require an LLM (or injectable) judge and are marked
  ``judged: true`` when a judge is used. Without a judge they fall back to
  conservative heuristics and set ``judged: false``.

This module is pure measurement: no graph wiring, no engine mutation, no I/O.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from .valuation_engine import (
    _evidence_value,
    _has_resolvable_evidence,
)

# Optional injectable judge: (criterion_id, state, valuation_text) -> (passed, detail)
JudgeFn = Callable[[int, dict, str], tuple[bool, str]]

# Held-out tickers for baseline scoring (VAL-02 part 2) — §10.2.
# Not executed by this module; listed here so the harness and docs share one source.
HELD_OUT_TICKERS: list[dict[str, str]] = [
    {"ticker": "NVDA", "archetype": "general", "note": "desk memo exists"},
    {"ticker": "QCOM", "archetype": "general", "note": "desk memo exists"},
    {"ticker": "CRM", "archetype": "software_saas", "note": "desk memo exists"},
    {"ticker": "JPM", "archetype": "bank_lender", "note": "DCF must be rejected as primary"},
    {"ticker": "PLD", "archetype": "equity_reit", "note": "FFO/NAV path"},
    {"ticker": "PGR", "archetype": "insurance", "note": "book-value path"},
    {"ticker": "XOM", "archetype": "cyclical_commodity", "note": "mid-cycle normalization"},
    {"ticker": "KO", "archetype": "mature_dividend_payer", "note": "stable-assumption control"},
]

# ── Rubric definition (§10.1) ────────────────────────────────────────────────

RUBRIC: list[dict[str, Any]] = [
    {
        "id": 1,
        "name": "archetype_and_method",
        "criterion": "Archetype named and primary method justified",
        "type": "binary",
        "mechanical": False,
        "requires_judgment": True,
    },
    {
        "id": 2,
        "name": "evidence_for_argued_inputs",
        "criterion": "Every argued input cites ≥1 resolvable evidence field",
        "type": "binary",
        "mechanical": True,
        "requires_judgment": False,
    },
    {
        "id": 3,
        "name": "no_untraceable_currency",
        "criterion": (
            "No currency figure appears that is not traceable to an engine block, "
            "a canonical metric, or a filed financial statement"
        ),
        "type": "binary",
        "mechanical": True,
        "requires_judgment": False,
    },
    {
        "id": 4,
        "name": "terminal_value_share_stated",
        "criterion": "Terminal-value share of EV stated (DCF path)",
        "type": "binary",
        "mechanical": True,
        "requires_judgment": False,
    },
    {
        "id": 5,
        "name": "valuation_as_range",
        "criterion": "Valuation expressed as a range, not a point",
        "type": "binary",
        "mechanical": True,
        "requires_judgment": False,
    },
    {
        "id": 6,
        "name": "peer_changes_justified",
        "criterion": "Each peer inclusion/exclusion justified individually",
        "type": "binary",
        "mechanical": True,
        "requires_judgment": False,
    },
    {
        "id": 7,
        "name": "comparison_windows_consistent",
        "criterion": "Comparison windows consistent and stated (no YTD vs 1-yr mixing)",
        "type": "binary",
        "mechanical": True,
        "requires_judgment": False,
    },
    {
        "id": 8,
        "name": "unresolved_risk",
        "criterion": "≥1 risk left explicitly unresolved (no self-neutralizing close)",
        "type": "binary",
        "mechanical": False,
        "requires_judgment": True,
    },
    {
        "id": 9,
        "name": "default_and_judgment_cases",
        "criterion": "Both default and judgment cases present",
        "type": "binary",
        "mechanical": True,
        "requires_judgment": False,
    },
    {
        "id": 10,
        "name": "band_dissents_flagged",
        "criterion": "Band dissents flagged where applicable",
        "type": "binary",
        "mechanical": True,
        "requires_judgment": False,
    },
    {
        "id": 11,
        "name": "no_numeric_contradiction",
        "criterion": "No internal numeric contradiction (same metric, two values)",
        "type": "binary",
        "mechanical": True,
        "requires_judgment": False,
    },
]

assert len(RUBRIC) == 11
assert [c["id"] for c in RUBRIC] == list(range(1, 12))


# ── Public API ───────────────────────────────────────────────────────────────

def format_rubric_for_prompt() -> str:
    """Render the rubric as a QC-facing checklist block."""
    lines = [
        "=== VALUATION QUALITY RUBRIC (binary; score = count passed) ===",
        "Source: VALUATION_ICL_DESIGN.md §10.1. Report per-criterion, not just the total.",
        "",
    ]
    for c in RUBRIC:
        mode = "LLM-judged" if c["requires_judgment"] else "mechanical"
        lines.append(f"{c['id']:2d}. [{mode}] {c['criterion']}")
    lines.append("")
    lines.append(
        "Score each criterion PASS or FAIL. Do not rewrite the memo; report only."
    )
    return "\n".join(lines)


def grade_valuation(
    state: dict,
    *,
    judge: Optional[JudgeFn] = None,
) -> dict[str, Any]:
    """Grade valuation quality for a research-run state.

    Parameters
    ----------
    state:
        A ``ResearchState``-like dict (or synthetic fixture). Reads valuation
        narratives, engine blocks, and optional ICL critique/judgment fields.
    judge:
        Optional callable ``(criterion_id, state, valuation_text) -> (passed, detail)``
        used for criteria 1 and 8. When provided, those results are marked
        ``judged: true``. When omitted, conservative heuristics run and results
        are marked ``judged: false``.

    Returns
    -------
    dict with keys:
        score, max_score, criteria (list of per-criterion results),
        ticker, notes.
    """
    text = _valuation_text(state)
    results: list[dict[str, Any]] = []

    agent_text = _agent_valuation_text(state)
    checkers: dict[int, Callable[..., dict[str, Any]]] = {
        1: lambda: _grade_c1(state, text, judge),
        2: lambda: _grade_c2(state),
        3: lambda: _grade_c3(state, agent_text),
        4: lambda: _grade_c4(state, agent_text),
        5: lambda: _grade_c5(state, agent_text),
        6: lambda: _grade_c6(state),
        7: lambda: _grade_c7(agent_text),
        8: lambda: _grade_c8(state, text, judge),
        9: lambda: _grade_c9(state),
        10: lambda: _grade_c10(state),
        11: lambda: _grade_c11(state, agent_text),
    }

    for spec in RUBRIC:
        cid = int(spec["id"])
        result = checkers[cid]()
        result = {
            "id": cid,
            "name": spec["name"],
            "criterion": spec["criterion"],
            "type": spec["type"],
            "mechanical": spec["mechanical"],
            "requires_judgment": spec["requires_judgment"],
            "passed": bool(result["passed"]),
            "judged": bool(result.get("judged", False)),
            "detail": str(result.get("detail") or ""),
            "method": str(result.get("method") or ("mechanical" if spec["mechanical"] else "unknown")),
        }
        results.append(result)

    score = sum(1 for r in results if r["passed"])
    return {
        "ticker": state.get("ticker"),
        "score": score,
        "max_score": len(RUBRIC),
        "criteria": results,
        "notes": _summary_notes(results),
    }


# ── Text / number helpers ────────────────────────────────────────────────────

def _valuation_text(state: dict) -> str:
    """Full valuation-facing prose (agents + memo + critiques).

    Used for LLM-judged criteria (1, 8) where synthesis context matters.
    """
    parts: list[str] = []
    for key in (
        "fundamental_valuation",
        "relative_valuation",
        "final_memo",
    ):
        val = state.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    # Structured critique reasoning also counts as valuation prose when present.
    for key in ("valuation_critique", "relative_critique"):
        obj = state.get(key)
        if isinstance(obj, dict) and obj:
            parts.append(_flatten_strings(obj))
    return "\n\n".join(parts)


def _agent_valuation_text(state: dict) -> str:
    """Prose owned by the valuation agents only (not the full memo).

    Mechanical criteria 3/4/5/7/11 grade *valuation* quality. Scanning the
    entire ``final_memo`` false-flags business-overview currency (buybacks,
    segment revenue) and peer-table multiples as engine/contradiction defects.
    Live NVDA baseline (2026-07-28) surfaced both failure modes.
    """
    parts: list[str] = []
    for key in ("fundamental_valuation", "relative_valuation"):
        val = state.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    for key in ("valuation_critique", "relative_critique"):
        obj = state.get(key)
        if isinstance(obj, dict) and obj:
            parts.append(_flatten_strings(obj))
    return "\n\n".join(parts)


def _flatten_strings(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return "\n".join(_flatten_strings(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return "\n".join(_flatten_strings(v) for v in obj)
    return ""


def _nonempty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


# Currency: $318.63 | $1.2B | $4.1 billion | USD 210
# Short units (b/m/k/t) must NOT be followed by a letter so "$130 to $150"
# is never read as "$130 t" (trillion).
_CURRENCY_RE = re.compile(
    r"""
    (?:
        \$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)
        \s*(trillion|billion|million|thousand|tn|bn|mm|m|k|t|b)?(?![a-zA-Z])
      |
        (?:USD|US\$)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)
        \s*(trillion|billion|million|thousand|tn|bn|mm|m|k|t|b)?(?![a-zA-Z])
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_UNIT_MULT = {
    "trillion": 1e12,
    "tn": 1e12,
    "t": 1e12,
    "billion": 1e9,
    "bn": 1e9,
    "b": 1e9,
    "million": 1e6,
    "mm": 1e6,
    "m": 1e6,
    "thousand": 1e3,
    "k": 1e3,
}


def _parse_currency_matches(text: str) -> list[tuple[str, float]]:
    """Return (raw_span, absolute_usd_value) for currency mentions in *text*."""
    out: list[tuple[str, float]] = []
    for m in _CURRENCY_RE.finditer(text or ""):
        raw = m.group(0)
        num_s = m.group(1) or m.group(3)
        unit = (m.group(2) or m.group(4) or "").lower()
        if not num_s:
            continue
        try:
            num = float(num_s.replace(",", ""))
        except ValueError:
            continue
        mult = _UNIT_MULT.get(unit, 1.0)
        # Ambiguous single-letter units after a small number that looks like a
        # multiple (e.g. "$32x") are rare with our pattern; skip zero.
        if num == 0:
            continue
        out.append((raw.strip(), abs(num * mult)))
    return out


def _collect_engine_numbers(state: dict) -> list[float]:
    """Absolute numeric values a writer is entitled to quote.

    Engine and judgment blocks, canonical metrics, and the filed statements the
    agents are handed. A figure outside this set appears nowhere in anything the
    pipeline fetched — it was recalled or invented, and that is what C3 exists to
    catch.
    """
    nums: list[float] = []

    def walk(obj: Any, *, depth: int = 0) -> None:
        if depth > 12:
            return
        if isinstance(obj, bool):
            return
        if isinstance(obj, (int, float)):
            nums.append(abs(float(obj)))
            return
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v, depth=depth + 1)
            return
        if isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v, depth=depth + 1)

    for key in (
        "dcf_engine",
        "comps_engine",
        "dcf_judgment",
        "comps_judgment",
        "canonical_metrics",
        # The filings themselves. Omitting these made C3 fail any correctly
        # sourced statement figure that had no canonical metric — on the
        # 2026-07-30 baseline that was 38 of 46 flags (83%), including every
        # single flag on NVDA and KO. The false positives buried the 8 figures
        # that genuinely appear nowhere in the state, which are the ones worth
        # stopping a memo over.
        "income_statement",
        "balance_sheet",
        "cash_flow_statement",
    ):
        walk(state.get(key))

    # canonical_metrics values often live under {"value": ...}
    cm = state.get("canonical_metrics")
    if isinstance(cm, dict):
        for rec in cm.values():
            if isinstance(rec, dict) and rec.get("value") is not None:
                try:
                    nums.append(abs(float(rec["value"])))
                except (TypeError, ValueError):
                    pass

    # Also accept common rounded display forms of large magnitudes.
    expanded: list[float] = list(nums)
    for n in nums:
        if n >= 1e6:
            expanded.append(n / 1e6)   # millions as bare figure
            expanded.append(n / 1e9)   # billions
        if n >= 1e9:
            expanded.append(n / 1e12)

    return expanded


def _number_traceable(value: float, allowed: list[float], *, rel_tol: float = 0.02, abs_tol: float = 0.75) -> bool:
    """True if *value* matches any allowed engine number within tolerance.

    Absolute tolerance covers share-price rounding ($318.63 vs $318.85).
    Relative tolerance covers large enterprise values.
    """
    if value <= 0:
        return False
    for a in allowed:
        if a <= 0:
            continue
        if abs(value - a) <= abs_tol:
            return True
        # Scale-aware: $1.20B vs 1.2e9
        if abs(value - a) / max(a, value) <= rel_tol:
            return True
        # Unit-scaled match: 1.2 (billions display) vs 1.2e9
        for scale in (1e3, 1e6, 1e9, 1e12):
            if abs(value * scale - a) / max(a, value * scale) <= rel_tol:
                return True
            if abs(value - a / scale) / max(a / scale, value, 1e-12) <= rel_tol:
                return True
    return False


# Range patterns: $210 – $250, $210-$250, between $210 and $250, range of $210 to $250
_RANGE_RE = re.compile(
    r"""
    (?:
        \$\s*[0-9,]+\.?[0-9]*\s*(?:–|—|-|to|through)\s*\$?\s*[0-9,]+\.?[0-9]*
      |
        (?:between|range(?:\s+of)?|band(?:\s+of)?)\s+\$?\s*[0-9,]+\.?[0-9]*
        \s+(?:and|to|–|—|-)\s+\$?\s*[0-9,]+\.?[0-9]*
      |
        (?:low|high)\s*(?:case|end|corner)?\s*[:\-]?\s*\$\s*[0-9,]+\.?[0-9]*
      |
        fair\s*value\s*range
      |
        argued_range
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Comparison-window tokens
_WINDOW_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ytd", re.compile(r"\bYTD\b|\byear[- ]to[- ]date\b", re.I)),
    ("1y", re.compile(r"\b1[- ]?year\b|\b1[- ]?yr\b|\bone[- ]year\b|\btrailing\s+twelve\b|\bTTM\b", re.I)),
    ("3y", re.compile(r"\b3[- ]?year\b|\b3[- ]?yr\b|\bthree[- ]year\b", re.I)),
    ("5y", re.compile(r"\b5[- ]?year\b|\b5[- ]?yr\b|\bfive[- ]year\b", re.I)),
    ("qoq", re.compile(r"\bQoQ\b|\bquarter[- ]over[- ]quarter\b", re.I)),
    ("yoy", re.compile(r"\bYoY\b|\byear[- ]over[- ]year\b", re.I)),
]

# Labeled metric → number (for contradiction detection).
# Gap excludes `.` so "patents. Fair value $122" does not bind patents→122.
_LABELED_METRIC_RE = re.compile(
    r"""
    \b(?P<label>
        wacc|discount\s+rate|g_terminal|terminal\s+growth|g_high|
        fair\s*value(?:\s*/\s*share|\s+per\s+share)?|price\s*target|
        trailing\s*p/?e|forward\s*p/?e|p/?e|ev/?ebitda|price[- ]to[- ]sales|p/?s|p/?b|
        base\s*fcf|enterprise\s+value|equity\s+value|net\s+debt|
        shares?\s+outstanding|eps
    )
    \b
    [^0-9$.]{0,16}
    (?P<sign>[-+])?
    \$?\s*(?P<num>[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)
    \s*(?P<unit>%|percent|x|×|billion|million|bn|mm|m|k)?
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Count nouns with the number first: "196,000 patents" / "300,000 patents"
_COUNT_BEFORE_LABEL_RE = re.compile(
    r"""
    (?P<num>[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})
    \+?
    \s+
    (?P<label>patents?|shares)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_ARCHETYPE_HINTS = re.compile(
    r"\b("
    r"software_saas|bank_lender|equity_reit|insurance|cyclical_commodity|"
    r"mature_dividend_payer|utility|midstream|general|"
    r"semiconductor|saas|bank|reit|insurer|commodity|dividend\s+payer|"
    r"archetype"
    r")\b",
    re.I,
)

_METHOD_HINTS = re.compile(
    r"\b("
    r"dcf|fcff|fcfe|residual\s+income|dividend\s+discount|ddm|ffo|nav|"
    r"book[- ]value|multiples?|comps?|peer\s+comps?|primary\s+method|"
    r"intrinsic|gordon|epv"
    r")\b",
    re.I,
)

# Explicit open/unresolved risk language (heuristic for c8)
_UNRESOLVED_RISK_RE = re.compile(
    r"("
    r"remains?\s+(open|unresolved|unsettled|uncertain)|"
    r"left\s+(open|unresolved)|"
    r"open\s+question|"
    r"not\s+(yet\s+)?resolved|"
    r"cannot\s+(yet\s+)?(close|rule\s+out)|"
    r"genuinely\s+uncertain|"
    r"still\s+an?\s+open\s+risk|"
    r"key\s+unresolved"
    r")",
    re.I,
)

# Self-neutralizing closes (heuristic fail signals for c8)
_SELF_NEUTRALIZE_RE = re.compile(
    r"("
    r"but\s+I\s+think\s+.+\s+(well\s+suited|can\s+fend|will\s+manage)|"
    r"risks?\s+are\s+(fully\s+)?mitigated|"
    r"nothing\s+to\s+worry\s+about|"
    r"all\s+risks?\s+(are\s+)?(manageable|contained)"
    r")",
    re.I,
)

# Matches "terminal value's ~65% share of enterprise value", "TV/EV", etc.
_TV_SHARE_RE = re.compile(
    r"("
    r"terminal[- ]value'?s?\s*(?:[~≈]?\s*[0-9]+(?:\.[0-9]+)?\s*%\s*)?"
    r"(?:share|as\s+a\s+share|portion|fraction|%|percent)|"
    r"terminal[- ]value'?s?\s+~?\s*[0-9]+(?:\.[0-9]+)?\s*%\s+share|"
    r"tv\s*/\s*ev|"
    r"terminal\s+value\s+(?:is|accounts?\s+for|represents?|comprises?)\s+"
    r"~?\s*[0-9]+(?:\.[0-9]+)?\s*%|"
    r"~?\s*[0-9]+(?:\.[0-9]+)?\s*%\s+(?:share\s+)?of\s+(?:enterprise\s+value|ev)"
    r"(?:\s+(?:is\s+)?(?:from\s+)?terminal)?|"
    r"terminal_value_share_of_ev|"
    r"share\s+of\s+enterprise\s+value\s+means\s+the\s+dcf|"  # "TV's ~65% share of EV means the DCF"
    r"[0-9]+(?:\.[0-9]+)?\s*%\s+share\s+of\s+enterprise\s+value"
    r")",
    re.I,
)


# ── Criterion graders ────────────────────────────────────────────────────────

def _grade_c1(state: dict, text: str, judge: Optional[JudgeFn]) -> dict[str, Any]:
    """Archetype named and primary method justified — LLM preferred."""
    if judge is not None:
        passed, detail = judge(1, state, text)
        return {
            "passed": passed,
            "judged": True,
            "method": "llm_judge",
            "detail": detail,
        }

    has_arch = bool(_ARCHETYPE_HINTS.search(text or ""))
    has_method = bool(_METHOD_HINTS.search(text or ""))
    # Also accept structured critique fields when present.
    vc = state.get("valuation_critique") if isinstance(state.get("valuation_critique"), dict) else {}
    rc = state.get("relative_critique") if isinstance(state.get("relative_critique"), dict) else {}
    if vc.get("archetype") or rc.get("archetype"):
        has_arch = True
    if vc.get("method_reasoning") or rc.get("multiple_reasoning") or vc.get("method_appropriate") is not None:
        has_method = True

    passed = has_arch and has_method
    detail_parts = []
    detail_parts.append("archetype_named" if has_arch else "archetype_missing")
    detail_parts.append("method_justified" if has_method else "method_missing")
    return {
        "passed": passed,
        "judged": False,
        "method": "heuristic_fallback",
        "detail": "; ".join(detail_parts) + " (no judge provided)",
    }


def _evidence_rejection_params(state: dict) -> set[str]:
    """Params the engine rejected specifically for empty/unresolvable evidence."""
    rejected: set[str] = set()
    for key in ("dcf_judgment", "comps_judgment"):
        block = state.get(key)
        if not isinstance(block, dict):
            continue
        for w in block.get("clamp_warnings") or []:
            s = str(w)
            low = s.lower()
            if "evidence" not in low:
                continue
            if "rejected" not in low and "unresolvable" not in low and "empty" not in low:
                continue
            # "high_growth_years rejected: evidence list is empty or unresolvable"
            m = re.match(r"^\s*([A-Za-z0-9_]+)\s+rejected\b", s, re.I)
            if m:
                rejected.add(m.group(1))
    return rejected


def _engine_accepted_dcf_params(state: dict) -> set[str]:
    """Parameters present on the judgment case (engine accepted them)."""
    accepted: set[str] = set()
    dj = state.get("dcf_judgment")
    if not isinstance(dj, dict) or not dj:
        return accepted
    assumptions = dj.get("assumptions") if isinstance(dj.get("assumptions"), dict) else {}
    for k in assumptions:
        accepted.add(str(k))
    inputs = dj.get("inputs") if isinstance(dj.get("inputs"), dict) else {}
    if "base_fcf_method" in inputs or inputs.get("base_fcf_method"):
        accepted.add("base_fcf_method")
    # Also surface from input_source metadata if present
    for k in ("wacc", "g_high", "g_terminal", "high_growth_years", "fade_years", "base_fcf_method"):
        if k in dj:
            accepted.add(k)
    return accepted


def _grade_c2(state: dict) -> dict[str, Any]:
    """Every argued input cites ≥1 resolvable evidence field.

    Uses the engine's ``_has_resolvable_evidence`` / ``_evidence_value`` so the
    grader and ``validate_argued_inputs`` cannot disagree on field resolution
    (e.g. ``canonical_metrics.by_id`` nesting). When the state slice omits
    statement trees, fall back to the engine's own accept/reject record in
    ``clamp_warnings`` + presence on ``dcf_judgment`` rather than false-failing.
    """
    argued: list[tuple[str, str, list[Any]]] = []  # label, param, evidence

    vc = state.get("valuation_critique")
    if isinstance(vc, dict):
        for arg in vc.get("arguments") or []:
            if isinstance(arg, dict):
                param = str(arg.get("parameter") or "unknown")
                evidence = arg.get("evidence") or []
                if not isinstance(evidence, list):
                    evidence = [evidence]
                argued.append((f"dcf:{param}", param, evidence))

    rc = state.get("relative_critique")
    if isinstance(rc, dict):
        for ch in rc.get("peer_changes") or []:
            if isinstance(ch, dict):
                t = str(ch.get("ticker") or "?")
                evidence = ch.get("evidence") or []
                if not isinstance(evidence, list):
                    evidence = [evidence]
                argued.append((f"peer:{t}", f"peer:{t}", evidence))
        jm = rc.get("justified_multiple")
        if isinstance(jm, dict) and jm:
            evidence = jm.get("evidence") or []
            if not isinstance(evidence, list):
                evidence = [evidence]
            argued.append(("justified_multiple", "justified_multiple", evidence))

    if not argued:
        return {
            "passed": True,
            "judged": False,
            "method": "mechanical",
            "detail": "no argued inputs present — vacuous pass (pre-ICL baseline)",
        }

    evidence_rejected = _evidence_rejection_params(state)
    engine_accepted = _engine_accepted_dcf_params(state)
    comps_j = state.get("comps_judgment")
    comps_accepted = bool(isinstance(comps_j, dict) and comps_j)

    failures: list[str] = []
    via_engine_record = 0
    via_resolver = 0
    for label, param, evidence in argued:
        if not evidence:
            failures.append(f"{label}: empty evidence")
            continue
        # (a) Same resolver the engine uses — including by_id / peer_rows.
        if _has_resolvable_evidence(state, evidence):
            via_resolver += 1
            continue
        # Explicit engine rejection for evidence → fail.
        bare = param.split(":", 1)[-1] if param.startswith("dcf:") else param
        if bare in evidence_rejected or param in evidence_rejected:
            bad = ", ".join(str(f) for f in evidence[:4])
            failures.append(f"{label}: engine rejected for unresolvable evidence (tried: {bad})")
            continue
        # (b) Slice may omit statements; if the engine accepted the param live,
        # treat that accept/reject record as authoritative.
        if bare in engine_accepted or (
            param.startswith("peer:") and comps_accepted
        ) or (param == "justified_multiple" and comps_accepted):
            via_engine_record += 1
            continue
        bad = ", ".join(str(f) for f in evidence[:4])
        # Show what the engine resolver saw for debugging.
        tried = []
        for f in evidence[:4]:
            tried.append(f"{f}→{_evidence_value(state, str(f))!r}"[:60])
        failures.append(f"{label}: no resolvable evidence (tried: {bad})")

    if failures:
        return {
            "passed": False,
            "judged": False,
            "method": "mechanical",
            "detail": "; ".join(failures[:8]),
        }
    detail = (
        f"{len(argued)} argued input(s) each have ≥1 resolvable evidence field"
        f" (resolver={via_resolver}, engine_record={via_engine_record})"
    )
    return {
        "passed": True,
        "judged": False,
        "method": "mechanical",
        "detail": detail,
    }


def _grade_c3(state: dict, text: str) -> dict[str, Any]:
    """No currency figure untraceable to an engine block."""
    figures = _parse_currency_matches(text)
    if not figures:
        return {
            "passed": True,
            "judged": False,
            "method": "mechanical",
            "detail": "no currency figures in valuation text",
        }

    allowed = _collect_engine_numbers(state)
    if not allowed:
        # Currency claimed with no engine block at all — fail all of them.
        sample = ", ".join(r for r, _ in figures[:5])
        return {
            "passed": False,
            "judged": False,
            "method": "mechanical",
            "detail": f"currency present ({sample}) but no engine numbers in state",
        }

    untraceable: list[str] = []
    for raw, val in figures:
        if not _number_traceable(val, allowed):
            untraceable.append(raw)

    if untraceable:
        # Deduplicate while preserving order
        seen: set[str] = set()
        uniq: list[str] = []
        for u in untraceable:
            key = u.lower().replace(" ", "")
            if key not in seen:
                seen.add(key)
                uniq.append(u)
        return {
            "passed": False,
            "judged": False,
            "method": "mechanical",
            "detail": f"untraceable currency: {', '.join(uniq[:8])}",
        }
    return {
        "passed": True,
        "judged": False,
        "method": "mechanical",
        "detail": f"{len(figures)} currency figure(s) traceable to engine blocks",
    }


def _grade_c4(state: dict, text: str) -> dict[str, Any]:
    """Terminal-value share of EV stated (DCF path).

    §10.1 scopes this to the DCF path. Residual-income / book methods
    (e.g. ``excess_return_on_equity`` for banks) are N/A — live JPM baseline
    correctly rejected FCF DCF as primary but was false-failed here because
    any fair_value_per_share was treated as a DCF path.
    """
    vc = state.get("valuation_critique") if isinstance(state.get("valuation_critique"), dict) else {}
    dcf = state.get("dcf_engine") if isinstance(state.get("dcf_engine"), dict) else {}

    # If critique says DCF is not the appropriate method, N/A pass.
    if vc.get("method_appropriate") is False:
        return {
            "passed": True,
            "judged": False,
            "method": "mechanical",
            "detail": "DCF path not applicable (method_appropriate=false) — N/A pass",
        }

    method = str(dcf.get("method") or "").lower()
    # Explicit non-FCF-DCF engine methods → N/A (bank residual income, etc.).
    non_fcff_markers = (
        "excess_return",
        "residual_income",
        "dividend_discount",
        "ddm",
        "ffo",
        "nav",
        "book_value",
        "p_b",
        "price_to_book",
    )
    if method and any(m in method for m in non_fcff_markers):
        return {
            "passed": True,
            "judged": False,
            "method": "mechanical",
            "detail": f"non-FCF method ({dcf.get('method')}) — TV-share N/A pass",
        }

    tv_share = vc.get("terminal_value_share_of_ev")
    if isinstance(tv_share, (int, float)):
        return {
            "passed": True,
            "judged": False,
            "method": "mechanical",
            "detail": f"terminal_value_share_of_ev={tv_share} on valuation_critique",
        }

    if _TV_SHARE_RE.search(text or ""):
        return {
            "passed": True,
            "judged": False,
            "method": "mechanical",
            "detail": "terminal-value share language found in valuation text",
        }

    # FCF DCF path: need terminal_value (or EV + projections), not merely a
    # fair_value from a non-DCF engine.
    has_fcf_dcf = bool(
        dcf.get("terminal_value") is not None
        or (dcf.get("projections") and dcf.get("enterprise_value") is not None)
        or "fcf" in method
        or "multi_stage" in method
    )
    if not has_fcf_dcf:
        return {
            "passed": True,
            "judged": False,
            "method": "mechanical",
            "detail": "no FCF DCF path present — N/A pass",
        }

    return {
        "passed": False,
        "judged": False,
        "method": "mechanical",
        "detail": "DCF path present but terminal-value share of EV not stated",
    }


def _is_mechanical_band(fr: dict) -> bool:
    """True if a 'range' is just base × (1∓k) — a fixed ruler, not analysis.

    The FCF path computes real compounded corners, but every other archetype
    (`excess_return_on_equity`, and any path falling through the net-debt
    override) attaches a hardcoded ±15% band. On the 2026-07-30 baseline JPM and
    PGR both shipped one, exact to 14 decimal places, with zero sensitivities
    behind it — and C5 passed them for "expressing a range". A fixed multiplier
    carries no information about this company; it is a point estimate wearing a
    range's clothes.
    """
    low, base, high = fr.get("low"), fr.get("base"), fr.get("high")
    if not all(isinstance(v, (int, float)) for v in (low, base, high)):
        return False
    if not base:
        return False
    down, up = 1.0 - (low / base), (high / base) - 1.0
    # Symmetric to floating-point noise ⇒ generated by a constant multiplier.
    return abs(down - up) < 1e-9 and down > 1e-9


def _substantive_engine_range(state: dict) -> tuple[Optional[str], Optional[dict]]:
    """The first engine/judgment range that reflects real work, if any."""
    for key in ("dcf_judgment", "dcf_engine", "comps_judgment"):
        block = state.get(key)
        if not isinstance(block, dict):
            continue
        fr = block.get("fair_value_range")
        if not isinstance(fr, dict):
            continue
        low, high = fr.get("low"), fr.get("high")
        if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
            continue
        if abs(high - low) <= 1e-9 or _is_mechanical_band(fr):
            continue
        return key, fr
    return None, None


def _grade_c5(state: dict, text: str) -> dict[str, Any]:
    """Valuation expressed as a range, not a point.

    Prose alone is not evidence. Until FWD-07 this criterion returned PASS the
    moment the word "range" appeared anywhere in the valuation text, so PLD
    passed with `fair_value_range` null at every level and no engine fair value
    at all, while JPM and PGR passed on a hardcoded ±15% band. The engine has to
    have produced something real before the narrative can express it.
    """
    source, fr = _substantive_engine_range(state)
    if fr is None:
        # Distinguish "no range at all" from "a fixed ruler" — different fixes.
        mechanical = []
        for key in ("dcf_judgment", "dcf_engine", "comps_judgment"):
            block = state.get(key)
            if isinstance(block, dict) and isinstance(block.get("fair_value_range"), dict):
                if _is_mechanical_band(block["fair_value_range"]):
                    mechanical.append(key)
        if mechanical:
            return {
                "passed": False,
                "judged": False,
                "method": "mechanical",
                "detail": (
                    "range is a fixed ±% band on the point estimate "
                    f"({', '.join(mechanical)}) — no per-company analysis behind it"
                ),
            }
        return {
            "passed": False,
            "judged": False,
            "method": "mechanical",
            "detail": "no engine or judgment fair-value range produced",
        }

    if _RANGE_RE.search(text or ""):
        return {
            "passed": True,
            "judged": False,
            "method": "mechanical",
            "detail": f"range language in valuation text, backed by {source}.fair_value_range",
        }

    # Structured ranges on engine / judgment / critique
    for key in ("dcf_engine", "dcf_judgment", "comps_judgment"):
        block = state.get(key)
        if not isinstance(block, dict):
            continue
        fr = block.get("fair_value_range") or {}
        if isinstance(fr, dict) and fr.get("low") is not None and fr.get("high") is not None:
            # Engine having a range is not enough — the *expression* must be a range.
            # Count only if the narrative cites both corners or says "range".
            low, high = fr.get("low"), fr.get("high")
            low_s = f"{float(low):.2f}" if isinstance(low, (int, float)) else ""
            high_s = f"{float(high):.2f}" if isinstance(high, (int, float)) else ""
            cites_both = (
                low_s
                and high_s
                and low_s.split(".")[0] in (text or "")
                and high_s.split(".")[0] in (text or "")
            )
            if cites_both:
                return {
                    "passed": True,
                    "judged": False,
                    "method": "mechanical",
                    "detail": f"narrative cites both ends of {key}.fair_value_range",
                }

    for key in ("valuation_critique", "relative_critique"):
        obj = state.get(key)
        if not isinstance(obj, dict):
            continue
        for arg in obj.get("arguments") or []:
            if isinstance(arg, dict) and _is_range_pair(arg.get("argued_range")):
                return {
                    "passed": True,
                    "judged": False,
                    "method": "mechanical",
                    "detail": f"argued_range present on {key}",
                }
        jm = obj.get("justified_multiple") if key == "relative_critique" else None
        if isinstance(jm, dict) and _is_range_pair(jm.get("argued_range")):
            # Still need the *valuation* expressed as a range in prose or
            # implied-value band. Structured argued_range alone is a partial signal;
            # accept it as pass for the ICL-era state.
            return {
                "passed": True,
                "judged": False,
                "method": "mechanical",
                "detail": "justified_multiple.argued_range present",
            }

    return {
        "passed": False,
        "judged": False,
        "method": "mechanical",
        "detail": "valuation appears as a point estimate with no range expression",
    }


def _is_range_pair(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return False
    try:
        lo, hi = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return False
    return hi >= lo


def _grade_c6(state: dict) -> dict[str, Any]:
    """Each peer inclusion/exclusion justified individually."""
    rc = state.get("relative_critique") if isinstance(state.get("relative_critique"), dict) else {}
    changes = rc.get("peer_changes") if isinstance(rc.get("peer_changes"), list) else []

    if changes:
        missing: list[str] = []
        for ch in changes:
            if not isinstance(ch, dict):
                missing.append("(malformed peer_change)")
                continue
            t = str(ch.get("ticker") or "?")
            reason = (ch.get("reasoning") or "").strip()
            if not reason:
                missing.append(t)
        if missing:
            return {
                "passed": False,
                "judged": False,
                "method": "mechanical",
                "detail": f"peer_changes missing reasoning: {', '.join(missing[:8])}",
            }
        return {
            "passed": True,
            "judged": False,
            "method": "mechanical",
            "detail": f"{len(changes)} peer_change(s) each justified",
        }

    # Fall back to engine peer_exclusions (pre-ICL): each should carry a reason.
    comps = state.get("comps_engine") if isinstance(state.get("comps_engine"), dict) else {}
    exclusions = comps.get("peer_exclusions") or []
    if exclusions:
        missing = []
        for e in exclusions:
            if isinstance(e, dict):
                if not (e.get("reason") or e.get("reasoning") or "").strip():
                    missing.append(str(e.get("ticker") or "?"))
            else:
                missing.append(str(e))
        if missing:
            return {
                "passed": False,
                "judged": False,
                "method": "mechanical",
                "detail": f"peer_exclusions missing reason: {', '.join(missing[:8])}",
            }
        return {
            "passed": True,
            "judged": False,
            "method": "mechanical",
            "detail": f"{len(exclusions)} engine peer_exclusion(s) justified",
        }

    return {
        "passed": True,
        "judged": False,
        "method": "mechanical",
        "detail": "no peer include/exclude actions — vacuous pass",
    }


def _grade_c7(text: str) -> dict[str, Any]:
    """Comparison windows consistent — fail on YTD vs 1-yr style mixing."""
    present = [name for name, pat in _WINDOW_PATTERNS if pat.search(text or "")]
    # Mixing YTD with a fixed trailing window is the defect called out in §11.3.
    mixed_ytd = "ytd" in present and any(w in present for w in ("1y", "3y", "5y"))
    # Mixing QoQ growth with YoY in the same valuation block without clear labels
    # is softer; only flag the hard §11.3 case.
    if mixed_ytd:
        return {
            "passed": False,
            "judged": False,
            "method": "mechanical",
            "detail": f"mixed comparison windows: {', '.join(present)}",
        }
    return {
        "passed": True,
        "judged": False,
        "method": "mechanical",
        "detail": (
            f"windows present: {', '.join(present)}" if present else "no explicit comparison windows"
        ),
    }


def _grade_c8(state: dict, text: str, judge: Optional[JudgeFn]) -> dict[str, Any]:
    """≥1 risk left explicitly unresolved — LLM preferred."""
    if judge is not None:
        passed, detail = judge(8, state, text)
        return {
            "passed": passed,
            "judged": True,
            "method": "llm_judge",
            "detail": detail,
        }

    has_open = bool(_UNRESOLVED_RISK_RE.search(text or ""))
    has_neutralize = bool(_SELF_NEUTRALIZE_RE.search(text or ""))
    # Heuristic: pass only if open language is present and not fully neutralized.
    if has_open and not has_neutralize:
        return {
            "passed": True,
            "judged": False,
            "method": "heuristic_fallback",
            "detail": "open/unresolved risk language found (no judge provided)",
        }
    if has_neutralize and not has_open:
        return {
            "passed": False,
            "judged": False,
            "method": "heuristic_fallback",
            "detail": "self-neutralizing close detected without open risk language",
        }
    return {
        "passed": False,
        "judged": False,
        "method": "heuristic_fallback",
        "detail": "no explicit unresolved risk language (no judge provided)",
    }


def _grade_c9(state: dict) -> dict[str, Any]:
    """Both default and judgment cases present."""
    dcf_base = _nonempty_dict(state.get("dcf_engine"))
    comps_base = _nonempty_dict(state.get("comps_engine"))
    dcf_j = _nonempty_dict(state.get("dcf_judgment"))
    comps_j = _nonempty_dict(state.get("comps_judgment"))

    # Relative path may be inapplicable (banks, sparse peers).
    comps = state.get("comps_engine") if isinstance(state.get("comps_engine"), dict) else {}
    comps_applicable = bool(comps.get("relative_valuation_applicable", True)) if comps else False

    dcf_ok = dcf_base and dcf_j
    comps_ok = (not comps_applicable) or (comps_base and comps_j)

    # Need at least one valuation path fully present.
    if dcf_ok and comps_ok and (dcf_base or comps_base):
        return {
            "passed": True,
            "judged": False,
            "method": "mechanical",
            "detail": (
                f"dcf_base={dcf_base} dcf_judgment={dcf_j} "
                f"comps_base={comps_base} comps_judgment={comps_j} "
                f"comps_applicable={comps_applicable}"
            ),
        }

    missing = []
    if not dcf_base:
        missing.append("dcf_engine")
    if dcf_base and not dcf_j:
        missing.append("dcf_judgment")
    if comps_applicable and not comps_base:
        missing.append("comps_engine")
    if comps_applicable and comps_base and not comps_j:
        missing.append("comps_judgment")

    return {
        "passed": False,
        "judged": False,
        "method": "mechanical",
        "detail": "missing: " + (", ".join(missing) if missing else "incomplete default/judgment pair"),
    }


def _grade_c10(state: dict) -> dict[str, Any]:
    """Band dissents flagged where applicable."""
    dissents: list[Any] = []
    for key in ("valuation_critique", "relative_critique", "dcf_judgment", "comps_judgment"):
        obj = state.get(key)
        if isinstance(obj, dict) and isinstance(obj.get("band_dissents"), list):
            dissents.extend(obj["band_dissents"])

    if not dissents:
        return {
            "passed": True,
            "judged": False,
            "method": "mechanical",
            "detail": "no band_dissents recorded — N/A pass (nothing to flag)",
        }

    bad: list[str] = []
    for i, d in enumerate(dissents):
        if isinstance(d, str):
            if not d.strip():
                bad.append(f"[{i}] empty string")
        elif isinstance(d, dict):
            if not (d.get("reasoning") or d.get("reason") or d.get("parameter") or "").strip():
                # Require at least a parameter name or reasoning so the dissent is flagged.
                if not d:
                    bad.append(f"[{i}] empty dict")
                # A non-empty dict with parameter is enough.
                elif not d.get("parameter") and not (d.get("reasoning") or d.get("reason")):
                    bad.append(f"[{i}] missing parameter/reasoning")
        else:
            bad.append(f"[{i}] unsupported type")

    if bad:
        return {
            "passed": False,
            "judged": False,
            "method": "mechanical",
            "detail": "band_dissents incomplete: " + "; ".join(bad[:6]),
        }
    return {
        "passed": True,
        "judged": False,
        "method": "mechanical",
        "detail": f"{len(dissents)} band dissent(s) flagged",
    }


# Peer multiples legitimately take many values in one comps write-up.
# Criterion 11 targets *identity* contradictions (patents 196k vs 300k), not
# peer tables and not the intentional two-case (default vs judgment) design.
# Digits belonging to a period token, not to a value: "FY2025", "FY26", "Q1",
# "H1 2026". The label→number gap allows 16 characters, which is enough to reach
# across "EPS ~flat vs FY|2025" and read 202 as an EPS. Observed live on PGR
# (eps 202.0) and CRM (g_high 0.26, scraped from "FY26").
_PERIOD_TOKEN_TAIL_RE = re.compile(r"(?:FY|CY|Q[1-4]\s*(?:FY)?|H[12]\s*)$", re.I)
# "g_high (5-year high-growth rate)" — 5 is a duration in the label's own gloss,
# not a value. Observed live on NVDA (g_high 0.05).
_DURATION_TAIL_RE = re.compile(r"^\s*[-–]\s*(year|yr|month|quarter|day)s?\b", re.I)


def _is_spurious_c11_match(text: str, m: "re.Match[str]") -> bool:
    """Reject matches whose digits are not the labelled quantity.

    C11 failed 5 of 8 tickers on the 2026-07-30 baseline. Every failure I traced
    was one of these two patterns or a period conflation — none were writer
    errors. NVDA's and CRM's flags were invented entirely by the extractor.
    """
    raw = m.group(0)
    num_start = m.start("num") - m.start()
    if _PERIOD_TOKEN_TAIL_RE.search(raw[:num_start].rstrip()):
        return True
    if _DURATION_TAIL_RE.match(text[m.end("num"):m.end("num") + 12]):
        return True
    return False


# "Q1 FY2026" is one quarterly marker, not a quarter followed by an annual one —
# consume the fiscal-year token so the nearest-marker vote cannot be won by the
# FY half of a quarter label.
_QUARTER_CONTEXT_RE = re.compile(
    r"\bQ[1-4]\b(?:\s*(?:FY|CY)?\s*\d{2,4})?|\bquarter(?:ly)?\b"
    r"|_current_quarter|_prior_quarter",
    re.I,
)
_ANNUAL_CONTEXT_RE = re.compile(
    r"year\s+ended|full[- ]year|_current_annual|_prior_annual|\bannual\b|\bFY\d{2,4}\b",
    re.I,
)
# Annualizing is an operation performed *on* a quarterly figure, so a figure
# described that way is quarterly in origin however it is scaled. Both JPM
# ("annualizing Q1 FY2026 EPS of $23.76") and PGR ("EPS of 4.80 annualizes flat
# to FY2025") were misread as annual without this.
_ANNUALIZED_RE = re.compile(r"annualiz|run[- ]rate", re.I)
# Labels where the same name legitimately carries different values across
# periods. Annual and quarterly EPS are not "the same metric stated twice".
_C11_PERIOD_SCOPED_LABELS = frozenset({"eps", "base_fcf"})


def _c11_period_of(text: str, m: "re.Match[str]") -> str:
    """Classify the period a labelled figure belongs to from its context.

    JPM stated FY2025 EPS 20.02, annualized Q1 23.76 and quarterly Q1 5.94 — all
    correctly labelled in the prose — and C11 reported a three-way contradiction.
    PLD tagged its two figures `[eps_diluted__current_annual]` and
    `[..._current_quarter]`; the memo was more precise than the grader.
    """
    start = max(0, m.start() - 130)
    window = text[start: m.end() + 70]
    # Position of the figure inside the window, as the point to measure from.
    anchor_lo = m.start() - start
    anchor_hi = m.end() - start

    def _nearest(pattern: "re.Pattern[str]") -> Optional[int]:
        best: Optional[int] = None
        for mm in pattern.finditer(window):
            if mm.end() <= anchor_lo:
                gap = anchor_lo - mm.end()      # marker before the figure
            elif mm.start() >= anchor_hi:
                gap = mm.start() - anchor_hi    # marker after the figure
            else:
                gap = 0                          # overlaps the figure itself
            if best is None or gap < best:
                best = gap
        return best

    # A window vote is too blunt: on dense valuation prose it picks up the
    # qualifier belonging to a *neighbouring* figure. Distance to the nearest
    # marker is what actually disambiguates "diluted EPS 20.02 from year ended
    # 2025-12-31" (annual, marker adjacent) from "annualizing Q1 FY2026 EPS of
    # $23.76" (quarter, marker adjacent) inside the same paragraph.
    q = _nearest(_QUARTER_CONTEXT_RE)
    ann = _nearest(_ANNUALIZED_RE)
    if ann is not None and (q is None or ann < q):
        q = ann
    a = _nearest(_ANNUAL_CONTEXT_RE)

    if q is None and a is None:
        return "unscoped"
    if a is None:
        return "quarter"
    if q is None:
        return "annual"
    # Ties go to quarter: "Q1 FY2026" is one quarterly label that *contains* an
    # annual-looking token, so both patterns end at the same offset. The
    # quarter reading is strictly the more specific one.
    return "quarter" if q <= a else "annual"


# Labels C11 will compare. Every one here has a structured counterpart the
# argued-shape allowlist can reconcile against (`_argued_shape_allowed_values`),
# so a residual really is unexplained rather than un-modelled.
#
# `eps` was removed after FWD-07. A memo legitimately quotes annual, quarterly
# and annualized-quarterly EPS in the same paragraph — JPM carried 20.02 / 23.76
# / 5.94, all three correctly labelled in the prose — and no amount of regex
# period-scoping separates "annualized Q1" from "raw Q1" reliably, because the
# distinction lives in the sentence, not in the tokens. C11 flagged JPM, PGR and
# PLD for it and was wrong all three times; PLD had tagged each figure with its
# canonical metric id and was still failed.
#
# The right check for EPS is traceability (does each figure match a canonical
# record for the period it claims), which is C3's shape, not a contradiction
# check. Left as a follow-up rather than patched here — see FWD07_REVIEW.md.
_C11_IDENTITY_LABELS = frozenset(
    {
        "wacc",
        "g_terminal",
        "g_high",
        "fair_value",
        "price_target",
        "base_fcf",
        # Count nouns: no period dimension, so no conflation risk.
        "patents",
        "shares",
    }
)


def _norm_c11_label(raw: str) -> str:
    label = re.sub(r"\s+", " ", raw.lower()).strip()
    return {
        "discount rate": "wacc",
        "p/e": "pe",
        "trailing p/e": "trailing_pe",
        "forward p/e": "forward_pe",
        "ev/ebitda": "ev_ebitda",
        "price-to-sales": "ps",
        "p/s": "ps",
        "p/b": "pb",
        "fair value / share": "fair_value",
        "fair value per share": "fair_value",
        "fair value": "fair_value",
        "price target": "price_target",
        "terminal growth": "g_terminal",
        "g_terminal": "g_terminal",
        "g_high": "g_high",
        "high-growth": "g_high",
        "high growth": "g_high",
        "base fcf": "base_fcf",
        "enterprise value": "ev",
        "equity value": "equity_value",
        "net debt": "net_debt",
        "shares outstanding": "shares",
        "share outstanding": "shares",
        "share": "shares",
        "shares": "shares",
        "patent": "patents",
        "patents": "patents",
        "eps": "eps",
    }.get(label, label)


def _as_float(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _extend_floats(dest: list[float], *values: Any) -> None:
    for v in values:
        if isinstance(v, (list, tuple)):
            for item in v:
                f = _as_float(item)
                if f is not None:
                    dest.append(f)
        else:
            f = _as_float(v)
            if f is not None:
                dest.append(f)


def _argued_shape_allowed_values(state: dict) -> dict[str, list[float]]:
    """Numbers that are intentionally present under the full argued-output shape.

    VAL-15 four-value (plus sensitivities) shape, read from structured state
    rather than prose:

    * ``dcf_engine.fair_value_per_share`` — sector-default case
    * ``dcf_judgment.fair_value_range.base`` / ``central_case`` — central case
      (every argued parameter at its range midpoint)
    * ``fair_value_range.low`` / ``low_case`` — compounded pessimistic corner
    * ``fair_value_range.high`` / ``high_case`` — compounded optimistic corner
    * ``sensitivities[*].fair_value_per_share`` — one parameter moved alone

    Also absorbs rate assumptions at each of those points, critique
    ``argued_range`` corners, and comps-implied values.
    """
    allowed: dict[str, list[float]] = {
        "wacc": [],
        "g_high": [],
        "g_terminal": [],
        "fair_value": [],
        "base_fcf": [],
        "price_target": [],
        "eps": [],
    }

    def _ingest_engine_block(block: Any, *, depth: int = 0) -> None:
        if not isinstance(block, dict) or not block or depth > 4:
            return
        assumptions = block.get("assumptions") if isinstance(block.get("assumptions"), dict) else {}
        # low/high cases store assumptions nested under low/high keys in some shapes
        if "wacc" not in assumptions and isinstance(assumptions.get("low"), dict):
            for side in ("low", "high"):
                side_a = assumptions.get(side)
                if isinstance(side_a, dict):
                    for key in ("wacc", "g_high", "g_terminal"):
                        _extend_floats(allowed[key], side_a.get(key))
        inputs = block.get("inputs") if isinstance(block.get("inputs"), dict) else {}
        for key in ("wacc", "g_high", "g_terminal"):
            _extend_floats(allowed[key], assumptions.get(key), block.get(key))
        _extend_floats(
            allowed["fair_value"],
            block.get("fair_value_per_share"),
            block.get("epv_per_share"),
        )
        fr = block.get("fair_value_range") if isinstance(block.get("fair_value_range"), dict) else {}
        _extend_floats(
            allowed["fair_value"],
            fr.get("low"),
            fr.get("base"),
            fr.get("high"),
        )
        # Nested structured cases (VAL-14/15 shape)
        for corner_key in (
            "low_case",
            "high_case",
            "base_case",
            "central_case",
            "base_engine",
        ):
            corner = block.get(corner_key)
            if isinstance(corner, dict):
                _ingest_engine_block(corner, depth=depth + 1)
        # One-at-a-time sensitivity table — each FV is a legitimate design output
        sens = block.get("sensitivities")
        if isinstance(sens, list):
            for row in sens:
                if not isinstance(row, dict):
                    continue
                _extend_floats(
                    allowed["fair_value"],
                    row.get("fair_value_per_share"),
                    row.get("fair_value"),
                )
                param = str(row.get("parameter") or "")
                if param in ("wacc", "g_high", "g_terminal"):
                    _extend_floats(
                        allowed[param],
                        row.get("engine_default"),
                        row.get("argued_midpoint"),
                    )
        _extend_floats(
            allowed["base_fcf"],
            inputs.get("base_fcf_annual"),
            inputs.get("base_fcf"),
            assumptions.get("base_fcf"),
        )
        _extend_floats(
            allowed["eps"],
            inputs.get("eps_diluted_current"),
            inputs.get("eps_basic_current"),
            block.get("eps_diluted"),
            block.get("eps"),
        )
        # Comps implied values
        for k in (
            "implied_value_low",
            "implied_value_high",
            "implied_low",
            "implied_high",
            "implied_value_per_share",
        ):
            _extend_floats(allowed["fair_value"], block.get(k))
        corners = block.get("corners")
        if isinstance(corners, list):
            for c in corners:
                if isinstance(c, dict):
                    _extend_floats(
                        allowed["fair_value"],
                        c.get("implied_value"),
                        c.get("implied_value_per_share"),
                        c.get("fair_value_per_share"),
                        c.get("value"),
                    )
                    _extend_floats(allowed["wacc"], c.get("wacc"))
                    _extend_floats(allowed["g_high"], c.get("g_high"))
                    _extend_floats(allowed["g_terminal"], c.get("g_terminal"))

    for key in ("dcf_engine", "dcf_judgment", "comps_engine", "comps_judgment"):
        _ingest_engine_block(state.get(key))

    # Argued ranges from critiques (the two corners of each argued parameter)
    vc = state.get("valuation_critique")
    if isinstance(vc, dict):
        for arg in vc.get("arguments") or []:
            if not isinstance(arg, dict):
                continue
            param = str(arg.get("parameter") or "")
            if param in allowed:
                _extend_floats(allowed[param], arg.get("argued_range"), arg.get("engine_default"))
        for d in vc.get("band_dissents") or []:
            if isinstance(d, dict) and str(d.get("parameter") or "") in allowed:
                _extend_floats(allowed[str(d["parameter"])], d.get("argued_range"))

    return allowed


# Back-compat alias used by older tests / call sites.
_two_case_allowed_values = _argued_shape_allowed_values


def _value_in_allowed(val: float, allowed: list[float], *, rate: bool = False) -> bool:
    if not allowed:
        return False
    for a in allowed:
        # Absolute tolerance: share prices / FCF in dollars; rates as fractions.
        if rate:
            tol = max(0.005, 0.02 * max(abs(a), abs(val), 1e-9))
        else:
            tol = max(0.75, 0.02 * max(abs(a), abs(val), 1e-9))
        if abs(val - a) <= tol:
            return True
        # Percent-display of a rate: 10.5 vs 0.105
        if rate and abs(val) > 1.0 and abs(val / 100.0 - a) <= max(tol, 0.005):
            return True
        if rate and abs(a) > 1.0 and abs(val - a / 100.0) <= max(tol, 0.005):
            return True
        # Dollar magnitudes quoted in K/M/B/T display form ($96.68B vs 9.67e10).
        if not rate and abs(a) >= 1e6:
            for scale in (1e3, 1e6, 1e9, 1e12):
                scaled = a / scale
                st = max(0.02 * max(abs(scaled), abs(val), 1e-9), 0.05)
                if abs(val - scaled) <= st:
                    return True
                if abs(val * scale - a) / max(abs(a), 1e-9) <= 0.02:
                    return True
    return False


def _grade_c11(state: dict, text: str) -> dict[str, Any]:
    """No internal numeric contradiction within a single case.

    Argued-shape aware (VAL-13/15): values that reconcile to any of

    * sector default (``dcf_engine``),
    * central case (``fair_value_range.base`` / ``central_case``),
    * compounded corners (``low`` / ``high`` / ``low_case`` / ``high_case``),
    * single-parameter sensitivities (``sensitivities[*].fair_value_per_share``),
    * critique ``argued_range`` corners for rate inputs,

    are NOT contradictions — they are the design. Only flag the same quantity
    stated inconsistently outside that permitted set (e.g. patents 196k vs 300k).

    Allowed values are read from structured ``dcf_judgment`` / engine dicts,
    not pattern-matched from prose.
    """
    if not (text or "").strip():
        return {
            "passed": True,
            "judged": False,
            "method": "mechanical",
            "detail": "empty valuation text",
        }

    by_label: dict[str, list[float]] = {}
    allowed = _argued_shape_allowed_values(state)

    for m in _LABELED_METRIC_RE.finditer(text):
        label = _norm_c11_label(m.group("label"))
        if label not in _C11_IDENTITY_LABELS:
            continue
        raw = m.group(0)
        if _is_spurious_c11_match(text, m):
            continue
        try:
            num = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        if m.group("sign") == "-":
            num = -num
        unit = (m.group("unit") or "").lower()
        if label in ("wacc", "g_terminal", "g_high"):
            if "$" in raw:
                continue
            # "NOW's 68.8x trailing" is a multiple, never a growth or discount
            # rate. Before FWD-07 this was read as g_high = 68.8%.
            if (m.group("unit") or "").lower() in ("x", "×"):
                continue
            if re.search(r"\bby\s+Y?\s*\d+\s*$", raw, re.I):
                continue
            if re.search(r"terminal\s+growth\s+by\s+Y", raw, re.I):
                continue
            if unit in ("%", "percent"):
                num = num / 100.0 if abs(num) > 1.0 else num
            elif abs(num) > 1.0:
                if abs(num) <= 100:
                    num = num / 100.0
                else:
                    continue
            if abs(num) > 1.0:
                continue
        key = label
        if label in _C11_PERIOD_SCOPED_LABELS:
            key = f"{label}@{_c11_period_of(text, m)}"
        by_label.setdefault(key, []).append(num)

    for m in _COUNT_BEFORE_LABEL_RE.finditer(text):
        label = _norm_c11_label(m.group("label"))
        if label not in _C11_IDENTITY_LABELS:
            continue
        try:
            num = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        by_label.setdefault(label, []).append(num)

    conflicts: list[str] = []
    explained = 0
    for scoped_label, vals in by_label.items():
        # Keys may carry a period suffix ("eps@quarter"); allowed-value and
        # rate lookups are keyed on the bare label.
        label = scoped_label.split("@", 1)[0]
        if len(vals) < 2:
            continue
        uniq: list[float] = []
        for v in vals:
            pool = ([v] + uniq) if uniq else [v]
            tol = max(0.02 * max(abs(u) for u in pool), 0.005 if abs(v) < 2 else 0.5)
            if not any(abs(v - u) <= tol for u in uniq):
                uniq.append(v)
        if len(uniq) < 2:
            continue

        is_rate = label in ("wacc", "g_high", "g_terminal")
        permitted = allowed.get(label) or []
        residual = [v for v in uniq if not _value_in_allowed(v, permitted, rate=is_rate)]
        # Base FCF is often narrated next to YoY % growth ("base FCF … 58.9%").
        # When permitted values are large dollar magnitudes, drop residual
        # candidates that look like percentages, not FCF dollars.
        if label == "base_fcf" and permitted and any(abs(a) >= 1e6 for a in permitted):
            residual = [v for v in residual if not (0 < abs(v) <= 100)]

        if not residual:
            # Every distinct value is accounted for by the two-case design.
            explained += 1
            continue
        if len(residual) == 1 and len(uniq) - len(residual) >= 1:
            # One leftover next to permitted two-case values — often live price
            # or a sensitivity illustration. Not a same-case contradiction.
            explained += 1
            continue
        if len(residual) >= 2:
            conflicts.append(
                f"{scoped_label}: {residual[:4]} (not explained by argued shape: "
                f"default/central/corners/sensitivities)"
            )

    if conflicts:
        return {
            "passed": False,
            "judged": False,
            "method": "mechanical",
            "detail": "contradictions: " + "; ".join(conflicts[:6]),
        }
    detail = f"no within-case contradictions across {len(by_label)} identity metric(s)"
    if explained:
        detail += (
            f"; {explained} multi-value set(s) explained by "
            f"default/central/corners/sensitivities"
        )
    return {
        "passed": True,
        "judged": False,
        "method": "mechanical",
        "detail": detail,
    }


def _summary_notes(results: list[dict[str, Any]]) -> str:
    failed = [r for r in results if not r["passed"]]
    judged = [r for r in results if r.get("judged")]
    parts = [f"passed {sum(1 for r in results if r['passed'])}/{len(results)}"]
    if failed:
        parts.append("failed: " + ", ".join(f"{r['id']}:{r['name']}" for r in failed))
    if judged:
        parts.append("llm-judged: " + ", ".join(str(r["id"]) for r in judged))
    return "; ".join(parts)


__all__ = [
    "RUBRIC",
    "HELD_OUT_TICKERS",
    "grade_valuation",
    "format_rubric_for_prompt",
]
