"""Tests of the dialect path of tools/gen/mavlink2pack.py (`--dialect`).

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_mavlink2pack_dialect*.py'

The input is the `mavlink2pack` fixture (common.xml, standard.xml, minimal.xml)
with `fixtures/mavlink2pack-dialect/input/`: a dialect `testdialect.xml`
written for these tests, which includes that common.xml, and the
PROVENANCE.md of its pack. A real dialect is checked against the CRC_EXTRA
and length table of the generator; for the test dialect the test computes
that table itself, from the protocol's definition, and puts it into the
generator's table for the run. After an edit of testdialect.xml write its new
SHA-256 into that PROVENANCE.md, then run once with GT_UPDATE_GOLDEN=1 and
review the diff of `expected/`.
"""
import support

import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

import gtcheck
import mavlink2pack as gen
from test_mavlink2pack import crc16_mcrf4xx

COMMON_INPUT = os.path.join(support.FIXTURES, "mavlink2pack", "input")
FIXTURE = os.path.join(support.FIXTURES, "mavlink2pack-dialect")
INPUT = os.path.join(FIXTURE, "input")
EXPECTED = os.path.join(FIXTURE, "expected")
DIALECT = "testdialect"
FORMAT = "mavlink2-testdialect"
MODULE = "mavlinktestdialect"
SIZES = {"char": 1, "uint8_t": 1, "int8_t": 1, "uint16_t": 2, "int16_t": 2, "uint32_t": 4,
         "int32_t": 4, "float": 4, "uint64_t": 8, "int64_t": 8, "double": 8}

# The cross-format case of the test dialect: lat 47.397742, lng 8.545594
# degrees, written by hand as GeoJSON ([lon, lat], no properties).
CROSS = [("TEST_FIX", 5, 1, 1, {"time_boot_ms": 1000, "lat": 473977420, "lng": 85455940, "alt": 12.5},
          '{"type":"Feature","geometry":{"type":"Point","coordinates":[8.545594,47.397742]},"properties":{}}')]


def crc_table(xml_path):
    """{id: (CRC_EXTRA, full payload length)} of every message of a dialect
    file, from the protocol's definition: fields before <extensions/> sorted
    by element size (stable), the checksum over the message name and over
    type, name and array length of each of them; the length over all fields."""
    text = open(xml_path, encoding="utf-8").read()
    table = {}
    for m in re.finditer(r'<message id="(\d+)" name="(\w+)">(.*?)</message>', text, re.S):
        body = m.group(3)
        ext_at = body.find("<extensions/>")
        fields = []
        for f in re.finditer(r'<field type="([^"]+)" name="(\w+)"', body):
            t = re.match(r"(\w+?)(?:\[(\d+)\])?$", f.group(1))
            fields.append((t.group(1), int(t.group(2) or 0), f.group(2), ext_at >= 0 and f.start() > ext_at))
        base = sorted([f for f in fields if not f[3]], key=lambda f: -SIZES[f[0]])
        data = (m.group(2) + " ").encode()
        for typ, n, name, _ in base:
            data += (typ + " " + name + " ").encode() + (bytes([n]) if n else b"")
        crc = crc16_mcrf4xx(data)
        length = sum(SIZES[t] * (n or 1) for t, n, _, _ in fields)
        table[int(m.group(1))] = ((crc & 0xFF) ^ (crc >> 8), length)
    return table


class DialectCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        table = crc_table(os.path.join(INPUT, "sources", "testdialect.xml"))
        for patch in (mock.patch.dict(gen.KNOWN_DIALECT, {DIALECT: table}),
                      mock.patch.dict(gen.POSITION_NOTES, {"TEST_FIX": "the vehicle (test)"}),
                      mock.patch.dict(gen.CROSS_DIALECT, {DIALECT: CROSS})):
            patch.start()
            self.addCleanup(patch.stop)

    def make_root(self, name="root", common_args=()):
        """The two fixture inputs in one directory, with mavlink2 generated."""
        root = support.copy_tree(COMMON_INPUT, os.path.join(self.tmp, name))
        support.copy_tree(INPUT, root)
        status, _, err = support.run_main(gen.main, ["--out", root] + list(common_args))
        self.assertEqual((status, err), (0, ""))
        return root

    def run_dialect(self, root, *more):
        return support.run_main(gen.main, ["--out", root, "--dialect", DIALECT] + list(more))

    def pack_dir(self, root):
        return os.path.join(root, "packs", FORMAT)

    def load(self, root):
        model = gtcheck.Model()
        model.add(gen.CORE_STAND_IN, "<core stand-in>")
        for name in ("mavlink", MODULE):
            path = os.path.join(root, "model", name + ".def")
            model.add(open(path, encoding="utf-8").read(), path)
        path = os.path.join(self.pack_dir(root), "pack.def")
        return gtcheck.load_pack(open(path, encoding="utf-8").read(), model, path)

    def refused(self, root, *more):
        status, _, err = self.run_dialect(root, *more)
        self.assertEqual(status, 1, err)
        self.assertEqual(err.count("\n"), 1, err)
        self.assertTrue(err.startswith("mavlink2pack: "), err)
        self.assertFalse(os.path.exists(os.path.join(self.pack_dir(root), "pack.md")))
        return err


