"""Per-run token and cost accounting for the MAS research pipeline.

Figures are **estimates** from token counts × a local pricing table — not
billed amounts. Reconcile against Anthropic/Tavily invoices for real budgets.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── Pricing (edit here when rates change or models are swapped) ──────────────
# $ per 1M tokens: (input, output, cache_write, cache_read)
# Cache write is typically ~1.25× base input; cache read ~0.1× base input.
# Verify against Anthropic's current docs — multipliers have changed before.
#
# Sonnet 5 intro pricing runs through 2026-08-31, then moves toward $3/$15.
# Update this table (or set SONNET_POST_INTRO) when that date passes.
MODEL_PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5": (5.00, 25.00, 6.25, 0.50),
    "claude-sonnet-5": (2.00, 10.00, 2.50, 0.20),
    # add open-weight / alternate models here when the stack changes
}

# Alias map: full model ids / provider variants → pricing key
_MODEL_ALIASES: dict[str, str] = {
    "claude-opus-5": "claude-opus-5",
    "claude-sonnet-5": "claude-sonnet-5",
    "claude-opus-4": "claude-opus-5",  # fallback if API renames mid-flight
    "claude-sonnet-4": "claude-sonnet-5",
}

# Tavily: set to your plan's effective per-search rate (USD). Free tier → 0.0.
TAVILY_PRICE_PER_SEARCH: float = 0.01

# SEC EDGAR is free; we only count calls for rate-limit visibility.
SEC_PRICE_PER_CALL: float = 0.0

_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_DIR.parent
DEFAULT_COST_LOG = _REPO_ROOT / "outputs" / "cost_log.jsonl"

# ── Run-scoped tracker (thread-safe for parallel foundation fan-out) ─────────

_tracker_lock = threading.Lock()
_tracker: Optional["RunCostTracker"] = None


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _short_model(model: str) -> str:
    m = (model or "unknown").strip()
    # claude-sonnet-5 → sonnet-5; claude-opus-5 → opus-5
    if m.startswith("claude-"):
        return m[len("claude-") :]
    return m


def resolve_pricing_key(model: str) -> str:
    """Map a raw model string to a MODEL_PRICING key (best-effort)."""
    raw = (model or "").strip()
    if not raw:
        return "claude-sonnet-5"
    if raw in MODEL_PRICING:
        return raw
    if raw in _MODEL_ALIASES:
        return _MODEL_ALIASES[raw]
    # Prefix / substring match (e.g. dated API slugs)
    lower = raw.lower()
    for key in MODEL_PRICING:
        if key in lower or lower in key:
            return key
    if "opus" in lower:
        return "claude-opus-5"
    if "sonnet" in lower:
        return "claude-sonnet-5"
    return raw


def price_llm_call(
    *,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_create: int = 0,
    cache_read: int = 0,
) -> dict[str, float]:
    """Estimate USD cost for one call. Missing models use sonnet-5 rates + flag."""
    key = resolve_pricing_key(model)
    rates = MODEL_PRICING.get(key) or MODEL_PRICING.get("claude-sonnet-5")
    if rates is None:
        rates = (2.0, 10.0, 2.5, 0.2)
    pin, pout, pwrite, pread = rates
    # Treat reported input_tokens as uncached base input (matches Anthropic usage shape).
    in_t = max(0, int(input_tokens or 0))
    out_t = max(0, int(output_tokens or 0))
    cw = max(0, int(cache_create or 0))
    cr = max(0, int(cache_read or 0))
    cost_in = (in_t / 1_000_000.0) * pin
    cost_out = (out_t / 1_000_000.0) * pout
    cost_cw = (cw / 1_000_000.0) * pwrite
    cost_cr = (cr / 1_000_000.0) * pread
    # What the same tokens would have cost if none were cache reads (for "saved").
    uncached_equiv = ((in_t + cw + cr) / 1_000_000.0) * pin + cost_out
    actual = cost_in + cost_out + cost_cw + cost_cr
    return {
        "cost_usd": actual,
        "uncached_equiv_usd": uncached_equiv,
        "saved_vs_uncached_usd": max(0.0, uncached_equiv - actual),
        "pricing_key": key,
        "pricing_known": key in MODEL_PRICING,
    }


def _fmt_tokens(n: int) -> str:
    if n <= 0:
        return "—"
    if n >= 1000:
        return f"{n / 1000.0:.1f}k"
    return str(n)


def _fmt_usd(x: float) -> str:
    if x < 0.01 and x > 0:
        return f"${x:.3f}"
    return f"${x:.2f}"


def _fmt_duration(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    m, sec = divmod(s, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}h {m}m {sec}s"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


class RunCostTracker:
    """Accumulate per-call LLM and tool usage for a single graph invoke."""

    def __init__(
        self,
        *,
        ticker: Optional[str] = None,
        sector: str = "",
        mode: str = "",
        user_query: str = "",
    ) -> None:
        self.lock = threading.Lock()
        self.ticker = ticker
        self.sector = sector
        self.mode = mode
        self.user_query = user_query
        self.started_at = time.monotonic()
        self.started_at_utc = _now_utc()
        self.calls: list[dict[str, Any]] = []
        self.tavily_searches = 0
        self.sec_calls = 0
        self._finalized = False
        # Node count captured by the finalize that wrote the run's log line.
        # A later, more complete finalize corrects it — see mark_finalized().
        self._finalized_node_count = 0

    def record_llm(
        self,
        *,
        node: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_create: int = 0,
        cache_read: int = 0,
        thinking_tokens: int = 0,
        stop_reason: Optional[str] = None,
        duration_s: float = 0.0,
        attempt: int = 1,
        text_chars: int = 0,
    ) -> None:
        priced = price_llm_call(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_create=cache_create,
            cache_read=cache_read,
        )
        rec = {
            "node": node or "unknown",
            "model": model or "unknown",
            "pricing_key": priced["pricing_key"],
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "cache_create": int(cache_create or 0),
            "cache_read": int(cache_read or 0),
            "thinking_tokens": int(thinking_tokens or 0),
            "stop_reason": stop_reason,
            "duration_s": float(duration_s or 0.0),
            "attempt": int(attempt or 1),
            "text_chars": int(text_chars or 0),
            "cost_usd": float(priced["cost_usd"]),
            "saved_vs_uncached_usd": float(priced["saved_vs_uncached_usd"]),
            "pricing_known": priced["pricing_known"],
        }
        with self.lock:
            self.calls.append(rec)

    def record_tavily(self, n: int = 1) -> None:
        with self.lock:
            self.tavily_searches += max(0, int(n))

    def record_sec(self, n: int = 1) -> None:
        with self.lock:
            self.sec_calls += max(0, int(n))

    def build_summary(self) -> dict[str, Any]:
        with self.lock:
            calls = list(self.calls)
            tavily = self.tavily_searches
            sec = self.sec_calls
            started = self.started_at
            meta = {
                "ticker": self.ticker,
                "sector": self.sector,
                "mode": self.mode,
                "user_query": self.user_query,
                "started_at_utc": self.started_at_utc,
            }

        wall_s = time.monotonic() - started
        by_node: dict[str, dict[str, Any]] = {}
        for c in calls:
            node = c["node"]
            slot = by_node.setdefault(
                node,
                {
                    "node": node,
                    "model": c["model"],
                    "models": set(),
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_create": 0,
                    "cache_read": 0,
                    "thinking_tokens": 0,
                    "duration_s": 0.0,
                    "cost_usd": 0.0,
                    "saved_vs_uncached_usd": 0.0,
                },
            )
            slot["calls"] += 1
            slot["models"].add(c["model"])
            # Prefer last non-empty model string for display
            if c["model"]:
                slot["model"] = c["model"]
            slot["input_tokens"] += c["input_tokens"]
            slot["output_tokens"] += c["output_tokens"]
            slot["cache_create"] += c["cache_create"]
            slot["cache_read"] += c["cache_read"]
            slot["thinking_tokens"] += c["thinking_tokens"]
            slot["duration_s"] += c["duration_s"]
            slot["cost_usd"] += c["cost_usd"]
            slot["saved_vs_uncached_usd"] += c["saved_vs_uncached_usd"]

        nodes = []
        for slot in by_node.values():
            models = sorted(slot.pop("models"))
            slot["models"] = models
            if len(models) == 1:
                slot["model"] = models[0]
            elif models:
                slot["model"] = models[0]
            nodes.append(slot)
        nodes.sort(key=lambda r: r["cost_usd"], reverse=True)

        total_in = sum(c["input_tokens"] for c in calls)
        total_out = sum(c["output_tokens"] for c in calls)
        total_cw = sum(c["cache_create"] for c in calls)
        total_cr = sum(c["cache_read"] for c in calls)
        llm_cost = sum(c["cost_usd"] for c in calls)
        saved = sum(c["saved_vs_uncached_usd"] for c in calls)
        # Cache hit rate: cache_read / (uncached + cache_write + cache_read)
        denom = total_in + total_cw + total_cr
        hit_rate = (total_cr / denom) if denom > 0 else 0.0

        tavily_cost = tavily * TAVILY_PRICE_PER_SEARCH
        sec_cost = sec * SEC_PRICE_PER_CALL
        total_cost = llm_cost + tavily_cost + sec_cost

        # Model role summary for memo
        opus_nodes = sorted(
            {
                n["node"]
                for n in nodes
                if "opus" in (n.get("model") or "").lower()
                or "opus" in resolve_pricing_key(n.get("model") or "").lower()
            }
        )
        sonnet_nodes = sorted(
            {
                n["node"]
                for n in nodes
                if n["node"] not in opus_nodes
            }
        )

        return {
            **meta,
            "finished_at_utc": _now_utc(),
            "wall_clock_s": wall_s,
            "nodes": nodes,
            "calls": calls,
            "totals": {
                "input_tokens": total_in,
                "output_tokens": total_out,
                "cache_create": total_cw,
                "cache_read": total_cr,
                "llm_cost_usd": llm_cost,
                "tavily_searches": tavily,
                "tavily_cost_usd": tavily_cost,
                "sec_calls": sec,
                "sec_cost_usd": sec_cost,
                "total_cost_usd": total_cost,
                "cache_hit_rate": hit_rate,
                "saved_vs_uncached_usd": saved,
            },
            "model_roles": {
                "opus_nodes": opus_nodes,
                "sonnet_nodes": sonnet_nodes,
            },
            "pricing_note": (
                "Estimate from local MODEL_PRICING × token counts — not a billed amount. "
                "Reconcile against API invoices for budgeting."
            ),
            "pricing_table": {
                k: {
                    "input": v[0],
                    "output": v[1],
                    "cache_write": v[2],
                    "cache_read": v[3],
                }
                for k, v in MODEL_PRICING.items()
            },
            "tavily_price_per_search": TAVILY_PRICE_PER_SEARCH,
        }

    def mark_finalized(self, node_count: int = 0) -> str:
        """Decide what this finalize call should do with the run log.

        Returns "write" (first finalize), "rewrite" (a later finalize that
        saw strictly more nodes, so the line already on disk understates the
        run), or "skip".

        Why this is not a plain first-wins flag: `validation_halt` finalizes
        and then — because three parallel foundation branches never pass
        through the validation gate — the graph keeps running and the rest of
        the nodes execute anyway. First-wins recorded only the pre-gate nodes,
        under-reporting those runs by roughly two thirds. Correcting on a more
        complete pass keeps exactly one honest line per run.
        """
        with self.lock:
            if not self._finalized:
                self._finalized = True
                self._finalized_node_count = node_count
                return "write"
            if node_count > getattr(self, "_finalized_node_count", 0):
                self._finalized_node_count = node_count
                return "rewrite"
            return "skip"


def begin_run(
    *,
    ticker: Optional[str] = None,
    sector: str = "",
    mode: str = "",
    user_query: str = "",
) -> RunCostTracker:
    """Start a fresh run tracker (call once at graph entry)."""
    global _tracker
    t = RunCostTracker(
        ticker=ticker,
        sector=sector,
        mode=mode,
        user_query=user_query,
    )
    with _tracker_lock:
        _tracker = t
    return t


def get_tracker() -> Optional[RunCostTracker]:
    with _tracker_lock:
        return _tracker


def record_llm_call(**kwargs: Any) -> None:
    t = get_tracker()
    if t is not None:
        t.record_llm(**kwargs)


def record_tavily_search(n: int = 1) -> None:
    t = get_tracker()
    if t is not None:
        t.record_tavily(n)


def record_sec_call(n: int = 1) -> None:
    t = get_tracker()
    if t is not None:
        t.record_sec(n)


def format_console_table(summary: dict[str, Any]) -> str:
    """Full run-cost table for stdout (nodes sorted by cost desc)."""
    ticker = (summary.get("ticker") or summary.get("sector") or "RUN").upper()
    mode = summary.get("mode") or "?"
    totals = summary.get("totals") or {}
    nodes: list[dict[str, Any]] = list(summary.get("nodes") or [])

    lines = [
        "─────────────────────────────────────────────",
        f"RUN COST — {ticker} {mode}",
        "─────────────────────────────────────────────",
        f"{'Node':<24} {'Model':<10} {'In':>7} {'Out':>7} {'Cache':>7} {'Cost':>8}",
    ]
    for n in nodes:
        cache_tokens = int(n.get("cache_read") or 0) + int(n.get("cache_create") or 0)
        lines.append(
            f"{str(n.get('node', ''))[:24]:<24} "
            f"{_short_model(str(n.get('model', '')))[:10]:<10} "
            f"{_fmt_tokens(int(n.get('input_tokens') or 0)):>7} "
            f"{_fmt_tokens(int(n.get('output_tokens') or 0)):>7} "
            f"{_fmt_tokens(cache_tokens):>7} "
            f"{_fmt_usd(float(n.get('cost_usd') or 0)):>8}"
        )
    lines.append("─────────────────────────────────────────────")
    lines.append(
        f"{'LLM total':<50} {_fmt_usd(float(totals.get('llm_cost_usd') or 0))}"
    )
    tavily_n = int(totals.get("tavily_searches") or 0)
    tavily_c = float(totals.get("tavily_cost_usd") or 0)
    lines.append(
        f"Tavily: {tavily_n} searches"
        f"{'':<{max(1, 42 - len(str(tavily_n)) - 9)}} {_fmt_usd(tavily_c)}"
    )
    sec_n = int(totals.get("sec_calls") or 0)
    if sec_n:
        lines.append(f"SEC EDGAR: {sec_n} calls (free)")
    hit = float(totals.get("cache_hit_rate") or 0)
    saved = float(totals.get("saved_vs_uncached_usd") or 0)
    lines.append(
        f"Cache hit rate: {hit * 100:.0f}%  |  Saved vs. uncached: ~{_fmt_usd(saved)}"
    )
    lines.append(f"Wall clock: {_fmt_duration(float(summary.get('wall_clock_s') or 0))}")
    lines.append(
        f"Total (est.): {_fmt_usd(float(totals.get('total_cost_usd') or 0))}  "
        f"— estimate, not billed amount"
    )
    lines.append("─────────────────────────────────────────────")
    return "\n".join(lines)


def format_memo_appendix(summary: dict[str, Any]) -> str:
    """Condensed cost block appended to every memo unconditionally."""
    totals = summary.get("totals") or {}
    nodes: list[dict[str, Any]] = list(summary.get("nodes") or [])
    top = nodes[:3]
    top_str = (
        ", ".join(f"{n['node']} ({_fmt_usd(n['cost_usd'])})" for n in top)
        if top
        else "n/a"
    )
    roles = summary.get("model_roles") or {}
    opus = roles.get("opus_nodes") or []
    sonnet = roles.get("sonnet_nodes") or []
    opus_s = ", ".join(opus) if opus else "none"
    sonnet_s = "all other nodes" if sonnet else "none"
    if sonnet and len(sonnet) <= 6:
        sonnet_s = ", ".join(sonnet)

    hit = float(totals.get("cache_hit_rate") or 0)
    return (
        "── Run Cost ──\n"
        f"Total: {_fmt_usd(float(totals.get('total_cost_usd') or 0))}  |  "
        f"Wall clock: {_fmt_duration(float(summary.get('wall_clock_s') or 0))}  |  "
        f"Cache hit rate: {hit * 100:.0f}%\n"
        f"Most expensive: {top_str}\n"
        f"Models: opus-5 ({opus_s}) · sonnet-5 ({sonnet_s})\n"
        "Note: local estimate from token counts × pricing table, not billed amount."
    )


def append_cost_log(
    summary: dict[str, Any],
    *,
    path: Optional[Path] = None,
    replace_last: bool = False,
) -> Path:
    """Append one JSON line for cross-run analysis. Returns log path.

    `replace_last` rewrites the final line instead of appending, so a run
    that finalized early (validation_halt) and then kept executing ends up
    with one corrected line rather than two conflicting ones. The rewrite
    only proceeds if that last line is the same ticker — otherwise it falls
    back to appending rather than risk clobbering another run's record.
    """
    log_path = Path(path) if path else DEFAULT_COST_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Slimmer line for the rolling log (drop raw per-call list bloat if huge)
    line_obj = {
        "timestamp": summary.get("finished_at_utc") or _now_utc(),
        "ticker": summary.get("ticker"),
        "sector": summary.get("sector"),
        "mode": summary.get("mode"),
        "wall_clock_s": summary.get("wall_clock_s"),
        "totals": summary.get("totals"),
        "nodes": [
            {
                "node": n.get("node"),
                "model": n.get("model"),
                "input_tokens": n.get("input_tokens"),
                "output_tokens": n.get("output_tokens"),
                "cache_create": n.get("cache_create"),
                "cache_read": n.get("cache_read"),
                "cost_usd": n.get("cost_usd"),
                "calls": n.get("calls"),
                "duration_s": n.get("duration_s"),
            }
            for n in (summary.get("nodes") or [])
        ],
        "tavily_price_per_search": summary.get("tavily_price_per_search"),
        "pricing_note": summary.get("pricing_note"),
    }
    new_line = json.dumps(line_obj, default=str) + "\n"

    if replace_last and log_path.exists():
        try:
            existing = log_path.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError:
            existing = []
        while existing and not existing[-1].strip():
            existing.pop()
        same_run = False
        if existing:
            try:
                same_run = (
                    json.loads(existing[-1]).get("ticker") == line_obj.get("ticker")
                )
            except (json.JSONDecodeError, AttributeError):
                same_run = False
        if same_run:
            existing[-1] = new_line
            log_path.write_text("".join(existing), encoding="utf-8")
            return log_path.resolve()
        # Last line belongs to a different run — append rather than clobber it.

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(new_line)
    return log_path.resolve()


def finalize_run_cost(
    state: Optional[dict[str, Any]] = None,
    *,
    print_console: bool = True,
    write_jsonl: bool = True,
) -> dict[str, Any]:
    """Build cost_report + cost_data, print table, append JSONL (once per run).

    Returns a partial state update: {cost_report, cost_data}.
    Idempotent: second call in the same run reuses the same summary without
    double-writing JSONL or double-printing.
    """
    tracker = get_tracker()
    if tracker is None:
        # No active run — empty payload so callers still get keys.
        empty = {
            "cost_report": "── Run Cost ──\nNo cost tracker active for this run.\n",
            "cost_data": {},
        }
        return empty

    summary = tracker.build_summary()
    # Overlay state meta if tracker was started without full context
    if state:
        summary["ticker"] = summary.get("ticker") or state.get("ticker")
        summary["sector"] = summary.get("sector") or state.get("sector") or ""
        summary["mode"] = summary.get("mode") or state.get("mode") or ""

    report = format_memo_appendix(summary)
    action = tracker.mark_finalized(len(summary.get("nodes") or []))
    if action in ("write", "rewrite"):
        if print_console:
            print(format_console_table(summary), flush=True)
        if write_jsonl:
            path = append_cost_log(summary, replace_last=(action == "rewrite"))
            if action == "rewrite":
                print(
                    f"[cost] corrected run line ({len(summary.get('nodes') or [])} "
                    f"nodes — an earlier finalize recorded fewer) → {path}",
                    flush=True,
                )
            else:
                print(f"[cost] wrote run line → {path}", flush=True)

    return {
        "cost_report": report,
        "cost_data": summary,
    }


def append_cost_to_memo(memo: str, cost_report: str) -> str:
    """Append the condensed cost block if not already present."""
    body = (memo or "").rstrip()
    block = (cost_report or "").strip()
    if not block:
        return memo or ""
    if "── Run Cost ──" in body:
        return body + "\n"
    if not body:
        return block + "\n"
    return body + "\n\n" + block + "\n"
