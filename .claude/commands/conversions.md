Run a pipeline conversion and efficiency analysis for Hyperline.

## Steps

1. Sync Attio deals first (refresh snapshot):
   ```
   cd /Users/lucas/business/Analysis/sync && .venv/bin/python attio_sync.py --no-notes
   ```

2. Run the prep script:
   ```
   cd /Users/lucas/business/Analysis/sync && .venv/bin/python prepare_conversions.py
   ```
   For a longer window: `prepare_conversions.py --months 12` or `--all`

3. Read `/Users/lucas/business/Analysis/data/conversions_context.json`

4. Produce the full report using the rules below.

---

## How to read the data

- `overview` — totals: won, lost, disqualified, open, win rate, values
- `funnel[]` — stage-by-stage counts with conversion from previous stage
- `time_in_stage` — median/avg/p25/p75 days spent in each stage
- `sales_cycle` — lead-to-won duration stats
- `by_owner` — per-rep win/loss/rate/cycle breakdown
- `monthly_cohorts` — deals created each month with outcomes
- `lost_reasons` — why deals were lost (from Attio multiselect + free text)
- `disqualification_reasons` — why deals were disqualified
- `bottlenecks` — auto-detected: stages with long dwell time or high drop-off

---

## Analysis framework

### 1. Summary block
```
## Pipeline Conversion — [period]
[N] deals | Win rate: [X]% ([N] won / [N] closed)
Median sales cycle: [N] days | Won value: €[N]
Pipeline: €[N] ([N] open deals)
```

### 2. Conversion funnel
```
| Stage | Reached | Conv. from prev | Value |
|---|---|---|---|
| Inbound Lead | [N] | — | €[N] |
| Discovery | [N] | [X]% | €[N] |
| Technical Validation | [N] | [X]% | €[N] |
| Negotiations | [N] | [X]% | €[N] |
| Contract Sent | [N] | [X]% | €[N] |
| Won | [N] | [X]% | €[N] |
```

Highlight the steepest drop-off point. Calculate overall lead-to-won conversion.

### 3. Stage velocity
For each stage:
- Median and average time spent
- P25/P75 spread (wide spread = inconsistent process)
- Compare to healthy benchmarks:
  - Lead → Discovery: <7 days
  - Discovery → Tech Val: <14 days
  - Tech Val → Negotiations: <21 days
  - Negotiations → Won: <30 days

Flag stages where median exceeds 2x the benchmark.

### 4. Bottleneck analysis
From `bottlenecks[]` and your own analysis:
- Which stage loses the most deals?
- Which stage takes the longest?
- Where is value leaking? (high-value deals dropping off)
- Are there stage-specific patterns? (e.g., tech val kills outbound deals but not inbound)

### 5. Lost deal analysis
From `lost_reasons`:
- Top reasons ranked by frequency
- For each top reason: representative deals, common patterns
- Actionable vs non-actionable losses:
  - Actionable: product gap, pricing, competitor loss → specific improvement possible
  - Non-actionable: timing, org change, ghosted → qualification improvement

### 6. Monthly cohort analysis
Table showing deal cohorts by creation month:
```
| Month | Created | Won | Lost | DQ | Open | Win Rate | Value Won |
|---|---|---|---|---|---|---|---|
```

Flag:
- Months with unusually high/low win rates
- Old open deals (created >3 months ago, still in early stages = stale)
- Improving or declining trends

### 7. Per-owner comparison
```
| Owner | Won | Lost | Win Rate | Avg Cycle | Won Value | Pipeline |
|---|---|---|---|---|---|---|
```

Flag:
- Reps with win rate >20% above/below team average
- Reps with significantly longer/shorter cycles
- Reps with heavy pipeline but low win rate (potential coaching opportunity)

### 8. Recommendations
Based on the analysis:
- Process improvements (where to tighten qualification, speed up stages)
- Coaching opportunities (rep-specific)
- Product/positioning gaps (from lost reasons)
- Pipeline health assessment

---

## Output format

Start with summary, funnel, velocity, bottlenecks, lost analysis, cohorts, owner comparison, then recommendations.

Keep it operational — this feeds into weekly pipeline reviews and process optimization.

---

## Context

- Hyperline is a billing + CPQ platform for B2B SaaS
- Pipeline stages: Inbound Lead → Discovery → Technical Validation → Negotiations → Contract Sent → Won/Lost
- Disqualified is a separate terminal state (bad fit, spam, duplicate, timing)
- Reps: Margaret Mixon, Victoire Pelletier, Haylei Plageman, Quentin Fehlbaum, Victoria Dalleau, Anna Harvey
- Note: "Date Entered Contract Sent" is not tracked in Attio — velocity for that stage may be incomplete
- "Trading" date field may correspond to an older stage name — treat as Negotiations
