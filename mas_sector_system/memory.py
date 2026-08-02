"""Long-term run memory for the MAS equity research desk.

Lightweight SQLite archive of completed (and partial) deep dives so the next
run can compare current facts against the desk's own prior thesis.

No new LangGraph nodes — load at deep_dive entry / foundation prompts;
persist from export and QC-halt finalize paths.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_DIR.parent
DEFAULT_DB_PATH = _REPO_ROOT / "outputs" / "research_memory.sqlite"

# Keep prompt injection bounded (foundation agents already carry large packets).
_MAX_MEMO_CHARS = 3500
_MAX_MACRO_CHARS = 1500
_MAX_METRIC_HEADLINES = 24


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[Path] = None) -> Path:
    """Create the runs table if missing. Returns the DB path.

    Retention policy: keep **all** runs forever (no prune). Gemini/Ani 2026-07-27.
    """
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    with _connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT,
                sector TEXT,
                mode TEXT,
                user_query TEXT,
                created_at TEXT NOT NULL,
                qc_status TEXT,
                rating TEXT,
                price_target TEXT,
                live_price TEXT,
                final_memo TEXT,
                styled_memo TEXT,
                macro_regime_assessment TEXT,
                management_assessment TEXT,
                capital_allocation_assessment TEXT,
                bull_thesis TEXT,
                bear_thesis TEXT,
                fundamental_valuation TEXT,
                relative_valuation TEXT,
                metrics_summary_json TEXT,
                canonical_metrics_json TEXT,
                metrics_full_json TEXT,
                valuation_json TEXT,
                cost_total_usd REAL,
                source_path TEXT
            )
            """
        )
        # Migrate older DBs. CREATE TABLE IF NOT EXISTS is a no-op once the
        # table exists, so every column added after the first release needs an
        # explicit ALTER or live databases keep writing the old shape.
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(runs)").fetchall()
        }
        for name in ("source_path", "metrics_full_json", "valuation_json"):
            if name not in cols:
                conn.execute(f"ALTER TABLE runs ADD COLUMN {name} TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_ticker_created "
            "ON runs(ticker, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_source_path "
            "ON runs(source_path)"
        )
        conn.commit()
    return path


_RECOMMENDATION_HEADING_RE = re.compile(
    r"^#{1,4}\s*(?:\d+\.\s*)?(?:RECOMMENDATION|RATING|VERDICT|THE\s+CALL)\b.*$",
    re.I | re.M,
)
_CALL_RE = re.compile(
    r"\b(BUY|HOLD|AVOID|SELL|ADD|TRIM|OVERWEIGHT|UNDERWEIGHT|NEUTRAL)\b", re.I
)


def _extract_from_recommendation_section(text: str) -> dict[str, str]:
    """Read the call out of the RECOMMENDATION section.

    Takes the first call token that appears after the heading, plus the rest of
    its line as the qualifier ("HOLD — do not add at $88.49").
    """
    out: dict[str, str] = {}
    head = _RECOMMENDATION_HEADING_RE.search(text or "")
    if not head:
        return out
    # Bound the search to this section: stop at the next same-or-shallower ATX
    # heading so a later section's language cannot be picked up.
    depth = len(head.group(0)) - len(head.group(0).lstrip("#"))
    tail = text[head.end():]
    nxt = re.search(rf"^#{{1,{max(depth, 1)}}}\s+\S", tail, re.M)
    section = tail[: nxt.start()] if nxt else tail

    for line in (head.group(0), *section.splitlines()):
        stripped = line.strip().lstrip("#").strip()
        if not stripped:
            continue
        call = _CALL_RE.search(stripped)
        if not call:
            continue
        # Keep the qualifier — "HOLD" alone loses the sizing and the condition.
        start = call.start()
        out["rating"] = stripped[start:].strip().strip("*").strip()[:200]
        break

    pt = re.search(
        r"(?:price\s+target|fair\s+value|target\s+price)[^\n\d$]{0,24}\$?\s*"
        r"([0-9]+(?:\.[0-9]+)?)",
        section,
        re.I,
    )
    if pt:
        out["price_target"] = pt.group(1)
    return out


