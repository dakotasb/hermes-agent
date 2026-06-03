---
name: suggest_project_plan
description: In the Kiri dashboard chat, propose a project, a task-dispatch plan, and an optional team as one-tap approval cards instead of raw kanban tables, task IDs, or @handle lists.
trigger: User expresses a multi-step initiative or project in conversation that needs more than one task or agent (e.g. "launch X", "grow Y", "build Z", "win the market", "hit $50k MRR")
---

# Suggest Project Plan — dashboard chat offer cards

When the user describes an initiative in the Kiri dashboard chat, do **not** dump raw kanban
tables, task IDs (`t_xxxx`), or `@handle` lists. Instead **propose** the work as structured
offer cards the user approves with one tap. The dashboard creates the real kanban tasks when
the user approves — here you only **propose**.

## When this applies
- You are responding in a Kiri gateway chat session (the dashboard companion chat).
- The request implies a project / multiple tasks / a team — not a single status check.

For single status checks or terminal/CLI dispatch, follow `kiri-dispatch-orchestration` as normal.

## What to emit
Write ONE short, warm natural-language sentence first (what you understood + that you've lined
up a plan). Then append the structured blocks at the very **end** of your message, each on its
own line. Emit only valid JSON inside the sentinels. Do **not** wrap them in code fences. Do
**not** also print a markdown task table or task IDs.

### 1. Project — always, when an initiative is proposed
```
<<PROJECT:{"name":"<concise project name, Title Case>","summary":"<one line on what it delivers>","goalId":"<goal-XXXX if it advances an existing goal, else omit the key>"}>>
```

### 2. Task plan — the tasks you would dispatch, pre-assigned
```
<<TASKS:{"projectName":"<same name as the project>","tasks":[{"title":"<imperative title, no @handle prefix, no task IDs>","agentId":"<agent id>","priority":"high|medium|low"}]}>>
```
Include 2–5 tasks. `priority`: `high` = critical path / first, `medium` = supporting, `low` = nice-to-have.

### 3. Team — only if 2+ agents collaborate
```
<<TEAM:{"name":"<team name>","purpose":"<one line>","memberIds":["<agent id>","<agent id>"],"complementarity":<70-95>}>>
```

## Agent ids — use ONLY these (they must match the user's fleet)
`horizon` (research, market intel, competitive analysis) · `forge` (build, code, ship) ·
`ledger` (finance, revenue, budgeting) · `coach` (fitness, habits) · `alloy` (integrations, APIs) ·
`compass` (strategy, routing) · `bastion` (security) · `codex` (codebase intelligence) ·
`palette` (design system) · `surge` (business development, partnerships) · `vault` (project
portfolio, risk) · `archivist` (memory) · `watcher` (monitoring) · `keystone` · `mason` ·
`prism` · `relay` · `scale` · `vantage` · `tempo` · `temper` · `drift` · `harbor` · `haven` ·
`hoard` · `launchpad` · `relic`.

Never invent ids (no `@scope`, no `@ember`). If unsure, use `compass` (strategic router) or `horizon`.

## Rules
- **Propose only** — do NOT run `hermes kanban create` for these. The user's approval in the UI
  dispatches them.
- Keep the natural sentence to ~2 lines. **Never** print raw task IDs, `| Task ID | Agent |`
  tables, or internal dispatch/debug narration ("dispatch syntax", "let me check the pattern").
- Reuse the **same** project name across the PROJECT and TASKS blocks so they link.
- After the user approves (you'll see follow-up context), confirm warmly and point them to the
  orbit or the project board — don't re-list the tasks.

## Example
> Love it — I've lined up a launch plan and a squad to run it.
>
> `<<PROJECT:{"name":"SaaS Launch","summary":"Stand up the new product line and drive it to $50k MRR by Q4."}>>`
> `<<TASKS:{"projectName":"SaaS Launch","tasks":[{"title":"Market research & competitive landscape","agentId":"horizon","priority":"high"},{"title":"Technical feasibility & MVP scoping","agentId":"forge","priority":"medium"},{"title":"Revenue model & pricing tiers","agentId":"ledger","priority":"medium"}]}>>`
> `<<TEAM:{"name":"Launch Squad","purpose":"Research, build, and price the new line","memberIds":["horizon","forge","ledger"],"complementarity":91}>>`
