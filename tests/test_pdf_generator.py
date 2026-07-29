"""Offline tests for the clean-memo Hawktrade PDF renderer."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from mas_sector_system.pdf_generator import (
    CleanMemoError,
    MetricBook,
    _column_markdown,
    _iter_sections,
    _pick_side,
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


# ── Schema 1.1 visual pages ──────────────────────────────────────────────────


def _visual_payload() -> dict:
    """A schema-1.1 payload carrying the numeric blocks the deck pages need."""
    payload = _payload()
    payload["schema_version"] = "1.1"
    payload["subsections"] = {
        "key_debate_points": [
            {"title": "Where the bull survives contact", "text": "Margins already turned."},
            {"title": "Where the bear lands real blows", "text": "Working capital outruns revenue."},
            {"title": "My adjudication", "text": "Bear wins the near term."},
        ]
    }
    records = [
        {"id": "price", "value": 196.51, "unit": "USD", "basis_period": "live"},
        {"id": "market_cap", "value": 4.76e12, "unit": "USD", "basis_period": "live"},
        {"id": "trailing_pe", "value": 40.1, "unit": "x", "basis_period": "live"},
        {"id": "revenue__current_annual", "value": 215.94e9, "unit": "USD",
         "basis_period": "year ended 2026-01-25 (filer FY field=2026)"},
        {"id": "revenue__prior_annual", "value": 130.5e9, "unit": "USD",
         "basis_period": "year ended 2025-01-26 (filer FY field=2025)"},
        {"id": "gross_margin__current_annual", "value": 0.711, "unit": "ratio", "basis_period": "FY2026"},
        {"id": "gross_margin__prior_annual", "value": 0.75, "unit": "ratio", "basis_period": "FY2025"},
        {"id": "fcf__current_annual", "value": 96.74e9, "unit": "USD", "basis_period": "FY2026"},
        {"id": "buyback_spend__current_annual", "value": 40.09e9, "unit": "USD", "basis_period": "FY2026"},
        {"id": "capex__current_annual", "value": 8.26e9, "unit": "USD", "basis_period": "FY2026"},
        {"id": "options_put_call_volume_ratio__live", "value": 0.4996, "unit": "ratio", "basis_period": "live"},
        {"id": "insider_net_shares_heuristic__live", "value": -3388137.0, "unit": "shares", "basis_period": "live"},
    ]
    payload["metrics"] = {
        "records": records,
        "by_id": {r["id"]: r for r in records},
        "count": len(records),
        "excluded_stale": 3,
    }
    payload["valuation"] = {
        "dcf": {
            "method": "multi_stage_fcf_dcf",
            "inputs": {"price": 196.51, "base_fcf_annual": 96.74e9, "net_debt": -2.14e9},
            "assumptions": {"wacc": 0.10, "g_high": 0.35, "g_terminal": 0.03},
            "projections": [{"year": 1, "fcf": 130.6e9}, {"year": 2, "fcf": 176.3e9}],
            "fair_value_per_share": 318.85,
            "fair_value_range": {"low": 271.0, "base": 318.85, "high": 366.7},
            "epv_per_share": 40.03,
            "implied_upside_vs_price": 0.6226,
            "enterprise_value": 7.7e12,
        },
        "comps": {
            "subject": {"ticker": "NVDA", "price": 196.51, "trailing_pe": 40.1,
                        "forward_pe": 31.7, "ev_to_ebitda": 34.2, "price_to_sales": 22.0},
            "peers": [
                {"ticker": "AMD", "price": 178.4, "trailing_pe": 92.1, "forward_pe": 38.4,
                 "ev_to_ebitda": 61.2, "price_to_sales": 9.8},
                {"ticker": "TSM", "price": 268.3, "trailing_pe": 32.8, "forward_pe": 24.1,
                 "ev_to_ebitda": 18.9, "price_to_sales": 13.6},
            ],
            "peer_medians": {"trailing_pe": 32.8, "forward_pe": 29.2,
                             "ev_to_ebitda": 18.6, "price_to_sales": 8.0},
            "overall_vs_peers": "cheap",
        },
    }
    return payload


def _pdf_text(path: Path) -> str:
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def test_visual_pages_render_engine_numbers(tmp_path: Path):
    """The deck must show the figures, not merely narrate them."""
    out = generate_pdf(_visual_payload(), output_path=tmp_path / "deck.pdf")
    text = _pdf_text(out)
    assert "Operating & Financial Profile" in text
    assert "What It Is Worth" in text
    assert "Against the Peer Set" in text
    assert "Bull vs Bear" in text
    assert "318.85" in text          # DCF fair value
    assert "62.3%" in text           # implied upside
    assert "$4.76T" in text          # market cap tile
    assert "40.1x" in text           # canonical trailing P/E


def test_schema_1_0_payload_still_renders_without_visual_pages(tmp_path: Path):
    """Older artifacts carry no numbers; every visual page must self-skip."""
    out = generate_pdf(_payload(), output_path=tmp_path / "legacy.pdf")
    text = _pdf_text(out)
    assert out.is_file()
    assert "Operating & Financial Profile" not in text
    assert "Against the Peer Set" not in text
    assert "BUSINESS OVERVIEW" in text.upper()


def test_stale_and_compliance_content_never_reaches_the_deck(tmp_path: Path):
    payload = _visual_payload()
    out = generate_pdf(payload, output_path=tmp_path / "deck.pdf")
    text = _pdf_text(out)
    for probe in ("MUST NEVER RENDER", "QC & Compliance", "backend metadata"):
        assert probe not in text


def test_debate_spread_falls_back_when_sides_are_not_identifiable(tmp_path: Path):
    """Sub-heading wording is model-authored and drifts; a miss must not ship
    a half-empty spread — the section falls back to long-form prose."""
    payload = _visual_payload()
    payload["subsections"] = {
        "key_debate_points": [
            {"title": "First consideration", "text": "..."},
            {"title": "Second consideration", "text": "..."},
        ]
    }
    text = _pdf_text(generate_pdf(payload, output_path=tmp_path / "d.pdf"))
    assert "Bull vs Bear" not in text
    assert "CENTRAL DEBATE" in text.upper()


def test_pick_side_matches_drifting_subsection_titles():
    subs = [{"title": "Where the bear lands real blows"}, {"title": "The long case"}]
    assert _pick_side(subs, ("bear", "short case"))["title"].startswith("Where the bear")
    assert _pick_side(subs, ("bull", "long case"))["title"] == "The long case"
    assert _pick_side(subs, ("nothing",)) is None


def test_metric_book_tolerates_missing_and_null_values():
    book = MetricBook({"by_id": {"price": {"id": "price", "value": None}}})
    assert book.value("price") is None
    assert book.value("does_not_exist") is None
    assert MetricBook(None).value("price") is None
    assert not MetricBook({})


def test_column_overflow_returns_the_remainder_exactly_once():
    """Regression: overflow paragraphs were re-appended and printed twice."""
    from mas_sector_system.pdf_generator import HawktradePDF

    pdf = HawktradePDF(ticker="TEST", as_of="today")
    pdf.add_page()
    paragraphs = [f"Paragraph {i}. " + "word " * 60 for i in range(12)]
    left = _column_markdown(pdf, 20, 30, 70, paragraphs, max_y=90)
    assert left, "expected an overflow with this much text"
    assert len(left) == len(set(left))
    rendered = len(paragraphs) - len(left)
    assert paragraphs[rendered:] == left


# ── Refactor: sanitization, styling, page budget ─────────────────────────────


def test_sanitizer_converts_xbrl_tags_instead_of_deleting_them():
    """Provenance is what makes a claim checkable — condense it, don't drop it."""
    from mas_sector_system.pdf_generator import sanitize_prose

    raw = ('gross margin of 71.1% (year ended 2026-01-25 (filer FY field=2026)) '
           'vs "gross margin of 75.0% (year ended 2025-01-26 (filer FY field=2026))"')
    out = sanitize_prose(raw)
    assert "filer FY" not in out
    assert "2026-01-25" not in out
    assert "(FY2026)" in out
    # Annual labels come from the period end date: the filer FY field stamps
    # both of these as 2026, which would render "FY2026 vs FY2026".
    assert "FY2025" in out
    assert "71.1%" in out and "75.0%" in out


