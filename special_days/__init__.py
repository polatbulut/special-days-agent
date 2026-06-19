"""Special-Date Intelligence Agents (MVP).

Discovers forward-looking *special dates* — public/religious holidays, school
breaks and public events (concerts, sports, arts) — and emits them as:

    Event — Start date — End date — City — Nearest airport — Impact

Two collector agents share one canonical schema:

* :class:`special_days.agents.TurkeyAgent`        — domestic (TR)
* :class:`special_days.agents.InternationalAgent` — international markets

Sources used in this MVP (free only):

* Nager.Date         — public holidays (no API key required)
* Ticketmaster Discovery — events (free API key, optional)
"""

__version__ = "0.1.0"
