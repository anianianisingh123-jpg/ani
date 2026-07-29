"""Valuation Doctrine and Archetype Cards (Track A).

Pure data and functions. No I/O, no LLM calls.
"""

from __future__ import annotations
from typing import Dict, Tuple, Optional
from .exemplars import get_exemplars

DOCTRINE_CORE = """\
VALUATION FIRST PRINCIPLES (L0 Doctrine)

1. INTRINSIC VS RELATIVE SEPARATION: Separate intrinsic value (DCF / residual income) from relative value (peer comps). Do not force them to agree. Reconcile disagreements explicitly.
2. DCF VALIDITY: FCF DCF is structurally invalid for banks/lenders (use residual income / excess return on equity) and insurers (use book methods). For REITs, rely on FFO/NAV, not industrial FCF.
3. TERMINAL VALUE DOMINANCE: If terminal value > 80% of EV, the model is highly sensitive to terminal growth and WACC assumptions. Treat this as a red flag and stress-test assumptions.
4. SUM-OF-THE-PARTS DISCIPLINE: For conglomerates with distinct businesses, value them separately rather than using a blended multiple, or you get the wrong answer (e.g., three businesses bundled into one ticker).
5. DECOMPOSITION: Decompose headline metrics into their drivers. Distinguish between mix vs. rate decomposition (e.g., ARPU drop from price erosion vs. mix shift to lower-tier products).
6. RANGES OVER POINTS: Valuation is a range. Point estimates are false precision.
"""

_GENERAL_BANDS = {
    "wacc": (0.08, 0.12),
    "g_high": (0.02, 0.20),
    "g_terminal": (0.01, 0.03),
    "high_growth_years": (3, 7),
    "fade_years": (3, 7),
    "justified_multiple": (10.0, 30.0),
}

