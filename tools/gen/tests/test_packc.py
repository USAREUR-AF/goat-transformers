"""packc: a derive line whose target the source decode already gives is not
needed by a cross-format plan; and the sentinels of the `absent` field option
(engine-spec 0.9) are compiled into the FIELD operation (embedded/FORMAT.md);
and the `present` derive function (engine-spec 0.12) is compiled as function 13;
and `armor sixbit` and the `sixbit` transform (engine-spec 0.14) are compiled
as format flag 4 and transform 8.

A model module may state both directions between `uid` and a numeric
identifier (`derive uid text_of x.id`, `derive x.id parse_int uid`). A derive
line only sets a key the entity lacks, so converting from a format that
decodes `uid` never runs `uid = text_of(x.id)`. packc must not count that line
as needed, or the device profile, which has no text store, refuses the plan.
"""
import os
import struct
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



ABSENT_MODEL = """module        probe
version       0.1.0
distribution  public
source        "test"
key  x    int    -
key  y    int    -
key  z    float  -
key  n    int    -
key  tag  string -
"""

FIXED = """format        fx
version       0.1.0
distribution  public
source        "test"
uses          probe
wire          bits
word_bytes    1
field  probe.x    0:0:8    uint            absent 255,0
field  probe.z    0:8:16   uscale:0.5      absent 65535
field  probe.y    0:24:8   uint
field  probe.tag  0:32:16  ascii           absent 0
"""

SEQ = """format        sq
version       0.1.0
distribution  public
source        "test"
uses          probe
wire          bits
layout        sequential
field  probe.x  8   uint
field  probe.n  16  uint  swap  absent 65280
field  probe.y  8   uint
"""

# a target whose `probe.n` no source gives: with `absent` the field still
# writes its sentinel, so it stays in the plan; `probe.y` has none and goes
TARGET_N = """format        tn
version       0.1.0
distribution  public
source        "test"
uses          probe
wire          bits
word_bytes    1
field  probe.x  0:0:8   uint
field  probe.n  0:8:8   uint  absent 255
field  probe.y  0:16:8  uint
"""

SOURCE_X = """format        sx
version       0.1.0
distribution  public
source        "test"
uses          probe
wire          bits
word_bytes    1
field  probe.x  0:0:8  uint
"""


def sections(blob):
    """{section id: (entry size, data)} of a blob, after the header checks."""
    assert blob[:4] == b"GTP1"
    version, _, total, n, _ = struct.unpack_from("<HHIHH", blob, 4)
    assert total == len(blob)
    out = {}
    for i in range(n):
        sid, entry, at, count = struct.unpack_from("<HHII", blob, 16 + 12 * i)
        out[sid] = (entry, blob[at:at + entry * count])
    return version, out


def ops(secs):
    entry, data = secs[packc.S_OPS]
    return [dict(zip(("op", "xf", "flags", "nabsent", "key", "len", "a", "b", "c"),
                     struct.unpack_from("<BBBBHHIHH", data, i))) for i in range(0, len(data), entry)]


def pool(secs):
    entry, data = secs[packc.S_POOL]
    return [struct.unpack_from("<Q", data, i)[0] for i in range(0, len(data), entry)]


class AbsentSentinelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "model"))
        for name, text in (("core.def", CORE), ("probe.def", ABSENT_MODEL)):
            with open(os.path.join(root, "model", name), "w", encoding="utf-8") as fh:
                fh.write(text)
        self.model_dir = os.path.join(root, "model")
        self.packs_dir = os.path.join(root, "packs")
        for name, text in (("fx", FIXED), ("sq", SEQ), ("tn", TARGET_N), ("sx", SOURCE_X)):
            self.write_pack(name, text)
        # packc caches packs and models by directory; this test writes its own
        packc._INDEX.clear()
        packc._MODELS.clear()

    def tearDown(self):
        packc._INDEX.clear()
        packc._MODELS.clear()
        self.tmp.cleanup()

    def write_pack(self, name, text):
        d = os.path.join(self.packs_dir, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "pack.def"), "w", encoding="utf-8") as fh:
            fh.write(text)
        packc._INDEX.clear()

    def compile(self, src, dst):
        blob, report = packc.compile_plan(self.model_dir, self.packs_dir, src, dst, {}, False)[:2]
        version, secs = sections(blob)
        return version, secs, report

    def fields(self, secs, report):
        ids = {v: k for k, v in report["key_ids"].items()}
        return {ids[o["key"]]: o for o in ops(secs) if o["op"] == packc.OP_FIELD}

    def test_the_plan_format_version(self):
        version, _, _ = self.compile("fx", "fx")
        self.assertEqual(version, packc.VERSION)
        self.assertEqual(packc.VERSION, 3)

    def test_fixed_sentinels_follow_the_scale_in_the_pool(self):
        _, secs, report = self.compile("fx", "fx")
        f, words = self.fields(secs, report), pool(secs)
        # no scale: the sentinels start at `b`, in the order written
        self.assertEqual(f["probe.x"]["nabsent"], 2)
        self.assertEqual(words[f["probe.x"]["b"]:f["probe.x"]["b"] + 2], [255, 0])
        # a scale: its three words, then the sentinels
        z = f["probe.z"]
        self.assertEqual(z["nabsent"], 1)
        self.assertEqual(words[z["b"]], packc.f64_bits(0.5))
        self.assertEqual(words[z["b"] + 3], 65535)
        # ruling 2 of 0.9: a sentinel on `ascii` is an integer
        self.assertEqual(f["probe.tag"]["nabsent"], 1)
        self.assertEqual(words[f["probe.tag"]["b"]], 0)
        # a field without `absent` has none
        self.assertEqual(f["probe.y"]["nabsent"], 0)

    def test_sequential_sentinel_keeps_swap(self):
        _, secs, report = self.compile("sq", "sq")
        n = self.fields(secs, report)["probe.n"]
        self.assertEqual(n["nabsent"], 1)
        self.assertEqual(n["flags"] & packc.F_SWAP, packc.F_SWAP)
        self.assertEqual(pool(secs)[n["b"]], 65280)

    def test_target_field_with_a_sentinel_stays_when_no_value_can_reach_it(self):
        _, secs, report = self.compile("sx", "tn")
        f = self.fields(secs, report)
        # `probe.n`: never given, still written as its sentinel; `probe.y`: dropped
        self.assertIn("probe.n", f)
        self.assertNotIn("probe.y", f)
        self.assertEqual(f["probe.n"]["nabsent"], 1)
        # the key is in the plan, and the plan never uses its value or carries it
        entry, data = secs[packc.S_KEYS]
        kid = report["key_ids"]["probe.n"]
        self.assertEqual(data[kid * entry + 1] & packc.K_LIVE, 0)
        self.assertNotIn("probe.n", report["carried"])

    def refused(self, text):
        self.write_pack("bad", text)
        with self.assertRaises(packc.Refused) as cm:
            packc.compile_plan(self.model_dir, self.packs_dir, "bad", "bad", {}, False)
        return cm.exception.reason

    def bad(self, line):
        return FIXED.replace("format        fx", "format        bad").replace(
            "field  probe.y    0:24:8   uint\n", line + "\n")

    def test_refusals(self):
        # a value that does not fit the field, or is not an unsigned decimal integer
        self.assertEqual(self.refused(self.bad("field  probe.y  0:24:8  uint  absent 256")), "bad-pack")
        self.assertEqual(self.refused(self.bad("field  probe.y  0:24:8  uint  absent +7")), "bad-pack")
        self.assertEqual(self.refused(self.bad("field  probe.y  0:24:8  uint  absent 1,,2")), "bad-pack")
        # no argument, or twice on one line
        self.assertEqual(self.refused(self.bad("field  probe.y  0:24:8  uint  absent")), "bad-pack")
        self.assertEqual(self.refused(self.bad("field  probe.y  0:24:8  uint  absent 1 absent 2")), "bad-pack")
        # longer than 64 bits
        self.assertEqual(self.refused(self.bad("field  probe.tag  0:24:72  ascii  absent 0")), "bad-pack")
        # more sentinels than the operation's count holds
        many = ",".join(str(i) for i in range(256))
        self.assertEqual(self.refused(self.bad("field  probe.y  0:24:16  uint  absent " + many)), "value-range")

    def test_absent_is_no_longer_unsupported(self):
        for src, dst in (("fx", "fx"), ("sq", "sq"), ("sx", "tn")):
            self.compile(src, dst)


