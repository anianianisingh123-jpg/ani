"""The core-metric gate must not punish an archetype for being itself.

`archetype.py::_SUPPRESS_PREFIXES` deliberately marks `gross_margin` as
not-applicable for `bank_lender` (a bank has no cost of goods sold, so a gross
margin is meaningless, not missing). The coverage check previously treated
`applicable is False` identically to `value is None` and emitted
"Core metrics missing: gross_margin__current_annual" — failing validation for
every bank, insurer and REIT for behaving exactly as designed.

Observed live: JPM 2026-07-29, `validation status=FAIL ... failures=1
archetype=bank_lender`, the single failure being that message.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mas_sector_system.validate import validate_inputs  # noqa: E402


def _metric(mid, value, applicable=True):
    return {"id": mid, "value": value, "applicable": applicable, "staleness": []}


def _state(metrics, *, archetype):
    """Minimal state carrying only what the core-coverage check reads.

    `get_metric` resolves through `canonical_metrics["by_id"]`, and the market
    gate reads `live_market` off a statement block — both are required or the
    run fails for unrelated reasons and the core check never gets exercised.
    """
    return {
        "ticker": "TEST",
        "sector": "Financials",
        "canonical_metrics": {
            "archetype": archetype,
            "metrics": metrics,
            "by_id": {m["id"]: m for m in metrics},
            "summary": {"applicable_with_value": 20},
        },
        "income_statement": {
            "current_annual": {"Revenues": {"value": 1.0e11}},
            "live_market": {"price": 250.0, "market_cap": 6.0e11},
        },
        "balance_sheet": {"current_annual": {}},
        "cash_flow_statement": {"current_annual": {}},
    }


def _core_failures(report):
    return [f for f in (report.get("failures") or []) if "Core metrics missing" in f]


def _check(report, name):
    return next(
        (c for c in (report.get("checks") or []) if c.get("name") == name), None
    )


def test_bank_is_not_failed_for_a_suppressed_gross_margin():
    report = validate_inputs(
        _state(
            [
                _metric("market_cap", 6.0e11),
                _metric("revenue__current_annual", 1.8e11),
                _metric("gross_margin__current_annual", None, applicable=False),
            ],
            archetype="bank_lender",
        )
    )
    assert not _core_failures(report), (
        "a suppressed metric is not missing data: " f"{report.get('failures')}"
    )


def test_the_exclusion_is_recorded_rather_than_silent():
    """A compliance log should show the gate reasoned about it, not skipped it."""
    report = validate_inputs(
        _state(
            [
                _metric("market_cap", 6.0e11),
                _metric("revenue__current_annual", 1.8e11),
                _metric("gross_margin__current_annual", None, applicable=False),
            ],
            archetype="bank_lender",
        )
    )
    c = _check(report, "metrics_core_not_applicable")
    assert c is not None and c.get("status") == "PASS"
    assert "gross_margin__current_annual" in (c.get("detail") or "")


def test_genuinely_missing_core_metric_still_fails():
    """The gate must keep its teeth for real data loss."""
    report = validate_inputs(
        _state(
            [
                _metric("market_cap", None),          # applicable, no value
                _metric("revenue__current_annual", 1.8e11),
                _metric("gross_margin__current_annual", 0.6),
            ],
            archetype="general",
        )
    )
    failures = _core_failures(report)
    assert failures, "an applicable-but-empty core metric must still fail"
    assert "market_cap" in failures[0]


def test_commercial_company_still_requires_gross_margin():
    """The exclusion is archetype-driven, not a blanket softening."""
    report = validate_inputs(
        _state(
            [
                _metric("market_cap", 6.0e11),
                _metric("revenue__current_annual", 1.8e11),
                _metric("gross_margin__current_annual", None),  # applicable, empty
            ],
            archetype="general",
        )
    )
    failures = _core_failures(report)
    assert failures and "gross_margin__current_annual" in failures[0]
