#!/usr/bin/env python3
"""
Assemble pipeline conversion & efficiency context.
Reads data/deals/snapshot.csv → outputs data/conversions_context.json

Called by the /conversions skill. Run directly to refresh data.

Usage:
    python prepare_conversions.py              # Last 6 months
    python prepare_conversions.py --months 12
    python prepare_conversions.py --all
"""

import argparse
import csv
import datetime
import json
from collections import defaultdict
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent.parent / "data"

STAGE_ORDER = [
    "Inbound Lead", "Discovery", "Technical Validation",
    "Negotiations", "Contract Sent", "Won 🎉",
]

# Date field mapping for stage entry dates
STAGE_DATE_FIELD = {
    "Inbound Lead": "date_entered_lead",
    "Discovery": "date_entered_discovery",
    "Technical Validation": "date_entered_tech_val",
    "Negotiations": "date_entered_negotiations",
    "Contract Sent": None,  # no date field exists
    "Won 🎉": "date_entered_won",
    "Lost": "date_entered_lost",
    "Disqualified": "date_entered_disqualified",
}


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


def days_between(d1: Optional[datetime.date], d2: Optional[datetime.date]) -> Optional[int]:
    if d1 and d2:
        return (d2 - d1).days
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

    # Parse dates for each deal
    for d in all_deals:
        d["_created"] = parse_date(d.get("date_entered_lead") or d.get("created_at"))
        d["_won_date"] = parse_date(d.get("date_entered_won"))
        d["_lost_date"] = parse_date(d.get("date_entered_lost"))
        d["_disqualified_date"] = parse_date(d.get("date_entered_disqualified"))
        for stage, field in STAGE_DATE_FIELD.items():
            if field:
                d[f"_date_{stage}"] = parse_date(d.get(field))

    # Filter by creation date
    deals = all_deals
    if since:
        deals = [d for d in all_deals if d["_created"] and d["_created"] >= since]

    # ── Overall funnel ───────────────────────────────────────────────────────
    # Count deals that reached each stage (based on date fields or current stage)
    reached_stage: dict[str, int] = defaultdict(int)
    reached_stage_value: dict[str, float] = defaultdict(float)

    for d in deals:
        val = eur(d.get("value_eur"))
        current_stage = d.get("stage") or ""
        current_idx = stage_index(current_stage)

        for i, stage in enumerate(STAGE_ORDER):
            date_key = f"_date_{stage}"
            has_date = d.get(date_key) is not None
            # A deal reached a stage if it has a date for it, OR its current stage is at/beyond it
            if has_date or (current_idx >= 0 and i <= current_idx):
                reached_stage[stage] += 1
                reached_stage_value[stage] += val

    funnel = []
    for i, stage in enumerate(STAGE_ORDER):
        count = reached_stage.get(stage, 0)
        value = reached_stage_value.get(stage, 0)
        prev_count = reached_stage.get(STAGE_ORDER[i - 1], 0) if i > 0 else len(deals)
        conversion = round(count / prev_count * 100, 1) if prev_count else None
        funnel.append({
            "stage": stage,
            "reached": count,
            "value": round(value),
            "conversion_from_previous_pct": conversion,
        })

    # ── Time in each stage ───────────────────────────────────────────────────
    stage_durations: dict[str, list[int]] = defaultdict(list)

    for d in deals:
        for i in range(len(STAGE_ORDER) - 1):
            stage = STAGE_ORDER[i]
            next_stage = STAGE_ORDER[i + 1]
            d1 = d.get(f"_date_{stage}")
            d2 = d.get(f"_date_{next_stage}")
            if d1 and d2:
                days = (d2 - d1).days
                if 0 <= days <= 365:  # sanity check
                    stage_durations[stage].append(days)

        # Also compute lead→lost and lead→disqualified durations
        if d["_created"] and d["_lost_date"]:
            days = (d["_lost_date"] - d["_created"]).days
            if 0 <= days <= 730:
                stage_durations["_lead_to_lost"].append(days)
        if d["_created"] and d["_disqualified_date"]:
            days = (d["_disqualified_date"] - d["_created"]).days
            if 0 <= days <= 730:
                stage_durations["_lead_to_disqualified"].append(days)

    time_in_stage = {}
    for stage, durations in stage_durations.items():
        if durations:
            durations_sorted = sorted(durations)
            time_in_stage[stage] = {
                "median_days": durations_sorted[len(durations_sorted) // 2],
                "avg_days": round(sum(durations) / len(durations), 1),
                "p25_days": durations_sorted[len(durations_sorted) // 4],
                "p75_days": durations_sorted[3 * len(durations_sorted) // 4],
                "sample_size": len(durations),
            }

    # ── Win/Loss rates ───────────────────────────────────────────────────────
    won_deals = [d for d in deals if d.get("stage") == "Won 🎉"]
    lost_deals = [d for d in deals if d.get("stage") == "Lost"]
    disqualified = [d for d in deals if d.get("stage") == "Disqualified"]
    open_deals = [d for d in deals if d.get("stage") not in ("Won 🎉", "Lost", "Disqualified")]

    closed = len(won_deals) + len(lost_deals)
    win_rate = round(len(won_deals) / closed * 100, 1) if closed else None

    # Sales cycle for won deals (lead → won)
    cycles = []
    for d in won_deals:
        if d["_created"] and d["_won_date"]:
            days = (d["_won_date"] - d["_created"]).days
            if 0 <= days <= 730:
                cycles.append(days)
    cycles_sorted = sorted(cycles) if cycles else []

    sales_cycle = {
        "median_days": cycles_sorted[len(cycles_sorted) // 2] if cycles_sorted else None,
        "avg_days": round(sum(cycles) / len(cycles), 1) if cycles else None,
        "p25_days": cycles_sorted[len(cycles_sorted) // 4] if len(cycles_sorted) > 3 else None,
        "p75_days": cycles_sorted[3 * len(cycles_sorted) // 4] if len(cycles_sorted) > 3 else None,
        "sample_size": len(cycles),
    }

    # ── Win/Loss by owner ────────────────────────────────────────────────────
    by_owner: dict[str, dict] = defaultdict(lambda: {
        "won": 0, "lost": 0, "disqualified": 0, "open": 0,
        "won_value": 0.0, "total_value": 0.0,
        "cycles": [],
    })

    for d in deals:
        owner = d.get("owner") or "Unassigned"
        b = by_owner[owner]
        val = eur(d.get("value_eur"))
        b["total_value"] += val
        stage = d.get("stage") or ""
        if stage == "Won 🎉":
            b["won"] += 1
            b["won_value"] += val
            if d["_created"] and d["_won_date"]:
                b["cycles"].append((d["_won_date"] - d["_created"]).days)
        elif stage == "Lost":
            b["lost"] += 1
        elif stage == "Disqualified":
            b["disqualified"] += 1
        else:
            b["open"] += 1

    owners_out = {}
    for owner, b in sorted(by_owner.items(), key=lambda x: -(x[1]["won"] + x[1]["lost"])):
        c = b["won"] + b["lost"]
        owners_out[owner] = {
            "won": b["won"],
            "lost": b["lost"],
            "disqualified": b["disqualified"],
            "open": b["open"],
            "win_rate_pct": round(b["won"] / c * 100, 1) if c else None,
            "won_value": round(b["won_value"]),
            "avg_cycle_days": round(sum(b["cycles"]) / len(b["cycles"]), 1) if b["cycles"] else None,
        }

    # ── Monthly cohort conversion ────────────────────────────────────────────
    by_month: dict[str, dict] = defaultdict(lambda: {
        "created": 0, "won": 0, "lost": 0, "disqualified": 0, "open": 0,
        "value_created": 0.0, "value_won": 0.0,
    })

    for d in deals:
        mk = month_key(d["_created"])
        b = by_month[mk]
        b["created"] += 1
        val = eur(d.get("value_eur"))
        b["value_created"] += val
        stage = d.get("stage") or ""
        if stage == "Won 🎉":
            b["won"] += 1
            b["value_won"] += val
        elif stage == "Lost":
            b["lost"] += 1
        elif stage == "Disqualified":
            b["disqualified"] += 1
        else:
            b["open"] += 1

    monthly_out = {}
    for mk in sorted(by_month.keys()):
        b = by_month[mk]
        closed = b["won"] + b["lost"]
        monthly_out[mk] = {
            "created": b["created"],
            "won": b["won"],
            "lost": b["lost"],
            "disqualified": b["disqualified"],
            "open": b["open"],
            "win_rate_pct": round(b["won"] / closed * 100, 1) if closed else None,
            "value_created": round(b["value_created"]),
            "value_won": round(b["value_won"]),
        }

    # ── Lost reason breakdown ────────────────────────────────────────────────
    lost_reasons: dict[str, int] = defaultdict(int)
    for d in lost_deals:
        reason = d.get("closed_lost_reason") or d.get("closed_lost_reason_text") or "Unknown"
        for r in reason.split(","):
            r = r.strip()
            if r:
                lost_reasons[r] += 1

    disq_reasons: dict[str, int] = defaultdict(int)
    for d in disqualified:
        reason = d.get("disqualification_reason") or d.get("disqualification_text") or "Unknown"
        for r in reason.split(","):
            r = r.strip()
            if r:
                disq_reasons[r] += 1

    # ── Bottleneck detection ─────────────────────────────────────────────────
    bottlenecks = []
    for stage, stats in time_in_stage.items():
        if stage.startswith("_"):
            continue
        if stats["median_days"] > 30:
            bottlenecks.append({
                "stage": stage,
                "median_days": stats["median_days"],
                "note": f"Median time in {stage} is {stats['median_days']} days — potential bottleneck",
            })

    # Check for high drop-off stages
    for i in range(1, len(funnel)):
        conv = funnel[i].get("conversion_from_previous_pct")
        if conv is not None and conv < 40:
            bottlenecks.append({
                "stage": funnel[i]["stage"],
                "conversion_pct": conv,
                "note": f"Only {conv}% of deals advance from {funnel[i-1]['stage']} to {funnel[i]['stage']}",
            })

    # ── Output ───────────────────────────────────────────────────────────────
    period_label = "all time" if args.all_time else f"last {args.months} months"

    out = {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "period": period_label,
        "since": since.isoformat() if since else None,
        "total_deals": len(deals),
        "overview": {
            "total": len(deals),
            "won": len(won_deals),
            "lost": len(lost_deals),
            "disqualified": len(disqualified),
            "open": len(open_deals),
            "win_rate_pct": win_rate,
            "won_value": round(sum(eur(d.get("value_eur")) for d in won_deals)),
            "pipeline_value": round(sum(eur(d.get("value_eur")) for d in open_deals)),
        },
        "funnel": funnel,
        "time_in_stage": time_in_stage,
        "sales_cycle": sales_cycle,
        "by_owner": owners_out,
        "monthly_cohorts": monthly_out,
        "lost_reasons": dict(sorted(lost_reasons.items(), key=lambda x: -x[1])),
        "disqualification_reasons": dict(sorted(disq_reasons.items(), key=lambda x: -x[1])),
        "bottlenecks": bottlenecks,
    }

    out_path = DATA_DIR / "conversions_context.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"Conversions context written: {len(deals)} deals ({period_label})")
    print(f"  Won: {len(won_deals)} | Lost: {len(lost_deals)} | "
          f"Win rate: {win_rate}% | Median cycle: {sales_cycle['median_days']}d")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
