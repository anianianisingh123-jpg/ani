"""Split the run deliverable into two separate artifacts.

Historically the reader-facing memo, the QC findings, and the data-quality
disclosures were mashed into one document: ``docx_export_node`` appended a
``## QC Notes`` block on PASS_WITH_FLAGS and ``append_cost_to_memo`` appended a
run-cost block, on top of whatever validation warnings synthesis disclosed
inline.

This module separates the two audiences:

1. ``{TICKER}_{DATE}_clean_memo.json`` — the thesis only: business overview,
   recommendation, macro positioning, management/capital allocation, key
   debate, valuation reconciliation, catalysts/risks.
2. ``{TICKER}_{DATE}_compliance_audit_log.md`` — every data-quality
   disclosure: stale XBRL tags, validation gate warnings/failures, QC report
   and status, metric availability, and the run-cost block.

Design constraints:

- **Parses ``final_memo``, never ``styled_memo``.** ``style_pass_node`` is
  explicitly allowed to rename section headers, so heading-keyed parsing over
  the styled text is nondeterministic. ``final_memo`` carries the headings the
  synthesis prompt names verbatim and is overwritten by the QC retry, so it is
  the substance-of-record. The .docx keeps rendering ``styled_memo``.
- **No LLM call and no new graph node.** Pure deterministic post-processing,
  invoked from inside existing terminal nodes.
- **Nothing is silently dropped.** Sections that do not map to a known key are
  preserved under ``unmapped_sections``; absent sections are ``null`` and named
  in ``sections_missing`` rather than emitted as empty strings.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_DIR.parent
DEFAULT_OUTPUT_DIR = _REPO_ROOT / "outputs"

# Held at 1.1 deliberately when `headline_source` was added (2026-08-03, VAL-18).
# The field is additive and optional: every 1.1 consumer that ignores it still
# reads a valid artifact, and `_target_basis` degrades to "Memo text" when it is
# absent. **1.2 is reserved for VAL-08** (judgment blocks + disclosure routing),
# which is a genuine shape change; burning the number on an optional string
# would leave that ticket without a version to claim. A consumer that must
# distinguish "old artifact" from "field not computed" should test for the key,
# not the version.
CLEAN_MEMO_SCHEMA_VERSION = "1.1"

# ── Numeric contract (schema 1.1) ────────────────────────────────────────────
# 1.0 carried prose only, so any downstream renderer had thesis text and no
# figures to chart. 1.1 adds `metrics` and `valuation` blocks. The audience
# split is unchanged and load-bearing: metric *values* are thesis content;
# every statement about a value's *reliability* is compliance content and stays
# in the audit log.
#
# Consequences, all deliberate:
#   - A metric with a non-empty `staleness` list is omitted from the clean memo
#     entirely rather than exported with a caveat, so a stale figure can never
#     reach a reader-facing deliverable. The count is disclosed; the values are
#     not. Nothing is lost — §1 of the audit log already itemises every one.
#   - Engine warnings/errors and peer exclusions are stripped from the
#     valuation block and re-emitted in §6 of the audit log. Stripping without
#     re-emitting would destroy them, which the module contract forbids.
_METRIC_PUBLIC_FIELDS = (
    "id",
    "value",
    "unit",
    "basis_period",
    "period_key",
    "headline",
    "computation",
    "qualifiers",
    "confidence",
)

# Engine keys that describe data quality rather than value. Audit log only.
_DCF_DISCLOSURE_FIELDS = ("warnings", "errors")
_COMPS_DISCLOSURE_FIELDS = ("peer_exclusions", "notes")
# Judgment-layer (argued-input) disclosures. These live on `dcf_judgment` /
# `comps_judgment`, not on the engine blocks — see collect_valuation_disclosures.
_JUDGMENT_DISCLOSURE_FIELDS = ("clamp_warnings", "band_dissents", "errors")

# Blocks that must never reach the clean memo, in case an upstream path ever
# appends them to final_memo. Matched case-sensitively on the exact markers
# written by cost.format_memo_appendix / docx_export_node.
_APPENDIX_MARKERS = ("── Run Cost ──", "## QC Notes")

_ATX_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_BOLD_LINE_RE = re.compile(r"^\*\*(.+?)\*\*:?\s*$")
_NUMBERED_CAPS_RE = re.compile(r"^\s*(?:\d+[.)]\s*)?([A-Z][A-Z0-9 &/,'\-()]{5,})\s*:?\s*$")


# Ordered section contract. Keys mirror the seven-part structure in
# SYNTHESIS_SYSTEM_PROMPT, plus the optional "Thesis evolution" note the
# synthesis user prompt requests when prior desk memory is loaded.
SECTION_SPECS: list[dict[str, Any]] = [
    {
        "key": "business_overview",
        "title": "Business Overview",
        "keywords": ("BUSINESS OVERVIEW", "UNDERSTANDING THE BUSINESS", "WHAT THE COMPANY DOES"),
    },
    {
        "key": "recommendation",
        "title": "Recommendation",
        "keywords": ("RECOMMENDATION", "THE CALL", "OUR VIEW", "VERDICT"),
    },
    {
        "key": "macro_positioning",
        "title": "Macro / Cycle Positioning",
        "keywords": ("MACRO", "CYCLE POSITIONING", "REGIME"),
    },
    {
        "key": "management_and_capital_allocation",
        "title": "Management & Capital Allocation",
        "keywords": ("MANAGEMENT", "CAPITAL ALLOCATION", "STEWARDSHIP"),
    },
    {
        "key": "key_debate_points",
        "title": "Key Debate Points",
        "keywords": ("KEY DEBATE", "DEBATE", "BULL VS BEAR", "BULL AND BEAR"),
    },
    {
        "key": "valuation_reconciliation",
        "title": "Valuation Reconciliation",
        "keywords": ("VALUATION", "WHAT IT IS WORTH", "FAIR VALUE"),
    },
    {
        "key": "catalysts_and_risks",
        "title": "Risks, Catalysts & Monitoring Triggers",
        "keywords": (
            "RISK",
            "MONITORING",
            "TRIGGER",
            "CATALYST",
            "WHAT TO WATCH",
            "FLIP FACTOR",
        ),
    },
    {
        "key": "thesis_evolution",
        "title": "Thesis Evolution",
        "keywords": ("THESIS EVOLUTION", "VS PRIOR", "SINCE LAST", "PRIOR DESK"),
    },
]

# The four groupings the desk asked for, expressed as views over the sections
# above so no section is lost to the grouping.
CLEAN_MEMO_VIEWS: dict[str, tuple[str, ...]] = {
    "fundamental_thesis": (
        "business_overview",
        "recommendation",
        "key_debate_points",
        "management_and_capital_allocation",
        "thesis_evolution",
    ),
    "macro_positioning": ("macro_positioning",),
    "valuation": ("valuation_reconciliation",),
    "catalysts": ("catalysts_and_risks",),
}

_SECTION_KEYS = [s["key"] for s in SECTION_SPECS]

# Synthesis is still instructed to disclose validation warnings inline
# (agents.py, "If validation WARNINGs are present, disclose them in the memo"),
# and Opus reliably emits them as their own section. That section is compliance
# content by definition: it is routed to the audit log and kept out of the
# clean memo. The synthesis prompt is deliberately NOT changed to suppress it —
# inline disclosure that is load-bearing for the thesis stays where the analyst
# put it, and QC audits the memo for exactly that honesty.
DISCLOSURE_KEYWORDS = (
    "DATA QUALITY",
    "DATA LIMITATION",
    "DISCLOSURE",
    "DATA CAVEAT",
    "DATA INTEGRITY",
)

# Minimum ATX headings before bold / ALL-CAPS lines stop counting as headings.
# A well-formed memo uses ATX throughout; in that case bold standalone lines
# ("**What would change this to HOLD:**") are paragraph lead-ins, and treating
# them as headings fragments real sections.
_ATX_DOMINANCE_THRESHOLD = 3


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_ticker(ticker: Optional[str]) -> str:
    return re.sub(r"[^\w.-]+", "_", (ticker or "SECTOR").strip().upper()) or "SECTOR"


def strip_appendices(memo: str) -> str:
    """Drop any appended cost / QC-notes block from a memo body."""
    body = memo or ""
    cut = len(body)
    for marker in _APPENDIX_MARKERS:
        idx = body.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    return body[:cut].rstrip()


def _heading(line: str, *, atx_only: bool = False) -> Optional[tuple[str, Optional[int]]]:
    """Return ``(text, level)`` for a heading line, or None if it is not one.

    Recognizes ATX headings, bold-only lines, and bare ALL-CAPS lines with an
    optional leading number — synthesis emits all three shapes in practice.
    ``atx_only`` disables the looser two when the memo is ATX-structured.
    ``level`` is the ATX depth; pseudo-headings carry ``None`` (no depth), and
    always act as section boundaries.
    """
    stripped = line.strip()
    if not stripped:
        return None

    m = _ATX_RE.match(stripped)
    if m:
        return m.group(2).strip(), len(m.group(1))
    if atx_only:
        return None

    m = _BOLD_LINE_RE.match(stripped)
    if m:
        text = m.group(1).strip()
        # A bold sentence is not a heading; headings are short.
        if len(text) <= 80 and not text.endswith("."):
            return text, None
        return None

    m = _NUMBERED_CAPS_RE.match(stripped)
    if m:
        text = m.group(1).strip()
        if len(text) <= 80:
            return text, None
        return None

    return None


def _heading_text(line: str, *, atx_only: bool = False) -> Optional[str]:
    """Heading text only — thin wrapper over :func:`_heading`."""
    found = _heading(line, atx_only=atx_only)
    return found[0] if found else None


def _section_level(levels: list[int]) -> Optional[int]:
    """The ATX depth that delimits top-level sections, or None if undecidable.

    Synthesis writes the memo as one H1 title followed by numbered H2 sections,
    each of which may carry H3 sub-headings ("Where the bear lands real blows").
    Treating every heading as a boundary — the pre-fix behaviour — orphaned
    those H3 bodies into ``unmapped_sections`` because their parent key was
    already ``taken``, thinning the real sections to a sentence.

    The delimiting depth is the *shallowest* depth used more than once: a lone
    H1 is a document title, not a section. When no depth repeats there is no
    hierarchy to infer, so the caller falls back to boundary-per-heading.
    """
    counts: dict[int, int] = {}
    for lv in levels:
        counts[lv] = counts.get(lv, 0) + 1
    repeated = [lv for lv, n in sorted(counts.items()) if n >= 2]
    return repeated[0] if repeated else None


def _normalize_title(title: str) -> str:
    """Uppercase, strip markdown/numbering/punctuation for keyword matching."""
    t = re.sub(r"[*_`#]", "", title or "")
    t = re.sub(r"^\s*\d+\s*[.)\-:]\s*", "", t)
    t = re.sub(r"[^A-Za-z0-9 &/]", " ", t)
    return re.sub(r"\s+", " ", t).strip().upper()


def _match_section_key(title: str, taken: set[str]) -> Optional[str]:
    """Map a heading to a section key by keyword, longest keyword wins."""
    norm = _normalize_title(title)
    if not norm:
        return None
    best: Optional[tuple[int, str]] = None
    for spec in SECTION_SPECS:
        key = spec["key"]
        if key in taken:
            continue
        for kw in spec["keywords"]:
            if kw in norm:
                score = len(kw)
                if best is None or score > best[0]:
                    best = (score, key)
    return best[1] if best else None


def split_memo_sections(memo: str) -> dict[str, Any]:
    """Split a raw synthesis memo into mapped sections + preamble + leftovers.

    Returns ``{"sections", "unmapped_sections", "preamble", "order"}``. Never
    raises on malformed input; an unparseable memo yields empty sections and
    the whole body as preamble, which the caller surfaces honestly.
    """
    body = strip_appendices(memo)
    lines = body.replace("\r\n", "\n").split("\n")

    # If the memo is ATX-structured, bold/caps lines are lead-ins, not headings.
    atx_levels = [len(m.group(1)) for m in (_ATX_RE.match(ln.strip()) for ln in lines) if m]
    atx_only = len(atx_levels) >= _ATX_DOMINANCE_THRESHOLD
    section_level = _section_level(atx_levels) if atx_only else None

    blocks: list[dict[str, Any]] = []
    preamble: list[str] = []
    current: Optional[dict[str, Any]] = None

    for line in lines:
        found = _heading(line, atx_only=atx_only)
        if found is not None:
            title, level = found
            # A heading deeper than the section depth is a sub-heading: it stays
            # inside its parent's body (verbatim, so the renderer keeps it) and
            # is also indexed under ``subsections`` for structured layouts.
            if (
                section_level is not None
                and level is not None
                and level > section_level
                and current is not None
            ):
                current["subsections"].append({"title": title, "level": level, "start": len(current["lines"])})
                current["lines"].append(line)
                continue
            if current is not None:
                blocks.append(current)
            current = {"title": title, "level": level, "lines": [], "subsections": []}
            continue
        if current is None:
            preamble.append(line)
        else:
            current["lines"].append(line)
    if current is not None:
        blocks.append(current)

    # A lone heading shallower than the section depth is the document title
    # ("# NVIDIA CORPORATION (NVDA)"), not a section. Its body is the preamble.
    doc_title: Optional[str] = None
    if (
        blocks
        and section_level is not None
        and blocks[0].get("level") is not None
        and blocks[0]["level"] < section_level
        and sum(1 for lv in atx_levels if lv == blocks[0]["level"]) == 1
    ):
        head = blocks.pop(0)
        doc_title = head["title"].strip()
        preamble = preamble + head["lines"]

    sections: dict[str, str] = {}
    subsections: dict[str, list[dict[str, str]]] = {}
    unmapped: list[dict[str, str]] = []
    disclosures: list[dict[str, str]] = []
    order: list[str] = []
    taken: set[str] = set()

    for block in blocks:
        text = "\n".join(block["lines"]).strip()
        title = block["title"].strip()
        norm = _normalize_title(title)
        if any(kw in norm for kw in DISCLOSURE_KEYWORDS):
            # Compliance content — routed to the audit log, never the clean memo.
            disclosures.append({"title": title, "text": text})
            continue
        key = _match_section_key(title, taken)
        if key:
            taken.add(key)
            sections[key] = text
            order.append(key)
            subs = _slice_subsections(block)
            if subs:
                subsections[key] = subs
        else:
            unmapped.append({"title": title, "text": text})

    return {
        "sections": sections,
        "subsections": subsections,
        "unmapped_sections": unmapped,
        "disclosures": disclosures,
        "title": doc_title,
        "preamble": "\n".join(preamble).strip(),
        "order": order,
    }


def _slice_subsections(block: dict[str, Any]) -> list[dict[str, str]]:
    """Cut a parent block's body into its sub-headed parts.

    Sub-heading bodies stay in the parent text as well; this is an index over
    the same characters, not a second copy of the contract.
    """
    marks = block.get("subsections") or []
    if not marks:
        return []
    lines = block["lines"]
    out: list[dict[str, str]] = []
    for i, mark in enumerate(marks):
        start = mark["start"] + 1
        end = marks[i + 1]["start"] if i + 1 < len(marks) else len(lines)
        text = "\n".join(lines[start:end]).strip()
        if text:
            out.append({"title": mark["title"], "text": text})
    return out


_RATING_RE = re.compile(
    r"\b(STRONG BUY|BUY|ACCUMULATE|OVERWEIGHT|HOLD|NEUTRAL|MARKET ?PERFORM|"
    r"UNDERWEIGHT|REDUCE|SELL|AVOID)\b",
    re.IGNORECASE,
)
# "fair value" is deliberately NOT in this pattern. Memos discuss the engine's
# fair value inside the recommendation section — often to argue against it — so
# matching it lifted a deterministic engine output and published it as the
# desk's target. Live on 2026-08-01: KO shipped `rating: HOLD` with
# `price_target: "$24.76"` (the mechanical DCF, which the memo argued down), and
# QCOM shipped `"$335.83"` from a memo whose second paragraph rejects that exact
# figure as peak extrapolation. A missing target must read as null, never as a
# number the analyst did not write.
_PRICE_TARGET_RE = re.compile(
    r"(?:price target|target price|\bPT\b)\D{0,15}(\$?\s?[\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _extract_rating(text: str) -> Optional[str]:
    m = _RATING_RE.search(text or "")
    return m.group(1).upper() if m else None


def _as_float(raw: Any) -> Optional[float]:
    try:
        return float(str(raw).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _extract_price_target(
    text: str, *, engine_values: Optional[list[float]] = None
) -> Optional[str]:
    """Pull an explicitly-stated price target out of the recommendation prose.

    `engine_values` are deterministic outputs (DCF / comps fair values). A match
    equal to one of them is discarded: that is the signature of prose describing
    the engine rather than issuing a target.
    """
    m = _PRICE_TARGET_RE.search(text or "")
    if not m:
        return None
    raw = m.group(1).strip().replace(" ", "")
    value = _as_float(raw)
    for engine_value in engine_values or []:
        if (
            value is not None
            and isinstance(engine_value, (int, float))
            and abs(value - float(engine_value)) < 0.01
        ):
            return None
    return raw if raw.startswith("$") else f"${raw}"


def engine_fair_values(state: dict[str, Any]) -> list[float]:
    """Deterministic per-share fair values the memo may quote in prose.

    These are engine outputs, not desk views. Collected so the headline parser
    can recognise and refuse them.
    """
    values: list[float] = []
    for key in ("dcf_engine", "dcf_judgment", "comps_engine", "comps_judgment"):
        block = state.get(key)
        if not isinstance(block, dict):
            continue
        for field in (
            "fair_value_per_share",
            "implied_value_per_share",
            "epv_per_share",
        ):
            value = block.get(field)
            if isinstance(value, (int, float)):
                values.append(float(value))
        band = block.get("fair_value_range")
        if isinstance(band, (list, tuple)):
            values.extend(float(v) for v in band if isinstance(v, (int, float)))
    return values


def resolve_headline(
    state: dict[str, Any], rating_source: str
) -> tuple[Optional[str], Optional[str], str]:
    """Resolve (rating, price_target, source) for the clean memo.

    Order matters. Synthesis emits a machine-readable ```recommendation fence
    (added FWD-06); that is the desk's own statement and is authoritative. Only
    when it is absent do we fall back to reading the prose, and that fallback
    now yields `None` rather than a number the analyst never wrote — see the
    note on `_PRICE_TARGET_RE`.
    """
    recommendation = state.get("recommendation")
    if isinstance(recommendation, dict):
        rating = recommendation.get("rating")
        target = recommendation.get("price_target")
        if rating or target is not None:
            target_value = _as_float(target)
            return (
                str(rating).upper() if rating else _extract_rating(rating_source),
                f"${target_value:,.2f}" if target_value is not None else None,
                "structured",
            )

    rating = _extract_rating(rating_source)
    target = _extract_price_target(
        rating_source, engine_values=engine_fair_values(state)
    )
    if rating is None and target is None:
        return None, None, "none"
    return rating, target, "parsed"


def build_metrics_block(canonical_metrics: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Every computed figure that carries a value, minus anything stale.

    Three exclusion classes, counted separately so the block is auditable:
    ``unavailable`` (the engine could not compute it), ``valueless``
    (applicable but null), and ``stale`` (the XBRL tag lags the period spine).
    Only the counts travel; the stale records themselves are audit-log content.
    """
    empty = {
        "records": [],
        "count": 0,
        "excluded_stale": 0,
        "excluded_unavailable": 0,
        "excluded_valueless": 0,
    }
    if not isinstance(canonical_metrics, dict):
        return empty

    records: list[dict[str, Any]] = []
    stale = unavailable = valueless = 0
    for rec in canonical_metrics.get("metrics") or []:
        if not isinstance(rec, dict):
            continue
        if not rec.get("applicable"):
            unavailable += 1
            continue
        if rec.get("value") is None:
            valueless += 1
            continue
        if rec.get("staleness"):
            stale += 1
            continue
        records.append({f: rec.get(f) for f in _METRIC_PUBLIC_FIELDS if rec.get(f) is not None})

    return {
        "ticker": canonical_metrics.get("ticker"),
        "archetype": canonical_metrics.get("archetype"),
        "computed_at_utc": canonical_metrics.get("computed_at_utc"),
        "period_labels": canonical_metrics.get("period_labels") or {},
        "records": records,
        "by_id": {r["id"]: r for r in records if r.get("id")},
        "count": len(records),
        "excluded_stale": stale,
        "excluded_unavailable": unavailable,
        "excluded_valueless": valueless,
        "note": (
            "Values only. Metrics whose SEC XBRL tag lags the period spine are "
            "omitted outright, not caveated — see the compliance audit log for "
            "the itemised stale-tag findings."
        ),
    }


def build_valuation_block(state: dict[str, Any]) -> dict[str, Any]:
    """Structured DCF + peer comps, with data-quality keys stripped out.

    Returns ``{}`` when neither engine ran, so a screener or ``direct_answer``
    run does not carry an empty scaffold.
    """
    dcf = state.get("dcf_engine")
    comps = state.get("comps_engine")
    out: dict[str, Any] = {}

    if isinstance(dcf, dict) and dcf:
        out["dcf"] = {k: v for k, v in dcf.items() if k not in _DCF_DISCLOSURE_FIELDS}

    if isinstance(comps, dict) and comps:
        clean_comps = {k: v for k, v in comps.items() if k not in _COMPS_DISCLOSURE_FIELDS}
        # A peer row carrying an `error` is a failed fetch, not a comparable.
        peers = [
            {k: v for k, v in row.items() if k != "error"}
            for row in (comps.get("peers") or [])
            if isinstance(row, dict) and not row.get("error")
        ]
        clean_comps["peers"] = peers
        subject = comps.get("subject")
        if isinstance(subject, dict):
            clean_comps["subject"] = {k: v for k, v in subject.items() if k != "error"}
        out["comps"] = clean_comps

    if out:
        out["note"] = (
            "Deterministic engine output (CLAUDE.md §6). Engine warnings, peer "
            "exclusions, and methodology notes are compliance content and live "
            "in the audit log."
        )
    return out


def _format_disclosure(item: Any) -> str:
    """Render one disclosure for the audit log.

    Band dissents arrive as structured dicts; a bare ``str()`` on them prints a
    Python repr into a compliance document. Render the fields a reader needs.
    """
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        parameter = item.get("parameter")
        argued = item.get("argued_range")
        band = item.get("archetype_band")
        reasoning = str(item.get("reasoning") or "").strip()
        head = f"**{parameter}**" if parameter else "Band dissent"
        if argued and band:
            head += f": argued {argued} vs archetype band {band}"
        elif argued:
            head += f": argued {argued}"
        return f"{head}{' — ' + reasoning if reasoning else ''}".strip()
    return str(item).strip()


def collect_valuation_disclosures(state: dict[str, Any]) -> dict[str, list[str]]:
    """The data-quality keys :func:`build_valuation_block` strips out."""
    out: dict[str, list[str]] = {}
    dcf = state.get("dcf_engine")
    comps = state.get("comps_engine")

    if isinstance(dcf, dict):
        for field in _DCF_DISCLOSURE_FIELDS:
            items = [str(x) for x in (dcf.get(field) or [])]
            if items:
                out[f"dcf_{field}"] = items

    # The judgment layer (Epic V) emits its own disclosures — one-sided argument
    # sets, parameter clamps, inert-FCF notices on non-DCF archetypes, band
    # dissents. Until FWD-07 these were generated, stored on `dcf_judgment`, and
    # then dropped: `collect_valuation_disclosures` only ever read `dcf_engine`
    # and `comps_engine`, so no DIRECTIONAL BIAS, clamp or inert-FCF line
    # appeared in any audit log across the entire 2026-07-30 eight-ticker run.
    # A control nobody can read is not a control.
    for key, prefix in (("dcf_judgment", "judgment"), ("comps_judgment", "comps_judgment")):
        block = state.get(key)
        if not isinstance(block, dict):
            continue
        for field in _JUDGMENT_DISCLOSURE_FIELDS:
            items = [
                _format_disclosure(x)
                for x in (block.get(field) or [])
                if _format_disclosure(x)
            ]
            if items:
                out.setdefault(f"{prefix}_{field}", []).extend(items)
    if isinstance(comps, dict):
        for field in _COMPS_DISCLOSURE_FIELDS:
            items = [str(x) for x in (comps.get(field) or [])]
            if items:
                out[f"comps_{field}"] = items
        failed = [
            f"{row.get('ticker')}: {row.get('error')}"
            for row in (comps.get("peers") or [])
            if isinstance(row, dict) and row.get("error")
        ]
        if failed:
            out["comps_peer_fetch_errors"] = failed
        if comps and not comps.get("relative_valuation_applicable", True):
            out["comps_applicability"] = [
                "Fewer than 2 archetype-matched peers — relative valuation not applicable."
            ]
    return out


def build_clean_memo(state: dict[str, Any], *, audit_log_filename: Optional[str] = None) -> dict[str, Any]:
    """Build the clean_memo payload from ``final_memo`` — thesis content only.

    Not every synthesis mode produces the seven-section structure
    (``direct_answer`` and ``business_brief`` deliberately do not), so absent
    sections are ``null`` and listed in ``sections_missing``.
    """
    from .routing import synthesis_mode_for_query_type

    memo = state.get("final_memo") or ""
    parsed = split_memo_sections(memo)
    found = parsed["sections"]

    query_type = str(state.get("query_type") or "full_underwrite")
    try:
        mode = synthesis_mode_for_query_type(query_type)
    except Exception:
        mode = "full_memo"

    rating_source = found.get("recommendation") or parsed["preamble"] or memo
    sections_payload = {k: found.get(k) or None for k in _SECTION_KEYS}
    rating, price_target, headline_source = resolve_headline(state, rating_source)

    return {
        "schema_version": CLEAN_MEMO_SCHEMA_VERSION,
        "artifact": "clean_memo",
        "generated_at_utc": _now_utc(),
        "ticker": state.get("ticker"),
        "sector": state.get("sector"),
        "mode": state.get("mode"),
        "user_query": state.get("user_query"),
        "query_type": query_type,
        "synthesis_mode": mode,
        "rating": rating,
        "price_target": price_target,
        # Which channel produced the two fields above: "structured" (the
        # synthesis recommendation fence), "parsed" (regex over prose), or
        # "none". A consumer that needs a guaranteed target should require
        # "structured" rather than trusting a scrape.
        "headline_source": headline_source,
        "title": parsed.get("title"),
        "sections": sections_payload,
        "subsections": parsed.get("subsections") or {},
        "sections_found": [k for k in _SECTION_KEYS if found.get(k)],
        "sections_missing": [k for k in _SECTION_KEYS if not found.get(k)],
        "unmapped_sections": parsed["unmapped_sections"],
        "metrics": build_metrics_block(state.get("canonical_metrics")),
        "valuation": build_valuation_block(state),
        # Count only — the disclosure text itself is routed to the audit log.
        "disclosure_sections_routed_out": len(parsed["disclosures"]),
        "preamble": parsed["preamble"] or None,
        "views": {name: list(keys) for name, keys in CLEAN_MEMO_VIEWS.items()},
        "source": {
            "basis": "final_memo",
            "chars": len(memo),
            "note": (
                "Parsed from final_memo (pre-style substance of record). The .docx "
                "renders styled_memo; style renames headers, so it is not parsed."
            ),
        },
        "compliance_audit_log": audit_log_filename,
        "notice": (
            "Thesis content only. Data-quality disclosures, stale XBRL tag warnings, "
            "QC findings, and run cost live in the compliance audit log."
        ),
    }


def collect_stale_tags(canonical_metrics: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every canonical metric record carrying a non-empty ``staleness`` list."""
    if not isinstance(canonical_metrics, dict):
        return []
    out: list[dict[str, Any]] = []
    for rec in canonical_metrics.get("metrics") or []:
        if not isinstance(rec, dict):
            continue
        stale = rec.get("staleness") or []
        if not stale:
            continue
        out.append(
            {
                "metric_id": rec.get("id"),
                "basis_period": rec.get("basis_period"),
                "confidence": rec.get("confidence"),
                "applicable": bool(rec.get("applicable")),
                "notes": [str(s) for s in stale],
            }
        )
    return out


def collect_unavailable_metrics(
    canonical_metrics: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Metric records the engine could not compute (missing tags, etc.)."""
    if not isinstance(canonical_metrics, dict):
        return []
    return [
        {"metric_id": r.get("id"), "headline": r.get("headline")}
        for r in (canonical_metrics.get("metrics") or [])
        if isinstance(r, dict) and not r.get("applicable")
    ]


def build_compliance_audit_log(
    state: dict[str, Any],
    *,
    clean_memo_filename: Optional[str] = None,
    context: str = "export",
) -> str:
    """Assemble the full data-quality / QC disclosure document as markdown.

    ``context`` records which terminal path produced the log: ``export``,
    ``qc_halt``, or ``validation_halt``. Halt paths ship no memo, so the log is
    the only artifact and must stand alone.
    """
    ticker = state.get("ticker") or state.get("sector") or "SECTOR"
    cm = state.get("canonical_metrics") or {}
    vr = state.get("validation_report") or {}
    qc_status = (state.get("qc_status") or "").strip() or "n/a"
    validation_status = (state.get("validation_status") or vr.get("status") or "").strip() or "n/a"

    stale = collect_stale_tags(cm)
    unavailable = collect_unavailable_metrics(cm)
    warnings = list(vr.get("warnings") or [])
    failures = list(vr.get("failures") or [])

    L: list[str] = []
    L.append(f"# Compliance & Data Quality Audit Log — {ticker}")
    L.append("")
    L.append(
        "Companion to the clean memo. Every data-quality disclosure, QC finding, and "
        "stale-tag warning for this run lives here rather than in the reader-facing memo."
    )
    L.append("")
    L.append("| Field | Value |")
    L.append("|-------|-------|")
    L.append(f"| Ticker | {state.get('ticker') or 'n/a'} |")
    L.append(f"| Sector | {state.get('sector') or 'n/a'} |")
    L.append(f"| Run mode | {state.get('mode') or 'n/a'} |")
    L.append(f"| Query type | {state.get('query_type') or 'n/a'} |")
    L.append(f"| Terminal path | {context} |")
    L.append(f"| Validation status | {validation_status} |")
    L.append(f"| QC status | {qc_status} |")
    L.append(f"| Stale-tag findings | {len(stale)} |")
    L.append(f"| Valuation engine disclosures | {sum(len(v) for v in collect_valuation_disclosures(state).values())} |")
    L.append(f"| Validation warnings | {len(warnings)} |")
    L.append(f"| Validation failures | {len(failures)} |")
    L.append(f"| Generated (UTC) | {_now_utc()} |")
    if clean_memo_filename:
        L.append(f"| Clean memo | `{clean_memo_filename}` |")
    L.append("")

    # ── 1. Stale XBRL tags ────────────────────────────────────────────────
    L.append("## 1. Stale XBRL Tag Warnings")
    L.append("")
    if stale:
        L.append(
            "Canonical metric records whose underlying SEC XBRL tag end-date lags the "
            "period spine. Figures below carry reduced confidence and must not anchor "
            "a thesis claim."
        )
        L.append("")
        L.append("| Metric | Basis period | Confidence | Note |")
        L.append("|--------|--------------|------------|------|")
        for item in stale:
            note = "; ".join(item["notes"]).replace("|", "\\|")
            L.append(
                f"| `{item['metric_id']}` | {item['basis_period'] or 'n/a'} | "
                f"{item['confidence'] or 'n/a'} | {note} |"
            )
    else:
        L.append("No stale-tag findings recorded for this run.")
    L.append("")

    # ── 1b. Disclosure sections lifted out of the memo body ───────────────
    memo_disclosures = split_memo_sections(state.get("final_memo") or "")["disclosures"]
    if memo_disclosures:
        L.append("## 1b. Disclosures Written Into the Memo Body")
        L.append("")
        L.append(
            "Synthesis writes data-quality disclosures inline when the validation gate "
            "raises warnings. Those sections were lifted out of the clean memo and are "
            "reproduced verbatim here."
        )
        L.append("")
        for d in memo_disclosures:
            L.append(f"### {d['title']}")
            L.append("")
            L.append(d["text"] or "_(empty)_")
            L.append("")

    # ── 2. Validation gate ────────────────────────────────────────────────
    L.append("## 2. Validation Gate")
    L.append("")
    L.append(f"**Status:** {validation_status}")
    if vr.get("summary"):
        L.append("")
        L.append(f"**Summary:** {vr.get('summary')}")
    L.append("")
    if failures:
        L.append("### Failures")
        L.append("")
        for f in failures:
            L.append(f"- {f}")
        L.append("")
    if warnings:
        L.append("### Warnings")
        L.append("")
        for w in warnings:
            L.append(f"- {w}")
        L.append("")
    if not failures and not warnings:
        L.append("No validation warnings or failures.")
        L.append("")

    checks = vr.get("checks") or []
    if checks:
        L.append("### All checks")
        L.append("")
        L.append("| Check | Status | Detail |")
        L.append("|-------|--------|--------|")
        for c in checks:
            if not isinstance(c, dict):
                continue
            detail = str(c.get("detail") or "").replace("|", "\\|")
            L.append(f"| {c.get('name')} | {c.get('status')} | {detail} |")
        L.append("")

    # ── 3. Metric availability ────────────────────────────────────────────
    L.append("## 3. Metric Availability")
    L.append("")
    summary = cm.get("summary") if isinstance(cm, dict) else None
    if isinstance(summary, dict):
        L.append(
            f"Computed {summary.get('metric_count', 'n/a')} metric records — "
            f"{summary.get('applicable_with_value', 'n/a')} applicable with a value, "
            f"{summary.get('unavailable', 'n/a')} unavailable."
        )
        L.append("")
    if unavailable:
        L.append("<details><summary>Unavailable metric records</summary>")
        L.append("")
        for item in unavailable:
            L.append(f"- `{item['metric_id']}` — {item['headline'] or 'unavailable'}")
        L.append("")
        L.append("</details>")
    else:
        L.append("No unavailable metric records.")
    L.append("")

    # ── 4. QC review ──────────────────────────────────────────────────────
    L.append("## 4. QC Review")
    L.append("")
    L.append(f"**Status:** {qc_status}")
    L.append("")
    if qc_status == "PASS_WITH_FLAGS":
        L.append(
            "Institutional review flagged the items below. The memo body was **not** "
            "auto-corrected — QC reports, it never silently edits."
        )
        L.append("")
    elif qc_status == "FAIL":
        L.append(
            "**Hard stop.** QC failed after the permitted synthesis retry; no memo was "
            "exported for this run."
        )
        L.append("")
    qc_report = (state.get("qc_report") or "").strip()
    L.append(qc_report if qc_report else "_No QC report recorded for this run._")
    L.append("")

    style_status = (state.get("qc_style_status") or "").strip()
    if style_status:
        L.append("### Style check")
        L.append("")
        L.append(f"**Status:** {style_status}")
        style_report = (state.get("qc_style_report") or "").strip()
        if style_report:
            L.append("")
            L.append(style_report)
        L.append("")

    # ── 5. Valuation engine disclosures ───────────────────────────────────
    # The clean memo carries the engine's numbers; everything the engine said
    # about the reliability of those numbers is reproduced here instead.
    L.append("## 5. Valuation Engine Disclosures")
    L.append("")
    vdis = collect_valuation_disclosures(state)
    if vdis:
        L.append(
            "Warnings, peer exclusions, and methodology notes emitted by the "
            "deterministic valuation engine. These are stripped from the clean "
            "memo's `valuation` block, which carries values only."
        )
        L.append("")
        labels = {
            "dcf_warnings": "DCF warnings",
            "dcf_errors": "DCF errors",
            "comps_notes": "Comps methodology notes",
            "comps_peer_exclusions": "Peer exclusions",
            "comps_peer_fetch_errors": "Peer fetch failures",
            "comps_applicability": "Relative valuation applicability",
            "judgment_clamp_warnings": "Judgment-case disclosures (argued inputs)",
            "judgment_band_dissents": "Archetype band dissents",
            "judgment_errors": "Judgment-case errors",
            "comps_judgment_clamp_warnings": "Judgment-case disclosures (peer set)",
            "comps_judgment_band_dissents": "Peer band dissents",
            "comps_judgment_errors": "Judgment-case errors (peer set)",
        }
        for field, items in vdis.items():
            L.append(f"### {labels.get(field, field)}")
            L.append("")
            for item in items:
                L.append(f"- {item}")
            L.append("")
    else:
        L.append("No valuation engine warnings, exclusions, or errors recorded for this run.")
        L.append("")

    # ── 6. Run cost ───────────────────────────────────────────────────────
    L.append("## 6. Run Cost")
    L.append("")
    cost_report = (state.get("cost_report") or "").strip()
    L.append(cost_report if cost_report else "_No cost report recorded for this run._")
    L.append("")
    L.append("---")
    L.append("")
    L.append(
        "_Generated by `mas_sector_system.artifacts`. Cost figures are local estimates "
        "from token counts × pricing table, not billed amounts._"
    )
    L.append("")
    return "\n".join(L)


def artifact_filenames(
    ticker: Optional[str], *, as_of: Optional[date] = None
) -> tuple[str, str]:
    """(clean_memo_filename, audit_log_filename) — matches the .docx convention."""
    day = as_of or date.today()
    stem = f"{_safe_ticker(ticker)}_{day.isoformat()}"
    return f"{stem}_clean_memo.json", f"{stem}_compliance_audit_log.md"


def write_run_artifacts(
    state: dict[str, Any],
    *,
    output_dir: Optional[Path] = None,
    as_of: Optional[date] = None,
    context: str = "export",
    write_clean_memo: bool = True,
) -> dict[str, Any]:
    """Write both artifacts and return a state update.

    ``write_clean_memo=False`` on halt paths: a run that hard-stopped ships no
    thesis, but the audit log is exactly what a halted run needs to explain
    itself.
    """
    out_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    ticker = state.get("ticker")
    clean_name, audit_name = artifact_filenames(ticker, as_of=as_of)

    update: dict[str, Any] = {}

    audit_md = build_compliance_audit_log(
        state,
        clean_memo_filename=clean_name if write_clean_memo else None,
        context=context,
    )
    audit_path = out_dir / audit_name
    audit_path.write_text(audit_md, encoding="utf-8")
    update["compliance_audit_log"] = audit_md
    update["compliance_audit_log_path"] = str(audit_path.resolve())
    print(f"Saved compliance audit log: {audit_path.resolve()}", flush=True)

    if write_clean_memo:
        payload = build_clean_memo(state, audit_log_filename=audit_name)
        clean_path = out_dir / clean_name
        clean_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        update["clean_memo"] = payload
        update["clean_memo_path"] = str(clean_path.resolve())
        print(f"Saved clean memo: {clean_path.resolve()}", flush=True)
        missing = payload.get("sections_missing") or []
        if missing:
            print(
                f"[artifacts] clean_memo sections absent ({payload['synthesis_mode']}): "
                f"{', '.join(missing)}",
                flush=True,
            )
        if payload.get("unmapped_sections"):
            titles = ", ".join(
                s["title"] for s in payload["unmapped_sections"] if s.get("title")
            )
            print(f"[artifacts] unmapped memo sections preserved: {titles}", flush=True)

    return update
