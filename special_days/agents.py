"""The two collector agents, sharing one canonical schema and pipeline.

Both collect into :class:`~special_days.models.SpecialDate` over a date
window. They differ in which countries and sources they pull:

* :class:`TurkeyAgent`        — domestic (TR), incl. Diyanet + MEB sources
* :class:`InternationalAgent` — destination markets across the network
"""

from __future__ import annotations

import logging
from datetime import date

from .config import (
    DEFAULT_INTERNATIONAL_COUNTRIES,
    eventseye_enabled,
    get_football_api_key,
    get_ticketmaster_key,
)
from .models import SpecialDate
from .sources import diyanet, eventseye, football, meb, nager, ticketmaster

logger = logging.getLogger(__name__)


class Agent:
    """Base collector: a set of countries + the shared API sources."""

    def __init__(
        self,
        name: str,
        countries: list[str],
        ticketmaster_key: str | None = None,
        football_key: str | None = None,
        eventseye: bool = False,
    ):
        self.name = name
        self.countries = [c.upper() for c in countries]
        self.ticketmaster_key = ticketmaster_key
        self.football_key = football_key
        self.eventseye_enabled = eventseye

    def collect(
        self,
        start: date,
        end: date,
        include_holidays: bool = True,
        include_events: bool = True,
    ) -> list[SpecialDate]:
        """Collect special dates within ``[start, end]`` across this agent's countries.

        A failure on one country/source is logged and skipped so the rest of
        the run still produces output.
        """
        results: list[SpecialDate] = []

        for country in self.countries:
            if include_holidays:
                try:
                    results.extend(nager.fetch_holidays_in_window(country, start, end))
                except Exception as exc:  # noqa: BLE001 - resilient collection
                    logger.warning("[%s] holidays failed for %s: %s", self.name, country, exc)

            if include_events:
                self._collect_events_for_country(country, start, end, results)

        # Football is league- (not country-) keyed, so it runs once after the
        # per-country loop, gated on its own key (skipped cleanly if absent).
        if include_events:
            results.extend(self._collect_football(start, end))

        return results

    def _collect_events_for_country(
        self, country: str, start: date, end: date, results: list[SpecialDate]
    ) -> None:
        """Run the country-keyed event sources, each gated and resilient.

        Ticketmaster (concerts/sports/arts) and EventsEye (free corporate/B2B
        trade-fair scrape) are independent: each is gated on its own credential/
        flag and a failure on one is logged and skipped so the other still
        produces output.
        """
        # Ticketmaster — concerts/sports/arts, gated on its API key.
        if self.ticketmaster_key:
            try:
                results.extend(ticketmaster.fetch_events(country, self.ticketmaster_key, start, end))
            except Exception as exc:  # noqa: BLE001 - resilient collection
                logger.warning("[%s] ticketmaster failed for %s: %s", self.name, country, exc)
        else:
            logger.info(
                "[%s] skipping ticketmaster for %s (no TICKETMASTER_API_KEY set)", self.name, country
            )

        # EventsEye — free trade-fair scrape, opt-in via EVENTSEYE_ENABLED.
        if self.eventseye_enabled:
            try:
                results.extend(eventseye.fetch_events_in_window(country, start, end))
            except Exception as exc:  # noqa: BLE001 - resilient collection
                logger.warning("[%s] eventseye failed for %s: %s", self.name, country, exc)

    def _football_leagues(self) -> list[int]:
        """API-Football league ids this agent pulls — top league per country."""
        leagues: list[int] = []
        for country in self.countries:
            league = football.TOP_LEAGUE_BY_COUNTRY.get(country)
            if league is None:
                logger.info("[%s] no football league mapping for %s; skipping", self.name, country)
            elif league not in leagues:
                leagues.append(league)
        return leagues

    def _collect_football(self, start: date, end: date) -> list[SpecialDate]:
        if not self.football_key:
            logger.info("[%s] skipping football (no FOOTBALL_API_KEY set)", self.name)
            return []
        results: list[SpecialDate] = []
        for league in self._football_leagues():
            try:
                results.extend(
                    football.fetch_fixtures_in_window(league, self.football_key, start, end)
                )
            except Exception as exc:  # noqa: BLE001 - resilient collection
                logger.warning("[%s] football league %s failed: %s", self.name, league, exc)
        return results


class TurkeyAgent(Agent):
    """Domestic agent — Turkey, plus the bundled Diyanet + MEB sources."""

    def __init__(
        self,
        ticketmaster_key: str | None = None,
        football_key: str | None = None,
        eventseye: bool | None = None,
    ):
        super().__init__(
            name="turkey",
            countries=["TR"],
            ticketmaster_key=ticketmaster_key if ticketmaster_key is not None else get_ticketmaster_key(),
            football_key=football_key if football_key is not None else get_football_api_key(),
            eventseye=eventseye if eventseye is not None else eventseye_enabled(),
        )

    def _football_leagues(self):
        return [football.SUPER_LIG]  # Süper Lig

    def collect(self, start, end, include_holidays=True, include_events=True):
        results = super().collect(start, end, include_holidays, include_events)
        if include_holidays:
            for source, label in ((diyanet, "diyanet"), (meb, "meb")):
                try:
                    results.extend(source.fetch_in_window(start, end))
                except Exception as exc:  # noqa: BLE001 - resilient collection
                    logger.warning("[turkey] %s failed: %s", label, exc)
        return results


class InternationalAgent(Agent):
    """International agent — a configurable list of destination markets."""

    def __init__(
        self,
        countries: list[str] | None = None,
        ticketmaster_key: str | None = None,
        football_key: str | None = None,
        eventseye: bool | None = None,
    ):
        super().__init__(
            name="international",
            countries=countries or DEFAULT_INTERNATIONAL_COUNTRIES,
            ticketmaster_key=ticketmaster_key if ticketmaster_key is not None else get_ticketmaster_key(),
            football_key=football_key if football_key is not None else get_football_api_key(),
            eventseye=eventseye if eventseye is not None else eventseye_enabled(),
        )

    def _football_leagues(self):
        # Top domestic league per configured country, plus UEFA club competitions.
        leagues = super()._football_leagues()
        for uefa in football.UEFA_LEAGUES:
            if uefa not in leagues:
                leagues.append(uefa)
        return leagues
