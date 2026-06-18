"""Render collected :class:`SpecialDate` records in the requested format.

The headline output is exactly what the business asked for:

    Event  —  start date  —  end date  —  city
"""

from __future__ import annotations

import csv
import io
import json

from .models import SpecialDate

HEADERS = ("Event", "Start date", "End date", "City")


def render_table(rows: list[SpecialDate]) -> str:
    """Aligned, human-readable table of the four headline fields."""
    if not rows:
        return "No special dates found."

    table = [HEADERS] + [r.core_row() for r in rows]
    widths = [max(len(str(col[i])) for col in table) for i in range(len(HEADERS))]

    def fmt(cols: tuple[str, ...]) -> str:
        return "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(cols))

    lines = [fmt(HEADERS), "  ".join("-" * w for w in widths)]
    lines.extend(fmt(r.core_row()) for r in rows)
    lines.append("")
    lines.append(f"{len(rows)} special date(s).")
    return "\n".join(lines)


def render_csv(rows: list[SpecialDate]) -> str:
    """CSV with the four headline columns: event,start_date,end_date,city."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["event", "start_date", "end_date", "city"])
    for r in rows:
        writer.writerow(r.core_row())
    return buffer.getvalue().rstrip("\n")


def render_json(rows: list[SpecialDate]) -> str:
    """Full records (incl. category/country/source) as a JSON array."""
    return json.dumps([r.to_dict() for r in rows], ensure_ascii=False, indent=2)


RENDERERS = {
    "table": render_table,
    "csv": render_csv,
    "json": render_json,
}


def render(rows: list[SpecialDate], fmt: str) -> str:
    return RENDERERS[fmt](rows)
