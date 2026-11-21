"""Tests for tools/catalog-radial.py. Standard library only:

    python3 -I -m unittest discover -s tools/tests

The rules are tested on a small invented tree; the last test checks that the
chart of this repository's table holds every family the catalog figure holds.
"""
import importlib.machinery
import importlib.util
import json
import os
import re
import unittest

from support import REPO, TempTree, run_main


def _load(name, file):
    loader = importlib.machinery.SourceFileLoader(name, os.path.join(REPO, "tools", file))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


rad = _load("catalog_radial", "catalog-radial.py")

DOMAINS = {"synthetic_prefixes": ["conformance", "demo-"],
           "domains": [{"id": "air", "name": "Air"}, {"id": "sea", "name": "Sea"}, {"id": "space", "name": "Space"}]}
FAMILIES = {
    "radar.json": {"name": "Radar & co", "domain": "air", "prefixes": ["radar-"]},
    "adsb.json": {"name": "ADS-B", "domain": "air", "exact": ["adsb"]},
    "ais.json": {"name": "AIS", "domain": "sea", "exact": ["ais", "ais-binary"]},
    "ccsds.json": {"name": "CCSDS \"frames\"", "domain": "space", "prefixes": ["ccsds-"]},
}
PACKS = ["radar-cat001", "radar-cat048", "radar-cat062", "adsb", "ais", "ais-binary", "ccsds-tm", "conformance-x"]
PAGE = "<html><body>\n<section id=\"hero\"></section>\n%s\n%s\n<section id=\"hub\"></section>\n</body></html>\n" % (rad.START, rad.END)


class RadialTree(unittest.TestCase):
    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        self.tree.write("tools/catalog-families/_domains.json", json.dumps(DOMAINS))
        for name, fam in FAMILIES.items():
            self.tree.write("tools/catalog-families/" + name, json.dumps(fam))
        for p in PACKS:
            self.tree.write("packs/%s/pack.def" % p, "format %s\n" % p)
        self.tree.write("site/index.html", PAGE)
        self.root = self.tree.root

    def run_tool(self, *argv):
        return run_main(rad.main, *argv, root=self.root)

    def read(self, rel):
        with open(os.path.join(self.root, rel), encoding="utf-8") as fh:
            return fh.read()

    def domains(self):
        return rad.survey(os.path.join(self.root, "packs"), os.path.join(self.root, "tools", "catalog-families"))

    def test_survey_counts_families_and_leaves_out_synthetic_packs(self):
        ds = self.domains()
        self.assertEqual([d["id"] for d in ds], ["air", "sea", "space"])
        self.assertEqual(ds[0]["families"][0], {"name": "Radar & co", "packs": 3})
        self.assertEqual(sum(d["packs"] for d in ds), 7)

    def test_arcs_fill_the_ring_and_hold_their_labels(self):
        ds = self.domains()
        spans = rad.allocate(ds)
        self.assertAlmostEqual(spans[0][0], rad.DOM_GAP / 2)
        for (a0, a1), (b0, _) in zip(spans, spans[1:]):
            self.assertAlmostEqual(b0 - a1, rad.DOM_GAP)
        self.assertAlmostEqual(spans[-1][1] + rad.DOM_GAP / 2, 360.0)
        for d, (a0, a1) in zip(ds, spans):
            need = rad.fig.text_width(d["short"], rad.LABEL_SIZE, True) + 2 * rad.LABEL_PAD
            self.assertGreaterEqual((a1 - a0) * 3.141592653589793 / 180 * rad.R_LABEL, need - 1e-6)

    def test_page_block(self):
        block = rad.site_block(self.domains())
        self.assertTrue(block.startswith(rad.START) and block.endswith(rad.END))
        bars = re.findall(r'<path d="[^"]+" class="rd-bar rd-(\w+)" tabindex="(-?\d)" role="img" aria-label="([^"]+)" data-tip="([^"]+)">', block)
        self.assertEqual(len(bars), 4)
        self.assertEqual([b[1] for b in bars].count("0"), 1)
        self.assertTrue(all(b[2] == b[3] for b in bars))
        self.assertIn('aria-label="Radar &amp; co: 3 packs (Air)"', block)
        self.assertIn('CCSDS &quot;frames&quot;: 1 pack (Space)', block)
        self.assertIn('class="rd-private"', block)
        self.assertIn("7 formats in 4 families", block)
        self.assertEqual(block.count("<tr><td>"), 4)

    def test_write_then_check(self):
        self.assertEqual(self.run_tool()[0], 0)
        page = self.read("site/index.html")
        self.assertTrue(page.startswith("<html><body>\n<section id=\"hero\"></section>\n" + rad.START))
        self.assertTrue(page.endswith(rad.END + "\n<section id=\"hub\"></section>\n</body></html>\n"))
        for name in rad.OUT_NAMES:
            svg = self.read("docs/figures/" + name)
            self.assertNotIn("nan", svg)
            self.assertIn("private overlays plug in here", svg)
        self.assertEqual(self.run_tool("--check")[0], 0)
        self.assertEqual(self.run_tool()[0], 0)
        self.assertEqual(self.read("site/index.html"), page)  # the same bytes again

    def test_check_fails_when_a_pack_is_added(self):
        self.run_tool()
        self.tree.write("packs/radar-cat240/pack.def", "format radar-cat240\n")
        code, _, err = self.run_tool("--check")
        self.assertEqual(code, 1)
        self.assertIn("site/index.html", err)

    def test_site_writes_only_the_page(self):
        self.assertEqual(self.run_tool("--site")[0], 0)
        self.assertFalse(os.path.exists(os.path.join(self.root, "docs", "figures", rad.OUT_NAMES[0])))

    def test_a_pack_with_no_family_stops_it(self):
        self.tree.write("packs/zzz/pack.def", "format zzz\n")
        code, _, err = self.run_tool("--site")
        self.assertEqual(code, 1)
        self.assertIn("zzz", err)

    def test_markers_are_required_once(self):
        self.tree.write("site/index.html", "<html></html>\n")
        code, _, err = self.run_tool("--site")
        self.assertEqual(code, 1)
        self.assertIn("must hold the line", err)

    def test_a_domain_without_a_colour_stops_it(self):
        d = dict(DOMAINS, domains=DOMAINS["domains"] + [{"id": "deep", "name": "Deep"}])
        self.tree.write("tools/catalog-families/_domains.json", json.dumps(d))
        self.tree.write("tools/catalog-families/sub.json", json.dumps({"name": "Sub", "domain": "deep", "exact": ["sub"]}))
        self.tree.write("packs/sub/pack.def", "format sub\n")
        code, _, err = self.run_tool("--site")
        self.assertEqual(code, 1)
        self.assertIn("no colour", err)


class RepositoryChart(unittest.TestCase):
    def test_every_family_of_the_figure_is_a_bar(self):
        ds = rad.survey(os.path.join(REPO, "packs"), os.path.join(REPO, "tools", "catalog-families"))
        table = rad.fig.load_table(os.path.join(REPO, "tools", "catalog-families"))
        self.assertEqual(sum(len(d["families"]) for d in ds), len(table["families"]))
        self.assertEqual(set(d["id"] for d in ds), set(rad.COLOURS))
        rad.allocate(ds)  # the labels fit


if __name__ == "__main__":
    unittest.main()