ARCHETYPE_CARDS: Dict[str, dict] = {
    "general": {
        "primary_method": "multi_stage_fcf_dcf",
        "defensible_bands": _GENERAL_BANDS,
        "cycle_traps": "Avoid extrapolating peak margins linearly.",
        "thesis_invalidators": "Growth decelerates faster than fade assumptions.",
        "multiple_set": ["forward_pe", "trailing_pe", "ev_to_ebitda"],
    },
    "bank_lender": {
        "primary_method": "excess_return_on_equity",
        "defensible_bands": {
            "wacc": (0.08, 0.12),
            "g_terminal": (0.01, 0.03),
            "justified_multiple": (0.5, 2.5),
        },
        "cycle_traps": "Under-provisioning during late expansions.",
        "thesis_invalidators": "NIM compression beyond cycle assumptions.",
        "multiple_set": ["price_to_book", "trailing_pe"],
    },
    "insurance": {
        "primary_method": "excess_return_on_equity",
        "defensible_bands": {
            "wacc": (0.07, 0.11),
            "g_terminal": (0.01, 0.03),
            "justified_multiple": (0.8, 2.5),
        },
        "cycle_traps": "Soft pricing markets combined with high catastrophe losses.",
        "thesis_invalidators": "Combined ratio consistently exceeding 100%.",
        "multiple_set": ["price_to_book", "trailing_pe"],
    },
    "equity_reit": {
        "primary_method": "ffo_nav",
        "defensible_bands": {
            "wacc": (0.06, 0.10),
            "justified_multiple": (10.0, 25.0),
        },
        "cycle_traps": "Rising cap rates impairing NAV while debt costs reset higher.",
        "thesis_invalidators": "Occupancy declining amidst oversupply.",
        "multiple_set": ["price_to_ffo"],
    },
    "mortgage_reit": {
        "primary_method": "book_value_spread",
        "defensible_bands": {
            "wacc": (0.08, 0.14),
            "justified_multiple": (0.5, 1.5),
        },
        "cycle_traps": "Yield curve inversions destroying net interest spread.",
        "thesis_invalidators": "Margin calls and forced deleveraging.",
        "multiple_set": ["price_to_book"],
    },
    "reit_real_estate": {
        "primary_method": "ffo_nav",
        "defensible_bands": {
            "wacc": (0.06, 0.10),
            "justified_multiple": (10.0, 25.0),
        },
        "cycle_traps": "Rising cap rates impairing NAV while debt costs reset higher.",
        "thesis_invalidators": "Occupancy declining amidst oversupply.",
        "multiple_set": ["price_to_ffo"],
    },
    "asset_heavy_industrial": {
        "primary_method": "multi_stage_fcf_dcf",
        "defensible_bands": {
            "wacc": (0.08, 0.11),
            "g_high": (0.02, 0.10),
            "g_terminal": (0.01, 0.03),
            "high_growth_years": (3, 5),
            "fade_years": (2, 5),
            "justified_multiple": (10.0, 20.0),
        },
        "cycle_traps": "Valuing at peak cycle margins and treating them as terminal.",
        "thesis_invalidators": "Capex cycles turning down persistently.",
        "multiple_set": ["ev_to_ebitda", "forward_pe"],
    },
    "asset_heavy": {
        "primary_method": "multi_stage_fcf_dcf",
        "defensible_bands": {
            "wacc": (0.08, 0.11),
            "g_high": (0.02, 0.10),
            "g_terminal": (0.01, 0.03),
            "high_growth_years": (3, 5),
            "fade_years": (2, 5),
            "justified_multiple": (10.0, 20.0),
        },
        "cycle_traps": "Peak margin extrapolation.",
        "thesis_invalidators": "Capital intensity eroding FCF generation.",
        "multiple_set": ["ev_to_ebitda", "forward_pe"],
    },
    "asset_light": {
        "primary_method": "multi_stage_fcf_dcf",
        "defensible_bands": {
            "wacc": (0.07, 0.10),
            "g_high": (0.05, 0.15),
            "g_terminal": (0.02, 0.03),
            "high_growth_years": (3, 7),
            "fade_years": (3, 7),
            "justified_multiple": (15.0, 35.0),
        },
        "cycle_traps": "Underestimating competition from new entrants.",
        "thesis_invalidators": "Core network effect or moat deteriorating.",
        "multiple_set": ["forward_pe", "ev_to_ebitda"],
    },
    "utility": {
        "primary_method": "multi_stage_fcf_dcf",
        "defensible_bands": {
            "wacc": (0.05, 0.08),
            "g_high": (0.02, 0.05),
            "g_terminal": (0.01, 0.025),
            "high_growth_years": (3, 5),
            "fade_years": (2, 5),
            "justified_multiple": (12.0, 22.0),
        },
        "cycle_traps": "Regulatory lag during high inflation.",
        "thesis_invalidators": "Unfavorable rate case outcomes.",
        "multiple_set": ["forward_pe", "ev_to_ebitda"],
    },
    "software_saas": {
        "primary_method": "multi_stage_fcf_dcf",
        "defensible_bands": {
            "wacc": (0.09, 0.13),
            "g_high": (0.10, 0.30),
            "g_terminal": (0.02, 0.03),
            "high_growth_years": (5, 10),
            "fade_years": (3, 7),
            "justified_multiple": (20.0, 50.0),
        },
        "cycle_traps": "Valuing SBC-heavy earnings without adjusting for dilution.",
        "thesis_invalidators": "NRR (Net Retention Rate) falling below 100%.",
        "multiple_set": ["forward_pe", "price_to_sales", "ev_to_revenue"],
    },
    "mature_dividend_payer": {
        "primary_method": "multi_stage_fcf_dcf",
        "defensible_bands": {
            "wacc": (0.06, 0.09),
            "g_high": (0.01, 0.05),
            "g_terminal": (0.01, 0.025),
            "high_growth_years": (3, 5),
            "fade_years": (2, 5),
            "justified_multiple": (12.0, 25.0),
        },
        "cycle_traps": "Chasing yield into a dividend trap.",
        "thesis_invalidators": "Payout ratio > FCF forcing a dividend cut.",
        "multiple_set": ["forward_pe", "ev_to_ebitda"],
    },
    "cyclical_commodity": {
        "primary_method": "cycle_normalized_fcf_dcf",
        "defensible_bands": {
            "wacc": (0.09, 0.14),
            "g_high": (-0.05, 0.05),
            "g_terminal": (0.0, 0.02),
            "high_growth_years": (3, 5),
            "fade_years": (2, 5),
            "justified_multiple": (5.0, 15.0),
        },
        "cycle_traps": "Valuing peak earnings with peak multiples.",
        "thesis_invalidators": "Structural demand destruction.",
        "multiple_set": ["ev_to_ebitda", "price_to_book"],
    },
    "pre_profit_growth": {
        "primary_method": "path_to_profitability",
        "defensible_bands": {
            "wacc": (0.11, 0.18),
            "g_high": (0.15, 0.40),
            "g_terminal": (0.02, 0.035),
            "high_growth_years": (5, 10),
            "fade_years": (5, 10),
            "justified_multiple": (2.0, 20.0),
        },
        "cycle_traps": "Assuming margins scale linearly forever.",
        "thesis_invalidators": "Liquidity exhaustion before reaching FCF breakeven.",
        "multiple_set": ["price_to_sales", "ev_to_revenue"],
    },
    "telecom": {
        "primary_method": "multi_stage_fcf_dcf",
        "defensible_bands": {
            "wacc": (0.06, 0.09),
            "g_high": (0.01, 0.04),
            "g_terminal": (0.01, 0.02),
            "high_growth_years": (3, 5),
            "fade_years": (2, 5),
            "justified_multiple": (8.0, 15.0),
        },
        "cycle_traps": "Underestimating massive continuous capex requirements.",
        "thesis_invalidators": "Leverage driving credit rating downgrades.",
        "multiple_set": ["ev_to_ebitda", "forward_pe"],
    },
    "midstream": {
        "primary_method": "multi_stage_fcf_dcf",
        "defensible_bands": {
            "wacc": (0.07, 0.11),
            "g_high": (0.02, 0.06),
            "g_terminal": (0.01, 0.025),
            "high_growth_years": (3, 5),
            "fade_years": (2, 5),
            "justified_multiple": (8.0, 16.0),
        },
        "cycle_traps": "Counterparty credit risk during commodity busts.",
        "thesis_invalidators": "Distribution cuts due to high leverage.",
        "multiple_set": ["ev_to_ebitda", "price_to_book"],
    },
}

def doctrine_block_for(archetype: str) -> str:
    lines = [DOCTRINE_CORE]
    card = ARCHETYPE_CARDS.get(archetype)
    if card:
        lines.append(f"\\n=== ARCHETYPE CARD: {archetype} ===")
        lines.append(f"- Primary Method: {card['primary_method']}")
        lines.append(f"- Cycle Traps: {card['cycle_traps']}")
        lines.append(f"- Thesis Invalidators: {card['thesis_invalidators']}")
        lines.append(f"- Relevant Multiples: {', '.join(card['multiple_set'])}")
    return "\n".join(lines)

def band_for(archetype: str, parameter: str) -> Optional[Tuple[float, float]]:
    card = ARCHETYPE_CARDS.get(archetype)
    if not card:
        card = ARCHETYPE_CARDS["general"]
    bands = card.get("defensible_bands", _GENERAL_BANDS)
    return bands.get(parameter)

def exemplar_block_for(archetype: str) -> Tuple[str, bool]:
    ex_text = get_exemplars(archetype)
    if not ex_text:
        return ("", False)
    return (f"=== IN-CONTEXT EXEMPLARS (Reasoning Moves) ===\n{ex_text}", True)
