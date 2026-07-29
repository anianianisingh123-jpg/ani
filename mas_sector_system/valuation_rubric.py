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

# Allowed evidence field roots per §4.4 (used by criterion 2).
_EVIDENCE_ROOTS: tuple[str, ...] = (
    "canonical_metrics",
    "income_statement",
    "balance_sheet",
    "cash_flow_statement",
    "comps_engine",
    "dcf_engine",
    "business_overview",
    "macro_regime_assessment",
    "management_assessment",
    "capital_allocation_assessment",
)

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
        "criterion": "No currency figure appears that is not traceable to an engine block",
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
        11: lambda: _grade_c11(agent_text),
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
    """Absolute numeric values that count as engine-traceable."""
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
        wacc|discount\s+rate|g_terminal|terminal\s+growth|g_high|high[- ]growth|
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


def _grade_c2(state: dict) -> dict[str, Any]:
    """Every argued input cites ≥1 resolvable evidence field."""
    argued: list[tuple[str, list[Any]]] = []

    vc = state.get("valuation_critique")
    if isinstance(vc, dict):
        for arg in vc.get("arguments") or []:
            if isinstance(arg, dict):
                param = str(arg.get("parameter") or "unknown")
                evidence = arg.get("evidence") or []
                if not isinstance(evidence, list):
                    evidence = [evidence]
                argued.append((f"dcf:{param}", evidence))

    rc = state.get("relative_critique")
    if isinstance(rc, dict):
        for ch in rc.get("peer_changes") or []:
            if isinstance(ch, dict):
                t = str(ch.get("ticker") or "?")
                evidence = ch.get("evidence") or []
                if not isinstance(evidence, list):
                    evidence = [evidence]
                argued.append((f"peer:{t}", evidence))
        jm = rc.get("justified_multiple")
        if isinstance(jm, dict) and jm:
            evidence = jm.get("evidence") or []
            if not isinstance(evidence, list):
                evidence = [evidence]
            argued.append(("justified_multiple", evidence))

    if not argued:
        # No argued inputs yet (pre-ICL baseline): vacuously satisfied.
        return {
            "passed": True,
            "judged": False,
            "method": "mechanical",
            "detail": "no argued inputs present — vacuous pass (pre-ICL baseline)",
        }

    # §4.4: each argued parameter needs ≥1 resolvable evidence field.
    # Extra unresolvable citations are noise, not a fail — validate_argued_inputs
    # accepts the param when any listed field resolves; the grader must match.
    failures: list[str] = []
    for label, evidence in argued:
        if not evidence:
            failures.append(f"{label}: empty evidence")
            continue
        resolved = [str(f) for f in evidence if _evidence_resolves(state, str(f))]
        if not resolved:
            bad = ", ".join(str(f) for f in evidence[:4])
            failures.append(f"{label}: no resolvable evidence (tried: {bad})")

    if failures:
        return {
            "passed": False,
            "judged": False,
            "method": "mechanical",
            "detail": "; ".join(failures[:8]),
        }
    return {
        "passed": True,
        "judged": False,
        "method": "mechanical",
        "detail": f"{len(argued)} argued input(s) each have ≥1 resolvable evidence field",
    }


def _evidence_resolves(state: dict, field_id: str) -> bool:
    """§4.4: evidence must resolve to a non-null value under an allowed root."""
    if not field_id or not isinstance(field_id, str):
        return False
    root = field_id.split(".", 1)[0]
    if root not in _EVIDENCE_ROOTS:
        return False

    # Narrative roots: non-empty string is enough.
    if root in (
        "business_overview",
        "macro_regime_assessment",
        "management_assessment",
        "capital_allocation_assessment",
    ):
        val = state.get(root)
        return isinstance(val, str) and bool(val.strip())

    parts = field_id.split(".")
    cur: Any = state
    for p in parts:
        if isinstance(cur, dict):
            if p not in cur:
                # comps_engine.peer_rows.XXXX style — accept if parent peer list
                # contains the ticker even when path is not nested exactly.
                if p in ("peer_rows", "peers") and isinstance(cur.get("peers"), list):
                    cur = {str(r.get("ticker")): r for r in cur["peers"] if isinstance(r, dict)}
                    continue
                return False
            cur = cur[p]
        else:
            return False

    if cur is None:
        return False
    if isinstance(cur, dict):
        # canonical_metrics record: need a non-null value key when present.
        if "value" in cur:
            return cur.get("value") is not None
        return bool(cur)
    if isinstance(cur, str):
        return bool(cur.strip())
    if isinstance(cur, (list, tuple)):
        return len(cur) > 0
    return True


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


