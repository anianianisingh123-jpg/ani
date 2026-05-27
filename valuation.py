"""P/E ratio fetching, history tracking, and divergence alert logic.

- `fetch_pe_ratios()` pulls trailing (fallback forward) P/E for each market
  via its country ETF proxy. Cached 24h, all errors swallowed.
- `update_history_and_alerts()` rolls a per-market history (max 12 entries,
  no same-day duplicates) and returns band-change alerts.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st


# ETF proxies per market
ETF_PROXIES: dict[str, str] = {
    "United States":  "SPY",
    "United Kingdom": "EWU",
    "Japan":          "EWJ",
    "Germany":        "EWG",
    "France":         "EWQ",
    "China":          "MCHI",
    "Hong Kong":      "EWH",
    "India":          "INDA",
    "Brazil":         "EWZ",
    "Canada":         "EWC",
    "Australia":      "EWA",
    "South Korea":    "EWY",
    "Singapore":      "EWS",
    "Switzerland":    "EWL",
    "Saudi Arabia":   "KSA",
    "Taiwan":         "EWT",
    "Mexico":         "EWW",
    "South Africa":   "EZA",
}

# Country shift → which portfolio positions get the inline alert
COUNTRY_TO_POSITIONS: dict[str, list[str]] = {
    "United States":  ["QCOM", "CRM"],
    "China":          ["XIAOMI"],
    "Hong Kong":      ["XIAOMI"],
    "India":          ["XIAOMI"],
    "Taiwan":         ["QCOM"],
    "South Korea":    ["QCOM"],
    "Saudi Arabia":   ["KMI"],
    "Canada":         ["KMI"],
    "Mexico":         ["KMI"],
}

GOLD = "#c9a84c"

# (upper_bound, label, color) — first match wins
BANDS = [
    (12.0,         "CHEAP",          "#4ade80"),
    (16.0,         "FAIR",           "#a3e635"),
    (20.0,         "ELEVATED",       "#f59e0b"),
    (24.0,         "EXPENSIVE",      "#f97316"),
    (float("inf"), "VERY EXPENSIVE", "#ef4444"),
]

BAND_ORDER = ["CHEAP", "FAIR", "ELEVATED", "EXPENSIVE", "VERY EXPENSIVE"]


def band_for(pe: float | None) -> tuple[str, str]:
    """Return (label, hex_color) for a P/E. None → NO DATA / gold."""
    if pe is None or pe != pe:  # NaN check
        return ("NO DATA", GOLD)
    for upper, label, color in BANDS:
        if pe < upper:
            return (label, color)
    last = BANDS[-1]
    return (last[1], last[2])


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_pe_ratios() -> dict[str, float | None]:
    """Pull trailing/forward P/E for every market ETF. Cached 24h."""
    try:
        import yfinance as yf
    except Exception:
        return {country: None for country in ETF_PROXIES}

    out: dict[str, float | None] = {}
    for country, ticker in ETF_PROXIES.items():
        pe: float | None = None
        try:
            info = yf.Ticker(ticker).info or {}
            raw = info.get("trailingPE")
            if raw is None or (isinstance(raw, float) and raw != raw):
                raw = info.get("forwardPE")
            if raw is not None and not (isinstance(raw, float) and raw != raw):
                pe = float(raw)
                if pe <= 0 or pe > 1000:
                    pe = None  # garbage filter
        except Exception:
            pe = None
        out[country] = pe
    return out


def _history_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "valuation_history.json",
    )


def _load_history() -> dict:
    p = _history_path()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_history(data: dict) -> None:
    try:
        with open(_history_path(), "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass  # non-fatal — read-only filesystem on Cloud is OK


def _today_iso() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def update_history_and_alerts(pe_map: dict[str, float | None]) -> list[dict]:
    """
    Append new readings to history (max 12 per market, no same-day dupes),
    return alerts for markets whose band changed vs most-recent stored.
    """
    history = _load_history()
    today = _today_iso()
    alerts: list[dict] = []

    for country, pe in pe_map.items():
        band, _ = band_for(pe)
        entries = history.get(country, [])
        prev = entries[0] if entries else None

        # Detect band shift against last stored, only when both sides have real data
        if (
            prev
            and prev.get("band")
            and prev["band"] != "NO DATA"
            and band != "NO DATA"
            and prev["band"] != band
        ):
            try:
                old_idx = BAND_ORDER.index(prev["band"])
                new_idx = BAND_ORDER.index(band)
                direction = "expensive" if new_idx > old_idx else "cheaper"
            except ValueError:
                direction = "expensive"
            alerts.append({
                "country": country,
                "prev_band": prev["band"],
                "prev_pe": prev.get("pe"),
                "new_band": band,
                "new_pe": pe,
                "direction": direction,
            })

        # Append today's reading (only real data, only when date changes)
        if pe is not None and (not prev or prev.get("date") != today):
            entries.insert(0, {"date": today, "pe": round(pe, 2), "band": band})
            history[country] = entries[:12]

    _save_history(history)
    return alerts


def alerts_for_position(alerts: list[dict]) -> dict[str, list[dict]]:
    """Re-key alerts by position ticker via COUNTRY_TO_POSITIONS."""
    out: dict[str, list[dict]] = {}
    for a in alerts:
        for ticker in COUNTRY_TO_POSITIONS.get(a["country"], []):
            out.setdefault(ticker, []).append(a)
    return out
