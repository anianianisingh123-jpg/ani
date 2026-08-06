import pytest

from mas_sector_system.archetype import ARCHETYPES
from mas_sector_system.driver_templates import (
    DRIVER_TEMPLATES,
    OUTPUT_KINDS,
    band_for_driver,
    drivers_for,
    forecast_output_kind,
    ungrounded_drivers,
)

ARCHETYPE_IDS = {a["id"] if isinstance(a, dict) else a for a in ARCHETYPES}

# The four shapes named in the FWD-01 API contract.
VALID_OUTPUT_KINDS = {"eps_fcf", "ffo", "residual_income", "book_value"}

# Mirrors the per-period metrics forecast_engine.historical_profile() computes.
# A `basis_status: profile` driver naming anything outside this set is claiming a
# history that is not calculated.
PROFILE_METRICS = {
    "revenue_growth", "cagr_3y", "cagr_5y", "gross_margin", "opex_growth",
    "opex_pct_revenue", "capex_pct_revenue", "d_and_a_pct_revenue",
    "working_capital_pct_revenue", "effective_tax_rate", "dividend_payout",
    "share_count_growth", "fcf_conversion",
}


def test_every_archetype_has_a_template():
    assert set(DRIVER_TEMPLATES) == ARCHETYPE_IDS


def test_output_kinds_cover_every_archetype_exactly():
    assert set(OUTPUT_KINDS) == ARCHETYPE_IDS
    assert set(OUTPUT_KINDS.values()) <= VALID_OUTPUT_KINDS


@pytest.mark.parametrize(
    "archetype,expected",
    [
        ("bank_lender", "residual_income"),
        ("insurance", "book_value"),
        ("equity_reit", "ffo"),
        ("reit_real_estate", "ffo"),
        ("mortgage_reit", "book_value"),
    ],
)
def test_financials_never_report_an_earnings_forecast(archetype, expected):
    """The regression this module exists to prevent: a bank handed an EPS forecast."""
    assert forecast_output_kind(archetype) == expected


def test_written_templates_report_their_own_output_kind():
    for archetype, template in DRIVER_TEMPLATES.items():
        assert forecast_output_kind(archetype) == template["output_kind"]


def test_a_bank_has_no_gross_margin_or_opex_dial():
    """Verified live against JPM: no gross profit, cost of revenue or operating
    expense line parses for a bank, so those dials cannot be argued from history."""
    ids = {d["id"] for d in DRIVER_TEMPLATES["bank_lender"]["drivers"]}
    assert "gross_margin" not in ids
    assert "opex_growth" not in ids


def test_drivers_for_flags_a_substituted_template():
    native, is_native = drivers_for("general")
    assert is_native is True
    assert [d["id"] for d in native] == ["segment_growth", "gross_margin", "opex_growth"]

    substituted, is_native = drivers_for("not_a_real_archetype")
    assert is_native is False
    assert [d["id"] for d in substituted] == [d["id"] for d in native]


def test_drivers_for_returns_a_copy_the_caller_cannot_corrupt():
    first, _ = drivers_for("general")
    first[0]["hard_clamp"] = (-99.0, 99.0)
    second, _ = drivers_for("general")
    assert second[0]["hard_clamp"] == (-0.50, 2.00)


def test_hard_clamps_match_the_guardrail_table():
    """§8.1 is the authority on these; the template may not widen them."""
    expected = {
        "segment_growth": (-0.50, 2.00),
        "gross_margin": (0.0, 0.99),
        "opex_growth": (-0.30, 1.50),
        "net_interest_margin": (0.0, 0.15),
        "provision_rate": (0.0, 0.10),
        "combined_ratio": (0.50, 1.50),
        "occupancy": (0.50, 1.00),
        "capex_intensity": (0.0, 0.60),
    }
    for archetype, template in DRIVER_TEMPLATES.items():
        for d in template["drivers"]:
            if d["id"] in expected:
                assert d["hard_clamp"] == expected[d["id"]], (archetype, d["id"])


def test_gross_margin_band_stays_asymmetric():
    """§8.2 allows arguing margin down 1000bps but only up 500bps. Symmetrising it
    loosens the ceiling, which is the direction that inflates a forecast."""
    for archetype, template in DRIVER_TEMPLATES.items():
        if any(d["id"] == "gross_margin" for d in template["drivers"]):
            assert band_for_driver(archetype, "gross_margin") == (-0.10, 0.05)


