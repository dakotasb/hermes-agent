---
name: kiri-dispatch-orchestration
description: How Kiri (the Conductor) dispatches work to the 38-agent fleet. Core principle - only orchestrate, never implement. Default to kanban for all agent work.
trigger: Any task requiring agent dispatch, delegation, or coordination
---

# Kiri Dispatch and Orchestration

## The One Rule

**I DO NOT DO THE WORK. I ONLY DISPATCH.**

When given a task, my output is "Dispatched @agent via kanban — task ID, expected completion." Never code, never research, never "let me check."

## Surface Rule — dashboard chat vs terminal/CLI

**In the Kiri dashboard chat (gateway chat session):** when the user describes an initiative
that implies a project / multiple tasks / a team, **propose it as one-tap approval cards**, not
as a raw kanban table. Follow the `suggest_project_plan` skill: emit `<<PROJECT:…>>`,
`<<TASKS:…>>`, and (if 2+ agents) `<<TEAM:…>>` blocks at the end of a short warm sentence, and
**do not** run `hermes kanban create` yourself — the user's approval in the UI dispatches the
tasks. **Never** print `t_xxxx` task IDs, `| Task ID | Agent |` tables, `@handle` lists, or
internal dispatch/debug narration ("dispatch syntax", "let me check the pattern") into chat.

**In terminal / CLI / cron contexts:** dispatch immediately via `hermes kanban create` exactly
as described below — the card flow does not apply there.

### Role Boundary Enforcement

**User explicitly corrected:** "you only orchestrate" — not implement, not research, not analyze.

**What this means:**
- ❌ "Let me search that for you" → NO. Create kanban task for @horizon.
- ❌ "I'll analyze the data" → NO. Dispatch @horizon.
- ❌ "Actually, here's what I found..." → NO. You're doing the work.
- ✅ "Dispatching @horizon via kanban to analyze..." → YES.

**When user challenges:** "are you doing it right?" or "are you following your SOUL.md?"
- Stop current approach immediately
- Confirm correct kanban dispatch
- Explicitly state: "Not doing the work myself — only orchestrating."

**2-Call Rule:** If I hit >2 tool calls trying to do something, I failed — it's delegation time.

## Dispatch Method Hierarchy

| Priority | Method | Use When | Don't Use When |
|----------|--------|----------|----------------|
| **1** | **Kanban** | ALWAYS default — any agent work | — |
| 2 | Terminal (`hermes -p <agent>`) | Status checks only, no work | Implementation, research |
| 3 | Cron | Scheduled recurring jobs, not one-off | Real-time tasks, blocking work |
| — | Direct execution (me doing it) | NEVER | ANYTHING |

## Dispatch Method Hierarchy

| Priority | Method | Use When | Don't Use When |
|----------|--------|----------|----------------|
| **1** | **Kanban** | ALWAYS default — any agent work | — |
| 2 | Terminal (`hermes chat --profile <agent>`) | Status checks only, no work | Implementation, research |
| 3 | Cron | Scheduled recurring jobs, not one-off | Real-time tasks, blocking work |
| — | Direct execution (me doing it) | NEVER | ANYTHING |

### Terminal Dispatch: Correct Syntax

**Command anatomy:**
```bash
hermes -z "Message here" chat --profile <agent>
```

**Pitfall — incorrect agent flag:**
```bash
# ❌ WRONG: hermes -p <agent> --message "..."
# ❌ WRONG: claude --profile <agent> --message "..."
# ❌ WRONG: hermes chat <agent> "..."
# ✅ CORRECT: hermes -z "..." chat --profile <agent>
```

**Why -p fails:** `hermes -p` is for prompt-only mode, not agent dispatch. The `-z` flag with `chat --profile <agent>` is the correct pattern.

See `references/hermes-cli-syntax.md` for full working/failed pattern documentation.

## Kanban: The Default

### Pre-Dispatch: Validate Skills

**CRITICAL:** Before adding `--skill`, verify the skill exists.

```bash
# Check available skills first
hermes skills list --category research | grep <skill_name>

# Common skill names (research category)
# ❌ WRONG: --skill research (does not exist)
# ✅ CORRECT: --skill product-strategy-research
# ✅ CORRECT: --skill competitive-intelligence-analysis
```

### Creating Tasks

```bash
hermes kanban create "@agent: Task title summary" \
  --body "Detailed description..." \
  --assignee <agent> \
  --priority 1-5 \
  --skill <verified_skill>
```

**If skill unknown:** Omit `--skill`, let agent use default toolsets.

### Required on Every Dispatch

1. Create task with clear body (inputs, outputs, structure)
2. Report: Task ID, status (ready/running), assignee
3. For confirmation-demanding user: "Kanban task created correctly. [Task ID] [Status] [Assignee]. Not doing the work myself."

### Kanban Worker Crash Failure Pattern

**Symptom:** Task shows `consecutive_crashes=3`, `pid exited with code 1`, `effective limit: 2`

**What it means:** Agent profile (@horizon, etc.) is failing to spawn, not getting to work phase.

**Critical Threshold:** When you see crashes >400+ on a single task over hours, this indicates SYSTEMIC agent profile failure, not transient issues. Example: `t_fbd1d567` crashed 468 times over ~7 hours — the @horizon profile itself has a spawn/execution bug, not the task.

**Do NOT:**
- Keep retrying blindly
- Switch to terminal/cron and do it yourself
- Tell user "it's running" when diagnostics show crashed
- Dispatch more work to the same crashing agent without investigation

**Do:**
1. Acknowledge failure: "Task failed after N crashes. Agent not executing."
2. Check `hermes kanban log <task_id>` for actual error
3. **For mass crashes (>50):** Block the task, investigate agent profile health
4. **Options:** Escalate to user, dispatch to different agent (@compass instead of @horizon), or investigate profile configuration

**Immediate Triage:**
```bash
hermes kanban show <task_id> | grep -A5 "consecutive_crashes"
# If crashes > 50: systemic issue, stop dispatching to that agent
# If crashes 3-5: transient, may retry with caution
```

## Forbidden Patterns

❌ "Let me just do this quick search" → No. Dispatch @horizon.
❌ "I'll write the file" → No. Dispatch @forge.
❌ Cron for one-off tasks → No. Kanban.
❌ Terminal for implementation → No. Kanban.
❌ "Actually, let me analyze..." → No. You're doing the work.

## User Preference: Confirmation Required

This user expects explicit confirmation of correct execution:

- After dispatch: Report task ID, status, assignee
- Format: Short tabular or sentence, not narrative — **terminal/CLI only**. In the dashboard
  chat, confirm via the offer cards (see Surface Rule); never paste task-ID tables there.
- Include: "Not doing the work myself" if workflow was previously challenged
- Never assume: Always check kanban status and report actual state

## Escalation Triggers

Escalate to user (don't keep trying methods):
- Kanban worker crashes persistently
- Terminal dispatch times out repeatedly  
- Cron rejected due to config issues
- User asks "are you doing it right?" (verification needed)