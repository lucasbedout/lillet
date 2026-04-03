#!/usr/bin/env python3
"""
Assemble cold call context for analysis.
Reads data/calls/index.csv + call files → outputs data/coldcalls_context.json

Called by the /coldcalls skill. Run directly to refresh data.

Usage:
    python prepare_coldcalls.py              # Last 30 days
    python prepare_coldcalls.py --days 60
    python prepare_coldcalls.py --all
"""

import argparse
import csv
import datetime
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent.parent / "data"
CALLS_DIR = DATA_DIR / "calls"

# Map Allo numbers to rep names.
# Set in .env.local as: ALLO_REP_NAMES=+33612345678:Victoire Pelletier,+14155550100:Margaret Mixon
# Falls back to the phone number if not set.
import os
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent / ".env.local", override=True)

REP_NAMES: dict[str, str] = {}
for pair in os.environ.get("ALLO_REP_NAMES", "").split(","):
    pair = pair.strip()
    if ":" in pair:
        num, name = pair.split(":", 1)
        REP_NAMES[num.strip()] = name.strip()


# ─── Signal detection ────────────────────────────────────────────────────────

MEETING_SIGNALS = [
    r"rendez[\s-]?vous", r"\brdv\b", r"d[ée]mo\s+(planifi|programm|r[ée]serv)",
    r"(prochain|next)\s+(call|meeting|réunion|appel)",
    r"(scheduled?|booked?|set up)\s+a?\s*(demo|meeting|call)",
    r"meeting\s+(book|schedul|set)", r"rappel\s+(prévu|planifi)",
    r"on\s+(se\s+)?rappelle", r"je\s+vous\s+rappelle",
    r"envoi.{0,20}invitation", r"agenda\s+(envoy|partagé)",
]

OBJECTION_PATTERNS = {
    "Budget / Prix":      [r"\bbudget\b", r"trop\s+cher", r"prix\s+[ée]lev", r"pas\s+le\s+budget",
                           r"coût\s+trop", r"not\s+in\s+(the\s+)?budget", r"too\s+expensive",
                           r"afford", r"cost\s+concern"],
    "Pas le bon moment":  [r"pas\s+(maintenant|prioritaire|le\s+bon\s+moment)", r"trop\s+tôt",
                           r"not\s+(right\s+)?now", r"not\s+a\s+priority", r"next\s+(quarter|year)",
                           r"après\s+l['a]", r"(Q[1-4]|premier|second)\s+(trimestre|quarter)",
                           r"pas\s+prêt", r"not\s+ready"],
    "Déjà un outil":      [r"d[ée]j[aà]\s+un\s+(outil|solution|logiciel)", r"already\s+(have|using)",
                           r"(stripe|chargebee|maxio|lago|sequence|pennylane|recurly|zuora)",
                           r"satisfied\s+with", r"satisfaits?\s+de", r"ça\s+marche\s+(bien|très)"],
    "Pas décideur":       [r"pas\s+(le\s+)?d[ée]cideur", r"not\s+(the\s+)?(decision|right\s+person)",
                           r"(CTO|CFO|CEO|DG|DAF)\s+(doit|must|needs?)",
                           r"(valider|approuver|checker)\s+avec", r"need\s+to\s+(check|confirm|discuss)"],
    "Pas de besoin":      [r"pas\s+(de\s+)?(besoin|int[ée]r[eê]t)", r"no\s+(need|interest)",
                           r"happy\s+with", r"content\s+de", r"(trop\s+)?petit",
                           r"too\s+small", r"out\s+of\s+scope"],
    "Fonctionnalité manquante": [r"(manque|missing)\s+.{0,40}(feature|fonctionnalit)",
                                  r"ne\s+fait\s+pas", r"doesn[''`]t\s+(support|do|handle)",
                                  r"(salesforce|netsuite|fortnox|datev|sap|oracle)",
                                  r"(staircase|phases|SYNTEC|SEPA|EBICS)"],
}

