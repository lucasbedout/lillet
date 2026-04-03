#!/usr/bin/env python3
"""
Sync deals and notes from Attio to local files.

Usage:
    python attio_sync.py              # Full sync
    python attio_sync.py --no-notes   # Skip notes (faster)
"""

import argparse
import csv
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent / ".env.local", override=True)

ATTIO_API_KEY = os.environ.get("ATTIO_API_KEY", "")
if not ATTIO_API_KEY:
    sys.exit("Error: ATTIO_API_KEY not set. Copy sync/.env.example to sync/.env and fill it in.")

BASE_URL = "https://api.attio.com/v2"
DATA_DIR = Path(__file__).parent.parent / "data"

HEADERS = {
    "Authorization": f"Bearer {ATTIO_API_KEY}",
    "Content-Type": "application/json",
}

# Workspace member ID → display name (fetched once via MCP, hardcoded to avoid User Management scope)
MEMBER_NAMES: dict = {
    "68073a07-0a62-4b5f-92bf-06e1905b82d1": "Quentin Kozyra",
    "9c973ad2-6067-4a46-b2a2-c7f26001293f": "Vincent Terol",
    "c0ad87bc-dad7-47f5-8344-204fa4049538": "Antonin Goudet",
    "d4a4c913-a59d-4182-aae5-05ee8f5dbcad": "Lucas Bédout",
    "dd2da34a-48ff-4481-8c84-3c57ff1311c5": "Nathan Simony",
    "ea203a6b-4e85-4378-a448-00b564fc5086": "Victoria Dalleau",
    "f6839110-9b0e-4b19-b8e7-3e405901ab24": "Clément Garbay",
    "188ae7d1-1d4d-4505-8318-12fa7ce244fa": "Quentin Fehlbaum",
    "1ada8556-377a-42da-8410-b07cf242233d": "Victoire Pelletier",
    "2188edb5-798e-4574-9d8e-fdc7f86da2f4": "Gabriel Pimont Lyonnet",
    "7fc698ec-a16a-4651-a56c-d91fadd4b821": "Margaret Mixon",
    "8d173e42-2eeb-4f15-be47-2591c3dd0577": "Adrien Gaucher",
    "e92941a5-8860-4a8d-879c-c4891cba85e8": "Anna Harvey",
    "f45d4bd5-7af6-4c53-a237-3daa17c1db0e": "Haylei Plageman",
}

# Attio attribute slugs for the deals object
DEAL_FIELDS = {
    "name": "name",
    "stage": "stage",
    "owner": "owner",
    "value_eur": "value",
    "estimated_variable_revenue": "total_client_value",
    "one_time_fees": "migration_fees",
    "associated_company_id": "associated_company",
    "forecast_category": "forecast_category_status",
    "date_entered_lead": "date_entered_stage_lead",
    "date_entered_discovery": "date_entered_stage_discovery_6",
    "date_entered_tech_val": "date_entered_stage_demo_1",
    "date_entered_trading": "date_entered_stage_trading_3",
    "date_entered_won": "date_entered_stage_won_2",
    "date_entered_lost": "date_entered_stage_lost_1",
    "date_entered_negotiations": "date_entered_stage_negotiations",
    "date_entered_disqualified": "date_entered_stage_disqualifed",
    "demo_date": "demo_date",
    "expected_closing_date": "expected_closing_date",
    "deal_type": "inbound_outbound",
    "deal_source": "source_details",
    "next_steps": "next_steps",
    "closed_won_reason": "closed_won_reason",
    "closed_lost_reason_text": "closed_lost_reason",
    "closed_lost_reason": "closed_lost_reason_8",    # multiselect
    "competition": "competition",                     # multiselect
    "pain": "pain",                                   # multiselect
    "disqualification_reason": "disqualification_reason_4",
    "disqualification_text": "disqualification_reason",
    "situation": "situation_impact",
    "critical_event": "critical_event_4",
    "comment": "comment",
    "created_at": "created_at",
    "utm_source": "utm_source",
    "utm_medium": "utm_medium",
    "utm_campaign": "utm_campaign",
    "first_page_visit": "first_page_visit",
    "last_page_visit": "last_page_visit",
    "how_did_you_hear": "how_did_you_hear_about_us",
    "use_case": "use_case",
    "sales_cycle_length": "sales_cycle_length",
}


# ---------------------------------------------------------------------------
# Value extraction helpers
# ---------------------------------------------------------------------------

