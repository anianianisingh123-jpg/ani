"""Deterministic business-archetype classification (US 10-K / 10-Q).

Priority: SIC → balance-sheet composition → income shape → GICS/sector keywords.
``general`` means standard commercial treatment — wrong for banks/REITs/insurers;
low-confidence / conflict → general + loud flag.
"""

from __future__ import annotations

from typing import Any, Optional

# Public archetype ids
ARCHETYPES = (
    "bank_lender",
    "insurance",
    "equity_reit",
    "mortgage_reit",
    "asset_heavy_industrial",
    "asset_heavy",
    "asset_light",
    "utility",
    "software_saas",
    "mature_dividend_payer",
    "cyclical_commodity",
    "pre_profit_growth",
    "telecom",
    "midstream",
    "general",
    # legacy alias still accepted
    "reit_real_estate",
)

# Canonical hard archetypes where commercial metrics are structurally wrong
HARD_ARCHETYPES = frozenset(
    {"bank_lender", "insurance", "equity_reit", "mortgage_reit", "reit_real_estate"}
)

# Sector / industry keyword → archetype (weak final tie-breaker).
_SECTOR_RULES: list[tuple[tuple[str, ...], str]] = [
    (("BANK", "BANKS", "THRIFT", "SAVINGS", "LENDING", "CREDIT UNION", "REGIONAL BANK"), "bank_lender"),
    (("INSURANCE", "INSURER", "LIFE INSURANCE", "P&C", "PROPERTY CASUALTY", "MANAGED CARE"), "insurance"),
    (("MORTGAGE REIT", "MREIT"), "mortgage_reit"),
    (("REIT", "EQUITY REIT", "REAL ESTATE INVESTMENT TRUST"), "equity_reit"),
    (("REAL ESTATE", "REALTY"), "equity_reit"),
    (("UTILITY", "UTILITIES", "ELECTRIC UTILITY", "GAS UTILITY", "WATER UTILITY", "REGULATED ELECTRIC"), "utility"),
    (("SOFTWARE", "SAAS", "CLOUD SOFTWARE", "APPLICATION SOFTWARE"), "software_saas"),
    (("SEMICONDUCTOR", "SEMI", "CHIP", "FABLESS"), "general"),
    (("MIDSTREAM", "PIPELINE", "MLP"), "midstream"),
    (("OIL", "GAS", "ENERGY", "PETROLEUM", "E&P", "EXPLORATION"), "cyclical_commodity"),
    (("MINING", "COAL", "METALS", "STEEL", "COMMODITY"), "cyclical_commodity"),
    (("TELECOM", "TELECOMMUNICATION", "WIRELESS"), "telecom"),
    (("INDUSTRIAL", "MACHINERY", "AEROSPACE", "DEFENSE", "CONSTRUCTION", "RAIL"), "asset_heavy_industrial"),
    (("AIRLINE", "AIRLINES"), "asset_heavy_industrial"),
    (("BIOTECH", "BIOTECHNOLOGY", "PRE-REVENUE"), "pre_profit_growth"),
    (("PHARMA", "PHARMACEUTICAL", "DRUG MANUFACTUR"), "general"),
    (("RETAIL", "RESTAURANT", "APPAREL"), "general"),
    (("STAPLE", "BEVERAGE", "TOBACCO", "HOUSEHOLD PRODUCT"), "mature_dividend_payer"),
]

ARCHETYPE_PEERS: dict[str, list[str]] = {
    "bank_lender": ["JPM", "BAC", "WFC", "USB", "PNC", "C", "TFC", "CFG"],
    "insurance": ["PGR", "CB", "TRV", "ALL", "AIG", "MET", "PRU", "HIG"],
    "equity_reit": ["PLD", "AMT", "EQIX", "O", "SPG", "WELL", "DLR", "PSA"],
    "mortgage_reit": ["NLY", "AGNC", "STWD", "BXMT", "RITM", "TWO"],
    "reit_real_estate": ["PLD", "AMT", "EQIX", "O", "SPG", "WELL"],
    "asset_heavy_industrial": ["CAT", "DE", "HON", "GE", "MMM", "EMR", "UNP", "BA"],
    "asset_heavy": ["CAT", "DE", "HON", "GE", "UNP"],
    "asset_light": ["V", "MA", "SPGI", "MCO", "ICE"],
    "utility": ["NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE"],
    "software_saas": ["MSFT", "ORCL", "CRM", "ADBE", "NOW", "INTU", "SNOW"],
    "mature_dividend_payer": ["JNJ", "PG", "KO", "PEP", "CL", "MDLZ"],
    "cyclical_commodity": ["XOM", "CVX", "COP", "EOG", "FCX", "NEM", "MPC"],
    "pre_profit_growth": ["PLTR", "SNOW", "PATH", "DKNG", "ABNB"],
    "telecom": ["T", "VZ", "TMUS"],
    "midstream": ["EPD", "ET", "WMB", "KMI", "OKE"],
    "general": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AMD"],
}