def test_sanitizer_strips_machine_fragments_and_balances_parens():
    from mas_sector_system.pdf_generator import sanitize_prose

    raw = "net margin of 55.6% (year ended 2026-01-25 (filer FY field=2026); net_income / revenue)"
    out = sanitize_prose(raw)
    assert "net_income / revenue" not in out
    assert out.count("(") == out.count(")"), out
    assert not re.search(r"\(\s*[;,]", out)
    assert "55.6%" in out


def test_sanitizer_preserves_every_numeric_token():
    from mas_sector_system.pdf_generator import sanitize_prose

    raw = ("revenue of $215.94B (year ended 2026-01-25 (filer FY field=2026)), "
           "EPS 4.90, growth 65.5%, P/E 40.1x")
    out = sanitize_prose(raw)
    for token in ("$215.94B", "4.90", "65.5%", "40.1x"):
        assert token in out


def test_rendered_report_carries_no_raw_xbrl_or_timestamps(tmp_path: Path):
    payload = _visual_payload()
    payload["sections"]["business_overview"] = (
        "Margin of 71.1% (year ended 2026-01-25 (filer FY field=2026)) held. " * 6
    )
    text = _pdf_text(generate_pdf(payload, output_path=tmp_path / "clean.pdf"))
    assert "filer FY" not in text
    assert not re.search(r"\d{4}-\d{2}-\d{2}", text)


