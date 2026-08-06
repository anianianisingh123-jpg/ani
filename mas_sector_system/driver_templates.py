"""Layer-2 driver templates, per `FORWARD_ESTIMATE_DESIGN.md` §5.2.

Pure data and pure functions. No I/O, no LLM, no import from `agents.py`.

The template is the versioned, reviewable half of the forecast: it decides *which*
dials exist and how far each may be turned. The model argues values within them and
owns no figures (§2, §5.5). Four conventions matter to anyone reading the data below:

`hard_clamp` — `(min, max)` absolute bounds. Where §8.1 names a driver its numbers
are authoritative and are used verbatim; the rest are template-author choices marked
`SPEC-GAP` in a comment, pending a product decision.

`history_relative_band` — `(low_offset, high_offset)` from §8.2, applied to the
*observed range*: floor is `hist_min + low_offset`, ceiling is `hist_max + high_offset`.
Both are decimals, not percentages. Soft — a value outside is recorded in
`band_dissents` and surfaced as a stated dissent, not rejected. Note the asymmetry the
spec asks for on gross margin: margin may be argued down further than up.

`basis_status` / `basis` — which history the driver departs from, per §7's mandatory
`historical_basis`. Three cases, and the distinction is the point:
  `profile`      — `basis` names a series `forecast_engine.historical_profile()`
                   computes today. The driver is ready to argue.
  `derivable`    — `basis` names filing lines that *do* parse, but no ratio is computed
                   from them yet. Needs a profile extension before the driver is usable.
  `unavailable`  — no filing-derived history exists at any depth. Occupancy, subscribers,
                   throughput and realised price are operating disclosures we do not
                   collect. A model asked to argue one of these must invent its basis,
                   which is precisely what §7 exists to forbid — so these are reported
                   by `ungrounded_drivers()` and must be refused, not quietly defaulted.

**No driver is a currency amount.** §2 bounds the model's output surface to scalars and
enums, so price, ARPU, fee-per-unit and unit-cost dials are all expressed as *changes*
rather than levels.
"""

import copy
from typing import Optional, List, Tuple, Dict, Any

# Forecast output shape per archetype (§5.2, final column). Kept separate from
# DRIVER_TEMPLATES on purpose: the output *shape* is doctrine and was knowable before
# any driver set existed. Without it, every archetype lacking a template silently
# reported eps_fcf and a bank received an earnings forecast.
#
# `insurance` maps to book_value: §5.2 states the chain as net income → book value →
# ROE, and ROE is a ratio read off book value rather than a fourth output shape.
OUTPUT_KINDS: Dict[str, str] = {
    "general": "eps_fcf",
    "asset_light": "eps_fcf",
    "software_saas": "eps_fcf",
    "semiconductor": "eps_fcf",
    "asset_heavy": "eps_fcf",
    "asset_heavy_industrial": "eps_fcf",
    "mature_dividend_payer": "eps_fcf",
    "pre_profit_growth": "eps_fcf",
    "cyclical_commodity": "eps_fcf",
    "midstream": "eps_fcf",
    "telecom": "eps_fcf",
    "utility": "eps_fcf",
    "bank_lender": "residual_income",
    "insurance": "book_value",
    "equity_reit": "ffo",
    "reit_real_estate": "ffo",
    "mortgage_reit": "book_value",
}


def _driver(
    id: str,
    label: str,
    unit: str,
    clamp: Tuple[float, float],
    band: Tuple[float, float],
    evidence: str,
    basis_status: str,
    basis: Any = None,
) -> Dict[str, Any]:
    """Build one driver record. A constructor rather than 16 hand-written literals —
    the fields stay explicit at each call site, which is what makes the table
    reviewable, without 800 lines of repeated punctuation."""
    return {
        "id": id,
        "human_label": label,
        "unit": unit,
        "hard_clamp": clamp,
        "history_relative_band": band,
        "evidence_justification": evidence,
        "basis_status": basis_status,
        "basis": basis,
    }


# §8.1 values, quoted once so no template can drift from them.
_CLAMP_GROWTH = (-0.50, 2.00)
_CLAMP_GROSS_MARGIN = (0.0, 0.99)
_CLAMP_OPEX_GROWTH = (-0.30, 1.50)
_CLAMP_NIM = (0.0, 0.15)
_CLAMP_PROVISION = (0.0, 0.10)
_CLAMP_COMBINED_RATIO = (0.50, 1.50)
_CLAMP_OCCUPANCY = (0.50, 1.00)
_CLAMP_CAPEX_INTENSITY = (0.0, 0.60)

