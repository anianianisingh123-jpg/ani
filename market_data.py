"""
market_data.py — global equity-market valuation registry + live yfinance fetch.

Design for accuracy (per Ani's "real numbers, not fake" requirement):
  • price / P/E / P/B / YTD% / 52w-high%  -> fetched LIVE from yfinance at
    runtime, cached 1h. These are genuine market numbers.
  • 10yr-average P/E and Shiller CAPE      -> slow-moving structural baselines,
    clearly labelled with an as-of date. CAPE only where it is widely published
    and reasonably stable; otherwise None (renders "—") rather than invented.
  • valuation label (CHEAP/FAIR/RICH/EXPENSIVE) -> computed from the LIVE P/E
    against the baseline 10yr-avg P/E, per the spec's thresholds.

Every yfinance call is wrapped; failures degrade to None so nothing breaks.
"""

from __future__ import annotations

import streamlit as st

# As-of stamp for the curated structural baselines below.
BASELINE_ASOF = "Q4-2025"

# Valuation bands vs the market's own 10yr-average P/E (spec thresholds).
#   CHEAP:     > 20% BELOW 10yr avg
#   FAIR:      within ±10% of 10yr avg
#   RICH:      10–30% above
#   EXPENSIVE: > 30% above
VAL_COLORS = {
    "CHEAP":     "#4ade80",
    "FAIR":      "#d6c645",
    "RICH":      "#e0954c",
    "EXPENSIVE": "#e05c5c",
    "NO DATA":   "#c9a84c",
}

# Globe legend order
VAL_ORDER = ["CHEAP", "FAIR", "RICH", "EXPENSIVE"]


# ── Registry ─────────────────────────────────────────────────────────────────
# index_sym : yfinance symbol for the headline index (price / YTD / 52w)
# etf       : liquid ETF proxy used for trailing P/E and P/B via .info
# avg_pe    : ~10yr average trailing P/E (structural baseline, BASELINE_ASOF)
# cape      : Shiller CAPE where widely published & stable, else None
# continent : Americas / Europe / Asia-Pacific / ME-Africa
# em        : emerging-market flag (for the EM region filter)
MARKETS_REGISTRY = [
    # code            country          index_name      index_sym     etf     lat    lng    avg_pe cape  ccy   continent       em
    ("US_SPX",  "United States", "S&P 500",      "^GSPC",      "SPY",  40.7,  -74.0, 20.5,  37.0, "USD", "Americas",     False),
    ("US_NDX",  "United States", "Nasdaq 100",   "^NDX",       "QQQ",  40.7,  -74.0, 26.0,  None, "USD", "Americas",     False),
    ("US_DJI",  "United States", "Dow Jones",    "^DJI",       "DIA",  40.7,  -74.0, 18.5,  None, "USD", "Americas",     False),
    ("UK",      "United Kingdom","FTSE 100",     "^FTSE",      "EWU",  51.5,   -0.1, 14.0,  16.0, "GBP", "Europe",       False),
    ("DE",      "Germany",       "DAX",          "^GDAXI",     "EWG",  50.1,    8.7, 15.0,  20.0, "EUR", "Europe",       False),
    ("FR",      "France",        "CAC 40",       "^FCHI",      "EWQ",  48.9,    2.3, 16.0,  22.0, "EUR", "Europe",       False),
    ("JP",      "Japan",         "Nikkei 225",   "^N225",      "EWJ",  35.7,  139.7, 17.0,  24.0, "JPY", "Asia-Pacific", False),
    ("HK",      "Hong Kong",     "Hang Seng",    "^HSI",       "EWH",  22.3,  114.2, 11.0,  11.0, "HKD", "Asia-Pacific", False),
    ("CN",      "China",         "CSI 300",      "000300.SS",  "MCHI", 31.2,  121.5, 13.0,  13.0, "CNY", "Asia-Pacific", True),
    ("IN",      "India",         "SENSEX",       "^BSESN",     "INDA", 19.1,   72.9, 23.0,  32.0, "INR", "Asia-Pacific", True),
    ("KR",      "South Korea",   "KOSPI",        "^KS11",      "EWY",  37.6,  127.0, 12.0,  14.0, "KRW", "Asia-Pacific", True),
    ("AU",      "Australia",     "ASX 200",      "^AXJO",      "EWA", -33.9,  151.2, 17.0,  18.0, "AUD", "Asia-Pacific", False),
    ("CA",      "Canada",        "TSX",          "^GSPTSE",    "EWC",  43.7,  -79.4, 17.0,  21.0, "CAD", "Americas",     False),
    ("BR",      "Brazil",        "Bovespa",      "^BVSP",      "EWZ", -23.5,  -46.6, 11.0,  12.0, "BRL", "Americas",     True),
    ("MX",      "Mexico",        "IPC",          "^MXX",       "EWW",  19.4,  -99.1, 16.0,  18.0, "MXN", "Americas",     True),
    ("CH",      "Switzerland",   "SMI",          "^SSMI",      "EWL",  47.4,    8.5, 18.0,  24.0, "CHF", "Europe",       False),
    ("NL",      "Netherlands",   "AEX",          "^AEX",       "EWN",  52.4,    4.9, 17.0,  22.0, "EUR", "Europe",       False),
    ("ES",      "Spain",         "IBEX 35",      "^IBEX",      "EWP",  40.4,   -3.7, 14.0,  13.0, "EUR", "Europe",       False),
    ("IT",      "Italy",         "FTSE MIB",     "FTSEMIB.MI", "EWI",  41.9,   12.5, 13.0,  17.0, "EUR", "Europe",       False),
    ("TR",      "Turkey",        "BIST 100",     "XU100.IS",   "TUR",  41.0,   28.9,  8.0,   9.0, "TRY", "Europe",       True),
    ("SA",      "Saudi Arabia",  "Tadawul",      "^TASI.SR",   "KSA",  24.7,   46.7, 17.0,  None, "SAR", "ME-Africa",    True),
    ("ZA",      "South Africa",  "JSE Top 40",   "^J200.JO",   "EZA", -26.2,   28.0, 13.0,  17.0, "ZAR", "ME-Africa",    True),
    ("ID",      "Indonesia",     "IDX Composite","^JKSE",      "EIDO", -6.2,  106.8, 16.0,  16.0, "IDR", "Asia-Pacific", True),
    ("TW",      "Taiwan",        "TAIEX",        "^TWII",      "EWT",  25.0,  121.5, 15.0,  22.0, "TWD", "Asia-Pacific", True),
    ("PL",      "Poland",        "WIG",          "WIG.WA",     "EPOL", 52.2,   21.0, 11.0,  11.0, "PLN", "Europe",       True),
]

