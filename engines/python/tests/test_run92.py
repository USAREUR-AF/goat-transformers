"""Version 0.92: a run of inner messages (spec/engine-spec.md)."""

import gc
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from goat_transformers import Engine, Entity, GTError, Item  # noqa: E402

CORE = "module core\nversion 1\ndistribution public\nsource s\nkey uid string -\nkey time_ms int ms\n"
MODEL = ("module m\nversion 1\ndistribution public\nsource s\nkey a int -\nkey b int -\nkey c int -\nkey n int -\n"
         "key s string -\nkey d int -\nlist rows\nlist subs\nderive m.d copy m.a\n")
HEAD = "format %s\nversion 1\ndistribution public\nsource s\nuses m\n"
SEQ = "wire bits\nlayout sequential\nbit_order msb\n"
SELF = SEQ + "framing self\n"
TWO = "field m.a 8 uint\nfield m.b 8 uint\n"
C = SEQ + "field m.n 8 uint\nlength 8 bytes\n  inner in run\nend\n"
JSON = "wire json\nfield m.n n int\nfield m.a a int\nfield m.b b int\nfield m.c c int\nfield m.s s string\nfield m.d d int\n"


def engine(**packs):
    eng = Engine()
    eng.load_model(CORE)
    eng.load_model(MODEL)
    for name, body in packs.items():
        eng.load(HEAD % name.rstrip("_") + body)
    return eng


class Base(unittest.TestCase):
    def code(self, fn, *args, **kw):
        try:
            fn(*args, **kw)
        except GTError as e:
            return e.code
        return None

    def results(self, eng, src, dst, data, context=None, **kw):
        return [r.code if isinstance(r, GTError) else r.decode() for r in eng.convert_run(src, dst, data, context, **kw)]


