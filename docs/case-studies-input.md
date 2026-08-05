# Case-study inputs — the two files you have to supply

`python -m special_days.case_studies` reads exactly two local files and writes
CSVs plus (via `special_days.case_report`) an Excel workbook, an HTML dashboard
and one SVG per event. It makes **no network calls and no LLM calls**.
Everything it knows about which events to look at, and about load factor, comes
from these two files.

```
python -m special_days.case_studies \
    --events out/events.csv \
    --lf     out/lf_route_day.csv \
    --out    out/case_studies

# or, equivalently
make case-studies EVENTS=out/events.csv LF=out/lf_route_day.csv OUT=out/case_studies
```

| | file | who fills it | grain |
|---|---|---|---|
| 1 | events file | Polat, by hand | one row per event |
| 2 | LF extract | the data owner (hand them `docs/lf-extract-spec.md`) | one row per (ORG, DST, flight date) |

Start from **`out/events.template.csv`**, which has three worked rows in it
already: a one-day concert with explicit routes, a multi-day bayram with routes
left blank, and a football fixture.

---

## 0. Rules that apply to both files

- **`.csv` or `.xlsx`, decided by the file extension.** For an `.xlsx` LF file,
  name the sheet with `--lf-sheet`; without it the active sheet is used.
- **Encoding is UTF-8, and a byte-order mark is fine.** The CSV reader opens
  with `utf-8-sig`, so Excel's "CSV UTF-8 (Comma delimited)" save on Windows
  works and `İstanbul` survives. Save as plain "CSV (Comma delimited)" in a
  Turkish locale and you will get cp1254 bytes that fail to decode — use the
  UTF-8 variant.
- **Delimiter is a comma.** Turkish-locale Excel defaults to semicolons; if
  every row lands in one column, that is what happened.
- **The header row is required.** Headers are matched case-insensitively after
  lower-casing, turning `_` into a space and collapsing runs of whitespace, so
  `Start Date`, `start_date` and `START  DATE` are the same header. Column
  *order* is free.
- **Unknown columns are ignored**, not an error. Keep working notes in the file.
- **Dates** are accepted as `YYYY-MM-DD`, `YYYYMMDD`, `DD/MM/YYYY`, `MM/DD/YYYY`,
  a real Excel date cell, or an ISO timestamp (the time is dropped). Prefer
  `YYYY-MM-DD`: `30/03/2026` and `03/30/2026` are both accepted and the first
  one that parses wins, which is an ambiguity you do not want on a day ≤ 12.
- **Blank means blank.** An empty cell and a cell of only spaces are the same.
  The meaning of blank is given per column below — it is never "zero".

---

## 1. Events file

One row per event. Ten to twenty rows is the intended size. There is no ranking
and no selection step anywhere downstream: **every row you put in this file gets
a chart and a summary line, whether the result is positive, flat or negative.**
The module returns results in events-file order and never sorts by effect size,
because ranking a fixed list by outcome turns it into a cherry-picked one.

One run writes six things into `--out`: `summary.csv`, `timeline.csv`,
`coverage.txt`, `case_studies.xlsx` (a Summary sheet plus one charted timeline
sheet per event × route), `case_studies.html` (one self-contained page) and
`charts/*.svg` (one standalone chart per event × route). `--csv-only` stops
after the first three.

### Columns

All six required columns must be **present in the header row**, even where the
cell is blank. A missing header is a hard error naming the column; a blank cell
is a documented default.

| column | header required | cell required | blank cell means |
|---|---|---|---|
| `event` | yes | yes | — (error) |
| `start_date` | yes | yes | — (error) |
| `end_date` | yes | no | one-day event: `end_date = start_date` |
| `city` | yes | no | nothing — the column is a label, not a lookup key |
| `airport` | yes | conditional | must then have explicit `routes` |
| `routes` | yes | conditional | every inbound leg into `airport` |
| `note` | no | no | nothing; carried through to the output |

**`event`** — free text; the chart title and the sheet name. Non-ASCII is fine
(`Kurban Bayramı`).

**`start_date` / `end_date`** — inclusive at both ends. A three-day bayram is
`start_date` = day 1 and `end_date` = day 3, not day 4. Blank `end_date` means a
one-day event. `end_date` before `start_date` is an error naming the row.

**`city`** — carried into the output for the reader's benefit. It is **not** used
to look up an airport. There is no city→airport resolution in this module and no
`country` column: you name the airport yourself, because with ten hand-picked
events guessing is unnecessary and being wrong is invisible.

**`airport`** — one IATA code, e.g. `IST`. Non-letters are stripped and the rest
upper-cased, so `ist` and `"IST "` both work; anything that is not exactly three
letters after cleaning is read as blank. Only one code per row — for a second
airport, write a second row.

