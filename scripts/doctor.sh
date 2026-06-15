#!/usr/bin/env bash
# doctor.sh — codenav self-healing bootstrap + health check.
#
# Diagnoses (and with --fix, repairs) everything the codenav combine needs:
#   * graphify CLI + its python deps (graphify, networkx)
#   * graphify-out/graph.json present and fresh vs the current git HEAD
#   * canonical-taxonomy re-cluster applied when a taxonomy.py is present
#   * the bundled scripts are runnable
# It also prints the agent-side checks for the three MCP tools a shell cannot
# reach (qdrant, beacon, serena), so the in-session agent can verify them.
#
# Shell can only touch graphify + git + the filesystem. MCP servers are reachable
# only by the agent, so for those this script prints the exact call to make rather
# than pretending to verify them.
#
# Usage:
#   doctor.sh              # diagnose only — report health, change nothing
#   doctor.sh --fix        # self-heal: install deps, build/refresh graph, recluster
#   doctor.sh --fix --quiet
#
# Exit: 0 = healthy (or all fixes applied), 1 = unhealthy and --fix not given / failed.
set -uo pipefail

FIX=0
QUIET=0
for arg in "$@"; do
  case "$arg" in
    --fix) FIX=1 ;;
    --quiet) QUIET=1 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRAPH_DIR="graphify-out"
GRAPH="$GRAPH_DIR/graph.json"
LABELS="$GRAPH_DIR/.graphify_labels.json"
PYMARK="$GRAPH_DIR/.graphify_python"
UNHEALTHY=0
FIXED=0

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_ylw=$'\033[33m'; c_dim=$'\033[2m'; c_rst=$'\033[0m'
if [ ! -t 1 ] || [ "$QUIET" = 1 ]; then c_red=""; c_grn=""; c_ylw=""; c_dim=""; c_rst=""; fi

say()  { [ "$QUIET" = 1 ] || echo "$*"; }
ok()   { say "  ${c_grn}OK${c_rst}   $*"; }
warn() { say "  ${c_ylw}WARN${c_rst} $*"; }
bad()  { say "  ${c_red}FAIL${c_rst} $*"; UNHEALTHY=1; }
fixed(){ say "  ${c_grn}FIXED${c_rst} $*"; FIXED=1; }

# The interpreter graphify recorded at build time, if any; else python3.
PY="python3"
if [ -f "$PYMARK" ]; then
  _rec="$(cat "$PYMARK" 2>/dev/null || true)"
  [ -n "$_rec" ] && [ -x "$_rec" ] && PY="$_rec"
fi

say "=== codenav doctor ${c_dim}($([ "$FIX" = 1 ] && echo 'self-heal' || echo 'diagnose-only'))${c_rst} ==="
say ""

# --- 1. graphify CLI + python deps -------------------------------------------
say "[1] graphify toolchain"
if command -v graphify >/dev/null 2>&1; then
  ok "graphify on PATH ($(command -v graphify))"
else
  if [ "$FIX" = 1 ] && command -v pip >/dev/null 2>&1; then
    say "  installing graphifyy ..."
    if pip install --quiet graphifyy >/dev/null 2>&1; then
      command -v graphify >/dev/null 2>&1 && fixed "graphify installed" || bad "pip ran but graphify still not on PATH"
    else
      bad "pip install graphifyy failed — install manually"
    fi
  else
    bad "graphify not on PATH — run with --fix, or: pip install graphifyy"
  fi
fi

if "$PY" -c "import graphify, networkx" >/dev/null 2>&1; then
  ok "python deps importable (graphify, networkx)"
else
  if [ "$FIX" = 1 ] && command -v pip >/dev/null 2>&1; then
    pip install --quiet graphifyy networkx >/dev/null 2>&1 \
      && { "$PY" -c "import graphify, networkx" >/dev/null 2>&1 \
            && fixed "python deps installed" || warn "installed but not importable under $PY — recluster may need the recorded interpreter"; } \
      || warn "could not install python deps (graphify, networkx) — recluster.py will be unavailable"
  else
    warn "graphify/networkx not importable under $PY — recluster.py needs them (run --fix)"
  fi
fi