class GoldenTree(DialectCase):
    def test_fixture_gives_the_expected_tree(self):
        root = self.make_root()
        status, out, err = self.run_dialect(root)
        self.assertEqual((status, err), (0, ""))
        self.assertIn("self-check        ok", out)
        written = os.path.join(self.tmp, "dialect-only")
        os.makedirs(os.path.join(written, "model"))
        shutil.copy(os.path.join(root, "model", MODULE + ".def"), os.path.join(written, "model"))
        shutil.copytree(self.pack_dir(root), os.path.join(written, "packs", FORMAT))
        support.assert_same_tree(self, EXPECTED, written, ignore=("packs/%s/PROVENANCE.md" % FORMAT,))

    def test_check_after_a_run_passes_and_a_second_run_changes_nothing(self):
        root = self.make_root()
        self.assertEqual(self.run_dialect(root)[0], 0)
        before = support.tree(root)
        status, _, err = self.run_dialect(root, "--check")
        self.assertEqual(status, 0, err)
        self.assertIn("--check: ok", err)
        self.assertEqual(self.run_dialect(root)[0], 0)
        self.assertEqual(support.tree(root), before)

    def test_mavlink2_is_not_touched(self):
        root = self.make_root()
        common = {rel: data for rel, data in support.tree(root).items() if "testdialect" not in rel}
        self.assertEqual(self.run_dialect(root)[0], 0)
        after = {rel: data for rel, data in support.tree(root).items() if "testdialect" not in rel}
        self.assertEqual(after, common)


class WhatThePackHolds(DialectCase):
    def setUp(self):
        super().setUp()
        self.root = self.make_root()
        status, _, err = self.run_dialect(self.root)
        self.assertEqual((status, err), (0, ""))
        self.pack = self.load(self.root)
        self.kinds = {k.name: k for k in self.pack.kinds}

    def fields(self, kind):
        return {n.key: n for n in self.kinds[kind].lines if n.d == "field"}

    def test_only_the_dialects_own_messages_are_kinds(self):
        self.assertEqual(list(self.kinds), ["test_fix", "test_draft", "test_half"])

    def test_a_message_with_no_field_to_map_gets_no_kind_and_is_listed(self):
        md = open(os.path.join(self.pack_dir(self.root), "pack.md"), encoding="utf-8").read()
        self.assertNotIn("test_blob", self.kinds)
        self.assertIn("| TEST_BLOB | 60101 | `data` `uint8_t[16]` |", md)

    def test_header_keys_come_from_module_mavlink(self):
        self.assertEqual([u for u in self.pack.uses if u != "core"], ["mavlink", MODULE])
        common = [n.key for n in self.pack.common if n.d == "field"]
        self.assertEqual(common, ["mavlink.seq", "mavlink.sysid", "mavlink.compid"])

    def test_lng_is_core_lon_when_paired_with_lat(self):
        f = self.fields("test_fix")
        self.assertEqual((f["lat"].tr, f["lon"].tr), ("sscale", "sscale"))
        self.assertNotIn(MODULE + ".lng", f)

    def test_a_latitude_without_a_longitude_stays_raw(self):
        f = self.fields("test_half")
        self.assertIn(MODULE + ".lat_dege7", f)
        self.assertNotIn("lat", f)

    def test_a_field_named_like_a_header_key_takes_the_message_name(self):
        self.assertIn(MODULE + ".test_half_seq", self.fields("test_half"))

    def test_wip_and_deprecated_messages_are_named_in_pack_md(self):
        md = open(os.path.join(self.pack_dir(self.root), "pack.md"), encoding="utf-8").read()
        self.assertIn("work in progress", md)
        self.assertIn("`test_draft`", md)
        self.assertIn("deprecated: `test_half`", md)

    def test_geojson_vector_has_the_hand_written_expect(self):
        path = os.path.join(self.pack_dir(self.root), "vectors", "x-01-test_fix-to-geojson.json")
        vec = json.load(open(path, encoding="utf-8"))
        # the hand-written expect, with the uid the mavlink module derives from the system id
        self.assertEqual(vec["expect"], CROSS[0][5][:-1] + ',"id":"%d"}' % CROSS[0][2])
        self.assertEqual((vec["model"]["lat"], vec["model"]["lon"]), ("47.397742", "8.545594"))


