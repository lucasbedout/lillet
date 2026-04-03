Run a variable revenue analysis for Hyperline.

## Steps

1. Run the prep script to assemble fresh data (default: previous calendar month):
   ```
   cd /Users/lucas/business/Analysis/sync && .venv/bin/python prepare_variable_revenue.py
   ```
   For a specific month: `prepare_variable_revenue.py --month 2026-03`

2. Read `/Users/lucas/business/Analysis/data/variable_revenue_context.json`

3. Produce the full report using the rules below.

---

## How to read the data

- `summary` — total billing, usage, and variable revenue for the period
- `customers[]` — one entry per Hyperline customer with usage or >500€ billing
- `customers[].case` — how variable revenue was computed:
  - `case_a`: fixed fees cover committed → all usage is variable on top
  - `case_a_override`: user-confirmed Case A
  - `case_b`: committed embedded in usage → variable = usage - deal/12
  - `all_variable`: pure variable account, no committed floor
  - `no_deal`: no Attio deal found (flag for review)
- `customers[].line_items[]` — individual Hyperline line items with product_type and revenue_type
- All EUR amounts are converted from native currency using invoice conversion_rate

---

## Variable revenue logic

**Deal value** (from Attio) = annual committed/recognized ARR.

**Variable revenue** = usage billed above the monthly committed amount.

Two cases:
- **Case A**: Customer has fixed/recurring fees that cover the committed amount. All usage/dynamic line items are pure variable revenue on top.
- **Case B**: Customer has no or low fixed fees. The committed amount is embedded in usage billing. Variable = usage billed (EUR) - deal_value / 12.

Overrides are maintained in `prepare_variable_revenue.py`:
- `CASE_A_OVERRIDE`: customers confirmed as Case A regardless of fee structure
- `ALL_VARIABLE`: accounts with no committed floor (all billing is variable)
- `NAME_MAP`: Hyperline→Attio customer name mappings

---

## Analysis framework

### 1. Summary block
```
## Variable Revenue — [period]
Total billed: [N]€ | Usage/dynamic: [N]€ | Variable revenue: [N]€
Annualized variable: [N]€
[N] customers with usage billing
```

### 2. Variable revenue table
```
| Customer | CCY | Usage (native) | Usage € | Fixed € | Deal ARR € | Mo. Committed € | Case | Var Rev € |
|---|---|---|---|---|---|---|---|---|
```
Sort by variable revenue descending. Include all customers with usage > 0.

### 3. Top contributors
List the top 10 variable revenue contributors with monthly and annualized amounts.

### 4. Case B deep-dive
For each Case B customer where usage > committed (i.e., positive variable revenue):
- What's driving the overage? (volume growth, new product lines, seasonal spike)
- Is this sustainable or a one-time blip?

### 5. Trend flags
Flag customers where:
- Usage is **>2x** the monthly committed (significant overage — potential upsell)
- Usage is **<50%** of committed (underutilization — churn risk or billing issue)
- `no_deal` case with >500€ usage (needs Attio deal or NAME_MAP entry)
- Currency risk: large non-EUR billers (GBP, USD) where FX moves matter

### 6. Month-over-month (if prior month data exists)
Compare to previous month's variable revenue. Flag:
- New customers generating variable revenue
- Customers whose variable revenue changed >30%
- Customers who dropped to zero

---

## Output format

Start with the summary block, then the full table, then top contributors, then flags.

Keep it actionable — this report feeds into monthly revenue recognition and forecasting.

---

## Maintenance notes

When new customers are onboarded or deals close:
- If Hyperline customer name differs from Attio deal name, add to `NAME_MAP` in `prepare_variable_revenue.py`
- If a customer is confirmed as Case A or all-variable, add to the override sets
- Run `attio_sync.py` before this script to ensure deal snapshot is fresh