class TestOperations(Base):
    def setUp(self):
        self.eng = engine(c=C, in_=SELF + TWO, j=JSON)

    def test_decode_run(self):
        outer, got = self.eng.decode_run("c", b"05" b"04" b"0102" b"0304")
        self.assertEqual(outer.fields, {"m.n": 5})
        self.assertEqual([m.fields for m in got], [{"m.n": 5, "m.a": 1, "m.b": 2}, {"m.n": 5, "m.a": 3, "m.b": 4}])
        self.assertEqual(self.eng.decode_run("c", b"0500")[1], [])
        outer, got = self.eng.decode_run("in", b"0102")
        self.assertEqual((outer.fields, [m.fields for m in got]), ({"m.a": 1, "m.b": 2}, [{"m.a": 1, "m.b": 2}]))

    def test_convert_run(self):
        r = lambda *a, **k: self.results(self.eng, *a, **k)  # noqa: E731
        self.assertEqual(r("c", "j", b"05" b"04" b"01020304"),
                         ['{"n":5,"a":1,"b":2,"d":1}', '{"n":5,"a":3,"b":4,"d":3}'])
        self.assertEqual(r("c", "j", b"0500"), [])
        self.assertEqual(r("c", "c", b"05" b"04" b"01020304"), ["050401020304"])
        self.assertEqual(r("c", "c", b"0500"), ["0500"])
        self.assertEqual(r("j", "c", b'{"n":5,"a":1,"b":2}'), ["05020102"])
        self.assertEqual(r("c", "in", b"05" b"04" b"01020304"), ["0102", "0304"])
        self.assertEqual(r("in", "c", b"0102"), ["00020102"])

    def test_decode_and_convert(self):
        eng = self.eng
        self.assertEqual(eng.convert("c", "c", b"05020102"), b"05020102")
        self.assertEqual(eng.decode("c", b"05020102").fields, {"m.n": 5, "m.a": 1, "m.b": 2})
        for data in (b"0500", b"050401020304", b"0503010203"):
            self.assertEqual(self.code(eng.decode, "c", data), "message-count", data)
            self.assertEqual(self.code(eng.convert, "c", "j", data), "message-count", data)
        self.assertEqual(self.code(eng.decode, "c", b"050101"), "malformed-wire")
        self.assertEqual(self.results(eng, "c", "j", b"0503010203"), ['{"n":5,"a":1,"b":2,"d":1}', "malformed-wire"])
        self.assertEqual(self.code(eng.convert_run, "c", "c", b"0503010203"), "malformed-wire")

    def test_max_items(self):
        r = lambda *a, **k: self.results(self.eng, *a, **k)  # noqa: E731
        self.assertEqual(len(r("c", "j", b"050401020304", max_items=2)), 2)
        self.assertEqual(self.code(self.eng.convert_run, "c", "j", b"050401020304", max_items=1), "malformed-wire")
        self.assertEqual(r("c", "j", b"0500", max_items=0), [])

    def test_max_items_sums_the_joined_entities(self):
        # ruling 5: the items of every message that came to its end, and the outer entity's once per message
        rows = "group m.rows count 8\n  field m.a 8 uint\nend\n"
        after = "group m.subs count 8\n  field m.b 8 uint\nend\n"
        eng = engine(c=C, k=C + after, in_=SELF + rows, j=JSON)
        run = b"05" b"06" b"020102" b"020304"
        self.assertEqual(len(eng.decode_run("c", run, max_items=4)[1]), 2)
        self.assertEqual(self.code(eng.decode_run, "c", run, max_items=3), "malformed-wire")
        self.assertEqual(len(self.results(eng, "c", "j", run, max_items=4)), 2)
        self.assertEqual(self.code(eng.convert_run, "c", "j", run, max_items=3), "malformed-wire")
        self.assertEqual(self.code(eng.convert_run, "c", "c", run, max_items=3), "malformed-wire")
        # a message whose decode stops is not counted
        got = self.results(eng, "c", "j", b"05" b"05" b"020102" b"0301", max_items=2)
        self.assertEqual((len(got), got[1]), (2, "malformed-wire"))
        # outer items after the run count once per message; the outer entity alone is not counted again
        run = b"05" b"04" b"0101" b"0102" b"01" b"09"
        self.assertEqual(len(eng.decode_run("k", run, max_items=4)[1]), 2)
        self.assertEqual(self.code(eng.decode_run, "k", run, max_items=3), "malformed-wire")
        # a message that ends the run with its own error is no error of the call: the sum is still checked
        self.assertEqual(self.results(eng, "k", "j", b"05" b"04" b"0101" b"0301" b"0109", max_items=2),
                         ['{"n":5}', "malformed-wire"])
        self.assertEqual(self.code(eng.convert_run, "k", "j", b"05" b"04" b"0101" b"0301" b"020909", max_items=2),
                         "malformed-wire")
        # a bad context key comes after the bound
        self.assertEqual(self.code(eng.convert_run, "k", "j", run, {"m.zz": "1"}, max_items=3), "malformed-wire")

    def test_context(self):
        eng = self.eng
        run = b"050401020304"
        self.assertEqual(self.results(eng, "c", "j", run, {"m.c": "7", "m.a": "9"}),
                         ['{"n":5,"a":1,"b":2,"c":7,"d":1}', '{"n":5,"a":3,"b":4,"c":7,"d":3}'])
        for data in (run, b"0500", b"0503010203"):
            self.assertEqual(self.code(eng.convert_run, "c", "j", data, {"m.zz": "1"}), "undeclared-key")
            self.assertEqual(self.code(eng.convert_run, "c", "c", b"0500", {"m.a": "x"}), "key-type-mismatch")
        self.assertEqual(self.code(eng.convert_run, "j", "j", b"{}", {"m.zz": "1"}), "undeclared-key")
        self.assertEqual(self.results(eng, "j", "j", b"[", {"m.zz": "1"}), ["malformed-wire"])
        self.assertEqual(self.code(eng.convert_run, "j", "c", b"[", {"m.zz": "1"}), "malformed-wire")
        self.assertEqual(self.code(eng.convert_run, "c", "c", b"0503010203", {"m.zz": "1"}), "malformed-wire")

    def test_unknown_formats(self):
        for a, b in (("zz", "j"), ("c", "zz")):
            self.assertEqual(self.code(self.eng.convert_run, a, b, b""), "unknown-format")


