"""US all-sector coverage tests (classifier + maps + dispatch).

Cheap offline tests + optional live SEC smoke for hard archetypes.

  python3 tests/test_us_sector_coverage.py
  LIVE_SEC=1 python3 tests/test_us_sector_coverage.py   # hits EDGAR
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mas_sector_system.archetype import (  # noqa: E402
    HARD_ARCHETYPES,
    classify_archetype,
    classify_from_sic,
    filter_peers_by_archetype,
    valuation_method_for_archetype,
)
from mas_sector_system.concept_maps import maps_for_archetype  # noqa: E402
from mas_sector_system.metrics import compute_canonical_metrics, get_metric  # noqa: E402
from mas_sector_system.valuation_engine import compute_dcf_from_state  # noqa: E402

# ── 16-row golden matrix (classifier expectations) ──────────────────────────

GOLDEN_MATRIX = [
    # archetype, ticker, sector, expect high conf via ticker map
    # NVDA moved off `general` on 2026-08-04: semis carry a 1.40 unlevered beta
    # against `general`'s 0.95, and routing them through the catch-all was the
    # measured cause of the +99% / +78% overvaluation on NVDA / QCOM.
    ("semiconductor", "NVDA", "Information Technology Semiconductors"),
    ("software_saas", "CRM", "Information Technology Software"),
    ("bank_lender", "JPM", "Financials Banks"),
    ("insurance", "PGR", "Financials Insurance"),
    ("equity_reit", "PLD", "Real Estate Equity REIT"),
    ("mortgage_reit", "NLY", "Real Estate Mortgage REIT"),
    ("utility", "NEE", "Utilities Electric"),
    ("cyclical_commodity", "XOM", "Energy Oil Gas E&P"),
    ("midstream", "EPD", "Energy Midstream"),
    ("general", "PFE", "Health Care Pharmaceuticals"),
    ("pre_profit_growth", "PLTR", "Information Technology Software"),
    ("general", "HD", "Consumer Discretionary Retail"),
    ("mature_dividend_payer", "KO", "Consumer Staples Beverages"),
    ("asset_heavy_industrial", "CAT", "Industrials Machinery"),
    ("telecom", "T", "Communication Services Telecom"),
    ("cyclical_commodity", "FCX", "Materials Metals Mining"),
]


def test_ticker_archetype_has_no_duplicate_keys():
    """A repeated ticker in the literal is invisible — and reaches the DCF.

    Python collapses a duplicate key at parse time and keeps the *last* one,
    silently and with no warning. On 2026-08-04 `TSM` and `ASML` appeared both
    in the semiconductor block and again under "Foreign", so both classified as
    `general` and were priced off a 0.95 unlevered beta instead of 1.40 — the
    exact defect the semiconductor archetype was added to fix, shipped half
    working. Nothing at runtime can catch this, so it has to be caught in the
    source: read the AST, not the dict.
    """
    import ast

    src = (ROOT / "mas_sector_system" / "archetype.py").read_text()
    for node in ast.walk(ast.parse(src)):
        targets = getattr(node, "targets", []) or ([node.target] if getattr(node, "target", None) else [])
        if not any(getattr(t, "id", None) == "TICKER_ARCHETYPE" for t in targets):
            continue
        keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        assert not dupes, (
            f"duplicate tickers in TICKER_ARCHETYPE: {dupes}. The last entry "
            f"silently wins and the earlier one is dead code."
        )
        assert len(keys) > 50, f"only parsed {len(keys)} keys — the AST walk missed the literal"
        break
    else:
        raise AssertionError("TICKER_ARCHETYPE assignment not found in archetype.py")


def test_classifier_golden_matrix():
    for arch, ticker, sector in GOLDEN_MATRIX:
        clf = classify_archetype(ticker=ticker, sector=sector)
        got = clf["archetype"]
        # normalize
        if got == "reit_real_estate":
            got = "equity_reit"
        assert got == arch, f"{ticker}: expected {arch}, got {got} signals={clf.get('signals')}"
        assert clf["confidence"] == "high", f"{ticker}: confidence={clf['confidence']}"


def test_sic_ranges():
    assert classify_from_sic("6022")[0] == "bank_lender"
    assert classify_from_sic("6311")[0] == "insurance"
    assert classify_from_sic("6798")[0] == "equity_reit"
    assert classify_from_sic("4911")[0] == "utility"
    assert classify_from_sic("1311")[0] == "cyclical_commodity"
    # Semis route to their own archetype as of 2026-08-04. They previously fell
    # through to `general`, whose 0.95 unlevered beta understated the discount
    # rate badly enough to put NVDA at +99% and QCOM at +78% against market.
    assert classify_from_sic("3674")[0] == "semiconductor"  # device makers
    assert classify_from_sic("3559")[0] == "semiconductor"  # capital equipment


def test_concept_maps_exist_for_hard_archetypes():
    for arch in ("general", "bank_lender", "insurance", "equity_reit", "mortgage_reit"):
        m = maps_for_archetype(arch)
        assert "income" in m and "balance" in m and "cashflow" in m
        assert "Revenues" in m["income"] or "InterestIncome" in m["income"]
    # Bank has loans/deposits
    b = maps_for_archetype("bank_lender")["balance"]
    assert "LoansNet" in b and "Deposits" in b
    # Insurer has premiums
    assert "PremiumsEarned" in maps_for_archetype("insurance")["income"]
    # REIT has depreciation / real estate
    assert "DepreciationRealEstate" in maps_for_archetype("equity_reit")["income"]


def test_valuation_dispatch_never_fcf_for_hard():
    for arch, method in [
        ("bank_lender", "excess_return_on_equity"),
        ("insurance", "excess_return_on_equity"),
        ("equity_reit", "ffo_nav"),
        ("mortgage_reit", "book_value_spread"),
        ("pre_profit_growth", "path_to_profitability"),
    ]:
        assert valuation_method_for_archetype(arch) == method

    # Bank state without needing live SEC
    state = {
        "ticker": "JPM",
        "sector": "Banks",
        "sic": "6022",
        "income_statement": {
            "current_annual": {
                "NetIncomeLoss": {"value": 50e9, "end": "2025-12-31", "fy": 2025, "fp": "FY"},
                "Revenues": {"value": 160e9, "end": "2025-12-31", "fy": 2025, "fp": "FY"},
            }
        },
        "balance_sheet": {
            "current_annual": {
                "StockholdersEquity": {"value": 300e9, "end": "2025-12-31"},
                "TotalAssets": {"value": 4e12, "end": "2025-12-31"},
                "LoansNet": {"value": 1.3e12, "end": "2025-12-31"},
                "Deposits": {"value": 2.4e12, "end": "2025-12-31"},
                "live_market": {"price": 200.0, "market_cap": 600e9, "shares_outstanding": 3e9},
            }
        },
        "cash_flow_statement": {},
        "canonical_metrics": {"archetype": "bank_lender", "by_id": {}, "metrics": []},
    }
    dcf = compute_dcf_from_state(state)
    assert dcf["method"] == "excess_return_on_equity"
    assert dcf.get("method") != "multi_stage_fcf_dcf"
    assert not any("fall back to FCF" in e for e in (dcf.get("errors") or []))
    # Should produce a value when NI + equity present
    assert dcf.get("equity_value") is not None or dcf.get("errors")


def test_bank_metrics_suppress_net_cash():
    state_income = {
        "current_annual": {
            "NetIncomeLoss": {"value": 50e9, "end": "2025-12-31", "fy": 2025, "fp": "FY"},
            "InterestIncome": {"value": 100e9, "end": "2025-12-31", "fy": 2025, "fp": "FY"},
            "NetInterestIncome": {"value": 70e9, "end": "2025-12-31", "fy": 2025, "fp": "FY"},
            "NoninterestIncome": {"value": 40e9, "end": "2025-12-31", "fy": 2025, "fp": "FY"},
            "Revenues": {"value": 110e9, "end": "2025-12-31", "fy": 2025, "fp": "FY", "note": "derived"},
            "live_market": {"price": 200.0, "market_cap": 600e9, "shares_outstanding": 3e9},
        },
        "prior_annual": {},
        "current_quarter": {},
        "prior_quarter": {},
    }
    state_bal = {
        "current_annual": {
            "CashAndCashEquivalents": {"value": 500e9, "end": "2025-12-31"},
            "ShortTermDebt": {"value": 50e9, "end": "2025-12-31"},
            "LongTermDebt": {"value": 300e9, "end": "2025-12-31"},
            "TotalAssets": {"value": 4e12, "end": "2025-12-31"},
            "StockholdersEquity": {"value": 300e9, "end": "2025-12-31"},
            "LoansNet": {"value": 1.3e12, "end": "2025-12-31"},
            "Deposits": {"value": 2.4e12, "end": "2025-12-31"},
            "live_market": state_income["current_annual"]["live_market"],
        },
        "prior_annual": {},
        "current_quarter": {},
        "prior_quarter": {},
    }
    cm = compute_canonical_metrics(
        income_statement=state_income,
        balance_sheet=state_bal,
        cash_flow_statement={"current_annual": {}, "prior_annual": {}, "current_quarter": {}, "prior_quarter": {}},
        live_market=state_income["current_annual"]["live_market"],
        ticker="JPM",
        sector="Banks",
        sic="6022",
    )
    assert cm["archetype"] == "bank_lender"
    nc = get_metric(cm, "net_cash_incl_st_investments__current_annual")
    assert nc is not None
    assert nc.get("applicable") is False
    assert "not meaningful" in (nc.get("headline") or "").lower() or "bank" in (
        nc.get("headline") or ""
    ).lower()


def test_peer_filter_hard_archetypes():
    kept, excl = filter_peers_by_archetype(
        ["JPM", "BAC", "MSFT", "PLD", "PGR"], "bank_lender", subject="WFC"
    )
    assert "JPM" in kept and "BAC" in kept
    assert "MSFT" not in kept and "PLD" not in kept
    assert any(e["ticker"] == "MSFT" for e in excl)


def test_equity_reit_ffo_path_no_fcf_dcf():
    state = {
        "ticker": "PLD",
        "sector": "Real Estate",
        "canonical_metrics": {"archetype": "equity_reit", "by_id": {}, "metrics": []},
        "income_statement": {
            "current_annual": {
                "NetIncomeLoss": {"value": 3e9},
                "FFO": {"value": 5e9, "note": "derived"},
                "live_market": {"price": 120.0, "market_cap": 100e9, "shares_outstanding": 900e6},
            }
        },
        "balance_sheet": {"current_annual": {"StockholdersEquity": {"value": 50e9}}},
        "cash_flow_statement": {},
    }
    # attach live market on income for _live_market_from_state
    state["income_statement"]["current_annual"]["live_market"] = {
        "price": 120.0,
        "market_cap": 100e9,
        "shares_outstanding": 900e6,
    }
    dcf = compute_dcf_from_state(state)
    assert dcf["method"] == "ffo_nav"
    assert dcf.get("method") != "multi_stage_fcf_dcf"
    assert dcf["inputs"].get("ffo") == 5e9 or dcf.get("errors")


def _live_sec_smoke(ticker: str, expect_arch: str, must_have_lines: list[str]):
    """Optional: pull real company facts and check concept resolution."""
    from mas_sector_system.tools import (
        extract_statements_from_company_facts,
        fetch_entity_metadata,
        fetch_sec_company_facts,
        get_cik_for_ticker,
    )

    cik = get_cik_for_ticker(ticker)
    meta = fetch_entity_metadata(cik)
    print(f"  {ticker} CIK={cik} SIC={meta.get('sic')} {meta.get('sic_description')}")
    facts = fetch_sec_company_facts(cik)
    parsed = extract_statements_from_company_facts(facts, archetype=expect_arch)
    inc = parsed["income_statement"]["current_annual"]
    bal = parsed["balance_sheet"]["current_annual"]
    resolved = []
    empty = []
    for line in must_have_lines:
        cell = inc.get(line) or bal.get(line)
        val = cell.get("value") if isinstance(cell, dict) else None
        if val is not None:
            resolved.append(line)
        else:
            empty.append(line)
    print(f"  resolved={resolved} empty={empty} derived={parsed.get('derived_notes')}")
    clf = classify_archetype(
        ticker=ticker,
        sic=meta.get("sic"),
        income_statement=parsed["income_statement"],
        balance_sheet=parsed["balance_sheet"],
        cash_flow_statement=parsed["cash_flow_statement"],
    )
    print(f"  classify → {clf['archetype']} conf={clf['confidence']} flag={clf.get('flag')}")
    return resolved, empty, clf


def test_live_sec_hard_archetypes_optional():
    if os.environ.get("LIVE_SEC") != "1":
        print("SKIP live SEC smoke (set LIVE_SEC=1 to enable)")
        return
    cases = [
        ("JPM", "bank_lender", ["InterestIncome", "NetIncomeLoss", "LoansNet", "Deposits"]),
        ("PGR", "insurance", ["PremiumsEarned", "NetIncomeLoss", "PolicyReserves"]),
        ("PLD", "equity_reit", ["NetIncomeLoss", "FFO", "RealEstateInvestments"]),
        ("NVDA", "general", ["Revenues", "NetIncomeLoss", "CashAndCashEquivalents"]),
    ]
    for ticker, arch, lines in cases:
        print(f"\nLIVE {ticker} as {arch}:")
        resolved, empty, clf = _live_sec_smoke(ticker, arch, lines)
        # At least net income or revenues should resolve for a major filer
        assert resolved, f"{ticker}: no lines resolved"
        assert clf["archetype"] in (arch, "equity_reit", "general") or clf["confidence"] != "none"


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
