"""Tests of tools/gen/xsd2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_xsd2pack*.py'

The fixture under fixtures/xsd2pack/input is a synthetic schema set of two
files (`fieldnet`), a two-module model, a second xml format with one vector, and
a names file with one pinned name. fixtures/xsd2pack/expected is the tree the
generator writes for it.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import support
import genio
import gtcheck
import xsd2pack as x

FIXTURE = os.path.join(support.FIXTURES, "xsd2pack")

# A schema file around a body of declarations. The opening tag is line 1, so
# the first line of a body is line 2.
SCHEMA_HEAD = ('<xs:schema xmlns:t="urn:example:t" xmlns:xs="http://www.w3.org/2001/XMLSchema" '
               'targetNamespace="urn:example:t" elementFormDefault="qualified">'
               '<!-- Distribution Statement A. Approved for public release: distribution is unlimited. -->\n')


def schema_text(body):
    return SCHEMA_HEAD + body + "\n</xs:schema>\n"


def schema_of(body):
    schema = x.Schema()
    schema.read_bytes(schema_text(body).encode("utf-8"), "t.xsd", {})
    return schema


def simple_type(name, base, facets):
    return '<xs:simpleType name="%s"><xs:restriction base="%s">%s</xs:restriction></xs:simpleType>' % (
        name, base, "".join('<xs:%s value="%s"/>' % f for f in facets))


def walk_root(schema, max_depth=x.MAX_DEPTH, max_nest=x.MAX_DEPTH):
    return x.Walker(schema, max_depth, max_nest).walk(schema.elements["Root"])


def outline(items):
    """Lines as nested tuples: a leaf is its locator, a group is (path, [lines])."""
    return [i.locator if isinstance(i, x.Leaf) else (i.path, outline(i.items)) for i in items]


class Workspace(unittest.TestCase):
    """A temporary directory with a copy of the fixture input in `in/`."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="xsd2pack-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        support.copy_tree(os.path.join(FIXTURE, "input"), self.path("in"))
        self.out = self.path("out")
        os.makedirs(self.path("out", "names"))
        shutil.copy(self.path("in", "names", "fieldnet.json"), self.path("out", "names", "fieldnet.json"))

    def path(self, *parts):
        return os.path.join(self.work, *parts)

    def fixture_argv(self, *extra, names_file=None):
        """The command line of a real run, on the fixture."""
        return [
            "--xsd", self.path("in", "schema", "fieldnet-messages.xsd"), self.path("in", "schema", "fieldnet-types.xsd"),
            "--alias", "fieldnet-types-v1.xsd=fieldnet-types.xsd",
            "--format", "fieldnet", "--module", "fieldnet", "--out", self.out,
            "--model-dir", self.path("in", "model"),
            "--title", "Fieldnet synthetic test schema 1.0 message definitions",
            "--source", "A second source line, given on the command line",
            "--message-type-suffix", "MT", "--name-drop", "MessageData",
            "--sample", "MessageHeader/Mode/#text=SIMULATION",
            "--map", "StationReport:MessageData/StationID/UUID/#text=uid",
            "--map", "StationReport:MessageData/ObservedAt/#text=time_ms",
            "--map", "StationReport:MessageData/Kinematics/NorthSpeed/#text=track.vel_north_ms",
            "--default-kind", "StationReport", "--default-requires", "uid",
            "--cross", "%s=%s:input" % (self.path("in", "packs", "note-xml", "pack.def"),
                                        self.path("in", "packs", "note-xml", "vectors", "01-note.json")),
            "--names-file", names_file or self.path("out", "names", "fieldnet.json"),
        ] + list(extra)

    def run_fixture(self, *extra, **kw):
        return support.run_main(x.main, self.fixture_argv(*extra, **kw))

    def run_schema(self, body, *extra, raw=None):
        """Run the generator on a one-file schema with `Root` as the only message."""
        with open(self.path("s.xsd"), "w", encoding="utf-8") as fh:
            fh.write(schema_text(body) if raw is None else raw)
        return support.run_main(x.main, [
            "--xsd", self.path("s.xsd"), "--format", "demo", "--module", "demo", "--out", self.out,
            "--model-dir", self.path("in", "model"), "--title", "Demo", "--message", "Root",
            "--names-file", self.path("out", "names", "demo.json")] + list(extra))

    def read_out(self, *parts):
        with open(self.path("out", *parts), encoding="utf-8") as fh:
            return fh.read()


class GoldenTest(Workspace):
    def test_fixture_output_matches_the_expected_tree(self):
        status, _, err = self.run_fixture()
        self.assertEqual((status, err), (0, ""))
        support.assert_same_tree(self, os.path.join(FIXTURE, "expected"), self.out)

    def test_second_run_over_its_own_output_changes_nothing(self):
        self.assertEqual(self.run_fixture()[0], 0)
        first = support.tree(self.out)
        self.assertEqual(self.run_fixture()[0], 0)
        self.assertEqual(support.tree(self.out), first)

    def test_summary_on_stdout_counts_what_was_written(self):
        status, out, _ = self.run_fixture()
        summary = json.loads(out)
        self.assertEqual(status, 0)
        self.assertEqual(summary["kinds"], 2)
        self.assertEqual(summary["messages_without_kind"], ["Heartbeat"])
        self.assertEqual(summary["default_kind"], "station_report")
        # one name was pinned before the run, so one identity fewer is new
        self.assertEqual(summary["names_added"], summary["module_keys"] + summary["module_lists"] - 1)
        self.assertEqual(summary["bytes"]["pack.def"], os.path.getsize(self.path("out", "packs", "fieldnet", "pack.def")))

    def test_a_vector_of_an_earlier_run_that_is_no_longer_written_is_removed(self):
        stale = self.path("out", "packs", "fieldnet", "vectors", "gen-9-old_kind-roundtrip.json")
        kept = self.path("out", "packs", "fieldnet", "vectors", "01-hand-written.json")
        os.makedirs(os.path.dirname(stale))
        with open(stale, "w") as fh:
            fh.write("{}\n")
        self.assertEqual(self.run_fixture()[0], 0)
        self.assertFalse(os.path.exists(stale))
        # a vector that does not carry the generator's prefix is replayed, not removed
        shutil.copy(self.path("out", "packs", "fieldnet", "vectors", "gen-1-station_report-roundtrip.json"), kept)
        status, _, err = self.run_fixture()
        self.assertEqual(status, 1)
        self.assertIn("vector name gen-station_report-roundtrip twice", err)
        self.assertTrue(os.path.exists(kept))

    def test_output_does_not_depend_on_the_hash_seed(self):
        trees = []
        for seed in ("1", "2"):
            shutil.rmtree(self.out)
            os.makedirs(self.path("out", "names"))
            shutil.copy(self.path("in", "names", "fieldnet.json"), self.path("out", "names", "fieldnet.json"))
            done = subprocess.run([sys.executable, os.path.join(support.GEN, "xsd2pack.py")] + self.fixture_argv(),
                                  env=dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1"),
                                  capture_output=True)
            self.assertEqual(done.returncode, 0, done.stderr.decode())
            trees.append(support.tree(self.out))
        self.assertEqual(trees[0], trees[1])


class CheckModeTest(Workspace):
    def test_check_on_fresh_output_passes_and_writes_nothing(self):
        self.assertEqual(self.run_fixture()[0], 0)
        before = support.tree(self.work)
        status, out, err = self.run_fixture("--check")
        self.assertEqual(status, 0, err)
        self.assertIn("--check: ok", err)
        self.assertEqual(out, "")
        self.assertEqual(support.tree(self.work), before)

    def test_check_names_a_changed_file_and_leaves_the_tree_alone(self):
        self.assertEqual(self.run_fixture()[0], 0)
        target = self.path("out", "packs", "fieldnet", "pack.def")
        with open(target, "rb") as fh:
            data = fh.read()
        with open(target, "wb") as fh:
            fh.write(data.replace(b"kind      sensor_status", b"kind      sensor_statuz"))
        before = support.tree(self.work)
        status, _, err = self.run_fixture("--check")
        self.assertEqual(status, 1)
        self.assertIn("packs/fieldnet/pack.def differs at line", err)
        self.assertEqual(support.tree(self.work), before)

    def test_check_on_an_empty_directory_reports_every_file_and_creates_none(self):
        shutil.rmtree(self.out)
        status, _, err = self.run_fixture("--check")
        self.assertEqual(status, 1)
        for rel in ("model/fieldnet.def", "packs/fieldnet/pack.def", "packs/fieldnet/pack.md",
                    "packs/fieldnet/vectors/gen-1-station_report-roundtrip.json",
                    "packs/note-xml/vectors/gen-note-xml-to-fieldnet.json", "names/fieldnet.json"):
            self.assertIn("%s is missing" % rel, err)
        self.assertFalse(os.path.exists(self.out))

    def test_check_reports_a_stale_generated_vector(self):
        self.assertEqual(self.run_fixture()[0], 0)
        stale = self.path("out", "packs", "fieldnet", "vectors", "gen-9-old_kind-roundtrip.json")
        shutil.copy(self.path("out", "packs", "fieldnet", "vectors", "gen-2-sensor_status-roundtrip.json"), stale)
        status, _, err = self.run_fixture("--check")
        self.assertEqual(status, 1)
        self.assertIn("gen-9-old_kind-roundtrip.json is not written by the generator and would be removed", err)
        self.assertTrue(os.path.exists(stale))

    def test_check_covers_a_names_file_outside_the_output_directory(self):
        names = self.path("elsewhere", "fieldnet.json")
        os.makedirs(os.path.dirname(names))
        shutil.copy(self.path("in", "names", "fieldnet.json"), names)
        self.assertEqual(self.run_fixture(names_file=names)[0], 0)
        self.assertEqual(self.run_fixture("--check", names_file=names)[0], 0)
        with open(names, encoding="utf-8") as fh:
            pinned = json.load(fh)
        del pinned["@at int"]
        with open(names, "w", encoding="utf-8") as fh:
            json.dump(pinned, fh, indent=1, sort_keys=True)
            fh.write("\n")
        status, _, err = self.run_fixture("--check", names_file=names)
        self.assertEqual(status, 1)
        self.assertIn("fieldnet.json differs", err)
        with open(names, encoding="utf-8") as fh:
            self.assertNotIn("@at int", json.load(fh))


