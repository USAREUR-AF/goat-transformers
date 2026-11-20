"""Tests of tools/gen/ubx2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_ubx2pack*.py'

`fixtures/ubx2pack/input/src/` is a small pyubx2-shaped tree written for these
tests: the core names, GET, SET and POLL definitions with a case for each rule,
a variant table, and stand-ins for the three example files the provenance
names; `input/ublox/` holds stand-ins for the ublox_msgs files that state the
units, the .msg files with a `.txt` suffix (the boundary gate admits no .msg
file; each test copies them back without it).
`input/tools/gen/sources/ubx-PROVENANCE.md` states the SHA-256 of each
file. After an edit of a fixture file, rewrite that table with
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
import ubx2pack as gen

FIXTURE = os.path.join(support.FIXTURES, "ubx2pack")
INPUT = os.path.join(FIXTURE, "input")
EXPECTED = os.path.join(FIXTURE, "expected")
CORE_DEF = os.path.join(support.REPO, "model", "core.def")
TRACK_DEF = os.path.join(support.REPO, "model", "track.def")


class UbxCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.src = support.copy_tree(os.path.join(INPUT, "src"), os.path.join(self.tmp, "src"))
        self.ublox = support.copy_tree(os.path.join(INPUT, "ublox"), os.path.join(self.tmp, "ublox"))
        for directory, _, names in os.walk(self.ublox):
            for name in names:
                if name.endswith(".msg.txt"):          # the boundary gate admits no .msg file
                    os.rename(os.path.join(directory, name), os.path.join(directory, name[:-4]))

    def make_root(self):
        root = os.path.join(self.tmp, "root")
        support.copy_tree(os.path.join(INPUT, "tools"), os.path.join(root, "tools"))
        return root

    def run_gen(self, root, *more):
        return support.run_main(gen.main, ["--src", self.src, "--ublox-msgs", self.ublox, "--out", root,
                                           "--core-def", CORE_DEF, "--track-def", TRACK_DEF] + list(more))

    def generated(self):
        root = self.make_root()
        status, out, err = self.run_gen(root)
        self.assertEqual((status, err), (0, ""))
        return root

    def text(self, root, *path):
        with open(os.path.join(root, *path), encoding="utf-8") as fh:
            return fh.read()

    def pack(self, root, fmt, module):
        model = gtcheck.Model()
        model.add(self.text(support.REPO, "model", "core.def"), CORE_DEF)
        model.add(self.text(support.REPO, "model", "track.def"), TRACK_DEF)
        model.add(self.text(root, "model", module + ".def"), module)
        return gtcheck.load_pack(self.text(root, "packs", fmt, "pack.def"), model, fmt)


class GoldenTree(UbxCase):
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

    def test_a_changed_units_file_is_refused(self):
        with open(os.path.join(self.ublox, "ublox_msgs", "msg", "NavPVT.msg"), "a", encoding="utf-8") as fh:
            fh.write("\n")
        status, _, err = self.run_gen(self.make_root())
        self.assertEqual(status, 1, err)
        self.assertIn("does not match the SHA-256", err)

    def test_a_changed_source_is_refused(self):
        with open(os.path.join(self.src, gen.PKG_DIR, "ubxtypes_get.py"), "a", encoding="utf-8") as fh:
            fh.write("\n")
        root = self.make_root()
        status, _, err = self.run_gen(root)
        self.assertEqual(status, 1, err)
        self.assertIn("does not match the SHA-256", err)
        self.assertFalse(os.path.exists(os.path.join(root, "packs")))

    def test_the_source_is_read_not_run(self):
        # a statement that would fail if the file were run changes nothing
        path = os.path.join(self.src, gen.PKG_DIR, "ubxtypes_poll.py")
        source = gen.Source(self.src)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("raise SystemExit(3)\n")
        self.assertEqual(gen.Source(self.src).defs["POLL"], source.defs["POLL"])


class Layout(UbxCase):
    def setUp(self):
        super().setUp()
        self.root = self.generated()
        self.nav = self.text(self.root, "packs", "ubx-nav", "pack.def")
        self.md = self.text(self.root, "packs", "ubx-nav", "pack.md")

    def test_frame_header_and_kind_selection(self):
        self.assertIn("when   0:0:8 181\nwhen   0:8:8 98\nwhen   0:16:8 1\n", self.nav)
        self.assertIn("kind      nav_pvt\nwhen      0:24:8 7\nwhen      0:32:16 52\n", self.nav)

    def test_bits_groups_arrays_scales_and_padding(self):
        for line in ("ubxnav.nav_pvt_gnssfixok 0:88:1 uint",
                     "ubxnav.nav_pvt_psmstate 0:90:3 uint",
                     "ubxnav.nav_pvt_headveh 0:392:32 sscale:45/4194304",
                     "ubxnav.nav_pvt_pdop 0:424:16 uscale:1/100",
                     "ubxnav.nav_mixed_name 0:56:48 ascii",
                     "ubxnav.nav_mixed_ratio 0:104:32 f32",
                     "ubxnav.nav_mixed_value 0:136:64 f64",
                     "ubxnav.nav_mixed_small 0:200:8 twos",
                     "ubxnav.nav_mixed_cno_02 0:232:8 uscale:16",
                     "ubxnav.nav_mixed_big_01 0:240:64 uint",
                     "ubxnav.nav_mixed_big_02 0:304:32 uint",
                     "ubxnav.nav_mixed_mid 0:340:2 twos"):
            self.assertIn("field     " + line + "\n", self.nav)
        self.assertIn("const     0:342:10 0\n", self.nav)

    def test_core_keys_only_with_evidence(self):
        for line in ("lon 0:104:32 sscale:1/10000000", "lat 0:136:32 sscale:1/10000000",
                     "hae 0:168:32 sscale:1/1000"):
            self.assertEqual(self.nav.count("field     " + line + "\n"), 2)     # NAV-PVT and its alias NAV-POSLLH
        for line in ("track.vel_north_ms 0:232:32 sscale:1/1000", "track.vel_up_ms 0:296:32 sscale:-0.001",
                     "speed_ms 0:328:32 sscale:1/1000", "track.vel_east_ms", "uses          track"):
            self.assertIn(line, self.nav)
        self.assertIn("field     course 0:360:32 sscale:1/100000\n", self.nav)
        # a field the units file does not name stays raw, with its own scale
        self.assertIn("ubxnav.nav_pvt_headveh 0:392:32 sscale:45/4194304", self.nav)
        for line in ("track.vel_north_ms 0:80:32 sscale:1/100", "track.vel_up_ms 0:144:32 sscale:-0.01",
                     "speed_ms 0:176:32 uscale:1/100", "course 0:208:32 sscale:1/100000"):
            self.assertIn("field     " + line + "\n", self.nav)
        mga = self.text(self.root, "packs", "ubx-mga", "pack.def")
        self.assertIn("ubxmga.mga_ini_pos_set_lat 0:64:32 sscale:1/10000000", mga)

    def test_identity_and_selector_bytes(self):
        mga = self.text(self.root, "packs", "ubx-mga", "pack.def")
        self.assertIn("kind      mga_ini_pos_set\nwhen      0:24:8 64\nwhen      0:32:16 10\nwhen      0:48:8 0\n", mga)
        first = self.nav.index("kind      nav_variantb\n")
        self.assertIn("when      0:48:8 1\n", self.nav[first:first + 120])
        self.assertLess(first, self.nav.index("kind      nav_variant\n"))

    def test_what_is_not_built(self):
        for row in ("| NAV-COUNTED | GET | 0x01 0x51 | a group repeated by field `numCh` |",
                    "| NAV-TEXT | GET | 0x01 0x52 | text that runs to the end of the payload |",
                    "| NAV-MIXED | SET | 0x01 0x50 | the same class, id and payload length as kind `nav_mixed` |",
                    "| NAV-PVT | POLL | 0x01 0x07 | an empty payload: a kind needs at least one field |"):
            self.assertIn(row, self.md)
        self.assertFalse(os.path.exists(os.path.join(self.root, "packs", "ubx-foo")))

    def test_vectors_decode_through_the_pack(self):
        pack = self.pack(self.root, "ubx-nav", "ubxnav")
        vdir = os.path.join(self.root, "packs", "ubx-nav", "vectors")
        for name in sorted(os.listdir(vdir)):
            vec = json.loads(self.text(vdir, name))
            kind, ent = gen.decode(pack, bytes.fromhex(vec["input"]))
            self.assertEqual(kind, vec["model"]["@kind"], name)
        cross = json.loads(self.text(vdir, "x-01-nav_pvt-to-geojson.json"))
        self.assertEqual(cross["model"], {"@kind": "nav_pvt", "lon": "8.545594", "lat": "47.397742", "hae": "488.25",
                                          "track.vel_north_ms": "1.5", "track.vel_east_ms": "-2.5",
                                          "track.vel_up_ms": "-0.3", "speed_ms": "12.34", "course": "45.12345"})


class Units(unittest.TestCase):
    def test_a_field_binds_only_when_the_file_states_the_unit(self):
        leaves = [gen.Leaf("velN", "s", 0, 32, None), gen.Leaf("gSpeed", "s", 32, 32, None)]
        stated = {"NavPVT.msg": {"vel_n": ("north velocity [mm/s]", "mm/s"),
                                 "g_speed": ("ground speed (2-d) [cm/s]", "cm/s")}}
        bound = gen.unit_bindings(stated, "NAV-PVT", leaves)
        self.assertEqual(sorted(bound), ["velN"])
        self.assertEqual(bound["velN"][:2], ("track.vel_north_ms", "sscale:1/1000"))

    def test_msg_lines(self):
        units = gen.read_msg_units("uint32 i_tow  # time [ms]\nint32 vel_d # down velocity [mm/s]\n# a comment\n")
        self.assertEqual(units["vel_d"], ("down velocity [mm/s]", "mm/s"))


class Serializer(unittest.TestCase):
    def test_checksum(self):
        # 8-bit Fletcher over class, id and length of an empty NAV-PVT poll
        self.assertEqual(gen.checksum(bytes([0x01, 0x07, 0x00, 0x00])), bytes([0x08, 0x19]))

    def test_a_scale_beyond_64_bits_is_written_as_exact_decimal_text(self):
        F = gen.Fraction
        self.assertEqual(gen.factor_text(F(45, 4194304)), "45/4194304")
        self.assertEqual(gen.factor_text(F(1, 2 ** 63 - 1)), "1/9223372036854775807")
        text = gen.factor_text(F(1, 2 ** 66))
        self.assertEqual(text, "0.000000000000000000013552527156068805425093160010874271392822265625")
        self.assertEqual(float(text), 2.0 ** -66)          # the nearest double is the value
        self.assertEqual(gen.factor_text(F(-3, 2 ** 70))[:3], "-0.")
        self.assertEqual(gen.factor_text(F(2 ** 70)), str(2 ** 70))
        for f in (F(1, 2 ** 66), F(-3, 2 ** 70), F(7, 10 ** 25)):
            self.assertEqual(F(gen.Decimal(gen.factor_text(f))), f)
            self.assertNotIn("e", gen.factor_text(f))
        with self.assertRaises(gen.GenError):
            gen.factor_text(F(1, 3 * 2 ** 64))              # no exact decimal text

    def test_scale_names(self):
        F = gen.Fraction
        self.assertEqual(gen.scale_of_name("E1_N7"), F(1, 10 ** 7))
        self.assertEqual(gen.scale_of_name("P2_N24"), F(1, 2 ** 24))
        self.assertEqual(gen.scale_of_name("P2_P4"), F(16))
        self.assertIsNone(gen.scale_of_name("U4"))
        self.assertEqual(gen.exact(0.25, "t"), F(1, 4))


if __name__ == "__main__":
    unittest.main()
