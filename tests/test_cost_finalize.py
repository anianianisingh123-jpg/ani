"""Cost finalization must not under-report a run that finalized early.

Background: `validation_halt` calls `finalize_run_cost` and then — because the
three parallel foundation branches never pass through the validation gate —
the graph keeps executing and the remaining nodes run anyway. With a plain
first-wins idempotency flag the JSONL kept only the pre-gate nodes, which
under-reported those runs by roughly two thirds (JPM logged $1.00 across 4
nodes for a run that actually executed all 12).

The contract these tests pin: exactly one line per run, and that line reflects
the most complete view of the run that any finalize saw.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mas_sector_system import cost  # noqa: E402


@pytest.fixture
def log(tmp_path):
    return tmp_path / "cost_log.jsonl"


def _lines(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _summary(ticker, n_nodes, usd):
    return {
        "ticker": ticker,
        "sector": "Financials",
        "mode": "deep_dive",
        "totals": {"total_cost_usd": usd},
        "nodes": [{"node": f"n{i}", "cost_usd": usd / max(n_nodes, 1)}
                  for i in range(n_nodes)],
    }


def test_single_finalize_writes_one_line(log):
    cost.append_cost_log(_summary("AAA", 12, 2.80), path=log)
    assert len(_lines(log)) == 1


def test_rewrite_corrects_in_place_rather_than_appending(log):
    """The halt-then-continue case: 4 nodes logged, then 12 actually ran."""
    cost.append_cost_log(_summary("JPM", 4, 1.00), path=log)
    cost.append_cost_log(_summary("JPM", 12, 2.80), path=log, replace_last=True)

    rows = _lines(log)
    assert len(rows) == 1, "a corrected run must not leave two conflicting lines"
    assert len(rows[0]["nodes"]) == 12
    assert rows[0]["totals"]["total_cost_usd"] == 2.80


def test_rewrite_never_clobbers_a_different_runs_line(log):
    """If the trailing line belongs to another ticker, append instead."""
    cost.append_cost_log(_summary("NVDA", 12, 2.79), path=log)
    cost.append_cost_log(_summary("JPM", 12, 2.80), path=log, replace_last=True)

    rows = _lines(log)
    assert len(rows) == 2
    assert rows[0]["ticker"] == "NVDA"
    assert rows[0]["totals"]["total_cost_usd"] == 2.79, "NVDA must be untouched"
    assert rows[1]["ticker"] == "JPM"


def test_rewrite_on_empty_log_just_writes(log):
    cost.append_cost_log(_summary("JPM", 12, 2.80), path=log, replace_last=True)
    assert len(_lines(log)) == 1


# ── the decision function itself ────────────────────────────────────────────

def test_mark_finalized_write_then_rewrite_then_skip():
    t = cost.begin_run(ticker="JPM", sector="Financials", mode="deep_dive")
    assert t.mark_finalized(4) == "write"       # validation_halt
    assert t.mark_finalized(12) == "rewrite"    # run continued anyway
    assert t.mark_finalized(12) == "skip"       # docx export, no new nodes
    assert t.mark_finalized(3) == "skip"        # never regress to a smaller view


def test_first_finalize_always_writes_even_with_zero_nodes():
    t = cost.begin_run(ticker="AAA")
    assert t.mark_finalized(0) == "write"
    assert t.mark_finalized(0) == "skip"
