#!/usr/bin/env python3
"""beacon -> graphify glue.

Given a file path (a beacon semantic-search hit), situate it in the graph:
which canonical abstract does it belong to, and which other abstracts do its
symbols bridge to? Turns a flat retrieval hit into a topological one.

Runs entirely off graphify-out/graph.json — no MCP calls. The agent runs beacon,
passes each hit's file path here, and gets back the abstract + bridges to decide
whether the hit is central or peripheral.

Usage:
    python3 beacon_enrich.py --file apps/api/src/modules/ai/chat/engine/loop.ts
    python3 beacon_enrich.py --file <path> --graph graphify-out/graph.json
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--graph", default="graphify-out/graph.json")
    ap.add_argument("--labels", default="graphify-out/.graphify_labels.json")
    args = ap.parse_args()

    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    labels: dict[str, str] = {}
    lp = Path(args.labels)
    if lp.exists():
        labels = json.loads(lp.read_text(encoding="utf-8"))

    needle = args.file.replace("\\", "/").lstrip("./")
    comm_of = {n["id"]: n.get("community", -1) for n in g["nodes"]}
    label_of = {n["id"]: n.get("label", n["id"]) for n in g["nodes"]}

    def same_file(node_sf: str) -> bool:
        sf = node_sf.replace("\\", "/")
        # exact path, or needle is a trailing path segment of sf (or vice-versa)
        return sf == needle or sf.endswith("/" + needle) or needle.endswith("/" + sf)

    # nodes living in this file
    in_file = [n for n in g["nodes"] if same_file(n.get("source_file", ""))]
    if not in_file:
        print(json.dumps({"file": needle, "found": False,
                          "note": "no graph nodes for this file — run graphify update ."}))
        return

    # guard: a bare filename ("service.ts") can match many distinct files.
    # Report the candidates instead of silently merging them into one fake file.
    distinct = sorted({n.get("source_file", "").replace("\\", "/") for n in in_file})
    if len(distinct) > 1:
        print(json.dumps({
            "file": needle, "found": False, "ambiguous": True,
            "note": f"{len(distinct)} files match — pass a fuller path to disambiguate",
            "candidates": distinct[:20],
        }, ensure_ascii=False, indent=2))
        return

    ids = {n["id"] for n in in_file}
    own_comms = {comm_of[n["id"]] for n in in_file}
    own_abstracts = sorted({labels.get(str(c), f"community {c}") for c in own_comms})

    # which abstracts do this file's symbols connect out to?
    span: set = set()
    neighbours: dict[str, set] = defaultdict(set)
    for link in g.get("links", []):
        s, t = link["source"], link["target"]
        if s in ids and t not in ids:
            c = comm_of.get(t, -1)
            span.add(c)
            neighbours[labels.get(str(c), f"community {c}")].add(label_of.get(t, t))
        elif t in ids and s not in ids:
            c = comm_of.get(s, -1)
            span.add(c)
            neighbours[labels.get(str(c), f"community {c}")].add(label_of.get(s, s))

    bridges_out = sorted(
        ((abst, sorted(syms)[:5]) for abst, syms in neighbours.items()
         if abst not in own_abstracts),
        key=lambda kv: len(kv[1]), reverse=True,
    )

    out = {
        "file": needle,
        "found": True,
        "symbols": sorted(label_of[n["id"]] for n in in_file)[:20],
        "lives_in": own_abstracts,
        "bridges_to": [{"abstract": a, "via": syms} for a, syms in bridges_out[:8]],
        "centrality_hint": f"connects to {len(span)} distinct abstracts",
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
