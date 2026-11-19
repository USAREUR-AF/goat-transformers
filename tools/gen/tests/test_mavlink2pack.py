"""Tests of tools/gen/mavlink2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_mavlink2pack*.py'

The fixture under `fixtures/mavlink2pack/input/sources/` is three small dialect
files written for these tests and a PROVENANCE.md that states their SHA-256.
The generator refuses a file whose SHA-256 differs, so after an edit of a
fixture file write its new value into that table (`shasum -a 256 <file>`),
then run once with GT_UPDATE_GOLDEN=1 and review the diff of `expected/`.
"""
import support

import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import unittest

import gtcheck
import mavlink2pack as gen

FIXTURE = os.path.join(support.FIXTURES, "mavlink2pack")
INPUT = os.path.join(FIXTURE, "input")
EXPECTED = os.path.join(FIXTURE, "expected")
SCRIPT = os.path.join(support.GEN, "mavlink2pack.py")


def crc16_mcrf4xx(data):
    """CRC-16/MCRF4XX one bit at a time (reflected polynomial 0x8408, initial
    value 0xFFFF, no final XOR): the definition, not the generator's byte form."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc


def dialect(messages, includes=()):
    """The bytes of a dialect file that holds the given <message> elements.
    With no include the first of them starts on line 4."""
    head = "".join("  <include>%s</include>\n" % name for name in includes)
    return ("<?xml version=\"1.0\"?>\n<mavlink>\n%s  <messages>\n%s\n  </messages>\n</mavlink>\n"
            % (head, messages)).encode()


def messages_of(xml):
    """The SourceMessage records of inline <message> elements, in id order."""
    return sorted(gen.parse_dialect(dialect(xml), "common.xml")[1], key=lambda m: m.id)


def plan_of(xml):
    return gen.make_plan(messages_of(xml))


def lines_of(kind):
    """{field name: [(key, locator, transform)]} of a planned kind."""
    return {f.field.name: [(line.key, gen.loc(line.pos, line.bits), line.transform) for line in f.lines]
            for f in kind.fields}


def field(type_text, name="f", **attrs):
    return gen.parse_field(dict(attrs, type=type_text, name=name), "M", False, "sources/common.xml", 1)


class TempDirCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def make_root(self, name="root", edits=None):
        """A copy of the fixture input. `edits` maps a source file name to a
        function of its text; the SHA-256 table is rewritten for the result."""
        root = support.copy_tree(INPUT, os.path.join(self.tmp, name))
        src = os.path.join(root, "sources")
        for file_name, edit in (edits or {}).items():
            path = os.path.join(src, file_name)
            with open(path, encoding="utf-8") as fh:
                text = edit(fh.read())
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        prov = os.path.join(src, "PROVENANCE.md")
        with open(prov, encoding="utf-8") as fh:
            table = fh.read()
        for file_name in gen.XML_FILES:
            with open(os.path.join(src, file_name), "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            table = re.sub(r"(\| `%s` \|[^|]*\| `)[0-9a-f]{64}" % re.escape(file_name),
                           lambda m: m.group(1) + digest, table)
        with open(prov, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(table)
        return root

    def run_gen(self, root, *more):
        return support.run_main(gen.main, ["--out", root] + list(more))

    def refused(self, edits):
        """Run on an edited fixture; the one-line message of the refusal."""
        root = self.make_root(edits=edits)
        status, _, err = self.run_gen(root)
        self.assertEqual(status, 1, err)
        self.assertEqual(err.count("\n"), 1, err)
        self.assertTrue(err.startswith("mavlink2pack: "), err)
        self.assertFalse(os.path.exists(os.path.join(root, "packs", "mavlink2", "pack.md")),
                         "pack.md is written only after every check passed")
        return err


class GoldenTree(TempDirCase):
    def test_fixture_input_gives_the_expected_tree(self):
        root = self.make_root()
        status, out, err = self.run_gen(root)
        self.assertEqual((status, err), (0, ""))
        self.assertIn("self-check        ok", out)
        support.assert_same_tree(self, EXPECTED, root, ignore=("sources/",))

    def test_second_run_over_its_own_output_changes_nothing(self):
        root = self.make_root()
        self.run_gen(root)
        first = support.tree(root)
        status, _, _ = self.run_gen(root)
        self.assertEqual(status, 0)
        self.assertEqual(support.tree(root), first)

    def test_root_is_the_old_spelling_of_out(self):
        root = self.make_root()
        status, _, err = support.run_main(gen.main, ["--root", root])
        self.assertEqual((status, err), (0, ""))
        support.assert_same_tree(self, EXPECTED, root, ignore=("sources/",))

    def test_core_def_of_the_repository_is_accepted_and_changes_no_byte(self):
        root = self.make_root()
        status, _, err = self.run_gen(root, "--core-def", os.path.join(support.REPO, "model", "core.def"))
        self.assertEqual((status, err), (0, ""))
        support.assert_same_tree(self, EXPECTED, root, ignore=("sources/",))

    def test_a_vector_file_of_an_earlier_run_that_is_no_longer_written_is_removed(self):
        root = self.make_root()
        stale = os.path.join(root, "packs", "mavlink2", "vectors", "rt-00999-gone.json")
        os.makedirs(os.path.dirname(stale))
        with open(stale, "w") as fh:
            fh.write("{}\n")
        self.assertEqual(self.run_gen(root)[0], 0)
        self.assertFalse(os.path.exists(stale))
        support.assert_same_tree(self, EXPECTED, root, ignore=("sources/",))


class CheckMode(TempDirCase):
    def test_check_passes_on_fresh_output_and_writes_nothing(self):
        root = self.make_root()
        self.run_gen(root)
        before = support.tree(root)
        status, _, err = self.run_gen(root, "--check")
        self.assertEqual(status, 0, err)
        self.assertIn("--check: ok", err)
        self.assertEqual(support.tree(root), before)

    def test_check_names_a_changed_file_and_leaves_the_tree_alone(self):
        root = self.make_root()
        self.run_gen(root)
        path = os.path.join(root, "packs", "mavlink2", "vectors", "rt-00300-test_point.json")
        with open(path, "rb") as fh:
            data = fh.read()
        with open(path, "wb") as fh:
            fh.write(data.replace(b"fd", b"fe", 1))
        before = support.tree(root)
        status, _, err = self.run_gen(root, "--check")
        self.assertEqual(status, 1)
        self.assertIn("packs/mavlink2/vectors/rt-00300-test_point.json differs", err)
        self.assertEqual(support.tree(root), before)

    def test_check_on_a_directory_with_no_output_reports_missing_files_and_creates_none(self):
        root = self.make_root()
        before = support.tree(root)
        status, _, err = self.run_gen(root, "--check")
        self.assertEqual(status, 1)
        self.assertIn("model/mavlink.def is missing", err)
        self.assertIn("packs/mavlink2/pack.md is missing", err)
        self.assertEqual(support.tree(root), before)

    def test_check_reports_a_stale_vector_file_and_keeps_it(self):
        root = self.make_root()
        self.run_gen(root)
        stale = os.path.join(root, "packs", "mavlink2", "vectors", "rt-00999-gone.json")
        with open(stale, "w") as fh:
            fh.write("{}\n")
        status, _, err = self.run_gen(root, "--check")
        self.assertEqual(status, 1)
        self.assertIn("rt-00999-gone.json is not written by the generator", err)
        self.assertTrue(os.path.exists(stale))


class GeneratedFilesLoad(unittest.TestCase):
    """The expected tree, read by gtcheck: the golden files are not the only
    witness of what the pack states."""

    @classmethod
    def setUpClass(cls):
        cls.model = gtcheck.Model()
        cls.model.add(gen.CORE_STAND_IN, "core")
        with open(os.path.join(EXPECTED, "model", "mavlink.def"), encoding="utf-8") as fh:
            cls.module = cls.model.add(fh.read(), "model/mavlink.def")
        with open(os.path.join(EXPECTED, "packs", "mavlink2", "pack.def"), encoding="utf-8") as fh:
            cls.pack = gtcheck.load_pack(fh.read(), cls.model, "packs/mavlink2/pack.def")
        cls.kinds = {k.name: k for k in cls.pack.kinds}

    def fields(self, kind):
        return {n.key: n for n in self.kinds[kind].lines if n.d == "field"}

    def test_header_is_the_fixed_layout_lsb_bits_wire_with_one_byte_words(self):
        p = self.pack
        self.assertEqual((p.format, p.wire, p.layout, p.bit_order, p.word_bytes, p.distribution),
                         ("mavlink2", "bits", "fixed", "lsb", 1, "public"))
        self.assertEqual(p.uses, ["core", "mavlink"])

    def test_kinds_are_in_message_id_order_whatever_the_order_in_the_files(self):
        self.assertEqual([k.name for k in self.pack.kinds],
                         ["heartbeat", "sys_status", "system_time", "gps_raw_int", "attitude", "global_position_int",
                          "command_long", "hil_gps", "gps2_raw", "adsb_vehicle", "test_point", "test_survey",
                          "utm_global_position", "test_shapes", "test_arrays", "test_unknowns"])

    def test_a_kind_is_selected_by_message_id_and_full_payload_length(self):
        # TEST_SHAPES: id 50001 in the 24-bit MSGID at bit 56; 52 base bytes and
        # 8 extension bytes
        whens = sorted((n.loc, n.value) for n in self.kinds["test_shapes"].lines if n.d == "when")
        self.assertEqual(whens, [("0:56:24", "50001"), ("0:8:8", "60")])

    def test_dege7_lat_is_core_lat_through_sscale_with_a_fraction(self):
        lat = self.fields("global_position_int")["lat"]
        self.assertEqual((lat.loc, lat.tr, lat.targs), ("0:112:32", "sscale", ("1/10000000",)))
        self.assertEqual(self.model.type_of("lat"), "float")

    def test_array_elements_are_one_key_each_at_consecutive_offsets(self):
        f = self.fields("test_shapes")
        # wire order: total(8) precise(8) ratio(4) height(4), then the 2-byte fields
        self.assertEqual([f["mavlink.counts_%d" % i].loc for i in range(4)],
                         ["0:272:16", "0:288:16", "0:304:16", "0:320:16"])
        self.assertEqual(f["mavlink.counts_0"].tr, "uint")

    def test_text_field_is_one_ascii_key_of_eight_bits_per_character(self):
        label = self.fields("test_shapes")["mavlink.label"]
        self.assertEqual((label.tr, label.bits), ("ascii", 80))
        self.assertEqual(self.module.keys["label"], "string")

    def test_requires_names_only_raw_keys_of_the_kind(self):
        for kind in self.pack.kinds:
            own = {n.key for n in kind.lines if n.d == "field"}
            self.assertTrue(kind.requires and set(kind.requires) <= own, kind.name)
            self.assertTrue(all(k.startswith("mavlink.") for k in kind.requires), kind.name)

    def test_frame_invariants_hold_and_every_expected_vector_passes_the_codec(self):
        gen.check_frame_invariants(self.pack)
        directory = os.path.join(EXPECTED, "packs", "mavlink2", "vectors")
        vectors = []
        for name in sorted(os.listdir(directory)):
            with open(os.path.join(directory, name), encoding="utf-8") as fh:
                vectors.append((name, fh.read()))
        self.assertEqual(gen.check_vectors(self.pack, vectors), 16 + 9 + 4 + 2)

    def test_long_arrays_are_listed_in_pack_md_and_have_no_field_line(self):
        with open(os.path.join(EXPECTED, "packs", "mavlink2", "pack.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("| TEST_ARRAYS | samples | `uint8_t[9]` |", text)
        self.assertIn("| TEST_ARRAYS | history | `int16_t[12]` |", text)
        keys = self.fields("test_arrays")
        self.assertFalse([k for k in keys if "samples" in k or "history" in k])
        self.assertIn("mavlink.window_7", keys)


class CommittedPack(unittest.TestCase):
    """The pack of the repository, without regenerating it."""

    def test_committed_mavlink2_pack_loads_keeps_the_frame_and_passes_every_vector(self):
        model = gtcheck.Model().load_dir(os.path.join(support.REPO, "model"))
        pack_dir = os.path.join(support.REPO, "packs", "mavlink2")
        pack = gtcheck.load_pack_file(os.path.join(pack_dir, "pack.def"), model)
        gen.check_frame_invariants(pack)
        vectors = []
        for name in sorted(os.listdir(os.path.join(pack_dir, "vectors"))):
            if name.endswith(".json"):
                with open(os.path.join(pack_dir, "vectors", name), encoding="utf-8") as fh:
                    vectors.append((name, fh.read()))
        self.assertEqual(gen.check_vectors(pack, vectors), len(vectors))
        self.assertGreater(len(vectors), len(pack.kinds))


class Refusals(TempDirCase):
    def test_xml_that_is_not_well_formed_is_refused_with_file_and_line(self):
        err = self.refused({"standard.xml": lambda t: t.replace("</message>", "</mesage>", 1)})
        # the closing tag of the one message of standard.xml is on line 20
        self.assertRegex(err, r"^mavlink2pack: sources/standard\.xml:20: not well-formed XML: mismatched tag")

    def test_unknown_field_type_is_refused_with_file_line_message_and_field(self):
        err = self.refused({"minimal.xml": lambda t: t.replace('type="uint32_t" name="custom_mode"',
                                                               'type="uint24_t" name="custom_mode"')})
        self.assertEqual(err, "mavlink2pack: sources/minimal.xml:21: HEARTBEAT.custom_mode: unknown type uint24_t\n")

    def test_source_file_that_differs_from_its_sha256_is_refused(self):
        root = self.make_root()
        with open(os.path.join(root, "sources", "standard.xml"), "a") as fh:
            fh.write("\n")
        status, _, err = self.run_gen(root)
        self.assertEqual(status, 1)
        self.assertEqual(err, "mavlink2pack: sources/standard.xml: does not match the SHA-256 in PROVENANCE.md\n")
        self.assertFalse(os.path.exists(os.path.join(root, "model")))

    def test_two_messages_with_one_id_are_refused_and_both_places_named(self):
        err = self.refused({"common.xml": lambda t: t.replace('id="300"', 'id="33"')})
        self.assertRegex(err, r"sources/common\.xml:\d+: message id 33 is also declared at sources/standard\.xml:10\n")

    def test_changed_field_order_of_a_message_with_a_fixed_crc_extra_is_refused(self):
        def swap(text):
            a = '      <field type="uint8_t" name="type">kind of vehicle or component</field>\n'
            b = '      <field type="uint8_t" name="autopilot">kind of flight controller</field>\n'
            self.assertIn(a + b, text)
            return text.replace(a + b, b + a)
        err = self.refused({"minimal.xml": swap})
        self.assertRegex(err, r"CRC_EXTRA of HEARTBEAT is \[\d+\], protocol value is 50")

    def test_payload_longer_than_255_bytes_is_refused(self):
        err = self.refused({"common.xml": lambda t: t.replace('type="int16_t[12]" name="history"',
                                                              'type="int16_t[110]" name="history"')})
        self.assertRegex(err, r"sources/common\.xml:\d+: TEST_ARRAYS: payload length 263 outside 1\.\.255")

    def test_two_fields_of_one_message_that_give_one_key_are_refused(self):
        # `level` in cm proposes level_cm, and so does a field named level_cm
        err = self.refused({"common.xml": lambda t: t.replace(
            '<field type="int16_t" name="climb" units="cm/s">', '<field type="int16_t" name="level_cm" units="cm">')})
        self.assertRegex(err, r"sources/common\.xml:\d+: TEST_SHAPES: fields level and level_cm both give the key ")

    def test_include_chain_other_than_the_three_files_is_refused(self):
        err = self.refused({"standard.xml": lambda t: t.replace("  <include>minimal.xml</include>\n", "")})
        self.assertIn("sources/common.xml: include chain is ['common.xml', 'standard.xml']", err)

    def test_missing_source_file_is_one_line_and_status_1(self):
        root = self.make_root()
        os.remove(os.path.join(root, "sources", "minimal.xml"))
        status, _, err = self.run_gen(root)
        self.assertEqual(status, 1)
        self.assertRegex(err, r"^mavlink2pack: .*minimal\.xml: No such file or directory\n$")

    def test_source_without_a_message_a_geojson_vector_needs_is_refused(self):
        err = self.refused({"common.xml": lambda t: t.replace('name="HIL_GPS"', 'name="TEST_HIL"')})
        self.assertIn("the source has no message HIL_GPS", err)

    def test_unknown_option_is_a_usage_error(self):
        status, _, err = support.run_main(gen.main, ["--no-such-option"])
        self.assertEqual(status, 2)
        self.assertIn("usage:", err)


class Determinism(TempDirCase):
    def test_messages_in_another_order_in_the_file_give_the_same_bytes(self):
        def reverse(text):
            blocks = re.findall(r"    <message .*?</message>\n", text, re.S)
            self.assertEqual(len(blocks), 14)
            head = text[:text.index("  <messages>\n")]
            return head + "  <messages>\n" + "".join(reversed(blocks)) + "  </messages>\n</mavlink>\n"
        root = self.make_root(edits={"common.xml": reverse})
        status, _, err = self.run_gen(root)
        self.assertEqual((status, err), (0, ""))
        support.assert_same_tree(self, EXPECTED, root, ignore=("sources/",))

    def test_output_does_not_depend_on_the_hash_seed(self):
        for seed in ("1", "4242"):
            root = self.make_root("seed-" + seed)
            done = subprocess.run([sys.executable, "-I", SCRIPT, "--out", root],
                                  env=dict(os.environ, PYTHONHASHSEED=seed),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(done.returncode, 0, done.stderr.decode())
            support.assert_same_tree(self, EXPECTED, root, ignore=("sources/",))


class ParseDialect(unittest.TestCase):
    XML = dialect("""    <message id="7" name="ONE">
      <description>text with a <b>child</b> element</description>
      <field type="uint8_t_mavlink_version" name="version">v</field>
      <field type="char[5]" name="tag" units="x" enum="E" invalid="[0]">t</field>
      <extensions/>
      <field type="float[3]" name="more">m</field>
      <wip><field type="uint8_t" name="not_a_child_of_the_message"/></wip>
    </message>
    <message id="9" name="TWO"><field type="double" name="d"/></message>""", includes=["standard.xml"])

    def test_records_hold_types_attributes_extension_flag_and_lines(self):
        includes, (one, two) = gen.parse_dialect(self.XML, "common.xml")
        self.assertEqual(includes, ["standard.xml"])
        self.assertEqual((one.name, one.id, one.file, one.line), ("ONE", 7, "common.xml", 5))
        self.assertEqual(list(one.fields), [
            gen.SourceField("version", "uint8_t", None, None, None, None, False, 7),
            gen.SourceField("tag", "char", 5, "x", "E", "[0]", False, 8),
            gen.SourceField("more", "float", 3, None, None, None, True, 10)])
        self.assertEqual((two.name, two.id, [f.name for f in two.fields]), ("TWO", 9, ["d"]))

    def test_field_sizes(self):
        _, (one, _) = gen.parse_dialect(self.XML, "common.xml")
        self.assertEqual([(f.size, f.bytes, f.is_array) for f in one.fields],
                         [(1, 1, False), (1, 5, False), (4, 12, True)])

    def test_message_of_an_xml_namespace_is_not_a_mavlink_message(self):
        data = b'<mavlink xmlns:o="urn:other"><messages><o:message id="1" name="X"/></messages></mavlink>'
        self.assertEqual(gen.parse_dialect(data, "common.xml"), ([], []))

    def test_refusals_carry_file_and_line(self):
        cases = [
            ('<message id="x1" name="M"/>', "sources/common.xml:4: M: id `x1` is not a number"),
            ('<message id="1"/>', "sources/common.xml:4: a message has no name"),
            ('<message id="1" name="M">\n<field type="char" name="c"/></message>',
             "sources/common.xml:5: M.c: type char has no length"),
            ('<message id="1" name="M">\n<field type="uint8_t[0]" name="z"/></message>',
             "sources/common.xml:5: M.z: type uint8_t[0] has no length"),
            ('<message id="1" name="M">\n\n<field type="uint8_t"/></message>',
             "sources/common.xml:6: M: a field has no name or no type"),
        ]
        for xml, message in cases:
            with self.assertRaises(gen.GenError) as raised:
                gen.parse_dialect(dialect("    " + xml), "common.xml")
            self.assertEqual(str(raised.exception), message)


class Provenance(TempDirCase):
    def test_commit_is_read_and_a_missing_commit_or_row_is_refused(self):
        root = self.make_root()
        src = os.path.join(root, "sources")
        self.assertEqual(gen.read_provenance(src), "0123456789abcdef0123456789abcdef01234567")
        path = os.path.join(src, "PROVENANCE.md")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for broken, message in ((re.sub(r"\| `minimal.xml`.*\n", "", text), "no SHA-256 row for minimal.xml"),
                                (text.replace("Commit: `0123", "Commit: `xyz"), "no `Commit:` line")):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(broken)
            with self.assertRaises(gen.GenError) as raised:
                gen.read_provenance(src)
            self.assertIn("sources/PROVENANCE.md: " + message, str(raised.exception))


class Checksum(unittest.TestCase):
    HEARTBEAT = [("uint8_t", "type"), ("uint8_t", "autopilot"), ("uint8_t", "base_mode"),
                 ("uint32_t", "custom_mode"), ("uint8_t", "system_status"), ("uint8_t", "mavlink_version")]

    def test_x25_gives_the_published_check_value_of_crc16_mcrf4xx(self):
        self.assertEqual(gen.x25(b"123456789"), 0x6F91)
        self.assertEqual(gen.x25(b""), 0xFFFF)

    def test_x25_agrees_with_the_bit_by_bit_definition_and_continues_a_checksum(self):
        for data in (b"\x00", b"\xff" * 7, bytes(range(256)), b"HEARTBEAT uint32_t custom_mode "):
            self.assertEqual(gen.x25(data), crc16_mcrf4xx(data))
        self.assertEqual(gen.x25(b"6789", gen.x25(b"12345")), 0x6F91)

    def test_crc_extra_of_heartbeat_as_the_protocol_defines_it_is_50(self):
        fields = [field(t, n) for t, n in self.HEARTBEAT]
        self.assertEqual(gen.crc_extra("HEARTBEAT", fields), 50)

    def test_extension_field_does_not_change_crc_extra(self):
        fields = [field(t, n) for t, n in self.HEARTBEAT]
        extension = gen.parse_field({"type": "uint64_t", "name": "later"}, "HEARTBEAT", True, "f", 1)
        self.assertEqual(gen.crc_extra("HEARTBEAT", fields + [extension]), 50)

    def test_crc_extra_depends_on_order_within_one_size_and_on_array_length(self):
        fields = [field(t, n) for t, n in self.HEARTBEAT]
        swapped = [fields[1], fields[0]] + fields[2:]
        self.assertNotEqual(gen.crc_extra("HEARTBEAT", swapped), 50)
        self.assertNotEqual(gen.crc_extra("M", [field("uint8_t[2]", "a")]), gen.crc_extra("M", [field("uint8_t[3]", "a")]))

    def test_crc_extra_does_not_depend_on_declaration_order_across_sizes(self):
        # custom_mode is the only 4-byte field: wherever it is declared it is first on the wire
        fields = [field(t, n) for t, n in self.HEARTBEAT]
        moved = [fields[3]] + fields[:3] + fields[4:]
        self.assertEqual(gen.crc_extra("HEARTBEAT", moved), 50)


class LayOut(unittest.TestCase):
    XML = """    <message id="70000" name="M">
      <field type="uint8_t" name="a"/>
      <field type="uint16_t[4]" name="b"/>
      <field type="char[10]" name="c"/>
      <field type="uint64_t" name="d"/>
      <field type="float" name="e"/>
      <field type="uint16_t" name="f"/>
      %s
    </message>"""
    EXT = '<extensions/><field type="uint8_t" name="x"/><field type="double" name="y"/>'

    def placed(self, xml):
        layout = gen.lay_out(messages_of(xml)[0])
        return [(p.field.name, p.offset) for p in layout.wire], layout.length

    def test_base_fields_go_largest_type_first_and_keep_declaration_order_within_a_size(self):
        # d is 8 bytes; e is 4; b (an array of 2-byte elements, 8 bytes in all)
        # and f are 2 and stay in declaration order; a and c are 1
        self.assertEqual(self.placed(self.XML % ""),
                         ([("d", 0), ("e", 8), ("b", 12), ("f", 20), ("a", 22), ("c", 23)], 33))

    def test_extension_fields_follow_in_declaration_order_whatever_their_size(self):
        wire, length = self.placed(self.XML % self.EXT)
        self.assertEqual(wire[6:], [("x", 33), ("y", 34)])
        self.assertEqual(length, 42)

    def test_payload_of_256_bytes_and_an_empty_message_are_refused_with_the_message_line(self):
        for body in ('<field type="uint8_t[255]" name="a"/><field type="uint8_t" name="b"/>', ""):
            with self.assertRaises(gen.GenError) as raised:
                gen.lay_out(messages_of('<message id="1" name="M">%s</message>' % body)[0])
            self.assertRegex(str(raised.exception), r"^sources/common\.xml:4: M: payload length (256|0) outside")

    def test_payload_of_255_bytes_is_accepted(self):
        xml = '<message id="1" name="M"><field type="uint8_t[255]" name="a"/></message>'
        self.assertEqual(gen.lay_out(messages_of(xml)[0]).length, 255)

    def test_message_id_that_does_not_fit_24_bits_is_refused(self):
        xml = '<message id="16777216" name="M"><field type="uint8_t" name="a"/></message>'
        with self.assertRaises(gen.GenError):
            gen.lay_out(messages_of(xml)[0])
        ok = xml.replace("16777216", "16777215")
        self.assertEqual(gen.lay_out(messages_of(ok)[0]).message.id, 16777215)


class Naming(unittest.TestCase):
    def test_slug(self):
        for text, want in (("cm/s", "cm_per_s"), ("d%", "dpct"), ("%", "pct"), ("m/s*5", "m_per_s_x5"),
                           ("m^2", "m2"), ("degE7", "dege7"), ("Air-Speed", "air_speed"),
                           ("rad/s", "rad_per_s"), ("_x__y_", "x_y")):
            self.assertEqual(gen.slug(text), want, text)

    def test_base_key_appends_the_unit_unless_the_name_already_ends_with_it(self):
        self.assertEqual(gen.base_key(field("int32_t", "alt", units="mm")), "alt_mm")
        self.assertEqual(gen.base_key(field("int32_t", "alt_mm", units="mm")), "alt_mm")
        self.assertEqual(gen.base_key(field("int32_t", "mm", units="mm")), "mm")
        self.assertEqual(gen.base_key(field("int32_t", "alt")), "alt")
        self.assertEqual(gen.base_key(field("uint16_t", "Vcc", units="mV")), "vcc_mv")
        # `time_usec` does not end with `_us`, so the unit is appended
        self.assertEqual(gen.base_key(field("uint64_t", "time_usec", units="us")), "time_usec_us")
        self.assertEqual(gen.base_key(field("uint32_t", "time_boot_ms", units="ms")), "time_boot_ms")

    def test_transform_and_model_type_of_every_wire_type(self):
        table = {"uint8_t": ("uint", "int"), "uint16_t": ("uint", "int"), "uint32_t": ("uint", "int"),
                 "uint64_t": ("uint", "int"), "int8_t": ("twos", "int"), "int16_t": ("twos", "int"),
                 "int32_t": ("twos", "int"), "int64_t": ("twos", "int"), "float": ("f32", "float"),
                 "double": ("f64", "float"), "char[7]": ("ascii", "string"),
                 "uint8_t_mavlink_version": ("uint", "int")}
        for type_text, want in table.items():
            f = field(type_text)
            self.assertEqual((gen.transform_for(f), gen.type_class(f)), want, type_text)
        self.assertEqual(sorted(gen.SIZES), sorted(set(t.split("[")[0] for t in table) - {"uint8_t_mavlink_version"}))

    def test_every_transform_the_generator_writes_yields_the_type_it_declares(self):
        for type_text in ("uint8_t", "int64_t", "float", "double", "char[2]"):
            f = field(type_text)
            self.assertEqual(gtcheck.BITS_TRANSFORMS[gen.transform_for(f)], gen.type_class(f))

    def test_loc_is_word_zero_and_a_bit_offset_from_stx(self):
        self.assertEqual(gen.loc(80, 32), "0:80:32")
        self.assertEqual(gen.loc(*gen.LOC_MSGID), "0:56:24")


class AssignKeys(unittest.TestCase):
    def test_same_name_with_different_types_takes_the_message_name_in_both_messages(self):
        plan = plan_of("""<message id="1" name="ONE"><field type="uint8_t" name="value"/></message>
                          <message id="2" name="TWO"><field type="float" name="value"/></message>""")
        self.assertEqual(lines_of(plan.kinds[0])["value"], [("mavlink.one_value", "0:80:8", "uint")])
        self.assertEqual(lines_of(plan.kinds[1])["value"], [("mavlink.two_value", "0:80:32", "f32")])
        self.assertEqual(dict(plan.qualified), {("ONE", "value"): "different types", ("TWO", "value"): "different types"})
        self.assertEqual((plan.keys["one_value"].type, plan.keys["two_value"].type), ("int", "float"))

    def test_int_widths_and_signs_are_one_type_class_and_share_a_key(self):
        plan = plan_of("""<message id="1" name="ONE"><field type="uint8_t" name="value"/></message>
                          <message id="2" name="TWO"><field type="int32_t" name="value"/></message>""")
        self.assertEqual(dict(plan.qualified), {})
        self.assertEqual(plan.keys["value"].uses, [("ONE", "value"), ("TWO", "value")])
        self.assertEqual(lines_of(plan.kinds[1])["value"], [("mavlink.value", "0:80:32", "twos")])

    def test_names_that_differ_only_in_case_share_one_key(self):
        plan = plan_of("""<message id="1" name="ONE"><field type="uint16_t" name="Vcc" units="mV"/></message>
                          <message id="2" name="TWO"><field type="uint16_t" name="vcc" units="mV"/></message>""")
        self.assertEqual(list(plan.keys), ["vcc_mv"])
        self.assertEqual(plan.keys["vcc_mv"], gen.KeyDecl("int", "mV", [("ONE", "Vcc"), ("TWO", "vcc")]))

    def test_same_key_name_from_different_units_or_enums_is_qualified(self):
        plan = plan_of("""<message id="1" name="ONE"><field type="int32_t" name="alt" units="mm"/>
                                                     <field type="uint8_t" name="mode" enum="E"/></message>
                          <message id="2" name="TWO"><field type="int32_t" name="alt_mm"/>
                                                     <field type="uint8_t" name="mode"/></message>""")
        self.assertEqual(plan.qualified[("ONE", "alt")], "different units")
        self.assertEqual(plan.qualified[("TWO", "alt_mm")], "different units")
        self.assertEqual(plan.qualified[("ONE", "mode")], "different enums")
        self.assertEqual(sorted(plan.keys), ["one_alt_mm", "one_mode", "two_alt_mm", "two_mode"])
        self.assertEqual((plan.keys["one_alt_mm"].unit, plan.keys["two_alt_mm"].unit), ("mm", "-"))

    def test_field_named_like_a_frame_header_key_is_qualified(self):
        plan = plan_of('<message id="1" name="ONE"><field type="uint8_t" name="seq"/></message>')
        self.assertEqual(lines_of(plan.kinds[0])["seq"], [("mavlink.one_seq", "0:80:8", "uint")])
        self.assertEqual(plan.qualified[("ONE", "seq")], "same name as a frame-header key")

    def test_dege7_int32_lat_lon_map_to_core_keys_with_the_fraction_scale(self):
        plan = plan_of("""<message id="1" name="ONE"><field type="uint8_t" name="fix"/>
            <field type="int32_t" name="lat" units="degE7"/><field type="int32_t" name="lon" units="degE7"/></message>""")
        lines = lines_of(plan.kinds[0])
        self.assertEqual(lines["lat"], [("lat", "0:80:32", "sscale:1/10000000")])
        self.assertEqual(lines["lon"], [("lon", "0:112:32", "sscale:1/10000000")])
        self.assertEqual(list(plan.keys), ["fix"])
        self.assertEqual(plan.kinds[0].requires, ["mavlink.fix"])

    def test_positions_that_are_not_plain_dege7_int32_lat_lon_stay_raw(self):
        plan = plan_of("""<message id="1" name="ONE"><field type="uint8_t" name="fix"/>
            <field type="int32_t" name="lat" units="degE7" invalid="INT32_MAX"/>
            <field type="int32_t" name="lon" units="deg"/>
            <field type="int32_t" name="latitude" units="degE7"/>
            <field type="int64_t" name="longitude" units="degE7"/></message>""")
        self.assertEqual({name: lines[0][0::2] for name, lines in lines_of(plan.kinds[0]).items()}, {
            "longitude": ("mavlink.longitude_dege7", "twos"), "lat": ("mavlink.lat_dege7", "twos"),
            "lon": ("mavlink.lon_deg", "twos"), "latitude": ("mavlink.latitude_dege7", "twos"),
            "fix": ("mavlink.fix", "uint")})

    def test_message_with_nothing_but_lat_and_lon_keeps_them_raw_so_it_has_a_key_to_require(self):
        plan = plan_of("""<message id="1" name="ONE"><field type="int32_t" name="lat" units="degE7"/>
            <field type="int32_t" name="lon" units="degE7"/><field type="uint8_t[9]" name="long_array"/></message>""")
        kind = plan.kinds[0]
        self.assertFalse(kind.core_ok)
        self.assertEqual(kind.requires, ["mavlink.lat_dege7", "mavlink.lon_dege7"])
        self.assertEqual([f.status for f in kind.fields], ["scalar", "scalar", "unmapped"])

    def test_array_of_eight_is_mapped_per_element_and_array_of_nine_is_not(self):
        plan = plan_of("""<message id="1" name="ONE"><field type="int16_t[8]" name="a" units="cm"/>
                          <field type="int16_t[9]" name="b"/><field type="uint8_t" name="c"/></message>""")
        kind = plan.kinds[0]
        lines = lines_of(kind)
        self.assertEqual(lines["a"], [("mavlink.a_cm_%d" % i, "0:%d:16" % (80 + 16 * i), "twos") for i in range(8)])
        self.assertEqual(lines["b"], [])
        self.assertEqual(lines["c"], [("mavlink.c", "0:%d:8" % (80 + 8 * 34), "uint")])
        self.assertEqual([f.status for f in kind.fields], ["elements", "unmapped", "scalar"])
        self.assertEqual(plan.keys["a_cm_7"], gen.KeyDecl("int", "cm", [("ONE", "a")]))

    def test_char_array_longer_than_eight_is_one_text_key(self):
        plan = plan_of('<message id="1" name="ONE"><field type="char[20]" name="text"/></message>')
        self.assertEqual(lines_of(plan.kinds[0])["text"], [("mavlink.text", "0:80:160", "ascii")])
        self.assertEqual(plan.keys["text"].type, "string")

    def test_key_of_every_field_is_the_same_whatever_the_order_of_the_messages(self):
        xml = """<message id="1" name="ONE"><field type="uint8_t" name="value"/><field type="float" name="x"/></message>
                 <message id="2" name="TWO"><field type="float" name="value"/><field type="float" name="x"/></message>
                 <message id="3" name="SIX"><field type="uint16_t[2]" name="value"/><field type="char[3]" name="x"/></message>"""
        messages = messages_of(xml)

        def keys_by_field(order):
            plan = gen.make_plan(order)
            return ({(k.message.name, name): lines for k in plan.kinds for name, lines in lines_of(k).items()},
                    {name: (decl.type, decl.unit, sorted(decl.uses)) for name, decl in plan.keys.items()})
        self.assertEqual(keys_by_field(messages), keys_by_field(messages[::-1]))
        self.assertEqual(keys_by_field(messages), keys_by_field([messages[1], messages[2], messages[0]]))

    def test_two_fields_of_one_message_with_one_key_are_refused_at_the_second_field(self):
        cases = ['<field type="uint8_t" name="Rate"/>\n<field type="uint8_t" name="rate"/>',
                 '<field type="uint8_t[2]" name="v"/>\n<field type="uint8_t" name="v_0"/>']
        for body in cases:
            with self.assertRaises(gen.GenError) as raised:
                plan_of('<message id="1" name="ONE">%s</message>' % body)
            self.assertRegex(str(raised.exception), r"^sources/common\.xml:5: ONE: fields \w+ and \w+ both give the key ")


class Requires(unittest.TestCase):
    def test_the_keys_fewest_kinds_map_are_chosen_and_written_in_line_order(self):
        # kind A maps 8 keys; k0 and k3 are mapped by B as well, so the six others are chosen
        a = ["k%d" % i for i in range(8)]
        chosen = gen.choose_requires(["A", "B"], [a, ["k3", "k0", "b"]])
        self.assertEqual(chosen[0], ["k1", "k2", "k4", "k5", "k6", "k7"])
        self.assertEqual(chosen[1], ["k3", "k0", "b"])

    def test_at_most_six_keys_and_among_equals_the_earlier_lines(self):
        chosen = gen.choose_requires(["A"], [["k%d" % i for i in range(9)]])
        self.assertEqual(chosen, [["k0", "k1", "k2", "k3", "k4", "k5"]])
        self.assertEqual(gen.MAX_REQUIRES, 6)

    def test_a_shared_key_is_still_required_when_the_kind_has_too_few_others(self):
        chosen = gen.choose_requires(["A", "B"], [["s", "a"], ["s"]])
        self.assertEqual(chosen, [["s", "a"], ["s"]])

    def test_kind_with_no_raw_key_is_refused_by_name(self):
        with self.assertRaises(gen.GenError) as raised:
            gen.choose_requires(["A", "B"], [["a"], []])
        self.assertEqual(str(raised.exception), "B has no raw key to require")

    def test_message_with_only_long_arrays_is_refused(self):
        with self.assertRaises(gen.GenError) as raised:
            plan_of('<message id="1" name="ONE"><field type="uint8_t[9]" name="a"/></message>')
        self.assertIn("ONE has no raw key to require", str(raised.exception))

    def test_shadows_name_every_other_kind_that_maps_all_required_keys(self):
        raw = [["p", "q"], ["p", "q", "r"], ["p"]]
        requires = gen.choose_requires(["A", "B", "C"], raw)
        self.assertEqual(requires, [["p", "q"], ["p", "q", "r"], ["p"]])
        self.assertEqual(gen.find_shadows(["A", "B", "C"], requires, raw), [["B"], [], ["A", "B"]])


class Frames(unittest.TestCase):
    # id 300 = 0x00012C. Wire order: big (4 bytes) at 0, small at 4, tag at 5; LEN 8.
    XML = """<message id="300" name="TEST_FRAME"><field type="uint8_t" name="small"/>
             <field type="char[3]" name="tag"/><field type="uint32_t" name="big"/>
             <extensions/><field type="int16_t[9]" name="tail"/></message>"""
    HEAD = "fd" "1a" "00" "00" "05" "01" "02" "2c0100"          # STX LEN flags SEQ SYSID COMPID MSGID
    PAYLOAD = "44332211" "07" "410000"                             # big, small, tag "A" padded with NUL

    def setUp(self):
        self.kind = plan_of(self.XML).kinds[0]

    def test_pack_scalar_is_little_endian_and_text_is_padded_with_nul(self):
        self.assertEqual(gen.pack_scalar(field("uint32_t"), 0x11223344).hex(), "44332211")
        self.assertEqual(gen.pack_scalar(field("int16_t"), -2).hex(), "feff")
        self.assertEqual(gen.pack_scalar(field("int8_t"), -128).hex(), "80")
        self.assertEqual(gen.pack_scalar(field("uint64_t"), 1 << 63).hex(), "0000000000000080")
        self.assertEqual(gen.pack_scalar(field("float"), 1.0).hex(), "0000803f")
        self.assertEqual(gen.pack_scalar(field("double"), -2.0).hex(), "00000000000000c0")
        self.assertEqual(gen.pack_scalar(field("char[3]"), "A"), b"A\0\0")

    def test_build_payload_puts_fields_in_wire_order_and_zero_fills_the_rest(self):
        payload = gen.build_payload(self.kind, {"small": 7, "tag": "A", "big": 0x11223344})
        self.assertEqual(payload.hex(), self.PAYLOAD + "00" * 18)
        with_tail = gen.build_payload(self.kind, {"tail": list(range(1, 10))})
        self.assertEqual(with_tail.hex(), "00" * 8 + "".join("%02x00" % i for i in range(1, 10)))

    def test_build_payload_refuses_a_name_the_message_does_not_have_and_a_short_array(self):
        with self.assertRaises(gen.GenError):
            gen.build_payload(self.kind, {"bigg": 1})
        with self.assertRaises(gen.GenError):
            gen.build_payload(self.kind, {"tail": [1, 2]})

    def test_frame_is_the_hand_packed_mavlink2_frame_with_crc_over_all_but_stx_plus_crc_extra(self):
        payload = gen.build_payload(self.kind, {"small": 7, "tag": "A", "big": 0x11223344})
        got = gen.frame(self.kind, payload, 5, 1, 2, True)
        body = bytes.fromhex(self.HEAD + self.PAYLOAD + "00" * 18)
        self.assertEqual(got[:-2], body)
        crc = crc16_mcrf4xx(body[1:] + bytes([self.kind.crc_extra]))
        self.assertEqual(got[-2:], struct.pack("<H", crc))
        self.assertEqual(len(got), 10 + 26 + 2)
        self.assertEqual(gen.frame(self.kind, payload, 5, 1, 2, False), body)

    def test_roundtrip_vector_ends_at_the_last_mapped_byte_and_keeps_the_full_len(self):
        # `tail` (9 elements) is not mapped: the frame is the header and 8 payload
        # bytes, LEN still states 26, and no CRC follows
        data = gen.roundtrip_vector(self.kind, 261)
        self.assertEqual(self.kind.mapped_len, 8)
        self.assertEqual(len(data), 18)
        self.assertEqual(data[:4].hex(), "fd1a0000")
        self.assertEqual(data[4], 261 % 256)
        self.assertEqual(data[7:10].hex(), "2c0100")

    def test_roundtrip_vector_does_not_drop_trailing_zero_bytes_of_mapped_fields(self):
        kind = plan_of('<message id="2" name="Z"><field type="uint8_t" name="a"/><field type="char[6]" name="t"/></message>').kinds[0]
        data = gen.roundtrip_vector(kind, 0)
        self.assertEqual(len(data), 10 + 7)
        self.assertEqual(data[-3:], b"\0\0\0")       # the sample text is shorter than the field

    def test_vector_files_refuse_a_source_without_a_message_of_the_geojson_cases(self):
        with self.assertRaises(gen.GenError) as raised:
            gen.vector_files([self.kind])
        self.assertIn("no message GLOBAL_POSITION_INT", str(raised.exception))


class Numbers(unittest.TestCase):
    def test_fmt_float_is_plain_shortest_decimal(self):
        for value, want in ((0.0, "0"), (-0.0, "0"), (-180.0, "-180"), (47.397742, "47.397742"),
                            (1e-07, "0.0000001"), (-2.5e-05, "-0.000025"), (0.1 + 0.2, "0.30000000000000004"),
                            (1e22, "10000000000000000000000"), (0.25, "0.25")):
            self.assertEqual(gen.fmt_float(value), want)

    def test_round_away_rounds_halves_away_from_zero(self):
        for value, want in ((0.5, 1), (-0.5, -1), (1.5, 2), (2.5, 3), (-2.5, -3), (2.4, 2), (-2.4, -2), (0.0, 0)):
            self.assertEqual(gen.round_away(value), want, value)

    def test_sample_values_fit_their_type(self):
        for type_text, lo, hi in (("uint8_t", 0, 255), ("int8_t", -128, 127), ("uint16_t", 0, 65535),
                                  ("int16_t", -32768, 32767), ("int32_t", -2 ** 31, 2 ** 31 - 1),
                                  ("uint64_t", 0, 2 ** 64 - 1), ("int64_t", -2 ** 63, 2 ** 63 - 1)):
            f = field(type_text)
            for salt in range(0, 3000, 7):
                value = gen.sample_value(f, salt)
                self.assertTrue(lo <= value <= hi, (type_text, salt, value))
                gen.pack_scalar(f, value)
        self.assertTrue(any(gen.sample_value(field("uint64_t"), s) >> 63 for s in range(4)))
        self.assertLessEqual(len(gen.sample_value(field("char[1]"), 96)), 1)


PACK_TEXT = """format mavlink2
version 0.1.0
distribution public
source "test"
uses mavlink
wire bits
bit_order lsb
word_bytes 1
when 0:0:8 253
field mavlink.seq 0:32:8 uint

