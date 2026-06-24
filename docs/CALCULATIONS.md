# How everything is calculated

A precise, code-grounded reference for every computation in the pipeline. Each
section gives the exact formula, the constants, the edge cases, and a worked
example. Line references point at [`special_days/`](../special_days).

The run is a fixed, strictly sequential pipeline ([`cli.py:271-276`](../special_days/cli.py)):

```
collect → de-duplicate → drop_long_events → enrich → sort → limit → render
                                              │
                          enrich() sub-stages (fixed order):
                          1. map nearest airport
                          2. score impact (+ attendance)
                          3. compute köprü bridge range
                          4. build two per-day weight curves
```

Every row is one immutable [`SpecialDate`](../special_days/models.py) record that
accumulates fields as it flows through the stages.

---

## 1. The rolling window

[`window.py`](../special_days/window.py) — the agent always collects a **forward
window** (default: the next 12 months from today), not a fixed calendar year, so a
recurring job keeps looking ahead.

**`resolve_window(start, months)`** → `(start, end)`:
- `start = start or date.today()` (a missing `--start` defaults to today)
- `end = add_months(start, months)`

**`add_months(start, months)`** — calendar-safe, in this exact order:
1. `index = start.month - 1 + months` (month → 0-based index, then offset)
2. `year  = start.year + index // 12` (floor division borrows years correctly)
3. `month = index % 12 + 1` (always a valid 1–12)
4. `day   = min(start.day, calendar.monthrange(year, month)[1])` (clamp to the target month's last day)
5. `return date(year, month, day)`

**`overlaps(start, end, window_start, window_end)`** = `start <= window_end and end >= window_start` — the standard **inclusive** closed-interval intersection. Each source parses every candidate's dates and keeps it only if it overlaps the window.

**`is_weekend(day)`** = `day.isoweekday() >= 6` (Sat = 6, Sun = 7; locale-independent). Used by the bridge and curve stages.

- **Constants:** `DEFAULT_MONTHS = 12` ([`cli.py:46`](../special_days/cli.py)).
- **Edge cases:** day clamping (`2026-01-31 +1mo → 2026-02-28`); year wrap (`2026-12-15 +1mo → 2027-01-15`); `months=0` is a no-op; boundary touch counts as overlap (an event whose only day equals `window_end` is **kept**).
- **Worked example:** start `2026-06-23`, `months=12` → window `2026-06-23 … 2027-06-23`. Kurban `2027-06-16…19` overlaps → kept; an event ending `2026-06-22` (day before start) → dropped.

---

## 2. Collection & de-duplication

Six sources each return `list[SpecialDate]`. The two agents collect per country
(per league for football) and concatenate; [`cli.collect()`](../special_days/cli.py)
flattens everything and de-dupes.

**Order** ([`agents.py`](../special_days/agents.py)): for each agent → for each
country → holidays (`nager`) then events (`ticketmaster`, then `eventseye`), each
in its own `try/except` so one failure is logged and skipped without losing the
run; football runs once after the country loop (league-keyed); `TurkeyAgent` also
appends the bundled `diyanet` + `meb`. Insertion order = agent → source → record.

**De-duplication** = `list(dict.fromkeys(results))` ([`cli.py:208`](../special_days/cli.py)):
- `SpecialDate` is a `@dataclass(frozen=True)`, so it is **hashable**; `dict.fromkeys` keeps unique keys in **first-seen order**.
- The key is **every field except `raw`**, because `raw` is declared `field(default=None, compare=False, repr=False)` ([`models.py:48`](../special_days/models.py)) — excluded from the generated `__eq__`/`__hash__`. So two records identical in everything but their source payload collapse to one (the first survives, keeping its own `raw`).
- `compare=False` is **load-bearing**: `raw` is an unhashable `dict`; without it the frozen record could not be hashed and `dict.fromkeys` would raise. The per-day curves are stored as **tuples-of-tuples** for the same reason.

- **Why dedup exists:** the Turkey and International agents can overlap (e.g. `--agent both` with `TR` in `--countries`), producing duplicate TR rows.
- **Edge case:** same calendar day from two different `source`s (e.g. `nager` and `diyanet`) are **not** equal → kept as two distinct rows.

---

## 3. Noise filter — `drop_long_events`

[`enrich.py:68-86`](../special_days/enrich.py) — drops over-long *event* listings
(season tickets, multi-month expo passes) before any airport/scoring work is spent
on them.

- Drop a record iff `record.source in {"ticketmaster", "eventseye"}` **and** `span > max_event_span_days`, where `span = (end - start).days + 1` (inclusive) and the default is `DEFAULT_MAX_EVENT_SPAN_DAYS = 30`.
- `max_event_span_days <= 0` disables the filter entirely.
- **Football and the three holiday sources are never filtered** (football fixtures are single-day; holidays/school breaks are always kept).
- **Edge case:** a 30-day span is kept; a 31-day span is dropped.

---

## 4. Enrichment

[`enrich.py:113-150`](../special_days/enrich.py) runs three sub-stages in a
**hard-coded order**. Airport mapping must come first because **both** scorers read
the airport off the record (the heuristic adds a proximity bonus; the LLM event
prompt injects `nearest_airport` into the text).

### 4a. Nearest-airport mapping

For a record with non-null `lat`/`lon`, measure the great-circle distance to all
46 bundled Turkish airports ([`data/airports.json`](../special_days/data/airports.json)),
pick the global closest, keep it only if within the catchment radius.

**Haversine** ([`enrich.py:25-32`](../special_days/enrich.py)), with `R = 6371.0` km:

```
a = sin²(Δφ/2) + cos(φ₁)·cos(φ₂)·sin²(Δλ/2)
d = 2 · R · asin(√a)
```

where φ = latitude, λ = longitude, Δ = (point2 − point1), all in radians.

**Selection** ([`nearest_airport`](../special_days/enrich.py)): scan all airports,
keep the one with the smallest `d` (strict `<`, so on a tie the first in file order
wins); then **reject** if `d > catchment_km` (strict `>`, so exactly `150.0` km is
accepted). Default `DEFAULT_CATCHMENT_KM = 150.0`. The stored `airport_distance_km`
is rounded to 1 decimal.

- **No coordinates → no airport:** football fixtures and EventsEye expos never set `lat`/`lon`, so `nearest_airport` and `airport_distance_km` stay blank (only the Ticketmaster venue gives coordinates).
- **Worked example:** Taksim Square `(41.0370, 28.9850)` → SAW `= 31.3 km`, IST `= 32.9 km` → nearest = **SAW**, distance `31.3` (≤ 150 → accepted).

### 4b. Impact scoring

`impact` is a **0–100** score; `predicted_attendance` is an integer for event
sources only. Two interchangeable scorers (`--impact-scorer`):

#### Heuristic (default, offline, no key) — [`scoring.py:57-70`](../special_days/scoring.py)

Sum three terms, then `round`, then clamp to `[0, 100]`:

```
score  = _CATEGORY_WEIGHT.get(category, 45)            # base
score += min(20, (span_days - 1) * 3)                  # duration bonus
score += proximity_adjustment                          # airport term
impact = max(0, min(100, round(score)))
```

- **Category base weights** ([`scoring.py:21-32`](../special_days/scoring.py)): `religious_holiday 90`, `public_holiday 70`, `sports 60`, `school_holiday 55`, `concert 55`, `expo 50`, `event 50`, `arts 45`, `film 40`; unknown → `_DEFAULT_WEIGHT = 45`.
- **Duration bonus:** `+3` per day beyond the first, capped at `+20` (cap reached at span ≥ 8 days).
- **Proximity adjustment** (mutually exclusive `if/elif`): `airport_distance_km` known → `+15` if `≤ 30 km`, else `+8`; **elif** the record is geocoded (`lat` *and* `lon` present) but had no airport within catchment → `−10`; else no change.
- **No attendance** under the heuristic — always `ScoreResult(impact, None)`.
- **Worked example (expo):** `expo (50)` + 5-day span `(min(20, 4·3)=12)` + airport 12 km `(+15)` = **77**. A 9-day religious holiday: `90 + 20 + 15 = 125 → clamped to 100`.

#### LLM (`openai` / `vllm` / `azure`) — [`scoring.py:225-264`](../special_days/scoring.py)

One model call per record. The shared anchored rubric `_IMPACT_RUBRIC` is prepended
to **every** prompt so impact means the same thing across sources:

> **impact = the relative volume of *incremental Turkish Airlines ticket
> purchases* the date/event drives** — literally, how many people would buy a THY
> ticket *because of it*. Not raw event size.

Anchor bands ([`scoring.py:93-104`](../special_days/scoring.py)):

| Band | Anchor |
|---|---|
| 90–100 | Turkish national religious holiday (Kurban / Ramazan Bayramı) — peak domestic + VFR |
| 70–85 | Turkish national public holiday (esp. with a köprü) or major TR school break |
| 35–55 | marquee international event in a THY hub (UCL final, superstar concert in Istanbul) |
| 10–30 | a large event in a THY-served destination abroad drawing *some* intl/diaspora travel |
| 0–10 | a local/regional foreign event, overwhelmingly local audience, no Türkiye link |

- **Per-source prompts** ([`scoring.py:113-203`](../special_days/scoring.py)): each `source` gets a distinct builder (`nager` / `diyanet` / `meb` / `ticketmaster` / `football` / `eventseye`; unknown → ticketmaster builder). Event builders embed the **full raw payload** (`json.dumps(record.raw)`) and ask for `{"attendance", "impact"}`; holiday builders ask for `{"impact"}` only.
- **Attendance** is requested only for `_EVENT_SOURCES = {ticketmaster, football, eventseye}`; for holiday sources it is force-set to `None` after parsing, even if the model returned one. EventsEye carries no headcount, so the model **estimates** it from the event facts.
- **Reply parsing** ([`_parse`](../special_days/scoring.py)): strip a markdown fence; take the first `{…}` (greedy under `DOTALL`) and `json.loads` it → use `impact` (clamped 0–100) and `attendance` (int, `≥0` else None). If that fails, **fall back** to the *last* integer run in the raw reply, clamped 0–100 (so a trailing year like `2026` clamps to 100); if there are no digits at all → `ValueError`.
- **Gateways** ([`gateways.py`](../special_days/gateways.py)): one `ChatGateway` fronts OpenAI / vLLM / Azure — same chat-completions body, differing only in URL, model/deployment, and auth header (`Authorization: Bearer` vs Azure `api-key`). Defaults: OpenAI model `gpt-5-mini`; Azure api-version `2024-10-21`, `max_completion_tokens 16384`.

### 4c. Köprü (bridge) range

[`bridge.py`](../special_days/bridge.py) — extends a **Turkish holiday's** statutory
`[start, end]` outward to the maximal contiguous block of non-working days, because
Turks commonly take the one or two working days between the holiday and an adjacent
weekend off, forming one long break that inflates travel demand.

- Only bridged when `record.is_tr_holiday()` (`source ∈ {diyanet, meb, nager}` **and** `country == "TR"`); everything else returns its statutory range unchanged.
- `gap_budget = 1` if single-day (`start == end`) else `2` — the max **working** days that may be bridged per side.
- Each side is computed **independently** ([`_extend_backward`](../special_days/bridge.py) / [`_extend_forward`](../special_days/bridge.py)): step outward day by day, counting only **working** days (weekends are free); if a weekend is reached within `gap_budget` working days, **absorb the entire contiguous weekend run**; otherwise that side is left unchanged (strict `working > gap_budget` guard).
- **Worked example:** Ramazan Bayramı `2027-03-08…03-11` (4 days, `gap_budget=2`). Backward: `03-07` is already Sun → absorb `Sun 03-07 + Sat 03-06` → start `2027-03-06`. Forward: `Fri 03-12` (1 working day) → absorb `Sat 03-13 + Sun 03-14` → end `2027-03-14`. **Bridge = `2027-03-06 … 2027-03-14`** (a 4-day holiday becomes a 9-day block).

### 4d. Per-day weight curves

[`curve.py`](../special_days/curve.py) — a **Linear-V** weight per day, built twice:
`impact_by_day` over the statutory range and `impact_by_day_bridge` over the bridge
range. The record's `impact` is the peak.

For a range of `n` days, day at 0-based index `i`:

```
if n == 1:                      weight = peak              # single day, no V
elif is_weekend(day):           weight = peak              # weekends forced to peak (raw, not rounded)
else:
    t      = i / (n - 1)                                   # 0 … 1
    factor = 1 - (1 - trough) * (1 - |2·t - 1|)            # 1 at the ends, `trough` at the middle
    weight = round(peak * factor)
```

`trough = TROUGH_FRACTION = 0.5` (the middle dips to half the peak). Weekends are
always peak travel demand, so they override the V even at an interior trough day.

- **Worked example:** bridge `2027-03-06 … 03-14`, peak 99. Days 0,1,7,8 are weekends → forced to 99. Interior weekdays: `t=0.25 → 0.75 → 74`, `t=0.375 → 0.625 → 62`, `t=0.5 → 0.5 → 50 (round 49.5 → 50, banker's rounding)`, `0.625 → 62`, `0.75 → 74`. **Curve = `99, 99, 74, 62, 50, 62, 74, 99, 99`.**

---

## 5. Concurrency, sort & output

- **Concurrency** ([`_score_all`](../special_days/enrich.py)): scoring is the only
  I/O-bound step. It runs serially when `concurrency <= 1` or there is a single
  record; otherwise a `ThreadPoolExecutor(max_workers=concurrency)` maps the
  scorer over the records, **preserving order** and re-raising the first error.
  Default `concurrency` is `1` for the heuristic and `8` for any LLM scorer.
- **Sort** ([`models.py:54`](../special_days/models.py)): `sort_key = (start_date, event.lower())`.
- **Limit:** `--limit N` slices the first N rows after sorting.
- **Render** ([`output.py`](../special_days/output.py) / [`xlsx_writer.py`](../special_days/xlsx_writer.py)):
  ten headline columns (Event, Start, End, City, Source, Nearest airport, Impact,
  Predicted attendance, Bridge start, Bridge end); CSV/XLSX/JSON additionally carry
  the two per-day weight lists.

---

*This document is verified against the code as of the EventsEye source addition.
If a formula here disagrees with the source, the source wins — please open an issue.*
