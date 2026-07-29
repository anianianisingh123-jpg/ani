"""Render thesis-only ``clean_memo.json`` artifacts as institutional decks.

This module is intentionally downstream of :mod:`artifacts`: it consumes the
clean JSON contract and never reads or renders QC reports, validation output,
cost records, stale-tag findings, or compliance audit logs. Stale metrics are
already absent from the artifact by construction (``artifacts`` drops them
rather than caveating them), so nothing here needs to re-check freshness.

Schema 1.1 clean memos carry ``metrics`` and ``valuation`` blocks, which drive
the designed pages: a tearsheet, a valuation spread with a football field, a
peer-comparison page, a capital-and-market-structure page, and a bull/bear
spread. Schema 1.0 files carry prose only; every visual page is individually
skipped when its inputs are missing, so an older artifact still renders as the
long-form document it was.

Charts are drawn with fpdf2 vector primitives — no charting dependency, and
output stays crisp at any zoom. The data-ink palette is the validated default
from the `dataviz` skill, checked against this document's white surface
(categorical slots 1-3: worst all-pairs CVD ΔE 9.2, normal-vision ΔE 24.0;
diverging blue/red: CVD ΔE 23.8). Aqua sits at 2.82:1 contrast, below the 3:1
bar, so the relief rule applies: every chart carries direct value labels.

CLI:
    python -m mas_sector_system.pdf_generator outputs/NVDA_2026-07-28_clean_memo.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from fpdf import FPDF
from fpdf.enums import MethodReturnValue, XPos, YPos

_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_DIR.parent
DEFAULT_OUTPUT_DIR = _REPO_ROOT / "outputs"

_SECTION_TITLES = {
    "business_overview": "Business Overview",
    "recommendation": "Investment View",
    "macro_positioning": "Macro & Cycle Positioning",
    "management_and_capital_allocation": "Management & Capital Allocation",
    "key_debate_points": "The Central Debate",
    "valuation_reconciliation": "Valuation & Expectations",
    "catalysts_and_risks": "Catalysts, Risks & Monitoring",
    "thesis_evolution": "Thesis Evolution",
}
_DEFAULT_ORDER = tuple(_SECTION_TITLES)
_EXCLUDED_TITLE_RE = re.compile(
    r"\b(?:QC|COMPLIANCE|AUDIT|DATA QUALITY|VALIDATION|STALE[- ]TAG|RUN COST)\b",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.+)$")
_RULE_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")

# ── Institutional identity ───────────────────────────────────────────────────
_NAVY = (26, 43, 76)      # #1A2B4C deep navy — headers, rules, primary chrome
_SLATE = (91, 103, 112)   # #5B6770 slate gray — secondary text
_WHITE = (255, 255, 255)
_INK = (28, 34, 44)       # near-black body text
_LINE = (196, 202, 209)   # table rules
_PALE = (240, 243, 246)   # shaded header / zebra fill
_ACCENT = (132, 31, 41)   # restrained crimson, used only as a section marker

# ── Data ink (validated palette — see module docstring) ──────────────────────
_S1 = (42, 120, 214)      # #2a78d6 categorical slot 1 / sequential hue
_S2 = (235, 104, 52)      # #eb6834 categorical slot 2
_S3 = (27, 175, 122)      # #1baf7a categorical slot 3
_POS = _S1                # diverging cool pole
_NEG = (208, 59, 59)      # #d03b3b diverging warm pole
_MID = (240, 239, 236)    # #f0efec diverging neutral midpoint
_GOOD = (12, 163, 12)     # status — always shipped with a label, never alone
_WARN = (250, 178, 25)
_CRIT = (208, 59, 59)
_GRID = (225, 224, 217)   # #e1e0d9 hairline
_MUTED = (137, 135, 129)  # #898781 axis / muted label
# Single-hue sequential ramp, light → dark (blue).
_RAMP = [(158, 197, 244), (109, 167, 236), (85, 152, 231), (42, 120, 214), (24, 92, 171), (16, 66, 129)]

_BAR_RADIUS = 1.2   # mm ≈ 4px rounded data-end
_BAR_GAP = 0.7      # mm ≈ 2px surface gap between adjacent fills

# Every exhibit panel is drawn to a fixed width:height ratio so a chart is
# never stretched to fill whatever space is left on the page.
_ASPECT_WIDE = 2.60     # full-width exhibit
_ASPECT_HALF = 1.55     # half-width exhibit

# Strict page budget. The prose is what previously ran to 19 pages, so the cap
# applies there; exhibits are fixed-count by construction.
MAX_ANALYSIS_PAGES = 3


# ─────────────────────────────────────────────────────────────────────────────
# Prose sanitization
# ─────────────────────────────────────────────────────────────────────────────
#
# Synthesis cites canonical metrics verbatim, so the memo body is dense with
# raw XBRL provenance — 106 "(filer FY field=YYYY)" tags, 119 ISO dates, and
# machine formula fragments in the live NVDA memo. That is auditable and
# correct in the artifact; it is unreadable on a client-facing page.
#
# Converted, not deleted: the period attribution is what makes a claim
# checkable, so "(year ended 2026-01-25 (filer FY field=2026))" becomes
# "(FY2026)" rather than vanishing. Annual labels take the year from the
# period END DATE because the filer's FY field is the known-unreliable tag —
# it stamps NVDA's FY2025 close as "2026", which would render "FY2026 vs
# FY2026". Quarterly labels do use the filer field, where it is correct.

_SANITIZE_PERIODS = [
    (re.compile(r"(Q[1-4])\s+ended\s+\d{4}-\d{2}-\d{2}\s*\(?\s*filer\s+FY\s+field\s*=\s*(\d{4})\s*\)?"), r"\1 FY\2"),
    (re.compile(r"year\s+ended\s+(\d{4})-\d{2}-\d{2}\s*\(?\s*filer\s+FY\s+field\s*=\s*\d{4}\s*\)?"), r"FY\1"),
    (re.compile(r"(Q[1-4])\s+ended\s+(\d{4})-\d{2}-\d{2}"), r"\1 \2"),
    (re.compile(r"year\s+ended\s+(\d{4})-\d{2}-\d{2}"), r"FY\1"),
    (re.compile(r"\(?\s*filer\s+FY\s+field\s*=\s*(\d{4})\s*\)?"), r"FY\1"),
]

_SANITIZE_MACHINE = [
    # snake_case formula fragments: "free_cash_flow / revenue", "operating_income / revenue"
    (re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\s*/\s*[a-z][a-z0-9_]*\b"), ""),
    (re.compile(r"\b[a-z]+(?:_[a-z0-9]+){2,}\b"), ""),
    (re.compile(r"\d{4}-\d{2}-\d{2}T[\d:+\-.]+Z?"), ""),
    (re.compile(r"\bas of\s+\d{4}-\d{2}-\d{2}\b"), ""),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), ""),
    (re.compile(r"[{}\[\]]"), ""),
]

_SANITIZE_TIDY = [
    (re.compile(r"\(\s*[;,:]\s*"), "("),
    (re.compile(r"[;,:]\s*\)"), ")"),
    (re.compile(r"\(\s*\)"), ""),
    (re.compile(r"\s+([,.;:)%])"), r"\1"),
    (re.compile(r"\(\s+"), "("),
    (re.compile(r"[,;]\s*[,;]+"), ","),
    (re.compile(r"\.\s*\."), "."),
    (re.compile(r"[ \t]{2,}"), " "),
]

_QUOTED_CITATION_RE = re.compile(r'"\s*([^"\n]{1,200}?)\s*"')


def _balance_parens(line: str) -> str:
    """Drop orphan ')' and close anything left open.

    Required because the tags removed above were themselves parenthesised and
    often nested inside a paren carrying real trailing content, so a straight
    substitution leaves debris like "(FY2026);)".
    """
    out: list[str] = []
    depth = 0
    for ch in line:
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                continue
            depth -= 1
        out.append(ch)
    return "".join(out) + (")" * depth)


def sanitize_prose(text: str) -> str:
    """Strip raw XBRL tags, timestamps and JSON debris from memo prose.

    Numbers, percentages and currency are never touched — verified against the
    live memo, where all 220 numeric tokens survive.
    """
    out = text or ""
    for rules in (_SANITIZE_PERIODS, _SANITIZE_MACHINE):
        for pattern, repl in rules:
            out = pattern.sub(repl, out)
    out = _QUOTED_CITATION_RE.sub(r"\1", out)
    out = "\n".join(_balance_parens(line) for line in out.split("\n"))
    for pattern, repl in _SANITIZE_TIDY:
        out = pattern.sub(repl, out)
    return out.strip()


class CleanMemoError(ValueError):
    """Raised when an input file is not a valid clean memo artifact."""


# ─────────────────────────────────────────────────────────────────────────────
# Fonts
# ─────────────────────────────────────────────────────────────────────────────


def _font_candidates() -> list[tuple[Path, Path, Path, Path]]:
    """Return portable regular/bold/italic/bold-italic TrueType candidates."""
    candidates: list[tuple[Path, Path, Path, Path]] = []
    custom = os.environ.get("MAS_PDF_FONT_DIR")
    if custom:
        root = Path(custom).expanduser()
        candidates.append(
            tuple(root / name for name in (
                "DejaVuSans.ttf",
                "DejaVuSans-Bold.ttf",
                "DejaVuSans-Oblique.ttf",
                "DejaVuSans-BoldOblique.ttf",
            ))
        )
    candidates.extend(
        [
            tuple(Path("/usr/share/fonts/truetype/dejavu") / name for name in (
                "DejaVuSans.ttf",
                "DejaVuSans-Bold.ttf",
                "DejaVuSans-Oblique.ttf",
                "DejaVuSans-BoldOblique.ttf",
            )),
            tuple(Path("/System/Library/Fonts/Supplemental") / name for name in (
                "Arial.ttf",
                "Arial Bold.ttf",
                "Arial Italic.ttf",
                "Arial Bold Italic.ttf",
            )),
            tuple(Path("C:/Windows/Fonts") / name for name in (
                "arial.ttf",
                "arialbd.ttf",
                "ariali.ttf",
                "arialbi.ttf",
            )),
        ]
    )
    return candidates


def _resolve_font_family() -> tuple[Path, Path, Path, Path]:
    for family in _font_candidates():
        if all(path.is_file() for path in family):
            return family
    raise FileNotFoundError(
        "No Unicode TrueType font family found. Install DejaVu Sans or set "
        "MAS_PDF_FONT_DIR to a directory containing DejaVuSans.ttf and its "
        "Bold, Oblique, and BoldOblique variants."
    )


class HawktradePDF(FPDF):
    """FPDF document with restrained institutional page furniture."""

    def __init__(self, *, ticker: str, as_of: str) -> None:
        super().__init__(orientation="P", unit="mm", format="Letter")
        self.ticker = ticker
        self.as_of = as_of
        self.set_margins(22, 20, 22)
        self.set_auto_page_break(auto=True, margin=18)
        self.set_title(f"{ticker} Investment Memo")
        self.set_author("Hawktrade Research")
        regular, bold, italic, bold_italic = _resolve_font_family()
        self.add_font("Memo", "", str(regular))
        self.add_font("Memo", "B", str(bold))
        self.add_font("Memo", "I", str(italic))
        self.add_font("Memo", "BI", str(bold_italic))
        self.set_font("Memo", size=10)

    @property
    def usable_width(self) -> float:
        return self.w - self.l_margin - self.r_margin

    def header(self) -> None:
        """Fixed masthead on every page, cover included."""
        self.set_y(9)
        self.set_font("Memo", "B", 7.5)
        self.set_text_color(*_NAVY)
        self.cell(0, 4, "HAWKTRADE  |  INSTITUTIONAL EQUITY RESEARCH", align="L")
        self.set_x(self.w - self.r_margin - 60)
        self.set_font("Memo", "", 7.5)
        self.set_text_color(*_SLATE)
        self.cell(60, 4, f"{self.ticker}  ·  {self.as_of}", align="R")
        self.set_draw_color(*_NAVY)
        self.set_line_width(0.45)
        self.line(self.l_margin, 15, self.w - self.r_margin, 15)
        self.set_y(20)

    def footer(self) -> None:
        self.set_y(-11)
        self.set_draw_color(*_LINE)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_y(-9)
        self.set_font("Memo", "", 7)
        self.set_text_color(*_SLATE)
        self.cell(0, 4, "HAWKTRADE  ·  INVESTMENT MEMORANDUM", align="L")
        self.set_x(self.w - self.r_margin - 30)
        self.cell(30, 4, f"Page {self.page_no()} of {{nb}}", align="R")

    def exhibit_box(self, y: float, width: float, aspect: float) -> float:
        """Height for an exhibit of the given width at a fixed aspect ratio.

        Panels are sized from the ratio rather than from leftover page space,
        so a chart is never stretched to fill a gap.
        """
        height = width / aspect
        available = self.h - self.b_margin - y - 4
        return min(height, available)


def load_clean_memo(path: Path | str) -> dict[str, Any]:
    """Load and validate a thesis-only clean memo JSON artifact."""
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CleanMemoError(f"Invalid JSON in {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CleanMemoError("clean_memo.json must contain a JSON object")
    if payload.get("artifact") != "clean_memo":
        raise CleanMemoError(
            f"Refusing non-clean artifact {payload.get('artifact')!r}; "
            "expected artifact='clean_memo'"
        )
    if not isinstance(payload.get("sections"), dict):
        raise CleanMemoError("clean_memo.json is missing the sections object")
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Number formatting
# ─────────────────────────────────────────────────────────────────────────────


def _num(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _money(value: Any, *, digits: int = 1) -> str:
    v = _num(value)
    if v is None:
        return "n/a"
    sign = "-" if v < 0 else ""
    a = abs(v)
    for cut, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= cut:
            return f"{sign}${a / cut:.{digits}f}{suffix}"
    return f"{sign}${a:,.0f}"


def _pct(value: Any, *, digits: int = 1) -> str:
    v = _num(value)
    return "n/a" if v is None else f"{v * 100:.{digits}f}%"


def _mult(value: Any, *, digits: int = 1) -> str:
    v = _num(value)
    return "n/a" if v is None else f"{v:.{digits}f}x"


def _price(value: Any) -> str:
    v = _num(value)
    return "n/a" if v is None else f"${v:,.2f}"


def _count(value: Any) -> str:
    v = _num(value)
    if v is None:
        return "n/a"
    a = abs(v)
    sign = "-" if v < 0 else ""
    for cut, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= cut:
            return f"{sign}{a / cut:.1f}{suffix}"
    return f"{sign}{a:,.0f}"


# ─────────────────────────────────────────────────────────────────────────────
# Metric access
# ─────────────────────────────────────────────────────────────────────────────


class MetricBook:
    """Read-only lookup over the clean memo's ``metrics`` block.

    Every accessor tolerates absence: a screener run, an older schema-1.0
    artifact, or an archetype that simply does not produce a line all return
    ``None`` rather than raising, because each visual panel decides for itself
    whether it has enough data to draw.
    """

    def __init__(self, block: Any) -> None:
        self._by_id: dict[str, dict[str, Any]] = {}
        if isinstance(block, dict):
            by_id = block.get("by_id")
            if isinstance(by_id, dict):
                self._by_id = {k: v for k, v in by_id.items() if isinstance(v, dict)}
            elif isinstance(block.get("records"), list):
                self._by_id = {
                    r["id"]: r
                    for r in block["records"]
                    if isinstance(r, dict) and r.get("id")
                }
        self.count = len(self._by_id)

    def __bool__(self) -> bool:
        return bool(self._by_id)

    def value(self, *ids: str) -> Optional[float]:
        """First present value across candidate ids (metric names vary by archetype)."""
        for mid in ids:
            rec = self._by_id.get(mid)
            if rec is not None:
                v = _num(rec.get("value"))
                if v is not None:
                    return v
        return None

    def period(self, *ids: str) -> Optional[str]:
        for mid in ids:
            rec = self._by_id.get(mid)
            if rec is not None and rec.get("basis_period"):
                return str(rec["basis_period"])
        return None


def _short_period(label: Optional[str]) -> str:
    """Condense 'year ended 2026-01-25 (filer FY field=2026)' to 'FY2026'."""
    if not label:
        return ""
    m = re.search(r"filer FY field=(\d{4})", label)
    if m:
        return f"FY{m.group(1)}"
    m = re.search(r"(Q[1-4]) ended (\d{4})-", label)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    m = re.search(r"(\d{4})-\d{2}-\d{2}", label)
    return m.group(1) if m else ""


# ─────────────────────────────────────────────────────────────────────────────
# Drawing primitives
# ─────────────────────────────────────────────────────────────────────────────


def _text(
    pdf: HawktradePDF,
    x: float,
    y: float,
    txt: str,
    *,
    size: float = 8,
    style: str = "",
    color: Sequence[int] = _INK,
    align: str = "L",
    width: Optional[float] = None,
) -> None:
    pdf.set_font("Memo", style, size)
    pdf.set_text_color(*color)
    w = width if width is not None else pdf.get_string_width(txt) + 1
    if align == "R" and width is None:
        x -= w
    pdf.set_xy(x, y)
    pdf.cell(w, size * 0.42, txt, align=align)


def _caption(
    pdf: HawktradePDF,
    x: float,
    y: float,
    w: float,
    txt: str,
    *,
    size: float = 5.9,
    color: Sequence[int] = _MUTED,
) -> float:
    """Wrapped footnote text. Never use _text for captions — it does not wrap,
    so a long note runs off the page edge and collides with its neighbour."""
    pdf.set_font("Memo", "I", size)
    pdf.set_text_color(*color)
    pdf.set_xy(x, y)
    pdf.multi_cell(w, size * 0.52, txt, new_x=XPos.LEFT, new_y=YPos.NEXT)
    return pdf.get_y()


def _panel(
    pdf: HawktradePDF,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    *,
    subtitle: str = "",
    fill: Optional[Sequence[int]] = None,
) -> tuple[float, float, float, float]:
    """Draw a titled panel; return the inner plot rect (x, y, w, h)."""
    pdf.set_draw_color(*_GRID)
    pdf.set_line_width(0.2)
    if fill is not None:
        pdf.set_fill_color(*fill)
        pdf.rect(x, y, w, h, style="DF", round_corners=True, corner_radius=1.5)
    else:
        pdf.rect(x, y, w, h, style="D", round_corners=True, corner_radius=1.5)
    _text(pdf, x + 3.5, y + 3.2, title.upper(), size=6.6, style="B", color=_NAVY)
    top = y + 9.5
    if subtitle:
        _text(pdf, x + 3.5, y + 7.4, subtitle, size=5.9, color=_MUTED)
        top = y + 12.4
    return x + 3.5, top, w - 7, y + h - top - 3.5


def _legend(
    pdf: HawktradePDF,
    x: float,
    y: float,
    entries: Sequence[tuple[str, Sequence[int]]],
) -> None:
    """Swatch + ink-coloured label. Identity is never carried by colour alone."""
    cx = x
    for label, color in entries:
        pdf.set_fill_color(*color)
        pdf.set_draw_color(*color)
        pdf.rect(cx, y + 0.6, 2.6, 2.6, style="F", round_corners=True, corner_radius=0.6)
        _text(pdf, cx + 3.8, y, label, size=6, color=_SLATE)
        cx += 4.6 + pdf.get_string_width(label) + 5.5


def _hbars(
    pdf: HawktradePDF,
    x: float,
    y: float,
    w: float,
    h: float,
    rows: Sequence[tuple[str, Optional[float], str]],
    *,
    color: Sequence[int] = _S1,
    ramp: bool = False,
    label_w: float = 30,
) -> None:
    """Horizontal magnitude bars with a direct value label on every bar."""
    vals = [abs(v) for _, v, _ in rows if v is not None]
    if not vals:
        return
    top = max(vals) or 1.0
    n = len(rows)
    slot = h / n
    bar_h = min(6.5, max(3.2, slot - 2.6))
    plot_x = x + label_w
    plot_w = max(10.0, w - label_w - 20)
    for i, (label, value, shown) in enumerate(rows):
        cy = y + i * slot + (slot - bar_h) / 2
        _text(pdf, x, cy + bar_h / 2 - 1.4, label, size=6.4, color=_SLATE)
        if value is None:
            _text(pdf, plot_x, cy + bar_h / 2 - 1.4, "not available", size=6.2,
                  style="I", color=_MUTED)
            continue
        bw = max(0.8, plot_w * (abs(value) / top))
        # Sequential encoding must track MAGNITUDE, not row order — stepping by
        # position paints the largest bar the lightest whenever rows are not
        # already sorted, which inverts the whole point of the ramp.
        fill = _RAMP[min(len(_RAMP) - 1, int(round((abs(value) / top) * (len(_RAMP) - 1))))] if ramp else color
        pdf.set_fill_color(*fill)
        pdf.set_draw_color(*fill)
        pdf.rect(plot_x, cy, bw, bar_h, style="F", round_corners=("TOP_RIGHT", "BOTTOM_RIGHT"), corner_radius=_BAR_RADIUS)
        _text(pdf, plot_x + bw + 2, cy + bar_h / 2 - 1.4, shown, size=6.4, style="B", color=_INK)


def _grouped_hbars(
    pdf: HawktradePDF,
    x: float,
    y: float,
    w: float,
    h: float,
    rows: Sequence[tuple[str, Sequence[Optional[float]], Sequence[str]]],
    *,
    colors: Sequence[Sequence[int]],
    label_w: float = 30,
) -> None:
    """Two-series comparison bars — current period against the prior one."""
    vals = [abs(v) for _, series, _ in rows for v in series if v is not None]
    if not vals:
        return
    top = max(vals) or 1.0
    n = len(rows)
    slot = h / n
    k = max(1, len(colors))
    bar_h = min(3.6, max(2.0, (slot - 3.4) / k))
    plot_x = x + label_w
    plot_w = max(10.0, w - label_w - 20)
    for i, (label, series, shown) in enumerate(rows):
        base = y + i * slot + (slot - (bar_h * k + _BAR_GAP * (k - 1))) / 2
        _text(pdf, x, base + (bar_h * k) / 2 - 1.4, label, size=6.4, color=_SLATE)
        for j, value in enumerate(series):
            cy = base + j * (bar_h + _BAR_GAP)
            if value is None:
                continue
            bw = max(0.8, plot_w * (abs(value) / top))
            pdf.set_fill_color(*colors[j % k])
            pdf.rect(plot_x, cy, bw, bar_h, style="F",
                     round_corners=("TOP_RIGHT", "BOTTOM_RIGHT"), corner_radius=_BAR_RADIUS * 0.7)
            if j == 0 and j < len(shown):
                _text(pdf, plot_x + bw + 2, cy + bar_h / 2 - 1.3, shown[j], size=6.3,
                      style="B", color=_INK)


def _kpi_tile(
    pdf: HawktradePDF,
    x: float,
    y: float,
    w: float,
    h: float,
    label: str,
    value: str,
    *,
    note: str = "",
    emphasis: bool = False,
) -> None:
    """A hero number — the right form when the data's job is a single headline."""
    pdf.set_draw_color(*(_NAVY if emphasis else _GRID))
    pdf.set_fill_color(*(_NAVY if emphasis else _PALE))
    pdf.set_line_width(0.2)
    pdf.rect(x, y, w, h, style="DF", round_corners=True, corner_radius=1.5)
    _text(pdf, x + 3, y + 3.4, label.upper(), size=5.8, style="B",
          color=(_WHITE if emphasis else _MUTED))
    size = 12.5 if len(value) <= 8 else (10.5 if len(value) <= 12 else 8.6)
    _text(pdf, x + 3, y + 8.4, value, size=size, style="B",
          color=(_WHITE if emphasis else _NAVY))
    if note:
        _text(pdf, x + 3, y + h - 5.6, note, size=5.6,
              color=(_LINE if emphasis else _SLATE))


