#!/usr/bin/env python3
"""
Generate a markdown digest of sales activity for a given period.
Reads from data/deals/snapshot.csv — run attio_sync.py first.

Usage:
    python generate_digest.py               # Last 7 days
    python generate_digest.py --days 30     # Last 30 days
    python generate_digest.py --from 2026-03-24 --to 2026-03-30
"""

import argparse
import csv
import datetime
import json
from collections import defaultdict
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_deals() -> list[dict]:
    csv_path = DATA_DIR / "deals" / "snapshot.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"No snapshot found at {csv_path}. Run attio_sync.py first.")
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def in_period(date_str: Optional[str], start: datetime.date, end: datetime.date) -> bool:
    if not date_str:
        return False
    try:
        d = datetime.date.fromisoformat(str(date_str)[:10])
        return start <= d <= end
    except ValueError:
        return False


def eur(val) -> str:
    try:
        return f"€{int(float(val)):,}"
    except (TypeError, ValueError):
        return "—"


def days_since(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    try:
        d = datetime.date.fromisoformat(str(date_str)[:10])
        return (datetime.date.today() - d).days
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Section generators
# ---------------------------------------------------------------------------

def section_overview(all_deals: list[dict], won: list[dict], lost: list[dict],
                     new_deals: list[dict], start: datetime.date, end: datetime.date) -> str:
    open_deals = [d for d in all_deals if d.get("stage") not in ("Won 🎉", "Lost", "Disqualified")]

    total_pipeline = sum(
        float(d.get("value_eur") or 0) for d in open_deals if d.get("value_eur")
    )
    won_value = sum(float(d.get("value_eur") or 0) for d in won if d.get("value_eur"))

    stages = defaultdict(int)
    for d in open_deals:
        stages[d.get("stage") or "Unknown"] += 1

    stage_order = ["Inbound Lead", "Discovery", "Technical Validation", "Negotiations", "Contract Sent"]
    stage_lines = " | ".join(
        f"**{s}**: {stages[s]}" for s in stage_order if stages.get(s)
    )

    return f"""## Pipeline Overview
- Open deals: **{len(open_deals)}** (pipeline value: {eur(total_pipeline)})
- {stage_lines}
- **Won** this period: {len(won)} ({eur(won_value)})
- **Lost** this period: {len(lost)}
- New deals entered: {len(new_deals)}
"""


def section_won(won: list[dict]) -> str:
    if not won:
        return "## Won\n*No deals won in this period.*\n"

    lines = ["## Won\n", "| Deal | Owner | Value | Type | Source | Closed Won Reason |",
             "|---|---|---|---|---|---|"]
    for d in sorted(won, key=lambda x: x.get("date_entered_won") or "", reverse=True):
        lines.append(
            f"| {d.get('name')} | {d.get('owner') or '—'} | {eur(d.get('value_eur'))} "
            f"| {d.get('deal_type') or '—'} | {d.get('deal_source') or '—'} "
            f"| {(d.get('closed_won_reason') or '—')[:80]} |"
        )
    return "\n".join(lines) + "\n"


def section_lost(lost: list[dict]) -> str:
    if not lost:
        return "## Lost\n*No deals lost in this period.*\n"

    lines = ["## Lost\n", "| Deal | Owner | Reason | Detail | Value |",
             "|---|---|---|---|---|"]
    for d in sorted(lost, key=lambda x: x.get("date_entered_lost") or "", reverse=True):
        reason = d.get("closed_lost_reason") or d.get("closed_lost_reason_text") or "—"
        detail = (d.get("closed_lost_reason_text") or "—")[:80]
        lines.append(
            f"| {d.get('name')} | {d.get('owner') or '—'} | {reason} | {detail} | {eur(d.get('value_eur'))} |"
        )
    return "\n".join(lines) + "\n"


def section_new_deals(new_deals: list[dict]) -> str:
    if not new_deals:
        return "## New Deals\n*No new deals this period.*\n"

    lines = ["## New Deals\n", "| Deal | Owner | Type | Source | Value | Stage |",
             "|---|---|---|---|---|---|"]
    for d in sorted(new_deals, key=lambda x: x.get("date_entered_lead") or x.get("created_at") or ""):
        lines.append(
            f"| {d.get('name')} | {d.get('owner') or '—'} | {d.get('deal_type') or '—'} "
            f"| {d.get('deal_source') or '—'} | {eur(d.get('value_eur'))} | {d.get('stage') or '—'} |"
        )
    return "\n".join(lines) + "\n"


def section_owner_summary(all_deals: list[dict], won: list[dict], lost: list[dict]) -> str:
    open_deals = [d for d in all_deals if d.get("stage") not in ("Won 🎉", "Lost", "Disqualified")]

    owners = sorted(set(
        d.get("owner") for d in all_deals if d.get("owner")
    ))

    lines = ["## By Owner\n", "| Owner | Open | Won (period) | Lost (period) | Open Pipeline |",
             "|---|---|---|---|---|"]

    for owner in owners:
        o_open = [d for d in open_deals if d.get("owner") == owner]
        o_won = [d for d in won if d.get("owner") == owner]
        o_lost = [d for d in lost if d.get("owner") == owner]
        # Skip rows with no activity and no open deals (old/archived members)
        if not o_open and not o_won and not o_lost:
            continue
        pipeline = sum(float(d.get("value_eur") or 0) for d in o_open)
        lines.append(
            f"| {owner} | {len(o_open)} | {len(o_won)} | {len(o_lost)} | {eur(pipeline)} |"
        )

    return "\n".join(lines) + "\n"


def section_alerts(all_deals: list[dict]) -> str:
    open_deals = [d for d in all_deals if d.get("stage") not in ("Won 🎉", "Lost", "Disqualified")]

    # Stale Tech Val (> 30 days)
    stale_tv = [
        d for d in open_deals
        if d.get("stage") == "Technical Validation"
        and (days_since(d.get("date_entered_tech_val")) or 0) > 30
    ]

    # Commit + Best Case deals
    hot_deals = [
        d for d in open_deals
        if d.get("forecast_category") in ("Commit", "Best Case")
    ]

    # Overdue expected close
    today = datetime.date.today().isoformat()
    overdue = [
        d for d in open_deals
        if d.get("expected_closing_date") and d.get("expected_closing_date") < today
    ]

    lines = ["## Alerts\n"]

    if stale_tv:
        lines.append(f"### Stale in Technical Validation (>30 days) — {len(stale_tv)}\n")
        for d in sorted(stale_tv, key=lambda x: days_since(x.get("date_entered_tech_val")) or 0, reverse=True):
            age = days_since(d.get("date_entered_tech_val"))
            lines.append(f"- **{d.get('name')}** ({d.get('owner')}) — {age}d in Tech Val | {eur(d.get('value_eur'))}")
        lines.append("")

    if hot_deals:
        lines.append(f"### Commit / Best Case — {len(hot_deals)}\n")
        for d in sorted(hot_deals, key=lambda x: x.get("forecast_category") or ""):
            lines.append(
                f"- **{d.get('name')}** [{d.get('forecast_category')}] ({d.get('owner')}) "
                f"— {d.get('stage')} | {eur(d.get('value_eur'))} "
                f"| close: {d.get('expected_closing_date') or '—'}"
            )
        lines.append("")

    if overdue:
        lines.append(f"### Overdue Expected Close — {len(overdue)}\n")
        for d in overdue:
            lines.append(
                f"- **{d.get('name')}** ({d.get('owner')}) — expected {d.get('expected_closing_date')} "
                f"| {d.get('stage')} | {eur(d.get('value_eur'))}"
            )
        lines.append("")

    if not (stale_tv or hot_deals or overdue):
        lines.append("*No alerts.*\n")

    return "\n".join(lines)


def section_recent_notes(start: datetime.date, end: datetime.date) -> str:
    """List note files that were modified in the period."""
    notes_dir = DATA_DIR / "notes"
    if not notes_dir.exists():
        return ""

    start_ts = datetime.datetime.combine(start, datetime.time.min).timestamp()
    end_ts = datetime.datetime.combine(end, datetime.time.max).timestamp()

    recent = sorted(
        [f for f in notes_dir.glob("*.md") if start_ts <= f.stat().st_mtime <= end_ts],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    if not recent:
        return ""

    lines = ["## Recent Meeting Notes\n"]
    for f in recent[:15]:
        lines.append(f"- [`notes/{f.name}`](../data/notes/{f.name})")
    return "\n".join(lines) + "\n"


def section_recent_transcripts(start: datetime.date, end: datetime.date) -> str:
    """List transcript files created in the period."""
    transcripts_dir = DATA_DIR / "transcripts"
    if not transcripts_dir.exists():
        return ""

    index_path = transcripts_dir / "index.csv"
    if not index_path.exists():
        return ""

    with open(index_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    recent = [
        r for r in rows
        if r.get("has_transcript") in ("True", True)
        and in_period(r.get("created_at"), start, end)
    ]

    if not recent:
        return ""

    # Show sales calls first
    recent.sort(key=lambda r: (r.get("category") != "sales", r.get("created_at") or ""), reverse=False)

    lines = ["## Claap Transcripts\n", "| Recording | Date | Category | Participants | File |",
             "|---|---|---|---|---|"]
    for r in recent:
        cat = r.get("category") or "—"
        participants = r.get("external_participants") or "—"
        fname = r.get("filename") or ""
        lines.append(
            f"| {r.get('title', '—')} | {r.get('created_at', '—')} | {cat} "
            f"| {participants[:50]} | [`{fname}`](../data/transcripts/{fname}) |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--from", dest="date_from", type=str, default=None)
    parser.add_argument("--to", dest="date_to", type=str, default=None)
    args = parser.parse_args()

    today = datetime.date.today()

    if args.date_from and args.date_to:
        start = datetime.date.fromisoformat(args.date_from)
        end = datetime.date.fromisoformat(args.date_to)
    else:
        end = today
        start = today - datetime.timedelta(days=args.days)

    print(f"Generating digest for {start} → {end}...")

    deals = load_deals()

    # Classify deals by period
    won = [d for d in deals if in_period(d.get("date_entered_won"), start, end)]
    lost = [d for d in deals if in_period(d.get("date_entered_lost"), start, end)]
    new_deals = [
        d for d in deals
        if in_period(d.get("date_entered_lead") or d.get("created_at"), start, end)
    ]

    # Build digest
    period_label = f"{start} to {end}" if start != end else str(start)
    synced_at = ""
    meta_path = DATA_DIR / "meta" / "last_sync.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            synced_at = f"\n*Data synced: {meta.get('last_attio_sync', '')[:16]} UTC*"
        except json.JSONDecodeError:
            pass

    header = f"# Sales Digest: {period_label}{synced_at}\n\n"

    sections = [
        header,
        section_overview(deals, won, lost, new_deals, start, end),
        "\n---\n",
        section_won(won),
        "\n---\n",
        section_lost(lost),
        "\n---\n",
        section_new_deals(new_deals),
        "\n---\n",
        section_owner_summary(deals, won, lost),
        "\n---\n",
        section_alerts(deals),
    ]

    notes_section = section_recent_notes(start, end)
    transcripts_section = section_recent_transcripts(start, end)
    if notes_section or transcripts_section:
        sections.append("\n---\n")
        if notes_section:
            sections.append(notes_section)
        if transcripts_section:
            sections.append(transcripts_section)

    content = "\n".join(sections)

    # Save digest
    digests_dir = DATA_DIR / "digests"
    digests_dir.mkdir(parents=True, exist_ok=True)

    if start == today - datetime.timedelta(days=args.days) and not args.date_from:
        filename = f"week_{today.isocalendar().year}-W{today.isocalendar().week:02d}.md"
    else:
        filename = f"period_{start}_to_{end}.md"

    out_path = digests_dir / filename
    out_path.write_text(content)
    print(f"Digest saved: {out_path}")

    # Also update context.md (the main entry point for Claude Code)
    context_path = DATA_DIR / "context.md"
    context_path.write_text(content)
    print(f"Updated: {context_path}")


if __name__ == "__main__":
    main()