def _extract_cover_bits(memo: str) -> dict[str, str]:
    """Best-effort rating / PT / price from memo cover lines."""
    text = memo or ""
    out: dict[str, str] = {}
    # Rating: BUY / HOLD / AVOID (with optional sizing parenthetical)
    m = re.search(
        r"\bRating:\s*\**\s*(BUY|HOLD|AVOID)[^\n|]*",
        text,
        re.I,
    )
    if m:
        out["rating"] = m.group(0).split(":", 1)[-1].strip().strip("*").strip()
    else:
        # Synthesis does not emit a "Rating:" cover line — it writes a
        # "## 2. RECOMMENDATION" section with the call in the heading or the
        # first line under it. The old fallback only scanned the first 800
        # characters, which never reaches that section, so `rating` and
        # `price_target` were stored EMPTY for 6 of the 7 completed runs on the
        # 2026-07-30 baseline. Every later "thesis evolution vs prior desk run"
        # then reasons about a prior run whose actual conclusion is unknown.
        out.update(_extract_from_recommendation_section(text))
        if "rating" not in out:
            m2 = re.search(r"\b(BUY|HOLD|AVOID)\b[^\n]{0,80}", text[:800], re.I)
            if m2:
                out["rating"] = m2.group(0).strip()[:120]
    m = re.search(
        r"Price Target:\s*\**\s*\$?([0-9]+(?:\.[0-9]+)?)",
        text,
        re.I,
    )
    if m:
        out["price_target"] = m.group(1)
    m = re.search(
        r"live price[^\d]{0,40}([0-9]+(?:\.[0-9]+)?)",
        text[:1500],
        re.I,
    )
    if m:
        out["live_price"] = m.group(1)
    return out


