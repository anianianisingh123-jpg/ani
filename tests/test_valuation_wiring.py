"""Wiring tests for the argued-input valuation path (VAL-03b / VAL-05b).

These cover the seams the engine's own tests cannot reach: what happens when
the critique LLM misbehaves, and whether doctrine/exemplar selection degrades
the way design §3 requires. No live LLM calls — `_run` is stubbed.

The load-bearing property here is design §9: a failed critique must leave the
run exactly as it was before this feature existed. A valuation must never
hard-fail because the judgment layer did.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mas_sector_system import agents  # noqa: E402


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
