"""Loaders for the bundled reference data (airports, Diyanet, MEB)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"


def _load(name: str) -> list:
    return json.loads((_DATA_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def load_airports() -> list[dict]:
    """Curated airport reference: iata, name, city, country, lat, lon."""
    return _load("airports.json")


@lru_cache(maxsize=None)
def load_diyanet() -> list[dict]:
    """Official Diyanet religious-holiday dates (curated, updated yearly)."""
    return _load("diyanet_holidays.json")


@lru_cache(maxsize=None)
def load_meb() -> list[dict]:
    """Official MEB school-break dates (curated, updated yearly)."""
    return _load("meb_breaks.json")
