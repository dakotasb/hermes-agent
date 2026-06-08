# MemPalace — canonical Python migration (K41) — repo mirror

Durable runtime artifacts for the MemPalace migration (2026-06-08), mirrored here so
the daily Hermes upstream auto-update can't silently lose them. See the CHANGELOG
entries "[infra] K41 MemPalace migration …" + `D:\Project Alpha\MEMPALACE_MIGRATION_PLAN.md`.

**What changed:** memory moved off the Node fork (Qdrant + Neo4j) to the canonical
**Python `MemPalace/mempalace`** (gemma-q8 embeddings + embedded ChromaDB). Hermes
talks to it over **stdio MCP**; the dashboard reads it via a Python JSON adapter.

## Runtime layout (live locations)
- **Canonical install:** `~/mempalace-py` — clone of `github.com/MemPalace/mempalace`
  (`upstream` remote), branch `kiri-customizations`, editable-installed into a venv:
  `python3 -m venv ~/mempalace-py/.venv && ~/mempalace-py/.venv/bin/pip install -e ~/mempalace-py`.
- **Palace data:** `~/.mempalace/palace` (embedded ChromaDB + SQLite). Config:
  `~/.mempalace/config.json` → `{"palace_path":"…/.mempalace/palace","embedding_model":"embeddinggemma","backend":"chroma"}`.
- **Embedding model:** `embeddinggemma` (= `onnx-community/embeddinggemma-300m-ONNX`, q8, 384-dim), lazy-downloaded to the HF cache on first use.

## Files in this dir (copies of the live runtime files)
| File | Live location |
|---|---|
| `mempalace-update.sh` | `~/.hermes/scripts/mempalace-update.sh` |
| `mempalace-update.service` / `.timer` | `~/.config/systemd/user/` (daily auto-update; `systemctl --user enable --now mempalace-update.timer`) |
| `kiri_adapter.py` | `~/.mempalace/kiri_adapter.py` (kiri-api shells out to it for stats/graph/stage) |

## ⚠️ Hermes config block — RESTORE THIS if an upstream update clears it
Both `~/.hermes/config.yaml` and `~/.hermes/profiles/kiri/config.yaml` have their
`mcp_servers.mempalace` entry pointing at the **stdio** canonical MCP (it was previously
`url: http://localhost:3100/mcp` for the Node fork). If a Hermes update resets it, restore:

```yaml
mcp_servers:
  mempalace:
    command: /home/dakotasb/mempalace-py/.venv/bin/mempalace-mcp
    args:
    - --palace
    - /home/dakotasb/.mempalace/palace
    - --backend
    - chroma
    env:
      MEMPALACE_EMBEDDING_MODEL: embeddinggemma
```

(Hermes' `mcp_tool.py` dispatches `command` → stdio, `url` → http.)

## Dashboard side (lives in dashboard-v2 / `design-v2` — update-safe, no Hermes upstream)
- `api/lib/mempalace.js` — shells out to `kiri_adapter.py` (`getStats`/`getGraph`/`stageFact`), async + 20s TTL cache.
- `api/routes/stats.js` — `memoriesStored`/`byPalace` from the adapter (no longer Qdrant).
- `api/routes/mempalace-update.js` + `server.js` — the `/mempalace-update` status/apply route.
- `hooks/useUpdateAvailable.ts` + `components/shell/UpdateBanner.tsx` — unified update banner (hermes + MemPalace).

## Rollback (legacy Node stack — stopped, not deleted)
Restore `~/.hermes/*.bak-premigrate-*` configs, restart the gateway, then
`systemctl --user start mempalace-mcp` + `docker start mempalace-qdrant mempalace-neo4j`.
