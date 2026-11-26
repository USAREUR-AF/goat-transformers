"""packc: a derive line whose target the source decode already gives is not
needed by a cross-format plan; and the sentinels of the `absent` field option
(engine-spec 0.9) are compiled into the FIELD operation (embedded/FORMAT.md);
and the `present` derive function (engine-spec 0.12) is compiled as function 13;
and `armor sixbit` and the `sixbit` transform (engine-spec 0.14) are compiled
as format flag 4 and transform 8; the value transforms of engine-spec 0.15
as transforms 9 to 18; and the derive functions of engine-spec 0.16 as
functions 14 to 28, the four that need a power or a cube root refused; and the
gate blocks of engine-spec 0.17 as GATE operations.

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
        self.assertEqual(packc.VERSION, 4)

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
        # version 3 added armor; version 4 (spec 0.17) keeps it
        self.assertGreaterEqual(version, 3)
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


V015_MODEL = """module        probe
version       0.1.0
distribution  public
source        "test"
key  a  int     -
key  b  int     -
key  c  int     -
key  d  float   -
key  e  float   -
key  f  float   -
key  g  string  -
key  h  string  -
key  i  string  -
key  j  string  -
"""

V015 = """format        vt
version       0.1.0
distribution  public
source        "test"
uses          probe
wire          bits
word_bytes    1
field  probe.a  0:0:16     uiscale:0.001:-5   absent 65535
field  probe.b  0:16:16    siscale:-3/6
field  probe.c  0:32:8     smag
field  probe.d  0:40:16    smscale:0.5:1
field  probe.e  0:56:32    f32scale:1/3
field  probe.f  0:88:64    f64scale:10
field  probe.g  0:152:48   chars:icao6
field  probe.h  0:200:24   chars:ais6
field  probe.i  0:224:21   chars:ascii7
field  probe.j  0:245:9    octal
"""


class ValueTransformTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "model"))
        for name, text in (("core.def", CORE), ("probe.def", V015_MODEL)):
            with open(os.path.join(root, "model", name), "w", encoding="utf-8") as fh:
                fh.write(text)
        self.model_dir = os.path.join(root, "model")
        self.packs_dir = os.path.join(root, "packs")
        self.write_pack("vt", V015)

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

    def test_transform_numbers_and_parameters(self):
        blob, report = packc.compile_plan(self.model_dir, self.packs_dir, "vt", "vt", {}, False)[:2]
        _, secs = sections(blob)
        ids = {v: k for k, v in report["key_ids"].items()}
        f = {ids[o["key"]]: o for o in ops(secs) if o["op"] == packc.OP_FIELD}
        words = pool(secs)
        want = {"probe.a": 9, "probe.b": 10, "probe.c": 11, "probe.d": 12, "probe.e": 13, "probe.f": 14,
                "probe.g": 15, "probe.h": 16, "probe.i": 17, "probe.j": 18}
        self.assertEqual({k: o["xf"] for k, o in f.items()}, want)
        mask = (1 << 64) - 1
        # an exact factor in lowest terms and an integer offset, then the sentinels
        a = f["probe.a"]
        self.assertEqual(words[a["b"]:a["b"] + 4], [1, 1000, -5 & mask, 65535])
        self.assertEqual(a["nabsent"], 1)
        # a signed fraction: the sign on the numerator
        b = f["probe.b"]
        self.assertEqual(words[b["b"]:b["b"] + 3], [-1 & mask, 2, 0])
        # float scales: three doubles, as `sscale`
        d, e = f["probe.d"], f["probe.e"]
        self.assertEqual(words[d["b"]:d["b"] + 3], [packc.f64_bits(0.5), 0, packc.f64_bits(1.0)])
        self.assertEqual(words[e["b"]:e["b"] + 3], [packc.f64_bits(1.0), packc.f64_bits(3.0), 0])

    def refused(self, line):
        self.write_pack("bad", V015.replace("format        vt", "format        bad").replace(
            "field  probe.j  0:245:9    octal", line))
        with self.assertRaises(packc.Refused) as cm:
            packc.compile_plan(self.model_dir, self.packs_dir, "bad", "bad", {}, False)
        return cm.exception.reason

    def test_refusals(self):
        for line in (
            "field  probe.j  0:245:8    octal",                 # not a multiple of 3
            "field  probe.j  0:245:9    octal  trim",           # trim (ruling 18)
            "field  probe.j  0:245:24   octal  swap",           # swap with octal
            "field  probe.g  0:245:48   chars:icao6  swap",     # swap with chars
            "field  probe.g  0:245:20   chars:ais6",            # not a multiple of 6
            "field  probe.g  0:245:12   chars:ebcdic",          # an unknown set
            "field  probe.c  0:245:1    smag",                  # smag needs 2 bits
            "field  probe.e  0:245:64   f32scale:2",            # f32scale is 32 bits
            "field  probe.a  0:245:16   uiscale:0",             # factor 0
            "field  probe.a  0:245:16   uiscale:-0",            # factor 0 (ruling 19)
            "field  probe.a  0:245:16   uiscale:4294967297",    # beyond 2^32 (ruling 19)
            "field  probe.a  0:245:16   uiscale:1:1.5",         # an offset that is not an integer
            "field  probe.a  0:245:16   uiscale:1e3",           # an exponent
        ):
            self.assertEqual(self.refused(line), "bad-pack", line)

    def test_bounds_that_load(self):
        for line in ("field  probe.a  0:245:16   uiscale:4294967296",
                     "field  probe.a  0:245:16   uiscale:2/8589934592",       # 1/2^32 in lowest terms
                     "field  probe.a  0:245:16   siscale:1:-9223372036854775807"):
            self.write_pack("ok", V015.replace("format        vt", "format        ok").replace(
                "field  probe.j  0:245:9    octal", line))
            packc.compile_plan(self.model_dir, self.packs_dir, "ok", "ok", {}, False)
        self.assertEqual(self.refused("field  probe.a  0:245:16   siscale:1:-9223372036854775808"), "bad-pack")

    def test_fallible_transforms(self):
        for t in ("uiscale", "siscale", "smscale", "f32scale", "f64scale", "chars_icao6", "chars_ascii7"):
            self.assertIn(t, packc.FALLIBLE)
        for t in ("smag", "chars_ais6", "octal"):
            self.assertNotIn(t, packc.FALLIBLE)


D016_MODEL = """module        probe
version       0.1.0
distribution  public
source        "test"
key  ms     int    -
key  sec    int    -
key  nsec   int    -
key  back   int    -
key  i0     int    -
key  i1     int    -
key  isum   int    -
key  f0     float  -
key  f1     float  -
key  fdiff  float  -
key  r      float  -
key  d      float  -
key  lat    float  -
key  lon    float  -
key  hae    float  -
key  dlon   float  -
key  x      float  -
key  y      float  -
key  z      float  -
key  rlon   float  -
key  dlat   float  -
key  rlat   float  -
derive  probe.sec    sec_of       probe.ms
derive  probe.nsec   nsec_of      probe.ms
derive  probe.back   ms_of        probe.sec  probe.nsec
derive  probe.isum   add          probe.i0  probe.i1
derive  probe.fdiff  sub          probe.f0  probe.f1
derive  probe.d      deg          probe.r
derive  probe.dlon   deg_lon_of   probe.d  probe.lat
derive  probe.x      ecef_x       probe.lat  probe.lon  probe.hae
derive  probe.y      ecef_y       probe.lat  probe.lon  probe.hae
derive  probe.z      ecef_z       probe.lat  probe.lon  probe.hae
derive  probe.rlon   lon_of_ecef  probe.x  probe.y  probe.z
derive  probe.dlat   deg_lat_of   probe.d  probe.lat
derive  probe.rlat   lat_of_ecef  probe.x  probe.y  probe.z
"""


def d016_pack(name, keys):
    text = ("format        %s\nversion       0.1.0\ndistribution  public\nsource        \"test\"\n"
            "uses          probe\nwire          bits\nword_bytes    1\n" % name)
    for i, (k, xf) in enumerate(keys):
        text += "field  probe.%s  %d:0:64  %s\n" % (k, i * 8, xf)
    return text


D016_ARGS = [("ms", "twos"), ("i0", "twos"), ("i1", "twos"), ("f0", "f64"), ("f1", "f64"), ("r", "f64"),
             ("lat", "f64"), ("lon", "f64"), ("hae", "f64")]


class Derive016Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "model"))
        for name, text in (("core.def", CORE), ("probe.def", D016_MODEL)):
            with open(os.path.join(root, "model", name), "w", encoding="utf-8") as fh:
                fh.write(text)
        self.model_dir = os.path.join(root, "model")
        self.packs_dir = os.path.join(root, "packs")
        self.write_pack("da", d016_pack("da", D016_ARGS))
        self.write_pack("dr", d016_pack("dr", [("sec", "twos"), ("nsec", "twos"), ("back", "twos"),
                                               ("isum", "twos"), ("fdiff", "f64"), ("d", "f64"), ("dlon", "f64"),
                                               ("x", "f64"), ("rlon", "f64")]))

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

    def test_function_numbers_and_features(self):
        blob, report = packc.compile_plan(self.model_dir, self.packs_dir, "da", "dr", {}, False)[:2]
        _, secs = sections(blob)
        entry, data = secs[packc.S_DERIVES]
        ids = {v: k for k, v in report["key_ids"].items()}
        funcs = {ids[struct.unpack_from("<BBHHH", data, i)[2]]: data[i] for i in range(0, len(data), entry)}
        self.assertEqual(funcs, {"probe.sec": 14, "probe.nsec": 15, "probe.back": 16, "probe.isum": 19,
                                 "probe.fdiff": 22, "probe.d": 17, "probe.dlon": 23, "probe.x": 25,
                                 "probe.y": 26, "probe.z": 27, "probe.rlon": 28})
        # the WGS 84 functions need the square root and the trigonometry of gt-core
        self.assertEqual(report["features"], ["sqrt", "trig"])

    def test_add_and_sub_by_type(self):
        self.assertEqual(packc.DERIVE["add_i"], 19)
        self.assertEqual(packc.DERIVE["add_f"], 20)
        self.assertEqual(packc.DERIVE["sub_i"], 21)
        self.assertEqual(packc.DERIVE["sub_f"], 22)

    def test_power_and_cube_root_functions_are_refused_when_needed(self):
        for key, fn in (("dlat", "deg_lat_of"), ("rlat", "lat_of_ecef")):
            self.write_pack("dx", d016_pack("dx", [(key, "f64")]))
            with self.assertRaises(packc.Refused) as cm:
                packc.compile_plan(self.model_dir, self.packs_dir, "da", "dx", {}, False)
            self.assertEqual(cm.exception.reason, "unsupported-feature")
            self.assertIn(fn, str(cm.exception))
        # not needed by the conversion: not compiled, and no refusal
        packc.compile_plan(self.model_dir, self.packs_dir, "da", "dr", {}, False)

    def test_a_length_given_by_an_earlier_count_is_refused(self):
        # spec 0.83; refused by its own name, before the 0.21 `count` line it needs
        self.write_pack("du", "format  du\nversion  0.1.0\ndistribution  public\nsource  \"test\"\nuses  probe\n"
                        "wire  bits\nlayout  sequential\ncount  w  8\nlength  @w  units  8\n"
                        "field  probe.i0  8  uint\nend\n")
        with self.assertRaises(packc.Refused) as cm:
            packc.compile_plan(self.model_dir, self.packs_dir, "da", "du", {}, False)
        self.assertEqual(cm.exception.reason, "unsupported-feature")
        self.assertIn("spec 0.83", str(cm.exception))

    def test_framing_is_refused(self):
        self.write_pack("df", "format  df\nversion  0.1.0\ndistribution  public\nsource  \"test\"\nuses  probe\n"
                        "wire  bits\nlayout  sequential\nframing  self\nfield  probe.i0  8  uint\n")
        with self.assertRaises(packc.Refused) as cm:
            packc.compile_plan(self.model_dir, self.packs_dir, "da", "df", {}, False)
        self.assertEqual(cm.exception.reason, "unsupported-feature")
        self.assertIn("spec 0.92", str(cm.exception))

    def test_only_four_functions_of_016_stay_refused(self):
        self.assertEqual(sorted(packc.V016_DERIVES), ["deg_lat_of", "hae_of_ecef", "lat_of_ecef", "m_lat_of"])


GATE_MODEL = """module        probe
version       0.1.0
distribution  public
source        "test"
key  a  int  -
key  b  int  -
key  c  int  -
key  d  int  -
key  e  int  -
list items
"""

GATE_PACK = """format        gt
version       0.1.0
distribution  public
source        "test"
uses          probe
wire          bits
word_bytes    1
field  probe.a  0:0:4   uint
if     0:4:2  2,1
  default probe.b  7
  const  0:40:8  170
  field  probe.b  0:8:8   uint
  if     !0:6:1 0
    field probe.c  0:16:8  uint  optional
  end
