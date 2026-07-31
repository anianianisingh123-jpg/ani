#!/usr/bin/env python3
"""FWD-07: full eight-ticker pre-forecast baseline.

Artifacts: outputs/val02_baseline/{TICKER}_*_{SUFFIX}.json
           outputs/val02_baseline/comparison_fwd_baseline.md
           outputs/val02_baseline/summary_fwd_baseline.json
           outputs/val02_baseline/failures_fwd_baseline.json

Continues on per-ticker failure; logs extraction/archetype breakage without
workarounds.
"""

from __future__ import annotations

import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from mas_sector_system.main import run_deep_dive  # noqa: E402
from mas_sector_system.valuation_engine import fcf_history  # noqa: E402
from mas_sector_system.valuation_rubric import (  # noqa: E402
    HELD_OUT_TICKERS,
    RUBRIC,
    grade_valuation,
)
from tmp.run_val02_baseline import (  # noqa: E402
    _jsonable,
    make_llm_judge,
    state_slice,
)

OUT_DIR = ROOT / "outputs" / "val02_baseline"
SUFFIX = "_fwd_baseline"

# Sector strings for the pipeline CLI / empty_state.
TICKER_SPECS: list[dict[str, str]] = [
    {
        "ticker": "NVDA",
        "sector": "Semiconductors",
        "archetype_note": "general / semis",
        "query": (
            "Full institutional underwrite of NVDA. Complete investment memo "
            "with valuation reconciliation (DCF + peer comps)."
        ),
    },
    {
        "ticker": "QCOM",
        "sector": "Semiconductors",
        "archetype_note": "general / semis",
        "query": (
            "Full institutional underwrite of QCOM (Qualcomm). Complete investment "
            "memo with valuation reconciliation (DCF + peer comps)."
        ),
    },
    {
        "ticker": "CRM",
        "sector": "Software",
        "archetype_note": "software_saas",
        "query": (
            "Full institutional underwrite of CRM (Salesforce). Complete investment "
            "memo with valuation reconciliation (DCF + peer comps)."
        ),
    },
    {
        "ticker": "JPM",
        "sector": "Financials",
        "archetype_note": "bank_lender — residual income; FCF DCF not primary",
        # Avoid bare "valuation" keyword so router stays on full_underwrite
        # (valuation_only skips bull/bear/overview — not a clean baseline).
        "query": (
            "Full institutional equity research underwrite and investment thesis "
            "on JPM (JPMorgan Chase). Cover business, management, macro, debate, "
            "and fair-value work. For a bank, residual income or P/B is preferred "
            "over FCF DCF as primary method."
        ),
    },
    {
        "ticker": "PLD",
        "sector": "Real Estate",
        "archetype_note": "equity_reit — FFO/NAV path",
        "query": (
            "Full institutional equity research underwrite and investment thesis "
            "on PLD (Prologis). Cover business, management, macro, debate, and "
            "fair-value work. For a REIT, FFO/NAV methods are preferred over FCF "
            "DCF as primary."
        ),
    },
    {
        "ticker": "PGR",
        "sector": "Financials",
        "archetype_note": "insurance — book-value path",
        "query": (
            "Full institutional equity research underwrite and investment thesis "
            "on PGR (Progressive). Cover business, management, macro, debate, and "
            "fair-value work. For an insurer, book-value / residual income methods "
            "are preferred over FCF DCF as primary."
        ),
    },
    {
        "ticker": "XOM",
        "sector": "Energy",
        "archetype_note": "cyclical_commodity — mid-cycle normalization",
        "query": (
            "Full institutional equity research underwrite and investment thesis "
            "on XOM (Exxon Mobil). Cover business, management, macro, debate, and "
            "fair-value work; emphasize mid-cycle normalization for a commodity "
            "cyclical."
        ),
    },
    {
        "ticker": "KO",
        "sector": "Consumer Staples",
        "archetype_note": "mature_dividend_payer — stable-assumption control",
        "query": (
            "Full institutional equity research underwrite and investment thesis "
            "on KO (Coca-Cola). Cover business, management, macro, debate, and "
            "fair-value work for a mature dividend payer."
        ),
    },
]