REGION_FILTERS = ["All", "Americas", "Europe", "Asia-Pacific", "EM", "ME+Africa"]


def _registry_dict() -> dict:
    out = {}
    for row in MARKETS_REGISTRY:
        (code, country, idx_name, idx_sym, etf, lat, lng,
         avg_pe, cape, ccy, continent, em) = row
        out[code] = {
            "code": code, "country": country, "index": idx_name,
            "index_sym": idx_sym, "etf": etf, "lat": lat, "lng": lng,
            "avg_pe": avg_pe, "cape": cape, "currency": ccy,
            "continent": continent, "em": em,
        }
    return out


REGISTRY = _registry_dict()


def valuation_label(current_pe, avg_pe) -> tuple[str, str]:
    """(label, color) from live P/E vs the market's 10yr-avg P/E."""
    if current_pe is None or avg_pe is None or current_pe != current_pe or avg_pe <= 0:
        return ("NO DATA", VAL_COLORS["NO DATA"])
    ratio = current_pe / avg_pe
    if ratio < 0.80:
        label = "CHEAP"
    elif ratio <= 1.10:
        label = "FAIR"
    elif ratio <= 1.30:
        label = "RICH"
    else:
        label = "EXPENSIVE"
    return (label, VAL_COLORS[label])


def _safe_num(v):
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_market_data() -> dict:
    """
    Live fetch for every market. Returns code -> data dict with:
      price, pe, pb, ytd, hi52 (% from 52w high), plus the static registry
      fields and a computed valuation label/color.
    All network failures degrade to None — never raises.
    """
    try:
        import yfinance as yf
    except Exception:
        yf = None

    results: dict[str, dict] = {}
    for code, meta in REGISTRY.items():
        rec = dict(meta)
        rec.update({"price": None, "pe": None, "pb": None, "ytd": None, "hi52": None})

        if yf is not None:
            # Price / YTD / 52w from the headline index
            try:
                hist = yf.Ticker(meta["index_sym"]).history(period="1y", auto_adjust=False)
                if hist is not None and not hist.empty:
                    closes = hist["Close"].dropna()
                    if len(closes):
                        last = float(closes.iloc[-1])
                        rec["price"] = last
                        first = float(closes.iloc[0])
                        if first > 0:
                            rec["ytd"] = (last / first - 1.0) * 100.0
                        hi = float(closes.max())
                        if hi > 0:
                            rec["hi52"] = (last / hi - 1.0) * 100.0
            except Exception:
                pass

            # P/E and P/B from the liquid ETF proxy
            try:
                info = yf.Ticker(meta["etf"]).info or {}
                pe = _safe_num(info.get("trailingPE"))
                if pe is None:
                    pe = _safe_num(info.get("forwardPE"))
                if pe is not None and 0 < pe < 1000:
                    rec["pe"] = pe
                pb = _safe_num(info.get("priceToBook"))
                if pb is not None and 0 < pb < 100:
                    rec["pb"] = pb
            except Exception:
                pass

        label, color = valuation_label(rec["pe"], meta["avg_pe"])
        rec["valuation"] = label
        rec["color"] = color
        # vs 10yr avg, as a signed %
        if rec["pe"] is not None and meta["avg_pe"]:
            rec["vs_avg_pe"] = (rec["pe"] / meta["avg_pe"] - 1.0) * 100.0
        else:
            rec["vs_avg_pe"] = None
        results[code] = rec

    return results


