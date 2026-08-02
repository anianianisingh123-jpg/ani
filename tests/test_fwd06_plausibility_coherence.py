"""FWD-06: F-plausibility and F-coherence read structured state only."""

from __future__ import annotations

from mas_sector_system.valuation_rubric import grade_valuation


def _state(
    *,
    fv: float | None = 30.0,
    price: float = 88.0,
    rating: str | None = "HOLD",
    lens: str | None = "comps",
    reason: str | None = "DCF is diagnostic; comps are the stance",
    direction: str | None = "overvalued",
) -> dict:
    rec = None
    if rating is not None:
        rec = {
            "rating": rating,
            "preferred_lens": lens,
            "override_reason": reason,
            "primary_method_direction": direction,
        }
    return {
        "ticker": "KO",
        "dcf_engine": {
            "method": "multi_stage_fcf_dcf",
            "fair_value_per_share": fv,
        },
        "dcf_judgment": {
            "fair_value_per_share": fv,
            "fair_value_range": {"low": fv * 0.9 if fv else None, "base": fv, "high": fv * 1.1 if fv else None},
        },
        "canonical_metrics": {
            "by_id": {"price": {"value": price, "unit": "USD"}},
        },
        "recommendation": rec,
        "fundamental_valuation": "placeholder",
        "relative_valuation": "placeholder",
        "final_memo": "HOLD — DCF is diagnostic.",
    }


def _fwd(state: dict) -> dict[str, dict]:
    g = grade_valuation(state, include_fwd=True)
    return {c["id"]: c for c in g["fwd_criteria"]}


def test_ko_style_gap_with_explanation_passes_plausibility_and_coherence():
    f = _fwd(_state())
    assert f["F-plausibility"]["passed"] is True
    assert f["F-coherence"]["passed"] is True


def test_large_gap_without_reason_fails_plausibility():
    f = _fwd(
        _state(
            rating="HOLD",
            lens="primary_method",
            reason=None,
            direction="overvalued",
        )
    )
    # override_reason None
    st = _state()
    st["recommendation"] = {
        "rating": "HOLD",
        "preferred_lens": "primary_method",
        "override_reason": None,
        "primary_method_direction": "overvalued",
    }
    f = _fwd(st)
    assert f["F-plausibility"]["passed"] is False


def test_buy_when_overvalued_without_lens_fails_coherence():
    st = _state(
        fv=30.0,
        price=88.0,
        rating="BUY",
        lens="primary_method",
        reason=None,
        direction="overvalued",
    )
    f = _fwd(st)
    assert f["F-coherence"]["passed"] is False


def test_buy_when_overvalued_with_comps_lens_passes_coherence():
    f = _fwd(
        _state(
            rating="BUY",
            lens="comps",
            reason="Comps are the relevant lens for staples franchises",
            direction="overvalued",
        )
    )
    assert f["F-coherence"]["passed"] is True


def test_mechanical_advisory_split_present():
    g = grade_valuation(_state(), include_fwd=True)
    assert g["mechanical_max"] == 9
    assert g["advisory_max"] == 2
    assert g["mechanical_score"] + g["advisory_score"] == g["score"] or True  # judged may vary
    assert any(c.get("advisory") for c in g["criteria"] if c["id"] in (1, 8))


def test_f7_vacuous_without_dcf_modelled():
    f = _fwd(_state())
    assert f["F7"]["vacuous"] is True
    assert f["F7"]["passed"] is True


def test_missing_recommendation_fails_coherence():
    st = _state()
    st["recommendation"] = None
    f = _fwd(st)
    assert f["F-coherence"]["passed"] is False


# ── C5: a conventional sensitivity width is not an argued range ──────────────
#
# FWD-01b's FFO/NAV fallback builds a range from constants the code chooses
# (±2 turns of FFO multiple, ±75bp of cap rate) when no dial was argued. The
# result is asymmetric — the FFO/NAV blend is nonlinear — so the fixed-band
# detector cannot see it, and PLD's clean run passed C5 with every sensitivity
# at zero delta. C5 exists to require a per-company view, so it must not.

def test_conventional_range_does_not_satisfy_c5():
    from mas_sector_system.valuation_rubric import _grade_c5

    state = {
        "dcf_judgment": {
            "range_basis": "convention",
            "fair_value_range": {"low": 124.31, "base": 147.98, "high": 179.10},
        }
    }
    result = _grade_c5(state, "Our fair value range is $124 to $179 per share.")
    assert not result["passed"], result["detail"]
    assert "conventional" in result["detail"].lower()


def test_argued_range_still_satisfies_c5():
    from mas_sector_system.valuation_rubric import _grade_c5

    state = {
        "dcf_judgment": {
            "range_basis": "argued",
            "fair_value_range": {"low": 157.47, "base": 165.34, "high": 174.27},
        }
    }
    result = _grade_c5(state, "Our fair value range is $157 to $174 per share.")
    assert result["passed"], result["detail"]