class GeneratedPackTest(Workspace):
    """The golden file is not the only witness: what was written loads in
    gtcheck and holds the facts the fixture was built to produce."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.run_fixture()[0], 0)
        self.model = gtcheck.Model().load_dir(self.path("out", "model"))
        self.pack = gtcheck.load_pack_file(self.path("out", "packs", "fieldnet", "pack.def"), self.model)

    def lines_of(self, kind_name):
        kind = next(k for k in self.pack.kinds if k.name == kind_name)
        return {(n.key, n.loc): n for n in gtcheck.walk(self.pack.common + kind.lines)}

    def test_one_kind_per_message_with_its_root_and_the_default_kind_last(self):
        self.assertEqual([(k.name, k.root) for k in self.pack.kinds],
                         [("sensor_status", "SensorStatus"), ("station_report", "StationReport")])
        self.assertIsNone(self.pack.root)
        self.assertEqual(self.pack.kinds[-1].requires, ["uid"])
        self.assertEqual(self.pack.kinds[0].requires, ["fieldnet.sensor_id_uuid"])
        self.assertEqual(self.pack.uses, ["core", "fieldnet", "track"])

    def test_leading_lines_every_message_shares_are_common_lines(self):
        self.assertEqual([(n.key, n.loc, n.tr) for n in self.pack.common], [
            ("fieldnet.schema_version", "@schemaVersion", "string"),
            ("fieldnet.message_header_timestamp", "MessageHeader/Timestamp/#text", "iso8601_ms"),
            ("fieldnet.message_header_mode", "MessageHeader/Mode/#text", "string"),
            ("fieldnet.message_header_sequence", "MessageHeader/Sequence/#text", "int")])

    def test_transform_follows_the_schema_type(self):
        station = self.lines_of("station_report")
        for key, loc, tr in [
                ("fieldnet.observed_at", "MessageData/ObservedAt/#text", "iso8601_ms"),      # dateTime with a Z pattern
                ("fieldnet.last_contact", "MessageData/LastContact/#text", "string"),        # dateTime with none
                ("fieldnet.position_latitude", "MessageData/Position/Latitude/#text", "float"),      # decimal
                ("fieldnet.position_altitude", "MessageData/Position/Altitude/#text", "float"),      # simple content
                ("fieldnet.position_altitude_datum", "MessageData/Position/Altitude/@datum", "string"),
                ("fieldnet.channel", "MessageData/Channel/#text", "int"),
                ("fieldnet.active", "MessageData/Active/#text", "string"),                   # boolean
                ("fieldnet.revision", "MessageData/@revision", "int")]:
            self.assertEqual(station[(key, loc)].tr, tr, key)

    def test_a_shared_key_and_the_raw_key_stand_on_one_locator_shared_first(self):
        kind = self.pack.kinds[-1]
        at = [n.key for n in kind.lines if n.d == "field" and n.loc == "MessageData/StationID/UUID/#text"]
        self.assertEqual(at, ["uid", "fieldnet.station_id_uuid"])

    def test_a_repeated_element_is_a_group_with_item_relative_lines(self):
        station = self.lines_of("station_report")
        reading = station[("fieldnet.reading", "MessageData/Reading")]
        self.assertEqual(reading.d, "group")
        self.assertEqual([(n.d, n.key, n.loc) for n in reading.body], [
            ("field", "fieldnet.quantity", "@quantity"), ("field", "fieldnet.unit", "@unit"),
            ("field", "fieldnet.value", "Value/#text"),
            ("group", "fieldnet.flag", "Flag"), ("group", "fieldnet.sample", "Sample")])
        # an item of simple type is its own text
        self.assertEqual([(n.key, n.loc) for n in reading.body[3].body], [("fieldnet.item", "#text")])
        self.assertEqual(self.model.type_of("fieldnet.reading"), "list")

    def test_names_settle_collisions_and_keep_the_pinned_name(self):
        sensor, station = self.lines_of("sensor_status"), self.lines_of("station_report")
        # an element and an attribute of one name under one parent
        self.assertIn(("fieldnet.site_name", "MessageData/Site/Name/#text"), sensor)
        self.assertIn(("fieldnet.site_name_attr", "MessageData/Site/@Name"), sensor)
        # one locator with two model types across kinds
        self.assertIn(("fieldnet.level_string", "MessageData/Level/#text"), sensor)
        self.assertIn(("fieldnet.level_int", "MessageData/Level/#text"), station)
        # the name the names file pinned before the run, not `comment`
        self.assertIn(("fieldnet.station_comment", "MessageData/Comment/#text"), station)
        self.assertNotIn("comment", self.model.modules["fieldnet"].keys)
        self.assertTrue(all(len(k) <= x.MAX_KEY_LEN for k in self.model.modules["fieldnet"].keys))

    def test_declined_places_are_counted_in_pack_md_with_their_reason(self):
        md = self.read_out("packs", "fieldnet", "pack.md")
        for reason, places in [(x.R_ANY, 2), (x.R_ANYATTR, 1), (x.R_CHOICE, 1), (x.R_REPEAT_NOTHING, 1),
                               (x.R_MIXED, 1), (x.R_ABSTRACT, 1), (x.R_RECURSE, 1), (x.R_ANYTYPE, 1),
                               (x.R_EMPTY, 1), (x.R_PROHIBITED, 1), (x.R_REPEAT_GROUP, 1), (x.R_SIBLING, 1)]:
            self.assertIn("| %s | %d |" % (reason, places), md)
        self.assertIn("No kind is written for 1 message in which nothing can be mapped (`Heartbeat`: xs:any wildcard)", md)

    def test_every_sample_in_the_vectors_is_inside_the_bounds_of_its_type(self):
        vec = json.loads(self.read_out("packs", "fieldnet", "vectors", "gen-1-station_report-roundtrip.json"))
        root = x.xml_parse(vec["input"])
        text = lambda loc: x.xml_get(root, "MessageData/" + loc)
        self.assertTrue(-90 <= float(text("Position/Latitude/#text")) <= 90)
        self.assertTrue(0 <= float(text("Kinematics/Heading/#text")) < 360)
        self.assertTrue(-3.2 < float(text("Kinematics/Bearing/#text")) < 3.2)
        self.assertTrue(1 <= int(text("Priority/#text")) <= 5)
        self.assertTrue(10 < int(text("Channel/#text")) < 20)
        self.assertRegex(text("StationID/UUID/#text"), r"\A[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
        self.assertEqual(x.xml_get(root, "MessageHeader/Mode/#text"), "SIMULATION")     # --sample
        # the enumeration's first value holds characters a vector must not hold; the next one is used
        self.assertEqual(text("Reading/@quantity"), "TEMPERATURE")
        self.assertEqual(vec["model"]["time_ms"], str(x.iso8601_to_ms(text("ObservedAt/#text"))))
        # of a mapped choice only the first branch is present
        self.assertIsNotNone(text("Callsign/#text"))
        self.assertIsNone(text("Serial/#text"))

    def test_cross_vector_encodes_the_other_formats_entity_as_the_default_kind(self):
        vec = json.loads(self.read_out("packs", "note-xml", "vectors", "gen-note-xml-to-fieldnet.json"))
        self.assertEqual((vec["from"], vec["to"]), ("note-xml", "fieldnet"))
        self.assertEqual(vec["model"], {"uid": "00000000-0000-4000-8000-000000000042",
                                        "time_ms": "1772600767250", "track.vel_north_ms": "-2.5"})
        self.assertEqual(vec["expect"], (
            "<StationReport><MessageData><StationID><UUID>00000000-0000-4000-8000-000000000042</UUID></StationID>"
            "<ObservedAt>2026-03-04T05:06:07.250Z</ObservedAt>"
            "<Kinematics><NorthSpeed>-2.5</NorthSpeed></Kinematics></MessageData></StationReport>"))

    def test_self_check_refuses_a_vector_whose_expect_is_not_what_encode_writes(self):
        rel = "packs/fieldnet/vectors/gen-2-sensor_status-roundtrip.json"
        vec = json.loads(self.read_out(*rel.split("/")))
        vec["expect"] = vec["expect"].replace("<Mode>SIMULATION</Mode>", "<Mode>LIVE</Mode>")
        with open(self.path("out", *rel.split("/")), "w", encoding="utf-8") as fh:
            json.dump(vec, fh)
        with self.assertRaises(x.GenError) as caught:
            x.self_check(genio.Output(self.out), "fieldnet", "fieldnet")
        self.assertEqual((caught.exception.file, caught.exception.message), (rel, "re-encoded bytes differ from expect"))

    def test_self_check_refuses_a_vector_that_holds_a_value_no_line_carries(self):
        rel = "packs/fieldnet/vectors/gen-2-sensor_status-roundtrip.json"
        vec = json.loads(self.read_out(*rel.split("/")))
        # decode drops an unmapped child element (0.1.1 ruling 6), so the round trip still gives `expect`
        vec["input"] = vec["input"].replace("</MessageHeader>", "<Unmapped>1</Unmapped></MessageHeader>")
        with open(self.path("out", *rel.split("/")), "w", encoding="utf-8") as fh:
            json.dump(vec, fh)
        with self.assertRaises(x.GenError) as caught:
            x.self_check(genio.Output(self.out), "fieldnet", "fieldnet")
        self.assertRegex(caught.exception.message, r"\A\d+ values in the document, \d+ carried\Z")

    def test_self_check_refuses_a_kind_with_no_vector(self):
        os.remove(self.path("out", "packs", "fieldnet", "vectors", "gen-2-sensor_status-roundtrip.json"))
        with self.assertRaises(x.GenError) as caught:
            x.self_check(genio.Output(self.out), "fieldnet", "fieldnet")
        self.assertIn("1 kinds have no vector, first sensor_status", str(caught.exception))


class SmallSchemaRunTest(Workspace):
    def test_leaf_bound_to_a_shared_key_is_never_a_common_line(self):
        # `Id` leads both messages and would be the common line; bound to `uid` in one of them
        # it is a line of each kind, because a common line would bind the key in every kind
        body = ('<xs:element name="Root" type="t:R"/><xs:element name="Other" type="t:O"/>\n'
                '<xs:complexType name="R"><xs:sequence><xs:element name="Id" type="xs:string"/>'
                '<xs:element name="A" type="xs:string"/></xs:sequence></xs:complexType>\n'
                '<xs:complexType name="O"><xs:sequence><xs:element name="Id" type="xs:string"/>'
                '<xs:element name="B" type="xs:string"/></xs:sequence></xs:complexType>')
        self.assertEqual(self.run_schema(body, "--message", "Other")[0], 0)
        pack = gtcheck.load_pack_file(self.path("out", "packs", "demo", "pack.def"),
                                      gtcheck.Model().load_dir(self.path("out", "model")))
        self.assertEqual([n.key for n in pack.common], ["demo.id"])
        self.assertEqual(self.run_schema(body, "--message", "Other", "--map", "Root:Id/#text=uid")[0], 0)
        pack = gtcheck.load_pack_file(self.path("out", "packs", "demo", "pack.def"),
                                      gtcheck.Model().load_dir(self.path("out", "model")))
        self.assertEqual(pack.common, [])
        self.assertEqual([[n.key for n in k.lines] for k in pack.kinds],
                         [["uid", "demo.id", "demo.a"], ["demo.id", "demo.b"]])


class RefusalTest(Workspace):
    def assert_refused(self, result, *fragments):
        status, out, err = result
        self.assertEqual(status, 1, err)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("xsd2pack: "), err)
        self.assertEqual(err.count("\n"), 1, err)
        for fragment in fragments:
            self.assertIn(fragment, err)

    def test_schema_without_the_distribution_statement_is_refused_and_named(self):
        target = self.path("in", "schema", "fieldnet-types.xsd")
        with open(target, encoding="utf-8") as fh:
            text = fh.read()
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(text.replace("Distribution Statement A. Approved for public release: distribution is unlimited.", ""))
        self.assert_refused(self.run_fixture(), target + ": the file header does not state Distribution Statement A")
        self.assertFalse(os.path.exists(self.path("out", "packs")))

    def test_statement_beyond_the_first_6000_bytes_does_not_count(self):
        padding = "<!-- %s -->\n" % ("x" * 6000)
        raw = schema_text('<xs:element name="Root" type="xs:string"/>').replace(
            "<!-- Distribution", padding + "<!-- Distribution")
        self.assert_refused(self.run_schema("", raw=raw), "does not state Distribution Statement A")

    def test_malformed_schema_reports_file_and_line(self):
        body = '<xs:element name="Root" type="t:R"/>\n<xs:complexType name="R">\n</xs:complexTyp>'
        self.assert_refused(self.run_schema(body), "s.xsd:4: not well-formed XML: mismatched tag")

    def test_unknown_element_type_reports_the_line_of_the_element(self):
        body = ('<xs:element name="Root" type="t:R"/>\n'
                '<xs:complexType name="R"><xs:sequence>\n'
                '  <xs:element name="Fine" type="xs:string"/>\n'
                '  <xs:element name="Broken" type="t:Missing"/>\n'
                '</xs:sequence></xs:complexType>')
        self.assert_refused(self.run_schema(body), "s.xsd:5: type Missing of element Broken is not defined")

    def test_unknown_attribute_type_reports_the_line_of_the_attribute(self):
        body = ('<xs:element name="Root" type="t:R"/>\n'
                '<xs:complexType name="R">\n'
                '  <xs:attribute name="a" type="t:Missing"/>\n'
                '</xs:complexType>')
        self.assert_refused(self.run_schema(body), "s.xsd:4: simple type Missing is not defined")

    def test_unknown_restriction_base_reports_the_line_of_the_simple_type(self):
        body = ('<xs:element name="Root" type="t:R"/>\n'
                '<xs:complexType name="R"><xs:sequence><xs:element name="E" type="t:Short"/></xs:sequence></xs:complexType>\n'
                '<xs:simpleType name="Short">\n'
                '  <xs:restriction base="t:Missing"/>\n'
                '</xs:simpleType>')
        self.assert_refused(self.run_schema(body), "s.xsd:4: simple type Missing is not defined")

    def test_name_in_a_namespace_no_file_defines_reports_its_line(self):
        body = '<xs:element name="Root" type="t:R"/>\n<xs:complexType name="R">\n<xs:attribute name="a" type="other:T"/>\n</xs:complexType>'
        self.assert_refused(self.run_schema(body), "s.xsd:4: 'other:T' is in namespace None")

    def test_include_that_no_given_file_satisfies_reports_its_line(self):
        body = '<xs:include schemaLocation="absent.xsd"/>\n<xs:element name="Root" type="xs:string"/>'
        self.assert_refused(self.run_schema(body), "s.xsd:2: xs:include of absent.xsd is not among the files given (use --alias)")

    def test_message_that_is_no_global_element_is_refused(self):
        self.assert_refused(self.run_schema('<xs:element name="Other" type="xs:string"/>'),
                            "--message Root: no such global element")

    def test_message_set_in_which_nothing_maps_is_refused(self):
        self.assert_refused(self.run_schema('<xs:element name="Root" type="xs:string"/>'),
                            "nothing can be mapped in any of the 1 messages selected")

    def test_map_of_a_key_whose_type_differs_from_the_leaf_is_refused(self):
        self.assert_refused(self.run_fixture("--map", "StationReport:MessageData/Level/#text=uid"),
                            "key is string, the leaf yields int")

    def test_map_to_a_place_that_is_not_a_mapped_leaf_is_refused(self):
        self.assert_refused(self.run_fixture("--map", "StationReport:MessageData/Nowhere/#text=uid"),
                            "message StationReport has no mapped leaf at MessageData/Nowhere/#text")

    def test_map_of_a_degree_key_onto_a_radian_leaf_is_refused(self):
        self.assert_refused(self.run_fixture("--map", "StationReport:MessageData/Kinematics/Bearing/#text=course"),
                            "the schema states radians and the key is in degrees")

    def test_sample_that_is_not_a_value_of_the_enumeration_is_refused(self):
        self.assert_refused(self.run_fixture("--sample", "MessageHeader/Mode/#text=OFFLINE"),
                            "--sample MessageHeader/Mode/#text=OFFLINE: not a value of ModeEnum")

    def test_default_requires_must_be_bound_in_the_default_kind(self):
        self.assert_refused(self.run_fixture("--default-requires", "speed_ms"),
                            "--default-requires: every key must be bound in StationReport by a --map")

    def test_pinned_name_given_to_two_places_is_refused(self):
        with open(self.path("out", "names", "fieldnet.json"), "w", encoding="utf-8") as fh:
            json.dump({"MessageData/Comment/#text string": "same", "MessageData/Plate/#text string": "same"}, fh)
        self.assert_refused(self.run_fixture(), "pinned name same is given to two different places")

    def test_names_file_that_is_not_json_reports_file_and_line(self):
        with open(self.path("out", "names", "fieldnet.json"), "w", encoding="utf-8") as fh:
            fh.write('{\n "a": \n')
        self.assert_refused(self.run_fixture(), "fieldnet.json:3: not JSON")

    def test_missing_model_module_is_one_line_naming_the_file(self):
        os.remove(self.path("in", "model", "track.def"))
        self.assert_refused(self.run_fixture(), "track.def: No such file or directory")

    def test_cross_document_with_a_root_attribute_its_pack_does_not_map_is_refused(self):
        vector = self.path("in", "packs", "note-xml", "vectors", "01-note.json")
        with open(vector, encoding="utf-8") as fh:
            vec = json.load(fh)
        vec["input"] = vec["input"].replace("<note ", '<note extra="1" ')
        with open(vector, "w", encoding="utf-8") as fh:
            json.dump(vec, fh)
        self.assert_refused(self.run_fixture(), "root attributes its pack does not map (extra)")

    def test_cross_pack_that_does_not_load_is_refused_with_its_line(self):
        with open(self.path("in", "packs", "note-xml", "pack.def"), "a", encoding="utf-8") as fh:
            fh.write("field   nosuchkey   @n   string\n")
        self.assert_refused(self.run_fixture(), "pack.def:14: undeclared-key")

    def test_usage_errors_exit_2(self):
        for extra in (["--map", "no-equals-sign"], ["--cross", "pack.def=vector.json:neither"],
                      ["--sample", "novalue"], ["--alias", "nofile"]):
            status, _, err = self.run_fixture(*extra)
            self.assertEqual(status, 2, extra)
            self.assertIn("usage:", err)

    def test_help_states_inputs_outputs_and_guarantees(self):
        status, out, _ = support.run_main(x.main, ["--help"])
        self.assertEqual(status, 0)
        for text in ("Reads:", "Writes, under --out:", "Guarantees:", "Exit status:", "--check"):
            self.assertIn(text, out)


class NamesTest(unittest.TestCase):
    def test_snake_puts_an_underscore_before_a_capital_that_follows_a_lowercase_letter_or_digit(self):
        self.assertEqual(x.snake("KinematicsTimeStamp"), "kinematics_time_stamp")
        self.assertEqual(x.snake("EntityID"), "entity_id")
        self.assertEqual(x.snake("UUID"), "uuid")
        self.assertEqual(x.snake("IPv4Address"), "ipv4_address")
        self.assertEqual(x.snake("schemaVersion"), "schema_version")

    def test_snake_turns_every_run_of_other_characters_into_one_underscore(self):
        self.assertEqual(x.snake("A-B.c"), "a_b_c")
        self.assertEqual(x.snake("__x__"), "x")
        self.assertEqual(x.snake("-"), "")

    def test_base_name_joins_the_path_and_leaves_out_text_and_the_dropped_wrapper(self):
        self.assertEqual(x.base_name("MessageData/EntityID/UUID/#text", ("MessageData",)), "entity_id_uuid")
        self.assertEqual(x.base_name("MessageData/EntityID/UUID/#text"), "message_data_entity_id_uuid")
        self.assertEqual(x.base_name("Site/@Name"), "site_name")
        self.assertEqual(x.base_name("@schemaVersion"), "schema_version")
        # the wrapper is kept when it is the whole path, and only a leading one is dropped
        self.assertEqual(x.base_name("MessageData/#text", ("MessageData",)), "message_data")
        self.assertEqual(x.base_name("A/MessageData/#text", ("MessageData",)), "a_message_data")

    def test_base_name_of_the_text_of_an_item_is_item(self):
        self.assertEqual(x.base_name("#text"), "item")

    def test_base_name_longer_than_the_limit_keeps_first_part_last_two_parts_and_a_hash(self):
        middle = "/".join("VeryLongElementNameNumber%d" % i for i in range(5))
        locator = "Alpha/%s/@lastAttr" % middle
        digest = hashlib.sha1(locator.encode()).hexdigest()[:8]
        self.assertEqual(x.base_name(locator), "alpha_very_long_element_name_number4_last_attr_" + digest)
        # the same first and last parts with another middle: the hash keeps the names apart
        other = x.base_name("Alpha/%s/Extra/VeryLongElementNameNumber4/@lastAttr" % middle)
        self.assertTrue(other.startswith("alpha_very_long_element_name_number4_last_attr_"))
        self.assertNotEqual(other, x.base_name(locator))

    def test_base_name_never_passes_the_limit(self):
        locator = "/".join(["A" + "b" * 70] * 4) + "/#text"
        name = x.base_name(locator)
        self.assertEqual(len(name), x.MAX_KEY_LEN)
        self.assertTrue(name.endswith("_" + hashlib.sha1(locator.encode()).hexdigest()[:8]))

    def test_two_locators_that_sanitize_to_one_key_get_distinct_keys_from_their_identity(self):
        a, b = ("A/b/#text", "int"), ("a_b/#text", "string")
        names = x.assign_names([a, b], {})
        self.assertEqual(names[a], "a_b_" + hashlib.sha1(b"A/b/#text int").hexdigest()[:8])
        self.assertEqual(names[b], "a_b_" + hashlib.sha1(b"a_b/#text string").hexdigest()[:8])

    def test_attribute_and_element_of_one_name_differ_by_attr(self):
        names = x.assign_names([("Site/Name/#text", "string"), ("Site/@Name", "string")], {})
        self.assertEqual(names, {("Site/Name/#text", "string"): "site_name", ("Site/@Name", "string"): "site_name_attr"})

    def test_one_locator_with_two_model_types_gets_the_type_on_both(self):
        names = x.assign_names([("Level/#text", "int"), ("Level/#text", "string")], {})
        self.assertEqual(sorted(names.values()), ["level_int", "level_string"])

    def test_list_that_meets_a_key_of_its_name_gets_list(self):
        names = x.assign_names([("Tag/@id", "string"), ("Tag/Id/[]", "list")], {})
        self.assertEqual(names[("Tag/Id/[]", "list")], "tag_id_list")
        self.assertEqual(names[("Tag/@id", "string")], "tag_id_attr")
        # a list alone takes the plain name
        self.assertEqual(x.assign_names([("Tag/[]", "list")], {}), {("Tag/[]", "list"): "tag"})

    def test_pinned_name_wins_and_a_new_place_that_wants_it_is_hashed_away(self):
        pinned = {"Old/Speed/#text float": "speed"}
        names = x.assign_names([("Old/Speed/#text", "float"), ("Speed/#text", "float")], pinned)
        self.assertEqual(names[("Old/Speed/#text", "float")], "speed")
        self.assertEqual(names[("Speed/#text", "float")], "speed_" + hashlib.sha1(b"Speed/#text float").hexdigest()[:8])

    def test_name_pinned_to_a_place_no_longer_in_the_schema_stays_reserved(self):
        names = x.assign_names([("Speed/#text", "float")], {"Gone/#text float": "speed"})
        self.assertNotEqual(names[("Speed/#text", "float")], "speed")

    def test_long_locators_that_differ_only_in_the_middle_keep_unique_keys(self):
        idents = [("Alpha/%s/Omega/@value" % ("Middle%dOfAVeryLongPathThatRepeats/" % i * 3).rstrip("/"), "string")
                  for i in range(6)]
        names = x.assign_names(idents, {})
        self.assertEqual(len(set(names.values())), 6)
        self.assertTrue(all(len(n) <= x.MAX_KEY_LEN for n in names.values()))

    def test_order_of_the_identities_does_not_change_the_names(self):
        idents = [("A/B/#text", "string"), ("A/@B", "string"), ("A/B/[]", "list"), ("X/#text", "int"),
                  ("X/#text", "string"), ("a_b/#text", "string"), ("A/b/#text", "int")]
        pinned = {"Q/#text string": "x_int"}
        expected = x.assign_names(idents, pinned)
        self.assertEqual(x.assign_names(idents[::-1], pinned), expected)
        self.assertEqual(x.assign_names(idents[3:] + idents[:3], pinned), expected)
        self.assertEqual(len(set(expected.values())), len(idents))
        self.assertNotIn("x_int", expected.values())

    def test_names_text_keeps_pins_of_places_this_run_did_not_see(self):
        plan = x.Plan()
        plan.pinned = {"Gone/#text float": "gone"}
        plan.names = {("B/#text", "int"): "b", ("A/[]", "list"): "a"}
        self.assertEqual(json.loads(x.names_text(plan)), {"A/[] list": "a", "B/#text int": "b", "Gone/#text float": "gone"})
        self.assertEqual(x.names_text(plan), '{\n "A/[] list": "a",\n "B/#text int": "b",\n "Gone/#text float": "gone"\n}\n')


class SampleValueTest(unittest.TestCase):
    SCHEMA = "\n".join([
        simple_type("Priority", "xs:int", [("minInclusive", "1"), ("maxInclusive", "5")]),
        simple_type("Channel", "xs:integer", [("minExclusive", "10"), ("maxExclusive", "20")]),
        simple_type("Step", "xs:int", [("enumeration", "10"), ("enumeration", "20")]),
        simple_type("Latitude", "xs:decimal", [("minInclusive", "-90"), ("maxInclusive", "90")]),
        simple_type("Voltage", "xs:float", [("minInclusive", "9"), ("maxInclusive", "48")]),
        simple_type("Angle", "xs:double", [("minExclusive", "-3.2"), ("maxExclusive", "3.2")]),
        simple_type("Sliver", "xs:double", [("minExclusive", "9"), ("maxExclusive", "10")]),
        simple_type("Mode", "xs:string", [("enumeration", "n/a (unset)"), ("enumeration", "LIVE"), ("enumeration", "REPLAY")]),
        simple_type("Odd", "xs:string", [("enumeration", "a b  c"), ("enumeration", "(x)")]),
        simple_type("Code3", "xs:string", [("length", "3")]),
        simple_type("Long", "xs:string", [("minLength", "50")]),
        simple_type("Uuid", "xs:string", [("pattern", "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")]),
        simple_type("Plate", "xs:string", [("pattern", "[A-Z]{3}-[0-9]{4}")]),
        simple_type("ShortUuid", "t:Uuid", [("maxLength", "10")]),
        simple_type("Hex", "xs:hexBinary", [("length", "4")]),
    ])

    @classmethod
    def setUpClass(cls):
        cls.schema = schema_of(cls.SCHEMA)

    def sample(self, type_name, transform, i=0):
        qref = ("xs", type_name[3:]) if type_name.startswith("xs:") else ("t", type_name)
        return x.sample_value(self.schema, qref, transform, i)

    def test_int_stays_inside_inclusive_bounds(self):
        # i % 9 + 1 where that fits, the lower bound where it does not
        self.assertEqual([self.sample("Priority", "int", i)[0] for i in (0, 4, 5, 8, 9)], ["1", "5", "1", "1", "1"])

    def test_int_exclusive_bounds_are_moved_in_by_one(self):
        self.assertEqual(self.sample("Channel", "int", 3), ("11", True))

    def test_int_with_only_an_upper_bound_takes_it(self):
        self.assertEqual(self.sample("xs:negativeInteger", "int", 0), ("-1", True))
        self.assertEqual(self.sample("xs:unsignedByte", "int", 7), ("8", True))

    def test_int_enumeration_cycles_through_its_values(self):
        self.assertEqual([self.sample("Step", "int", i)[0] for i in range(3)], ["10", "20", "10"])

    def test_float_takes_a_short_decimal_inside_the_bounds(self):
        self.assertEqual(self.sample("Latitude", "float", 0), ("0.5", True))
        self.assertEqual(self.sample("Latitude", "float", 1), ("1.5", True))
        # 3.5 comes first for i = 5 and lies outside the open interval; 0.75 is next
        self.assertEqual(self.sample("Angle", "float", 5), ("0.75", True))

    def test_float_with_no_candidate_inside_takes_an_inclusive_bound(self):
        self.assertEqual(self.sample("Voltage", "float", 0), ("9", True))

    def test_float_that_cannot_be_fitted_says_so(self):
        self.assertEqual(self.sample("Sliver", "float", 0), ("0.5", False))

    def test_every_numeric_sample_is_valid_for_its_type(self):
        bounds = {"Priority": lambda v: 1 <= v <= 5, "Channel": lambda v: 10 < v < 20,
                  "Latitude": lambda v: -90 <= v <= 90, "Voltage": lambda v: 9 <= v <= 48,
                  "Angle": lambda v: -3.2 < v < 3.2}
        for name, inside in bounds.items():
            transform = "int" if name in ("Priority", "Channel") else "float"
            for i in range(40):
                value, honored = self.sample(name, transform, i)
                self.assertTrue(honored and inside(float(value)), (name, i, value))
                self.assertEqual(x.t_encode(transform, x.t_decode(transform, value)), value, "not canonical")

    def test_date_time_sample_is_canonical_for_iso8601_ms(self):
        value, honored = self.sample("xs:dateTime", "iso8601_ms", 1234)
        self.assertEqual((value, honored), ("2026-01-02T03:04:05.234Z", True))
        self.assertEqual(x.t_encode("iso8601_ms", x.t_decode("iso8601_ms", value)), value)

    def test_string_enumeration_skips_values_that_are_not_safe_in_a_vector(self):
        self.assertEqual(self.sample("Mode", "string", 0), ("LIVE", True))
        self.assertEqual(self.sample("Mode", "string", 2), ("REPLAY", True))
        self.assertEqual(self.sample("Odd", "string", 4), ("v4", False))

    def test_string_enumeration_skips_a_handling_marking_word(self):
        word = "NO" + "FORN"        # in two halves: the boundary gate reads the whole word as a marking
        schema = schema_of(simple_type("Mark", "xs:string", [("enumeration", word), ("enumeration", "OPEN")]))
        self.assertEqual(x.sample_value(schema, ("t", "Mark"), "string", 0), ("OPEN", True))

    def test_string_with_no_facet_is_a_short_token(self):
        self.assertEqual(self.sample("xs:string", "string", 7), ("s7", True))

    def test_string_fits_length_facets(self):
        self.assertEqual(self.sample("Code3", "string", 0), ("ABC", True))
        self.assertEqual(self.sample("Long", "string", 0), ("A" * 50, True))
        self.assertEqual(self.sample("Hex", "string", 0), ("0A0A0A0A", True))

    def test_string_fits_a_pattern_when_a_candidate_does(self):
        self.assertEqual(self.sample("Uuid", "string", 5), ("00000000-0000-4000-8000-000000000005", True))

    def test_string_no_candidate_fits_is_reported_as_not_honored(self):
        self.assertEqual(self.sample("Plate", "string", 7), ("v7", False))
        # a facet of the derived type and the pattern of its base must both hold
        self.assertEqual(self.sample("ShortUuid", "string", 1), ("v1", False))

    def test_built_ins_kept_as_string_get_a_value_of_their_lexical_form(self):
        self.assertEqual(self.sample("xs:boolean", "string", 0), ("true", True))
        self.assertEqual(self.sample("xs:boolean", "string", 1), ("false", True))
        self.assertEqual(self.sample("xs:date", "string", 0), ("2026-01-02", True))
        self.assertEqual(self.sample("xs:dateTime", "string", 0), ("2026-01-02T03:04:05Z", True))
        self.assertEqual(self.sample("xs:duration", "string", 3), ("PT4S", True))


class FloatTextTest(unittest.TestCase):
    def test_whole_number_has_no_decimal_point(self):
        self.assertEqual(x.plain_float(30.0), "30")
        self.assertEqual(x.plain_float(-2.0), "-2")

    def test_zero_and_negative_zero_are_0(self):
        self.assertEqual(x.plain_float(0.0), "0")
        self.assertEqual(x.plain_float(-0.0), "0")

    def test_shortest_text_that_reads_back_as_the_same_double(self):
        self.assertEqual(x.plain_float(0.1), "0.1")
        self.assertEqual(x.plain_float(-85.9578182), "-85.9578182")
        self.assertEqual(x.plain_float(1 / 3), "0.3333333333333333")
        self.assertEqual(float(x.plain_float(1 / 3)), 1 / 3)

    def test_never_an_exponent(self):
        self.assertEqual(x.plain_float(1e-7), "0.0000001")
        self.assertEqual(x.plain_float(2.5e-5), "0.000025")
        self.assertEqual(x.plain_float(1e22), "10000000000000000000000")
        self.assertEqual(x.plain_float(1.5e300), "15" + "0" * 299)

    def test_float_transform_writes_the_same_text(self):
        for value, text in ((30.0, "30"), (-0.0, "0"), (0.1, "0.1"), (1e-7, "0.0000001")):
            self.assertEqual(x.t_encode("float", value), text)

    def test_float_decode_refuses_an_exponent_and_words(self):
        self.assertEqual(x.t_decode("float", "-42.6"), -42.6)
        self.assertEqual(x.t_decode("float", ".5"), 0.5)
        for bad in ("1e5", "NaN", "INF", "", "1,5"):
            with self.assertRaises(x.WireError, msg=bad) as caught:
                x.t_decode("float", bad)
            self.assertEqual(caught.exception.kind, "transform-decode")

    def test_int_decode_refuses_a_fraction(self):
        self.assertEqual(x.t_decode("int", "-17"), -17)
        with self.assertRaises(x.WireError):
            x.t_decode("int", "1.0")


class Iso8601Test(unittest.TestCase):
    # 2026-01-02 is day 20455 of the epoch: 56 years of 365 days, 14 leap days, and 1.
    # 20455 * 86400 + 3 * 3600 + 4 * 60 + 5 = 1767323045 seconds.
    BASE = 1767323045000

    def test_utc_with_and_without_a_fraction(self):
        self.assertEqual(x.t_decode("iso8601_ms", "2026-01-02T03:04:05Z"), self.BASE)
        self.assertEqual(x.t_decode("iso8601_ms", "2026-01-02T03:04:05.007Z"), self.BASE + 7)
        self.assertEqual(x.t_decode("iso8601_ms", "2026-01-02T03:04:05.5Z"), self.BASE + 500)

    def test_fraction_beyond_milliseconds_is_truncated_not_rounded(self):
        self.assertEqual(x.t_decode("iso8601_ms", "2026-01-02T03:04:05.1239Z"), self.BASE + 123)
        self.assertEqual(x.t_decode("iso8601_ms", "1970-01-01T00:00:00.0009Z"), 0)

    def test_lowercase_t_and_z_are_read(self):
        self.assertEqual(x.t_decode("iso8601_ms", "2026-01-02t03:04:05z"), self.BASE)

    def test_offset_is_converted_to_utc(self):
        self.assertEqual(x.t_decode("iso8601_ms", "2026-01-02T03:04:05+01:30"), self.BASE - 5400000)
        self.assertEqual(x.t_decode("iso8601_ms", "2026-01-02T03:04:05-05:00"), self.BASE + 18000000)
        self.assertEqual(x.t_decode("iso8601_ms", "2026-01-02T03:04:05+00:00"), self.BASE)

    def test_instant_before_the_epoch(self):
        self.assertEqual(x.t_decode("iso8601_ms", "1969-12-31T23:59:59.999Z"), -1)
        self.assertEqual(x.t_encode("iso8601_ms", -1), "1969-12-31T23:59:59.999Z")

    def test_encode_writes_uppercase_and_three_fraction_digits(self):
        self.assertEqual(x.t_encode("iso8601_ms", self.BASE), "2026-01-02T03:04:05.000Z")
        self.assertEqual(x.t_encode("iso8601_ms", self.BASE + 7), "2026-01-02T03:04:05.007Z")
        self.assertEqual(x.t_encode("iso8601_ms", 0), "1970-01-01T00:00:00.000Z")
        self.assertEqual(x.t_encode("iso8601_ms", 951782400000), "2000-02-29T00:00:00.000Z")

    def test_no_designator_a_bad_date_and_a_bare_date_are_decode_errors(self):
        for bad in ("2026-01-02T03:04:05", "2026-02-30T00:00:00Z", "2026-01-02", "2026-01-02 03:04:05Z",
                    "2026-01-02T24:00:00Z", "2026-01-02T03:04:05+0130", ""):
            with self.assertRaises(x.WireError, msg=bad) as caught:
                x.t_decode("iso8601_ms", bad)
            self.assertEqual(caught.exception.kind, "transform-decode")


class CanonicalXmlTest(unittest.TestCase):
    def test_attributes_in_line_order_then_the_residue_of_the_root(self):
        doc = x.canonical_xml("R", [("f", "@b", "1"), ("f", "@a", "2")], [("xmlns", "urn:x")])
        self.assertEqual(doc, '<R b="1" a="2" xmlns="urn:x"/>')

    def test_element_stands_where_the_first_line_that_addresses_into_it_stands(self):
        doc = x.canonical_xml("R", [("f", "K/#text", "k"), ("f", "E/@z", "1"), ("f", "K/@late", "9")], [])
        self.assertEqual(doc, '<R><K late="9">k</K><E z="1"/></R>')

    def test_element_with_no_text_and_no_child_is_self_closing(self):
        self.assertEqual(x.canonical_xml("R", [], []), "<R/>")
        self.assertEqual(x.canonical_xml("R", [("f", "A/B/@c", "")], []), '<R><A><B c=""/></A></R>')

    def test_text_comes_before_child_elements(self):
        doc = x.canonical_xml("R", [("f", "A/B/#text", "inner"), ("f", "A/#text", "outer")], [])
        self.assertEqual(doc, "<R><A>outer<B>inner</B></A></R>")

    def test_escapes_ampersand_and_less_than_and_the_quote_in_an_attribute_only(self):
        doc = x.canonical_xml("R", [("f", "@a", 'x"<&>'), ("f", "K/#text", 'a<b&c"d>')], [])
        self.assertEqual(doc, '<R a="x&quot;&lt;&amp;>"><K>a&lt;b&amp;c"d></K></R>')

    def test_group_writes_one_element_per_item_at_its_line(self):
        doc = x.canonical_xml("R", [
            ("f", "First/#text", "1"),
            ("g", "List/Item", [[("f", "#text", "p")], [("f", "@q", "r"), ("g", "Sub", [[("f", "#text", "s")]])]]),
            ("f", "Last/#text", "2")], [])
        self.assertEqual(doc, '<R><First>1</First><List><Item>p</Item><Item q="r"><Sub>s</Sub></Item></List><Last>2</Last></R>')

    def test_writer_and_codec_agree_on_a_document(self):
        doc = x.canonical_xml("R", [("f", "@a", 'x"<&'), ("f", "K/#text", "a<b&c")], [("xmlns", "urn:x")])
        root = x.xml_parse(doc)
        self.assertEqual(root.attrs, [("a", 'x"<&'), ("xmlns", "urn:x")])
        self.assertEqual(x.xml_get(root, "K/#text"), "a<b&c")


class XmlReaderTest(unittest.TestCase):
    def test_named_entities_and_character_references(self):
        self.assertEqual(x.xml_unescape("&amp;&lt;&gt;&quot;&apos;"), "&<>\"'")
        self.assertEqual(x.xml_unescape("&#65;&#x42;&#x20AC;"), "AB€")
        self.assertEqual(x.xml_unescape("a &amp;amp; b"), "a &amp; b")      # one pass, not two

    def test_unknown_entity_and_bad_reference_are_malformed_wire(self):
        for bad in ("&bogus;", "&#xZZ;", "&#;"):
            with self.assertRaises(x.WireError, msg=bad) as caught:
                x.xml_unescape(bad)
            self.assertEqual(caught.exception.kind, "malformed-wire")

    def test_both_quote_styles_and_entities_in_attributes(self):
        root = x.xml_parse("<a x='1&amp;2' y=\"it's &lt;\" z = 'say \"hi\"'/>")
        self.assertEqual(root.attrs, [("x", "1&2"), ("y", "it's <"), ("z", 'say "hi"')])

    def test_declaration_comments_and_cdata(self):
        root = x.xml_parse("<?xml version='1.0'?>\n<!-- c --><a><b>t&gt;<![CDATA[<raw>&amp;]]></b><!-- <x/> --><c/></a>\n")
        self.assertEqual([k.name for k in root.kids], ["b", "c"])
        self.assertEqual(root.kids[0].text, "t><raw>&amp;")

    def test_names_are_kept_as_written_with_their_prefix(self):
        root = x.xml_parse('<p:a xmlns:p="urn:x"><p:b/></p:a>')
        self.assertEqual((root.name, root.kids[0].name, root.attrs), ("p:a", "p:b", [("xmlns:p", "urn:x")]))

    def test_locator_takes_the_first_sibling_of_a_name(self):
        root = x.xml_parse('<r><i n="1">a</i><i n="2">b</i><e/></r>')
        self.assertEqual(x.xml_get(root, "i/@n"), "1")
        self.assertEqual(x.xml_get(root, "i/#text"), "a")
        self.assertIsNone(x.xml_get(root, "e/#text"))       # empty text is absent
        self.assertIsNone(x.xml_get(root, "missing/@n"))
        self.assertIsNone(x.xml_get(root, "@n"))

    def test_malformed_documents_are_malformed_wire(self):
        for bad in ("<a><b></a>", "<a>", "x<a/>", "<a/><b/>", "<a b=1/>", "", "<a><!-- x</a>", "<a/>trailing",
                    "<a><![CDATA[x</a>", "</a>"):
            with self.assertRaises(x.WireError, msg=bad) as caught:
                x.xml_parse(bad)
            self.assertEqual(caught.exception.kind, "malformed-wire", bad)

    def test_count_values_counts_attributes_texts_and_empty_elements(self):
        # x, the text of b, the empty c; the root itself is not a value
        self.assertEqual(x.count_values(x.xml_parse('<a x="1"><b>t</b><c/></a>')), 3)
        self.assertEqual(x.count_values(x.xml_parse("<a/>")), 0)


class WalkerTest(unittest.TestCase):
    REPEATS = '''<xs:element name="Root" type="t:R"/>
<xs:complexType name="R"><xs:sequence>
  <xs:element name="Name" type="xs:string"/>
  <xs:element name="Tag" type="xs:string" maxOccurs="unbounded"/>
  <xs:element name="Row" type="t:Row" minOccurs="0" maxOccurs="4"/>
  <xs:element name="Blob" type="t:Blob" maxOccurs="2"/>
  <xs:element name="Wrap" type="t:Wrap" maxOccurs="2"/>
  <xs:sequence maxOccurs="unbounded"><xs:element name="K" type="xs:string"/></xs:sequence>
  <xs:choice maxOccurs="3"><xs:element name="P" type="xs:string"/><xs:element name="Q" type="xs:string"/></xs:choice>
</xs:sequence></xs:complexType>
<xs:complexType name="Row"><xs:sequence><xs:element name="Cell" type="xs:int" maxOccurs="unbounded"/></xs:sequence>
  <xs:attribute name="id" type="xs:string" use="required"/></xs:complexType>
<xs:complexType name="Blob"><xs:sequence><xs:any/></xs:sequence></xs:complexType>
<xs:complexType name="Wrap"><xs:sequence><xs:element name="Inner" type="t:Blob"/></xs:sequence></xs:complexType>'''

    def test_repeated_element_becomes_a_group_whose_lines_are_relative_to_the_item(self):
        items, _ = walk_root(schema_of(self.REPEATS))
        self.assertEqual(outline(items), [
            "Name/#text",
            ("Tag", ["#text"]),
            ("Row", ["@id", ("Cell", ["#text"])])])
        self.assertEqual([(g.path, g.nest, g.tname) for g in x.all_groups(items)],
                         [("Tag", 1, "xs:string"), ("Row", 1, "Row"), ("Cell", 2, "xs:int")])

    def test_repeated_element_with_nothing_to_map_is_declined_with_the_reason(self):
        _, skipped = walk_root(schema_of(self.REPEATS))
        # the item itself is the wildcard holder: its own reason is kept
        self.assertIn((x.R_ANY, "Blob", "Blob", "xs:any"), skipped)
        # the reasons lie deeper in the item: one line for the repeated element
        self.assertIn((x.R_REPEAT_NOTHING, "Wrap", "R", "Wrap"), skipped)
        self.assertNotIn("Wrap/Inner", [place for _, place, _, _ in skipped])

    def test_repeated_sequence_and_repeated_choice_are_declined(self):
        items, skipped = walk_root(schema_of(self.REPEATS))
        self.assertIn((x.R_REPEAT_GROUP, "", "R", "sequence"), skipped)
        self.assertIn((x.R_REPEAT_GROUP, "", "R", "choice"), skipped)
        self.assertFalse({"K/#text", "P/#text", "Q/#text"} & {lf.locator for lf in x.all_leaves(items)})

    def test_group_inside_an_item_is_declined_at_the_nesting_limit(self):
        items, skipped = walk_root(schema_of(self.REPEATS), max_nest=1)
        self.assertEqual(outline(items), ["Name/#text", ("Tag", ["#text"]), ("Row", ["@id"])])
        self.assertIn((x.R_NEST, "Row/Cell", "Row", "Cell"), skipped)

    CHOICES = '''<xs:element name="Root" type="t:R"/>
<xs:complexType name="R"><xs:sequence>
  <xs:choice><xs:element name="Callsign" type="xs:string"/><xs:element name="Serial" type="xs:int"/></xs:choice>
  <xs:choice><xs:element name="Fixed" type="t:Pos"/><xs:element name="Mobile" type="xs:string"/></xs:choice>
  <xs:choice><xs:element name="One" type="xs:string"/><xs:element name="Many" type="xs:string" maxOccurs="2"/></xs:choice>
  <xs:choice minOccurs="0"><xs:element name="Up" type="xs:string"/><xs:element name="Down" type="xs:string"/></xs:choice>
</xs:sequence></xs:complexType>
<xs:complexType name="Pos"><xs:sequence><xs:element name="Lat" type="xs:double"/></xs:sequence></xs:complexType>'''

    def test_choice_of_simple_elements_maps_every_branch_as_an_optional_line(self):
        items, _ = walk_root(schema_of(self.CHOICES))
        self.assertEqual([(lf.locator, lf.choice, lf.mandatory) for lf in items], [
            ("Callsign/#text", (1, 0), False), ("Serial/#text", (1, 1), False),
            ("Up/#text", (2, 0), False), ("Down/#text", (2, 1), False)])

    def test_choice_with_a_complex_or_repeated_branch_is_declined_and_names_its_branches(self):
        _, skipped = walk_root(schema_of(self.CHOICES))
        self.assertEqual(skipped, [(x.R_CHOICE, "", "R", "choice of Fixed, Mobile"),
                                   (x.R_CHOICE, "", "R", "choice of One, Many")])

    def test_only_the_first_branch_of_a_choice_is_a_candidate_for_requires(self):
        # A second message maps Callsign too. `Serial` is mapped by Root alone and would be the
        # best key to require, but a document has one branch of a choice and the vectors hold
        # the first, so the candidates are Callsign and Up, and Up tells the kinds apart.
        schema = schema_of(self.CHOICES + '<xs:element name="Other" type="t:O"/><xs:complexType name="O">'
                           '<xs:sequence><xs:element name="Callsign" type="xs:string"/></xs:sequence></xs:complexType>')
        w = x.walk_messages(schema, ["Root", "Other"], x.MAX_DEPTH, x.MAX_DEPTH)
        x.name_lines(w.kinds, x.assign_names(w.idents, {}), "m")
        x.choose_requires(w.kinds, 0)
        self.assertEqual(w.kinds[0].requires, ["m.up"])

    def test_mandatory_follows_min_occurs_down_the_path(self):
        schema = schema_of('''<xs:element name="Root" type="t:R"/>
<xs:complexType name="R"><xs:sequence>
  <xs:element name="Must" type="t:Pair"/>
  <xs:element name="May" type="t:Pair" minOccurs="0"/>
</xs:sequence><xs:attribute name="req" type="xs:string" use="required"/><xs:attribute name="opt" type="xs:string"/></xs:complexType>
<xs:complexType name="Pair"><xs:sequence>
  <xs:element name="A" type="xs:string"/><xs:element name="B" type="xs:string" minOccurs="0"/>
</xs:sequence></xs:complexType>''')
        items, _ = walk_root(schema)
        self.assertEqual({lf.locator: lf.mandatory for lf in items}, {
            "@req": True, "@opt": False, "Must/A/#text": True, "Must/B/#text": False,
            "May/A/#text": False, "May/B/#text": False})

    DEEP = '''<xs:element name="Root" type="t:R"/>
<xs:complexType name="R"><xs:sequence><xs:element name="A" type="t:A"/></xs:sequence></xs:complexType>
<xs:complexType name="A"><xs:sequence><xs:element name="B" type="xs:string"/></xs:sequence>
  <xs:attribute name="x" type="xs:string"/></xs:complexType>'''

    def test_depth_cap_of_the_run_declines_what_lies_below_it(self):
        items, skipped = walk_root(schema_of(self.DEEP), max_depth=1)
        self.assertEqual(outline(items), ["A/@x"])
        self.assertEqual(skipped, [(x.R_CAP, "A/B", "A", "B")])

    def test_extension_puts_base_content_first_and_a_recursive_type_ends_the_walk(self):
        schema = schema_of('''<xs:element name="Root" type="t:Derived"/>
<xs:complexType name="Base"><xs:sequence><xs:element name="First" type="xs:string"/></xs:sequence>
  <xs:attribute name="id" type="xs:string"/></xs:complexType>
<xs:complexType name="Derived"><xs:complexContent><xs:extension base="t:Base"><xs:sequence>
  <xs:element name="Second" type="xs:string"/>
  <xs:element name="Tree" type="t:Node"/>
</xs:sequence><xs:attribute name="extra" type="xs:int"/></xs:extension></xs:complexContent></xs:complexType>
<xs:complexType name="Node"><xs:sequence>
  <xs:element name="Label" type="xs:string"/><xs:element name="Child" type="t:Node" minOccurs="0"/>
</xs:sequence></xs:complexType>''')
        items, skipped = walk_root(schema)
        self.assertEqual(outline(items), ["@id", "@extra", "First/#text", "Second/#text", "Tree/Label/#text"])
        self.assertEqual(skipped, [(x.R_RECURSE, "Tree/Child", "Node", "Child")])

    def test_root_element_of_simple_type_has_no_line(self):
        items, skipped = walk_root(schema_of('<xs:element name="Root" type="xs:string"/>'))
        self.assertEqual((items, skipped), ([], [(x.R_ROOT_TEXT, "", "(global element)", "Root")]))

    def test_date_time_is_iso8601_ms_only_when_a_pattern_ends_every_value_in_z(self):
        schema = schema_of('<xs:element name="Root" type="t:R"/>\n<xs:complexType name="R"><xs:sequence>'
                           '<xs:element name="Utc" type="t:Zulu"/><xs:element name="Either" type="t:ZOrOffset"/>'
                           '<xs:element name="Any" type="xs:dateTime"/></xs:sequence></xs:complexType>\n'
                           + simple_type("Zulu", "xs:dateTime", [("pattern", ".*Z")])
                           + simple_type("ZOrOffset", "xs:dateTime", [("pattern", ".*Z|.*[+-]..:..Z")]))
        items, _ = walk_root(schema)
        self.assertEqual([(lf.locator, lf.transform, lf.mtype) for lf in items], [
            ("Utc/#text", "iso8601_ms", "int"), ("Either/#text", "string", "string"), ("Any/#text", "string", "string")])

    def test_unqualified_local_elements_are_counted(self):
        raw = schema_text('<xs:element name="Root" type="t:R"/>\n<xs:complexType name="R"><xs:sequence>'
                          '<xs:element name="A" type="xs:string"/><xs:element name="B" type="xs:string" form="qualified"/>'
                          '</xs:sequence></xs:complexType>').replace(' elementFormDefault="qualified"', "")
        schema = x.Schema()
        schema.read_bytes(raw.encode("utf-8"), "t.xsd", {})
        walker = x.Walker(schema, x.MAX_DEPTH)
        walker.walk(schema.elements["Root"])
        self.assertEqual(walker.unqualified, 1)


class PlanTest(unittest.TestCase):
    def test_module_over_the_key_budget_lowers_group_nesting_first(self):
        schema = schema_of(WalkerTest.REPEATS)
        free = x.walk_messages(schema, ["Root"], x.MAX_DEPTH, x.MAX_DEPTH)
        self.assertEqual((len(free.idents), free.deepest, free.nest_limited), (7, 2, False))
        w = x.walk_messages(schema, ["Root"], x.MAX_DEPTH, x.MAX_DEPTH, key_budget=6)
        # without the group inside an item: its list and the int text of its item are gone
        self.assertEqual(w.idents, [("#text", "string"), ("@id", "string"), ("Name/#text", "string"),
                                    ("Row/[]", "list"), ("Tag/[]", "list")])
        self.assertEqual((w.deepest, w.nest_free, w.keys_free, w.nest_limited, w.depth), (1, 2, 7, True, x.MAX_DEPTH))
        self.assertIn(x.R_NEST, [reason for reason, _, _, _ in w.kinds[0].skipped])

    def test_module_still_over_the_budget_lowers_the_depth_down_to_one(self):
        w = x.walk_messages(schema_of(WalkerTest.REPEATS), ["Root"], x.MAX_DEPTH, x.MAX_DEPTH, key_budget=2)
        self.assertEqual((w.depth, w.depth_asked), (1, x.MAX_DEPTH))

    def test_module_that_cannot_be_brought_under_the_budget_is_reported_not_passed_in_silence(self):
        # one key cannot hold what is left of this schema at depth 1 and nesting 1
        w = x.walk_messages(schema_of(WalkerTest.REPEATS), ["Root"], x.MAX_DEPTH, x.MAX_DEPTH, key_budget=1)
        self.assertTrue(w.over_budget)
        self.assertGreater(len(w.idents), 1)
        warning = x.over_budget_warning(w, "demo")
        self.assertIn("module demo holds %d keys and lists, more than the budget of 1" % len(w.idents), warning)

    def test_module_within_the_budget_gives_no_warning(self):
        w = x.walk_messages(schema_of(WalkerTest.REPEATS), ["Root"], x.MAX_DEPTH, x.MAX_DEPTH)
        self.assertFalse(w.over_budget)
        self.assertIsNone(x.over_budget_warning(w, "demo"))

    TWO = '''<xs:element name="Alpha" type="t:AlphaMT"/>
<xs:element name="Beta" type="t:BetaMT"/>
<xs:element name="Gamma" type="t:Other"/>
<xs:complexType name="AlphaMT"><xs:sequence>
  <xs:element name="Id" type="xs:string"/><xs:element name="Only" type="xs:string" minOccurs="0"/>
  <xs:element name="Both" type="xs:string"/>
</xs:sequence></xs:complexType>
<xs:complexType name="BetaMT"><xs:sequence>
  <xs:element name="Id" type="xs:string"/><xs:element name="Both" type="xs:string"/>
</xs:sequence></xs:complexType>
<xs:complexType name="Other"><xs:sequence><xs:element name="Id" type="xs:string"/></xs:sequence></xs:complexType>
<xs:complexType name="Pick"><xs:choice><xs:element ref="t:Gamma"/><xs:element ref="t:Alpha"/></xs:choice></xs:complexType>'''

    def kinds_of(self, schema, names):
        w = x.walk_messages(schema, names, x.MAX_DEPTH, x.MAX_DEPTH)
        x.name_lines(w.kinds, x.assign_names(w.idents, {}), "m")
        return w.kinds

    def test_messages_are_selected_by_suffix_choice_or_name_in_schema_order(self):
        schema = schema_of(self.TWO)
        self.assertEqual(x.select_messages(schema, "MT", [], [])[0], ["Alpha", "Beta"])
        self.assertEqual(x.select_messages(schema, None, ["Pick"], [])[0], ["Alpha", "Gamma"])
        names, rule = x.select_messages(schema, "MT", [], ["Gamma", "Alpha"])
        self.assertEqual(names, ["Alpha", "Beta", "Gamma"])
        self.assertEqual(len(rule), 3)
        with self.assertRaises(x.GenError):
            x.select_messages(schema, "NoSuchSuffix", [], [])
        with self.assertRaises(x.GenError):
            x.select_messages(schema, None, ["Other"], [])

    def test_common_lines_are_the_leading_lines_every_kind_has(self):
        kinds = self.kinds_of(schema_of(self.TWO), ["Alpha", "Beta"])
        # `Id` leads both; `Both` is in both but not at the same position
        self.assertEqual(x.common_prefix(kinds), 1)
        self.assertEqual(x.common_prefix(kinds[:1]), 0)

    def test_requires_prefers_mandatory_keys_and_falls_back_to_optional_ones(self):
        kinds = self.kinds_of(schema_of(self.TWO), ["Alpha", "Beta"])
        x.choose_requires(kinds, 1)
        alpha, beta = kinds
        # Alpha: the mandatory `Both` is mapped by Beta too, so the optional `Only` is added
        self.assertEqual((alpha.requires, alpha.unique, alpha.optional_required), (["m.both", "m.only"], True, 1))
        # Beta: every key it has is also Alpha's
        self.assertEqual((beta.requires, beta.unique), (["m.both"], False))

    def test_kind_with_no_leaf_outside_its_groups_requires_its_first_list(self):
        schema = schema_of('<xs:element name="Root" type="t:R"/>\n<xs:complexType name="R"><xs:sequence>'
                           '<xs:element name="Item" type="xs:string" maxOccurs="unbounded"/></xs:sequence></xs:complexType>')
        kinds = self.kinds_of(schema, ["Root"])
        x.choose_requires(kinds, 0)
        self.assertEqual(kinds[0].requires, ["m.item_list"])

    def test_vectors_over_the_byte_budget_fall_back_to_one_item_per_group(self):
        schema = schema_of(WalkerTest.REPEATS)
        plan = x.Plan()
        plan.format, plan.tns = "demo", "urn:example:t"
        plan.kinds = self.kinds_of(schema, ["Root"])
        two = x.vectors_within_budget(schema, plan, {})
        self.assertEqual(two.per_group, 2)
        doc = json.loads(two.files[0][1])
        self.assertEqual(two.files[0][0], "gen-1-root-roundtrip.json")
        self.assertEqual(doc["input"], "<Root><Name>s0</Name><Tag>s1</Tag><Tag>s2</Tag>"
                                       '<Row id="s3"><Cell>5</Cell></Row><Row id="s5"><Cell>7</Cell></Row></Root>')
        self.assertEqual(doc["model"], {
            "@kind": "root", "m.name": "s0", "m.tag.#": "2", "m.tag[1].m.item_string": "s2",
            "m.row[0].m.cell.#": "1", "m.row.#": "2", "m.row[1].m.id": "s5"})
        one = x.vectors_within_budget(schema, plan, {}, budget=two.two_bytes - 1)
        self.assertEqual((one.per_group, one.two_bytes), (1, two.two_bytes))
        self.assertEqual(json.loads(one.files[0][1])["input"],
                         '<Root><Name>s0</Name><Tag>s1</Tag><Row id="s2"><Cell>4</Cell></Row></Root>')


def load_demo(pack_body, extra_keys=""):
    """A gtcheck Pack of a hand-written xml pack over a small model."""
    model = gtcheck.Model()
    model.add('module core\nversion 0.1.0\ndistribution public\nsource "test"\nkey uid string - "id"\n', "core.def")
    model.add('module m\nversion 0.1.0\ndistribution public\nsource "test"\n'
              'key a string - "a"\nkey b string - "b"\nkey n int - "n"\nkey t int ms "t"\n'
              'list rows "rows"\nlist more "more"\n' + extra_keys, "m.def")
    head = 'format demo\nversion 0.1.0\ndistribution public\nsource "test"\nwire xml\nuses m\n'
    return gtcheck.load_pack(head + pack_body, model, "pack.def"), model


class CatalogCheckTest(unittest.TestCase):
    GOOD = ("kind one\nroot One\nrequires m.a\n"
            "field uid @a string\nfield m.a @a string\n"
            "group m.rows R/I\n  field m.b \"#text\" string\n  group m.more J\n    field m.n @n int\n  end\nend\n"
            "kind two\nroot Two\nfield m.b @b string\n")

    def refused(self, check, body, line, fragment):
        pack, _ = load_demo(body)
        with self.assertRaises(x.GenError) as caught:
            check(pack)
        self.assertEqual((caught.exception.file, caught.exception.line), ("pack.def", line))
        self.assertIn(fragment, caught.exception.message)

    def test_pack_of_the_shape_the_generator_writes_passes_every_check(self):
        pack, _ = load_demo(self.GOOD)
        x.check_catalog_pack(pack)

    def test_key_mapped_at_two_locators_of_one_scope_is_refused(self):
        body = "kind one\nroot One\nfield m.a @a string\nfield m.a X/#text string\n"
        self.refused(x.check_catalog_pack, body, 10, "kind one: key m.a is mapped at two locators")

    def test_key_at_two_locators_inside_one_item_is_refused(self):
        body = "kind one\nroot One\ngroup m.rows R\n  field m.a @a string\n  field m.a @b string\nend\n"
        self.refused(x.check_catalog_pack, body, 11, "kind one, group m.rows: key m.a is mapped at two locators")

    def test_two_keys_of_one_module_at_one_locator_are_refused(self):
        body = "kind one\nroot One\nfield m.a @a string\nfield m.b @a string\n"
        self.refused(x.check_catalog_pack, body, 10, "two keys of module m at @a")

    def test_same_line_twice_is_refused(self):
        body = "kind one\nroot One\nfield m.a @a string\nfield m.a @a string\n"
        self.refused(x.check_catalog_pack, body, 10, "line m.a @a twice")

    def test_common_line_and_kind_line_count_as_one_scope(self):
        body = "field m.a @a string\nkind one\nroot One\nfield m.b @a string\n"
        self.refused(x.check_catalog_pack, body, 10, "two keys of module m at @a")

    def test_two_kinds_that_share_a_root_are_refused(self):
        body = "kind one\nroot Same\nrequires m.a\nfield m.a @a string\nkind two\nroot Same\nfield m.b @b string\n"
        self.refused(x.check_one_kind_per_root, body, 11, "kinds one and two share root <Same> and nothing tells them apart")

    def test_kind_with_no_root_in_a_pack_with_none_is_refused(self):
        self.refused(x.check_one_kind_per_root, "kind one\nfield m.a @a string\n", 7, "kind one has no root")

    def test_group_below_the_path_of_another_group_is_refused(self):
        body = ("kind one\nroot One\ngroup m.rows R/I\n  field m.a @a string\nend\n"
                "group m.more R/I/J\n  field m.b @b string\nend\n")
        self.refused(x.check_catalog_pack, body, 12, "groups R/I and R/I/J overlap")

    def test_two_groups_at_one_path_are_refused(self):
        body = ("kind one\nroot One\ngroup m.rows R/I\n  field m.a @a string\nend\n"
                "group m.more R/I\n  field m.b @b string\nend\n")
        self.refused(x.check_catalog_pack, body, 12, "groups R/I and R/I overlap")

    def test_field_that_addresses_the_item_element_of_a_group_does_not_load(self):
        # this one is a load rule (0.7 ruling 21): gtcheck refuses it before any check here runs
        for locator in ("R/I/@x", "R/I/#text", "R/I/J/#text"):
            with self.assertRaises(gtcheck.CheckError, msg=locator) as caught:
                load_demo("kind one\nroot One\ngroup m.rows R/I\n  field m.a @a string\nend\nfield m.b %s string\n" % locator)
            self.assertEqual((caught.exception.kind, caught.exception.line), ("bad-directive", 12))

    def test_locator_that_names_neither_an_attribute_nor_text_is_refused(self):
        self.refused(x.check_locator_shapes, "kind one\nroot One\nfield m.a a/b string\n", 9, "bad xml locator a/b")

    def test_text_of_the_root_element_is_refused_outside_a_group(self):
        self.refused(x.check_locator_shapes, 'kind one\nroot One\nfield m.a "#text" string\n', 9, "bad xml locator #text")

    def test_line_the_codec_does_not_read_is_refused(self):
        self.refused(x.check_only_fields_and_groups, "kind one\nroot One\nconst @v 1\nfield m.a @a string\n", 9,
                     "a `const` line in a generated pack")

    def test_kind_without_requires_before_another_kind_is_refused(self):
        body = "kind one\nroot One\nfield m.a @a string\nkind two\nroot Two\nfield m.b @b string\n"
        self.refused(x.check_kinds_do_not_shadow, body, 7, "kind one has no requires and would shadow")

    def test_module_key_that_no_line_maps_is_refused(self):
        pack, model = load_demo("kind one\nroot One\nfield m.a @a string\n")
        with self.assertRaises(x.GenError) as caught:
            x.check_module_is_mapped(pack, model.modules["m"])
        self.assertIn("module m declares 5 keys or lists no line maps, first b", str(caught.exception))


class CodecTest(unittest.TestCase):
    def setUp(self):
        self.pack, _ = load_demo(CatalogCheckTest.GOOD + "field m.t T/#text iso8601_ms\n")

    def test_decode_selects_the_kind_by_root_and_fills_shared_and_raw_keys(self):
        kind, ent, residue, places = x.decode(
            self.pack, '<One a="v" xmlns="urn:x"><R><I>p<J n="1"/><J n="2"/></I><I>q</I></R><Skipped>1</Skipped></One>')
        self.assertEqual(kind.name, "one")
        self.assertEqual(ent, {"uid": "v", "m.a": "v",
                               "m.rows": [{"m.b": "p", "m.more": [{"m.n": 1}, {"m.n": 2}]}, {"m.b": "q"}]})
        self.assertEqual(residue, [("@xmlns", "urn:x")])
        # @a once, two item texts, two @n
        self.assertEqual(places, 5)

    def test_encode_writes_groups_at_their_line_and_residue_last(self):
        kind = self.pack.kinds[0]
        ent = {"uid": "v", "m.rows": [{"m.b": "p", "m.more": [{"m.n": 1}]}, {}], "m.more": [{"m.n": 9}]}
        self.assertEqual(x.encode(self.pack, kind, ent, [("@xmlns", "urn:x")]),
                         '<One a="v" xmlns="urn:x"><R><I>p<J n="1"/></I><I/></R></One>')

    def test_empty_list_writes_nothing_not_even_the_element_that_would_hold_it(self):
        self.assertEqual(x.encode(self.pack, self.pack.kinds[0], {"m.a": "v", "m.rows": []}, []), '<One a="v"/>')

    def test_two_lines_on_one_locator_write_it_once_with_the_value_of_the_first(self):
        # 0.5 ruling 16: the shared key stands first and its value is the one written
        kind = self.pack.kinds[0]
        self.assertEqual(x.encode(self.pack, kind, {"uid": "shared", "m.a": "raw"}, []), '<One a="shared"/>')
        self.assertEqual(x.encode(self.pack, kind, {"m.a": "raw"}, []), '<One a="raw"/>')

    def test_plain_decode_takes_the_earliest_present_line_of_a_key_and_reports_unmapped_root_attributes(self):
        other, _ = load_demo("root note\nconst @v 1\nfield m.t @time iso8601_ms\nfield m.t @start iso8601_ms\n"
                             "field m.a body/#text string\ndefault m.b none\n")
        ent, loose = x.plain_decode(other, '<note v="1" start="1970-01-01T00:00:02Z" time="1970-01-01T00:00:01Z" x="9"/>')
        self.assertEqual((dict(ent), loose), ({"m.t": 1000}, ["x"]))
        ent, _ = x.plain_decode(other, '<note start="1970-01-01T00:00:02Z"><body>b</body></note>')
        self.assertEqual(dict(ent), {"m.t": 2000, "m.a": "b"})

    def test_plain_decode_refuses_a_pack_with_kinds_or_tables(self):
        for body in ("kind one\nroot One\nfield m.a @a string\n",
                     "root note\nmap tbl 1 one\nfield m.a @a string via tbl\n",
                     "root note\ngroup m.rows r\n  field m.a @a string\nend\n"):
            with self.assertRaises(x.GenError, msg=body):
                x.plain_decode(load_demo(body)[0], "<note/>")

    def test_document_with_an_unknown_root_is_no_kind(self):
        with self.assertRaises(x.WireError) as caught:
            x.decode(self.pack, "<Three/>")
        self.assertEqual(caught.exception.kind, "no-kind")

    def test_encode_selection_takes_the_first_kind_whose_requires_are_present(self):
        self.assertEqual(x.select_kind(self.pack, {"m.a": "v", "m.b": "w"}).name, "one")
        self.assertEqual(x.select_kind(self.pack, {"m.b": "w"}).name, "two")

    def test_required_list_counts_only_when_it_has_an_item(self):
        pack, _ = load_demo("kind one\nroot One\nrequires m.rows\ngroup m.rows R\n  field m.a @a string\nend\n")
        self.assertEqual(x.select_kind(pack, {"m.rows": [{}]}).name, "one")
        with self.assertRaises(x.WireError) as caught:
            x.select_kind(pack, {"m.rows": []})
        self.assertEqual(caught.exception.kind, "no-kind")

    def test_model_lookup_steps_into_items_and_counts_lists(self):
        ent = {"m.a": "v", "m.rows": [{"m.b": "p", "m.more": [{"m.n": 1}]}, {"m.b": "q"}]}
        self.assertEqual(x.model_lookup(ent, "m.a"), "v")
        self.assertEqual(x.model_lookup(ent, "m.rows.#"), 2)
        self.assertEqual(x.model_lookup(ent, "m.rows[1].m.b"), "q")
        self.assertEqual(x.model_lookup(ent, "m.rows[0].m.more[0].m.n"), 1)
        self.assertEqual(x.model_lookup(ent, "m.rows[0].m.more.#"), 1)
        self.assertEqual(x.model_lookup(ent, "m.rows[1].m.more.#"), "absent")
        self.assertIsNone(x.model_lookup(ent, "m.rows[2].m.b"))
        self.assertIsNone(x.model_lookup(ent, "m.b"))

    def test_keys_a_conversion_would_derive_are_found_by_presence(self):
        model = gtcheck.Model().load_dir(os.path.join(FIXTURE, "input", "model"))
        self.assertEqual(x.would_derive(model, {"uid", "track.vel_north_ms"}), set())
        self.assertEqual(x.would_derive(model, {"track.vel_east_ms", "track.vel_north_ms"}), {"course", "speed_ms"})
        self.assertEqual(x.would_derive(model, {"track.vel_east_ms", "track.vel_north_ms", "course"}), {"speed_ms"})


class SchemaReaderTest(unittest.TestCase):
    def test_declarations_carry_the_file_and_line_they_stand_on(self):
        schema = schema_of('<xs:element name="Root" type="t:R"/>\n'
                           '<xs:complexType name="R">\n'
                           '  <xs:sequence>\n'
                           '    <xs:element name="E" type="xs:string"/>\n'
                           '  </xs:sequence>\n'
                           '  <xs:attribute name="a" type="xs:string"/>\n'
                           '</xs:complexType>')
        ct = schema.complex["R"]
        self.assertEqual((schema.elements["Root"].file, schema.elements["Root"].line), ("t.xsd", 2))
        self.assertEqual((ct.line, ct.particle.children[0].line, ct.attrs[0].line), (3, 5, 7))

    def test_facet_of_a_derived_type_replaces_the_facet_of_its_base(self):
        schema = schema_of(simple_type("Wide", "xs:int", [("minInclusive", "0"), ("maxInclusive", "100")])
                           + simple_type("Narrow", "t:Wide", [("maxInclusive", "10")]))
        builtin, chain, facets = schema.facets(("t", "Narrow"))
        self.assertEqual((builtin, [st.name for st in chain]), ("int", ["Narrow", "Wide"]))
        self.assertEqual(facets, {"minInclusive": "0", "maxInclusive": "10"})

    def test_type_defined_twice_and_a_second_target_namespace_are_refused(self):
        with self.assertRaises(x.GenError) as caught:
            schema_of('<xs:complexType name="T"/>\n<xs:simpleType name="T"><xs:restriction base="xs:int"/></xs:simpleType>')
        self.assertEqual((caught.exception.line, caught.exception.message), (3, "type T is defined twice"))
        schema = schema_of('<xs:complexType name="T"/>')
        with self.assertRaises(x.GenError) as caught:
            schema.read_bytes(schema_text("").replace("urn:example:t", "urn:example:other").encode(), "u.xsd", {})
        self.assertEqual(caught.exception.file, "u.xsd")

    def test_header_statement_is_read_from_the_head_of_the_file(self):
        head = b"<d>distribution statement a. Approved  for\tpublic release !</d>" + b" " * 7000
        self.assertEqual(x.header_statement(head), "distribution statement a. Approved for public release")
        self.assertIsNone(x.header_statement(b"<xs:schema/>"))
        self.assertIsNone(x.header_statement(b" " * x.STATEMENT_BYTES + b"Distribution Statement A."))


# A set of the shape CCSDS NDM/XML has: a types file in a namespace with
# unqualified local elements, and a "master" file with no targetNamespace that
# imports it and declares the message root. Neither header states Distribution
# Statement A.
NS_TYPES = ('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:n="urn:example:n" '
            'targetNamespace="urn:example:n" elementFormDefault="unqualified">\n'
            '<xs:complexType name="Body"><xs:sequence><xs:element name="NAME" type="xs:string"/>'
            '<xs:element name="LEVEL" type="xs:int"/></xs:sequence></xs:complexType>\n</xs:schema>\n')
MASTER = ('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:n="urn:example:n" '
          'elementFormDefault="unqualified">\n'
          '%s'
          '<xs:element name="msg" type="n:Body"/>\n</xs:schema>\n')
PUBLIC = "The publisher states that  this set is public\nand may be reused."


class PublicSetOptionsTest(Workspace):
    """--public-statement, --notes-file and a master file with no targetNamespace."""

    def run_master(self, *extra, imports=("urn:example:n",)):
        with open(self.path("types.xsd"), "w", encoding="utf-8") as fh:
            fh.write(NS_TYPES)
        with open(self.path("master.xsd"), "w", encoding="utf-8") as fh:
            fh.write(MASTER % "".join('<xs:import namespace="%s" schemaLocation="types.xsd"/>\n' % ns
                                      for ns in imports))
        return support.run_main(x.main, [
            "--xsd", self.path("master.xsd"), self.path("types.xsd"), "--format", "demo", "--module", "demo",
            "--out", self.out, "--model-dir", self.path("in", "model"), "--title", "Demo set",
            "--message", "msg", "--names-file", self.path("out", "names", "demo.json")] + list(extra))

    def test_set_without_a_header_statement_is_refused_without_the_option(self):
        status, _, err = self.run_master()
        self.assertEqual(status, 1)
        self.assertIn("master.xsd: the file header does not state Distribution Statement A, and no "
                      "--public-statement is given", err)
        self.assertFalse(os.path.exists(self.path("out", "packs")))

    def test_public_statement_is_recorded_once_in_the_sources_and_per_file_in_pack_md(self):
        status, _, err = self.run_master("--public-statement", PUBLIC)
        self.assertEqual((status, err), (0, ""))
        pack = self.read_out("packs", "demo", "pack.def")
        said = "The publisher states that this set is public and may be reused."
        self.assertIn('source        "No file of the set carries a statement in its header (master.xsd, types.xsd); '
                      "publisher's statement: %s\"\n" % said, pack)
        self.assertNotIn("File header of", pack)
        md = self.read_out("packs", "demo", "pack.md")
        for base in ("master.xsd", "types.xsd"):
            self.assertRegex(md, r"\| `%s` \| \d+ \| `[0-9a-f]{64}` \| \(no statement in the file; "
                                 r"publisher's statement\) %s \|" % (re.escape(base), re.escape(said)))

    def test_master_file_with_no_namespace_declares_the_roots_and_refers_to_imported_types(self):
        self.assertEqual(self.run_master("--public-statement", PUBLIC)[0], 0)
        pack = gtcheck.load_pack_file(self.path("out", "packs", "demo", "pack.def"),
                                      gtcheck.Model().load_dir(self.path("out", "model")))
        self.assertEqual([(k.name, k.root) for k in pack.kinds], [("msg", "msg")])
        self.assertEqual([(n.key, n.loc) for n in pack.common + pack.kinds[0].lines],
                         [("demo.name", "NAME/#text"), ("demo.level", "LEVEL/#text")])
        # no element of such a document is in a namespace: the vectors declare none
        vec = json.loads(self.read_out("packs", "demo", "vectors", "gen-1-msg-roundtrip.json"))
        self.assertTrue(vec["input"].startswith("<msg>"), vec["input"])
        md = self.read_out("packs", "demo", "pack.md")
        self.assertIn("The message roots are declared in `master.xsd`, which has no targetNamespace and imports", md)
        self.assertIn("- targetNamespace `urn:example:n`;", md)

    def test_master_file_that_imports_a_second_namespace_is_refused(self):
        status, _, err = self.run_master("--public-statement", PUBLIC, imports=("urn:example:n", "urn:example:other"))
        self.assertEqual(status, 1)
        self.assertIn("master.xsd: has no targetNamespace and imports ['urn:example:n', 'urn:example:other']; "
                      "the set's namespace is 'urn:example:n'", err)

    def test_notes_file_stands_after_the_shared_keys_and_before_requires(self):
        notes = self.path("notes.md")
        with open(notes, "w", encoding="utf-8") as fh:
            fh.write("## Notes\n\nA paragraph written by hand.\n\n\n")
        self.assertEqual(self.run_master("--public-statement", PUBLIC, "--notes-file", notes)[0], 0)
        md = self.read_out("packs", "demo", "pack.md")
        shared, mine, req = (md.index("## Mapped to shared keys"), md.index("## Notes\n\nA paragraph written by hand.\n\n## `requires`"),
                             md.index("## `requires`"))
        self.assertTrue(shared < mine < req)
        # without the option there is no such section, and --check still holds on the output
        self.assertEqual(self.run_master("--public-statement", PUBLIC, "--notes-file", notes, "--check")[0], 0)
        self.assertEqual(self.run_master("--public-statement", PUBLIC, "--check")[0], 1)


# --substitution-groups, --substitute, --decline-namespace and --skip. The
# schema has the shape NeTEx has: an abstract head with members (one declared
# without a type), a ref to the head that occurs once and one that repeats, a
# repeated choice of elements, a choice of complex branches, and references
# into a namespace whose files are not given.
SG_HEAD = ('<xs:schema xmlns:t="urn:example:t" xmlns:o="urn:example:o" xmlns:xs="http://www.w3.org/2001/XMLSchema" '
           'targetNamespace="urn:example:t" elementFormDefault="qualified">'
           '<!-- Distribution Statement A. Approved for public release: distribution is unlimited. -->\n'
           '<xs:import namespace="urn:example:o" schemaLocation="other.xsd"/>\n')
SG_BODY = """<xs:element name="Root" type="t:R"/>
<xs:element name="Thing" type="t:Thing" abstract="true"/>
<xs:element name="Stop" type="t:Stop" substitutionGroup="t:Thing"/>
<xs:element name="Line" substitutionGroup="t:Thing"/>
<xs:element name="Note" type="xs:string"/>
<xs:complexType name="Thing"><xs:sequence><xs:element name="Name" type="xs:string"/></xs:sequence>
  <xs:attribute name="id" type="xs:string"/></xs:complexType>