POSITIVE_SIGNALS = [
    r"int[ée]ress[ée]", r"interested", r"sounds?\s+good", r"ça\s+(m'int|int[ée]resse)",
    r"bonne\s+solution", r"(great|good)\s+(fit|match|solution)",
    r"pain\s+point", r"probl[eè]me\s+(actuel|avec)", r"(exactement|exactly)\s+ce\s+(qu[ei]|what)",
    r"(Chargebee|Stripe|Pennylane).{0,50}probl[eè]me",
    r"(factu|billing).{0,30}(manuel|manual|galère|pain)",
    r"on\s+(pourrait|could)\s+(aller|move|proceed)",
]


def _match(text: str, patterns: list[str]) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def _count_matches(text: str, patterns: list[str]) -> int:
    t = text.lower()
    return sum(1 for p in patterns if re.search(p, t))


# ─── Helpers ─────────────────────────────────────────────────────────────────

def rep_name(allo_number: str) -> str:
    return REP_NAMES.get(allo_number, allo_number)


def iso_week(date_str: str) -> str:
    try:
        d = datetime.date.fromisoformat(date_str[:10])
        return d.strftime("%Y-W%V")
    except Exception:
        return "unknown"


def read_call_file(filename: str) -> dict:
    """Read a call .md file and extract summary + first 1500 chars of transcript."""
    path = CALLS_DIR / filename
    if not path.exists():
        return {}
    text = path.read_text(errors="replace")

    summary = ""
    m = re.search(r"## AI Summary\n(.*?)(?:\n##|\Z)", text, re.DOTALL)
    if m:
        summary = m.group(1).strip()

    transcript = ""
    m = re.search(r"## Transcript\n(.*)", text, re.DOTALL)
    if m:
        transcript = m.group(1).strip()[:1500]

    return {"summary": summary, "transcript": transcript}


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--all", dest="all_time", action="store_true")
    args = parser.parse_args()

    index_path = CALLS_DIR / "index.csv"
    if not index_path.exists():
        print("No calls index found. Run allo_sync.py first.")
        return

    since: Optional[datetime.date] = None
    if not args.all_time:
        since = datetime.date.today() - datetime.timedelta(days=args.days)

    rows = list(csv.DictReader(open(index_path, encoding="utf-8")))

    # Only outbound + voicemails (voicemails are attempted outbound)
    cold_rows = [r for r in rows if r.get("category") in ("outbound", "voicemail")]
    if since:
        cold_rows = [r for r in cold_rows if r.get("date", "") >= since.isoformat()]

    # ── Per-rep buckets ───────────────────────────────────────────────────────
    by_rep: dict[str, dict] = defaultdict(lambda: {
        "allo_number": "",
        "rep_name": "",
        "total": 0,
        "answered": 0,
        "voicemail": 0,
        "failed": 0,
        "total_duration_min": 0.0,
        "meeting_booked": 0,
        "positive_signal": 0,
        "by_tag": defaultdict(int),
        "by_week": defaultdict(lambda: {"total": 0, "answered": 0}),
        "objections": defaultdict(int),
        "calls": [],   # detailed list for the skill to read
    })

    for row in cold_rows:
        num = row.get("allo_number") or row.get("contact") or "unknown"
        # For outbound, the allo_number is the calling number
        allo_num = row.get("allo_number", "")
        # In allo_sync, for outbound: allo_number column = from_number
        # Let's use the allo_number field
        rep_key = allo_num or "unknown"

        r = by_rep[rep_key]
        r["allo_number"] = allo_num
        r["rep_name"] = rep_name(allo_num)
        r["total"] += 1

        cat = row.get("category", "")
        result = row.get("result", "").upper()
        if result == "ANSWERED":
            r["answered"] += 1
        elif cat == "voicemail" or result == "VOICEMAIL":
            r["voicemail"] += 1
        else:
            r["failed"] += 1

        try:
            r["total_duration_min"] += float(row.get("duration_min") or 0)
        except ValueError:
            pass

        tag = row.get("tag") or "—"
        r["by_tag"][tag] += 1

        week = iso_week(row.get("date", ""))
        r["by_week"][week]["total"] += 1
        if result == "ANSWERED":
            r["by_week"][week]["answered"] += 1

        # Read file for content signals
        call_detail: dict = {}
        if row.get("filename"):
            call_detail = read_call_file(row["filename"])

        full_text = (call_detail.get("summary") or "") + " " + (call_detail.get("transcript") or "")

        meeting_booked = _match(full_text, MEETING_SIGNALS)
        positive = _match(full_text, POSITIVE_SIGNALS)
        if meeting_booked:
            r["meeting_booked"] += 1
        if positive:
            r["positive_signal"] += 1

        for obj_label, obj_patterns in OBJECTION_PATTERNS.items():
            if _match(full_text, obj_patterns):
                r["objections"][obj_label] += 1

        # Add to calls list (answered calls with content only, cap at 50 per rep)
        if result == "ANSWERED" and full_text.strip() and len(r["calls"]) < 50:
            r["calls"].append({
                "date":           row.get("date", ""),
                "contact":        row.get("contact", ""),
                "duration_min":   row.get("duration_min", ""),
                "tag":            tag,
                "meeting_booked": meeting_booked,
                "positive":       positive,
                "summary":        (call_detail.get("summary") or "")[:800],
                "objections":     [k for k, pats in OBJECTION_PATTERNS.items()
                                   if _match(full_text, pats)],
            })

    # ── Global stats ─────────────────────────────────────────────────────────
    all_total    = sum(r["total"]    for r in by_rep.values())
    all_answered = sum(r["answered"] for r in by_rep.values())
    all_vm       = sum(r["voicemail"] for r in by_rep.values())
    all_meetings = sum(r["meeting_booked"] for r in by_rep.values())

    global_objections: dict[str, int] = defaultdict(int)
    for r in by_rep.values():
        for k, v in r["objections"].items():
            global_objections[k] += v

    # ── Weekly trend (global) ─────────────────────────────────────────────────
    weekly: dict[str, dict] = defaultdict(lambda: {"total": 0, "answered": 0})
    for r in by_rep.values():
        for week, wdata in r["by_week"].items():
            weekly[week]["total"]    += wdata["total"]
            weekly[week]["answered"] += wdata["answered"]

    # ── Clean up for JSON serialisation ──────────────────────────────────────
    reps_out = []
    for rep_key, r in sorted(by_rep.items()):
        connect_rate = round(r["answered"] / r["total"] * 100, 1) if r["total"] else 0
        avg_dur = round(r["total_duration_min"] / r["answered"], 1) if r["answered"] else 0
        meeting_rate = round(r["meeting_booked"] / r["answered"] * 100, 1) if r["answered"] else 0
        reps_out.append({
            "allo_number":        r["allo_number"],
            "rep_name":           r["rep_name"],
            "total_outbound":     r["total"],
            "answered":           r["answered"],
            "voicemail":          r["voicemail"],
            "failed":             r["failed"],
            "connect_rate_pct":   connect_rate,
            "avg_duration_min":   avg_dur,
            "meeting_booked":     r["meeting_booked"],
            "meeting_rate_pct":   meeting_rate,
            "positive_signals":   r["positive_signal"],
            "by_tag":             dict(sorted(r["by_tag"].items(), key=lambda x: -x[1])),
            "by_week":            dict(sorted(r["by_week"].items())),
            "top_objections":     dict(sorted(r["objections"].items(), key=lambda x: -x[1])),
            "calls":              sorted(r["calls"], key=lambda c: c["date"], reverse=True),
        })

    period_label = "all time" if args.all_time else f"last {args.days} days"

    out = {
        "generated_at":    datetime.datetime.utcnow().isoformat(),
        "period":          period_label,
        "since":           since.isoformat() if since else None,
        "global": {
            "total_outbound":   all_total,
            "answered":         all_answered,
            "voicemail":        all_vm,
            "connect_rate_pct": round(all_answered / all_total * 100, 1) if all_total else 0,
            "meetings_booked":  all_meetings,
            "meeting_rate_pct": round(all_meetings / all_answered * 100, 1) if all_answered else 0,
            "top_objections":   dict(sorted(global_objections.items(), key=lambda x: -x[1])),
            "weekly_trend":     dict(sorted(weekly.items())),
        },
        "reps": reps_out,
    }

    out_path = DATA_DIR / "coldcalls_context.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"Cold calls context written: {all_total} outbound calls ({period_label})")
    print(f"  Connect rate: {out['global']['connect_rate_pct']}% | "
          f"Meetings detected: {all_meetings} | "
          f"Reps: {len(reps_out)}")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