def _diverging_gauge(
    pdf: HawktradePDF,
    x: float,
    y: float,
    w: float,
    value: float,
    *,
    midpoint: float,
    lo: float,
    hi: float,
    low_label: str,
    high_label: str,
    readout: str,
) -> None:
    """Polarity around a neutral midpoint — a diverging job, drawn as a track."""
    track_h = 4.2
    span = max(1e-9, hi - lo)
    pdf.set_fill_color(*_MID)
    pdf.rect(x, y, w, track_h, style="F", round_corners=True, corner_radius=track_h / 2)
    mid_x = x + w * ((midpoint - lo) / span)
    val_x = x + w * ((min(max(value, lo), hi) - lo) / span)
    # Fill from the neutral midpoint toward the reading — the arm carries sign.
    arm_color = _POS if value <= midpoint else _NEG
    left, right = sorted((mid_x, val_x))
    if right - left > 0.4:
        pdf.set_fill_color(*arm_color)
        pdf.rect(left, y, right - left, track_h, style="F",
                 round_corners=True, corner_radius=track_h / 2)
    pdf.set_draw_color(*_SLATE)
    pdf.set_line_width(0.5)
    pdf.line(mid_x, y - 1.4, mid_x, y + track_h + 1.4)
    # 2px surface ring keeps the marker legible where it overlaps the fill.
    pdf.set_fill_color(*_WHITE)
    pdf.circle(val_x - 2.0, y + track_h / 2 - 2.0, 2.0, style="F")
    pdf.set_fill_color(*arm_color)
    pdf.circle(val_x - 1.35, y + track_h / 2 - 1.35, 1.35, style="F")
    _text(pdf, x, y + track_h + 2.6, low_label, size=5.7, color=_MUTED)
    _text(pdf, x + w, y + track_h + 2.6, high_label, size=5.7, color=_MUTED, align="R")
    _text(pdf, x, y - 5.2, readout, size=7.6, style="B", color=_INK)


