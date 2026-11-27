"""Tests for tools/bench-table.py: the files of engine-spec 0.25 ruling 2c are
read, checked against the set, and tabulated; a malformed file is refused and
no number fails anything. Standard library only:

    python3 -I -m unittest discover -s tools/tests
"""
import json
import os
import tempfile
import unittest

from support import load_tool, run_main

bt = load_tool("bench-table.py")

SET = {"iterations": 10, "vectors": ["packs/a/vectors/01-x.json", "packs/b/vectors/02-y.json"]}


class BenchTable(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.set = self.write("set.json", json.dumps(SET))

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def run_file(self, name, ns=(1500, 250000), load=(2, 3000000), vectors=None):
        lines = [json.dumps({"vector": v, "iterations": 10, "ns_per_op": n})
                 for v, n in zip(vectors or SET["vectors"], ns)]
        lines.append(json.dumps({"load": load[0], "ns": load[1]}))
        return self.write(name, "\n".join(lines) + "\n")

    def test_a_table_of_two_engines(self):
        a, b = self.run_file("bench-rust.jsonl"), self.run_file("bench-go.jsonl", ns=(800, 120000))
        status, out, err = run_main(bt.main, *["--set", self.set, a, b])
        self.assertEqual((status, err), (0, ""))
        self.assertEqual(out.splitlines(), [
            "| Vector | rust | go |",
            "|---|---:|---:|",
            "| `a/01-x` | 1.5 | 0.8 |",
            "| `b/02-y` | 250.0 | 120.0 |",
            "| load, ms (packs) | 3 (2) | 3 (2) |",
        ])

    def test_check_mode_prints_no_table(self):
        status, out, err = run_main(bt.main, *["--set", self.set, "--check", self.run_file("bench-zig.jsonl")])
        self.assertEqual((status, out), (0, ""))
        self.assertIn("ok, 1 run(s) of 2 vectors", err)

    def test_a_vector_out_of_the_sets_order_is_refused(self):
        bad = self.run_file("bench-cpp.jsonl", vectors=list(reversed(SET["vectors"])))
        status, out, err = run_main(bt.main, *["--set", self.set, bad])
        self.assertEqual(status, 1)
        self.assertIn("bench-cpp.jsonl:1: vector", err)

    def test_a_missing_load_line_is_refused(self):
        lines = [json.dumps({"vector": v, "iterations": 10, "ns_per_op": 1}) for v in SET["vectors"]]
        bad = self.write("bench-java.jsonl", "\n".join(lines) + "\n")
        status, _, err = run_main(bt.main, *["--set", self.set, bad])
        self.assertEqual(status, 1)
        self.assertIn("2 lines, the set has 2 vectors and one load line", err)

    def test_any_number_passes(self):
        """Ruling 2d: no number fails a run, however slow."""
        slow = self.run_file("bench-python.jsonl", ns=(10 ** 12, 10 ** 13), load=(2, 10 ** 15))
        self.assertEqual(run_main(bt.main, *["--set", self.set, "--check", slow])[0], 0)

    def test_the_repository_set_is_readable(self):
        with open(os.path.join(bt.REPO, "bench", "set.json"), encoding="utf-8") as f:
            self.assertTrue(json.load(f)["vectors"])


if __name__ == "__main__":
    unittest.main()
