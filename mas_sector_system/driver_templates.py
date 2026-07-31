"""Layer-2 driver templates, per `FORWARD_ESTIMATE_DESIGN.md` §5.2.

Pure data and pure functions. No I/O, no LLM, no import from `agents.py`.

The template is the versioned, reviewable half of the forecast: it decides *which*
dials exist and how far each may be turned. The model argues values within them and
owns no figures (§2, §5.5). Two conventions matter to anyone reading the data below:

`hard_clamp` — `(min, max)` absolute bounds from §8.1. A value outside is rejected in
code, not warned about.

`history_relative_band` — `(low_offset, high_offset)` from §8.2, applied to the
*observed range*: the floor is `hist_min + low_offset` and the ceiling is
`hist_max + high_offset`. Both offsets are decimals, not percentages, matching the
argued-input contract. These are soft: a value outside is recorded in `band_dissents`
and surfaced as a stated dissent, not rejected. Note the asymmetry the spec asks for
on gross margin — an analyst may argue margin down further than up.
"""

import copy
from typing import Optional, List, Tuple, Dict, Any

# Forecast output shape per archetype (§5.2, final column). Kept separate from
# DRIVER_TEMPLATES on purpose: the output *shape* is doctrine and is knowable today,
# while the driver *sets* for financials are held until the 8-ticker baseline (FWD-07)
# shows what actually parses for a bank, an insurer and a REIT. Without this map a
# bank silently received an EPS/FCF forecast, which is the wrong instrument entirely.
#
# `insurance` maps to book_value: §5.2 states the chain as net income → book value →
# ROE, and ROE is a ratio read off book value rather than a fourth output shape.
OUTPUT_KINDS: Dict[str, str] = {
    "general": "eps_fcf",
    "asset_light": "eps_fcf",
    "software_saas": "eps_fcf",
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

DRIVER_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "general": {
        "output_kind": "eps_fcf",
        "drivers": [
            {
                "id": "segment_growth",
                "human_label": "Segment Revenue Growth",
                "unit": "rate",
                "hard_clamp": (-0.50, 2.00),
                "history_relative_band": (-0.5, 0.5),
                "evidence_justification": "Must cite specific segment demand trends, product cycles, or market share shifts from the filing."
            },
            {
                "id": "gross_margin",
                "human_label": "Gross Margin",
                "unit": "ratio",
                "hard_clamp": (0.0, 0.99),
                "history_relative_band": (-0.10, 0.05),
                "evidence_justification": "Must cite pricing power, product mix shifts, or unit cost leverage from recent periods."
            },
            {
                "id": "opex_growth",
                "human_label": "Operating Expense Growth",
                "unit": "rate",
                "hard_clamp": (-0.30, 1.50),
                "history_relative_band": (-0.3, 0.3),
                "evidence_justification": "Must cite management guidance on cost control, headcount changes, or reinvestment intensity."
            }
        ]
    },
    "software_saas": {
        "output_kind": "eps_fcf",
        "drivers": [
            {
                "id": "segment_growth",
                "human_label": "Segment Revenue Growth",
                "unit": "rate",
                "hard_clamp": (-0.50, 2.00),
                "history_relative_band": (-0.5, 0.5),
                "evidence_justification": "Must cite subscription momentum, net revenue retention (NRR) trends, or new product adoption."
            },
            {
                "id": "gross_margin",
                "human_label": "Gross Margin",
                "unit": "ratio",
                "hard_clamp": (0.0, 0.99),
                "history_relative_band": (-0.10, 0.05),
                "evidence_justification": "Must cite hosting efficiency, professional services mix, or scale leverage."
            },
            {
                "id": "sm_margin",
                "human_label": "S&M as % of Revenue",
                "unit": "ratio",
                "hard_clamp": (0.0, 2.0),
                "history_relative_band": (-0.15, 0.15),
                "evidence_justification": "Must cite customer acquisition cost (CAC) trends, go-to-market efficiency, or sales hiring plans."
            },
            {
                "id": "rd_margin",
                "human_label": "R&D as % of Revenue",
                "unit": "ratio",
                "hard_clamp": (0.0, 1.0),
                "history_relative_band": (-0.1, 0.1),
                "evidence_justification": "Must cite platform expansion, AI integration costs, or product development lifecycle."
            }
        ]
    }
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
        return "segment_growth"
    return head


def drivers_for(archetype: str) -> Tuple[List[Dict[str, Any]], bool]:
    """Return `(drivers, is_native)` for the given archetype.

    `is_native` is False when no template exists yet and the `general` set was
    substituted. §8 requires that case to run consolidated-only **and flagged** —
    returning the general drivers unflagged would let a bank's forecast pass as if
    it had been modelled on a bank's dials.
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


def forecast_output_kind(archetype: str) -> str:
    """Return the forecast output shape: eps_fcf | ffo | residual_income | book_value.

    Answered from §5.2 for all 16 archetypes, including the 14 whose driver sets are
    still outstanding. A caller that can only build `eps_fcf` must check this and
    refuse the others rather than produce an EPS forecast for a REIT.
    """
    return OUTPUT_KINDS.get(archetype, "eps_fcf")