def _football_field(
    pdf: HawktradePDF,
    x: float,
    y: float,
    w: float,
    h: float,
    rows: Sequence[dict[str, Any]],
    *,
    price: Optional[float],
    label_w: float = 34,
) -> None:
    """Valuation ranges on one shared price axis, with spot as a reference line.

    One axis only: every method is expressed in dollars per share, so the bars
    are directly comparable — which is the entire point of the form.
    """
    points: list[float] = []
    for row in rows:
        points.extend([v for v in (row.get("low"), row.get("base"), row.get("high")) if v is not None])
    if price is not None:
        points.append(price)
    if not points:
        return
    lo, hi = min(points), max(points)
    pad = max((hi - lo) * 0.12, hi * 0.04, 1.0)
    lo, hi = max(0.0, lo - pad), hi + pad
    span = max(1e-9, hi - lo)

    plot_x = x + label_w
    plot_w = max(20.0, w - label_w - 4)
    axis_y = y + h - 6

    def px(v: float) -> float:
        return plot_x + plot_w * ((v - lo) / span)

    # Recessive gridlines + axis ticks.
    pdf.set_draw_color(*_GRID)
    pdf.set_line_width(0.15)
    ticks = 5
    for i in range(ticks + 1):
        v = lo + span * i / ticks
        tx = px(v)
        pdf.line(tx, y, tx, axis_y)
        _text(pdf, tx - 5, axis_y + 1.4, f"${v:,.0f}", size=5.6, color=_MUTED, width=10, align="C")

    slot = (axis_y - y - 2) / max(1, len(rows))
    bar_h = min(7.0, max(3.6, slot - 4.0))
    for i, row in enumerate(rows):
        cy = y + i * slot + (slot - bar_h) / 2
        _text(pdf, x, cy + bar_h / 2 - 1.6, str(row.get("label") or ""), size=6.4,
              style="B", color=_SLATE)
        sub = str(row.get("sub") or "")
        if sub:
            _text(pdf, x, cy + bar_h / 2 + 1.6, sub, size=5.5, color=_MUTED)
        color = row.get("color") or _S1
        low, high = row.get("low"), row.get("high")
        base = row.get("base")
        if low is not None and high is not None and high > low:
            bx, bw = px(low), px(high) - px(low)
            pdf.set_fill_color(*color)
            pdf.rect(bx, cy, max(1.0, bw), bar_h, style="F",
                     round_corners=True, corner_radius=_BAR_RADIUS)
            _text(pdf, bx - 1.5, cy + bar_h / 2 - 1.4, f"${low:,.0f}", size=5.9,
                  color=_INK, align="R")
            _text(pdf, bx + bw + 1.5, cy + bar_h / 2 - 1.4, f"${high:,.0f}", size=5.9,
                  color=_INK)
            if base is not None:
                pdf.set_draw_color(*_WHITE)
                pdf.set_line_width(0.9)
                pdf.line(px(base), cy + 0.4, px(base), cy + bar_h - 0.4)
                _text(pdf, px(base) - 6, cy - 2.6, f"${base:,.0f}", size=6.0,
                      style="B", color=_INK, width=12, align="C")
        elif base is not None:
            pdf.set_fill_color(*_WHITE)
            pdf.circle(px(base) - 2.3, cy + bar_h / 2 - 2.3, 2.3, style="F")
            pdf.set_fill_color(*color)
            pdf.circle(px(base) - 1.6, cy + bar_h / 2 - 1.6, 1.6, style="F")
            _text(pdf, px(base) + 3, cy + bar_h / 2 - 1.4, f"${base:,.0f}", size=6.2,
                  style="B", color=_INK)

    if price is not None:
        pdf.set_draw_color(*_ACCENT)
        pdf.set_line_width(0.5)
        pdf.set_dash_pattern(dash=1.2, gap=1.0)
        pdf.line(px(price), y - 1, px(price), axis_y)
        pdf.set_dash_pattern()
        _text(pdf, px(price) + 1.6, y - 4.6, f"SPOT {_price(price)}", size=5.9,
              style="B", color=_ACCENT)


