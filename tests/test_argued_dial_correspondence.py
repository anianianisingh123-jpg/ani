"""No parameter is consumed under a different name than it was argued (VAL-23).

The defect this locks out: `CRITIQUE_SYSTEM_PROMPT` offered six FCF dials to
every archetype, and the engine then reinterpreted `wacc` as `cost_of_equity`
and `g_high` as `plowback` for banks and insurers. The reasoning published to
the reader was about a discount rate; the number computed was a required
equity return. Criterion C2 — every argued input cites resolvable evidence —
passed the whole time, because the evidence did resolve. It was just written
about a different quantity.

The guarantee is correspondence, not merely coverage: the set of dials OFFERED
to the model must equal the set the engine CONSUMES, per method, and a dial
belonging to another model must be dropped and disclosed rather than
translated.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fixtures import state_slice  # noqa: E402
from mas_sector_system.agents import _arguable_dials_block  # noqa: E402
from mas_sector_system.valuation_engine import (  # noqa: E402
    ARGUED_DIAL_DEFINITIONS,
    ARGUED_DIALS_BY_METHOD,
    ARGUED_INPUT_BOUNDS,
    _FCF_DCF_METHODS,
    _non_fcf_ranges,
    argued_dials_for_method,
    compute_dcf_from_state,
    compute_dcf_with_argued_inputs,
)

# Committed fixtures (TEST-02) — these run everywhere, not just on the machine
# that recorded them. One ticker per valuation path.
_TICKERS = {"residual": "JPM", "ffo": "PLD", "fcf": "KO"}


def _state(kind):
    return state_slice(_TICKERS[kind])


def _argue(**dials):
    """Shape a critique the way `_non_fcf_ranges` expects to read it."""
    return {name: {"argued_range": list(rng)} for name, rng in dials.items()}


# ── The correspondence guarantee ────────────────────────────────────────────


def test_every_dial_offered_has_a_definition():
    """A dial named without its meaning is how `wacc` got argued on a bank."""
    for method, dials in ARGUED_DIALS_BY_METHOD.items():
        for dial in dials:
            assert dial in ARGUED_DIAL_DEFINITIONS, f"{method}: {dial} undefined"


def test_every_dial_offered_has_enforceable_bounds():
    """An offered dial with no bound cannot be clamped, so it cannot be trusted."""
    for method, dials in ARGUED_DIALS_BY_METHOD.items():
        for dial in dials:
            if dial == "base_fcf_method":
                continue  # enum, validated separately
            assert dial in ARGUED_INPUT_BOUNDS, f"{method}: {dial} has no bounds"


def test_every_fcf_method_is_offered_the_fcf_dials():
    for method in _FCF_DCF_METHODS:
        assert argued_dials_for_method(method), f"{method} offers nothing"


def test_an_unknown_method_offers_nothing_rather_than_defaulting_to_fcf():
    """Silently defaulting to the FCF six is the original bug's mechanism."""
    assert argued_dials_for_method("some_future_model") == ()
    assert argued_dials_for_method(None) == ()
    assert _arguable_dials_block("some_future_model") == ""


def test_the_prompt_block_names_exactly_the_consumed_dials():
    """What the model is told it may argue == what the engine will apply."""
    for method, dials in ARGUED_DIALS_BY_METHOD.items():
        block = _arguable_dials_block(method)
        for dial in dials:
            assert f"- {dial}:" in block, f"{method}: {dial} not offered"
        for other in set(ARGUED_DIAL_DEFINITIONS) - set(dials):
            assert f"- {other}:" not in block, (
                f"{method} offers {other}, which it does not consume"
            )


def test_a_bank_is_never_offered_a_wacc():
    """The specific mismatch that shipped: JPM reasoned about a WACC."""
    block = _arguable_dials_block("excess_return_on_equity")
    assert "- cost_of_equity:" in block
    assert "- wacc:" not in block
    assert "NOT a WACC" in block, "the definition must say what it is not"


def test_a_reit_is_offered_its_own_dials():
    """REITs previously had no shim at all, so every range fell to `convention`."""
    block = _arguable_dials_block("ffo_nav")
    for dial in ("ffo_multiple", "cap_rate", "nav_discount"):
        assert f"- {dial}:" in block
    assert "- g_high:" not in block


