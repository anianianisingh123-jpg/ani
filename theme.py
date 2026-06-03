"""
theme.py — SIGNAL Bloomberg-terminal UI: global CSS, sticky nav, and the
shared render helpers (section headers, memo containers, pills, tables).
"""

from __future__ import annotations

import html as _html

import streamlit as st

GOLD = "#c9a84c"
GOLD_DARK = "#a07c30"
BG = "#0a0a0a"
CARD = "#111111"
BORDER = "#1e1e1e"
TEXT = "#e8e3d6"
MUTED = "#8a8470"

def inject_theme() -> None:
    # IMPORTANT: the markdown string MUST begin with <style> so CommonMark treats
    # it as a single raw-HTML block that ends only at </style>. (A leading <link>
    # tag would open a different HTML block that terminates at the first blank
    # line, leaking the rest of the CSS onto the page as visible text.) The font
    # is therefore pulled in via @import as the first line inside the stylesheet.
    st.markdown(
        f"""<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Cormorant+Garamond:wght@500;600&display=swap');
:root {{
  --gold:{GOLD}; --gold-dark:{GOLD_DARK}; --bg:{BG};
  --card:{CARD}; --border:{BORDER}; --text:{TEXT}; --muted:{MUTED};
}}

html {{ scroll-behavior: smooth; }}

html, body, .stApp {{
  background-color: var(--bg) !important;
  color: var(--text) !important;
}}
.stApp {{
  background: radial-gradient(ellipse at top, #121110 0%, #0a0a0a 55%) !important;
}}

/* Base font: JetBrains Mono throughout */
html, body, p, li, span, div, label, input, button,
.stMarkdown, .stMarkdown p, .stMarkdown li {{
  font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace !important;
}}

/* Readability: body 15px, memo text 16px, generous line height */
.stMarkdown, .stMarkdown p, .stMarkdown li, p, li {{
  font-size: 15px !important;
  line-height: 1.8 !important;
  color: var(--text) !important;
}}

h1, h2, h3, h4, h5 {{ color: var(--gold) !important; font-weight: 600 !important; }}
.stMarkdown h2 {{
  font-size: 18px !important; letter-spacing: 0.06em;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0.35rem; margin-top: 1.4rem;
}}
.stMarkdown h3 {{ font-size: 15px !important; color: var(--gold-dark) !important; letter-spacing: 0.05em; }}
strong, b {{ color: #f0e6c8 !important; font-weight: 600 !important; }}
a, a:visited {{ color: var(--gold) !important; text-decoration: none !important; }}

#MainMenu, footer, header {{ visibility: hidden; }}

.block-container {{
  padding-top: 1.6rem !important;
  max-width: 1080px;
}}

/* ── Tabs (the primary navigation) ──────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {{
  gap: 2px; justify-content: center; flex-wrap: wrap;
  border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 50;
  background: rgba(10,10,10,0.92);
  backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
}}
.stTabs [data-baseweb="tab"] {{
  background: transparent !important; color: var(--muted) !important;
  font-family: 'JetBrains Mono', monospace !important; font-size: 11px !important;
  letter-spacing: 0.2em; text-transform: uppercase; font-weight: 500;
  padding: 10px 16px;
}}
.stTabs [data-baseweb="tab"]:hover {{ color: var(--gold) !important; }}
.stTabs [aria-selected="true"] {{ color: var(--gold) !important; }}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] {{ background-color: var(--gold) !important; }}

/* anchor (kept harmless; tabs are the real nav now) */
.anchor {{ display: none; }}

/* ── Hero ───────────────────────────────────────────────────────────── */
.signal-title {{
  font-family: 'JetBrains Mono', monospace; font-size: 4.6rem; font-weight: 700;
  letter-spacing: 0.55rem; color: var(--gold); margin: 0; line-height: 1;
  text-shadow: 0 0 28px rgba(201,168,76,0.16);
}}
.signal-subtitle {{
  font-size: 0.66rem; font-weight: 500; letter-spacing: 0.42rem;
  color: var(--muted); margin-top: 0.7rem; text-transform: uppercase;
}}
.signal-meta {{ font-size: 0.66rem; color: #6a6555; letter-spacing: 0.2rem; margin-top: 0.7rem; text-transform: uppercase; }}

/* ── Section headers (3px gold left border + 12px pad) ───────────────── */
.sig-section {{ margin-top: 2rem; margin-bottom: 1rem; }}
.sig-section .num {{ font-size: 0.6rem; color: #6a6555; letter-spacing: 0.3em; text-transform: uppercase; }}
.sig-section .title {{
  font-size: 20px; letter-spacing: 0.12em; color: var(--gold);
  text-transform: uppercase; font-weight: 600;
  border-left: 3px solid var(--gold); padding-left: 12px; margin-top: 4px;
}}
.sig-sub {{
  font-size: 14px; letter-spacing: 0.08em; color: var(--gold-dark);
  text-transform: uppercase; font-weight: 500; margin: 0.6rem 0 0.4rem 0;
}}
.sig-caption {{
  font-size: 11px; color: #6a6555; letter-spacing: 0.12em;
  margin: 0.2rem 0 0.8rem 0; line-height: 1.6;
}}
.sig-divider {{ border: none; border-top: 1px solid var(--gold); opacity: 0.18; margin: 2rem 0; }}

/* ── Memo / generic card containers (bordered) ──────────────────────── */
div[data-testid="stVerticalBlockBorderWrapper"] {{
  background: var(--card); border: 1px solid var(--border) !important;
  border-left: 3px solid var(--gold) !important;
  border-radius: 3px; padding: 6px 10px;
  transition: border-color 0.4s ease;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:hover {{
  border-color: rgba(201,168,76,0.5) !important;
}}
.memo-body, .memo-body p, .memo-body li {{ font-size: 16px !important; line-height: 1.8 !important; }}

/* ── Buttons ────────────────────────────────────────────────────────── */
.stButton > button, .stDownloadButton > button {{
  background-color: transparent !important; color: var(--gold) !important;
  font-family: 'JetBrains Mono', monospace !important; font-weight: 500 !important;
  font-size: 10px !important; letter-spacing: 0.2em !important; text-transform: uppercase !important;
  border: 1px solid var(--gold) !important; padding: 0.6rem 1.2rem !important;
  border-radius: 2px !important; transition: all 0.2s ease; width: 100%;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
  background-color: var(--gold) !important; color: var(--bg) !important;
}}
.stButton > button:focus {{ box-shadow: none !important; outline: none !important; }}

/* Inputs / selects */
.stTextInput > div > div > input, .stSelectbox div[data-baseweb="select"] > div {{
  background-color: #131313 !important; color: var(--text) !important;
  border: 1px solid var(--border) !important; border-radius: 2px !important;
  font-family: 'JetBrains Mono', monospace !important; font-size: 14px !important;
}}
.stTextInput > div > div > input:focus {{ border-color: var(--gold) !important; box-shadow: none !important; }}

/* Progress bar gold + indeterminate loader */
.stProgress > div > div > div > div {{ background-color: var(--gold) !important; }}
.stProgress > div > div > div {{ background-color: var(--border) !important; }}
.gold-loader {{ height: 3px; width: 100%; background: var(--border); overflow: hidden; border-radius: 2px; margin: 6px 0 10px 0; }}
.gold-loader::after {{
  content: ""; display: block; height: 100%; width: 40%;
  background: linear-gradient(90deg, transparent, var(--gold), transparent);
  animation: loadslide 1.1s ease-in-out infinite;
}}
@keyframes loadslide {{ 0% {{ transform: translateX(-100%); }} 100% {{ transform: translateX(350%); }} }}

/* status dots */
.dot {{ display:inline-block; width:7px; height:7px; border-radius:50%; margin-right:6px; vertical-align:middle; animation: pulse 1.6s ease-in-out infinite; }}
@keyframes pulse {{ 0%,100% {{ opacity:0.35; }} 50% {{ opacity:1; }} }}

/* pills / badges */
.pill {{
  display:inline-block; font-family:'JetBrains Mono',monospace; font-size:10px;
  font-weight:600; letter-spacing:0.18em; text-transform:uppercase;
  padding:2px 8px; border-radius:2px;
}}

/* ── Generic data table (screener / CDS / CB) ───────────────────────── */
.table-scroll {{ overflow-x: auto; border:1px solid var(--border); border-radius:3px; margin-top:0.4rem; }}
table.sig-table {{ width:100%; border-collapse:collapse; font-family:'JetBrains Mono',monospace; font-size:12px; min-width:680px; }}
table.sig-table th {{
  color:#6a6555; font-size:9px; letter-spacing:0.2em; text-transform:uppercase;
  text-align:right; padding:9px 10px; border-bottom:1px solid var(--gold);
  background:#0e0e0e; position:sticky; top:0; white-space:nowrap;
}}
table.sig-table th.l, table.sig-table td.l {{ text-align:left; }}
table.sig-table td {{ padding:8px 10px; border-bottom:1px solid #161616; text-align:right; color:var(--text); white-space:nowrap; }}
table.sig-table tr:hover td {{ background:#141310; }}
table.sig-table .tk {{ color:var(--gold); font-weight:600; letter-spacing:0.1em; }}
table.sig-table .mut {{ color:var(--muted); }}
.pos {{ color:#4ade80; }} .neg {{ color:#e05c5c; }}

/* ── Globe legend + geo legend + hotspots ───────────────────────────── */
.legend-row {{
  display:flex; flex-wrap:wrap; justify-content:center; gap:14px;
  font-family:'JetBrains Mono',monospace; font-size:10px; letter-spacing:0.12em;
  color:var(--muted); margin-top:0.6rem;
}}
.legend-dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:5px; vertical-align:middle; }}
.hotspot {{
  background:var(--card); border:1px solid var(--border); border-left:3px solid #c43a1a;
  border-radius:3px; padding:10px 12px; margin-bottom:8px;
}}
.hotspot .hs-name {{ color:var(--gold); font-weight:600; font-size:12px; letter-spacing:0.12em; }}
.hotspot .hs-lvl {{ font-size:9px; letter-spacing:0.2em; font-weight:600; padding:1px 6px; border-radius:2px; margin-left:8px; }}
.hotspot .hs-brief {{ font-size:13px; line-height:1.7; color:var(--text); margin-top:6px; }}

/* ── Pulse / position / stress / macro cards ────────────────────────── */
.pulse-card {{
  background:var(--card); border:1px solid var(--border); border-left:3px solid var(--gold);
  border-radius:3px; padding:1rem 1.1rem; margin-bottom:0.8rem; min-height:210px;
  transition: border-color 0.4s ease;
}}
.pulse-card:hover {{ border-color: rgba(201,168,76,0.5); }}
.pulse-card .ticker {{ font-size:1.4rem; font-weight:600; color:var(--gold); letter-spacing:0.08em; }}
.pulse-card .company {{ font-size:0.66rem; color:var(--muted); letter-spacing:0.22em; text-transform:uppercase; margin-bottom:0.3rem; }}
.pulse-card .weight {{ font-size:0.62rem; color:#6a6555; letter-spacing:0.2em; text-transform:uppercase; }}
.pulse-card .status-badge {{ display:inline-block; font-size:0.62rem; font-weight:600; letter-spacing:0.2em; text-transform:uppercase; padding:3px 8px; border-radius:2px; margin-top:0.4rem; }}
.pulse-card .body {{ font-size:14px; line-height:1.7; color:var(--text); margin-top:0.7rem; }}
.pulse-card .val-signal {{ font-size:10px; color:var(--gold); letter-spacing:0.08em; margin-top:0.6rem; padding-top:0.4rem; border-top:1px dotted var(--border); }}
.pulse-card.skeleton .body::after {{ content:"researching…"; font-size:0.7rem; color:#6a6555; letter-spacing:0.22em; animation:pulse 1.4s ease-in-out infinite; }}

.stress-card {{ background:#0e0e0e; border:1px solid var(--border); border-radius:3px; padding:0.9rem 1.1rem; margin-top:0.5rem; }}
.stress-card.strong {{ border-left:3px solid #4ade80; }}
.stress-card.weak {{ border-left:3px solid #e05c5c; }}
.stress-card.neutral {{ border-left:3px solid var(--gold); }}
.stress-card .row {{ font-size:13px; line-height:1.7; }}
.stress-card .lbl {{ font-size:9px; letter-spacing:0.2em; text-transform:uppercase; color:#6a6555; }}

/* ── Debt-cycle profile card ────────────────────────────────────────── */
.dc-card {{ background:var(--card); border:1px solid var(--border); border-left:3px solid var(--gold); border-radius:3px; padding:1rem 1.2rem; }}
.dc-card .dc-name {{ font-size:1.3rem; color:var(--gold); font-weight:600; letter-spacing:0.06em; }}
.dc-card .dc-phase {{ font-size:11px; letter-spacing:0.16em; text-transform:uppercase; font-weight:600; padding:3px 9px; border-radius:2px; display:inline-block; margin-top:6px; }}
.dc-ind {{ display:grid; grid-template-columns:1fr 1fr; gap:6px 14px; margin-top:0.9rem; font-size:12px; }}
.dc-ind .k {{ color:#6a6555; letter-spacing:0.1em; }}
.dc-ind .v {{ color:var(--text); text-align:right; }}

/* ── Native st.metric cards (debt-cycle indicators) ─────────────────── */
div[data-testid="stMetric"] {{
  background: var(--card); border: 1px solid var(--border);
  border-left: 3px solid var(--gold); border-radius: 3px;
  padding: 0.7rem 0.9rem;
}}
div[data-testid="stMetric"] label,
div[data-testid="stMetricLabel"], div[data-testid="stMetricLabel"] p {{
  color: var(--muted) !important; font-size: 10px !important;
  letter-spacing: 0.14em !important; text-transform: uppercase !important;
  font-family: 'JetBrains Mono', monospace !important;
}}
div[data-testid="stMetricValue"] {{
  color: var(--text) !important; font-family: 'JetBrains Mono', monospace !important;
  font-size: 1.45rem !important; font-weight: 600 !important;
}}
.dc-badge-row {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:0.2rem 0 0.4rem 0; }}

/* ── Earnings calendar rows ─────────────────────────────────────────── */
.cal-row {{ display:grid; grid-template-columns:80px 1fr 150px 90px 90px; gap:0.8rem; align-items:center; padding:0.7rem 0.9rem; border-bottom:1px solid #161616; font-size:12px; }}
.cal-row .tk {{ color:var(--gold); font-weight:600; letter-spacing:0.12em; }}
.cal-row .nm {{ color:var(--text); }}
.cal-row .dt {{ color:var(--text); letter-spacing:0.06em; }}
.cal-row .ep {{ color:var(--muted); }}
.cal-row .du {{ color:#6a6555; letter-spacing:0.12em; text-align:right; }}
.cal-row.head {{ color:#6a6555; font-size:9px; letter-spacing:0.24em; text-transform:uppercase; border-bottom:1px solid var(--gold); opacity:0.6; }}

/* ── Toggle (radio) styling for globe layers ────────────────────────── */
div[role="radiogroup"] label {{ font-size:11px !important; letter-spacing:0.1em; }}

/* ── Mobile ─────────────────────────────────────────────────────────── */
@media (max-width: 640px) {{
  .signal-title {{ font-size: 3rem !important; letter-spacing: 0.32rem !important; }}
  .block-container {{ padding-top: 5.4rem !important; }}
  .sig-section .title {{ font-size: 17px; }}
  .cal-row {{ grid-template-columns: 1fr; gap:0.15rem; }}
  .cal-row .du {{ text-align:left; }}
  .dc-ind {{ grid-template-columns: 1fr; }}
  .signal-nav .brand {{ display:none; }}
  .legend-row {{ gap:8px; font-size:9px; }}
}}
</style>
""",
        unsafe_allow_html=True,
    )