def _dot_row(
    pdf: HawktradePDF,
    x: float,
    y: float,
    w: float,
    label: str,
    subject: Optional[float],
    peers: Sequence[tuple[str, Optional[float]]],
    median: Optional[float],
    *,
    label_w: float = 30,
    fmt=_mult,
) -> None:
    """Subject against its peer set on one axis — identity, not magnitude.

    Peers are deliberately one muted ink rather than eight hues: their identity
    is carried by the direct ticker label, and a per-peer palette would blow
    past the categorical series cap for nothing.
    """
    values = [v for _, v in peers if v is not None]
    if subject is not None:
        values.append(subject)
    if median is not None:
        values.append(median)
    if not values:
        return
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        lo, hi = lo * 0.9, hi * 1.1 or 1.0
    pad = (hi - lo) * 0.16
    lo, hi = lo - pad, hi + pad
    span = max(1e-9, hi - lo)
    plot_x = x + label_w
    plot_w = max(20.0, w - label_w - 22)

    def px(v: float) -> float:
        return plot_x + plot_w * ((v - lo) / span)

    _text(pdf, x, y - 1.2, label, size=6.4, style="B", color=_SLATE)
    pdf.set_draw_color(*_GRID)
    pdf.set_line_width(0.4)
    pdf.line(plot_x, y + 1.2, plot_x + plot_w, y + 1.2)

    # Draw left-to-right and stagger onto a second label line whenever the
    # previous ticker would collide — clustered peers otherwise overprint into
    # unreadable strings like "QCOMTC".
    placed: list[tuple[float, float, int]] = []
    for ticker, value in sorted(
        [(t, v) for t, v in peers if v is not None], key=lambda p: p[1]
    ):
        cx = px(value)
        pdf.set_fill_color(*_MUTED)
        pdf.circle(cx - 1.15, y + 0.05, 1.15, style="F")
        pdf.set_font("Memo", "", 4.9)
        half = max(4.0, pdf.get_string_width(ticker) / 2 + 0.6)
        row = 0
        while row < 2 and any(
            r == row and abs(cx - ox) < half + oh for ox, oh, r in placed
        ):
            row += 1
        placed.append((cx, half, row))
        _text(pdf, cx - 5, y + 3.0 + row * 2.6, ticker, size=4.9, color=_MUTED,
              width=10, align="C")

    if median is not None:
        pdf.set_draw_color(*_SLATE)
        pdf.set_line_width(0.45)
        pdf.line(px(median), y - 1.6, px(median), y + 4.0)
        _text(pdf, px(median) - 5, y - 4.4, "median", size=4.9, color=_SLATE, width=10, align="C")

    if subject is not None:
        pdf.set_fill_color(*_WHITE)
        pdf.circle(px(subject) - 2.2, y - 0.95, 2.2, style="F")
        pdf.set_fill_color(*_S1)
        pdf.circle(px(subject) - 1.6, y - 0.35, 1.6, style="F")

    _text(pdf, plot_x + plot_w + 3, y - 0.9, fmt(subject), size=6.8, style="B", color=_NAVY)


def _stat_line(pdf: HawktradePDF, x: float, y: float, w: float, label: str, value: str) -> None:
    _text(pdf, x, y, label, size=6.4, color=_SLATE)
    _text(pdf, x + w, y, value, size=6.6, style="B", color=_INK, align="R")
    pdf.set_draw_color(*_GRID)
    pdf.set_line_width(0.15)
    pdf.line(x, y + 4.0, x + w, y + 4.0)


# ─────────────────────────────────────────────────────────────────────────────
# Markdown rendering (long-form pages)
# ─────────────────────────────────────────────────────────────────────────────


