# AGENTS.md — Collaboration Protocol

Applies to **every** agent working in this repository (Claude Code, Gemini CLI, Grok, sub-agents, and humans driving them).

The architecture specification lives in `CLAUDE.md`. The live engineering state lives in
`mas_sector_system/DEV_SCRATCHPAD.md`. This file defines how agents coordinate.

---

## Rule 1 — Read First

**Before starting ANY task, read `mas_sector_system/DEV_SCRATCHPAD.md`.**

It carries recent changes, the active data contracts and schemas, the task queue, and notes left by
other agents. Do not begin work — not even "quick" work — from the code alone. Another agent may
have changed a schema, claimed your task, or recorded a blocker that invalidates your plan.

Also skim `mas_sector_system/AI_SYNC.md` when the task touches an area with a recorded post-mortem
(memory, market-structure data, graph topology, QC).

## Rule 2 — Isolated Edits

**Stay within your assigned module boundary.**

- Touch only the modules your task names. The ownership table in `DEV_SCRATCHPAD.md`
  ("Active Architecture & Data Contracts") is the reference.
- **Do not modify core orchestration logic unless explicitly assigned.** Core orchestration means
  `main.py` (graph topology, node registration, edges) and `routing.py` (deterministic routers).
- Changing `state.py` alters a shared contract — announce it in the scratchpad *before* editing, so
  agents mid-task on other modules are not broken.
- If a task appears to require an out-of-boundary edit, stop and log it as `BLOCKED` with the reason.
  Do not widen your own scope.
- The hard invariants in `CLAUDE.md` (no `red_team_node`, no `qc_style_check`, single-parent analysis
  path, QC-never-edits-the-memo, deterministic valuation math, free-source market data) are not
  negotiable at the agent level. Overriding one requires an explicit product decision from the user.

## Rule 3 — Log When Done

**Upon completing a task or hitting a blocker, append an entry to the
"📝 Agent Activity & Handoff Logs" section of `mas_sector_system/DEV_SCRATCHPAD.md`.**

Append to the bottom. Never rewrite or delete another agent's entry. Use exactly this format:

```markdown
### [TIMESTAMP] - [AGENT_NAME] - [TASK_ID/NAME]
- What I changed:
- Files modified:
- Notes / Handoff for next agent:
- Status: [COMPLETED / BLOCKED / IN_PROGRESS]
```

Guidance:
- `TIMESTAMP` — absolute date (`2026-07-28`), or date + time when ordering within a day matters. Never relative ("yesterday").
- `AGENT_NAME` — model/tool identity, e.g. `Claude/Opus-5`, `Gemini-CLI`, `Grok`.
- `TASK_ID/NAME` — the ID from the task queue (`PDF-03`, `SEC-01`) or a short name if unqueued.
- **Files modified** — real paths, so the next agent can diff.
- **Notes / Handoff** — the part that actually matters: what you learned, what you deliberately did
  not do, what will bite the next agent. Write the sentence you would have wanted to read.
- Also update the task's row in the "📌 Active Task Queue" table (`Assignee`, `Status`) as you claim,
  finish, or block it.

Log on blockers too, not just completions. An unlogged blocker gets rediscovered at full cost by the
next agent.
