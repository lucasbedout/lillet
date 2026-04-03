#!/usr/bin/env python3
"""
Assemble sales performance context per rep.
Reads deals snapshot + cold calls index + transcripts index.
Outputs data/sales_performance_context.json

Called by the /sales-performance skill. Run directly to refresh data.

Usage:
    python prepare_sales_performance.py              # Last 30 days activity, 6 months deals
    python prepare_sales_performance.py --days 60    # Activity window
    python prepare_sales_performance.py --months 12  # Deal window
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

# Map Allo rep names to Attio deal owner names (handle minor variations)
REP_NAME_NORMALIZE = {
    "lucas bédout": "Lucas Bédout",
    "quentin fehlbaum": "Quentin Fehlbaum",
    "victoire pelletier": "Victoire Pelletier",
    "margaret mixon": "Margaret Mixon",
    "haylei plageman": "Haylei Plageman",
    "quentin kalmogo": "Quentin Kalmogo",
    "anna harvey": "Anna Harvey",
    "victoria dalleau": "Victoria Dalleau",
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


def normalize_rep(name: str) -> str:
    return REP_NAME_NORMALIZE.get(name.lower().strip(), name.strip())


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30, help="Activity window (calls, meetings)")
    parser.add_argument("--months", type=int, default=6, help="Deal analysis window")
    parser.add_argument("--all", dest="all_time", action="store_true")
    args = parser.parse_args()

    activity_since = None if args.all_time else (
        datetime.date.today() - datetime.timedelta(days=args.days)
    )
    deal_since = None if args.all_time else (
        datetime.date.today() - datetime.timedelta(days=args.months * 30)
    )

    # ── Load deals ───────────────────────────────────────────────────────────
    csv_path = DATA_DIR / "deals" / "snapshot.csv"
    if not csv_path.exists():
        print("No snapshot found. Run attio_sync.py first.")
        return

    all_deals = list(csv.DictReader(open(csv_path, encoding="utf-8")))

    for d in all_deals:
        d["_created"] = parse_date(d.get("date_entered_lead") or d.get("created_at"))
        d["_won_date"] = parse_date(d.get("date_entered_won"))
        d["_lost_date"] = parse_date(d.get("date_entered_lost"))

    deals = all_deals
    if deal_since:
        deals = [d for d in all_deals if d["_created"] and d["_created"] >= deal_since]

    # ── Deal metrics per owner ───────────────────────────────────────────────
    by_owner: dict[str, dict] = defaultdict(lambda: {
        "deals_created": 0, "won": 0, "lost": 0, "disqualified": 0, "open": 0,
        "won_value": 0.0, "pipeline_value": 0.0, "total_value": 0.0,
        "cycles": [],  # won deal cycle lengths
        "won_deals": [],
        "open_deals": [],
        "deals_created_this_period": 0,
        "by_stage": defaultdict(int),
        "by_type": defaultdict(int),
        "by_source": defaultdict(int),
        "monthly_wins": defaultdict(int),
    })

    for d in deals:
        owner = d.get("owner") or "Unassigned"
        b = by_owner[owner]
        b["deals_created"] += 1
        val = eur(d.get("value_eur"))
        b["total_value"] += val
        stage = d.get("stage") or ""
        b["by_stage"][stage] += 1
        b["by_type"][d.get("deal_type") or "Unknown"] += 1
        b["by_source"][d.get("deal_source") or "Unknown"] += 1

        if stage == WON_STAGE:
            b["won"] += 1
            b["won_value"] += val
            b["won_deals"].append({
                "name": d.get("name"), "value_eur": val,
                "won_date": d.get("date_entered_won"),
            })
            if d["_created"] and d["_won_date"]:
                cycle = (d["_won_date"] - d["_created"]).days
                if 0 <= cycle <= 730:
                    b["cycles"].append(cycle)
            if d["_won_date"]:
                b["monthly_wins"][d["_won_date"].strftime("%Y-%m")] += 1
        elif stage == "Lost":
            b["lost"] += 1
        elif stage == "Disqualified":
            b["disqualified"] += 1
        else:
            b["open"] += 1
            b["pipeline_value"] += val
            b["open_deals"].append({
                "name": d.get("name"), "stage": stage, "value_eur": val,
            })

    # Recent deal creation (within activity window)
    if activity_since:
        for d in deals:
            if d["_created"] and d["_created"] >= activity_since:
                owner = d.get("owner") or "Unassigned"
                by_owner[owner]["deals_created_this_period"] += 1

    # ── Cold call metrics per rep ────────────────────────────────────────────
    calls_by_rep: dict[str, dict] = defaultdict(lambda: {
        "total_calls": 0, "answered": 0, "voicemail": 0,
        "meetings_booked": 0, "total_duration_min": 0.0,
    })

    calls_index = DATA_DIR / "calls" / "index.csv"
    if calls_index.exists():
        import os
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent / ".env", override=False)
        load_dotenv(Path(__file__).parent / ".env.local", override=True)

        rep_names_env: dict[str, str] = {}
        for pair in os.environ.get("ALLO_REP_NAMES", "").split(","):
            pair = pair.strip()
            if ":" in pair:
                num, name = pair.split(":", 1)
                rep_names_env[num.strip()] = name.strip()

        rows = list(csv.DictReader(open(calls_index, encoding="utf-8")))
        for row in rows:
            if row.get("category") not in ("outbound", "voicemail"):
                continue
            call_date = row.get("date", "")
            if activity_since and call_date < activity_since.isoformat():
                continue

            allo_num = row.get("allo_number", "")
            rep = normalize_rep(rep_names_env.get(allo_num, allo_num))
            b = calls_by_rep[rep]
            b["total_calls"] += 1
            result = (row.get("result") or "").upper()
            if result == "ANSWERED":
                b["answered"] += 1
            elif row.get("category") == "voicemail" or result == "VOICEMAIL":
                b["voicemail"] += 1
            try:
                b["total_duration_min"] += float(row.get("duration_min") or 0)
            except ValueError:
                pass

        # Load meetings count from coldcalls context if available
        cc_ctx = DATA_DIR / "coldcalls_context.json"
        if cc_ctx.exists():
            try:
                cc = json.loads(cc_ctx.read_text())
                for rep_data in cc.get("reps", []):
                    rep = normalize_rep(rep_data.get("rep_name", ""))
                    if rep in calls_by_rep:
                        calls_by_rep[rep]["meetings_booked"] = rep_data.get("meeting_booked", 0)
            except (json.JSONDecodeError, KeyError):
                pass

    # ── Meeting metrics per rep (Claap) ──────────────────────────────────────
    meetings_by_rep: dict[str, int] = defaultdict(int)

    transcripts_index = DATA_DIR / "transcripts" / "index.csv"
    if transcripts_index.exists():
        rows = list(csv.DictReader(open(transcripts_index, encoding="utf-8")))
        for row in rows:
            if row.get("category") != "sales":
                continue
            meeting_date = row.get("created_at", "")
            if activity_since and meeting_date < activity_since.isoformat():
                continue
            # Attribute to owner by matching title to deal owner
            # For now just count total — the skill can cross-reference
            meetings_by_rep["_total"] += 1

    # ── Assemble per-rep output ──────────────────────────────────────────────
    all_rep_names = set(by_owner.keys()) | set(calls_by_rep.keys())
    # Exclude "Unassigned" and reps that are just phone numbers
    all_rep_names = {r for r in all_rep_names if r != "Unassigned" and not r.startswith("+")}

    reps_out = []
    for rep in sorted(all_rep_names):
        deal = by_owner.get(rep, {})
        calls = calls_by_rep.get(rep, {})

        won = deal.get("won", 0)
        lost = deal.get("lost", 0)
        closed = won + lost
        cycles = deal.get("cycles", [])

        rep_out = {
            "name": rep,
            # Deal metrics
            "deals_created": deal.get("deals_created", 0),
            "deals_created_this_period": deal.get("deals_created_this_period", 0),
            "won": won,
            "lost": lost,
            "disqualified": deal.get("disqualified", 0),
            "open": deal.get("open", 0),
            "win_rate_pct": round(won / closed * 100, 1) if closed else None,
            "won_value": round(deal.get("won_value", 0)),
            "pipeline_value": round(deal.get("pipeline_value", 0)),
            "avg_deal_size": round(deal.get("won_value", 0) / won) if won else None,
            "avg_cycle_days": round(sum(cycles) / len(cycles), 1) if cycles else None,
            "median_cycle_days": sorted(cycles)[len(cycles) // 2] if cycles else None,
            # Stage breakdown
            "by_stage": dict(deal.get("by_stage", {})),
            "by_type": dict(deal.get("by_type", {})),
            "by_source": dict(deal.get("by_source", {})),
            "monthly_wins": dict(deal.get("monthly_wins", {})),
            # Open deals
            "open_deals": deal.get("open_deals", [])[:10],
            "recent_wins": deal.get("won_deals", [])[:5],
            # Activity metrics
            "cold_calls": calls.get("total_calls", 0),
            "cold_calls_answered": calls.get("answered", 0),
            "cold_call_connect_rate_pct": (
                round(calls["answered"] / calls["total_calls"] * 100, 1)
                if calls.get("total_calls") else None
            ),
            "cold_call_meetings": calls.get("meetings_booked", 0),
            "call_duration_min": round(calls.get("total_duration_min", 0), 1),
        }
        reps_out.append(rep_out)

    # Sort by won_value desc
    reps_out.sort(key=lambda r: -(r.get("won_value") or 0))

    # ── Global summary ───────────────────────────────────────────────────────
    total_won = sum(r["won"] for r in reps_out)
    total_lost = sum(r["lost"] for r in reps_out)
    total_won_value = sum(r["won_value"] for r in reps_out)
    total_pipeline = sum(r["pipeline_value"] for r in reps_out)
    total_calls = sum(r["cold_calls"] for r in reps_out)
    total_meetings_booked = sum(r["cold_call_meetings"] for r in reps_out)

    period_label_deals = "all time" if args.all_time else f"last {args.months} months"
    period_label_activity = "all time" if args.all_time else f"last {args.days} days"

    out = {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "period_deals": period_label_deals,
        "period_activity": period_label_activity,
        "deal_since": deal_since.isoformat() if deal_since else None,
        "activity_since": activity_since.isoformat() if activity_since else None,
        "summary": {
            "total_reps": len(reps_out),
            "total_won": total_won,
            "total_lost": total_lost,
            "total_won_value": round(total_won_value),
            "total_pipeline": round(total_pipeline),
            "overall_win_rate_pct": (
                round(total_won / (total_won + total_lost) * 100, 1)
                if (total_won + total_lost) else None
            ),
            "total_cold_calls": total_calls,
            "total_meetings_booked": total_meetings_booked,
            "total_sales_meetings": meetings_by_rep.get("_total", 0),
        },
        "reps": reps_out,
    }

    out_path = DATA_DIR / "sales_performance_context.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"Sales performance context written: {len(reps_out)} reps")
    print(f"  Deals: {period_label_deals} | Activity: {period_label_activity}")
    print(f"  Won: {total_won} (€{total_won_value:,.0f}) | Pipeline: €{total_pipeline:,.0f} | "
          f"Calls: {total_calls}")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
