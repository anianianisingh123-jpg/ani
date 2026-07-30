"""Regressions from the first live argued-input run (2026-07-29).

Three bugs, all at the seam between the LLM and the deterministic engine —
the one place the existing suites had no coverage, because every fixture was
hand-written and therefore encoded the author's own assumptions.

1. UNITS. Asked for a defensible WACC, the model answered `11` on NVDA and
   `0.095` on CRM in the same batch. The engine expects decimals, so 11 was
   clamped to the 0.20 ceiling — silently producing a 20% WACC, a 40% growth
   rate and no fair value at all. Inconsistency made it unpredictable rather
   than uniformly wrong.
2. ENUM SHAPE. The prompt asks for `base_fcf_method` inside `argued_range`;
   the validator read `value`. Cash-flow normalisation — the single most
   valuable judgment in the design — never once applied.
3. EMPTY HEADLINE. The argued case leaves `fair_value_per_share` None by
   design (it is a range), but `fair_value_range["base"]` was also None, so
   every downstream consumer rendered a blank judgment case.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mas_sector_system import agents  # noqa: E402
from mas_sector_system.valuation_engine import validate_argued_inputs  # noqa: E402


DEFAULTS = {
    "assumptions": {
        "wacc": 0.10,
        "g_high": 0.12,
        "g_terminal": 0.025,
        "high_growth_years": 5,
        "fade_years": 5,
    }
}
STATE = {"canonical_metrics": {"by_id": {"beta": {"value": 1.6}}, "beta": {"value": 1.6}}}


def _arg(parameter, argued_range):
    return {
        "parameter": parameter,
        "argued_range": argued_range,
        "reasoning": "because",
        "evidence": ["canonical_metrics.beta"],
    }


def _validate(*args):
    return validate_argued_inputs(
        {"arguments": list(args)},
        archetype="general",
        engine_default=DEFAULTS,
        state=STATE,
    )


# ── 1. units ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "parameter,given,expected",
    [
        ("wacc", [11.0, 13.0], [0.11, 0.13]),          # NVDA, live
        ("g_high", [20.0, 30.0], [0.20, 0.30]),        # NVDA, live
        ("g_terminal", [2.25, 3.0], [0.0225, 0.03]),   # NVDA, live
    ],
)
def test_percent_scale_rates_are_normalized_not_clamped(parameter, given, expected):
    accepted, _ = _validate(_arg(parameter, given))
    got = accepted[parameter]["argued_range"]
    assert got == pytest.approx(expected), (
        f"{parameter} {given} must normalise to {expected}, not clamp to a ceiling"
    )


def test_normalization_is_disclosed_not_silent():
    _, warnings = _validate(_arg("wacc", [11.0, 13.0]))
    assert any("interpreted as a percentage" in w for w in warnings)


@pytest.mark.parametrize(
    "parameter,given",
    [
        ("wacc", [0.095, 0.11]),      # CRM, live — already correct
        ("g_terminal", [0.02, 0.03]),
        ("g_high", [0.08, 0.11]),
    ],
)
def test_decimal_rates_pass_through_untouched(parameter, given):
    accepted, warnings = _validate(_arg(parameter, given))
    assert accepted[parameter]["argued_range"] == pytest.approx(given)
    assert not any("interpreted as a percentage" in w for w in warnings)


def test_year_counts_are_not_treated_as_percentages():
    """fade_years=7 means seven years, not 0.07."""
    accepted, _ = _validate(_arg("fade_years", [7, 10]))
    assert accepted["fade_years"]["argued_range"] == [7, 10]


def test_a_genuinely_absurd_rate_is_still_clamped():
    """Normalising must not become a loophole: 5000 -> 50.0 -> clamped to 0.20."""
    accepted, warnings = _validate(_arg("wacc", [5000.0, 5000.0]))
    assert max(accepted["wacc"]["argued_range"]) <= 0.20
    assert any("clamped" in w for w in warnings)


# ── 2. enum shape ───────────────────────────────────────────────────────────

def test_base_fcf_method_accepted_from_argued_range():
    accepted, warnings = _validate(_arg("base_fcf_method", ["avg_3y", "ttm"]))
    assert accepted["base_fcf_method"]["value"] == "avg_3y"
    assert not any("base_fcf_method rejected" in w for w in warnings)


def test_base_fcf_method_prefers_the_normalized_corner():
    """["avg_3y", "ttm"] must not silently collapse to the raw trailing year."""
    accepted, _ = _validate(_arg("base_fcf_method", ["ttm", "mid_cycle"]))
    assert accepted["base_fcf_method"]["value"] == "mid_cycle"


def test_base_fcf_method_still_accepted_as_a_plain_value():
    proposed = {
        "arguments": [
            {
                "parameter": "base_fcf_method",
                "value": "avg_5y",
                "reasoning": "r",
                "evidence": ["canonical_metrics.beta"],
            }
        ]
    }
    accepted, _ = validate_argued_inputs(
        proposed, archetype="general", engine_default=DEFAULTS, state=STATE
    )
    assert accepted["base_fcf_method"]["value"] == "avg_5y"


def test_a_bogus_method_is_still_rejected():
    _, warnings = _validate(_arg("base_fcf_method", ["wishful_thinking", "vibes"]))
    assert any("base_fcf_method rejected" in w for w in warnings)


# ── 3. the judgment case must render ────────────────────────────────────────

def test_judgment_block_shows_the_range_when_point_value_is_none():
    judgment = {
        "fair_value_per_share": None,          # by design
        "fair_value_range": {"low": 180.0, "base": 210.0, "high": 240.0},
        "low_case": {"fair_value_per_share": 180.0, "assumptions": {"wacc": 0.13}},
        "high_case": {"fair_value_per_share": 240.0, "assumptions": {"wacc": 0.11}},
        "band_dissents": [],
        "clamp_warnings": [],
    }
    block = agents._format_judgment_case(judgment)
    assert "180.00" in block and "240.00" in block
    assert "210.00" in block, "the midpoint anchors the range for consumers"


def test_judgment_block_says_so_when_no_value_was_produced():
    """A bank: argued FCF inputs do not apply, and that must be visible."""
    judgment = {
        "fair_value_per_share": None,
        "fair_value_range": None,
        "clamp_warnings": [
            "Argued FCF inputs not applied: the archetype does not use an FCF DCF."
        ],
        "band_dissents": [],
    }
    block = agents._format_judgment_case(judgment)
    assert "No argued fair value produced" in block
    assert "does not use an FCF DCF" in block, "the disclosure must survive"


def test_dissents_are_surfaced_to_the_writer():
    judgment = {
        "fair_value_per_share": None,
        "fair_value_range": {"low": 1.0, "base": 1.5, "high": 2.0},
        "band_dissents": [
            {
                "parameter": "wacc",
                "argued_range": [0.14, 0.14],
                "archetype_band": [0.08, 0.12],
                "reasoning": "demand is a derivative of hyperscaler capex",
            }
        ],
        "clamp_warnings": [],
    }
    block = agents._format_judgment_case(judgment)
    assert "DISSENT wacc" in block and "hyperscaler" in block
