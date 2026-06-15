#!/usr/bin/env python3
"""blast-radius / change-impact off the graphify graph.

The codenav combine already builds graphify-out/graph.json. This is the axis it
never used: "if I touch these files, what else breaks, and is any of it tested?"

Given a set of changed files (explicit --files, or derived from a git ref via
--base, or the current working tree by default), it walks the dependency graph
to find the dependents — the nodes that point AT the changed code — out to N
hops, then groups them by file and by canonical abstract and flags changed files
that have no test node in their blast radius.

Runs entirely off graph.json + git. No MCP calls — the agent runs it, reads the
result, and confirms the hot edges with serena (the live-source authority) before
trusting them. A graphify edge is a hypothesis, not a fact.

Edge-direction assumption: a link source->target means "source depends on target"
(source imports/calls target). Dependents of X are therefore the nodes reached by
walking edges in REVERSE from X. If your graph encodes the opposite direction,
pass --forward to flip, or --undirected to ignore direction entirely.

Usage:
    python3 blast_radius.py --base origin/main
    python3 blast_radius.py --files apps/api/src/modules/ai/chat/engine/loop.ts
    python3 blast_radius.py                       # uncommitted working-tree changes
    python3 blast_radius.py --base HEAD~3 --hops 3 --json
"""
import argparse
import json
import subprocess
from collections import defaultdict, deque
from pathlib import Path

# source files matching these are test nodes — a changed file with a test in its
# blast radius is covered; one without is a coverage gap worth flagging.
TEST_MARKERS = (
    ".test.", ".spec.", "_test.", "-test.", ".tc.test.",
    "/tests/", "/test/", "/__tests__/", "/spec/",
)


def _norm(p: str) -> str:
    return p.replace("\\", "/").lstrip("./")


def _is_test(source_file: str) -> bool:
    sf = _norm(source_file)
    return any(m in sf for m in TEST_MARKERS)


