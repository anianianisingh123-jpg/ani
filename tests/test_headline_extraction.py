"""The published rating/target must be the desk's view, never an engine figure.

`clean_memo.json` carries `rating` and `price_target`, and `pdf_generator.py`
prints both on the deck cover. Until 2026-08-03 both were regex-scraped from the
recommendation prose with `fair value` in the pattern, so the scrape lifted
deterministic engine output and published it as the analyst's target.

Every case below is taken from the 2026-08-01 eight-name run:

    KO    HOLD  price_target "$24.76"   — the mechanical DCF the memo argues down
    QCOM  HOLD  price_target "$335.83"  — a figure the memo explicitly rejects
    PGR   HOLD  price_target "$132.28"  — the residual-income engine output
    NVDA  BUY   price_target "$192.40"  — a *sensitivity probe* ("move the lever
                                          from 0.35 to 0.25 and fair value falls
                                          to $192.40"), not a target at all

None of those four memos issues a numeric target. The correct answer in all four
is `None`.
"""

import pytest

from mas_sector_system.artifacts import (
    engine_fair_values,
    resolve_headline,
)


def _state(**kwargs):
    base = {"ticker": "TEST", "sector": "Technology"}
    base.update(kwargs)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# The regression cases
# ─────────────────────────────────────────────────────────────────────────────

KO_PROSE = (
    "**HOLD — do not add at $87.59.** The fundamental engine's mechanical DCF "
    "puts fair value at **$24.76/share (range $21.05-$28.48)** against a live "
    "price of 87.59. Even the analyst judgment case only reaches $40.52/share."
)

NVDA_PROSE = (
    "**NVIDIA is an exceptional business trading at a price where the intrinsic "
    "case does not clear.** When you move that single dominant lever from 0.35 "
    "to 0.25 in isolation, fair value falls to $192.40 — again below the live "
    "price."
)


def test_engine_fair_value_in_prose_is_not_published_as_a_target():
    state = _state(dcf_engine={"fair_value_per_share": 24.760912353640027})
    rating, target, source = resolve_headline(state, KO_PROSE)
    assert rating == "HOLD"
    assert target is None, "the mechanical DCF was republished as a desk target"
    assert source == "parsed"


def test_a_sensitivity_probe_is_not_published_as_a_target():
    """NVDA's $192.40 was the value of a one-lever probe, not a view."""
    state = _state(dcf_engine={"fair_value_per_share": 318.62611476243546})
    _, target, _ = resolve_headline(state, NVDA_PROSE)
    assert target is None


def test_bare_fair_value_phrasing_never_yields_a_target():
    """`fair value` is out of the pattern entirely — it describes the engine."""
    _, target, _ = resolve_headline(_state(), "Our fair value is $101.00.")
    assert target is None


def test_an_explicit_target_is_still_extracted():
    """The fix must not make the field permanently null."""
    _, target, source = resolve_headline(
        _state(), "BUY. We set a price target of $250.00 over twelve months."
    )
    assert target == "$250.00"
    assert source == "parsed"

    _, target, _ = resolve_headline(_state(), "HOLD; target price $88.")
    assert target == "$88"


def test_a_target_equal_to_an_engine_figure_is_refused():
    """Belt and braces: the value itself is checked, not only the phrasing.

    A false negative here is acceptable — a null target is recoverable, a
    fabricated one printed on a client cover is not.
    """
    state = _state(
        dcf_engine={"fair_value_per_share": 250.0},
        comps_engine={"implied_value_per_share": 199.0},
    )
    _, target, _ = resolve_headline(state, "price target of $250.00")
    assert target is None
    _, target, _ = resolve_headline(state, "price target of $199.00")
    assert target is None
    _, target, _ = resolve_headline(state, "price target of $260.00")
    assert target == "$260.00"


def test_engine_fair_values_collects_every_deterministic_figure():
    values = engine_fair_values(
        _state(
            dcf_engine={
                "fair_value_per_share": 10.0,
                "epv_per_share": 8.0,
                "fair_value_range": [9.0, 11.0],
            },
            dcf_judgment={"fair_value_per_share": 12.0},
            comps_engine={"implied_value_per_share": 13.0},
        )
    )
    assert sorted(values) == [8.0, 9.0, 10.0, 11.0, 12.0, 13.0]


# ─────────────────────────────────────────────────────────────────────────────
# The structured channel takes precedence
# ─────────────────────────────────────────────────────────────────────────────

def test_structured_recommendation_beats_the_prose_scrape():
    state = _state(
        recommendation={"rating": "buy", "price_target": 275.5},
        dcf_engine={"fair_value_per_share": 318.6},
    )
    rating, target, source = resolve_headline(state, "price target of $999.00")
    assert (rating, target, source) == ("BUY", "$275.50", "structured")


def test_structured_null_target_is_respected_not_backfilled():
    """A desk that declines to issue a target must not have one invented."""
    state = _state(recommendation={"rating": "HOLD", "price_target": None})
    rating, target, source = resolve_headline(state, "price target of $250.00")
    assert rating == "HOLD"
    assert target is None
    assert source == "structured"


def test_empty_recommendation_falls_through_to_prose():
    state = _state(recommendation={})
    rating, target, source = resolve_headline(
        state, "BUY. Price target of $250.00."
    )
    assert (rating, target, source) == ("BUY", "$250.00", "parsed")


def test_no_signal_at_all_reports_none():
    rating, target, source = resolve_headline(_state(), "No view expressed here.")
    assert (rating, target, source) == (None, None, "none")


@pytest.mark.parametrize("raw", ["275.5", "$275.50", 275.5, "1,275.50"])
def test_structured_target_is_normalized_to_a_dollar_string(raw):
    state = _state(recommendation={"rating": "BUY", "price_target": raw})
    _, target, _ = resolve_headline(state, "")
    assert target.startswith("$")
    assert target.replace("$", "").replace(",", "") in {"275.50", "1275.50"}
