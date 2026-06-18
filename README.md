# Special-Date Intelligence Agents — MVP

Discovers forward-looking **special dates** — public holidays and public
events (concerts, sports, arts) — and emits them in one simple shape for the
flight-occupancy forecasting work (*Uçuş Doluluk Tahmini*):

```
Event  —  start date  —  end date  —  city
```

This is the **Phase-1 MVP**: free APIs only, a couple of sources, deliberately
small. (See the research document for the full two-agent vision; this repo is
the first runnable slice of it.)

## What it does

Two collector agents share one canonical record and one output:

| Agent              | Countries                     | Purpose                       |
| ------------------ | ----------------------------- | ----------------------------- |
| `TurkeyAgent`      | `TR`                          | Domestic demand               |
| `InternationalAgent` | configurable (default DE, GB, NL, FR, US) | Destination markets |

## Sources (free only)

| Source                  | Data            | API key            |
| ----------------------- | --------------- | ------------------ |
| [Nager.Date](https://date.nager.at/)            | Public holidays | **None needed**    |
| [Ticketmaster Discovery](https://developer.ticketmaster.com/) | Events (concerts/sports/arts) | Free key, optional |

## Quick start

No installation and no API key required for holidays — it runs on the Python
3.9+ standard library alone:

```bash
# Turkey public holidays for 2026
python -m special_days --agent turkey --source holidays --year 2026
```

```
Event                                    Start date  End date    City
---------------------------------------  ----------  ----------  ---------------
Yılbaşı                                  2026-01-01  2026-01-01  Nationwide (TR)
Ulusal Egemenlik ve Çocuk Bayramı        2026-04-23  2026-04-23  Nationwide (TR)
İşçi Bayramı                             2026-05-01  2026-05-01  Nationwide (TR)
Atatürk'ü Anma, Gençlik ve Spor Bayramı  2026-05-19  2026-05-19  Nationwide (TR)
Demokrasi ve Millî Birlik Günü           2026-07-15  2026-07-15  Nationwide (TR)
Zafer Bayramı                            2026-08-30  2026-08-30  Nationwide (TR)
Cumhuriyet Bayramı                       2026-10-29  2026-10-29  Nationwide (TR)

7 special date(s).
```

## Adding events (Ticketmaster)

Get a free key at <https://developer.ticketmaster.com/>, then:

```bash
cp .env.example .env          # paste your key into .env
# ...or just: export TICKETMASTER_API_KEY=your_key

python -m special_days --agent turkey --source events --year 2026
```

Without a key, the events step is skipped cleanly and you still get holidays.

## CLI

```
python -m special_days [options]

--agent       turkey | international | both     (default: both)
--year        calendar year                     (default: 2026)
--countries   CSV ISO codes for the intl agent  (default: DE,GB,NL,FR,US)
--source      holidays | events | all           (default: all)
--format      table | csv | json                (default: table)
--limit       cap rows printed (after sorting by date)
--verbose     log progress / skipped sources to stderr
```

Examples:

```bash
# Everything both agents can find, as CSV
python -m special_days --agent both --year 2026 --format csv

# International holidays for chosen markets
python -m special_days --agent international --countries DE,GB,AE --source holidays
```

## Canonical record

Every source maps into one `SpecialDate` (see [`special_days/models.py`](special_days/models.py)).
The four headline fields are the output; the rest aid traceability:

| Field        | Example            |
| ------------ | ------------------ |
| `event`      | `Tarkan Live`      |
| `start_date` | `2026-07-15`       |
| `end_date`   | `2026-07-16`       |
| `city`       | `Istanbul`         |
| `category`   | `holiday` / `event`|
| `country`    | `TR`               |
| `source`     | `nager` / `ticketmaster` |

## Project layout

```
special_days/
  models.py        SpecialDate (canonical record)
  http_client.py   tiny stdlib GET → JSON helper
  config.py        defaults + .env loader + API-key lookup
  sources/
    nager.py       holidays  (Nager.Date)
    ticketmaster.py events   (Ticketmaster Discovery)
  agents.py        TurkeyAgent, InternationalAgent
  output.py        table / csv / json renderers
  cli.py           argument parsing + orchestration
tests/             unittest suite (no network)
```

## Tests

```bash
python -m unittest discover -s tests
```

The suite mocks the network, so it runs offline and fast.

## Known limitations (MVP)

- **Moving religious holidays.** Nager.Date returns Turkey's *fixed* national
  holidays but not the moving Ramazan/Kurban Bayramı dates. Per the research
  doc, Diyanet is the source of truth for those — a planned next source.
- **No bridge-day (köprü) logic** yet, and holidays are single-day only.
- **Events** are limited to Ticketmaster-ticketed inventory.
- **No impact scoring / nearest-airport mapping** yet — this MVP delivers the
  raw `event — start — end — city` feed only.

These are intentional Phase-1 boundaries, not oversights.
