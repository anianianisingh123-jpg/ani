"""
valuation.py — valuation-history tracking and band-shift divergence alerts.

Works off the vs-10yr-average valuation labels produced by market_data
(CHEAP / FAIR / RICH / EXPENSIVE). Keeps a rolling per-country history in
valuation_history.json (max 12 entries, no same-day duplicates) and emits
an alert whenever a country's band changes vs the most recent stored reading.
Alerts are mapped to the affected portfolio positions for the Thesis War Room.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# Country band shift -> which portfolio positions are affected
COUNTRY_TO_POSITIONS: dict[str, list[str]] = {
    "United States": ["QCOM", "CRM"],
    "China":         ["XIAOMI"],
    "Hong Kong":     ["XIAOMI"],
    "India":         ["XIAOMI"],
    "Taiwan":        ["QCOM"],
    "South Korea":   ["QCOM"],
    "Saudi Arabia":  ["KMI"],
    "Canada":        ["KMI"],
    "Mexico":        ["KMI"],
}

# Severity order for direction (cheaper vs more-expensive)
BAND_ORDER = ["CHEAP", "FAIR", "RICH", "EXPENSIVE"]


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
        pass  # read-only filesystem on Cloud is fine — alerts just won't persist


def _today_iso() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def update_history_and_alerts(label_map: dict[str, str]) -> list[dict]:
    """
    label_map: country -> current valuation label.
    Appends today's reading (no same-day dupes, max 12), returns band-change
    alerts vs the most recent stored reading.
    """
    history = _load_history()
    today = _today_iso()
    alerts: list[dict] = []

    for country, label in label_map.items():
        if not label or label == "NO DATA":
            continue
        entries = history.get(country, [])
        prev = entries[0] if entries else None

        if (
            prev
            and prev.get("band")
            and prev["band"] != "NO DATA"
            and prev["band"] != label
        ):
            try:
                direction = (
                    "expensive"
                    if BAND_ORDER.index(label) > BAND_ORDER.index(prev["band"])
                    else "cheaper"
                )
            except ValueError:
                direction = "expensive"
            alerts.append({
                "country": country,
                "prev_band": prev["band"],
                "new_band": label,
                "direction": direction,
            })

        if not prev or prev.get("date") != today:
            entries.insert(0, {"date": today, "band": label})
            history[country] = entries[:12]

    _save_history(history)
    return alerts


def alerts_for_position(alerts: list[dict]) -> dict[str, list[dict]]:
    """Re-key alerts by affected position ticker."""
    out: dict[str, list[dict]] = {}
    for a in alerts:
        for ticker in COUNTRY_TO_POSITIONS.get(a["country"], []):
            out.setdefault(ticker, []).append(a)
    return out
