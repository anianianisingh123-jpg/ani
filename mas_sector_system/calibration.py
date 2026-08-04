"""Score past calls against what the stock actually did (VAL-07).

The rubric in `valuation_rubric.py` grades how an argument was *made* — method
named, evidence cited, figures traceable, no internal contradiction. All eleven
criteria are process. None of them asks whether the call was right.

This module asks that. It reads the runs the desk has kept since day one, pairs
each with a later price, and reports a hit rate.

Three design decisions worth knowing:

**Direction is the primary measure, not target accuracy.** Most stored calls
carry no price target — and going forward `null` is the correct value whenever
the memo declines to issue one (see VAL-18). A scorer keyed on targets would be
structurally empty. Direction is scoreable on any call that has a rating and a
price, which is the common case.

**Coverage is a first-class output, not a footnote.** "4 of 26 calls scoreable"
is itself the finding: it tells you the back catalogue is thin and why. A hit
rate quoted without its denominator is the kind of number that gets a desk into
trouble.

**Nothing here fetches a price.** The realized-price lookup is injected, so the
scoring logic is pure, testable offline, and cannot silently depend on a vendor
being reachable. `yfinance_prices` is provided as one implementation; the CLI
accepts a JSON file of prices instead so the whole module runs with no network.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

_PKG_DIR = Path(__file__).resolve().parent
DEFAULT_DB = _PKG_DIR.parent / "outputs" / "research_memory.sqlite"

# Ratings are stored as free text ("BUY (sized as a satellite position)",
# "HOLD / TRIM", "BUY — satellite"), so the direction has to be read out of the
# first recognised token rather than matched whole.
_BULLISH = ("STRONG BUY", "BUY", "ACCUMULATE", "OVERWEIGHT", "ADD")
_BEARISH = ("SELL", "AVOID", "UNDERWEIGHT", "REDUCE", "TRIM")
_NEUTRAL = ("HOLD", "NEUTRAL", "MARKET PERFORM", "MARKETPERFORM")

_RATING_TOKEN = re.compile(
    r"\b(STRONG BUY|ACCUMULATE|OVERWEIGHT|MARKET ?PERFORM|UNDERWEIGHT|"
    r"BUY|HOLD|NEUTRAL|REDUCE|TRIM|SELL|AVOID|ADD)\b",
    re.IGNORECASE,
)

# A move smaller than this is treated as "went nowhere", which is what a HOLD
# predicts. Not a risk model — a deliberately blunt threshold, stated openly so
# a reader can disagree with it.
DEFAULT_BAND = 0.05

# Before this date every stored `price_target` was regex-scraped from prose with
# "fair value" in the pattern, so it is an engine output rather than a desk view
# (VAL-18, fixed 2026-08-03). This is a fact about the code history, not a guess
# about any individual row — which matters, because the `valuation_json` column
# was added by a later migration and is empty on the oldest runs, so the
# value-matching check below cannot see them.
TARGET_PROVENANCE_FIX = datetime(2026, 8, 3, tzinfo=timezone.utc)


def normalize_rating(raw: Any) -> Optional[str]:
    """Reduce a stored rating string to BULLISH / NEUTRAL / BEARISH."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    match = _RATING_TOKEN.search(raw)
    if not match:
        return None
    token = re.sub(r"\s+", " ", match.group(1).upper())
    if token in _BULLISH:
        return "BULLISH"
    if token in _BEARISH:
        return "BEARISH"
    if token in _NEUTRAL:
        return "NEUTRAL"
    return None


