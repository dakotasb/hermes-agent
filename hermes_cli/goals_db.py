"""SQLite-backed goal tracking for Hermes.

Goals live at ``~/.hermes/goals.db`` — a sibling to ``kanban.db``.
They are first-class Hermes objects: independent of any dashboard,
readable by any profile, writable by skills via ``hermes goals …``.

Schema
------
goals
    id, title, goal_type, agent_id, category, metric,
    target_value, target_unit, current_value, target_date, status,
    progress, created_at, updated_at

goal_milestones
    OKR-style key results that belong to a goal. Each is either a binary
    "done / not" flag or a numeric current/target measure; together they
    roll up (weighted) into the goal's overall progress, which is written
    back to goals.progress so it stays the canonical 0–100 value regardless
    of which client mutated the key results. Enables cross-device key
    results (the dashboard's client-side tracking store points here).

goal_events
    Append-only audit log for every progress update or status change.
    Lets future tooling reconstruct velocity, streaks, and decay curves
    without denormalising into the goals row.

goal_type
---------
milestone     Work toward a completion event. Progress derived from
              fraction of linked kanban tasks done, or manually updated.
frequency     Repeat-based habits ("3x / week"). Progress incremented
              by Kiri each time the user reports an activity.
quantitative  Numeric target ("save $500 / month"). Target stored in
              target_value + target_unit; progress is user-reported %.

DB path resolution
------------------
Explicit: HERMES_GOALS_DB env var (full path).
Default:  $HERMES_HOME/goals.db  (HERMES_HOME defaults to ~/.hermes).
"""

from __future__ import annotations

import contextlib
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterator, Optional


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


def goals_db_path() -> Path:
    explicit = os.environ.get("HERMES_GOALS_DB")
    if explicit:
        return Path(explicit)
    return _hermes_home() / "goals.db"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS goals (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    goal_type     TEXT NOT NULL DEFAULT 'milestone',
    agent_id      TEXT,
    category      TEXT,
    metric        TEXT,
    target_value  REAL,
    target_unit   TEXT,
    current_value REAL,
    target_date   TEXT,
    status        TEXT NOT NULL DEFAULT 'active',
    progress      INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS goal_events (
    id             TEXT PRIMARY KEY,
    goal_id        TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    note           TEXT,
    progress_delta INTEGER,
    progress_after INTEGER,
    created_at     INTEGER NOT NULL,
    FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS goal_milestones (
    id            TEXT PRIMARY KEY,
    goal_id       TEXT NOT NULL,
    title         TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'binary',   -- 'binary' | 'numeric'
    done          INTEGER NOT NULL DEFAULT 0,
    current_value REAL,
    target_value  REAL,
    unit          TEXT,
    weight        REAL NOT NULL DEFAULT 1,
    position      INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_goal_milestones_goal ON goal_milestones(goal_id);
"""

VALID_TYPES           = {"milestone", "frequency", "quantitative"}
VALID_STATUSES        = {"active", "paused", "completed", "abandoned"}
VALID_MILESTONE_KINDS = {"binary", "numeric"}

# Columns added after the initial release. ``connect()`` runs a guarded
# ``ALTER TABLE`` for any of these missing from an existing goals.db so older
# databases pick them up without a manual migration step.
_GOALS_ADDED_COLUMNS = {"current_value": "REAL"}


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotently add columns introduced after the first release.

    ``CREATE TABLE IF NOT EXISTS`` never alters an existing table, so a
    goals.db created before ``current_value`` existed would be missing it.
    Add any absent column via ``ALTER TABLE`` — cheap, runs once per process
    on first connect, and a no-op once the column is present.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(goals)").fetchall()}
    for col, decl in _GOALS_ADDED_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE goals ADD COLUMN {col} {decl}")
    conn.commit()


@contextlib.contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    db_path = goals_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _migrate(conn)
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------

def _goal_id() -> str:
    return "goal-" + secrets.token_hex(4)


def _event_id() -> str:
    return "ev-" + secrets.token_hex(4)


def _milestone_id() -> str:
    return "kr-" + secrets.token_hex(4)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_goal(
    *,
    title: str,
    goal_type: str = "milestone",
    agent_id: Optional[str] = None,
    category: Optional[str] = None,
    metric: Optional[str] = None,
    target_value: Optional[float] = None,
    target_unit: Optional[str] = None,
    current_value: Optional[float] = None,
    target_date: Optional[str] = None,
) -> dict[str, Any]:
    if goal_type not in VALID_TYPES:
        raise ValueError(f"goal_type must be one of {sorted(VALID_TYPES)}")
    now = int(time.time())
    gid = _goal_id()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO goals
                (id, title, goal_type, agent_id, category, metric,
                 target_value, target_unit, current_value, target_date,
                 status, progress, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,'active',0,?,?)
            """,
            (gid, title.strip(), goal_type, agent_id, category, metric,
             target_value, target_unit, current_value, target_date, now, now),
        )
        conn.commit()
    return get_goal(gid)


def _attach_milestones(conn: sqlite3.Connection, goal: dict[str, Any]) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT * FROM goal_milestones WHERE goal_id=? ORDER BY position, created_at",
        (goal["id"],),
    ).fetchall()
    goal["milestones"] = [dict(r) for r in rows]
    return goal


def get_goal(goal_id: str, *, with_milestones: bool = False) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM goals WHERE id=?", (goal_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Goal {goal_id!r} not found")
        goal = dict(row)
        if with_milestones:
            _attach_milestones(conn, goal)
        return goal