def _git_changed(base: str | None) -> list[str]:
    """Changed files: a diff against <base> if given, else staged + unstaged +
    untracked in the working tree. Returns [] on any git failure (not a repo,
    bad ref) — the caller then requires --files."""
    cmds: list[list[str]]
    if base:
        cmds = [["git", "diff", "--name-only", f"{base}...HEAD"],
                ["git", "diff", "--name-only", base]]
    else:
        cmds = [["git", "diff", "--name-only"],
                ["git", "diff", "--name-only", "--staged"],
                ["git", "ls-files", "--others", "--exclude-standard"]]
    seen: list[str] = []
    for cmd in cmds:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
        for line in out.splitlines():
            line = line.strip()
            if line and line not in seen:
                seen.append(line)
    return seen


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default="graphify-out/graph.json")
    ap.add_argument("--labels", default="graphify-out/.graphify_labels.json")
    ap.add_argument("--base", default=None,
                    help="git ref to diff against (e.g. origin/main, HEAD~3)")
    ap.add_argument("--files", default=None,
                    help="comma-separated changed files (overrides git detection)")
    ap.add_argument("--hops", type=int, default=2, help="dependency hops to walk")
    ap.add_argument("--forward", action="store_true",
                    help="walk edges source->target (flip if your graph is inverted)")
    ap.add_argument("--undirected", action="store_true",
                    help="ignore edge direction entirely")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = ap.parse_args()

    gp = Path(args.graph)
    if not gp.exists():
        raise SystemExit(f"no {gp} — build the graph first: graphify .")
    g = json.loads(gp.read_text(encoding="utf-8"))

    labels: dict[str, str] = {}
    lp = Path(args.labels)
    if lp.exists():
        labels = json.loads(lp.read_text(encoding="utf-8"))

    if args.files:
        changed = [c.strip() for c in args.files.split(",") if c.strip()]
        source = "--files"
    else:
        changed = _git_changed(args.base)
        source = f"git diff ({args.base or 'working tree'})"
    if not changed:
        raise SystemExit(
            "no changed files detected — pass --files \"a,b\" or run inside a git "
            "repo with uncommitted changes / a valid --base ref")

    nodes = g["nodes"]
    label_of = {n["id"]: n.get("label", n["id"]) for n in nodes}
    comm_of = {n["id"]: n.get("community", -1) for n in nodes}
    file_of = {n["id"]: _norm(n.get("source_file", "")) for n in nodes}
    abstract_of = {nid: labels.get(str(c), f"community {c}") for nid, c in comm_of.items()}

    changed_norm = [_norm(c) for c in changed]

    def in_changed(sf: str) -> bool:
        return any(sf == c or sf.endswith("/" + c) or c.endswith("/" + sf)
                   for c in changed_norm)

    seed_ids = {nid for nid, sf in file_of.items() if sf and in_changed(sf)}
    matched_files = sorted({file_of[i] for i in seed_ids})
    unmatched = [c for c in changed_norm
                 if not any(in_changed(file_of[i]) and file_of[i] and
                            (file_of[i] == c or file_of[i].endswith("/" + c) or
                             c.endswith("/" + file_of[i])) for i in seed_ids)]

    # adjacency: dependents walk REVERSE (incoming) by default
    adj: dict[str, set] = defaultdict(set)
    for link in g.get("links", []):
        s, t = link["source"], link["target"]
        if args.undirected:
            adj[s].add(t)
            adj[t].add(s)
        elif args.forward:
            adj[s].add(t)
        else:  # default: dependents = who points AT me = reverse
            adj[t].add(s)

    # BFS out to N hops, recording the shortest hop distance per node and the set
    # of originating seeds that reach it (provenance — needed for per-seed coverage).
    dist: dict[str, int] = {i: 0 for i in seed_ids}
    roots: dict[str, set] = {i: {i} for i in seed_ids}
    q: deque = deque((i, 0) for i in seed_ids)
    while q:
        nid, d = q.popleft()
        if d >= args.hops:
            continue
        for nb in adj.get(nid, ()):  # noqa: B007
            if nb not in dist:
                dist[nb] = d + 1
                roots[nb] = set(roots[nid])
                q.append((nb, d + 1))
            elif dist[nb] == d + 1:
                roots[nb] |= roots[nid]

    impacted = {i for i in dist if i not in seed_ids}

    files_hit: dict[str, int] = {}
    for i in impacted:
        sf = file_of.get(i, "")
        if sf:
            files_hit[sf] = min(files_hit.get(sf, 99), dist[i])
    abstracts_hit = sorted({abstract_of[i] for i in impacted})

    # test coverage (per-seed): a changed file is covered only if a test node whose
    # provenance includes one of THAT file's seeds is in the radius. Crediting every
    # seed whenever any test appears anywhere would mask real gaps on multi-file diffs.
    covered: set = set()
    for i in dist:
        if _is_test(file_of.get(i, "")):
            for s in roots.get(i, ()):
                covered.add(file_of[s])
    test_gaps = sorted(f for f in matched_files if f not in covered)

    direction = ("undirected" if args.undirected
                 else "forward (source->target)" if args.forward
                 else "reverse (dependents)")
    risk = "low"
    if len(files_hit) >= 8 or len(abstracts_hit) >= 4:
        risk = "high"
    elif len(files_hit) >= 3 or len(abstracts_hit) >= 2:
        risk = "medium"

    result = {
        "changed_source": source,
        "edge_direction": direction,
        "hops": args.hops,
        "changed_files_in_graph": matched_files,
        "changed_files_not_in_graph": unmatched,
        "impacted_file_count": len(files_hit),
        "impacted_files": [
            {"file": f, "hop": h} for f, h in
            sorted(files_hit.items(), key=lambda kv: (kv[1], kv[0]))
        ],
        "abstracts_spanned": abstracts_hit,
        "test_coverage_gaps": test_gaps,
        "risk_hint": risk,
        "note": "graph-derived hypothesis — confirm hot edges with serena "
                "find_referencing_symbols before trusting; run graphify update . if stale",
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"=== blast radius: {source} ({direction}, {args.hops} hops) ===\n")
    if not matched_files:
        print("none of the changed files have nodes in the graph.")
        print("run `graphify update .` — the graph is stale or these are new files.")
        if unmatched:
            print("\nchanged but absent from graph:")
            for u in unmatched:
                print(f"  {u}")
        return
    print(f"changed (in graph): {len(matched_files)} file(s)")
    for f in matched_files:
        print(f"  * {f}")
    if unmatched:
        print(f"\nchanged but NOT in graph ({len(unmatched)}) — possibly new/stale:")
        for u in unmatched:
            print(f"  ? {u}")
    print(f"\nimpacted: {len(files_hit)} file(s) across "
          f"{len(abstracts_hit)} abstract(s) — risk: {risk.upper()}")
    for f, h in sorted(files_hit.items(), key=lambda kv: (kv[1], kv[0]))[:40]:
        print(f"  {h}h  {f}")
    if len(files_hit) > 40:
        print(f"  ... +{len(files_hit) - 40} more")
    print("\nabstracts touched: " + (", ".join(abstracts_hit) or "(none)"))
    if test_gaps:
        print(f"\nTEST COVERAGE GAPS ({len(test_gaps)}) — changed, no test in blast radius:")
        for f in test_gaps:
            print(f"  ! {f}")
    else:
        print("\ntest coverage: every changed file has a test in its blast radius.")
    print(f"\n{result['note']}")


if __name__ == "__main__":
    main()
