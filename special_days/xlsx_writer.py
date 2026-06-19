"""Excel (``.xlsx``) writer, built on openpyxl.

Produces a single "Special Dates" sheet with the six headline columns
(Event, Start date, End date, City, Nearest airport, Impact), a bold +
frozen header row, an auto-filter, real Excel date cells and sensible
column widths.

openpyxl is imported lazily so the other output formats (table/csv/json)
keep working even if it is not installed.
"""

from __future__ import annotations

from .models import SpecialDate
from .output import HEADERS

_COLUMN_WIDTHS = {"A": 50, "B": 13, "C": 13, "D": 22, "E": 15, "F": 8}


def write_xlsx(rows: list[SpecialDate], path: str) -> None:
    """Write ``rows`` to an ``.xlsx`` file at ``path``."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Special Dates"

    sheet.append(list(HEADERS))
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for special_date in rows:
        sheet.append(
            [
                special_date.event,
                special_date.start_date,  # real date cell
                special_date.end_date,  # real date cell
                special_date.city,
                special_date.nearest_airport or "",
                special_date.impact_score,  # numeric cell (or None)
            ]
        )

    for row in sheet.iter_rows(min_row=2, min_col=2, max_col=3):
        for cell in row:
            cell.number_format = "yyyy-mm-dd"

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{sheet.max_row}"

    for column, width in _COLUMN_WIDTHS.items():
        sheet.column_dimensions[column].width = width

    workbook.save(path)
