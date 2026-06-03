# kiri-skills — dashboard chat offer cards

Mirror of the Kiri-profile skills that drive the dashboard chat "offer card" UX
(project / task-dispatch / team), kept here so the customization is version-controlled
and PR-stageable. Runtime copies live in `~/.hermes/skills/`.

| Skill | Runtime path | Purpose |
|-------|--------------|---------|
| `suggest_project_plan/SKILL.md` | `~/.hermes/skills/suggest_project_plan/` | Propose project + task plan + team as `<<PROJECT>>` / `<<TASKS>>` / `<<TEAM>>` blocks for one-tap approval |
| `agent_org/kiri-dispatch-orchestration/SKILL.md` | `~/.hermes/skills/agent_org/kiri-dispatch-orchestration/` | Adds the "Surface Rule": in dashboard chat, propose via cards (not raw kanban tables); terminal/CLI dispatch unchanged |

## Mechanism (aligned with the Hermes-native direction)

- The sentinels are emitted in the assistant message and parsed **client-side** in the
  dashboard (`lib/chat-context.tsx`) — there is **no gateway special-casing**. The objection
  that retired the old `<<GOAL>>` path (gateway had to parse the block) does not apply here.
- On approval, the dashboard writes through the **Hermes-native CLI**: `kiri-api` shells out to
  `hermes kanban` / `hermes goals`. Source of truth stays `~/.hermes/*.db`.
- **No core-Hermes files are patched** — the change is isolated to Kiri-profile skills plus the
  dashboard repo, so it stays a clean, staged PR on `kiri-customizations`.

## Sentinel formats (must match the dashboard parser)

```
<<PROJECT:{"name":"...","summary":"...","goalId":"goal-XXXX (optional)"}>>
<<TASKS:{"projectName":"...","tasks":[{"title":"...","agentId":"...","priority":"high|medium|low"}]}>>
<<TEAM:{"name":"...","purpose":"...","memberIds":["...","..."],"complementarity":91}>>
```

`agentId` / `memberIds` must be ids the dashboard fleet recognizes (see the skill for the list);
never invent ids such as `@scope` or `@ember`.
