"""Tests of tools/gen/gtcheck.py, the loader every generator checks its output with.

Three kinds of evidence:
  - small texts written here, one rule each, where a refusal must carry the
    error kind of the specification and the line it belongs to;
  - the load vectors of the conformance suite (packs/conformance/load-vectors):
    gtcheck must accept and refuse exactly what an engine must;
  - every model module and pack of this repository must load.
"""
import glob
import json
import os
import tempfile
import unittest

import support
import gtcheck

CORE = """module core
version 0.1.0
distribution public
source "test"
key uid string -
key lat float deg
key lon float deg
key time_ms int ms
"""
PROBE = """module probe
version 0.1.0
distribution public
source "test"
key label string -
key qty int -
key ratio float -
list items "a list"
list subs
"""
HEAD = 'format demo\nversion 0.1.0\ndistribution public\nsource "test"\nuses probe\n'


def model(*texts, limit="controlled"):
    m = gtcheck.Model(limit)
    for i, text in enumerate(texts or (CORE, PROBE)):
        m.add(text, "module[%d]" % i)
    return m


class Refusals(unittest.TestCase):
    def refuse_pack(self, text, kind, line, modules=None):
        """The pack must be refused with `kind`, naming `line` (None: the whole file)."""
        with self.assertRaises(gtcheck.CheckError) as caught:
            gtcheck.load_pack(text, modules or model(), "demo/pack.def")
        e = caught.exception
        self.assertEqual((e.kind, e.line), (kind, line), str(e))
        where = "demo/pack.def" + ("" if line is None else ":%d" % line)
        self.assertTrue(str(e).startswith("%s: %s: " % (where, kind)), str(e))
        return e

    def refuse_module(self, text, kind, line, loaded=(CORE,)):
        with self.assertRaises(gtcheck.CheckError) as caught:
            model(*loaded).add(text, "model/x.def")
        e = caught.exception
        self.assertEqual((e.kind, e.line), (kind, line), str(e))
        return e


class TokenizerTest(unittest.TestCase):
    def test_tokens_are_separated_by_spaces_and_tabs(self):
        self.assertEqual(gtcheck.tokenize("field  uid\t@id   string"), ["field", "uid", "@id", "string"])

    def test_hash_starts_a_comment_only_at_the_start_of_a_token(self):
        # 0.1.1 ruling 1: `detail/remarks/#text` is a locator, not a comment
        self.assertEqual(gtcheck.tokenize("field uid detail/remarks/#text string # note"),
                         ["field", "uid", "detail/remarks/#text", "string"])
        self.assertEqual(gtcheck.tokenize("# a whole-line comment"), [])
        self.assertEqual(gtcheck.tokenize("   "), [])

    def test_a_quoted_value_keeps_whitespace_and_hash(self):
        # 0.5 rulings 6 and 17; 0.7 ruling 1 (`"#text"` at the start of a locator)
        self.assertEqual(gtcheck.tokenize('source "a b # c"'), ["source", "a b # c"])
        self.assertEqual(gtcheck.tokenize('field uid "#text" string'), ["field", "uid", "#text", "string"])

    def test_an_empty_quoted_value_is_a_token(self):
        self.assertEqual(gtcheck.tokenize('key x string - ""'), ["key", "x", "string", "-", ""])

    def test_the_fast_path_and_the_scanner_agree(self):
        # the same line with and without a trailing comment takes the two code paths
        line = "field\tprobe.qty 0:0:8  uint"
        self.assertEqual(gtcheck.tokenize(line), gtcheck.tokenize(line + " # c"))

    def test_a_carriage_return_is_whitespace(self):
        self.assertEqual(gtcheck.tokenize("wire xml\r"), ["wire", "xml"])

    def test_an_unclosed_quote_is_refused_with_its_line(self):
        with self.assertRaises(gtcheck.CheckError) as caught:
            gtcheck.directive_lines('format demo\nsource "never closed\n', "p.def")
        self.assertEqual((caught.exception.kind, caught.exception.line), ("bad-directive", 2))
        self.assertIn("p.def:2:", str(caught.exception))

    def test_directive_lines_number_lines_from_one_and_skip_blank_and_comment_lines(self):
        rows = gtcheck.directive_lines("# c\n\nformat demo\n  # c\nwire xml\n")
        self.assertEqual(rows, [(3, ["format", "demo"]), (5, ["wire", "xml"])])


class HelperTest(unittest.TestCase):
    def test_split_key_takes_the_text_before_the_first_dot_as_the_module(self):
        self.assertEqual(gtcheck.split_key("lat"), ("core", "lat"))
        self.assertEqual(gtcheck.split_key("track.confidence"), ("track", "confidence"))
        self.assertEqual(gtcheck.split_key("a.b.c"), ("a", "b.c"))

    def test_parse_factor_reads_a_decimal_or_an_exact_fraction(self):
        self.assertEqual(gtcheck.parse_factor("0.25"), 0.25)
        self.assertEqual(gtcheck.parse_factor("1/10000000"), (1, 10000000))
        self.assertIsNone(gtcheck.parse_factor("-3/8"))  # spec 0.15 ruling 25: fractions are unsigned
        for refused in ("0", "0/5", "5/0", "1/-2", "abc", "", "1/2/3"):
            self.assertIsNone(gtcheck.parse_factor(refused), refused)

    def test_reads_as_checks_a_default_value_against_the_key_type(self):
        self.assertTrue(gtcheck.reads_as("-12", "int"))
        self.assertFalse(gtcheck.reads_as("1.5", "int"))
        self.assertTrue(gtcheck.reads_as("1.5", "float"))
        self.assertFalse(gtcheck.reads_as("north", "float"))
        self.assertTrue(gtcheck.reads_as("anything at all", "string"))


