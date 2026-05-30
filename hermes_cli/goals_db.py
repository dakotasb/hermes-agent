"""SQLite-backed goal tracking for Hermes.

Goals live at ``~/.hermes/goals.db`` — a sibling to ``kanban.db``.
They are first-class Hermes objects: independent of any dashboard,
readable by any profile, writable by skills via ``hermes goals …``.

Schema
------
goals
    id, title, goal_type, agent_id, category, metric,
    target_value, target_unit, target_date, status, progress,
    created_at, updated_at

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
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    goal_type    TEXT NOT NULL DEFAULT 'milestone',
    agent_id     TEXT,
    category     TEXT,
    metric       TEXT,
    target_value REAL,
    target_unit  TEXT,
    target_date  TEXT,
    status       TEXT NOT NULL DEFAULT 'active',
    progress     INTEGER NOT NULL DEFAULT 0,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL
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
"""

VALID_TYPES    = {"milestone", "frequency", "quantitative"}
VALID_STATUSES = {"active", "paused", "completed", "abandoned"}


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    db_path = goals_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
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
                 target_value, target_unit, target_date,
                 status, progress, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,'active',0,?,?)
            """,
            (gid, title.strip(), goal_type, agent_id, category, metric,
             target_value, target_unit, target_date, now, now),
        )
        conn.commit()
    return get_goal(gid)


def get_goal(goal_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM goals WHERE id=?", (goal_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Goal {goal_id!r} not found")
        return dict(row)


def list_goals(
    status: Optional[str] = "active",
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
        return [dict(r) for r in rows]


def update_progress(
    goal_id: str,
    progress: int,
    *,
    note: Optional[str] = None,
) -> dict[str, Any]:
    progress = max(0, min(100, int(progress)))
    now = int(time.time())
    with connect() as conn:
        row = conn.execute(
            "SELECT progress FROM goals WHERE id=?", (goal_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Goal {goal_id!r} not found")
        old_progress = row[0]
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
