---
name: codenav
description: >
  Unified code-navigation doctrine combining four persistent tools on four distinct axes —
  qdrant (memory/time), graphify (topology/macro), beacon (semantic retrieval), serena
  (precision/micro). Use at the start of ANY non-trivial code task in a repo wired with
  these MCPs: orient before editing, locate symbols by meaning, recall prior decisions, and
  feed findings back so each tool sharpens the others. Trigger phrases — "where is X",
  "how does Y work", "who calls Z", "trace the flow", "orient me", "find the code that...",
  "понять проект", "разберись в коде", "где это".
---

# codenav — the four-axis code navigation combine

Four tools. Four DIFFERENT questions. They are not redundant — each owns an axis the
others cannot see. Used together in order, they turn "I don't know this codebase" into a
precise edit with minimal token burn.

## The four axes (memorize this table)

| Tool | Axis | The question it answers | Authority |
|---|---|---|---|
| **qdrant** | time | "what did we decide / break / learn before?" | the diary |
| **graphify** | topology (macro) | "how does the whole thing connect, where are the hubs and bridges?" | the map |
| **beacon** | semantic retrieval | "find the code by meaning — I don't know the symbol name" | the front door |
| **serena** | precision (micro), live | "where EXACTLY is it defined, who references it?" | the scalpel |

Key insight: graphify and serena both assume you roughly KNOW a name. beacon is the entry
point when you have only a fuzzy description. qdrant is the only one that crosses sessions.
serena is the only one that reads live source (the other three read an index that can lag).

## The mandatory pipeline

Run in this order. Each step narrows the search space for the next.

```
1. qdrant-find "<task keywords>"        → recall prior context for THIS repo (skip on trivial lookups)
2. graphify query "<question>"          → orient by topology; which abstracts/communities are involved
3. beacon semantic-search "<meaning>"   → fuzzy-locate candidate files when the symbol name is unknown
4. serena find_symbol / find_referencing_symbols  → pinpoint exact symbol + callers (the authority)
5. grep / Glob                          → last resort only
6. AFTER the change:
     graphify update .                  → keep the map fresh (AST-only, free)
     qdrant-store                        → persist any decision / gotcha / architectural fact
```

You do NOT always run all five. Decision rule:

- Know the exact symbol name? → skip beacon, go qdrant → graphify (orient) → serena (pinpoint).
- Only a vague description ("the thing that retries failed calls")? → beacon first to surface candidates, then serena to confirm.
- Pure "what is the architecture / where are the seams?" question? → graphify alone answers it; no serena needed.
- Touching code you've edited before? → always qdrant-find first; you may have left a gotcha.

## How they complement each other (sync directions)

These are not four silos — outputs of one become inputs to another.

- **graphify → qdrant.** After a build/update, store the god-nodes and cross-community
  bridges as `kind: architectural-fact`. Future sessions recall the topology without a rebuild.
  (`scripts/graphify_to_qdrant.py`)
- **beacon → graphify.** A beacon hit returns a file + snippet. Cross-reference it against
  the graph: which abstract does it live in, what does it bridge to? Turns a flat hit into a
  situated one. (`scripts/beacon_enrich.py`)
- **serena ↔ graphify.** `serena find_symbol` gives the exact `source_location`; feed that
  back to `graphify explain "<symbol>"` for its neighbourhood, and vice-versa. Micro and macro
  views of the same node.
- **qdrant → everything.** A recalled decision often names a symbol or file — hand it straight
  to serena/graphify instead of re-discovering it.

## Unified entry point

For "I have a fuzzy concept, find and situate it" run the fan-out helper:

```
scripts/locate.sh "<concept or description>"
```

It queries beacon (semantic) + graphify (topology) + serena (symbol guess) in parallel and
merges into one ranked answer: candidate files, the abstract each belongs to, and exact
symbol locations where serena resolved them. Use it as step 2-4 collapsed into one call when
you genuinely don't know where to start.

## Honesty rules

- serena is the authority on live code. If graphify/beacon disagree with serena, trust serena
  and flag the index as stale (`graphify update .`, beacon reindex).
- A graphify INFERRED edge is a hypothesis, not a fact — verify with serena before acting.
- Never narrate memory ops. qdrant-find/store happen silently unless the result changes the answer.
- Re-cluster graphify by canonical project taxonomy when Louvain over-fragments (see README).

## Setup

This skill assumes four MCP servers / tools are available in the session:
graphify (CLI + `--mcp`), serena, beacon, qdrant. See `README.md` for wiring each one and the
project-taxonomy re-cluster recipe.
