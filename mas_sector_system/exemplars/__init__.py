"""Exemplar library (VAL-04)."""

from typing import Tuple

_GENERAL_EXEMPLARS = """\
[EXEMPLAR: Steelman -> mechanism -> concede]
[INPUT]
=== CANONICAL METRICS ===
- gross margin of 76.0% (current annual)
=== SEC FILING SUMMARY ===
MD&A notes hyperscalers extending GPU depreciation schedules.
[OUTPUT]
Where the bear lands real blows: The bear case argues that gross margins are at cyclical peaks and must mean-revert. This is structurally supported by hyperscalers extending GPU depreciation schedules, which mechanically lifted margins this quarter. While we maintain our base case, we concede that this accounting tailwind is a one-time benefit and future margin expansion must be driven purely by mix shift, which remains an open question.

[EXEMPLAR: Discount rate tied to a named company risk]
[INPUT]
=== DETERMINISTIC DCF ENGINE (Python — source of truth for math) ===
Method: multi_stage_fcf_dcf | Confidence: moderate
Assumptions: WACC=10.0%, g_high=3.0%, g_terminal=2.5%, explicit=5+5 years
=== SEC FILING SUMMARY ===
Apple insourcing its modem components remains a key risk. Apple currently represents ~$7bn of total revenues.
[OUTPUT]
We apply a 12.0% WACC (above the 10.0% sector default) to reflect specific customer concentration risks, highlighting the potential lost revenues from Apple insourcing its modem components, which currently constitutes ~$7bn of the top line.

[EXEMPLAR: Like-for-like adjustment]
[INPUT]
=== CANONICAL METRICS ===
- revenue growth of 2.0% (current annual vs prior annual; YoY)
=== SEC FILING SUMMARY ===
Excluding the impact of the Sun Art and Trendyol divestitures, underlying revenue growth was 10.0%.
[OUTPUT]
While reported revenue growth is 2.0%, underlying like-for-like growth is 10.0% when excluding the impact of the Sun Art and Trendyol divestitures. This demonstrates the core business is compounding faster than the headline figure suggests.

[EXEMPLAR: Mix vs rate decomposition]
[INPUT]
=== CANONICAL METRICS ===
- ARPU of $66 (current annual)
- ARPU of $86 (prior annual)
=== BUSINESS OVERVIEW ===
Growth is driven by international expansion into emerging markets, which utilize lower-tier, lower-priced plans.
[OUTPUT]
The ARPU decline from $86 to $66 is optically concerning, but decomposing the driver reveals it is primarily a geographic mix shift toward lower-tier plans in emerging markets rather than price erosion in the core premium base. This expands the total addressable market without compromising the margin profile of existing cohorts.
"""

_SOFTWARE_SAAS_EXEMPLARS = """\
[EXEMPLAR: Variant perception frame]
[INPUT]
=== CANONICAL METRICS ===
- revenue growth of 10.8% (current annual vs prior annual)
- operating margin of 30.5% (current annual)
=== DETERMINISTIC PEER COMPS (peer multiples from yfinance; subject standalone multiples prefer canonical_metrics when present) ===
Subject CRM (source=canonical_metrics_preferred): P/E f=27.3x
Peer medians: P/E f=24.1x
[OUTPUT]
Consensus assumes that the deceleration in top-line growth (10.8%) dictates a terminal multiple contraction. However, our variant perception is that this deceleration is an intentional pivot away from low-margin SMBs toward enterprise multi-product adoption. The mechanism is visible in expanding operating margins (30.5%), justifying a premium forward multiple (27.3x vs 24.1x peer median).
"""

def get_exemplars(archetype: str) -> str:
    """Return an exemplar string block for the given archetype."""
    if archetype == "general":
        return _GENERAL_EXEMPLARS
    if archetype == "software_saas":
        return _SOFTWARE_SAAS_EXEMPLARS
    return ""
