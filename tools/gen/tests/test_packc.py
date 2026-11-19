"""packc: a derive line whose target the source decode already gives is not
needed by a cross-format plan.

A model module may state both directions between `uid` and a numeric
identifier (`derive uid text_of x.id`, `derive x.id parse_int uid`). A derive
line only sets a key the entity lacks, so converting from a format that
decodes `uid` never runs `uid = text_of(x.id)`. packc must not count that line
as needed, or the device profile, which has no text store, refuses the plan.
"""
import os
import tempfile
import unittest

import support  # noqa: F401  (puts tools/gen on sys.path)
import packc

CORE = """module        core
version       0.1.0
distribution  public
source        "test"
key  uid  string  -
key  lat  float   deg
"""

PROBE = """module        probe
version       0.1.0
distribution  public
source        "test"
key  id      int  -
key  number  int  -
derive  uid           text_of    probe.id
derive  probe.id      parse_int  uid
derive  probe.number  parse_int  uid
"""

SOURCE = """format        src
version       0.1.0
distribution  public
source        "test"
wire          bits
word_bytes    1
bit_order     msb
field  uid  0:0:64  ascii
"""

TARGET = """format        dst
version       0.1.0
distribution  public
source        "test"
uses          probe
wire          bits
word_bytes    1
bit_order     msb
field  probe.number  0:0:32  uint
"""


class DeriveTargetFromSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "model"))
        for name, text in (("core.def", CORE), ("probe.def", PROBE)):
            with open(os.path.join(root, "model", name), "w", encoding="utf-8") as fh:
                fh.write(text)
        for name, text in (("src", SOURCE), ("dst", TARGET)):
            os.makedirs(os.path.join(root, "packs", name))
            with open(os.path.join(root, "packs", name, "pack.def"), "w", encoding="utf-8") as fh:
                fh.write(text)
        self.model_dir = os.path.join(root, "model")
        self.packs_dir = os.path.join(root, "packs")

    def tearDown(self):
        self.tmp.cleanup()

    def test_uid_id_pair_does_not_need_text_of(self):
        blob, report = packc.compile_plan(self.model_dir, self.packs_dir, "src", "dst", {}, False)[:2]
        self.assertTrue(blob)
        derives = report["derives"]
        self.assertIn("probe.number = parse_int(uid)", derives)
        self.assertFalse([d for d in derives if d.startswith("uid =")], derives)


if __name__ == "__main__":
    unittest.main()
