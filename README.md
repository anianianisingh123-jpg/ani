# Ani Terminal

A personal macro and investment research terminal built in Streamlit.

Pulls live data from free APIs (yfinance, FRED, NewsAPI) and uses Claude
to score the integrity of three live investment theses against current
news flow.

## Tabs

1. **Overview** — daily 30-second read across markets, rates, commodities, FX
2. **Debt Cycle** — Dalio-style short and long-term debt cycle indicators
3. **Bonds** — yield curve, spreads, inflation expectations, bond ETFs
4. **Macro Data** — US economic indicators table + global ETF proxies
5. **Commodities** — energy, metals, ag, copper/gold ratio, MAs
6. **Currencies** — DXY, majors, EM pairs, crypto
7. **Equities** — breadth, sectors, major stocks, recent earnings, news
8. **Portfolio & Thesis Tracker** — QCOM / Xiaomi / CRM thesis scoring via Claude

## Setup

### 1. Get API keys

| Key | Where | Cost |
| --- | --- | --- |
| `FRED_API_KEY` | https://fred.stlouisfed.org/docs/api/api_key.html | Free |
| `NEWS_API_KEY` | https://newsapi.org/register | Free tier available |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com/ | Pay-as-you-go |

### 2. Configure

```bash
cp .env.example .env
# edit .env and paste your keys
```

### 3. Install

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Run

```bash
streamlit run app.py
```

The app opens at http://localhost:8501.

## Notes

- All data fetches are cached for 1 hour (`st.cache_data(ttl=3600)`). Use
  the "Refresh data" button in the sidebar to force a refetch.
- News searches are cached for 30 minutes.
- The thesis tracker shows no P&L, cost basis, or dollar amounts — it
  is a thesis-integrity monitor only.
- If an API key is missing, the related sections render an empty/warning
  state rather than crashing.
- Thesis scoring uses `claude-sonnet-4-20250514` and costs a few cents
  per re-score across all three positions.

## Files

```
app.py              # Streamlit UI, all 8 tabs
data_fetcher.py     # yfinance / FRED / NewsAPI wrappers
thesis_engine.py    # Position definitions + Claude scoring
.streamlit/
  config.toml       # Dark theme
.env.example        # Template for API keys
requirements.txt
```
