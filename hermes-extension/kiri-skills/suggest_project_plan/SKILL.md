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
<<PROJECT:{"name":"<concise project name, Title Case>","summary":"<one line on what it delivers>","goalId":"<best-matching goal-XXXX, or omit for a new goal — see Goal association>","targetDate":"<inferred completion, e.g. 'Dec 2026' — see Timing>"}>>
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

## Agent ids — assign to agents IN THE USER'S FLEET
Assign each task to an agent that is **in the user's fleet** (the agents shown in their orbit /
"My Agents"). The fleet is the user's *installed* agents — a subset of the larger catalog — and it
can include agents beyond the defaults below, so do not restrict yourself to a fixed list. When
unsure which agents are in the fleet, check with `hermes profiles list`, or fall back to the agents
already visible in their fleet/orbit.

Role guidance (typical ids, not an exclusive list): `horizon` (research, market intel) ·
`forge` (build, code, ship) · `ledger` (finance, revenue) · `coach` (fitness, habits) ·
`alloy` (integrations, APIs) · `compass` (strategy, routing) · `bastion` (security) ·
`codex` (codebase intelligence) · `palette` (design) · `surge` (business development) ·
`vault` (portfolio, risk) · `mason` · `keystone` · `prism` · `launchpad`.

Rules: use **real** agent ids only (never hallucinate an agent that doesn't exist); assign only to
**fleet** agents, not catalog-only ones the user hasn't installed. If the ideal agent for a task is
in the catalog but not the fleet, assign the closest fleet agent and mention the user could add the
specialist from the catalog. If genuinely unsure, use `compass` (strategic router) or `horizon`.

## Goal association
Do NOT attach a random or loosely-related goal. Before setting `goalId`:
1. Check the user's existing goals (`hermes goals list --json`).
2. If one is a clear match for this initiative, set `goalId` to it (the card shows "Advances <goal>").
3. If none genuinely match, **omit `goalId`** — the project stands alone and may seed a new goal later.
A wrong association is worse than none.

## Timing & sprints
Infer a realistic `targetDate` from the scope and ambition — not a generic default.
- **Simple / direct goals** (one clear outcome): the initial tasks may complete it; set a near target.
- **Complex initiatives** (multi-stage, e.g. "launch a product to $50k MRR"): treat the tasks you emit
  as the **opening sprint**, set a later `targetDate` that reflects the full multi-sprint arc, and say
  so in your one warm sentence ("…this is sprint 1; I'll propose the next phase once these land").
  Do NOT cram an entire complex program into one flat task list — propose the first sprint well.

## Rules
- **Propose only** — do NOT run `hermes kanban create` for these. The user's approval in the UI
  dispatches them.
- **Always end the message with the sentinel block(s)** when you propose an initiative — never
  describe the plan only in prose. The blocks ARE the proposal; prose alone renders no card.
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
