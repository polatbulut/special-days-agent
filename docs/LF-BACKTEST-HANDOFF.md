# Handoff — LF backtest: correlating special events against historical load-factor spikes

**Status:** designed, not built. No code from this design exists yet.
**Written:** 2026-07-26
**Audience:** a session with access to the `explf` and `expectedrevenue` repos (and ideally to
THY's data platform), which this session did not have.

This document is self-contained. You should not need to reconstruct anything from the
conversation that produced it. Section 8 is the part that needs *you* specifically — it lists
what to go find in the other two repos.

---

## 1. What this project is

`specialevents-schedule` (this repo; application formerly developed in `special-days-agent`)
feeds Turkish Airlines Revenue Management's flight-occupancy
forecasting with "special dates" — holidays, school breaks, concerts, football fixtures, trade
fairs, business seminars. It collects a **rolling forward window** (default: next 12 months),
scores each date for expected demand impact, maps events to a nearest airport, and writes two
Parquet objects to Huawei OBS that two downstream repos read by path.

Pipeline ([`special_days/cli.py`](../special_days/cli.py) `main()`):

```
collect → dedup → drop_long_events → enrich → sort → limit → render
                                        │
                    enrich() sub-stages, fixed order:
                    1. map nearest airport   (enrich.py)
                    2. score impact          (scoring.py)
                    3. köprü bridge range    (bridge.py)
                    4. two per-day curves    (curve.py)
```

Outputs, written by [`special_days/sinks/obs.py`](../special_days/sinks/obs.py):

| Object | Grain | Columns |
|---|---|---|
| `obs://lakehouse-dev/special_events/special_days_raw/data.parquet` | one row per special date (span) | `RAW_COLUMNS` |
| `obs://lakehouse-dev/special_events/special_days_features/data.parquet` | day × airport | `event_date, country, airport, impact, predicted_attendance, sources, n_events, feature_timestamp, run_id` |

Consumers: **`explf`** (Expected Load Factor — the flight-occupancy target) and
**`expectedrevenue`** (ileri gelir; RandomForest over 0–120 and 120–360 day horizons). Both are
OpenShift CronJobs reading by path. See [`docs/CALCULATIONS.md`](CALCULATIONS.md) for every
formula in the pipeline, verified against the code.

---

## 2. The new request

Polat has a THY **load-factor dataset covering last year**, by route, and wants to compare the
**high-impact special events this project finds** against **spikes in those historical load
factors** — matched to specific airports, so it joins to THY's route encoding (`ISTJFK`).

His framing, verbatim in intent:

> I want to see how an event in New York affected the ISTJFK sales. Currently this is just for
> seeing the correlation between past events and the load factors — we will integrate the
> events into the expected load factor project next.

So: **this is a backtest / correlation study, not a production feature.** Integration into
`explf` is a later phase and explicitly out of scope here.

### What Polat confirmed about the LF data

Asked directly, he answered:

| Question | Answer |
|---|---|
| Grain and columns | **Flight-level, with `pax` and `capacity` as separate columns** |
| Route code direction | **Both directions present** — `ISTJFK` *and* `JFKIST` are separate rows |
| Year, and is the file local? | **2025 is fine; he does not have the file on hand** |

Consequences, all good news except the last:
- Flight-level pax+capacity means LF can be aggregated **correctly** (see §6.3).
- Both directions present means the **directional asymmetry test is available** (an event at the
  destination fills the inbound leg on arrival days and the outbound leg a few days later).
- The file not being local means **everything must be built and proven against synthetic
  fixtures**, then pointed at the real CSV on the THY box.

**Still unconfirmed** (see §9): whether the date column is departure date, whether there is a
cabin split, the actual min/max date range, and whether "last year" means calendar 2025 or a
trailing 12 months.

---

## 3. The core idea

An LF row says `ISTJFK, 2025-06-07, 0.94`. Split the route code into its two endpoint airports,
`IST` and `JFK`. An event carries a **set** of airports — a venue event carries every airport
near its coordinates (metro-grouped, so a Manhattan concert carries **both JFK and EWR**), and a
Turkish national holiday carries "every TR airport", i.e. it touches any leg with a TR endpoint.

A leg is **treated** on a date if one of its two endpoints is in some event's airport set and the
date falls inside that event's block. Compare that leg's load factor on treated dates against
**the same leg's own same-weekday median in the surrounding weeks**. The difference in percentage
points is the answer. Sweeping the day offset −14…+14 tells you whether the lift lands before or
after the event.

That is the whole chain. Everything below is about making each link not lie to you.

---

## 4. Verified findings

Everything in this section was **measured in this session**, not inferred. Each row says how, so
you can re-verify cheaply. These were expensive to establish and several of them overturn the
obvious plan.

### 4.1 For a 2025 window, this is a *holidays* study, not an *events* study

This is the single most important finding, and it partially contradicts what Polat asked for.

| Source | Past-window behaviour | Evidence |
|---|---|---|
| `nager` | **Full 2025 coverage, including both bayrams** | live `GET /api/v3/PublicHolidays/2025/TR` → 14 rows, all `global=True` |
| `diyanet` | earliest row **2026-03-19** | read [`special_days/data/diyanet_holidays.json`](../special_days/data/diyanet_holidays.json) |
| `meb` | earliest row **2025-11-10** | read [`special_days/data/meb_breaks.json`](../special_days/data/meb_breaks.json) |
| `eventseye` | **structurally zero rows for any past window** | [`eventseye.py:151`](../special_days/sources/eventseye.py:151) breaks out of paging once a page is entirely past window end — true on page 1 for a past window |
| `seminars` | **structurally zero rows for any past window** | [`seminars.py:180`](../special_days/sources/seminars.py:180), same mechanism |
| `ticketmaster` | capped at **300 chronologically-earliest events per country per run** | `page_size=100, max_pages=3, sort="date,asc"` ([`ticketmaster.py:37`](../special_days/sources/ticketmaster.py:37)), called with defaults at [`agents.py:91`](../special_days/agents.py:91) |
| `football` | historical **yes**, but sets no `lat`/`lon` → never gets an airport | [`football.py:176`](../special_days/sources/football.py:176) |

A naïve 12-month past pull would therefore cover roughly **January** of Ticketmaster and silently
treat the other eleven months as "event-free control" — which would poison the baseline in the
worst possible way (fake untreated days).

**⇒ The literal "New York event → ISTJFK" question cannot be answered honestly for 2025 until the
collector paging is fixed.** That work is step 5 in §10, not step 1.

### 4.2 The Turkish-holiday backfill is free — no data-file edits

Nager returns bayrams as **consecutive single-day rows** (`Ramazan Bayramı 1. Gün`, `2. Gün`, …).
Diyanet returns one multi-day span. That difference matters: it changes the heuristic impact
(duration bonus), the köprü gap budget (`1` if single-day else `2`, see
[`bridge.py`](../special_days/bridge.py)), and the shape of the Linear-V curve.

The fix is **not** hand-entering Diyanet rows for 2025. Merging touching `bridge_start..bridge_end`
spans reconstructs the blocks correctly. Verified by running the real `enrich()` over the real
2025 Nager feed:

```
2025-01-01              (1d)  Yılbaşı
2025-03-29 .. 04-01     (4d)  Ramazan Bayramı        ← 3 Nager rows + köprü
2025-04-23              (1d)  Ulusal Egemenlik ve Çocuk Bayramı
2025-05-01 .. 05-04     (4d)  İşçi Bayramı + köprü
2025-05-17 .. 05-19     (3d)  Atatürk'ü Anma, Gençlik ve Spor + köprü
2025-06-06 .. 06-09     (4d)  Kurban Bayramı         ← 4 Nager rows
2025-07-12 .. 07-15     (4d)  Demokrasi ve Millî Birlik + köprü
2025-08-30 .. 08-31     (2d)  Zafer Bayramı
2025-10-29              (1d)  Cumhuriyet Bayramı

→ 9 disjoint blocks, 24 treated days (6.6% of the year), 341 clean days
```

Nine well-separated blocks is a clean event-study design. Note the bayram dates match the
independently-known 2025 dates (Ramazan 30 Mar–1 Apr, Kurban 6–9 Jun), and the bridge extends
**backward** as well as forward — Kurban 2026 has `start_date=2026-05-26` but
`bridge_start=2026-05-23`, and those pre-bayram days are peak *outbound*.

MEB school breaks are **not** in Nager, so the Jan/Mar/summer 2025 breaks stay missing. That is
acceptable for slice 1 and arguably a blessing — see §6.4 on the 79-day summer block.

### 4.3 A literal `ISTJFK` filter returns zero rows today

[`enrich.nearest_airport()`](../special_days/enrich.py:35) returns the **single** globally closest
airport. Real haversine numbers over this repo's own
[`airports.json`](../special_days/data/airports.json):

| Venue | Rank 1 | Rank 2 | Consequence |
|---|---|---|---|
| Madison Square Garden | **EWR 16.3 km** | JFK 21.9 km | a Manhattan concert never matches `ISTJFK` |
| MetLife Stadium | **EWR 15.9 km** | JFK 31.5 km | same |
| Wembley | **LHR 15.4 km** | LGW 45.8, STN 50.9 | `ISTLGW` / `ISTSTN` never match |
| Kadıköy, İstanbul | **SAW 24.9 km** | IST | an Istanbul event joins to Pegasus's airport, not THY's hub |

You need a catchment **set**, not a nearest. See §6.1.

### 4.4 `impact_score` is a constant on this data

Ran the real `enrich()` over the real 2025 Nager TR feed: **all 14 rows score exactly 70**, and
**all 14 have `nearest_airport = None`**.

Why, from [`scoring.py:63`](../special_days/scoring.py:63): `public_holiday` base weight 70, span
1 day so the duration bonus is `min(20, 0) = 0`, and no coordinates so no proximity term.

**⇒ A Spearman correlation of `impact_score` vs LF residual is not weak here, it is undefined —
a correlation against a constant.** The "high-weighted events" ranking Polat asked for must come
**out of the LF data** in slice 1. That is strictly more useful for `explf` anyway: a ranking
discovered from realized load factors is a validation target, whereas the heuristic score is just
a category lookup.

Related: `impact` in `special_days_features` is `max`-aggregated per cell, and the heuristic
contains **zero** information about event size — a global-superstar stadium show and a club gig in
the same category, same span, same airport distance score identically.

### 4.5 `impact_by_day` is partly a weekend indicator

[`curve.py:47`](../special_days/curve.py:47) forces **every** Saturday and Sunday in a span to the
peak weight, and [`bridge.py`](../special_days/bridge.py) widens TR holidays specifically to absorb
adjacent weekends. LF is strongly weekend-seasonal.

**⇒ Correlating LF against the per-day curve would substantially measure "it is Saturday".** Keep
the curve out of the regressor, and stratify the baseline by weekday (§6.3).

### 4.6 Environment and mechanics

- **Python 3.14.4** locally; the Dockerfile pins `python:3.12-slim`.
- `statistics.correlation(x, y, method="ranked")` **is** Spearman and exists on 3.12+ — verified
  (returns `1.0` on a monotone-nonlinear pair). **No scipy needed.**
- `pandas`, `numpy`, `scipy` and **`pyarrow`** are **not installed** in the current env, even though
  `pyarrow` is declared in `requirements.txt`. ⇒ feed the backtest `--format json` output, not
  Parquet.
- [`window.resolve_window`](../special_days/window.py:22) takes only `months`, so
  `--start 2025-01-01 --months 12` ends **2026-01-01** and drags in six spurious 2026-01-01 New
  Year rows. Harmless — they cannot join to a 2025 LF date — so **do not** add an `--end` flag just
  for this.
- `out/` is gitignored. **`*.csv` is not**, so an LF extract at `data/lf_2025.csv` would be fully
  committable internal revenue data. Read the LF file from **outside the repo**. If you do add a
  gitignore line, use root-anchored `/data/` — a bare `data/` would also match the tracked
  `special_days/data/` reference JSON.
- **The original development repo was public on GitHub**
  (`github.com/polatbulut/special-days-agent`). This Bitbucket repo now carries the same codebase
  and still includes internal hostnames (`bigdata-dev.obs`, bucket `lakehouse-dev`) in `README.md`,
  `.env.example`, `config.py`, `sinks/obs.py` and tests. No credentials are committed. Keep it that
  way if this repo stays private.

---

## 5. Hard guardrails

1. **Never run the backtest with `--obs`.** It defaults to
   `obs://lakehouse-dev/special_events` ([`sinks/obs.py:33`](../special_days/sinks/obs.py:33)) —
   the exact objects `explf` and `expectedrevenue` read by path, overwritten in place.
2. **Do not change `RAW_COLUMNS` / `FEATURE_COLUMNS`, and do not add `SpecialDate` fields.** Those
   are a live Parquet contract for two other repos. One design draft proposed "write
   `predicted_attendance` only on the rank-1 airport" — that silently changes the semantics of a
   dataset already in production.
3. **Catchment-set logic goes in the new backtest module, not in `enrich.py`.** `nearest_airport`
   lands in `special_days_features.airport`; the backtest needs the opposite policy (recall over
   precision). Reuse the *maths* (`enrich.haversine_km`, `dataset.load_airports()`), not the policy.
4. **No live LLM or paid API calls during development.** Standing project rule. Verify with the
   heuristic scorer and mocked HTTP. (Free read-only endpoints like Nager.Date are fine — that is
   how §4.1 and §4.2 were established.)
5. **Never run anything against THY links from the dev box.** Polat develops on his Mac, `git pull`s
   on the THY server, and runs there.

---

## 6. The design

### 6.1 Event → airport catchment set

```python
CATCH_KM = 150.0   # a filter, not a tuning parameter

def airports_for(rec: SpecialDate) -> tuple[set[str], str]:
    """-> (airport set, scope) where scope is 'venue' | 'country' | 'none'."""
    if rec.lat is not None and rec.lon is not None:
        near = [(a["iata"], haversine_km(rec.lat, rec.lon, a["lat"], a["lon"]))
                for a in load_airports()]
        return metro_expand({i for i, d in near if d <= CATCH_KM}), "venue"
    if rec.country:                       # 'Nationwide (TR)' and friends
        return airports_in(rec.country), "country"
    return set(), "none"
```

**One radius, no fallback tier.** Emit every airport within 150 km *with its `distance_km`*, and
make the radius a `WHERE distance_km <= 75` in the analysis. A 75 km default with a 150 km tier-2
fallback is non-monotone — shrinking the radius wouldn't shrink the match set, defeating its own
sensitivity test.

**Metro grouping falls out of `airports.json`'s own `city` field** — verified:
`('US','New York') → [JFK, EWR]`, `('GB','London') → [LHR, LGW, STN]`,
`('TR','İstanbul') → [IST, SAW]`, `('FR','Paris') → [CDG, ORY]`. Forty distinct `(country, city)`
keys across 46 airports.

```python
@lru_cache(1)
def _metro() -> dict[str, tuple[str, ...]]:
    m = defaultdict(list)
    for a in load_airports():
        m[(a["country"], a["city"])].append(a["iata"])
    return {iata: tuple(v) for v in m.values() for iata in v}

def metro_expand(iatas):
    return {j for i in iatas for j in _metro().get(i, (i,))}
```

Known wart: `Muğla` maps to both DLM and BJV, 157 km apart, so metro-expanding a Bodrum event
reaches Dalaman. Guard with `distance_km <= 150` on expanded members, or accept it — no THY LF row
hinges on it.

**City → airport gazetteer for coord-less sources: cut from the MVP.** ~85 of the entries a full
gazetteer would need are for EventsEye/Seminars cities that *cannot appear in a past window* (§4.1).
Football is the only coord-less source with real history. When it does land, **generate** the
gazetteer from the distinct `(country, city)` strings actually observed, frequency-ordered — do not
hand-write it. Two gotchas worth preserving for that day:
- The Turkish pre-map must run **before** NFKD. Verified: `'İstanbul'.lower()` yields `'i̇stanbul'`
  (8 chars → 9), and NFKD+lower without a pre-map turns `Şanlıurfa` into `sanl urfa`.
- [`football._country_code`](../special_days/sources/football.py:180) returns `'INT'` for UEFA
  fixtures, so a gazetteer keyed on ISO-2 would silently drop every Champions League away leg.

### 6.2 Airport → route, and direction

```python
def parse_route(code: str) -> tuple[str, str] | None:
    c = code.strip().upper().replace("-", "").replace("/", "").replace(" ", "")
    return (c[:3], c[3:]) if len(c) == 6 and c.isalpha() else None
```

**Do not require endpoints to be in `airports.json`** — `ISTBKK` must parse or you reject most of
THY's network. Membership is what the *join* filters on. Report the unmatched-endpoint count but
**do not gate on it** (a "halt above 10% unmatched" rule fires immediately, since 46 airports cannot
express THY's network).

Two booleans rather than a three-value taxonomy: `event_at_org = org in event_airports`,
`event_at_dst = dst in event_airports`.

**Dedupe to one row per `(event_block, route, flight_date)`.** Otherwise a TR national holiday
matches a domestic leg like `ISTADB` on *both* endpoints and every domestic route gets double weight
in every mean — precisely where the bayram signal lives.

Direction: one `SELECT DISTINCT route` on the LF file. Polat says both orientations are present, so
report the offset curve separately for TR-origin and TR-destination legs. Verify rather than trust —
if only one orientation actually appears, say in the output that inbound and outbound are not
separable and stop there.

**Do not pre-register a signed window per direction.** Treating `dest_country == TR` as "returning"
with a window of `[-1, +2]` is backwards for diaspora VFR: `DUSIST` / `FRAIST` peak *before* bayram,
because people fly home *for* the holiday. A pre-registered window misaligned by the length of the
block, on exactly the highest-signal routes, is a false-null machine. Let the offset curve answer it.

### 6.3 The LF baseline and the spike definition

Route-day grain, **capacity-weighted**:

```python
lf = sum(pax) / sum(capacity)          # per (route, flight_date)
```

Never the mean of per-flight LFs. THY up-gauges on high-demand days, so
`mean(lf) = weighted_lf + Cov(cap, lf)/mean(cap)` with `Cov > 0` — the plain mean **understates** LF
precisely on the days an event would show.

Then per `(route, date)`:

```
y        = log((pax + 0.5) / (cap - pax + 0.5))          # empirical logit; handles lf == 1.0
b(r,d)   = median{ y(r,d') : weekday(d')==weekday(d), |d'-d| <= 42, d' not in EXCLUDED }
resid    = y - b
lf_base  = 1 / (1 + exp(-b))                             # baseline back on the LF scale
resid_pp = 100 * (lf - lf_base)                          # what an RM analyst reads
scale    = 1.4826 * median|resid - median(resid)|        # per route, clean days only
z        = resid / scale
```

`EXCLUDED` = every treated day ± 2, per route. **Same-weekday stratification is non-negotiable**,
for the reason in §4.5.

**Require ≥ 2 clean same-weekday observations on each side of the target. If not, DROP the row and
count it. Never fall back to an annual median.** This is the single most important rule in the
design. A fallback variant was simulated on a purely seasonal, **completely event-free** series and
produced a phantom **+13.07 pp "lift"** with a headline Spearman of **−0.60** — because a one-sided
or annual baseline measures summer-vs-annual, not event-vs-neighbourhood. Recording the fallback in
a `method` column just annotates a fabricated number.

Verified feasible: with `guard=2, W=42, min_side=2` there are **zero drops across all 24 treated
days of 2025**. (`guard=3, W=42` drops 2025-04-23, because 23 Nisan and 1 Mayıs are 8 days apart.)
So the parameters are measured, not guessed.

- **Spike:** `z >= 2.0`, secondary. The **headline is the continuous `resid_pp`** — with 9 blocks a
  binary flag just adds a threshold and a second inference problem.
- **Saturation:** one boolean, `high_base = lf_base >= 0.92`, cut on the **baseline**, never on
  observed LF. Bucketing on the observed value conditions on the outcome, so any day that actually
  spiked lands in "saturated" and deletes itself. Report `headroom = 1 - lf_base` and the count of
  treated route-days with baseline above 0.95. On a route at 0.95 baseline the maximum possible
  residual is +5 pp; a null there is uninformative about demand. The empirical logit softens this
  (a 0.93→0.96 move gets weight comparable to 0.60→0.72) but does not remove it.

### 6.4 Cap event span at 14 days

[`drop_long_events`](../special_days/enrich.py:68) only filters `{ticketmaster, eventseye}`, so
MEB's `Yaz tatili` — **79 days at impact 75** — survives. A ±42-day local baseline is mathematically
*inside* an 80-day block, so no clean baseline exists and the "control" days are treatment. Summer
school break is a seasonality question, not a spike question. (For a 2025 window it doesn't arise,
since `meb_breaks.json` starts 2025-11-10.)

### 6.5 Blocks, lead/lag, and inference

**The treatment unit is a merged block** — not a record, not a day. Use
`bridge_start..bridge_end` (bridges extend backward too, §4.2), then merge blocks that touch or
overlap:

```python
def blocks(records, *, max_span=14):
    spans = sorted((r.bridge_start or r.start_date, r.bridge_end or r.end_date, r)
                   for r in records
                   if (r.end_date - r.start_date).days + 1 <= max_span)
    out = []
    for s, e, r in spans:
        if out and s <= out[-1].end + timedelta(days=1):
            out[-1] = out[-1].extend(e, r)          # same block
        else:
            out.append(Block(s, e, [r]))
    return out
```

This also removes the `n_events` double-count: Nager and Diyanet can't both fire, and MEB's 2026
`İkinci ara tatili` (2026-03-16…20) overlapping Ramazan (2026-03-19…22) becomes **one** block rather
than two labels for one set of days.

- **Offset:** `tau = (flight_date - block.start).days`, swept **−14 … +14**, plotted as mean
  `resid_pp` with a permutation band, one panel per direction. Read the lead/lag off the plot.
- **Headline:** block-level mean `resid_pp` over `[block.start − 2, block.end + 2]`, reported **per
  block — all 9 rows** — plus one pooled number. **Not** an argmax over 29 offsets (29 correlated
  tests with no null distribution will confidently "find" a return-leg lag in pure noise). **Not** a
  Spearman against `impact_score` (§4.4). The per-block table *is* the "high-weighted events"
  ranking Polat asked for, discovered from the LF data.
- **Inference:** permutation, clustering on the **block**, not the route. One block hits every
  TR-touching leg on the same dates, so routes are not independent — route-clustered intervals here
  are *anti*-conservative and would turn one well-timed bayram into a headline. Shuffle each block's
  start date within its route's calendar year preserving weekday and length (multiples of 7), 2000
  draws, `random.Random(seed)`. Print `n_blocks = 9` on the face of every number.

---

## 7. Making the result trustworthy

- **`--placebo-shift-days 182`** — shift every block, re-run. If the placebo also lifts, the number
  is seasonality, not events. Three lines, and it is the direct guard against the +13 pp artefact
  above. Add ±364 if free. **Multiples of 7 only** — a non-multiple shift breaks weekday alignment
  and is not a fair null.
- **Skip the route-swap placebo.** Essentially every THY leg touches TR, so for the holiday arm
  there is no untreated route to swap to. Say that in the output rather than shipping an invalid
  control.
- **Capacity response is the confounder that matters most.** LF = pax/capacity, and RM up-gauges and
  adds frequency for known bayram dates. **Report `Δcap` in-window vs baseline on every block row.**
  Flat LF with `Δpax > 0` *and* `Δcap > 0` means the event drove demand and RM already absorbed it —
  that is a finding, not an absence. Write it in those words.
- **Weekend confound** is the most likely route to a false positive on Turkish holiday data. The
  same-weekday baseline plus the planted-null weekend test (§8 of the build list) is the defence.
- **Reporting a null honestly.** Template:
  > 9 blocks, 24 treated days, 341 clean days, N legs. Kurban Bayramı: TR-origin legs +X.X pp
  > [placebo −0.2, +0.4], Δcap +Y%. Pooled across 9 blocks: +Z pp, permutation p = P. Measured on
  > flown load factor by departure date — this says nothing about when the booking happened.

  If pooled is flat, the two honest readings are "underpowered at 9 blocks" and "capacity absorbed
  it, see Δcap" — **never** "events don't matter". And say plainly that departure-date LF cannot
  speak to booking-curve timing; a DCP/snapshot study is a separate exercise (see §8.6).

---

## 8. What I need from you — the `explf` / `expectedrevenue` side

This is the reason for the handoff. This session had **no access** to the other two repos or to the
data platform. Everything below is a lookup that would change or de-risk the design. Roughly in
value order.

### 8.1 Where the LF data actually lives, and its real schema — *highest value*

Polat said flight-level with `pax` + `capacity`, both route directions, 2025. Confirm against the
real thing, because §6.3 depends on it:

- The table/schema/path `explf` reads to build its LF target, and the exact query.
- Column names for pax, capacity/seats, date, route, flight number, cabin, carrier.
- **Is the date column departure date?** The design assumes so and says so in the output.
- **Is there a cabin split?** If rows are per cabin, aggregation must sum pax and capacity across
  cabins *before* computing LF, not average cabin LFs.
- **Is there a carrier / operating-carrier column?** Default is `TK` only if such a column exists,
  else everything, stated in the output.
- **Actual min/max date.** "Last year" as of 2026-07 could mean calendar 2025 or trailing
  2025-08→2026-07. The 9-block table in §4.2 is for calendar 2025 and **changes** if the window
  moves.
- Whether codeshare / operated-by rows would double-count pax.

### 8.2 `explf`'s hard-coded route/date exclusion lists — *cheapest high-signal win*

Memory of this project records that `explf` **carries hard-coded route/date exclusion lists**. Those
lists are a **human-curated, RM-validated answer to "which dates are special"**. Extract them.

Two uses, both better than the LF correlation as a *first* test:
1. **Validate this repository against them directly.** If the agent's blocks don't recover the
   dates RM already hand-excluded, the agent is wrong in a way no LF correlation will reveal
   cleanly. This is a same-day check with no statistics involved.
2. **They are the incumbent this project must beat.** "Replaces two hand-maintained lists" is a far
   stronger business case than a correlation coefficient.

### 8.3 `expectedrevenue`'s `ileri_peak.txt` — same argument

Memory records that `expectedrevenue` **merges ad-hoc peak flags from `ileri_peak.txt` on S3**.
Another human-curated event calendar. Pull it, diff it against the agent's 2025 blocks, and report
precision/recall of the agent against the human list. Cheap, legible, and it speaks RM's vocabulary.

### 8.4 `explf`'s `modelmonitoringdata` realized-error tables — *possibly a better target than LF*

Memory records that `explf` writes `modelmonitoringdata` realized-error tables. Consider this
seriously:

> The dates where `explf`'s **forecast error** spikes are exactly the dates where an event feature
> would add value. Correlating events against **model error** sidesteps both of the design's worst
> problems at once — LF saturation (§6.3) and THY's capacity response (§7) — because the error is
> already net of whatever capacity RM added and whatever the model already knew.

If those tables exist at daily × route grain, **run this arm too, and quite possibly first.** A
result of the form "explf's error is +X pp on the agent's high-impact blocks" is a directly
actionable case for integration, whereas "LF is +X pp on holidays" is something RM already knows.

### 8.5 Capacity / schedule data for the Δcap control

§7 needs in-window vs baseline capacity per block. If `capacity` is in the LF extract, done. If not,
find the schedule/ASK table. Also worth knowing: whether a route **gained or lost frequency**
mid-2025, which changes LF mechanically and is a confounder the residual won't catch.

### 8.6 Is there a booking-curve / DCP snapshot table?

Departure-date LF **cannot** speak to booking timing, and events drive bookings weeks ahead. If
`explf` or `expectedrevenue` has DCP snapshots (bookings-on-hand by days-before-departure), then the
much stronger study is "does the *booking curve* steepen ahead of an event" — which is also what an
event feature would actually feed. Note `expectedrevenue` runs 0–120 and 120–360 day horizons, which
strongly suggests such data exists. Flag whether it does; don't build it here.

### 8.7 Route encoding convention

Confirm `explf` / `expectedrevenue` use the same 6-char `ISTJFK` concat, and whether they work at
**leg** or **O&D** level. If they use O&D with connections, a New York event affects `ISTJFK`
*and* every behind/beyond itinerary through it, and the join in §6.2 is a simplification worth
stating explicitly in the output.

### 8.8 Does RM have an in-house LF "spike" definition?

A pp threshold, or a percentile against a specific baseline. If one exists, adopt it as the primary
flag so the output speaks the vocabulary the room already uses, and keep `z >= 2.0` secondary. Ask
Polat or look for it in `explf`.

---

## 9. Open questions for Polat

These were asked and are still outstanding:

1. **Paste the LF header, two sample rows, and min/max date.** Specifically: is the date departure
   date; is there a cabin split; and does "last year" mean calendar 2025 or trailing 12 months.
2. **Does RM already have an in-house LF spike definition?** (§8.8)
3. **May a single free Ticketmaster Discovery GET with a past date window be made?** Keyed but free
   and read-only — no LLM, no charge. It is the one fact that decides whether the New-York-event arm
   exists at all or whether this study is honestly "TR holidays only". If the no-live-API rule is to
   stay absolute, step 5 in §10 becomes "probe manually before building".

**Defaults being taken rather than asked about:** window = whatever the LF file covers; carrier = `TK`
only if such a column exists, else everything (stated in output); routes = the full set present in
the file, per-block table reported for the top ~20 by volume; impact source = the heuristic, with the
block ranking coming from the LF data rather than `impact_score`.

---

## 10. Sequenced plan

1. **LF recon — ~1 hour. Nothing else starts before it.** Print the header, two sample rows,
   min/max date, distinct route count, whether both `ISTJFK` and `JFKIST` appear, whether
   `pax`/`capacity` exist. Then run the collect command below for the file's *actual* window and
   confirm the block table. Everything downstream — the window, the grain, whether the empirical
   logit and the Δcap control are even possible — is contingent on this one table. Do not skip it:
   three of the five design drafts specified concrete work against an *assumed* calendar-2025 window.

2. **Slice 1 — ~1 day. The smallest thing that yields a real number.**
   `special_days/backtest.py` with `load_lf` → capacity-weighted route-day → `blocks` (Nager TR
   only, bridge-merged) → strict same-weekday baseline (`guard=2, W=42, min_side=2`,
   drop-don't-fallback) → `blocks.csv` + printed summary + the `--placebo-shift-days 182` run.
   **Deliverable: 9 rows of mean LF residual in percentage points, split TR-origin vs
   TR-destination, with a placebo column beside every one.** Needs no coordinates, no API keys, no
   scraping, no edits to any bundled JSON.

3. **Offset curve + case studies — ~half a day.** τ ∈ −14…+14 per direction, plus raw LF series for
   3–6 known cases (Kurban on `ISTFRA`, `ISTDUS`, `ISTBER`, `ISTESB`) with the baseline line and the
   block shaded. If the effect isn't visible by eye there, no permutation test will find it — and
   this is the artefact that convinces an RM audience.

4. **Δcap and saturation columns — small.** Converts a possible null from "events don't matter" into
   "RM already absorbed it".

5. **Probe Ticketmaster, then decide — medium.** One GET with a past `startDateTime`/`endDateTime`;
   count rows, print min/max event date. If it serves real past events: month-chunk the collection
   (the 300/country date-ascending cap makes a single 12-month call useless), persist
   `sales.public.startDateTime` and `dates.status` from `raw` so cancelled events can be dropped and
   "was this known during the booking window" is answerable, and add the metro-level venue arm.
   **Gate: if fewer than ~30 treated leg-days per metro after JFK+EWR grouping, write "underpowered"
   and stop.** This is the arm that answers the literal New-York→`ISTJFK` question, and it is step 5
   because it may not exist.

6. **Deferred, explicitly.** Football city→IATA gazetteer (generated, not hand-written). The
   box-vs-curve-vs-empirical exposure comparison — testing whether Linear-V, weekend-forced-to-peak
   and the köprü rule are actually *right*. That last one is the most valuable thing here for
   `explf`, and it needs a populated event feed first. Also: start weekly `--obs` snapshots to a
   **scratch** location, since a point-in-time archive is the only way to ever validate
   Ticketmaster/EventsEye/Seminars against LF — a one-line cron note, not part of this deliverable.

**In the first slice:** TR national holidays from Nager, 9 merged blocks, TR-touching legs,
capacity-weighted route-day LF, same-weekday drop-don't-fallback baseline, per-block residual in pp,
one placebo, one CSV, one printed summary, **zero** new dependencies, **zero** changes outside
`special_days/backtest.py` + `tests/test_backtest.py`.

**Deferred out of the first slice:** the venue/Ticketmaster arm and therefore the literal `ISTJFK`
question; the city gazetteer; any LLM scoring pass; Diyanet/MEB JSON backfill (unnecessary — Nager
covers it); XLSX output; an `--end` flag; correlation against `impact_score`;
precision/recall tables; power/MDE machinery; the curve-vs-box exposure comparison.

---

## 11. What to build, concretely

**Files.**
- `special_days/backtest.py` — **one module**, ~300 lines. Not a subpackage, not nine modules. The
  existing package is ~3,400 lines across 17 modules; a first-pass correlation study does not get
  its own ten-file architecture.
- `tests/test_backtest.py` — `unittest.TestCase` classes. The Makefile runs
  `python -m unittest discover -s tests` and every existing test file uses that style.
- Artefacts to `out/backtest/` (already gitignored).

**Dependencies: none.** `requirements.txt` untouched. `statistics.median` covers the baseline,
`statistics.correlation(method="ranked")` covers Spearman, `random.Random(seed)` covers the
permutation test, `csv` reads the LF file. ~110k route-days is nothing for plain dicts. Adding scipy
for one coefficient, or pandas+numpy+matplotlib for a 9-row table, is the worst
dependency-per-line trade available.

**CLI.**

```bash
# 1) the event set — no new flags, and NEVER --obs
python -m special_days --agent turkey --source holidays \
    --start 2025-01-01 --months 12 --format json -o out/events_2025.json

# 2) the study
python -m special_days.backtest \
    --lf ~/lf/lf_2025.csv --events out/events_2025.json \
    --out out/backtest --placebo-shift-days 182
```

Six flags total: `--lf`, `--events`, `--out`, `--placebo-shift-days`, `--max-span-days` (14),
`--radius-km` (150). Everything else is a module constant. Nobody tunes 26 knobs on a first look at
their own data.

**Output artefacts** (four, in `out/backtest/`):
- `blocks.csv` — 9 rows × (block dates, contents, direction, n_legs, mean `resid_pp`, permutation
  interval, Δcap%, n above 0.95 baseline). **The deliverable.**
- `offsets.csv` — τ ∈ −14…+14 × direction × mean `resid_pp`.
- `pairs.csv` — the (block, route, date) drill-down, so an analyst can hand-check a single row.
- `coverage.txt` — LF date range, event date range, overlap, distinct routes, routes whose reverse
  also appears, unmatched endpoints, treated/clean day counts, rows dropped for thin baseline.

**The tests that matter** (one file, five cases):

1. **Planted signal.** Synthetic LF for 4 routes over 2025: base 0.75, +6 pp on Sat/Sun,
   `gauss(0, 0.02)` noise, **+12 pp injected on the 9 real 2025 block windows**. Assert: every block
   yields ≥1 leg; block mean `resid_pp > +8`; permutation p < 0.05; the offset curve peaks **inside**
   the block, not at ±14.
2. **Planted null.** Same routes, same seed, **no injection**. Assert `|block mean| < 2 pp` for all
   9, p > 0.10 — **and that rows are still produced**, so a null can never be confused with a broken
   join. This pair is what tells you a null is a real null and not a bug.
3. **Weekend confound.** No injection, every block forced onto Sat/Sun. Assert no positive lift.
   Proves the same-weekday baseline earns its keep.
4. **Seasonal leak.** Event-free series with a ±10 pp annual sine. Assert every block mean is within
   ±2 pp and the placebo agrees. This is the regression test for the fallback-baseline artefact — it
   must fail if anyone reintroduces a fallback.
5. **Capacity weighting + metro.** A 300-seat/90% flight and a 60-seat/20% flight on one route-day
   give `lf = 0.783`, not the naive mean 0.55. And `airports_for` on Madison Square Garden
   coordinates returns a set containing **both EWR and JFK**, even though rank 1 is EWR at 16.3 km.

No live API calls, no LLM calls, no filesystem where an injected-rows seam will do.

---

## 12. Provenance

The design was produced by a 5-dimension fan-out (historical backfill, airport/route mapping, LF
baseline & spikes, alignment & validation, deliverable & implementation), each dimension
adversarially critiqued by an independent reviewer, then synthesised. 11 agents, ~1.13M tokens.

Every number in §4 was then **independently re-verified** in the main session before being written
here: the Nager 2025 GET, the 9-block merge, the constant `impact_score = 70`, the MSG/MetLife/
Wembley haversine distances, the paging-exit code paths in `eventseye.py` / `seminars.py`, the
Ticketmaster cap at `agents.py:91`, the installed-package set, and
`statistics.correlation(method="ranked")`.

Claims that remain **unverified** and are flagged as such in-line: whether the Ticketmaster
Discovery API serves past events at all (§9.3), and whether the API-Football key/plan grants 2025
fixtures.
