"""Tests of tools/gen/uni2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_uni2pack*.py'

`fixtures/uni2pack/input/src/` is a small pyunigps-shaped tree written for these
tests: messages with a case for each rule.
`input/tools/gen/sources/unicore-PROVENANCE.md` states the SHA-256 of each file.
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
import uni2pack as gen

FIXTURE = os.path.join(support.FIXTURES, "uni2pack")
INPUT = os.path.join(FIXTURE, "input")
EXPECTED = os.path.join(FIXTURE, "expected")
CORE_DEF = os.path.join(support.REPO, "model", "core.def")


class UniCase(unittest.TestCase):
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


class GoldenTree(UniCase):
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
        with open(os.path.join(self.src, gen.PKG_DIR, "unitypes_get.py"), "a", encoding="utf-8") as fh:
            fh.write("\n")
        root = self.make_root()
        status, _, err = self.run_gen(root)
        self.assertEqual(status, 1, err)
        self.assertIn("does not match the SHA-256", err)
        self.assertFalse(os.path.exists(os.path.join(root, "packs")))


class Layout(UniCase):
    def setUp(self):
        super().setUp()
        self.root = self.generated()
        self.pdef = self.text(self.root, "packs", "unicore", "pack.def")
        self.md = self.text(self.root, "packs", "unicore", "pack.md")

    def test_header_and_kind_selection(self):
        self.assertIn("field  unicore.header_tow 0:72:32 uint\n", self.pdef)
        self.assertNotIn("header_msgid", self.pdef)
        self.assertIn("kind      fixnav\nwhen      0:8:16 2118\nwhen      0:24:16 67\n", self.pdef)

    def test_types_bits_groups_and_scales(self):
        for line in ("fixnav_lat 0:200:64 f64", "fixnav_stationid 0:424:32 ascii", "fixnav_mode 0:457:3 uint",
                     "fixnav_level_02 0:496:16 sscale:1/100", "fixnav_wide_02 0:576:16 uint",
                     "fixnav_drift 0:624:32 f32scale:1/128", "fixnav_offset 0:656:32 twos",
                     "fixnav_age 0:688:16 uscale:1/4"):
            self.assertIn("field     unicore." + line + "\n", self.pdef)

    def test_no_core_key_without_a_stated_datum(self):
        self.assertNotIn("field     lat ", self.pdef)
        self.assertIn("datumid", self.md)

    def test_what_is_not_built(self):
        for row in ("| SATS | 1042 | a group repeated by field `numsat` |",
                    "| INFO | 37 | a field of type CXXX whose length the payload length gives |",
                    "| NOID | - | no message ID in UNI_MSGIDS |"):
            self.assertIn(row, self.md)

    def test_vectors_decode_through_the_pack(self):
        model = gtcheck.Model()
        model.add(self.text(support.REPO, "model", "core.def"), CORE_DEF)
        model.add(self.text(self.root, "model", "unicore.def"), "unicore")
        pack = gtcheck.load_pack(self.pdef, model, "unicore")
        for name in sorted(os.listdir(os.path.join(self.root, "packs", "unicore", "vectors"))):
            vec = json.loads(self.text(self.root, "packs", "unicore", "vectors", name))
            data = bytes.fromhex(vec["input"])
            self.assertEqual(int.from_bytes(data[3:5], "little"), len(data) - 21, name)
            kind, ent = gen.decode(pack, data)
            self.assertEqual(gen.encode(pack, kind, ent).hex(), vec["expect"], name)


class Values(unittest.TestCase):
    def test_crc32_check_value(self):
        # the reflected CRC-32 of the ASCII digits 1 to 9 with initial value 0 and no final XOR
        self.assertEqual(gen.crc32(b"123456789"), 0x2DFD2D88)


if __name__ == "__main__":
    unittest.main()
