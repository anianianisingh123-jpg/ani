"""Tests for valuation_rubric.py (VAL-02 Track C part 1).

Offline and free — synthetic ResearchState fixtures only. No live SEC,
yfinance, Tavily, or LLM API calls. Injectable judge covers criteria 1 and 8.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mas_sector_system.valuation_rubric import (  # noqa: E402
    HELD_OUT_TICKERS,
    RUBRIC,
    format_rubric_for_prompt,
    grade_valuation,
)


# ── Rubric shape ─────────────────────────────────────────────────────────────

def test_rubric_has_eleven_binary_criteria():
    assert len(RUBRIC) == 11
    assert [c["id"] for c in RUBRIC] == list(range(1, 12))
    for c in RUBRIC:
        assert c["type"] == "binary"
        assert "criterion" in c and c["criterion"]
        assert "name" in c and c["name"]
        assert "mechanical" in c
        assert "requires_judgment" in c


def test_rubric_mechanical_and_judgment_flags_match_design():
    """§12: 3,5,7,9,11 mechanical; 1,8 require judgment."""
    by_id = {c["id"]: c for c in RUBRIC}
    for cid in (3, 5, 7, 9, 11):
        assert by_id[cid]["mechanical"] is True
        assert by_id[cid]["requires_judgment"] is False
    for cid in (1, 8):
        assert by_id[cid]["requires_judgment"] is True
        assert by_id[cid]["mechanical"] is False


def test_format_rubric_for_prompt_lists_all_criteria():
    block = format_rubric_for_prompt()
    assert "VALUATION QUALITY RUBRIC" in block
    for c in RUBRIC:
        assert c["criterion"] in block
        assert str(c["id"]) in block
    assert "LLM-judged" in block
    assert "mechanical" in block


def test_held_out_tickers_match_section_10_2():
    tickers = [h["ticker"] for h in HELD_OUT_TICKERS]
    assert tickers == ["NVDA", "QCOM", "CRM", "JPM", "PLD", "PGR", "XOM", "KO"]
    assert "BABA" not in tickers


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _base_engines() -> dict:
    """Minimal dcf_engine + comps_engine with realistic numbers."""
    return {
        "dcf_engine": {
            "method": "multi_stage_fcf_dcf",
            "ticker": "NVDA",
            "sector": "Semiconductors",
            "inputs": {
                "base_fcf_annual": 6.0e10,
                "price": 120.0,
                "shares_outstanding": 2.45e10,
                "net_debt": -3.0e10,
            },
            "assumptions": {
                "wacc": 0.105,
                "g_high": 0.20,
                "g_terminal": 0.03,
                "high_growth_years": 5,
                "fade_years": 5,
            },
            "enterprise_value": 3.5e12,
            "equity_value": 3.53e12,
            "fair_value_per_share": 144.08,
            "fair_value_range": {
                "low": 122.47,
                "base": 144.08,
                "high": 165.69,
                "basis": "±15% band",
            },
            "terminal_value": 2.8e12,
            "terminal_value_pv": 1.9e12,
            "epv_per_share": 40.0,
            "implied_upside_vs_price": 0.20,
            "warnings": [],
            "errors": [],
        },
        "comps_engine": {
            "subject_archetype": "general",
            "peer_source": "sector",
            "peer_list": ["AMD", "AVGO", "TSM"],
            "relative_valuation_applicable": True,
            "overall_vs_peers": "rich",
            "subject": {
                "ticker": "NVDA",
                "price": 120.0,
                "trailing_pe": 40.0,
                "forward_pe": 28.0,
                "ev_to_ebitda": 32.0,
                "price_to_sales": 22.0,
            },
            "peer_medians": {
                "trailing_pe": 27.0,
                "forward_pe": 22.0,
                "ev_to_ebitda": 18.0,
                "price_to_sales": 8.0,
            },
            "peers": [
                {"ticker": "AMD", "trailing_pe": 30.0, "forward_pe": 24.0, "price": 150.0},
                {"ticker": "AVGO", "trailing_pe": 28.0, "forward_pe": 23.0, "price": 200.0},
                {"ticker": "TSM", "trailing_pe": 22.0, "forward_pe": 18.0, "price": 180.0},
            ],
            "peer_exclusions": [
                {"ticker": "AAPL", "reason": "Archetype mismatch (consumer hardware)"},
            ],
            "notes": [],
        },
        "canonical_metrics": {
            "trailing_pe": {"value": 40.0, "headline": "Trailing P/E 40.0x", "staleness": ""},
            "revenue_growth": {"value": 0.55, "headline": "Revenue growth 55%", "staleness": ""},
        },
    }


def _icl_critique_and_judgment() -> dict:
    """Post-ICL fields per §4.5 / §7."""
    return {
        "valuation_critique": {
            "archetype": "general",
            "method_appropriate": True,
            "method_reasoning": "FCF DCF is appropriate; capital-light, positive FCF.",
            "arguments": [
                {
                    "parameter": "wacc",
                    "engine_default": 0.105,
                    "argued_range": [0.090, 0.100],
                    "verdict": "too_high",
                    "reasoning": "Net cash and IG customer base.",
                    "evidence": ["dcf_engine.inputs.net_debt"],
                }
            ],
            "terminal_value_share_of_ev": 0.71,
            "overall_confidence": "moderate",
            "band_dissents": [],
            "clamp_warnings": [],
        },
        "relative_critique": {
            "archetype": "general",
            "primary_multiple": "forward_pe",
            "multiple_reasoning": "Forward P/E is the cleanest multiple here.",
            "peer_changes": [
                {
                    "ticker": "TSM",
                    "action": "exclude",
                    "reasoning": "Foundry vs fabless end-market mismatch.",
                    "evidence": ["comps_engine.peers"],
                }
            ],
            "justified_multiple": {
                "metric": "forward_pe",
                "subject_current": 28.0,
                "peer_median": 22.0,
                "argued_range": [26.0, 30.0],
                "reasoning": "Growth premium still warranted.",
                "evidence": ["canonical_metrics.revenue_growth"],
            },
            "clamp_warnings": [],
            "band_dissents": [],
        },
        "dcf_judgment": {
            "input_source": "argued",
            "fair_value_per_share": 160.0,
            "fair_value_range": {"low": 150.0, "base": 160.0, "high": 175.0},
            "clamp_warnings": [],
            "band_dissents": [],
        },
        "comps_judgment": {
            "input_source": "argued",
            "implied_value_low": 130.0,
            "implied_value_high": 150.0,
            "clamp_warnings": [],
            "band_dissents": [],
        },
    }


def _passing_narratives() -> dict:
    return {
        "fundamental_valuation": (
            "Archetype: general (semiconductor catch-all). Primary method is multi-stage "
            "FCF DCF — capital-light with durable free cash flow. Engine base fair value "
            "is $144.08 per share (range $122.47 – $165.69). Terminal value is 71% of "
            "enterprise value, a red flag for assumption sensitivity. WACC 10.5% is the "
            "sector default. One risk remains open: customer concentration at the top "
            "hyperscalers is not resolved by backlog disclosures. "
            "What would change this call is still an open question on export controls."
        ),
        "relative_valuation": (
            "Forward P/E 28.0x versus peer median 22.0x. Peers used: AMD, AVGO. "
            "TSM excluded for foundry mismatch. Relative read is rich on a 1-year window "
            "only (single comparison window). Valuation band from argued multiple: "
            "between $130 and $150 per share."
        ),
        "final_memo": (
            "## 6. VALUATION RECONCILIATION\n"
            "Default DCF $144.08; judgment case $150 – $175. Comps band $130 to $150.\n"
            "Geopolitical export risk remains unresolved.\n"
        ),
        "business_overview": "Accelerated computing platforms.",
        "macro_regime_assessment": "TAILWIND moderate.",
        "management_assessment": "Founder-led.",
        "capital_allocation_assessment": "Buybacks + R&D.",
    }


def _good_state(**over) -> dict:
    state = {
        "ticker": "NVDA",
        "sector": "Semiconductors",
        "mode": "deep_dive",
        "user_query": "Full underwrite",
        **_base_engines(),
        **_icl_critique_and_judgment(),
        **_passing_narratives(),
    }
    state.update(over)
    return state


def _always_pass_judge(cid: int, state: dict, text: str) -> tuple[bool, str]:
    return True, f"judge pass for criterion {cid}"


def _always_fail_judge(cid: int, state: dict, text: str) -> tuple[bool, str]:
    return False, f"judge fail for criterion {cid}"


def _result_by_id(grade: dict) -> dict[int, dict]:
    return {r["id"]: r for r in grade["criteria"]}


# ── Full-score happy path ────────────────────────────────────────────────────

def test_grade_all_pass_with_icl_state_and_judge():
    grade = grade_valuation(_good_state(), judge=_always_pass_judge)
    assert grade["max_score"] == 11
    assert grade["score"] == 11
    assert grade["ticker"] == "NVDA"
    by = _result_by_id(grade)
    assert by[1]["judged"] is True and by[1]["passed"] is True
    assert by[8]["judged"] is True and by[8]["passed"] is True
    for cid in (2, 3, 4, 5, 6, 7, 9, 10, 11):
        assert by[cid]["judged"] is False
        assert by[cid]["passed"] is True
        assert by[cid]["method"] == "mechanical" or by[cid]["mechanical"] is True


def test_judge_failure_only_affects_criteria_1_and_8():
    grade = grade_valuation(_good_state(), judge=_always_fail_judge)
    by = _result_by_id(grade)
    assert by[1]["passed"] is False and by[1]["judged"] is True
    assert by[8]["passed"] is False and by[8]["judged"] is True
    # Mechanical criteria still pass.
    for cid in (3, 5, 7, 9, 11):
        assert by[cid]["passed"] is True
    assert grade["score"] == 9


# ── Criterion 3 — untraceable currency ───────────────────────────────────────

def test_c3_fails_on_invented_currency_figure():
    state = _good_state(
        fundamental_valuation=(
            "I modeled FY2027 revenue to be $376,503 million with no engine support. "
            "Engine fair value is $144.08."
        ),
        relative_valuation="Peer table only.",
        final_memo="",
    )
    grade = grade_valuation(state, judge=_always_pass_judge)
    by = _result_by_id(grade)
    assert by[3]["passed"] is False
    assert "untraceable" in by[3]["detail"].lower() or "376" in by[3]["detail"]


def test_c3_passes_when_currency_matches_engine():
    state = _good_state(
        fundamental_valuation="Fair value is $144.08; live price $120.0.",
        relative_valuation="No extra currency.",
        final_memo="",
        # Drop ICL narratives that inject other $ figures; keep engines.
        valuation_critique={
            "archetype": "general",
            "method_appropriate": True,
            "method_reasoning": "DCF ok",
            "arguments": [],
            "terminal_value_share_of_ev": 0.71,
            "band_dissents": [],
        },
        relative_critique={
            "archetype": "general",
            "primary_multiple": "forward_pe",
            "multiple_reasoning": "ok",
            "peer_changes": [],
            "justified_multiple": {
                "metric": "forward_pe",
                "subject_current": 28.0,
                "peer_median": 22.0,
                "argued_range": [26.0, 30.0],
                "reasoning": "ok",
                "evidence": ["canonical_metrics.revenue_growth"],
            },
            "band_dissents": [],
        },
    )
    # Re-add required open risk + range + archetype for other criteria if needed;
    # we only assert c3 here.
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[3]["passed"] is True


# ── Criterion 5 — range vs point ─────────────────────────────────────────────

def test_c5_fails_on_point_only_valuation():
    state = _good_state(
        fundamental_valuation=(
            "Archetype general. Primary method DCF. Fair value is $144.08. "
            "Terminal value is 71% of enterprise value. Risk remains open."
        ),
        relative_valuation="Rich on forward P/E.",
        final_memo="Price target $144.08.",
        # Remove structured ranges that would rescue the criterion.
        valuation_critique={
            "archetype": "general",
            "method_appropriate": True,
            "method_reasoning": "DCF",
            "arguments": [
                {
                    "parameter": "wacc",
                    "engine_default": 0.105,
                    # deliberately no argued_range
                    "verdict": "defensible",
                    "reasoning": "ok",
                    "evidence": ["dcf_engine.inputs.net_debt"],
                }
            ],
            "terminal_value_share_of_ev": 0.71,
            "band_dissents": [],
        },
        relative_critique={
            "archetype": "general",
            "primary_multiple": "forward_pe",
            "multiple_reasoning": "ok",
            "peer_changes": [],
            "justified_multiple": {
                "metric": "forward_pe",
                "subject_current": 28.0,
                "peer_median": 22.0,
                # no argued_range
                "reasoning": "ok",
                "evidence": ["canonical_metrics.revenue_growth"],
            },
            "band_dissents": [],
        },
        dcf_judgment={"input_source": "argued", "fair_value_per_share": 160.0},
        comps_judgment={"input_source": "argued", "implied_value": 140.0},
    )
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[5]["passed"] is False


def test_c5_passes_on_range_language():
    state = _good_state(
        fundamental_valuation="Fair value range $122.47 – $165.69 per share.",
        relative_valuation="Comps imply between $130 and $150.",
        final_memo="",
    )
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[5]["passed"] is True


# ── Criterion 7 — comparison windows ─────────────────────────────────────────

def test_c7_fails_on_ytd_vs_1y_mix():
    state = _good_state(
        relative_valuation=(
            "Stock is up 40% YTD while peers returned 12% over the 1-year window."
        ),
    )
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[7]["passed"] is False
    assert "mixed" in by[7]["detail"].lower()


def test_c7_passes_when_single_window():
    state = _good_state(
        relative_valuation="Peer multiples use trailing twelve month earnings only.",
        fundamental_valuation="DCF uses annual FCF. Risk remains open. Range $120 – $170.",
        final_memo="",
    )
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[7]["passed"] is True


# ── Criterion 9 — default + judgment ─────────────────────────────────────────

def test_c9_fails_without_judgment_cases():
    """Pre-ICL baseline shape: engines + narratives only."""
    state = {
        "ticker": "NVDA",
        "sector": "Semiconductors",
        **_base_engines(),
        "fundamental_valuation": "DCF narrated at $144.08.",
        "relative_valuation": "Comps rich.",
        "final_memo": "",
    }
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[9]["passed"] is False
    assert "dcf_judgment" in by[9]["detail"] or "missing" in by[9]["detail"].lower()


def test_c9_passes_with_both_default_and_judgment():
    by = _result_by_id(grade_valuation(_good_state(), judge=_always_pass_judge))
    assert by[9]["passed"] is True


def test_c9_comps_inapplicable_does_not_require_comps_judgment():
    engines = _base_engines()
    engines["comps_engine"] = {
        "relative_valuation_applicable": False,
        "peer_list": [],
        "peers": [],
        "notes": ["Fewer than 2 peers"],
    }
    state = _good_state(
        **engines,
        comps_judgment=None,  # type: ignore[arg-type]
    )
    # Explicitly remove comps_judgment
    state.pop("comps_judgment", None)
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[9]["passed"] is True


# ── Criterion 11 — numeric contradiction ─────────────────────────────────────

def test_c11_fails_on_conflicting_labeled_numbers():
    state = _good_state(
        fundamental_valuation=(
            "The company holds 196,000 patents in the portfolio overview. "
            "Later the same memo claims over 300,000 patents. "
            "Fair value range $122 – $166. Risk remains open. Archetype general, method DCF."
        ),
        relative_valuation="No extra labels.",
        final_memo="",
    )
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[11]["passed"] is False
    assert "patent" in by[11]["detail"].lower()


def test_c11_passes_when_labels_consistent():
    state = _good_state(
        fundamental_valuation=(
            "WACC 10.5% throughout. Fair value $144.08. "
            "Range $122.47 – $165.69. Terminal value 71% of EV. Risk remains open."
        ),
        relative_valuation="Trailing P/E 40.0.",
        final_memo="",
    )
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[11]["passed"] is True


def test_c11_two_case_default_and_judgment_not_contradiction():
    """VAL-13: base FV + judgment corners are the feature, not a fail."""
    state = _good_state(
        fundamental_valuation=(
            "Engine base fair value $144.08 per share (WACC 10.5%, g_high 20%). "
            "Judgment case: fair value $88.24 – $146.45 (WACC 11.5%–13.5%, "
            "g_high 18%–28%). Risk remains open."
        ),
        relative_valuation="Comps only.",
        final_memo="",
        dcf_engine={
            **_base_engines()["dcf_engine"],
            "fair_value_per_share": 144.08,
            "fair_value_range": {"low": 122.47, "base": 144.08, "high": 165.69},
            "assumptions": {
                "wacc": 0.105,
                "g_high": 0.20,
                "g_terminal": 0.03,
            },
        },
        dcf_judgment={
            "input_source": "argued",
            "fair_value_per_share": None,
            "fair_value_range": {
                "low": 88.24,
                "base": 117.34,
                "high": 146.45,
                "basis": "two argued-input corners",
            },
            "assumptions": {
                "wacc": 0.125,
                "g_high": 0.23,
                "g_terminal": 0.03,
            },
            "clamp_warnings": [],
            "band_dissents": [],
        },
        valuation_critique={
            "archetype": "general",
            "method_appropriate": True,
            "method_reasoning": "DCF ok",
            "arguments": [
                {
                    "parameter": "wacc",
                    "engine_default": 0.105,
                    "argued_range": [0.115, 0.135],
                    "verdict": "too_low",
                    "reasoning": "concentration risk",
                    "evidence": ["dcf_engine.inputs.net_debt"],
                },
                {
                    "parameter": "g_high",
                    "engine_default": 0.20,
                    "argued_range": [0.18, 0.28],
                    "verdict": "defensible",
                    "reasoning": "fade from peak",
                    "evidence": ["canonical_metrics.revenue_growth"],
                },
            ],
            "terminal_value_share_of_ev": 0.65,
            "band_dissents": [],
        },
    )
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[11]["passed"] is True, by[11]["detail"]
    assert "two-case" in by[11]["detail"].lower() or "explained" in by[11]["detail"].lower()


def test_c11_still_flags_true_within_case_contradiction():
    """Patents 196k vs 300k is still a real contradiction."""
    state = _good_state(
        fundamental_valuation=(
            "The company holds 196,000 patents. Later: over 300,000 patents. "
            "Fair value $144.08. Range $122 – $166."
        ),
        relative_valuation="",
        final_memo="",
    )
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[11]["passed"] is False
    assert "patent" in by[11]["detail"].lower()


# ── Criterion 2 — evidence ───────────────────────────────────────────────────

def test_c2_vacuous_pass_without_critiques():
    state = {
        "ticker": "KO",
        **_base_engines(),
        "fundamental_valuation": "Point estimate only.",
        "relative_valuation": "",
        "final_memo": "",
    }
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[2]["passed"] is True
    assert "vacuous" in by[2]["detail"].lower()


def test_c2_fails_on_empty_evidence():
    state = _good_state(
        valuation_critique={
            "archetype": "general",
            "method_appropriate": True,
            "method_reasoning": "DCF",
            "arguments": [
                {
                    "parameter": "wacc",
                    "engine_default": 0.105,
                    "argued_range": [0.09, 0.10],
                    "verdict": "too_high",
                    "reasoning": "hand-wave",
                    "evidence": [],
                }
            ],
            "terminal_value_share_of_ev": 0.71,
            "band_dissents": [],
        },
    )
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[2]["passed"] is False
    assert "empty evidence" in by[2]["detail"].lower()


def test_c2_fails_on_unresolvable_evidence_field():
    state = _good_state(
        # No judgment case → cannot fall back to engine accept record.
        dcf_judgment=None,  # type: ignore[arg-type]
        valuation_critique={
            "archetype": "general",
            "method_appropriate": True,
            "method_reasoning": "DCF",
            "arguments": [
                {
                    "parameter": "g_high",
                    "engine_default": 0.20,
                    "argued_range": [0.12, 0.15],
                    "verdict": "too_high",
                    "reasoning": "invented field",
                    "evidence": ["made_up_root.foo"],
                }
            ],
            "terminal_value_share_of_ev": 0.71,
            "band_dissents": [],
        },
    )
    state.pop("dcf_judgment", None)
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[2]["passed"] is False
    assert "no resolvable evidence" in by[2]["detail"].lower() or "rejected" in by[2]["detail"].lower()


def test_c2_uses_engine_resolver_for_canonical_by_id():
    """VAL-13: metric keys live under canonical_metrics.by_id, not top-level."""
    state = _good_state(
        canonical_metrics={
            "ticker": "NVDA",
            "by_id": {
                "fcf__current_annual": {
                    "value": 14_402_000_000.0,
                    "headline": "FCF $14.4B",
                    "staleness": "",
                },
                "revenue_growth": {"value": 0.55, "headline": "rev +55%", "staleness": ""},
            },
        },
        valuation_critique={
            "archetype": "general",
            "method_appropriate": True,
            "method_reasoning": "DCF",
            "arguments": [
                {
                    "parameter": "g_high",
                    "engine_default": 0.20,
                    "argued_range": [0.12, 0.15],
                    "verdict": "too_high",
                    "reasoning": "peak FCF",
                    "evidence": ["canonical_metrics.fcf__current_annual"],
                }
            ],
            "terminal_value_share_of_ev": 0.71,
            "band_dissents": [],
        },
        # Drop other arguments so only this one is graded
        relative_critique={
            "archetype": "general",
            "primary_multiple": "forward_pe",
            "multiple_reasoning": "ok",
            "peer_changes": [],
            "justified_multiple": {
                "metric": "forward_pe",
                "subject_current": 28.0,
                "peer_median": 22.0,
                "argued_range": [26.0, 30.0],
                "reasoning": "ok",
                "evidence": ["canonical_metrics.revenue_growth"],
            },
            "band_dissents": [],
        },
    )
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[2]["passed"] is True, by[2]["detail"]


def test_c2_engine_accept_record_fallback_when_slice_incomplete():
    """When statements are missing but the engine accepted the param, pass."""
    state = _good_state(
        # No cash_flow_statement in state (simulates thin slice)
        valuation_critique={
            "archetype": "general",
            "method_appropriate": True,
            "method_reasoning": "DCF",
            "arguments": [
                {
                    "parameter": "base_fcf_method",
                    "engine_default": "ttm",
                    "argued_range": ["avg_3y", "avg_3y"],
                    "verdict": "defensible",
                    "reasoning": "mid-cycle",
                    "evidence": ["cash_flow_statement.current_annual.FreeCashFlow"],
                }
            ],
            "terminal_value_share_of_ev": 0.71,
            "band_dissents": [],
        },
        dcf_judgment={
            "input_source": "argued",
            "assumptions": {"base_fcf_method": "avg_3y", "wacc": 0.10},
            "fair_value_range": {"low": 100.0, "base": 110.0, "high": 120.0},
            "clamp_warnings": [],  # no evidence rejection
            "band_dissents": [],
        },
        relative_critique={
            "archetype": "general",
            "primary_multiple": "forward_pe",
            "multiple_reasoning": "ok",
            "peer_changes": [],
            "justified_multiple": {
                "metric": "forward_pe",
                "argued_range": [26.0, 30.0],
                "reasoning": "ok",
                "evidence": ["canonical_metrics.revenue_growth"],
            },
            "band_dissents": [],
        },
    )
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[2]["passed"] is True, by[2]["detail"]
    assert "engine_record" in by[2]["detail"]


# ── Criterion 4 — TV share ───────────────────────────────────────────────────

def test_c4_passes_when_critique_has_tv_share():
    by = _result_by_id(grade_valuation(_good_state(), judge=_always_pass_judge))
    assert by[4]["passed"] is True


def test_c4_fails_when_dcf_present_but_tv_share_missing():
    state = _good_state(
        valuation_critique={
            "archetype": "general",
            "method_appropriate": True,
            "method_reasoning": "DCF",
            "arguments": [],
            # no terminal_value_share_of_ev
            "band_dissents": [],
        },
        fundamental_valuation="DCF fair value $144.08. No TV share mentioned.",
        relative_valuation="Comps only.",
        final_memo="",
    )
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[4]["passed"] is False


def test_c4_na_pass_when_method_not_appropriate():
    state = _good_state(
        valuation_critique={
            "archetype": "bank_lender",
            "method_appropriate": False,
            "method_reasoning": "Use residual income for banks.",
            "arguments": [],
            "band_dissents": [],
        },
        fundamental_valuation="Residual income path; no FCF DCF.",
        final_memo="",
    )
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[4]["passed"] is True
    assert "not applicable" in by[4]["detail"].lower() or "n/a" in by[4]["detail"].lower()


# ── Criterion 6 — peer justifications ────────────────────────────────────────

def test_c6_fails_when_peer_change_lacks_reasoning():
    state = _good_state(
        relative_critique={
            "archetype": "general",
            "primary_multiple": "forward_pe",
            "multiple_reasoning": "ok",
            "peer_changes": [
                {
                    "ticker": "TSM",
                    "action": "exclude",
                    "reasoning": "",
                    "evidence": ["comps_engine.peers"],
                }
            ],
            "justified_multiple": {
                "metric": "forward_pe",
                "subject_current": 28.0,
                "peer_median": 22.0,
                "argued_range": [26.0, 30.0],
                "reasoning": "ok",
                "evidence": ["canonical_metrics.revenue_growth"],
            },
            "band_dissents": [],
        },
    )
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[6]["passed"] is False


def test_c6_uses_engine_exclusions_pre_icl():
    state = {
        "ticker": "NVDA",
        **_base_engines(),
        "fundamental_valuation": "DCF.",
        "relative_valuation": "Comps.",
        "final_memo": "",
    }
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[6]["passed"] is True
    assert "exclusion" in by[6]["detail"].lower() or "vacuous" in by[6]["detail"].lower()


# ── Criterion 10 — band dissents ─────────────────────────────────────────────

def test_c10_passes_when_no_dissents():
    by = _result_by_id(grade_valuation(_good_state(), judge=_always_pass_judge))
    assert by[10]["passed"] is True


def test_c10_passes_when_dissents_flagged_with_reasoning():
    state = _good_state(
        valuation_critique={
            "archetype": "general",
            "method_appropriate": True,
            "method_reasoning": "DCF",
            "arguments": [
                {
                    "parameter": "wacc",
                    "engine_default": 0.105,
                    "argued_range": [0.07, 0.08],
                    "verdict": "too_high",
                    "reasoning": "Out of band low.",
                    "evidence": ["dcf_engine.inputs.net_debt"],
                }
            ],
            "terminal_value_share_of_ev": 0.71,
            "band_dissents": [
                {
                    "parameter": "wacc",
                    "reasoning": "Below software_saas band floor; justified by net cash.",
                }
            ],
        },
    )
    by = _result_by_id(grade_valuation(state, judge=_always_pass_judge))
    assert by[10]["passed"] is True
    assert "1 band dissent" in by[10]["detail"].lower() or "dissent" in by[10]["detail"].lower()


# ── Heuristic fallback for 1/8 (no judge) ────────────────────────────────────

def test_c1_and_c8_heuristic_without_judge_not_marked_judged():
    state = _good_state()
    grade = grade_valuation(state)  # no judge
    by = _result_by_id(grade)
    assert by[1]["judged"] is False
    assert by[8]["judged"] is False
    assert by[1]["method"] == "heuristic_fallback"
    assert by[8]["method"] == "heuristic_fallback"
    # Good narratives should still pass the heuristics.
    assert by[1]["passed"] is True
    assert by[8]["passed"] is True


def test_c8_heuristic_fails_on_self_neutralizing_close():
    state = _good_state(
        fundamental_valuation=(
            "Archetype general. Method DCF. Fair value range $120 – $170. "
            "All risks are fully mitigated and nothing to worry about."
        ),
        relative_valuation="Comps.",
        final_memo="",
    )
    by = _result_by_id(grade_valuation(state))
    assert by[8]["passed"] is False


# ── Grade result contract ────────────────────────────────────────────────────

def test_grade_result_shape_stable():
    grade = grade_valuation(_good_state(), judge=_always_pass_judge)
    assert set(grade.keys()) >= {"ticker", "score", "max_score", "criteria", "notes"}
    assert grade["max_score"] == 11
    assert isinstance(grade["score"], int)
    assert 0 <= grade["score"] <= 11
    for r in grade["criteria"]:
        assert set(r.keys()) >= {
            "id",
            "name",
            "criterion",
            "type",
            "mechanical",
            "requires_judgment",
            "passed",
            "judged",
            "detail",
            "method",
        }
        assert isinstance(r["passed"], bool)
        assert isinstance(r["judged"], bool)


def test_pre_icl_baseline_state_produces_partial_score():
    """What a live pre-VAL-01 run roughly looks like — engines + prose, no judgment."""
    state = {
        "ticker": "NVDA",
        "sector": "Semiconductors",
        **_base_engines(),
        "fundamental_valuation": (
            "Multi-stage FCF DCF at sector WACC. Fair value $144.08. "
            "Stock looks attractive at $120."
        ),
        "relative_valuation": (
            "Trailing P/E 40.0 vs peers. Up 40% YTD and 25% over the 1-year window."
        ),
        "final_memo": "Price target $144.08. All risks are fully mitigated.",
    }
    grade = grade_valuation(state, judge=_always_fail_judge)
    by = _result_by_id(grade)
    # Expected structural fails on a pre-ICL point-estimate memo:
    assert by[5]["passed"] is False  # point, not range
    assert by[7]["passed"] is False  # YTD + 1y mix
    assert by[9]["passed"] is False  # no judgment case
    assert by[1]["judged"] is True and by[1]["passed"] is False
    assert by[8]["judged"] is True and by[8]["passed"] is False
    assert grade["score"] < grade["max_score"]