class ModuleTest(Refusals):
    def test_a_module_loads_with_keys_units_and_lists_in_file_order(self):
        mod = model().modules["probe"]
        self.assertEqual(list(mod.keys.items()), [("label", "string"), ("qty", "int"), ("ratio", "float")])
        self.assertEqual(mod.units["ratio"], "-")
        self.assertEqual(mod.lists, {"items": "a list", "subs": ""})
        self.assertEqual(mod.type_of("items"), "list")
        self.assertIsNone(mod.type_of("nosuch"))

    def test_a_key_and_a_list_share_one_namespace(self):
        self.refuse_module(PROBE + "key items string -\n", "duplicate-key", 10)
        self.refuse_module(PROBE + "list label\n", "duplicate-key", 10)
        self.refuse_module(PROBE + "key qty int -\n", "duplicate-key", 10)

    def test_a_key_line_is_checked_for_type_name_and_argument_count(self):
        self.refuse_module(PROBE + "key speed double m/s\n", "bad-directive", 10)
        self.refuse_module(PROBE + "key a.b int -\n", "bad-directive", 10)
        self.refuse_module(PROBE + "key lonely\n", "bad-directive", 10)
        self.refuse_module(PROBE + "colour red\n", "bad-directive", 10)

    def test_distribution_and_source_are_required(self):
        self.refuse_module("module x\nversion 0.1.0\nsource \"t\"\nkey a int -\n", "missing-distribution", None)
        self.refuse_module("module x\nversion 0.1.0\ndistribution public\nkey a int -\n", "missing-source", None)
        self.refuse_module("module x\ndistribution secret\nsource \"t\"\n", "bad-directive", 2)

    def test_a_module_name_loads_once(self):
        self.refuse_module(PROBE, "duplicate-module", None, loaded=(CORE, PROBE))

    def test_uses_needs_the_module_loaded_and_no_wider_distribution(self):
        other = 'module other\nversion 0.1.0\ndistribution public\nsource "t"\nuses probe\nkey o int -\n'
        self.assertEqual(model(CORE, PROBE, other).modules["other"].uses, ["probe"])
        self.refuse_module(other, "unknown-module", None)
        controlled = PROBE.replace("distribution public", "distribution controlled")
        self.refuse_module(other, "distribution-violation", None, loaded=(CORE, controlled))

    def test_the_public_limit_refuses_a_controlled_module(self):
        with self.assertRaises(gtcheck.CheckError) as caught:
            model(CORE, PROBE.replace("distribution public", "distribution controlled"), limit="public")
        self.assertEqual(caught.exception.kind, "distribution-refused")

    def test_derive_lines_are_checked_for_function_arity_keys_and_types(self):
        ok = PROBE + ("derive probe.ratio scale:1/2 probe.ratio\n"
                      "derive probe.label join:- probe.label uid\n"
                      "derive probe.qty offset:3 probe.qty\n"
                      "derive probe.ratio day_seconds time_ms\n")
        self.assertEqual([d.function for d in model(CORE, ok).modules["probe"].derives],
                         ["scale", "join", "offset", "day_seconds"])
        for line, why in (
                ("derive probe.ratio cube probe.ratio", "an unknown function"),
                ("derive probe.ratio hypot probe.ratio", "one argument where two are needed"),
                ("derive probe.ratio neg probe.qty", "an int argument of a float function"),
                ("derive probe.ratio copy probe.nosuch", "an undeclared argument"),
                ("derive probe.ratio scale probe.ratio", "scale with no factor"),
                ("derive probe.qty offset:1.5 probe.qty", "a fractional offset on integers"),
                ("derive probe.items copy probe.items", "a list as target"),
                ("derive lat copy track.lat", "an argument of a module that is not used")):
            with self.subTest(why):
                self.refuse_module(PROBE + line + "\n", "bad-directive", 10)

    def test_a_derive_target_is_a_key_of_core_or_of_the_module_itself(self):
        other = ('module other\nversion 0.1.0\ndistribution public\nsource "t"\nuses probe\nkey o int -\n'
                 "derive probe.qty copy other.o\n")
        self.refuse_module(other, "bad-directive", 7, loaded=(CORE, PROBE))

    def test_load_dir_loads_core_first_and_a_module_after_the_modules_it_uses(self):
        with tempfile.TemporaryDirectory() as d:
            files = {
                "core.def": CORE,
                # `aaa` sorts first and uses `zzz`, so byte order alone would fail
                "aaa.def": 'module aaa\nversion 1.0.0\ndistribution public\nsource "t"\nuses zzz\nkey a int -\n'
                           "derive aaa.a copy zzz.z\n",
                "zzz.def": 'module zzz\nversion 1.0.0\ndistribution public\nsource "t"\nkey z int -\n',
            }
            for name, text in files.items():
                with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                    fh.write(text)
            self.assertEqual(list(gtcheck.Model().load_dir(d).modules), ["core", "zzz", "aaa"])

    def test_load_dir_refuses_a_uses_cycle(self):
        with tempfile.TemporaryDirectory() as d:
            for name, other in (("a", "b"), ("b", "a")):
                with open(os.path.join(d, name + ".def"), "w", encoding="utf-8") as fh:
                    fh.write('module %s\nversion 1.0.0\ndistribution public\nsource "t"\nuses %s\n' % (name, other))
            with self.assertRaises(gtcheck.CheckError) as caught:
                gtcheck.Model().load_dir(d)
            self.assertEqual(caught.exception.kind, "bad-directive")
            self.assertIn("cycle", str(caught.exception))


class PackHeaderAndModelTest(Refusals):
    XML = HEAD + "wire xml\nroot msg\n"

    def test_a_pack_loads_and_exposes_what_a_generator_reads(self):
        pack = gtcheck.load_pack(self.XML + "field uid @id string\nfield probe.qty body/qty/#text int\n", model())
        self.assertEqual((pack.format, pack.wire, pack.root, pack.uses), ("demo", "xml", "msg", ["core", "probe"]))
        self.assertEqual([(n.key, n.loc, n.tr, n.line) for n in pack.common],
                         [("uid", "@id", "string", 8), ("probe.qty", "body/qty/#text", "int", 9)])

    def test_every_mapped_key_is_of_a_used_module_declared_and_typed(self):
        self.refuse_pack(self.XML.replace("uses probe\n", "") + "field probe.qty @q int\n", "module-not-used", 7)
        self.refuse_pack(self.XML + "field probe.nosuch @q int\n", "undeclared-key", 8)
        self.refuse_pack(self.XML + "field nosuch @q int\n", "undeclared-key", 8)
        self.refuse_pack(self.XML + "field probe.qty @q string\n", "key-type-mismatch", 8)
        self.refuse_pack(self.XML + "field time_ms @t iso8601_ms\nfield lat @t iso8601_ms\n", "key-type-mismatch", 9)

    def test_checks_run_in_the_order_of_the_specification(self):
        # 0.4: module-not-used on a later line is reported ahead of undeclared-key on an earlier one
        text = self.XML.replace("uses probe\n", "") + "field nosuch @a string\nfield probe.qty @q int\n"
        self.refuse_pack(text, "module-not-used", 8)
        # and undeclared-key ahead of a key-type-mismatch on an earlier line
        self.refuse_pack(self.XML + "field lat @a string\nfield nosuch @q int\n", "undeclared-key", 9)

    def test_distribution_source_and_modules_of_the_pack(self):
        self.refuse_pack(self.XML.replace("distribution public\n", ""), "missing-distribution", None)
        self.refuse_pack(self.XML.replace('source "test"\n', ""), "missing-source", None)
        self.refuse_pack(self.XML + "uses nosuch\n", "unknown-module", None)
        controlled = model(CORE, PROBE.replace("distribution public", "distribution controlled"))
        self.refuse_pack(self.XML, "distribution-violation", None, controlled)
        with self.assertRaises(gtcheck.CheckError) as caught:
            gtcheck.load_pack(self.XML.replace("public", "controlled"), model(limit="public"))
        self.assertEqual(caught.exception.kind, "distribution-refused")

    def test_an_unknown_directive_or_transform_names_its_line(self):
        self.refuse_pack(self.XML + "feild uid @id string\n", "bad-directive", 8)
        self.refuse_pack(self.XML + "field uid @id pstring\n", "bad-directive", 8)
        self.refuse_pack(self.XML + "field uid @id\n", "bad-directive", 8)
        self.refuse_pack(self.XML + "field uid @id string sideways\n", "bad-directive", 8)

    def test_header_lines_of_another_wire_are_refused(self):
        self.refuse_pack(self.XML + "bit_order msb\n", "bad-directive", 8)
        self.refuse_pack(self.XML + "layout sequential\n", "bad-directive", 8)
        self.refuse_pack(HEAD + "wire json\nroot msg\n", "bad-directive", 7)
        self.refuse_pack(HEAD + "wire morse\n", "bad-directive", 6)


