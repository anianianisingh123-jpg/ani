"""Exemplar library (VAL-04)."""

from typing import Tuple

_GENERAL_EXEMPLARS = """\
[EXEMPLAR: Steelman -> mechanism -> concede]
Where the bear lands real blows: The bear case argues that gross margins are at cyclical peaks and must mean-revert. This is structurally supported by the recent change to extend depreciation useful lives of server equipment from 4 to 5 years, which mechanically lifted margins this quarter. While we maintain our base case, we concede that this accounting tailwind is a one-time benefit and future margin expansion must be driven purely by mix shift, which remains an open question.

[EXEMPLAR: Discount rate tied to a named company risk]
We apply a 12% WACC (above the 10% sector default) to reflect specific customer concentration risks, highlighting the potential lost revenues from Apple insourcing its modem components, which currently constitutes ~20% of the top line.
"""

_SOFTWARE_SAAS_EXEMPLARS = """\
[EXEMPLAR: Variant perception frame]
Consensus assumes that the deceleration in billings growth dictates a terminal multiple contraction. However, our variant perception is that this deceleration is an intentional pivot away from low-margin SMBs toward enterprise multi-product adoption. The mechanism is visible in the stable RPO growth and expanding operating margins, justifying a premium forward multiple.
"""

def get_exemplars(archetype: str) -> str:
    """Return an exemplar string block for the given archetype."""
    if archetype == "general":
        return _GENERAL_EXEMPLARS
    if archetype == "software_saas":
        return _SOFTWARE_SAAS_EXEMPLARS
    return ""