def _metrics_summary(canonical: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Compact, JSON-serializable snapshot of load-bearing metrics."""
    if not isinstance(canonical, dict):
        return {}
    summary = canonical.get("summary") or {}
    headlines: list[dict[str, Any]] = []
    by_id = canonical.get("by_id") or {}
    preferred = (
        "price",
        "market_cap",
        "trailing_pe",
        "revenue__current_annual",
        "revenue_growth__current_annual_vs_prior_annual",
        "gross_margin__current_annual",
        "net_margin__current_annual",
        "free_cash_flow__current_annual",
        "fcf_margin__current_annual",
        "fcf_growth__current_annual_vs_prior_annual",
        "net_cash_ex_st_investments__current_quarter",
        "net_cash_ex_st_investments__current_annual",
        "total_debt__current_quarter",
        "buyback_dollars_per_pct_point__current_annual_vs_prior_annual",
        "inventory__current_quarter",
        "options_put_call_volume_ratio__live",
        "insider_net_shares_heuristic__live",
        "insider_form4_recent_count__live",
    )
    seen: set[str] = set()
    for mid in preferred:
        m = by_id.get(mid) if isinstance(by_id, dict) else None
        if not isinstance(m, dict):
            # fallback scan metrics list
            for row in canonical.get("metrics") or []:
                if isinstance(row, dict) and row.get("id") == mid:
                    m = row
                    break
        if not isinstance(m, dict) or not m.get("headline"):
            continue
        seen.add(mid)
        headlines.append(
            {
                "id": mid,
                "headline": m.get("headline"),
                "value": m.get("value"),
                "stale": bool(m.get("staleness")),
            }
        )
        if len(headlines) >= _MAX_METRIC_HEADLINES:
            break
    return {
        "ticker": canonical.get("ticker"),
        "archetype": canonical.get("archetype"),
        "metric_count": summary.get("metric_count"),
        "applicable_with_value": summary.get("applicable_with_value"),
        "headlines": headlines,
    }


def save_run(
    state: dict[str, Any],
    *,
    db_path: Optional[Path] = None,
) -> Optional[int]:
    """Persist a run snapshot. Returns row id or None if nothing to save."""
    ticker = (state.get("ticker") or "").strip().upper() or None
    memo = (state.get("final_memo") or state.get("styled_memo") or "").strip()
    if not ticker and not memo:
        return None

    init_db(db_path)
    cover = _extract_cover_bits(memo)
    cm = state.get("canonical_metrics") if isinstance(state.get("canonical_metrics"), dict) else {}
    metrics_summary = _metrics_summary(cm)
    cost = state.get("cost_data") if isinstance(state.get("cost_data"), dict) else {}
    totals = cost.get("totals") if isinstance(cost.get("totals"), dict) else {}
    cost_total = totals.get("total_cost_usd")

    # Store a trimmed metrics blob (summary + by_id headlines only) to keep DB small.
    cm_slim: dict[str, Any] = {
        "ticker": cm.get("ticker") if cm else ticker,
        "archetype": cm.get("archetype") if cm else None,
        "summary": cm.get("summary") if cm else {},
        "metrics_summary": metrics_summary,
    }

    # Full metric records + structured engine output, so a past run can be
    # re-rendered with the same figures the live run had. Deliberately NOT
    # read by format_prior_run_for_prompt, which whitelists the 16 headlines
    # from metrics_summary_json — the QC input packet is the largest cost
    # hotspot in the system and must not grow with this blob.
    metrics_full = cm if cm else {}
    valuation_full = {
        k: state.get(k)
        for k in ("dcf_engine", "comps_engine")
        if isinstance(state.get(k), dict) and state.get(k)
    }

    created_at = state.get("memory_created_at") or _now_utc()
    source_path = state.get("memory_source_path") or None

    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO runs (
                ticker, sector, mode, user_query, created_at,
                qc_status, rating, price_target, live_price,
                final_memo, styled_memo,
                macro_regime_assessment, management_assessment,
                capital_allocation_assessment,
                bull_thesis, bear_thesis,
                fundamental_valuation, relative_valuation,
                metrics_summary_json, canonical_metrics_json,
                metrics_full_json, valuation_json,
                cost_total_usd, source_path
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?
            )
            """,
            (
                ticker,
                state.get("sector") or "",
                state.get("mode") or "deep_dive",
                state.get("user_query") or "",
                created_at,
                state.get("qc_status") or "",
                cover.get("rating") or "",
                cover.get("price_target") or "",
                cover.get("live_price") or "",
                state.get("final_memo") or "",
                state.get("styled_memo") or "",
                state.get("macro_regime_assessment") or "",
                state.get("management_assessment") or "",
                state.get("capital_allocation_assessment") or "",
                state.get("bull_thesis") or "",
                state.get("bear_thesis") or "",
                state.get("fundamental_valuation") or "",
                state.get("relative_valuation") or "",
                json.dumps(metrics_summary, default=str),
                json.dumps(cm_slim, default=str),
                json.dumps(metrics_full, default=str) if metrics_full else None,
                json.dumps(valuation_full, default=str) if valuation_full else None,
                float(cost_total) if cost_total is not None else None,
                source_path,
            ),
        )
        conn.commit()
        run_id = int(cur.lastrowid)
    print(
        f"[memory] saved run id={run_id} ticker={ticker!r} "
        f"qc={state.get('qc_status') or 'n/a'} db={db_path or DEFAULT_DB_PATH}",
        flush=True,
    )
    return run_id


