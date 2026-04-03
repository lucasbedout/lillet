Run a deal source analysis for Hyperline.

## Steps

1. Sync Attio deals first (refresh snapshot):
   ```
   cd /Users/lucas/business/Analysis/sync && .venv/bin/python attio_sync.py --no-notes
   ```

2. Run the prep script:
   ```
   cd /Users/lucas/business/Analysis/sync && .venv/bin/python prepare_deal_sources.py
   ```
   For a longer window: `prepare_deal_sources.py --months 12` or `--all`

3. Read `/Users/lucas/business/Analysis/data/deal_sources_context.json`

4. Produce the full report using the rules below.

---

## How to read the data

- `by_type` — deals grouped by Deal Type (Inbound/Outbound/Partnerships/Upsell)
- `by_source` — deals grouped by Deal Source (Events/Referral/Sales/LinkedIn/LLM Search/etc.)
- `by_utm_source` — deals with UTM tracking, grouped by utm_source
- `by_utm_campaign` — deals with UTM campaign tracking
- `monthly_cohorts` — deals created each month with outcomes and source breakdowns
- `first_page_visits` — first page the prospect visited before converting
- `how_did_you_hear` — self-reported attribution
- Win rates are calculated on closed deals only (won + lost, excluding disqualified/open)

---

## Analysis framework

### 1. Summary block
```
## Deal Sources — [period]
[N] deals analyzed | [N] won | [N] lost | [N] open
Win rate: [X]% | Total value created: €[N] | Won value: €[N]
```

### 2. Source breakdown table
```
| Source Type | Deals | Won | Lost | Open | Win Rate | Avg Deal Size | Won Value |
|---|---|---|---|---|---|---|---|
```
One table for Deal Type, one for Deal Source. Sort by deal count desc.

### 3. Best-performing sources
Identify sources with:
- Highest win rate (min 3 closed deals for statistical relevance)
- Highest average deal size
- Fastest sales cycles
- Best value-to-volume ratio

### 4. Source trends
Using monthly cohorts:
- Is the mix shifting? (more inbound vs outbound over time)
- Any new sources emerging? (LLM Search, Reddit)
- Month-over-month volume by top sources
- Flag months with unusual spikes or drops in any source

### 5. Digital attribution
If UTM data is available:
- Which utm_source drives the most deals?
- Which campaigns converted best?
- First page visit analysis — what content drives conversions?
- "How did you hear about us" — self-reported vs tracked attribution comparison

### 6. Source quality analysis
For each major source (>5 deals):
- Conversion funnel: created → discovery → tech val → won
- Average time to close
- Common lost reasons by source
- Are certain sources producing lower-quality leads? (high disqualification rate)

### 7. Recommendations
Based on the data:
- Where should the team invest more? (channels with high win rate but low volume)
- Where to cut? (high volume, low conversion)
- Channel-specific suggestions (e.g., "LinkedIn produces high-value deals but slow cycles — consider different targeting")

---

## Output format

Start with the summary, then source tables, then trends, then digital attribution, then quality analysis, then recommendations.

Keep it strategic — this feeds into marketing spend and channel allocation decisions.

---

## Context

- Hyperline is a billing + CPQ platform for B2B SaaS
- ICP: SaaS companies doing $1M–$50M ARR, CFOs, RevOps leads, CTOs
- Channels: Website (inbound), cold outreach (outbound via Allo), partnerships, events, content/SEO, LinkedIn, Reddit, LLM search (ChatGPT/Perplexity referrals)
- UTM tracking is set up on the website — deals that convert through the website should have UTM data
- "How did you hear about us" is a free-text field filled during onboarding
