#!/usr/bin/env bash
# MemPalace auto-update for Kiri OS — mirrors hermes-update.sh.
#   mode "apply" (default): fetch upstream, auto-merge if clean, abort+flag on conflict.
#   mode "check": fetch + report behind-count only.
# Writes ~/.hermes/mempalace_update_status.json (dashboard banner polls it) +
# ~/.hermes/logs/mempalace-update.log. No daemon to restart — the canonical is a
# per-session stdio MCP + per-call adapter, so an editable reinstall is live at once.
set -uo pipefail
REPO="/home/dakotasb/mempalace-py"
HOME_H="/home/dakotasb/.hermes"
STATUS="$HOME_H/mempalace_update_status.json"
LOG="$HOME_H/logs/mempalace-update.log"
UPSTREAM="upstream/main"
MODE="${1:-apply}"
mkdir -p "$HOME_H/logs"
cd "$REPO" || { echo "repo missing: $REPO" >&2; exit 1; }
ts()  { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$(ts)] $*" >> "$LOG"; }
write_status() {
  printf '{\n  "available": %s,\n  "behind": %s,\n  "ahead": %s,\n  "latestTag": "%s",\n  "applied": %s,\n  "conflict": %s,\n  "restartRequired": %s,\n  "message": "%s",\n  "lastChecked": "%s"\n}\n' \
    "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$(ts)" > "$STATUS"
}
log "=== run (mode=$MODE) ==="
if ! git fetch upstream --tags --quiet 2>>"$LOG"; then log "fetch failed"; exit 1; fi
BEHIND=$(git rev-list --count "HEAD..$UPSTREAM" 2>/dev/null || echo 0)
AHEAD=$(git rev-list --count "$UPSTREAM..HEAD" 2>/dev/null || echo 0)
TAG=$(git describe --tags --abbrev=0 "$UPSTREAM" 2>/dev/null || echo "unknown")
if [ "$BEHIND" = "0" ]; then
  log "up to date (ahead=$AHEAD, tag=$TAG)"
  write_status false 0 "$AHEAD" "$TAG" false false false "Up to date"; exit 0
fi
if [ "$MODE" = "check" ]; then
  log "behind=$BEHIND tag=$TAG (check-only)"
  write_status true "$BEHIND" "$AHEAD" "$TAG" false false false "$BEHIND commits behind upstream"; exit 0
fi
BEFORE=$(git rev-parse HEAD)
if git merge --no-edit --no-ff "$UPSTREAM" >>"$LOG" 2>&1; then
  AFTER=$(git rev-parse HEAD)
  "$REPO/.venv/bin/pip" install -q -e "$REPO" >>"$LOG" 2>&1 || log "pip reinstall warned"
  NB=$(git rev-list --count "HEAD..$UPSTREAM" 2>/dev/null || echo 0)
  NA=$(git rev-list --count "$UPSTREAM..HEAD" 2>/dev/null || echo 0)
  log "merged clean ${BEFORE:0:9}..${AFTER:0:9}"
  write_status false "$NB" "$NA" "$TAG" true false false "Update applied ($BEHIND commits)"
else
  git merge --abort 2>>"$LOG"
  log "merge conflict against $UPSTREAM - aborted, manual merge needed"
  write_status true "$BEHIND" "$AHEAD" "$TAG" false true false "Update needs manual merge ($BEHIND behind)"
fi
