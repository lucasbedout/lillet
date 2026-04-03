#!/usr/bin/env python3
"""
Sync call history and transcripts from Allo to local files.
Covers inbound and outbound calls, voicemails, and AI summaries.

Allo API docs: https://help.withallo.com/en/api-reference/calls
Base URL: https://api.withallo.com/v1/api

Usage:
    python allo_sync.py                        # Last 30 days, all numbers
    python allo_sync.py --days 90
    python allo_sync.py --all                  # Full history
    python allo_sync.py --number +33123456789  # Specific number only
"""

import argparse
import csv
import datetime
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent / ".env.local", override=True)

ALLO_API_KEY = os.environ.get("ALLO_API_KEY", "")
if not ALLO_API_KEY:
    sys.exit("Error: ALLO_API_KEY not set in sync/.env.local")

# Allo phone numbers to sync — set in .env.local as comma-separated list
# e.g. ALLO_NUMBERS=+33123456789,+12025551234
ALLO_NUMBERS_ENV = os.environ.get("ALLO_NUMBERS", "")

BASE_URL = "https://api.withallo.com/v1/api"
HEADERS = {
    "Authorization": ALLO_API_KEY,
    "Content-Type": "application/json",
}

DATA_DIR = Path(__file__).parent.parent / "data"
CALLS_DIR = DATA_DIR / "calls"


# ---------------------------------------------------------------------------
# Call type helpers
# ---------------------------------------------------------------------------

def classify_call(call: dict) -> str:
    """Return 'outbound', 'inbound', or 'voicemail'."""
    result = (call.get("result") or "").upper()
    call_type = (call.get("type") or "").upper()
    if result == "VOICEMAIL":
        return "voicemail"
    if call_type == "OUTBOUND":
        return "outbound"
    return "inbound"


