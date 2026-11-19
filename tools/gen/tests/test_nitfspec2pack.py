"""Tests of tools/gen/nitfspec2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_nitfspec2pack*.py'

`fixtures/nitfspec2pack/input/nitf_spec.xml` holds TREs written for these tests
in the shape of GDAL's file: a flat one with an integer, a signed integer, a
reserved constant, a fixed repeat and an unnamed field; one with a counted
repeat and one with a condition, which must not be built; and BLOCKA, whose
corner binding the generator holds. `expected/` is the tree the generator must
write; after a deliberate change run once with GT_UPDATE_GOLDEN=1 and review
the diff.
"""
import support

import json
import os
import tempfile
import unittest

import nitfspec2pack as gen

FIXTURES = os.path.join(support.FIXTURES, "nitfspec2pack")
SPEC = os.path.join(FIXTURES, "input", "nitf_spec.xml")
CORE_DEF = os.path.join(support.REPO, "model", "core.def")
COMMIT = "0123456789abcdef0123456789abcdef01234567"


class NitfSpecTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

    def run_gen(self, *more):
        return support.run_main(gen.main, ["--spec", SPEC, "--out", self.root, "--spec-commit", COMMIT,
                                           "--core-def", CORE_DEF] + list(more))

    def test_golden(self):
        status, out, err = self.run_gen()
        self.assertEqual((status, err), (0, ""))
        self.assertIn("TREs built      2", out)
        self.assertIn("TREs not built  2", out)
        self.assertIn("self-check      ok", out)
        support.assert_same_tree(self, os.path.join(FIXTURES, "expected"), self.root)

    def test_check_mode_and_second_run(self):
        self.assertEqual(self.run_gen()[0], 0)
        first = support.tree(self.root)
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 0, err)
        self.assertIn("--check: ok", err)
        self.assertEqual(self.run_gen()[0], 0)
        self.assertEqual(support.tree(self.root), first)

    def test_check_mode_reports_an_edited_file(self):
        self.assertEqual(self.run_gen()[0], 0)
        path = os.path.join(self.root, "packs", "nitf-tre-testaa", "pack.def")
        with open(path, "a") as fh:
            fh.write("# edited\n")
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("packs/nitf-tre-testaa/pack.def", err)

    def test_not_flat_tres_are_listed_with_their_construct(self):
        self.assertEqual(self.run_gen()[0], 0)
        with open(os.path.join(self.root, "packs", "nitf-tre-testaa", "pack.md")) as fh:
            md = fh.read()
        self.assertIn("| TESTBB | a repeat whose count is a decimal text field", md)
        self.assertIn("| TESTCC | a part present only when an earlier field holds a given value", md)
        self.assertFalse(os.path.exists(os.path.join(self.root, "packs", "nitf-tre-testbb")))

    def test_layout_of_the_flat_tre(self):
        self.assertEqual(self.run_gen()[0], 0)
        with open(os.path.join(self.root, "packs", "nitf-tre-testaa", "pack.def")) as fh:
            text = fh.read()
        self.assertIn("nitftre.testaa_count_a                       0:0:3        int", text)
        self.assertIn("const     0:11:2       00", text)           # reserved, fixed value
        self.assertIn("nitftre.testaa_offset                        0:13:5       string", text)   # signed
        self.assertIn("nitftre.testaa_pair_02                       0:28:4       string", text)   # unrolled
        self.assertIn("nitftre.testaa_reserved_32                   0:32:4       string", text)

    def test_vector_round_trip_has_the_stated_length(self):
        self.assertEqual(self.run_gen()[0], 0)
        with open(os.path.join(self.root, "packs", "nitf-tre-testaa", "vectors",
                               "gen-01-testaa-round-trip.json")) as fh:
            v = json.load(fh)
        self.assertEqual(len(v["input"]), 40)
        self.assertEqual(v["input"], v["expect"])
        self.assertEqual(v["input"][11:13], "00")

    def test_blocka_binds_the_decimal_frfc_corner(self):
        self.assertEqual(self.run_gen()[0], 0)
        with open(os.path.join(self.root, "packs", "nitf-tre-blocka", "vectors",
                               "gen-01-blocka-decimal-north-round-trip.json")) as fh:
            v = json.load(fh)
        self.assertEqual((v["model"]["lat"], v["model"]["lon"]), ("45.123456", "-122.654321"))
        self.assertEqual(v["input"][97:118], "+45.123456-122.654321")

    def test_a_stated_length_that_does_not_add_up_is_refused(self):
        bad = os.path.join(self.root, "bad.xml")
        with open(SPEC) as fh:
            text = fh.read().replace('<tre name="TESTAA" length="40"', '<tre name="TESTAA" length="41"')
        with open(bad, "w") as fh:
            fh.write(text)
        status, _, err = support.run_main(gen.main, ["--spec", bad, "--out", self.root, "--core-def", CORE_DEF])
        self.assertEqual(status, 1)
        self.assertIn("TESTAA: fields add up to 40, the TRE states 41", err)


if __name__ == "__main__":
    unittest.main()
