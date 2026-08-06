"""Run the full research graph with no network and no LLM spend.

Why this exists
---------------
Every node that matters is an LLM call behind a network call, so until now the
only way to see the pipeline actually execute was to pay for it. That made the
three things unit tests cannot reach untestable in practice:

  1. the terminal paths — `docx_export`, `qc_halt`, `validation_halt` — and
     whether the compliance audit log is written on each,
  2. whether `finalize_run_cost` runs exactly once per run on every path,
  3. whether state keys are populated at each phase boundary, in a real graph
     traversal rather than a hand-built fixture.

`offline_mode()` swaps the model and every network seam for recorded material,
leaving routing, the deferred joins, validation, the deterministic valuation
math, artifact writing and cost accounting completely untouched. What runs is
the real graph; only the two things that cost money are replaced.

This is a fidelity boundary, not a simulation: it exercises the machine, not
the judgment. It cannot tell you whether a memo is any good.

Usage
-----
    from mas_sector_system.offline import offline_mode, transcript_from_slice

    transcript = transcript_from_slice("outputs/val02_baseline/KO_state_slice_fwd_clean.json")
    with offline_mode(transcript) as recorder:
        result = run_deep_dive(ticker="KO", sector="Consumer Staples",
                               user_query="Is KO a buy?")
    recorder.calls            # every node label the graph actually invoked
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

# Node labels that `_invoke` is called with, mapped to the state field whose
# recorded text should be replayed for them. Labels not listed here fall back
# to `Transcript.default`, which keeps the harness working when a new node is
# added rather than failing on an unrelated change.
LABEL_TO_STATE_FIELD: dict[str, str] = {
    "business_overview": "business_overview",
    "macro_regime": "macro_regime_assessment",
    "management_track_record": "management_assessment",
    "capital_allocation": "capital_allocation_assessment",
    "bull": "bull_thesis",
    "bear": "bear_thesis",
    "fundamental": "fundamental_valuation",
    "relative": "relative_valuation",
    "synthesis": "final_memo",
    "style_pass": "styled_memo",
    "qc": "qc_report",
    "screener": "final_memo",
}

# Critique calls expect a JSON object back, not prose. Replaying the recorded
# prose here would exercise the parse-failure branch on every run, so these get
# the recorded critique object when the slice carries one.
LABEL_TO_JSON_FIELD: dict[str, str] = {
    "fundamental:critique": "valuation_critique",
    "relative:critique": "relative_critique",
}

_GENERIC_PROSE = (
    "## Offline replay\n\nThis text was produced by the offline harness, not by "
    "a model. It exists so the graph has a non-empty response to carry.\n"
)


class Transcript:
    """Recorded responses keyed by the node label `_invoke` receives."""

    def __init__(
        self,
        responses: Optional[dict[str, str]] = None,
        *,
        default: str = _GENERIC_PROSE,
        live: Optional[dict[str, Any]] = None,
        peers: Optional[dict[str, Any]] = None,
    ) -> None:
        self.responses = dict(responses or {})
        self.default = default
        self.live = live or {}
        self.peers = peers or {}
        self.gaps: set[str] = set()

    def text_for(self, label: str) -> str:
        if label in self.responses:
            return self.responses[label]
        # `_run` retries a weak response under the same label with a suffix.
        base = label.split(":")[0]
        if base in self.responses:
            return self.responses[base]
        self.gaps.add(label)
        return self.default

    @property
    def missing(self) -> list[str]:
        """Labels that fell through to placeholder text.

        Worth asserting on: placeholder text is short enough to trip
        `_is_weak_output`, so a gap silently doubles that node's LLM calls and
        makes any "each node ran once" assertion misleading.
        """
        return sorted(self.gaps)

    def set(self, label: str, text: str) -> "Transcript":
        self.responses[label] = text
        return self


def _prose_from_memory(
    db_path: str | Path, ticker: str
) -> dict[str, str]:
    """Newest run for `ticker` that carries a full debate, as label → text.

    The stored `*_state_slice*.json` runs have `bull_thesis` / `bear_thesis`
    empty on every ticker — the slice writer never captured them. The SQLite
    memory does carry them, so the two sources are complementary: statements
    and engine blocks from the slice, agent prose from the database.
    """
    import sqlite3

    if not Path(db_path).exists():
        return {}
    columns = {
        field: label
        for label, field in LABEL_TO_STATE_FIELD.items()
        if field not in {"styled_memo"}
    }
    fields = list(columns)
    conn = sqlite3.connect(str(db_path))
    try:
        available = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
        fields = [f for f in fields if f in available]
        if not fields:
            return {}
        rows = conn.execute(
            f"SELECT {', '.join(fields)} FROM runs "
            "WHERE UPPER(ticker) = ? ORDER BY id DESC",
            (ticker.upper(),),
        ).fetchall()
    finally:
        conn.close()

    best: dict[str, str] = {}
    for row in rows:
        candidate = {
            columns[field]: value
            for field, value in zip(fields, row)
            if isinstance(value, str) and value.strip()
        }
        # Prefer the most recent run that actually recorded the debate.
        if "bull" in candidate and "bear" in candidate:
            return candidate
        if len(candidate) > len(best):
            best = candidate
    return best


def transcript_from_slice(
    path: str | Path,
    *,
    memory_db: Optional[str | Path] = None,
    extra_prose: Optional[dict[str, str]] = None,
) -> Transcript:
    """Build a transcript from a stored `*_state_slice*.json` run.

    The recorded runs carry every agent's real output, so the replay uses the
    desk's actual language rather than placeholder text. That matters for the
    artifact assertions: the clean-memo parser is heading-driven, so a fixture
    with invented headings would prove nothing about the real parse.

    `extra_prose` supplies agent text the slice does not carry, for callers
    with no run database. The slice has no `bull_thesis` / `bear_thesis`, so
    without one of the two sources those nodes fall back to placeholder text —
    which is short enough to trip `_is_weak_output`, fire the retry, and double
    their call count. That failure only appears where the 9 MB memory DB is
    absent, which is every machine except the one that recorded the runs, and
    it stayed hidden for as long as those tests skipped instead of running.
    """
    state = json.loads(Path(path).read_text())
    responses: dict[str, str] = {}
    for label, field in LABEL_TO_STATE_FIELD.items():
        value = state.get(field)
        if isinstance(value, str) and value.strip():
            responses[label] = value

    # Fill gaps (notably bull/bear) from the run database, then from any prose
    # the caller committed alongside the slice.
    if memory_db:
        for label, text in _prose_from_memory(memory_db, state.get("ticker") or "").items():
            responses.setdefault(label, text)
    for label, text in (extra_prose or {}).items():
        if isinstance(text, str) and text.strip():
            responses.setdefault(label, text)
    for label, field in LABEL_TO_JSON_FIELD.items():
        value = state.get(field)
        if isinstance(value, dict) and value:
            responses[label] = json.dumps(value)

    # data_gatherer only has to carry prose: `_stmt` in that node falls back to
    # the SEC-path statements for any key the model omits, and always restores
    # `annual_series` from the filing extraction regardless.
    # Kept comfortably above MIN_USEFUL_CHARS (200): a shorter response trips
    # `_is_weak_output` and `_run` retries, which silently doubles this node's
    # call count and would make a "each node ran once" assertion misleading.
    # The retry path gets its own dedicated test instead.
    _filler = (
        " The slice does not record this field, so the harness supplies "
        "placeholder narrative of realistic length rather than a stub short "
        "enough to trip the weak-output retry gate."
    )
    responses["data_gatherer"] = json.dumps(
        {
            "sec_filing_summary": state.get("sec_filing_summary")
            or ("Offline replay: filing summary for "
                f"{state.get('ticker')}." + _filler),
            "macro_context": state.get("macro_context")
            or ("Offline replay: macro context." + _filler),
        }
    )

    return Transcript(
        responses,
        live={
            "ticker": state.get("ticker"),
            "income_statement": state.get("income_statement") or {},
            "balance_sheet": state.get("balance_sheet") or {},
            "cash_flow_statement": state.get("cash_flow_statement") or {},
        },
        peers=(state.get("comps_engine") or {}),
    )


class _FakeResponse:
    """Minimal stand-in for a LangChain AIMessage.

    Token counts are fixed at zero on purpose: cost assertions ("finalize ran
    once", "one line in the cost log") must not depend on a text length that
    changes whenever a fixture is edited.
    """

    def __init__(self, text: str, model: str) -> None:
        self.content = text
        self.response_metadata = {
            "model": model,
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }
        self.usage_metadata = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }


class _FakeChat:
    def __init__(self, recorder: "Recorder", model: str) -> None:
        self._recorder = recorder
        self._model = model

    def invoke(self, messages: Any) -> _FakeResponse:
        label = self._recorder.current_label or "unknown"
        return _FakeResponse(self._recorder.transcript.text_for(label), self._model)


class Recorder:
    """Observes what the graph actually did during an offline run."""

    def __init__(self, transcript: Transcript) -> None:
        self.transcript = transcript
        self.calls: list[str] = []
        self.current_label: Optional[str] = None
        self.searches: list[str] = []

    @property
    def unique_calls(self) -> list[str]:
        seen: list[str] = []
        for call in self.calls:
            if call not in seen:
                seen.append(call)
        return seen

    def count(self, label: str) -> int:
        return sum(1 for call in self.calls if call == label)


def _search_digest(tag: str) -> dict[str, Any]:
    return {
        "web_research": f"[1] Offline replay digest ({tag}). No network was used.",
        "queries_run": [f"offline:{tag}"],
        "gathered_at_utc": "2026-08-03T00:00:00+00:00",
    }


@contextlib.contextmanager
def offline_mode(
    transcript: Transcript,
    *,
    memory_db: Optional[str] = None,
    disable_prior: bool = True,
) -> Iterator[Recorder]:
    """Patch the model and every network seam for the duration of the block.

    Deliberately NOT patched: routing, the graph topology, validation, the
    valuation engine, `artifacts.py`, `cost.py`, `memory.py`. Those are the
    things under test.
    """
    from . import agents, tools, valuation_engine

    recorder = Recorder(transcript)
    stack = contextlib.ExitStack()

    tmpdir = stack.enter_context(tempfile.TemporaryDirectory())
    prior_env = {
        "MAS_MEMORY_DB": os.environ.get("MAS_MEMORY_DB"),
        "MAS_MEMORY_DISABLE_PRIOR": os.environ.get("MAS_MEMORY_DISABLE_PRIOR"),
    }
    # Never let a harness run touch outputs/research_memory.sqlite.
    os.environ["MAS_MEMORY_DB"] = memory_db or str(Path(tmpdir) / "offline_memory.sqlite")
    if disable_prior:
        os.environ["MAS_MEMORY_DISABLE_PRIOR"] = "1"

    def _restore_env() -> None:
        for key, value in prior_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    stack.callback(_restore_env)

    def patch(module: Any, name: str, replacement: Any) -> None:
        original = getattr(module, name)
        setattr(module, name, replacement)
        stack.callback(setattr, module, name, original)

    # ── The model ────────────────────────────────────────────────────────────
    # `_invoke` is left completely intact so that retry-on-empty, usage
    # extraction, logging and `record_llm_call` all still run. The label is
    # captured by wrapping `_invoke`, and `_llm` returns the fake client.
    real_invoke = agents._invoke

    def fake_invoke(messages: Any, *, label: str, **kwargs: Any) -> Any:
        recorder.calls.append(label)
        recorder.current_label = label
        try:
            return real_invoke(messages, label=label, **kwargs)
        finally:
            recorder.current_label = None

    patch(agents, "_invoke", fake_invoke)
    patch(
        agents,
        "_llm",
        lambda model=agents.SONNET_MODEL, max_tokens=None, **kw: _FakeChat(
            recorder, model
        ),
    )

    # ── Network: SEC + Tavily bundle behind data_gatherer ────────────────────
    def fake_live_research(*, ticker: Any, sector: str, user_query: str) -> dict[str, Any]:
        live = transcript.live
        return {
            "entity_name": f"{ticker} (offline)",
            "cik": "0000000000",
            "gathered_at_utc": "2026-08-03T00:00:00+00:00",
            "statements_incomplete": False,
            "statements_error": None,
            "queries_run": ["offline:data_gatherer"],
            "income_statement": live.get("income_statement") or {},
            "balance_sheet": live.get("balance_sheet") or {},
            "cash_flow_statement": live.get("cash_flow_statement") or {},
            "live_market": (live.get("cash_flow_statement") or {}).get("live_market")
            or {},
            "web_research": "[1] Offline replay narrative. No network was used.",
        }

    patch(agents, "gather_live_research_context", fake_live_research)
    patch(
        agents,
        "gather_business_overview_context",
        lambda **kw: _search_digest("business_overview"),
    )
    patch(agents, "gather_macro_regime_context", lambda **kw: _search_digest("macro"))
    patch(
        agents,
        "gather_management_track_record_context",
        lambda **kw: _search_digest("management"),
    )

    def fake_multi_search(queries: list[str], **kwargs: Any) -> str:
        recorder.searches.extend(queries)
        return "[1] Offline replay search result. No network was used."

    patch(agents, "multi_search", fake_multi_search)
    patch(tools, "multi_search", fake_multi_search)

    # ── Network: yfinance-backed market structure and peers ──────────────────
    patch(
        agents,
        "fetch_options_flow",
        lambda ticker: {
            "source": "offline_replay",
            "notes": ["Offline replay — no option chain fetched."],
        },
    )
    patch(
        agents,
        "fetch_insider_alerts",
        lambda ticker: {
            "source": "offline_replay",
            "notes": ["Offline replay — no Form 4 fetch."],
        },
    )

    def fake_peers(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return dict(transcript.peers) or {
            "peers": [],
            "warnings": ["Offline replay — no peer data fetched."],
        }

    patch(valuation_engine, "fetch_peer_multiples", fake_peers)
    patch(agents, "fetch_peer_multiples", fake_peers)

    try:
        yield recorder
    finally:
        stack.close()


def offline_deep_dive(
    *,
    ticker: str,
    sector: str,
    user_query: str,
    transcript: Transcript,
    output_dir: Optional[str] = None,
) -> tuple[dict[str, Any], Recorder]:
    """Convenience wrapper: one full offline deep-dive run.

    `output_dir` redirects artifact writes so a harness run never lands a file
    in `outputs/` beside real deliverables.
    """
    from .main import run_deep_dive

    stack = contextlib.ExitStack()
    with stack:
        if output_dir:
            from . import artifacts, cost, export_docx

            # All three write into `outputs/` by default. A harness run that
            # lands a .docx or a cost line beside real deliverables is worse
            # than no harness — the first run of this leaked exactly those two.
            redirects = (
                (artifacts, "DEFAULT_OUTPUT_DIR", Path(output_dir)),
                (export_docx, "DEFAULT_OUTPUT_DIR", Path(output_dir)),
                (cost, "DEFAULT_COST_LOG", Path(output_dir) / "cost_log.jsonl"),
            )
            for module, name, value in redirects:
                if not hasattr(module, name):
                    raise AttributeError(
                        f"offline harness cannot redirect {module.__name__}.{name} "
                        "— it was renamed; fix the redirect rather than letting "
                        "the run write into outputs/"
                    )
                original = getattr(module, name)
                setattr(module, name, value)
                stack.callback(setattr, module, name, original)

        recorder = stack.enter_context(offline_mode(transcript))
        result = run_deep_dive(
            ticker=ticker, sector=sector, user_query=user_query
        )
    return result, recorder
