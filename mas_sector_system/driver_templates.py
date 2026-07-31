from typing import Optional, List, Tuple, Dict, Any

DRIVER_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "general": {
        "output_kind": "eps_fcf",
        "drivers": [
            {
                "id": "segment_growth",
                "human_label": "Segment Revenue Growth",
                "unit": "rate",
                "hard_clamp": (-1.0, 10.0),
                "history_relative_band": (-0.5, 0.5),
                "evidence_justification": "Must cite specific segment demand trends, product cycles, or market share shifts from the filing."
            },
            {
                "id": "gross_margin",
                "human_label": "Gross Margin",
                "unit": "ratio",
                "hard_clamp": (0.0, 1.0),
                "history_relative_band": (-0.1, 0.1),
                "evidence_justification": "Must cite pricing power, product mix shifts, or unit cost leverage from recent periods."
            },
            {
                "id": "opex_growth",
                "human_label": "Operating Expense Growth",
                "unit": "rate",
                "hard_clamp": (-1.0, 5.0),
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
                "hard_clamp": (-1.0, 10.0),
                "history_relative_band": (-0.5, 0.5),
                "evidence_justification": "Must cite subscription momentum, net revenue retention (NRR) trends, or new product adoption."
            },
            {
                "id": "gross_margin",
                "human_label": "Gross Margin",
                "unit": "ratio",
                "hard_clamp": (0.0, 1.0),
                "history_relative_band": (-0.05, 0.05),
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

def drivers_for(archetype: str) -> List[Dict[str, Any]]:
    """
    Return the list of argued drivers for the given archetype.
    Returns an empty list if the template is not found, enabling the caller to fall back to general.
    """
    return DRIVER_TEMPLATES.get(archetype, {}).get("drivers", [])

def band_for_driver(archetype: str, driver: str) -> Optional[Tuple[float, float]]:
    """
    Return the history-relative band rule for a specific driver within an archetype.
    """
    template = DRIVER_TEMPLATES.get(archetype)
    if not template:
        return None
        
    for d in template.get("drivers", []):
        if d["id"] == driver:
            return d["history_relative_band"]
            
        # Support dynamically named segment growth drivers (e.g., segment_growth_1)
        if driver.startswith("segment_growth_") and d["id"] == "segment_growth":
            return d["history_relative_band"]
            
    return None

def forecast_output_kind(archetype: str) -> str:
    """
    Return the forecast output kind for the archetype (e.g., eps_fcf, ffo, residual_income, book_value).
    Defaults to eps_fcf if the archetype is not defined.
    """
    template = DRIVER_TEMPLATES.get(archetype)
    if not template:
        return "eps_fcf"
    return template.get("output_kind", "eps_fcf")
