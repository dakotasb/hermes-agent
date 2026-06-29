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

# K76: ensure a committer identity exists so `git merge`'s commit step never
# fails on a fresh repo. A missing identity used to abort the merge and get
# mislabeled as a conflict. Repo-local; only set when no identity resolves.
git config user.name  >/dev/null 2>&1 || git config user.name  "Kiri OS Updater"
git config user.email >/dev/null 2>&1 || git config user.email "dakotasb@users.noreply.github.com"

# K77: enable rerere so a once-resolved recurring conflict (e.g. the
# hermes_cli/main.py CLI-subcommand-registration block, which collides every
# upstream merge) is replayed automatically instead of re-flagged each run.
git config rerere.enabled    >/dev/null 2>&1 || git config rerere.enabled    true
git config rerere.autoupdate >/dev/null 2>&1 || git config rerere.autoupdate true

ts()  { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

# args: available behind ahead latestTag applied conflict restartRequired message
write_status() {
  printf '{\n  "available": %s,\n  "behind": %s,\n  "ahead": %s,\n  "latestTag": "%s",\n  "applied": %s,\n  "conflict": %s,\n  "restartRequired": %s,\n  "message": "%s",\n  "lastChecked": "%s"\n}\n' \
    "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$(ts)" > "$STATUS"
}

# Finalize a completed merge: detect whether core dirs changed (→ gateway
# restart required), write the applied status, and push so the base-image CI
# rebuilds the ghcr image. $1 = short note appended to the message (e.g.
# " - rerere-resolved"). Best-effort push (image only; prod redeploy separate).
finalize_applied() {
  local note="$1"
  local AFTER NB NA RESTART MSG
  AFTER=$(git rev-parse HEAD)
  if git diff --name-only "$BEFORE" "$AFTER" | grep -qE '^(gateway/|hermes_cli/|cron/)'; then
    RESTART=true;  MSG="Update applied ($BEHIND commits$note) - gateway restart required"
  else
    RESTART=false; MSG="Update applied ($BEHIND commits$note)"
  fi
  NB=$(git rev-list --count "HEAD..$UPSTREAM" 2>/dev/null || echo 0)
  NA=$(git rev-list --count "$UPSTREAM..HEAD" 2>/dev/null || echo 0)
  log "merge complete ${BEFORE:0:9}..${AFTER:0:9} restart=$RESTART$note"
  write_status false "$NB" "$NA" "$TAG" true false "$RESTART" "$MSG"
  if git push origin kiri-customizations >>"$LOG" 2>&1; then
    log "pushed kiri-customizations to origin (base image will rebuild)"
  else
    log "push to origin failed (base image not refreshed) - non-fatal"
  fi
  # Restart is NOT performed here to allow a drainage check via Kiri. The
  # dashboard UpdateBanner shows a "Restart" button when restartRequired=true;
  # the user clicks -> Kiri runs the drain check -> invokes hermes-restart.sh.
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
  finalize_applied ""
else
  # K77: the merge stopped. With rerere on, a previously-recorded resolution
  # for a recurring conflict may already have been replayed (and, with
  # autoupdate, staged). Decide:
  #   - rerere still has UNRESOLVED conflicts  -> genuinely new, needs a human
  #   - merge in progress, nothing unresolved  -> finish it (self-heal)
  #   - no merge state                         -> non-content failure, retry
  git rerere 2>>"$LOG"
  if [ -n "$(git rerere remaining 2>/dev/null)" ]; then
    git merge --abort 2>>"$LOG"
    log "merge conflict against $UPSTREAM with no recorded rerere resolution - manual merge needed"
    write_status true "$BEHIND" "$AHEAD" "$TAG" false true false "Update needs manual merge ($BEHIND behind)"
  elif [ -f .git/MERGE_HEAD ]; then
    git add -u >>"$LOG" 2>&1
    if git commit --no-edit >>"$LOG" 2>&1; then
      log "rerere auto-resolved recurring conflict; merge completed"
      finalize_applied " - rerere-resolved"
    else
      git merge --abort 2>>"$LOG"
      log "post-rerere commit failed against $UPSTREAM - see log; will retry"
      write_status true "$BEHIND" "$AHEAD" "$TAG" false false false "Update could not be applied automatically - see log"
    fi
  else
    git reset --hard "$BEFORE" >>"$LOG" 2>&1
    log "merge failed (no content conflict) against $UPSTREAM - see log; will retry"
    write_status true "$BEHIND" "$AHEAD" "$TAG" false false false "Update could not be applied automatically - see log"
  fi
fi