# Golden / known tickers — high confidence when set.
TICKER_ARCHETYPE: dict[str, str] = {
    # Banks
    "JPM": "bank_lender", "BAC": "bank_lender", "WFC": "bank_lender",
    "C": "bank_lender", "USB": "bank_lender", "PNC": "bank_lender",
    "TFC": "bank_lender", "CFG": "bank_lender", "KEY": "bank_lender",
    # Insurance / managed care
    "MET": "insurance", "AIG": "insurance", "PGR": "insurance", "CB": "insurance",
    "TRV": "insurance", "ALL": "insurance", "PRU": "insurance",
    "UNH": "insurance", "CVS": "insurance", "CI": "insurance", "ELV": "insurance",
    # Equity REITs
    "PLD": "equity_reit", "AMT": "equity_reit", "O": "equity_reit",
    "SPG": "equity_reit", "EQIX": "equity_reit", "WELL": "equity_reit",
    "DLR": "equity_reit", "PSA": "equity_reit",
    # Mortgage REITs
    "NLY": "mortgage_reit", "AGNC": "mortgage_reit", "STWD": "mortgage_reit",
    "BXMT": "mortgage_reit", "RITM": "mortgage_reit",
    # Utilities
    "NEE": "utility", "DUK": "utility", "SO": "utility", "D": "utility",
    "AEP": "utility", "EXC": "utility",
    # Software
    "CRM": "software_saas", "NOW": "software_saas", "ADBE": "software_saas",
    "MSFT": "software_saas", "ORCL": "software_saas", "INTU": "software_saas",
    "SNOW": "software_saas",
    # Commodity / energy
    "XOM": "cyclical_commodity", "CVX": "cyclical_commodity", "COP": "cyclical_commodity",
    "EOG": "cyclical_commodity", "FCX": "cyclical_commodity", "NEM": "cyclical_commodity",
    "MPC": "cyclical_commodity", "VLO": "cyclical_commodity",
    # Midstream
    "EPD": "midstream", "ET": "midstream", "WMB": "midstream", "KMI": "midstream",
    # Industrial
    "CAT": "asset_heavy_industrial", "DE": "asset_heavy_industrial",
    "HON": "asset_heavy_industrial", "UNP": "asset_heavy_industrial", "BA": "asset_heavy_industrial",
    # Staples
    "JNJ": "mature_dividend_payer", "PG": "mature_dividend_payer",
    "KO": "mature_dividend_payer", "PEP": "mature_dividend_payer",
    # Tech general / fabless semi
    "NVDA": "general", "AMD": "general", "AVGO": "general", "QCOM": "general",
    "AAPL": "general", "GOOGL": "general", "AMZN": "general", "META": "general",
    # Pre-profit / growth
    "PLTR": "pre_profit_growth", "PATH": "pre_profit_growth", "DKNG": "pre_profit_growth",
    # Telecom
    "T": "telecom", "VZ": "telecom", "TMUS": "telecom",
    # Biotech (pre-revenue often)
    "MRNA": "pre_profit_growth", "BNTX": "pre_profit_growth",
    # Pharma
    "PFE": "general", "LLY": "general", "MRK": "general", "ABBV": "general",
    # Retail
    "WMT": "general", "TGT": "general", "COST": "mature_dividend_payer",
    "HD": "general", "LOW": "general", "SBUX": "general", "MCD": "mature_dividend_payer",
    # Foreign (out of scope but mapped general)
    "TSM": "general", "ASML": "general", "SAP": "software_saas",
}

