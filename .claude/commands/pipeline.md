Run an open pipeline analysis for Hyperline.

## Steps

1. Run the prep script to assemble fresh pipeline data:
   ```
   cd /Users/lucas/business/Analysis/sync && .venv/bin/python prepare_pipeline.py
   ```

2. Read `/Users/lucas/business/Analysis/data/pipeline_context.json`

3. For every deal in `deals[]`, produce a structured assessment using the rules below.

4. Output the full report as markdown — a summary table first, then a deal-by-deal section.

---

## How to assess each deal

### Close probability

Start from `base_probability` (already calculated). Then adjust:

| Signal | Adjustment |
|---|---|
| Active test / sandbox running | +12 |
| Quote sent, awaiting signature | +15 |
| Last activity < 7 days | +8 |
| Last activity 14–30 days | -8 |
| Last activity > 30 days | -20 |
| Hard blocker identified in notes (missing feature, integration, budget) | -15 to -30 |
| Multiple stakeholders aligned | +8 |
| Decision deferred / "not now" | -20 |
| Overdue expected close | -8 |
| No notes / no context | -10 |

Cap: 5–92%. Round to nearest 5%.

### Situation

Write 1–2 sentences max. What's the actual current state of this deal? Use the notes (`notes_summary`), `next_steps`, and `situation` fields. Be specific — reference what was said in the last call, not generic stage descriptions.

### Recommended action

Only write an action if something is needed. If the deal is progressing normally with a clear next step, write **"—"**. 

Flag an action when:
- Last activity > 21 days and deal is not frozen on a feature
- A specific blocker exists that requires internal action (product, SE, escalation)
- A deadline is approaching (test ending, close date overdue, quote expiring)
- The deal shows ghost risk (last interaction ended with "we'll follow up internally")

Keep actions short and concrete: who does what by when.

---

## Output format

### Summary table

```
## Open Pipeline — [date]
[N] deals | €[total] total value

| Deal | Owner | Stage | Value | Close prob | Last activity | Action needed |
|---|---|---|---|---|---|---|
...
```

Sort: highest probability first within each stage group (Contract Sent → Negotiations → Tech Val → Discovery).

Use these symbols in the Action needed column:
- ✅ nothing needed
- ⚡ action this week
- 🔴 overdue / at risk

### Per-deal section

For each deal, a block:

```
### [Deal name] — [stage] | €[value] | [owner]
**Close probability:** X%  
**Forecast:** [Commit/Best Case/Pipeline]  
**Expected close:** [date or —]  
**Competition:** [or —]

**Situation:** [1-2 sentences from notes]

**Action:** [concrete action or —]
```

Skip deals with value = 0 and no notes unless they are in Negotiations or Contract Sent.

---

## Context

- Hyperline is a billing + CPQ platform for B2B SaaS
- Reps: Margaret Mixon (US/international), Victoire Pelletier (France), Haylei Plageman (US), Quentin Fehlbaum (EU), Victoria Dalleau, Anna Harvey
- Key competitors: Stripe Billing, Chargebee, Sequence, Maxio, Lago, Solvimon, PandaDoc
- Known product gaps to flag as blockers: Fortnox/Datev/Avalara ERP, Stripe phases/staircase pricing, SEPA/EBICS, white-label branding, SYNTEC automation
- Arc browser breaks HubSpot widget — flag if deal is in a live test and this hasn't been resolved
