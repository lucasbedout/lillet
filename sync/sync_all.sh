#!/bin/bash
# Run a full sync: Attio deals + notes, Claap transcripts, weekly digest.
#
# Usage:
#   ./sync/sync_all.sh              # Full sync, last 7-day digest
#   ./sync/sync_all.sh --no-notes   # Skip notes (faster)
#   ./sync/sync_all.sh --days 30    # Generate 30-day digest
#   CLAAP_ONLY=1 ./sync/sync_all.sh # Claap only

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv if present
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
elif [ -f "../.venv/bin/activate" ]; then
  source ../.venv/bin/activate
fi

NOTES_FLAG=""
DIGEST_DAYS=7

for arg in "$@"; do
  case $arg in
    --no-notes) NOTES_FLAG="--no-notes" ;;
    --days=*) DIGEST_DAYS="${arg#*=}" ;;
    --days) shift; DIGEST_DAYS="$1" ;;
  esac
done

echo "=== Sales Data Sync — $(date '+%Y-%m-%d %H:%M') ==="
echo ""

if [ -z "$CLAAP_ONLY" ]; then
  echo ">>> Attio sync..."
  python attio_sync.py $NOTES_FLAG
  echo ""
fi

if [ -z "$ATTIO_ONLY" ] && [ -n "$CLAAP_API_KEY" ]; then
  echo ">>> Claap sync (last 30 days)..."
  python claap_sync.py --days 30
  echo ""
elif [ -z "$ATTIO_ONLY" ]; then
  echo ">>> Skipping Claap (CLAAP_API_KEY not set)"
  echo ""
fi

if [ -z "$ATTIO_ONLY" ] && [ -n "$ALLO_API_KEY" ]; then
  echo ">>> Allo sync (last 30 days)..."
  python allo_sync.py --days 30
  echo ""
elif [ -z "$ATTIO_ONLY" ]; then
  echo ">>> Skipping Allo (ALLO_API_KEY not set)"
  echo ""
fi

echo ">>> Generating digest (last ${DIGEST_DAYS} days)..."
python generate_digest.py --days "$DIGEST_DAYS"
echo ""

echo "=== Sync complete. ==="
echo "Main output: data/context.md"