# Metric id prefixes suppressed per archetype
_SUPPRESS_PREFIXES: dict[str, tuple[str, ...]] = {
    "bank_lender": (
        "net_cash", "net_debt", "enterprise_value", "ev_to_ebitda",
        "fcf_yield", "fcf__", "fcf_margin", "fcf_yoy", "fcf_per_share",
        "fcf_conversion", "fcf_annualized", "buyback_dollars_per_pct_point",
        "gross_margin", "price_to_sales",
    ),
    "insurance": (
        "net_cash", "net_debt", "enterprise_value", "ev_to_ebitda",
        "fcf_yield", "gross_margin",
    ),
    "equity_reit": (
        "trailing_pe", "forward_pe", "peg", "ev_to_ebitda",
    ),
    "reit_real_estate": (
        "trailing_pe", "forward_pe", "peg", "ev_to_ebitda",
    ),
    "mortgage_reit": (
        "trailing_pe", "forward_pe", "peg", "ev_to_ebitda", "fcf_yield",
        "net_cash", "enterprise_value",
    ),
    "pre_profit_growth": (
        "trailing_pe", "forward_pe", "peg", "fcf_yield",
    ),
}


def _line_value(period: Any, *keys: str) -> Optional[float]:
    if not isinstance(period, dict):
        return None
    for k in keys:
        cell = period.get(k)
        if isinstance(cell, dict) and cell.get("value") is not None:
            try:
                return float(cell["value"])
            except (TypeError, ValueError):
                continue
        if isinstance(cell, (int, float)) and not isinstance(cell, bool):
            return float(cell)
    return None


def _period(stmt: Any, name: str) -> dict:
    if not isinstance(stmt, dict):
        return {}
    b = stmt.get(name)
    return b if isinstance(b, dict) else {}


def _parse_sic(sic: Optional[str]) -> Optional[int]:
    if sic is None:
        return None
    try:
        return int(str(sic).strip()[:4])
    except ValueError:
        return None


def classify_from_sic(sic: Optional[str]) -> Optional[tuple[str, str]]:
    """Return (archetype, signal) from SIC or None."""
    s = _parse_sic(sic)
    if s is None:
        return None
    # Banks / thrifts / credit institutions
    if 6000 <= s <= 6099 or 6100 <= s <= 6199 or s in (6021, 6022, 6029, 6035, 6036):
        return "bank_lender", f"SIC {s} (depository / credit institution)"
    # Insurance
    if 6300 <= s <= 6499 or 6311 <= s <= 6411:
        return "insurance", f"SIC {s} (insurance)"
    # REITs — SIC 6798 is classic; real estate 6500-6799 needs sub-type
    if s == 6798:
        return "equity_reit", f"SIC {s} (REIT)"
    if 6500 <= s <= 6799:
        return "equity_reit", f"SIC {s} (real estate)"
    # Utilities
    if 4900 <= s <= 4991:
        return "utility", f"SIC {s} (utility)"
    # Oil & gas
    if 1300 <= s <= 1389 or 2900 <= s <= 2999:
        return "cyclical_commodity", f"SIC {s} (oil/gas/refining)"
    if 1000 <= s <= 1499:
        return "cyclical_commodity", f"SIC {s} (mining/materials)"
    # Telecom
    if 4800 <= s <= 4899:
        return "telecom", f"SIC {s} (communications)"
    # Pharma / biotech
    if s == 2836 or s == 2834:
        return "general", f"SIC {s} (pharma/biotech — refine via income shape)"
    # Software
    if s in (7371, 7372, 7373):
        return "software_saas", f"SIC {s} (software/services)"
    # Semiconductors
    if s == 3674:
        return "general", f"SIC {s} (semiconductors)"
    return None