PRESENT_MODEL = """module        probe
version       0.1.0
distribution  public
source        "test"
key  alt   float  m
key  name  string -
key  mrh   int    -
key  seen  int    -
derive  probe.mrh   present  probe.alt
derive  probe.seen  present  probe.name
"""

PRESENT_SOURCE = """format        ps
version       0.1.0
distribution  public
source        "test"
uses          probe
wire          bits
word_bytes    1
field  probe.alt   0:0:16   uscale:0.5
field  probe.name  0:16:16  ascii
"""

PRESENT_TARGET = """format        pt
version       0.1.0
distribution  public
source        "test"
uses          probe
wire          bits
word_bytes    1
field  probe.mrh   0:0:1  uint
field  probe.seen  0:1:1  uint
"""


class PresentDeriveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "model"))
        for name, text in (("core.def", CORE), ("probe.def", PRESENT_MODEL)):
            with open(os.path.join(root, "model", name), "w", encoding="utf-8") as fh:
                fh.write(text)
        for name, text in (("ps", PRESENT_SOURCE), ("pt", PRESENT_TARGET)):
            os.makedirs(os.path.join(root, "packs", name))
            with open(os.path.join(root, "packs", name, "pack.def"), "w", encoding="utf-8") as fh:
                fh.write(text)
        self.model_dir = os.path.join(root, "model")
        self.packs_dir = os.path.join(root, "packs")
        packc._INDEX.clear()
        packc._MODELS.clear()

    def tearDown(self):
        packc._INDEX.clear()
        packc._MODELS.clear()
        self.tmp.cleanup()

    def test_present_is_function_13_with_one_argument_of_any_scalar_type(self):
        self.assertEqual(packc.DERIVE["present"], 13)
        self.assertNotIn("present", packc.DERIVE_FEATURE)
        blob, report = packc.compile_plan(self.model_dir, self.packs_dir, "ps", "pt", {}, False)[:2]
        self.assertEqual(report["derives"], ["probe.mrh = present(probe.alt)", "probe.seen = present(probe.name)"])
        self.assertEqual(report["features"], [])
        _, secs = sections(blob)
        entry, data = secs[packc.S_DERIVES]
        rows = [struct.unpack_from("<BBHHH", data, i) for i in range(0, len(data), entry)]
        ids = report["key_ids"]
        _, args = secs[packc.S_ARGS]
        for (func, nargs, target, first, _), (t, a) in zip(rows, (("probe.mrh", "probe.alt"), ("probe.seen", "probe.name"))):
            self.assertEqual((func, nargs, target), (13, 1, ids[t]))
            self.assertEqual(struct.unpack_from("<H", args, first * 2)[0], ids[a])
        # both targets reach the target format as derived keys
        self.assertIn("probe.mrh (derived)", report["carried"])
        self.assertIn("probe.seen (derived)", report["carried"])

    def test_an_encode_only_plan_keeps_present(self):
        # the caller may set any key, so the argument may be present
        blob, report = packc.compile_plan(self.model_dir, self.packs_dir, None, "pt", {}, False)[:2]
        self.assertIn("probe.mrh = present(probe.alt)", report["derives"])


SIXBIT_MODEL = """module        probe
version       0.1.0
distribution  public
source        "test"
key  x     int    -
key  name  string -
"""

ARMOR_FIXED = """format        af
version       0.1.0
distribution  public
source        "test"
uses          probe
wire          bits
bit_order     msb
armor         sixbit
word_bytes    1
field  probe.x     0:0:6    uint
field  probe.name  0:6:42   sixbit  trim
"""

ARMOR_SEQ = """format        aq
version       0.1.0
distribution  public
source        "test"
uses          probe
wire          bits
bit_order     msb
armor         sixbit
layout        sequential
field  probe.x     6   uint
field  probe.name  12  sixbit
"""

