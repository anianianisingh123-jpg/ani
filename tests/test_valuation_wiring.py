"""Wiring tests for the argued-input valuation path (VAL-03b / VAL-05b).

These cover the seams the engine's own tests cannot reach: what happens when
the critique LLM misbehaves, and whether doctrine/exemplar selection degrades
the way design §3 requires. No live LLM calls — `_run` is stubbed.

The load-bearing property here is design §9: a failed critique must leave the
run exactly as it was before this feature existed. A valuation must never
hard-fail because the judgment layer did.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mas_sector_system import agents  # noqa: E402
from mas_sector_system.valuation_engine import fcf_history  # noqa: E402


PACKET = "=== PACKET ==="
ENGINE = "=== ENGINE ==="


@pytest.fixture(autouse=True)
def _restore_run():
    """Every test stubs agents._run; put it back afterwards."""
    original = agents._run
    yield
    agents._run = original


def _stub(returns=None, raises=None):
    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return returns
    agents._run = _fake


# ── §9: the critique must never break a run ─────────────────────────────────

@pytest.mark.parametrize(
    "payload",
    [
        "not json at all",
        "",
        "   ",
        "[1, 2, 3]",            # valid JSON, wrong type
        '{"unterminated": ',    # truncated mid-object
    ],
    ids=["prose", "empty", "whitespace", "json-array", "truncated"],
)
def test_unusable_critique_output_returns_none_and_does_not_raise(payload):
    _stub(returns=payload)
    out = agents._run_critique(
        "sys", PACKET, ENGINE, [], archetype="general", label="t"
    )
    assert out is None


def test_critique_call_raising_is_swallowed():
    """A transport/API error must degrade to base-case, not propagate."""
    _stub(raises=RuntimeError("api exploded"))
    out = agents._run_critique(
        "sys", PACKET, ENGINE, [], archetype="general", label="t"
    )
    assert out is None


def test_wellformed_critique_is_parsed_through():
    _stub(returns='{"archetype": "general", "arguments": [], '
                  '"overall_confidence": "moderate"}')
    out = agents._run_critique(
        "sys", PACKET, ENGINE, [], archetype="general", label="t"
    )
    assert isinstance(out, dict)
    assert out["archetype"] == "general"


def test_critique_output_wrapped_in_fences_is_parsed():
    """Models routinely fence JSON; _parse_json_blob must cope."""
    _stub(returns='```json\n{"archetype": "general", "arguments": []}\n```')
    out = agents._run_critique(
        "sys", PACKET, ENGINE, [], archetype="general", label="t"
    )
    assert isinstance(out, dict) and out["archetype"] == "general"


# ── §3: graceful degradation of the ICL stack ───────────────────────────────

def test_icl_blocks_present_for_an_archetype_with_exemplars():
    blocks = agents._icl_blocks("general")
    assert blocks, "general should carry doctrine and exemplars"
    assert any("EXEMPLAR" in b for b in blocks)


def test_icl_blocks_degrade_without_borrowing_another_archetype():
    """A bank must never receive the semis/general exemplars.

    Design §3: fall back to doctrine only. Substituting a mismatched
    archetype's exemplars is worse than having none.
    """
    blocks = agents._icl_blocks("bank_lender")
    assert not any("EXEMPLAR" in b for b in blocks)


def test_unknown_archetype_does_not_raise():
    assert isinstance(agents._icl_blocks("not_a_real_archetype"), list)


# ── archetype sourcing must be single-valued ────────────────────────────────

def test_archetype_prefers_canonical_metrics_over_engine_output():
    """Divergent sources are how a bank gets scored against the general card."""
    state = {"canonical_metrics": {"archetype": "bank_lender"}}
    assert agents._archetype_for(state, {"archetype": "general"}) == "bank_lender"


def test_archetype_falls_back_to_engine_then_general():
    assert agents._archetype_for({}, {"archetype": "equity_reit"}) == "equity_reit"
    assert agents._archetype_for({}, {}) == "general"
    assert agents._archetype_for({}, None) == "general"


def test_archetype_ignores_non_dict_canonical_metrics():
    assert agents._archetype_for({"canonical_metrics": "junk"}, None) == "general"


def test_model_supplied_statements_retain_filing_annual_series(monkeypatch):
    """VAL-12: model statement blocks must not erase XBRL history."""

    def _cell(value):
        return {"value": value}

    income_series = [
        {"rank": rank, "fy": str(2025 - rank), "Revenues": _cell(revenue)}
        for rank, revenue in enumerate((1000.0, 900.0, 800.0))
    ]
    cash_series = [
        {
            "rank": rank,
            "fy": str(2025 - rank),
            "FreeCashFlow": _cell(fcf),
        }
        for rank, fcf in enumerate((200.0, 150.0, 100.0))
    ]
    live = {
        "entity_name": "Fixture Corp",
        "cik": "0000000001",
        "sic": "7372",
        "extraction_archetype": "software_saas",
        "income_statement": {
            "current_annual": {"Revenues": _cell(1000.0)},
            "annual_series": income_series,
        },
        "balance_sheet": {
            "current_annual": {},
            "annual_series": [],
        },
        "cash_flow_statement": {
            "current_annual": {"FreeCashFlow": _cell(200.0)},
            "annual_series": cash_series,
        },
        "live_market": {"price": 100.0},
        "web_research": "",
        "queries_run": [],
        "statements_incomplete": False,
        "statements_error": None,
        "gathered_at_utc": "2026-07-29T00:00:00+00:00",
    }
    model_payload = {
        "sec_filing_summary": "Model-supplied filing summary.",
        "macro_context": "Model-supplied macro context.",
        "income_statement": {
            "current_annual": {"model_marker": True},
            "annual_series": [{"rank": 99, "model_originated": True}],
        },
        "balance_sheet": {
            "current_annual": {"model_marker": True},
        },
        "cash_flow_statement": {
            "current_annual": {"model_marker": True},
            "annual_series": [{"rank": 99, "model_originated": True}],
        },
    }

    monkeypatch.setattr(agents, "gather_live_research_context", lambda **_: live)
    _stub(returns=json.dumps(model_payload))

    result = agents.data_gatherer_node(
        {
            "mode": "deep_dive",
            "query_type": "full_underwrite",
            "ticker": "FIX",
            "sector": "Software",
            "user_query": "Fixture valuation",
        }
    )

    assert result["income_statement"]["current_annual"]["model_marker"] is True
    assert result["cash_flow_statement"]["current_annual"]["model_marker"] is True
    assert result["income_statement"]["annual_series"] == income_series
    assert result["cash_flow_statement"]["annual_series"] == cash_series
    assert len(fcf_history(result)) >= 3