def anchor(aid: str) -> None:
    st.markdown(f'<span class="anchor" id="{aid}"></span>', unsafe_allow_html=True)


def section_header(num: str, title: str, aid: str | None = None) -> None:
    if aid:
        anchor(aid)
    st.markdown(
        f'<div class="sig-section"><div class="num">{num}</div>'
        f'<div class="title">{title}</div></div>',
        unsafe_allow_html=True,
    )


def subheader(text: str) -> None:
    st.markdown(f'<div class="sig-sub">{text}</div>', unsafe_allow_html=True)


def caption(text: str) -> None:
    st.markdown(f'<div class="sig-caption">{text}</div>', unsafe_allow_html=True)


def divider() -> None:
    st.markdown('<hr class="sig-divider">', unsafe_allow_html=True)


def loader(label: str = "") -> str:
    """Return HTML for an indeterminate gold progress bar (place under a header)."""
    cap = f'<div class="sig-caption">{_html.escape(label)}</div>' if label else ""
    return f'{cap}<div class="gold-loader"></div>'


def pill(label: str, color: str) -> str:
    return f'<span class="pill" style="background:{color}22;color:{color};border:1px solid {color};">{_html.escape(label)}</span>'


def esc(s) -> str:
    return _html.escape(str(s)) if s is not None else ""
