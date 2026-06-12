#!/usr/bin/env python3
"""Re-cluster a graphify graph into project-canonical abstracts.

graphify's Louvain clustering over-fragments a sparse AST-only graph. When the
project already has a canonical architecture (layers, bounded contexts), re-cluster
by THAT taxonomy: map every node to an abstract by its source path, then regenerate
graph.json + report + HTML.

Provide your own taxonomy by copying taxonomy.example.py and editing classify().

Usage:
    python3 recluster.py --map taxonomy.py
    python3 recluster.py --map taxonomy.py --graph graphify-out/graph.json
"""
import argparse
import importlib.util
import json
from pathlib import Path

import networkx as nx
from graphify.cluster import score_all
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.report import generate
from graphify.export import to_json


def load_classifier(map_path: Path):
    spec = importlib.util.spec_from_file_location("codenav_taxonomy", map_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load taxonomy module: {map_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "classify"):
        raise SystemExit("taxonomy module must define classify(source_file: str) -> str")
    return mod.classify


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True, help="path to a taxonomy module with classify()")
    ap.add_argument("--graph", default="graphify-out/graph.json")
    ap.add_argument("--out", default="graphify-out/graph.json")
    args = ap.parse_args()

    classify = load_classifier(Path(args.map))
    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    G = nx.node_link_graph(g, edges="links")

    buckets: dict[str, list[str]] = {}
    for nid, data in G.nodes(data=True):
        b = classify(data.get("source_file", ""))
        buckets.setdefault(b, []).append(nid)

    ordered = sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)
    communities: dict[int, list[str]] = {}
    labels: dict[int, str] = {}
    for cid, (bname, nodes) in enumerate(ordered):
        communities[cid] = nodes
        labels[cid] = bname
        for nid in nodes:
            G.nodes[nid]["community"] = cid

    cohesion = score_all(G, communities)
    gods = god_nodes(G)
    surprises = surprising_connections(G, communities)
    questions = suggest_questions(G, communities, labels)
    detection = {"total_files": 0, "files": {}, "total_words": 0}
    commit = g.get("built_at_commit")

    out_dir = Path(args.out).parent
    report = generate(G, communities, cohesion, labels, gods, surprises,
                      detection, {"input": 0, "output": 0}, ".",
                      suggested_questions=questions, built_at_commit=commit)
    (out_dir / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
    to_json(G, communities, args.out, force=True, built_at_commit=commit)
    (out_dir / ".graphify_labels.json").write_text(
        json.dumps({str(k): v for k, v in labels.items()}, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Re-clustered into {len(communities)} canonical abstracts:")
    for bname, nodes in ordered:
        print(f"  {len(nodes):5d}  {bname}")


if __name__ == "__main__":
    main()
