#!/usr/bin/env bash
# Hermes auto-update for Kiri OS.
#   mode "apply" (default): fetch upstream, auto-merge if clean, abort+flag on conflict.
#   mode "check": fetch + report behind-count only, never merges.
# Writes ~/.hermes/update_status.json for the dashboard UpdateBanner to poll,
# and appends a human log to ~/.hermes/logs/update.log.
set -uo pipefail

REPO="/home/dakotasb/hermes-agent"
HERMES_HOME="/home/dakotasb/.hermes"
STATUS="$HERMES_HOME/update_status.json"
LOG="$HERMES_HOME/logs/update.log"
UPSTREAM="upstream/main"
MODE="${1:-apply}"

mkdir -p "$HERMES_HOME/logs"
cd "$REPO" || { echo "repo missing: $REPO" >&2; exit 1; }

ts()  { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

# args: available behind ahead latestTag applied conflict restartRequired message
write_status() {
  printf '{\n  "available": %s,\n  "behind": %s,\n  "ahead": %s,\n  "latestTag": "%s",\n  "applied": %s,\n  "conflict": %s,\n  "restartRequired": %s,\n  "message": "%s",\n  "lastChecked": "%s"\n}\n' \
    "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$(ts)" > "$STATUS"
}

log "=== run (mode=$MODE) ==="
if ! git fetch upstream --tags --quiet 2>>"$LOG"; then
  log "fetch failed"
  exit 1
fi

BEHIND=$(git rev-list --count "HEAD..$UPSTREAM" 2>/dev/null || echo 0)
AHEAD=$(git rev-list --count "$UPSTREAM..HEAD" 2>/dev/null || echo 0)
TAG=$(git describe --tags --abbrev=0 "$UPSTREAM" 2>/dev/null || echo "unknown")

if [ "$BEHIND" = "0" ]; then
  log "up to date (ahead=$AHEAD, tag=$TAG)"
  write_status false 0 "$AHEAD" "$TAG" false false false "Up to date"
  exit 0
fi

if [ "$MODE" = "check" ]; then
  log "behind=$BEHIND tag=$TAG (check-only)"
  write_status true "$BEHIND" "$AHEAD" "$TAG" false false false "$BEHIND commits behind upstream"
  exit 0
fi

# apply: attempt a clean merge of upstream into the current (custom) branch
BEFORE=$(git rev-parse HEAD)
if git merge --no-edit --no-ff "$UPSTREAM" >>"$LOG" 2>&1; then
  AFTER=$(git rev-parse HEAD)
  if git diff --name-only "$BEFORE" "$AFTER" | grep -qE '^(gateway/|hermes_cli/|cron/)'; then
    RESTART=true;  MSG="Update applied ($BEHIND commits) - gateway restart required"
  else
    RESTART=false; MSG="Update applied ($BEHIND commits)"
  fi
  NB=$(git rev-list --count "HEAD..$UPSTREAM" 2>/dev/null || echo 0)
  NA=$(git rev-list --count "$UPSTREAM..HEAD" 2>/dev/null || echo 0)
  log "merged clean ${BEFORE:0:9}..${AFTER:0:9} restart=$RESTART"
  write_status false "$NB" "$NA" "$TAG" true false "$RESTART" "$MSG"

  # Keep origin/kiri-customizations current so the base-image CI rebuilds
  # the ghcr image with the merged upstream changes. Best-effort; refreshes
  # the base IMAGE only (prod redeploys are a separate kiri-os trigger).
  if git push origin kiri-customizations >>"$LOG" 2>&1; then
    log "pushed kiri-customizations to origin (base image will rebuild)"
  else
    log "push to origin failed (base image not refreshed) - non-fatal"
  fi

  # Note: Restart is NOT performed here to allow drainage check via Kiri.
  # The dashboard UpdateBanner shows "Restart" button when restartRequired=true.
  # User clicks → Kiri runs drainage check → invokes hermes-restart.sh
else
  git merge --abort 2>>"$LOG"
  log "merge conflict against $UPSTREAM - aborted, manual merge needed"
  write_status true "$BEHIND" "$AHEAD" "$TAG" false true false "Update needs manual merge ($BEHIND behind)"
fi