def classify_archetype(
    *,
    ticker: Optional[str] = None,
    sector: Optional[str] = None,
    income_statement: Optional[dict] = None,
    balance_sheet: Optional[dict] = None,
    cash_flow_statement: Optional[dict] = None,
    sic: Optional[str] = None,
    industry: Optional[str] = None,
) -> dict[str, Any]:
    """Return archetype classification dict.

    Keys: archetype, confidence, signals (list), sector, sub_archetype,
    reasons (alias of signals for back-compat), conflict (bool).
    """
    signals: list[str] = []
    votes: list[tuple[str, str, str]] = []  # archetype, confidence, signal

    t = (ticker or "").strip().upper()
    sector_u = (sector or "").upper()
    industry_u = (industry or "").upper()
    blob = f"{sector_u} {industry_u}"

    # ── 1) SIC (strongest) ───────────────────────────────────────────────
    sic_hit = classify_from_sic(sic)
    if sic_hit:
        arch, sig = sic_hit
        signals.append(sig)
        votes.append((arch, "high", sig))

    # ── 2) Balance sheet composition ─────────────────────────────────────
    bal = _period(balance_sheet, "current_annual") or _period(
        balance_sheet, "current_quarter"
    )
    assets = _line_value(bal, "TotalAssets", "Assets")
    if assets and assets > 0:
        loans = _line_value(bal, "LoansNet", "LoansAndLeasesReceivableNetReportedAmount")
        deposits = _line_value(bal, "Deposits", "DepositLiabilities")
        ppe = _line_value(bal, "PropertyPlantAndEquipment", "PropertyPlantAndEquipmentNet")
        re_inv = _line_value(
            bal,
            "RealEstateInvestments",
            "RealEstateInvestmentPropertyNet",
            "InvestmentInRealEstate",
        )
        gw = _line_value(bal, "Goodwill") or 0.0
        intang = _line_value(bal, "IntangibleAssets") or 0.0
        mbs = _line_value(
            bal,
            "MortgageBackedSecurities",
            "MortgageBackedSecuritiesAvailableForSaleAtFairValue",
        )
        policy = _line_value(
            bal,
            "PolicyReserves",
            "LiabilityForFuturePolicyBenefits",
            "UnearnedPremiums",
        )
        st_debt = _line_value(bal, "ShortTermDebt") or 0.0
        lt_debt = _line_value(bal, "LongTermDebt") or 0.0
        total_debt = st_debt + lt_debt

        if loans is not None and loans / assets > 0.30:
            sig = f"loans {loans/assets:.0%} of assets"
            signals.append(sig)
            votes.append(("bank_lender", "high", sig))
        if deposits is not None and deposits / assets > 0.30:
            sig = f"deposits {deposits/assets:.0%} of assets"
            signals.append(sig)
            votes.append(("bank_lender", "high", sig))
        if policy is not None and policy / assets > 0.15:
            sig = f"policy reserves/unearned premiums {policy/assets:.0%} of assets"
            signals.append(sig)
            votes.append(("insurance", "high", sig))
        re_share = (re_inv / assets) if re_inv else ((ppe / assets) if ppe else 0)
        # Mortgage REIT: securities heavy + high leverage
        if mbs is not None and mbs / assets > 0.35 and total_debt / assets > 0.50:
            sig = f"MBS {mbs/assets:.0%} of assets + leverage {total_debt/assets:.0%}"
            signals.append(sig)
            votes.append(("mortgage_reit", "high", sig))
        elif re_inv is not None and re_inv / assets > 0.50:
            sig = f"real estate investments {re_inv/assets:.0%} of assets"
            signals.append(sig)
            votes.append(("equity_reit", "high", sig))
        elif ppe is not None and ppe / assets > 0.40 and not loans:
            sig = f"PP&E {ppe/assets:.0%} of assets"
            signals.append(sig)
            votes.append(("asset_heavy", "moderate", sig))
        if (gw + intang) / assets > 0.40 and (ppe is None or ppe / assets < 0.10):
            sig = f"intangibles+GW {(gw+intang)/assets:.0%} assets, PP&E low"
            signals.append(sig)
            votes.append(("asset_light", "moderate", sig))

    # ── 3) Income statement shape ────────────────────────────────────────
    inc = _period(income_statement, "current_annual") or _period(
        income_statement, "prior_annual"
    )
    rev = _line_value(inc, "Revenues")
    opinc = _line_value(inc, "OperatingIncomeLoss")
    interest_inc = _line_value(inc, "InterestIncome", "InterestAndDividendIncomeOperating")
    premiums = _line_value(inc, "PremiumsEarned", "PremiumsEarnedNet")
    ni = _line_value(inc, "NetIncomeLoss")

    if interest_inc is not None and rev is not None and rev > 0:
        if interest_inc / rev > 0.50:
            sig = "interest income primary revenue line"
            signals.append(sig)
            votes.append(("bank_lender", "high", sig))
    elif interest_inc is not None and (rev is None or rev == 0):
        # Banks often lack Revenues tag — interest income present alone
        sig = "interest income present without commercial Revenues tag"
        signals.append(sig)
        votes.append(("bank_lender", "moderate", sig))

    if premiums is not None and (rev is None or (rev > 0 and premiums / rev > 0.40) or rev == 0):
        sig = "premiums earned primary / material revenue line"
        signals.append(sig)
        votes.append(("insurance", "high", sig))

    # Pre-profit growth
    prior = _period(income_statement, "prior_annual")
    rev_p = _line_value(prior, "Revenues")
    if opinc is not None and opinc < 0 and rev is not None and rev_p and rev_p > 0:
        g = (rev / rev_p) - 1.0
        if g > 0.40:
            sig = f"negative operating income + revenue growth {g:.0%}"
            signals.append(sig)
            votes.append(("pre_profit_growth", "high", sig))
    if ni is not None and ni < 0 and rev is not None and rev > 0:
        fcf = _line_value(
            _period(cash_flow_statement, "current_annual"), "FreeCashFlow"
        )
        if fcf is not None and fcf < 0:
            sig = "negative NI and FCF"
            signals.append(sig)
            votes.append(("pre_profit_growth", "moderate", sig))

    # ── 4) Ticker map ────────────────────────────────────────────────────
    if t and t in TICKER_ARCHETYPE:
        arch = TICKER_ARCHETYPE[t]
        sig = f"ticker map: {t} → {arch}"
        signals.append(sig)
        votes.append((arch, "high", sig))

    # ── 5) Sector keywords (weak) ────────────────────────────────────────
    for keys, arch in _SECTOR_RULES:
        if any(k in blob for k in keys):
            sig = f"sector/industry keyword → {arch}"
            signals.append(sig)
            votes.append((arch, "low", sig))
            break

    # ── Tally votes ──────────────────────────────────────────────────────
    if not votes:
        return {
            "archetype": "general",
            "confidence": "low",
            "signals": ["no strong signals — default general (flag: may be wrong for banks/REITs/insurers)"],
            "reasons": ["no strong signals — default general"],
            "sector": sector,
            "sub_archetype": None,
            "conflict": False,
            "flag": "LOW_CONFIDENCE_GENERAL",
        }

    # Weight by confidence
    weight = {"high": 3, "moderate": 2, "low": 1}
    scores: dict[str, int] = {}
    for arch, conf, _ in votes:
        # normalize legacy
        if arch == "reit_real_estate":
            arch = "equity_reit"
        scores[arch] = scores.get(arch, 0) + weight.get(conf, 1)

    # Conflict if two hard archetypes both scored high
    hard_scores = {a: s for a, s in scores.items() if a in HARD_ARCHETYPES or a == "equity_reit"}
    conflict = len([s for s in hard_scores.values() if s >= 3]) > 1

    winner = max(scores.items(), key=lambda x: x[1])[0]
    top_score = scores[winner]
    # Confidence
    high_votes = [v for v in votes if (v[0] if v[0] != "reit_real_estate" else "equity_reit") == winner and v[1] == "high"]
    if conflict:
        # Prefer SIC / BS over sector keyword — already weighted; if still conflict, general
        if top_score < 6:
            return {
                "archetype": "general",
                "confidence": "low",
                "signals": signals + ["CONFLICT among hard archetypes — defaulting to general (flag loudly)"],
                "reasons": signals + ["CONFLICT among hard archetypes"],
                "sector": sector,
                "sub_archetype": None,
                "conflict": True,
                "flag": "ARCHETYPE_CONFLICT_DEFAULT_GENERAL",
            }

    conf_out = "high" if high_votes and top_score >= 3 else ("moderate" if top_score >= 3 else "low")
    if conf_out == "low" and winner not in HARD_ARCHETYPES:
        # low confidence general-ish — still return winner but flag
        pass

    sub = _sub_archetype(winner, t, sector_u, industry_u, bal if bal else {})

    out = {
        "archetype": winner,
        "confidence": conf_out,
        "signals": signals,
        "reasons": signals,  # back-compat
        "sector": sector,
        "sub_archetype": sub,
        "conflict": conflict,
        "flag": None if conf_out == "high" else "REVIEW_ARCHETYPE",
    }
    if conf_out != "high" and winner in HARD_ARCHETYPES:
        out["flag"] = "HARD_ARCHETYPE_BUT_NOT_HIGH_CONFIDENCE"
    return out


