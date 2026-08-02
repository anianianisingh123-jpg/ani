#!/usr/bin/env python3
"""FWD-07-CLEAN: controlled eight-ticker baseline (post arithmetic fix).

Requirements (FWD07_REVIEW §5, §6, §9, §11):
  - One prompt template; only ticker + company name parameterised
  - Memory isolated: scratch DB, prior load disabled
  - XOM → CVX (entity resolution is not a commodity-extraction failure)
  - Headline = mechanical (9) + advisory C1/C8; no single 11-point score
  - Artifacts under outputs/val02_baseline/*_fwd_clean*

Branch base: fix/valuation-engine-arithmetic.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

# ── Memory isolation BEFORE importing the pipeline ──────────────────────────
CLEAN_MEMORY_DB = ROOT / "outputs" / "val02_baseline" / "fwd07_clean_memory.sqlite"
os.environ["MAS_MEMORY_DB"] = str(CLEAN_MEMORY_DB)
os.environ["MAS_MEMORY_DISABLE_PRIOR"] = "1"
if CLEAN_MEMORY_DB.exists():
    CLEAN_MEMORY_DB.unlink()  # each full batch starts empty

from mas_sector_system.main import run_deep_dive  # noqa: E402
from mas_sector_system.valuation_engine import fcf_history  # noqa: E402
from mas_sector_system.valuation_rubric import (  # noqa: E402
    ADVISORY_CRITERION_IDS,
    RUBRIC,
    grade_valuation,
)
from tmp.run_val02_baseline import (  # noqa: E402
    _jsonable,
    make_llm_judge,
    state_slice,
)

OUT_DIR = ROOT / "outputs" / "val02_baseline"
SUFFIX = "_fwd_clean"

# Single template — no archetype, no method, no section list.
PROMPT_TEMPLATE = (
    "Full institutional equity research underwrite and investment thesis "
    "on {ticker} ({company})."
)

# Company names are identity only — not archetype/method hints.
TICKER_SPECS: list[dict[str, str]] = [
    {"ticker": "NVDA", "sector": "Semiconductors", "company": "NVIDIA", "archetype_note": "general / semis"},
    {"ticker": "QCOM", "sector": "Semiconductors", "company": "Qualcomm", "archetype_note": "general / semis"},
    {"ticker": "CRM", "sector": "Software", "company": "Salesforce", "archetype_note": "software_saas"},
    {"ticker": "JPM", "sector": "Financials", "company": "JPMorgan Chase", "archetype_note": "bank_lender"},
    {"ticker": "PLD", "sector": "Real Estate", "company": "Prologis", "archetype_note": "equity_reit"},
    {"ticker": "PGR", "sector": "Financials", "company": "Progressive", "archetype_note": "insurance"},
    {"ticker": "CVX", "sector": "Energy", "company": "Chevron", "archetype_note": "cyclical_commodity (XOM substituted)"},
    {"ticker": "KO", "sector": "Consumer Staples", "company": "Coca-Cola", "archetype_note": "mature_dividend_payer"},
]


def _query(spec: dict[str, str]) -> str:
    return PROMPT_TEMPLATE.format(ticker=spec["ticker"], company=spec["company"])


def extract_stats(state: dict, *, run_error: Optional[str] = None) -> dict[str, Any]:
    from mas_sector_system.valuation_engine import validate_argued_inputs

    dcf = state.get("dcf_engine") if isinstance(state.get("dcf_engine"), dict) else {}
    dj = state.get("dcf_judgment") if isinstance(state.get("dcf_judgment"), dict) else {}
    vc = state.get("valuation_critique") if isinstance(state.get("valuation_critique"), dict) else {}
    rc = state.get("relative_critique") if isinstance(state.get("relative_critique"), dict) else {}

    history: list = []
    fcf_err = None
    try:
        history = fcf_history(state)
    except Exception as exc:  # noqa: BLE001
        fcf_err = str(exc)

    clamp_warnings = list(dj.get("clamp_warnings") or [])
    dcf_warnings = list(dcf.get("warnings") or []) if dcf else []
    dcf_errors = list(dcf.get("errors") or []) if dcf else []
    all_disc = clamp_warnings + dcf_warnings + dcf_errors
    directional_disclosures = [str(w) for w in all_disc if "DIRECTIONAL BIAS" in str(w).upper()]
    argued_fcf_not_applied = [
        str(w) for w in all_disc if "Argued FCF inputs not applied" in str(w)
    ]

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
    material = [s for s in sens_rows if isinstance(s.get("delta_vs_default"), (int, float))]
    if material:
        dominant = max(material, key=lambda s: abs(s["delta_vs_default"] or 0))

    bias = dj.get("directional_bias") if isinstance(dj.get("directional_bias"), dict) else {}
    proposed = [
        str(a["parameter"])
        for a in (vc.get("arguments") or [])
        if isinstance(a, dict) and a.get("parameter")
    ]
    accepted: list[str] = []
    rejected: list[str] = []
    if vc and dcf:
        try:
            arch = (
                (state.get("canonical_metrics") or {}).get("archetype")
                if isinstance(state.get("canonical_metrics"), dict)
                else None
            ) or dcf.get("archetype") or state.get("extraction_archetype") or "general"
            acc, _warns = validate_argued_inputs(
                vc, archetype=str(arch), engine_default=dcf, state=dict(state)
            )
            accepted = [k for k in acc if k != "band_dissents"]
            rejected = [p for p in proposed if p not in accepted]
        except Exception:  # noqa: BLE001
            pass

    failures: list[dict[str, str]] = []
    if run_error:
        failures.append({"stage": "pipeline", "what": run_error[:500]})
    if state.get("validation_status") == "FAIL":
        vr = state.get("validation_report") or {}
        failures.append(
            {
                "stage": "validation_gate",
                "what": str(vr.get("summary") or "validation FAIL")[:500],
            }
        )
    if not dcf and state.get("validation_status") != "FAIL":
        failures.append({"stage": "dcf_engine", "what": "dcf_engine empty/missing"})
    if argued_fcf_not_applied:
        failures.append(
            {"stage": "argued_fcf_inert", "what": "; ".join(argued_fcf_not_applied)[:500]}
        )

    cm = state.get("canonical_metrics") if isinstance(state.get("canonical_metrics"), dict) else {}
    rec = state.get("recommendation") if isinstance(state.get("recommendation"), dict) else {}
    return {
        "ticker": state.get("ticker"),
        "sector": state.get("sector"),
        "extraction_archetype": state.get("extraction_archetype") or cm.get("archetype"),
        "validation_status": state.get("validation_status"),
        "qc_status": state.get("qc_status"),
        "query_type": state.get("query_type"),
        "user_query": state.get("user_query"),
        "prior_run_id": state.get("prior_run_id"),
        "recommendation": rec,
        "dcf_engine_method": dcf.get("method"),
        "dcf_engine_fv": dcf.get("fair_value_per_share"),
        "fair_value_range": {
            "low": fr.get("low"),
            "base": fr.get("base"),
            "high": fr.get("high"),
            "basis": fr.get("basis"),
        },
        "sensitivities": {"n": len(sens_rows), "table": sens_rows, "dominant_driver": dominant},
        "directional_bias": {
            "dominant_share": bias.get("dominant_share"),
            "dominant_direction": bias.get("dominant_direction"),
            "one_sided": bias.get("one_sided"),
            "material_arguments": bias.get("material_arguments"),
            "disclosures": directional_disclosures,
        },
        "disclosures": {
            "directional_bias": directional_disclosures,
            "argued_fcf_not_applied": argued_fcf_not_applied,
        },
        "cashflow": {
            "fcf_history_n": len(history),
            "fcf_history_ge_3": len(history) >= 3,
            "fcf_history_error": fcf_err,
        },
        "icl": {
            "fundamental_critique_parseable": bool(vc),
            "relative_critique_parseable": bool(rc),
            "arguments_proposed": proposed,
            "arguments_accepted": accepted,
            "arguments_rejected": rejected,
            "proposed_n": len(proposed),
            "accepted_n": len(accepted),
            "rejected_n": len(rejected),
        },
        "failures": failures,
        "run_error": run_error,
    }


def run_one(spec: dict, *, judge, force: bool = False) -> tuple[dict, dict]:
    ticker = spec["ticker"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slice_path = OUT_DIR / f"{ticker}_state_slice{SUFFIX}.json"
    grade_path = OUT_DIR / f"{ticker}_grade{SUFFIX}.json"
    stats_path = OUT_DIR / f"{ticker}_icl_stats{SUFFIX}.json"
    fail_path = OUT_DIR / f"{ticker}_failure{SUFFIX}.json"
    query = _query(spec)

    run_error = None
    state_clean: dict = {"ticker": ticker, "sector": spec["sector"]}

    if slice_path.exists() and not force:
        print(f"[{ticker}] reusing {slice_path}")
        raw = json.loads(slice_path.read_text())
        state_clean = {k: v for k, v in raw.items() if not str(k).startswith("_")}
        run_error = (raw.get("_baseline_meta") or {}).get("run_error")
    else:
        print(f"[{ticker}] FWD-07-CLEAN deep_dive sector={spec['sector']}")
        print(f"[{ticker}] query={query!r}")
        t0 = datetime.now(timezone.utc)
        try:
            result = run_deep_dive(
                ticker=ticker,
                sector=spec["sector"],
                user_query=query,
            )
            elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
            state = state_slice(result)
            # recommendation is structured — ensure slice keeps it
            if isinstance(result.get("recommendation"), dict):
                state["recommendation"] = result["recommendation"]
            state["query_type"] = result.get("query_type")
            state["user_query"] = query
            state["prior_run_id"] = result.get("prior_run_id")
            state["_baseline_meta"] = {
                "phase": "fwd_clean",
                "elapsed_sec": elapsed,
                "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "archetype_note": spec["archetype_note"],
                "qc_status": result.get("qc_status"),
                "validation_status": result.get("validation_status"),
                "query_type": result.get("query_type"),
                "user_query": query,
                "prior_run_id": result.get("prior_run_id"),
                "memory_db": str(CLEAN_MEMORY_DB),
                "prompt_template": PROMPT_TEMPLATE,
            }
            slice_path.write_text(json.dumps(state, indent=2, default=str))
            state_clean = {k: v for k, v in state.items() if not str(k).startswith("_")}
            print(
                f"[{ticker}] done in {elapsed/60:.1f} min; "
                f"qc={result.get('qc_status')} validation={result.get('validation_status')} "
                f"query_type={result.get('query_type')} prior={result.get('prior_run_id')}"
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
            run_error = f"{type(exc).__name__}: {exc}"
            fail_path.write_text(
                json.dumps(
                    {
                        "ticker": ticker,
                        "error": run_error,
                        "traceback": traceback.format_exc(),
                        "elapsed_sec": elapsed,
                    },
                    indent=2,
                )
            )
            state = {
                "ticker": ticker,
                "sector": spec["sector"],
                "mode": "deep_dive",
                "user_query": query,
                "fundamental_valuation": "",
                "relative_valuation": "",
                "final_memo": "",
                "_baseline_meta": {"phase": "fwd_clean", "run_error": run_error},
            }
            slice_path.write_text(json.dumps(state, indent=2, default=str))
            state_clean = {k: v for k, v in state.items() if not str(k).startswith("_")}
            print(f"[{ticker}] PIPELINE FAILED: {run_error}")

    stats = extract_stats(state_clean, run_error=run_error)
    stats["archetype_note"] = spec["archetype_note"]
    stats_path.write_text(json.dumps(_jsonable(stats), indent=2))
    if stats.get("failures"):
        fail_path.write_text(json.dumps(_jsonable(stats["failures"]), indent=2))

    grade = grade_valuation(state_clean, judge=judge, include_fwd=True)
    grade["phase"] = "fwd_clean"
    grade["archetype_note"] = spec["archetype_note"]
    grade["extraction_archetype"] = stats.get("extraction_archetype")
    grade["graded_at_utc"] = datetime.now(timezone.utc).isoformat()
    grade["source_slice"] = slice_path.name
    grade["user_query"] = query
    grade["prior_run_id"] = stats.get("prior_run_id")
    grade_path.write_text(json.dumps(grade, indent=2))

    print(
        f"[{ticker}] mechanical {grade['mechanical_score']}/{grade['mechanical_max']} "
        f"advisory {grade['advisory_score']}/{grade['advisory_max']} "
        f"(legacy total {grade['score']}/{grade['max_score']}) "
        f"arch={stats.get('extraction_archetype')} method={stats.get('dcf_engine_method')}"
    )
    for c in grade["criteria"]:
        tag = "ADV" if c.get("advisory") else "MEC"
        mark = "PASS" if c["passed"] else "FAIL"
        print(f"  {c['id']:2} [{tag}] {mark}  {c['name']}")
    for c in grade.get("fwd_criteria") or []:
        vac = " (vacuous)" if c.get("vacuous") else ""
        mark = "PASS" if c["passed"] else "FAIL"
        print(f"  {c['id']:16} {mark}{vac}  {c['name']}")
    return grade, stats


def write_reports(grades: list[dict], stats_by: dict[str, dict]) -> None:
    lines = [
        "# FWD-07-CLEAN Controlled Eight-Ticker Baseline",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "Branch base: `fix/valuation-engine-arithmetic` (argued-DCF arithmetic + grader fixes).",
        f"Artifact suffix: `{SUFFIX}`",
        f"Memory: isolated at `{CLEAN_MEMORY_DB.name}` + `MAS_MEMORY_DISABLE_PRIOR=1`",
        f"Prompt template: `{PROMPT_TEMPLATE}`",
        "XOM → CVX (entity resolution filed separately against `get_cik_for_ticker`).",
        "",
        "## Headline (do not use a single 11-point score)",
        "",
        "| Ticker | Archetype note | Extracted | Method | Mechanical 9 | Advisory C1/C8 | F-plaus | F-coher | Prior id | Failures |",
        "|--------|----------------|-----------|--------|-------------:|--------------:|:-------:|:-------:|---------:|---------:|",
    ]
    for g in grades:
        t = g.get("ticker") or "?"
        st = stats_by.get(t) or {}
        fwd = {c["id"]: c for c in (g.get("fwd_criteria") or [])}
        fp = fwd.get("F-plausibility") or {}
        fc = fwd.get("F-coherence") or {}
        lines.append(
            f"| {t} | {g.get('archetype_note')} | {st.get('extraction_archetype')} | "
            f"{st.get('dcf_engine_method')} | "
            f"**{g.get('mechanical_score')}/{g.get('mechanical_max')}** | "
            f"{g.get('advisory_score')}/{g.get('advisory_max')} (advisory) | "
            f"{'PASS' if fp.get('passed') else 'FAIL'} | "
            f"{'PASS' if fc.get('passed') else 'FAIL'} | "
            f"{st.get('prior_run_id')} | {len(st.get('failures') or [])} |"
        )

    lines += [
        "",
        "## Per-criterion × per-ticker (mechanical + advisory)",
        "",
        "| # | Criterion | kind | "
        + " | ".join(g.get("ticker") or "?" for g in grades)
        + " | Pass rate |",
        "|---|-----------|------|"
        + "|".join(["---"] * len(grades))
        + "|----------|",
    ]
    by_ticker = {
        g.get("ticker"): {c["id"]: c for c in g.get("criteria") or []} for g in grades
    }
    for spec in RUBRIC:
        cid = spec["id"]
        kind = "advisory" if cid in ADVISORY_CRITERION_IDS else "mechanical"
        cells = []
        n_pass = n = 0
        for g in grades:
            c = by_ticker.get(g.get("ticker"), {}).get(cid)
            if not c:
                cells.append("—")
                continue
            n += 1
            if c.get("passed"):
                n_pass += 1
                cells.append("PASS")
            else:
                cells.append("FAIL")
        lines.append(
            f"| {cid} | {spec['criterion']} | {kind} | "
            + " | ".join(cells)
            + f" | {n_pass}/{n} |"
        )

    lines += [
        "",
        "## FWD criteria (structured-state)",
        "",
        "F-arithmetic is enforced by `tests/test_argued_arithmetic_invariants.py` "
        "(unit tests, not a per-memo grade). F1–F7 vacuous-pass when forecast path is off.",
        "",
    ]
    # Per-ticker detail
    lines += ["## Per-ticker detail", ""]
    for g in grades:
        t = g.get("ticker")
        st = stats_by.get(t) or {}
        fr = st.get("fair_value_range") or {}
        lines += [
            f"### {t}",
            f"- Query: `{st.get('user_query')}`",
            f"- query_type={st.get('query_type')} prior_run_id={st.get('prior_run_id')}",
            f"- Mechanical **{g.get('mechanical_score')}/{g.get('mechanical_max')}** "
            f"advisory {g.get('advisory_score')}/{g.get('advisory_max')}",
            f"- Method `{st.get('dcf_engine_method')}` arch `{st.get('extraction_archetype')}`",
            f"- FV range {fr.get('low')} / **{fr.get('base')}** / {fr.get('high')}",
            f"- Recommendation: `{st.get('recommendation')}`",
            f"- Failures: {st.get('failures')}",
            "",
        ]
        for c in g.get("criteria") or []:
            if not c.get("passed"):
                lines.append(f"  - FAIL C{c['id']} {c['name']}: {c.get('detail')}")
        for c in g.get("fwd_criteria") or []:
            if not c.get("passed") or (c.get("vacuous") is False and c.get("id", "").startswith("F-")):
                mark = "PASS" if c.get("passed") else "FAIL"
                vac = " vacuous" if c.get("vacuous") else ""
                lines.append(f"  - {mark}{vac} {c['id']}: {c.get('detail')}")
        lines.append("")

    path = OUT_DIR / f"comparison{SUFFIX}.md"
    path.write_text("\n".join(lines))
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "fwd_clean",
        "suffix": SUFFIX,
        "prompt_template": PROMPT_TEMPLATE,
        "memory_db": str(CLEAN_MEMORY_DB),
        "memory_prior_disabled": True,
        "tickers": [g.get("ticker") for g in grades],
        "scores": [
            {
                "ticker": g.get("ticker"),
                "mechanical_score": g.get("mechanical_score"),
                "mechanical_max": g.get("mechanical_max"),
                "advisory_score": g.get("advisory_score"),
                "advisory_max": g.get("advisory_max"),
                "extraction_archetype": (stats_by.get(g.get("ticker") or "") or {}).get(
                    "extraction_archetype"
                ),
                "method": (stats_by.get(g.get("ticker") or "") or {}).get("dcf_engine_method"),
                "criteria": [
                    {
                        "id": c["id"],
                        "passed": c["passed"],
                        "advisory": c.get("advisory"),
                        "detail": c.get("detail"),
                    }
                    for c in g.get("criteria") or []
                ],
                "fwd_criteria": g.get("fwd_criteria"),
                "failures": (stats_by.get(g.get("ticker") or "") or {}).get("failures"),
                "prior_run_id": (stats_by.get(g.get("ticker") or "") or {}).get("prior_run_id"),
            }
            for g in grades
        ],
    }
    (OUT_DIR / f"summary{SUFFIX}.json").write_text(json.dumps(summary, indent=2, default=str))
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
            print("unknown ticker(s)", sorted(only or []))
            return 2

    print(f"[fwd_clean] MAS_MEMORY_DB={os.environ.get('MAS_MEMORY_DB')}")
    print(f"[fwd_clean] MAS_MEMORY_DISABLE_PRIOR={os.environ.get('MAS_MEMORY_DISABLE_PRIOR')}")
    print(f"[fwd_clean] prompt={PROMPT_TEMPLATE!r}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    judge = make_llm_judge()
    grades: list[dict] = []
    stats_by: dict[str, dict] = {}

    for spec in specs:
        try:
            need = force or not (OUT_DIR / f"{spec['ticker']}_state_slice{SUFFIX}.json").exists()
            g, st = run_one(spec, judge=judge, force=need)
            grades.append(g)
            stats_by[spec["ticker"]] = st
        except Exception as exc:  # noqa: BLE001
            print(f"[{spec['ticker']}] outer failure: {exc}")
            traceback.print_exc()
            grades.append(
                {
                    "ticker": spec["ticker"],
                    "mechanical_score": 0,
                    "mechanical_max": 9,
                    "advisory_score": 0,
                    "advisory_max": 2,
                    "score": 0,
                    "max_score": 11,
                    "criteria": [],
                    "archetype_note": spec["archetype_note"],
                }
            )
            stats_by[spec["ticker"]] = {
                "ticker": spec["ticker"],
                "failures": [{"stage": "outer", "what": str(exc)}],
            }

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
