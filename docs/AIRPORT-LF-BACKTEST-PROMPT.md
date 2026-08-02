# Prompt: rewrite the LF backtest as a simpler airport-specific correlation workflow

Use this prompt when you want a coding agent to build or refine the airport-LF correlation workflow without touching the current `special_days/backtest.py` implementation.

## Prompt

I want you to build a simpler LF backtest that proves whether special events correlate with load-factor increases on the same airport and the same day.

Inputs:
- Use the uploaded LF Excel workbook.
- Use the uploaded `special_days_enriched` Excel workbook.
- Treat the enriched workbook as the authoritative airport-event mapping source.

Core business requirement:
- This analysis must be airport-specific.
- The join grain must be `AIRPORT + date` only.
- Example: LF for `FRA` must only be compared with events that were mapped to `FRA` on that same date.
- Do not collapse everything into IST.
- Include non-IST airports in the summary and in the proof.
- Support multiple destinations in one run.
- Put each destination timeline on a separate sheet.
- Make sure `IST` is shown as an explicit benchmark even when the main proof emphasis is on non-IST airports.

Enrichment requirement:
- Make sure enrichment is enabled.
- The workflow must require the enriched workbook to contain the `event_day_airport` sheet.
- If that sheet is missing, stop with a clear error saying the workbook is not enriched correctly.
- Do not silently fall back to raw events.

What I want the code to do:
- Read LF rows from the LF workbook at airport-day grain.
- Read airport-day event rows from the enriched workbook.
- Match them strictly on `AIRPORT` and date.
- Aggregate event weights per airport-day without using a high-impact threshold.
- Use general event impact weights directly. Do not filter to only high-impact events.
- For each airport-day, compute at least:
  - `event_weight_sum`
  - `event_weight_max`
  - `event_count`
  - `event_flag`
  - `event_names`
- Join those features to LF on the same airport-day.

What I want as proof of correlation:
- Give me airport-specific statistics, not only overall statistics.
- For each airport, calculate:
  - average LF on event days
  - average LF on non-event days
  - uplift in LF percentage points
  - Pearson correlation between LF and event-weight intensity
  - Spearman correlation between LF and event-weight intensity
  - a significance-style check such as a t-statistic and p-value for event-day uplift or correlation
- The results must clearly show both positive and negative airport-specific cases where they exist.
- Non-IST airports like `FRA`, `CGN`, `CDG`, `AMS`, `ISE`, `IST`, etc. should be easy to inspect in the output.
- Add period-level proof for `IST` so Bayram windows and summer periods can be reviewed directly.
- Show whether LF in `IST` is higher during Bayram periods and during summer-related periods than in the surrounding non-period days.

What I want visually:
- Produce timeline graphs for multiple destinations.
- X-axis must be dates.
- Y-axis must include LF.
- Plot the event signal on the same date axis so I can visually inspect whether LF rises when events happen.
- Put the special-event signal on the graph using the matched airport-day event weights.
- Include the event names in the output sheet so I can inspect which events caused the signal.
- Do not stop at Excel charts only. Also export graph files outside Excel, for example SVG charts and an HTML dashboard that groups the selected destinations.
- Visually highlight Bayram periods and summer periods on the graphs when they are present.

What I want the agent to reason about:
- Explain why proving the effect on non-IST airports is important.
- The reasoning should say that non-IST airports are a cleaner falsification test than IST alone because IST is a large hub with many unrelated demand drivers.
- The reasoning should also say that repeated airport-specific signal at destinations like `FRA`, `CGN`, `CDG`, `AMS`, etc. is stronger evidence that special events really affect LF.
- The reasoning should also explain why IST should still be shown: it is the hub benchmark where Bayram and summer seasonality should be visible even if it is not the cleanest causal proof slice.
- Also mention the caveat that airport-day LF is strong screening evidence, but route-direction LF would be an even stricter causal test.

Implementation constraints:
- Do not edit `special_days/backtest.py`.
- Create a new simpler module instead.
- Keep the implementation dependency-light. Prefer the standard library and `openpyxl`.
- Keep the code easy to read and easy to audit.
- Use explicit workbook sheet names and explicit required-column validation.
- Do not add production OBS writes or change any existing production data contracts.

Expected deliverables:
- A new standalone Python module for the simpler airport-specific LF backtest.
- A focused test file that proves the airport-specific join and correlation behavior on synthetic data.
- A workbook output containing:
  - methodology notes
  - overall summary
  - per-airport summary
  - graph index
  - focus-period summary
  - focus-period windows
  - monthly seasonality summary
  - joined airport-day data
  - one timeline sheet per selected destination with a chart
- External graph outputs, not only workbook charts.

Definition of done:
- The code uses the enriched workbook correctly.
- The join is airport-specific.
- Non-IST airports are included.
- The output makes it obvious whether event days tend to align with higher LF at the same airport.
- The current backtest file remains untouched.