#!/usr/bin/env python3
"""kiri-api ↔ canonical MemPalace JSON adapter.

The canonical MCP is stdio-only and the CLI has no --json, so the Node kiri-api
shells out to this (mirrors goals-db.js → hermes CLI).

NOTE: importing ``mempalace.mcp_server`` triggers its MCP stdio FD-protection
(it expects to BE a stdio MCP server and redirects fd 1). So we duplicate the
real stdout fd *before* importing, route Python-level prints to stderr, and
write the single result-JSON line to the saved fd at the end.

Usage:  python3 kiri_adapter.py {stats|graph|stage} [text]
"""
import os, sys, json

os.environ.setdefault("MEMPALACE_PALACE_PATH", "/home/dakotasb/.mempalace/palace")
os.environ.setdefault("MEMPALACE_EMBEDDING_MODEL", "embeddinggemma")
os.environ.setdefault("MEMPALACE_BACKEND", "chroma")

# Preserve the real stdout fd before mempalace hijacks fd 1, then route all
# Python-level output to stderr so only our final JSON reaches the saved fd.
_OUT_FD = os.dup(1)
sys.stdout = sys.stderr

from mempalace import mcp_server as M  # noqa: E402


def _call(name, *a, **k):
    fn = getattr(M, name, None)
    if not fn:
        return None
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        print(f"[adapter] {name} err: {e}", file=sys.stderr)
        return None


def stats():
    st = _call("tool_status") or {}
    wings = st.get("wings") or {}
    return {"total": st.get("total_drawers", sum(wings.values())), "byPalace": wings}


def graph():
    gs = _call("tool_graph_stats") or {}
    kg = _call("tool_kg_stats") or {}
    tax = (_call("tool_get_taxonomy") or {}).get("taxonomy")
    tl = _call("tool_kg_timeline") or {}
    timeline = tl.get("timeline", []) if isinstance(tl, dict) else []
    nodes, edges = [], []
    for i, t in enumerate(timeline):
        for nid in (t.get("subject"), t.get("object")):
            if nid and all(n["id"] != nid for n in nodes):
                nodes.append({"id": nid, "label": str(nid).replace("agent_org//", "").replace("@", ""), "type": "concept"})
        if t.get("subject") and t.get("object"):
            edges.append({"id": f"e{i}", "source": t["subject"], "target": t["object"], "predicate": t.get("predicate")})
    return {
        "nodes": nodes, "edges": edges, "timeline": timeline, "taxonomy": tax,
        "stats": {
            "entities": kg.get("entities", 0), "triples": kg.get("triples", 0),
            "currentFacts": kg.get("current_facts", 0),
            "relationshipTypes": kg.get("relationship_types", []),
            "palaces": len(((_call("tool_list_wings") or {}).get("wings") or {})),
            "rooms": gs.get("total_rooms", 0),
            "drawers": (_call("tool_status") or {}).get("total_drawers", 0),
            "roomsPerPalace": gs.get("rooms_per_wing", {}),
        },
    }


def stage(text):
    r = _call("tool_add_drawer", wing="kiri", room="staged", content=text, added_by="dashboard")
    return {"ok": bool(r) and not (isinstance(r, dict) and r.get("success") is False)}


cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
if cmd == "stats":
    out = stats()
elif cmd == "graph":
    out = graph()
elif cmd == "stage":
    out = stage(sys.argv[2] if len(sys.argv) > 2 else "")
else:
    out = {"error": f"unknown command {cmd}"}

os.write(_OUT_FD, (json.dumps(out, default=str) + "\n").encode())