**`routes`** — the specific directed legs to chart, separated by `;` or `,`. A
comma inside a CSV field needs the field quoted, so **use `;`**. Each token is
`ORG-DST`; `SVO-IST`, `SVO/IST`, `SVO IST` and `SVOIST` all parse (non-letters
are stripped and the result must be exactly six letters). A token that does not
parse is an error quoting the token — it is never skipped silently.

  **This is the column that answers the Kanye question.** A concert in Istanbul
  fills the *inbound* legs, so you write `SVO-IST`, not `IST-SVO`. Duplicate
  routes in one row are collapsed, keeping first-written order.

  Blank `routes` means: take **every route in the LF extract whose DST is
  `airport`** — all inbound legs into the event airport, in whatever order the
  extract yields them, sorted. That is the deliberate default, because inbound
  is the direction an event in that city fills. If you want the outbound side
  (a bayram exodus, say), name those legs explicitly.

**`airport` and `routes` cannot both be blank.** That combination is an error
naming the row; there is nothing left to point at.

### Run-level knobs (CLI flags, not columns)

These apply to every event in the file. There is no per-event override.

| flag | default | what it does |
|---|---|---|
| `--window-days` | 14 | days drawn either side of the event span |
| `--baseline-days` | 42 | how far a baseline day may sit from the day it explains |
| `--guard-days` | 3 | days either side of the event excluded from every baseline pool |
| `--csv-only` | off | skip the xlsx/html/svg renderers |

`--guard-days` is **baseline hygiene only**. It does not widen the measured
window: the reported numbers always cover the event span itself, so raising the
guard cannot dilute a one-day concert spike across its shoulder days.

### How the comparison is built

For each `(event, route)` and each day in the window, the baseline is built from
the **same route on the same weekday**, within `--baseline-days` of that day,
drawn only from days the event does not touch — the event span widened by
`--guard-days` — and never from the day itself. Fewer than **3** such days and
the baseline is reported as missing rather than computed from two observations.

The three baseline numbers come from one construction, so they reconcile:
`baseline_pax` and `baseline_capacity` are the pool means and `baseline_lf =
baseline_pax / baseline_capacity`, which is the capacity-weighted
`sum(pax)/sum(capacity)` over the pool. Three separate medians would not
compose, and `delta_pp` could then disagree with the pax and capacity moves
printed next to it.

The span-level numbers are capacity-weighted aggregates over the in-event days,
not averages of daily percentages — a 60-seat day cannot outvote a 1000-seat
one.

Same-weekday is not decoration: day-of-week alone swings LF by 4.27 pp
network-wide and 4.17 pp at IST, which is larger than most of the effects being
looked for.

Load factor is always **capacity-weighted**: `lf = sum(pax) / sum(capacity)`
over the flights in that route-day — never the mean of per-flight LFs. Every LF
number is reported beside its pax change and its capacity change, and the
verdict string is **composed** from those three so that it can never contradict
them: `<demand up|flat|down>, <capacity up|flat|cut>, <LF up|flat|down>` — for
example `demand up, capacity up, LF flat` (capacity absorbed the demand) or
`demand flat, capacity up, LF down` (LF diluted by seats, not lost demand). All
three flat reads `no movement`. The thresholds are fixed constants — 2.0 pp for
LF, 5% for pax and capacity — not fitted to anything. Four labels describe the
data rather than the movement: `no LF data` (nothing on that route in the
window), `event days not in extract` (the file stops before the event),
`no baseline` (too few clean same-weekday peers) and `no movement`.

That third number is the one that matters. THY up-gauges on days it already
expects to be busy, so a genuine demand rise can print a flat or falling load
factor. Measured: Kurban runs +10.45% capacity and −2.92 pp LF. Read as LF
alone, that event is a null result; read with capacity beside it, it is a
capacity decision.

### Worked example A — one-day Istanbul concert, explicit routes

Kanye West plays Istanbul on 2026-06-13. You think it pulled Russian fans in, so
you name the two Russian gateways explicitly and only in the inbound direction.

```csv
event,city,start_date,end_date,airport,routes,note
Kanye West — İstanbul,İstanbul,2026-06-13,,IST,SVO-IST;LED-IST,Konser; Rusya çıkışlı talep testi
```

Reading it back:

- `end_date` blank → the event is 2026-06-13 only.
- `airport` = `IST`, but because `routes` is filled, `airport` is only a label
  here; the route list is what gets charted.
- `routes` = `SVO-IST;LED-IST` → exactly two directed legs, each charted
  separately. `IST-SVO` is **not** included: a departing Moscow flight has
  nothing to do with fans arriving for a concert.
- Default `--window-days 14` → the chart covers 2026-05-30 … 2026-06-27.
- 2026-06-13 is a Saturday, so its baseline is built from the other Saturdays on
  that leg within 42 days, excluding 2026-06-10 … 2026-06-16 (the guard). The
  reported number still covers 2026-06-13 alone — the guard shapes the
  comparison set, not the measured window.
- Note the `;` inside the `note` field. It is fine — the field separator is the
  comma. A comma inside a note would need the field quoted.

### Worked example B — multi-day bayram, routes left blank

