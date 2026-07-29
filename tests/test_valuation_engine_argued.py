from __future__ import annotations

import pytest

from mas_sector_system.valuation_engine import (
    _normalized_base_fcf,
    fcf_history,
    implied_value_from_multiple,
    validate_argued_inputs,
)


def _cell(value):
    return {"value": value}


def _defaults():
    return {
        "assumptions": {
            "wacc": 0.10,
            "g_terminal": 0.025,
            "g_high": 0.08,
            "high_growth_years": 5,
            "fade_years": 5,
        }
    }


def _state():
    return {"business_overview": "Resolvable filing-backed business evidence."}


def _argument(parameter, argued_range):
    return {
        "parameter": parameter,
        "argued_range": argued_range,
        "reasoning": "A specific supported dissent.",
        "evidence": ["business_overview"],
    }


@pytest.mark.parametrize(
    ("parameter", "proposed_range", "expected_range"),
    [
        ("wacc", [0.01, 0.25], [0.05, 0.20]),
        ("g_terminal", [-0.01, 0.05], [0.0, 0.035]),
        ("g_high", [-0.20, 0.50], [-0.10, 0.40]),
        ("high_growth_years", [1, 12], [3, 10]),
        ("fade_years", [1, 12], [2, 10]),
    ],
)
def test_each_static_clamp_boundary(parameter, proposed_range, expected_range):
    accepted, warnings = validate_argued_inputs(
        {"arguments": [_argument(parameter, proposed_range)]},
        archetype="general",
        engine_default=_defaults(),
        state=_state(),
    )

    assert accepted[parameter]["argued_range"] == expected_range
    assert any("clamped" in warning for warning in warnings)


def test_justified_multiple_relative_and_absolute_clamp_boundaries():
    comps = {"peer_medians": {"trailing_pe": 100.0}}
    state = {
        **_state(),
        "comps_engine": comps,
    }
    accepted, warnings = validate_argued_inputs(
        {
            "justified_multiple": {
                "metric": "trailing_pe",
                "argued_range": [1.0, 500.0],
                "reasoning": "Supported multiple range.",
                "evidence": ["comps_engine.peer_medians.trailing_pe"],
            }
        },
        archetype="general",
        engine_default=comps,
        state=state,
    )

    # 0.25x peer median supplies the lower bound; the metric's absolute
    # 150x cap is tighter than the 3.0x peer-median upper bound.
    assert accepted["justified_multiple"]["argued_range"] == [25.0, 150.0]
    assert sum("justified_multiple clamped" in warning for warning in warnings) == 2


def test_g_terminal_respects_wacc_spread_at_joint_boundary():
    accepted, _warnings = validate_argued_inputs(
        {
            "arguments": [
                _argument("wacc", [0.05, 0.06]),
                _argument("g_terminal", [0.035, 0.035]),
            ]
        },
        archetype="general",
        engine_default=_defaults(),
        state=_state(),
    )

    assert accepted["g_terminal"]["argued_range"] == [0.035, 0.035]
    assert accepted["g_terminal"]["argued_range"][0] <= (
        accepted["wacc"]["argued_range"][0] - 0.015
    )


def test_empty_evidence_rejects_and_reverts_to_default():
    argument = _argument("wacc", [0.08, 0.09])
    argument["evidence"] = []

    accepted, warnings = validate_argued_inputs(
        {"arguments": [argument]},
        archetype="general",
        engine_default=_defaults(),
        state=_state(),
    )

    assert "wacc" not in accepted
    assert any("reverted to engine default" in warning for warning in warnings)


def test_unresolvable_evidence_rejects_and_reverts_to_default():
    argument = _argument("wacc", [0.08, 0.09])
    argument["evidence"] = ["balance_sheet.net_debt"]

    accepted, warnings = validate_argued_inputs(
        {"arguments": [argument]},
        archetype="general",
        engine_default=_defaults(),
        state={"balance_sheet": {}},
    )

    assert "wacc" not in accepted
    assert any("unresolvable" in warning for warning in warnings)


def _history_state():
    fcf_values = [90.0, 10.0, -20.0]
    revenues = [500.0, 200.0, 100.0]
    cash_rows = [
        {
            "rank": rank,
            "fy": str(2025 - rank),
            "FreeCashFlow": _cell(fcf),
        }
        for rank, fcf in enumerate(fcf_values)
    ]
    income_rows = [
        {
            "rank": rank,
            "fy": str(2025 - rank),
            "Revenues": _cell(revenue),
        }
        for rank, revenue in enumerate(revenues)
    ]
    return {
        "cash_flow_statement": {
            "current_annual": {"FreeCashFlow": _cell(fcf_values[0])},
            "annual_series": cash_rows,
        },
        "income_statement": {"annual_series": income_rows},
    }


def test_mid_cycle_is_margin_based_and_differs_from_avg_3y():
    state = _history_state()

    avg_value, avg_method, avg_warnings = _normalized_base_fcf(state, "avg_3y")
    mid_value, mid_method, mid_warnings = _normalized_base_fcf(state, "mid_cycle")

    assert avg_method == "avg_3y"
    assert avg_value == pytest.approx(80.0 / 3.0)
    assert avg_warnings == []
    assert mid_method == "mid_cycle"
    # Margins are 18%, 5%, and -20%; median 5% x current revenue 500 = 25.
    assert mid_value == pytest.approx(25.0)
    assert mid_value != pytest.approx(avg_value)
    assert mid_warnings == []


def test_negative_fcf_period_is_retained_in_history_and_average():
    state = _history_state()

    history = fcf_history(state)
    avg_value, method, warnings = _normalized_base_fcf(state, "avg_3y")

    assert [row["fcf"] for row in history] == [90.0, 10.0, -20.0]
    assert avg_value == pytest.approx((90.0 + 10.0 - 20.0) / 3.0)
    assert method == "avg_3y"
    assert warnings == []


def test_null_forward_pe_falls_back_to_trailing_eps():
    result = implied_value_from_multiple(
        metric="forward_pe",
        multiple=25.0,
        comps={
            "subject": {
                "price": 100.0,
                "forward_pe": None,
                "trailing_pe": 20.0,
            }
        },
        state={},
    )

    assert result["forward_estimate_available"] is False
    assert result["estimate_basis"] == "trailing_eps_fallback"
    assert result["estimate_per_share"] == pytest.approx(5.0)
    assert result["implied_value_per_share"] == pytest.approx(125.0)
