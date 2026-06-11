# SIGNAL

A private research agent for Anirudh Singh, built in Streamlit on top of the
Anthropic API with web search enabled.

> **Also in this repo: ANI Terminal** — a Bloomberg-style macro research
> terminal in a single self-contained file, `index.html`. No build step, no
> API keys: open the file in a browser (or `python -m http.server` and visit
> http://localhost:8000). Live data via Yahoo Finance (allorigins proxy),
> FRED public CSV, and Atlanta Fed GDPNow; everything else is manually
> editable and persisted in localStorage. Keyboard: `1–6` switch modules,
> `/` focuses search.

Two modes:

1. **Full Research Cycle** — a six-section daily intelligence memo
   (Macro & Rates, Earnings & Corporate, AI & Technology, Geopolitical,
   Cross-Asset, Synthesis), each section streamed live to the page as it's
   generated.
2. **Deep Dive** — a single topic memo. Type any subject ("Japan yield
   crisis", "private credit stress", "Qualcomm edge AI thesis") and the agent
   produces a Howard-Marks-format memo on it.

The system prompt encodes Ani's investment lens (Dalio long-term debt cycle,
Soros reflexivity, Marks memo discipline) and current positions
(QCOM 40%, KMI 17%, CRM, Xiaomi).

## Setup

### 1. Get an Anthropic API key

https://console.anthropic.com/ — pay-as-you-go. Make sure web search is
enabled on the org (it is by default for most accounts).

### 2. Configure

```bash
cp .env.example .env
# edit .env and paste ANTHROPIC_API_KEY=sk-ant-…
```

### 3. Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Run

```bash
streamlit run app.py
```

Opens at http://localhost:8501.

## Deploy to Streamlit Community Cloud

1. Push this repo to GitHub.
2. Go to https://share.streamlit.io/ and sign in with GitHub.
3. Click **New app**, point it at this repo and `app.py` on the
   `claude/research-agent-streamlit-tW4uT` branch (or `main` once merged).
4. Open **Advanced settings → Secrets** and paste:

   ```toml
   ANTHROPIC_API_KEY = "sk-ant-…"
   ```

5. Deploy. Streamlit Cloud gives you a public URL like
   `https://signal-ani.streamlit.app`. Add it to your phone's home screen
   and you're done.

## Files

```
app.py                  # all of it — UI + prompts + streaming
.streamlit/config.toml  # dark + gold theme
requirements.txt        # streamlit, anthropic, python-dotenv
.env.example            # template for ANTHROPIC_API_KEY
```

## Notes

- Model: `claude-sonnet-4-5` with the `web_search_20250305` tool.
- Each section is capped at ~6 web searches. A full 6-section cycle is
  several dollars per run.
- Output streams section by section — text appears live, with a
  "◆ searching the web…" marker when the model is fetching.
- Each completed memo can be downloaded as markdown, or shown as a
  copyable code block.