def globe_nodes(data: dict) -> list[dict]:
    """One node per *country* (collapse the 3 US indices to S&P 500) for the globe."""
    seen = set()
    nodes = []
    for code, rec in data.items():
        country = rec["country"]
        if country in seen:
            continue
        seen.add(country)
        # use the S&P 500 record for the US
        nodes.append({
            "name": country,
            "lat": rec["lat"],
            "lng": rec["lng"],
            "color": rec["color"],
            "pe": rec["pe"],
            "cape": rec["cape"],
            "ytd": rec["ytd"],
            "band": rec["valuation"],
            "index": rec["index"],
        })
    return nodes


def country_label_map(data: dict) -> dict[str, str]:
    """country -> valuation label, for the history/divergence-alert system."""
    out = {}
    for rec in data.values():
        if rec["country"] not in out:
            out[rec["country"]] = rec["valuation"]
    return out


# ── Currency debasement vs gold (live, computed from yfinance) ───────────────
# (code, label, USD->ccy yfinance FX symbol)  — USD has no pair (base).
CURRENCIES = [
    ("USD", "US Dollar",        None),
    ("EUR", "Euro",             "USDEUR=X"),
    ("JPY", "Japanese Yen",     "USDJPY=X"),
    ("GBP", "British Pound",    "USDGBP=X"),
    ("CNY", "Chinese Yuan",     "USDCNY=X"),
    ("CHF", "Swiss Franc",      "USDCHF=X"),
    ("AUD", "Australian Dollar","USDAUD=X"),
    ("CAD", "Canadian Dollar",  "USDCAD=X"),
    ("BRL", "Brazilian Real",   "USDBRL=X"),
    ("TRY", "Turkish Lira",     "USDTRY=X"),
    ("ARS", "Argentine Peso",   "USDARS=X"),
    ("INR", "Indian Rupee",     "USDINR=X"),
    ("KRW", "Korean Won",       "USDKRW=X"),
    ("MXN", "Mexican Peso",     "USDMXN=X"),
    ("SAR", "Saudi Riyal",      "USDSAR=X"),
    ("ZAR", "South Afr. Rand",  "USDZAR=X"),
]

_DEBASE_PERIODS = {"chg1y": "1y", "chg3y": "3y", "chg5y": "5y", "chg10y": "10y"}


def _first_last(hist):
    try:
        closes = hist["Close"].dropna()
        if len(closes) >= 2:
            return float(closes.iloc[0]), float(closes.iloc[-1])
    except Exception:
        pass
    return None, None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_currency_debasement() -> list[dict]:
    """
    For each currency, % change of its gold value over 1/3/5/10y.
    Positive = appreciated vs gold; negative = debased. Computed live from
    gold (USD) and FX histories. Missing data -> None. Never raises.
    """
    try:
        import yfinance as yf
    except Exception:
        return [{"ccy": c, "label": lbl, "chg1y": None, "chg3y": None,
                 "chg5y": None, "chg10y": None} for c, lbl, _ in CURRENCIES]

    # Gold in USD history per period
    def gold_hist(period):
        for sym in ("GC=F", "XAUUSD=X"):
            try:
                h = yf.Ticker(sym).history(period=period, auto_adjust=False)
                if h is not None and not h.empty:
                    return h
            except Exception:
                continue
        return None

    gold_cache = {p: gold_hist(p) for p in set(_DEBASE_PERIODS.values())}

    out = []
    for code, label, fx_sym in CURRENCIES:
        rec = {"ccy": code, "label": label, "chg1y": None, "chg3y": None,
               "chg5y": None, "chg10y": None}
        for key, period in _DEBASE_PERIODS.items():
            try:
                g0, g1 = _first_last(gold_cache.get(period))
                if g0 is None:
                    continue
                if fx_sym is None:  # USD base: gold priced in USD directly
                    c0, c1 = 1.0, 1.0
                else:
                    fxh = yf.Ticker(fx_sym).history(period=period, auto_adjust=False)
                    c0, c1 = _first_last(fxh)
                    if c0 is None:
                        continue
                # gold priced in this currency = gold_usd * (ccy per usd)
                gold_in_c_then = g0 * c0
                gold_in_c_now = g1 * c1
                if gold_in_c_now > 0:
                    # appreciation of currency vs gold
                    rec[key] = (gold_in_c_then / gold_in_c_now - 1.0) * 100.0
            except Exception:
                continue
        out.append(rec)
    return out
