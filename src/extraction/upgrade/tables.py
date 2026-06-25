"""Deterministic HTML-table -> upgrade facts (stage 3 of the funnel).

Most "supported upgrade path" and compatibility content on docs.cloudera.com
lives in HTML tables. Parsing those structurally costs *zero* LLM tokens, so we
do it first and only fall back to the LLM for prose the tables don't cover.

Uses the stdlib ``html.parser`` to stay dependency-free (the rest of the
codebase avoids bs4/lxml for the same reason).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import List, Optional

from .schema import UpgradeFact

_CELL_TAGS = {"td", "th"}
_SUPPORT_TOKENS = {"yes", "y", "supported", "\u2713", "\u2714", "x", "ok", "true"}
_FROM_HEADERS = ("from", "source", "current", "existing", "old")
_TO_HEADERS = ("to", "target", "new", "destination")


@dataclass
class Table:
    header: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)


class _TableCollector(HTMLParser):
    """Collect flat HTML tables as header + data rows (nested tables not split)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: List[Table] = []
        self._depth = 0
        self._rows: List[List[str]] = []
        self._header_index: Optional[int] = None
        self._row: List[str] = []
        self._row_all_th = True
        self._cell: Optional[List[str]] = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._rows, self._header_index = [], None
        elif tag == "tr" and self._depth:
            self._row, self._row_all_th = [], True
        elif tag in _CELL_TAGS and self._depth:
            self._cell = []
            if tag == "td":
                self._row_all_th = False

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in _CELL_TAGS and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._depth and self._row:
            if self._row_all_th and self._header_index is None:
                self._header_index = len(self._rows)
            self._rows.append(self._row)
        elif tag == "table" and self._depth:
            if self._depth == 1:
                self._finish_table()
            self._depth -= 1

    def _finish_table(self):
        if not self._rows:
            return
        head_idx = self._header_index if self._header_index is not None else 0
        header = self._rows[head_idx]
        rows = [r for i, r in enumerate(self._rows) if i != head_idx]
        self.tables.append(Table(header=header, rows=rows))


def extract_tables(html: str) -> List[Table]:
    parser = _TableCollector()
    parser.feed(html)
    return parser.tables


def _header_index(header: List[str], needles) -> Optional[int]:
    for idx, cell in enumerate(header):
        lowered = cell.casefold()
        if any(needle in lowered for needle in needles):
            return idx
    return None


def _from_to_facts(table: Table, source: str) -> List[UpgradeFact]:
    """`From X | To Y` shaped tables -> upgradesTo(X, Y) per data row."""
    from_idx = _header_index(table.header, _FROM_HEADERS)
    to_idx = _header_index(table.header, _TO_HEADERS)
    if from_idx is None or to_idx is None or from_idx == to_idx:
        return []
    facts: List[UpgradeFact] = []
    for row in table.rows:
        if max(from_idx, to_idx) >= len(row):
            continue
        src, dst = row[from_idx], row[to_idx]
        if src and dst:
            facts.append(UpgradeFact(src, "upgradesTo", dst, source=source, origin="table"))
    return facts


def _matrix_facts(table: Table, source: str) -> List[UpgradeFact]:
    """Compatibility matrix -> isCompatibleWith for each supported cell.

    Header is `[corner, col1, col2, ...]`; each row is `[label, cell, ...]`. A
    cell counts as supported when its text is an affirmative token (yes/✓/...).
    """
    if len(table.header) < 2:
        return []
    if not _is_compat_header(table.header):
        return []
    columns = table.header[1:]
    facts: List[UpgradeFact] = []
    for row in table.rows:
        if not row:
            continue
        label = row[0]
        for col_idx, col in enumerate(columns, start=1):
            if col_idx < len(row) and _is_supported(row[col_idx]) and label and col:
                facts.append(
                    UpgradeFact(label, "isCompatibleWith", col, source=source, origin="table")
                )
    return facts


def _is_compat_header(header: List[str]) -> bool:
    joined = " ".join(header).casefold()
    return "compat" in joined or "support" in joined


def _is_supported(cell: str) -> bool:
    return cell.strip().casefold() in _SUPPORT_TOKENS


def facts_from_html(html: str, source: str = "") -> List[UpgradeFact]:
    """Extract all deterministic upgrade facts from a page's HTML tables."""
    facts: List[UpgradeFact] = []
    for table in extract_tables(html):
        facts.extend(_from_to_facts(table, source))
        facts.extend(_matrix_facts(table, source))
    return facts