def _sub_archetype(
    arch: str,
    ticker: str,
    sector: str,
    industry: str,
    bal: dict,
) -> Optional[str]:
    blob = f"{sector} {industry}".upper()
    if arch == "bank_lender":
        if any(x in blob for x in ("REGIONAL", "COMMUNITY")):
            return "regional_bank"
        if ticker in ("JPM", "BAC", "C", "WFC"):
            return "money_center_bank"
        return "bank"
    if arch == "insurance":
        if any(x in blob for x in ("LIFE",)):
            return "life"
        if any(x in blob for x in ("MANAGED CARE", "HEALTH")):
            return "managed_care"
        return "pc_or_multi"
    if arch == "equity_reit":
        return "equity_reit"
    if arch == "mortgage_reit":
        return "mortgage_reit"
    if arch == "cyclical_commodity":
        if "MIDSTREAM" in blob or "PIPELINE" in blob:
            return "midstream"
        if any(x in blob for x in ("REFIN", "CRACK")):
            return "refining"
        if any(x in blob for x in ("E&P", "EXPLOR", "PRODUCTION")):
            return "upstream_ep"
        return "commodity"
    return None


def archetype_of_ticker(ticker: str, *, sector: str = "", sic: Optional[str] = None) -> str:
    t = (ticker or "").strip().upper()
    if t in TICKER_ARCHETYPE:
        a = TICKER_ARCHETYPE[t]
        return "equity_reit" if a == "reit_real_estate" else a
    if sic:
        hit = classify_from_sic(sic)
        if hit:
            return hit[0]
    for arch, peers in ARCHETYPE_PEERS.items():
        if t in peers:
            return "equity_reit" if arch == "reit_real_estate" else arch
    c = classify_archetype(ticker=t, sector=sector, sic=sic)
    return c["archetype"]


