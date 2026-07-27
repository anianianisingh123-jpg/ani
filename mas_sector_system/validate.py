"""Pre-narration validation gate.

Runs after metrics are computed and before analysis agents spend tokens.
PASS / WARN / FAIL — FAIL hard-stops the graph (same fail-closed posture as QC).
"""

from __future__ import annotations

from typing import Any, Optional

from .metrics import get_metric
from .tools import check_search_relevance


def _safe_float(x: Any) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _line_val(period: dict, *keys: str) -> Optional[float]:
    if not isinstance(period, dict):
        return None
    for k in keys:
        cell = period.get(k)
        if isinstance(cell, dict) and cell.get("value") is not None:
            return _safe_float(cell.get("value"))
        if isinstance(cell, (int, float)) and not isinstance(cell, bool):
            return float(cell)
    return None


def _period(stmt: Any, name: str) -> dict:
    if not isinstance(stmt, dict):
        return {}
    b = stmt.get(name)
    return b if isinstance(b, dict) else {}


def _check(
    checks: list[dict[str, Any]],
    *,
    name: str,
    status: str,
    detail: str,
) -> None:
    checks.append({"name": name, "status": status, "detail": detail})


def validate_inputs(state: dict[str, Any]) -> dict[str, Any]:
    """Validate statements, market data, metrics coverage, and search relevance.

    Returns::
        {
          "status": "PASS" | "WARN" | "FAIL",
          "checks": [{"name", "status", "detail"}, ...],
          "warnings": [str, ...],
          "failures": [str, ...],
          "summary": str,
        }
    """
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    failures: list[str] = []

    income = state.get("income_statement") or {}
    balance = state.get("balance_sheet") or {}
    cash_flow = state.get("cash_flow_statement") or {}
    cm = state.get("canonical_metrics") or {}
    ticker = state.get("ticker")
    sector = state.get("sector") or ""

    # ── Statement integrity ──────────────────────────────────────────────
    bal = _period(balance, "current_annual") or _period(balance, "current_quarter")
    assets = _line_val(bal, "TotalAssets")
    liab = _line_val(bal, "TotalLiabilities")
    equity = _line_val(bal, "StockholdersEquity")
    if assets is not None and liab is not None and equity is not None:
        residual = abs(assets - (liab + equity))
        tol = max(abs(assets) * 0.02, 1e6)  # 2% or $1M
        # Some filers put L+E in TotalLiabilities via alias — residual can be large.
        if residual <= tol or abs(liab - assets) < tol:
            _check(
                checks,
                name="balance_sheet_identity",
                status="PASS",
                detail=f"assets={assets:.0f} liab={liab:.0f} equity={equity:.0f}",
            )
        else:
            msg = (
                f"Assets ({assets:.0f}) ≉ Liabilities+Equity "
                f"({liab + equity:.0f}); residual={residual:.0f}"
            )
            _check(checks, name="balance_sheet_identity", status="WARN", detail=msg)
            warnings.append(msg)
    else:
        _check(
            checks,
            name="balance_sheet_identity",
            status="WARN",
            detail="missing assets/liabilities/equity tags — cannot verify identity",
        )
        warnings.append("Balance sheet identity not verifiable (missing tags).")

    inc = _period(income, "current_annual")
    rev = _line_val(inc, "Revenues")
    if rev is not None and rev > 0:
        _check(checks, name="revenue_positive", status="PASS", detail=f"revenue={rev:.0f}")
    elif rev is not None and rev <= 0:
        msg = f"Revenue non-positive ({rev}) for operating company check"
        # Pre-profit growth may have near-zero revenue — WARN not FAIL
        _check(checks, name="revenue_positive", status="WARN", detail=msg)
        warnings.append(msg)
    else:
        msg = "Revenue missing on current annual income statement"
        _check(checks, name="revenue_positive", status="FAIL", detail=msg)
        failures.append(msg)

    gp = _line_val(inc, "GrossProfit")
    opinc = _line_val(inc, "OperatingIncomeLoss")
    if rev is not None and gp is not None and gp > rev * 1.01:
        msg = f"Gross profit ({gp}) > revenue ({rev})"
        _check(checks, name="gross_vs_revenue", status="FAIL", detail=msg)
        failures.append(msg)
    else:
        _check(checks, name="gross_vs_revenue", status="PASS", detail="ok or n/a")

    if gp is not None and opinc is not None and opinc > gp * 1.01 and gp > 0:
        msg = f"Operating income ({opinc}) > gross profit ({gp})"
        _check(checks, name="opinc_vs_gross", status="WARN", detail=msg)
        warnings.append(msg)
    else:
        _check(checks, name="opinc_vs_gross", status="PASS", detail="ok or n/a")

    # Period duration labels from canonical metrics
    period_labels = (cm.get("period_labels") or {}) if isinstance(cm, dict) else {}
    ambiguous = []
    for pk, meta in period_labels.items():
        if not isinstance(meta, dict):
            continue
        dur = meta.get("duration") or "unknown"
        if dur in ("unknown",) or (
            "quarter" in pk and "assumed" in str(dur) and meta.get("notes")
        ):
            # assumed 3mo is OK; unknown is not
            if dur == "unknown":
                ambiguous.append(pk)
    if ambiguous:
        msg = f"Ambiguous period duration for: {', '.join(ambiguous)}"
        _check(checks, name="period_duration", status="FAIL", detail=msg)
        failures.append(msg)
    else:
        _check(
            checks,
            name="period_duration",
            status="PASS",
            detail=f"labeled periods: {list(period_labels.keys())}",
        )

    # Stale tags on load-bearing lines
    stale_count = 0
    stale_ids: list[str] = []
    for m in (cm.get("metrics") or []) if isinstance(cm, dict) else []:
        if not isinstance(m, dict):
            continue
        st = m.get("staleness") or []
        if st and m.get("applicable"):
            stale_count += 1
            if len(stale_ids) < 8:
                stale_ids.append(str(m.get("id")))
    if stale_count == 0:
        _check(checks, name="stale_tags", status="PASS", detail="no stale flags")
    elif stale_count <= 6:
        msg = f"{stale_count} metrics with stale source tags (e.g. {', '.join(stale_ids[:4])})"
        _check(checks, name="stale_tags", status="WARN", detail=msg)
        warnings.append(msg)
    else:
        msg = (
            f"{stale_count} metrics carry stale XBRL tags — above threshold; "
            f"examples: {', '.join(stale_ids[:5])}"
        )
        _check(checks, name="stale_tags", status="FAIL", detail=msg)
        failures.append(msg)

    # ── Market data ──────────────────────────────────────────────────────
    price_m = get_metric(cm, "price") if cm else None
    mcap_m = get_metric(cm, "market_cap") if cm else None
    price = price_m.get("value") if price_m else None
    mcap = mcap_m.get("value") if mcap_m else None
    if price and price > 0 and mcap and mcap > 0:
        _check(
            checks,
            name="market_data_present",
            status="PASS",
            detail=f"price={price} mcap={mcap}",
        )
    else:
        msg = f"Missing/zero price or market cap (price={price}, mcap={mcap})"
        _check(checks, name="market_data_present", status="FAIL", detail=msg)
        failures.append(msg)

    div_m = get_metric(cm, "market_cap_vs_price_x_shares_divergence") if cm else None
    if div_m and div_m.get("applicable") and div_m.get("value") is not None:
        div = float(div_m["value"])
        if div > 0.10:
            msg = (
                f"Market cap vs price×shares divergence {div:.1%} > 10% "
                f"— possible vintage/share-count mismatch"
            )
            _check(checks, name="mcap_reconciliation", status="WARN", detail=msg)
            warnings.append(msg)
        else:
            _check(
                checks,
                name="mcap_reconciliation",
                status="PASS",
                detail=f"divergence={div:.2%}",
            )
    else:
        _check(checks, name="mcap_reconciliation", status="PASS", detail="n/a")

    # ── Metrics coverage ─────────────────────────────────────────────────
    summ = (cm.get("summary") or {}) if isinstance(cm, dict) else {}
    n_app = int(summ.get("applicable_with_value") or 0)
    core_ids = (
        "market_cap",
        "revenue__current_annual",
        "gross_margin__current_annual",
    )
    core_missing = []
    for cid in core_ids:
        m = get_metric(cm, cid) if cm else None
        if not m or not m.get("applicable") or m.get("value") is None:
            # revenue may be under slightly different path
            if cid == "revenue__current_annual":
                # try any revenue annual
                found = False
                for mm in (cm.get("metrics") or []) if cm else []:
                    if (
                        isinstance(mm, dict)
                        and str(mm.get("id", "")).startswith("revenue__")
                        and mm.get("applicable")
                        and mm.get("value") is not None
                    ):
                        found = True
                        break
                if not found:
                    core_missing.append(cid)
            else:
                core_missing.append(cid)

    if core_missing:
        msg = f"Core metrics missing: {', '.join(core_missing)}"
        _check(checks, name="metrics_core", status="FAIL", detail=msg)
        failures.append(msg)
    elif n_app < 15:
        msg = f"Only {n_app} applicable metrics with values (threshold 15)"
        _check(checks, name="metrics_coverage", status="WARN", detail=msg)
        warnings.append(msg)
    else:
        _check(
            checks,
            name="metrics_coverage",
            status="PASS",
            detail=f"applicable_with_value={n_app}",
        )

    # ── Archetype noted (informational) ──────────────────────────────────
    arch = None
    if isinstance(cm, dict):
        arch = cm.get("archetype")
    if arch:
        _check(checks, name="archetype", status="PASS", detail=str(arch))

    # ── Peer set (from state if relative already ran; else skip lightly) ──
    peer_list = state.get("peer_list") or []
    peer_excl = state.get("peer_exclusions") or []
    if peer_list is not None and len(list(peer_list)) >= 2:
        _check(
            checks,
            name="peer_set",
            status="PASS",
            detail=f"{len(peer_list)} peers; excluded={peer_excl}",
        )
    elif peer_list is not None and len(list(peer_list)) < 2 and peer_list != []:
        msg = f"Fewer than 2 archetype-matched peers ({peer_list})"
        _check(checks, name="peer_set", status="WARN", detail=msg)
        warnings.append(msg)
    else:
        _check(
            checks,
            name="peer_set",
            status="PASS",
            detail="peers not yet selected (checked at relative valuation)",
        )

    # ── Search relevance ─────────────────────────────────────────────────
    macro = state.get("macro_context") or ""
    sec = state.get("sec_filing_summary") or ""
    # Only fail macro when ticker is set and digest is non-trivial but off-topic
    if ticker and macro and len(macro) > 200:
        ok = check_search_relevance(
            macro,
            ticker=str(ticker),
            entity_name=None,
            label="validation.macro_context",
        )
        if not ok:
            msg = (
                f"macro_context has no mention of ticker={ticker!r} — "
                "treating narrative macro field as failed retrieval"
            )
            _check(checks, name="macro_relevance", status="FAIL", detail=msg)
            failures.append(msg)
            # Clear poison for downstream if we soft-handle? Spec says FAIL field.
            # Hard FAIL status will halt; also record cleared note.
        else:
            _check(checks, name="macro_relevance", status="PASS", detail="ticker present")
    else:
        _check(
            checks,
            name="macro_relevance",
            status="PASS",
            detail="skipped (no ticker or short macro)",
        )

    if ticker and sec and len(sec) > 400:
        # Filing summary should almost always mention ticker or company
        ok = check_search_relevance(
            sec,
            ticker=str(ticker),
            entity_name=None,
            label="validation.sec_filing_summary",
        )
        if not ok:
            msg = f"sec_filing_summary lacks ticker={ticker!r}"
            _check(checks, name="sec_summary_relevance", status="WARN", detail=msg)
            warnings.append(msg)
        else:
            _check(checks, name="sec_summary_relevance", status="PASS", detail="ok")
    else:
        _check(checks, name="sec_summary_relevance", status="PASS", detail="skipped")

    # ── Aggregate status ─────────────────────────────────────────────────
    if failures:
        status = "FAIL"
    elif warnings:
        status = "WARN"
    else:
        status = "PASS"

    summary = (
        f"validation status={status} "
        f"checks={len(checks)} warnings={len(warnings)} failures={len(failures)}"
    )
    if arch:
        summary += f" archetype={arch}"

    return {
        "status": status,
        "checks": checks,
        "warnings": warnings,
        "failures": failures,
        "summary": summary,
        "sector": sector,
        "ticker": ticker,
    }


def format_validation_for_prompt(report: Optional[dict[str, Any]]) -> str:
    if not report or not isinstance(report, dict):
        return "=== VALIDATION GATE ===\n(not run)"
    lines = [
        "=== VALIDATION GATE (pre-narration) ===",
        f"Status: {report.get('status')}",
        f"Summary: {report.get('summary')}",
    ]
    warns = report.get("warnings") or []
    fails = report.get("failures") or []
    if fails:
        lines.append("FAILURES (must not be narrated past without halt):")
        for f in fails:
            lines.append(f"  - {f}")
    if warns:
        lines.append(
            "WARNINGS (memo MUST disclose these; do not paper over data quality issues):"
        )
        for w in warns:
            lines.append(f"  - {w}")
    if not fails and not warns:
        lines.append("No warnings or failures.")
    return "\n".join(lines)
