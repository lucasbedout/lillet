Run a sales performance analysis for Hyperline.

## Steps

1. Sync data sources:
   ```
   cd /Users/lucas/business/Analysis/sync && .venv/bin/python attio_sync.py --no-notes
   ```
   Optionally sync cold calls and transcripts for activity data:
   ```
   cd /Users/lucas/business/Analysis/sync && .venv/bin/python allo_sync.py --days 30
   cd /Users/lucas/business/Analysis/sync && .venv/bin/python claap_sync.py --days 30
   ```

2. Run the prep script:
   ```
   cd /Users/lucas/business/Analysis/sync && .venv/bin/python prepare_sales_performance.py --days 30 --months 6
   ```
   Adjust `--days` for activity window and `--months` for deal window.

3. Read `/Users/lucas/business/Analysis/data/sales_performance_context.json`

4. Produce the full report using the rules below.

---

## How to read the data

- `summary` — team-level totals: reps, won, pipeline, calls, meetings
- `reps[]` — one entry per rep with deal metrics + activity metrics
- Deal metrics cover the `--months` window (default 6 months)
- Activity metrics (calls, meetings) cover the `--days` window (default 30 days)
- `reps[].by_stage` — current stage distribution of their deals
- `reps[].by_type/by_source` — deal type and source mix
- `reps[].open_deals` — top 10 open deals
- `reps[].recent_wins` — last 5 won deals
- `reps[].monthly_wins` — win distribution by month

---

## Analysis framework

### 1. Summary block
```
## Sales Performance — [period]
[N] reps active | Team win rate: [X]%
Won: [N] deals (€[N]) | Pipeline: €[N] ([N] open)
Activity (last [N] days): [N] cold calls | [N] meetings booked | [N] sales meetings
```

### 2. Leaderboard
```
| Rep | Won | Won Value | Win Rate | Pipeline | Avg Deal | Avg Cycle | Calls | Meetings |
|---|---|---|---|---|---|---|---|---|
```
Sort by won value. Highlight top performer and biggest improvement.

### 3. Per-rep deep dive
For each rep with activity:

```
### [Rep name]
**Deals:** [N] won (€[N]) | [N] lost | [N] open (€[N] pipeline)
**Win rate:** [X]% | **Avg deal size:** €[N] | **Avg cycle:** [N] days
**Activity:** [N] calls ([X]% connect) | [N] meetings booked
**Source mix:** [top 2-3 sources]
**Deal type:** [Inbound X / Outbound Y / ...]

**Open pipeline:**
[List top open deals with stage and value]

**Recent wins:**
[List recent wins with value]

**Assessment:** [1-2 sentences: what's going well, what to improve]
**Action:** [specific coaching point or —]
```

### 4. Comparative analysis
Compare reps on key dimensions:
- **Efficiency**: win rate, avg cycle length
- **Volume**: deals created, calls made, pipeline built
- **Quality**: avg deal size, pipeline-to-close ratio
- **Activity**: calls per day, connect rate, meetings booked

Flag outliers:
- High activity but low conversion → pitch/qualification coaching
- High win rate but low volume → capacity to take on more
- Large pipeline but few closes → deal progression issue
- Short cycles but small deals → could push for larger deals

### 5. Activity-to-outcome correlation
For reps with both call and deal data:
- Calls → meetings → pipeline → close relationship
- Which reps are most efficient at converting activity into deals?
- Is there a minimum activity threshold that predicts success?

### 6. Monthly trends
Win distribution by month per rep:
```
| Rep | [Month-3] | [Month-2] | [Month-1] | Current |
|---|---|---|---|---|
```
Flag improving/declining trends.

### 7. Team recommendations
Based on the analysis:
- Resource allocation (who needs help, who should mentor)
- Territory/source alignment (match reps to sources they convert best)
- Coaching priorities per rep
- Team-level process improvements

---

## Output format

Start with summary, leaderboard, per-rep deep dives, comparative analysis, activity correlation, trends, then recommendations.

Keep it actionable — this feeds into 1:1s, team meetings, and quota reviews.

---

## Context

- Hyperline is a billing + CPQ platform for B2B SaaS
- Sales team:
  - **Margaret Mixon** — US/international, English-speaking markets
  - **Victoire Pelletier** — France, French-speaking
  - **Haylei Plageman** — US market
  - **Quentin Fehlbaum** — EU, multilingual
  - **Victoria Dalleau** — France
  - **Anna Harvey** — US/international
  - **Quentin Kalmogo** — SDR/prospecting
- Cold calls tracked via Allo, meetings via Claap, deals via Attio
- Note: not all reps may have cold call data (some focus on inbound/partnerships)