class KindsTest(Refusals):
    JSON = HEAD + "wire json\nfield uid id string\n"

    def test_kinds_keep_their_lines_requires_and_when_values(self):
        pack = gtcheck.load_pack(self.JSON + "kind a\nwhen t alpha\nrequires lat lon\nfield lat pos.lat float\n"
                                 "kind b\nfield probe.qty n int\n", model())
        self.assertEqual([k.name for k in pack.kinds], ["a", "b"])
        self.assertEqual(pack.kinds[0].requires, ["lat", "lon"])
        self.assertEqual([(n.d, n.loc) for n in pack.kinds[0].lines], [("when", "t"), ("field", "pos.lat")])
        self.assertEqual([[n.line for n in lines] for _, lines in pack.scopes()], [[7, 9, 11], [7, 13]])

    def test_kind_rules(self):
        self.refuse_pack(self.JSON + "kind a\nkind a\n", "duplicate-kind", 9)
        self.refuse_pack(self.JSON + "requires lat\nkind a\n", "bad-directive", 8)
        self.refuse_pack(self.JSON + "when t alpha\n", "bad-directive", 8)
        self.refuse_pack(self.JSON + "kind a\nrequires probe.nosuch\n", "undeclared-key", 9)

    def test_requires_may_name_a_list_and_a_key_the_kind_does_not_map(self):
        gtcheck.load_pack(self.JSON + "kind a\nrequires probe.items probe.ratio\n", model())

    def test_one_xml_root_per_kind(self):
        pack = gtcheck.load_pack(HEAD + "wire xml\nkind a\nroot A\nfield uid @id string\nkind b\nroot B\n", model())
        self.assertEqual([k.root for k in pack.kinds], ["A", "B"])
        self.refuse_pack(HEAD + "wire xml\nkind a\nroot A\nroot B\n", "bad-directive", 9)


class RulesOf06Test(Refusals):
    JSON = HEAD + "wire json\n"

    def test_a_table_types_the_field_by_its_model_side(self):
        tables = "map cls 1 air\nmap cls 2 sea\nmap code 1 10\nmap code 2 20\n"
        pack = gtcheck.load_pack(self.JSON + tables + "field probe.label c int via cls\n"
                                 "field probe.qty d string via code\nfield probe.ratio e int via code\n", model())
        self.assertEqual(pack.tables["cls"], [("1", "air"), ("2", "sea")])
        self.assertEqual([n.via for n in pack.common], ["cls", "code", "code"])
        self.refuse_pack(self.JSON + tables + "field probe.qty c int via cls\n", "key-type-mismatch", 11)
        self.refuse_pack(self.JSON + "field probe.qty c int via nosuch\n", "bad-directive", 7)

    def test_default_and_const(self):
        gtcheck.load_pack(self.JSON + "default probe.qty 7\nconst kind track\nconst note =present\n", model())
        self.refuse_pack(self.JSON + "default probe.qty seven\n", "key-type-mismatch", 7)
        self.refuse_pack(self.JSON + "default probe.items 1\n", "key-type-mismatch", 7)
        self.refuse_pack(self.JSON + "default probe.nosuch 1\n", "undeclared-key", 7)
        self.refuse_pack(self.JSON + "const kind present\n", "bad-directive", 7)


class BitsTest(Refusals):
    BITS = HEAD + "wire bits\nword_bytes 1\n"

    def test_a_locator_becomes_a_bit_start_and_length(self):
        pack = gtcheck.load_pack(HEAD + "wire bits\nword_bytes 4\nfield probe.qty 2:5:12 uint\n", model())
        node = pack.common[0]
        # word 2 of 4-byte words starts at bit 64; `pos` 5 within it
        self.assertEqual((node.start, node.bits, node.tr), (69, 12, "uint"))

    def test_transform_arguments_are_kept_as_text(self):
        pack = gtcheck.load_pack(self.BITS + "field probe.ratio 0:0:32 sscale:1/10000000:-90\n", model())
        self.assertEqual((pack.common[0].tr, pack.common[0].targs), ("sscale", ("1/10000000", "-90")))

    def test_a_length_its_transform_does_not_allow_is_refused(self):
        for line in ("field probe.qty 0:0:65 uint", "field probe.qty 0:0:0 uint", "field probe.ratio 0:0:31 f32",
                     "field probe.ratio 0:0:32 f64", "field probe.label 0:0:12 ascii",
                     "field probe.ratio 0:0:8 uscale", "field probe.ratio 0:0:8 uscale:0",
                     "field probe.ratio 0:0:8 sscale:1/0", "field probe.qty 0:8 uint"):
            with self.subTest(line):
                self.refuse_pack(self.BITS + line + "\n", "bad-directive", 8)

    def test_field_options_fit_their_wire_and_transform(self):
        gtcheck.load_pack(self.BITS + "field probe.qty 0:0:16 uint swap optional\n"
                          "field probe.label 0:16:16 ascii trim\n", model())
        self.refuse_pack(self.BITS + "field probe.qty 0:0:12 uint swap\n", "bad-directive", 8)
        self.refuse_pack(self.BITS + "field probe.qty 0:0:8 uint trim\n", "bad-directive", 8)
        self.refuse_pack(self.BITS + "field probe.qty 0:0:8 uint swap swap\n", "bad-directive", 8)
        self.refuse_pack(HEAD + "wire json\nfield probe.qty n int optional\n", "bad-directive", 7)

    def test_a_when_or_const_value_must_fit_its_bits(self):
        gtcheck.load_pack(self.BITS + "const 0:0:4 15\nkind a\nwhen 0:4:4 9\n", model())
        self.refuse_pack(self.BITS + "kind a\nwhen 0:0:4 16\n", "bad-directive", 9)
        self.refuse_pack(self.BITS + "const 0:0:4 16\n", "bad-directive", 8)
        self.refuse_pack(self.BITS + "kind a\nwhen 0:0:4 -1\n", "bad-directive", 9)

    def test_a_fixed_bits_pack_needs_word_bytes(self):
        self.refuse_pack(HEAD + "wire bits\nfield probe.qty 0:0:8 uint\n", "bad-directive", None)


