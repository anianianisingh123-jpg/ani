"""Guards on annual-period selection and the cash-flow concept map.

The forward-estimate epic assumes `annual_series` holds five *distinct* fiscal
years. It did not: filers report each period twice — once as its own fiscal year,
then again as the prior-year comparative in the following 10-K under a different
`fy` stamp — and the de-duplication signature included `fy`, so both copies
survived. Ranks 0-4 held three real years with two counted twice, which silently
halves every mean, CAGR and trend a forecast is built on.
"""

from mas_sector_system.concept_maps import (
    BANK_CASHFLOW,
    GENERAL_CASHFLOW,
    INSURANCE_CASHFLOW,
    MREIT_CASHFLOW,
    REIT_CASHFLOW,
)
from mas_sector_system.tools import extract_statements_from_company_facts


def _obs(end, val, fy, filed):
    return {"form": "10-K", "fp": "FY", "end": end, "val": val, "fy": fy, "filed": filed}


def _facts_with_restated_comparatives():
    """Five fiscal years, each also republished as the next year's comparative."""
    years = [
        ("2026-01-25", 5000.0, 2026, "2026-02-20"),
        ("2025-01-26", 4000.0, 2025, "2025-02-20"),
        ("2024-01-28", 3000.0, 2024, "2024-02-20"),
        ("2023-01-29", 2000.0, 2023, "2023-02-20"),
        ("2022-01-30", 1000.0, 2022, "2022-02-20"),
    ]
    series = []
    for i, (end, val, fy, filed) in enumerate(years):
        series.append(_obs(end, val, fy, filed))
        if i + 1 < len(years):
            # The same period as it appears inside the *next* year's filing.
            nxt = years[i - 1] if i else years[0]
            series.append(_obs(end, val, fy + 1, nxt[3]))
    return {
        "cik": "0000000000",
        "entityName": "Fixture Co",
        "facts": {
            "us-gaap": {
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": series}},
                "DepreciationDepletionAndAmortization": {"units": {"USD": series}},
            }
        },
    }


def _annual_ends(statement, label):
    ends = []
    for period in statement.get("annual_series") or []:
        cell = period.get(label) or {}
        ends.append(cell.get("period_end") or cell.get("end"))
    return ends


def test_annual_ranks_are_five_distinct_years():
    st = extract_statements_from_company_facts(
        _facts_with_restated_comparatives(), archetype="general"
    )
    ends = _annual_ends(st["cash_flow_statement"], "NetCashFromOperatingActivities")
    assert len(ends) == 5
    assert len(set(ends)) == 5, f"duplicated fiscal years in annual_series: {ends}"
    assert ends == sorted(ends, reverse=True), "annual_series must be newest-first"


def test_restated_comparative_does_not_displace_an_older_year():
    """The regression in its original form: the oldest year fell off the end
    because a duplicate of a recent year occupied its rank."""
    st = extract_statements_from_company_facts(
        _facts_with_restated_comparatives(), archetype="general"
    )
    ends = _annual_ends(st["cash_flow_statement"], "NetCashFromOperatingActivities")
    assert "2022-01-30" in ends


def test_every_cashflow_map_carries_depreciation():
    """`forecast_engine` requires d_and_a_pct_revenue and has no fallback, so a
    map without this line cannot produce a forecast for that company type."""
    for name, cmap in (
        ("general", GENERAL_CASHFLOW),
        ("bank", BANK_CASHFLOW),
        ("insurance", INSURANCE_CASHFLOW),
        ("reit", REIT_CASHFLOW),
        ("mortgage_reit", MREIT_CASHFLOW),
    ):
        assert "DepreciationAndAmortization" in cmap, name


def test_depreciation_aliases_are_total_measures_only():
    """Aliases are merged, not tried in order, so a PP&E-only `Depreciation` tag
    could win a period and understate the add-back."""
    assert "Depreciation" not in GENERAL_CASHFLOW["DepreciationAndAmortization"]


def test_depreciation_extracts_across_all_ranks():
    st = extract_statements_from_company_facts(
        _facts_with_restated_comparatives(), archetype="general"
    )
    values = [
        (p.get("DepreciationAndAmortization") or {}).get("value")
        for p in st["cash_flow_statement"]["annual_series"]
    ]
    assert values == [5000.0, 4000.0, 3000.0, 2000.0, 1000.0]
