"""
debt_cycle.py — Ray Dalio Monetary-Policy (MP) framework + per-country baselines.

The MP-phase classification and the structural indicators here are a
*framework baseline* (labelled DEBT_ASOF). Debt/GDP figures are general
government gross debt from IMF WEO (~2025). Real-rate, CB-balance-sheet and
deficit figures are approximate structural anchors — the live, web-searched
country memo verifies and updates them on demand. Nothing here is presented as
real-time tick data.
"""

from __future__ import annotations

DEBT_ASOF = "IMF WEO 2025 / framework baseline"

# Dalio's four monetary-policy regimes — baked into every debt-cycle AI prompt.
MP_FRAMEWORK = """Ray Dalio Monetary Policy (MP) framework:
- MP0 — Hard money constraint (gold-standard-style, no policy flexibility). Debt crises become depressions.
- MP1 — Conventional monetary policy (rate cuts/hikes, short rates > 0). Central bank has full flexibility.
- MP2 — Quantitative easing / asset purchases (rates at/near zero, CB buys bonds/assets). Rate cuts no longer work.
- MP3 — Fiscal-monetary coordination / debt monetization (CB funds fiscal deficits via money creation). Last resort, currency-debasement risk high.
Transition signals: debt/GDP trajectory, real interest rates, CB balance sheet % of GDP, currency debasement rate, yield-curve control, deficit monetization."""

# Phase -> (display label, color) per spec.
PHASE_COLORS = {
    "MP0":           ("MP0 · Hard Money",        "#4a4a4a"),
    "MP1":           ("MP1 · Conventional",      "#2d6b4a"),
    "MP2":           ("MP2 · QE",                "#c9a84c"),
    "MP3":           ("MP3 · Fiscal-Monetary",   "#c43a1a"),
    "TRANSITIONING": ("Transitioning",           "#7a5c1a"),
}


def phase_color(phase: str) -> str:
    return PHASE_COLORS.get(phase, ("Unknown", "#c9a84c"))[1]


def phase_label(phase: str) -> str:
    return PHASE_COLORS.get(phase, (phase, "#c9a84c"))[0]


