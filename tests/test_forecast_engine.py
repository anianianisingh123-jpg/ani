import math

import pytest

from mas_sector_system.forecast_engine import (
    build_forecast,
    historical_profile,
    mechanical_defaults,
)


def _cell(value):
    return {"value": value}


@pytest.fixture
def forecast_state():
    revenues = [1000.0, 900.0, 800.0, 700.0, 600.0]
    gross_margins = [0.60, 0.58, 0.56, 0.54, 0.52]
    opex = [300.0, 280.0, 260.0, 240.0, 220.0]
    net_income = [180.0, 160.0, -20.0, 120.0, 100.0]
    taxes = [45.0, 40.0, -5.0, 30.0, 25.0]
    shares = [100.0, 102.0, 104.0, 106.0, 108.0]
    income = []
    balance = []
    cash = []
    for rank, revenue in enumerate(revenues):
        gross_profit = revenue * gross_margins[rank]
        income.append(
            {
                "rank": rank,
                "fy": str(2025 - rank),
                "Revenues": _cell(revenue),
                "GrossProfit": _cell(gross_profit),
                "OperatingIncomeLoss": _cell(gross_profit - opex[rank]),
                "NetIncomeLoss": _cell(net_income[rank]),
                "IncomeTaxExpenseBenefit": _cell(taxes[rank]),
                "WeightedAverageNumberOfDilutedSharesOutstanding": _cell(
                    shares[rank]
                ),
                "segments": {
                    "alpha": _cell(revenue * 0.7),
                    "beta": _cell(revenue * 0.3),
                },
            }
        )
        balance.append(
            {
                "rank": rank,
                "fy": str(2025 - rank),
                "TotalCurrentAssets": _cell(revenue * 0.40),
                "TotalCurrentLiabilities": _cell(revenue * 0.25),
            }
        )
        capex = revenue * 0.05
        fcf = [190.0, 170.0, -30.0, 130.0, 110.0][rank]
        cash.append(
            {
                "rank": rank,
                "fy": str(2025 - rank),
                "CapitalExpenditures": _cell(capex),
                "DepreciationAndAmortization": _cell(revenue * 0.04),
                "NetCashFromOperatingActivities": _cell(fcf + capex),
                "FreeCashFlow": _cell(fcf),
                "DividendsPaid": _cell(20.0),
            }
        )
    return {
        "income_statement": {"annual_series": income},
        "balance_sheet": {"annual_series": balance},
        "cash_flow_statement": {"annual_series": cash},
    }


def test_historical_profile_computes_requested_facts(forecast_state):
    profile = historical_profile(forecast_state)

    assert profile["period_count"] == 5
    assert profile["revenue"]["growth_by_year"][0]["value"] == pytest.approx(
        1000.0 / 900.0 - 1.0
    )
    assert profile["revenue"]["cagr_3y"] == pytest.approx(
        (1000.0 / 800.0) ** 0.5 - 1.0
    )
    assert profile["revenue"]["cagr_5y"] == pytest.approx(
        (1000.0 / 600.0) ** 0.25 - 1.0
    )
    assert profile["gross_margin"]["min"] == pytest.approx(0.52)
    assert profile["gross_margin"]["max"] == pytest.approx(0.60)
    assert profile["gross_margin"]["mean"] == pytest.approx(0.56)
    assert profile["gross_margin"]["trend"] == "increasing"
    assert profile["effective_tax_rate"]["mean_5y"] == pytest.approx(0.20)
    assert profile["capex_pct_revenue"]["mean_5y"] == pytest.approx(0.05)
    assert profile["d_and_a_pct_revenue"]["mean_5y"] == pytest.approx(0.04)
    assert profile["working_capital_pct_revenue"]["mean_5y"] == pytest.approx(
        0.15
    )
    assert profile["share_count"]["trajectory"] == [
        100.0,
        102.0,
        104.0,
        106.0,
        108.0,
    ]
    assert profile["share_count"]["pace"] < 0
    assert profile["share_count"]["implied_buyback_pace"] > 0
    assert profile["periods"][2]["fcf_conversion"] == pytest.approx(1.5)


def test_missing_ranks_are_omitted_and_negative_values_retained(forecast_state):
    for key in ("income_statement", "balance_sheet", "cash_flow_statement"):
        forecast_state[key]["annual_series"] = [
            row
            for row in forecast_state[key]["annual_series"]
            if row["rank"] != 1
        ]

    profile = historical_profile(forecast_state)

    assert [row["rank"] for row in profile["periods"]] == [0, 2, 3, 4]
    assert profile["periods"][1]["free_cash_flow"] == -30.0
    assert profile["periods"][1]["fcf_conversion"] == pytest.approx(1.5)
    assert profile["revenue"]["cagr_3y"] == pytest.approx(
        (1000.0 / 800.0) ** 0.5 - 1.0
    )


