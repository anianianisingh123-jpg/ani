"""Full-graph runs with no network and no LLM spend (TEST-04 / TEST-06 / TEST-07).

These are the assertions the 288 unit tests cannot make, because they need an
actual graph traversal:

  * every node fires exactly once — the guard against the multi-parent fan-in
    double-execution bug `main.py` was restructured to kill,
  * all three terminal paths (`docx_export`, `qc_halt`, `validation_halt`) write
    the compliance audit log, and only the export path writes a .docx,
  * `finalize_run_cost` runs exactly once per run, on every path.

The transcript replays real recorded output — statements and engine blocks from
a stored state slice, agent prose from the run database — so the clean-memo
parser is exercised against language the desk actually produced. A fixture of
invented headings would prove nothing about the real parse.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mas_sector_system.offline import (
    Transcript,
    offline_deep_dive,
    offline_mode,
    transcript_from_slice,
)

REPO = Path(__file__).resolve().parent.parent
from fixtures import agent_prose, state_slice_path  # noqa: E402

# The KO slice is now a committed fixture (TEST-02), falling back to a local
# recording under `outputs/`. It used to resolve only to `outputs/`, which is
# gitignored — so on every machine except the one that produced the runs, the
# ten tests below SKIPPED. A fresh clone reported green while the only tests
# that exercise an actual graph traversal had never run. Skips are not passes.
#
# The memory DB stays machine-local (9 MB of real run history), but it is NOT
# optional in effect: the slice carries no `bull_thesis` / `bear_thesis`, and
# without them the transcript falls back to placeholder text short enough to
# trip the weak-output retry — so bull and bear each fire twice and
# `test_no_node_executes_twice` fails. That was invisible while these tests
# skipped. `agent_prose("KO")` commits the 63 KB those two nodes need, so the
# guarantee holds with or without the database.
SLICE = state_slice_path("KO")
MEMORY_DB = REPO / "outputs" / "research_memory.sqlite"

needs_recording = pytest.mark.skipif(
    SLICE is None,
    reason="KO state slice missing from tests/fixtures AND outputs/ — broken checkout",
)


@pytest.fixture()
def transcript() -> Transcript:
    return transcript_from_slice(
        SLICE,
        memory_db=MEMORY_DB if MEMORY_DB.exists() else None,
        extra_prose=agent_prose("KO"),
    )


@pytest.fixture()
def run(tmp_path, transcript):
    result, recorder = offline_deep_dive(
        ticker="KO",
        sector="Consumer Staples",
        user_query="Is KO a buy for a long-only book?",
        transcript=transcript,
        output_dir=str(tmp_path),
    )
    return result, recorder, tmp_path, transcript


# ─────────────────────────────────────────────────────────────────────────────
# The happy path
# ─────────────────────────────────────────────────────────────────────────────

@needs_recording
def test_the_whole_graph_runs_with_no_network_and_no_spend(run):
    result, recorder, out_dir, transcript = run

    assert transcript.missing == [], (
        f"transcript fell back to placeholder text for {transcript.missing} — "
        "placeholder is short enough to trip the weak-output retry and would "
        "distort the call counts below"
    )
    assert result["qc_status"] in {"PASS", "PASS_WITH_FLAGS"}
    assert (result.get("cost_data") or {}).get("totals", {}).get(
        "total_cost_usd"
    ) == 0.0, "a replayed run must cost nothing"


@needs_recording
def test_every_phase_populates_its_state_keys(run):
    result, _, _, _ = run
    for field in (
        "income_statement",
        "balance_sheet",
        "cash_flow_statement",
        "canonical_metrics",
        "business_overview",
        "macro_regime_assessment",
        "management_assessment",
        "capital_allocation_assessment",
        "bull_thesis",
        "bear_thesis",
        "fundamental_valuation",
        "relative_valuation",
        "final_memo",
        "styled_memo",
        "qc_report",
    ):
        assert result.get(field), f"{field} empty after a full run"

    # The deterministic engine ran and its output survived into state.
    assert (result.get("dcf_engine") or {}).get("fair_value_per_share")
    assert result["dcf_engine"]["inputs"]["base_fcf_method"] == "mid_cycle"


@needs_recording
def test_no_node_executes_twice(run):
    """The multi-parent fan-in guard, checked by traversal rather than by edges.

    `main.py` folds the foundation into one deferred join and gives bull a
    single parent precisely because analysis used to re-fire. Counting actual
    invocations is the only way to prove that still holds.
    """
    _, recorder, _, _ = run
    repeated = {
        label: recorder.count(label)
        for label in recorder.unique_calls
        if recorder.count(label) > 1
    }
    assert repeated == {}, f"nodes executed more than once: {repeated}"


@needs_recording
def test_all_three_artifacts_are_written_on_the_export_path(run):
    _, _, out_dir, _ = run
    names = sorted(p.name for p in out_dir.iterdir())
    assert any(n.endswith("_memo.docx") for n in names), names
    assert any(n.endswith("_clean_memo.json") for n in names), names
    assert any(n.endswith("_compliance_audit_log.md") for n in names), names


@needs_recording
def test_cost_is_finalized_exactly_once(run):
    """TEST-07: one run, one line in the cost log, on the export path."""
    _, _, out_dir, _ = run
    log = out_dir / "cost_log.jsonl"
    assert log.exists(), "cost log not written"
    lines = [l for l in log.read_text().splitlines() if l.strip()]
    assert len(lines) == 1, f"expected exactly one cost line, got {len(lines)}"
    assert json.loads(lines[0])["ticker"] == "KO"


@needs_recording
def test_a_harness_run_never_touches_the_real_outputs_directory(run):
    """The first version of this harness leaked a .docx and a cost line."""
    _, _, out_dir, _ = run
    real = REPO / "outputs"
    assert (out_dir / "cost_log.jsonl").exists()
    assert not (real / "KO_2026-08-03_memo.docx").exists() or (
        out_dir != real
    ), "harness wrote into the real outputs/ directory"


# ─────────────────────────────────────────────────────────────────────────────
# The paths that only exist to fail
# ─────────────────────────────────────────────────────────────────────────────

@needs_recording
def test_validation_failure_halts_before_any_analysis_spend(tmp_path, transcript):
    """A FAIL must stop before capital/bull/bear, and still write the log."""
    from mas_sector_system import agents

    result, recorder = _run_with_patch(
        agents,
        "validate_inputs",
        lambda *a, **k: {
            "status": "FAIL",
            "failures": ["offline harness: forced validation failure"],
            "warnings": [],
            "checks": [],
        },
        tmp_path,
        transcript,
    )

    assert result["validation_status"] == "FAIL"
    for downstream in ("capital_allocation", "bull", "bear", "synthesis", "qc"):
        assert downstream not in recorder.unique_calls, (
            f"{downstream} ran after a validation FAIL — the gate was bypassed"
        )

    names = sorted(p.name for p in tmp_path.iterdir())
    assert any(n.endswith("_compliance_audit_log.md") for n in names), names
    assert not any(n.endswith("_memo.docx") for n in names), names
    lines = [
        l
        for l in (tmp_path / "cost_log.jsonl").read_text().splitlines()
        if l.strip()
    ]
    assert len(lines) == 1, "cost must finalize exactly once on the halt path"


@needs_recording
def test_qc_failure_hard_stops_without_a_docx(tmp_path, transcript):
    """A QC FAIL retries synthesis once, then stops. No .docx, log still written."""
    from mas_sector_system import agents

    result, recorder = _run_with_patch(
        agents,
        "_run_qc_audit",
        # (report, status, coverage_note)
        lambda state, label="qc": ("offline harness: forced QC failure", "FAIL", ""),
        tmp_path,
        transcript,
    )

    assert result["qc_status"] == "FAIL"
    names = sorted(p.name for p in tmp_path.iterdir())
    assert not any(n.endswith("_memo.docx") for n in names), (
        f"a .docx was exported despite a QC FAIL: {names}"
    )
    assert any(n.endswith("_compliance_audit_log.md") for n in names), names
    lines = [
        l
        for l in (tmp_path / "cost_log.jsonl").read_text().splitlines()
        if l.strip()
    ]
    assert len(lines) == 1, "cost must finalize exactly once on the QC halt path"


@needs_recording
def test_a_weak_model_response_is_retried_once(tmp_path):
    """`_run`'s retry-on-empty gate, exercised end to end rather than in a unit."""
    from mas_sector_system.main import run_deep_dive

    thin = transcript_from_slice(
        SLICE,
        memory_db=MEMORY_DB if MEMORY_DB.exists() else None,
        extra_prose=agent_prose("KO"),
    )
    thin.set("business_overview", "too short")  # under MIN_USEFUL_CHARS

    with offline_mode(thin) as recorder:
        with _redirect_outputs(tmp_path):
            run_deep_dive(
                ticker="KO",
                sector="Consumer Staples",
                user_query="Is KO a buy?",
            )

    assert recorder.count("business_overview") == 2, (
        "a weak response should be retried exactly once"
    )


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _redirect_outputs(tmp_path):
    import contextlib

    from mas_sector_system import artifacts, cost, export_docx

    @contextlib.contextmanager
    def _ctx():
        saved = [
            (artifacts, "DEFAULT_OUTPUT_DIR", artifacts.DEFAULT_OUTPUT_DIR),
            (export_docx, "DEFAULT_OUTPUT_DIR", export_docx.DEFAULT_OUTPUT_DIR),
            (cost, "DEFAULT_COST_LOG", cost.DEFAULT_COST_LOG),
        ]
        artifacts.DEFAULT_OUTPUT_DIR = Path(tmp_path)
        export_docx.DEFAULT_OUTPUT_DIR = Path(tmp_path)
        cost.DEFAULT_COST_LOG = Path(tmp_path) / "cost_log.jsonl"
        try:
            yield
        finally:
            for module, name, value in saved:
                setattr(module, name, value)

    return _ctx()


def _run_with_patch(module, name, replacement, tmp_path, transcript):
    """Run one offline deep dive with a single extra patch applied."""
    from mas_sector_system.main import run_deep_dive

    original = getattr(module, name)
    setattr(module, name, replacement)
    try:
        with offline_mode(transcript) as recorder:
            with _redirect_outputs(tmp_path):
                result = run_deep_dive(
                    ticker="KO",
                    sector="Consumer Staples",
                    user_query="Is KO a buy for a long-only book?",
                )
        return result, recorder
    finally:
        setattr(module, name, original)