def extract_fwd_stats(state: dict, *, run_error: Optional[str] = None) -> dict[str, Any]:
    from mas_sector_system.valuation_engine import validate_argued_inputs

    dcf = state.get("dcf_engine") if isinstance(state.get("dcf_engine"), dict) else {}
    dj = state.get("dcf_judgment") if isinstance(state.get("dcf_judgment"), dict) else {}
    vc = state.get("valuation_critique") if isinstance(state.get("valuation_critique"), dict) else {}
    rc = state.get("relative_critique") if isinstance(state.get("relative_critique"), dict) else {}
    cj = state.get("comps_judgment") if isinstance(state.get("comps_judgment"), dict) else {}

    history: list = []
    fcf_err = None
    try:
        history = fcf_history(state)
    except Exception as exc:  # noqa: BLE001
        fcf_err = str(exc)

    cf = state.get("cash_flow_statement") if isinstance(state.get("cash_flow_statement"), dict) else {}
    annual_series = cf.get("annual_series") if isinstance(cf.get("annual_series"), list) else []

    clamp_warnings = list(dj.get("clamp_warnings") or [])
    dcf_warnings = list(dcf.get("warnings") or []) if dcf else []
    dcf_errors = list(dcf.get("errors") or []) if dcf else []
    all_disc = clamp_warnings + dcf_warnings + dcf_errors
    directional_disclosures = [
        str(w)
        for w in all_disc
        if "DIRECTIONAL BIAS" in str(w).upper() or "directional bias" in str(w).lower()
    ]
    argued_fcf_not_applied = [
        str(w)
        for w in all_disc
        if "Argued FCF inputs not applied" in str(w)
        or "argued fcf inputs not applied" in str(w).lower()
        or ("not applied" in str(w).lower() and "fcf" in str(w).lower())
    ]
    ttm_fallback = [
        str(w)
        for w in all_disc
        if "fell back to ttm" in str(w).lower()
        or re.search(r"avg_3y requested,\s*\d+ annual", str(w), re.I)
        or re.search(r"mid_cycle requested,\s*\d+ annual", str(w), re.I)
    ]

    assumptions = dj.get("assumptions") if isinstance(dj.get("assumptions"), dict) else {}
    inputs = dj.get("inputs") if isinstance(dj.get("inputs"), dict) else {}
    applied_method = (
        assumptions.get("base_fcf_method_applied")
        or assumptions.get("base_fcf_method")
        or inputs.get("base_fcf_method")
        or dj.get("base_fcf_method")
    )
    requested_method = assumptions.get("base_fcf_method_requested")
    if not requested_method:
        for arg in vc.get("arguments") or []:
            if isinstance(arg, dict) and arg.get("parameter") == "base_fcf_method":
                ar = arg.get("argued_range") or []
                if isinstance(ar, (list, tuple)) and ar:
                    requested_method = ar[0]
                break

    fr = dj.get("fair_value_range") if isinstance(dj.get("fair_value_range"), dict) else {}
    sens = dj.get("sensitivities") if isinstance(dj.get("sensitivities"), list) else []
    sens_rows = [
        {
            "parameter": s.get("parameter"),
            "engine_default": s.get("engine_default"),
            "argued_midpoint": s.get("argued_midpoint"),
            "fair_value_per_share": s.get("fair_value_per_share"),
            "delta_vs_default": s.get("delta_vs_default"),
        }
        for s in sens
        if isinstance(s, dict)
    ]
    dominant = None
    if sens_rows:
        material = [
            s
            for s in sens_rows
            if isinstance(s.get("delta_vs_default"), (int, float))
        ]
        if material:
            dominant = max(material, key=lambda s: abs(s["delta_vs_default"] or 0))

    bias = dj.get("directional_bias") if isinstance(dj.get("directional_bias"), dict) else {}

    proposed: list[str] = []
    for arg in vc.get("arguments") or []:
        if isinstance(arg, dict) and arg.get("parameter"):
            proposed.append(str(arg["parameter"]))
    accepted: list[str] = []
    rejected: list[str] = []
    reval_warns: list[str] = []
    band_dissents: list = []
    if vc and dcf:
        try:
            arch = (
                (state.get("canonical_metrics") or {}).get("archetype")
                if isinstance(state.get("canonical_metrics"), dict)
                else None
            ) or dcf.get("archetype") or state.get("extraction_archetype") or "general"
            acc, warns = validate_argued_inputs(
                vc, archetype=str(arch), engine_default=dcf, state=dict(state)
            )
            accepted = [k for k in acc if k != "band_dissents"]
            reval_warns = list(warns or [])
            rejected = [p for p in proposed if p not in accepted]
            band_dissents = acc.get("band_dissents") or []
        except Exception as exc:  # noqa: BLE001
            reval_warns = [f"revalidate error: {exc}"]
            band_dissents = dj.get("band_dissents") or []
    else:
        band_dissents = dj.get("band_dissents") or []

    # Failure inventory (for never-run tickers / extraction breaks)
    failures: list[dict[str, str]] = []
    if run_error:
        failures.append({"stage": "pipeline", "what": run_error[:500]})
    if state.get("validation_status") == "FAIL":
        vr = state.get("validation_report") or {}
        failures.append(
            {
                "stage": "validation_gate",
                "what": str(vr.get("summary") or vr.get("failures") or "validation FAIL")[:500],
            }
        )
    if dcf_errors:
        failures.append({"stage": "dcf_engine", "what": "; ".join(str(e) for e in dcf_errors)[:500]})
    if not dcf:
        failures.append({"stage": "dcf_engine", "what": "dcf_engine empty/missing"})
    if not vc and not run_error:
        failures.append(
            {
                "stage": "fundamental_critique",
                "what": "valuation_critique missing (parse fail / API / skipped / inert path)",
            }
        )
    if not dj and dcf:
        failures.append(
            {
                "stage": "dcf_judgment",
                "what": "dcf_judgment missing — base case only",
            }
        )
    if fcf_err:
        failures.append({"stage": "fcf_history", "what": fcf_err[:500]})
    if len(history) < 3 and dcf.get("method") == "multi_stage_fcf_dcf":
        failures.append(
            {
                "stage": "fcf_history",
                "what": f"fcf_history returned {len(history)} rows (<3)",
            }
        )
    if argued_fcf_not_applied:
        failures.append(
            {
                "stage": "argued_fcf_inert",
                "what": "; ".join(argued_fcf_not_applied)[:500],
            }
        )

    cm = state.get("canonical_metrics") if isinstance(state.get("canonical_metrics"), dict) else {}
    return {
        "ticker": state.get("ticker"),
        "sector": state.get("sector"),
        "extraction_archetype": state.get("extraction_archetype") or cm.get("archetype"),
        "validation_status": state.get("validation_status"),
        "qc_status": state.get("qc_status"),
        "dcf_engine_method": dcf.get("method"),
        "dcf_engine_fv": dcf.get("fair_value_per_share"),
        "dcf_engine_errors": dcf_errors,
        "cashflow": {
            "annual_series_len": len(annual_series),
            "fcf_history_n": len(history),
            "fcf_history_ge_3": len(history) >= 3,
            "fcf_history_error": fcf_err,
            "base_fcf_method_requested": requested_method,
            "base_fcf_method_applied": applied_method,
            "ttm_fallback_warnings": ttm_fallback,
            "base_fcf_engine": (dcf.get("inputs") or {}).get("base_fcf_annual")
            if isinstance(dcf.get("inputs"), dict)
            else None,
            "base_fcf_judgment": inputs.get("base_fcf_annual"),
        },
        "fair_value_range": {
            "low": fr.get("low"),
            "base": fr.get("base"),
            "high": fr.get("high"),
            "basis": fr.get("basis"),
        },
        "sensitivities": {
            "n": len(sens_rows),
            "table": sens_rows,
            "dominant_driver": dominant,
        },
        "directional_bias": {
            "dominant_share": bias.get("dominant_share"),
            "dominant_direction": bias.get("dominant_direction"),
            "one_sided": bias.get("one_sided"),
            "material_arguments": bias.get("material_arguments"),
            "disclosures": directional_disclosures,
            "one_sided_fired": bool(bias.get("one_sided")) or bool(directional_disclosures),
        },
        "disclosures": {
            "directional_bias": directional_disclosures,
            "argued_fcf_not_applied": argued_fcf_not_applied,
            "all_clamp_warnings": clamp_warnings[:20],
        },
        "icl": {
            "fundamental_critique_parseable": bool(vc),
            "relative_critique_parseable": bool(rc),
            "both_critiques_parseable": bool(vc) and bool(rc),
            "dcf_judgment_present": bool(dj),
            "comps_judgment_present": bool(cj),
            "arguments_proposed": proposed,
            "arguments_accepted": accepted,
            "arguments_rejected": rejected,
            "proposed_n": len(proposed),
            "accepted_n": len(accepted),
            "rejected_n": len(rejected),
            "band_dissents_n": len(band_dissents) if isinstance(band_dissents, list) else 0,
            "band_dissents": band_dissents,
            "revalidate_warnings": reval_warns[:12],
        },
        "failures": failures,
        "run_error": run_error,
    }


