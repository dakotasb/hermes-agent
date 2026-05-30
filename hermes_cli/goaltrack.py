"""CLI for Hermes user goal tracking — ``hermes goals …`` subcommand.

Note on naming: ``goals.py`` is taken by the session goal-loop (Ralph loop)
module. This module provides the personal/project goal tracking surface that
writes to ``~/.hermes/goals.db``. The subcommand is still ``hermes goals``.

Subcommands
-----------
list     List goals (default: active only).
create   Create a new goal.
update   Record a progress update.
show     Print a single goal in detail.
complete Mark a goal as completed (progress → 100).
abandon  Mark a goal as abandoned.
events   Show the audit log for a goal.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from hermes_cli import goals_db as gdb


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_STATUS_ICONS = {
    "active":    "●",
    "paused":    "⏸",
    "completed": "✓",
    "abandoned": "✗",
}

_TYPE_LABELS = {
    "milestone":    "Milestone",
    "frequency":    "Frequency",
    "quantitative": "Quantitative",
}


def _fmt_ts(ts: int | None) -> str:
    if not ts:
        return ""
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _progress_bar(pct: int, width: int = 20) -> str:
    filled = round(width * pct / 100)
    return "[" + "█" * filled + "░" * (width - filled) + f"] {pct}%"


def _fmt_goal_line(g: dict[str, Any]) -> str:
    icon  = _STATUS_ICONS.get(g["status"], "?")
    gtype = _TYPE_LABELS.get(g["goal_type"], g["goal_type"])
    agent = g.get("agent_id") or "—"
    cat   = g.get("category") or "—"
    date  = g.get("target_date") or "—"
    pbar  = _progress_bar(g.get("progress", 0))
    return (
        f"{icon} {g['id']}  [{gtype}]  agent={agent}  cat={cat}  due={date}\n"
        f"    {g['title']}\n"
        f"    {pbar}"
    )


def _fmt_goal_detail(g: dict[str, Any]) -> str:
    lines = [
        f"ID:       {g['id']}",
        f"Title:    {g['title']}",
        f"Type:     {_TYPE_LABELS.get(g['goal_type'], g['goal_type'])}",
        f"Status:   {g['status']}",
        f"Progress: {_progress_bar(g.get('progress', 0))}",
        f"Agent:    {g.get('agent_id') or '—'}",
        f"Category: {g.get('category') or '—'}",
        f"Metric:   {g.get('metric') or '—'}",
    ]
    if g.get("target_value") is not None:
        lines.append(f"Target:   {g['target_value']} {g.get('target_unit') or ''}")
    lines += [
        f"Due:      {g.get('target_date') or '—'}",
        f"Created:  {_fmt_ts(g.get('created_at'))}",
        f"Updated:  {_fmt_ts(g.get('updated_at'))}",
    ]
    return "\n".join(lines)


def _fmt_event_line(ev: dict[str, Any]) -> str:
    ts    = _fmt_ts(ev.get("created_at"))
    etype = ev.get("event_type", "?")
    note  = ev.get("note") or ""
    delta = ev.get("progress_delta")
    after = ev.get("progress_after")
    parts = [f"{ts}  [{etype}]"]
    if delta is not None and after is not None:
        sign = "+" if delta >= 0 else ""
        parts.append(f"progress {sign}{delta}% → {after}%")
    if note:
        parts.append(note)
    return "  ".join(parts)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_list(args: argparse.Namespace) -> int:
    status = "all" if getattr(args, "all", False) else args.status
    goals = gdb.list_goals(status=status)
    if not goals:
        print("No goals found.")
        return 0
    if args.json:
        print(json.dumps(goals, indent=2))
        return 0
    for g in goals:
        print(_fmt_goal_line(g))
        print()
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    try:
        goal = gdb.create_goal(
            title=args.title,
            goal_type=args.type,
            agent_id=args.agent or None,
            category=args.category or None,
            metric=args.metric or None,
            target_value=args.target_value,
            target_unit=args.target_unit or None,
            target_date=args.target_date or None,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(goal, indent=2))
        return 0
    print(f"Created goal {goal['id']}")
    print(_fmt_goal_detail(goal))
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    try:
        goal = gdb.update_progress(
            args.id, args.progress, note=args.note or None
        )
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(goal, indent=2))
        return 0
    print(f"Updated {goal['id']}")
    print(_progress_bar(goal["progress"]))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    try:
        goal = gdb.get_goal(args.id)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(goal, indent=2))
        return 0
    print(_fmt_goal_detail(goal))
    return 0


def cmd_complete(args: argparse.Namespace) -> int:
    try:
        gdb.update_progress(args.id, 100, note="marked complete")
        goal = gdb.set_status(args.id, "completed")
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"✓ Goal {goal['id']} completed.")
    return 0


def cmd_abandon(args: argparse.Namespace) -> int:
    try:
        goal = gdb.set_status(args.id, "abandoned")
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Goal {goal['id']} abandoned.")
    return 0


def cmd_events(args: argparse.Namespace) -> int:
    try:
        events = gdb.list_events(args.id)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(events, indent=2))
        return 0
    if not events:
        print("No events recorded yet.")
        return 0
    for ev in events:
        print(_fmt_event_line(ev))
    return 0


# ---------------------------------------------------------------------------
# Parser construction (called from main.py)
# ---------------------------------------------------------------------------

def build_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "goals",
        help="Personal and project goal tracking (hermes goals …)",
        description=(
            "Create and track goals stored in ~/.hermes/goals.db. "
            "Goals are independent of any dashboard and readable by all skills."
        ),
    )
    sub = p.add_subparsers(dest="goals_command")

    # -- list --
    pl = sub.add_parser("list", help="List goals")
    pl.add_argument(
        "--status",
        default="active",
        choices=["active", "paused", "completed", "abandoned", "all"],
        help="Filter by status (default: active)",
    )
    pl.add_argument("--all",  action="store_true", help="Shorthand for --status all")
    pl.add_argument("--json", action="store_true", help="Output JSON")

    # -- create --
    pc = sub.add_parser("create", help="Create a new goal")
    pc.add_argument("--title",        required=True,  help="Goal title (max 80 chars)")
    pc.add_argument("--type",         dest="type",    default="milestone",
                    choices=["milestone", "frequency", "quantitative"],
                    help="Goal type (default: milestone)")
    pc.add_argument("--metric",       default="",     help="Success criteria (free text)")
    pc.add_argument("--agent",        default="",     help="Owning agent profile ID")
    pc.add_argument("--category",     default="",     help="Category (Health, Finance, …)")
    pc.add_argument("--target-date",  default="",     help="Target date (YYYY-MM-DD)")
    pc.add_argument("--target-value", type=float,     default=None,
                    help="Numeric target for quantitative goals")
    pc.add_argument("--target-unit",  default="",
                    help="Unit for target-value (e.g. '$/month', 'sessions/week')")
    pc.add_argument("--json", action="store_true",    help="Output JSON")

    # -- update --
    pu = sub.add_parser("update", help="Record a progress update")
    pu.add_argument("id",         help="Goal ID (e.g. goal-a1b2c3d4)")
    pu.add_argument("--progress", type=int, required=True, help="New progress (0–100)")
    pu.add_argument("--note",     default="", help="Optional note for the event log")
    pu.add_argument("--json",     action="store_true", help="Output JSON")

    # -- show --
    ps = sub.add_parser("show", help="Show goal details")
    ps.add_argument("id",   help="Goal ID")
    ps.add_argument("--json", action="store_true", help="Output JSON")

    # -- complete --
    pco = sub.add_parser("complete", help="Mark a goal as completed (progress → 100)")
    pco.add_argument("id", help="Goal ID")

    # -- abandon --
    pab = sub.add_parser("abandon", help="Mark a goal as abandoned")
    pab.add_argument("id", help="Goal ID")

    # -- events --
    pev = sub.add_parser("events", help="Show progress audit log")
    pev.add_argument("id",   help="Goal ID")
    pev.add_argument("--json", action="store_true", help="Output JSON")

    return p


# ---------------------------------------------------------------------------
# Dispatcher (called by cmd_goals in main.py)
# ---------------------------------------------------------------------------

_HANDLERS = {
    "list":     cmd_list,
    "create":   cmd_create,
    "update":   cmd_update,
    "show":     cmd_show,
    "complete": cmd_complete,
    "abandon":  cmd_abandon,
    "events":   cmd_events,
}


def goals_command(args: argparse.Namespace) -> int:
    sub = getattr(args, "goals_command", None)
    if not sub:
        print(
            "usage: hermes goals <subcommand>\n\n"
            "Subcommands: " + ", ".join(_HANDLERS),
            file=sys.stderr,
        )
        return 1
    handler = _HANDLERS.get(sub)
    if handler is None:
        print(f"Unknown goals subcommand: {sub}", file=sys.stderr)
        return 1
    return handler(args)