# Per-country baseline.
#   phase     : MP0/MP1/MP2/MP3/TRANSITIONING
#   sub       : finer transition note (e.g. "MP2 → MP3")
#   debt_gdp  : general govt gross debt / GDP, % (IMF ~2025)
#   real_rate : approx real policy rate, % (policy − CPI, baseline)
#   cb_bs     : central bank balance sheet, % of GDP (baseline)
#   deficit   : fiscal balance / GDP, % (negative = deficit)
#   start     : Dalio-framework marker for the current long-term cycle
#   parallel  : a historical parallel the framework would draw
COUNTRY_BASELINES = {
    "United States": {
        "phase": "TRANSITIONING", "sub": "MP2 → MP3",
        "debt_gdp": 123, "real_rate": 1.5, "cb_bs": 22, "deficit": -6.5, "lat": 38.9, "lng": -77.0,
        "start": "1945 — post-war long-term debt cycle; leveraging accelerated post-1980",
        "parallel": "1930s–40s US and 1970s fiscal dominance: debt monetization pressure as deficits run hot at full employment.",
    },
    "Japan": {
        "phase": "TRANSITIONING", "sub": "MP3-leaning (furthest along)",
        "debt_gdp": 250, "real_rate": -1.0, "cb_bs": 125, "deficit": -5.5, "lat": 35.7, "lng": 139.7,
        "start": "1990 — asset bubble burst; multi-decade deleveraging + MP2/MP3 experimentation",
        "parallel": "Japan IS the parallel everyone else studies — the template for MP1→MP2→MP3.",
    },
    "United Kingdom": {
        "phase": "MP1", "sub": "QT underway, space restored",
        "debt_gdp": 101, "real_rate": 1.0, "cb_bs": 28, "deficit": -4.5, "lat": 51.5, "lng": -0.1,
        "start": "1945 — post-war cycle; 2022 gilt crisis exposed fiscal-monetary fragility",
        "parallel": "2022 LDI/gilt crisis rhymed with classic late-cycle funding stress.",
    },
    "Germany": {
        "phase": "MP1", "sub": "fiscal space, ECB constraint",
        "debt_gdp": 63, "real_rate": 0.5, "cb_bs": 45, "deficit": -2.0, "lat": 52.5, "lng": 13.4,
        "start": "Euro era from 1999; debt-brake discipline, recent fiscal loosening",
        "parallel": "The creditor anchor of the euro bloc — 1990s reunification fiscal expansion echoes today's defense/infrastructure spend.",
    },
    "France": {
        "phase": "MP1", "sub": "fiscal stress rising",
        "debt_gdp": 112, "real_rate": 0.7, "cb_bs": 45, "deficit": -5.5, "lat": 48.9, "lng": 2.3,
        "start": "Euro era; chronic deficits, political fragmentation post-2024",
        "parallel": "Late-cycle European sovereign with widening OAT-Bund spread — 2011-style periphery risk migrating to the core.",
    },
    "European Union": {
        "phase": "MP1", "sub": "post-QE normalization",
        "debt_gdp": 82, "real_rate": 0.6, "cb_bs": 45, "deficit": -3.0, "lat": 50.8, "lng": 4.4,
        "start": "ECB QE 2015→2022; now QT with fragmentation backstop (TPI)",
        "parallel": "A monetary union without a fiscal union — the unresolved tension of 2010–12.",
    },
    "Switzerland": {
        "phase": "MP1", "sub": "low rates, huge SNB balance sheet",
        "debt_gdp": 38, "real_rate": 0.5, "cb_bs": 110, "deficit": -0.5, "lat": 46.9, "lng": 7.4,
        "start": "Post-2011 franc cap era; SNB balance sheet ballooned via FX intervention",
        "parallel": "A small open economy importing the world's monetary distortions — the safe-haven curse.",
    },
    "China": {
        "phase": "TRANSITIONING", "sub": "MP1 → MP2 (balance-sheet recession risk)",
        "debt_gdp": 88, "real_rate": 1.5, "cb_bs": 35, "deficit": -7.0, "lat": 39.9, "lng": 116.4,
        "start": "Post-2008 credit super-cycle; property deleveraging from 2021",
        "parallel": "Japan circa 1990 — a property-led balance-sheet recession with reluctant policy easing.",
    },
    "India": {
        "phase": "MP1", "sub": "conventional, growth-led",
        "debt_gdp": 83, "real_rate": 1.5, "cb_bs": 25, "deficit": -5.0, "lat": 28.6, "lng": 77.2,
        "start": "Early-cycle relative to DM; structural credit deepening",
        "parallel": "Early-stage productivity/credit expansion — closer to 1990s EM Asia ascent than to late-cycle DM.",
    },
    "South Korea": {
        "phase": "MP1", "sub": "high household leverage",
        "debt_gdp": 55, "real_rate": 0.8, "cb_bs": 25, "deficit": -2.5, "lat": 37.6, "lng": 127.0,
        "start": "Post-1998 cycle; household debt now among world's highest",
        "parallel": "Private-debt overhang reminiscent of pre-2008 consumer-credit peaks.",
    },
    "Australia": {
        "phase": "MP1", "sub": "conventional, housing-levered",
        "debt_gdp": 50, "real_rate": 0.8, "cb_bs": 20, "deficit": -1.5, "lat": -35.3, "lng": 149.1,
        "start": "33 years without recession to 2020; household debt elevated",
        "parallel": "A commodity-funded household-debt cycle — 2000s rhyme.",
    },
    "Canada": {
        "phase": "MP1", "sub": "household-debt overhang",
        "debt_gdp": 106, "real_rate": 0.7, "cb_bs": 18, "deficit": -1.5, "lat": 45.4, "lng": -75.7,
        "start": "Post-2008 housing/credit expansion; among highest household debt in G7",
        "parallel": "Pre-crisis household leverage like the US in 2006 — but without the 2008 reset.",
    },
    "Brazil": {
        "phase": "MP1", "sub": "deeply restrictive real rates",
        "debt_gdp": 87, "real_rate": 8.0, "cb_bs": 15, "deficit": -7.5, "lat": -15.8, "lng": -47.9,
        "start": "Post-2015 fiscal cycle; orthodox high-real-rate regime",
        "parallel": "Classic EM orthodoxy — punishingly high real rates defending the currency, 1990s-style.",
    },
    "Mexico": {
        "phase": "MP1", "sub": "orthodox, nearshoring tailwind",
        "debt_gdp": 58, "real_rate": 4.0, "cb_bs": 15, "deficit": -4.5, "lat": 19.4, "lng": -99.1,
        "start": "Post-1994 tequila-crisis orthodoxy; nearshoring structural shift",
        "parallel": "Disciplined EM benefitting from supply-chain realignment — early-cycle optionality.",
    },
    "Turkey": {
        "phase": "MP1", "sub": "post-heterodox normalization",
        "debt_gdp": 30, "real_rate": 5.0, "cb_bs": 20, "deficit": -5.0, "lat": 39.9, "lng": 32.9,
        "start": "2021–23 heterodox debasement; 2023→ orthodox tightening to 40%+",
        "parallel": "A live currency-debasement case study — Weimar-lite, now attempting the orthodox cure.",
    },
    "Argentina": {
        "phase": "TRANSITIONING", "sub": "MP3 legacy → shock orthodoxy",
        "debt_gdp": 85, "real_rate": 2.0, "cb_bs": 30, "deficit": -1.0, "lat": -34.6, "lng": -58.4,
        "start": "Serial monetization; 2023→ Milei fiscal shock + dollarization push",
        "parallel": "The textbook MP3 endgame — hyperinflation history now attempting a hard-money reset.",
    },
    "Saudi Arabia": {
        "phase": "MP1", "sub": "USD peg, follows the Fed",
        "debt_gdp": 30, "real_rate": 1.0, "cb_bs": 20, "deficit": -3.0, "lat": 24.7, "lng": 46.7,
        "start": "Riyal pegged to USD since 1986; Vision 2030 fiscal expansion",
        "parallel": "A petro-sovereign importing US monetary policy via the peg — 1980s oil-cycle echoes.",
    },
}

# Order for the dropdown/globe
COUNTRY_ORDER = list(COUNTRY_BASELINES.keys())
