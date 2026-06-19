# Special-Date Intelligence Agents

Discovers forward-looking **special dates** — public/religious holidays, school
breaks and public events (concerts, sports, arts) — for flight-occupancy
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
| `TurkeyAgent`        | `TR`                                       | Nager.Date, **Diyanet**, **MEB**, Ticketmaster |
| `InternationalAgent` | configurable (default DE, GB, NL, FR, US)  | Nager.Date, Ticketmaster                 |

Collected dates are then **enriched**: nearest-airport mapping (IATA, within a
catchment radius) and a transparent **0-100 impact score**.

## Sources (free only)

| Source                                                        | Data                            | API key         |
| ------------------------------------------------------------- | ------------------------------- | --------------- |
| [Nager.Date](https://date.nager.at/)                          | Public holidays                 | **None**        |
| Diyanet (bundled, official)                                   | Ramazan/Kurban Bayramı          | **None**        |
| MEB (bundled, official)                                       | School breaks                   | **None**        |
| [Ticketmaster Discovery](https://developer.ticketmaster.com/) | Events (concerts/sports/arts)   | Free, optional  |

Diyanet and MEB dates have no clean API, so they are bundled as curated
**official** dates (`special_days/data/`) and refreshed yearly.

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

## Adding events (Ticketmaster)

Get a free key at <https://developer.ticketmaster.com/>, then:

```bash
cp .env.example .env          # paste your key into .env
python -m special_days --agent turkey --source events
```

Without a key the events step is skipped cleanly and you still get holidays.

## Excel output (`.xlsx`)

```bash
python -m special_days --agent both --format xlsx -o out/special_days.xlsx
```

The file has the six columns, a bold/frozen header, an auto-filter, real Excel
date cells and a numeric impact column (built with `openpyxl`). Missing parent
directories are created automatically. If `--output` is omitted it defaults to
`special_days_<start>_<end>.xlsx`.

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
--format              table | csv | json | xlsx         (default: table)
--output, -o          write to a file instead of stdout (xlsx always writes a file)
--catchment-km        nearest-airport radius in km      (default: 150)
--max-event-span-days drop events longer than this; 0 = off (default: 30)
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

## Canonical record & impact score

Every source maps into one `SpecialDate` (see [`special_days/models.py`](special_days/models.py)).
The six headline fields are the output; the rest aid traceability.

The **impact score** (`special_days/enrich.py`) is a transparent, tunable
heuristic combining a per-category base weight (religious holiday > public
holiday > school break ≈ concert > …), a duration bonus (a 9-day bayram
outranks a 3-day one) and airport proximity, clamped to 0-100. Calibrate the
weights against historical load factors, then later replace with a learned model.

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
  agents.py        TurkeyAgent, InternationalAgent
  enrich.py        nearest-airport mapping + impact scoring + noise filter
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
- **Airport list** covers major TR airports + destination hubs; extend
  `data/airports.json` for finer coverage.
- **Events** are limited to Ticketmaster-ticketed inventory.