# --- 2. graph.json present + fresh -------------------------------------------
say ""
say "[2] knowledge graph"
in_git=0
git rev-parse --git-dir >/dev/null 2>&1 && in_git=1
HEAD_SHA=""
[ "$in_git" = 1 ] && HEAD_SHA="$(git rev-parse --short HEAD 2>/dev/null || true)"

build_graph() {  # $1 = build|update
  command -v graphify >/dev/null 2>&1 || { bad "cannot $1 graph — graphify missing"; return 1; }
  say "  running: graphify $([ "$1" = update ] && echo 'update .' || echo '.') ..."
  if [ "$1" = update ]; then graphify update . >/dev/null 2>&1; else graphify . --no-viz >/dev/null 2>&1 || graphify . >/dev/null 2>&1; fi
}

if [ -f "$GRAPH" ]; then
  built_at="$("$PY" -c "import json,sys; print(json.load(open('$GRAPH')).get('built_at_commit','') or '')" 2>/dev/null || true)"
  if [ -n "$built_at" ] && [ -n "$HEAD_SHA" ] && [ "${built_at#"$HEAD_SHA"}" = "$built_at" ] && [ "${HEAD_SHA#"$built_at"}" = "$HEAD_SHA" ]; then
    if [ "$FIX" = 1 ]; then
      build_graph update && fixed "graph refreshed to HEAD ($HEAD_SHA)" || warn "graph update failed — using stale graph"
    else
      warn "graph built at '$built_at' but HEAD is '$HEAD_SHA' — stale (run --fix or: graphify update .)"
    fi
  else
    ok "graph present$([ -n "$built_at" ] && echo " (built_at $built_at)")"
  fi
else
  if [ "$FIX" = 1 ]; then
    build_graph build && [ -f "$GRAPH" ] && fixed "graph built" || bad "graph build failed"
  else
    bad "no $GRAPH — run --fix, or: graphify ."
  fi
fi

# --- 3. canonical-taxonomy re-cluster ----------------------------------------
say ""
say "[3] taxonomy re-cluster"
if [ -f taxonomy.py ]; then
  if [ -f "$LABELS" ]; then
    ok "taxonomy.py present and labels applied ($LABELS)"
  elif [ "$FIX" = 1 ] && [ -f "$GRAPH" ]; then
    say "  running: recluster.py --map taxonomy.py ..."
    "$PY" "$SCRIPT_DIR/recluster.py" --map taxonomy.py >/dev/null 2>&1 \
      && [ -f "$LABELS" ] && fixed "re-clustered into canonical abstracts" \
      || warn "recluster failed — graph still uses Louvain communities"
  else
    warn "taxonomy.py present but not applied — run --fix to re-cluster into named abstracts"
  fi
else
  say "  ${c_dim}no taxonomy.py — using graphify's Louvain communities (fine for most repos)${c_rst}"
  say "  ${c_dim}for named abstracts: cp $SCRIPT_DIR/taxonomy.example.py taxonomy.py, edit classify(), re-run --fix${c_rst}"
fi

# --- 4. bundled scripts runnable ---------------------------------------------
say ""
say "[4] bundled scripts"
for s in blast_radius.py beacon_enrich.py graphify_to_qdrant.py recluster.py locate.sh; do
  if [ -f "$SCRIPT_DIR/$s" ]; then ok "$s"; else bad "$s missing from $SCRIPT_DIR"; fi
done

# --- 5. MCP tools (agent must verify — shell cannot reach them) --------------
say ""
say "[5] MCP tools — ${c_dim}shell cannot reach these; agent verifies${c_rst}"
say "  qdrant : call mcp__qdrant__qdrant-find with any keyword — empty result OK, an error = not wired"
say "  beacon : run the beacon:index-status skill — expect a healthy index with chunks"
say "  serena : call mcp__serena__check_onboarding_performed — 'no project activated' → run onboarding once"

# --- summary -----------------------------------------------------------------
say ""
if [ "$UNHEALTHY" = 1 ]; then
  if [ "$FIX" = 1 ]; then
    say "${c_ylw}=== still unhealthy after --fix — see FAIL lines above ===${c_rst}"
  else
    say "${c_red}=== unhealthy — re-run with --fix to self-heal ===${c_rst}"
  fi
  exit 1
fi
[ "$FIXED" = 1 ] && say "${c_grn}=== healthy (repairs applied) ===${c_rst}" || say "${c_grn}=== healthy ===${c_rst}"
exit 0