# ── The shim is gone, and its absence is disclosed ─────────────────────────


def test_wacc_argued_on_a_bank_is_dropped_and_disclosed_not_renamed():
    base = compute_dcf_from_state(_state("residual"))
    assert base["method"] == "excess_return_on_equity"

    defaults, ranges, warnings, basis = _non_fcf_ranges(
        base, _argue(wacc=[0.09, 0.105])
    )
    assert "cost_of_equity" not in ranges, (
        "a WACC argument must not become a cost-of-equity range — that is the "
        "deleted shim"
    )
    assert basis == "convention", "nothing native was argued, so nothing is argued"
    assert any("were not applied" in w and "wacc" in w for w in warnings), warnings


def test_g_high_argued_on_a_bank_does_not_become_plowback():
    base = compute_dcf_from_state(_state("residual"))
    _, ranges, warnings, _ = _non_fcf_ranges(base, _argue(g_high=[0.04, 0.08]))
    assert "plowback" not in ranges, "the g_high → plowback shim must be gone"
    assert any("g_high" in w for w in warnings), warnings


def test_native_bank_dials_are_applied_and_move_the_answer():
    """Correspondence has to cut both ways: the right dial must actually work."""
    state = _state("residual")
    base = compute_dcf_from_state(state)
    defaults, ranges, _, basis = _non_fcf_ranges(
        base, _argue(cost_of_equity=[0.09, 0.105])
    )
    assert ranges["cost_of_equity"] == [0.09, 0.105]
    assert basis == "argued"

    argued = compute_dcf_with_argued_inputs(state, _argue(cost_of_equity=[0.09, 0.105]))
    assert argued.get("input_source") == "argued"


def test_sustainable_roe_is_arguable_now_that_it_is_normalized():
    """VAL-21 made the default mid-cycle; VAL-23 lets a desk argue it."""
    base = compute_dcf_from_state(_state("residual"))
    _, ranges, _, basis = _non_fcf_ranges(base, _argue(sustainable_roe=[0.14, 0.18]))
    assert ranges["sustainable_roe"] == [0.14, 0.18]
    assert basis == "argued"


def test_a_reit_can_finally_produce_an_argued_range():
    """Before VAL-23 no FFO/NAV dial was ever offered, so PLD could not argue."""
    base = compute_dcf_from_state(_state("ffo"))
    assert base["method"] == "ffo_nav"
    _, ranges, _, basis = _non_fcf_ranges(base, _argue(cap_rate=[0.045, 0.055]))
    assert ranges["cap_rate"] == [0.045, 0.055]
    assert basis == "argued", "a REIT range must no longer be stuck at `convention`"


def test_fcf_dials_on_a_reit_are_dropped_and_disclosed():
    """The REIT branch still emits conventional widths — but never calls them argued.

    `ranges` is non-empty here by design: with no native dial accepted the
    branch produces market-anchored cases at conventional widths (±2 turns,
    ±75bp). The guarantee under test is the label, not the emptiness — the
    basis stays `convention`, so `_substantive_engine_range` will not let it
    satisfy the "expressed as a range" criterion, and the dropped `wacc` is
    disclosed rather than absorbed into one of those widths.
    """
    base = compute_dcf_from_state(_state("ffo"))
    _, ranges, warnings, basis = _non_fcf_ranges(base, _argue(wacc=[0.07, 0.09]))
    assert basis == "convention", "a dropped FCF dial must not upgrade the basis"
    assert set(ranges) <= set(ARGUED_DIALS_BY_METHOD["ffo_nav"]), (
        f"a non-FFO dial leaked into the REIT ranges: {sorted(ranges)}"
    )
    assert any("were not applied" in w and "wacc" in w for w in warnings), warnings
    assert any("not an argued view" in w for w in warnings), warnings


def test_the_fcf_path_still_consumes_its_own_dials():
    """Guard against the fix breaking the archetypes that were already right."""
    state = _state("fcf")
    base = compute_dcf_from_state(state)
    assert base["method"] in _FCF_DCF_METHODS
    argued = compute_dcf_with_argued_inputs(state, _argue(wacc=[0.085, 0.095]))
    assert argued.get("input_source") == "argued"
