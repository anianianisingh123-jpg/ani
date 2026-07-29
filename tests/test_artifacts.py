"""Tests for the split output artifacts (clean memo vs compliance audit log).

Deterministic and offline — no LLM calls, no network. Guards the invariant the
refactor exists to establish: QC findings, stale-tag warnings, and cost figures
must never reach the clean memo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mas_sector_system.artifacts import (  # noqa: E402
    build_clean_memo,
    build_compliance_audit_log,
    build_metrics_block,
    build_valuation_block,
    collect_stale_tags,
    collect_valuation_disclosures,
    split_memo_sections,
    strip_appendices,
    write_run_artifacts,
)

# Real memos are one H1 title, numbered H2 sections, and H3 sub-headings inside
# them. Before the hierarchy fix every heading was a boundary, so the H3 bodies
# orphaned into unmapped_sections and their parents thinned to a sentence.
HIERARCHICAL_MEMO = """\
# NVIDIA CORPORATION (NVDA)

Rating: BUY | Price Target: $318.63

## 1. BUSINESS OVERVIEW
Accelerated computing platforms.

## 4. MANAGEMENT & CAPITAL ALLOCATION
One-line preamble under the parent heading.

### Management: low-confidence, high key-person concentration
Founder-led with real key-person risk.

### Capital allocation: disciplined on reinvestment
Buybacks at $34.29B per percentage point.

## 5. KEY DEBATE POINTS

### Where the bear lands real blows
Working capital is outrunning revenue.

### Where the bull survives contact
The margin story has already turned.

### My adjudication
The bear wins the near term.

## 6. VALUATION RECONCILIATION
DCF and comps disagree on the horizon.
"""

FULL_MEMO = """\
Preamble line before any heading.

## 1. BUSINESS OVERVIEW
NVIDIA designs accelerated computing platforms.
Data center is the dominant segment.

## 2. RECOMMENDATION
BUY. Price target $210. Evidence that would change it: hyperscaler capex cuts.

## 3. MACRO / CYCLE POSITIONING
Regime read is TAILWIND with moderate confidence.

## 4. MANAGEMENT & CAPITAL ALLOCATION
Founder-led; buybacks at $4.1B per percentage point of share count.

## 5. KEY DEBATE POINTS
Bull lands on backlog; bear lands on customer concentration.

## 6. VALUATION RECONCILIATION
DCF says rich, comps say fair versus semis peers.

## 7. RISKS AND MONITORING TRIGGERS
Watch export controls and the CoWoS supply line.