class TestErrors(Base):
    def test_message_errors(self):  # ruling 3
        inner = SELF + "field m.b 8 uint\nkind k\nwhen 8 1\nkind j\nwhen 8 2\nfield m.s 8 ascii\n"
        eng = engine(c=C + "field m.c 8 uint\n", in_=inner, j=JSON)
        run = b"05" b"07" + b"0901" + b"0902ff" + b"0801" + b"07"
        self.assertEqual(self.results(eng, "c", "j", run),
                         ['{"n":5,"b":9,"c":7}', "transform-decode", '{"n":5,"b":8,"c":7}'])
        self.assertEqual(self.code(eng.convert_run, "c", "c", run), "transform-decode")
        stop = b"05" b"06" + b"0901" + b"0903" + b"0801" + b"07"
        self.assertEqual(self.results(eng, "c", "j", stop), ['{"n":5,"b":9,"c":7}', "no-kind"])
        self.assertEqual(self.code(eng.convert_run, "c", "c", stop), "no-kind")
        # a call error: the outer lines after the run
        self.assertEqual(self.code(eng.convert_run, "c", "j", stop[:-2]), "malformed-wire")
        self.assertEqual(self.code(eng.convert_run, "c", "c", stop[:-2]), "no-kind")  # reading order
        self.assertEqual(self.code(eng.convert_run, "c", "c", run[:-2]), "malformed-wire")  # those that stop first

    def test_a_switch_on_a_failed_key(self):
        inner = (SELF + "field m.s 8 ascii\nfield m.s 8 ascii\nswitch m.s\n  case A\n    field m.a 8 uint\n"
                 "  else\n    field m.b 8 uint\nend\n")
        eng = engine(c=C, in_=inner, j=JSON)
        ok = b"414101"
        self.assertEqual(self.results(eng, "c", "j", b"0506" + ok + b"ff4102"), ['{"n":5,"a":1,"s":"A","d":1}', "transform-decode"])
        self.assertEqual(self.results(eng, "c", "j", b"0509" + ok + b"ff4102" + ok), ['{"n":5,"a":1,"s":"A","d":1}', "transform-decode"])
        for call in (lambda: eng.decode("c", b"0503ff4102"), lambda: eng.convert("c", "j", b"0503ff4102")):
            self.assertEqual(self.code(call), "transform-decode")  # in every operation
        # it stops the decode of message 1, so it is reported ahead of message-count
        self.assertEqual(self.code(eng.decode, "c", b"0506ff4102414101"), "transform-decode")
        # a plain `inner` and the pack on its own keep 0.20 as it is
        plain = engine(c=C.replace(" run", ""), in_=inner)
        self.assertEqual(plain.decode("c", b"0503ff4102").fields, {"m.n": 5, "m.s": "A", "m.a": 2})
        self.assertEqual(plain.decode("in", b"ff4102").fields, {"m.s": "A", "m.a": 2})

    def test_encode_errors_are_results(self):
        eng = engine(c=C, in_=SELF + TWO, t="wire json\nkind k\nrequires m.a=1\nfield m.a a int\n")
        self.assertEqual(self.results(eng, "c", "t", b"050401020304"), ['{"a":1}', "no-kind"])

    def test_outer_errors_are_of_the_call(self):
        eng = engine(c=SEQ + "field m.s 8 ascii\nlength 8 bytes\n  inner in run\nend\n", in_=SELF + TWO, j=JSON)
        self.assertEqual(self.code(eng.convert_run, "c", "j", b"ff020102"), "transform-decode")
        self.assertEqual(self.code(eng.convert_run, "c", "j", b"ff020102", {"m.zz": "1"}), "transform-decode")
        self.assertEqual(self.code(eng.convert_run, "c", "j", b"41"), "malformed-wire")
        self.assertEqual(self.code(eng.convert_run, "c", "j", b"4104"), "malformed-wire")

    def test_ordinary_messages(self):
        body = (SEQ + "kind r\nwhen 8 1\nlength 8 bytes\n  inner in run\nend\nkind o\nwhen 8 2\nfield m.s 8 ascii\n")
        eng = engine(c=body, in_=SELF + TWO, j=JSON)
        self.assertEqual(self.results(eng, "c", "j", b"0241"), ['{"s":"A"}'])
        self.assertEqual(self.results(eng, "c", "j", b"02ff"), ["transform-decode"])
        self.assertEqual(self.results(eng, "c", "j", b"02"), ["malformed-wire"])  # known not to reach it
        self.assertEqual(self.code(eng.convert_run, "c", "j", b"03"), "no-kind")  # not known
        self.assertEqual(self.code(eng.convert_run, "c", "c", b"02ff"), "transform-decode")
        self.assertEqual(self.results(eng, "c", "c", b"0241"), ["0241"])
        self.assertEqual(self.results(eng, "c", "c", b"010401020304"), ["010401020304"])
        absent = engine(c=SEQ + "length 8 bytes\n  field m.n 8 uint\n  length 8 bytes\n    inner in run\n  end\nend\n",
                        in_=SELF + TWO, j=JSON)
        self.assertEqual(self.results(absent, "c", "j", b"0105"), ['{"n":5}'])
        self.assertEqual(absent.decode("c", b"0105").fields, {"m.n": 5})
        self.assertEqual(self.code(absent.decode, "c", b"020500"), "message-count")

    def test_a_run_line_passed_before_the_kind_is_selected(self):  # ruling 4
        eng = engine(c=SEQ + "length 8 bytes\n  field m.n 8 uint\n  length 8 bytes\n    inner in run\n  end\nend\n"
                     "kind k\nwhen 8 1\nfield m.c 8 uint\n", in_=SELF + TWO, j=JSON)
        self.assertEqual(self.results(eng, "c", "j", b"01050107"), ['{"n":5,"c":7}'])
        for data, code in ((b"010509", "no-kind"), (b"010501", "malformed-wire")):  # ordinary from the block on
            self.assertEqual(self.results(eng, "c", "j", data), [code])
            self.assertEqual(self.results(eng, "c", "j", data, {"m.zz": "1"}), [code])
            self.assertEqual(self.code(eng.convert_run, "c", "c", data), code)
        self.assertEqual(self.code(eng.convert_run, "c", "j", b"01"), "malformed-wire")  # not known yet
        self.assertEqual(self.code(eng.convert_run, "c", "j", b"0205" b"00" b"09"), "no-kind")  # reached: the call's

    def test_checks_of_the_line(self):
        for inner in (None, SEQ + TWO, SEQ.replace("layout sequential\n", "word_bytes 1\n") + "field m.a 0:0:8 uint\n",
                      "wire json\nfield m.a a int\n", SELF + "field m.n 8 uint\n"):
            packs = {"c": C, "j": JSON}
            if inner is not None:
                packs["in"] = inner
            eng = engine(**packs)
            want = "unknown-format" if inner is None else "bad-directive"
            for data in (b"0500", b"05020102", b"0504"):
                stop = "malformed-wire" if data == b"0504" else want
                self.assertEqual(self.code(eng.decode, "c", data), stop)
                self.assertEqual(self.code(eng.convert_run, "c", "j", data), stop)
            self.assertEqual(self.code(eng.convert, "j", "c", b'{"n":5}'), want)
        eng = engine(c=SEQ + "field m.n 8 uint with m.a\nlength 8 bytes\n  inner in run\nend\n", in_=SELF + TWO,
                     p=SEQ + "field m.n 8 uint with m.a\nlength 8 bytes\n  inner in\nend\n")
        self.assertEqual(self.code(eng.decode, "c", b"0500"), "bad-directive")
        self.assertEqual(self.code(eng.encode, "c", Entity()), "bad-directive")
        self.assertIsNone(self.code(eng.decode, "p", b"05020102"))


