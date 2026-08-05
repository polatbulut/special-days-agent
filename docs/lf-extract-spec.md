# Load-factor extract — request spec

**For:** whoever owns the historical flight/booking extract
**From:** Revenue Management — Demand & Occupancy Forecasting (Polat Bulut)
**Purpose:** measure whether specific special days (concerts, bayrams, derbies)
moved load factor on specific routes. One file, one delivery, no ongoing feed.

---

## 1. The grain

**One row per origin, destination and flight date.**

| column | type | notes |
|---|---|---|
| `ORG` | char(3) | IATA code of the departure airport |
| `DST` | char(3) | IATA code of the arrival airport |
| `FLIGHT_DATE` | date | the operating date of the flight, `YYYY-MM-DD` |
| `BOARDED_PAX` | integer | passengers actually flown on that route that day |
| `CAPACITY` | integer | seats offered on that route that day |

Flight-number level or leg level is also fine — we will aggregate it ourselves.
What we cannot use is anything already aggregated **above** this grain: an
airport-day file, a monthly file, or a file where the two directions have been
combined.

CSV or Parquet. UTF-8. Comma-delimited if CSV.

---

## 2. The window

**2021-01-01 to today.**

More years is strictly better and we will take everything you can give. The
analysis compares an event day against other same-weekday days around it, so
every extra year adds independent instances of the same annual event (four
Kurban Bayramıs are worth much more than one). 2020 is welcome too even though
it is a pandemic year — we would rather have it and exclude it ourselves than
not have it.

---

## 3. Two questions we need answered in writing

These change what the numbers mean, and we cannot infer either from the file.

### Q1. Is `BOARDED_PAX` departures-only?

That is: for the row `ORG=IST, DST=FRA, FLIGHT_DATE=2026-06-13`, is
`BOARDED_PAX` the count of people who **boarded at IST and flew to FRA** on that
date? Or does it include passengers counted at some other point — connecting
traffic attributed to a different segment, arriving passengers, or a
whole-journey origin-destination figure?

Why it matters: we are testing whether an event in Istanbul pulled people *in*.
If the pax figure on `SVO-IST` is anything other than "people who got on a plane
at Sheremetyevo and got off at Istanbul", the test measures something else.

### Q2. Are both `ISTFRA` and `FRAIST` present as separate rows?

We need each direction as its own row. An event fills the inbound leg and leaves
the outbound leg alone — that asymmetry *is* the finding. If the extract holds
only one direction per city pair, or sorts the two codes alphabetically into a
single undirected pair, the analysis cannot run and we need to know before you
build it, not after.

Please state explicitly which of these the file is:

- [ ] both directions, as separate rows (what we want)
- [ ] one row per city pair, direction collapsed
- [ ] one direction only

---

## 4. Please do not send a load-factor column instead of pax and capacity

`BOARDED_PAX` and `CAPACITY` must arrive as **two separate numeric columns**.

A pre-computed `LOAD_FACTOR` column is not a substitute, and we will ignore it
if present. The reason is arithmetic: to get the load factor of a group of
flights you need

```
LF = sum(BOARDED_PAX) / sum(CAPACITY)
```

which weights each flight by its size. Averaging per-flight LFs instead gives a
different and wrong number — it lets a 70-seat regional jet count the same as a
350-seat widebody. Once the two columns are collapsed into a ratio, that
weighting is unrecoverable.

Keeping capacity separate is also the only way to read the result at all. THY
up-gauges on days it already expects to be busy, so a genuine demand rise can
show up as a *flat or falling* load factor while pax and capacity both climb. We
have measured this: Kurban Bayramı runs +10.45% capacity and prints −2.92 pp LF.
Without the capacity column that event looks like a null result instead of a
capacity decision.

---

## 5. What we do not need

- No revenue, fare, yield or currency fields.
- No passenger-level or PNR-level data, no names, no booking references.
- No cabin split — a single total pax and total capacity is enough.
- No forward bookings. This is history only.

---

## 6. Delivery

One file (or one file per year) on any internal share. If it is easier to expose
it as a Hive/Parquet table on the lakehouse, that works too — send the path and
the column names and we will read it there.

Questions to Polat Bulut, Revenue Management — Demand & Occupancy Forecasting.
