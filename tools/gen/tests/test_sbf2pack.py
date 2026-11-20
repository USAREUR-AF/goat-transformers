"""Tests of tools/gen/sbf2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_sbf2pack*.py'

`fixtures/sbf2pack/input/src/` is a small pysbf2-shaped tree written for these
tests: two block groups with a block for each rule.
`input/tools/gen/sources/sbf-PROVENANCE.md` states the SHA-256 of each file.
After an edit of a fixture file, rewrite that table with
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
import sbf2pack as gen

FIXTURE = os.path.join(support.FIXTURES, "sbf2pack")
INPUT = os.path.join(FIXTURE, "input")
EXPECTED = os.path.join(FIXTURE, "expected")
CORE_DEF = os.path.join(support.REPO, "model", "core.def")


class SbfCase(unittest.TestCase):
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


class GoldenTree(SbfCase):
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
        with open(os.path.join(self.src, gen.PKG_DIR, "sbftypes_blocks.py"), "a", encoding="utf-8") as fh:
            fh.write("\n")
        root = self.make_root()
        status, _, err = self.run_gen(root)
        self.assertEqual(status, 1, err)
        self.assertIn("does not match the SHA-256", err)
        self.assertFalse(os.path.exists(os.path.join(root, "packs")))


class Layout(SbfCase):
    def setUp(self):
        super().setUp()
        self.root = self.generated()
        self.pdef = self.text(self.root, "packs", "sbf-position", "pack.def")
        self.md = self.text(self.root, "packs", "sbf-other", "pack.md")

    def test_header_block_number_and_length(self):
        self.assertIn("field  sbf.revision 0:13:3 uint\n", self.pdef)
        # body 68 bytes, padded to 72, plus the 8-byte header the length counts
        self.assertIn("kind      fix\nwhen      0:0:13 4007\nwhen      0:16:16 76\n", self.pdef)
        self.assertIn("const     0:568:8 0\n", self.pdef)

    def test_types_bits_and_scales(self):
        for line in ("fix_type 0:80:4 uint", "fix_two_d 0:87:1 uint", "fix_latitude 0:88:64 f64",
                     "fix_speed 0:280:32 f32", "fix_drift 0:312:32 f32scale:1/100", "fix_name 0:344:48 ascii",
                     "fix_wide_01 0:392:64 uint", "fix_wide_02 0:456:32 uint", "fix_age 0:488:16 uscale:1/100",
                     "fix_count 0:504:16 uiscale:1000", "fix_tilt 0:520:16 sscale:1/32", "fix_spin 0:536:32 twos"):
            self.assertIn("field     sbfposition." + line + "\n", self.pdef)

    def test_a_counted_group_ending_the_body(self):
        other = self.text(self.root, "packs", "sbf-other", "pack.def")
        self.assertIn("kind      track\nwhen      0:0:13 4101\nrequires", other)
        self.assertIn("field     sbf.length 0:16:16 uint\n", other)
        self.assertIn("group     sbfother.track_sv 0:96 item 32 count 0:64:8\n"
                      "  field   sbfother.track_sv_svid 0:0:8 uint\n", other)
        self.assertNotIn("track_n ", other)

    def test_no_core_key_for_radians(self):
        self.assertNotIn("field     lat ", self.pdef)
        self.assertIn("sbfposition.fix_latitude", self.pdef)

    def test_what_is_not_built(self):
        for row in ("| Satellites | 4027 | a group counted by field `N` whose items vary: a sub-block padded to a length the block states |",
                    "| Odd | 4102 | a group counted by field `N` whose items or fixed part are not a multiple of 4 bytes",
                    "| Optional | 4060 | a part present only when field `Mode` is 1 |",
                    "| Blob | 4061 | a field of type V001 whose length the block length gives |",
                    "| Unnumbered | - | no block number in SBF_MSGIDS |"):
            self.assertIn(row, self.md)
        self.assertIn("| Marker | 5921 | an empty body", self.text(self.root, "packs", "sbf-position", "pack.md"))

    def test_vectors_decode_through_the_pack(self):
        model = gtcheck.Model()
        model.add(self.text(support.REPO, "model", "core.def"), CORE_DEF)
        model.add(self.text(self.root, "model", "sbf.def"), "sbf")
        model.add(self.text(self.root, "model", "sbfposition.def"), "sbfposition")
        pack = gtcheck.load_pack(self.pdef, model, "sbf-position")
        vec = json.loads(self.text(self.root, "packs", "sbf-position", "vectors", "rt-4007-fix.json"))
        data = bytes.fromhex(vec["input"])
        self.assertEqual(int.from_bytes(data[2:4], "little"), len(data) + 4)   # the length counts sync and CRC
        kind, ent = gen.decode(pack, data)
        self.assertEqual(kind, "fix")
        self.assertEqual(gen.encode(pack, kind, ent).hex(), vec["expect"])


class Values(unittest.TestCase):
    def test_crc_check_value(self):
        self.assertEqual(gen.crc16(b"123456789"), 0x31C3)

    def test_scale_names(self):
        F = gen.Fraction
        self.assertEqual(gen.scale_of_name("E1_N2"), F(1, 100))
        self.assertEqual(gen.scale_of_name("E1_P3"), F(1000))
        self.assertEqual(gen.scale_of_name("P2_N5"), F(1, 32))
        self.assertIsNone(gen.scale_of_name("U4"))

    def test_integer_scale_is_exact(self):
        node = type("N", (), {"tr": "uiscale", "bits": 16, "targs": ["1000"]})()
        self.assertEqual(gen.decode_value(node, 7), 7000)
        self.assertEqual(gen.encode_value(node, 7000), 7)


if __name__ == "__main__":
    unittest.main()
