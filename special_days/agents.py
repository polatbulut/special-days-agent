"""The two collector agents, sharing one canonical schema and pipeline.

Both agents collect into :class:`~special_days.models.SpecialDate`. They
differ only in *which* countries and sources they pull:

* :class:`TurkeyAgent`        — domestic demand (TR)
* :class:`InternationalAgent` — destination markets across the network
"""

from __future__ import annotations

import logging

from .config import DEFAULT_INTERNATIONAL_COUNTRIES, get_ticketmaster_key
from .models import SpecialDate
from .sources import nager, ticketmaster

logger = logging.getLogger(__name__)


class Agent:
    """Base collector: one set of countries + the shared sources."""

    def __init__(self, name: str, countries: list[str], ticketmaster_key: str | None = None):
        self.name = name
        self.countries = [c.upper() for c in countries]
        self.ticketmaster_key = ticketmaster_key

    def collect(
        self,
        year: int,
        include_holidays: bool = True,
        include_events: bool = True,
    ) -> list[SpecialDate]:
        """Collect special dates for ``year`` across this agent's countries.

        A failure on one country/source is logged and skipped so the rest of
        the run still produces output.
        """
        results: list[SpecialDate] = []

        for country in self.countries:
            if include_holidays:
                try:
                    results.extend(nager.fetch_holidays(country, year))
                except Exception as exc:  # noqa: BLE001 - resilient collection
                    logger.warning("[%s] holidays failed for %s: %s", self.name, country, exc)

            if include_events:
                if not self.ticketmaster_key:
                    logger.info(
                        "[%s] skipping events for %s (no TICKETMASTER_API_KEY set)",
                        self.name,
                        country,
                    )
                else:
                    try:
                        results.extend(
                            ticketmaster.fetch_events(country, self.ticketmaster_key, year=year)
                        )
                    except Exception as exc:  # noqa: BLE001 - resilient collection
                        logger.warning("[%s] events failed for %s: %s", self.name, country, exc)

        return results


class TurkeyAgent(Agent):
    """Domestic agent — Turkey only."""

    def __init__(self, ticketmaster_key: str | None = None):
        super().__init__(
            name="turkey",
            countries=["TR"],
            ticketmaster_key=ticketmaster_key if ticketmaster_key is not None else get_ticketmaster_key(),
        )


class InternationalAgent(Agent):
    """International agent — a configurable list of destination markets."""

    def __init__(self, countries: list[str] | None = None, ticketmaster_key: str | None = None):
        super().__init__(
            name="international",
            countries=countries or DEFAULT_INTERNATIONAL_COUNTRIES,
            ticketmaster_key=ticketmaster_key if ticketmaster_key is not None else get_ticketmaster_key(),
        )
