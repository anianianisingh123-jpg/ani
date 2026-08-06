"""The method name must describe what actually ran (VAL-22).

`cycle_normalized_fcf_dcf_placeholder_trailing_base` was emitted for every
cyclical-commodity run. Since 2026-08-03 the base has been margin-normalized
over the filing history, so on any run with history the label was false — and
it is not an internal detail: it reaches `clean_memo.json` and the deck cover,
where "placeholder" tells a reader to discount a number that was computed
properly. On the runs where the base genuinely was trailing, the identical
string gave no way to tell the two cases apart.

Splitting the name creates a second hazard, which the last test here guards:
the argued path gates on the method string, so a rename that misses the gate
silently routes an entire archetype down the non-FCF branch and throws its
critique away.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fixtures import state_slice  # noqa: E402
from mas_sector_system.valuation_engine import (  # noqa: E402
    _FCF_DCF_METHODS,
    compute_dcf_from_state,
)

# Committed fixture (TEST-02) — no skip, so this contract holds on every clone.


def test_no_method_name_claims_to_be_a_placeholder():
    """A shipped artifact should never carry the word `placeholder`."""
    for method in _FCF_DCF_METHODS:
        assert "placeholder" not in method, method


def test_cvx_reports_the_normalization_it_actually_performed():
    result = compute_dcf_from_state(state_slice("CVX"))
    assert result["method"] == "cycle_normalized_fcf_dcf"
    assert result["inputs"]["base_fcf_method"] != "ttm", "name must track the basis used"


def test_the_price_deck_limitation_is_still_disclosed():
    """Renaming must not quietly upgrade the confidence of a commodity name.

    Margin normalization is not price normalization. The honest position is a
    truthful method name *plus* the standing disclosure, not one or the other.
    """
    result = compute_dcf_from_state(state_slice("CVX"))
    assert result["confidence"] == "low"
    assert any(
        "NOT commodity price" in w or "not mid-cycle normalized" in w
        for w in result.get("warnings") or []
    ), result.get("warnings")


def test_a_history_less_commodity_name_is_labelled_trailing():
    """Strip the history and the name must change with it, not stay optimistic."""
    state = state_slice("CVX")
    for key in ("cash_flow_statement", "income_statement"):
        state.setdefault(key, {})["annual_series"] = []
    result = compute_dcf_from_state(state)
    assert result["method"] == "cycle_normalized_fcf_dcf_trailing_base"


def test_every_emitted_cyclical_method_stays_on_the_argued_path():
    """The coupling guard: emitted name ∈ the set the argued gate accepts.

    `compute_dcf_with_argued_inputs` sends anything outside `_FCF_DCF_METHODS`
    to `_compute_non_fcf_with_argued_inputs`, which discards argued FCF dials
    with a clamp warning. A cyclical name landing there loses its whole
    critique — silently, because a discarded argument still returns a result.
    """
    state = state_slice("CVX")
    with_history = compute_dcf_from_state(state)["method"]

    stripped = state_slice("CVX")
    for key in ("cash_flow_statement", "income_statement"):
        stripped.setdefault(key, {})["annual_series"] = []
    without_history = compute_dcf_from_state(stripped)["method"]

    assert with_history != without_history, "the two cases must be distinguishable"
    for method in (with_history, without_history):
        assert method in _FCF_DCF_METHODS, (
            f"{method} is emitted by the engine but is not in _FCF_DCF_METHODS — "
            "argued FCF inputs for this archetype will be silently discarded"
        )
