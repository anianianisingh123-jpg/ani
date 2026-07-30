"""The argued case must headline a coherent central view, not a compounded tail.

Observed live 2026-07-29 (NVDA): sector-default fair value $318.63, argued
"range" $88.24–$146.45. That 72% haircut came from taking the pessimistic end
of five parameters *simultaneously* — WACC up, growth down, high-growth years
shortened, fade lengthened, terminal trimmed. Each choice was individually
defensible; discount-rate and growth effects multiply, so stacking them
produced a spread far wider than the analysis supported.

A memo headlining "$88 vs $318" reads as a screaming sell when what it actually
says is "if five things each go moderately worse at once". So:

  * the headline argued number is the CENTRAL case — every parameter at the
    midpoint of its argued range,
  * the compounded corners are retained but labelled as extremes, and
  * a one-at-a-time sensitivity answers the question a compounded range cannot:
    which assumption actually drives the value.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mas_sector_system import agents  # noqa: E402
from mas_sector_system.valuation_engine import _argued_midpoint  # noqa: E402


def _argued(parameter, lo, hi):
    return {parameter: {"argued_range": [lo, hi]}}


# ── midpoint arithmetic ─────────────────────────────────────────────────────

def test_midpoint_of_a_rate_range():
    assert _argued_midpoint(_argued("wacc", 0.115, 0.135), "wacc", 0.10) == pytest.approx(0.125)


def test_year_counts_round_to_whole_years():
    """You cannot have 3.5 years of high growth in a discrete projection."""
    got = _argued_midpoint(_argued("fade_years", 6, 8), "fade_years", 5)
    assert got == 7 and isinstance(got, int)
    got = _argued_midpoint(_argued("high_growth_years", 3, 4), "high_growth_years", 5)
    assert isinstance(got, int) and got in (3, 4)


def test_missing_or_malformed_argument_falls_back_to_default():
    assert _argued_midpoint({}, "wacc", 0.10) == 0.10
    assert _argued_midpoint({"wacc": {"argued_range": [0.1]}}, "wacc", 0.10) == 0.10
    assert _argued_midpoint({"wacc": {"argued_range": ["x", "y"]}}, "wacc", 0.10) == 0.10


def test_nvdas_live_ranges_produce_sane_midpoints():
    argued = {
        "wacc": {"argued_range": [0.115, 0.135]},
        "g_high": {"argued_range": [0.18, 0.28]},
        "g_terminal": {"argued_range": [0.025, 0.03]},
    }
    assert _argued_midpoint(argued, "wacc", 0.10) == pytest.approx(0.125)
    assert _argued_midpoint(argued, "g_high", 0.35) == pytest.approx(0.23)
    assert _argued_midpoint(argued, "g_terminal", 0.03) == pytest.approx(0.0275)


# ── what the writer is shown ────────────────────────────────────────────────

def _judgment(**over):
    j = {
        "fair_value_per_share": None,
        "fair_value_range": {
            "low": 88.24,
            "base": 210.50,      # central case
            "high": 146.45,
            "basis": "base = central case ...",
        },
        "sensitivities": [
            {"parameter": "wacc", "engine_default": 0.10,
             "argued_midpoint": 0.125, "fair_value_per_share": 250.0,
             "delta_vs_default": -68.63},
            {"parameter": "g_high", "engine_default": 0.35,
             "argued_midpoint": 0.23, "fair_value_per_share": 300.0,
             "delta_vs_default": -18.63},
        ],
        "band_dissents": [],
        "clamp_warnings": [],
    }
    j.update(over)
    return j


def test_central_case_is_the_headline():
    block = agents._format_judgment_case(_judgment())
    assert "ARGUED CENTRAL CASE: 210.50" in block


def test_extremes_are_labelled_as_compounded_not_as_the_range():
    block = agents._format_judgment_case(_judgment())
    assert "Compounded extremes" in block
    assert "not scenarios" in block.lower()
    assert "do not headline" in block.lower()


def test_sensitivity_drivers_are_shown_to_the_writer():
    block = agents._format_judgment_case(_judgment())
    assert "Sensitivity" in block
    assert "wacc" in block and "-68.63" in block


def test_sensitivity_section_omitted_when_absent():
    block = agents._format_judgment_case(_judgment(sensitivities=[]))
    assert "Sensitivity" not in block


def test_no_central_value_still_reports_honestly():
    """Banks: argued FCF inputs do not apply and that must stay visible."""
    block = agents._format_judgment_case(
        {
            "fair_value_per_share": None,
            "fair_value_range": None,
            "sensitivities": [],
            "band_dissents": [],
            "clamp_warnings": [
                "Argued FCF inputs not applied: the archetype does not use an FCF DCF."
            ],
        }
    )
    assert "No argued fair value produced" in block
    assert "does not use an FCF DCF" in block
