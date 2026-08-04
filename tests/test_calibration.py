"""Scoring past calls against realized prices (VAL-07).

The rubric grades how an argument was made. This grades whether it worked. The
scorer is pure — a realized price is passed in, never fetched — so every case
here runs offline.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from mas_sector_system.calibration import (
    Call,
    build_scorecard,
    format_scorecard,
    load_calls,
    normalize_rating,
    score_call,
)

NOW = datetime(2026, 8, 3, tzinfo=timezone.utc)


def _call(direction="BULLISH", price=100.0, *, target=None, engine=False, made_at=None):
    return Call(
        run_id=1,
        ticker="TEST",
        made_at=made_at or (NOW - timedelta(days=30)),
        rating_raw=direction,
        direction=direction,
        price_at_call=price,
        price_target=target,
        target_is_engine_figure=engine,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Reading a free-text rating
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("BUY", "BULLISH"),
        ("BUY (sized as a satellite position)", "BULLISH"),
        ("BUY — satellite", "BULLISH"),
        ("STRONG BUY", "BULLISH"),
        ("accumulate on weakness", "BULLISH"),
        ("HOLD", "NEUTRAL"),
        ("HOLD / TRIM", "NEUTRAL"),
        ("Market Perform", "NEUTRAL"),
        ("SELL", "BEARISH"),
        ("AVOID — do not initiate", "BEARISH"),
        ("", None),
        (None, None),
        ("no view expressed", None),
    ],
)
def test_ratings_are_reduced_to_a_direction(raw, expected):
    """Stored ratings are free text; the direction has to be read out of them."""
    assert normalize_rating(raw) == expected


def test_hold_slash_trim_reads_as_neutral_not_bearish():
    """Order matters: HOLD appears first and is the stance; TRIM is the sizing."""
    assert normalize_rating("HOLD / TRIM") == "NEUTRAL"


# ─────────────────────────────────────────────────────────────────────────────
# Scoring one call
# ─────────────────────────────────────────────────────────────────────────────

def test_a_buy_is_right_when_the_stock_rises_through_the_band():
    assert score_call(_call("BULLISH", 100.0), 110.0, band=0.05).correct
    assert not score_call(_call("BULLISH", 100.0), 103.0, band=0.05).correct
    assert not score_call(_call("BULLISH", 100.0), 90.0, band=0.05).correct


def test_a_sell_is_right_when_the_stock_falls_through_the_band():
    assert score_call(_call("BEARISH", 100.0), 90.0, band=0.05).correct
    assert not score_call(_call("BEARISH", 100.0), 98.0, band=0.05).correct
    assert not score_call(_call("BEARISH", 100.0), 120.0, band=0.05).correct


def test_a_hold_is_right_when_the_stock_goes_nowhere():
    """A HOLD predicts no move, and gets credit when that is what happened."""
    assert score_call(_call("NEUTRAL", 100.0), 102.0, band=0.05).correct
    assert score_call(_call("NEUTRAL", 100.0), 96.0, band=0.05).correct
    assert not score_call(_call("NEUTRAL", 100.0), 130.0, band=0.05).correct
    assert not score_call(_call("NEUTRAL", 100.0), 70.0, band=0.05).correct


def test_the_band_is_a_real_dial():
    call = _call("BULLISH", 100.0)
    assert not score_call(call, 107.0, band=0.10).correct
    assert score_call(call, 107.0, band=0.05).correct


def test_return_and_horizon_are_reported():
    verdict = score_call(
        _call("BULLISH", 100.0, made_at=NOW - timedelta(days=45)),
        125.0,
        realized_at=NOW,
    )
    assert verdict.total_return == pytest.approx(0.25)
    assert verdict.horizon_days == 45
    assert "+25.0%" in verdict.detail


def test_an_unscoreable_call_returns_nothing():
    assert score_call(Call(1, "T", NOW, None, None, 100.0, None), 110.0) is None
    assert score_call(_call("BULLISH", None), 110.0) is None


# ─────────────────────────────────────────────────────────────────────────────
# Target accuracy is secondary, and engine figures are excluded
# ─────────────────────────────────────────────────────────────────────────────

def test_a_genuine_target_is_scored_for_error():
    verdict = score_call(_call("BULLISH", 100.0, target=120.0), 110.0)
    assert verdict.target_error == pytest.approx(110.0 / 120.0 - 1.0)


def test_an_engine_figure_is_never_scored_as_a_target():
    """Grading the engine's own output against the market measures nothing."""
    verdict = score_call(
        _call("BULLISH", 100.0, target=318.63, engine=True), 110.0
    )
    assert verdict.target_error is None
    assert verdict.correct is True  # direction still scores normally


