"""Tests for tools/catalog-figure.py. Standard library only:

    python3 -I -m unittest discover -s tools/tests

The rules are tested on a small invented tree and family table; the last
class checks that the family table of this repository holds every pack of
packs/.
"""
import json
import os
import re
import unittest
from xml.sax.saxutils import escape

import importlib.machinery
import importlib.util

from support import REPO, TempTree, run_main


def _load():
    loader = importlib.machinery.SourceFileLoader("catalog_figure", os.path.join(REPO, "tools", "catalog-figure.py"))
    spec = importlib.util.spec_from_loader("catalog_figure", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


fig = _load()

TABLE = {
    "synthetic_prefixes": ["conformance", "demo-"],
    "domains": [
        {"id": "air", "name": "Air"},
        {"id": "sea", "name": "Sea & shore"},
        {"id": "unused", "name": "A domain with no family"},
    ],
    "families": [
        {"name": "Radar categories", "domain": "air", "prefixes": ["radar-cat"],
         "members": {"pattern": "^radar-cat([0-9]{3})", "label": "{n} categories"}},
        {"name": "Beacon", "domain": "air", "exact": ["beacon", "beacon-v2"], "detail": "v1, v2"},
        {"name": "Ship log", "domain": "sea", "prefixes": ["shiplog-"]},
    ],
}
PACKS = ["radar-cat001", "radar-cat048", "radar-cat048-full", "beacon", "beacon-v2",
         "shiplog-a", "shiplog-b", "shiplog-c", "conformance", "conformance-seq", "demo-bits"]


class CatalogCase(unittest.TestCase):
    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        for name in PACKS:
            self.tree.write("packs/%s/pack.def" % name, "format %s\n" % name)
        self.tree.write("packs/not-a-pack/readme.md", "no pack.def\n")
        self.write_table(TABLE)

    def write_table(self, table):
        """The table as tools/catalog-families/: _domains.json and one file per family."""
        folder = os.path.join(self.tree.root, "tools", "catalog-families")
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                os.remove(os.path.join(folder, name))
        head = {k: v for k, v in table.items() if k != "families"}
        self.tree.write("tools/catalog-families/_domains.json", json.dumps(head))
        for i, fam in enumerate(table["families"]):
            self.tree.write("tools/catalog-families/%02d-family.json" % i, json.dumps(fam))

    def run_fig(self, *argv):
        return run_main(fig.main, *argv,
                        "--packs", os.path.join(self.tree.root, "packs"),
                        "--families", os.path.join(self.tree.root, "tools", "catalog-families"),
                        "--out", os.path.join(self.tree.root, "out"))

    def svg(self, name="catalog-light.svg"):
        with open(os.path.join(self.tree.root, "out", name), encoding="utf-8") as fh:
            return fh.read()


class Families(CatalogCase):
    def test_an_unknown_pack_fails_with_its_name(self):
        self.tree.write("packs/mystery-format/pack.def", "format mystery-format\n")
        for argv in ((), ("--check",), ("--check-families",)):
            code, out, err = self.run_fig(*argv)
            self.assertEqual(code, 1, argv)
            self.assertIn("mystery-format", err)
        self.assertFalse(os.path.exists(os.path.join(self.tree.root, "out")))

    def test_a_family_with_no_pack_fails_with_its_name(self):
        self.tree.remove("packs/shiplog-a/pack.def")
        self.tree.remove("packs/shiplog-b/pack.def")
        self.tree.remove("packs/shiplog-c/pack.def")
        code, out, err = self.run_fig("--check-families")
        self.assertEqual(code, 1)
        self.assertIn("Ship log", err)

    def test_check_families_passes_and_writes_nothing(self):
        code, out, err = self.run_fig("--check-families")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("3 families in 2 domains", out)
        self.assertFalse(os.path.exists(os.path.join(self.tree.root, "out")))

    def test_an_exact_name_or_else_the_longest_prefix_holds_a_pack(self):
        table = fig.load_table(os.path.join(self.tree.root, "tools", "catalog-families"))
        domains, synthetic = fig.classify(table, fig.pack_names(os.path.join(self.tree.root, "packs")))
        got = {f["name"]: (f["packs"], f["detail"]) for d in domains for f in d["families"]}
        self.assertEqual(got, {
            "Radar categories": (3, "2 categories: 001, 048"),
            "Beacon": (2, "v1, v2"),
            "Ship log": (3, ""),
        })


class Matching(CatalogCase):
    def classify(self):
        table = fig.load_table(os.path.join(self.tree.root, "tools", "catalog-families"))
        domains, _ = fig.classify(table, fig.pack_names(os.path.join(self.tree.root, "packs")))
        return {f["name"]: f["packs"] for d in domains for f in d["families"]}

    def test_the_longest_prefix_wins_whatever_the_file_order(self):
        for first in (True, False):
            fams = [{"name": "Radar categories", "domain": "air", "prefixes": ["radar-cat"]},
                    {"name": "Radar full", "domain": "air", "prefixes": ["radar-cat048-"]}]
            table = dict(TABLE, families=(fams if first else fams[::-1]) + TABLE["families"][1:])
            self.write_table(table)
            with self.subTest(first=first):
                self.assertEqual(self.classify(), {"Radar categories": 2, "Radar full": 1, "Beacon": 2, "Ship log": 3})

    def test_an_exact_name_wins_over_a_prefix(self):
        table = dict(TABLE, families=TABLE["families"] + [{"name": "Beta ship", "domain": "sea", "exact": ["shiplog-b"]}])
        self.write_table(table)
        got = self.classify()
        self.assertEqual((got["Ship log"], got["Beta ship"]), (2, 1))

    def test_two_families_that_hold_a_pack_equally_stop_the_tool(self):
        table = dict(TABLE, families=TABLE["families"] + [{"name": "Other log", "domain": "sea", "prefixes": ["shiplog-"]}])
        self.write_table(table)
        code, _, err = self.run_fig("--check-families")
        self.assertEqual(code, 1)
        self.assertIn("two families hold the packs shiplog-a", err)


class Figure(CatalogCase):
    def test_the_synthetic_packs_are_left_out_and_counted(self):
        self.assertEqual(self.run_fig()[0], 0)
        svg = self.svg()
        self.assertNotRegex(svg, r">[^<]*(conformance-seq|demo-bits)[^<]*<")
        self.assertIn("Not shown: the 3 synthetic packs whose names start with conformance or demo-", svg)
        self.assertIn("The 3 synthetic", svg)
        self.assertIn("3 families, 8 formats", svg)

    def test_every_family_and_domain_name_appears(self):
        self.assertEqual(self.run_fig()[0], 0)
        for name in ("catalog-light.svg", "catalog-dark.svg"):
            svg = self.svg(name)
            for fam in TABLE["families"]:
                self.assertIn(">%s</text>" % escape(fam["name"]), svg)
            self.assertIn(">Air</text>", svg)
            self.assertIn(">Sea &amp; shore</text>", svg)
            self.assertNotIn("A domain with no family", svg)
            self.assertIn("<title", svg)
            self.assertIn("<desc", svg)

    def test_the_output_is_deterministic(self):
        self.assertEqual(self.run_fig()[0], 0)
        first = {n: self.svg(n) for n in fig.OUT_NAMES}
        self.assertEqual(self.run_fig()[0], 0)
        for n in fig.OUT_NAMES:
            self.assertEqual(self.svg(n), first[n])
            with open(os.path.join(self.tree.root, "out", n), "rb") as fh:
                raw = fh.read()
            self.assertNotIn(b"\r", raw)
            self.assertTrue(raw.endswith(b"</svg>\n"))
        self.assertNotRegex(first["catalog-light.svg"], r'(x|y|width|height)="-?\d+\.\d{2,}')

    def test_check_compares_bytes(self):
        code, out, err = self.run_fig("--check")
        self.assertEqual(code, 1)
        self.assertIn("catalog-light.svg", err)
        self.assertEqual(self.run_fig()[0], 0)
        self.assertEqual(self.run_fig("--check")[0], 0)
        self.tree.write("packs/shiplog-d/pack.def", "format shiplog-d\n")
        self.assertEqual(self.run_fig("--check-families")[0], 0)
        code, out, err = self.run_fig("--check")
        self.assertEqual(code, 1)

    def test_text_is_never_narrower_than_measured(self):
        # the same width table that places text: a wider character is never cheaper
        self.assertGreater(fig.text_width("W", 14), fig.text_width("i", 14))
        self.assertGreater(fig.text_width("ab", 14, True), fig.text_width("ab", 14))
        self.assertEqual(fig.text_width("☃", 10), 10 * fig.MARGIN_OF_SAFETY)

    def test_a_wrong_command_line_is_status_2(self):
        self.assertEqual(self.run_fig("--check", "--check-families")[0], 2)


class ThisRepository(unittest.TestCase):
    def test_every_pack_of_this_repository_has_a_family(self):
        code, out, err = run_main(fig.main, "--check-families")
        self.assertEqual((code, err), (0, ""))


if __name__ == "__main__":
    unittest.main()
