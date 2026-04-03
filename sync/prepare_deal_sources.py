#!/usr/bin/env python3
"""
Assemble deal source analysis context.
Reads data/deals/snapshot.csv → outputs data/deal_sources_context.json

Called by the /deal-sources skill. Run directly to refresh data.

Usage:
    python prepare_deal_sources.py              # Last 6 months
    python prepare_deal_sources.py --months 12  # Last 12 months
    python prepare_deal_sources.py --all
"""

import argparse
import csv
import datetime
import json
from collections import defaultdict
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent.parent / "data"

TERMINAL_STAGES = {"Won 🎉", "Lost", "Disqualified"}
WON_STAGE = "Won 🎉"

STAGE_ORDER = [
    "Inbound Lead", "Discovery", "Technical Validation",
    "Negotiations", "Contract Sent", "Won 🎉", "Lost", "Disqualified",
]


def eur(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def parse_date(s: Optional[str]) -> Optional[datetime.date]:
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def month_key(d: Optional[datetime.date]) -> str:
    return d.strftime("%Y-%m") if d else "unknown"


def stage_index(stage: str) -> int:
    try:
        return STAGE_ORDER.index(stage)
    except ValueError:
        return -1


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--all", dest="all_time", action="store_true")
    args = parser.parse_args()

    csv_path = DATA_DIR / "deals" / "snapshot.csv"
    if not csv_path.exists():
        print("No snapshot found. Run attio_sync.py first.")
        return

    all_deals = list(csv.DictReader(open(csv_path, encoding="utf-8")))

    since: Optional[datetime.date] = None
    if not args.all_time:
        since = datetime.date.today() - datetime.timedelta(days=args.months * 30)

    # Filter deals by creation date
    deals = []
    for d in all_deals:
        created = parse_date(d.get("date_entered_lead") or d.get("created_at"))
        if since and (not created or created < since):
            continue
        d["_created"] = created
        deals.append(d)

    # ── By Deal Type (Inbound/Outbound/Partnerships/Upsell) ─────────────────
    by_type: dict[str, dict] = defaultdict(lambda: {
        "count": 0, "won": 0, "lost": 0, "disqualified": 0, "open": 0,
        "total_value": 0.0, "won_value": 0.0, "deals": [],
    })

    for d in deals:
        dtype = d.get("deal_type") or "Unknown"
        b = by_type[dtype]
        b["count"] += 1
        stage = d.get("stage") or ""
        val = eur(d.get("value_eur"))
        b["total_value"] += val
        if stage == WON_STAGE:
            b["won"] += 1
            b["won_value"] += val
        elif stage == "Lost":
            b["lost"] += 1
        elif stage == "Disqualified":
            b["disqualified"] += 1
        else:
            b["open"] += 1
        b["deals"].append({
            "name": d.get("name"), "stage": stage, "value_eur": val,
            "owner": d.get("owner"), "source": d.get("deal_source"),
        })

    # Win rate for closed deals
    for dtype, b in by_type.items():
        closed = b["won"] + b["lost"]
        b["win_rate_pct"] = round(b["won"] / closed * 100, 1) if closed else None
        b["avg_deal_value"] = round(b["won_value"] / b["won"], 0) if b["won"] else None

    # ── By Deal Source ───────────────────────────────────────────────────────
    by_source: dict[str, dict] = defaultdict(lambda: {
        "count": 0, "won": 0, "lost": 0, "disqualified": 0, "open": 0,
        "total_value": 0.0, "won_value": 0.0,
    })

    for d in deals:
        source = d.get("deal_source") or "Unknown"
        b = by_source[source]
        b["count"] += 1
        stage = d.get("stage") or ""
        val = eur(d.get("value_eur"))
        b["total_value"] += val
        if stage == WON_STAGE:
            b["won"] += 1
            b["won_value"] += val
        elif stage == "Lost":
            b["lost"] += 1
        elif stage == "Disqualified":
            b["disqualified"] += 1
        else:
            b["open"] += 1

    for source, b in by_source.items():
        closed = b["won"] + b["lost"]
        b["win_rate_pct"] = round(b["won"] / closed * 100, 1) if closed else None
        b["avg_deal_value"] = round(b["won_value"] / b["won"], 0) if b["won"] else None

    # ── By UTM Source ────────────────────────────────────────────────────────
    by_utm: dict[str, dict] = defaultdict(lambda: {"count": 0, "won": 0, "value": 0.0})
    for d in deals:
        utm = d.get("utm_source") or ""
        if not utm:
            continue
        b = by_utm[utm]
        b["count"] += 1
        if d.get("stage") == WON_STAGE:
            b["won"] += 1
            b["value"] += eur(d.get("value_eur"))

    # ── By UTM Campaign ──────────────────────────────────────────────────────
    by_campaign: dict[str, dict] = defaultdict(lambda: {"count": 0, "won": 0, "value": 0.0})
    for d in deals:
        campaign = d.get("utm_campaign") or ""
        if not campaign:
            continue
        b = by_campaign[campaign]
        b["count"] += 1
        if d.get("stage") == WON_STAGE:
            b["won"] += 1
            b["value"] += eur(d.get("value_eur"))

    # ── Monthly cohorts ──────────────────────────────────────────────────────
    by_month: dict[str, dict] = defaultdict(lambda: {
        "created": 0, "won": 0, "lost": 0, "disqualified": 0, "open": 0,
        "value_created": 0.0, "value_won": 0.0,
        "by_type": defaultdict(int), "by_source": defaultdict(int),
    })

    for d in deals:
        mk = month_key(d.get("_created"))
        b = by_month[mk]
        b["created"] += 1
        val = eur(d.get("value_eur"))
        b["value_created"] += val
        stage = d.get("stage") or ""
        if stage == WON_STAGE:
            b["won"] += 1
            b["value_won"] += val
        elif stage == "Lost":
            b["lost"] += 1
        elif stage == "Disqualified":
            b["disqualified"] += 1
        else:
            b["open"] += 1
        dtype = d.get("deal_type") or "Unknown"
        b["by_type"][dtype] += 1
        source = d.get("deal_source") or "Unknown"
        b["by_source"][source] += 1

    # Serialize monthly cohorts
    monthly_out = {}
    for mk in sorted(by_month.keys()):
        b = by_month[mk]
        monthly_out[mk] = {
            "created": b["created"],
            "won": b["won"],
            "lost": b["lost"],
            "disqualified": b["disqualified"],
            "open": b["open"],
            "value_created": round(b["value_created"]),
            "value_won": round(b["value_won"]),
            "by_type": dict(b["by_type"]),
            "by_source": dict(b["by_source"]),
        }

    # ── First page visit analysis ────────────────────────────────────────────
    page_visits: dict[str, int] = defaultdict(int)
    for d in deals:
        page = d.get("first_page_visit") or ""
        if page:
            page_visits[page] += 1

    # ── How did you hear about us ────────────────────────────────────────────
    hear_about: dict[str, int] = defaultdict(int)
    for d in deals:
        h = d.get("how_did_you_hear") or ""
        if h:
            hear_about[h.strip()[:80]] += 1

    # ── Output ───────────────────────────────────────────────────────────────
    period_label = "all time" if args.all_time else f"last {args.months} months"

    out = {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "period": period_label,
        "since": since.isoformat() if since else None,
        "total_deals": len(deals),
        "by_type": {k: {kk: vv for kk, vv in v.items() if kk != "deals"}
                    for k, v in sorted(by_type.items(), key=lambda x: -x[1]["count"])},
        "by_type_deals": {k: v["deals"][:20]
                          for k, v in sorted(by_type.items(), key=lambda x: -x[1]["count"])},
        "by_source": dict(sorted(by_source.items(), key=lambda x: -x[1]["count"])),
        "by_utm_source": dict(sorted(by_utm.items(), key=lambda x: -x[1]["count"])),
        "by_utm_campaign": dict(sorted(by_campaign.items(), key=lambda x: -x[1]["count"])) if by_campaign else {},
        "monthly_cohorts": monthly_out,
        "first_page_visits": dict(sorted(page_visits.items(), key=lambda x: -x[1])[:20]),
        "how_did_you_hear": dict(sorted(hear_about.items(), key=lambda x: -x[1])[:20]),
    }

    out_path = DATA_DIR / "deal_sources_context.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"Deal sources context written: {len(deals)} deals ({period_label})")
    types_summary = ", ".join(f"{k}: {v['count']}" for k, v in
                              sorted(by_type.items(), key=lambda x: -x[1]["count"]))
    print(f"  By type: {types_summary}")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
