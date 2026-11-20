"""Tests of tools/gen/vss2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_vss2pack*.py'

fixtures/vss2pack/input/source is a synthetic stand-in for COVESA/vehicle_signal_specification,
written for these tests: a root vspec with a left-out VehicleDataTypes branch and an include
with a prefix; a Vehicle file with a speed in km/h, a current location, a flow list over
lines, a two-level instance branch with an `instantiate: false` child, a one-level instance
branch with an array signal, and an include resolved from the spec root.
fixtures/vss2pack/expected is the tree the run writes into the checkout. The fixture files
are kept as `*.vspec.yaml` (the boundary gate's allowlist has no `.vspec`); the test copies
them to `*.vspec` before each run.
"""
import json
import os
import shutil
import tempfile
import unittest

import support

V = support.load_script("vss2pack.py")
FIXTURE = os.path.join(support.FIXTURES, "vss2pack")
INPUTS = ("model/core.def", "model/track.def", "tools/gen/notes/vss.md")


class VssTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="vss2pack-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.src = support.copy_tree(os.path.join(FIXTURE, "input", "source"), os.path.join(self.work, "src"))
        for d, _, files in os.walk(self.src):
            for f in files:
                if f.endswith(".vspec.yaml"):
                    os.rename(os.path.join(d, f), os.path.join(d, f[:-5]))
        self.gt = support.copy_tree(os.path.join(FIXTURE, "input", "checkout"), os.path.join(self.work, "gt"))

    def run_gen(self, *extra):
        return support.run_main(V.main, ["--no-commit-check", "--no-cross"] + list(extra) + [self.src, self.gt])

    def read(self, *parts):
        with open(os.path.join(self.gt, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_run_writes_the_expected_tree(self):
        status, out, err = self.run_gen()
        self.assertEqual((status, err), (0, ""))
        self.assertEqual(out, "vss-vehicle\n")
        support.assert_same_tree(self, os.path.join(FIXTURE, "expected"), self.gt, ignore=INPUTS)

    def test_tree_and_bindings(self):
        read = set()
        tree = V.load_tree(os.path.join(self.src, "spec"), "VehicleSignalSpecification.vspec", "", None, read)
        self.assertEqual(sorted(read), ["spec/Vehicle/Vehicle.vspec", "spec/VehicleSignalSpecification.vspec",
                                        "spec/include/Extra.vspec"])
        self.assertEqual(tree["Vehicle.Seat"]["instances"], ["Row[1,2]", ["Left", "Right"]])
        doc = V.build_schema(tree)
        self.assertEqual(list(doc["properties"]), ["Vehicle"])
        veh = doc["properties"]["Vehicle"]["properties"]
        self.assertEqual(list(veh["Seat"]["properties"]), ["Count", "Row1", "Row2"])
        self.assertEqual(list(veh["Seat"]["properties"]["Row2"]["properties"]["Right"]["properties"]), ["IsOccupied"])
        self.assertEqual(list(veh["Door"]["properties"]["Rear"]["properties"]), ["Codes", "IsOpen"])
        self.assertEqual(V.count_leaves(doc), 2 + 2 + 1 + 1 + 4 + 2 * 2)
        self.assertEqual(self.run_gen()[0], 0)
        pack = self.read("packs", "vss-vehicle", "pack.def")
        for line in ("field  vssvehicle.vehicle_speed  Vehicle.Speed  float\nfield  speed_ms  Vehicle.Speed  scale:5/18\n",
                     "field  time_ms  Vehicle.CurrentLocation.Timestamp  iso8601_ms\n",
                     "field  lat  Vehicle.CurrentLocation.Latitude  float\n",
                     "field  lon  Vehicle.CurrentLocation.Longitude  float\n",
                     "Vehicle.Seat.Row2.Right.IsOccupied  bool\n", "group  vssvehicle.vehicle_door_rear_codes"):
            self.assertIn(line, pack)
        self.assertNotIn("Altitude", pack)        # not in the fixture: its binding is skipped
        md = self.read("packs", "vss-vehicle", "pack.md")
        self.assertNotIn("A latitude.", md)
        v = json.loads(self.read("packs", "vss-vehicle", "vectors", "gen-001-vehicle-roundtrip.json"))
        speed = json.loads(v["input"])["Vehicle"]["Speed"]
        self.assertEqual(float(v["model"]["speed_ms"]), speed * 5.0 / 18.0)

    def test_check_after_a_run_is_ok_and_writes_nothing(self):
        self.assertEqual(self.run_gen()[0], 0)
        before = support.tree(self.work)
        status, out, err = self.run_gen("--check")
        self.assertEqual(status, 0, err)
        self.assertEqual(out, "")
        self.assertEqual(support.tree(self.work), before)

    def test_check_without_output_reports_and_creates_nothing(self):
        before = support.tree(self.work)
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("packs/vss-vehicle/pack.def is missing", err)
        self.assertIn("packs/vss-vehicle/PROVENANCE.md is missing", err)
        self.assertEqual(support.tree(self.work), before)

    def test_instances_and_refusals(self):
        self.assertEqual(V.instance_levels("Row[1,3]"), [["Row1", "Row2", "Row3"]])
        self.assertEqual(V.instance_levels(["A", "B"]), [["A", "B"]])
        self.assertEqual(V.instance_levels(["Row[1,2]", ["A", "B"]]), [["Row1", "Row2"], ["A", "B"]])
        self.assertEqual(V.parse_list('[Row[1,2], ["A","B"]]', "t"), ["Row[1,2]", ["A", "B"]])
        with self.assertRaises(V.VssError):
            V.instance_levels("Row[3,1]")
        f = os.path.join(self.src, "spec", "include", "Extra.vspec")
        with open(f, "a", encoding="utf-8") as fh:
            fh.write("Odd:\n  datatype: Types.Thing\n  type: sensor\n")
        status, _, err = self.run_gen()
        self.assertEqual(status, 1)
        self.assertIn("datatype Types.Thing, which this program does not take", err)
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("Odd:\n type: sensor\n")
        status, _, err = self.run_gen()
        self.assertEqual(status, 1)
        self.assertIn("Odd", err)
        status, _, err = support.run_main(V.main, [self.src, self.gt])
        self.assertEqual(status, 1)
        self.assertIn("not %s (tag %s)" % (V.COMMIT, V.TAG), err)


if __name__ == "__main__":
    unittest.main()
