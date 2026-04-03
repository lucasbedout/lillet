#!/usr/bin/env python3
"""
Sync meeting transcripts from Claap to local markdown files.
Classifies recordings as 'sales' or 'internal' based on participants.

Claap API docs: https://docs.claap.io/
Base URL: https://api.claap.io/v1

Usage:
    python claap_sync.py              # Sync last 30 days
    python claap_sync.py --days 90    # Sync last 90 days
    python claap_sync.py --all        # Sync full history
"""

import argparse
import csv
import datetime
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent / ".env.local", override=True)

CLAAP_API_KEY = os.environ.get("CLAAP_API_KEY", "")
if not CLAAP_API_KEY:
    sys.exit("Error: CLAAP_API_KEY not set. Copy sync/.env.example to sync/.env and fill it in.")

BASE_URL = "https://api.claap.io/v1"

HEADERS = {
    "X-Claap-Key": CLAAP_API_KEY,
    "Content-Type": "application/json",
}

DATA_DIR = Path(__file__).parent.parent / "data"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"

# All known Hyperline team emails (used to distinguish sales vs internal recordings)
TEAM_EMAILS = {
    "quentin@hyperline.co",
    "vincent@hyperline.co",
    "contact@antoningoudet.com",
    "webanalyse3@tagexpert.fr",
    "lucas@meterly.co",
    "nathan@hyperline.co",
    "victoria@hyperline.co",
    "clement@hyperline.co",
    "quentin.fehlbaum@hyperline.co",
    "victoire@hyperline.co",
    "gabriel@hyperline.co",
    "margaret@hyperline.co",
    "adrien.gaucher.pro@gmail.com",
    "anna@hyperline.co",
    "haylei@hyperline.co",
}


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_recording(rec: dict) -> str:
    """
    Return 'sales' or 'internal'.

    Logic:
    - If any participant has an email not in TEAM_EMAILS → sales
    - Otherwise → internal (screen recording, internal sync, QBR, etc.)
    """
    participants = rec.get("meeting", {}).get("participants", [])
    for p in participants:
        email = (p.get("email") or "").lower()
        if email and email not in TEAM_EMAILS:
            return "sales"
    return "internal"


def get_external_participants(rec: dict) -> list[str]:
    """Return names/emails of non-Hyperline participants."""
    participants = rec.get("meeting", {}).get("participants", [])
    external = []
    for p in participants:
        email = (p.get("email") or "").lower()
        if email and email not in TEAM_EMAILS:
            name = p.get("name") or email
            external.append(name)
    return external


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def fetch_recordings(client: httpx.Client, since: Optional[datetime.date] = None) -> list[dict]:
    """Fetch all recordings, optionally filtered by date."""
    recordings = []
    params: dict = {"limit": 50}
    if since:
        params["created_after"] = since.isoformat()

    while True:
        resp = client.get(f"{BASE_URL}/recordings", params=params)

        if resp.status_code == 401:
            sys.exit("Claap API: 401 Unauthorized. Check your CLAAP_API_KEY.")
        if resp.status_code != 200:
            print(f"Warning: Claap returned HTTP {resp.status_code}: {resp.text[:200]}")
            return []

        data = resp.json()
        result = data.get("result") or data
        batch = result.get("recordings") or []
        recordings.extend(batch)
        print(f"  Fetched {len(recordings)} recordings...", end="\r")

        next_page = result.get("nextPage")
        if not batch or not next_page:
            break
        params["page"] = next_page

    print()  # newline after \r progress
    return recordings


def fetch_transcript(client: httpx.Client, recording_id: str) -> Optional[str]:
    """Fetch transcript text for a recording. Returns None if unavailable."""
    resp = client.get(f"{BASE_URL}/recordings/{recording_id}/transcript")
    if resp.status_code != 200:
        return None

    data = resp.json()
    segments = (
        data.get("result", {}).get("transcript", {}).get("segments")
        or data.get("transcript", {}).get("segments")
        or data.get("segments")
        or []
    )
    return _segments_to_markdown(segments) if segments else None


def _segments_to_markdown(segments: list[dict]) -> str:
    """Convert Claap transcript segments to readable markdown."""
    lines = []
    current_speaker = None

    for seg in segments:
        speaker = seg.get("speaker") or "Unknown"
        text = (seg.get("text") or "").strip()
        start = seg.get("startedAt") or seg.get("start")

        if not text:
            continue

        if speaker != current_speaker:
            timestamp = f" [{_fmt_seconds(start)}]" if start is not None else ""
            lines.append(f"\n**{speaker}**{timestamp}")
            current_speaker = speaker

        lines.append(text)

    return "\n".join(lines)


def _fmt_seconds(seconds) -> str:
    try:
        s = int(float(seconds))
        return f"{s // 60}:{s % 60:02d}"
    except (TypeError, ValueError):
        return str(seconds)


