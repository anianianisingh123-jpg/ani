"""A uniformly conservative argument set is a bias, not a view.

Observed live 2026-07-30 (NVDA, confirming run). The critique moved four
parameters and the one-at-a-time sensitivities came back:

    growth rate        -$145
    discount rate       -$77
    high-growth years   -$63
    fade years          +$37

Not unanimous — fade years pushed the other way — but 89% of the total
movement ran downward, taking fair value from $318.63 to $117.56 with no
single defensible reason accounting for it. Unanimity is therefore the wrong
test; net imbalance is the signal.

The sensitivity deltas already measure this, so the engine flags it and the
writer is told not to present it as high conviction.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mas_sector_system import agents  # noqa: E402


def _judgment(bias):
    return {
        "fair_value_per_share": None,
        "fair_value_range": {"low": 85.37, "base": 117.56, "high": 148.62},
        "sensitivities": [
            {"parameter": "g_high", "engine_default": 0.35, "argued_midpoint": 0.23,
             "fair_value_per_share": 173.46, "delta_vs_default": -145.16},
        ],
        "directional_bias": bias,
        "band_dissents": [],
        "clamp_warnings": [],
    }


def test_one_sided_argument_set_is_flagged_to_the_writer():
    block = agents._format_judgment_case(
        _judgment(
            {"material_arguments": 3, "one_sided": True,
             "dominant_direction": "below default", "dominant_share": 0.89}
        )
    )
    assert "DIRECTIONAL BIAS" in block
    assert "3 material" in block
    assert "below default" in block
    assert "high conviction" in block


def test_balanced_argument_set_is_not_flagged():
    """One or two departures with the rest left alone is a normal view."""
    block = agents._format_judgment_case(
        _judgment({"material_arguments": 3, "one_sided": False,
                   "dominant_direction": "below default", "dominant_share": 0.55})
    )
    assert "DIRECTIONAL BIAS" not in block


def test_absent_bias_block_does_not_break_rendering():
    j = _judgment(None)
    del j["directional_bias"]
    block = agents._format_judgment_case(j)
    assert "ARGUED CENTRAL CASE" in block
    assert "DIRECTIONAL BIAS" not in block


def test_bias_notice_does_not_replace_the_central_case():
    """The number still has to be quoted; the caveat rides alongside it."""
    block = agents._format_judgment_case(
        _judgment(
            {"material_arguments": 4, "one_sided": True,
             "dominant_direction": "below default", "dominant_share": 0.91}
        )
    )
    assert "ARGUED CENTRAL CASE: 117.56" in block
    assert "DIRECTIONAL BIAS" in block


def test_prompt_instructs_against_one_sided_argument_sets():
    """The control is enforced in two places; the prompt is the first."""
    assert "DIRECTION IS NOT A FREE VARIABLE" in agents.CRITIQUE_SYSTEM_PROMPT
    assert "thumb on the scale" in agents.CRITIQUE_SYSTEM_PROMPT
