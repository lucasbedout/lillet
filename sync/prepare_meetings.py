#!/usr/bin/env python3
"""
Assemble meeting analysis context from Claap transcripts + Attio notes.
Reads data/transcripts/ + data/notes/ → outputs data/meetings_context.json

Called by the /meetings skill. Run directly to refresh data.

Usage:
    python prepare_meetings.py              # Last 30 days
    python prepare_meetings.py --days 60
    python prepare_meetings.py --all
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
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
NOTES_DIR = DATA_DIR / "notes"


# ─── Signal detection ────────────────────────────────────────────────────────

OBJECTION_PATTERNS = {
    "Budget / Pricing": [
        r"\bbudget\b", r"trop\s+cher", r"prix\s+[ée]lev", r"pas\s+le\s+budget",
        r"not\s+in\s+(the\s+)?budget", r"too\s+expensive", r"cost\s+concern",
        r"pricing\s+(is|seems|looks)\s+(high|steep)", r"can.{0,20}discount",
        r"(cher|expensive)\s+(pour|for)", r"ROI\s+(not|isn)",
    ],
    "Timing / Not now": [
        r"pas\s+(maintenant|prioritaire|le\s+bon\s+moment)", r"not\s+(right\s+)?now",
        r"not\s+a\s+priority", r"next\s+(quarter|year|semester)",
        r"(Q[1-4]|premier|second)\s+(trimestre|quarter)",
        r"roadmap\s+(20\d{2}|next)", r"revoir\s+(en|dans|après)",
        r"pas\s+prêt", r"not\s+ready", r"too\s+early",
    ],
    "Already have a solution": [
        r"d[ée]j[aà]\s+un\s+(outil|solution|logiciel|système)",
        r"already\s+(have|using|built|implemented)",
        r"(stripe|chargebee|maxio|lago|sequence|pennylane|recurly|zuora|orb)\s+(billing|works|is)",
        r"satisfaits?\s+de", r"satisfied\s+with", r"happy\s+with\s+(our|the|current)",
        r"switching\s+cost", r"coût\s+de\s+(migration|changement)",
    ],
    "Missing feature / Integration": [
        r"(manque|missing)\s+.{0,40}(feature|fonctionnalit|intégration)",
        r"ne\s+(fait|supporte)\s+pas", r"doesn[''`]t\s+(support|do|handle|integrate)",
        r"(salesforce|netsuite|fortnox|datev|sap|oracle|xero|sage)\s+(integration|connect)",
        r"(staircase|phases|SYNTEC|SEPA|EBICS|Avalara|white.?label)",
        r"API\s+(limitation|missing|doesn)", r"webhook\s+(missing|need)",
    ],
    "Internal decision process": [
        r"pas\s+(le\s+)?d[ée]cideur", r"not\s+(the\s+)?(decision|right\s+person)",
        r"(CTO|CFO|CEO|DG|DAF|board|comité)\s+(doit|must|needs?\s+to|will\s+decide)",
        r"(valider|approuver|checker)\s+avec", r"need\s+to\s+(check|confirm|discuss)\s+with",
        r"procurement\s+process", r"(buying|purchase)\s+committee",
        r"internal\s+(review|approval|validation)", r"aligner\s+(en\s+)?interne",
    ],
    "Security / Compliance": [
        r"(security|sécurité)\s+(review|audit|team|concern)",
        r"(compliance|conformité|RGPD|GDPR|SOC\s*2|ISO\s*27001|HIPAA)",
        r"(DPA|data\s+processing)", r"infosec",
        r"(hébergement|hosting)\s+(données|data|EU|France)",
    ],
}

COMPETITIVE_MENTIONS = {
    "Chargebee": [r"\bchargebee\b"],
    "Stripe Billing": [r"stripe\s+billing", r"stripe.{0,20}(invoic|subscript|billing)"],
    "Lago": [r"\blago\b(?!\s+(di|city))"],
    "Maxio": [r"\bmaxio\b", r"\bchargify\b"],
    "Sequence": [r"\bsequence\b(?!\s+(of|diagram))"],
    "Recurly": [r"\brecurly\b"],
    "Zuora": [r"\bzuora\b"],
    "Orb": [r"\borb\b(?!\s+(web|it))"],
    "PandaDoc": [r"\bpandadoc\b"],
    "Salesforce CPQ": [r"salesforce\s+cpq", r"\bSF\s+CPQ\b"],
    "Pennylane": [r"\bpennylane\b"],
    "HubSpot": [r"\bhubspot\b"],
}

PAIN_SIGNALS = {
    "Manual billing": [
        r"(factu|billing|invoic).{0,30}(manuel|manual|galère|pain|tedious|time.?consuming)",
        r"(spreadsheet|excel|google\s+sheet).{0,20}(billing|invoic|factur)",
        r"(manuellement|by\s+hand|à\s+la\s+main)",
    ],
    "Scaling issues": [
        r"(scale|scal|grandissant|growing|growth).{0,30}(billing|invoic|problèm|issue|challenge)",
        r"(volume|transaction).{0,20}(increase|augment|growing)",
        r"ne\s+(scale|tient)\s+pas",
    ],
    "Usage/metering complexity": [
        r"(usage|metering|consumption|consommation).{0,30}(complex|difficul|challenge|problèm)",
        r"(tarification|pricing)\s+(dynamique|variable|usage)",
        r"(event|événement).{0,20}(based|billing|track)",
    ],
    "Quote-to-cash gap": [
        r"(quote|devis).{0,30}(cash|invoice|facturation|automation|automatis)",
        r"(CPQ|quote.?to.?cash|devis.?à.?facture)",
        r"(sales|commercial).{0,20}(quote|proposal|devis)",
    ],
    "Multi-product / hybrid pricing": [
        r"(multi.?product|plusieurs\s+produit|hybrid\s+pric|mix.{0,10}(flat|usage|seat))",
        r"(combinaison|combination).{0,20}(pricing|tarif|abonnement)",
        r"(subscription|abonnement).{0,20}(usage|consommation|variable)",
    ],
    "Revenue recognition": [
        r"(revenue\s+recognition|reconnaissance\s+de\s+revenu|ASC\s+606|IFRS\s+15)",
        r"(comptab|account).{0,20}(complexit|challenge|problèm)",
    ],
}

POSITIVE_SIGNALS = [
    r"int[ée]ress[ée]", r"interested", r"sounds?\s+good", r"looks?\s+great",
    r"ça\s+(m'int|nous\s+int[ée]resse)", r"(great|good|perfect)\s+(fit|match|solution)",
    r"(exactement|exactly)\s+(ce\s+qu[ei]|what)", r"impressive",
    r"(quand|when)\s+(peut-on|can\s+we)\s+(commencer|start|begin|go\s+live)",
    r"(next\s+step|prochaine\s+étape|étape\s+suivante)",
    r"(trial|essai|POC|proof\s+of\s+concept|sandbox|test\s+environment)",
    r"let.{0,10}(move\s+forward|go\s+ahead|proceed|avancer)",
]

NEXT_STEP_SIGNALS = [
    r"(next\s+step|prochaine\s+étape|action\s+item)",
    r"(envoyer|send|share).{0,30}(proposal|devis|quote|pricing|contrat|contract)",
    r"(planifier|schedule|organiser|set\s+up).{0,30}(call|meeting|demo|réunion|appel)",
    r"(revenir|follow\s+up|get\s+back).{0,20}(avec|with|to\s+you)",
    r"(POC|trial|essai|sandbox|test).{0,20}(set|crée|launch|start|mise\s+en\s+place)",
    r"(intro|présent).{0,20}(CTO|CFO|CEO|decision|décideur|tech\s+team|équipe)",
]


def _match(text: str, patterns: list[str]) -> bool:
    t = text.lower()
    return any(re.search(p, t, re.IGNORECASE) for p in patterns)


def _count_matches(text: str, patterns: list[str]) -> int:
    t = text.lower()
    return sum(1 for p in patterns if re.search(p, t, re.IGNORECASE))


def _extract_quotes(text: str, patterns: list[str], max_quotes: int = 2) -> list[str]:
    """Extract short surrounding context around pattern matches."""
    quotes = []
    t_lower = text.lower()
    for p in patterns:
        for m in re.finditer(p, t_lower, re.IGNORECASE):
            start = max(0, m.start() - 60)
            end = min(len(text), m.end() + 60)
            snippet = text[start:end].strip()
            snippet = re.sub(r'\s+', ' ', snippet)
            if snippet and len(snippet) > 15:
                quotes.append(f"...{snippet}...")
                if len(quotes) >= max_quotes:
                    return quotes
    return quotes


# ─── Helpers ─────────────────────────────────────────────────────────────────

def read_transcript_file(filepath: Path) -> dict:
    """Read a Claap transcript file and extract header + body."""
    if not filepath.exists():
        return {}
    text = filepath.read_text(errors="replace")

    # Extract title
    title = ""
    m = re.match(r"# (.+)", text)
    if m:
        title = m.group(1).strip()

    # Extract participants from header
    participants = ""
    m = re.search(r"\*\*Participants:\*\*\s*(.+?)(\s*\||\n)", text)
    if m:
        participants = m.group(1).strip()

    # Extract duration
    duration = ""
    m = re.search(r"\*\*Duration:\*\*\s*(\S+)", text)
    if m:
        duration = m.group(1).strip()

    # Body after the --- separator
    parts = text.split("---", 1)
    body = parts[1].strip() if len(parts) > 1 else text

    return {
        "title": title,
        "participants": participants,
        "duration": duration,
        "body": body,
    }


def load_deals_snapshot() -> dict[str, dict]:
    """Load deals snapshot as name→deal dict for linking."""
    csv_path = DATA_DIR / "deals" / "snapshot.csv"
    if not csv_path.exists():
        return {}
    deals = {}
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").lower().strip()
            if name:
                deals[name] = row
    return deals


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--all", dest="all_time", action="store_true")
    args = parser.parse_args()

    since: Optional[datetime.date] = None
    if not args.all_time:
        since = datetime.date.today() - datetime.timedelta(days=args.days)

    # ── Load Claap transcript index ──────────────────────────────────────────
    index_path = TRANSCRIPTS_DIR / "index.csv"
    if not index_path.exists():
        print("No transcripts index found. Run claap_sync.py first.")
        return

    rows = list(csv.DictReader(open(index_path, encoding="utf-8")))

    # Filter to sales meetings with transcripts
    sales_rows = [
        r for r in rows
        if r.get("category") == "sales"
        and r.get("has_transcript") in ("True", "true", True)
        and r.get("filename")
    ]
    if since:
        sales_rows = [r for r in sales_rows if (r.get("created_at") or "") >= since.isoformat()]

    deals = load_deals_snapshot()

    # ── Analyze each meeting ─────────────────────────────────────────────────
    meetings = []
    global_objections: dict[str, int] = defaultdict(int)
    global_competitors: dict[str, int] = defaultdict(int)
    global_pains: dict[str, int] = defaultdict(int)

    for row in sorted(sales_rows, key=lambda r: r.get("created_at", ""), reverse=True):
        filepath = TRANSCRIPTS_DIR / row["filename"]
        content = read_transcript_file(filepath)
        if not content:
            continue

        body = content.get("body", "")
        full_text = (content.get("title") or "") + " " + body

        # Detect signals
        detected_objections = {}
        for label, patterns in OBJECTION_PATTERNS.items():
            if _match(full_text, patterns):
                quotes = _extract_quotes(body, patterns, max_quotes=1)
                detected_objections[label] = quotes
                global_objections[label] += 1

        detected_competitors = []
        for comp, patterns in COMPETITIVE_MENTIONS.items():
            if _match(full_text, patterns):
                detected_competitors.append(comp)
                global_competitors[comp] += 1

        detected_pains = {}
        for label, patterns in PAIN_SIGNALS.items():
            if _match(full_text, patterns):
                quotes = _extract_quotes(body, patterns, max_quotes=1)
                detected_pains[label] = quotes
                global_pains[label] += 1

        positive = _match(full_text, POSITIVE_SIGNALS)
        has_next_steps = _match(full_text, NEXT_STEP_SIGNALS)

        # Try to link to a deal
        linked_deal = None
        ext_participants = row.get("external_participants", "")
        title = row.get("title", "")
        # Check deal names against meeting title or participants
        for deal_name, deal in deals.items():
            if deal_name in title.lower() or deal_name in ext_participants.lower():
                linked_deal = {
                    "name": deal.get("name"),
                    "stage": deal.get("stage"),
                    "value_eur": deal.get("value_eur"),
                    "owner": deal.get("owner"),
                }
                break

        meeting = {
            "date": row.get("created_at", ""),
            "title": row.get("title", ""),
            "duration_s": row.get("duration_s", ""),
            "external_participants": ext_participants,
            "linked_deal": linked_deal,
            "objections": detected_objections,
            "competitors_mentioned": detected_competitors,
            "pain_points": detected_pains,
            "positive_signal": positive,
            "has_next_steps": has_next_steps,
            "transcript_excerpt": body[:3000] if body else "",
        }
        meetings.append(meeting)

    # ── Aggregate stats ──────────────────────────────────────────────────────
    total = len(meetings)
    with_objections = sum(1 for m in meetings if m["objections"])
    with_competitors = sum(1 for m in meetings if m["competitors_mentioned"])
    with_positive = sum(1 for m in meetings if m["positive_signal"])
    with_next_steps = sum(1 for m in meetings if m["has_next_steps"])

    period_label = "all time" if args.all_time else f"last {args.days} days"

    out = {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "period": period_label,
        "since": since.isoformat() if since else None,
        "summary": {
            "total_sales_meetings": total,
            "with_objections": with_objections,
            "with_competitor_mentions": with_competitors,
            "with_positive_signals": with_positive,
            "with_next_steps": with_next_steps,
        },
        "top_objections": dict(sorted(global_objections.items(), key=lambda x: -x[1])),
        "top_competitors": dict(sorted(global_competitors.items(), key=lambda x: -x[1])),
        "top_pain_points": dict(sorted(global_pains.items(), key=lambda x: -x[1])),
        "meetings": meetings,
    }

    out_path = DATA_DIR / "meetings_context.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"Meetings context written: {total} sales meetings ({period_label})")
    print(f"  Objections in {with_objections} | Competitors in {with_competitors} | "
          f"Positive in {with_positive} | Next steps in {with_next_steps}")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
