"""Tests of tools/gen/rtcm2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_rtcm2pack*.py'

`fixtures/rtcm2pack/input/src/` is a small pyrtcm-shaped tree written for these
tests: data fields of each type and scale form, and messages with a case for
each rule. `input/tools/gen/sources/rtcm3-PROVENANCE.md` states the SHA-256 of
each file. After an edit of a fixture file, rewrite that table with
`--commit 0123456789abcdef0123456789abcdef01234567 --tag v0.0.0-fixture` into a
scratch directory and copy it back, then run once with GT_UPDATE_GOLDEN=1 and
review the diff of `expected/`.
"""
import support

import json
import os
import tempfile
import unittest

import gtcheck
import rtcm2pack as gen

FIXTURE = os.path.join(support.FIXTURES, "rtcm2pack")
INPUT = os.path.join(FIXTURE, "input")
EXPECTED = os.path.join(FIXTURE, "expected")
CORE_DEF = os.path.join(support.REPO, "model", "core.def")


class RtcmCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.src = support.copy_tree(os.path.join(INPUT, "src"), os.path.join(self.tmp, "src"))

    def make_root(self):
        root = os.path.join(self.tmp, "root")
        support.copy_tree(os.path.join(INPUT, "tools"), os.path.join(root, "tools"))
        return root

    def run_gen(self, root, *more):
        return support.run_main(gen.main, ["--src", self.src, "--out", root, "--core-def", CORE_DEF] + list(more))

    def generated(self):
        root = self.make_root()
        status, out, err = self.run_gen(root)
        self.assertEqual((status, err), (0, ""))
        return root

    def text(self, root, *path):
        with open(os.path.join(root, *path), encoding="utf-8") as fh:
            return fh.read()


class GoldenTree(RtcmCase):
    def test_fixture_gives_the_expected_tree(self):
        root = self.make_root()
        status, out, err = self.run_gen(root)
        self.assertEqual((status, err), (0, ""))
        self.assertIn("self-check      ok", out)
        support.assert_same_tree(self, EXPECTED, root, ignore=("tools/",))

    def test_second_run_and_check_mode_change_nothing(self):
        root = self.generated()
        first = support.tree(root)
        status, _, err = self.run_gen(root, "--check")
        self.assertEqual(status, 0, err)
        self.assertIn("--check: ok", err)
        self.assertEqual(self.run_gen(root)[0], 0)
        self.assertEqual(support.tree(root), first)

    def test_a_changed_source_is_refused(self):
        with open(os.path.join(self.src, gen.PKG_DIR, "rtcmtypes_get.py"), "a", encoding="utf-8") as fh:
            fh.write("\n")
        root = self.make_root()
        status, _, err = self.run_gen(root)
        self.assertEqual(status, 1, err)
        self.assertIn("does not match the SHA-256", err)
        self.assertFalse(os.path.exists(os.path.join(root, "packs")))


