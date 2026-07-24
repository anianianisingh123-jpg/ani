# Master Architecture Specification: Financial Multi-Agent System (MAS)

## 1. System Objective & Architecture
The system operates in two distinct modes managed by a Supervisor Router:
- Mode 1: "The Radar" (Top-Down Screener): Takes sector-level queries (e.g., sector="Financials") and scans for high-conviction shortlists using financial APIs.
- Mode 2: "The Sniper" (Bottom-Up Deep Dive): Runs an adversarial deep-dive analysis on a single ticker (e.g., ticker="QCOM").

## 2. State Schema (`state.py`)
Our `ResearchState` dictionary must maintain the end-to-end memory context:
- Base Inputs: `mode` ("screener" | "deep_dive"), `ticker`, `sector`, `user_query`
- Worker Scratchpads: `sec_filings_summary`, `earnings_sentiment`, `quantitative_raw_data`, `raw_financials`
- Normalized Ledger: `normalized_metrics` (Holds clean non-GAAP math, e.g., stripping out non-cash tax distortions or one-off charges to calculate true adjusted P/E)
- Adversarial Debate: `bull_thesis`, `bear_thesis`, `red_team_critique`
- Final Output: `final_memo`

## 3. Execution Pipeline Topology (`main.py` & `agents.py`)
- Screener Branch: `supervisor` -> `screener_node` -> `synthesis` -> `END`
- Deep Dive Branch: `supervisor` -> `data_gatherer` -> `bull_agent` -> `bear_agent` -> `red_team_node` -> `synthesis` -> `END`

## 4. Dynamic Sector Prompt Injection
When an agent node runs, it inspects `state["sector"]` to dynamically inject valuation rules:
- Technology: Focus on SaaS margins, R&D intensity, QTL recurring licensing streams, DCF, and Sum-of-the-Parts (SOTP).
- Financials: Focus on Net Interest Margins (NIM), Loan-to-Deposit ratios, and Residual Income / Price-to-Book models.
- Energy: Focus on Net Asset Value (NAV), reserve replacement, and Brent crude correlations.

## 5. Multi-Model Tiering Logic (Anthropic mapping)
- Heavy Workers (`data_gatherer`, `screener`, `bull`, `bear`): Claude Haiku 4.5 (`claude-haiku-4-5` — cheap, fast data extraction).
- Red Team Critic (`red_team_node`): Claude Opus 4.8 (`claude-opus-4-8`) — independent auditor that critiques both bull and bear arguments against `raw_financials` for logical flaws or cherry-picked data.
- Senior Planner & Writer (`supervisor`, `synthesis`): Claude Opus 4.8 (`claude-opus-4-8` — high-level synthesis and institutional memo drafting). The supervisor itself is deterministic routing code and makes no LLM calls.
