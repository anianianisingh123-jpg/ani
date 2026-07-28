"""Render thesis-only ``clean_memo.json`` artifacts as presentation PDFs.

This module is intentionally downstream of :mod:`artifacts`: it consumes the
clean JSON contract and never reads or renders QC reports, validation output,
cost records, stale-tag findings, or compliance audit logs.

CLI:
    python -m mas_sector_system.pdf_generator outputs/NVDA_2026-07-28_clean_memo.json
"""

from __future__ import annotations

import argparse
import json
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

_NAVY = (14, 29, 48)
_INK = (30, 35, 41)
_SLATE = (86, 96, 107)
_LINE = (196, 202, 209)
_PALE = (241, 244, 247)
_WHITE = (255, 255, 255)
_ACCENT = (132, 31, 41)


class CleanMemoError(ValueError):
    """Raised when an input file is not a valid clean memo artifact."""


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

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_y(9)
        self.set_font("Memo", "B", 7.5)
        self.set_text_color(*_NAVY)
        self.cell(0, 4, "HAWKTRADE  /  EQUITY RESEARCH", align="L")
        self.set_x(self.w - self.r_margin - 55)
        self.set_font("Memo", "", 7.5)
        self.set_text_color(*_SLATE)
        self.cell(55, 4, f"{self.ticker}  ·  {self.as_of}", align="R")
        self.set_draw_color(*_LINE)
        self.line(self.l_margin, 15, self.w - self.r_margin, 15)
        self.set_y(20)

    def footer(self) -> None:
        self.set_y(-11)
        self.set_draw_color(*_LINE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_y(-9)
        self.set_font("Memo", "", 7)
        self.set_text_color(*_SLATE)
        self.cell(0, 4, "HAWKTRADE  ·  INVESTMENT MEMORANDUM", align="L")
        self.set_x(self.w - self.r_margin - 20)
        self.cell(20, 4, str(self.page_no()), align="R")


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
    # fpdf2 markdown handles **bold**, __bold__, *italic*, and _italic_.
    # Backticks/links are rendered as plain text so no external content is used.
    return re.sub(r"`([^`]*)`", r"\1", text or "")


def _write_body(pdf: HawktradePDF, text: str, *, indent: float = 0) -> None:
    pdf.set_x(pdf.l_margin + indent)
    pdf.set_font("Memo", "", 9.6)
    pdf.set_text_color(*_INK)
    width = pdf.w - pdf.r_margin - pdf.get_x()
    pdf.multi_cell(
        width,
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
) -> None:
    height = _table_row_height(pdf, cells, widths)
    if pdf.get_y() + height > pdf.h - pdf.b_margin:
        pdf.add_page()
    x0, y0 = pdf.l_margin, pdf.get_y()
    pdf.set_fill_color(*(_NAVY if header else (_PALE if int(y0) % 2 else _WHITE)))
    pdf.set_draw_color(*_LINE)
    pdf.set_text_color(*(_WHITE if header else _INK))
    pdf.set_font("Memo", "B" if header else "", 8)
    x = x0
    for cell, width in zip(cells, widths):
        pdf.rect(x, y0, width, height, style="DF")
        pdf.set_xy(x + 2, y0 + 1.5)
        pdf.multi_cell(
            width - 4,
            4.2,
            _plain_markdown(cell),
            new_x=XPos.RIGHT,
            new_y=YPos.TOP,
        )
        x += width
    pdf.set_xy(x0, y0 + height)


def _write_table(pdf: HawktradePDF, header: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    if not header:
        return
    total = pdf.w - pdf.l_margin - pdf.r_margin
    widths = [total / len(header)] * len(header)
    _draw_table_row(pdf, header, widths, header=True)
    for row in rows:
        padded = list(row[: len(header)]) + [""] * max(0, len(header) - len(row))
        _draw_table_row(pdf, padded, widths, header=False)
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
            pdf.line(pdf.l_margin, pdf.get_y() + 2, pdf.w - pdf.r_margin, pdf.get_y() + 2)
            pdf.ln(5)
            i += 1
            continue
        paragraph.append(stripped)
        i += 1
    flush()


def _display_date(payload: dict[str, Any]) -> str:
    raw = str(payload.get("generated_at_utc") or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%B %d, %Y")
    except ValueError:
        return raw[:10] or "Undated"


def _iter_sections(payload: dict[str, Any]) -> Iterable[tuple[str, str]]:
    sections = payload["sections"]
    order = [key for key in _DEFAULT_ORDER if sections.get(key)]
    for key in payload.get("sections_found") or []:
        if key not in order and sections.get(key):
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


def _render_cover(pdf: HawktradePDF, payload: dict[str, Any]) -> None:
    ticker = str(payload.get("ticker") or "SECTOR").upper()
    sector = str(payload.get("sector") or "Equity Research")
    rating = str(payload.get("rating") or "NOT RATED")
    target = str(payload.get("price_target") or "—")
    pdf.add_page()
    pdf.set_fill_color(*_NAVY)
    pdf.rect(0, 0, pdf.w, 51, style="F")
    pdf.set_xy(pdf.l_margin, 14)
    pdf.set_font("Memo", "B", 8)
    pdf.set_text_color(*_WHITE)
    pdf.cell(0, 5, "HAWKTRADE  /  INSTITUTIONAL EQUITY RESEARCH")
    pdf.set_xy(pdf.l_margin, 61)
    pdf.set_font("Memo", "B", 31)
    pdf.set_text_color(*_NAVY)
    pdf.cell(0, 12, ticker)
    pdf.set_xy(pdf.l_margin, 76)
    pdf.set_font("Memo", "", 13)
    pdf.set_text_color(*_SLATE)
    pdf.multi_cell(0, 7, sector)
    pdf.ln(10)
    usable = pdf.w - pdf.l_margin - pdf.r_margin
    box_width = usable / 3
    box_y = pdf.get_y()
    for idx, (label, value) in enumerate(
        (("INVESTMENT VIEW", rating), ("PRICE TARGET", target), ("AS OF", _display_date(payload)))
    ):
        x = pdf.l_margin + box_width * idx
        pdf.set_fill_color(*(_PALE if idx != 0 else _NAVY))
        pdf.rect(x, box_y, box_width - 2, 22, style="F")
        pdf.set_xy(x + 4, box_y + 4)
        pdf.set_font("Memo", "B", 6.5)
        pdf.set_text_color(*(_WHITE if idx == 0 else _SLATE))
        pdf.cell(box_width - 8, 4, label)
        pdf.set_xy(x + 4, box_y + 11)
        pdf.set_font("Memo", "B", 11)
        pdf.set_text_color(*(_WHITE if idx == 0 else _INK))
        pdf.cell(box_width - 8, 6, value)
    pdf.set_y(box_y + 34)
    preamble = str(payload.get("preamble") or "").strip()
    if preamble:
        pdf.set_font("Memo", "I", 11)
        pdf.set_text_color(*_SLATE)
        pdf.multi_cell(0, 6.2, _safe_markdown(preamble), markdown=True)
    pdf.set_y(max(pdf.get_y() + 10, 205))
    pdf.set_draw_color(*_ACCENT)
    pdf.set_line_width(1.1)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + 32, pdf.get_y())
    pdf.ln(6)
    pdf.set_font("Memo", "", 8)
    pdf.set_text_color(*_SLATE)
    pdf.multi_cell(
        0,
        4.5,
        "A long-form investment memorandum prepared for decision-makers. "
        "The argument, evidence, and disconfirming conditions are presented "
        "separately from operational quality-control records.",
    )


def generate_pdf(
    clean_memo: Path | str | dict[str, Any],
    *,
    output_path: Optional[Path | str] = None,
) -> Path:
    """Generate a Hawktrade presentation PDF from a clean memo path or payload."""
    payload = load_clean_memo(clean_memo) if not isinstance(clean_memo, dict) else clean_memo
    if payload.get("artifact") != "clean_memo" or not isinstance(payload.get("sections"), dict):
        raise CleanMemoError("payload must satisfy the clean_memo artifact contract")

    ticker = re.sub(r"[^\w.-]+", "_", str(payload.get("ticker") or "SECTOR").upper()) or "SECTOR"
    as_of = _display_date(payload)
    pdf = HawktradePDF(ticker=ticker, as_of=as_of)
    _render_cover(pdf, payload)
    for number, (title, body) in enumerate(_iter_sections(payload), start=1):
        pdf.add_page()
        pdf.set_font("Memo", "B", 7)
        pdf.set_text_color(*_ACCENT)
        pdf.cell(0, 5, f"{number:02d}  /  INVESTMENT MEMORANDUM")
        pdf.ln(8)
        pdf.set_font("Memo", "B", 21)
        pdf.set_text_color(*_NAVY)
        pdf.multi_cell(0, 9, title)
        pdf.set_draw_color(*_ACCENT)
        pdf.set_line_width(0.8)
        pdf.line(pdf.l_margin, pdf.get_y() + 2, pdf.l_margin + 26, pdf.get_y() + 2)
        pdf.ln(8)
        _render_markdown(pdf, body)

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
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    path = generate_pdf(args.clean_memo, output_path=args.output)
    print(f"Saved Hawktrade presentation: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
