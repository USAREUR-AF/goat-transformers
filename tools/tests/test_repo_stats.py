"""Tests for tools/repo-stats. Standard library only:

    python3 -I -m unittest discover -s tools/tests

The counting rules are tested on a small invented tree. The last class
compares README.md with the counts of this repository, so a number in
README.md that no longer matches the tree fails here.
"""
import json
import os
import re
import unittest

from support import REPO, TempTree, load_tool, run_main

stats = load_tool("repo-stats")

PACK = 'format %s\ndistribution public\nsource  "an invented document, part 1"  \nsource "a second source"\nwire %s\n'
FILES = {
    # two kinds; an indented `kind` line and a commented one are not kinds
    "packs/real-one/pack.def": PACK % ("one", "json") + (
        "field uid id string\nkind first\nfield lat lat float\nkind second\n  kind indented\n# kind commented\n"),
    "packs/real-one/vectors/a.json": "{}\n",
    "packs/real-one/vectors/b.json": "{}\n",
    "packs/real-one/vectors/notes.txt": "not a vector\n",
    "packs/real-one/vectors/deeper/c.json": "not counted: not directly in vectors/\n",
    # no `kind` line: one message layout
    "packs/real-two/pack.def": PACK % ("two", "bits"),
    "packs/conformance/pack.def": PACK % ("conformance", "json") + "kind a\nkind b\nkind c\n",
    "packs/conformance/vectors/a.json": "{}\n",
    "packs/conformance/load-vectors/a.json": "{}\n",
    "packs/conformance/load-vectors/b.json": "{}\n",
    "packs/conformance/load-vectors/c.json": "{}\n",
    "packs/conformance-extra/pack.def": PACK % ("conformance-extra", "xml"),
    "packs/demo-thing/pack.def": PACK % ("demo-thing", "json"),
    "packs/demonstration/pack.def": PACK % ("demonstration", "json"),  # `demo-` needs the hyphen: a format
    "packs/not-a-pack/readme.md": "no pack.def\n",
    "packs/stray-file.md": "not a directory\n",
    "model/core.def": 'module core\nkey a string - "a"\nkey b string - "b"\n  key c string - "c"\nlist items "items"\n# key d\n',
    "model/more.def": 'module more\nkey e string - "e"\n',
    "model/readme.md": "key not-a-key\n",
    "engines/alpha/src.txt": "x\n",
    "engines/beta/src.txt": "x\n",
    "engines/README.md": "not an engine\n",
}
TOTALS = {
    "formats": 3,
    "synthetic_formats": 3,
    "packs": 6,
    "message_kinds": 4,
    "model_modules": 2,
    "model_keys": 4,
    "model_lists": 1,
    "conversion_vectors": 3,
    "load_vectors": 3,
    "wire_types": ["bits", "json", "xml"],
    "engines": ["alpha", "beta"],
}


class StatsCase(unittest.TestCase):
    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        for rel, text in FILES.items():
            self.tree.write(rel, text)

    def run_stats(self, *argv):
        code, out, err = run_main(stats.main, *argv, root=self.tree.root)
        self.assertEqual((code, err), (0, ""))
        return out


class Counts(StatsCase):
    def test_json_totals(self):
        self.assertEqual(json.loads(self.run_stats("--json")), TOTALS)

    def test_totals_as_text(self):
        self.assertEqual(self.run_stats().splitlines(), [
            "formats             3",
            "synthetic formats   3",
            "packs (both)        6",
            "message kinds       4",
            "model modules       2",
            "model keys          4",
            "model lists         1",
            "conversion vectors  3",
            "load vectors        3",
            "wire types          3 (bits, json, xml)",
            "engines             2 (alpha, beta)",
            "wasm module         not built (bindings/README.md states how)",
        ])

    def test_format_rows_leave_out_the_synthetic_formats_and_quote_the_first_source(self):
        self.assertEqual(self.run_stats("--formats").splitlines(), [
            "| Pack | Wire | Message kinds | Vectors | Written from |",
            "|---|---|---:|---:|---|",
            "| `demonstration` | `json` | 1 | 0 | an invented document, part 1 |",
            "| `real-one` | `json` | 2 | 2 | an invented document, part 1 |",
            "| `real-two` | `bits` | 1 | 0 | an invented document, part 1 |",
        ])

    def test_json_wins_when_both_are_asked(self):
        self.assertEqual(json.loads(self.run_stats("--formats", "--json")), TOTALS)

    def test_message_kinds_count_only_the_formats_that_are_not_synthetic(self):
        self.tree.write("packs/conformance/pack.def", FILES["packs/conformance/pack.def"] + "kind d\n")
        self.assertEqual(json.loads(self.run_stats("--json"))["message_kinds"], 4)
        self.tree.write("packs/real-two/pack.def", FILES["packs/real-two/pack.def"] + "kind a\nkind b\nkind c\n")
        self.assertEqual(json.loads(self.run_stats("--json"))["message_kinds"], 6)

    def test_large_numbers_are_grouped_in_text_and_plain_in_json(self):
        self.tree.write("model/big.def", "module big\n" + "".join('key k%d string - "k"\n' % n for n in range(1500)))
        self.assertIn("model keys          1,504", self.run_stats().splitlines())
        self.assertEqual(json.loads(self.run_stats("--json"))["model_keys"], 1504)

    def test_a_built_wasm_module_is_reported_with_its_size(self):
        label, rel = stats.WASM_BUILDS[0]
        self.tree.write(rel, b"\0" * 1234)
        self.assertEqual(json.loads(self.run_stats("--json"))["wasm_%s_bytes" % label], 1234)
        lines = self.run_stats().splitlines()
        self.assertEqual(lines[-1], "wasm module, %s build  1,234 bytes" % label)
        self.assertFalse(any("not built" in line for line in lines))

    def test_a_pack_with_a_bare_source_line_is_counted(self):
        self.tree.write("packs/real-two/pack.def", "format two\nwire bits\nsource\n")
        self.assertIn("| `real-two` | `bits` | 1 | 0 |  |", self.run_stats("--formats").splitlines())

    def test_a_tree_with_nothing_counts_zero(self):
        empty = os.path.join(self.tree.beside, "empty")
        os.makedirs(empty)
        code, out, _ = run_main(stats.main, "--json", root=empty)
        self.assertEqual(code, 0)
        totals = json.loads(out)
        self.assertEqual((totals["formats"], totals["model_keys"], totals["engines"]), (0, 0, []))

    def test_a_wrong_command_line_is_status_2(self):
        code, _, err = run_main(stats.main, "--no-such-option", root=self.tree.root)
        self.assertEqual(code, 2)
        self.assertIn("--no-such-option", err)