@pytest.mark.parametrize(
    "driver",
    ["segment_growth", "segment_growth_1", "revenue_growth.data_center", "revenue_growth"],
)
def test_per_segment_driver_names_resolve_to_the_segment_band(driver):
    """§7 names revenue drivers per segment. Every spelling must find a band, or the
    dissent check silently has nothing to test."""
    assert band_for_driver("general", driver) == (-0.5, 0.5)


def test_unknown_driver_has_no_band():
    assert band_for_driver("general", "combined_ratio") is None


def test_substituted_archetype_still_resolves_bands():
    assert band_for_driver("not_a_real_archetype", "gross_margin") == (-0.10, 0.05)


def test_no_driver_is_a_currency_amount():
    """§2 bounds the model's output surface to scalars and enums. Price, ARPU and
    fee dials are therefore expressed as changes, never levels."""
    for archetype, template in DRIVER_TEMPLATES.items():
        for d in template["drivers"]:
            assert d["unit"] in {"rate", "ratio", "multiple"}, (archetype, d["id"])


def test_ratio_dials_cannot_be_argued_negative():
    for archetype, template in DRIVER_TEMPLATES.items():
        for d in template["drivers"]:
            if d["unit"] == "ratio":
                assert d["hard_clamp"][0] >= 0.0, (archetype, d["id"])


def test_every_driver_declares_where_its_history_comes_from():
    """§7's mandatory historical_basis in code: a driver must either name a computed
    series, name the filing lines it can be derived from, or admit it has neither."""
    for archetype, template in DRIVER_TEMPLATES.items():
        for d in template["drivers"]:
            status = d["basis_status"]
            assert status in {"profile", "derivable", "unavailable"}, (archetype, d["id"])
            if status == "profile":
                assert d["basis"] in PROFILE_METRICS, (archetype, d["id"], d["basis"])
            elif status == "derivable":
                assert isinstance(d["basis"], list) and d["basis"], (archetype, d["id"])
            else:
                assert d["basis"] is None, (archetype, d["id"])


def test_ungrounded_drivers_names_the_dials_that_must_be_refused():
    """Verified live against PLD: occupancy, same-store NOI and development yield are
    property-level disclosures absent from the statements we parse."""
    assert set(ungrounded_drivers("equity_reit")) == {
        "occupancy", "same_store_noi_growth", "development_yield"
    }
    assert ungrounded_drivers("equity_reit") == ungrounded_drivers("reit_real_estate")


def test_fully_grounded_archetypes_report_nothing_ungrounded():
    for archetype in ("general", "asset_light", "software_saas", "bank_lender",
                      "insurance", "mortgage_reit", "asset_heavy", "pre_profit_growth"):
        assert ungrounded_drivers(archetype) == [], archetype


def test_template_entry_count_leaves_room_for_segments():
    """§2 caps *runtime* drivers at 4–8, and template entries are not runtime drivers:
    one `segment_growth` entry expands to one driver per reported segment. NVDA's five
    segments (§7) plus the non-segment entries is the binding case."""
    max_segments = 5
    for archetype, template in DRIVER_TEMPLATES.items():
        entries = template["drivers"]
        expands = any(d["id"] == "segment_growth" for d in entries)
        runtime = len(entries) - 1 + max_segments if expands else len(entries)
        assert runtime <= 8, f"{archetype}: {runtime} runtime drivers at {max_segments} segments"


def test_driver_records_are_well_formed():
    required = {"id", "human_label", "unit", "hard_clamp", "history_relative_band",
                "evidence_justification", "basis_status", "basis"}
    for archetype, template in DRIVER_TEMPLATES.items():
        drivers = template["drivers"]
        assert len({d["id"] for d in drivers}) == len(drivers), archetype
        for d in drivers:
            assert required == set(d), (archetype, d.get("id"))
            low, high = d["hard_clamp"]
            assert low < high
            band_low, band_high = d["history_relative_band"]
            assert band_low <= 0 <= band_high
            assert d["evidence_justification"].strip()
            assert d["human_label"].strip()