def _as_float(raw: Any) -> Optional[float]:
    try:
        value = float(str(raw).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return value if value == value and value not in (float("inf"), float("-inf")) else None


@dataclass
class Call:
    """One stored recommendation, reduced to what scoring needs."""

    run_id: int
    ticker: str
    made_at: Optional[datetime]
    rating_raw: Optional[str]
    direction: Optional[str]
    price_at_call: Optional[float]
    price_target: Optional[float]
    target_is_engine_figure: bool = False

    @property
    def scoreable(self) -> bool:
        return bool(self.direction) and self.price_at_call is not None

    def blockers(self) -> list[str]:
        reasons = []
        if not self.direction:
            reasons.append("no rating recorded")
        if self.price_at_call is None:
            reasons.append("no price at call")
        return reasons


@dataclass
class Verdict:
    call: Call
    realized_price: float
    horizon_days: Optional[int]
    total_return: float
    correct: bool
    detail: str
    target_error: Optional[float] = None


@dataclass
class Scorecard:
    total_calls: int = 0
    verdicts: list[Verdict] = field(default_factory=list)
    unscoreable: dict[str, int] = field(default_factory=dict)
    no_realized_price: int = 0
    targets_recorded: int = 0
    targets_that_are_engine_figures: int = 0

    @property
    def scored(self) -> int:
        return len(self.verdicts)

    @property
    def hits(self) -> int:
        return sum(1 for v in self.verdicts if v.correct)

    @property
    def hit_rate(self) -> Optional[float]:
        return (self.hits / self.scored) if self.scored else None

    @property
    def coverage(self) -> Optional[float]:
        return (self.scored / self.total_calls) if self.total_calls else None

    def by_direction(self) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        for verdict in self.verdicts:
            key = verdict.call.direction or "UNKNOWN"
            hits, total = out.get(key, (0, 0))
            out[key] = (hits + (1 if verdict.correct else 0), total + 1)
        return out

    @property
    def scoreable_targets(self) -> int:
        return sum(1 for v in self.verdicts if v.target_error is not None)


def load_calls(db_path: str | Path = DEFAULT_DB) -> list[Call]:
    """Read every stored run as a Call. Never mutates the database."""
    path = Path(db_path)
    if not path.exists():
        return []
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, ticker, created_at, rating, price_target, live_price, "
            "valuation_json FROM runs ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    calls: list[Call] = []
    for row in rows:
        target = _as_float(row["price_target"])
        calls.append(
            Call(
                run_id=int(row["id"]),
                ticker=str(row["ticker"] or "").upper(),
                made_at=_parse_ts(row["created_at"]),
                rating_raw=row["rating"],
                direction=normalize_rating(row["rating"]),
                price_at_call=_as_float(row["live_price"]),
                price_target=target,
                target_is_engine_figure=(
                    target is not None
                    and (
                        _looks_like_engine_figure(target, row["valuation_json"])
                        or _predates_target_fix(_parse_ts(row["created_at"]))
                    )
                ),
            )
        )
    return calls


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _predates_target_fix(made_at: Optional[datetime]) -> bool:
    """True for calls recorded while the target was still a prose scrape."""
    return made_at is not None and made_at < TARGET_PROVENANCE_FIX


def _looks_like_engine_figure(target: Optional[float], valuation_json: Any) -> bool:
    """True when a stored target matches a deterministic engine output.

    Every price target in the database before 2026-08-03 is the engine's DCF
    fair value, because the extraction regex matched the words "fair value"
    (VAL-18). Those are not desk views and must not be scored as though they
    were — silently grading them would measure the engine against itself.
    """
    if target is None or not valuation_json:
        return False
    try:
        blob = json.loads(valuation_json) if isinstance(valuation_json, str) else valuation_json
    except (TypeError, ValueError):
        return False
    if not isinstance(blob, dict):
        return False
    for key in ("dcf", "comps", "dcf_judgment", "comps_judgment"):
        block = blob.get(key)
        if not isinstance(block, dict):
            continue
        for field_name in (
            "fair_value_per_share",
            "implied_value_per_share",
            "epv_per_share",
        ):
            value = _as_float(block.get(field_name))
            if value is not None and abs(value - target) < 0.01:
                return True
    return False


def score_call(
    call: Call,
    realized_price: float,
    *,
    band: float = DEFAULT_BAND,
    realized_at: Optional[datetime] = None,
) -> Optional[Verdict]:
    """Was this call right? Direction first, target accuracy alongside.

    BULLISH is correct if the stock rose more than `band`; BEARISH if it fell
    more than `band`; NEUTRAL if it stayed inside the band — a HOLD predicts
    that the stock goes nowhere, and it deserves credit when it does.
    """
    if not call.scoreable or call.price_at_call in (None, 0):
        return None
    total_return = (realized_price / float(call.price_at_call)) - 1.0

    if call.direction == "BULLISH":
        correct = total_return > band
        expected = f"rise more than {band:.0%}"
    elif call.direction == "BEARISH":
        correct = total_return < -band
        expected = f"fall more than {band:.0%}"
    else:
        correct = abs(total_return) <= band
        expected = f"stay within +/-{band:.0%}"

    horizon = None
    if call.made_at and realized_at:
        horizon = max(0, (realized_at - call.made_at).days)

    target_error = None
    if call.price_target and not call.target_is_engine_figure:
        target_error = (realized_price / call.price_target) - 1.0

    return Verdict(
        call=call,
        realized_price=realized_price,
        horizon_days=horizon,
        total_return=total_return,
        correct=correct,
        detail=(
            f"{call.direction} at {call.price_at_call:.2f} -> {realized_price:.2f} "
            f"({total_return:+.1%}); expected to {expected}"
        ),
        target_error=target_error,
    )


def build_scorecard(
    calls: Iterable[Call],
    prices: dict[str, float] | Callable[[str], Optional[float]],
    *,
    band: float = DEFAULT_BAND,
    realized_at: Optional[datetime] = None,
) -> Scorecard:
    """Score every call for which a realized price is available."""
    lookup: Callable[[str], Optional[float]]
    lookup = prices.get if isinstance(prices, dict) else prices

    card = Scorecard()
    for call in calls:
        card.total_calls += 1
        if call.price_target is not None:
            card.targets_recorded += 1
            if call.target_is_engine_figure:
                card.targets_that_are_engine_figures += 1

        if not call.scoreable:
            for reason in call.blockers():
                card.unscoreable[reason] = card.unscoreable.get(reason, 0) + 1
            continue

        realized = lookup(call.ticker)
        if realized is None:
            card.no_realized_price += 1
            continue

        verdict = score_call(
            call, float(realized), band=band, realized_at=realized_at
        )
        if verdict:
            card.verdicts.append(verdict)
    return card


def yfinance_prices(tickers: Iterable[str]) -> dict[str, float]:
    """Last close per ticker. The one function here that touches the network."""
    out: dict[str, float] = {}
    try:
        import yfinance as yf
    except ImportError:
        return out
    for ticker in sorted({t.upper() for t in tickers if t}):
        try:
            info = yf.Ticker(ticker).fast_info
            price = getattr(info, "last_price", None) or info.get("lastPrice")
            if price:
                out[ticker] = float(price)
        except Exception:  # noqa: BLE001 - a missing quote must not abort the run
            continue
    return out


def format_scorecard(card: Scorecard, *, band: float = DEFAULT_BAND) -> str:
    """Human-readable report. Coverage before hit rate, deliberately."""
    lines = ["=" * 64, "CALIBRATION — did the desk's past calls work out?", "=" * 64]
    lines.append(f"Stored calls:        {card.total_calls}")

    coverage = card.coverage
    lines.append(
        f"Scoreable:           {card.scored}"
        + (f" ({coverage:.0%} of stored)" if coverage is not None else "")
    )
    for reason, count in sorted(card.unscoreable.items(), key=lambda kv: -kv[1]):
        lines.append(f"  excluded — {reason}: {count}")
    if card.no_realized_price:
        lines.append(f"  excluded — no realized price available: {card.no_realized_price}")

    lines.append("")
    if not card.scored:
        lines.append("No call could be scored. The hit rate below is not a number yet —")
        lines.append("it is a statement about the back catalogue, not about the desk.")
    else:
        rate = card.hit_rate or 0.0
        lines.append(
            f"Direction hit rate:  {card.hits}/{card.scored} ({rate:.0%})  "
            f"[band +/-{band:.0%}]"
        )
        for direction, (hits, total) in sorted(card.by_direction().items()):
            lines.append(f"  {direction:<9} {hits}/{total}")

    lines.append("")
    lines.append(f"Price targets recorded: {card.targets_recorded}")
    if card.targets_that_are_engine_figures:
        lines.append(
            f"  of which engine figures, NOT desk views: "
            f"{card.targets_that_are_engine_figures} — excluded from target scoring "
            "(VAL-18; fixed 2026-08-03, so this shrinks going forward)"
        )
    lines.append(f"  scoreable as genuine targets: {card.scoreable_targets}")

    if card.scored:
        lines.append("")
        lines.append("Per call:")
        for verdict in card.verdicts:
            mark = "HIT " if verdict.correct else "MISS"
            horizon = f" after {verdict.horizon_days}d" if verdict.horizon_days else ""
            lines.append(
                f"  [{mark}] run {verdict.call.run_id:>3} {verdict.call.ticker:<5} "
                f"{verdict.detail}{horizon}"
            )
    lines.append("=" * 64)
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mas_sector_system.calibration",
        description="Score stored recommendations against realized prices.",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Run database path.")
    parser.add_argument(
        "--prices",
        default=None,
        help='JSON file of {"TICKER": price}. Omit to fetch via yfinance.',
    )
    parser.add_argument(
        "--band",
        type=float,
        default=DEFAULT_BAND,
        help=f"Move treated as 'went nowhere' (default {DEFAULT_BAND}).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON, not a report.")
    args = parser.parse_args(argv)

    calls = load_calls(args.db)
    if not calls:
        print(f"No runs found in {args.db}", file=sys.stderr)
        return 1

    if args.prices:
        prices = {
            str(k).upper(): float(v)
            for k, v in json.loads(Path(args.prices).read_text()).items()
        }
    else:
        prices = yfinance_prices(call.ticker for call in calls)
        if not prices:
            print(
                "No realized prices available (yfinance unreachable or absent). "
                "Pass --prices with a JSON file to score offline.",
                file=sys.stderr,
            )

    card = build_scorecard(
        calls, prices, band=args.band, realized_at=datetime.now(timezone.utc)
    )

    if args.json:
        print(
            json.dumps(
                {
                    "total_calls": card.total_calls,
                    "scored": card.scored,
                    "coverage": card.coverage,
                    "hits": card.hits,
                    "hit_rate": card.hit_rate,
                    "by_direction": {
                        k: {"hits": h, "total": t}
                        for k, (h, t) in card.by_direction().items()
                    },
                    "unscoreable": card.unscoreable,
                    "no_realized_price": card.no_realized_price,
                    "targets_recorded": card.targets_recorded,
                    "targets_that_are_engine_figures": (
                        card.targets_that_are_engine_figures
                    ),
                },
                indent=2,
            )
        )
    else:
        print(format_scorecard(card, band=args.band))
    return 0


if __name__ == "__main__":
    sys.exit(main())
