# Special-Date Intelligence Agents

Discovers forward-looking **special dates** — public/religious holidays, school
breaks, public events (concerts, sports, arts, football fixtures) and
corporate/B2B events (trade fairs, exhibitions, expos) — for flight-occupancy
forecasting (*Uçuş Doluluk Tahmini*), and emits them as:

```
Event — Start date — End date — City — Nearest airport (IATA) — Impact (0-100)
```

It collects a **rolling window** (default: the next 12 months) so a weekly job
always looks ahead, scores each date for expected demand impact, and maps
attended events to the nearest airport.

## What it does

Two collector agents share one canonical record, one enrichment pipeline and
one output:

| Agent                | Countries                                  | Sources                                  |
| -------------------- | ------------------------------------------ | ---------------------------------------- |
| `TurkeyAgent`        | `TR`                                       | Nager.Date, **Diyanet**, **MEB**, Ticketmaster, Football (Süper Lig), EventsEye |
| `InternationalAgent` | configurable (default DE, GB, NL, FR, US)  | Nager.Date, Ticketmaster, Football (top league per country + UEFA), EventsEye |

Collected dates are then **enriched**: nearest-airport mapping (IATA, within a
catchment radius) and a transparent **0-100 impact score**.

## Sources

| Source                                                        | Data                            | API key         |
| ------------------------------------------------------------- | ------------------------------- | --------------- |
| [Nager.Date](https://date.nager.at/)                          | Public holidays                 | **None**        |
| Diyanet (bundled, official)                                   | Ramazan/Kurban Bayramı          | **None**        |
| MEB (bundled, official)                                       | School breaks                   | **None**        |
| [Ticketmaster Discovery](https://developer.ticketmaster.com/) | Events (concerts/sports/arts)   | Free, optional  |
| [API-Football (API-Sports)](https://www.api-football.com/)    | Football fixtures (Süper Lig, UEFA, top leagues; incl. historical) | Free, optional  |
| [EventsEye](https://www.eventseye.com/) (scrape)              | Corporate/B2B trade fairs & expos (free directory, facts only) | None, opt-in |

Diyanet and MEB dates have no clean API, so they are bundled as curated
**official** dates (`special_days/data/`) and refreshed yearly. Football fixtures
carry away-fan / visiting-supporter travel demand that Ticketmaster does not
list, and API-Football also exposes **historical** fixtures for backtesting.

**Corporate / B2B events.** Trade fairs, exhibitions and expos drive incremental
business-cabin and inbound demand on fixed forward dates. They are collected by
**EventsEye** (`EVENTSEYE_ENABLED`) — a polite, opt-in scraper of the public
EventsEye trade-fair directory (no API key, no anti-bot wall). It extracts
**facts only** — name, dates, city, venue, sector and recurrence — and
deliberately **never collects organizer names, emails or phones** (KVKK/GDPR).
Listings carry no attendance figure and no coordinates, so the LLM scorer
estimates attendance from the event facts and the nearest-airport column stays
blank (as with football).

Other corporate-event sources were evaluated and rejected: **10times** is behind
a Cloudflare challenge and its ToS forbids commercial automated access;
**Eventbrite** removed its public event-search API in 2019 (it can only list your
own org's events); **Meetup** has no free API (paid Meetup Pro only). EventsEye
is the one free, scrapeable trade-fair directory.

## Quick start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# Turkey holidays for the next 12 months (no API key needed)
python -m special_days --agent turkey --source holidays
```

```
Event              Start date  End date    City             Nearest airport  Impact
-----------------  ----------  ----------  ---------------  ---------------  ------
Yaz tatili         2026-06-27  2026-09-13  Nationwide (TR)                   75
Zafer Bayramı      2026-08-30  2026-08-30  Nationwide (TR)                   70
...
Ramazan Bayramı    2027-03-08  2027-03-11  Nationwide (TR)                   99
Kurban Bayramı     2027-05-15  2027-05-19  Nationwide (TR)                   100
```

(Or: `make run ARGS="--agent turkey --source holidays"`.)

## Adding events (Ticketmaster + Football + Corporate/B2B)

Get a free [Ticketmaster](https://developer.ticketmaster.com/) and/or
[API-Football](https://www.api-football.com/) key, then:

```bash
cp .env.example .env          # paste TICKETMASTER_API_KEY / FOOTBALL_API_KEY into .env
python -m special_days --agent turkey --source events

# Corporate/B2B: free EventsEye trade-fair scrape (opt-in, no key)
EVENTSEYE_ENABLED=1 python -m special_days --agent turkey --source events
```

Each event source is independent and gated on its own credential: set
`TICKETMASTER_API_KEY` for concerts/sports/arts, `FOOTBALL_API_KEY` for league
and cup football fixtures, and `EVENTSEYE_ENABLED=1` to turn on the free EventsEye
corporate/B2B trade-fair scrape. Any source whose credential is missing (or the
EventsEye flag left off) is skipped cleanly, so you still get holidays (and
whichever event source you did configure).

## Excel output (`.xlsx`)

```bash
# A .xlsx output path implies --format xlsx (no need to pass it)
python -m special_days --agent both -o out/special_days.xlsx
```

The file has a bold/frozen header, an auto-filter, real Excel date cells and a
numeric impact column (built with `openpyxl`). The format is inferred from the
output extension (`.xlsx`/`.csv`/`.json`); pass `--format` to override. Missing
parent directories are created automatically. If `--output` is omitted, `--format
xlsx` writes `special_days_<start>_<end>.xlsx`.

## Scheduling

The rolling window (`--months`) makes this a drop-in for any scheduler — wire
the command up to run as often as you like (cron, CI, a task runner, …). No
scheduler is bundled.

## CLI

```
python -m special_days [options]

--agent               turkey | international | both    (default: both)
--start               window start YYYY-MM-DD          (default: today)
--months              window length in months          (default: 12)
--countries           CSV ISO codes for the intl agent  (default: DE,GB,NL,FR,US)
--source              holidays | events | all           (default: all)
--format              table | csv | json | xlsx         (default: inferred from -o, else table)
--output, -o          write to a file instead of stdout (xlsx always writes a file)
--catchment-km        nearest-airport radius in km      (default: 150)
--max-event-span-days drop events longer than this; 0 = off (default: 30)
--impact-scorer       heuristic | openai | vllm | azure (default: heuristic)
--llm-model           override the LLM model name (openai/vllm)
--concurrency         parallel LLM scoring requests     (default: 8 llm / 1 heuristic)
--limit               cap rows printed (after sorting by date)
--verbose             log progress / skipped sources to stderr
```

Examples:

```bash
# Next 12 months, both agents, Excel deliverable
python -m special_days --agent both --format xlsx -o out/special_days.xlsx

# A specific 6-month window starting on a chosen date, as CSV
python -m special_days --start 2026-09-01 --months 6 --format csv -o autumn.csv

# International holidays for chosen markets, to the terminal
python -m special_days --agent international --countries DE,GB,AE --source holidays
```

## Docker

```bash
docker build -t special-days-agent .

# holidays (no key needed)
docker run --rm special-days-agent --agent turkey --source holidays

# events + Excel: pass the key via --env-file and mount ./out for the file
mkdir -p out
docker run --rm --env-file .env -v "$PWD/out:/app/out" special-days-agent \
    --agent both --format xlsx -o out/special_days.xlsx
```

Or via the Makefile: `make docker-run ARGS="--agent both --format xlsx -o out/special_days.xlsx"`.

## Canonical record, bridges & impact

> 📐 **For the exact formulas, constants, edge cases and worked examples of every
> calculation** — window math, the haversine airport mapping, both impact scorers,
> the köprü bridge and the per-day curves — see
> **[docs/CALCULATIONS.md](docs/CALCULATIONS.md)**. The summary below is the
> overview; that document is the precise, code-grounded reference.

Every source maps into one `SpecialDate` (see [`special_days/models.py`](special_days/models.py)).
Output columns: Event, Start date, End date, City, Source (nager/diyanet/meb/
ticketmaster/football/eventseye), Nearest airport, Impact, Predicted attendance,
Bridge start, Bridge end — plus two per-day weight lists (csv/xlsx/json).

**Bridge ranges (köprü).** For Turkish holidays, `bridge_start`/`bridge_end`
([`special_days/bridge.py`](special_days/bridge.py)) extend the statutory dates
outward to the full long-weekend block: adjacent weekends are absorbed, and up
to 2 working days (1 for a single-day holiday) are bridged to reach a weekend.
E.g. Ramazan Bayramı 2027 `08–11 Mar` → bridge `06–14 Mar`.

**Per-day impact curves.** Each record carries two ordered weight lists
([`special_days/curve.py`](special_days/curve.py)) — over the statutory range
(`impact_by_day`) and the bridge range (`impact_by_day_bridge`). The curve is a
**Linear V** (peak at the departure/return ends, ~50% mid-break) with **weekends
forced to the peak**. Example bridge curve: `99,99,74,62,50,62,74,99,99`.

**Impact & predicted attendance** come from a pluggable scorer
([`special_days/scoring.py`](special_days/scoring.py)) with **per-source prompts**
(`nager` / `diyanet` / `meb` / `ticketmaster` / `football` / `eventseye` each
distinct).
**Impact** (0-100, the curve peak) is defined as the **relative volume of
incremental Turkish Airlines ticket purchases** the date/event drives — literally
*"how many people would buy a THY ticket because of it"*. The prompt forces the
model to reason about **who travels and whether they'd fly THY** (Türkiye as
origin/destination, THY's network and IST connecting hub, diaspora/VFR demand),
then calibrate to an anchored rubric:

| Band   | Anchor                                                                            |
| ------ | -------------------------------------------------------------------------------- |
| 90-100 | Turkish national religious holiday (Kurban / Ramazan Bayramı) — peak domestic+VFR |
| 70-85  | Turkish national public holiday (esp. with a köprü bridge) or major TR school break |
| 35-55  | marquee international event in a THY hub (UEFA CL final / global-superstar concert in Istanbul) |
| 10-30  | a large event in a THY-served destination abroad drawing **some** international/diaspora travel |
| 0-10   | a local/regional foreign event, overwhelmingly local audience, no Türkiye link (e.g. Isle of Wight Festival in Newport; a domestic lower-league match) |

So a big local foreign event scores **single digits**, not high, because almost
nobody flies THY for it. For **events** (Ticketmaster, football and EventsEye) the
prompt embeds the **full raw payload** and the model also returns **predicted
attendance** (THY impact is usually a small fraction of attendance for foreign
local events); holiday rows leave attendance blank. For corporate/B2B trade fairs
the prompt notes their business-cabin / advance-booking skew and has the model
estimate attendance from the event facts (EventsEye carries no headcount).
- `heuristic` (default): offline category + duration + airport-proximity score,
  no key, **no attendance**.
- `openai` (`--impact-scorer openai`): scores each record via the OpenAI chat API
  (default model `gpt-5-mini`); needs `OPENAI_API_KEY`.
- `vllm` (`--impact-scorer vllm`): same prompts against any OpenAI-compatible vLLM
  server; needs `VLLM_BASE_URL` (+ `VLLM_MODEL`, optional `VLLM_API_KEY`).
- `azure` (`--impact-scorer azure`): Azure OpenAI; needs `AZURE_OPENAI_ENDPOINT`
  (e.g. `https://your-resource.openai.azure.com/`), `AZURE_OPENAI_API_KEY` and
  `AZURE_OPENAI_DEPLOYMENT` (the deployment name; or pass `--llm-model`).
  `AZURE_OPENAI_API_VERSION` is optional (default `2024-10-21`; reasoning models
  like **gpt-5.1** need a preview version, e.g. `2024-12-01-preview`). A generous
  `max_completion_tokens` (default 16384, override with
  `AZURE_OPENAI_MAX_COMPLETION_TOKENS`) is sent so reasoning models don't return
  empty content.

> Predicted attendance is populated only by an LLM scorer (the heuristic leaves
> it blank). Event prompts send the full payload, so input-token cost rises with
> the feed size — scope LLM runs with `--source` / `--agent`.

All LLM backends share one OpenAI-compatible client
([`special_days/gateways.py`](special_days/gateways.py)); pick the model with
`--llm-model`. Examples:

```bash
# OpenAI gpt-5-mini (set OPENAI_API_KEY in .env). Scope small for cost:
python -m special_days --agent turkey --source holidays --impact-scorer openai

# A self-hosted vLLM model
VLLM_BASE_URL=http://localhost:8000/v1 VLLM_MODEL=my-model \
  python -m special_days --agent turkey --source holidays --impact-scorer vllm

# Azure OpenAI (endpoint + key + deployment in .env, or --llm-model for the deployment)
python -m special_days --agent turkey --source holidays --impact-scorer azure
```

The LLM scorer makes **one request per record**. Those calls run **concurrently**
(`--concurrency`, default 8 for the LLM backends) — airport mapping and the
bridge/curve maths stay sequential. Lower `--concurrency` if you hit rate limits;
still, scope large runs with `--agent` / `--source` to control cost (each record
is a billable call).

```bash
# Score the full feed faster (16 requests in flight at once)
python -m special_days --agent both --impact-scorer openai --concurrency 16 \
    --format xlsx -o out/special_days.xlsx
```

## Project layout

```
special_days/
  models.py        SpecialDate (canonical record)
  window.py        rolling-window date math
  http_client.py   tiny stdlib GET → JSON helper
  config.py        defaults + .env loader + API-key lookup
  dataset.py       loaders for the bundled reference data
  data/            airports.json, diyanet_holidays.json, meb_breaks.json
  sources/
    nager.py       public holidays   (Nager.Date)
    diyanet.py     religious holidays (bundled official)
    meb.py         school breaks      (bundled official)
    ticketmaster.py events           (Ticketmaster Discovery)
    football.py    football fixtures (API-Football / API-Sports)
  agents.py        TurkeyAgent, InternationalAgent
  bridge.py        köprü bridge ranges (TR holidays)
  curve.py         per-day Linear-V weight curves
  scoring.py       pluggable impact scorer (heuristic default + LLM)
  gateways.py      OpenAI / vLLM chat-completions gateways
  enrich.py        airport mapping + scoring + bridges + curves + noise filter
  output.py        table / csv / json renderers
  xlsx_writer.py   Excel (.xlsx) writer (openpyxl)
  cli.py           argument parsing + orchestration
tests/             unittest suite (no network)
Dockerfile · Makefile · requirements.txt
```

## Tests

```bash
make test          # creates the venv if needed, then runs the suite
# ...or, with the venv active:
python -m unittest discover -s tests
```

The suite mocks the network, so it runs offline and fast.

## Known limitations

- **Bridge days (köprü).** Government-declared administrative leave that extends
  a bayram (e.g. 3 days → 9) is announced ad hoc and is **not** auto-included;
  the bundled spans are the statutory holiday only.
- **Diyanet/MEB dates are bundled** from official announcements and need a yearly
  refresh. The 2027-2028 MEB summer-break *end* is an estimate (calendar not yet
  published).
- **Event noise.** Some Ticketmaster "season ticket" listings have a single date
  and so slip past the span filter; impact scoring is heuristic, not learned.
- **Football coverage & free tier.** Football pulls Süper Lig (Turkey) plus the
  top league per international market and UEFA club competitions — kept modest to
  respect the free-tier request cap (a few paged requests per league per season).
  Seasons are derived from the window using the European August-start convention,
  so calendar-year leagues (e.g. MLS) and unmapped countries are skipped. Fixture
  timestamps are UTC and recorded as the UTC calendar day (a very late kickoff can
  land on the adjacent local day); fixtures carry no venue coordinates, so
  football rows have no nearest airport.
- **Airport list** covers major TR airports + destination hubs; extend
  `data/airports.json` for finer coverage.
- **Events** are limited to Ticketmaster-ticketed inventory.