def peers_for_archetype(
    archetype: str,
    *,
    subject: Optional[str] = None,
    limit: int = 6,
) -> list[str]:
    key = archetype
    if key == "reit_real_estate":
        key = "equity_reit"
    peers = list(ARCHETYPE_PEERS.get(key) or ARCHETYPE_PEERS["general"])
    subj = (subject or "").strip().upper()
    return [p for p in peers if p != subj][:limit]


def filter_peers_by_archetype(
    candidates: list[str],
    subject_archetype: str,
    *,
    subject: Optional[str] = None,
) -> tuple[list[str], list[dict[str, str]]]:
    kept: list[str] = []
    excluded: list[dict[str, str]] = []
    subj = (subject or "").strip().upper()
    sub_arch = subject_archetype
    if sub_arch == "reit_real_estate":
        sub_arch = "equity_reit"

    def _norm(a: str) -> str:
        return "equity_reit" if a == "reit_real_estate" else a

    for p in candidates:
        pu = (p or "").strip().upper()
        if not pu or pu == subj:
            continue
        pa = _norm(archetype_of_ticker(pu))
        if pa != _norm(sub_arch):
            excluded.append(
                {
                    "ticker": pu,
                    "peer_archetype": pa,
                    "reason": (
                        f"archetype mismatch: peer is {pa}, subject is {sub_arch}"
                    ),
                }
            )
        else:
            kept.append(pu)
    return kept, excluded


def apply_archetype_to_metrics(
    canonical: dict[str, Any],
    archetype: str,
) -> dict[str, Any]:
    """Suppress inapplicable metrics; attach archetype metadata."""
    if not isinstance(canonical, dict):
        return canonical

    arch = "equity_reit" if archetype == "reit_real_estate" else archetype
    prefixes = _SUPPRESS_PREFIXES.get(arch, ())
    metrics = list(canonical.get("metrics") or [])
    new_metrics: list[dict[str, Any]] = []

    for m in metrics:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "")
        suppress = any(mid.startswith(p) or p in mid for p in prefixes)
        if suppress and m.get("applicable"):
            nm = dict(m)
            nm["applicable"] = False
            nm["value"] = None
            nm["confidence"] = "none"
            why = _suppress_reason(arch, mid)
            nm["qualifiers"] = list(m.get("qualifiers") or []) + [
                f"suppressed for archetype={arch}"
            ]
            nm["headline"] = why
            nm["computation"] = (m.get("computation") or "") + f" [suppressed:{arch}]"
            new_metrics.append(nm)
        else:
            new_metrics.append(m)

    new_metrics.extend(_archetype_extra_metrics(arch, canonical))

    by_id = {m["id"]: m for m in new_metrics if m.get("id")}
    headlines = []
    for m in new_metrics:
        h = m.get("headline")
        if not h:
            continue
        if m.get("applicable") and m.get("value") is not None:
            headlines.append(h)
        elif any(
            k in h.lower()
            for k in (
                "not meaningful",
                "unavailable",
                "not implemented",
                "suppressed",
                "ffo",
                "combined ratio",
                "excess return",
            )
        ):
            headlines.append(h)

    out = dict(canonical)
    out["archetype"] = arch
    out["metrics"] = new_metrics
    out["by_id"] = by_id
    out["headlines"] = headlines
    n_app = sum(
        1 for m in new_metrics if m.get("applicable") and m.get("value") is not None
    )
    n_un = sum(1 for m in new_metrics if not m.get("applicable"))
    out["summary"] = {
        "metric_count": len(new_metrics),
        "applicable_with_value": n_app,
        "unavailable": n_un,
        "archetype": arch,
    }
    return out


