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


# structural re-export files — high degree but not real abstractions
BARRELS = {"index.ts", "index.tsx", "index.js", "index.jsx", "__init__.py", "mod.rs"}


def _disambiguate(node: dict) -> str:
    """A stable display name. Barrel files share a label (index.ts) across the repo,
    so qualify them by parent dir; everything else uses its own label."""
    label = node.get("label", node["id"])
    if label in BARRELS:
        parts = node.get("source_file", "").replace("\\", "/").split("/")
        parent = parts[-2] if len(parts) >= 2 else ""
        return f"{label} ({parent})" if parent else label
    return label


def god_nodes(g: dict, top: int, *, skip_barrels: bool = False) -> list[tuple[str, int]]:
    deg: Counter = Counter()
    for link in g.get("links", []):
        deg[link["source"]] += 1
        deg[link["target"]] += 1
    node_by_id = {n["id"]: n for n in g["nodes"]}
    out: list[tuple[str, int]] = []
    for nid, c in deg.most_common():
        node = node_by_id.get(nid)
        if node is None:
            continue
        if skip_barrels and node.get("label") in BARRELS:
            continue
        out.append((_disambiguate(node), c))
        if len(out) >= top:
            break
    return out


def community_of(g: dict) -> dict[str, int]:
    return {n["id"]: n.get("community", -1) for n in g["nodes"]}


def bridges(g: dict, top: int) -> list[tuple[str, int]]:
    """Nodes linking the most distinct communities (own community included)."""
    comm = community_of(g)
    span: dict[str, set] = defaultdict(set)
    # seed every node with its own community so a bridge counts own + reached
    for nid, c in comm.items():
        span[nid].add(c)
    for link in g.get("links", []):
        s, t = link["source"], link["target"]
        span[s].add(comm.get(t, -1))
        span[t].add(comm.get(s, -1))
    node_by_id = {n["id"]: n for n in g["nodes"]}
    ranked = sorted(span.items(), key=lambda kv: len(kv[1]), reverse=True)
    out: list[tuple[str, int]] = []
    for nid, cs in ranked:
        node = node_by_id.get(nid)
        if node is None:
            continue
        out.append((_disambiguate(node), len(cs)))
        if len(out) >= top:
            break
    return out


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
    ap.add_argument("--skip-barrels", action="store_true",
                    help="exclude index.ts/__init__.py re-export files from god-nodes")
    args = ap.parse_args()

    g = load_graph(Path(args.graph))
    commit = g.get("built_at_commit", "unknown")

    label_map: dict[str, str] = {}
    lp = Path(args.labels)
    if lp.exists():
        label_map = json.loads(lp.read_text(encoding="utf-8"))

    records: list[dict] = []

    gods = god_nodes(g, args.top, skip_barrels=args.skip_barrels)
    facet = "god-nodes (real abstractions)" if args.skip_barrels else "god-nodes"
    records.append({
        "information": f"Graph {facet} (most-connected): "
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