def _plain_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text or "")
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_`~]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _split_table_row(line: str) -> list[str]:
    return [part.strip() for part in line.strip().strip("|").split("|")]


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.count("|") >= 2


def _safe_markdown(text: str) -> str:
    """Keep fpdf2's supported bold/italic subset and neutralize stray markers."""
    return re.sub(r"`([^`]*)`", r"\1", text or "")


def _write_body(pdf: HawktradePDF, text: str, *, indent: float = 0, width: Optional[float] = None) -> None:
    pdf.set_x(pdf.l_margin + indent)
    pdf.set_font("Memo", "", 9.6)
    pdf.set_text_color(*_INK)
    w = width if width is not None else pdf.w - pdf.r_margin - pdf.get_x()
    pdf.multi_cell(
        w,
        5.1,
        _safe_markdown(text),
        align="J",
        markdown=True,
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.ln(1.7)


def _write_subheading(pdf: HawktradePDF, text: str, level: int) -> None:
    size = 11.5 if level <= 2 else 9.5
    gap = 5 if level <= 2 else 3
    pdf.ln(gap)
    pdf.set_font("Memo", "B", size)
    pdf.set_text_color(*(_NAVY if level <= 2 else _SLATE))
    pdf.multi_cell(
        0,
        5.5,
        _plain_markdown(text).upper() if level <= 2 else _plain_markdown(text),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    if level <= 2:
        pdf.set_draw_color(*_LINE)
        pdf.set_line_width(0.2)
        pdf.line(pdf.l_margin, pdf.get_y() + 1, pdf.w - pdf.r_margin, pdf.get_y() + 1)
        pdf.ln(3)


def _table_row_height(pdf: HawktradePDF, cells: Sequence[str], widths: Sequence[float]) -> float:
    line_counts = []
    for cell, width in zip(cells, widths):
        lines = pdf.multi_cell(
            width - 4,
            4.2,
            _plain_markdown(cell),
            dry_run=True,
            output=MethodReturnValue.LINES,
        )
        line_counts.append(max(1, len(lines)))
    return max(7.5, max(line_counts, default=1) * 4.2 + 3)


def _draw_table_row(
    pdf: HawktradePDF,
    cells: Sequence[str],
    widths: Sequence[float],
    *,
    header: bool,
    origin: Optional[float] = None,
    size: float = 8,
    aligns: Optional[Sequence[str]] = None,
) -> None:
    """One row in the institutional table style: **horizontal rules only**.

    No vertical gridlines and no per-cell boxes — the header row carries a
    shaded fill, the block carries a rule above and below, and body rows are
    separated by a hairline. This is the convention every sell-side research
    table follows, and it is why cells are filled/ruled here rather than drawn
    as individual rects.
    """
    pdf.set_font("Memo", "B" if header else "", size)
    height = _table_row_height(pdf, cells, widths)
    if pdf.get_y() + height > pdf.h - pdf.b_margin:
        pdf.add_page()
    x0 = origin if origin is not None else pdf.l_margin
    y0 = pdf.get_y()
    total = sum(widths)

    if header:
        pdf.set_fill_color(*_PALE)
        pdf.rect(x0, y0, total, height, style="F")
        pdf.set_draw_color(*_NAVY)
        pdf.set_line_width(0.45)
        pdf.line(x0, y0, x0 + total, y0)
        pdf.line(x0, y0 + height, x0 + total, y0 + height)
        pdf.set_text_color(*_NAVY)
    else:
        pdf.set_draw_color(*_LINE)
        pdf.set_line_width(0.15)
        pdf.line(x0, y0 + height, x0 + total, y0 + height)
        pdf.set_text_color(*_INK)

    x = x0
    for idx, (cell, width) in enumerate(zip(cells, widths)):
        align = (aligns[idx] if aligns and idx < len(aligns) else ("L" if idx == 0 else "R"))
        pdf.set_xy(x + 2, y0 + 1.5)
        pdf.multi_cell(
            width - 4,
            4.2,
            _plain_markdown(cell),
            align=align,
            new_x=XPos.RIGHT,
            new_y=YPos.TOP,
        )
        x += width
    pdf.set_xy(x0, y0 + height)


def _write_table(
    pdf: HawktradePDF,
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    origin: Optional[float] = None,
    total_width: Optional[float] = None,
    size: float = 8,
    first_col_ratio: float = 1.6,
    aligns: Optional[Sequence[str]] = None,
) -> None:
    if not header:
        return
    total = total_width if total_width is not None else pdf.usable_width
    n = len(header)
    # Label column is wider than the figure columns; figures share the rest.
    unit = total / (first_col_ratio + (n - 1)) if n > 1 else total
    widths = [unit * first_col_ratio] + [unit] * (n - 1) if n > 1 else [total]
    _draw_table_row(pdf, header, widths, header=True, origin=origin, size=size, aligns=aligns)
    for row in rows:
        padded = list(row[: n]) + [""] * max(0, n - len(row))
        _draw_table_row(pdf, padded, widths, header=False, origin=origin, size=size, aligns=aligns)
    # Closing rule under the block.
    x0 = origin if origin is not None else pdf.l_margin
    pdf.set_draw_color(*_NAVY)
    pdf.set_line_width(0.45)
    pdf.line(x0, pdf.get_y(), x0 + total, pdf.get_y())
    pdf.ln(4)


def _render_markdown(pdf: HawktradePDF, markdown: str) -> None:
    lines = (markdown or "").replace("\r\n", "\n").split("\n")
    i = 0
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            _write_body(pdf, " ".join(part.strip() for part in paragraph))
            paragraph.clear()

    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            flush()
            i += 1
            continue
        heading = _HEADING_RE.match(stripped)
        if heading:
            flush()
            _write_subheading(pdf, heading.group(2), len(heading.group(1)))
            i += 1
            continue
        if _is_table_row(stripped) and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1].strip()):
            flush()
            header = _split_table_row(stripped)
            rows: list[list[str]] = []
            i += 2
            while i < len(lines) and _is_table_row(lines[i]):
                rows.append(_split_table_row(lines[i]))
                i += 1
            _write_table(pdf, header, rows)
            continue
        listed = _LIST_RE.match(lines[i])
        if listed:
            flush()
            marker = "•" if not listed.group(2)[0].isdigit() else listed.group(2)
            _write_body(pdf, f"{marker}  {listed.group(3)}", indent=4)
            i += 1
            continue
        if _RULE_RE.match(stripped):
            flush()
            pdf.set_draw_color(*_LINE)
            pdf.set_line_width(0.2)
            pdf.line(pdf.l_margin, pdf.get_y() + 2, pdf.w - pdf.r_margin, pdf.get_y() + 2)
            pdf.ln(5)
            i += 1
            continue
        paragraph.append(stripped)
        i += 1
    flush()


def _column_markdown(
    pdf: HawktradePDF,
    x: float,
    y: float,
    w: float,
    paragraphs: Sequence[str],
    *,
    max_y: float,
    size: float = 7.6,
    leading: float = 3.6,
) -> list[str]:
    """Flow paragraphs into a fixed column. Returns what did not fit.

    Auto page-break is disabled for the duration because the caller is placing
    an absolute two-column layout; without the hard stop fpdf2 would spill the
    overflow across the panel border and straight over the page footer.
    """
    pdf.set_auto_page_break(auto=False)
    cy = y
    remaining: list[str] = []
    for idx, para in enumerate(paragraphs):
        bullet = _LIST_RE.match(para)
        body = f"•  {bullet.group(3)}" if bullet else para
        heading = _HEADING_RE.match(para)
        if heading:
            body = _plain_markdown(heading.group(2))
            pdf.set_font("Memo", "B", size + 0.4)
            pdf.set_text_color(*_NAVY)
        else:
            pdf.set_font("Memo", "", size)
            pdf.set_text_color(*_INK)
        lines = pdf.multi_cell(w, leading, _safe_markdown(body), dry_run=True,
                               output=MethodReturnValue.LINES, markdown=True)
        if cy + len(lines) * leading > max_y:
            # Hand the rest back whole and stop — carrying on would re-add this
            # paragraph to the overflow list and print it twice.
            remaining = list(paragraphs[idx:])
            break
        pdf.set_xy(x, cy)
        pdf.multi_cell(w, leading, _safe_markdown(body), align="J", markdown=True,
                       new_x=XPos.LEFT, new_y=YPos.NEXT)
        cy = pdf.get_y() + 1.6
    pdf.set_auto_page_break(auto=True, margin=18)
    return remaining


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split("\n") if p.strip()]


# Roughly how many body characters fit on one analysis page at 8.6pt across the
# usable width. Used only to divide the budget between sections, so an
# approximation is fine — the renderer still hard-stops on real geometry.
_CHARS_PER_PAGE = 3800


def _condense(text: str, budget: int) -> tuple[list[str], bool]:
    """Leading whole paragraphs up to a character budget.

    Cuts on paragraph boundaries rather than mid-sentence: a research section
    that stops cleanly reads as edited, one that stops mid-clause reads broken.
    """
    kept: list[str] = []
    used = 0
    paragraphs = _paragraphs(text)
    for para in paragraphs:
        if used and used + len(para) > budget:
            return kept, True
        kept.append(para)
        used += len(para)
    return kept, False


# ─────────────────────────────────────────────────────────────────────────────
# Page builders
# ─────────────────────────────────────────────────────────────────────────────


def _display_date(payload: dict[str, Any]) -> str:
    raw = str(payload.get("generated_at_utc") or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%B %d, %Y")
    except ValueError:
        return raw[:10] or "Undated"


def _page_title(pdf: HawktradePDF, number: int, kicker: str, title: str) -> float:
    pdf.add_page()
    _text(pdf, pdf.l_margin, pdf.get_y(), f"{number:02d}  /  {kicker}", size=7,
          style="B", color=_ACCENT)
    pdf.set_y(pdf.get_y() + 6)
    _text(pdf, pdf.l_margin, pdf.get_y(), title, size=19, style="B", color=_NAVY)
    y = pdf.get_y() + 9
    pdf.set_draw_color(*_ACCENT)
    pdf.set_line_width(0.8)
    pdf.line(pdf.l_margin, y, pdf.l_margin + 26, y)
    return y + 6


def _upside(dcf: dict[str, Any], price: Optional[float]) -> Optional[float]:
    up = _num(dcf.get("implied_upside_vs_price"))
    if up is not None:
        return up
    fv = _num(dcf.get("fair_value_per_share"))
    if fv is not None and price:
        return fv / price - 1.0
    return None


_BULLET_LINE_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$")


def summary_bullets(payload: dict[str, Any], *, limit: int = 5) -> list[tuple[str, str]]:
    """Up to `limit` (lead-in, body) pairs for the cover.

    Prefers the memo's own bullets from the recommendation section — synthesis
    writes them as "- **Growth:** ..." — because those are the analyst's chosen
    headline points. Falls back to leading sentences when the memo is prose.
    """
    sections = payload.get("sections") or {}
    ordered = [
        sections.get("recommendation"),
        sections.get("key_debate_points"),
        sections.get("business_overview"),
    ]
    out: list[tuple[str, str]] = []
    for block in ordered:
        if not block or len(out) >= limit:
            continue
        for raw in str(block).split("\n"):
            m = _BULLET_LINE_RE.match(raw)
            if not m:
                continue
            text = sanitize_prose(m.group(1)).strip()
            lead = ""
            bold = re.match(r"^\*\*(.+?)\*\*:?\s*(.*)$", text)
            if bold:
                lead, text = bold.group(1).strip().rstrip(":"), bold.group(2).strip()
            text = _plain_markdown(text)
            if len(text) < 25:
                continue
            out.append((lead, text))
            if len(out) >= limit:
                break
    if not out:
        body = sanitize_prose(str(sections.get("recommendation") or payload.get("preamble") or ""))
        for sentence in re.split(r"(?<=\.)\s+", _plain_markdown(body)):
            if len(sentence) > 45:
                out.append(("", sentence.strip()))
            if len(out) >= limit:
                break
    return out[:limit]


def _render_cover(pdf: HawktradePDF, payload: dict[str, Any], book: MetricBook) -> None:
    """Page 1 — identification, the KPI table, and the five headline points."""
    ticker = str(payload.get("ticker") or "SECTOR").upper()
    sector = str(payload.get("sector") or "Equity Research")
    rating = str(payload.get("rating") or "NOT RATED")
    target = str(payload.get("price_target") or "—")
    valuation = payload.get("valuation") if isinstance(payload.get("valuation"), dict) else {}
    dcf = valuation.get("dcf") if isinstance(valuation.get("dcf"), dict) else {}
    price = book.value("price") or _num((dcf.get("inputs") or {}).get("price"))

    pdf.add_page()
    y = 26
    _text(pdf, pdf.l_margin, y, ticker, size=30, style="B", color=_NAVY)
    _text(pdf, pdf.l_margin, y + 15, sector, size=12, color=_SLATE)
    _text(pdf, pdf.w - pdf.r_margin, y + 2, "INVESTMENT MEMORANDUM", size=7.5,
          style="B", color=_SLATE, align="R")
    y += 26
    pdf.set_draw_color(*_NAVY)
    pdf.set_line_width(0.45)
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    y += 7

    # ── KPI table (shaded header, horizontal rules only) ─────────────────────
    up = _upside(dcf, price) if dcf else None
    pdf.set_y(y)
    _write_table(
        pdf,
        ["Metric", "Value", "Basis"],
        [
            ["Rating", rating.split("—")[0].split("(")[0].strip() or "NOT RATED",
             "Desk view"],
            ["Last price", _price(price), _short_period(book.period("price")) or "Live"],
            ["Price target", target, "Engine fair value" if dcf else "Memo"],
            ["Implied upside", _pct(up, digits=1) if up is not None else "—", "vs. last price"],
            ["Market cap", _money(book.value("market_cap"), digits=2), "Live"],
            ["Trailing P/E", _mult(book.value("trailing_pe")), "Canonical"],
        ],
        size=8.6,
        first_col_ratio=1.5,
        aligns=["L", "R", "R"],
    )

    # ── Five headline points ─────────────────────────────────────────────────
    bullets = summary_bullets(payload)
    if bullets:
        y = pdf.get_y() + 4
        _text(pdf, pdf.l_margin, y, "INVESTMENT SUMMARY", size=7.5, style="B", color=_NAVY)
        y += 6
        for lead, body in bullets:
            pdf.set_fill_color(*_NAVY)
            pdf.rect(pdf.l_margin, y + 1.2, 1.6, 1.6, style="F")
            pdf.set_xy(pdf.l_margin + 5, y - 0.6)
            pdf.set_text_color(*_INK)
            text = f"**{lead}.** {body}" if lead else body
            pdf.set_font("Memo", "", 8.8)
            pdf.multi_cell(pdf.usable_width - 5, 4.5, _safe_markdown(text)[:520],
                           align="J", markdown=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            y = pdf.get_y() + 2.6

    # ── Standing note ────────────────────────────────────────────────────────
    pdf.set_y(max(pdf.get_y() + 8, pdf.h - pdf.b_margin - 26))
    pdf.set_draw_color(*_ACCENT)
    pdf.set_line_width(1.1)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + 32, pdf.get_y())
    pdf.ln(4)
    pdf.set_font("Memo", "", 7.4)
    pdf.set_text_color(*_SLATE)
    pdf.multi_cell(
        0,
        4.0,
        "Thesis content only. Data-quality disclosures, stale-tag warnings, QC findings "
        "and run cost are published separately in the compliance audit log. Valuation "
        "figures are deterministic engine output, not model estimates from training data.",
    )


def _render_financials(pdf: HawktradePDF, payload: dict[str, Any], book: MetricBook, number: int) -> None:
    """Page 2 — financial summary tables, then two fixed-ratio exhibits."""
    y = _page_title(pdf, number, "FINANCIAL SUMMARY", "Operating & Financial Profile")
    usable = pdf.usable_width
    cur = _short_period(book.period("revenue__current_annual")) or "Current"
    prior = _short_period(book.period("revenue__prior_annual")) or "Prior"

    def yoy(now: Optional[float], before: Optional[float], pct: bool = False) -> str:
        if now is None or before is None:
            return "—"
        if pct:
            return f"{(now - before) * 10000:+,.0f} bps"
        return f"{(now / before - 1) * 100:+,.1f}%" if before else "—"

    pdf.set_y(y)
    _text(pdf, pdf.l_margin, y, "INCOME STATEMENT & MARGINS", size=7, style="B", color=_NAVY)
    pdf.set_y(y + 5)
    rev_c, rev_p = book.value("revenue__current_annual"), book.value("revenue__prior_annual")
    rows = [
        ["Revenue", _money(rev_c), _money(rev_p), yoy(rev_c, rev_p)],
        ["Gross profit", _money(book.value("gross_profit__current_annual")),
         _money(book.value("gross_profit__prior_annual")),
         yoy(book.value("gross_profit__current_annual"), book.value("gross_profit__prior_annual"))],
        ["Operating income", _money(book.value("operating_income__current_annual")),
         _money(book.value("operating_income__prior_annual")),
         yoy(book.value("operating_income__current_annual"), book.value("operating_income__prior_annual"))],
        ["Net income", _money(book.value("net_income__current_annual")),
         _money(book.value("net_income__prior_annual")),
         yoy(book.value("net_income__current_annual"), book.value("net_income__prior_annual"))],
        ["Free cash flow", _money(book.value("fcf__current_annual")),
         _money(book.value("fcf__prior_annual")),
         yoy(book.value("fcf__current_annual"), book.value("fcf__prior_annual"))],
        ["Diluted EPS", _price(book.value("eps_diluted__current_annual")),
         _price(book.value("eps_diluted__prior_annual")),
         yoy(book.value("eps_diluted__current_annual"), book.value("eps_diluted__prior_annual"))],
        ["Gross margin", _pct(book.value("gross_margin__current_annual")),
         _pct(book.value("gross_margin__prior_annual")),
         yoy(book.value("gross_margin__current_annual"), book.value("gross_margin__prior_annual"), True)],
        ["Operating margin", _pct(book.value("operating_margin__current_annual")),
         _pct(book.value("operating_margin__prior_annual")),
         yoy(book.value("operating_margin__current_annual"), book.value("operating_margin__prior_annual"), True)],
        ["Net margin", _pct(book.value("net_margin__current_annual")),
         _pct(book.value("net_margin__prior_annual")),
         yoy(book.value("net_margin__current_annual"), book.value("net_margin__prior_annual"), True)],
    ]
    _write_table(pdf, ["", cur, prior, "Change"], rows, size=7.8, first_col_ratio=1.8)

    y = pdf.get_y() + 2
    _text(pdf, pdf.l_margin, y, "BALANCE SHEET, RETURNS & VALUATION", size=7, style="B", color=_NAVY)
    pdf.set_y(y + 5)
    _write_table(
        pdf,
        ["", "Value", "", "Value"],
        [
            ["Net cash (ex ST inv.)",
             _money(book.value("net_cash_ex_st_investments__current_quarter",
                               "net_cash_ex_st_investments__current_annual")),
             "Diluted shares", _count(book.value("shares_diluted__current_annual"))],
            ["Total debt", _money(book.value("total_debt__current_quarter", "total_debt__current_annual")),
             "Share count change",
             _pct(book.value("share_count_change_pct__current_annual_vs_prior_annual"))],
            ["Debt / equity", _mult(book.value("debt_to_equity__current_quarter",
                                               "debt_to_equity__current_annual"), digits=2),
             "Price / sales", _mult(book.value("price_to_sales"))],
            ["Current ratio", _mult(book.value("current_ratio__current_annual"), digits=2),
             "Price / book", _mult(book.value("price_to_book"))],
            ["Inventory", _money(book.value("inventory__current_quarter", "inventory__current_annual")),
             "Book value / share", _price(book.value("book_value_per_share"))],
            ["Inventory YoY", _pct(book.value("inventory_yoy")),
             "Enterprise value",
             _money(book.value("enterprise_value_ex_st", "enterprise_value_incl_st"))],
        ],
        size=7.8,
        first_col_ratio=1.7,
        aligns=["L", "R", "L", "R"],
    )

    # ── Two half-width exhibits at a fixed aspect ratio ──────────────────────
    y = pdf.get_y() + 2
    half = (usable - 6) / 2
    height = min(pdf.exhibit_box(y, half, _ASPECT_HALF), pdf.h - pdf.b_margin - y - 10)
    if height > 26:
        px_, py, pw, ph = _panel(pdf, pdf.l_margin, y, half, height, "Margin structure",
                                 subtitle=f"{cur} vs {prior}")
        _legend(pdf, px_, py, [(cur, _S1), (prior, _S2)])
        mrows = []
        for label, base in (("Gross", "gross_margin"), ("Operating", "operating_margin"),
                            ("Net", "net_margin"), ("Free cash flow", "fcf_margin")):
            c, p = book.value(f"{base}__current_annual"), book.value(f"{base}__prior_annual")
            mrows.append((label, [c, p], [_pct(c), _pct(p)]))
        _grouped_hbars(pdf, px_, py + 6, pw, ph - 6, mrows, colors=[_S1, _S2], label_w=26)

        qx, qy, qw, qh = _panel(pdf, pdf.l_margin + half + 6, y, half, height,
                                "Growth & intensity", subtitle="annual basis")
        _hbars(pdf, qx, qy, qw, qh, [
            ("Revenue YoY", book.value("revenue_yoy"), _pct(book.value("revenue_yoy"))),
            ("Net income YoY", book.value("net_income_yoy"), _pct(book.value("net_income_yoy"))),
            ("Op income YoY", book.value("operating_income_yoy"), _pct(book.value("operating_income_yoy"))),
            ("R&D / revenue", book.value("rd_pct_revenue__current_annual"),
             _pct(book.value("rd_pct_revenue__current_annual"))),
            ("Capex / revenue", book.value("capex_pct_revenue__current_annual"),
             _pct(book.value("capex_pct_revenue__current_annual"))),
        ], ramp=True, label_w=28)
        y += height + 3

    _caption(pdf, pdf.l_margin, min(y, pdf.h - pdf.b_margin - 8), usable,
             f"{book.count} canonical metric records underpin this report. Figures whose SEC "
             "XBRL tag lags the reporting period are excluded upstream, so nothing shown "
             "carries a staleness caveat.")


def _render_valuation(
    pdf: HawktradePDF,
    payload: dict[str, Any],
    book: MetricBook,
    valuation: dict[str, Any],
    number: int,
) -> None:
    dcf = valuation.get("dcf") if isinstance(valuation.get("dcf"), dict) else {}
    comps = valuation.get("comps") if isinstance(valuation.get("comps"), dict) else {}
    if not dcf and not comps:
        return
    y = _page_title(pdf, number, "VALUATION", "What It Is Worth")
    usable = pdf.usable_width
    inputs = dcf.get("inputs") if isinstance(dcf.get("inputs"), dict) else {}
    assumptions = dcf.get("assumptions") if isinstance(dcf.get("assumptions"), dict) else {}
    price = book.value("price") or _num(inputs.get("price"))

    rows: list[dict[str, Any]] = []
    rng = dcf.get("fair_value_range") if isinstance(dcf.get("fair_value_range"), dict) else {}
    fv = _num(dcf.get("fair_value_per_share"))
    if rng.get("low") is not None and rng.get("high") is not None:
        rows.append({"label": "Multi-stage DCF", "sub": "FCF, sector WACC",
                     "low": _num(rng.get("low")), "base": _num(rng.get("base")) or fv,
                     "high": _num(rng.get("high")), "color": _S1})
    elif fv is not None:
        rows.append({"label": "Multi-stage DCF", "sub": "FCF, sector WACC", "base": fv, "color": _S1})
    epv = _num(dcf.get("epv_per_share"))
    if epv is not None:
        rows.append({"label": "EPV cross-check", "sub": "no growth", "base": epv, "color": _S3})

    # Comps-implied dollars per share, so the football field keeps one axis.
    #
    # Earnings-based only, deliberately. A peer P/S multiple applied to the
    # subject's revenue prices that revenue at *peer* profitability, so when
    # the subject's margins diverge from the peer median the resulting number
    # measures the margin gap rather than the valuation gap. On NVDA it landed
    # at $71/share against a $271-$367 DCF — a units artefact, not a finding,
    # and exactly the kind of chart no analyst would sign.
    medians = comps.get("peer_medians") if isinstance(comps.get("peer_medians"), dict) else {}
    eps = book.value("eps_diluted__current_annual") or _num(inputs.get("eps_diluted_current"))
    med_pe = _num(medians.get("trailing_pe"))
    if eps and med_pe:
        rows.append({
            "label": "Peer-implied", "sub": "median trailing P/E",
            "base": eps * med_pe, "color": _S2,
        })

    if rows:
        px_, py, pw, ph = _panel(pdf, pdf.l_margin, y, usable, 74, "Valuation range",
                                 subtitle="dollars per share, one axis across methods")
        _football_field(pdf, px_, py + 5, pw, ph - 5, rows, price=price)
        y += 79

    half = (usable - 6) / 2
    ax, ay, aw, _ah = _panel(pdf, pdf.l_margin, y, half, 50, "DCF assumptions",
                             subtitle=str(dcf.get("method") or ""))
    a_stats = [
        ("WACC", _pct(assumptions.get("wacc"))),
        ("High-growth rate", _pct(assumptions.get("g_high"))),
        ("Terminal growth", _pct(assumptions.get("g_terminal"))),
        ("Base FCF", _money(inputs.get("base_fcf_annual"))),
        ("FCF YoY (actual)", _pct(inputs.get("fcf_yoy_growth"))),
        ("Net debt", _money(inputs.get("net_debt"))),
    ]
    for i, (label, value) in enumerate(a_stats):
        _stat_line(pdf, ax, ay + i * 6.6, aw, label, value)

    bx, by, bw, _bh = _panel(pdf, pdf.l_margin + half + 6, y, half, 50, "Engine output")
    up = _upside(dcf, price)
    b_stats = [
        ("Fair value / share", _price(fv)),
        ("Implied upside", _pct(up) if up is not None else "n/a"),
        ("EPV / share", _price(epv)),
        ("Enterprise value", _money(dcf.get("enterprise_value"))),
        ("Equity value", _money(dcf.get("equity_value"))),
        ("Terminal value (PV)", _money(dcf.get("terminal_value_pv"))),
    ]
    for i, (label, value) in enumerate(b_stats):
        _stat_line(pdf, bx, by + i * 6.6, bw, label, value)
    y += 55

    projections = dcf.get("projections") if isinstance(dcf.get("projections"), list) else []
    if projections:
        height = pdf.h - pdf.b_margin - y - 4
        px_, py, pw, ph = _panel(pdf, pdf.l_margin, y, usable, height,
                                 "Projected free cash flow",
                                 subtitle="explicit forecast horizon — engine extrapolation, not guidance")
        rows2 = []
        for p in projections[:10]:
            if not isinstance(p, dict):
                continue
            year = p.get("year") or p.get("t") or len(rows2) + 1
            val = _num(p.get("fcf")) or _num(p.get("free_cash_flow"))
            rows2.append((f"Year {year}", val, _money(val)))
        if rows2:
            _hbars(pdf, px_, py, pw, ph - 6, rows2, ramp=True, label_w=20)
            _caption(pdf, px_, py + ph - 5, pw,
                     "Growth is capped and faded to terminal by the engine; later years are "
                     "the arithmetic consequence of the assumptions above, not a forecast.")


def _render_peers(
    pdf: HawktradePDF,
    payload: dict[str, Any],
    book: MetricBook,
    valuation: dict[str, Any],
    number: int,
) -> None:
    comps = valuation.get("comps") if isinstance(valuation.get("comps"), dict) else {}
    peers = [p for p in (comps.get("peers") or []) if isinstance(p, dict)]
    if not peers:
        return
    subject = comps.get("subject") if isinstance(comps.get("subject"), dict) else {}
    medians = comps.get("peer_medians") if isinstance(comps.get("peer_medians"), dict) else {}
    ticker = str(payload.get("ticker") or "SUBJECT").upper()

    y = _page_title(pdf, number, "RELATIVE VALUE", "Against the Peer Set")
    usable = pdf.usable_width

    read = str(comps.get("overall_vs_peers") or "").replace("_", " ")
    if read:
        _text(pdf, pdf.l_margin, y, f"Overall read vs peers: {read.upper()}", size=8,
              style="B", color=_NAVY)
        y += 6

    specs = [
        ("Trailing P/E", "trailing_pe", _mult),
        ("Forward P/E", "forward_pe", _mult),
        ("EV / EBITDA", "ev_to_ebitda", _mult),
        ("Price / sales", "price_to_sales", _mult),
        ("Operating margin", "operating_margins", _pct),
    ]
    px_, py, pw, _ph = _panel(pdf, pdf.l_margin, y, usable, 20 + len(specs) * 14,
                              f"{ticker} vs peers",
                              subtitle="subject highlighted; grey dots are peers, labelled by ticker")
    _legend(pdf, px_, py, [(ticker, _S1), ("Peer", _MUTED)])
    row_y = py + 9
    for label, key, fmt in specs:
        _dot_row(
            pdf, px_, row_y, pw, label,
            _num(subject.get(key)),
            [(str(p.get("ticker") or "?"), _num(p.get(key))) for p in peers],
            _num(medians.get(key)),
            fmt=fmt,
        )
        row_y += 14
    y += 24 + len(specs) * 14

    pdf.set_y(y)
    _text(pdf, pdf.l_margin, y, "PEER DETAIL", size=6.6, style="B", color=_NAVY)
    pdf.set_y(y + 5)
    header = ["Ticker", "Price", "Mkt cap", "Trail P/E", "Fwd P/E", "EV/EBITDA", "P/S"]
    body = []
    for row in [subject] + peers if subject else peers:
        body.append([
            str(row.get("ticker") or "—"),
            _price(row.get("price")),
            _money(row.get("market_cap"), digits=2),
            _mult(row.get("trailing_pe")),
            _mult(row.get("forward_pe")),
            _mult(row.get("ev_to_ebitda")),
            _mult(row.get("price_to_sales")),
        ])
    if medians:
        body.append([
            "Peer median", "—", "—",
            _mult(medians.get("trailing_pe")), _mult(medians.get("forward_pe")),
            _mult(medians.get("ev_to_ebitda")), _mult(medians.get("price_to_sales")),
        ])
    _write_table(pdf, header, body, size=7)


def _render_capital_and_flow(
    pdf: HawktradePDF,
    payload: dict[str, Any],
    book: MetricBook,
    number: int,
) -> bool:
    """Uses of cash and free-source market structure. False if nothing to draw."""
    buyback = book.value("buyback_spend__current_annual")
    capex = book.value("capex__current_annual")
    dividends = book.value("dividends_paid__current_annual")
    put_call = book.value("options_put_call_volume_ratio__live")
    insider = book.value("insider_net_shares_heuristic__live")
    form4 = book.value("insider_form4_recent_count__live")
    if not any(v is not None for v in (buyback, capex, dividends, put_call, insider, form4)):
        return False

    y = _page_title(pdf, number, "CAPITAL & FLOW", "Cash Deployment and Market Structure")
    usable = pdf.usable_width
    half = (usable - 6) / 2
    ocf = book.value("ocf__current_annual")
    fcf = book.value("fcf__current_annual", "free_cash_flow__current_annual")

    px_, py, pw, ph = _panel(pdf, pdf.l_margin, y, half, 76, "Uses of cash",
                             subtitle=_short_period(book.period("capex__current_annual")))
    rows = [
        ("Operating cash flow", ocf, _money(ocf)),
        ("Free cash flow", fcf, _money(fcf)),
        ("Buybacks", buyback, _money(buyback)),
        ("Capital expenditure", capex, _money(capex)),
        ("Dividends", dividends, _money(dividends)),
    ]
    rows = [r for r in rows if r[1] is not None]
    _hbars(pdf, px_, py, pw, ph, rows, ramp=True, label_w=30)

    qx, qy, qw, _qh = _panel(pdf, pdf.l_margin + half + 6, y, half, 76, "Shareholder returns")
    eff = book.value("buyback_dollars_per_pct_point__current_annual_vs_prior_annual")
    stats = [
        ("Buyback efficiency", (_money(eff) + " / pp") if eff is not None else "n/a"),
        ("Share count change", _pct(book.value("share_count_change_pct__current_annual_vs_prior_annual"))),
        ("Buybacks / FCF", _pct((buyback / fcf) if buyback and fcf else None)),
        ("Capex / OCF", _pct((capex / ocf) if capex and ocf else None)),
        ("Buyback spend", _money(buyback)),
        ("Dividends paid", _money(dividends)),
        ("Prior-year buybacks", _money(book.value("buyback_spend__prior_annual"))),
        ("Prior-year capex", _money(book.value("capex__prior_annual"))),
    ]
    for i, (label, value) in enumerate(stats):
        _stat_line(pdf, qx, qy + i * 7.0, qw, label, value)
    _caption(pdf, qx, qy + len(stats) * 7.0 + 1.5, qw,
             "Buyback efficiency is dollars spent per percentage point of diluted "
             "share-count reduction — a single annual pair, not a trend.")
    y += 82

    mx, my, mw, mh = _panel(pdf, pdf.l_margin, y, usable, 46, "Market structure",
                            subtitle="free sources only — yfinance chains and SEC Form 4 counts")
    gauge_w = mw * 0.52
    if put_call is not None:
        _diverging_gauge(
            pdf, mx, my + 8, gauge_w, put_call,
            midpoint=1.0, lo=0.0, hi=2.0,
            low_label="0.0x  call-skewed", high_label="put-skewed  2.0x",
            readout=f"Put / call volume ratio  {_mult(put_call, digits=2)}",
        )
        _caption(pdf, mx, my + 20, gauge_w,
                 "Below 1.0x the chain is call-weighted. A free volume proxy, not an "
                 "order-flow tape — mega-cap chains skew structurally, so this is "
                 "context rather than a signal.")

    ix = mx + mw * 0.60
    iw = mw - (ix - mx)
    _text(pdf, ix, my, "INSIDER ACTIVITY", size=6.2, style="B", color=_NAVY)
    if insider is not None:
        direction = "NET SELLING" if insider < 0 else ("NET BUYING" if insider > 0 else "FLAT")
        status = _CRIT if insider < 0 else (_GOOD if insider > 0 else _MUTED)
        # Status colour never carries meaning alone — it ships with the label.
        pdf.set_fill_color(*status)
        pdf.circle(ix, my + 5.4, 1.5, style="F")
        _text(pdf, ix + 5, my + 5.2, direction, size=7.4, style="B", color=_INK)
        _text(pdf, ix + 5, my + 9.6, f"{_count(abs(insider))} shares (heuristic)",
              size=6.2, color=_SLATE)
    if form4 is not None:
        _text(pdf, ix, my + 15, f"SEC Form 4 filings: {int(form4)}", size=6.4, color=_SLATE)
    _caption(pdf, ix, my + 20, iw,
             "Count-only by design for v1: no Form 4 dollar-value parse, so this is "
             "directional evidence, not a sized signal.")
    return True


_BULL_HINTS = ("bull", "long case", "upside case", "survives contact")
_BEAR_HINTS = ("bear", "short case", "downside case", "lands real blows")


def _pick_side(subs: Sequence[dict[str, Any]], hints: Sequence[str]) -> Optional[dict[str, Any]]:
    for sub in subs:
        title = str(sub.get("title") or "").lower()
        if any(h in title for h in hints):
            return sub
    return None


def _render_debate(
    pdf: HawktradePDF,
    payload: dict[str, Any],
    number: int,
    *,
    leftovers: Optional[list[tuple[str, str]]] = None,
) -> bool:
    """Facing bull/bear spread. Returns False when the split is not confident.

    The sub-heading wording is written by the model and drifts run to run, so a
    miss here falls back to rendering the section as ordinary prose rather than
    shipping a half-empty spread.
    """
    leftovers = leftovers if leftovers is not None else []
    sections = payload.get("sections") or {}
    body = sections.get("key_debate_points")
    subs = (payload.get("subsections") or {}).get("key_debate_points") or []
    if not body or not isinstance(subs, list) or len(subs) < 2:
        return False
    bull = _pick_side(subs, _BULL_HINTS)
    bear = _pick_side(subs, _BEAR_HINTS)
    if not bull or not bear or bull is bear:
        return False

    y = _page_title(pdf, number, "THE CENTRAL DEBATE", "Bull vs Bear")
    usable = pdf.usable_width
    col_w = (usable - 7) / 2

    sides = [
        {"color": _POS, "label": "BULL CASE", "title": str(bull.get("title") or ""),
         "left": _paragraphs(sanitize_prose(str(bull.get("text") or "")))},
        {"color": _NEG, "label": "BEAR CASE", "title": str(bear.get("title") or ""),
         "left": _paragraphs(sanitize_prose(str(bear.get("text") or "")))},
    ]

    spread = 0
    # Both cases must stay side by side to be comparable, so the spread
    # continues onto further pages until the longer column is exhausted.
    while any(s["left"] for s in sides) and spread < 6:
        if spread:
            y = _page_title(pdf, number, "THE CENTRAL DEBATE", "Bull vs Bear (cont.)")
        panel_h = pdf.h - pdf.b_margin - y - 6
        for idx, side in enumerate(sides):
            x = pdf.l_margin + idx * (col_w + 7)
            pdf.set_draw_color(*_GRID)
            pdf.set_line_width(0.2)
            pdf.rect(x, y, col_w, panel_h, style="D", round_corners=True, corner_radius=1.5)
            pdf.set_fill_color(*side["color"])
            pdf.rect(x, y, col_w, 7.5, style="F",
                     round_corners=("TOP_LEFT", "TOP_RIGHT"), corner_radius=1.5)
            _text(pdf, x + 3.5, y + 2.4, side["label"], size=6.8, style="B", color=_WHITE)
            body_top = y + 10.5
            if not spread:
                _text(pdf, x + 3.5, y + 10, _plain_markdown(side["title"])[:120],
                      size=7.2, style="B", color=_NAVY)
                body_top = y + 16.5
            if side["left"]:
                side["left"] = _column_markdown(
                    pdf, x + 3.5, body_top, col_w - 7, side["left"],
                    max_y=y + panel_h - 4,
                )
        spread += 1

    # Remaining subsections (typically the adjudication) are handed to the
    # thematic analysis stream rather than given a page of their own — a
    # two-paragraph coda does not earn a full page under the budget.
    leftovers.extend(
        (str(s.get("title") or "Adjudication"), str(s.get("text") or ""))
        for s in subs
        if s is not bull and s is not bear and str(s.get("text") or "").strip()
    )
    return True


def _render_analysis(
    pdf: HawktradePDF,
    payload: dict[str, Any],
    number: int,
    *,
    skip: Sequence[str] = (),
    extra: Sequence[tuple[str, str]] = (),
    max_pages: int = MAX_ANALYSIS_PAGES,
) -> int:
    """Thematic analysis: bolded lead-ins over short, sanitized paragraphs.

    Hard page cap. The prose is what previously ran the document to 19 pages,
    so the budget is enforced here and nowhere else; whatever does not fit is
    named on the page rather than silently dropped, and `--appendix` prints it
    in full.
    """
    items = list(extra) + [(t, b) for t, b in _iter_sections(payload, skip=skip)]
    if not items:
        return 0

    # Share the budget across every theme rather than printing the first two in
    # full and dropping the rest: a research report that covers all its themes
    # briefly is more useful than one missing "Catalysts & Risks" entirely.
    per_section = max(700, int(_CHARS_PER_PAGE * max_pages / max(1, len(items))))

    start_page = pdf.page_no()
    # Must use the y that _page_title returns — pdf.get_y() still points at the
    # title's own baseline, so reading it back overprints the first heading.
    pdf.set_y(_page_title(pdf, number, "THEMATIC ANALYSIS", "Analysis") + 4)
    condensed: list[str] = []

    for title, body in items:
        paragraphs, truncated = _condense(sanitize_prose(body), per_section)
        if not paragraphs:
            continue
        if truncated:
            condensed.append(title)
        need = 24
        if pdf.get_y() > pdf.h - pdf.b_margin - need:
            if pdf.page_no() - start_page + 1 >= max_pages:
                condensed.append(title)
                break
            pdf.add_page()
        pdf.ln(2)
        _text(pdf, pdf.l_margin, pdf.get_y(), title.upper(), size=9, style="B", color=_NAVY)
        pdf.set_y(pdf.get_y() + 5)
        pdf.set_draw_color(*_NAVY)
        pdf.set_line_width(0.3)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(2.6)

        for para in paragraphs:
            if _RULE_RE.match(para.strip()):
                continue  # markdown horizontal rule — never print the dashes
            heading = _HEADING_RE.match(para)
            if heading:
                pdf.ln(1.6)
                _text(pdf, pdf.l_margin, pdf.get_y(),
                      _plain_markdown(heading.group(2))[:110], size=8.2, style="B", color=_SLATE)
                pdf.set_y(pdf.get_y() + 5)
                continue
            bullet = _LIST_RE.match(para)
            text = f"•  {bullet.group(3)}" if bullet else para
            pdf.set_x(pdf.l_margin + (4 if bullet else 0))
            pdf.set_font("Memo", "", 8.6)
            pdf.set_text_color(*_INK)
            pdf.multi_cell(pdf.usable_width - (4 if bullet else 0), 4.4,
                           _safe_markdown(text), align="J", markdown=True,
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(1.4)

    if condensed:
        pdf.ln(2)
        _caption(pdf, pdf.l_margin, pdf.get_y(), pdf.usable_width,
                 "Condensed to the page budget: "
                 + "; ".join(dict.fromkeys(condensed))
                 + ". Re-run with --appendix for the unabridged text.")
    return pdf.page_no() - start_page + 1


def _iter_sections(payload: dict[str, Any], *, skip: Sequence[str] = ()) -> Iterable[tuple[str, str]]:
    sections = payload["sections"]
    order = [key for key in _DEFAULT_ORDER if sections.get(key) and key not in skip]
    for key in payload.get("sections_found") or []:
        if key not in order and sections.get(key) and key not in skip:
            order.append(key)
    for key in order:
        yield _SECTION_TITLES.get(key, key.replace("_", " ").title()), str(sections[key])
    for extra in payload.get("unmapped_sections") or []:
        if not isinstance(extra, dict):
            continue
        title = str(extra.get("title") or "Additional Analysis")
        text = str(extra.get("text") or "").strip()
        if text and not _EXCLUDED_TITLE_RE.search(title):
            yield title, text


# ─────────────────────────────────────────────────────────────────────────────
# Entry points
# ─────────────────────────────────────────────────────────────────────────────


def generate_pdf(
    clean_memo: Path | str | dict[str, Any],
    *,
    output_path: Optional[Path | str] = None,
    appendix: bool = False,
) -> Path:
    """Render a clean memo as an institutional equity research report.

    Fixed page plan, in order:
        1  Cover — identification, KPI table, five summary points
        2  Financial summary — tables plus two fixed-ratio exhibits
        3  Valuation — football field, assumptions, projections
        4  Peer comparison — dot plots and comps table
        5  Capital deployment and market structure
        6+ Thematic analysis, capped at ``MAX_ANALYSIS_PAGES``

    Every exhibit page self-skips when its inputs are absent, so a schema-1.0
    artifact (prose only) still renders as the written document it is.
    ``appendix=True`` appends the unabridged long-form behind the report.
    """
    payload = load_clean_memo(clean_memo) if not isinstance(clean_memo, dict) else clean_memo
    if payload.get("artifact") != "clean_memo" or not isinstance(payload.get("sections"), dict):
        raise CleanMemoError("payload must satisfy the clean_memo artifact contract")

    ticker = re.sub(r"[^\w.-]+", "_", str(payload.get("ticker") or "SECTOR").upper()) or "SECTOR"
    as_of = _display_date(payload)
    pdf = HawktradePDF(ticker=ticker, as_of=as_of)
    pdf.alias_nb_pages()   # resolves "Page n of {nb}" in the footer

    book = MetricBook(payload.get("metrics"))
    valuation = payload.get("valuation") if isinstance(payload.get("valuation"), dict) else {}

    _render_cover(pdf, payload, book)

    number = 1
    if book:
        _render_financials(pdf, payload, book, number)
        number += 1
    if valuation:
        before = pdf.page_no()
        _render_valuation(pdf, payload, book, valuation, number)
        if pdf.page_no() > before:
            number += 1
        before = pdf.page_no()
        _render_peers(pdf, payload, book, valuation, number)
        if pdf.page_no() > before:
            number += 1
    if book and _render_capital_and_flow(pdf, payload, book, number):
        number += 1

    skip: list[str] = []
    leftovers: list[tuple[str, str]] = []
    if _render_debate(pdf, payload, number, leftovers=leftovers):
        skip.append("key_debate_points")
        number += 1

    _render_analysis(pdf, payload, number, skip=skip, extra=leftovers)

    if appendix:
        number += 1
        pdf.set_y(_page_title(pdf, number, "APPENDIX", "Unabridged Analysis") + 4)
        for title, body in _iter_sections(payload):
            _write_subheading(pdf, title, 2)
            _render_markdown(pdf, sanitize_prose(body))

    if pdf.page_no() == 1:
        pdf.add_page()
        _write_body(pdf, "No thesis sections were available in this clean memo.")

    if output_path is None:
        raw_date = str(payload.get("generated_at_utc") or "")[:10]
        day = raw_date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date) else "undated"
        output_path = DEFAULT_OUTPUT_DIR / f"{ticker}_{day}_presentation.pdf"
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(destination))
    return destination.resolve()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a thesis-only clean_memo.json as a Hawktrade presentation PDF."
    )
    parser.add_argument("clean_memo", type=Path, help="Path to *_clean_memo.json")
    parser.add_argument("-o", "--output", type=Path, help="Destination PDF path")
    parser.add_argument(
        "--appendix",
        action="store_true",
        help="Append the unabridged long-form analysis behind the page-budgeted report.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    path = generate_pdf(args.clean_memo, output_path=args.output, appendix=args.appendix)
    print(f"Saved Hawktrade presentation: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
