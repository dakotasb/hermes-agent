# hermes-extension: Native Goal Tracking

This directory contains the PR candidate for adding personal/project goal tracking
as a first-class Hermes feature.

## What's here

| File | Maps to (in upstream PR) | Purpose |
|------|--------------------------|---------|
| `../hermes_cli/goals_db.py` | `hermes_cli/goals_db.py` | SQLite module — `~/.hermes/goals.db` |
| `../hermes_cli/goaltrack.py` | `hermes_cli/goaltrack.py` | CLI module — `hermes goals …` |
| `main.py` patch | `hermes_cli/main.py` | Registers `hermes goals` subcommand |

Skills that use this (Kiri-profile-specific, stay in `kiri/`):
- `~/.hermes/profiles/kiri/skills/suggest_goal/SKILL.md`
- `~/.hermes/profiles/kiri/skills/update_goal/SKILL.md`
- `~/.hermes/profiles/kiri/skills/goal_status/SKILL.md`  (new)

## Design decisions

### Goal types
Three types cover the full range of real goals:

- **milestone** — completion events. Progress from fraction of linked kanban
  tasks done, or manually updated. "Ship v2", "finish the course."
- **frequency** — repeat-based habits. Progress incremented by Kiri each time
  the user reports an activity. "Run 3x/week", "meditate daily."
- **quantitative** — numeric targets. `target_value` + `target_unit` store the
  goal. Progress is user-reported %. "Save $500/month", "lose 10 lbs."

This matters because a single `progress: 0–100` field with no type context
produces nonsense rollup math. A frequency goal at 50% after one week means
something different from a milestone goal at 50%.

### Hermes-native, dashboard-agnostic
Goals live in `~/.hermes/goals.db` — a WAL-mode SQLite file, same pattern as
`kanban.db`. They are:
- Readable by any skill via `hermes goals list --json`
- Writable by any skill via `hermes goals create/update`
- Displayed by the dashboard (which shells out to `hermes goals` — no native
  SQLite compilation required in Node)

The previous approach wrote goals to a dashboard-local `api/data/goals.db` via
HTTP and could only be read through the Express API. Moving the source of truth
to `~/.hermes/` makes goals available everywhere Hermes runs.

### Skills use terminal() not gateway blocks
The old `suggest_goal` / `update_goal` skills emitted `<<GOAL:...>>` and
`<<GOAL_UPDATE:...>>` magic blocks parsed by the gateway, which then called
the dashboard HTTP API. The new skills call `terminal(command="hermes goals …")`
directly. Benefits:
- No gateway special-casing required
- Works in any Hermes deployment (CLI, gateway, discord, API)
- Goal ID available immediately for follow-up queries

### audit log via goal_events
Every progress update and status change appends a row to `goal_events`. This
lets future tooling compute velocity, streaks, and decay curves without
denormalising into the goals row — same philosophy as `kanban_db`'s
`task_events` table.

## What still needs to happen for upstream PR

1. Tests — `tests/gateway/test_goals_db.py` mirroring `test_api_server_boards.py`
2. `hermes goals` needs to appear in `hermes --help` top-level summary
3. `KNOWN_SUBCOMMANDS` in `main.py` already updated (done in this branch)
4. Docs — update `docs/` to mention `hermes goals`
5. Optional: `hermes kanban create --goal <goal-id>` for milestone task linkage

## CLI reference

```
hermes goals list [--status active|paused|completed|abandoned|all] [--json]
hermes goals create --title "..." --type milestone|frequency|quantitative                     [--metric "..."] [--agent <profile>] [--category Health]                     [--target-date YYYY-MM-DD]                     [--target-value 500] [--target-unit "$/month"]
hermes goals update <id> --progress 45 [--note "ran today"]
hermes goals show   <id> [--json]
hermes goals complete <id>
hermes goals abandon  <id>
hermes goals events   <id> [--json]
```

## DB path

Default: `~/.hermes/goals.db`
Override: `HERMES_GOALS_DB` env var (full path) or `HERMES_HOME` env var.