class GroupsTest(Refusals):
    def test_a_group_holds_its_body_and_nests(self):
        pack = gtcheck.load_pack(HEAD + "wire json\ngroup probe.items items\n  field probe.label name string\n"
                                 "  group probe.subs subs\n    field probe.qty . int\n  end\nend\n", model())
        group = pack.common[0]
        self.assertEqual((group.d, group.key, group.loc, group.line), ("group", "probe.items", "items", 7))
        self.assertEqual([n.d for n in group.body], ["field", "group"])
        self.assertEqual([n.key for n in gtcheck.walk(pack.common, "field")], ["probe.label", "probe.qty"])

    def test_block_balance(self):
        self.refuse_pack(HEAD + "wire json\ngroup probe.items items\n  field probe.label n string\n", "bad-directive", 7)
        self.refuse_pack(HEAD + "wire json\nend\n", "bad-directive", 7)

    def test_a_group_names_a_list_and_a_field_names_a_key(self):
        self.refuse_pack(HEAD + "wire json\ngroup probe.qty items\nend\n", "key-type-mismatch", 7)
        self.refuse_pack(HEAD + "wire json\nfield probe.items items string\n", "key-type-mismatch", 7)
        self.refuse_pack(HEAD + "wire json\ngroup probe.nosuch items\nend\n", "undeclared-key", 7)

    def test_one_group_per_list_in_a_scope(self):
        twice = "group probe.items a\nend\ngroup probe.items b\nend\n"
        self.refuse_pack(HEAD + "wire json\n" + twice, "bad-directive", 9)
        # common and a kind are one scope; two kinds are two
        self.refuse_pack(HEAD + "wire json\ngroup probe.items a\nend\nkind k\ngroup probe.items b\nend\n",
                         "bad-directive", 10)
        gtcheck.load_pack(HEAD + "wire json\nkind j\ngroup probe.items a\nend\nkind k\ngroup probe.items b\nend\n",
                          model())

    def test_only_field_const_default_and_group_stand_inside_a_group(self):
        for line in ("when t x", "requires lat", "map t 1 a", "uses probe", "kind k"):
            with self.subTest(line):
                self.refuse_pack(HEAD + "wire json\nkind a\ngroup probe.items items\n  %s\nend\n" % line,
                                 "bad-directive", 9)

    def test_a_field_may_not_pass_through_the_path_of_a_group(self):
        self.refuse_pack(HEAD + "wire json\ngroup probe.items items\nend\nfield probe.qty items.n int\n",
                         "bad-directive", 9)
        # exactly the group's path: allowed on json, refused on xml (0.8 ruling 30)
        gtcheck.load_pack(HEAD + "wire json\ngroup probe.items items\nend\nfield probe.label items string\n", model())
        self.refuse_pack(HEAD + "wire xml\nroot m\ngroup probe.items body/item\nend\n"
                         "field probe.label body/item/@n string\n", "bad-directive", 10)
        gtcheck.load_pack(HEAD + "wire xml\nroot m\ngroup probe.items body/item\nend\n"
                          "field probe.label body/@n string\n", model())

    def test_a_protobuf_path_is_a_tuple_and_a_scalar_item_is_the_empty_path(self):
        pack = gtcheck.load_pack(HEAD + "wire protobuf\nfield uid 2.5 pstring\ngroup probe.items 4\n"
                                 "  field probe.qty . pvarint\nend\n", model())
        self.assertEqual(pack.common[0].path, (2, 5))
        self.assertEqual((pack.common[1].path, pack.common[1].body[0].path), ((4,), ()))
        self.refuse_pack(HEAD + "wire protobuf\nfield uid 0.5 pstring\n", "bad-directive", 7)
        self.refuse_pack(HEAD + "wire protobuf\nfield uid . pstring\n", "bad-directive", 7)
        self.refuse_pack(HEAD + "wire protobuf\ngroup probe.items 4\n  field probe.qty . pvarint\n"
                         "  field probe.label 1 pstring\nend\n", "bad-directive", 7)

    def test_a_counted_bits_group_is_the_last_thing_of_its_scope(self):
        base = HEAD + "wire bits\nword_bytes 1\nfield probe.qty 0:0:8 uint\n"
        group = "group probe.items 0:16 item 8 count 0:8:8\n  field probe.ratio 0:0:8 uscale:1/2\nend\n"
        pack = gtcheck.load_pack(base + group, model())
        node = pack.common[1]
        self.assertEqual((node.start, node.item, node.mode, node.count), (16, 8, "locator", (8, 8)))
        self.refuse_pack(base + group + "field probe.ratio 0:24:8 uscale:1/2\n", "bad-directive", 12)
        self.refuse_pack(base + "group probe.items 0:16 item 8 count 0:12:8\nend\n", "bad-directive", 9)
        self.refuse_pack(base + "group probe.items 0:16 item 8\nend\n", "bad-directive", 9)
        # a field of an item may not reach beyond `item <bits>`
        self.refuse_pack(base + "group probe.items 0:16 item 8 count 2\n  field probe.qty 0:4:8 uint\nend\n",
                         "bad-directive", 10)

    def test_count_and_item_belong_to_the_bits_wire(self):
        self.refuse_pack(HEAD + "wire json\ngroup probe.items items count 2\nend\n", "bad-directive", 7)


class SequentialTest(Refusals):
    SEQ = HEAD + "wire bits\nlayout sequential\nbit_order msb\n"

    def test_a_sequential_pack_gives_a_typed_tree(self):
        text = self.SEQ + (
            "kind rec\nwhen 8 250\n"
            "presence p fx\n"
            "if p.1\n  field probe.qty 8 uint\n  also time_ms\nend\n"
            "if p.2 !p.3\n  chain\n    field probe.ratio 7 uscale:1/4\n    fx\n    pad 7\n  end\nend\n"
            "if p.9\n  group probe.items count 8\n    field probe.label 16 ascii\n  end\nend\n"
            "length 8 bytes plus 1\n  group probe.subs fx\n    field probe.qty 7 twos\n  end\nend\n")
        pack = gtcheck.load_pack(text, model())
        self.assertTrue(pack.sequential)
        lines = pack.kinds[0].lines
        self.assertEqual([n.d for n in lines], ["when", "presence", "if", "if", "if", "length"])
        self.assertEqual((lines[0].bits, lines[0].value), (8, "250"))
        self.assertEqual((lines[1].name, lines[1].bits), ("p", "fx"))
        field = lines[2].body[0]
        self.assertEqual((field.bits, field.tr, field.also, gtcheck.keys_of(field)),
                         (8, "uint", [("time_ms", None)], ["probe.qty", "time_ms"]))
        self.assertEqual(lines[3].conds, [(False, "p", 2), (True, "p", 3)])
        self.assertEqual([n.d for n in lines[3].body[0].body], ["field", "fx", "pad"])
        self.assertEqual((lines[4].body[0].mode, lines[4].body[0].count), ("count", 8))
        self.assertEqual((lines[5].bits, lines[5].unit, lines[5].plus, lines[5].whole), (8, "bytes", 1, False))
        self.assertEqual(lines[5].body[0].mode, "fx")

    def test_an_if_names_a_visible_presence_bit(self):
        self.refuse_pack(self.SEQ + "if p.1\nend\n", "bad-directive", 9)
        self.refuse_pack(self.SEQ + "presence p 2\nif p.3\nend\n", "bad-directive", 10)
        self.refuse_pack(self.SEQ + "presence p 2\nif p.0\nend\n", "bad-directive", 10)
        # a name declared inside a block is not visible after it
        self.refuse_pack(self.SEQ + "opt\n  presence q 2\nend\nif q.1\nend\n", "bad-directive", 12)
        self.refuse_pack(self.SEQ + "presence p 2\npresence p 2\n", "bad-directive", 10)

    def test_also_stands_directly_after_a_field_and_shares_its_type(self):
        self.refuse_pack(self.SEQ + "pad 8\nalso probe.qty\n", "bad-directive", 10)
        self.refuse_pack(self.SEQ + "field probe.qty 8 uint\nalso probe.label\n", "key-type-mismatch", 10)
        self.refuse_pack(HEAD + "wire bits\nword_bytes 1\nfield probe.qty 0:0:8 uint\nalso time_ms\n",
                         "bad-directive", 9)

    def test_sequential_and_fixed_lines_do_not_mix(self):
        self.refuse_pack(self.SEQ + "field probe.qty 0:0:8 uint\n", "bad-directive", 9)
        self.refuse_pack(self.SEQ.replace("layout sequential\n", "layout sequential\nword_bytes 1\n"),
                         "bad-directive", 8)
        self.refuse_pack(self.SEQ + "field probe.qty 8 uint optional\n", "bad-directive", 9)
        self.refuse_pack(HEAD + "wire bits\nword_bytes 1\npad 8\n", "bad-directive", 8)
        self.refuse_pack(self.SEQ + "fx\n", "bad-directive", 9)

    def test_when_placement_in_a_kind(self):
        gtcheck.load_pack(self.SEQ + "kind a\nrequires probe.qty\ndefault probe.qty 1\nwhen 8 1\n", model())
        self.refuse_pack(self.SEQ + "kind a\nfield probe.qty 8 uint\nwhen 8 1\n", "bad-directive", 11)
        self.refuse_pack(self.SEQ + "kind a\nopt\n  when 8 1\nend\n", "bad-directive", 11)

    def test_length_forms(self):
        self.refuse_pack(self.SEQ + "length 8 bits whole\n", "bad-directive", 9)
        self.refuse_pack(self.SEQ + "length 65\nend\n", "bad-directive", 9)
        self.refuse_pack(self.SEQ + "length 8 bytes bytes\nend\n", "bad-directive", 9)
        pack = gtcheck.load_pack(self.SEQ + "length 16 whole plus -3\nfield probe.qty 8 uint\n", model())
        self.assertEqual((pack.common[0].whole, pack.common[0].plus, pack.common[0].body), (True, -3, None))

    def test_a_list_in_two_groups_needs_separate_if_or_opt_blocks(self):
        g = "  group probe.items count 8\n    field probe.qty 8 uint\n  end\n"
        gtcheck.load_pack(self.SEQ + "presence p 2\nif p.1\n" + g + "end\nif p.2\n" + g + "end\n", model())
        self.refuse_pack(self.SEQ + g + g, "bad-directive", 12)

    def test_item_kinds_of_a_group(self):
        pack = gtcheck.load_pack(self.SEQ + "group probe.items count 8\n  field probe.qty 4 uint\n"
                                 "  kind point\n  when 4 1\n  field probe.ratio 8 uscale:1/2\n"
                                 "  kind text\n  field probe.label 8 ascii\nend\n", model())
        group = pack.common[0]
        self.assertEqual([k.name for k in group.kinds], ["point", "text"])
        self.assertEqual([n.key for n in gtcheck.walk(pack.common, "field")],
                         ["probe.qty", "probe.ratio", "probe.label"])
        self.refuse_pack(self.SEQ + "group probe.items count 8\n  kind a\n  kind a\nend\n", "duplicate-kind", 11)


