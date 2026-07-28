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

CLEAN_MEMO_SCHEMA_VERSION = "1.0"

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


def _heading_text(line: str) -> Optional[str]:
    """Return the heading text of a line, or None if it is not a heading.

    Recognizes ATX headings, bold-only lines, and bare ALL-CAPS lines with an
    optional leading number — synthesis emits all three shapes in practice.
    """
    stripped = line.strip()
    if not stripped:
        return None

    m = _ATX_RE.match(stripped)
    if m:
        return m.group(2).strip()

    m = _BOLD_LINE_RE.match(stripped)
    if m:
        text = m.group(1).strip()
        # A bold sentence is not a heading; headings are short.
        if len(text) <= 80 and not text.endswith("."):
            return text
        return None

    m = _NUMBERED_CAPS_RE.match(stripped)
    if m:
        text = m.group(1).strip()
        if len(text) <= 80:
            return text
        return None

    return None


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

    blocks: list[dict[str, Any]] = []
    preamble: list[str] = []
    current: Optional[dict[str, Any]] = None

    for line in lines:
        title = _heading_text(line)
        if title is not None:
            if current is not None:
                blocks.append(current)
            current = {"title": title, "lines": []}
            continue
        if current is None:
            preamble.append(line)
        else:
            current["lines"].append(line)
    if current is not None:
        blocks.append(current)

    sections: dict[str, str] = {}
    unmapped: list[dict[str, str]] = []
    order: list[str] = []
    taken: set[str] = set()

    for block in blocks:
        text = "\n".join(block["lines"]).strip()
        key = _match_section_key(block["title"], taken)
        if key:
            taken.add(key)
            sections[key] = text
            order.append(key)
        else:
            unmapped.append({"title": block["title"].strip(), "text": text})

    return {
        "sections": sections,
        "unmapped_sections": unmapped,
        "preamble": "\n".join(preamble).strip(),
        "order": order,
    }


_RATING_RE = re.compile(
    r"\b(STRONG BUY|BUY|ACCUMULATE|OVERWEIGHT|HOLD|NEUTRAL|MARKET ?PERFORM|"
    r"UNDERWEIGHT|REDUCE|SELL|AVOID)\b",
    re.IGNORECASE,
)
_PRICE_TARGET_RE = re.compile(
    r"(?:price target|PT|fair value|target price)\D{0,15}(\$?\s?[\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _extract_rating(text: str) -> Optional[str]:
    m = _RATING_RE.search(text or "")
    return m.group(1).upper() if m else None


def _extract_price_target(text: str) -> Optional[str]:
    m = _PRICE_TARGET_RE.search(text or "")
    if not m:
        return None
    raw = m.group(1).strip().replace(" ", "")
    return raw if raw.startswith("$") else f"${raw}"


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
        "rating": _extract_rating(rating_source),
        "price_target": _extract_price_target(rating_source),
        "sections": sections_payload,
        "sections_found": [k for k in _SECTION_KEYS if found.get(k)],
        "sections_missing": [k for k in _SECTION_KEYS if not found.get(k)],
        "unmapped_sections": parsed["unmapped_sections"],
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

    # ── 5. Run cost ───────────────────────────────────────────────────────
    L.append("## 5. Run Cost")
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