def _suppress_reason(archetype: str, metric_id: str) -> str:
    if archetype == "bank_lender":
        if "net_cash" in metric_id or "net_debt" in metric_id:
            return (
                f"{metric_id} not meaningful for a bank_lender — deposits and "
                f"financial liabilities are operating inventory, not corporate leverage"
            )
        if "ev" in metric_id or "ebitda" in metric_id:
            return (
                f"{metric_id} not meaningful for a bank_lender — EV/EBITDA treats "
                f"deposit funding like industrial leverage; use P/TBV and ROE instead"
            )
        if "fcf" in metric_id:
            return (
                f"{metric_id} not meaningful for a bank_lender — free-cash-flow DCF "
                f"is invalid for deposit-taking institutions"
            )
        if "gross_margin" in metric_id:
            return (
                f"{metric_id} not meaningful for a bank — use net interest margin / NII"
            )
    if archetype == "insurance":
        if "net_cash" in metric_id or "net_debt" in metric_id or "ev" in metric_id:
            return (
                f"{metric_id} not meaningful for insurance — float and reserves dominate; "
                f"use combined ratio / P/B vs ROE"
            )
    if archetype in ("equity_reit", "reit_real_estate"):
        if "trailing_pe" in metric_id or "forward_pe" in metric_id or "ebitda" in metric_id:
            return (
                f"{metric_id} not meaningful as primary for equity REIT — D&A distorts "
                f"earnings; use FFO/AFFO or NAV (never net-income P/E alone)"
            )
    if archetype == "mortgage_reit":
        return (
            f"{metric_id} suppressed for mortgage_reit — use book value / net interest "
            f"spread, not industrial FCF or equity-REIT FFO metrics"
        )
    if archetype == "pre_profit_growth":
        if "pe" in metric_id or "peg" in metric_id or "fcf_yield" in metric_id:
            return (
                f"{metric_id} not meaningful for pre_profit_growth — use EV/Revenue "
                f"or path-to-profitability scenarios"
            )
    return (
        f"{metric_id} suppressed for archetype={archetype} — not applicable; "
        f"do not recompute from raw lines"
    )


