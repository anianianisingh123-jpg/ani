"""Unit tests for long-term desk memory (no LLM)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mas_sector_system.memory import (  # noqa: E402
    format_prior_run_for_prompt,
    load_previous_run,
    load_prior_context_for_state,
    save_run,
)


def test_save_and_load_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "mem.sqlite"
        state = {
            "ticker": "NVDA",
            "sector": "Semiconductors",
            "mode": "deep_dive",
            "user_query": "Is NVDA still a buy?",
            "qc_status": "PASS_WITH_FLAGS",
            "final_memo": (
                "Ticker: NVDA | Rating: BUY (sized) | Price Target: $318.63 | "
                "Implied Upside: 62%\n\n"
                "The business is exceptional. live price of 197.20 mentioned here."
            ),
            "styled_memo": "",
            "macro_regime_assessment": "NEUTRAL leaning cautious for long-duration assets.",
            "canonical_metrics": {
                "ticker": "NVDA",
                "archetype": "general",
                "summary": {"metric_count": 2, "applicable_with_value": 2},
                "by_id": {
                    "trailing_pe": {
                        "id": "trailing_pe",
                        "applicable": True,
                        "value": 40.2,
                        "headline": "trailing P/E of 40.2x",
                        "staleness": [],
                    },
                    "market_cap": {
                        "id": "market_cap",
                        "applicable": True,
                        "value": 4.78e12,
                        "headline": "market cap of $4.78T",
                        "staleness": [],
                    },
                },
            },
            "cost_data": {"totals": {"total_cost_usd": 1.23}},
        }
        run_id = save_run(state, db_path=db)
        assert run_id is not None and run_id >= 1

        prior = load_previous_run("NVDA", db_path=db)
        assert prior is not None
        assert prior["ticker"] == "NVDA"
        assert "BUY" in (prior.get("rating") or "")
        assert prior.get("price_target") == "318.63"

        ctx = load_prior_context_for_state(ticker="NVDA", db_path=db)
        assert ctx["prior_run_id"] == run_id
        assert "PRIOR DESK MEMORY" in ctx["prior_run_context"]
        assert "40.2" in ctx["prior_run_context"] or "trailing P/E" in ctx["prior_run_context"]

        # Second save becomes the new "previous" for subsequent loads.
        state2 = dict(state)
        state2["final_memo"] = (
            "Ticker: NVDA | Rating: HOLD | Price Target: $250.00\nSecond memo body."
        )
        state2["qc_status"] = "PASS"
        id2 = save_run(state2, db_path=db)
        assert id2 != run_id
        latest = load_previous_run("nvda", db_path=db)
        assert latest is not None
        assert latest["id"] == id2
        assert "HOLD" in (latest.get("rating") or "")


def test_no_prior_formats_cleanly():
    text = format_prior_run_for_prompt(None)
    assert "No prior deep-dive" in text


def test_missing_ticker_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "mem.sqlite"
        assert load_previous_run(None, db_path=db) is None
        assert load_previous_run("", db_path=db) is None


if __name__ == "__main__":
    test_save_and_load_roundtrip()
    test_no_prior_formats_cleanly()
    test_missing_ticker_returns_none()
    print("OK")
