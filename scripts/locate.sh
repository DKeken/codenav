#!/usr/bin/env bash
# locate.sh — fan-out code locator for the codenav combine.
#
# Collapses pipeline steps 2-4 into one call when you don't know where to start.
# It runs the parts that are shell-runnable (graphify CLI) and prints the exact
# MCP calls the in-session agent must make for the parts only the agent can reach
# (beacon, serena). The agent then merges all three into one situated answer.
#
# Usage:  locate.sh "<concept or fuzzy description>"
#
# Requires: graphify on PATH, graphify-out/graph.json present.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: locate.sh \"<concept>\"" >&2
  exit 2
fi
CONCEPT="$*"
GRAPH="graphify-out/graph.json"

if [ ! -f "$GRAPH" ]; then
  echo "no $GRAPH — build the graph first: /graphify ." >&2
  exit 1
fi

echo "=== codenav locate: \"$CONCEPT\" ==="
echo
echo "--- [topology] graphify query (runnable now) ---"
if command -v graphify >/dev/null 2>&1; then
  graphify query "$CONCEPT" || echo "(graphify query failed — check graph)"
else
  echo "(graphify not on PATH — skipping)"
fi

echo
echo "--- [semantic] agent: run beacon ---"
echo "Call the beacon semantic-search skill/tool with: \"$CONCEPT\""
echo "Then, for each hit file, situate it:"
echo "    python3 scripts/beacon_enrich.py --file <hit-path>"

echo
echo "--- [precision] agent: run serena ---"
echo "Call mcp__serena__find_symbol with name_path_pattern derived from the"
echo "graphify/beacon candidates above (substring_matching=true if unsure)."
echo "Then mcp__serena__find_referencing_symbols on the resolved symbol for callers."

echo
echo "--- merge rule ---"
echo "serena is the authority. Report: candidate files (beacon) + the abstract each"
echo "lives in and what it bridges to (graphify/beacon_enrich) + exact symbol +"
echo "callers (serena). Flag any beacon/graphify hit serena cannot confirm as stale."