class TextWireTest(Refusals):
    TEXT = HEAD + 'wire text\nstart "$"\nchecksum nmea\n'

    def test_text_locators_give_field_indexes_and_columns(self):
        pack = gtcheck.load_pack(self.TEXT + "field uid 0:2:3 string\nfield lat 2+1 dm:2:4:NS\n"
                                 "group probe.items 3 item 2\n  field probe.qty 1 int:3\nend\n", model())
        col, pair, group = pack.common
        self.assertEqual((col.fields, col.col, pair.fields, pair.col), ((0,), (2, 3), (2, 1), None))
        self.assertEqual((group.start, group.item, group.body[0].targs), (3, 2, ("3",)))

    def test_text_rules_are_refused_with_their_line(self):
        self.refuse_pack(self.TEXT + "field uid 0 string\nfield lat 1 dec:1:21\n", "bad-directive", 10)
        self.refuse_pack(self.TEXT + "kind a\nwhen 0 =\nfield uid 1 string\n", "bad-directive", 10)
        self.refuse_pack(self.TEXT + "field probe.qty 1 hms:1\n", "key-type-mismatch", 9)


# The load vectors of spec Version 0.11 (strict rulings), written by
# tools/gen/conformance-rulings011-vectors.py. gtcheck is written to the
# versions before 0.11 and does not yet name the load errors 0.11 adds
# (`unknown-directive`, `bad-locator`, `missing-wire`, ...), so these vectors
# are not compared with it until it implements 0.11.
V011_FIRST, V011_LAST = 339, 499
# The load vectors of rulings 11 to 14 of 0.13 pin how the tlv lines meet the
# 0.11 line checks (`unknown-directive`, `missing-wire`, and their order), so
# they wait for gtcheck's 0.11 too.
V011_TLV = {"wire-tlv-68", "wire-tlv-69", "wire-tlv-71", "wire-tlv-72", "wire-tlv-74"}
# Likewise rulings 13 and 14 of 0.14 and the second-armor vector.
V011_TLV |= {"wire-armor-18", "wire-armor-19"}
# And the 0.27 vectors that pin the 0.11 order of a checksum line.
V011_TLV |= {"wire-crc32-03", "wire-crc32-05"}
# Likewise the cbor vectors of 0.28 whose only point is that a cbor check
# (the top item type, a transform outside the cbor table, `swap` and `absent`
# on cbor, the `tag` value, a value path that is also a container path) runs
# after the file, so a later `bogus` line gives `unknown-directive`; gtcheck
# refuses `bogus` as `bad-directive`. The bad-locator vectors 03 to 14 are
# compared: the path form is a line check, which gtcheck makes as the line is read.
V011_TLV |= {"wire-cbor-16", "wire-cbor-25", "wire-cbor-28", "wire-cbor-35", "wire-cbor-42",
             "wire-cbor-45", "wire-cbor-57", "wire-cbor-60"}
# Ruling 28 of 0.15 pins the same order for a 0.15 transform on tlv.
V011_ORDER = {"580", "667", "668", "1003", "1004", "1077", "1078", "1079"}  # ruling 13 of 0.17, ruling 44 of 0.21 (bad-locator), ruling 28 of 0.22
# Ruling 16 of 0.30: the syntax of `when ... as` is checked after the file, so a
# later `bogus` line gives `unknown-directive`; gtcheck refuses `bogus` as `bad-directive`.
V011_ORDER |= {"3050", "3051", "3052", "3053"}
# Ruling 7 of 0.31: the 0.31 load errors are checked after the file, so a later
# `bogus` line gives `unknown-directive` (3132-3138); on protobuf the group step
# `count` stays `bad-locator` at its own line (3128, 3131, as ruling 44 of 0.21).
# gtcheck names neither kind and gives `bad-directive`.
V011_ORDER |= {"3128", "3131", "3132", "3133", "3134", "3135", "3136", "3137", "3138"}
# Rulings 10 and 16 of 0.33: every `at` error, the fixed window included, is
# checked after the file, so a later `bogus` line gives `unknown-directive`
# (3337, 3338). Ruling 14 of 0.33 puts `missing-version` before an `at` error
# (3343); gtcheck does not check a pack's `version` line (0.11, as load vector
# 378, which the 0.11 range above skips).
V011_ORDER |= {"3337", "3338", "3343"}
# And the UPER vectors of rulings 23-26 of 0.19 that pin the 0.11 order.
V011_TLV |= {"wire-uper-58", "wire-uper-61", "wire-uper-48", "wire-uper-50", "wire-uper-52", "wire-uper-53", "wire-uper-54", "wire-uper-55", "wire-uper-56", "wire-uper-57"}

