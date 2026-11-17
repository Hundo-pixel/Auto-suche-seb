#!/usr/bin/env bash
# Lokaler Lauf (Raspberry Pi / Docker / eigener Rechner) mit Veröffentlichung über den "data"-Branch.
#
# Voraussetzung: ein Git-Remote mit Schreibrecht (z. B. Deploy-Key oder Fine-grained PAT nur für dieses Repo).
#   REPO_URL=git@github.com:<user>/<repo>.git ./scraper/tools/local_publish.sh
# Danach baut der Workflow "deploy-pages" die Seite automatisch neu.
set -euo pipefail
cd "$(dirname "$0")/../.."
REPO_URL="${REPO_URL:-$(git remote get-url origin)}"
STATE_DIR="${STATE_DIR:-$PWD/.state}"

if [ -d "$STATE_DIR/.git" ]; then
  git -C "$STATE_DIR" fetch -q origin data && git -C "$STATE_DIR" reset -q --hard origin/data || true
else
  git clone -q --branch data --single-branch "$REPO_URL" "$STATE_DIR" 2>/dev/null || {
    mkdir -p "$STATE_DIR" && git -C "$STATE_DIR" init -q && git -C "$STATE_DIR" checkout -q -b data
    git -C "$STATE_DIR" remote add origin "$REPO_URL"
  }
fi
mkdir -p "$STATE_DIR/site"

(cd scraper && python -m autosuche.run --db "$STATE_DIR/autosuche.sqlite" --out "$STATE_DIR/site" "$@") \
  || echo "Scraper meldete Fehler – veröffentliche trotzdem den aktuellen Stand"

cd "$STATE_DIR"
git add -A
git -c user.name="autosuche-bot" -c user.email="autosuche-bot@users.noreply.github.com" \
  commit -q -m "Daten $(date -u +%Y-%m-%dT%H:%MZ)" || echo "keine Änderungen"
git push -q origin data
echo "veröffentlicht."