def test_mechanical_defaults_are_five_year_profile_values(forecast_state):
    defaults = mechanical_defaults(
        historical_profile(forecast_state), archetype="general"
    )

    assert defaults["archetype"] == "general"
    assert defaults["tax_rate"] == pytest.approx(0.20)
    assert defaults["d_and_a_pct_revenue"] == pytest.approx(0.04)
    assert defaults["capex_pct_revenue"] == pytest.approx(0.05)
    assert defaults["working_capital_pct_revenue"] == pytest.approx(0.15)
    assert defaults["share_count_pace"] == pytest.approx(
        (100.0 / 108.0) ** 0.25 - 1.0
    )
    assert defaults["payout"] == pytest.approx(
        sum((20 / 180, 20 / 160, -1.0, 20 / 120, 20 / 100)) / 5
    )


def test_build_forecast_general_driver_set(forecast_state):
    result = build_forecast(
        forecast_state,
        {
            "segment_growth": {
                "alpha": [0.10, 0.09, 0.08, 0.07, 0.06],
                "beta": 0.05,
            },
            "gross_margin": [0.61, 0.615, 0.62, 0.62, 0.62],
            "opex_growth": 0.06,
        },
        archetype="general",
    )

    assert result["segments_reconciled"] is True
    assert len(result["years"]) == 5
    year1 = result["years"][0]
    assert year1["fy"] == "2026E"
    assert year1["revenue_by_segment"] == pytest.approx(
        {"alpha": 770.0, "beta": 315.0}
    )
    assert year1["revenue"] == pytest.approx(1085.0)
    assert year1["gross_profit"] == pytest.approx(1085.0 * 0.61)
    assert year1["opex"] == pytest.approx(318.0)
    assert year1["operating_income"] == pytest.approx(1085.0 * 0.61 - 318.0)
    assert year1["net_income"] == pytest.approx(
        year1["operating_income"] * 0.80
    )
    assert math.isfinite(year1["eps_diluted"])
    assert year1["d_and_a"] == pytest.approx(1085.0 * 0.04)
    assert year1["capex"] == pytest.approx(1085.0 * 0.05)
    assert year1["delta_working_capital"] == pytest.approx(85.0 * 0.15)
    assert year1["free_cash_flow"] == pytest.approx(
        year1["net_income"]
        + year1["d_and_a"]
        - year1["capex"]
        - year1["delta_working_capital"]
    )


def test_unreconciled_segments_fall_back_to_consolidated(forecast_state):
    latest = forecast_state["income_statement"]["annual_series"][0]
    latest["segments"] = {"alpha": _cell(500.0), "beta": _cell(100.0)}

    result = build_forecast(
        forecast_state,
        {
            "segment_growth": {"consolidated": 0.10},
            "gross_margin": 0.60,
            "opex_growth": 0.05,
        },
        archetype="general",
        years=1,
    )

    assert result["segments_reconciled"] is False
    assert result["years"][0]["revenue_by_segment"] == {
        "consolidated": pytest.approx(1100.0)
    }
    assert any("did not reconcile" in warning for warning in result["warnings"])


def test_missing_segments_use_disclosed_consolidated_fallback(forecast_state):
    forecast_state["income_statement"]["annual_series"][0]["segments"] = {}

    result = build_forecast(
        forecast_state,
        {
            "segment_growth": {"consolidated": 0.10},
            "gross_margin": 0.60,
            "opex_growth": 0.05,
        },
        archetype="general",
        years=1,
    )

    assert result["segments_reconciled"] is False
    assert result["years"][0]["revenue"] == pytest.approx(1100.0)
    assert any("unavailable" in warning for warning in result["warnings"])


def test_missing_filing_derived_default_fails_instead_of_inventing(forecast_state):
    for row in forecast_state["cash_flow_statement"]["annual_series"]:
        row.pop("DepreciationAndAmortization")

    profile = historical_profile(forecast_state)
    assert profile["d_and_a_pct_revenue"]["mean_5y"] is None
    assert "d_and_a_pct_revenue unavailable from annual_series" in profile["warnings"]

    with pytest.raises(ValueError, match="d_and_a_pct_revenue"):
        build_forecast(
            forecast_state,
            {
                "segment_growth": {"alpha": 0.10, "beta": 0.05},
                "gross_margin": 0.60,
                "opex_growth": 0.05,
            },
            archetype="general",
        )