class TlvWireTest(Refusals):
    TLV = HEAD + "wire tlv\ntag 2\nkey 060e2b34\nchecksum sum16 1\n"

    def test_tlv_header_and_paths_give_tags_and_sizes(self):
        pack = gtcheck.load_pack(self.TLV + "field probe.qty 48.2:4 uint\nfield uid 3 utf8\n"
                                 "field lat 13 f64\nkind a\nwhen 65:1 1\n", model())
        nested, text, double = pack.common
        self.assertEqual((pack.tag, pack.length, pack.key, pack.sum16), ("2", "ber", "060e2b34", 1))
        self.assertEqual((nested.path, nested.size, text.path, text.size, double.size),
                         ((48, 2), 4, (3,), None, None))
        self.assertEqual((pack.kinds[0].lines[0].path, pack.kinds[0].lines[0].size), ((65,), 1))

    def test_tlv_rules_are_refused_with_their_line(self):
        self.refuse_pack(self.TLV + "field probe.qty 70000:1 uint\n", "bad-directive", 10)
        self.refuse_pack(self.TLV + "field probe.qty 4:1 uint\nfield lat 4.2 f32\n", "bad-directive", 11)
        self.refuse_pack(self.TLV + "field probe.qty 1.4:1 uint\n", "bad-directive", 10)
        self.refuse_pack(self.TLV + "field uid 3 utf8\nconst 5:1 256\n", "bad-directive", 11)
        self.refuse_pack(self.TLV + "field probe.qty 4 utf8\n", "key-type-mismatch", 10)
        # the tlv forms on another wire are refused after the file is read,
        # before `missing-distribution`
        no_distribution = 'format demo\nversion 0.1.0\nsource "test"\nuses probe\nwire json\n'
        self.refuse_pack(no_distribution + "tag 1\nfield uid id string\n", "bad-directive", 6)


class CborWireTest(Refusals):
    CBOR = HEAD + "wire cbor\n"

    def test_cbor_paths_give_steps_and_the_top_type(self):
        pack = gtcheck.load_pack(self.CBOR + "tag 18\nfield probe.qty -1 int\nfield uid a_b-c.[2].d text\n"
                                 "field probe.ratio 18446744073709551615 float\n"
                                 "group probe.items 9\n  field probe.label . bytes\nend\n", model())
        neg, deep, big, group = pack.common
        self.assertEqual((pack.cbor_tag, pack.cbor_top), (18, "map"))
        self.assertEqual(neg.path, (("int", -1),))
        self.assertEqual(deep.path, (("text", "a_b-c"), ("pos", 2), ("text", "d")))
        self.assertEqual(big.path, (("int", (1 << 64) - 1),))
        self.assertEqual((group.path, group.body[0].path), ((("int", 9),), ()))
        pack = gtcheck.load_pack(self.CBOR + "group probe.items .\n  field probe.qty [0] uint\nend\n", model())
        self.assertEqual(pack.cbor_top, "array")

    def test_when_and_const_values(self):
        self.assertEqual([gtcheck.cbor_value(v) for v in ("-0005", "00", "18446744073709551615", "true", "=7",
                                                          "18446744073709551616", "+1")],
                         [-5, 0, (1 << 64) - 1, True, "7", "18446744073709551616", "+1"])
        gtcheck.load_pack(self.CBOR + "field uid 1 text\nconst 2 -0005\nconst 3 =x\nkind a\nwhen 0 false\n",
                          model())

    def test_a_malformed_path_is_a_bad_locator_as_the_line_is_read(self):
        for path in ("a[0]", "[01]", "-0", "+1", "a..b", "01", "-a", "[65536]", "a:b", ".",
                     "18446744073709551616", "-9223372036854775809"):
            self.refuse_pack(self.CBOR + "field probe.qty %s int\nbogus\n" % path, "bad-locator", 7)
        self.refuse_pack(self.CBOR + "group probe.items 9\n  group probe.subs .\n    field probe.qty . int\n"
                         "  end\nend\n", "bad-locator", 8)

    def test_cbor_rules_are_refused_with_their_line(self):
        c = self.CBOR
        self.refuse_pack(c + "field uid 1 text\nfield probe.qty [0] int\n", "bad-directive", 8)
        self.refuse_pack(c + "field probe.qty 7.1 int\nfield uid 7.[0] text\n", "bad-directive", 8)
        self.refuse_pack(c + "group probe.items 9\n  field uid n text\nend\nfield probe.qty 9.1 int\n",
                         "bad-directive", 10)
        self.refuse_pack(c + "group probe.items 9\n  field uid n text\nend\ngroup probe.subs 9\n"
                         "  field probe.qty . int\nend\n", "bad-directive", 10)
        self.refuse_pack(c + "group probe.items 9\n  field uid . text\n  field probe.qty n uint\nend\n",
                         "bad-directive", 9)
        self.refuse_pack(c + "group probe.items 9\n  field uid [0] text\n  field probe.qty n uint\nend\n",
                         "bad-directive", 9)
        self.refuse_pack(c + "field probe.qty 2 int\nfield probe.ratio 2.1 float\n", "bad-directive", 8)
        self.refuse_pack(c + "field probe.qty 1 string\n", "bad-directive", 7)
        for option in ("swap", "trim", "optional", "absent 5"):
            self.refuse_pack(c + "field probe.qty 1 int %s\n" % option, "bad-directive", 7)
        self.refuse_pack(c + "tag 018\n", "bad-directive", 7)
        self.refuse_pack(c + "tag 18446744073709551616\n", "bad-directive", 7)
        self.refuse_pack(c + "tag ber-oid\n", "bad-directive", 7)
        self.refuse_pack(c + "tag 1\ntag 1\n", "bad-directive", 8)
        self.refuse_pack(c + "field uid 1 text\nkind k\nwhen 0 1\ntag 1\n", "bad-directive", 10)
        self.refuse_pack(c + "tag 1 2\nbogus\n", "bad-directive", 7)
        self.refuse_pack(c + "field uid 1 bool\n", "key-type-mismatch", 7)
        # a `when … present` may name a prefix of another line's path; the
        # same paths in two kinds are two scopes
        gtcheck.load_pack(c + "field uid 1 text\nkind a\nwhen 7 present\nfield lat 7.1 float\n", model())
        gtcheck.load_pack(c + "kind a\nwhen 0 1\nfield probe.qty 2 int\nkind b\nwhen 0 2\n"
                          "field probe.ratio 2.[0] float\n", model())