# `sixbit` without armor, on hex input in lsb order
SIXBIT_HEX = """format        sh
version       0.1.0
distribution  public
source        "test"
uses          probe
wire          bits
word_bytes    1
field  probe.name  0:0:24  sixbit
"""


class SixbitArmorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "model"))
        for name, text in (("core.def", CORE), ("probe.def", SIXBIT_MODEL)):
            with open(os.path.join(root, "model", name), "w", encoding="utf-8") as fh:
                fh.write(text)
        self.model_dir = os.path.join(root, "model")
        self.packs_dir = os.path.join(root, "packs")
        for name, text in (("af", ARMOR_FIXED), ("aq", ARMOR_SEQ), ("sh", SIXBIT_HEX)):
            self.write_pack(name, text)

    def tearDown(self):
        packc._INDEX.clear()
        packc._MODELS.clear()
        self.tmp.cleanup()

    def write_pack(self, name, text):
        d = os.path.join(self.packs_dir, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "pack.def"), "w", encoding="utf-8") as fh:
            fh.write(text)
        packc._INDEX.clear()
        packc._MODELS.clear()

    def compile(self, name):
        blob, report = packc.compile_plan(self.model_dir, self.packs_dir, name, name, {}, False)[:2]
        version, secs = sections(blob)
        self.assertEqual(version, 3)
        entry, data = secs[packc.S_FORMATS]
        flags = [data[i] for i in range(0, len(data), entry)]
        ids = {v: k for k, v in report["key_ids"].items()}
        fields = {ids[o["key"]]: o for o in ops(secs) if o["op"] == packc.OP_FIELD}
        return flags, fields

    def test_armor_is_format_flag_4_in_both_layouts(self):
        for name, seq in (("af", 0), ("aq", 2)):
            flags, fields = self.compile(name)
            self.assertEqual(flags, [1 | seq | 4], name)
            self.assertEqual(fields["probe.name"]["xf"], packc.XF["sixbit"])
            self.assertEqual(packc.XF["sixbit"], 8)
        _, fields = self.compile("af")
        self.assertEqual(fields["probe.name"]["flags"] & packc.F_TRIM, packc.F_TRIM)
        self.assertEqual(fields["probe.name"]["len"], 42)

    def test_sixbit_without_armor_is_hex(self):
        flags, fields = self.compile("sh")
        self.assertEqual(flags, [0])
        self.assertEqual(fields["probe.name"]["xf"], 8)

    def refused(self, text):
        self.write_pack("bad", text.replace("format        af", "format        bad"))
        with self.assertRaises(packc.Refused) as cm:
            packc.compile_plan(self.model_dir, self.packs_dir, "bad", "bad", {}, False)
        return cm.exception.reason

    def test_refusals(self):
        line = "field  probe.name  0:6:42   sixbit  trim"
        # a length that is not a multiple of 6, or outside 6 to 1530
        self.assertEqual(self.refused(ARMOR_FIXED.replace(line, "field  probe.name  0:6:40  sixbit")), "bad-pack")
        self.assertEqual(self.refused(ARMOR_FIXED.replace(line, "field  probe.name  0:6:1536  sixbit")), "bad-pack")
        # `swap` on `sixbit`
        self.assertEqual(self.refused(ARMOR_FIXED.replace(line, "field  probe.name  0:6:48  sixbit  swap")), "bad-pack")
        # `armor sixbit` needs `bit_order msb`; `armor` takes `hex` or `sixbit`
        self.assertEqual(self.refused(ARMOR_FIXED.replace("bit_order     msb\n", "")), "bad-pack")
        self.assertEqual(self.refused(ARMOR_FIXED.replace("armor         sixbit", "armor  base64")), "bad-pack")
        # `length ... whole` under armor (ruling 3 of 0.14)
        whole = ARMOR_SEQ.replace("format        aq", "format        af") + "length  8  whole\n"
        self.assertEqual(self.refused(whole), "bad-pack")

    def test_armor_hex_is_the_default(self):
        self.write_pack("hx", ARMOR_FIXED.replace("format        af", "format        hx").replace(
            "armor         sixbit", "armor         hex"))
        flags, _ = self.compile("hx")
        self.assertEqual(flags, [1])


if __name__ == "__main__":
    unittest.main()