class Refusals(DialectCase):
    def test_a_dialect_with_no_crc_table_is_refused(self):
        root = self.make_root()
        with mock.patch.dict(gen.KNOWN_DIALECT, clear=True):
            err = self.refused(root)
        self.assertIn("no CRC_EXTRA table for dialect testdialect", err)

    def test_a_crc_extra_that_differs_from_the_table_is_refused(self):
        root = self.make_root()
        bad = dict(gen.KNOWN_DIALECT[DIALECT])
        bad[60100] = (bad[60100][0] ^ 1, bad[60100][1])
        with mock.patch.dict(gen.KNOWN_DIALECT, {DIALECT: bad}):
            err = self.refused(root)
        self.assertIn("TEST_FIX: CRC_EXTRA", err)

    def test_an_id_also_used_by_an_included_file_is_refused(self):
        root = self.make_root()
        path = os.path.join(root, "sources", "testdialect.xml")
        text = open(path, encoding="utf-8").read().replace('id="60103"', 'id="1"')
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        err = self.refused(root, "--provenance", self.rehash(root))
        self.assertIn("message id 1 is also declared at sources/common.xml", err)

    def test_a_changed_source_file_is_refused(self):
        root = self.make_root()
        with open(os.path.join(root, "sources", "testdialect.xml"), "a", encoding="utf-8") as fh:
            fh.write("\n")
        self.assertIn("does not match the SHA-256", self.refused(root))

    def test_a_core_binding_with_no_position_note_is_refused(self):
        root = self.make_root()
        with mock.patch.dict(gen.POSITION_NOTES, clear=True):
            self.assertIn("TEST_FIX binds core lat/lon but has no POSITION_NOTES entry", self.refused(root))

    def test_without_module_mavlink_the_run_is_refused(self):
        root = self.make_root()
        os.remove(os.path.join(root, "model", "mavlink.def"))
        self.assertIn("model/mavlink.def", self.refused(root))

    def rehash(self, root):
        """A PROVENANCE.md with the SHA-256 of the edited dialect file."""
        import hashlib
        src = os.path.join(self.pack_dir(root), "PROVENANCE.md")
        digest = hashlib.sha256(open(os.path.join(root, "sources", "testdialect.xml"), "rb").read()).hexdigest()
        text = re.sub(r"(\| `testdialect.xml` \|[^|]*\| `)[0-9a-f]{64}", lambda m: m.group(1) + digest,
                      open(src, encoding="utf-8").read())
        path = os.path.join(self.tmp, "PROVENANCE.md")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return path


class Options(DialectCase):
    def test_max_array_maps_a_long_array_and_gives_its_message_a_kind(self):
        root = self.make_root()
        status, _, err = self.run_dialect(root, "--max-array", "16")
        self.assertEqual((status, err), (0, ""))
        kinds = {k.name: k for k in self.load(root).kinds}
        keys = [n.key for n in kinds["test_blob"].lines if n.d == "field"]
        self.assertEqual(keys, ["%s.data_%d" % (MODULE, i) for i in range(16)])

    def test_compat_flags_map_both_flag_bytes_from_module_mavlink(self):
        root = self.make_root(common_args=("--compat-flags",))
        status, _, err = self.run_dialect(root, "--compat-flags")
        self.assertEqual((status, err), (0, ""))
        pack = self.load(root)
        common = {n.key: (n.start, n.bits) for n in pack.common if n.d == "field"}
        self.assertEqual(common["mavlink.incompat_flags"], (16, 8))
        self.assertEqual(common["mavlink.compat_flags"], (24, 8))

    def test_compat_flags_without_the_keys_in_module_mavlink_is_refused(self):
        root = self.make_root()
        self.assertIn("declares no key incompat_flags", self.refused(root, "--compat-flags"))

    def test_max_array_below_eight_is_a_refusal(self):
        root = self.make_root()
        self.assertIn("--max-array is 8 to 255", self.refused(root, "--max-array", "4"))


if __name__ == "__main__":
    unittest.main()
