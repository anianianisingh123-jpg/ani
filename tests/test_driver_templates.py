import pytest

from mas_sector_system.archetype import ARCHETYPES
from mas_sector_system.driver_templates import (
    DRIVER_TEMPLATES,
    OUTPUT_KINDS,
    band_for_driver,
    drivers_for,
    forecast_output_kind,
)

ARCHETYPE_IDS = {a["id"] if isinstance(a, dict) else a for a in ARCHETYPES}

# The four shapes named in the FWD-01 API contract.
VALID_OUTPUT_KINDS = {"eps_fcf", "ffo", "residual_income", "book_value"}


def test_every_template_key_is_a_real_archetype():
    assert set(DRIVER_TEMPLATES) <= ARCHETYPE_IDS


def test_output_kinds_cover_every_archetype_exactly():
    """A missing entry is the silent-wrong-answer case: the lookup would fall through
    to eps_fcf and a bank would be handed an EPS forecast."""
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
    """The regression this module exists to prevent. These five have no driver set
    yet (FWD-01b), so the answer must come from the output map, not the template."""
    assert archetype not in DRIVER_TEMPLATES
    assert forecast_output_kind(archetype) == expected


def test_written_templates_report_their_own_output_kind():
    for archetype, template in DRIVER_TEMPLATES.items():
        assert forecast_output_kind(archetype) == template["output_kind"]


def test_drivers_for_flags_a_substituted_template():
    native, is_native = drivers_for("general")
    assert is_native is True
    assert [d["id"] for d in native] == ["segment_growth", "gross_margin", "opex_growth"]

    substituted, is_native = drivers_for("bank_lender")
    assert is_native is False
    assert [d["id"] for d in substituted] == [d["id"] for d in native]


def test_drivers_for_returns_a_copy_the_caller_cannot_corrupt():
    first, _ = drivers_for("general")
    first[0]["hard_clamp"] = (-99.0, 99.0)
    second, _ = drivers_for("general")
    assert second[0]["hard_clamp"] == (-0.50, 2.00)


def test_hard_clamps_match_the_guardrail_table():
    """§8.1 is the authority on these three; the template may not widen them."""
    expected = {
        "segment_growth": (-0.50, 2.00),
        "gross_margin": (0.0, 0.99),
        "opex_growth": (-0.30, 1.50),
    }
    for template in DRIVER_TEMPLATES.values():
        for d in template["drivers"]:
            if d["id"] in expected:
                assert d["hard_clamp"] == expected[d["id"]], d["id"]


def test_gross_margin_band_stays_asymmetric():
    """§8.2 allows arguing margin down 1000bps but only up 500bps. Symmetrising it
    quietly loosens the ceiling, which is the direction that inflates a forecast."""
    for archetype in DRIVER_TEMPLATES:
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
    assert band_for_driver("bank_lender", "gross_margin") == (-0.10, 0.05)


def test_driver_records_are_well_formed():
    required = {"id", "human_label", "unit", "hard_clamp", "history_relative_band",
                "evidence_justification"}
    for archetype, template in DRIVER_TEMPLATES.items():
        drivers = template["drivers"]
        # §2: a design that needs fifteen drivers is wrong.
        assert len(drivers) <= 8, archetype
        assert len({d["id"] for d in drivers}) == len(drivers), archetype
        for d in drivers:
            assert required <= set(d), (archetype, d.get("id"))
            assert d["unit"] in {"rate", "ratio"}
            low, high = d["hard_clamp"]
            assert low < high
            band_low, band_high = d["history_relative_band"]
            assert band_low <= 0 <= band_high
            assert d["evidence_justification"].strip()
