"""Minimal, dependency-free ``.xlsx`` writer.

Writes a single-sheet Office Open XML workbook using only the standard
library (``zipfile`` + string templates) — no third-party dependency, so the
project still "just runs" with no ``pip install``. Produces a clean,
Excel-/Numbers-readable file with a frozen, auto-filtered header row.

Cell values are written as inline strings (dates as ISO ``YYYY-MM-DD`` text),
which keeps the format tiny and robust while sorting correctly in Excel.
"""

from __future__ import annotations

import re
import zipfile
from typing import Iterable

from .models import SpecialDate
from .output import HEADERS

# XML 1.0 forbids most control characters; strip them defensively.
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _esc(value: str) -> str:
    value = _ILLEGAL_XML.sub("", value)
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _col(index: int) -> str:
    """1-based column index -> spreadsheet letter (1->A, 4->D, 27->AA)."""
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _cell(col_index: int, row_index: int, text: str) -> str:
    ref = f"{_col(col_index)}{row_index}"
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_esc(text)}</t></is></c>'


def _row(row_index: int, values: Iterable[str]) -> str:
    cells = "".join(_cell(i + 1, row_index, value) for i, value in enumerate(values))
    return f'<row r="{row_index}">{cells}</row>'


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    "</Types>"
)

_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    "</Relationships>"
)

_WORKBOOK = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<sheets><sheet name="Special Dates" sheetId="1" r:id="rId1"/></sheets>'
    "</workbook>"
)

_WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
    "</Relationships>"
)


def _sheet(rows: list[SpecialDate]) -> str:
    body = [_row(1, HEADERS)]
    for number, special_date in enumerate(rows, start=2):
        body.append(_row(number, special_date.core_row()))

    dimension = f"A1:{_col(len(HEADERS))}{len(rows) + 1}"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dimension}"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        "<cols>"
        '<col min="1" max="1" width="55" customWidth="1"/>'
        '<col min="2" max="3" width="14" customWidth="1"/>'
        '<col min="4" max="4" width="24" customWidth="1"/>'
        "</cols>"
        f'<sheetData>{"".join(body)}</sheetData>'
        f'<autoFilter ref="{dimension}"/>'
        "</worksheet>"
    )


def write_xlsx(rows: list[SpecialDate], path: str) -> None:
    """Write ``rows`` to an ``.xlsx`` file at ``path`` (four headline columns)."""
    parts = {
        "[Content_Types].xml": _CONTENT_TYPES,
        "_rels/.rels": _ROOT_RELS,
        "xl/workbook.xml": _WORKBOOK,
        "xl/_rels/workbook.xml.rels": _WORKBOOK_RELS,
        "xl/worksheets/sheet1.xml": _sheet(rows),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