def load_previous_run(
    ticker: Optional[str],
    *,
    mode: str = "deep_dive",
    db_path: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Return the most recent prior run for this ticker, or None."""
    t = (ticker or "").strip().upper()
    if not t:
        return None
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM runs
            WHERE UPPER(ticker) = ?
              AND (mode = ? OR mode IS NULL OR mode = '')
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (t, mode),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def format_prior_run_for_prompt(
    prior: Optional[dict[str, Any]],
    *,
    max_memo_chars: int = _MAX_MEMO_CHARS,
) -> str:
    """Format a prior run into a bounded prompt block for foundation agents."""
    if not prior:
        return (
            "=== PRIOR DESK MEMORY ===\n"
            "No prior deep-dive on file for this ticker. Treat this as a first pass.\n"
        )

    memo = (prior.get("final_memo") or prior.get("styled_memo") or "").strip()
    if len(memo) > max_memo_chars:
        memo = memo[:max_memo_chars].rstrip() + "\n…[prior memo truncated for prompt budget]"

    macro = (prior.get("macro_regime_assessment") or "").strip()
    if len(macro) > _MAX_MACRO_CHARS:
        macro = macro[:_MAX_MACRO_CHARS].rstrip() + "\n…[truncated]"

    headlines_txt = ""
    try:
        ms = json.loads(prior.get("metrics_summary_json") or "{}")
        lines = []
        for h in (ms.get("headlines") or [])[:_MAX_METRIC_HEADLINES]:
            if isinstance(h, dict) and h.get("headline"):
                flag = " [STALE]" if h.get("stale") else ""
                lines.append(f"- {h['headline']}{flag}")
        if lines:
            headlines_txt = "Prior canonical metric headlines:\n" + "\n".join(lines)
    except (json.JSONDecodeError, TypeError):
        headlines_txt = ""

    bits = [
        "=== PRIOR DESK MEMORY (this desk's last run — not street consensus) ===",
        f"Prior run id: {prior.get('id')} | saved_at: {prior.get('created_at')}",
        f"Prior query: {prior.get('user_query') or 'n/a'}",
        f"Prior QC status: {prior.get('qc_status') or 'n/a'}",
        f"Prior rating (extracted): {prior.get('rating') or 'n/a'}",
        f"Prior price target (extracted): {prior.get('price_target') or 'n/a'}",
        f"Prior live price (extracted): {prior.get('live_price') or 'n/a'}",
    ]
    if headlines_txt:
        bits.append(headlines_txt)
    if macro:
        bits.append(f"Prior macro / regime assessment:\n{macro}")
    if memo:
        bits.append(f"Prior final memo (excerpt):\n{memo}")
    bits.append(
        "Use this memory only to: (1) note what the desk previously believed, "
        "(2) flag material changes vs current live data, (3) avoid contradicting "
        "prior numbers without evidence. Do NOT copy the prior memo as current analysis."
    )
    return "\n".join(bits) + "\n"


def load_prior_context_for_state(
    *,
    ticker: Optional[str],
    mode: str = "deep_dive",
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Convenience: load prior run + formatted prompt block for ResearchState."""
    prior = load_previous_run(ticker, mode=mode, db_path=db_path)
    if not prior:
        print(
            f"[memory] no prior run for ticker={ticker!r} — first-pass context",
            flush=True,
        )
        return {
            "prior_run_id": None,
            "prior_run_meta": {},
            "prior_run_context": format_prior_run_for_prompt(None),
        }
    meta = {
        "id": prior.get("id"),
        "created_at": prior.get("created_at"),
        "qc_status": prior.get("qc_status"),
        "rating": prior.get("rating"),
        "price_target": prior.get("price_target"),
        "live_price": prior.get("live_price"),
        "user_query": prior.get("user_query"),
    }
    print(
        f"[memory] loaded prior run id={meta['id']} ticker={ticker!r} "
        f"at={meta['created_at']} rating={meta.get('rating') or 'n/a'}",
        flush=True,
    )
    return {
        "prior_run_id": prior.get("id"),
        "prior_run_meta": meta,
        "prior_run_context": format_prior_run_for_prompt(prior),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Docx / file backfill (one-shot import of historical memos)
# ─────────────────────────────────────────────────────────────────────────────

_DOCX_NAME_RE = re.compile(
    r"^(?P<ticker>[A-Za-z0-9.\-]+)_(?P<date>\d{4}-\d{2}-\d{2})_memo\.docx$",
    re.I,
)


def _extract_docx_text(path: Path) -> str:
    """Extract plain text from a .docx via python-docx."""
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError(
            "python-docx is required for memo backfill (pip install python-docx)"
        ) from exc
    doc = Document(str(path))
    paras = [p.text for p in doc.paragraphs if (p.text or "").strip()]
    return "\n\n".join(paras).strip()


def _parse_docx_filename(path: Path) -> dict[str, str]:
    """Parse TICKER_YYYY-MM-DD_memo.docx → ticker + ISO date (UTC midnight)."""
    m = _DOCX_NAME_RE.match(path.name)
    if not m:
        return {}
    date = m.group("date")
    return {
        "ticker": m.group("ticker").upper(),
        "created_at": f"{date}T12:00:00+00:00",
    }


def source_already_imported(
    source_path: str,
    *,
    db_path: Optional[Path] = None,
) -> bool:
    """True if this absolute/relative source_path was already backfilled."""
    init_db(db_path)
    key = str(source_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM runs WHERE source_path = ? LIMIT 1",
            (key,),
        ).fetchone()
    return row is not None


def backfill_docx_file(
    path: Path | str,
    *,
    db_path: Optional[Path] = None,
    sector: str = "",
    force: bool = False,
) -> Optional[int]:
    """Import one memo .docx into the runs table. Returns run id or None if skipped."""
    p = Path(path).resolve()
    if not p.is_file() or p.suffix.lower() != ".docx":
        print(f"[memory:backfill] skip (not a docx file): {p}", flush=True)
        return None

    rel = str(p.relative_to(_REPO_ROOT)) if _REPO_ROOT in p.parents else str(p)
    if not force and source_already_imported(rel, db_path=db_path):
        print(f"[memory:backfill] already imported: {rel}", flush=True)
        return None

    meta = _parse_docx_filename(p)
    text = _extract_docx_text(p)
    if not text:
        print(f"[memory:backfill] empty text: {rel}", flush=True)
        return None

    ticker = meta.get("ticker")
    if not ticker:
        # Fallback: first token of first line, or cover "Ticker: XYZ"
        m = re.search(r"\bTicker:\s*([A-Z0-9.\-]{1,10})\b", text)
        if m:
            ticker = m.group(1).upper()
        else:
            m2 = re.search(r"\(([A-Z]{1,5})\)", text[:200])
            ticker = m2.group(1).upper() if m2 else None
    if not ticker:
        print(f"[memory:backfill] could not infer ticker: {rel}", flush=True)
        return None

    created_at = meta.get("created_at")
    if not created_at:
        # File mtime as fallback
        ts = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        created_at = ts.isoformat(timespec="seconds")

    # Infer sector lightly from memo body
    sector_guess = sector
    if not sector_guess:
        m = re.search(r"\bSector:\s*([^\n|]+)", text)
        if m:
            sector_guess = m.group(1).strip().strip("*").strip()

    state = {
        "ticker": ticker,
        "sector": sector_guess or "",
        "mode": "deep_dive",
        "user_query": f"[backfill from {rel}]",
        "qc_status": "BACKFILL",
        "final_memo": text,
        "styled_memo": text,
        "memory_created_at": created_at,
        "memory_source_path": rel,
        "canonical_metrics": {},
        "cost_data": {},
    }
    return save_run(state, db_path=db_path)


def backfill_outputs_dir(
    outputs_dir: Optional[Path | str] = None,
    *,
    db_path: Optional[Path] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Import all ``*_memo.docx`` files under outputs/. Idempotent unless force=True."""
    out_dir = Path(outputs_dir) if outputs_dir else (_REPO_ROOT / "outputs")
    if not out_dir.is_dir():
        return {"imported": 0, "skipped": 0, "errors": [f"missing dir {out_dir}"]}

    imported: list[dict[str, Any]] = []
    skipped = 0
    errors: list[str] = []
    for path in sorted(out_dir.glob("*_memo.docx")):
        try:
            rid = backfill_docx_file(path, db_path=db_path, force=force)
            if rid is None:
                skipped += 1
            else:
                imported.append({"id": rid, "path": path.name})
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
            print(f"[memory:backfill] ERROR {path.name}: {exc}", flush=True)

    summary = {
        "imported": len(imported),
        "skipped": skipped,
        "errors": errors,
        "runs": imported,
        "db": str(db_path or DEFAULT_DB_PATH),
    }
    print(
        f"[memory:backfill] done imported={summary['imported']} "
        f"skipped={skipped} errors={len(errors)} db={summary['db']}",
        flush=True,
    )
    return summary


def main_cli(argv: Optional[list[str]] = None) -> int:
    """CLI: python -m mas_sector_system.memory --backfill [--force]"""
    import argparse

    parser = argparse.ArgumentParser(description="MAS long-term research memory tools")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Import outputs/*_memo.docx into SQLite research memory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-import even if source_path already present",
    )
    parser.add_argument(
        "--outputs-dir",
        default=None,
        help="Directory containing *_memo.docx (default: repo outputs/)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite path (default: outputs/research_memory.sqlite)",
    )
    args = parser.parse_args(argv)
    if not args.backfill:
        parser.print_help()
        return 2
    db = Path(args.db) if args.db else None
    summary = backfill_outputs_dir(
        args.outputs_dir,
        db_path=db,
        force=bool(args.force),
    )
    print(json.dumps(summary, indent=2))
    return 0 if not summary.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main_cli())