def run_one(spec: dict, *, judge, force: bool = False) -> tuple[Optional[dict], dict]:
    ticker = spec["ticker"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slice_path = OUT_DIR / f"{ticker}_state_slice{SUFFIX}.json"
    grade_path = OUT_DIR / f"{ticker}_grade{SUFFIX}.json"
    stats_path = OUT_DIR / f"{ticker}_icl_stats{SUFFIX}.json"
    fail_path = OUT_DIR / f"{ticker}_failure{SUFFIX}.json"
    log_path = OUT_DIR / f"{ticker}_console{SUFFIX}.log"

    run_error = None
    state_clean: dict = {"ticker": ticker, "sector": spec["sector"]}

    if slice_path.exists() and not force:
        print(f"[{ticker}] reusing {slice_path}")
        raw = json.loads(slice_path.read_text())
        state_clean = {k: v for k, v in raw.items() if not str(k).startswith("_")}
        run_error = (raw.get("_baseline_meta") or {}).get("run_error")
    else:
        print(f"[{ticker}] FWD-07 deep_dive sector={spec['sector']} …")
        t0 = datetime.now(timezone.utc)
        try:
            result = run_deep_dive(
                ticker=ticker,
                sector=spec["sector"],
                user_query=spec["query"],
            )
            elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
            state = state_slice(result)
            state["_baseline_meta"] = {
                "phase": "fwd_baseline",
                "elapsed_sec": elapsed,
                "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "archetype_note": spec["archetype_note"],
                "qc_status": result.get("qc_status"),
                "validation_status": result.get("validation_status"),
                "query_type": result.get("query_type"),
                "user_query": spec["query"],
            }
            slice_path.write_text(json.dumps(state, indent=2, default=str))
            state_clean = {k: v for k, v in state.items() if not str(k).startswith("_")}
            print(
                f"[{ticker}] done in {elapsed/60:.1f} min; "
                f"qc={result.get('qc_status')} validation={result.get('validation_status')}"
            )
        except Exception as exc:  # noqa: BLE001 — log, don't workaround
            elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
            run_error = f"{type(exc).__name__}: {exc}"
            tb = traceback.format_exc()
            log_path.write_text(tb)
            fail_payload = {
                "ticker": ticker,
                "sector": spec["sector"],
                "archetype_note": spec["archetype_note"],
                "stage": "pipeline_exception",
                "error": run_error,
                "traceback": tb,
                "elapsed_sec": elapsed,
            }
            fail_path.write_text(json.dumps(fail_payload, indent=2))
            # Minimal state for grading
            state = {
                "ticker": ticker,
                "sector": spec["sector"],
                "mode": "deep_dive",
                "user_query": spec["query"],
                "fundamental_valuation": "",
                "relative_valuation": "",
                "final_memo": "",
                "_baseline_meta": {
                    "phase": "fwd_baseline",
                    "run_error": run_error,
                    "elapsed_sec": elapsed,
                },
            }
            slice_path.write_text(json.dumps(state, indent=2, default=str))
            state_clean = {k: v for k, v in state.items() if not str(k).startswith("_")}
            print(f"[{ticker}] PIPELINE FAILED after {elapsed/60:.1f} min: {run_error}")

    stats = extract_fwd_stats(state_clean, run_error=run_error)
    stats["archetype_note"] = spec["archetype_note"]
    stats_path.write_text(json.dumps(_jsonable(stats), indent=2))
    if stats.get("failures"):
        fail_path.write_text(json.dumps(_jsonable(stats["failures"]), indent=2))

    grade = grade_valuation(state_clean, judge=judge)
    grade["phase"] = "fwd_baseline"
    grade["archetype_note"] = spec["archetype_note"]
    grade["extraction_archetype"] = stats.get("extraction_archetype")
    grade["graded_at_utc"] = datetime.now(timezone.utc).isoformat()
    grade["source_slice"] = slice_path.name
    grade["run_error"] = run_error
    grade["failures"] = stats.get("failures")
    grade_path.write_text(json.dumps(grade, indent=2))

    print(
        f"[{ticker}] grade {grade['score']}/{grade['max_score']} "
        f"arch={stats.get('extraction_archetype')} method={stats.get('dcf_engine_method')} "
        f"icl={stats['icl']['proposed_n']}/{stats['icl']['accepted_n']}/{stats['icl']['rejected_n']} "
        f"fcf_n={stats['cashflow']['fcf_history_n']} "
        f"bias={stats['directional_bias'].get('dominant_share')} "
        f"one_sided={stats['directional_bias'].get('one_sided')} "
        f"fails={len(stats.get('failures') or [])}"
    )
    for c in grade["criteria"]:
        mark = "PASS" if c["passed"] else "FAIL"
        print(f"  {c['id']:2d} {mark}  {c['name']}")
    return grade, stats


def write_reports(grades: list[dict], stats_by: dict[str, dict]) -> None:
    # Per-ticker scores
    lines = [
        "# FWD-07 Full Eight-Ticker Baseline",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Commit base: pull of main @ 1ffa771 (bias detector + central-case redesign).",
        f"Artifact suffix: `{SUFFIX}`",
        "",
        "## Per-ticker scores",
        "",
        "| Ticker | Archetype (note) | Extracted | Method | Score | Critiques | Args p/a/r | FCF hist | Central FV | One-sided | Failures |",
        "|--------|------------------|-----------|--------|------:|-----------|------------|----------|------------|:---------:|----------|",
    ]
    for g in grades:
        t = g.get("ticker") or "?"
        st = stats_by.get(t) or {}
        ic = st.get("icl") or {}
        cn = st.get("cashflow") or {}
        fr = st.get("fair_value_range") or {}
        bias = st.get("directional_bias") or {}
        fails = st.get("failures") or []
        lines.append(
            f"| {t} | {g.get('archetype_note') or st.get('archetype_note')} | "
            f"{st.get('extraction_archetype')} | {st.get('dcf_engine_method')} | "
            f"{g.get('score')}/{g.get('max_score')} | "
            f"f={ic.get('fundamental_critique_parseable')} r={ic.get('relative_critique_parseable')} | "
            f"{ic.get('proposed_n')}/{ic.get('accepted_n')}/{ic.get('rejected_n')} | "
            f"{cn.get('fcf_history_n')} | {fr.get('base')} | "
            f"{bias.get('one_sided')} | {len(fails)} |"
        )

    # Criterion × archetype matrix
    lines += [
        "",
        "## Per-criterion × per-ticker (PASS/FAIL)",
        "",
        "| # | Criterion | " + " | ".join(g.get("ticker") or "?" for g in grades) + " | Pass rate |",
        "|---|-----------|" + "|".join(["---"] * len(grades)) + "|----------|",
    ]
    by_ticker = {
        g.get("ticker"): {c["id"]: c for c in g.get("criteria") or []} for g in grades
    }
    for spec in RUBRIC:
        cid = spec["id"]
        cells = []
        n_pass = 0
        n = 0
        for g in grades:
            t = g.get("ticker")
            c = by_ticker.get(t, {}).get(cid)
            if not c:
                cells.append("—")
                continue
            n += 1
            if c.get("passed"):
                n_pass += 1
                cells.append("PASS")
            else:
                cells.append("FAIL")
        rate = f"{n_pass}/{n}" if n else "—"
        lines.append(f"| {cid} | {spec['criterion']} | " + " | ".join(cells) + f" | {rate} |")

    # Archetype grouping pass rates
    lines += ["", "## Per-criterion × archetype group", ""]
    # Map ticker → archetype_note group key
    arch_of = {}
    for g in grades:
        t = g.get("ticker")
        st = stats_by.get(t) or {}
        arch_of[t] = st.get("extraction_archetype") or g.get("extraction_archetype") or "unknown"

    groups: dict[str, list[str]] = {}
    for t, a in arch_of.items():
        groups.setdefault(str(a), []).append(t)

    lines.append("| # | Criterion | " + " | ".join(sorted(groups.keys())) + " |")
    lines.append("|---|-----------|" + "|".join(["---"] * len(groups)) + "|")
    for spec in RUBRIC:
        cid = spec["id"]
        cells = []
        for arch in sorted(groups.keys()):
            tickers = groups[arch]
            n_pass = 0
            n = 0
            for t in tickers:
                c = by_ticker.get(t, {}).get(cid)
                if not c:
                    continue
                n += 1
                if c.get("passed"):
                    n_pass += 1
            cells.append(f"{n_pass}/{n}" if n else "—")
        lines.append(f"| {cid} | {spec['criterion']} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Interpretation guide",
        "",
        "- Criterion fails **all 8** → definition / grader problem.",
        "- Criterion fails **only financials / REITs / insurers** → extraction or method-set gap.",
        "- `Argued FCF inputs not applied` on JPM/PLD/PGR is **expected** until the next epic adds non-FCF argued parameters.",
        "",
        "## Per-ticker detail",
        "",
    ]
    for g in grades:
        t = g.get("ticker")
        st = stats_by.get(t) or {}
        ic = st.get("icl") or {}
        cn = st.get("cashflow") or {}
        fr = st.get("fair_value_range") or {}
        se = st.get("sensitivities") or {}
        bias = st.get("directional_bias") or {}
        disc = st.get("disclosures") or {}
        lines += [
            f"### {t}",
            f"- Note: {g.get('archetype_note')}",
            f"- Extracted archetype: `{st.get('extraction_archetype')}` method=`{st.get('dcf_engine_method')}`",
            f"- Score: **{g.get('score')}/{g.get('max_score')}** validation=`{st.get('validation_status')}` qc=`{st.get('qc_status')}`",
            f"- Critiques parseable: fund={ic.get('fundamental_critique_parseable')} rel={ic.get('relative_critique_parseable')}",
            f"- Args proposed/accepted/rejected: **{ic.get('proposed_n')}/{ic.get('accepted_n')}/{ic.get('rejected_n')}** "
            f"`{ic.get('arguments_proposed')}` → `{ic.get('arguments_accepted')}` reject=`{ic.get('arguments_rejected')}`",
            f"- FV range low/base/high: `{fr.get('low')}` / **`{fr.get('base')}`** / `{fr.get('high')}`",
            f"- Sensitivities n={se.get('n')} dominant=`{se.get('dominant_driver')}`",
        ]
        for row in (se.get("table") or [])[:8]:
            lines.append(
                f"  - `{row.get('parameter')}`: def={row.get('engine_default')} → mid={row.get('argued_midpoint')} "
                f"FV={row.get('fair_value_per_share')} Δ={row.get('delta_vs_default')}"
            )
        lines += [
            f"- Directional bias: share={bias.get('dominant_share')} dir={bias.get('dominant_direction')} "
            f"one_sided={bias.get('one_sided')} fired={bias.get('one_sided_fired')}",
            f"- base_fcf_method requested/applied: `{cn.get('base_fcf_method_requested')}` / `{cn.get('base_fcf_method_applied')}` "
            f"fcf_history_n={cn.get('fcf_history_n')} (≥3={cn.get('fcf_history_ge_3')})",
            f"- DIRECTIONAL BIAS disclosures: `{disc.get('directional_bias')}`",
            f"- Argued FCF not applied: `{disc.get('argued_fcf_not_applied')}`",
            f"- Failures ({len(st.get('failures') or [])}):",
        ]
        fails = st.get("failures") or []
        if not fails:
            lines.append("  - (none)")
        for f in fails:
            lines.append(f"  - **{f.get('stage')}**: {f.get('what')}")
        grade_fails = [c for c in g.get("criteria") or [] if not c.get("passed")]
        lines.append("- Rubric fails:")
        if not grade_fails:
            lines.append("  - (none)")
        for c in grade_fails:
            lines.append(f"  - **C{c['id']} {c['name']}**: {c.get('detail')}")
        lines.append("")

    path = OUT_DIR / f"comparison{SUFFIX}.md"
    path.write_text("\n".join(lines))
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "fwd_baseline",
        "suffix": SUFFIX,
        "tickers": [g.get("ticker") for g in grades],
        "scores": [
            {
                "ticker": g.get("ticker"),
                "score": g.get("score"),
                "max_score": g.get("max_score"),
                "extraction_archetype": (stats_by.get(g.get("ticker") or "") or {}).get(
                    "extraction_archetype"
                ),
                "method": (stats_by.get(g.get("ticker") or "") or {}).get("dcf_engine_method"),
                "criteria": [
                    {"id": c["id"], "passed": c["passed"], "detail": c.get("detail")}
                    for c in g.get("criteria") or []
                ],
                "failures": (stats_by.get(g.get("ticker") or "") or {}).get("failures"),
            }
            for g in grades
        ],
        "stats": {t: stats_by.get(t) for t in [g.get("ticker") for g in grades]},
    }
    (OUT_DIR / f"summary{SUFFIX}.json").write_text(json.dumps(summary, indent=2, default=str))
    # Flat failure log
    all_fails = []
    for t, st in stats_by.items():
        for f in st.get("failures") or []:
            all_fails.append({"ticker": t, **f})
    (OUT_DIR / f"failures{SUFFIX}.json").write_text(json.dumps(all_fails, indent=2))
    print(f"reports → {path}")


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    force = "--force" in argv
    only: Optional[set[str]] = None
    for a in argv:
        if a.startswith("--only="):
            only = {x.strip().upper() for x in a.split("=", 1)[1].split(",") if x.strip()}
        if a == "--reuse":
            force = False

    specs = TICKER_SPECS
    if only:
        specs = [s for s in specs if s["ticker"] in only]
        if not specs:
            print("unknown ticker(s)", sorted(only))
            return 2

    # Default force for missing slices only handled in run_one
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    judge = make_llm_judge()
    grades: list[dict] = []
    stats_by: dict[str, dict] = {}

    for spec in specs:
        try:
            g, st = run_one(spec, judge=judge, force=force or not (
                OUT_DIR / f"{spec['ticker']}_state_slice{SUFFIX}.json"
            ).exists())
            grades.append(g)
            stats_by[spec["ticker"]] = st
        except Exception as exc:  # noqa: BLE001
            print(f"[{spec['ticker']}] outer failure: {exc}")
            traceback.print_exc()
            grades.append(
                {
                    "ticker": spec["ticker"],
                    "score": 0,
                    "max_score": 11,
                    "criteria": [],
                    "archetype_note": spec["archetype_note"],
                    "run_error": str(exc),
                }
            )
            stats_by[spec["ticker"]] = {
                "ticker": spec["ticker"],
                "failures": [{"stage": "outer", "what": str(exc)}],
                "icl": {},
                "cashflow": {},
                "fair_value_range": {},
                "sensitivities": {},
                "directional_bias": {},
                "disclosures": {},
            }

    # Load any pre-existing siblings when --only
    for s in TICKER_SPECS:
        t = s["ticker"]
        gp = OUT_DIR / f"{t}_grade{SUFFIX}.json"
        sp = OUT_DIR / f"{t}_icl_stats{SUFFIX}.json"
        if gp.exists() and not any(g.get("ticker") == t for g in grades):
            grades.append(json.loads(gp.read_text()))
        if sp.exists() and t not in stats_by:
            stats_by[t] = json.loads(sp.read_text())

    order = {s["ticker"]: i for i, s in enumerate(TICKER_SPECS)}
    grades.sort(key=lambda g: order.get(g.get("ticker") or "", 99))
    write_reports(grades, stats_by)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