<xs:complexType name="Stop"><xs:complexContent><xs:extension base="t:Thing"><xs:sequence>
  <xs:element name="Lon" type="xs:double"/></xs:sequence></xs:extension></xs:complexContent></xs:complexType>
<xs:complexType name="Pick"><xs:choice>
  <xs:element name="Empty" type="t:Nothing"/>
  <xs:element name="Rows" type="t:Rows"/></xs:choice></xs:complexType>
<xs:complexType name="Nothing"><xs:sequence><xs:any/></xs:sequence></xs:complexType>
<xs:complexType name="Rows"><xs:sequence><xs:element name="Row" type="xs:int" maxOccurs="unbounded"/></xs:sequence></xs:complexType>
<xs:complexType name="Ext"><xs:complexContent><xs:extension base="o:Base"><xs:sequence>
  <xs:element name="Own" type="xs:string"/></xs:sequence></xs:extension></xs:complexContent></xs:complexType>
<xs:complexType name="R"><xs:sequence>
  <xs:element ref="t:Thing"/>
  <xs:element name="things"><xs:complexType><xs:sequence>
    <xs:element ref="t:Thing" maxOccurs="unbounded"/></xs:sequence></xs:complexType></xs:element>
  <xs:element name="mixed"><xs:complexType><xs:choice maxOccurs="unbounded">
    <xs:element ref="t:Note"/><xs:element ref="t:Stop"/></xs:choice></xs:complexType></xs:element>
  <xs:element name="Pick" type="t:Pick"/>
  <xs:element ref="o:Foreign" minOccurs="0"/>
  <xs:element name="Typed" type="o:Simple" minOccurs="0"/>
  <xs:element name="Ext" type="t:Ext"/>
  <xs:element name="Gone"><xs:complexType><xs:sequence><xs:element name="X" type="xs:string"/></xs:sequence></xs:complexType></xs:element>