def is_answered(call: dict) -> bool:
    return (call.get("result") or "").upper() == "ANSWERED"


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def get_allo_numbers(client: httpx.Client) -> list[str]:
    """Fetch workspace phone numbers from Allo."""
    resp = client.get(f"{BASE_URL}/numbers", timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        numbers = data.get("data") or []
        if isinstance(numbers, list):
            return [n["number"] for n in numbers
                    if isinstance(n, dict) and n.get("number")]
    return []


def fetch_calls_for_number(
    client: httpx.Client,
    number: str,
    since: Optional[datetime.date] = None,
) -> list[dict]:
    """Fetch all calls for a given Allo number."""
    calls = []
    page = 0

    while True:
        params = {"allo_number": number, "page": page, "size": 100}
        resp = client.get(f"{BASE_URL}/calls", params=params, timeout=30)

        if resp.status_code == 401:
            sys.exit("Allo API: 401 Unauthorized. Check your ALLO_API_KEY.")
        if resp.status_code == 403:
            print(f"  403 Forbidden for {number} — check CONVERSATIONS_READ scope")
            return []
        if resp.status_code == 429:
            print("  Rate limited — waiting 5s...")
            import time; time.sleep(5)
            continue
        if resp.status_code != 200:
            print(f"  Warning: Allo returned {resp.status_code}: {resp.text[:200]}")
            return calls

        data = resp.json().get("data", {})
        batch = data.get("results") or []
        meta = data.get("metadata") or {}

        # Filter by date if requested
        if since:
            filtered = []
            stop = False
            for call in batch:
                call_date_str = call.get("start_date") or ""
                call_date = None
                try:
                    call_date = datetime.date.fromisoformat(call_date_str[:10])
                except ValueError:
                    pass
                if call_date and call_date < since:
                    stop = True
                    break
                filtered.append(call)
            calls.extend(filtered)
            if stop:
                break
        else:
            calls.extend(batch)

        total_pages = meta.get("total_pages") or 1
        if page + 1 >= total_pages or not batch:
            break
        page += 1
        print(f"    Fetched {len(calls)} calls for {number}...", end="\r")

    return calls


# ---------------------------------------------------------------------------
# Transcript formatting
# ---------------------------------------------------------------------------

def transcript_to_markdown(segments: list[dict]) -> str:
    if not segments:
        return ""

    lines = []
    current_source = None

    for seg in segments:
        source = seg.get("source") or "UNKNOWN"
        text = (seg.get("text") or "").strip()
        start = seg.get("start_seconds")

        if not text:
            continue

        # Map source to readable label
        label = {"AGENT": "Rep", "USER": "Rep", "EXTERNAL": "Prospect"}.get(source, source)

        if source != current_source:
            ts = f" [{int(start // 60)}:{int(start % 60):02d}]" if start is not None else ""
            lines.append(f"\n**{label}**{ts}")
            current_source = source

        lines.append(text)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------

def _safe_filename(date: str, call_type: str, contact: str, call_id: str) -> str:
    safe_contact = re.sub(r"[^\w\s+-]", "", contact or "unknown").strip().replace(" ", "_")[:40]
    short_id = call_id[:8] if call_id else "unknown"
    return f"{date}_{call_type}_{safe_contact}_{short_id}.md"


def save_call(call: dict, number: str) -> str:
    call_type = classify_call(call)
    out_dir = CALLS_DIR / call_type
    out_dir.mkdir(parents=True, exist_ok=True)

    call_id = call.get("id") or ""
    start_date = (call.get("start_date") or "")[:10]
    duration = call.get("length_in_minutes") or 0
    result = call.get("result") or ""
    tag = call.get("tag") or ""
    summary = call.get("summary") or ""
    recording_url = call.get("recording_url") or ""

    # Contact info
    if (call.get("type") or "").upper() == "OUTBOUND":
        contact_number = call.get("to_number") or "unknown"
    else:
        contact_number = call.get("from_number") or "unknown"

    filename = _safe_filename(start_date, call_type, contact_number, call_id)

    # Header
    header = f"# Call — {contact_number}\n"
    header += f"**Date:** {start_date}"
    header += f" | **Duration:** {duration:.1f}min"
    header += f" | **Direction:** {call.get('type', '').lower()}"
    header += f" | **Result:** {result}"
    if tag:
        header += f" | **Tag:** {tag}"
    if number:
        header += f" | **Allo number:** {number}"
    if recording_url:
        header += f" | **Recording:** {recording_url}"
    header += "\n\n"

    # AI summary
    body = ""
    if summary:
        body += f"## AI Summary\n{summary}\n\n"

    # Transcript
    segments = call.get("transcript") or []
    transcript_md = transcript_to_markdown(segments)
    if transcript_md:
        body += f"## Transcript\n{transcript_md}\n"

    (out_dir / filename).write_text(header + body)
    return f"{call_type}/{filename}"


def load_existing_index() -> dict[str, dict]:
    index_path = CALLS_DIR / "index.csv"
    if not index_path.exists():
        return {}
    with open(index_path, encoding="utf-8") as f:
        return {row["id"]: row for row in csv.DictReader(f)}


def save_index(rows: list[dict]):
    CALLS_DIR.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    index_path = CALLS_DIR / "index.csv"
    with open(index_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def generate_summary(calls: list[dict], period_label: str):
    """Write a human-readable summary of call activity."""
    CALLS_DIR.mkdir(parents=True, exist_ok=True)

    by_type: dict[str, list] = defaultdict(list)
    for c in calls:
        by_type[classify_call(c)].append(c)

    answered_outbound = [c for c in by_type["outbound"] if is_answered(c)]
    voicemails = by_type["voicemail"]
    inbound = by_type["inbound"]

    total = len(calls)
    connect_rate = len(answered_outbound) / len(by_type["outbound"]) * 100 if by_type["outbound"] else 0

    lines = [
        f"# Allo Call Activity — {period_label}\n",
        f"## Overview",
        f"- Total calls: **{total}**",
        f"- Outbound answered: **{len(answered_outbound)}** / {len(by_type['outbound'])} ({connect_rate:.0f}% connect rate)",
        f"- Voicemails left: **{len(voicemails)}**",
        f"- Inbound received: **{len(inbound)}**",
        "",
        "## Outbound Answered Calls",
    ]

    if answered_outbound:
        lines.append("| Date | Contact | Duration | Tag | Summary |")
        lines.append("|---|---|---|---|---|")
        for c in sorted(answered_outbound, key=lambda x: x.get("start_date") or "", reverse=True):
            contact = c.get("to_number") or "?"
            dur = f"{c.get('length_in_minutes', 0):.1f}min"
            tag = c.get("tag") or "—"
            summary = (c.get("summary") or "—")[:100]
            lines.append(f"| {(c.get('start_date') or '')[:10]} | {contact} | {dur} | {tag} | {summary} |")
    else:
        lines.append("*No answered outbound calls in this period.*")

    lines += ["", "## Voicemails Left"]
    if voicemails:
        for c in sorted(voicemails, key=lambda x: x.get("start_date") or "", reverse=True):
            contact = c.get("to_number") or "?"
            lines.append(f"- {(c.get('start_date') or '')[:10]} → {contact}")
    else:
        lines.append("*None.*")

    today = datetime.date.today().isoformat()
    out_path = CALLS_DIR / f"summary_{today}.md"
    out_path.write_text("\n".join(lines))
    print(f"  Summary: {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--all", dest="sync_all", action="store_true")
    parser.add_argument("--number", help="Sync a specific Allo number only")
    parser.add_argument("--force", action="store_true", help="Re-download all calls")
    args = parser.parse_args()

    since = None if args.sync_all else datetime.date.today() - datetime.timedelta(days=args.days)
    label = "all time" if args.sync_all else f"since {since}"

    existing = {} if args.force else load_existing_index()

    with httpx.Client(headers=HEADERS, timeout=30) as client:
        # Determine which numbers to sync
        if args.number:
            numbers = [args.number]
        elif ALLO_NUMBERS_ENV:
            numbers = [n.strip() for n in ALLO_NUMBERS_ENV.split(",") if n.strip()]
        else:
            print("Fetching Allo phone numbers from workspace...")
            numbers = get_allo_numbers(client)
            if not numbers:
                sys.exit(
                    "No Allo numbers found. Set ALLO_NUMBERS=+1234... in sync/.env.local "
                    "or pass --number."
                )

        print(f"Syncing {len(numbers)} Allo number(s) ({label})...")

        all_calls = []
        saved_files: dict[str, str] = {}
        new_count = skipped_count = 0

        for number in numbers:
            print(f"\n  Number: {number}")
            calls = fetch_calls_for_number(client, number, since=since)
            print(f"  Found {len(calls)} calls")

            for call in calls:
                call_id = call.get("id") or ""
                if call_id in existing and not args.force:
                    saved_files[call_id] = existing[call_id].get("filename", "")
                    skipped_count += 1
                    continue

                filename = save_call(call, number)
                saved_files[call_id] = filename
                new_count += 1

                call_type = classify_call(call)
                contact = call.get("to_number") if call.get("type","").upper() == "OUTBOUND" else call.get("from_number")
                answered = "✓" if is_answered(call) else "vm"
                print(f"    [{call_type:8} {answered}] {(call.get('start_date') or '')[:10]}  {contact or '?'}")

            all_calls.extend(calls)

        # Build index
        index_rows = []
        seen_ids = set()
        for call in all_calls:
            cid = call.get("id") or ""
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            contact = call.get("to_number") if (call.get("type") or "").upper() == "OUTBOUND" else call.get("from_number")
            index_rows.append({
                "id": cid,
                "date": (call.get("start_date") or "")[:10],
                "type": call.get("type") or "",
                "result": call.get("result") or "",
                "category": classify_call(call),
                "contact": contact or "",
                "allo_number": call.get("to_number") if (call.get("type") or "").upper() == "INBOUND" else call.get("from_number"),
                "duration_min": call.get("length_in_minutes") or "",
                "tag": call.get("tag") or "",
                "has_transcript": bool(call.get("transcript")),
                "has_summary": bool(call.get("summary")),
                "filename": saved_files.get(cid, ""),
            })

        # Merge with existing
        for cid, row in existing.items():
            if cid not in seen_ids:
                index_rows.append(row)

        save_index(index_rows)
        generate_summary(all_calls, label)

    print(f"\nNew: {new_count} | Skipped: {skipped_count}")
    print(f"Files: {CALLS_DIR}/")

    # Update meta
    meta_path = DATA_DIR / "meta" / "last_sync.json"
    try:
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    except json.JSONDecodeError:
        meta = {}
    meta["last_allo_sync"] = datetime.datetime.utcnow().isoformat()
    meta_path.write_text(json.dumps(meta, indent=2))
    print("Allo sync complete.")


if __name__ == "__main__":
    main()