# §8.2 values.
_BAND_GROWTH = (-0.5, 0.5)
_BAND_GROSS_MARGIN = (-0.10, 0.05)

# SPEC-GAP: §8.1 names none of the following. Chosen to be wide enough not to bind on
# a defensible argument and narrow enough to catch a runaway one. Revisit with §8.1.
_BAND_MARGIN_LIKE = (-0.05, 0.05)
_BAND_RATE_LIKE = (-0.25, 0.25)
_CLAMP_RATIO_OF_REVENUE = (0.0, 1.0)
_CLAMP_PRICE_CHANGE = (-0.60, 1.00)
_CLAMP_VOLUME_CHANGE = (-0.50, 1.00)

_SEGMENT_GROWTH = "segment_growth"


def _general_drivers() -> List[Dict[str, Any]]:
    return [
        _driver(
            _SEGMENT_GROWTH, "Segment Revenue Growth", "rate",
            _CLAMP_GROWTH, _BAND_GROWTH,
            "Must cite specific segment demand trends, product cycles, or market share "
            "shifts from the filing.",
            "profile", "revenue_growth",
        ),
        _driver(
            "gross_margin", "Gross Margin", "ratio",
            _CLAMP_GROSS_MARGIN, _BAND_GROSS_MARGIN,
            "Must cite pricing power, product mix shifts, or unit cost leverage from "
            "recent periods.",
            "profile", "gross_margin",
        ),
        _driver(
            "opex_growth", "Operating Expense Growth", "rate",
            _CLAMP_OPEX_GROWTH, (-0.3, 0.3),
            "Must cite management guidance on cost control, headcount changes, or "
            "reinvestment intensity.",
            "profile", "opex_growth",
        ),
    ]