def _safe_filename(title: str, date: str, recording_id: str) -> str:
    safe = re.sub(r"[^\w\s-]", "", title or "untitled").strip().replace(" ", "_")[:50]
    short_id = recording_id[:8] if recording_id else "unknown"
    return f"{date}_{safe}_{short_id}.md"


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------

def save_transcript(recording: dict, transcript: str, category: str) -> str:
    """Save transcript to data/transcripts/{category}/ and return filename."""
    out_dir = TRANSCRIPTS_DIR / category
    out_dir.mkdir(parents=True, exist_ok=True)

    recording_id = str(recording.get("id") or "")
    title = recording.get("title") or "Untitled"
    created_at = (recording.get("createdAt") or "")[:10]
    duration_s = recording.get("durationSeconds")
    url = recording.get("url") or ""
    external = get_external_participants(recording)

    filename = _safe_filename(title, created_at, recording_id)

    header = f"# {title}\n"
    header += f"**Date:** {created_at}"
    if duration_s:
        header += f" | **Duration:** {_fmt_seconds(duration_s)}"
    if external:
        header += f" | **Participants:** {', '.join(external)}"
    if url:
        header += f" | **Link:** {url}"
    header += f" | **Category:** {category}"
    header += "\n\n---\n\n"

    (out_dir / filename).write_text(header + transcript)
    return f"{category}/{filename}"


def load_existing_index() -> dict[str, dict]:
    """Load existing index so we can skip already-synced recordings."""
    index_path = TRANSCRIPTS_DIR / "index.csv"
    if not index_path.exists():
        return {}
    with open(index_path, encoding="utf-8") as f:
        return {row["id"]: row for row in csv.DictReader(f)}


def save_index(all_rows: list[dict]):
    """Write merged index CSV."""
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    index_path = TRANSCRIPTS_DIR / "index.csv"
    if not all_rows:
        return index_path
    with open(index_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_rows[0].keys())
        writer.writeheader()
        writer.writerows(all_rows)
    return index_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--all", dest="sync_all", action="store_true")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="Skip recordings already in index (default: on)")
    parser.add_argument("--force", action="store_true",
                        help="Re-download all transcripts even if already saved")
    args = parser.parse_args()

    since = None if args.sync_all else datetime.date.today() - datetime.timedelta(days=args.days)
    label = "all time" if args.sync_all else f"since {since}"
    print(f"Fetching Claap recordings ({label})...")

    existing = {} if args.force else load_existing_index()

    with httpx.Client(headers=HEADERS, timeout=60) as client:
        recordings = fetch_recordings(client, since=since)
        print(f"  Found {len(recordings)} recordings")

        saved_files: dict[str, str] = {}
        skipped = new_sales = new_internal = no_transcript = 0

        for rec in recordings:
            rid = str(rec.get("id") or "")
            title = (rec.get("title") or rid)[:60]
            category = classify_recording(rec)

            # Skip already synced
            if rid in existing and not args.force:
                if existing[rid].get("filename"):
                    saved_files[rid] = existing[rid]["filename"]
                    skipped += 1
                    continue

            transcript = fetch_transcript(client, rid)
            if transcript:
                filename = save_transcript(rec, transcript, category)
                saved_files[rid] = filename
                if category == "sales":
                    new_sales += 1
                    print(f"  [sales]    {title}")
                else:
                    new_internal += 1
                    print(f"  [internal] {title}")
            else:
                no_transcript += 1

        # Build merged index rows
        existing_by_id = {r["id"]: r for r in existing.values()} if isinstance(existing, dict) else {}
        index_rows = []
        seen_ids = set()

        for rec in recordings:
            rid = str(rec.get("id") or "")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)

            category = classify_recording(rec)
            external = get_external_participants(rec)
            filename = saved_files.get(rid, "")

            index_rows.append({
                "id": rid,
                "title": rec.get("title") or "",
                "created_at": (rec.get("createdAt") or "")[:10],
                "duration_s": rec.get("durationSeconds") or "",
                "category": category,
                "external_participants": "; ".join(external),
                "has_transcript": bool(filename),
                "filename": filename,
                "url": rec.get("url") or "",
            })

        # Merge with existing rows for IDs not in current fetch
        for rid, row in existing.items():
            if rid not in seen_ids:
                index_rows.append(row)

        index_path = save_index(index_rows)

    print(f"\nNew: {new_sales} sales, {new_internal} internal | Skipped: {skipped} | No transcript: {no_transcript}")
    print(f"Index: {index_path}")

    # Update meta
    meta_path = DATA_DIR / "meta" / "last_sync.json"
    try:
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    except json.JSONDecodeError:
        meta = {}
    meta["last_claap_sync"] = datetime.datetime.utcnow().isoformat()
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2))

    print("Claap sync complete.")


if __name__ == "__main__":
    main()
