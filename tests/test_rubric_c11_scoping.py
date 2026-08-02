"""C11 must reject extractor noise without going blind to real contradictions.

On the 2026-07-30 eight-ticker baseline C11 failed 5 of 8 tickers and the
handoff attributed it to writer discipline. Every failure traced to the
extractor: growth rates scraped out of "FY26", EPS scraped out of "FY2025",
peer P/E multiples read as growth rates, and annual EPS compared against
quarterly EPS that the memo had labelled correctly.

The risk in fixing that is over-correcting into a criterion that never fires.
These tests pin both directions.
"""

from __future__ import annotations

from mas_sector_system.valuation_rubric import _grade_c11


def _state() -> dict:
    return {
        "dcf_engine": {
            "method": "multi_stage_fcf_dcf",
            "assumptions": {"wacc": 0.10, "g_high": 0.158, "g_terminal": 0.03},
            "fair_value_per_share": 610.92,
        }
    }


# ── Must still fire on genuine contradictions ────────────────────────────────

def test_same_metric_same_period_stated_two_ways_is_still_a_contradiction():
    text = (
        "Our fair value per share is 420.00 on the base case. "
        "Later in the same section we conclude fair value per share of 260.00 "
        "with no change in assumptions."
    )
    result = _grade_c11(_state(), text)
    assert not result["passed"], f"C11 went blind: {result['detail']}"
    assert "fair_value" in result["detail"]


def test_contradictory_base_fcf_still_fires():
    text = (
        "Base FCF of $14.40B anchors the projection. "
        "The model actually compounds from base FCF of $9.10B."
    )
    result = _grade_c11(_state(), text)
    assert not result["passed"], f"C11 went blind on base FCF: {result['detail']}"


def test_contradictory_share_count_still_fires():
    text = (
        "The count is 960,000,000 shares on a diluted basis. "
        "Elsewhere the memo uses 1,240,000,000 shares for the same calculation."
    )
    result = _grade_c11(_state(), text)
    assert not result["passed"], f"C11 went blind on share count: {result['detail']}"


def test_contradictory_wacc_still_fires():
    text = "We discount at WACC = 9.0%. The model applies a discount rate of 14.0%."
    result = _grade_c11(_state(), text)
    assert not result["passed"], f"C11 went blind on WACC: {result['detail']}"


# ── Must not fire on the live false positives ────────────────────────────────

def test_multi_period_eps_is_not_a_contradiction():
    """JPM live text: FY2025 annual, annualized Q1, and raw Q1 EPS in one
    passage — all three correctly labelled by the memo, all three flagged by
    the old grader. EPS is no longer compared from prose at all."""
    text = (
        "Trailing P/E of 17.5x (price 350.85 / diluted EPS 20.02 from year ended "
        "2025-12-31). The packet separately notes that annualizing Q1 FY2026 EPS "
        "of $23.76 implies a forward-looking P/E near 14.8x. Q1 FY2026 net income "
        "of $16.49B (EPS $5.94) annualizes near $66B."
    )
    result = _grade_c11(_state(), text)
    assert result["passed"], f"period conflation returned: {result['detail']}"


def test_peer_multiple_is_not_a_growth_rate():
    """CRM live text — NOW's 68.8x trailing was read as g_high = 68.8%."""
    text = (
        "The engine's g_high = 15.8% is pulled from FY26 realized growth. "
        "Note the peer median is skewed by high-multiple, high-growth names "
        "(NOW's 68.8x trailing, SNOW's negative EV/EBITDA)."
    )
    result = _grade_c11(_state(), text)
    assert result["passed"], f"peer multiple read as a rate: {result['detail']}"


def test_fiscal_year_digits_are_not_values():
    """CRM/PGR live text — 'FY26' became 0.26, 'FY2025' became EPS 202.0."""
    text = (
        "The engine's 15.8% high growth rate is FY26 FCF growth, which was "
        "driven by margin timing. Annualized EPS ~flat vs FY2025 $19.23 — "
        "earnings plateau signal. Diluted EPS 19.23 for the year ended 2025-12-31."
    )
    result = _grade_c11(_state(), text)
    assert result["passed"], f"fiscal-year digits read as values: {result['detail']}"


def test_duration_gloss_is_not_a_rate():
    """NVDA live text — 'g_high (5-year high-growth rate)' became g_high = 0.05."""
    text = (
        "The engine runs at g_high = 35.0%, capped from the raw 58.9%. "
        "Key swing assumptions: g_high (5-year high-growth rate) dominates. "
        "A five-year linear fade from high growth to 3% is standard."
    )
    result = _grade_c11(_state(), text)
    assert result["passed"], f"duration gloss read as a rate: {result['detail']}"
