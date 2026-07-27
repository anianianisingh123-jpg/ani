"""Offline tests for free options/insider → canonical metrics mapping."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mas_sector_system.metrics import compute_canonical_metrics, get_metric  # noqa: E402


def test_options_and_insider_metrics_fold_into_canonical():
    options = {
        "applicable": True,
        "as_of_utc": "2026-07-27T00:00:00+00:00",
        "put_call_volume_ratio": 0.85,
        "put_call_oi_ratio": 0.9,
        "put_volume": 8500,
        "call_volume": 10000,
        "option_volume_to_oi": 0.6,
        "unusual_volume_flag": True,
        "expiries_used": ["2026-08-01"],
        "error": None,
    }
    insider = {
        "applicable": True,
        "as_of_utc": "2026-07-27T00:00:00+00:00",
        "net_shares_heuristic": -120000.0,
        "yfinance_row_count": 10,
        "form4_recent_count": 5,
        "latest_form4_date": "2026-07-15",
        "sec_form4": {"error": None},
        "yfinance": {
            "open_market_buys_shares": 0.0,
            "open_market_sells_shares": 120000.0,
        },
        "error": None,
    }
    cm = compute_canonical_metrics(
        income_statement={},
        balance_sheet={},
        cash_flow_statement={},
        live_market={"price": 100.0, "market_cap": 1e12},
        ticker="NVDA",
        sector="Semiconductors",
        options_flow=options,
        insider_alerts=insider,
    )
    pc = get_metric(cm, "options_put_call_volume_ratio__live")
    assert pc and pc.get("applicable") and abs(pc["value"] - 0.85) < 1e-9
    assert "free proxy" in (pc.get("headline") or "").lower() or "yfinance" in (
        pc.get("headline") or ""
    ).lower()

    flag = get_metric(cm, "options_unusual_volume_flag__live")
    assert flag and flag.get("applicable") and flag.get("value") == 1.0

    net = get_metric(cm, "insider_net_shares_heuristic__live")
    assert net and net.get("applicable") and net.get("value") == -120000.0
    assert "heuristic" in (net.get("headline") or "").lower()

    f4 = get_metric(cm, "insider_form4_recent_count__live")
    assert f4 and f4.get("applicable") and f4.get("value") == 5.0


def test_missing_market_structure_yields_unavailable():
    cm = compute_canonical_metrics(
        income_statement={},
        balance_sheet={},
        cash_flow_statement={},
        live_market={"price": 10.0, "market_cap": 1e9},
        ticker="TEST",
        options_flow={"applicable": False, "error": "No option expiries"},
        insider_alerts={"applicable": False, "error": "empty"},
    )
    pc = get_metric(cm, "options_put_call_volume_ratio__live")
    assert pc is not None
    assert not pc.get("applicable")


if __name__ == "__main__":
    test_options_and_insider_metrics_fold_into_canonical()
    test_missing_market_structure_yields_unavailable()
    print("OK")