end
field  probe.d  0:24:8  uint
if     !0:7:1 0,1
  field probe.e  0:32:8  uint
end
group  probe.items  0:64  item 16  count 0:56:8
  field probe.a  0:0:4  uint
  if    0:4:1  1
    field probe.b  0:8:8  uint
  end
end
kind   k1
when   0:48:4  1
if     0:52:2  0,2,3
  field probe.c  0:48:8  uint
end
kind   k2
when   0:48:4  2
"""


class GateBlockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "model"))
        for name, text in (("core.def", CORE), ("probe.def", GATE_MODEL)):
            with open(os.path.join(root, "model", name), "w", encoding="utf-8") as fh:
                fh.write(text)
        self.model_dir = os.path.join(root, "model")
        self.packs_dir = os.path.join(root, "packs")
        self.write_pack("gt", GATE_PACK)

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

    def compile(self, src, dst):
        blob, report = packc.compile_plan(self.model_dir, self.packs_dir, src, dst, {}, False)[:2]
        return sections(blob)[1], report

    def test_gate_operations(self):
        secs, report = self.compile("gt", "gt")
        o, words = ops(secs), pool(secs)
        ids = {v: k for k, v in report["key_ids"].items()}
        gates = [(i, g) for i, g in enumerate(o) if g["op"] == packc.OP_GATE]
        self.assertEqual(packc.OP_GATE, 20)
        # numbered per scope in line order, depth first: common 0 to 2, the kind
        # after them, an item's from 0
        self.assertEqual([g["key"] for _, g in gates], [0, 1, 2, 0, 3])
        # the pool run: offset, the extent of the block's own lines, the gate value
        # of step 3, then the values
        def run(g):
            return words[g["b"]:g["b"] + 5 + g["c"]]
        i0, g0 = gates[0]
        self.assertEqual((g0["len"], g0["flags"], g0["c"]), (2, packc.G_HAS_VALUE, 2))
        # reach 16 (probe.b), decode need 48 (the const), encode need 48; step 3 takes the first value listed
        self.assertEqual(run(g0), [4, 16, 48, 48, 2, 2, 1])
        # `!` with 0 listed: the smallest value not listed is 1; an optional field
        # counts toward the encode need only
        g1 = gates[1][1]
        self.assertEqual(g1["flags"], packc.G_NEG | packc.G_HAS_VALUE)
        self.assertEqual(run(g1), [6, 0, 0, 24, 1, 0])
        # `!` listing every value: no gate value
        g2 = gates[2][1]
        self.assertEqual(g2["flags"], packc.G_NEG)
        self.assertEqual(run(g2), [7, 40, 40, 40, 0, 0, 1])
        # inside the block: its defaults, then fields and blocks in line order, then `const`
        kids = [o[i] for i in range(i0 + 1, i0 + 1 + g0["a"])]
        self.assertEqual([k["op"] for k in kids], [packc.OP_DEFAULT, packc.OP_FIELD, packc.OP_GATE, packc.OP_FIELD,
                                                   packc.OP_CONST])
        self.assertEqual(ids[kids[1]["key"]], "probe.b")
        # the body's extent leaves the blocks out: probe.a, probe.d and the group count
        body = o[0]
        self.assertEqual(words[body["b"]:body["b"] + 3], [32, 32, 32])

    def test_blocks_stay_when_their_lines_are_not_carried(self):
        self.write_pack("only", GATE_PACK.replace("format        gt", "format        only").split("\nif")[0]
                        .replace("field  probe.a  0:0:4   uint", "field  probe.d  0:0:8  uint") + "\n")
        secs, _ = self.compile("gt", "only")
        # probe.b, probe.c and probe.e are not carried; the gates still decide the length
        self.assertEqual(sum(1 for g in ops(secs) if g["op"] == packc.OP_GATE), 5)

    def refused(self, text):
        self.write_pack("bad", text.replace("format        gt", "format        bad"))
        with self.assertRaises(packc.Refused) as cm:
            packc.compile_plan(self.model_dir, self.packs_dir, "bad", "bad", {}, False)
        return cm.exception.reason

    def test_refusals(self):
        self.assertEqual(self.refused(GATE_PACK.replace("if     0:4:2  2,1", "if     0:4:2  4")), "bad-pack")
        self.assertEqual(self.refused(GATE_PACK.replace("if     0:4:2  2,1", "if     0:4:2  1,1")), "bad-pack")
        self.assertEqual(self.refused(GATE_PACK.replace("if     0:4:2  2,1", "if     0:4:0  0")), "bad-pack")
        many = "".join("if  0:%d:1  1\nend\n" % (i % 64) for i in range(packc.MAX_GATES + 1))
        self.assertEqual(self.refused(GATE_PACK + many), "too-many-gates")
        # one fewer loads
        self.write_pack("fits", GATE_PACK.replace("format        gt", "format        fits") + "".join(
            "if  0:%d:1  1\nend\n" % (i % 64) for i in range(packc.MAX_GATES - 4)))
        self.compile("fits", "fits")

    def test_gates_are_no_longer_unsupported(self):
        self.compile("gt", "gt")
        self.compile("gt", None)
        self.compile(None, "gt")


if __name__ == "__main__":
    unittest.main()