class Layout(RtcmCase):
    def setUp(self):
        super().setUp()
        self.root = self.generated()
        self.pdef = self.text(self.root, "packs", "rtcm3", "pack.def")
        self.md = self.text(self.root, "packs", "rtcm3", "pack.md")

    def test_sequential_msb_and_the_message_number(self):
        self.assertIn("layout        sequential\nbit_order     msb\n", self.pdef)
        self.assertIn("kind      m2001\nwhen      12 2001\n", self.pdef)

    def test_types_and_exact_scales(self):
        for line in ("m2001_df012 20 sscale:1/10000", "m2001_df015 10 smscale:1/2147483648",
                     "m2001_df016 10 uiscale:16", "m2001_df017 22 sscale:1/256",
                     "m2001_df018 16 siscale:25000000",
                     "m2001_df019 24 sscale:0.000000000000000000013552527156068805425093160010874271392822265625",
                     "m2001_df020 6 uint", "m2001_df021 8 smag", "m2001_res_02_df020 6 uint"):
            self.assertIn("field     rtcm3." + line + "\n", self.pdef)

    def test_groups_counted_by_the_field_before_them(self):
        self.assertIn("group     rtcm3.m2002_chars count 8\n  field     rtcm3.m2002_chars_df014 8 ascii\nend\n",
                      self.pdef)
        self.assertIn("  group     rtcm3.m2002_sats_inner count 8\n", self.pdef)
        self.assertNotIn("m2002_df013", self.pdef)           # a count is the group's, with no key

    def test_flags_before_gated_parts_are_presence(self):
        self.assertIn("presence  p1 2\nif        p1.1\n  field     rtcm3.m2003_df012 20 sscale:1/10000\nend\n"
                      "if        p1.2\n", self.pdef)
        self.assertNotIn("m2003_df010", self.pdef)

    def test_what_is_not_built(self):
        for row in ("| 2004 | a group counted by field DF013, which does not come just before it |",
                    "| 2005 | the message number is not its first field |",
                    "| 4076_021 | a sub-type of message 4076",
                    "| 2071 | an MSM message"):
            self.assertIn(row, self.md)

    def test_vectors_decode_through_the_pack(self):
        model = gtcheck.Model()
        model.add(self.text(support.REPO, "model", "core.def"), CORE_DEF)
        model.add(self.text(self.root, "model", "rtcm3.def"), "rtcm3")
        pack = gtcheck.load_pack(self.pdef, model, "rtcm3")
        vdir = os.path.join(self.root, "packs", "rtcm3", "vectors")
        names = sorted(os.listdir(vdir))
        self.assertIn("rt-2003-m2003-some-absent.json", names)
        for name in names:
            vec = json.loads(self.text(vdir, name))
            kind, ent, lists = gen.decode(pack, bytes.fromhex(vec["input"]))
            self.assertEqual(kind, vec["model"]["@kind"], name)
            self.assertEqual(gen.encode(pack, kind, ent, lists).hex(), vec["expect"], name)
        absent = json.loads(self.text(vdir, "rt-2003-m2003-some-absent.json"))
        _, ent, _ = gen.decode(pack, bytes.fromhex(absent["input"]))
        self.assertIn("rtcm3.m2003_df012", ent)
        self.assertNotIn("rtcm3.m2003_df016", ent)


class Values(unittest.TestCase):
    def node(self, tr, bits):
        name, _, arg = tr.partition(":")
        return type("N", (), {"tr": name, "bits": bits, "targs": [arg] if arg else []})()

    def test_sign_magnitude_and_integer_scale(self):
        self.assertEqual(gen.decode_value(self.node("smag", 8), 0x85), -5)
        self.assertEqual(gen.encode_value(self.node("smag", 8), -5), 0x85)
        self.assertEqual(gen.decode_value(self.node("uiscale:16", 10), 3), 48)
        self.assertEqual(gen.encode_value(self.node("uiscale:16", 10), 48), 3)
        self.assertEqual(gen.decode_value(self.node("siscale:25000000", 16), 0xFFFF), -25000000)

    def test_exact_scale_text(self):
        F = gen.Fraction
        self.assertEqual(gen.factor_text(F(1, 2 ** 31)), "1/2147483648")
        self.assertEqual(float(gen.factor_text(F(1, 2 ** 66))), 2.0 ** -66)

    def test_scale_expressions_are_exact(self):
        import ast
        r = gen.Reader({"P2_31": ast.parse("4.656612873077393e-10", mode="eval").body})
        for text, want in (("P2_31", gen.Fraction(1, 2 ** 31)), ("1 / 256", gen.Fraction(1, 256)),
                           ("25 * 10 ** 6", gen.Fraction(25000000)), ("0.0001", gen.Fraction(1, 10000))):
            self.assertEqual(r.scale(ast.parse(text, mode="eval").body, "t"), want, text)


if __name__ == "__main__":
    unittest.main()
