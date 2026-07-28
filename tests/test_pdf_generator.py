"""Offline tests for the clean-memo Hawktrade PDF renderer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mas_sector_system.pdf_generator import (
    CleanMemoError,
    _iter_sections,
    generate_pdf,
    load_clean_memo,
)


def _payload() -> dict:
    return {
        "schema_version": "1.0",
        "artifact": "clean_memo",
        "generated_at_utc": "2026-07-28T12:00:00+00:00",
        "ticker": "NVDA",
        "sector": "Semiconductors",
        "rating": "BUY",
        "price_target": "$210",
        "preamble": "Durability—not velocity—is the central question.",
        "sections": {
            "business_overview": (
                "Revenue grew **≈114%**. Pricing × volume → operating leverage.\n\n"
                "| Driver | Read |\n|---|---|\n| Switching costs | High |"
            ),
            "recommendation": "BUY, with patience.",
            "macro_positioning": None,
            "management_and_capital_allocation": None,
            "key_debate_points": "- Demand duration\n- Competitive response",
            "valuation_reconciliation": "Fair value is **≈$210**.",
            "catalysts_and_risks": "Monitor lead times.",
            "thesis_evolution": None,
        },
        "sections_found": [
            "business_overview",
            "recommendation",
            "key_debate_points",
            "valuation_reconciliation",
            "catalysts_and_risks",
        ],
        "unmapped_sections": [
            {"title": "Additional Thesis Work", "text": "A valid thesis section."},
            {"title": "QC & Compliance Audit", "text": "MUST NEVER RENDER"},
        ],
        "compliance_audit_log": "NVDA_compliance_audit_log.md",
        "notice": "QC findings, stale tags, and run cost live elsewhere.",
        "source": {"note": "backend metadata must not render"},
    }


def test_rejects_non_clean_artifacts(tmp_path: Path):
    source = tmp_path / "audit.json"
    source.write_text(json.dumps({"artifact": "compliance_audit_log", "sections": {}}))
    with pytest.raises(CleanMemoError):
        load_clean_memo(source)


def test_section_iterator_excludes_audit_like_unmapped_sections():
    rendered = list(_iter_sections(_payload()))
    assert any(title == "Additional Thesis Work" for title, _ in rendered)
    assert all("Compliance" not in title for title, _ in rendered)
    assert all("MUST NEVER RENDER" not in text for _, text in rendered)


def test_generates_unicode_pdf_from_clean_memo(tmp_path: Path):
    source = tmp_path / "NVDA_clean_memo.json"
    source.write_text(json.dumps(_payload(), ensure_ascii=False), encoding="utf-8")
    destination = generate_pdf(source, output_path=tmp_path / "NVDA.pdf")
    assert destination.is_file()
    assert destination.read_bytes().startswith(b"%PDF-")
    assert destination.stat().st_size > 20_000
