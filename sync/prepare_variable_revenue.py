#!/usr/bin/env python3
"""
Assemble variable revenue context for analysis.
Pulls Hyperline invoices (via CLI) + Attio deals → outputs data/variable_revenue_context.json

Called by the /variable-revenue skill. Run directly to refresh data.

Usage:
    python prepare_variable_revenue.py                # Previous calendar month
    python prepare_variable_revenue.py --month 2026-03
    python prepare_variable_revenue.py --days 35      # Custom lookback from today
"""

import argparse
import csv
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent.parent / "data"

# ── Name mapping: Hyperline customer name (lowercase) → Attio deal normalized name ──
# Maintain this when new customers are added with mismatched names
NAME_MAP = {
    "truvi (ex-superhog)": "superhog",
    "donna (ex-dealside)": "donna",
    "claruswms": "clarus wms",
    "kls": "kolsquare",
    "my local influence": "myli",
    "flip cx, inc": "flip cx",
    "telli technologies gmbh": "telli*phone",
    "cargosnap ": "cargosnap",
    "vocca.ai": "vocca.ai",
    "lev, inc.": "lev",
    "positive group lyon": "groupe positive",
    "sandra ai": "sandra upsell",
    "2fifteen tech": "215tech",
    "sweego (ex-mindbaz)": "sweego",
    "gastronaut (ikki group)": "gastronaut",
    "kabilio technologies sl": "kabilio",
    "futurae technologies ag": "futurae",
    "swapcard corporation": "swapcard",
    "phacet labs": "phacet",
    "hiboo systems": "hiboo",
    "klaro": "klaro",
    "dolphins": "dolphins (qomon)",
    "hrmony": "hrmony",
    "fleane bv": "fleane",
    "zilo énergie": "zilo",
    "letterhead": "letterhead",
    "malou": "malou-food marketing",
    "firmhouse": "firmhouse b.v.",
    "zoï": "zoi",
    "newtone.ai": "newtone",
    "strapi inc": "strapi",
    "ubiq sas": "ubiq",
    "default": "default",
    "vestlane": "vestlane",
}

# Case overrides — maintain as deals are reviewed
# case_a_override: flat fee covers committed, all usage on top is variable
# all_variable: no committed floor, all billing is variable revenue
CASE_A_OVERRIDE = {"default", "letterhead"}
ALL_VARIABLE = {"malou", "vestlane"}


def normalize_deal_name(name: str) -> str:
    """Normalize Attio deal name for matching."""
    # "Sign-up – Person – Company" → company
    m = re.match(r"Sign-up\s*[–—-]\s*.+?\s*[–—-]\s*(.+)", name, re.IGNORECASE)
    if m:
        return m.group(1).strip().lower()
    # "Sign-up – Company"
    m = re.match(r"Sign-up\s*[–—-]\s*(.+)", name, re.IGNORECASE)
    if m:
        return m.group(1).strip().lower()
    name = re.sub(r"\s*\(From List.*?\)", "", name)
    name = re.sub(r"\s*\(ex-.*?\)", "", name)
    name = re.sub(r"\bNew:\s*", "", name)
    name = re.sub(r"\s*-\s*HubSpot.*", "", name)
    return name.strip().lower()