class ArmorTest(Refusals):
    ARMOR = HEAD + "wire bits\nword_bytes 1\nbit_order msb\narmor sixbit\n"
    SEQ = HEAD + "wire bits\nlayout sequential\nbit_order msb\narmor sixbit\n"

    def test_armor_and_sixbit_load_in_either_layout(self):
        pack = gtcheck.load_pack(self.ARMOR + "field uid 0:0:42 sixbit trim\n", model())
        self.assertEqual((pack.armor, pack.common[0].tr, pack.common[0].bits), ("sixbit", "sixbit", 42))
        pack = gtcheck.load_pack(self.SEQ + "field uid 120 sixbit\nlength 8 bytes\n  field probe.qty 8 uint\nend\n",
                                 model())
        self.assertEqual(pack.armor, "sixbit")
        # the default is hex, and `sixbit` needs no armor
        pack = gtcheck.load_pack(HEAD + "wire bits\nword_bytes 1\nfield uid 0:0:6 sixbit\n", model())
        self.assertEqual(pack.armor, "hex")

    def test_armor_rules_are_refused_with_their_line(self):
        bits = HEAD + "wire bits\nword_bytes 1\n"
        self.refuse_pack(bits + "armor sixbit\nfield probe.qty 0:0:6 uint\n", "bad-directive", 8)
        self.refuse_pack(bits + "bit_order msb\narmor ascii\nfield probe.qty 0:0:6 uint\n", "bad-directive", 9)
        self.refuse_pack(self.ARMOR + "armor hex\n", "bad-directive", 10)
        self.refuse_pack(self.ARMOR + "kind a\nwhen 0:0:6 1\narmor hex\n", "bad-directive", 12)
        self.refuse_pack(self.SEQ + "opt\n  armor hex\nend\n", "bad-directive", 11)
        self.refuse_pack(self.SEQ + "field probe.qty 6 uint\nlength 12 whole\n", "bad-directive", 11)
        self.refuse_pack(self.ARMOR + "field uid 0:0:12 sixbit swap\n", "bad-directive", 10)
        self.refuse_pack(self.ARMOR + "field uid 0:0:16 sixbit\n", "bad-directive", 10)
        self.refuse_pack(self.ARMOR + "field uid 0:0:1536 sixbit\n", "bad-directive", 10)
        self.refuse_pack(self.ARMOR + "field probe.qty 0:0:6 sixbit\n", "key-type-mismatch", 10)
        self.refuse_pack(HEAD + "wire json\nfield uid id sixbit\n", "bad-directive", 7)
        # `armor` on another wire is refused after the file is read, before
        # `missing-distribution`
        no_distribution = 'format demo\nversion 0.1.0\nsource "test"\nuses probe\n'
        self.refuse_pack(no_distribution + "armor hex\nwire json\nfield uid id string\n", "bad-directive", 5)



class GateTest(Refusals):
    SEQ = HEAD + "wire bits\nlayout sequential\nbit_order msb\n"

    def test_a_gate_block_on_a_fixed_layout(self):
        fixed = HEAD + "wire bits\nword_bytes 1\n"
        pack = gtcheck.load_pack(fixed + "if !0:8:2 0,3\n  default probe.qty 1\n  field probe.qty 0:0:8 uint\n"
                                 "  if 0:10:1 1\n    const 0:11:1 1\n  end\nend\n", model())
        gate = pack.common[0]
        self.assertEqual((gate.d, gate.gate, gate.start, gate.bits), ("if", (True, (0, 3)), 8, 2))
        self.assertEqual([n.d for n in gate.body], ["default", "field", "if"])
        self.refuse_pack(fixed + "if 0:0:2 4\nend\n", "bad-directive", 8)
        self.refuse_pack(fixed + "if 0:0:2 1,1\nend\n", "bad-directive", 8)
        self.refuse_pack(fixed + "if 0:0:2\nend\n", "bad-directive", 8)
        self.refuse_pack(fixed + "if p.1\nend\n", "bad-directive", 8)
        self.refuse_pack(fixed + "if 0:0:1 1\n", "bad-directive", 8)
        self.refuse_pack(fixed + "kind k\nwhen 0:0:4 1\nif 0:4:1 1\n  when 0:0:4 1\nend\n", "bad-directive", 11)
        self.refuse_pack(self.SEQ + "if 0:0:1 1\nend\n", "bad-directive", 9)
        self.refuse_pack(HEAD + "wire json\nif 0:0:1 1\nend\n", "bad-directive", 7)
        # ruling 2: item-relative, inside the item, before a group counted by a locator
        gtcheck.load_pack(fixed + "group probe.items 0:8 item 8 count 2\n  if 0:7:1 1\n"
                          "    field probe.qty 0:0:7 uint\n  end\nend\n", model())
        self.refuse_pack(fixed + "group probe.items 0:8 item 8 count 2\n  if 0:8:1 1\n  end\nend\n",
                         "bad-directive", 9)
        self.refuse_pack(fixed + "group probe.items 0:8 item 8 count 0:0:8\nend\nif 0:8:1 1\nend\n",
                         "bad-directive", 10)