DRIVER_TEMPLATES: Dict[str, Dict[str, Any]] = {
    # ── Standard operating shapes ────────────────────────────────────────────
    "general": {"output_kind": "eps_fcf", "drivers": _general_drivers()},
    # §5.2 groups asset_light with general.
    "asset_light": {"output_kind": "eps_fcf", "drivers": _general_drivers()},
    # Semiconductors take the general operating shape — revenue, gross margin,
    # opex all parse and are already computed — but the evidence bar is
    # cycle-specific, because the trap here is extrapolating a peak-cycle
    # margin as the run-rate. Added with the archetype itself (2026-08-04);
    # the three dials are `profile`-grounded, so this is usable today.
    "semiconductor": {
        "output_kind": "eps_fcf",
        "drivers": [
            _driver(
                _SEGMENT_GROWTH, "Segment Revenue Growth", "rate",
                _CLAMP_GROWTH, _BAND_GROWTH,
                "Must cite design wins, node transitions, end-market inventory "
                "position, or a named customer's build plan — not an industry "
                "forecast.",
                "profile", "revenue_growth",
            ),
            _driver(
                "gross_margin", "Gross Margin", "ratio",
                _CLAMP_GROSS_MARGIN, _BAND_GROSS_MARGIN,
                "Must cite mix, pricing, yield, or utilization. Peak-cycle "
                "margin is not a run-rate: state where in the cycle this sits.",
                "profile", "gross_margin",
            ),
            _driver(
                "opex_growth", "Operating Expense Growth", "rate",
                _CLAMP_OPEX_GROWTH, _BAND_RATE_LIKE,
                "Must cite R&D roadmap commitments or headcount plans; semis "
                "rarely cut R&D through a downcycle, so a falling opex "
                "assumption needs a stated reason.",
                "profile", "opex_growth",
            ),
        ],
    },
    "software_saas": {
        "output_kind": "eps_fcf",
        "drivers": [
            _driver(
                _SEGMENT_GROWTH, "Segment Revenue Growth", "rate",
                _CLAMP_GROWTH, _BAND_GROWTH,
                "Must cite subscription momentum, net revenue retention (NRR) trends, "
                "or new product adoption.",
                "profile", "revenue_growth",
            ),
            _driver(
                "gross_margin", "Gross Margin", "ratio",
                _CLAMP_GROSS_MARGIN, _BAND_GROSS_MARGIN,
                "Must cite hosting efficiency, professional services mix, or scale "
                "leverage.",
                "profile", "gross_margin",
            ),
            _driver(
                "sm_margin", "S&M as % of Revenue", "ratio",
                _CLAMP_RATIO_OF_REVENUE, (-0.15, 0.15),
                "Must cite customer acquisition cost (CAC) trends, go-to-market "
                "efficiency, or sales hiring plans.",
                "derivable", ["SellingGeneralAndAdministrativeExpense", "Revenues"],
            ),
            _driver(
                "rd_margin", "R&D as % of Revenue", "ratio",
                _CLAMP_RATIO_OF_REVENUE, (-0.1, 0.1),
                "Must cite platform expansion, AI integration costs, or product "
                "development lifecycle.",
                "derivable", ["ResearchAndDevelopmentExpense", "Revenues"],
            ),
        ],
    },
    "asset_heavy": {
        "output_kind": "eps_fcf",
        "drivers": [
            _driver(
                _SEGMENT_GROWTH, "Volume / Revenue Growth", "rate",
                _CLAMP_GROWTH, _BAND_GROWTH,
                "Must cite order backlog, utilisation, or end-market demand from the "
                "filing.",
                "profile", "revenue_growth",
            ),
            _driver(
                "gross_margin", "Gross Margin", "ratio",
                _CLAMP_GROSS_MARGIN, _BAND_GROSS_MARGIN,
                "Must cite input costs, fixed-cost absorption, or pricing actions.",
                "profile", "gross_margin",
            ),
            _driver(
                "capex_intensity", "Capex as % of Revenue", "ratio",
                _CLAMP_CAPEX_INTENSITY, _BAND_MARGIN_LIKE,
                "Must cite announced capacity programmes, maintenance requirements, or "
                "stated capital budgets.",
                "profile", "capex_pct_revenue",
            ),
        ],
    },
    "asset_heavy_industrial": {
        "output_kind": "eps_fcf",
        "drivers": [
            _driver(
                _SEGMENT_GROWTH, "Volume / Revenue Growth", "rate",
                _CLAMP_GROWTH, _BAND_GROWTH,
                "Must cite order backlog, utilisation, or end-market demand from the "
                "filing.",
                "profile", "revenue_growth",
            ),
            _driver(
                "gross_margin", "Gross Margin", "ratio",
                _CLAMP_GROSS_MARGIN, _BAND_GROSS_MARGIN,
                "Must cite input costs, fixed-cost absorption, or pricing actions.",
                "profile", "gross_margin",
            ),
            _driver(
                "capex_intensity", "Capex as % of Revenue", "ratio",
                _CLAMP_CAPEX_INTENSITY, _BAND_MARGIN_LIKE,
                "Must cite announced capacity programmes, maintenance requirements, or "
                "stated capital budgets.",
                "profile", "capex_pct_revenue",
            ),
        ],
    },
    "mature_dividend_payer": {
        "output_kind": "eps_fcf",
        "drivers": [
            _driver(
                _SEGMENT_GROWTH, "Organic Revenue Growth", "rate",
                _CLAMP_GROWTH, _BAND_GROWTH,
                "Must cite volume trends net of acquisitions and currency, as disclosed.",
                "profile", "revenue_growth",
            ),
            _driver(
                "pricing_change", "Realised Pricing Change", "rate",
                _CLAMP_PRICE_CHANGE, _BAND_RATE_LIKE,
                "Must cite disclosed price/mix contribution to revenue growth.",
                "unavailable",
            ),
            _driver(
                "gross_margin", "Gross Margin", "ratio",
                _CLAMP_GROSS_MARGIN, _BAND_GROSS_MARGIN,
                "Must cite commodity input costs, hedging, or productivity programmes.",
                "profile", "gross_margin",
            ),
            _driver(
                "opex_growth", "Operating Expense Growth", "rate",
                _CLAMP_OPEX_GROWTH, (-0.3, 0.3),
                "Must cite advertising intensity, restructuring, or overhead programmes.",
                "profile", "opex_growth",
            ),
        ],
    },
    "pre_profit_growth": {
        "output_kind": "eps_fcf",
        "drivers": [
            _driver(
                _SEGMENT_GROWTH, "Revenue Growth", "rate",
                _CLAMP_GROWTH, _BAND_GROWTH,
                "Must cite cohort behaviour, pipeline, or capacity to serve demand.",
                "profile", "revenue_growth",
            ),
            _driver(
                "gross_margin", "Gross Margin Trajectory", "ratio",
                _CLAMP_GROSS_MARGIN, _BAND_GROSS_MARGIN,
                "Must cite unit economics and the path to scale, not an aspiration.",
                "profile", "gross_margin",
            ),
            _driver(
                "opex_growth", "Operating Expense Growth", "rate",
                _CLAMP_OPEX_GROWTH, (-0.3, 0.3),
                "Must cite hiring plans and stated cash discipline. Runway is derived "
                "from this, not argued separately.",
                "profile", "opex_growth",
            ),
        ],
    },
    "cyclical_commodity": {
        "output_kind": "eps_fcf",
        "drivers": [
            _driver(
                "volume_change", "Production Volume Change", "rate",
                _CLAMP_VOLUME_CHANGE, _BAND_RATE_LIKE,
                "Must cite disclosed production guidance, field decline rates, or "
                "capacity additions.",
                "unavailable",
            ),
            _driver(
                "realised_price_change", "Realised Price Change", "rate",
                _CLAMP_PRICE_CHANGE, _BAND_RATE_LIKE,
                "Must cite realised price disclosure and hedge position, not a forward "
                "curve view alone.",
                "unavailable",
            ),
            _driver(
                "unit_cash_cost_change", "Unit Cash Cost Change", "rate",
                _CLAMP_PRICE_CHANGE, _BAND_RATE_LIKE,
                "Must cite disclosed cost per unit and its recent direction.",
                "unavailable",
            ),
        ],
    },
    "midstream": {
        "output_kind": "eps_fcf",
        "drivers": [
            _driver(
                "throughput_change", "Throughput Volume Change", "rate",
                _CLAMP_VOLUME_CHANGE, _BAND_RATE_LIKE,
                "Must cite contracted volumes, basin production trends, or committed "
                "capacity.",
                "unavailable",
            ),
            _driver(
                "fee_per_unit_change", "Fee per Unit Change", "rate",
                _CLAMP_PRICE_CHANGE, _BAND_RATE_LIKE,
                "Must cite tariff escalators or recontracting terms as disclosed.",
                "unavailable",
            ),
            _driver(
                "maintenance_capex_intensity", "Maintenance Capex as % of Revenue",
                "ratio", _CLAMP_CAPEX_INTENSITY, _BAND_MARGIN_LIKE,
                "Must cite the maintenance-versus-growth capex split as disclosed.",
                "profile", "capex_pct_revenue",
            ),
        ],
    },
    "telecom": {
        "output_kind": "eps_fcf",
        "drivers": [
            _driver(
                "subscriber_change", "Subscriber Growth", "rate",
                _CLAMP_VOLUME_CHANGE, _BAND_RATE_LIKE,
                "Must cite net adds and churn as disclosed, by segment where given.",
                "unavailable",
            ),
            _driver(
                "arpu_change", "ARPU Change", "rate",
                _CLAMP_PRICE_CHANGE, _BAND_RATE_LIKE,
                "Must cite disclosed ARPU trend and pricing actions.",
                "unavailable",
            ),
            _driver(
                "capex_intensity", "Capex as % of Revenue", "ratio",
                _CLAMP_CAPEX_INTENSITY, _BAND_MARGIN_LIKE,
                "Must cite network build programmes or spectrum commitments.",
                "profile", "capex_pct_revenue",
            ),
        ],
    },
    "utility": {
        "output_kind": "eps_fcf",
        "drivers": [
            _driver(
                "rate_base_growth", "Rate Base Growth", "rate",
                _CLAMP_GROWTH, _BAND_RATE_LIKE,
                "Must cite the approved capital plan and regulatory filings.",
                "unavailable",
            ),
            _driver(
                "allowed_roe", "Allowed Return on Equity", "ratio",
                (0.0, 0.20), _BAND_MARGIN_LIKE,
                "Must cite the authorised ROE from the most recent rate case.",
                "unavailable",
            ),
            _driver(
                "opex_growth", "O&M Expense Growth", "rate",
                _CLAMP_OPEX_GROWTH, (-0.3, 0.3),
                "Must cite disclosed O&M trends and any regulatory cost recovery.",
                "profile", "opex_growth",
            ),
        ],
    },
    # ── Financials ───────────────────────────────────────────────────────────
    # Every line these depend on parses today (verified live against JPM, PLD).
    # What is missing is the ratio layer: historical_profile computes none of NIM,
    # provision rate, efficiency ratio or combined ratio, so they are `derivable`
    # rather than `profile` and need a profile extension before they can be argued.
    "bank_lender": {
        "output_kind": "residual_income",
        "drivers": [
            _driver(
                "net_interest_margin", "Net Interest Margin", "ratio",
                _CLAMP_NIM, _BAND_MARGIN_LIKE,
                "Must cite deposit beta, asset repricing, or the disclosed rate "
                "sensitivity table.",
                "derivable", ["NetInterestIncome", "LoansNet", "InvestmentSecurities"],
            ),
            _driver(
                "earning_asset_growth", "Earning Asset Growth", "rate",
                _CLAMP_GROWTH, _BAND_GROWTH,
                "Must cite loan demand, deposit trends, or stated balance-sheet "
                "capacity.",
                "derivable", ["LoansNet", "InvestmentSecurities"],
            ),
            _driver(
                "provision_rate", "Provision Rate", "ratio",
                _CLAMP_PROVISION, _BAND_MARGIN_LIKE,
                "Must cite charge-off history, reserve coverage, or the disclosed "
                "macro scenario weighting.",
                "derivable", ["ProvisionForCreditLosses", "LoansNet",
                              "AllowanceForCreditLosses"],
            ),
            _driver(
                "fee_income_growth", "Fee Income Growth", "rate",
                _CLAMP_GROWTH, _BAND_GROWTH,
                "Must cite the disclosed noninterest income mix and its drivers.",
                "derivable", ["NoninterestIncome"],
            ),
            _driver(
                "efficiency_ratio", "Efficiency Ratio", "ratio",
                (0.30, 1.00), _BAND_MARGIN_LIKE,
                "Must cite expense programmes against revenue, as disclosed.",
                "derivable", ["NoninterestExpense", "NetInterestIncome",
                              "NoninterestIncome"],
            ),
        ],
    },
    "insurance": {
        "output_kind": "book_value",
        "drivers": [
            _driver(
                "premium_growth", "Premium Growth", "rate",
                _CLAMP_GROWTH, _BAND_GROWTH,
                "Must cite rate change, exposure growth, and retention as disclosed.",
                "derivable", ["PremiumsEarned"],
            ),
            _driver(
                "combined_ratio", "Combined Ratio", "ratio",
                _CLAMP_COMBINED_RATIO, _BAND_MARGIN_LIKE,
                "Must cite loss trend, catastrophe load, and prior-year development "
                "separately — a single blended number is not an argument.",
                "derivable", ["PolicyholderBenefits", "UnderwritingExpense",
                              "PremiumsEarned"],
            ),
            _driver(
                "investment_yield", "Investment Yield", "ratio",
                (0.0, 0.15), _BAND_MARGIN_LIKE,
                "Must cite portfolio duration, new-money yield, and reinvestment pace.",
                "derivable", ["NetInvestmentIncome", "InvestmentsInsurance"],
            ),
        ],
    },
    # REITs are the one place §5.2's named dials outrun the data. Occupancy,
    # same-store NOI and development yield are property-level operating disclosures
    # that do not appear in the statements we parse at any depth — verified live
    # against PLD. They ship marked `unavailable` so the critique layer refuses them
    # rather than letting a model invent the history it claims to depart from.
    "equity_reit": {
        "output_kind": "ffo",
        "drivers": [
            _driver(
                "occupancy", "Occupancy", "ratio",
                _CLAMP_OCCUPANCY, _BAND_MARGIN_LIKE,
                "Must cite disclosed occupancy by portfolio and leasing pipeline.",
                "unavailable",
            ),
            _driver(
                "same_store_noi_growth", "Same-Store NOI Growth", "rate",
                (-0.30, 0.50), _BAND_RATE_LIKE,
                "Must cite released spreads, escalators, and expense recovery.",
                "unavailable",
            ),
            _driver(
                "development_yield", "Development Yield", "ratio",
                (0.0, 0.25), _BAND_MARGIN_LIKE,
                "Must cite the disclosed development pipeline and stabilised yields.",
                "unavailable",
            ),
            _driver(
                "ga_growth", "G&A Growth", "rate",
                _CLAMP_OPEX_GROWTH, (-0.3, 0.3),
                "Must cite disclosed general and administrative expense trends.",
                "derivable", ["SellingGeneralAndAdministrativeExpense"],
            ),
        ],
    },
    "reit_real_estate": {
        "output_kind": "ffo",
        "drivers": [
            _driver(
                "occupancy", "Occupancy", "ratio",
                _CLAMP_OCCUPANCY, _BAND_MARGIN_LIKE,
                "Must cite disclosed occupancy by portfolio and leasing pipeline.",
                "unavailable",
            ),
            _driver(
                "same_store_noi_growth", "Same-Store NOI Growth", "rate",
                (-0.30, 0.50), _BAND_RATE_LIKE,
                "Must cite released spreads, escalators, and expense recovery.",
                "unavailable",
            ),
            _driver(
                "development_yield", "Development Yield", "ratio",
                (0.0, 0.25), _BAND_MARGIN_LIKE,
                "Must cite the disclosed development pipeline and stabilised yields.",
                "unavailable",
            ),
            _driver(
                "ga_growth", "G&A Growth", "rate",
                _CLAMP_OPEX_GROWTH, (-0.3, 0.3),
                "Must cite disclosed general and administrative expense trends.",
                "derivable", ["SellingGeneralAndAdministrativeExpense"],
            ),
        ],
    },
    "mortgage_reit": {
        "output_kind": "book_value",
        "drivers": [
            _driver(
                "net_interest_spread", "Net Interest Spread", "ratio",
                _CLAMP_NIM, _BAND_MARGIN_LIKE,
                "Must cite asset yield against funding cost and the hedge position.",
                "derivable", ["NetInterestIncome", "MortgageBackedSecurities"],
            ),
            _driver(
                "leverage", "Leverage (Debt / Equity)", "multiple",
                (0.0, 12.0), (-1.0, 1.0),
                "Must cite disclosed leverage policy and repo capacity.",
                "derivable", ["RepurchaseAgreements", "TotalEquity"],
            ),
            _driver(
                "book_value_change", "Book Value per Share Change", "rate",
                (-0.50, 0.50), _BAND_RATE_LIKE,
                "Must cite mark-to-market moves on the portfolio and hedge "
                "effectiveness — this is the output measure, argue it explicitly.",
                "derivable", ["TotalEquity",
                              "WeightedAverageNumberOfDilutedSharesOutstanding"],
            ),
        ],
    },
}