def fetch_invoices(period_start_gte: str, period_start_lte: str) -> list[dict]:
    """Fetch invoices from Hyperline CLI."""
    all_invoices = []
    skip = 0
    take = 100

    while True:
        cmd = [
            "hyperline", "invoices", "list",
            "--period-start.gte", period_start_gte,
            "--period-start.lte", period_start_lte,
            "--status", "all",
            "--take", str(take),
            "--skip", str(skip),
            "--output", "json",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error fetching invoices: {result.stderr}", file=sys.stderr)
            if "authentication" in result.stderr.lower():
                sys.exit("Run 'hyperline login' first.")
            break

        data = json.loads(result.stdout)
        batch = data.get("data", [])
        meta = data.get("meta", {})
        all_invoices.extend(batch)

        total = meta.get("total", 0)
        if skip + take >= total or not batch:
            break
        skip += take

    return all_invoices


def load_attio_deals() -> dict[str, dict]:
    """Load won deals from Attio snapshot, keyed by normalized name."""
    snapshot_path = DATA_DIR / "deals" / "snapshot.csv"
    if not snapshot_path.exists():
        print("Warning: No Attio snapshot found. Run attio_sync.py first.")
        return {}

    attio_by_name: dict[str, dict] = {}
    with open(snapshot_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("stage") != "Won \U0001f389":
                continue
            norm = normalize_deal_name(row["name"])
            val = float(row.get("value_eur") or 0)
            var_rev_str = row.get("estimated_variable_revenue") or ""
            var_rev = float(var_rev_str) if var_rev_str else None

            if norm not in attio_by_name:
                attio_by_name[norm] = {"deal_names": [], "total_value": 0, "estimated_variable": None}
            attio_by_name[norm]["deal_names"].append(row["name"])
            attio_by_name[norm]["total_value"] += val
            if var_rev is not None:
                prev = attio_by_name[norm]["estimated_variable"] or 0
                attio_by_name[norm]["estimated_variable"] = prev + var_rev

    return attio_by_name


def match_deal(customer_name: str, attio_by_name: dict) -> Optional[dict]:
    """Match a Hyperline customer to an Attio deal."""
    hl_norm = customer_name.strip().lower()
    attio = attio_by_name.get(hl_norm)
    if not attio and hl_norm in NAME_MAP:
        attio = attio_by_name.get(NAME_MAP[hl_norm])
    return attio


def classify_case(customer_name: str, fixed_eur: float, deal_value: Optional[float]) -> str:
    """Determine variable revenue case for a customer."""
    hl_norm = customer_name.strip().lower()
    mapped = NAME_MAP.get(hl_norm, hl_norm)

    if hl_norm in ALL_VARIABLE or mapped in ALL_VARIABLE:
        return "all_variable"
    if deal_value is None:
        return "no_deal"
    if deal_value == 0:
        return "no_deal"
    if mapped in CASE_A_OVERRIDE or hl_norm in CASE_A_OVERRIDE:
        return "case_a_override"
    monthly_committed = deal_value / 12
    if fixed_eur >= monthly_committed * 0.7:
        return "case_a"
    return "case_b"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", help="Target month as YYYY-MM (default: previous month)")
    parser.add_argument("--days", type=int, help="Lookback days from today (alternative to --month)")
    args = parser.parse_args()

    today = datetime.date.today()

    if args.days:
        start = today - datetime.timedelta(days=args.days)
        period_gte = f"{start.isoformat()}T00:00:00Z"
        period_lte = f"{today.isoformat()}T23:59:59Z"
        period_label = f"last {args.days} days"
    else:
        if args.month:
            year, month = map(int, args.month.split("-"))
        else:
            # Previous calendar month
            first_of_this = today.replace(day=1)
            prev_month_end = first_of_this - datetime.timedelta(days=1)
            year, month = prev_month_end.year, prev_month_end.month

        # Usage periods typically start ~25th of prev month to ~15th of target month
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        period_gte = f"{prev_year}-{prev_month:02d}-20T00:00:00Z"
        period_lte = f"{year}-{month:02d}-20T00:00:00Z"
        period_label = f"{year}-{month:02d}"

    print(f"Fetching Hyperline invoices ({period_label})...")
    invoices = fetch_invoices(period_gte, period_lte)
    print(f"  {len(invoices)} invoices fetched")

    # ── Aggregate by customer with EUR conversion ──
    hl_by_customer: dict[str, dict] = {}
    for inv in invoices:
        cname = inv["customer"]["name"]
        ccy = inv["currency"]
        rate = inv.get("conversion_rate", 1) or 1

        if cname not in hl_by_customer:
            hl_by_customer[cname] = {
                "currency": ccy, "rate": rate,
                "customer_id": inv["customer"]["id"],
                "total_eur": 0, "fixed_eur": 0, "variable_eur": 0,
                "total_native": 0, "variable_native": 0, "invoices": 0,
                "line_items_detail": [],
            }
        h = hl_by_customer[cname]
        h["invoices"] += 1

        for li in inv.get("line_items", []):
            amt_native = li.get("amount_excluding_tax", 0) / 100
            amt_eur = amt_native * rate
            is_var = li.get("revenue_type") == "variable" or li.get("product_type") == "dynamic"

            h["total_native"] += amt_native
            h["total_eur"] += amt_eur
            if is_var:
                h["variable_native"] += amt_native
                h["variable_eur"] += amt_eur
            else:
                h["fixed_eur"] += amt_eur

            h["line_items_detail"].append({
                "name": li.get("name", ""),
                "product_type": li.get("product_type", ""),
                "revenue_type": li.get("revenue_type", ""),
                "amount_native": round(amt_native, 2),
                "amount_eur": round(amt_eur, 2),
                "units": li.get("units_count"),
                "is_variable": is_var,
            })

    # ── Load Attio deals ──
    attio_by_name = load_attio_deals()
    print(f"  {sum(len(v['deal_names']) for v in attio_by_name.values())} won deals loaded from Attio")

    # ── Cross-reference and compute variable revenue ──
    customers_out = []
    total_var_rev = 0

    for cname, h in hl_by_customer.items():
        attio = match_deal(cname, attio_by_name)
        deal_value = attio["total_value"] if attio else None
        est_var = attio.get("estimated_variable") if attio else None

        case = classify_case(cname, h["fixed_eur"], deal_value)
        monthly_committed = (deal_value / 12) if deal_value and deal_value > 0 else 0

        if case in ("all_variable", "no_deal", "case_a_override", "case_a"):
            var_rev = h["variable_eur"]
        else:  # case_b
            var_rev = max(0, h["variable_eur"] - monthly_committed)

        total_var_rev += var_rev

        if h["variable_eur"] > 0 or h["total_eur"] > 500:
            customers_out.append({
                "customer": cname,
                "customer_id": h["customer_id"],
                "currency": h["currency"],
                "conversion_rate": h["rate"],
                "invoices": h["invoices"],
                "total_eur": round(h["total_eur"], 2),
                "fixed_eur": round(h["fixed_eur"], 2),
                "usage_eur": round(h["variable_eur"], 2),
                "usage_native": round(h["variable_native"], 2),
                "deal_value_eur": deal_value,
                "estimated_variable_eur": est_var,
                "monthly_committed_eur": round(monthly_committed, 2),
                "case": case,
                "variable_revenue_eur": round(var_rev, 2),
                "matched_deal": attio["deal_names"][0] if attio else None,
                "line_items": h["line_items_detail"],
            })

    customers_out.sort(key=lambda c: -c["variable_revenue_eur"])

    all_total = sum(h["total_eur"] for h in hl_by_customer.values())
    all_fixed = sum(h["fixed_eur"] for h in hl_by_customer.values())
    all_usage = sum(h["variable_eur"] for h in hl_by_customer.values())

    out = {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "period": period_label,
        "period_start_gte": period_gte,
        "period_start_lte": period_lte,
        "summary": {
            "total_customers": len(hl_by_customer),
            "customers_with_usage": sum(1 for h in hl_by_customer.values() if h["variable_eur"] > 0),
            "total_billed_eur": round(all_total, 2),
            "fixed_recurring_eur": round(all_fixed, 2),
            "usage_dynamic_eur": round(all_usage, 2),
            "variable_revenue_eur": round(total_var_rev, 2),
            "variable_revenue_annualized_eur": round(total_var_rev * 12, 2),
        },
        "customers": customers_out,
        "config": {
            "name_map_entries": len(NAME_MAP),
            "case_a_overrides": sorted(CASE_A_OVERRIDE),
            "all_variable_accounts": sorted(ALL_VARIABLE),
        },
    }

    out_path = DATA_DIR / "variable_revenue_context.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"\nVariable revenue context written ({period_label})")
    print(f"  Total billed:      {all_total:,.0f}€")
    print(f"  Usage/dynamic:     {all_usage:,.0f}€")
    print(f"  Variable revenue:  {total_var_rev:,.0f}€ (annualized: {total_var_rev * 12:,.0f}€)")
    print(f"  Customers:         {len(customers_out)} included")
    print(f"Output: {out_path}")

    # Flag unmatched customers with usage
    unmatched = [c for c in customers_out if c["case"] == "no_deal" and c["usage_eur"] > 10]
    if unmatched:
        print(f"\n  Unmatched customers ({len(unmatched)}):")
        for c in unmatched:
            print(f"    {c['customer']}: {c['usage_eur']:,.0f}€ usage — add to NAME_MAP or Attio")


if __name__ == "__main__":
    main()