## Thesis evolution
Conviction flat versus the prior desk memo.
"""


def _state(**over):
    base = {
        "ticker": "NVDA",
        "sector": "Semiconductors",
        "mode": "deep_dive",
        "user_query": "Full underwrite on NVDA",
        "query_type": "full_underwrite",
        "final_memo": FULL_MEMO,
        "styled_memo": "# Styled\nRenamed headers here.",
        "qc_status": "PASS_WITH_FLAGS",
        "qc_report": "MAJOR: interest expense line is stale.",
        "validation_status": "WARN",
        "validation_report": {
            "status": "WARN",
            "summary": "validation status=WARN checks=12 warnings=1 failures=0",
            "warnings": ["Balance sheet identity not verifiable (missing tags)."],
            "failures": [],
            "checks": [{"name": "revenue_positive", "status": "PASS", "detail": "revenue=1"}],
        },
        "canonical_metrics": {
            "metrics": [
                {
                    "id": "net_cash",
                    "value": 30.0e9,
                    "unit": "USD",
                    "basis_period": "FY2025",
                    "confidence": "moderate",
                    "applicable": True,
                    "staleness": ["ShortTermInvestments: tag missing — treated as 0"],
                    "headline": "Net cash ~$30B",
                },
                {
                    "id": "revenue",
                    "value": 130.0e9,
                    "unit": "USD",
                    "basis_period": "FY2025",
                    "confidence": "high",
                    "applicable": True,
                    "staleness": [],
                    "headline": "Revenue $130B",
                },
                {
                    "id": "interest_expense",
                    "applicable": False,
                    "staleness": [],
                    "headline": "interest_expense unavailable — tag missing",
                },
            ],
            "summary": {"metric_count": 3, "applicable_with_value": 2, "unavailable": 1},
        },
        "cost_report": "── Run Cost ──\nTotal: $2.63",
    }
    base.update(over)
    return base


# ── Parsing ──────────────────────────────────────────────────────────────────


def test_full_memo_maps_all_seven_sections():
    parsed = split_memo_sections(FULL_MEMO)
    for key in (
        "business_overview",
        "recommendation",
        "macro_positioning",
        "management_and_capital_allocation",
        "key_debate_points",
        "valuation_reconciliation",
        "catalysts_and_risks",
        "thesis_evolution",
    ):
        assert parsed["sections"].get(key), f"missing section {key}"
    assert parsed["unmapped_sections"] == []
    assert parsed["preamble"].startswith("Preamble line")


def test_valuation_heading_does_not_steal_the_risks_section():
    """'VALUATION RECONCILIATION' and 'RISKS' must not collapse into one key."""
    parsed = split_memo_sections(FULL_MEMO)
    assert "DCF says rich" in parsed["sections"]["valuation_reconciliation"]
    assert "export controls" in parsed["sections"]["catalysts_and_risks"]


def test_bold_and_allcaps_headings_are_recognized():
    memo = "**RECOMMENDATION**\nHold.\n\nVALUATION RECONCILIATION\nFairly valued.\n"
    parsed = split_memo_sections(memo)
    assert parsed["sections"]["recommendation"].strip() == "Hold."
    assert parsed["sections"]["valuation_reconciliation"].strip() == "Fairly valued."


def test_unknown_headings_are_preserved_not_dropped():
    memo = FULL_MEMO + "\n## SUPPLY CHAIN DEEP DIVE\nCoWoS capacity detail.\n"
    parsed = split_memo_sections(memo)
    titles = [s["title"] for s in parsed["unmapped_sections"]]
    assert "SUPPLY CHAIN DEEP DIVE" in titles


def test_appendices_are_stripped_from_memo_body():
    polluted = FULL_MEMO + "\n## QC Notes\n\nflagged stuff\n\n── Run Cost ──\nTotal: $2.63\n"
    body = strip_appendices(polluted)
    assert "QC Notes" not in body
    assert "Run Cost" not in body
    assert "export controls" in body


# ── Heading hierarchy (OUT-02) ───────────────────────────────────────────────


def test_sub_headings_stay_inside_their_parent_section():
    """Regression guard for OUT-02: H3 bodies must not orphan to unmapped."""
    parsed = split_memo_sections(HIERARCHICAL_MEMO)
    debate = parsed["sections"]["key_debate_points"]
    assert "Working capital is outrunning revenue" in debate
    assert "The margin story has already turned" in debate
    assert "The bear wins the near term" in debate

    mgmt = parsed["sections"]["management_and_capital_allocation"]
    assert "Founder-led with real key-person risk" in mgmt
    assert "Buybacks at $34.29B" in mgmt
    assert "One-line preamble" in mgmt

    assert parsed["unmapped_sections"] == []


def test_sub_headings_are_indexed_for_structured_layouts():
    parsed = split_memo_sections(HIERARCHICAL_MEMO)
    titles = [s["title"] for s in parsed["subsections"]["key_debate_points"]]
    assert titles == [
        "Where the bear lands real blows",
        "Where the bull survives contact",
        "My adjudication",
    ]
    bear = parsed["subsections"]["key_debate_points"][0]
    assert "Working capital" in bear["text"]
    assert "margin story" not in bear["text"], "subsection slices must not bleed"


def test_lone_top_heading_is_the_document_title_not_a_section():
    parsed = split_memo_sections(HIERARCHICAL_MEMO)
    assert parsed["title"] == "NVIDIA CORPORATION (NVDA)"
    assert "Rating: BUY" in parsed["preamble"]


def test_flat_memo_without_a_repeated_depth_keeps_boundary_per_heading():
    """No inferable hierarchy → every heading still delimits a section."""
    memo = "# RECOMMENDATION\nBuy.\n\n## VALUATION RECONCILIATION\nFair.\n"
    parsed = split_memo_sections(memo)
    assert parsed["sections"]["recommendation"].strip() == "Buy."
    assert parsed["sections"]["valuation_reconciliation"].strip() == "Fair."


# ── Clean memo ───────────────────────────────────────────────────────────────


def test_clean_memo_excludes_appended_compliance_blocks():
    """The guarantee is 'no appended QC/cost/stale-tag blocks, no disclosure sections'.

    It is NOT 'no compliance wording anywhere': synthesis is still instructed to
    disclose material data-quality caveats inline where they bear on the thesis
    (agents.py, "If validation WARNINGs are present, disclose them in the memo"),
    and that prompt was deliberately left intact. A sentence like "conviction
    firmer on data quality" is analyst judgment and stays in the thesis.
    """
    payload = build_clean_memo(_state())
    blob = json.dumps(payload)
    assert "QC Notes" not in blob
    assert "MAJOR: interest expense" not in blob
    assert "Run Cost" not in blob
    assert "tag missing" not in blob
    assert "Balance sheet identity" not in blob


def test_disclosure_section_is_routed_to_audit_log_not_clean_memo():
    """Opus writes a standalone 'DATA QUALITY DISCLOSURE' section in real memos."""
    memo = FULL_MEMO + (
        "\n## DATA QUALITY DISCLOSURE (read first)\n"
        "Short-term investments tag is missing; net cash is approximate.\n"
    )
    st = _state(final_memo=memo)
    payload = build_clean_memo(st)
    assert payload["disclosure_sections_routed_out"] == 1
    blob = json.dumps(payload)
    assert "Short-term investments tag is missing" not in blob
    assert "DATA QUALITY DISCLOSURE" not in blob
    log = build_compliance_audit_log(st)
    assert "Short-term investments tag is missing" in log
    assert "Disclosures Written Into the Memo Body" in log


def test_bold_lead_ins_do_not_fragment_an_atx_structured_memo():
    """Real memos put '**What would change this to HOLD:**' inside sections.

    Regression guard: before the ATX-dominance rule these bold lines were read
    as headings, splitting real sections into unmapped fragments.
    """
    memo = FULL_MEMO.replace(
        "BUY. Price target $210.",
        "**What would change this to HOLD or AVOID:**\nBUY. Price target $210.",
    )
    parsed = split_memo_sections(memo)
    assert parsed["unmapped_sections"] == []
    assert "What would change this to HOLD" in parsed["sections"]["recommendation"]


def test_clean_memo_extracts_rating_and_price_target():
    payload = build_clean_memo(_state())
    assert payload["rating"] == "BUY"
    assert payload["price_target"] == "$210"


def test_clean_memo_reports_absent_sections_as_null_not_empty():
    """direct_answer mode does not produce the seven-section structure."""
    payload = build_clean_memo(
        _state(query_type="specific_question", final_memo="Just a direct answer, no headings.")
    )
    assert payload["synthesis_mode"] == "direct_answer"
    assert payload["sections"]["recommendation"] is None
    assert "recommendation" in payload["sections_missing"]
    assert payload["preamble"] == "Just a direct answer, no headings."


def test_clean_memo_survives_empty_memo():
    payload = build_clean_memo(_state(final_memo=""))
    assert payload["sections_found"] == []
    assert payload["source"]["chars"] == 0


@pytest.mark.parametrize(
    "query_type,expected_mode",
    [
        ("full_underwrite", "full_memo"),
        ("specific_question", "direct_answer"),
        ("business_understanding", "business_brief"),
        ("valuation_only", "valuation_note"),
        ("risk_assessment", "risk_memo"),
    ],
)
def test_synthesis_mode_recorded_for_every_query_type(query_type, expected_mode):
    payload = build_clean_memo(_state(query_type=query_type))
    assert payload["synthesis_mode"] == expected_mode


# ── Numeric blocks (schema 1.1) ──────────────────────────────────────────────


def _engine_state(**over):
    """A state carrying structured DCF + comps output, as the nodes now return."""
    return _state(
        dcf_engine={
            "method": "multi_stage_fcf_dcf",
            "fair_value_per_share": 318.85,
            "assumptions": {"wacc": 0.10},
            "warnings": ["FCF grew 59% YoY — g_high capped at 35%."],
            "errors": [],
        },
        comps_engine={
            "subject": {"ticker": "NVDA", "trailing_pe": 40.1},
            "peers": [
                {"ticker": "AMD", "trailing_pe": 92.1, "error": None},
                {"ticker": "BADTKR", "error": "no data returned"},
            ],
            "peer_medians": {"trailing_pe": 32.8},
            "overall_vs_peers": "cheap",
            "peer_exclusions": ["MU excluded: market cap outside band"],
            "notes": ["yfinance trailing P/E was 41.8x; canonical 40.1x governs."],
            "relative_valuation_applicable": True,
        },
        **over,
    )


def test_metrics_block_omits_stale_records_and_counts_them():
    """Decision of record: stale figures are dropped, never caveated."""
    block = build_metrics_block(_state()["canonical_metrics"])
    ids = [r["id"] for r in block["records"]]
    assert ids == ["revenue"], "net_cash is stale and interest_expense unavailable"
    assert block["excluded_stale"] == 1
    assert block["excluded_unavailable"] == 1
    assert "staleness" not in json.dumps(block)


def test_metrics_block_survives_a_run_with_no_metrics():
    empty = build_metrics_block(None)
    assert empty["records"] == [] and empty["count"] == 0


def test_valuation_block_strips_engine_data_quality_keys():
    block = build_valuation_block(_engine_state())
    assert block["dcf"]["fair_value_per_share"] == 318.85
    assert "warnings" not in block["dcf"] and "errors" not in block["dcf"]
    assert "peer_exclusions" not in block["comps"] and "notes" not in block["comps"]
    # A peer row that failed to fetch is not a comparable.
    assert [p["ticker"] for p in block["comps"]["peers"]] == ["AMD"]


def test_stripped_engine_disclosures_are_routed_not_destroyed():
    """The module contract is 'nothing is silently dropped' — assert both halves."""
    st = _engine_state()
    clean = json.dumps(build_clean_memo(st)["valuation"])
    log = build_compliance_audit_log(st)
    for probe in ("g_high capped at 35%", "MU excluded", "canonical 40.1x governs",
                  "no data returned"):
        assert probe not in clean, f"{probe} leaked into the clean memo"
        assert probe in log, f"{probe} was destroyed instead of routed"
    assert "Valuation Engine Disclosures" in log


def test_valuation_block_absent_when_no_engine_ran():
    assert build_valuation_block(_state()) == {}
    assert collect_valuation_disclosures(_state()) == {}


def test_clean_memo_carries_numeric_blocks_at_schema_1_1():
    payload = build_clean_memo(_engine_state())
    assert payload["schema_version"] == "1.1"
    assert payload["metrics"]["count"] >= 1
    assert payload["valuation"]["dcf"]["fair_value_per_share"] == 318.85


# ── Compliance audit log ─────────────────────────────────────────────────────


def test_stale_tags_are_collected_from_canonical_metrics():
    stale = collect_stale_tags(_state()["canonical_metrics"])
    assert len(stale) == 1
    assert stale[0]["metric_id"] == "net_cash"


def test_audit_log_carries_every_disclosure_class():
    log = build_compliance_audit_log(_state())
    assert "Stale XBRL Tag Warnings" in log
    assert "ShortTermInvestments: tag missing" in log
    assert "Balance sheet identity not verifiable" in log
    assert "MAJOR: interest expense line is stale." in log
    assert "PASS_WITH_FLAGS" in log
    assert "Total: $2.63" in log


def test_audit_log_handles_a_run_with_no_qc_report():
    log = build_compliance_audit_log(_state(qc_status="", qc_report=""), context="validation_halt")
    assert "No QC report recorded" in log
    assert "validation_halt" in log


# ── Writer ───────────────────────────────────────────────────────────────────


def test_write_run_artifacts_emits_two_files(tmp_path):
    update = write_run_artifacts(_state(), output_dir=tmp_path)
    clean = Path(update["clean_memo_path"])
    audit = Path(update["compliance_audit_log_path"])
    assert clean.exists() and audit.exists()
    assert clean.name.endswith("_clean_memo.json")
    assert audit.name.endswith("_compliance_audit_log.md")
    assert json.loads(clean.read_text())["ticker"] == "NVDA"
    # Cross-reference between the two artifacts
    assert clean.name in audit.read_text()


def test_halt_path_writes_audit_log_but_no_clean_memo(tmp_path):
    update = write_run_artifacts(
        _state(qc_status="FAIL"), output_dir=tmp_path, context="qc_halt", write_clean_memo=False
    )
    assert "clean_memo_path" not in update
    assert Path(update["compliance_audit_log_path"]).exists()
    assert list(tmp_path.glob("*_clean_memo.json")) == []
    assert "Hard stop" in update["compliance_audit_log"]