_FALLBACK_ARCHETYPE = "general"


def _normalise_driver_id(driver: str) -> str:
    """Map an argued-driver name onto the template id that governs it.

    §7 names revenue drivers per segment (`revenue_growth.data_center`) and the
    forecast engine also accepts `segment_growth_1`. Both are governed by the
    template's single `segment_growth` entry — without this, a per-segment driver
    resolves to no band at all and the §8.2 dissent check has nothing to test.
    """
    head = driver.split(".", 1)[0]
    if head == "revenue_growth" or head.startswith("segment_growth"):
        return _SEGMENT_GROWTH
    return head


def drivers_for(archetype: str) -> Tuple[List[Dict[str, Any]], bool]:
    """Return `(drivers, is_native)` for the given archetype.

    `is_native` is False when no template exists and the `general` set was
    substituted. §8 requires that case to run consolidated-only **and flagged** —
    returning the general drivers unflagged would let a forecast pass as if it had
    been modelled on the right dials.
    """
    template = DRIVER_TEMPLATES.get(archetype)
    if template is not None:
        return (copy.deepcopy(template.get("drivers", [])), True)
    fallback = DRIVER_TEMPLATES[_FALLBACK_ARCHETYPE]
    return (copy.deepcopy(fallback["drivers"]), False)