class UperTest(Refusals):
    SEQ = HEAD + "wire bits\nlayout sequential\nbit_order msb\n"
    UPER = SEQ + "encoding uper\n"

    def test_uper_locators_blocks_and_sizes_give_a_typed_tree(self):
        pack = gtcheck.load_pack(
            self.UPER + "field probe.qty int:-5:5:ext twos\nfield probe.ratio int:0: uscale:1/4\n"
            "field probe.qty int:: uint\nfield probe.qty enum:3:ext uint\nfield probe.label chars:8:8 ascii\n"
            "field probe.label octets: hex\nalso uid\nfield probe.qty 1 uint\n"
            "ext\n  presence p 1\n  if p.1\n    field probe.qty int:0:15 uint\n  end\nend\n"
            "choice 3 ext\n  alt 2\n    field probe.label chars: ascii\n  alt 0\nend\n"
            "group probe.items size 0 3\n  field probe.ratio int:0:1023 uscale:1\nend\n"
            "group probe.subs size\nend\n", model())
        self.assertEqual(pack.encoding, "uper")
        locs = [n.uper for n in pack.common if n.d == "field"]
        self.assertEqual(locs, [("int", -5, 5, True), ("int", 0, None, False), ("int", None, None, False),
                                ("enum", 3, None, True), ("chars", 8, 8, False), ("octets", None, None, False),
                                None])
        choice = next(n for n in pack.common if n.d == "choice")
        self.assertEqual((choice.count, [(a.d, a.count, len(a.body)) for a in choice.body]),
                         (3, [("alt", 2, 1), ("alt", 0, 0)]))
        groups = [n for n in pack.common if n.d == "group"]
        self.assertEqual([(g.mode, g.count) for g in groups], [("size", (0, 3)), ("size", None)])
        # `encoding none` loads in any bits pack, and is the default
        self.assertEqual(gtcheck.load_pack(HEAD + "wire bits\nword_bytes 1\nencoding none\n"
                                           "field probe.qty 0:0:8 uint\n", model()).encoding, "none")

    def test_the_encoding_directive_is_refused_with_its_line(self):
        self.refuse_pack(HEAD + "wire bits\nlayout sequential\nencoding uper\n", "bad-directive", 8)
        self.refuse_pack(HEAD + "wire bits\nword_bytes 1\nbit_order msb\nencoding uper\n", "bad-directive", 9)
        self.refuse_pack(HEAD + "wire json\nencoding none\nfield uid id string\n", "bad-directive", 7)
        self.refuse_pack(self.SEQ + "encoding aper\n", "bad-directive", 9)
        self.refuse_pack(self.UPER + "encoding uper\n", "bad-directive", 10)
        self.refuse_pack(self.SEQ + "kind a\nencoding uper\n", "bad-directive", 10)
        self.refuse_pack(self.SEQ + "opt\n  encoding uper\nend\n", "bad-directive", 10)
        self.refuse_pack(self.UPER + "armor sixbit\n", "bad-directive", 9)
        # checked after the file is read, before `missing-distribution`
        no_distribution = 'format demo\nversion 0.1.0\nsource "test"\nuses probe\n'
        self.refuse_pack(no_distribution + "encoding uper\nwire json\nfield uid id string\n", "bad-directive", 5)

    def test_uper_lines_are_refused_outside_a_uper_pack(self):
        self.refuse_pack(self.SEQ + "field probe.qty int:0:3 uint\n", "bad-directive", 9)
        self.refuse_pack(self.SEQ + "ext\nend\n", "bad-directive", 9)
        self.refuse_pack(self.SEQ + "choice 1\n  alt 0\nend\n", "bad-directive", 9)
        self.refuse_pack(self.SEQ + "group probe.items size\nend\n", "bad-directive", 9)
        # on json such a locator is a path (ruling 19)
        gtcheck.load_pack(HEAD + "wire json\nfield probe.qty int:x int\n", model())

    def test_locator_numbers_and_ranges(self):
        for loc in ("int:5:4", "int:0:07", "int:-0:5", "int:+1:5", "int:0:9223372036854775808", "int:",
                    "int:1", "int::ext", "int:0:1:x", "enum:0", "enum:65537", "enum:3:x", "chars:0:65536",
                    "chars:4:3", "chars:-1:2", "octets:4", "octets:1:2:ext"):
            self.refuse_pack(self.UPER + "field probe.qty %s uint\n" % loc, "bad-directive", 10)
        gtcheck.load_pack(self.UPER + "field probe.qty int:-9223372036854775808:9223372036854775807 uint\n"
                          "field probe.qty enum:65536 uint\nfield probe.label chars:0:65535 ascii\n", model())

    def test_transforms_options_and_lines_on_uper_locators(self):
        for line in ("field probe.ratio int:0:3 f32", "field probe.qty enum:3 twos",
                     "field probe.label chars:1:8 utf8", "field probe.label octets: ascii",
                     "field probe.label chars: sixbit", "field probe.label 6 hex",
                     "field probe.qty int:0:65535 uint swap", "field probe.label chars:1:8 ascii trim",
                     "field probe.qty int:0:3 uint:2", "const int:0:3 1"):
            self.refuse_pack(self.UPER + line + "\n", "bad-directive", 10)
        self.refuse_pack(self.UPER + "kind a\nwhen int:0:3 1\n", "bad-directive", 11)
        self.refuse_pack(self.UPER + "group probe.items count int:0:3\nend\n", "bad-directive", 10)
        self.refuse_pack(self.UPER + "field probe.qty int:0:3 uscale:2\n", "key-type-mismatch", 10)
        self.refuse_pack(self.UPER + "field probe.qty octets: hex\n", "key-type-mismatch", 10)

    def test_ext_choice_and_size_rules_are_refused_with_their_line(self):
        self.refuse_pack(self.UPER + "ext\n  field probe.qty 1 uint\n  presence p 1\nend\n", "bad-directive", 12)
        self.refuse_pack(self.UPER + "ext 1\nend\n", "bad-directive", 10)
        self.refuse_pack(self.UPER + "choice 2\n  alt 0\n  alt 2\nend\n", "bad-directive", 12)
        self.refuse_pack(self.UPER + "choice 2\n  alt 0\n  alt 0\nend\n", "bad-directive", 12)
        self.refuse_pack(self.UPER + "choice 2\n  alt 01\nend\n", "bad-directive", 11)
        self.refuse_pack(self.UPER + "choice 2\n  field probe.qty 1 uint\n  alt 0\nend\n", "bad-directive", 11)
        self.refuse_pack(self.UPER + "alt 0\n", "bad-directive", 10)
        self.refuse_pack(self.UPER + "opt\n  alt 0\nend\n", "bad-directive", 11)
        self.refuse_pack(self.UPER + "choice 2\nend\n", "bad-directive", 10)
        for head in ("choice 0", "choice 65537", "choice 2 x", "choice"):
            self.refuse_pack(self.UPER + head + "\n  alt 0\nend\n", "bad-directive", 10)
        self.refuse_pack(self.UPER + "choice 1\n  alt 0\n    kind a\nend\n", "bad-directive", 12)
        for size in ("size 3 1", "size 0 65536", "size 1", "size -1 2"):
            self.refuse_pack(self.UPER + "group probe.items %s\nend\n" % size, "bad-directive", 10)
        # nested choices: one `end` closes the inner `alt` and its `choice`
        gtcheck.load_pack(self.UPER + "choice 2\n  alt 0\n    choice 1\n      alt 0\n    end\n"
                          "    field probe.qty 1 uint\n  alt 1\nend\n", model())


class ConformanceLoadVectorsTest(unittest.TestCase):
    """gtcheck against the load vectors every engine must pass
    (spec/vector-format.md, "Load vectors"), up to Version 0.10."""

    def test_gtcheck_accepts_and_refuses_what_every_load_vector_states(self):
        paths = sorted(glob.glob(os.path.join(support.REPO, "packs", "conformance", "load-vectors", "*.json")))
        self.assertGreater(len(paths), 300, "the load vectors were not found")
        disagree = []
        for path in paths:
            head = os.path.basename(path).split("-")[0]
            if head.isdigit() and V011_FIRST <= int(head) <= V011_LAST:
                continue
            if "-".join(os.path.basename(path).split("-")[:3]) in V011_TLV:
                continue
            if head in V011_ORDER:
                continue
            with open(path, encoding="utf-8") as fh:
                vector = json.load(fh)
            got = None
            try:
                m = gtcheck.Model(vector.get("max_distribution", "controlled"))
                for i, text in enumerate(vector["models"]):
                    m.add(text, "models[%d]" % i)
                for text in vector["packs"] if "packs" in vector else [vector["pack"]]:
                    gtcheck.load_pack(text, m, "pack")
            except gtcheck.CheckError as e:
                got = e.kind
            if got != vector.get("expect_error"):
                disagree.append("%s: expected %s, gtcheck gives %s"
                                % (os.path.basename(path), vector.get("expect_error", "a load"), got or "a load"))
        self.assertEqual(disagree, [])


class RepositoryTest(unittest.TestCase):
    def test_every_module_and_pack_of_the_repository_loads(self):
        model_dir = os.path.join(support.REPO, "model")
        packs = sorted(glob.glob(os.path.join(support.REPO, "packs", "*", "pack.def")))
        self.assertGreater(len(packs), 50)
        loaded_model, loaded = gtcheck.check_output(model_dir, packs)
        self.assertIn("core", loaded_model.modules)
        self.assertEqual(len(loaded), len(packs))
        self.assertEqual(len({p.format for p in loaded}), len(loaded), "two packs state one format name")

    def test_the_command_line_reports_a_refusal_with_file_and_line(self):
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "model"))
            for name, text in (("core.def", CORE), ("probe.def", PROBE)):
                with open(os.path.join(d, "model", name), "w", encoding="utf-8") as fh:
                    fh.write(text)
            good, bad = os.path.join(d, "good.def"), os.path.join(d, "bad.def")
            with open(good, "w", encoding="utf-8") as fh:
                fh.write(HEAD + "wire json\nfield uid id string\n")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write(HEAD + "wire json\nfield probe.nosuch id string\n")
            status, out, err = support.run_main(gtcheck.main, ["--model", os.path.join(d, "model"), good])
            self.assertEqual((status, err), (0, ""))
            self.assertIn("ok, 2 modules, 1 packs", out)
            status, out, err = support.run_main(gtcheck.main, ["--model", os.path.join(d, "model"), good, bad])
            self.assertEqual(status, 1)
            self.assertIn("bad.def:7: undeclared-key:", err)


if __name__ == "__main__":
    unittest.main()