class TestEnds(Base):
    def test_ends(self):
        eng = engine(c=C, in_=SELF + "length 8 whole\nfield m.a 8 uint\ngroup m.rows rest\n  field m.b 8 uint\nend\n", j=JSON)
        _, got = eng.decode_run("c", b"05" b"06" b"04010809" b"0202")
        self.assertEqual([(m.fields["m.a"], len(m.lists["m.rows"])) for m in got], [(1, 2), (2, 0)])
        self.assertEqual(self.results(eng, "c", "c", b"0506040108090202"), ["0506040108090202"])
        self.assertEqual(self.results(eng, "c", "j", b"0502" b"0301"), ["malformed-wire"])
        pad = engine(c=C, in_=SELF + "field m.a 4 uint\nalign 8\n", j=JSON)
        self.assertEqual(self.results(pad, "c", "j", b"05021f20"), ['{"n":5,"a":1,"d":1}', '{"n":5,"a":2,"d":2}'])
        part = engine(c=C, in_=SELF + "field m.a 4 uint\n", j=JSON)
        self.assertEqual(self.results(part, "c", "c", b"05021f20"), ["05021020"])
        none = engine(c=C, in_=SELF + "align 8\n", j=JSON)
        self.assertEqual(self.results(none, "c", "j", b"050101"), ["malformed-wire"])
        self.assertEqual(self.code(none.convert, "j", "c", b'{"n":5}'), "transform-encode")  # ruling 8
        self.assertEqual(self.results(none, "c", "c", b"0500"), ["0500"])

    def test_align_and_windows_count_from_the_message(self):
        inner = SELF + "field m.a 8 uint\nalign 16\nfield m.b 8 uint\n"
        eng = engine(c=C, in_=inner, j=JSON)
        self.assertEqual(self.results(eng, "c", "j", b"0506" b"010002" b"030004"),
                         ['{"n":5,"a":1,"b":2,"d":1}', '{"n":5,"a":3,"b":4,"d":3}'])

    def test_kinds_of_messages(self):
        inner = SELF + "kind k\nwhen 8 1\nfield m.a 8 uint\nkind j\nwhen 8 2\nkind l\nwhen 8 3\nfield m.a 8 uint\n"
        eng = engine(c=C, in_=inner, j=JSON)
        _, got = eng.decode_run("c", b"05050109" b"02" b"0308")
        self.assertEqual([m.inner_kind for m in got], [("in", "k"), ("in", "j"), ("in", "l")])
        self.assertEqual(self.results(eng, "c", "c", b"05050109020308"), ["05050109020308"])
        one = engine(c=C, in_=inner, d=C.replace("field m.n 8 uint\n", "field m.n 16 uint\n"))
        self.assertEqual(self.results(one, "c", "d", b"05050109020308"), ["0005050109020308"])