def _grade_c5(state: dict, text: str) -> dict[str, Any]:
    """Valuation expressed as a range, not a point."""
    if _RANGE_RE.search(text or ""):
        return {
            "passed": True,
            "judged": False,
            "method": "mechanical",
            "detail": "range language detected in valuation text",
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
# Criterion 11 targets *identity* contradictions (patents 196k vs 300k; two
# different fair values presented as the same base case), not peer tables.
_C11_IDENTITY_LABELS = frozenset(
    {
        "wacc",
        "g_terminal",
        "g_high",
        "fair_value",
        "price_target",
        "base_fcf",
        "patents",
        "shares",
        "eps",
    }
)


def _grade_c11(text: str) -> dict[str, Any]:
    """No internal numeric contradiction (same identity metric, two values)."""
    if not (text or "").strip():
        return {
            "passed": True,
            "judged": False,
            "method": "mechanical",
            "detail": "empty valuation text",
        }

    by_label: dict[str, list[float]] = {}

    def _norm_label(raw: str) -> str:
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

    for m in _LABELED_METRIC_RE.finditer(text):
        label = _norm_label(m.group("label"))
        if label not in _C11_IDENTITY_LABELS:
            continue
        raw = m.group(0)
        try:
            num = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        if m.group("sign") == "-":
            num = -num
        unit = (m.group("unit") or "").lower()
        # Rates: reject "$5.04" bound after "WACC" (live NVDA: "At 10.0% WACC, ~$5.04T").
        # Also reject "terminal growth by Y10" binding year 10 as g_terminal.
        if label in ("wacc", "g_terminal", "g_high"):
            if "$" in raw:
                continue
            if re.search(r"\bby\s+Y?\s*\d+\s*$", raw, re.I):
                continue
            if re.search(r"terminal\s+growth\s+by\s+Y", raw, re.I):
                continue
            if unit in ("%", "percent"):
                num = num / 100.0 if abs(num) > 1.0 else num
            elif abs(num) > 1.0:
                # bare 10.0 after WACC → treat as percent
                if abs(num) <= 100:
                    num = num / 100.0
                else:
                    continue
            # Growth/WACC rates are fractions in (0, 1] or small negatives; a bare
            # integer 10 from "Y10" after unit stripping should not survive.
            if abs(num) > 1.0:
                continue
        by_label.setdefault(label, []).append(num)

    for m in _COUNT_BEFORE_LABEL_RE.finditer(text):
        label = _norm_label(m.group("label"))
        if label not in _C11_IDENTITY_LABELS:
            continue
        try:
            num = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        by_label.setdefault(label, []).append(num)

    conflicts: list[str] = []
    for label, vals in by_label.items():
        if len(vals) < 2:
            continue
        # Distinct values beyond tolerance
        uniq: list[float] = []
        for v in vals:
            tol = max(0.02 * max(abs(u) for u in [v] + uniq) if uniq else 0.02 * abs(v), 0.005 if abs(v) < 2 else 0.5)
            if not any(abs(v - u) <= tol for u in uniq):
                uniq.append(v)
        if len(uniq) >= 2:
            conflicts.append(f"{label}: {uniq[:4]}")

    if conflicts:
        return {
            "passed": False,
            "judged": False,
            "method": "mechanical",
            "detail": "contradictions: " + "; ".join(conflicts[:6]),
        }
    return {
        "passed": True,
        "judged": False,
        "method": "mechanical",
        "detail": f"no contradictions across {len(by_label)} identity metric(s)",
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