def band_for_driver(archetype: str, driver: str) -> Optional[Tuple[float, float]]:
    """Return the §8.2 history-relative band for one driver, or None if the template
    does not govern it. Falls back to the `general` template on the same terms as
    `drivers_for`, so a substituted archetype still has bands to check against.
    """
    template = DRIVER_TEMPLATES.get(archetype) or DRIVER_TEMPLATES[_FALLBACK_ARCHETYPE]
    wanted = _normalise_driver_id(driver)
    for d in template.get("drivers", []):
        if d["id"] == wanted:
            return d["history_relative_band"]
    return None


def ungrounded_drivers(archetype: str) -> List[str]:
    """Driver ids with no filing-derived history at any depth.

    §7 makes `historical_basis` mandatory: a driver that cannot name the trend it
    departs from is a guess. These can never satisfy it from filings alone, so a
    caller must refuse them rather than let the model supply its own basis. Empty
    for every archetype whose dials are fully grounded.
    """
    template = DRIVER_TEMPLATES.get(archetype) or DRIVER_TEMPLATES[_FALLBACK_ARCHETYPE]
    return [d["id"] for d in template.get("drivers", [])
            if d.get("basis_status") == "unavailable"]


def forecast_output_kind(archetype: str) -> str:
    """Return the forecast output shape: eps_fcf | ffo | residual_income | book_value.

    Answered from §5.2 for all 16 archetypes. A caller that can only build `eps_fcf`
    must check this and refuse the others rather than produce an earnings forecast
    for a REIT.
    """
    return OUTPUT_KINDS.get(archetype, "eps_fcf")
