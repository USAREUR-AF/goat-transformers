"""Tests of tools/gen/uorb2pack.py, PX4 uORB topics as ULog data.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_uorb2pack*.py'

`fixtures/uorb2pack/input/px4/` is a small PX4-like tree written for these
tests: message definitions under `msg/` and `msg/versioned/`, and placeholder
files where the generator records the SHA-256 of PX4's licence, documentation
and generator files. The boundary gate admits no `.msg` or `.em` file, so those
carry a `.txt` suffix, and each test copies the tree to a scratch directory
without it. `expected/` is the tree a run with `--commit` writes; after a
deliberate change run once with GT_UPDATE_GOLDEN=1 and review the diff.
"""
import support

import json
import os
import shutil
import tempfile
import unittest

import uorb2pack as gen

FIXTURES = os.path.join(support.FIXTURES, "uorb2pack")
CORE_DEF = os.path.join(support.REPO, "model", "core.def")
COMMIT = "0123456789abcdef0123456789abcdef01234567"


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.px4 = os.path.join(self.tmp, "px4")
        support.copy_tree(os.path.join(FIXTURES, "input", "px4"), self.px4)
        for directory, _, names in os.walk(self.px4):
            for name in names:
                if name.endswith((".msg.txt", ".em.txt")):
                    os.rename(os.path.join(directory, name), os.path.join(directory, name[:-4]))
        self.root = os.path.join(self.tmp, "root")
        os.makedirs(os.path.join(self.root, "model"))
        shutil.copy(CORE_DEF, os.path.join(self.root, "model", "core.def"))

    def run_gen(self, *more):
        return support.run_main(gen.main, ["--px4", self.px4, "--out", self.root] + list(more))

    def first_run(self):
        status, out, err = self.run_gen("--commit", COMMIT, "--tag", "v0.0.0")
        self.assertEqual(status, 0, err)
        return out

    def test_golden(self):
        self.first_run()
        support.assert_same_tree(self, os.path.join(FIXTURES, "expected"), self.root,
                                 ignore=("model/core.def",))

    def test_check_mode(self):
        self.first_run()
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 0, err)
        path = os.path.join(self.root, "packs", "px4-ulog-holder", "pack.md")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("edited\n")
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("packs/px4-ulog-holder/pack.md", err)

    def test_changed_source_is_refused(self):
        self.first_run()
        with open(os.path.join(self.px4, "msg", "Item.msg"), "a", encoding="utf-8") as fh:
            fh.write("uint8 extra\n")
        status, _, err = self.run_gen()
        self.assertEqual(status, 1)
        self.assertIn("msg/Item.msg: SHA-256", err)

    def test_layout_rule(self):
        msgs = gen.load_catalog(self.px4)
        self.assertEqual(gen.format_string(msgs, "Holder"), [
            "uint64 timestamp", "float64 total", "uint16 code", "uint8 count", "char[8] label",
            "uint8[70] blob", "bool[3] flags", "uint8[4] _padding0", "item[2] items", "item last"])
        lay = gen.layout(msgs, "Holder")
        self.assertEqual([(s.field.name if s.field else "pad", s.offset) for s in lay.slots], [
            ("timestamp", 0), ("total", 8), ("code", 16), ("count", 18), ("label", 19),
            ("blob", 27), ("flags", 97), ("pad", 100), ("items", 104), ("last", 136)])
        self.assertEqual((lay.size, lay.end_padding, lay.logged_size), (152, 0, 152))
        item = gen.layout(msgs, "Item")
        self.assertEqual([(s.field.name if s.field else "pad", s.offset) for s in item.slots],
                         [("timestamp", 0), ("value", 8), ("delta", 12), ("mode", 14), ("pad", 15)])
        self.assertEqual((item.size, item.logged_size), (16, 15))
        vgp = gen.layout(msgs, "VehicleGlobalPosition")
        self.assertEqual((vgp.size, vgp.logged_size), (40, 34))

    def test_pack_lines(self):
        self.first_run()
        with open(os.path.join(self.root, "packs", "px4-ulog-holder", "pack.def"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("field  px4ulog.holder_label  0:152:64  ascii", text)
        self.assertIn("group  px4ulog.holder_blob  0:216  item 8  count 70", text)
        self.assertIn("field  px4ulog.holder_items_1_delta  0:1056:16  twos", text)
        self.assertIn("const  0:1208:8  0", text)       # the last byte of the nested `last`
        with open(os.path.join(self.root, "packs", "px4-ulog-estimator-global-position", "pack.def"),
                  encoding="utf-8") as fh:
            self.assertIn("field  lat  0:64:64  f64", fh.read())

    def test_time_and_height_bindings(self):
        self.first_run()
        with open(os.path.join(self.root, "packs", "px4-ulog-sensor-gps", "pack.def"), encoding="utf-8") as fh:
            text = fh.read()
        # layout: timestamp 0, latitude 8, longitude 16, altitude_ellipsoid_m 24, time_utc_usec 32
        self.assertIn("field  hae  0:192:64  f64", text)
        self.assertIn("field  time_ms  0:256:64  uiscale:1/1000  absent 0", text)
        with open(os.path.join(self.root, "model", "px4ulog.def"), encoding="utf-8") as fh:
            self.assertNotIn("sensor_gps_time_utc_usec", fh.read())   # bound from the first run: no raw key
        self.assertEqual(gen.utc_ms(1970, 1, 1, 0, 0, 0, 0), 0)
        self.assertEqual(gen.utc_ms(2000, 3, 1, 0, 0, 1, 5), 951868801005)
        self.assertEqual(gen.decode_value(1500, 64, "uiscale:1/1000"), 2)
        self.assertEqual(gen.decode_value(2500, 64, "uiscale:1/1000"), 3)
        self.assertEqual(gen.encode_value(3, 64, "uiscale:1/1000"), 3000)

    def test_bound_field_keeps_its_earlier_raw_key(self):
        names = os.path.join(self.root, "tools", "gen", "names")
        os.makedirs(names)
        with open(os.path.join(names, "px4-ulog.json"), "w", encoding="utf-8") as fh:
            json.dump({"SensorGps:time_utc_usec": "sensor_gps_time_utc_usec"}, fh)
        self.first_run()
        with open(os.path.join(self.root, "model", "px4ulog.def"), encoding="utf-8") as fh:
            model = fh.read()
        self.assertRegex(model, r'key  sensor_gps_time_utc_usec +int +- +"SensorGps.time_utc_usec \(uint64\); bound to `time_ms`')
        with open(os.path.join(self.root, "packs", "px4-ulog-sensor-gps", "pack.def"), encoding="utf-8") as fh:
            self.assertNotIn("px4ulog.sensor_gps_time_utc_usec", fh.read())

    def test_compare_formats(self):
        msgs = gen.load_catalog(self.px4)
        jdir = os.path.join(self.tmp, "json")
        os.makedirs(jdir)
        codes = {v: k for k, v in gen.PX4_CODES.items()}
        for name in msgs:
            fields = []
            for entry in gen.format_string(msgs, name):
                t, rest = entry.split(" ", 1)
                base, br = (t.split("[", 1) + [""])[:2]
                if base in codes:
                    t = chr(codes[base]) + ("[" + br if br else "")
                fields.append("%s %s" % (t, rest))
            with open(os.path.join(jdir, gen.snake(name) + ".json"), "w", encoding="utf-8") as fh:
                json.dump({"fields": ";".join(fields) + ";"}, fh)
        self.assertEqual(gen.compare_formats(msgs, jdir), len(msgs))
        path = os.path.join(jdir, "holder.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["fields"] = data["fields"].replace("code;", "code2;")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        with self.assertRaises(gen.GenError):
            gen.compare_formats(msgs, jdir)


if __name__ == "__main__":
    unittest.main()