class TestCarriers(Base):
    def test_outer_lines_are_encoded_alone(self):
        tgt = SEQ + "field m.n 8 uint\nfield m.c 8 uint\nfield m.d 8 uint\nlength 8 bytes\n  inner in run\nend\n"
        eng = engine(c=C, d=tgt, in_=SELF + TWO)
        self.assertEqual(self.results(eng, "c", "d", b"0502" b"0102"), ["050000020102"])

    def test_another_inner_format_runs_steps_1_to_4(self):
        other = SELF + "field m.d 8 uint\n"
        eng = engine(c=C, d=C.replace("inner in run", "inner o run"), in_=SELF + TWO, o=other)
        self.assertEqual(self.results(eng, "c", "d", b"050401020304"), ["05020103"])

    def test_the_kind_is_chosen_on_the_outer_entity(self):
        tgt = (SEQ + "kind p\nrequires m.a\nfield m.n 8 uint\nkind r\nfield m.n 8 uint\nlength 8 bytes\n  inner in run\nend\n")
        eng = engine(c=C, d=tgt, in_=SELF + TWO)
        self.assertEqual(self.results(eng, "c", "d", b"05020102"), ["05020102"])

    def test_a_kind_without_a_run(self):
        tgt = (SEQ + "kind q\nrequires m.c\nlength 8 bytes\n  inner in run\nend\nkind r\nfield m.n 8 uint\nfield m.b 8 uint\n"
               "field m.d 8 uint\n")
        eng = engine(c=C, d=tgt, in_=SELF + TWO)
        self.assertEqual(self.results(eng, "c", "d", b"05020102"), ["050201"])
        for data in (b"0500", b"050401020304"):
            self.assertEqual(self.code(eng.convert_run, "c", "d", data), "message-count")
        plain = tgt.replace("kind r\nfield m.n 8 uint\nfield m.b 8 uint\nfield m.d 8 uint\n",
                            "kind r\nfield m.n 8 uint\nlength 8 bytes\n  inner in\nend\n")
        eng = engine(c=C, d=plain, in_=SELF + TWO)
        self.assertEqual(self.results(eng, "c", "d", b"05020102"), ["05020102"])
        none = engine(c=C, d=tgt.replace("kind r\n", "kind r\nrequires m.c\n"), in_=SELF + TWO)
        self.assertEqual(self.code(none.convert_run, "c", "d", b"0500"), "no-kind")

    def test_an_empty_run_makes_the_checks(self):
        eng = engine(c=C, d=C.replace("inner in run", "inner zz run"), in_=SELF + TWO,
                     e=SEQ + "field m.n 4 uint\nlength 8 bytes\n  inner in run\nend\n")
        self.assertEqual(self.code(eng.convert_run, "c", "d", b"0500"), "unknown-format")
        self.assertEqual(self.code(eng.convert_run, "c", "e", b"0500"), "transform-encode")

    def test_nothing_is_written_in_part(self):
        eng = engine(c=C, d=C.replace("inner in run", "inner o run"), in_=SELF + TWO, o=SELF + "field m.a 4 uint\npad 4\n")
        self.assertEqual(self.code(eng.convert_run, "c", "d", b"050401022004"), "transform-encode")

    def test_a_count_of_units_covers_the_run(self):
        units = SEQ + "count w 8\nlength @w units 16\n  inner in run\nend\n"
        eng = engine(c=units, in_=SELF + TWO, j=JSON)
        self.assertEqual(self.results(eng, "c", "c", b"0201020304"), ["0201020304"])