# ─────────────────────────────────────────────────────────────────────────────
# The scorecard, and coverage as a first-class output
# ─────────────────────────────────────────────────────────────────────────────

def test_coverage_counts_and_names_what_could_not_be_scored():
    calls = [
        _call("BULLISH", 100.0),
        _call("NEUTRAL", 100.0),
        Call(3, "TEST", NOW, "", None, 100.0, None),        # no rating
        Call(4, "TEST", NOW, "BUY", "BULLISH", None, None),  # no price at call
        Call(5, "NOPRICE", NOW, "BUY", "BULLISH", 100.0, None),  # no realized px
    ]
    card = build_scorecard(calls, {"TEST": 110.0}, band=0.05)

    assert card.total_calls == 5
    assert card.scored == 2
    assert card.coverage == pytest.approx(0.4)
    assert card.unscoreable["no rating recorded"] == 1
    assert card.unscoreable["no price at call"] == 1
    assert card.no_realized_price == 1


def test_hit_rate_splits_by_direction():
    calls = [_call("BULLISH", 100.0), _call("BULLISH", 100.0), _call("NEUTRAL", 100.0)]
    card = build_scorecard(calls, {"TEST": 110.0}, band=0.05)
    assert card.hits == 2
    assert card.hit_rate == pytest.approx(2 / 3)
    assert card.by_direction() == {"BULLISH": (2, 2), "NEUTRAL": (0, 1)}


def test_an_empty_scorecard_says_so_rather_than_reporting_zero_percent():
    """A hit rate with no denominator is the number that gets a desk in trouble."""
    card = build_scorecard([_call("BULLISH", 100.0)], {}, band=0.05)
    assert card.scored == 0
    assert card.hit_rate is None
    report = format_scorecard(card)
    assert "No call could be scored" in report
    # Coverage may legitimately read 0%; a *hit rate* must not be printed at all.
    assert "Direction hit rate" not in report


def test_the_report_leads_with_coverage():
    card = build_scorecard([_call("BULLISH", 100.0)], {"TEST": 120.0}, band=0.05)
    report = format_scorecard(card)
    assert report.index("Scoreable") < report.index("Direction hit rate")


# ─────────────────────────────────────────────────────────────────────────────
# Reading the real database shape
# ─────────────────────────────────────────────────────────────────────────────

def test_load_calls_reads_the_run_table_and_flags_pre_fix_targets(tmp_path):
    db = tmp_path / "runs.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE runs (id INTEGER PRIMARY KEY, ticker TEXT, created_at TEXT, "
        "rating TEXT, price_target TEXT, live_price TEXT, valuation_json TEXT)"
    )
    conn.executemany(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
        [
            # Pre-VAL-18: the target is a scraped engine figure whatever it says.
            (1, "NVDA", "2026-07-28T03:37:33+00:00", "BUY (satellite)", "318.63",
             "196.51", None),
            # Post-fix with a target that matches the engine block: still excluded.
            (2, "KO", "2026-08-04T00:00:00+00:00", "HOLD", "24.76", "87.59",
             json.dumps({"dcf": {"fair_value_per_share": 24.76}})),
            # Post-fix, genuine desk target.
            (3, "KO", "2026-08-04T00:00:00+00:00", "BUY", "110.00", "87.59",
             json.dumps({"dcf": {"fair_value_per_share": 24.76}})),
        ],
    )
    conn.commit()
    conn.close()

    calls = load_calls(db)
    assert [c.run_id for c in calls] == [1, 2, 3]
    assert calls[0].direction == "BULLISH"
    assert calls[0].price_at_call == pytest.approx(196.51)
    assert calls[0].target_is_engine_figure, "pre-fix targets are prose scrapes"
    assert calls[1].target_is_engine_figure, "matches the engine block exactly"
    assert not calls[2].target_is_engine_figure


def test_load_calls_on_a_missing_database_is_empty_not_an_error(tmp_path):
    assert load_calls(tmp_path / "nope.sqlite") == []
