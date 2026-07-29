"""Cheap structural regression suite (Phases 1–5).

No full LLM deep dives. Asserts on:
  - metrics contract
  - archetype classification + suppression
  - valuation dispatch (no FCF DCF for banks)
  - peer archetype matching
  - validation gate
  - query routing
  - basis_period present on every metric

Run: python -m pytest tests/test_structural_phases.py -q
  or: python tests/test_structural_phases.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mas_sector_system.archetype import (  # noqa: E402
    apply_archetype_to_metrics,
    classify_archetype,
    filter_peers_by_archetype,
    peers_for_archetype,
    valuation_method_for_archetype,
)
from mas_sector_system.metrics import compute_canonical_metrics, get_metric  # noqa: E402
from mas_sector_system.routing import classify_query, agents_for_query_type  # noqa: E402
from mas_sector_system.validate import validate_inputs  # noqa: E402
from mas_sector_system.valuation_engine import (  # noqa: E402
    compute_dcf_from_state,
    fetch_peer_multiples,
)


def _line(v, **meta):
    d = {"value": v, "end": meta.get("end", "2026-01-01"), "fy": meta.get("fy", 2025), "fp": meta.get("fp", "FY"), "form": meta.get("form", "10-K"), "filed": meta.get("filed", "2026-02-01"), "note": meta.get("note")}
    return d


def _synthetic_industrial():
    """Minimal NVDA-like statements for offline tests."""
    income = {
        "current_annual": {
            "Revenues": _line(200e9, end="2026-01-25", fy=2026),
            "GrossProfit": _line(140e9, end="2026-01-25", fy=2026),
            "OperatingIncomeLoss": _line(100e9, end="2026-01-25", fy=2026),
            "NetIncomeLoss": _line(80e9, end="2026-01-25", fy=2026),
            "EarningsPerShareDiluted": _line(3.0, end="2026-01-25", fy=2026),
            "WeightedAverageNumberOfDilutedSharesOutstanding": _line(25e9, end="2026-01-25", fy=2026),
            "ResearchAndDevelopmentExpense": _line(10e9, end="2026-01-25", fy=2026),
            "live_market": {
                "price": 200.0,
                "market_cap": 5e12,
                "shares_outstanding": 25e9,
            },
        },
        "prior_annual": {
            "Revenues": _line(120e9, end="2025-01-26", fy=2025),
            "GrossProfit": _line(80e9, end="2025-01-26", fy=2025),
            "OperatingIncomeLoss": _line(50e9, end="2025-01-26", fy=2025),
            "NetIncomeLoss": _line(40e9, end="2025-01-26", fy=2025),
            "WeightedAverageNumberOfDilutedSharesOutstanding": _line(25.3e9, end="2025-01-26", fy=2025),
        },
        "current_quarter": {
            "Revenues": _line(50e9, end="2026-04-26", fy=2027, fp="Q1", form="10-Q"),
            "NetIncomeLoss": _line(20e9, end="2026-04-26", fy=2027, fp="Q1", form="10-Q"),
        },
        "prior_quarter": {
            "Revenues": _line(45e9, end="2026-01-26", fy=2026, fp="Q4", form="10-Q"),
            "NetIncomeLoss": _line(18e9, end="2026-01-26", fy=2026, fp="Q4", form="10-Q"),
        },
    }
    balance = {
        "current_annual": {
            "CashAndCashEquivalents": _line(10e9, end="2026-01-25"),
            "ShortTermInvestments": _line(30e9, end="2025-01-26"),  # intentionally older → stale
            "ShortTermDebt": _line(1e9, end="2026-01-25"),
            "LongTermDebt": _line(7e9, end="2026-01-25"),
            "TotalAssets": _line(100e9, end="2026-01-25"),
            "TotalLiabilities": _line(40e9, end="2026-01-25"),
            "StockholdersEquity": _line(60e9, end="2026-01-25"),
            "TotalCurrentAssets": _line(50e9, end="2026-01-25"),
            "TotalCurrentLiabilities": _line(20e9, end="2026-01-25"),
            "Inventory": _line(5e9, end="2026-01-25"),
            "AccountsReceivable": _line(8e9, end="2026-01-25"),
            "Goodwill": _line(4e9, end="2026-01-25"),
            "live_market": income["current_annual"]["live_market"],
        },
        "prior_annual": {
            "CashAndCashEquivalents": _line(8e9, end="2025-01-26"),
            "ShortTermInvestments": _line(20e9, end="2025-01-26"),
            "ShortTermDebt": _line(1e9, end="2025-01-26"),
            "LongTermDebt": _line(7e9, end="2025-01-26"),
            "TotalAssets": _line(80e9, end="2025-01-26"),
            "StockholdersEquity": _line(50e9, end="2025-01-26"),
            "Inventory": _line(3e9, end="2025-01-26"),
            "AccountsReceivable": _line(6e9, end="2025-01-26"),
            "Goodwill": _line(2e9, end="2025-01-26"),
        },
        "current_quarter": {},
        "prior_quarter": {},
    }
    cash = {
        "current_annual": {
            "NetCashFromOperatingActivities": _line(90e9, end="2026-01-25"),
            "CapitalExpenditures": _line(5e9, end="2026-01-25"),
            "FreeCashFlow": _line(85e9, end="2026-01-25"),
            "StockRepurchases": _line(40e9, end="2026-01-25"),
            "DividendsPaid": _line(1e9, end="2026-01-25"),
        },
        "prior_annual": {
            "NetCashFromOperatingActivities": _line(50e9, end="2025-01-26"),
            "CapitalExpenditures": _line(3e9, end="2025-01-26"),
            "FreeCashFlow": _line(47e9, end="2025-01-26"),
            "StockRepurchases": _line(30e9, end="2025-01-26"),
            "DividendsPaid": _line(0.8e9, end="2025-01-26"),
        },
        "current_quarter": {
            "FreeCashFlow": _line(20e9, end="2026-04-26", fp="Q1", form="10-Q"),
        },
        "prior_quarter": {},
    }
    return income, balance, cash


def _synthetic_bank():
    income, balance, cash = _synthetic_industrial()
    # Banks: huge assets, modest "debt" tags, positive NI
    balance["current_annual"]["TotalAssets"] = _line(4e12, end="2026-01-25")
    balance["current_annual"]["StockholdersEquity"] = _line(3e11, end="2026-01-25")
    balance["current_annual"]["TotalLiabilities"] = _line(3.7e12, end="2026-01-25")
    balance["current_annual"]["CashAndCashEquivalents"] = _line(5e11, end="2026-01-25")
    balance["current_annual"]["ShortTermDebt"] = _line(1e10, end="2026-01-25")
    balance["current_annual"]["LongTermDebt"] = _line(2e10, end="2026-01-25")
    return income, balance, cash


# ── Golden expectations ─────────────────────────────────────────────────────

GOLDEN = [
    {"ticker": "NVDA", "sector": "Semiconductors", "expect_archetype": "general"},
    {"ticker": "JPM", "sector": "Financials Banks", "expect_archetype": "bank_lender"},
    {"ticker": "PLD", "sector": "REIT Real Estate", "expect_archetype": "equity_reit"},
    {"ticker": "JNJ", "sector": "Healthcare", "expect_archetype": "mature_dividend_payer"},
    {"ticker": "PLTR", "sector": "Software", "expect_archetype": "pre_profit_growth"},
    {"ticker": "XOM", "sector": "Energy Oil", "expect_archetype": "cyclical_commodity"},
    {"ticker": "TSM", "sector": "Semiconductors", "expect_archetype": "general"},  # foreign filer → general
]


def test_archetype_golden_tickers():
    for g in GOLDEN:
        clf = classify_archetype(ticker=g["ticker"], sector=g["sector"])
        assert clf["archetype"] == g["expect_archetype"], (
            f"{g['ticker']}: got {clf['archetype']} reasons={clf['reasons']}"
        )


def test_metrics_have_basis_period_and_headline():
    income, balance, cash = _synthetic_industrial()
    cm = compute_canonical_metrics(
        income_statement=income,
        balance_sheet=balance,
        cash_flow_statement=cash,
        live_market=income["current_annual"]["live_market"],
        ticker="NVDA",
        sector="Semiconductors",
    )
    assert cm.get("metrics")
    for m in cm["metrics"]:
        assert "basis_period" in m, m.get("id")
        assert "headline" in m and m["headline"], m.get("id")
        assert "applicable" in m


def test_buyback_dollars_per_pp_not_wrong_magnitude():
    income, balance, cash = _synthetic_industrial()
    cm = compute_canonical_metrics(
        income_statement=income,
        balance_sheet=balance,
        cash_flow_statement=cash,
        live_market=income["current_annual"]["live_market"],
        ticker="NVDA",
        sector="Semiconductors",
    )
    bb = get_metric(cm, "buyback_dollars_per_pct_point__current_annual_vs_prior_annual")
    assert bb and bb.get("applicable")
    # 40B spend / ~1.186 pp ≈ 33.7B per pp — not 3.3B
    assert bb["value"] > 1e10, bb
    assert "single annual pair" in bb["headline"]


def test_net_cash_both_bases_labeled():
    income, balance, cash = _synthetic_industrial()
    cm = compute_canonical_metrics(
        income_statement=income,
        balance_sheet=balance,
        cash_flow_statement=cash,
        live_market=income["current_annual"]["live_market"],
        ticker="NVDA",
        sector="Semiconductors",
    )
    ex = get_metric(cm, "net_cash_ex_st_investments__current_annual")
    inc = get_metric(cm, "net_cash_incl_st_investments__current_annual")
    assert ex and ex["applicable"]
    assert "EXCLUDES" in ex["headline"]
    assert inc and inc["applicable"]
    assert "incl" in inc["headline"].lower() or "ST investments" in inc["headline"]


def test_bank_suppresses_net_cash_and_no_fcf_dcf():
    income, balance, cash = _synthetic_bank()
    cm = compute_canonical_metrics(
        income_statement=income,
        balance_sheet=balance,
        cash_flow_statement=cash,
        live_market=income["current_annual"]["live_market"],
        ticker="JPM",
        sector="Banks",
    )
    assert cm.get("archetype") == "bank_lender"
    nc = get_metric(cm, "net_cash_incl_st_investments__current_annual")
    assert nc is not None
    assert nc.get("applicable") is False
    assert "not meaningful" in (nc.get("headline") or "").lower() or "bank" in (
        nc.get("headline") or ""
    ).lower()

    state = {
        "ticker": "JPM",
        "sector": "Banks",
        "income_statement": income,
        "balance_sheet": balance,
        "cash_flow_statement": cash,
        "canonical_metrics": cm,
    }
    dcf = compute_dcf_from_state(state)
    assert dcf.get("method") == "excess_return_on_equity", dcf.get("method")
    assert dcf.get("method") != "multi_stage_fcf_dcf"


def test_bank_validation_skips_structurally_inapplicable_gross_margin():
    income, balance, cash = _synthetic_bank()
    cm = compute_canonical_metrics(
        income_statement=income,
        balance_sheet=balance,
        cash_flow_statement=cash,
        live_market=income["current_annual"]["live_market"],
        ticker="JPM",
        sector="Banks",
    )
    gross_margin = get_metric(cm, "gross_margin__current_annual")
    assert gross_margin is not None
    assert gross_margin.get("applicable") is False

    report = validate_inputs(
        {
            "ticker": "JPM",
            "sector": "Banks",
            "income_statement": income,
            "balance_sheet": balance,
            "cash_flow_statement": cash,
            "canonical_metrics": cm,
            "macro_context": "",
            "macro_regime_assessment": "",
            "sec_filing_summary": "",
        }
    )

    assert report["status"] in {"PASS", "WARN"}, report
    assert not any(
        check["name"] == "metrics_core" and check["status"] == "FAIL"
        for check in report["checks"]
    )
    assert not any(
        "gross_margin__current_annual" in failure
        for failure in report["failures"]
    )


def test_reit_valuation_not_fcf_dcf():
    state = {
        "ticker": "PLD",
        "sector": "REIT",
        "income_statement": {},
        "balance_sheet": {},
        "cash_flow_statement": {},
        "canonical_metrics": {"archetype": "reit_real_estate", "by_id": {}, "metrics": []},
    }
    dcf = compute_dcf_from_state(state)
    assert dcf.get("errors")
    assert "reit" in dcf["errors"][0].lower() or "ffo" in (dcf.get("method") or "")


def test_peer_filter_excludes_cross_archetype():
    kept, excl = filter_peers_by_archetype(
        ["JPM", "MSFT", "BAC", "CRM"], "bank_lender", subject="WFC"
    )
    assert "JPM" in kept and "BAC" in kept
    assert "MSFT" not in kept and "CRM" not in kept
    assert any(e["ticker"] == "MSFT" for e in excl)


def test_peers_for_bank_are_banks():
    peers = peers_for_archetype("bank_lender", subject="JPM")
    assert len(peers) >= 2
    for p in peers:
        assert classify_archetype(ticker=p)["archetype"] == "bank_lender"


def test_validation_pass_on_synthetic():
    income, balance, cash = _synthetic_industrial()
    cm = compute_canonical_metrics(
        income_statement=income,
        balance_sheet=balance,
        cash_flow_statement=cash,
        live_market=income["current_annual"]["live_market"],
        ticker="NVDA",
        sector="Semiconductors",
    )
    state = {
        "ticker": "NVDA",
        "sector": "Semiconductors",
        "income_statement": income,
        "balance_sheet": balance,
        "cash_flow_statement": cash,
        "canonical_metrics": cm,
        "macro_context": "NVDA semiconductors Fed rates inflation outlook",
        "sec_filing_summary": "NVIDIA NVDA filing summary revenue growth",
    }
    report = validate_inputs(state)
    assert report["status"] in ("PASS", "WARN"), report
    assert not any(c["status"] == "FAIL" and c["name"] == "revenue_positive" for c in report["checks"])


def test_validation_fails_missing_revenue():
    state = {
        "ticker": "ZZZZ",
        "sector": "Test",
        "income_statement": {"current_annual": {}},
        "balance_sheet": {},
        "cash_flow_statement": {},
        "canonical_metrics": {
            "metrics": [],
            "by_id": {},
            "summary": {"applicable_with_value": 0, "unavailable": 0, "metric_count": 0},
            "period_labels": {
                "current_annual": {"duration": "12mo", "label": "x", "comparable_for_qoq": False},
            },
        },
        "macro_context": "",
        "sec_filing_summary": "",
    }
    report = validate_inputs(state)
    assert report["status"] == "FAIL"
    assert report["failures"]


def test_query_routing_defaults_and_types():
    d = classify_query("Is NVDA still a buy after the run-up?")
    assert d["query_type"] == "full_underwrite"

    d = classify_query("What is NVDA fair value DCF?")
    assert d["query_type"] == "valuation_only"

    d = classify_query("What are the main risks and bear case for NVDA?")
    assert d["query_type"] == "risk_assessment"

    d = classify_query("What does NVIDIA do and how does it make money?")
    assert d["query_type"] == "business_understanding"

    d = classify_query("What is NVDA's China exposure?")
    assert d["query_type"] == "specific_question"

    d = classify_query("Screen top bank stocks", mode="screener")
    assert d["query_type"] == "screener"

    # Ambiguous → full
    d = classify_query("thoughts on the name")
    assert d["query_type"] == "full_underwrite"
    assert d["defaulted"] is True


def test_agents_for_query_type_valuation_only():
    flags = agents_for_query_type("valuation_only")
    assert flags["fundamental"] and flags["relative"]
    assert not flags["bull"] and not flags["bear"]
    assert flags["data_gatherer"] and flags["metrics"]


def test_valuation_method_dispatch_table():
    assert valuation_method_for_archetype("bank_lender") == "excess_return_on_equity"
    assert valuation_method_for_archetype("general") == "multi_stage_fcf_dcf"
    assert valuation_method_for_archetype("pre_profit_growth") == "path_to_profitability"
    assert valuation_method_for_archetype("equity_reit") == "ffo_nav"


def test_graph_imports():
    from mas_sector_system.main import app, empty_state

    nodes = set(app.get_graph().nodes)
    for n in (
        "metrics_compute",
        "validation_gate",
        "validation_halt",
        "capital_allocation",
        "capital_ready",
        "bull_agent",
        "synthesis_ready",
        "style_pass",
        "docx_export",
    ):
        assert n in nodes, n
    # Removed layers must stay gone (double-run barrier + style QC).
    assert "analysis_ready" not in nodes
    assert "qc_style_check" not in nodes
    assert "qc_style_halt" not in nodes
    assert "post_validation" not in nodes
    s = empty_state(
        ticker="NVDA",
        sector="Semiconductors",
        mode="deep_dive",
        user_query="test",
    )
    assert "canonical_metrics" in s
    assert "validation_report" in s
    assert "query_type" in s


def test_validation_is_the_only_path_from_foundation_to_capital():
    from mas_sector_system.main import app

    incoming = {}
    outgoing = {}
    for edge in app.get_graph().edges:
        incoming.setdefault(edge.target, set()).add(edge.source)
        outgoing.setdefault(edge.source, set()).add(edge.target)

    assert incoming["capital_ready"] == {
        "metrics_compute",
        "business_overview",
        "macro_regime",
        "management_track_record",
    }
    assert outgoing["capital_ready"] == {"validation_gate"}
    assert incoming["capital_allocation"] == {"validation_gate"}
    assert outgoing["validation_gate"] == {
        "capital_allocation",
        "validation_halt",
    }


def test_sector_peers_preferred_for_semiconductors():
    """NVDA / Semiconductors must not fall back to mega-cap tech peers only."""
    comps = fetch_peer_multiples(
        "NVDA",
        sector="Semiconductors",
        subject_archetype="general",
    )
    peers = set(comps.get("peer_list") or [])
    # At least one true semi peer should be present.
    semi = {"AMD", "AVGO", "INTC", "TSM", "QCOM", "AMAT", "MU", "ASML"}
    assert peers & semi, f"expected semi peers, got {peers}"
    # Mega-cap software/retail names should not dominate a pure mega-cap set.
    assert not peers.issubset({"AAPL", "MSFT", "GOOGL", "AMZN", "META"})
    src = comps.get("peer_source") or ""
    assert "sector" in src or peers & semi


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