class TestCost(Base):
    """Ten times the length costs about ten times as much: far under the 100
    of a cost that grows with the square."""

    def ratio(self, eng, fmt, call):
        def best(n):
            data = b"01" * n
            out = []
            for _ in range(3):
                gc.collect()
                gc.disable()  # the collector's passes over a long result are not what is measured
                try:
                    at = time.process_time()
                    call(eng, fmt, data)
                    out.append(time.process_time() - at)
                finally:
                    gc.enable()
            return min(out)
        return best(20000) / best(2000)

    def test_a_run_and_a_list_are_read_in_linear_time(self):
        item = "field m.a 8 uint\n"
        eng = engine(c=SEQ + "inner in run\n", in_=SELF + item, g=SEQ + "group m.rows rest\n  " + item + "end\n",
                     l="wire bits\nlayout sequential\ngroup m.rows rest\n  " + item + "end\n")
        self.assertLess(self.ratio(eng, "c", lambda e, f, d: e.decode_run(f, d)), 50)
        self.assertLess(self.ratio(eng, "g", lambda e, f, d: e.decode(f, d)), 50)
        self.assertLess(self.ratio(eng, "l", lambda e, f, d: e.decode(f, d)), 50)


class TestLoad(Base):
    def load(self, body, head=SEQ):
        return self.code(engine, x=head + body)

    def test_inner_words(self):
        for ok in ("inner in run", 'inner in "run"', "inner run", "inner run run", "inner in partial"):
            self.assertIsNone(self.load(ok + "\n"), ok)
        for bad in ("inner in RUN", "inner in runs", 'inner in ""'):
            self.assertEqual(self.load(bad + "\n"), "bad-directive")
            self.assertEqual(self.load(bad + "\nbogus\n"), "unknown-directive")
        for bad in ("inner", "inner in run partial", "inner in partial run"):
            self.assertEqual(self.load(bad + "\nbogus\n"), "bad-directive")

    def test_framing(self):
        for ok in ("framing self\n", 'framing "self"\n', "framing self\narmor hex\n", "framing self\nencoding none\n",
                   "framing self\ninner in\n", "framing self\nfield m.a 8 uint\n", "field m.a 8 uint\nframing self\n"):
            self.assertIsNone(self.load(ok), ok)
        for bad in ("framing SELF\n", "framing self\nframing self\n", "kind k\nframing self\n", "framing other\n",
                    "framing self\narmor sixbit\n", "armor sixbit\nframing self\n", "framing self\nencoding uper\n",
                    "length 8 bytes\nframing self\nend\n", "group m.rows count 8\nframing self\nfield m.a 8 uint\nend\n"):
            self.assertEqual(self.load(bad), "bad-directive", bad)
            self.assertEqual(self.load(bad + "bogus\n"), "unknown-directive", bad)
        for bad in ("framing\n", "framing self self\n"):
            self.assertEqual(self.load(bad + "bogus\n"), "bad-directive", bad)
        self.assertEqual(self.load("framing self\n" + SEQ, ""), "missing-wire")
        self.assertEqual(self.load("wire bits\nframing self\nlayout sequential\n", ""), "bad-directive")
        for head in ("wire bits\nword_bytes 1\n", "wire json\n", "wire xml\nroot r\n", "wire text\n", "wire protobuf\n",
                     "wire tlv\n", "wire cbor\n"):
            self.assertEqual(self.load("framing self\n", head), "bad-directive", head)
            self.assertEqual(self.load("framing self\nbogus\n", head), "unknown-directive", head)

    def test_a_rest_to_the_end_of_the_message(self):
        R = "group m.rows rest\n  field m.a 8 uint\nend\n"
        W = "length 8 whole\n"
        F = "framing self\nfield m.n 8 uint\n"
        for ok in ("length 8 bytes\n" + R + "end\n", "count w 8\nlength @w units 8\n" + R + "end\n", W + R,
                   W + "kind k\nwhen 8 1\n" + R + "kind j\nwhen 8 2\n", "kind k\nwhen 8 1\n" + W + R,
                   "opt\n" + W + R + "end\n", "switch m.n\n  case 1\n" + W + R + "  else\nend\n", W + "opt\n" + R + "end\n",
                   "chain\n" + W + "fx\n" + R + "end\n", "opt\n" + W + "opt\n" + R + "end\nend\n",
                   "group m.subs count 8\n  length 8 bytes\n" + R + "  end\nend\n",
                   W + "group m.subs rest\n  field m.b 8 uint\n" + R + "end\n"):
            self.assertIsNone(self.load(F + ok), ok)
        for bad in (R, "kind k\nwhen 8 1\n" + R + "kind j\nwhen 8 2\n", "kind k\nwhen 8 1\n" + W + "kind j\nwhen 8 2\n" + R,
                    "presence p 8\nif p.1\n" + W + "end\n" + R, "length 8 bytes\n" + W + "end\n" + R,
                    "switch m.n\n  case 1\n" + W + "  case 2\n" + R + "end\n", "opt\n" + R + "end\n", "chain\n" + R + "end\n",
                    "switch m.n\n  case 1\n" + R + "end\n", "opt\n" + W + "end\nopt\n" + R + "end\n",
                    "group m.subs rest\n  field m.b 8 uint\n" + R + "end\n"):
            self.assertEqual(self.load(F + bad), "bad-directive", bad)
            self.assertEqual(self.load(F + bad + "bogus\n"), "unknown-directive", bad)
            self.assertIsNone(self.load(F.replace("framing self\n", "") + bad), bad)

    def test_model_keys_use_checks_1_to_4(self):
        eng = engine(c=C, in_=SEQ + TWO)
        self.assertEqual(eng.model_keys("c"), ["m.n", "m.a", "m.b"])


if __name__ == "__main__":
    unittest.main()