Kurban Bayramı 2026, three days. You do not want to pre-judge which routes
moved, so you name the airport and leave `routes` blank.

```csv
event,city,start_date,end_date,airport,routes,note
Kurban Bayramı,İstanbul,2026-05-27,2026-05-29,IST,,Ülke geneli; yön seçilmedi — kapasite sütununa bak
```

Reading it back:

- `end_date` = 2026-05-29 → a three-day span, days 1-3 inclusive.
- `routes` blank → every route in the LF extract with `DST = IST`. On a full
  network extract that is hundreds of legs and hundreds of timeline sheets, so
  in practice either trim the LF extract to the markets you care about or write
  the ten legs you want into `routes`.
- The guard excludes 2026-05-24 … 2026-06-01 from every baseline pool, so the
  shoulder days of the bayram do not quietly become their own comparison.
- Expect the capacity column to do the talking here. This is exactly the case
  where the LF line can be flat or negative while pax is clearly up.
- One row per airport: a nationwide bayram means writing an `AYT` row, an `ADB`
  row and so on, not leaving `airport` blank. There is no country fan-out.

---

## 2. LF extract file

The grain is **route-day**, one row per origin, destination and date. This is
the whole point: an event in Istanbul fills the inbound legs, and an airport-day
file cannot show that. Finer than route-day (per flight number, per leg) is fine
— the module sums it. Coarser is not usable.

Hand `docs/lf-extract-spec.md` to whoever produces the extract. Summarised here:

| what | required | type | accepted headers |
|---|---|---|---|
| origin | yes* | IATA, 3 letters | `org`, `org_airport`, `origin`, `origin_airport`, `dep`, `dep_airport`, `from` |
| destination | yes* | IATA, 3 letters | `dst`, `dst_airport`, `destination`, `destination_airport`, `arr`, `arr_airport`, `to` |
| route | * | `ORG-DST` in one cell | `route`, `leg`, `od`, `o_d`, `market`, `route_code` |
| flight date | yes | date | `ymd`, `flight_date`, `date`, `dep_date`, `departure_date` |
| boarded pax | yes | number | `boarded_pax`, `pax`, `passengers`, `boarded`, `boarded_passengers` |
| capacity | yes | number | `capacity`, `seats`, `seat_capacity`, `capacity_seats` |

\* Either a separate origin **and** destination column, or a single combined
route column. If both are present the separate columns win and the combined one
is only consulted when one of them fails to parse.

A `load_factor` or `lf` column, if present, is **ignored**. LF is recomputed
from pax and capacity so it can be aggregated capacity-weighted. If your extract
has only an LF column and no pax/capacity, it is not usable — go back to the
data owner.

Numbers are parsed with commas stripped as thousands separators, so `1,250`
reads as 1250. That means a European decimal comma (`0,85`) reads as 85. Pax and
capacity are counts, so this is normally harmless — but do not send a decimal
capacity with a comma in it.

### Dirty rows that really occur, and what happens to them

None of these aborts the run; all are counted in the coverage output.

| condition | handling |
|---|---|
| `capacity` ≤ 0 | dropped from every aggregate — it cannot contribute to a ratio — and counted as `skipped_bad_capacity`. A fractional capacity that rounds the whole route-day total to 0 drops the same way, so nothing can divide by zero downstream |
| `capacity` ≤ 200 | **kept**, and the day is flagged `low_capacity`. Real narrowbody and regional legs live here; they are not errors. If only *some* flights on the day were that small, the day is flagged `row_low_capacity` instead — aggregation would otherwise hide them |
| `pax` > `capacity` (LF > 1.0) | **kept**, flagged `lf>1` (or `row_lf>1` when only a constituent flight was oversold). Not clipped and not dropped. Clipping silently deletes the oversale and standby rows, which cluster on exactly the peak days a case study is about |
| `pax` = 0 with `capacity` > 0 | kept; a cancelled or ferried leg is a real zero |
| duplicate `(org, dst, date)` | summed, with the flight count carried through. Not de-duplicated by picking one |
| unparseable code, date, pax or capacity | dropped and counted as `skipped_unparseable` |
| date written `03/04/2026` | read as **3 April** (DD/MM). Ambiguous with the US ordering, so the count is reported in `coverage.txt` with a warning — a misread date moves the row to the wrong weekday, and weekday is the whole baseline. Export as `YYYY-MM-DD` |
| header arrives as `CAPACİTY` / `ORİGİN` | resolved. Excel's `UPPER()` under a Turkish locale produces the dotted capital I; headers are Turkish-folded before matching |
| a `routes` entry absent from the extract | the result is still emitted with verdict `no LF data`, and the route is named in `coverage.txt` so a typo does not read as a genuine null |

### Size

Route-day for the whole network over five years is on the order of 10⁷ rows.
The module loads the extract into memory before aggregating, so trim it to the
markets and the years you need before handing it over — the events file is ten
rows, and the legs those ten rows touch are a small slice of the network.
