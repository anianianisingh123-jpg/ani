"""Committed test fixtures (TEST-02).

Why these are in git
--------------------
The recorded state slices used to live only under `outputs/`, which is
gitignored. Every test that needed one carried a `skipif` on the file
existing — so on any machine but the one that produced the runs, ten-plus
tests SKIPPED rather than failed. A fresh clone reported green while the
offline end-to-end harness, the argued-dial correspondence guarantee and the
cyclical method-naming contract had not run at all.

Skips are not passes. A guarantee that only holds on one laptop is not a
guarantee, so the four slices those tests need are committed here (~2.3 MB
total): KO (FCF DCF), JPM (residual income), PLD (FFO/NAV), CVX (cyclical
commodity) — one per valuation path the engine can take.

`state_slice()` still falls back to `outputs/val02_baseline/` so a fuller
local recording set keeps working, and so tickers beyond the committed four
can be pulled in without committing more.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent
SLICES = FIXTURES / "state_slices"
RECORDED = FIXTURES.parent.parent / "outputs" / "val02_baseline"

# Tickers guaranteed to be present in every clone, one per valuation method.
COMMITTED_TICKERS = ("KO", "JPM", "PLD", "CVX")


def state_slice_path(ticker: str) -> Path | None:
    """Committed fixture first, then a local recording. None if neither exists."""
    name = f"{ticker.upper()}_state_slice_fwd_clean.json"
    for candidate in (SLICES / name, RECORDED / name):
        if candidate.exists():
            return candidate
    return None


def agent_prose(ticker: str) -> dict[str, str]:
    """Recorded per-agent output the state slice does not carry.

    A slice has no `bull_thesis` / `bear_thesis` — those live in the run
    database, which is 9 MB and machine-local. Without them the offline
    transcript falls back to placeholder text short enough to trip the
    weak-output retry, so `bull` and `bear` each execute twice and the
    "no node runs twice" guard fires. Committing the prose (63 KB) is what
    lets that test mean the same thing on every machine.

    Returns `{}` when nothing is recorded for the ticker; callers pair this
    with `memory_db` and either source will do.
    """
    path = FIXTURES / "prose" / f"{ticker.upper()}_agent_prose.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def state_slice(ticker: str) -> dict[str, Any]:
    """Load a recorded `ResearchState` slice by ticker.

    Raises rather than returning None: a committed ticker that cannot be found
    is a broken checkout, and silently skipping is the failure mode this
    module exists to remove.
    """
    path = state_slice_path(ticker)
    if path is None:
        raise FileNotFoundError(
            f"no state slice for {ticker}: looked in {SLICES} and {RECORDED}. "
            f"Committed tickers are {COMMITTED_TICKERS}."
        )
    return json.loads(path.read_text())
