"""Excel (``.xlsx``) writer, built on openpyxl.

Produces a single "Special Dates" sheet: the eight headline columns (Event,
Start date, End date, City, Nearest airport, Impact, Bridge start, Bridge end)
plus two per-day weight columns (Impact by day, Impact by day (bridge)) carried
as JSON strings. Bold + frozen header, auto-filter, real Excel date cells.
"""

from __future__ import annotations

import json

from .models import SpecialDate
from .output import HEADERS

_JSON_HEADERS = ["Impact by day", "Impact by day (bridge)"]
_DATE_COLUMNS = (2, 3, 7, 8)  # Start, End, Bridge start, Bridge end
_COLUMN_WIDTHS = {
    "A": 46, "B": 12, "C": 12, "D": 20, "E": 15, "F": 8,
    "G": 12, "H": 12, "I": 58, "J": 58,
}


def write_xlsx(rows: list[SpecialDate], path: str) -> None:
    """Write ``rows`` to an ``.xlsx`` file at ``path``."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Special Dates"

    header = list(HEADERS) + _JSON_HEADERS
    sheet.append(header)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for sd in rows:
        sheet.append(
            [
                sd.event,
                sd.start_date,  # real date cell
                sd.end_date,  # real date cell
                sd.city,
                sd.nearest_airport or "",
                sd.impact_score,  # numeric cell
                sd.bridge_start,  # real date cell
                sd.bridge_end,  # real date cell
                json.dumps(dict(sd.impact_by_day or ()), ensure_ascii=False),
                json.dumps(dict(sd.impact_by_day_bridge or ()), ensure_ascii=False),
            ]
        )

    for row in sheet.iter_rows(min_row=2):
        for column in _DATE_COLUMNS:
            row[column - 1].number_format = "yyyy-mm-dd"

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(header))}{sheet.max_row}"

    for column, width in _COLUMN_WIDTHS.items():
        sheet.column_dimensions[column].width = width

    workbook.save(path)