def test_page_budget_is_enforced_and_appendix_restores_full_text(tmp_path: Path):
    payload = _visual_payload()
    long_body = "A materially long analytical paragraph about the thesis. " * 60
    for key in ("business_overview", "macro_positioning", "catalysts_and_risks"):
        payload["sections"][key] = long_body

    core = generate_pdf(payload, output_path=tmp_path / "core.pdf")
    full = generate_pdf(payload, output_path=tmp_path / "full.pdf", appendix=True)

    pypdf = pytest.importorskip("pypdf")
    core_pages = len(pypdf.PdfReader(str(core)).pages)
    full_pages = len(pypdf.PdfReader(str(full)).pages)
    assert core_pages <= 12, f"page budget breached: {core_pages}"
    assert full_pages > core_pages


def test_every_theme_survives_the_budget(tmp_path: Path):
    """The budget condenses each section; it must not drop whole themes."""
    payload = _visual_payload()
    body = "A substantive paragraph carrying the argument for this theme. " * 40
    for key in ("business_overview", "macro_positioning", "catalysts_and_risks",
                "valuation_reconciliation"):
        payload["sections"][key] = body
    payload["sections_found"] = list(payload["sections"])
    text = _pdf_text(generate_pdf(payload, output_path=tmp_path / "themes.pdf")).upper()
    for theme in ("BUSINESS OVERVIEW", "MACRO", "CATALYSTS", "VALUATION"):
        assert theme in text, f"{theme} was dropped entirely"


def test_cover_shows_kpi_table_and_summary_points(tmp_path: Path):
    from mas_sector_system.pdf_generator import summary_bullets

    payload = _visual_payload()
    payload["sections"]["recommendation"] = (
        "BUY.\n"
        "- **Growth:** revenue growth of 65.5% (year ended 2026-01-25 (filer FY field=2026)).\n"
        "- **Cash:** free cash flow of $96.68B with no leverage on the balance sheet.\n"
        "- **Multiple:** trailing P/E of 40.1x against those growth rates today.\n"
    )
    bullets = summary_bullets(payload)
    assert len(bullets) >= 3
    assert bullets[0][0] == "Growth"
    assert "filer FY" not in bullets[0][1]

    text = _pdf_text(generate_pdf(payload, output_path=tmp_path / "cover.pdf"))
    assert "INVESTMENT SUMMARY" in text
    assert "Implied upside" in text and "Price target" in text