def _extract_one(v: dict) -> Any:
    """Extract a scalar from a single Attio value object."""
    attr_type = v.get("attribute_type", "")
    if attr_type == "text":
        return v.get("value")
    if attr_type in ("date", "timestamp"):
        return v.get("value")
    if attr_type == "number":
        return v.get("value")
    if attr_type == "currency":
        return v.get("currency_value")
    if attr_type == "status":
        return (v.get("status") or {}).get("title")
    if attr_type == "select":
        return (v.get("option") or {}).get("title")
    if attr_type == "actor-reference":
        actor_id = v.get("referenced_actor_id", "")
        return MEMBER_NAMES.get(actor_id) or v.get("referenced_actor_name") or actor_id
    if attr_type == "record-reference":
        return v.get("target_record_id")
    # Fallback: try common keys
    for key in ("value", "title", "name"):
        if key in v:
            return v[key]
    return None


def extract_single(values_list: list) -> Any:
    if not values_list:
        return None
    return _extract_one(values_list[0])


def extract_multi(values_list: list) -> str:
    """Return comma-separated string of all values in a multiselect field."""
    results = []
    for v in values_list:
        val = _extract_one(v)
        if val is not None:
            results.append(str(val))
    return ", ".join(results)


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def fetch_all_deals(client: httpx.Client) -> list[dict]:
    """Fetch all deal records from Attio (handles pagination)."""
    deals = []
    offset = 0
    limit = 500

    while True:
        resp = client.post(
            f"{BASE_URL}/objects/deals/records/query",
            json={
                "limit": limit,
                "offset": offset,
                "sorts": [{"direction": "desc", "attribute": "created_at"}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("data", [])
        deals.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
        print(f"  Fetched {len(deals)} deals so far...")

    return deals


def flatten_deal(raw: dict) -> dict:
    """Flatten one raw Attio deal record into a simple dict."""
    record_id = raw.get("id", {}).get("record_id", "")
    values = raw.get("values", {})

    flat = {"id": record_id}

    # Single-value fields
    multi_fields = {"closed_lost_reason", "competition", "pain"}

    for local_name, attio_slug in DEAL_FIELDS.items():
        raw_values = values.get(attio_slug, [])
        if local_name in multi_fields:
            flat[local_name] = extract_multi(raw_values)
        else:
            flat[local_name] = extract_single(raw_values)

    return flat


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def _blocks_to_text(blocks: list) -> str:
    """Recursively extract plain text from Attio document content blocks."""
    lines = []
    for block in blocks:
        btype = block.get("type", "")
        children = block.get("content", [])

        if btype == "text":
            lines.append(block.get("text", ""))
        elif btype == "hardBreak":
            lines.append("\n")
        elif btype in ("paragraph", "heading"):
            text = _blocks_to_text(children)
            if text.strip():
                lines.append(text + "\n")
        elif btype == "bulletList":
            for item in children:
                item_text = _blocks_to_text(item.get("content", []))
                lines.append(f"- {item_text.strip()}")
        elif btype == "orderedList":
            for i, item in enumerate(children, 1):
                item_text = _blocks_to_text(item.get("content", []))
                lines.append(f"{i}. {item_text.strip()}")
        elif btype == "listItem":
            lines.append(_blocks_to_text(children))
        elif children:
            lines.append(_blocks_to_text(children))

    return "\n".join(lines)


def fetch_notes_for_deal(client: httpx.Client, record_id: str) -> list[dict]:
    resp = client.get(
        f"{BASE_URL}/notes",
        params={
            "parent_object": "deals",
            "parent_record_id": record_id,
            "limit": 50,
        },
    )
    if resp.status_code != 200:
        return []
    return resp.json().get("data", [])


def note_to_markdown(note: dict) -> str:
    created = (note.get("created_at") or "")[:10]
    title = note.get("title") or "Untitled"
    lines = [f"## {created} — {title}\n"]

    content = note.get("content") or {}
    doc_content = content.get("document", {}).get("content", [])
    body = _blocks_to_text(doc_content).strip()
    if body:
        lines.append(body)
    else:
        lines.append("*(no content)*")

    return "\n".join(lines)


def sync_notes(client: httpx.Client, deals: list[dict]):
    """Fetch and save notes for active + recently closed deals."""
    notes_dir = DATA_DIR / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    cutoff = (datetime.date.today() - datetime.timedelta(days=180)).isoformat()

    relevant = [
        d for d in deals
        if d.get("stage") not in ("Lost", "Won 🎉", "Disqualified")
        or (d.get("date_entered_won") or d.get("date_entered_lost") or "") >= cutoff
    ]

    print(f"  Syncing notes for {len(relevant)} active/recent deals...")

    for deal in relevant:
        record_id = deal["id"]
        safe_name = (deal.get("name") or record_id).replace("/", "_").replace(" ", "_")[:50]
        filename = f"{record_id[:8]}_{safe_name}.md"

        notes = fetch_notes_for_deal(client, record_id)
        if not notes:
            continue

        header = (
            f"# Notes: {deal.get('name', record_id)}\n"
            f"**Stage:** {deal.get('stage')} | "
            f"**Owner:** {deal.get('owner')} | "
            f"**Value:** {deal.get('value_eur')} EUR\n\n"
        )
        body = "\n\n---\n\n".join(note_to_markdown(n) for n in notes)

        (notes_dir / filename).write_text(header + body)

    print(f"  Notes saved to {notes_dir}")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_snapshot(deals: list[dict]):
    deals_dir = DATA_DIR / "deals"
    deals_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.utcnow().isoformat()

    # JSON
    snapshot = {"synced_at": now, "count": len(deals), "deals": deals}
    snapshot_path = deals_dir / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2, default=str))

    # CSV
    if deals:
        csv_path = deals_dir / "snapshot.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=deals[0].keys())
            writer.writeheader()
            writer.writerows(deals)

    print(f"  Saved {len(deals)} deals → {deals_dir}/snapshot.{{json,csv}}")


def save_changes(current_deals: list[dict]):
    """Diff against previous snapshot and write a changes file."""
    prev_path = DATA_DIR / "deals" / "snapshot.json"
    if not prev_path.exists():
        return

    try:
        prev_data = json.loads(prev_path.read_text())
    except json.JSONDecodeError:
        return

    prev = {d["id"]: d for d in prev_data.get("deals", [])}
    curr = {d["id"]: d for d in current_deals}

    new_deals, stage_changes, newly_won, newly_lost = [], [], [], []

    for deal_id, c in curr.items():
        p = prev.get(deal_id)
        if p is None:
            new_deals.append({"id": deal_id, "name": c.get("name"), "owner": c.get("owner"),
                               "stage": c.get("stage"), "value_eur": c.get("value_eur"),
                               "deal_type": c.get("deal_type"), "deal_source": c.get("deal_source")})
        elif p.get("stage") != c.get("stage"):
            change = {"id": deal_id, "name": c.get("name"), "owner": c.get("owner"),
                      "from": p.get("stage"), "to": c.get("stage"), "value_eur": c.get("value_eur")}
            stage_changes.append(change)
            if c.get("stage") == "Won 🎉":
                newly_won.append(c)
            elif c.get("stage") == "Lost":
                newly_lost.append(c)

    changes = {
        "recorded_at": datetime.datetime.utcnow().isoformat(),
        "new_deals": new_deals,
        "stage_changes": stage_changes,
        "newly_won": newly_won,
        "newly_lost": newly_lost,
    }

    date_str = datetime.date.today().isoformat()
    out_path = DATA_DIR / "deals" / "changes" / f"{date_str}.json"
    out_path.write_text(json.dumps(changes, indent=2, default=str))

    print(f"  Changes: +{len(new_deals)} new, {len(stage_changes)} stage moves, "
          f"{len(newly_won)} won, {len(newly_lost)} lost")


def update_meta(extra: dict = None):
    meta_dir = DATA_DIR / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta = {"last_attio_sync": datetime.datetime.utcnow().isoformat()}
    if extra:
        meta.update(extra)
    (meta_dir / "last_sync.json").write_text(json.dumps(meta, indent=2))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-notes", action="store_true", help="Skip note sync")
    args = parser.parse_args()

    with httpx.Client(headers=HEADERS, timeout=60) as client:
        print("Fetching deals from Attio...")
        raw_deals = fetch_all_deals(client)
        print(f"  Got {len(raw_deals)} deals")

        deals = [flatten_deal(d) for d in raw_deals]

        # Diff before overwriting snapshot
        save_changes(deals)
        save_snapshot(deals)

        if not args.no_notes:
            print("Syncing notes...")
            sync_notes(client, deals)

    update_meta({"deal_count": len(deals)})
    print("Attio sync complete.")


if __name__ == "__main__":
    main()
