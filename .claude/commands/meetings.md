Run a sales meeting analysis for Hyperline.

## Steps

1. Sync Claap transcripts first (fetches new recordings):
   ```
   cd /Users/lucas/business/Analysis/sync && .venv/bin/python claap_sync.py --days 30
   ```
   For a longer window: `claap_sync.py --days 60` or `--all`

2. Run the prep script to assemble the analysis context:
   ```
   cd /Users/lucas/business/Analysis/sync && .venv/bin/python prepare_meetings.py --days 30
   ```
   Match the `--days` to step 1.

3. Read `/Users/lucas/business/Analysis/data/meetings_context.json`

4. Produce the full report using the rules below.

---

## How to read the data

- `summary` — rolled-up counts: total meetings, how many had objections/competitor mentions/positive signals
- `top_objections` — frequency across all meetings
- `top_competitors` — which competitors came up most
- `top_pain_points` — what prospect pain points surfaced
- `meetings[]` — one entry per sales meeting with signals detected
- `meetings[].transcript_excerpt` — first 3000 chars of transcript for deeper analysis
- `meetings[].linked_deal` — matched Attio deal if title/participants overlap
- Signal detection is heuristic — treat counts as directional

---

## Analysis framework

### 1. Overview
```
## Sales Meetings — [period]
[N] sales meetings analyzed
Objections raised in [N] ([X]%) | Competitors mentioned in [N] ([X]%)
Positive signals in [N] ([X]%) | Clear next steps in [N] ([X]%)
```

### 2. Objection analysis
Rank all objections by frequency. For each:
- Count and percentage of meetings
- 1–2 verbatim quotes or paraphrases from transcripts
- Which deals/prospects raised it
- Whether it was handled effectively (look for positive signals in the same meeting)

Group into:
- **Hard blockers** — missing feature, compliance, integration gap (requires product action)
- **Soft objections** — timing, budget, internal process (requires sales technique)

### 3. Competitive landscape
For each competitor mentioned:
- How many meetings, which deals
- What context — are prospects comparing, migrating from, or just aware?
- Common comparison points (pricing, features, support)
- How reps handled the positioning (pull specific examples from transcripts)

### 4. What's resonating
From meetings with positive signals or clear next steps:
- What pain points opened the conversation?
- What product angles got traction? (CPQ, billing automation, usage metering, HubSpot integration)
- What messaging or framing worked?
- Pull specific examples from transcripts

### 5. Deal progression signals
For meetings linked to deals:
- Is the deal advancing? (positive + next steps = good sign)
- Any risk flags? (objections without resolution, competitor deep-dive, decision maker absent)
- Meetings where follow-up action is needed

### 6. Meeting-by-meeting detail
For each meeting with notable signals (objections, competitors, or linked to a high-value deal):
```
### [Title] — [date]
**Participants:** [external participants]
**Deal:** [linked deal name, stage, value — or "Unlinked"]
**Signals:** [objections | competitors | positive | next steps]

**Key moments:** [2-3 bullet points from transcript — what was discussed, what was agreed]
**Action:** [follow-up needed or —]
```

Skip meetings with no detected signals unless they are linked to deals in Negotiations or Contract Sent.

---

## Output format

Start with the overview, then objection analysis, competitive landscape, what's resonating, deal signals, then per-meeting details.

Keep it actionable — this feeds into sales coaching and competitive positioning.

---

## Context

- Hyperline is a billing + CPQ platform for B2B SaaS
- Reps: Margaret Mixon (US/international), Victoire Pelletier (France), Haylei Plageman (US), Quentin Fehlbaum (EU), Victoria Dalleau, Anna Harvey
- Key competitors: Stripe Billing, Chargebee, Sequence, Maxio, Lago, Orb, PandaDoc, Salesforce CPQ
- Known product gaps to flag: Fortnox/Datev/Avalara ERP, Stripe phases/staircase pricing, SEPA/EBICS, white-label branding, SYNTEC automation
- Meetings are recorded via Claap. Internal meetings (all Hyperline participants) are filtered out.
- French-speaking meetings (Victoire, Quentin) — transcripts may be in French, analyze accordingly
