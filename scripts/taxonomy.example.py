"""Example taxonomy for recluster.py — edit classify() for your repo's layout.

classify(source_file) maps a repo-relative path to ONE canonical abstract bucket.
recluster.py groups every graph node by this bucket. The goal: make the graph mirror
your intended architecture instead of blind Louvain modularity.

This example encodes a hexagonal monorepo with bounded contexts (the AGONTS shape):
  contracts -> core (ports) -> adapters (db/queue/...) -> apps (api/web).
Replace the rules with your own layers/contexts.
"""

CONTEXTS = {"ai", "billing", "comms", "compute", "flows", "identity", "platform"}


def classify(source_file: str) -> str:
    p = source_file.replace("\\", "/")
    parts = p.split("/")

    def seg(i: int) -> str:
        return parts[i] if len(parts) > i else ""

    # shared packages
    if seg(0) == "packages":
        pkg = seg(1)
        if pkg == "contracts":
            return "contracts"
        if pkg == "core":
            return "core (ports)"
        if pkg == "db":
            ctx = seg(3)
            return f"db:{ctx}" if ctx in CONTEXTS else "db:lib"
        if pkg == "agent-engine":
            return "agent-engine"
        return f"pkg:{pkg}" if pkg else "pkg:?"

    # backend app, grouped by bounded context
    if seg(0) == "apps" and seg(1) == "api":
        area = seg(3)
        if area == "modules":
            ctx = seg(4)
            return f"api:{ctx}" if ctx in CONTEXTS else "api:modules"
        if area in {"infrastructure", "http", "bootstrap", "composition", "shared"}:
            return "api:platform-infra"
        return "api:misc"

    # frontend app, grouped by FSD layer
    if seg(0) == "apps" and seg(1) == "web":
        if seg(2) == "app":
            return "web:routing"
        layer = seg(3)
        if layer in {"views", "widgets", "features", "entities", "shared"}:
            return f"web:{layer}"
        return "web:misc"

    if seg(0) == "apps" and seg(1) == "docs":
        return "docs"
    if seg(0) in {"scripts", "tools", "ops"}:
        return "ops/scripts"
    if seg(0) == "e2e":
        return "e2e tests"
    if seg(0) in {".claude", ".agents"}:
        return "agent-tooling"
    return "config/root"
