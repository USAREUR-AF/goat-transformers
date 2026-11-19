"""Tests of the json `scale` bindings of tools/gen/ros2msg2pack.py (engine-spec 0.15).

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_ros2msg2pack*.py'
"""
import support  # noqa: F401  (puts tools/gen on the path)

import unittest

import ros2msg2pack as gen


class ScaleCase(unittest.TestCase):
    def setUp(self):
        gen.SCALED.clear()

    def test_parse_maps_with_scale(self):
        maps = gen.parse_maps(["ublox_msgs/NavPVT:lat=lat@scale:1/10000000",
                               "ublox_msgs/NavPVT:height=hae@scale:1/1000",
                               "sensor_msgs/NavSatFix:latitude=lat"])
        self.assertEqual(maps["ublox_msgs"][("NavPVT", "lat")], "lat")
        self.assertEqual(gen.SCALED[("ublox_msgs", "NavPVT", "lat")], "scale:1/10000000")
        self.assertNotIn(("sensor_msgs", "NavSatFix", "latitude"), gen.SCALED)
        with self.assertRaises(gen.GenError):
            gen.parse_maps(["ublox_msgs/NavPVT:lat=lat@scale:1/0"])

    def test_decode_encode(self):
        tr = "scale:1/10000000"
        self.assertEqual(gen.scale_decode(470625000, tr), 47.0625)
        self.assertEqual(gen.scale_encode(47.0625, tr), 470625000.0)
        self.assertEqual(gen.scale_decode(431500, "scale:1/1000"), 431.5)
        self.assertEqual(gen.scale_decode(10, "scale:0.5:3"), 8.0)
        self.assertEqual(gen.scale_encode(8.0, "scale:0.5:3"), 10.0)

    def test_exact_wire_round_trips(self):
        tr = "scale:1/10000000"
        for w in (473977419, -353632621, 1, 123456789):
            c = gen.exact_wire(w, tr)
            self.assertEqual(gen.scale_encode(gen.scale_decode(c, tr), tr), float(c))
            self.assertLess(abs(c - w), 2000)

    def test_model_value(self):
        self.assertEqual(gen.model_value(470625000, "scale:1/10000000"), "47.0625")


if __name__ == "__main__":
    unittest.main()