kind one
when 0:56:24 300
when 0:8:8 15
requires mavlink.count
field lat 0:80:32 sscale:1/10000000
field mavlink.count 0:112:64 uint
field mavlink.tag 0:176:16 ascii
field mavlink.delta 0:192:8 twos

kind two
when 0:56:24 301
when 0:8:8 4
requires mavlink.ratio
field mavlink.ratio 0:80:32 f32
"""
MODULE_TEXT = """module mavlink
version 0.1.0
distribution public
source "test"
key seq int -
key count int -
key tag string -
key delta int -
key ratio float -
"""


def load(pack_text):
    model = gtcheck.Model()
    model.add(gen.CORE_STAND_IN, "core")
    model.add(MODULE_TEXT, "module")
    return gtcheck.load_pack(pack_text, model, "pack.def")


class Codec(unittest.TestCase):
    # kind one, seq 9: lat -33.8568 deg = -338568000 = 0xEBD1DCC0; count 2^63 + 1; tag "A"; delta -3
    ONE = "fd0f0000090000" "2c0100" "c0dcd1eb" "0100000000000080" "4100" "fd"

    def test_decode_reads_every_field_of_the_kind_the_when_lines_select(self):
        name, entity = gen.engine_decode(load(PACK_TEXT), bytes.fromhex(self.ONE))
        self.assertEqual(name, "one")
        self.assertEqual(dict(entity), {"mavlink.seq": 9, "lat": -33.8568, "mavlink.count": -(2 ** 63) + 1,
                                        "mavlink.tag": "A", "mavlink.delta": -3})

    def test_encode_gives_back_the_bytes_and_leaves_absent_fields_zero(self):
        pack = load(PACK_TEXT)
        name, entity = gen.engine_decode(pack, bytes.fromhex(self.ONE))
        self.assertEqual(gen.engine_encode(pack, name, entity).hex(), self.ONE)
        self.assertEqual(gen.engine_encode(pack, "two", {"mavlink.ratio": 1.0}).hex(),
                         "fd040000000000" "2d0100" "0000803f")

    def test_bytes_after_the_last_mapped_bit_are_ignored(self):
        name, _ = gen.engine_decode(load(PACK_TEXT), bytes.fromhex(self.ONE + "aabb"))
        self.assertEqual(name, "one")

    def test_wrong_stx_unknown_id_and_another_len_select_no_kind(self):
        pack = load(PACK_TEXT)
        for broken in ("fe" + self.ONE[2:], self.ONE[:14] + "2e0100" + self.ONE[20:], "fd0e" + self.ONE[4:]):
            with self.assertRaises(gen.CodecError) as raised:
                gen.engine_decode(pack, bytes.fromhex(broken))
            self.assertEqual(str(raised.exception), "no-kind")

    def test_message_shorter_than_the_last_mapped_bit_is_malformed(self):
        with self.assertRaises(gen.CodecError) as raised:
            gen.engine_decode(load(PACK_TEXT), bytes.fromhex(self.ONE)[:-1])
        self.assertEqual(str(raised.exception), "malformed-wire")

    def test_sscale_with_a_fraction_divides_by_the_denominator(self):
        # 0.5 ruling 1: 473977421 * 1 / 10000000 is the double nearest 47.3977421;
        # multiplying by 1e-07 gives 47.397742099999995
        self.assertEqual(gen.decode_value("sscale", ("1/10000000",), 32, 473977421), 47.3977421)
        self.assertNotEqual(473977421 * 1e-07, 47.3977421)
        self.assertEqual(gen.decode_value("sscale", ("0.0000001",), 32, 473977421), 473977421 * 1e-07)
        self.assertEqual(gen.decode_value("sscale", ("1/10000000",), 32, 0xEBD1DCC0), -33.8568)
        self.assertEqual(gen.encode_value("sscale", ("1/10000000",), 32, -33.8568), 0xEBD1DCC0)
        self.assertEqual(gen.encode_value("sscale", ("1/10000000",), 32, 47.397742), 473977420)

    def test_scale_with_a_decimal_factor_and_an_offset(self):
        self.assertEqual(gen.decode_value("uscale", ("0.5", "-40"), 8, 100), 10.0)
        self.assertEqual(gen.encode_value("uscale", ("0.5", "-40"), 8, 10.0), 100)
        self.assertEqual(gen.encode_value("uscale", ("2",), 8, 5.0), 3)        # 2.5 rounds away from zero

    def test_scale_refuses_a_value_outside_the_field(self):
        for tr, value in (("sscale", 214.7483648), ("sscale", -214.7483649), ("uscale", -0.0000001)):
            with self.assertRaises(gen.CodecError):
                gen.encode_value(tr, ("1/10000000",), 32, value)
        self.assertEqual(gen.encode_value("sscale", ("1/10000000",), 32, 214.7483647), 0x7FFFFFFF)

    def test_uint_of_64_bits_with_the_top_bit_set_is_the_negative_integer_and_narrower_is_not(self):
        self.assertEqual(gen.decode_value("uint", (), 64, 2 ** 64 - 1), -1)
        self.assertEqual(gen.encode_value("uint", (), 64, -1), 2 ** 64 - 1)
        self.assertEqual(gen.decode_value("uint", (), 32, 2 ** 32 - 1), 2 ** 32 - 1)

    def test_twos_complement(self):
        self.assertEqual(gen.decode_value("twos", (), 8, 0xFF), -1)
        self.assertEqual(gen.decode_value("twos", (), 8, 0x7F), 127)
        self.assertEqual(gen.decode_value("twos", (), 16, 0x8000), -32768)
        self.assertEqual(gen.encode_value("twos", (), 16, -32768), 0x8000)

    def test_ascii_drops_trailing_nul_and_refuses_bytes_outside_printable_ascii(self):
        raw = int.from_bytes(b"Hi\0\0", "little")
        self.assertEqual(gen.decode_value("ascii", (), 32, raw), "Hi")
        self.assertEqual(gen.decode_value("ascii", (), 32, 0), "")
        self.assertEqual(gen.encode_value("ascii", (), 32, "Hi"), raw)
        for data in (b"a\0b\0", b"\x7f\0\0\0", b"\xc3\xa9\0\0"):
            with self.assertRaises(gen.CodecError):
                gen.decode_value("ascii", (), 32, int.from_bytes(data, "little"))
        with self.assertRaises(gen.CodecError):
            gen.encode_value("ascii", (), 32, "five!")

    def test_floats_are_ieee_little_endian(self):
        self.assertEqual(gen.decode_value("f32", (), 32, 0x3F800000), 1.0)
        self.assertEqual(gen.encode_value("f64", (), 64, -2.0), 0xC000000000000000)

    def test_geojson_is_lon_then_lat_and_null_geometry_without_a_position(self):
        self.assertEqual(gen.geojson_encode({"lat": 47.5, "lon": -8.0}),
                         '{"type":"Feature","geometry":{"type":"Point","coordinates":[-8,47.5]},"properties":{}}')
        self.assertEqual(gen.geojson_encode({"lat": 1.0}), '{"type":"Feature","geometry":null,"properties":{}}')


class CheckVectors(unittest.TestCase):
    ONE = Codec.ONE
    TWO = "fd040000000000" "2d0100" "0000803f"

    def vector(self, **changes):
        vec = {"name": "v", "from": "mavlink2", "to": "mavlink2", "input": self.ONE, "expect": self.ONE,
               "model": {"@kind": "one", "lat": "-33.8568", "mavlink.seq": "9"}}
        vec.update(changes)
        return json.dumps(vec)

    def run_check(self, *vectors):
        two = json.dumps({"name": "two", "from": "mavlink2", "to": "mavlink2", "input": self.TWO, "expect": self.TWO})
        return gen.check_vectors(load(PACK_TEXT), [("a.json", v) for v in vectors] + [("two.json", two)])

    def refusal(self, *vectors):
        with self.assertRaises(gen.GenError) as raised:
            self.run_check(*vectors)
        return str(raised.exception)

    def test_good_vectors_are_counted(self):
        self.assertEqual(self.run_check(self.vector()), 2)

    def test_expect_that_the_codec_does_not_produce_is_refused_with_the_file_name(self):
        message = self.refusal(self.vector(expect=self.ONE[:-2] + "fc"))
        self.assertTrue(message.startswith("packs/mavlink2/vectors/a.json: convert gives"), message)

    def test_wrong_kind_wrong_model_value_and_unknown_model_key_are_refused(self):
        self.assertIn("decoded kind one, vector says two", self.refusal(self.vector(model={"@kind": "two"})))
        self.assertIn("a.json: model mavlink.seq", self.refusal(self.vector(model={"mavlink.seq": "8"})))
        self.assertIn("a.json: model lat", self.refusal(self.vector(model={"lat": "-33.8569"})))
        self.assertIn("model mavlink.ratio is not decoded", self.refusal(self.vector(model={"mavlink.ratio": "1"})))

    def test_input_that_selects_no_kind_is_refused_with_the_file_name(self):
        self.assertEqual(self.refusal(self.vector(input="00" + self.ONE[2:])), "packs/mavlink2/vectors/a.json: no-kind")

    def test_kind_without_a_same_format_round_trip_is_refused(self):
        geo = self.vector(to="geojson", expect='{"type":"Feature","geometry":null,"properties":{}}')
        self.assertIn("kinds with no round-trip vector: ['one']", self.refusal(geo))

    def test_two_vectors_with_one_name_are_refused(self):
        self.assertIn("duplicate vector name v", self.refusal(self.vector(), self.vector()))


class FrameInvariants(unittest.TestCase):
    def refusal(self, old, new):
        self.assertIn(old, PACK_TEXT)
        with self.assertRaises(gen.GenError) as raised:
            gen.check_frame_invariants(load(PACK_TEXT.replace(old, new)))
        return str(raised.exception)

    def test_the_base_pack_holds(self):
        gen.check_frame_invariants(load(PACK_TEXT))

    def test_pack_without_the_common_when_on_stx_is_refused(self):
        self.assertIn("common `when` on STX missing", self.refusal("when 0:0:8 253", "when 0:0:8 254"))

    def test_kind_needs_exactly_one_msgid_when_and_one_len_when(self):
        message = "needs exactly one MSGID when and one LEN when"
        self.assertIn(message, self.refusal("when 0:8:8 15\n", ""))
        self.assertIn(message, self.refusal("when 0:8:8 15\n", "when 0:8:8 15\nwhen 0:16:8 0\n"))
        self.assertIn(message, self.refusal("when 0:56:24 300", "when 0:56:16 300"))

    def test_field_outside_the_payload_len_states_is_refused_with_its_line(self):
        # kind one has LEN 15: the payload is bits 80..200 and `delta` is its last byte.
        # With LEN 14 the payload ends at bit 192.
        self.assertEqual(self.refusal("when 0:8:8 15", "when 0:8:8 14"),
                         "pack.def:19: kind one: field bits 192..200 outside the payload")

    def test_field_that_is_not_byte_aligned_is_refused(self):
        self.assertEqual(self.refusal("field mavlink.delta 0:192:8 twos", "field mavlink.delta 0:193:7 twos"),
                         "pack.def:19: kind one: field not byte aligned")

    def test_overlapping_bit_ranges_are_refused(self):
        self.assertIn("kind one: bit ranges overlap at 168",
                      self.refusal("field mavlink.tag 0:176:16", "field mavlink.tag 0:168:16"))
        self.assertIn("bit ranges overlap", self.refusal("field mavlink.seq 0:32:8", "field mavlink.seq 0:56:8"))

    def test_two_kinds_with_the_same_when_set_are_refused(self):
        text = self.refusal("when 0:56:24 301\nwhen 0:8:8 4", "when 0:8:8 15\nwhen 0:56:24 300")
        self.assertEqual(text, "pack.def:21: kind two: the same `when` set as kind one")

    def test_requires_must_name_a_key_the_kind_itself_maps(self):
        self.assertIn("requires mavlink.seq which the kind does not map",
                      self.refusal("requires mavlink.count", "requires mavlink.seq"))
        self.assertIn("requires lat which the kind does not map",
                      self.refusal("requires mavlink.ratio", "requires lat"))
        self.assertIn("kind one: no requires", self.refusal("requires mavlink.count\n", ""))

    def test_key_mapped_twice_in_one_kind_is_refused(self):
        self.assertIn("duplicate-field mavlink.seq",
                      self.refusal("field mavlink.delta 0:192:8 twos", "field mavlink.seq 0:192:8 uint"))

    def test_lines_and_layouts_the_codec_does_not_read_are_refused(self):
        self.assertIn("only `when` and `field` lines", self.refusal("when 0:0:8 253", "when 0:0:8 253\nconst 0:16:8 0"))
        self.assertIn("transform or option outside", self.refusal("0:176:16 ascii", "0:176:16 ascii trim"))
        self.assertIn("transform or option outside", self.refusal("0:80:32 f32", "0:80:32 linscale:1:2"))
        self.assertIn("bit_order lsb", self.refusal("bit_order lsb", "bit_order msb"))
        self.assertIn("word_bytes 1", self.refusal("word_bytes 1", "word_bytes 2"))


if __name__ == "__main__":
    unittest.main()


class Sentinels(unittest.TestCase):
    """`invalid` as `absent` raw values (engine-spec 0.9)."""

    def sent(self, type_text, invalid):
        return gen.field_sentinels(field(type_text, invalid=invalid))

    def test_limits_are_the_raw_bits_of_the_type(self):
        self.assertEqual(self.sent("int32_t", "INT32_MAX"), [(2147483647,)])
        self.assertEqual(self.sent("uint16_t", "UINT16_MAX"), [(65535,)])
        self.assertEqual(self.sent("int8_t", "-1"), [(255,)])
        self.assertEqual(self.sent("int16_t", "-1000"), [(64536,)])

    def test_floats_take_their_ieee_bits(self):
        self.assertEqual(self.sent("float", "NaN"), [(0x7FC00000, 0xFFC00000)])
        self.assertEqual(self.sent("double", "NAN"), [(0x7FF8000000000000, 0xFFF8000000000000)])
        self.assertEqual(self.sent("float", "-1000"), [(struct.unpack("<I", struct.pack("<f", -1000.0))[0],)])
        self.assertEqual(self.sent("float", "UINT16_MAX"), [(struct.unpack("<I", struct.pack("<f", 65535.0))[0],)])

    def test_array_forms(self):
        self.assertEqual(self.sent("uint16_t[3]", "[UINT16_MAX]"), [(65535,)] * 3)
        self.assertEqual(self.sent("uint8_t[4]", "[0,,7]"), [(0,), (), (7,), ()])
        self.assertEqual(self.sent("float[2]", "[NaN:]"), [(0x7FC00000, 0xFFC00000)] * 2)

    def test_what_cannot_be_stated(self):
        for type_text, invalid in (("uint8_t", "MAV_STATE_UNKNOWN"), ("char[12]", "[0]"),
                                   ("float[3]", "[0:]"), ("uint8_t", "300"), ("uint8_t[2]", "7")):
            with self.assertRaises(gen.Unstatable, msg=(type_text, invalid)):
                self.sent(type_text, invalid)
        self.assertEqual(self.sent("char[4]", "0"), [(0,)])

    def test_a_sentinel_decodes_to_no_key_and_an_absent_key_encodes_the_first(self):
        model = gtcheck.Model()
        model.add(gen.CORE_STAND_IN, "<core stand-in>")
        model.add(open(os.path.join(EXPECTED, "model", "mavlink.def"), encoding="utf-8").read(), "mavlink.def")
        pack = gtcheck.load_pack(open(os.path.join(EXPECTED, "packs", "mavlink2", "pack.def"),
                                      encoding="utf-8").read(), model, "pack.def")
        vec = json.load(open(os.path.join(EXPECTED, "packs", "mavlink2", "vectors",
                                          "sn-00246-adsb_vehicle.json"), encoding="utf-8"))
        name, entity = gen.engine_decode(pack, bytes.fromhex(vec["input"]))
        self.assertNotIn("lat", entity)
        self.assertNotIn("mavlink.heading_cdeg", entity)
        self.assertEqual(gen.engine_encode(pack, name, entity).hex(), vec["input"])


class Times(unittest.TestCase):
    """Fields bound to core time_ms (engine-spec 0.15 uiscale)."""

    def setUp(self):
        with open(os.path.join(EXPECTED, "packs", "mavlink2", "pack.def"), encoding="utf-8") as fh:
            self.text = fh.read()

    def test_a_unix_time_in_microseconds_is_time_ms_and_a_boot_time_stays_raw(self):
        kind = self.text[self.text.index("kind      system_time"):]
        kind = kind[:kind.index("\n\n")]
        self.assertIn("field     time_ms 0:80:64 uiscale:1/1000", kind)
        self.assertIn("mavlink.time_boot_ms", kind)

    def test_the_old_raw_key_stays_declared(self):
        with open(os.path.join(EXPECTED, "model", "mavlink.def"), encoding="utf-8") as fh:
            self.assertIn("key  time_unix_usec_us  int  us", fh.read())

    def test_rounding_vectors_are_whole_milliseconds(self):
        vdir = os.path.join(EXPECTED, "packs", "mavlink2", "vectors")
        vec = json.load(open(os.path.join(vdir, "tm-01-system_time-rounding.json"), encoding="utf-8"))
        self.assertEqual(vec["model"]["time_ms"], "1700000000001")
        self.assertEqual(struct.unpack("<Q", bytes.fromhex(vec["expect"])[10:18])[0], 1700000000001000)

    def test_uiscale_codec_is_exact(self):
        self.assertEqual(gen.decode_value("uiscale", ["1/1000"], 64, 1700000000000500), 1700000000001)
        self.assertEqual(gen.decode_value("uiscale", ["1000", "1546300800000"], 32, 1), 1546300801000)
        self.assertEqual(gen.encode_value("uiscale", ["1000", "1546300800000"], 32, 1546300801000), 1)
