"""Tests for codenav glue scripts. Stdlib only — run: python3 -m pytest tests/ or
python3 tests/test_glue.py. No graphify install needed (scripts under test are pure stdlib).
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import graphify_to_qdrant as g2q  # noqa: E402


def mini_graph() -> dict:
    """A 5-node graph: two barrels named index.ts in different dirs, a hub, two leaves."""
    return {
        "directed": False,
        "built_at_commit": "deadbeef",
        "nodes": [
            {"id": "a_index", "label": "index.ts", "source_file": "pkg/a/index.ts", "community": 0},
            {"id": "b_index", "label": "index.ts", "source_file": "pkg/b/index.ts", "community": 1},
            {"id": "hub", "label": "getDeps()", "source_file": "api/composition/deps.ts", "community": 2},
            {"id": "leaf1", "label": "foo()", "source_file": "pkg/a/foo.ts", "community": 0},
            {"id": "leaf2", "label": "bar()", "source_file": "pkg/b/bar.ts", "community": 1},
        ],
        "links": [
            {"source": "hub", "target": "a_index"},
            {"source": "hub", "target": "b_index"},
            {"source": "hub", "target": "leaf1"},
            {"source": "hub", "target": "leaf2"},
            {"source": "a_index", "target": "leaf1"},
            {"source": "b_index", "target": "leaf2"},
        ],
    }


class TestDisambiguate(unittest.TestCase):
    def test_barrel_qualified_by_parent(self):
        node = {"id": "a_index", "label": "index.ts", "source_file": "pkg/a/index.ts"}
        self.assertEqual(g2q._disambiguate(node), "index.ts (a)")

    def test_non_barrel_keeps_label(self):
        node = {"id": "hub", "label": "getDeps()", "source_file": "api/deps.ts"}
        self.assertEqual(g2q._disambiguate(node), "getDeps()")


class TestGodNodes(unittest.TestCase):
    def test_hub_is_top(self):
        gods = g2q.god_nodes(mini_graph(), top=5)
        self.assertEqual(gods[0][0], "getDeps()")
        self.assertEqual(gods[0][1], 4)

    def test_skip_barrels_excludes_index(self):
        gods = g2q.god_nodes(mini_graph(), top=5, skip_barrels=True)
        names = [n for n, _ in gods]
        self.assertNotIn("index.ts (a)", names)
        self.assertNotIn("index.ts (b)", names)
        self.assertIn("getDeps()", names)

    def test_barrels_disambiguated_not_merged(self):
        gods = g2q.god_nodes(mini_graph(), top=5)
        names = [n for n, _ in gods]
        # both barrels present as distinct entries, never a bare duplicate "index.ts"
        self.assertNotIn("index.ts", names)


class TestBridges(unittest.TestCase):
    def test_hub_spans_three_communities(self):
        brs = g2q.bridges(mini_graph(), top=5)
        top_name, span = brs[0]
        self.assertEqual(top_name, "getDeps()")
        self.assertEqual(span, 3)  # touches communities 0,1,2


class TestBeaconEnrich(unittest.TestCase):
    def _run(self, file_arg: str, graph_path: Path) -> dict:
        out = subprocess.run(
            [sys.executable, str(SCRIPTS / "beacon_enrich.py"),
             "--file", file_arg, "--graph", str(graph_path)],
            capture_output=True, text=True, check=True,
        )
        return json.loads(out.stdout)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.gpath = Path(self.tmp.name) / "graph.json"
        self.gpath.write_text(json.dumps(mini_graph()), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_path_resolves(self):
        d = self._run("pkg/a/foo.ts", self.gpath)
        self.assertTrue(d["found"])
        self.assertIn("foo()", d["symbols"])

    def test_bare_ambiguous_filename_reports_candidates(self):
        d = self._run("index.ts", self.gpath)
        self.assertFalse(d["found"])
        self.assertTrue(d["ambiguous"])
        self.assertEqual(len(d["candidates"]), 2)

    def test_unknown_file_not_found(self):
        d = self._run("does/not/exist.ts", self.gpath)
        self.assertFalse(d["found"])
        self.assertNotIn("ambiguous", d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
