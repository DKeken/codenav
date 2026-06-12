#!/usr/bin/env python3
"""graphify -> qdrant glue.

Reads graphify-out/graph.json and emits architectural facts as qdrant-store-ready
payloads (JSON lines on stdout). It does NOT call qdrant directly — MCP tools are
callable only by the in-session agent. The agent reads this output and feeds each
record to mcp__qdrant__qdrant-store.

Each fact carries metadata.project (from --project) and metadata.kind=architectural-fact
so a future session can recall the topology without rebuilding the graph.

Usage:
    python3 graphify_to_qdrant.py --graph graphify-out/graph.json --project agonts
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def load_graph(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def god_nodes(g: dict, top: int) -> list[tuple[str, int]]:
    deg: Counter = Counter()
    for link in g.get("links", []):
        deg[link["source"]] += 1
        deg[link["target"]] += 1
    label = {n["id"]: n.get("label", n["id"]) for n in g["nodes"]}
    return [(label.get(nid, nid), c) for nid, c in deg.most_common(top)]


def community_of(g: dict) -> dict[str, int]:
    return {n["id"]: n.get("community", -1) for n in g["nodes"]}


def labels_of(g: dict) -> dict[str, str]:
    return {n["id"]: n.get("label", n["id"]) for n in g["nodes"]}


def bridges(g: dict, top: int) -> list[tuple[str, int]]:
    """Nodes whose neighbours span the most distinct communities."""
    comm = community_of(g)
    span: dict[str, set] = defaultdict(set)
    for link in g.get("links", []):
        s, t = link["source"], link["target"]
        span[s].add(comm.get(t, -1))
        span[t].add(comm.get(s, -1))
    label = labels_of(g)
    ranked = sorted(span.items(), key=lambda kv: len(kv[1]), reverse=True)
    return [(label.get(nid, nid), len(cs)) for nid, cs in ranked[:top]]


def abstract_sizes(g: dict) -> list[tuple[str, int]]:
    """community id -> human label is not stored in graph.json nodes; use community int.
    The skill's re-cluster writes labels to .graphify_labels.json; load if present."""
    sizes: Counter = Counter()
    for n in g["nodes"]:
        sizes[n.get("community", -1)] += 1
    return sizes.most_common()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default="graphify-out/graph.json")
    ap.add_argument("--project", required=True)
    ap.add_argument("--labels", default="graphify-out/.graphify_labels.json")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    g = load_graph(Path(args.graph))
    commit = g.get("built_at_commit", "unknown")

    label_map: dict[str, str] = {}
    lp = Path(args.labels)
    if lp.exists():
        label_map = json.loads(lp.read_text(encoding="utf-8"))

    records: list[dict] = []

    gods = god_nodes(g, args.top)
    records.append({
        "information": "Graph god-nodes (most-connected core abstractions): "
        + ", ".join(f"{name} ({c} edges)" for name, c in gods),
        "metadata": {"project": args.project, "kind": "architectural-fact",
                     "facet": "god-nodes", "built_at_commit": commit},
    })

    brs = bridges(g, args.top)
    records.append({
        "information": "Graph cross-abstract bridges (nodes spanning the most communities): "
        + ", ".join(f"{name} (spans {n})" for name, n in brs),
        "metadata": {"project": args.project, "kind": "architectural-fact",
                     "facet": "bridges", "built_at_commit": commit},
    })

    sizes = abstract_sizes(g)
    named = []
    for cid, n in sizes[:args.top]:
        nm = label_map.get(str(cid), f"community {cid}")
        named.append(f"{nm} ({n} nodes)")
    records.append({
        "information": "Graph canonical abstracts by size: " + ", ".join(named),
        "metadata": {"project": args.project, "kind": "architectural-fact",
                     "facet": "abstracts", "built_at_commit": commit},
    })

    for r in records:
        print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