def _archetype_extra_metrics(
    archetype: str, canonical: dict[str, Any]
) -> list[dict[str, Any]]:
    extras: list[dict[str, Any]] = []
    basis = "archetype-derived"
    by_id = canonical.get("by_id") or {}

    def _ua(mid: str, why: str) -> dict[str, Any]:
        return {
            "id": mid,
            "value": None,
            "unit": "",
            "basis_period": basis,
            "period_key": None,
            "qualifiers": [f"archetype={archetype}"],
            "staleness": [],
            "source_lines": [],
            "computation": "not implemented or missing tags",
            "applicable": False,
            "headline": why,
            "confidence": "none",
        }

    def _find(*ids: str) -> Optional[dict]:
        for i in ids:
            m = by_id.get(i)
            if isinstance(m, dict) and m.get("value") is not None:
                return m
        # scan metrics list
        for m in canonical.get("metrics") or []:
            if isinstance(m, dict) and m.get("id") in ids and m.get("value") is not None:
                return m
        return None

    if archetype == "bank_lender":
        # ROE
        ni = _find("net_income__current_annual")
        eq = _find("stockholders_equity__current_annual")
        if ni and eq and float(eq["value"]) != 0:
            roe = float(ni["value"]) / float(eq["value"])
            extras.append(
                {
                    "id": "roe__current_annual",
                    "value": roe,
                    "unit": "ratio",
                    "basis_period": ni.get("basis_period") or "current annual",
                    "period_key": "current_annual",
                    "qualifiers": ["bank-relevant", "NI / book equity"],
                    "staleness": [],
                    "source_lines": ["NetIncomeLoss", "StockholdersEquity"],
                    "computation": "net_income / stockholders_equity",
                    "applicable": True,
                    "headline": (
                        f"ROE of {roe*100:.1f}% (net income / stockholders' equity; "
                        f"bank-relevant metric)"
                    ),
                    "confidence": "moderate",
                }
            )
        else:
            extras.append(_ua("roe__current_annual", "ROE unavailable — missing NI or equity"))
        extras.append(
            _ua(
                "nim",
                "NIM unavailable as a single XBRL tag — use NetInterestIncome / "
                "earning assets when both resolve",
            )
        )
        extras.append(
            _ua(
                "price_to_tbv",
                "P/TBV requires tangible book (equity − goodwill − intangibles); "
                "compute when tags resolve in bank concept map",
            )
        )

    if archetype == "insurance":
        extras.append(
            _ua(
                "combined_ratio",
                "combined ratio unavailable until PolicyholderBenefits + expense "
                "and PremiumsEarned both resolve — do not invent",
            )
        )

    if archetype in ("equity_reit", "reit_real_estate"):
        # FFO may already be in metrics from extract derived lines
        ffo = _find("ffo__current_annual")
        if not ffo:
            extras.append(
                {
                    "id": "ffo__current_annual",
                    "value": None,
                    "unit": "USD",
                    "basis_period": basis,
                    "qualifiers": ["NAREIT FFO is non-GAAP; not in XBRL company facts"],
                    "staleness": [],
                    "source_lines": ["NetIncomeLoss", "Depreciation", "GainOnSale"],
                    "computation": (
                        "NAREIT FFO ≈ NI + real-estate D&A − gains on property sales "
                        "(derived when components available)"
                    ),
                    "applicable": False,
                    "headline": (
                        "FFO unavailable — non-GAAP; not in XBRL. Derive from "
                        "NI + RE depreciation − property gains when components exist, "
                        "or mark unavailable. Never use net income as REIT primary earnings."
                    ),
                    "confidence": "none",
                }
            )
        extras.append(
            _ua(
                "nav",
                "NAV / cap-rate valuation not implemented — disclose gap; do not use NI P/E",
            )
        )

    if archetype == "mortgage_reit":
        extras.append(
            {
                "id": "mortgage_reit_method_note",
                "value": None,
                "unit": "",
                "basis_period": basis,
                "qualifiers": [],
                "staleness": [],
                "source_lines": [],
                "computation": "n/a",
                "applicable": False,
                "headline": (
                    "mortgage_reit: primary lens is book value and net interest spread "
                    "— not FFO and not industrial FCF DCF"
                ),
                "confidence": "none",
            }
        )

    if archetype == "pre_profit_growth":
        extras.append(
            {
                "id": "valuation_method_note",
                "value": None,
                "unit": "",
                "basis_period": basis,
                "qualifiers": [],
                "staleness": [],
                "source_lines": [],
                "computation": "n/a",
                "applicable": False,
                "headline": (
                    "primary valuation for pre_profit_growth is scenario path-to-"
                    "profitability — no single-point FCF DCF; do not invent a PE"
                ),
                "confidence": "none",
            }
        )

    if archetype == "cyclical_commodity":
        extras.append(
            {
                "id": "mid_cycle_normalization_note",
                "value": None,
                "unit": "",
                "basis_period": basis,
                "qualifiers": [],
                "staleness": [],
                "source_lines": [],
                "computation": "n/a",
                "applicable": False,
                "headline": (
                    "mid-cycle normalized margins/EPS not fully implemented — "
                    "trailing multiples must not be the sole headline without cycle context"
                ),
                "confidence": "none",
            }
        )

    if archetype == "utility":
        extras.append(
            _ua("rate_base", "rate base unavailable — regulated utility tags not fully mapped")
        )

    return extras


def valuation_method_for_archetype(archetype: str) -> str:
    a = "equity_reit" if archetype == "reit_real_estate" else archetype
    return {
        "bank_lender": "excess_return_on_equity",
        "insurance": "excess_return_on_equity",
        "equity_reit": "ffo_nav",
        "mortgage_reit": "book_value_spread",
        "pre_profit_growth": "path_to_profitability",
        "cyclical_commodity": "cycle_normalized_fcf_dcf",
        "midstream": "multi_stage_fcf_dcf",
        "utility": "multi_stage_fcf_dcf",
        "telecom": "multi_stage_fcf_dcf",
        "software_saas": "multi_stage_fcf_dcf",
        "mature_dividend_payer": "multi_stage_fcf_dcf",
        "asset_heavy_industrial": "multi_stage_fcf_dcf",
        "asset_heavy": "multi_stage_fcf_dcf",
        "asset_light": "multi_stage_fcf_dcf",
        "general": "multi_stage_fcf_dcf",
    }.get(a, "multi_stage_fcf_dcf")