</xs:sequence>
  <xs:attribute ref="o:lang"/>
  <xs:attributeGroup ref="o:Attrs"/>
</xs:complexType>"""
SG_DECLINE = ("--decline-namespace", "urn:example:o")


def sg_schema(body=SG_BODY, declined=("urn:example:o",), substitution=True, only=None):
    schema = x.Schema()
    schema.declined, schema.substitution = frozenset(declined), substitution
    schema.read_bytes((SG_HEAD + body + "\n</xs:schema>\n").encode("utf-8"), "t.xsd", {})
    if substitution:
        schema.resolve_member_types()
    schema.only = only or {}
    return schema


def leaf_choices(items):
    return {lf.locator: lf.choice for lf in x.all_leaves(items)}


class SubstitutionWalkTest(unittest.TestCase):
    def test_a_head_that_occurs_once_is_a_choice_of_its_members_the_first_in_vectors(self):
        items, _ = walk_root(sg_schema())
        ch = leaf_choices(items)
        # the abstract head itself is no candidate; Line has the head's type
        self.assertEqual({k: v[1] for k, v in ch.items() if k.split("/")[0] in ("Stop", "Line")},
                         {"Stop/@id": 0, "Stop/Name/#text": 0, "Stop/Lon/#text": 0,
                          "Line/@id": 1, "Line/Name/#text": 1})
        self.assertEqual(len({v[0] for k, v in ch.items() if k.split("/")[0] in ("Stop", "Line")}), 1)

    def test_a_head_that_repeats_is_one_group_per_member(self):
        items, _ = walk_root(sg_schema())
        self.assertIn(("things/Stop", ["@id", "Name/#text", "Lon/#text"]), outline(items))
        self.assertIn(("things/Line", ["@id", "Name/#text"]), outline(items))

    def test_a_repeated_choice_of_elements_is_one_group_per_element(self):
        items, skipped = walk_root(sg_schema())
        self.assertIn(("mixed/Note", ["#text"]), outline(items))
        self.assertIn(("mixed/Stop", ["@id", "Name/#text", "Lon/#text"]), outline(items))
        self.assertNotIn((x.R_REPEAT_GROUP, "mixed", "#mixed", "choice"), skipped)

    def test_the_first_branch_with_a_line_is_the_one_a_vector_holds(self):
        # Empty holds only a wildcard: Rows, the second branch, is on, its group with it
        items, _ = walk_root(sg_schema())
        rows = next(g for g in x.all_groups(items) if g.path == "Pick/Rows/Row")
        self.assertEqual(rows.choice[1], 0)

    def test_substitute_keeps_only_the_members_named(self):
        items, _ = walk_root(sg_schema(only={"Thing": ["Line"]}))
        tops = {lf.locator.split("/")[0] for lf in x.all_leaves(items)}
        self.assertIn("Line", tops)
        self.assertNotIn("Stop", tops)
        # one candidate is walked in place, not as a choice
        self.assertIsNone(leaf_choices(items)["Line/Name/#text"])

    def test_without_the_option_the_walk_is_as_before(self):
        items, skipped = walk_root(sg_schema(substitution=False))
        # the head is walked as the element it names; members are not considered
        self.assertIn("Thing/Name/#text", leaf_choices(items))
        self.assertFalse({"Stop", "Line"} & {lf.locator.split("/")[0] for lf in x.all_leaves(items)})
        reasons = {(r, p) for r, p, _, _ in skipped}
        self.assertIn((x.R_REPEAT_GROUP, "mixed"), reasons)
        self.assertIn((x.R_CHOICE, "Pick"), reasons)


class DeclinedNamespaceWalkTest(unittest.TestCase):
    def test_every_reference_into_a_declined_namespace_is_listed_not_mapped(self):
        _, skipped = walk_root(sg_schema())
        foreign = {(p, m) for r, p, o, m in skipped if r == x.R_FOREIGN}
        self.assertEqual(foreign, {("Foreign", "Foreign"), ("Typed", "Typed"), ("Ext", "base Base"),
                                   ("", "@lang"), ("", "@attributeGroup Attrs")})

    def test_the_own_content_of_a_type_with_a_declined_base_is_mapped(self):
        items, _ = walk_root(sg_schema())
        self.assertIn("Ext/Own/#text", leaf_choices(items))

    def test_without_the_option_a_reference_into_another_namespace_is_refused(self):
        with self.assertRaises(x.GenError) as caught:
            sg_schema(declined=())
        self.assertIn("is in namespace 'urn:example:o', which no file given here defines", caught.exception.message)


class SubstitutionRunTest(Workspace):
    def run_sg(self, *extra):
        with open(self.path("s.xsd"), "w", encoding="utf-8") as fh:
            fh.write(SG_HEAD + SG_BODY + "\n</xs:schema>\n")
        return support.run_main(x.main, [
            "--xsd", self.path("s.xsd"), "--format", "demo", "--module", "demo", "--out", self.out,
            "--model-dir", self.path("in", "model"), "--title", "Demo", "--message", "Root",
            "--names-file", self.path("out", "names", "demo.json")] + list(extra))

    def test_run_writes_a_pack_whose_vector_holds_first_branches_and_states_other_lists_absent(self):
        status, _, err = self.run_sg(*SG_DECLINE, "--substitution-groups", "--skip", "Gone")
        self.assertEqual((status, err), (0, ""))
        vec = json.loads(self.read_out("packs", "demo", "vectors", "gen-1-root-roundtrip.json"))
        self.assertIn("<Stop ", vec["input"])
        self.assertNotIn("<Line", vec["input"].split("<things>")[0])
        self.assertNotIn("<Gone>", vec["input"])
        md = self.read_out("packs", "demo", "pack.md")
        for heading in ("## Declined namespaces", "## Substitution groups", "## Left out of this pack"):
            self.assertIn(heading, md)
        self.assertIn("| %s |" % x.R_SKIP, md)
        self.assertEqual(self.run_sg(*SG_DECLINE, "--substitution-groups", "--skip", "Gone", "--check")[0], 0)

    def test_a_list_in_a_branch_the_vector_does_not_hold_is_stated_absent(self):
        body = SG_BODY.replace('<xs:element name="Empty" type="t:Nothing"/>',
                               '<xs:element name="First" type="xs:string"/>')
        with open(self.path("s.xsd"), "w", encoding="utf-8") as fh:
            fh.write(SG_HEAD + body + "\n</xs:schema>\n")
        status, _, err = support.run_main(x.main, [
            "--xsd", self.path("s.xsd"), "--format", "demo", "--module", "demo", "--out", self.out,
            "--model-dir", self.path("in", "model"), "--title", "Demo", "--message", "Root",
            "--names-file", self.path("out", "names", "demo.json"), *SG_DECLINE, "--substitution-groups"])
        self.assertEqual((status, err), (0, ""))
        vec = json.loads(self.read_out("packs", "demo", "vectors", "gen-1-root-roundtrip.json"))
        self.assertEqual(vec["model"]["demo.pick_rows_row.#"], "absent")
        self.assertNotIn("<Rows>", vec["input"])

    def test_substitute_is_refused_without_the_option_and_for_a_non_member(self):
        status, _, err = self.run_sg(*SG_DECLINE, "--substitute", "Thing=Stop")
        self.assertEqual(status, 1)
        self.assertIn("--substitute needs --substitution-groups", err)
        status, _, err = self.run_sg(*SG_DECLINE, "--substitution-groups", "--substitute", "Thing=Note")
        self.assertEqual(status, 1)
        self.assertIn("--substitute Thing: Note is not a member of its substitution group", err)

    def test_an_import_of_a_declined_namespace_needs_no_file(self):
        status, _, err = self.run_sg("--substitution-groups")
        self.assertEqual(status, 1)
        self.assertIn("which no file given here defines", err)
        self.assertEqual(self.run_sg(*SG_DECLINE)[0], 0)


class DeepWalkTest(unittest.TestCase):
    DEEP = ('<xs:element name="Root" type="t:L0"/>\n' + "".join(
        '<xs:complexType name="L%d"><xs:sequence><xs:element name="E%d" type="t:L%d"/>'
        '<xs:element name="V%d" type="xs:string"/></xs:sequence></xs:complexType>\n' % (i, i, i + 1, i)
        for i in range(12)) + '<xs:complexType name="L12"><xs:sequence><xs:element name="V12" type="xs:string"/>'
        '</xs:sequence></xs:complexType>')

    def test_a_depth_above_the_default_walks_deeper_and_names_the_rest_the_cap(self):
        schema = schema_of(self.DEEP)
        _, skipped = walk_root(schema)
        self.assertIn(x.R_DEPTH, {r for r, _, _, _ in skipped})
        items, skipped = walk_root(schema, max_depth=10)
        self.assertEqual(max(lf.depth for lf in x.all_leaves(items)), 10)
        reasons = {r for r, _, _, _ in skipped}
        self.assertNotIn(x.R_DEPTH, reasons)
        self.assertIn(x.R_CAP, reasons)

    def test_the_depth_asked_is_bounded_by_the_ceiling(self):
        w = x.walk_messages(schema_of(self.DEEP), ["Root"], 99, x.MAX_DEPTH)
        self.assertEqual(w.depth, x.DEPTH_CEILING)


if __name__ == "__main__":
    unittest.main()