def list_goals(
    status: Optional[str] = "active",
    *,
    with_milestones: bool = False,
) -> list[dict[str, Any]]:
    with connect() as conn:
        if status in (None, "all"):
            rows = conn.execute(
                "SELECT * FROM goals ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM goals WHERE status=? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        goals = [dict(r) for r in rows]
        if with_milestones:
            for g in goals:
                _attach_milestones(conn, g)
        return goals


def update_progress(
    goal_id: str,
    progress: int,
    *,
    note: Optional[str] = None,
    current_value: Optional[float] = None,
) -> dict[str, Any]:
    """Record a progress update (0–100). Optionally also stamp the goal's
    ``current_value`` — the measured numeric value behind a quantitative goal
    (e.g. 3050 for a "$5,000 saved" target), so the figure survives the
    rounding of the integer progress percentage and reads back exactly."""
    progress = max(0, min(100, int(progress)))
    now = int(time.time())
    with connect() as conn:
        row = conn.execute(
            "SELECT progress FROM goals WHERE id=?", (goal_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Goal {goal_id!r} not found")
        old_progress = row[0]
        if current_value is not None:
            conn.execute(
                "UPDATE goals SET progress=?, current_value=?, updated_at=? WHERE id=?",
                (progress, current_value, now, goal_id),
            )
        else:
            conn.execute(
                "UPDATE goals SET progress=?, updated_at=? WHERE id=?",
                (progress, now, goal_id),
            )
        conn.execute(
            """
            INSERT INTO goal_events
                (id, goal_id, event_type, note, progress_delta, progress_after, created_at)
            VALUES (?,?,'progress_update',?,?,?,?)
            """,
            (_event_id(), goal_id, note, progress - old_progress, progress, now),
        )
        conn.commit()
    return get_goal(goal_id)


def set_status(goal_id: str, status: str) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}")
    now = int(time.time())
    with connect() as conn:
        if not conn.execute(
            "SELECT 1 FROM goals WHERE id=?", (goal_id,)
        ).fetchone():
            raise KeyError(f"Goal {goal_id!r} not found")
        conn.execute(
            "UPDATE goals SET status=?, updated_at=? WHERE id=?",
            (status, now, goal_id),
        )
        conn.execute(
            """
            INSERT INTO goal_events
                (id, goal_id, event_type, note, created_at)
            VALUES (?,?,'status_change',?,?)
            """,
            (_event_id(), goal_id, f"status → {status}", now),
        )
        conn.commit()
    return get_goal(goal_id)


def list_events(goal_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        if not conn.execute(
            "SELECT 1 FROM goals WHERE id=?", (goal_id,)
        ).fetchone():
            raise KeyError(f"Goal {goal_id!r} not found")
        rows = conn.execute(
            "SELECT * FROM goal_events WHERE goal_id=? ORDER BY created_at DESC",
            (goal_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Milestones (OKR-style key results)
# ---------------------------------------------------------------------------

def _clamp_pct(n: float) -> float:
    return max(0.0, min(100.0, n))


def milestone_progress(m: dict[str, Any]) -> float:
    """A single milestone's completion as 0–100."""
    if m.get("kind") == "numeric":
        target = m.get("target_value")
        if not target:
            return 0.0
        return _clamp_pct((m.get("current_value") or 0) / target * 100)
    return 100.0 if m.get("done") else 0.0


def rollup_progress(milestones: list[dict[str, Any]]) -> Optional[int]:
    """Weighted-average roll-up of milestones → overall 0–100, or ``None``
    when there are no milestones (the goal's own progress then stands)."""
    if not milestones:
        return None
    total_w = 0.0
    total_p = 0.0
    for m in milestones:
        w = m.get("weight")
        w = 1.0 if w is None else float(w)
        total_w += w
        total_p += w * milestone_progress(m)
    if total_w <= 0:
        return None
    return round(total_p / total_w)


def _resync_goal_progress(conn: sqlite3.Connection, goal_id: str, now: int) -> None:
    """Recompute the goal's progress from its milestones and persist it (with
    an audit event) so ``goals.progress`` stays the canonical 0–100 value no
    matter which client edited the key results. No-op when the goal has none."""
    rows = conn.execute(
        "SELECT * FROM goal_milestones WHERE goal_id=?", (goal_id,)
    ).fetchall()
    roll = rollup_progress([dict(r) for r in rows])
    if roll is None:
        return
    cur = conn.execute("SELECT progress FROM goals WHERE id=?", (goal_id,)).fetchone()
    if cur is None:
        return
    old = cur[0]
    if roll == old:
        conn.execute("UPDATE goals SET updated_at=? WHERE id=?", (now, goal_id))
        return
    conn.execute(
        "UPDATE goals SET progress=?, updated_at=? WHERE id=?",
        (roll, now, goal_id),
    )
    conn.execute(
        """
        INSERT INTO goal_events
            (id, goal_id, event_type, note, progress_delta, progress_after, created_at)
        VALUES (?,?,'key_result_update',?,?,?,?)
        """,
        (_event_id(), goal_id, "rolled up from key results", roll - old, roll, now),
    )


def get_milestone(milestone_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM goal_milestones WHERE id=?", (milestone_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Milestone {milestone_id!r} not found")
        return dict(row)


def list_milestones(goal_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM goals WHERE id=?", (goal_id,)).fetchone():
            raise KeyError(f"Goal {goal_id!r} not found")
        rows = conn.execute(
            "SELECT * FROM goal_milestones WHERE goal_id=? ORDER BY position, created_at",
            (goal_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def add_milestone(
    goal_id: str,
    *,
    title: str,
    kind: str = "binary",
    target_value: Optional[float] = None,
    unit: Optional[str] = None,
    current_value: Optional[float] = None,
    weight: float = 1.0,
    done: bool = False,
) -> dict[str, Any]:
    if kind not in VALID_MILESTONE_KINDS:
        raise ValueError(f"kind must be one of {sorted(VALID_MILESTONE_KINDS)}")
    title = (title or "").strip()
    if not title:
        raise ValueError("milestone title is empty")
    now = int(time.time())
    mid = _milestone_id()
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM goals WHERE id=?", (goal_id,)).fetchone():
            raise KeyError(f"Goal {goal_id!r} not found")
        pos = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM goal_milestones WHERE goal_id=?",
            (goal_id,),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO goal_milestones
                (id, goal_id, title, kind, done, current_value, target_value,
                 unit, weight, position, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (mid, goal_id, title, kind, 1 if done else 0,
             current_value, target_value, unit, float(weight), pos, now, now),
        )
        _resync_goal_progress(conn, goal_id, now)
        conn.commit()
    return get_milestone(mid)


_MILESTONE_FIELDS = {"title", "kind", "done", "current_value", "target_value", "unit", "weight", "position"}


def update_milestone(milestone_id: str, **fields: Any) -> dict[str, Any]:
    """Patch one or more milestone fields, then re-sync the goal's progress.

    Accepts any of: title, kind, done (bool), current_value, target_value,
    unit, weight, position. Unknown keys are rejected.
    """
    unknown = set(fields) - _MILESTONE_FIELDS
    if unknown:
        raise ValueError(f"unknown milestone field(s): {sorted(unknown)}")
    if "kind" in fields and fields["kind"] not in VALID_MILESTONE_KINDS:
        raise ValueError(f"kind must be one of {sorted(VALID_MILESTONE_KINDS)}")
    if not fields:
        return get_milestone(milestone_id)
    now = int(time.time())
    sets, params = [], []
    for key, val in fields.items():
        if key == "done":
            val = 1 if val else 0
        elif key == "title" and val is not None:
            val = str(val).strip()
        elif key == "weight" and val is not None:
            val = float(val)
        sets.append(f"{key}=?")
        params.append(val)
    sets.append("updated_at=?")
    params.append(now)
    with connect() as conn:
        row = conn.execute(
            "SELECT goal_id FROM goal_milestones WHERE id=?", (milestone_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Milestone {milestone_id!r} not found")
        goal_id = row[0]
        conn.execute(
            f"UPDATE goal_milestones SET {', '.join(sets)} WHERE id=?",
            (*params, milestone_id),
        )
        _resync_goal_progress(conn, goal_id, now)
        conn.commit()
    return get_milestone(milestone_id)


def delete_milestone(milestone_id: str) -> str:
    """Delete a milestone and re-sync its goal's progress. Returns the goal id."""
    now = int(time.time())
    with connect() as conn:
        row = conn.execute(
            "SELECT goal_id FROM goal_milestones WHERE id=?", (milestone_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Milestone {milestone_id!r} not found")
        goal_id = row[0]
        conn.execute("DELETE FROM goal_milestones WHERE id=?", (milestone_id,))
        _resync_goal_progress(conn, goal_id, now)
        conn.commit()
    return goal_id
