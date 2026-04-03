Run a cold call analysis for Hyperline.

## Steps

1. Sync Allo call data first (fetches new calls from all rep numbers):
   ```
   cd /Users/lucas/business/Analysis/sync && .venv/bin/python allo_sync.py --days 30
   ```
   For a longer window: `allo_sync.py --days 60` or `--all`

2. Run the prep script to assemble the analysis context:
   ```
   cd /Users/lucas/business/Analysis/sync && .venv/bin/python prepare_coldcalls.py --days 30
   ```
   Match the `--days` to step 1.

3. Read `/Users/lucas/business/Analysis/data/coldcalls_context.json`

4. Produce the full report using the rules below.

---

## How to read the data

- `global` — rolled-up stats across all reps and numbers
- `reps[]` — one entry per Allo number. `rep_name` is populated if `ALLO_REP_NAMES` is set in `.env.local`, otherwise it shows the phone number
- `reps[].calls[]` — individual answered calls with summary, detected objections, meeting_booked flag
- `reps[].by_week` — weekly call volume and connect counts
- `reps[].by_tag` — Allo call tags (rep-assigned labels)
- Signal detection is heuristic — treat percentages as directional, not precise

---

## Rep attribution (Hyperline)

If rep names are not resolved from Allo numbers, use context clues (call times, accents in transcripts, email domains in summaries) to attribute calls to:
- **Victoire Pelletier** — France / FR numbers, calls in French
- **Quentin Fehlbaum** — EU / DE / FR numbers
- **Margaret Mixon** — US / EN, international
- **Haylei Plageman** — US / EN
- **Anna Harvey** — US / EN

---

## Analysis framework

### 1. Activity & Volume
Per rep:
- Total outbound, answered, voicemails
- Connect rate (answered / total)
- Avg call duration (answered only)
- Calls per week trend (increasing / flat / declining)

Flag if a rep has < 5 outbound calls in the period — either missing from Allo or low activity.

### 2. Conversion funnel
For each rep, the conversion stack is:
```
Total calls → Connected → Positive signal detected → Meeting booked
```
Report absolute numbers and the rate at each step.
"Meeting booked" is detected heuristically from summaries — treat as indicative.

### 3. Objection analysis
Rank objections by frequency across all reps and per rep.
For the top 3 objections, pull 1–2 verbatim quotes or paraphrases from `calls[].summary`.
Note whether objections differ by rep (e.g., one rep getting more budget pushback vs. another getting timing pushback).

### 4. What's working
From calls where `meeting_booked = true` or `positive = true`:
- What pain points resonated? (Chargebee frustration, manual billing, scaling issues)
- What product angle opened the door? (CPQ, billing automation, HubSpot integration)
- What conversation structure seemed to work? (discovery-first vs. pitch-first)
- Any specific messaging that appears repeatedly in positive calls

### 5. Tag analysis
Interpret the `by_tag` distribution. Tags are rep-assigned and may indicate:
- Prospect qualification level
- Call stage (first touch, follow-up, no answer)
- Industry or persona
Surface the most common tags and what they imply about the call mix.

### 6. Weekly trend
Plot the weekly call volume and connect rate as a text table.
Flag any weeks with notably low activity or high/low connect rates.

---

## Output format

### Summary block
```
## Cold Calls — [period]
[N] outbound calls | [N] connected ([X]% connect rate) | [N] meetings booked ([X]%)
[N] reps active
```

### Rep table
```
| Rep | Calls | Connected | Connect % | Avg dur | Meetings | Meeting % |
|---|---|---|---|---|---|---|
```
Sort by total calls desc.

### Objections section
```
## Top Objections
1. [Objection] — [N] calls ([X]%) — "example quote..."
2. ...
```

### What's working section
Bullet points from positive/meeting calls. Be specific — reference actual summaries, not generic advice.

### Per-rep section
For each rep with > 3 answered calls, a block:
```
### [Rep name] — [N] calls | [X]% connect
**Trend:** [increasing/flat/declining week-over-week]
**Top objections:** [list]
**What's working:** [1–2 specific observations]
**Action:** [concrete recommendation or —]
```

Flag a rep-level action when:
- Connect rate < 15% (targeting issue or wrong time slots)
- Zero meetings booked despite > 10 connected calls (pitch or qualification issue)
- Activity dropped > 30% week-over-week (check in)
- All calls hitting the same objection type (may need messaging support)

---

## Context

- Hyperline is a billing + CPQ platform for B2B SaaS
- Cold calls target: CFOs, RevOps leads, Finance Directors, CTOs at SaaS companies doing $1M–$20M ARR
- Key pain points that open doors: Chargebee/Stripe limitations, manual invoicing, HubSpot quote-to-cash gap, scaling billing ops
- Known product gaps to acknowledge honestly if raised: Fortnox/Datev/Avalara ERP, SYNTEC automation, Salesforce staging env, staircase pricing phases
- Competitors that come up in cold calls: Stripe Billing, Chargebee, Maxio, Lago, Sequence, PandaDoc (for CPQ)
- French-speaking prospects: Victoire and Quentin's territory. Calls often in French.
- English-speaking: Margaret and Haylei. US-focused but also UK/EU in English.
