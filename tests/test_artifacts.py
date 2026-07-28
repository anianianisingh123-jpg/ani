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
    collect_stale_tags,
    split_memo_sections,
    strip_appendices,
    write_run_artifacts,
)

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
                    "basis_period": "FY2025",
                    "confidence": "moderate",
                    "applicable": True,
                    "staleness": ["ShortTermInvestments: tag missing — treated as 0"],
                    "headline": "Net cash ~$30B",
                },
                {
                    "id": "revenue",
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


# ── Clean memo ───────────────────────────────────────────────────────────────


def test_clean_memo_excludes_all_compliance_content():
    payload = build_clean_memo(_state())
    blob = json.dumps(payload)
    assert "QC Notes" not in blob
    assert "MAJOR: interest expense" not in blob
    assert "Run Cost" not in blob
    assert "tag missing" not in blob
    assert "Balance sheet identity" not in blob


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
