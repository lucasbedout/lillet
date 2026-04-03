#!/usr/bin/env python3
"""
Assemble open pipeline context for analysis.
Reads snapshot.csv + note files → outputs data/pipeline_context.json

Called by the /pipeline skill. Run directly to refresh data.
"""

import csv
import datetime
import json
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent.parent / "data"
NOTES_DIR = DATA_DIR / "notes"

OPEN_STAGES = {"Inbound Lead", "Discovery", "Technical Validation", "Negotiations", "Contract Sent"}

STAGE_BASE_PROB = {
    "Contract Sent":        70,
    "Negotiations":         50,
    "Technical Validation": 28,
    "Discovery":            12,
    "Inbound Lead":          6,
}

def d(s):
    if not s: return None
    try: return datetime.date.fromisoformat(str(s)[:10])
    except: return None

def days_ago(s):
    x = d(s)
    return (datetime.date.today() - x).days if x else None

def eur(v):
    try: return int(float(v))
    except: return 0


def base_probability(deal: dict) -> int:
    stage = deal.get("stage") or ""
    base = STAGE_BASE_PROB.get(stage, 10)

    # Forecast category
    fc = deal.get("forecast_category") or ""
    if fc == "Commit":      base += 18
    elif fc == "Best Case": base += 8

    # Close date proximity / overdue
    close_date = d(deal.get("expected_closing_date"))
    if close_date:
        days_to_close = (close_date - datetime.date.today()).days
        if days_to_close < 0:   base -= 8   # overdue
        elif days_to_close < 7: base += 5   # imminent

    return max(5, min(90, base))


def find_note_file(deal_id: str, deal_name: str) -> Optional[Path]:
    prefix = deal_id[:8]
    for f in NOTES_DIR.glob(f"{prefix}_*.md"):
        return f
    # fallback: fuzzy name match
    safe = (deal_name or "").replace(" ", "_").replace("/", "_")[:30].lower()
    for f in NOTES_DIR.glob("*.md"):
        if safe and safe[:12] in f.name.lower():
            return f
    return None


def last_activity_days(note_content: str) -> Optional[int]:
    """Extract the most recent date mentioned in note headers."""
    import re
    dates = re.findall(r"## (\d{4}-\d{2}-\d{2})", note_content)
    if not dates:
        return None
    latest = max(dates)
    return days_ago(latest)


def main():
    snapshot_path = DATA_DIR / "deals" / "snapshot.csv"
    if not snapshot_path.exists():
        print("No snapshot found. Run attio_sync.py first.")
        return

    all_deals = list(csv.DictReader(open(snapshot_path, encoding="utf-8")))
    open_deals = [d for d in all_deals if d.get("stage") in OPEN_STAGES]

    pipeline = []

    for deal in open_deals:
        deal_id   = deal.get("id") or ""
        name      = deal.get("name") or "?"
        owner     = deal.get("owner") or "—"
        stage     = deal.get("stage") or "?"
        value     = eur(deal.get("value_eur"))
        forecast  = deal.get("forecast_category") or ""
        close_dt  = deal.get("expected_closing_date") or ""
        deal_type = deal.get("deal_type") or ""
        source    = deal.get("deal_source") or ""
        competition = deal.get("competition") or ""
        next_steps  = deal.get("next_steps") or ""
        pain        = deal.get("pain") or ""
        situation   = deal.get("situation") or ""
        lost_reason = deal.get("closed_lost_reason_text") or ""

        # Read notes
        note_path = find_note_file(deal_id, name)
        note_content = ""
        if note_path and note_path.exists():
            note_content = note_path.read_text(errors="replace")

        activity_days = last_activity_days(note_content) if note_content else None

        base_prob = base_probability(deal)

        pipeline.append({
            "id":              deal_id,
            "name":            name,
            "owner":           owner,
            "stage":           stage,
            "value_eur":       value,
            "forecast":        forecast,
            "expected_close":  close_dt[:10] if close_dt else "",
            "deal_type":       deal_type,
            "source":          source,
            "competition":     competition,
            "next_steps":      next_steps[:300] if next_steps else "",
            "pain":            pain,
            "situation":       situation[:400] if situation else "",
            "last_activity_days": activity_days,
            "base_probability":   base_prob,
            "notes_summary":   note_content[:6000] if note_content else "",
            "has_notes":       bool(note_content),
        })

    # Sort: Contract Sent first, then by value desc
    stage_order = list(STAGE_BASE_PROB.keys())
    pipeline.sort(key=lambda d: (
        stage_order.index(d["stage"]) if d["stage"] in stage_order else 99,
        -d["value_eur"]
    ))

    out = {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "total_open":   len(pipeline),
        "total_value":  sum(d["value_eur"] for d in pipeline),
        "deals":        pipeline,
    }

    out_path = DATA_DIR / "pipeline_context.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"Pipeline context written: {len(pipeline)} open deals, "
          f"€{out['total_value']:,} total value")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