@unittest.skipUnless(os.environ.get("GOAT_CHECK_README_COUNTS") == "1",
                     "README counts are updated by one counts PR after each merge wave, not by every PR; "
                     "set GOAT_CHECK_README_COUNTS=1 to check them")
class ReadmeAgreesWithTheTree(unittest.TestCase):
    """README.md quotes counts. Each is compared with what repo-stats counts
    in this repository. When one of these fails, run `python3 -I
    tools/repo-stats` and correct README.md. The counts lag on purpose between
    counts PRs, so this runs only with GOAT_CHECK_README_COUNTS=1."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(REPO, "README.md"), encoding="utf-8") as fh:
            cls.readme = fh.read()
        cls.formats, cls.totals = stats.collect(REPO)

    @staticmethod
    def number(text):
        return int(text.replace(",", ""))

    def table_count(self, label):
        """The count in the row of the "What the repository holds" table whose
        first cell starts with `label`. -> (the first cell, the count)"""
        rows = re.findall(r"^\| (%s[^|]*) \| ([\d,]+)(?: bytes)? \|$" % re.escape(label), self.readme, re.M)
        self.assertEqual(len(rows), 1, "README.md has no single table row that starts with %r" % label)
        return rows[0][0], self.number(rows[0][1])

    def test_the_bold_count_line(self):
        m = re.search(
            r"^\*\*([\d,]+) formats · ([\d,]+) message kinds · ([\d,]+) conversion vectors · ([\d,]+) engines\*\*",
            self.readme, re.M)
        self.assertIsNotNone(m, "README.md has no bold count line")
        self.assertEqual(
            dict(zip(("formats", "message kinds", "conversion vectors", "engines"), map(self.number, m.groups()))),
            {
                "formats": self.totals["formats"],
                "message kinds": self.totals["message_kinds"],
                "conversion vectors": self.totals["conversion_vectors"],
                "engines": len(self.totals["engines"]),
            })

    def test_the_count_table(self):
        expected = {
            "Formats": self.totals["formats"],
            "Message kinds": self.totals["message_kinds"],
            "Typed keys in the shared model": self.totals["model_keys"],
            "Lists in the shared model": self.totals["model_lists"],
            "Conversion vectors": self.totals["conversion_vectors"],
            "Load vectors": self.totals["load_vectors"],
            "Synthetic formats": self.totals["synthetic_formats"],
            "Wire types": len(self.totals["wire_types"]),
            "Engines": len(self.totals["engines"]),
        }
        self.assertEqual({label: self.table_count(label)[1] for label in expected}, expected)

    def test_the_module_count_and_the_wire_types_named_in_the_table(self):
        cell, _ = self.table_count("Typed keys in the shared model")
        self.assertIn("in %d modules" % self.totals["model_modules"], cell)
        cell, _ = self.table_count("Wire types")
        self.assertEqual(sorted(re.findall(r"`([a-z]+)`", cell)), self.totals["wire_types"])

    def test_each_pack_row_states_the_wire_and_the_message_kinds_of_that_pack(self):
        counted = {f["pack"]: (f["wire"], f["kinds"]) for f in self.formats}
        rows = re.findall(r"^\| `([a-z0-9-]+)` \| [^|]+ \| `([a-z]+)` \| ([\d,]+) \|$", self.readme, re.M)
        self.assertGreater(len(rows), 10, "README.md has no table of packs")
        for pack, wire, kinds in rows:
            with self.subTest(pack=pack):
                self.assertIn(pack, counted, "README.md names a pack that is not in packs/")
                self.assertEqual((wire, self.number(kinds)), counted[pack])


if __name__ == "__main__":
    unittest.main()
