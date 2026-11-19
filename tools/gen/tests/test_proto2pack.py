"""Tests of tools/gen/proto2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_proto2pack*.py'

The fixture under fixtures/proto2pack/ is a schema written for these tests: a
depot that reports parcels. Two runs are made over it, as tools/gen/proto2pack-run.sh
makes them over the real schemas: `depot` (kinds from a oneof) and then
`depot-link` (a proto2 union envelope that extends the module the first run wrote
and takes its names).
"""
import support

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import gtcheck
import proto2pack as p2p

FIXTURE = os.path.join(support.FIXTURES, "proto2pack")
INPUT = os.path.join(FIXTURE, "input")
EXPECTED = os.path.join(FIXTURE, "expected")
INPUT_FILES = sorted(support.tree(INPUT))
GENERATOR = os.path.join(support.GEN, "proto2pack.py")


def depot_args(root):
    """The first run: envelope with a oneof, hand bindings, a value table, a
    constant, vectors to and from three other packs."""
    def at(*parts):
        return os.path.join(root, *parts)
    return [
        "--proto", at("proto", "depot.proto"), at("proto", "depot_types.proto"), at("proto", "depot_options.proto"),
        "--envelope", "Envelope", "--format", "depot", "--module", "depot", "--out", root,
        "--mandatory-option", "is_mandatory",
        "--source", "The depot test schema: three .proto files written for the proto2pack tests",
        "--source", "No license applies: the schema is part of this repository",
        "--map", "2=time_ms", "--map", "10.1=uid", "--map", "10.2.1=lat", "--map", "10.2.2=lon",
        "--map", "10.2.3=hae", "--map", "10.19=motion.vel_east", "--map", "10.20=motion.vel_north",
        "--bind", "parcel_report:10.23.1=type:pstring:parcel-type",
        "--table", "parcel-type:BOX=a-box", "--table", "parcel-type:TUBE=a-tube", "--table", "parcel-type:BOX=a-crate",
        "--const", "parcel_report:10.2.4=1",
        "--default-kind", "parcel_report", "--default-requires", "lat", "lon",
        "--pack-version", "0.3.0",
        "--names-file", at("names", "depot.json"),
        "--cross", at("packs", "geojson", "pack.def") + "=" + at("packs", "geojson", "vectors",
                                                                 "01-point-roundtrip.json") + ":input",
        "--cross-text", at("packs", "geojson", "pack.def"), "--cross-text", at("packs", "tag-xml", "pack.def"),
        "--cross-text", at("packs", "slip", "pack.def"),
        "--cross-omit", "10.19", "--cross-omit", "10.20",
        "--notes-file", at("notes", "depot.md")]


def link_args(root):
    """The second run: every singular message field of the envelope is a kind,
    one member stands beside the others, the module of the first run is
    extended and its names are taken under field 2."""
    def at(*parts):
        return os.path.join(root, *parts)
    return [
        "--proto", at("proto", "depot_link.proto"), at("proto", "depot.proto"), at("proto", "depot_types.proto"),
        at("proto", "depot_options.proto"),
        "--envelope", "Frame", "--kinds-from-fields", "--common-member", "control", "--no-comments",
        "--format", "depot-link", "--module", "depot", "--out", root,
        "--max-depth", "8",
        "--module-base", at("model", "depot.def"), "--module-version", "0.2.0",
        "--names-from", at("names", "depot.json") + "=2", "--names-file", at("names", "depot-link.json"),
        "--source", "The depot test schema: four .proto files written for the proto2pack tests",
        "--map", "2.2=time_ms", "--map", "2.10.1=uid", "--map", "2.10.2.1=lat", "--map", "2.10.2.2=lon",
        "--map", "2.10.2.3=hae",
        "--default-kind", "event", "--default-requires", "lat", "lon",
        "--cross-text", at("packs", "geojson", "pack.def")]


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="proto2pack-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, rel, text):
        path = os.path.join(self.tmp, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return path

    def read(self, rel):
        with open(os.path.join(self.tmp, *rel.split("/")), encoding="utf-8") as fh:
            return fh.read()

    def run_ok(self, argv, **kwargs):
        status, out, err = support.run_main(lambda a: p2p.main(a, **kwargs), argv)
        self.assertEqual(status, 0, err)
        return out, err

    def run_refused(self, argv, **kwargs):
        status, _, err = support.run_main(lambda a: p2p.main(a, **kwargs), argv)
        self.assertEqual(status, 1, err)
        self.assertEqual(len(err.strip().split("\n")), 1, "one line on stderr: %r" % err)
        self.assertTrue(err.startswith("proto2pack: "), err)
        return err


class FixtureCase(TempDirCase):
    """A writable copy of the fixture input in `self.tmp`."""

    def setUp(self):
        super().setUp()
        support.copy_tree(INPUT, self.tmp)

    def run_both(self):
        self.run_ok(depot_args(self.tmp))
        self.run_ok(link_args(self.tmp))


# --------------------------------------------------------------------------
# the fixture, end to end
# --------------------------------------------------------------------------

class GoldenTest(FixtureCase):
    def test_the_two_fixture_runs_write_the_expected_tree(self):
        self.run_both()
        support.assert_same_tree(self, EXPECTED, self.tmp, ignore=INPUT_FILES)

    def test_a_second_pass_over_its_own_output_changes_no_byte_and_no_file(self):
        self.run_both()
        first = support.tree(self.tmp)
        self.run_both()
        self.assertEqual(support.tree(self.tmp), first)

    def test_running_the_last_run_again_changes_nothing(self):
        self.run_both()
        first = support.tree(self.tmp)
        self.run_ok(link_args(self.tmp))
        self.assertEqual(support.tree(self.tmp), first)

    def test_the_run_report_on_stdout_counts_what_was_written(self):
        out, _ = self.run_ok(depot_args(self.tmp))
        report = json.loads(out)
        self.assertEqual(report["format"], "depot")
        self.assertEqual([k["name"] for k in report["kinds"]], ["receipt", "parcel_report", "heartbeat"])
        self.assertEqual(report["kinds_without_fields"], ["heartbeat"])
        self.assertEqual(report["groups"], 10)          # 4 in receipt, 6 in parcel_report
        self.assertEqual(report["groups_nested"], 6)    # delays_s, notes and scans of each list of Stop
        self.assertEqual(report["vector_items_per_group"], 2)
        self.assertEqual(report["limits_lowered"], [])

    def test_the_proto_files_may_be_given_in_any_order(self):
        self.run_both()
        first = support.tree(self.tmp)
        for args in (depot_args(self.tmp), link_args(self.tmp)):
            i, j = args.index("--proto") + 1, args.index("--envelope")
            self.run_ok(args[:i] + args[i:j][::-1] + args[j:])
        self.assertEqual(support.tree(self.tmp), first)

    def test_the_output_does_not_depend_on_the_hash_seed(self):
        trees = []
        for seed in ("1", "4242"):
            root = os.path.join(self.tmp, "seed-" + seed)
            support.copy_tree(INPUT, root)
            for args in (depot_args(root), link_args(root)):
                done = subprocess.run([sys.executable, "-I", GENERATOR] + args, capture_output=True, text=True,
                                      env=dict(os.environ, PYTHONHASHSEED=seed))
                self.assertEqual(done.returncode, 0, done.stderr)
            trees.append(support.tree(root))
        self.assertEqual(trees[0], trees[1])
        support.assert_same_tree(self, EXPECTED, os.path.join(self.tmp, "seed-1"), ignore=INPUT_FILES)


class CheckModeTest(FixtureCase):
    def test_check_passes_on_fresh_output_and_writes_nothing(self):
        self.run_both()
        before = support.tree(self.tmp)
        status, _, err = support.run_main(p2p.main, link_args(self.tmp) + ["--check"])
        self.assertEqual(status, 0, err)
        self.assertIn("--check: ok", err)
        self.assertEqual(support.tree(self.tmp), before)

    def test_check_fails_and_names_the_file_after_one_byte_changes(self):
        self.run_both()
        rel = "packs/depot-link/pack.def"
        self.write(rel, self.read(rel).replace("pvarint", "psint  ", 1))
        before = support.tree(self.tmp)
        status, _, err = support.run_main(p2p.main, link_args(self.tmp) + ["--check"])
        self.assertEqual(status, 1)
        self.assertIn("proto2pack: --check: packs/depot-link/pack.def differs", err)
        self.assertEqual(support.tree(self.tmp), before)

    def test_check_names_a_changed_names_file_and_a_stray_generated_vector(self):
        self.run_both()
        names = json.loads(self.read("names/depot-link.json"))
        self.write("names/depot-link.json", json.dumps(names, indent=4, sort_keys=True) + "\n")   # other bytes
        self.write("packs/depot-link/vectors/gen-99-left-over.json", "{}\n")
        status, _, err = support.run_main(p2p.main, link_args(self.tmp) + ["--check"])
        self.assertEqual(status, 1)
        self.assertIn("names/depot-link.json differs", err)
        self.assertIn("packs/depot-link/vectors/gen-99-left-over.json is not written by the generator", err)

    def test_check_on_a_tree_with_no_output_lists_the_missing_files_and_writes_nothing(self):
        before = support.tree(self.tmp)
        status, _, err = support.run_main(p2p.main, depot_args(self.tmp) + ["--check"])
        self.assertEqual(status, 1)
        for rel in ("model/depot.def", "packs/depot/pack.def", "packs/depot/pack.md", "names/depot.json",
                    "packs/depot/vectors/gen-03-parcel_report-roundtrip.json",
                    "packs/geojson/vectors/gen-geojson-to-depot.json"):
            self.assertIn("%s is missing" % rel, err)
        self.assertEqual(support.tree(self.tmp), before)


class LoadedOutputTest(FixtureCase):
    """The expected files are not the only witness: gtcheck loads what was
    written, and the facts below are stated here by hand."""

    def setUp(self):
        super().setUp()
        self.run_both()
        self.model = gtcheck.Model().load_dir(os.path.join(self.tmp, "model"))

    def load(self, fmt):
        return gtcheck.load_pack_file(os.path.join(self.tmp, "packs", fmt, "pack.def"), self.model)

    def test_the_depot_pack_has_its_kinds_in_encode_order(self):
        pack = self.load("depot")
        self.assertEqual(pack.wire, "protobuf")
        self.assertEqual(pack.uses, ["core", "depot", "motion"])
        # a kind with fields, then the default kind, then the kind with no field
        self.assertEqual([k.name for k in pack.kinds], ["receipt", "parcel_report", "heartbeat"])
        self.assertEqual([[(w.loc, w.value) for w in gtcheck.walk(k.lines, "when")] for k in pack.kinds],
                         [[("11", "present")], [("10", "present")], [("12", "present")]])
        self.assertEqual([k.requires for k in pack.kinds],
                         [["depot.receipt_parcel_id"], ["lat", "lon"], ["depot.sender"]])

    def test_a_mapped_path_has_the_shared_key_first_and_the_raw_key_second(self):
        report = self.load("depot").kinds[1]
        at = [(f.key, f.tr) for f in report.lines if f.d == "field" and f.loc == "10.2.1"]
        self.assertEqual(at, [("lat", "pdouble"), ("depot.position_latitude", "pdouble")])

    def test_scalar_types_get_the_transform_of_their_wire_type(self):
        report = self.load("depot").kinds[1]
        tr = {f.loc: f.tr for f in report.lines if f.d == "field"}
        self.assertEqual(tr["10.2.3"], "pfloat")        # float height_m
        self.assertEqual(tr["10.7"], "psint")           # sint64 weight_g
        self.assertEqual(tr["10.3"], "pvarint")         # enum Handling
        self.assertEqual(tr["10.18"], "pvarint")        # bool insured

    def test_a_repeated_message_is_a_group_with_nested_groups(self):
        report = self.load("depot").kinds[1]
        groups = {g.key: g for g in report.lines if g.d == "group"}
        stops = groups["depot.parcel_report_stops"]
        self.assertEqual(stops.path, (10, 4))
        self.assertEqual([(g.key, g.path) for g in stops.body if g.d == "group"],
                         [("depot.stop_delays_s", (3,)), ("depot.stop_notes", (4,)), ("depot.stop_scans", (6,))])
        delays = next(g for g in stops.body if g.key == "depot.stop_delays_s")
        self.assertEqual([(f.key, f.path, f.tr) for f in delays.body], [("depot.stop_delays_s_item", (), "psint")])

    def test_two_lists_of_one_message_type_hold_the_same_item_keys(self):
        pack = self.load("depot")
        route = next(g for g in pack.kinds[0].lines if g.d == "group" and g.key == "depot.receipt_route")
        stops = next(g for g in pack.kinds[1].lines if g.d == "group" and g.key == "depot.parcel_report_stops")
        self.assertEqual([f.args for f in gtcheck.walk(route.body)], [f.args for f in gtcheck.walk(stops.body)])

    def test_the_hand_binding_the_table_and_the_constant_are_lines_of_their_kind(self):
        pack = self.load("depot")
        report = pack.kinds[1]
        bound = next(f for f in report.lines if f.d == "field" and f.loc == "10.23.1")
        self.assertEqual((bound.key, bound.tr, bound.via), ("type", "pstring", "parcel-type"))
        self.assertEqual(pack.tables["parcel-type"], [("BOX", "a-box"), ("TUBE", "a-tube"), ("BOX", "a-crate")])
        self.assertEqual([(c.loc, c.value) for c in report.lines if c.d == "const"], [("10.2.4", "1")])
        # the repeated message the binding reads through is not also a group
        self.assertNotIn("depot.parcel_report_classification", [g.key for g in report.lines if g.d == "group"])

    def test_two_field_names_that_sanitize_to_one_name_are_two_keys(self):
        receipt = self.load("depot").kinds[0]
        keys = {f.loc: f.key for f in receipt.lines if f.d == "field"}
        self.assertEqual(keys["11.2"], "depot.receipt_signed_by")           # signed_by
        self.assertEqual(keys["11.5"], "depot.receipt_signed_by_at_11_5")   # signedBy

    def test_what_no_transform_carries_is_not_mapped(self):
        locs = {n.loc for n in gtcheck.walk(self.load("depot").kinds[1].lines) if n.loc}
        for path in ("10.8", "10.9", "10.13", "10.16"):     # map, bytes, fixed32, the message inside itself
            self.assertNotIn(path, locs)

    def test_the_union_envelope_has_a_kind_per_member_and_the_common_member_in_the_common_lines(self):
        pack = self.load("depot-link")
        self.assertEqual([k.name for k in pack.kinds], ["ack", "event", "control"])
        self.assertEqual([f.loc for f in pack.common if f.d == "field"], ["1.1", "1.2", "5"])
        self.assertEqual(pack.kinds[2].lines[0].args, ["1", "present"])
        self.assertEqual([n.d for n in pack.kinds[2].lines], ["when"])
        self.assertEqual(pack.kinds[2].requires, ["depot.control_min_version"])

    def test_the_second_pack_uses_the_keys_the_first_pack_named(self):
        depot = {f.loc: f.key for f in gtcheck.walk(self.load("depot").kinds[1].lines, "field")
                 if f.key.startswith("depot.")}
        link = {f.loc: f.key for f in gtcheck.walk(self.load("depot-link").kinds[1].lines, "field")
                if f.key.startswith("depot.")}
        for loc, key in depot.items():
            if loc.startswith("10.") and loc != "10.23.1":
                self.assertEqual(link["2." + loc], key)

    def test_the_extended_module_keeps_the_lines_of_the_first_run_and_appends(self):
        self.run_ok(depot_args(self.tmp))
        first = [ln for ln in self.read("model/depot.def").split("\n") if ln.startswith(("key", "list"))]
        self.run_ok(link_args(self.tmp))
        both = [ln for ln in self.read("model/depot.def").split("\n") if ln.startswith(("key", "list"))]
        self.assertEqual(both[:len(first)], first)
        added = self.model.modules["depot"]
        self.assertEqual(added.keys["control_min_version"], "int")
        self.assertIn("hops", added.lists)

    def test_no_comment_of_the_schema_reaches_a_run_with_no_comments(self):
        text = self.read("packs/depot-link/pack.md") + self.read("packs/depot-link/pack.def")
        self.assertNotIn("degrees north", text)
        self.assertIn("degrees north", self.read("packs/depot/pack.md"))

    def test_every_generated_vector_states_bytes_the_codec_reproduces(self):
        for fmt in ("depot", "depot-link"):
            rel = "packs/%s/pack.def" % fmt
            pack = p2p.load_protobuf_pack(self.read(rel), self.model, rel)
            vec_dir = os.path.join(self.tmp, "packs", fmt, "vectors")
            names = sorted(n for n in os.listdir(vec_dir) if "roundtrip" in n)
            self.assertTrue(names)
            for name in names:
                vec = json.loads(self.read("packs/%s/vectors/%s" % (fmt, name)))
                ent, kind = p2p.engine_decode(pack, bytes.fromhex(vec["input"]))
                self.assertEqual(kind, vec["model"]["@kind"], name)
                self.assertEqual(p2p.engine_encode(pack, ent, kind)[0].hex(), vec["expect"], name)

    def test_the_oneof_variant_vector_sets_the_other_member(self):
        first = json.loads(self.read("packs/depot-link/vectors/gen-03-event-roundtrip.json"))["model"]
        other = json.loads(self.read("packs/depot-link/vectors/gen-03-event-roundtrip-oneof1.json"))["model"]
        self.assertIn("depot.parcel_report_parcel_id", first)
        self.assertNotIn("depot.receipt_parcel_id", first)
        self.assertIn("depot.receipt_parcel_id", other)
        self.assertIn("depot.receipt_route.#", other)       # the group the variant brings in

    def test_a_vector_from_another_format_carries_the_shared_keys(self):
        vec = json.loads(self.read("packs/geojson/vectors/gen-geojson-to-depot.json"))
        self.assertEqual((vec["from"], vec["to"]), ("geojson", "depot"))
        self.assertEqual(vec["model"], {"uid": "P-17", "type": "a-box", "time_ms": "1700000000000",
                                        "lat": "47.25", "lon": "8.5", "hae": "410"})
        rel = "packs/depot/pack.def"
        pack = p2p.load_protobuf_pack(self.read(rel), self.model, rel)
        ent, kind = p2p.engine_decode(pack, bytes.fromhex(vec["expect"]))
        self.assertEqual(kind, "parcel_report")
        self.assertEqual((ent["uid"], ent["lat"], ent["lon"], ent["type"]), ("P-17", 47.25, 8.5, "a-box"))
        self.assertEqual(ent["depot.position_frame"], 1)     # the constant


# --------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------

class RefusalTest(FixtureCase):
    def refuse_schema(self, text):
        path = self.write("proto/broken.proto", text)
        before = support.tree(self.tmp)
        err = self.run_refused(["--proto", path, "--envelope", "Note", "--format", "note", "--module", "note",
                                "--out", self.tmp, "--source", "a test"])
        self.assertEqual(support.tree(self.tmp), before, "a refused input writes nothing")
        return err, path

    def test_a_field_with_no_number_names_the_file_and_the_line(self):
        err, path = self.refuse_schema('syntax = "proto3";\nmessage Note {\n  string text = ;\n}\n')
        self.assertEqual(err, "proto2pack: %s:3: expected a number, found ';'\n" % path)

    def test_a_missing_semicolon_names_the_line_of_the_next_token(self):
        err, path = self.refuse_schema('syntax = "proto3";\nmessage Note {\n  string text = 1\n  string more = 2;\n}\n')
        self.assertEqual(err, "proto2pack: %s:4: expected ';', found 'string'\n" % path)

    def test_a_message_that_is_not_closed_is_refused_at_the_end_of_the_file(self):
        err, path = self.refuse_schema('syntax = "proto3";\nmessage Note {\n  string text = 1;\n')
        self.assertIn("%s:3: " % path, err)
        self.assertIn("the file ends inside a statement", err)

    def test_a_character_no_token_starts_with_names_the_line(self):
        err, path = self.refuse_schema('syntax = "proto3";\n\nmessage Note { string text = 1; } @\n')
        self.assertIn("%s:3: cannot tokenise" % path, err)

    def test_a_type_that_is_not_defined_names_the_field_line(self):
        err, path = self.refuse_schema('syntax = "proto3";\nmessage Note {\n  string text = 1;\n  Missing m = 2;\n}\n')
        self.assertEqual(err, "proto2pack: %s:4: Note.m: type Missing is not defined in the given files\n" % path)

    def test_an_import_that_is_not_given_names_the_importing_file(self):
        err, path = self.refuse_schema('syntax = "proto3";\nimport "elsewhere.proto";\nmessage Note { string text = 1; }\n')
        self.assertEqual(err, "proto2pack: %s: imports elsewhere.proto, which is not among the given files\n" % path)

    def test_a_proto_file_that_does_not_exist_is_one_line(self):
        err = self.run_refused(["--proto", os.path.join(self.tmp, "none.proto"), "--envelope", "Note",
                                "--format", "note", "--module", "note", "--out", self.tmp, "--source", "a test"])
        self.assertIn("none.proto", err)

    def test_an_envelope_that_is_not_in_the_schema_is_refused(self):
        args = depot_args(self.tmp)
        args[args.index("Envelope")] = "Parcel"
        self.assertIn("envelope Parcel matches 0 messages", self.run_refused(args))

    def test_a_map_option_for_a_path_the_walk_does_not_reach_is_refused_and_nothing_is_written(self):
        before = support.tree(self.tmp)
        err = self.run_refused(depot_args(self.tmp) + ["--map", "10.99=course"])
        self.assertIn("--map paths that are not mapped leaves of the schema: ['10.99']", err)
        self.assertEqual(support.tree(self.tmp), before)

    def test_a_bind_option_on_a_walked_path_is_refused(self):
        err = self.run_refused(depot_args(self.tmp) + ["--bind", "parcel_report:10.3=type:pstring"])
        self.assertIn("the walk maps that path; use --map", err)

    def test_a_bind_table_with_no_table_line_is_refused(self):
        args = depot_args(self.tmp)
        while "--table" in args:
            del args[args.index("--table"):args.index("--table") + 2]
        self.assertIn("--bind names table parcel-type, which has no --table line", self.run_refused(args))

    def test_a_map_key_no_module_declares_is_refused_by_the_load_check_with_file_and_line(self):
        args = depot_args(self.tmp)
        args[args.index("10.1=uid")] = "10.1=owner"
        err = self.run_refused(args)
        self.assertRegex(err, r"^proto2pack: packs/depot/pack\.def:\d+: undeclared-key: ")

    def test_a_map_key_of_the_wrong_type_is_refused_by_the_load_check(self):
        args = depot_args(self.tmp)
        args[args.index("10.1=uid")] = "10.1=lat"       # a string field on a float key
        self.assertRegex(self.run_refused(args), r"packs/depot/pack\.def:\d+: key-type-mismatch: ")

    def test_a_derived_key_the_other_pack_writes_is_refused_until_the_path_is_omitted(self):
        args = [a for a in depot_args(self.tmp) if a not in ("--cross-omit", "10.19", "10.20")]
        err = self.run_refused(args)
        self.assertIn("the engine would derive course speed_ms, which that pack writes", err)
        self.assertIn("--cross-omit", err)

    def test_a_names_file_that_is_not_json_names_the_file(self):
        path = self.write("names/depot.json", "{not json\n")
        self.assertIn("%s:1: --names-file is not JSON" % path, self.run_refused(depot_args(self.tmp)))

    def test_common_member_without_kinds_from_fields_is_refused(self):
        err = self.run_refused(depot_args(self.tmp) + ["--common-member", "sender"])
        self.assertIn("--common-member needs --kinds-from-fields", err)

    def test_a_usage_error_is_exit_status_2(self):
        status, _, err = support.run_main(p2p.main, ["--proto", "x.proto"])
        self.assertEqual(status, 2)
        self.assertIn("required", err)


# --------------------------------------------------------------------------
# the .proto parser
# --------------------------------------------------------------------------

class ParserTest(TempDirCase):
    def schema(self, text, name="t.proto", **kwargs):
        return p2p.load_schema([self.write(name, text)], **kwargs)

    def test_comments_are_skipped_and_a_field_keeps_the_comment_that_belongs_to_it(self):
        s = self.schema('''syntax = "proto3";
/* a block comment with a brace } and
   a second line */
message Note {
  // above, line one
  // above, line two
  string text = 1;
  int32 count = 2;  // on the line
  /// a documentation comment
  bool done = 3; /* a block comment is never a field comment */
  string plain = 4;
}
''')
        fields = {f.name: f for f in s.messages["Note"].fields}
        self.assertEqual(fields["text"].comment, "above, line one above, line two")
        self.assertEqual(fields["count"].comment, "on the line")
        self.assertEqual(fields["done"].comment, "a documentation comment")
        self.assertEqual(fields["plain"].comment, "")
        self.assertEqual([f.line for f in s.messages["Note"].fields], [7, 8, 10, 11])

    def test_a_comment_marker_inside_a_string_is_part_of_the_string(self):
        s = self.schema('syntax = "proto3";\noption go_package = "a//b; }";\nmessage Note { string text = 1; }\n')
        self.assertEqual([f.name for f in s.messages["Note"].fields], ["text"])

    def test_with_comments_off_no_field_has_a_comment(self):
        s = self.schema('syntax = "proto3";\nmessage Note {\n  string text = 1; // said\n}\n', comments=False)
        self.assertEqual(s.messages["Note"].fields[0].comment, "")

    def test_nested_messages_and_enums_are_named_with_their_scope(self):
        s = self.schema('''syntax = "proto3";
package shop.v1;
message Order {
  message Line {
    enum Unit { EACH = 0; BOX = 0x0C; }
    message Price { int64 cents = 1; }
    Unit unit = 1;
    Price price = 2;
  }
  repeated Line lines = 1;
}
''')
        self.assertEqual(sorted(s.messages), ["shop.v1.Order", "shop.v1.Order.Line", "shop.v1.Order.Line.Price"])
        self.assertEqual(s.enums["shop.v1.Order.Line.Unit"].values, [("EACH", 0), ("BOX", 12)])
        line = s.messages["shop.v1.Order.Line"]
        self.assertEqual([(f.name, f.kind, f.ref.full) for f in line.fields],
                         [("unit", "enum", "shop.v1.Order.Line.Unit"), ("price", "message", "shop.v1.Order.Line.Price")])
        lines = s.messages["shop.v1.Order"].fields[0]
        self.assertEqual((lines.label, lines.kind, lines.ref.full), ("repeated", "message", "shop.v1.Order.Line"))

    def test_a_type_name_is_resolved_in_the_innermost_scope_first(self):
        s = self.schema('''syntax = "proto3";
package p;
message Size { int32 outer = 1; }
message Box {
  message Size { int32 inner = 1; }
  Size near = 1;
  .p.Size far = 2;
  p.Size also_far = 3;
}
''')
        refs = {f.name: f.ref.full for f in s.messages["p.Box"].fields}
        self.assertEqual(refs, {"near": "p.Box.Size", "far": "p.Size", "also_far": "p.Size"})

    def test_oneof_members_are_fields_of_the_message_that_know_their_oneof(self):
        s = self.schema('''syntax = "proto3";
message Shape {
  string name = 1;
  oneof form {
    option (rule) = true;
    double radius = 2;
    double side = 3;
  }
  oneof color { string named = 4; uint32 rgb = 5; }
}
''')
        shape = s.messages["Shape"]
        self.assertEqual(shape.oneofs, ["form", "color"])
        self.assertEqual([(f.name, f.oneof) for f in shape.fields],
                         [("name", None), ("radius", "form"), ("side", "form"), ("named", "color"), ("rgb", "color")])

    def test_a_map_field_is_kept_as_a_repeated_field_of_kind_map(self):
        s = self.schema('syntax = "proto3";\nmessage Bag { map<string, int32> counts = 1; string id = 2; }\n')
        counts = s.messages["Bag"].fields[0]
        self.assertEqual((counts.name, counts.number, counts.kind, counts.label, counts.type),
                         ("counts", 1, "map", "repeated", "map<string,int32>"))

    def test_reserved_extensions_options_extend_and_service_are_skipped(self):
        s = self.schema('''syntax = "proto2";
option optimize_for = SPEED;
message Old {
  option deprecated = true;
  reserved 2, 15, 9 to 11;
  reserved "gone", "also_gone";
  extensions 100 to 199;
  extend Other { optional int32 extra = 100; }
  optional string kept = 1 [default = "x;y", (note) = { text: "a ] b" }];
  required int32 needed = 3;
  optional group Legacy = 4 { optional string inside = 1; }
  optional string after = 5;
}
message Other { extensions 100 to max; }
extend Other { optional string more = 101; }
service Lookup { rpc Get (Old) returns (Other) { option idempotency_level = NO_SIDE_EFFECTS; } }
enum Mode { option allow_alias = true; OFF = 0; ON = 1; reserved 5; }
''')
        old = s.messages["Old"]
        self.assertEqual([(f.name, f.number, f.kind) for f in old.fields],
                         [("kept", 1, "scalar"), ("needed", 3, "scalar"), ("Legacy", 4, "group"), ("after", 5, "scalar")])
        self.assertEqual([f.mandatory for f in old.fields], [False, True, False, False])
        self.assertEqual(s.enums["Mode"].values, [("OFF", 0), ("ON", 1)])
        self.assertEqual(sorted(s.messages), ["Old", "Other"])

    def test_the_mandatory_option_marks_a_field_only_when_it_is_true(self):
        text = '''syntax = "proto3";
message Note {
  string a = 1 [(rule) = {is_mandatory: true}];
  string b = 2 [(rule) = {is_mandatory: false}];
  string c = 3 [(rule) = {not_is_mandatory: true}];
  string d = 4;
}
'''
        marked = [f.mandatory for f in self.schema(text, mandatory_option="is_mandatory").messages["Note"].fields]
        self.assertEqual(marked, [True, False, False, False])
        unmarked = [f.mandatory for f in self.schema(text, name="u.proto").messages["Note"].fields]
        self.assertEqual(unmarked, [False, False, False, False])

    def test_the_well_known_timestamp_needs_no_file(self):
        s = self.schema('syntax = "proto3";\nimport "google/protobuf/timestamp.proto";\n'
                        'message Note { google.protobuf.Timestamp at = 1; }\n')
        at = s.messages["Note"].fields[0]
        self.assertEqual([(f.name, f.type) for f in at.ref.fields], [("seconds", "int64"), ("nanos", "int32")])

    def test_an_import_is_resolved_among_the_given_files_by_file_name(self):
        a = self.write("dir/a.proto", 'syntax = "proto3";\npackage p;\nimport "some/where/b.proto";\nmessage A { B b = 1; }\n')
        b = self.write("b.proto", 'syntax = "proto3";\npackage p;\nmessage B { string x = 1; }\n')
        for paths in ([a, b], [b, a]):
            s = p2p.load_schema(paths)
            self.assertEqual(s.messages["p.A"].fields[0].ref.full, "p.B")

    def test_an_error_carries_the_file_and_the_line_apart_from_the_message(self):
        path = self.write("bad.proto", 'syntax = "proto3";\nmessage Note {\n  string = 1;\n}\n')
        with self.assertRaises(p2p.GenError) as caught:
            p2p.load_schema([path])
        self.assertEqual((caught.exception.file, caught.exception.line), (path, 3))
        self.assertEqual(str(caught.exception), "%s:3: expected '=', found '1'" % path)


class SnakeTest(unittest.TestCase):
    def test_a_capital_after_a_lower_case_letter_or_a_digit_starts_a_word(self):
        self.assertEqual(p2p.snake("parcelId"), "parcel_id")
        self.assertEqual(p2p.snake("v2Id"), "v2_id")
        self.assertEqual(p2p.snake("TakMessage"), "tak_message")

    def test_a_run_of_capitals_is_one_word(self):
        self.assertEqual(p2p.snake("HTTPServer"), "httpserver")
        self.assertEqual(p2p.snake("xmlURL"), "xml_url")

    def test_a_character_a_key_name_cannot_hold_becomes_an_underscore(self):
        self.assertEqual(p2p.snake("a-b.c d"), "a_b_c_d")
        self.assertEqual(p2p.snake("already_snake_1"), "already_snake_1")


# --------------------------------------------------------------------------
# the plan: keys, kinds, limits
# --------------------------------------------------------------------------

class PlanCase(TempDirCase):
    def plan(self, text, *args, envelope="Top", budgets=p2p.DEFAULT_BUDGETS):
        path = self.write("schema.proto", text)
        opts = p2p.argument_parser().parse_args(
            ["--proto", path, "--envelope", envelope, "--format", "f", "--module", "m", "--out", self.tmp,
             "--source", "a test"] + list(args))
        return p2p.make_plan(p2p.load_schema(opts.proto, opts.mandatory_option), opts, budgets)

    @staticmethod
    def keys(plan):
        """{field-number path: key} of every leaf outside a group."""
        return {p2p.dotted(l.nums): l.key for l in plan.all_leaves}


TWO_KINDS = '''syntax = "proto3";
message Point { double x = 1; double y = 2; }
message Top {
  string id = 1;
  oneof body { Report report = 2; Notice notice = 3; }
}
message Report { string title = 1; Point place = 2; string titleText = 3; string title_text = 4; }
message Notice { string title = 1; Point place = 2; }
'''


class KeyAssignmentTest(PlanCase):
    def test_a_key_is_named_from_its_container_and_its_field(self):
        keys = self.keys(self.plan(TWO_KINDS))
        self.assertEqual(keys["1"], "m.id")                     # a field of the envelope: no container
        self.assertEqual(keys["2.1"], "m.report_title")         # a field of the kind's message: the kind name
        self.assertEqual(keys["3.1"], "m.notice_title")

    def test_two_kinds_that_reach_one_message_type_by_one_path_share_its_keys(self):
        keys = self.keys(self.plan(TWO_KINDS))
        self.assertEqual((keys["2.2.1"], keys["2.2.2"]), ("m.place_x", "m.place_y"))
        self.assertEqual((keys["3.2.1"], keys["3.2.2"]), ("m.place_x", "m.place_y"))

    def test_two_kinds_that_reach_different_types_by_one_path_take_the_kind_as_prefix(self):
        text = TWO_KINDS.replace("message Notice { string title = 1; Point place = 2; }",
                                 "message Spot { double x = 1; }\nmessage Notice { string title = 1; Spot place = 2; }")
        keys = self.keys(self.plan(text))
        self.assertEqual(keys["2.2.1"], "m.report_place_x")
        self.assertEqual(keys["3.2.1"], "m.notice_place_x")

    def test_two_source_names_that_sanitize_to_one_key_get_distinct_keys(self):
        keys = self.keys(self.plan(TWO_KINDS))
        # titleText (field 3) is met first and takes the name; title_text (field 4) adds its path
        self.assertEqual(keys["2.3"], "m.report_title_text")
        self.assertEqual(keys["2.4"], "m.report_title_text_at_2_4")

    def test_keys_pinned_by_a_names_file_stay_when_the_schema_changes_order(self):
        names = os.path.join(self.tmp, "names.json")
        first = self.keys(self.plan(TWO_KINDS, "--names-file", names))
        with open(names, "w", encoding="utf-8") as fh:
            json.dump({path: key.split(".", 1)[1] for path, key in first.items()}, fh)
        swapped = TWO_KINDS.replace("string titleText = 3; string title_text = 4;",
                                    "string title_text = 4; string titleText = 3;")
        self.assertNotEqual(self.keys(self.plan(swapped))["2.4"], first["2.4"])     # unpinned, the order decides
        self.assertEqual(self.keys(self.plan(swapped, "--names-file", names)), first)

    def test_a_pinned_name_wins_over_the_name_the_rules_give(self):
        names = self.write("names.json", json.dumps({"2.1": "headline"}))
        keys = self.keys(self.plan(TWO_KINDS, "--names-file", names))
        self.assertEqual(keys["2.1"], "m.headline")
        self.assertEqual(keys["3.1"], "m.notice_title")

    def test_a_new_field_never_takes_a_name_pinned_to_another_path(self):
        names = self.write("names.json", json.dumps({"9.9": "report_title"}))
        keys = self.keys(self.plan(TWO_KINDS, "--names-file", names))
        self.assertEqual(keys["2.1"], "m.report_title_at_2_1")

    def test_one_name_pinned_to_two_fields_is_refused(self):
        names = self.write("names.json", json.dumps({"2.1": "same", "3.1": "same"}))
        with self.assertRaisesRegex(p2p.GenError, "pinned name same is given to two different fields"):
            self.plan(TWO_KINDS, "--names-file", names)

    def test_the_names_file_content_holds_every_key_and_keeps_what_it_held(self):
        names = self.write("names.json", json.dumps({"9.9": "gone_from_the_schema"}))
        plan = self.plan(TWO_KINDS, "--names-file", names)
        self.assertEqual(plan.names["9.9"], "gone_from_the_schema")
        self.assertEqual(plan.names["2.2.1"], "place_x")
        self.assertEqual(json.loads(p2p.emit_names(plan)), plan.names)
        self.assertEqual(list(json.loads(p2p.emit_names(plan))), sorted(plan.names))

    def test_names_from_another_pack_are_pinned_under_the_prefix(self):
        other = self.write("other.json", json.dumps({"1": "headline", "Point:1": "point_east"}))
        plan = self.plan(TWO_KINDS + "message Wrap { Report inner = 7; repeated Point trail = 8; }\n",
                         "--names-from", other + "=7", envelope="Wrap")
        self.assertEqual(self.keys(plan)["7.1"], "m.headline")
        self.assertEqual(plan.inherited, 2)
        trail = plan.top_groups[0]
        self.assertEqual([l.key for l in trail.leaves], ["m.point_east", "m.point_y"])

    def test_item_keys_are_named_from_the_item_message_and_shared_by_its_lists(self):
        plan = self.plan('''syntax = "proto3";
message Point { double x = 1; repeated string tags = 2; }
message Top { repeated Point path = 1; repeated Point fence = 2; repeated int32 codes = 3; Point home = 4; }
''')
        path, fence, codes, home_tags = plan.top_groups
        self.assertEqual((path.list, fence.list, codes.list, home_tags.list),
                         ("m.top_path", "m.top_fence", "m.top_codes", "m.home_tags"))
        self.assertEqual(home_tags.scalar.key, "m.point_tags_item")
        self.assertEqual([l.key for l in path.leaves], ["m.point_x"])
        self.assertEqual([l.key for l in fence.leaves], ["m.point_x"])
        self.assertEqual(path.groups[0].list, "m.point_tags")
        self.assertEqual(path.groups[0].scalar.key, "m.point_tags_item")
        self.assertEqual(codes.scalar.key, "m.top_codes_item")
        # the same schema field outside a group has its own key: home.x is not an item
        self.assertEqual(self.keys(plan)["4.1"], "m.home_x")


class KindPlanTest(PlanCase):
    def test_an_envelope_with_no_oneof_is_one_kind_with_no_when_and_no_requires(self):
        plan = self.plan('syntax = "proto3";\nmessage Top { string id = 1; }\n')
        self.assertEqual([(k.name, k.number, k.requires) for k in plan.kinds], [("top", None, [])])
        self.assertTrue(plan.single)
        self.assertNotIn("when", p2p.emit_pack(plan))

    def test_the_default_kind_follows_the_kinds_with_fields_and_vectors_keep_their_numbers(self):
        text = TWO_KINDS.replace("Notice notice = 3; }", "Notice notice = 3; Empty empty = 4; }") + "message Empty {}\n"
        text = text.replace("string id = 1;", "string id = 1 [(rule) = {must: true}];")
        plan = self.plan(text, "--default-kind", "report", "--map", "2.2.1=lon", "--map", "2.2.2=lat",
                         "--mandatory-option", "must")
        self.assertEqual([k.name for k in plan.kinds], ["notice", "report", "empty"])
        self.assertEqual(plan.kind("empty").requires, ["m.id"])     # only the mandatory common key
        # numbered as if the default kind were simply last: notice 1, empty 2, report 3
        self.assertEqual({k.name: k.vector_number for k in plan.kinds}, {"notice": 1, "empty": 2, "report": 3})
        self.assertEqual(plan.kind("report").requires, ["lon", "lat"])    # every shared key it maps

    def test_a_kind_requires_a_raw_key_no_other_kind_maps_mandatory_ones_first(self):
        text = '''syntax = "proto2";
message Top { oneof body { A a = 1; B b = 2; } }
message Shared { optional int32 n = 1; }
message A { optional string loose = 1; required string firm = 2; optional Shared shared = 3; }
message B { optional string only = 1; optional Shared shared = 3; }
'''
        plan = self.plan(text)
        self.assertEqual(plan.kind("a").requires, ["m.a_firm"])
        self.assertEqual(plan.kind("b").requires, ["m.b_only"])

    def test_a_kind_with_nothing_but_a_repeated_field_requires_its_list(self):
        text = ('syntax = "proto3";\nmessage Top { oneof body { A a = 1; B b = 2; } }\n'
                'message A { repeated string words = 1; }\nmessage B { string x = 1; }\n')
        self.assertEqual(self.plan(text).kind("a").requires, ["m.a_words"])

    def test_a_default_kind_that_maps_no_shared_key_is_refused(self):
        with self.assertRaisesRegex(p2p.GenError, "default kind report maps no shared key to require"):
            self.plan(TWO_KINDS, "--default-kind", "report")

    def test_a_message_inside_itself_is_walked_once(self):
        plan = self.plan('syntax = "proto3";\nmessage Top { string id = 1; Top next = 2; repeated Top kids = 3; }\n')
        self.assertEqual(self.keys(plan), {"1": "m.top_id"})
        self.assertEqual([(reason, p2p.dotted(nums)) for reason, nums, _, _ in plan.kinds[0].skipped],
                         [("recursive message type", "2"), ("recursive message type", "3")])

    def test_max_depth_stops_the_walk_at_a_message_field(self):
        text = ('syntax = "proto3";\nmessage Top { A a = 1; }\nmessage A { string s = 1; B b = 2; }\n'
                'message B { string t = 1; }\n')
        self.assertEqual(sorted(self.keys(self.plan(text))), ["1.1", "1.2.1"])
        shallow = self.plan(text, "--max-depth", "2")
        self.assertEqual(sorted(self.keys(shallow)), ["1.1"])
        self.assertEqual([r for r, *_ in shallow.kinds[0].skipped], ["below depth 2"])


DEEP = '''syntax = "proto3";
message Top { string id = 1; repeated Row rows = 2; repeated int32 codes = 3; string tail = 4; }
message Row { string name = 1; Cell first = 2; repeated Cell cells = 3; }
message Cell { string text = 1; Mark mark = 2; }
message Mark { int32 level = 1; }
'''


def args_for(tmp, path, *more):
    return ["--proto", path, "--envelope", "Top", "--format", "deep", "--module", "deep", "--out", tmp,
            "--source", "a test"] + list(more)


class BudgetTest(PlanCase):
    """The three limits of a run, with budgets small enough to reach them."""

    def field_lines(self, plan):
        return [ln.split() for ln in p2p.emit_pack(plan).split("\n") if ln.split()[:1] in (["field"], ["group"])]

    def test_within_the_budgets_no_limit_is_lowered(self):
        plan = self.plan(DEEP)
        self.assertEqual((plan.nest, plan.item_depth), (plan.nest_asked, plan.depth_asked))
        # in items: rows 4 (name, first.text, first.mark.level, ...) and cells 2, codes 1
        self.assertEqual(len(plan.item_leaves), 6)

    def test_a_small_line_budget_shortens_the_paths_inside_items_first(self):
        full = self.plan(DEEP)
        # 2 lines outside groups + 6 inside; a budget of 7 does not hold them
        plan = self.plan(DEEP, budgets=p2p.Budgets(keys=60000, lines=7, vector_bytes=1 << 30))
        self.assertLess(plan.item_depth, plan.depth_asked)
        self.assertEqual(plan.nest, plan.nest_asked)
        self.assertLessEqual(len(plan.all_leaves) + len(plan.item_leaves), 7)
        self.assertIn("inside an item, below item depth %d" % plan.item_depth,
                      [reason for reason, *_ in plan.kinds[0].skipped])
        # what stays is in the order it has without the limit
        kept, everything = self.field_lines(plan), self.field_lines(full)
        self.assertLess(len(kept), len(everything))
        rest = iter(everything)
        self.assertTrue(all(line in rest for line in kept), "the lines that stay keep their order")

    def test_a_smaller_line_budget_then_lowers_the_group_nesting(self):
        plan = self.plan(DEEP, budgets=p2p.Budgets(keys=60000, lines=4, vector_bytes=1 << 30))
        # 2 lines outside groups, then `name` of a row and the item of codes: the group inside a row goes
        self.assertEqual((plan.item_depth, plan.nest), (1, 1))
        self.assertEqual([g.list for g in plan.all_groups], ["m.top_rows", "m.top_codes"])
        self.assertIn("repeated field below group nesting depth 1", [reason for reason, *_ in plan.kinds[0].skipped])

    def test_a_small_key_budget_lowers_the_group_nesting(self):
        full = self.plan(DEEP)
        plan = self.plan(DEEP, budgets=p2p.Budgets(keys=full.n_names - 1, lines=100000, vector_bytes=1 << 30))
        self.assertLess(plan.nest, plan.nest_asked)
        self.assertLessEqual(plan.n_names, full.n_names - 1)
        kept, everything = self.field_lines(plan), iter(self.field_lines(full))
        self.assertTrue(all(line in everything for line in kept))

    def test_a_budget_nothing_fits_is_refused(self):
        with self.assertRaisesRegex(p2p.GenError, "more than 1 field lines with no group at all"):
            self.plan(DEEP, budgets=p2p.Budgets(keys=60000, lines=1, vector_bytes=1 << 30))
        with self.assertRaisesRegex(p2p.GenError, "would hold 2 keys, over 1, with no group at all"):
            self.plan(DEEP, budgets=p2p.Budgets(keys=1, lines=100000, vector_bytes=1 << 30))

    def test_a_small_vector_budget_gives_one_item_per_group_and_the_same_files(self):
        plan = self.plan(DEEP)
        two = p2p.emit_vectors(plan)
        one = p2p.emit_vectors(plan, vector_budget=two.gen_bytes - 1)
        self.assertEqual((two.n_items, one.n_items), (2, 1))
        self.assertEqual(list(one.texts), list(two.texts))
        self.assertLess(one.gen_bytes, two.gen_bytes)
        self.assertEqual(json.loads(two.texts["gen-01-top-roundtrip.json"])["model"]["m.top_rows.#"], "2")
        self.assertEqual(json.loads(one.texts["gen-01-top-roundtrip.json"])["model"]["m.top_rows.#"], "1")

    def test_main_says_in_pack_md_which_limit_it_lowered_and_the_output_still_checks(self):
        path = self.write("schema.proto", DEEP)
        support.copy_tree(os.path.join(INPUT, "model"), os.path.join(self.tmp, "model"))
        self.run_ok(args_for(self.tmp, path), budgets=p2p.Budgets(keys=60000, lines=7, vector_bytes=600))
        md = self.read("packs/deep/pack.md")
        self.assertIn("Inside an item a path is at most 2 field numbers long (`--max-item-depth`, lowered by the run "
                      "from 6): with longer paths pack.def would hold more than 7 `field` lines.", md)
        self.assertIn("The generated vectors hold one item per group: with two they would pass 600 bytes.", md)
        self.assertIn("every group with one item and", md)
        gtcheck.check_output(os.path.join(self.tmp, "model"), [os.path.join(self.tmp, "packs", "deep", "pack.def")])

    def test_the_budgets_of_one_run_do_not_reach_the_next(self):
        path = self.write("schema.proto", DEEP)
        support.copy_tree(os.path.join(INPUT, "model"), os.path.join(self.tmp, "model"))
        self.run_ok(args_for(self.tmp, path))
        first = support.tree(self.tmp)
        self.run_ok(args_for(self.tmp, path, "--max-depth", "3"), budgets=p2p.Budgets(60000, 7, 600))
        self.assertNotEqual(support.tree(self.tmp), first)
        self.run_ok(args_for(self.tmp, path))
        self.assertEqual(support.tree(self.tmp), first)


# --------------------------------------------------------------------------
# the protobuf wire, with bytes worked by hand
# --------------------------------------------------------------------------

class VarintTest(unittest.TestCase):
    def test_one_byte_up_to_127_and_two_from_128(self):
        self.assertEqual(p2p.enc_varint(0), b"\x00")
        self.assertEqual(p2p.enc_varint(1), b"\x01")
        self.assertEqual(p2p.enc_varint(127), b"\x7f")
        self.assertEqual(p2p.enc_varint(128), b"\x80\x01")          # low seven bits 0, then 1
        self.assertEqual(p2p.enc_varint(150), b"\x96\x01")          # 150 = 1 * 128 + 22; 22 | 0x80 = 0x96
        self.assertEqual(p2p.enc_varint(20000), b"\xa0\x9c\x01")    # 20000 = 1 * 16384 + 28 * 128 + 32

    def test_two_to_the_63_takes_ten_bytes(self):
        # bit 63 is bit 0 of the tenth group of seven: nine empty groups, then 1
        self.assertEqual(p2p.enc_varint(1 << 63), b"\x80" * 9 + b"\x01")
        self.assertEqual(p2p.enc_varint((1 << 64) - 1), b"\xff" * 9 + b"\x01")

    def test_a_negative_integer_is_its_64_bit_twos_complement(self):
        self.assertEqual(p2p.enc_varint(-1), b"\xff" * 9 + b"\x01")
        self.assertEqual(p2p.enc_varint(-(1 << 63)), b"\x80" * 9 + b"\x01")
        self.assertEqual(p2p.dec_value("pvarint", 0, (1 << 64) - 1), -1)
        self.assertEqual(p2p.dec_value("pvarint", 0, 1 << 63), -(1 << 63))
        self.assertEqual(p2p.dec_value("pvarint", 0, (1 << 63) - 1), (1 << 63) - 1)

    def test_zig_zag_interleaves_negative_and_positive(self):
        for value, wire in ((0, 0), (-1, 1), (1, 2), (-2, 3), (2, 4), (2147483647, 4294967294),
                            (-2147483648, 4294967295), ((1 << 63) - 1, (1 << 64) - 2), (-(1 << 63), (1 << 64) - 1)):
            self.assertEqual(p2p.enc_value("psint", value), p2p.enc_varint(wire), value)
            self.assertEqual(p2p.dec_value("psint", 0, wire), value, wire)
        self.assertEqual(p2p.enc_value("psint", -3), b"\x05")

    def test_strings_doubles_and_floats(self):
        self.assertEqual(p2p.enc_value("pstring", "hé"), b"\x03h\xc3\xa9")       # length in bytes, UTF-8
        self.assertEqual(p2p.enc_value("pdouble", 1.0), bytes.fromhex("000000000000f03f"))
        self.assertEqual(p2p.enc_value("pfloat", 0.5), bytes.fromhex("0000003f"))
        self.assertEqual(p2p.dec_value("pdouble", 1, bytes.fromhex("000000000000f03f")), 1.0)
        self.assertEqual(p2p.dec_value("pfloat", 5, bytes.fromhex("0000003f")), 0.5)
        self.assertEqual(p2p.dec_value("pstring", 2, b"h\xc3\xa9"), "hé")

    def test_a_value_on_another_wire_type_is_a_decode_error(self):
        with self.assertRaisesRegex(p2p.GenError, "transform-decode: wire type 0 for pstring"):
            p2p.dec_value("pstring", 0, 5)
        with self.assertRaisesRegex(p2p.GenError, "transform-decode: wire type 2 for pdouble"):
            p2p.dec_value("pdouble", 2, b"12345678")


class MessageBytesTest(unittest.TestCase):
    def test_fields_are_written_in_ascending_number_order_whatever_the_tree_order(self):
        # field 1 varint 150: tag 08, 96 01; field 2 string "hi": tag 12, length 02, 68 69
        want = bytes.fromhex("089601" "12026869")
        self.assertEqual(p2p.enc_tree({2: ("pstring", "hi"), 1: ("pvarint", 150)}), want)
        self.assertEqual(p2p.enc_tree({1: ("pvarint", 150), 2: ("pstring", "hi")}), want)

    def test_a_subtree_is_a_length_delimited_field(self):
        # field 3, wire type 2: tag 1a, length 2, then field 1 varint 1
        self.assertEqual(p2p.enc_tree({3: {1: ("pvarint", 1)}}), bytes.fromhex("1a020801"))
        self.assertEqual(p2p.enc_tree({3: {}}), bytes.fromhex("1a00"))
        # field 16 needs a two-byte tag: 16 << 3 | 1 = 129 -> 81 01
        self.assertEqual(p2p.enc_tree({16: ("pdouble", 0.0)}), bytes.fromhex("8101") + b"\x00" * 8)

    def test_a_repeated_number_is_written_packed_and_a_repeated_string_once_per_item(self):
        # field 5, packed: tag 2a, length 3, values 1 and 150
        self.assertEqual(p2p.enc_tree({5: p2p.Packed("pvarint", [1, 150])}), bytes.fromhex("2a03019601"))
        self.assertEqual(p2p.enc_tree({5: p2p.Packed("pvarint", [])}), b"")
        self.assertEqual(p2p.enc_tree({4: p2p.Rep([("pstring", "a"), ("pstring", "b")])}), bytes.fromhex("22016122 0162"))
        self.assertEqual(p2p.enc_tree({4: p2p.Rep([{1: ("pvarint", 1)}, {}])}), bytes.fromhex("22020801 2200"))

    def test_a_tree_comes_back_through_dec_message(self):
        tree = {1: ("pvarint", 150), 2: ("pstring", "hi"), 3: {1: ("psint", -3), 2: ("pdouble", 2.5)},
                7: ("pfloat", 0.5)}
        top = p2p.dec_message(p2p.enc_tree(tree))
        self.assertEqual(top[1], (0, 150))
        self.assertEqual(top[2], (2, b"hi"))
        self.assertEqual(p2p.dec_value("pfloat", *top[7]), 0.5)
        inner = p2p.dec_message(top[3][1])
        self.assertEqual(p2p.dec_value("psint", *inner[1]), -3)
        self.assertEqual(p2p.dec_value("pdouble", *inner[2]), 2.5)
        self.assertEqual(p2p.wire_get(p2p.enc_tree(tree), (3, 1)), (0, 5))
        self.assertIsNone(p2p.wire_get(p2p.enc_tree(tree), (9, 1)))

    def test_the_last_occurrence_of_a_field_wins(self):
        twice = bytes.fromhex("0801" "0802")
        self.assertEqual(p2p.dec_fields(twice), [(1, 0, 1), (1, 0, 2)])
        self.assertEqual(p2p.dec_message(twice), {1: (0, 2)})
        self.assertEqual(p2p.wire_get(twice, (1,)), (0, 2))

    def test_packed_values_decode_by_the_width_of_the_transform(self):
        self.assertEqual(p2p.dec_packed("pvarint", bytes.fromhex("01 9601 a09c01")), [1, 150, 20000])
        self.assertEqual(p2p.dec_packed("psint", bytes.fromhex("05 02")), [-3, 1])
        self.assertEqual(p2p.dec_packed("pdouble", bytes.fromhex("000000000000f03f" "0000000000000440")), [1.0, 2.5])
        self.assertEqual(p2p.dec_packed("pfloat", bytes.fromhex("0000003f")), [0.5])
        self.assertEqual(p2p.dec_packed("pvarint", b""), [])

    def test_a_packed_payload_that_does_not_fit_its_values_is_malformed(self):
        with self.assertRaisesRegex(p2p.GenError, "malformed-wire: packed payload of 7 bytes"):
            p2p.dec_packed("pdouble", b"\x00" * 7)
        with self.assertRaisesRegex(p2p.GenError, "malformed-wire: truncated packed varint"):
            p2p.dec_packed("pvarint", b"\x01\x96")

    def test_truncated_bytes_and_group_wire_types_are_malformed(self):
        for hexs, what in (("08", "truncated varint"), ("0896", "truncated varint"), ("1205 6869", "truncated field 2"),
                           ("09 0000", "truncated field 1"), ("0b", "wire type 3"), ("0c", "wire type 4")):
            with self.assertRaisesRegex(p2p.GenError, "malformed-wire: " + what):
                p2p.dec_fields(bytes.fromhex(hexs))


# --------------------------------------------------------------------------
# decode and encode with a pack
# --------------------------------------------------------------------------

CORE = '''module core
version 0.1.0
distribution public
source "a test"
key uid string -
key type string -
key lat float deg
key lon float deg
key time_ms int ms
key speed_ms float m/s
key course float deg
list tags
key tag string -
list points
key level int -
list words
key word string -
'''

SMALL_PACK = '''format small
version 0.1.0
distribution public
source "a test"
wire protobuf
field uid 1 pstring
kind point
when 2 present
requires lat lon
field lat 2.1 pdouble
field lon 2.2 pdouble
field type 2.3 pstring via shape
const 2.4 7
group tags 2.5
  field level . pvarint
end
group words 2.6
  field word . pstring
end
group points 2.7
  field level 1 psint
  group tags 2
    field tag 1 pstring
  end
end
kind note
when 3.1 1
requires type
field type 3.2 pstring
map shape SQ square
map shape RD round
map shape SQ box
'''


def small_model(*more):
    model = gtcheck.Model()
    model.add(CORE, "core.def")
    for i, text in enumerate(more):
        model.add(text, "more%d.def" % i)
    return model


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.pack = p2p.load_protobuf_pack(SMALL_PACK, small_model(), "small/pack.def")

    def decode(self, hexs):
        return p2p.engine_decode(self.pack, bytes.fromhex(hexs))

    def test_the_kind_is_the_first_whose_when_lines_hold(self):
        self.assertEqual(self.decode("0a0175" "1200"), ({"uid": "u"}, "point"))         # 2 present, empty
        self.assertEqual(self.decode("1a04" "0801" "1200"), ({"type": ""}, "note"))      # 3.1 is 1
        with self.assertRaises(p2p.NoKind):
            self.decode("1a020802")                                                     # 3.1 is 2
        with self.assertRaises(p2p.NoKind):
            self.decode("0a0175")

    def test_both_encodings_of_a_repeated_number_decode_to_the_same_list(self):
        packed = "1208" + "2a03019601" + "2a0102"         # 2.5 packed [1, 150], then packed [2]
        unpacked = "1207" + "2801" + "289601" + "2802"    # one occurrence per value
        mixed = "1208" + "2801" + "2a029601" + "2802"
        want = {"tags": [{"level": 1}, {"level": 150}, {"level": 2}]}
        for hexs in (packed, unpacked, mixed):
            self.assertEqual(self.decode(hexs), (want, "point"), hexs)

    def test_encode_writes_a_repeated_number_packed_and_a_repeated_string_per_item(self):
        ent = {"tags": [{"level": 1}, {"level": 150}, {"level": 2}], "words": [{"word": "a"}, {"word": "b"}]}
        b, kind = p2p.engine_encode(self.pack, ent, "point")
        # 2 { 4: 7 (const)  5: packed 01 96 01 02  6: "a"  6: "b" }
        self.assertEqual(b.hex(), "120e" + "2007" + "2a0401960102" + "320161" + "320162")
        self.assertEqual(p2p.engine_decode(self.pack, b), (dict(ent), "point"))

    def test_a_repeated_message_and_a_nested_group_round_trip(self):
        ent = {"points": [{"level": -3, "tags": [{"tag": "x"}, {"tag": "y"}]}, {"level": 1}]}
        b, _ = p2p.engine_encode(self.pack, ent, "point")
        # 2 { 4: 7  7: { 1: zig-zag 5  2: { 1: "x" }  2: { 1: "y" } }  7: { 1: zig-zag 2 } }
        self.assertEqual(b.hex(), "1214" + "2007" + "3a0c" + "0805" + "12030a0178" + "12030a0179" + "3a02" + "0802")
        self.assertEqual(p2p.engine_decode(self.pack, b)[0], ent)

    def test_an_item_that_is_not_a_submessage_is_malformed(self):
        with self.assertRaisesRegex(p2p.GenError, "malformed-wire: an item of points is not a submessage"):
            self.decode("1202" + "3801")

    def test_a_value_table_maps_both_ways_and_passes_an_unknown_value_through(self):
        self.assertEqual(self.decode("1204" + "1a025351")[0], {"type": "square"})       # SQ
        self.assertEqual(self.decode("1204" + "1a025858")[0], {"type": "XX"})
        for model_value, wire in (("round", "RD"), ("box", "SQ"), ("square", "SQ"), ("other", "other")):
            b, _ = p2p.engine_encode(self.pack, {"type": model_value, "lat": 1.0, "lon": 2.0}, "point")
            self.assertEqual(p2p.wire_get(b, (2, 3)), (2, wire.encode()), model_value)

    def test_a_constant_is_written_over_any_field_and_a_when_value_is_written(self):
        b, kind = p2p.engine_encode(self.pack, {"uid": "u"}, "point")
        self.assertEqual(b.hex(), "0a0175" + "1202" + "2007")
        b, kind = p2p.engine_encode(self.pack, {"type": "t"}, "note")
        self.assertEqual(b.hex(), "1a05" + "0801" + "120174")

    def test_an_entity_from_another_format_takes_the_first_kind_whose_requires_hold(self):
        self.assertEqual(p2p.engine_encode(self.pack, {"lat": 1.0, "lon": 2.0, "type": "t"}, None)[1], "point")
        self.assertEqual(p2p.engine_encode(self.pack, {"lat": 1.0, "type": "t"}, None)[1], "note")
        with self.assertRaises(p2p.NoKind):
            p2p.engine_encode(self.pack, {"uid": "u"}, None)

    def test_one_key_at_two_paths_reads_the_earliest_present_and_writes_both(self):
        text = SMALL_PACK.replace("field uid 1 pstring", "field uid 1 pstring\nfield uid 9 pstring")
        pack = p2p.load_protobuf_pack(text, small_model(), "small/pack.def")
        self.assertEqual(p2p.engine_decode(pack, bytes.fromhex("1200" + "4a0162"))[0], {"uid": "b"})
        self.assertEqual(p2p.engine_decode(pack, bytes.fromhex("0a0161" + "1200" + "4a0162"))[0], {"uid": "a"})
        self.assertEqual(p2p.engine_encode(pack, {"uid": "a"}, "point")[0].hex(), "0a0161" + "12022007" + "4a0161")

    def test_names_are_the_entity_keys_and_lists_not_the_keys_of_items(self):
        self.assertEqual(self.pack.names(), {"uid", "lat", "lon", "type", "tags", "words", "points"})


class ProtobufPackCheckTest(unittest.TestCase):
    """What this generator asks of a protobuf pack beyond the load rules."""

    def refuse(self, text, pattern):
        with self.assertRaisesRegex(p2p.GenError, pattern):
            p2p.load_protobuf_pack(text, small_model(), "small/pack.def")

    def test_a_path_with_two_transforms_names_the_line(self):
        self.refuse(SMALL_PACK.replace("field lon 2.2 pdouble", "field lon 2.1 pfloat"),
                    r"small/pack\.def:11: path 2\.1 has two transforms in kind point")

    def test_a_path_that_is_a_value_and_a_submessage_is_refused(self):
        self.refuse(SMALL_PACK.replace("field uid 1 pstring", "field uid 2 pstring"),
                    r"path 2 is both a value and a submessage in kind point")

    def test_a_field_on_the_path_of_a_group_is_refused(self):
        self.refuse(SMALL_PACK.replace("field lon 2.2 pdouble", "field uid 2.5 pstring"),
                    r"path 2\.5 is a field and a group in kind point")

    def test_a_default_line_and_a_text_constant_are_refused(self):
        self.refuse(SMALL_PACK + "default uid x\n", r"small/pack\.def:\d+: a `default` line")
        self.refuse(SMALL_PACK.replace("const 2.4 7", "const 2.4 seven"), r"the `const` value seven is not an unsigned")

    def test_a_pack_of_another_wire_is_refused(self):
        self.refuse("format t\nversion 1\ndistribution public\nsource s\nwire geojson\nfield uid id string\n",
                    "the pack's wire is geojson, not protobuf")

    def test_a_load_rule_is_refused_by_gtcheck_before_these_checks(self):
        with self.assertRaises(gtcheck.CheckError) as caught:
            p2p.load_protobuf_pack(SMALL_PACK.replace("field uid 1 pstring", "field owner 1 pstring"),
                                   small_model(), "small/pack.def")
        self.assertEqual((caught.exception.kind, caught.exception.line), ("undeclared-key", 6))


class KindOrderCheckTest(unittest.TestCase):
    def pack(self, text):
        return p2p.load_protobuf_pack(text, small_model(), "small/pack.def")

    def test_a_kind_with_no_requires_before_another_kind_is_refused(self):
        with self.assertRaisesRegex(p2p.GenError, "kind point has no requires and would shadow"):
            p2p.check_kind_order(self.pack(SMALL_PACK.replace("requires lat lon\n", "")), None)
        p2p.check_kind_order(self.pack(SMALL_PACK.replace("requires type\n", "")), None)    # the last kind may

    def test_a_kind_with_fields_after_the_default_kind_is_refused(self):
        with self.assertRaisesRegex(p2p.GenError, "a kind with fields follows the default kind"):
            p2p.check_kind_order(self.pack(SMALL_PACK), "point")
        p2p.check_kind_order(self.pack(SMALL_PACK), "note")

    def test_a_superseded_common_line_must_be_a_line_of_the_new_pack(self):
        old = self.pack("format small\nversion 0\ndistribution public\nsource s\nwire protobuf\n"
                        "field uid 1 pstring\nfield lat 2.1 pdouble\n")
        p2p.check_supersedes(self.pack(SMALL_PACK), old)
        with self.assertRaisesRegex(p2p.GenError, "superseded mapping lat 2.1 pdouble is not preserved"):
            p2p.check_supersedes(self.pack(SMALL_PACK.replace("field lat 2.1 pdouble", "field lat 2.8 pdouble")), old)


# --------------------------------------------------------------------------
# other packs, models and vectors
# --------------------------------------------------------------------------

XML_PACK = '''format tag
version 0.1.0
distribution public
source "a test"
wire xml
root tag
const @schema 2
field uid @id string
field time_ms @time iso8601_ms
field lat place/@lat float
field lon place/@lon float
field speed_ms move/@speed float
default speed_ms 0
'''

GEOJSON_PACK = '''format gj
version 0.1.0
distribution public
source "a test"
wire geojson
field uid id string
field type properties.type string
field time_ms properties.t int
field lat geometry.lat float
field lon geometry.lon float
'''


class OtherPackTest(unittest.TestCase):
    def test_an_xml_pack_writes_attributes_in_line_order_with_constants_and_defaults(self):
        other = p2p.OtherPack(XML_PACK, small_model(), "tag/pack.def")
        ent = {"uid": 'a<b&"c"', "time_ms": 1700000000123, "lat": 47.25, "lon": 8.0}
        text = other.encode(ent)
        # 1700000000 s is 2023-11-14T22:13:20Z; an integer float has no decimal point
        self.assertEqual(text, '<tag schema="2" id="a&lt;b&amp;&quot;c&quot;" time="2023-11-14T22:13:20.123Z">'
                               '<place lat="47.25" lon="8"/><move speed="0"/></tag>')
        self.assertEqual(other.decode(text), dict(ent, speed_ms=0.0))

    def test_a_geojson_pack_writes_a_point_or_a_null_geometry(self):
        other = p2p.OtherPack(GEOJSON_PACK, small_model(), "gj/pack.def")
        ent = {"uid": "u-1", "type": "a", "time_ms": 5, "lat": 47.25, "lon": 8.5}
        text = other.encode(ent)
        self.assertEqual(text, '{"type":"Feature","geometry":{"type":"Point","coordinates":[8.5,47.25]},'
                               '"properties":{"type":"a","t":5},"id":"u-1"}')
        self.assertEqual(other.decode(text), ent)
        self.assertEqual(other.encode({"uid": "u-1", "lat": 1.0}),
                         '{"type":"Feature","geometry":null,"properties":{},"id":"u-1"}')
        self.assertEqual(other.mapped_keys(), {"uid", "type", "time_ms", "lat", "lon"})

    def test_a_protobuf_pack_takes_the_keys_it_maps_and_chooses_the_kind(self):
        other = p2p.OtherPack(SMALL_PACK, small_model(), "small/pack.def")
        hexs = other.encode({"uid": "u", "lat": 1.0, "lon": 2.0, "speed_ms": 9.0})
        self.assertEqual(hexs, "0a0175" + "1214" + "09000000000000f03f" + "110000000000000040" + "2007")
        self.assertEqual(other.decode(hexs), {"uid": "u", "lat": 1.0, "lon": 2.0})
        self.assertEqual(other.mapped_keys(), {"uid", "lat", "lon", "type", "tags", "words", "points"})

    def test_what_the_text_functions_do_not_handle_is_refused_not_guessed(self):
        model = small_model()
        with self.assertRaisesRegex(p2p.GenError, "tag/pack.def: xml_encode: locator note/#text is not an attribute"):
            p2p.OtherPack(XML_PACK + "field type note/#text string\n", model, "tag/pack.def").encode({"type": "x"})
        kinds = XML_PACK + "kind a\nwhen @k 1\nfield type @type string\n"
        with self.assertRaisesRegex(p2p.GenError, "kind lines are not supported"):
            p2p.OtherPack(kinds, model, "tag/pack.def").decode("<tag/>")
        with self.assertRaisesRegex(p2p.GenError, "cannot be converted"):
            p2p.OtherPack("format j\nversion 1\ndistribution public\nsource s\nwire json\nfield uid id string\n",
                          model, "j/pack.def")

    def test_plain_float_is_the_shortest_decimal_with_no_exponent(self):
        for value, text in ((1.0, "1"), (-0.0, "0"), (0.1, "0.1"), (1e-07, "0.0000001"), (-42.6, "-42.6"),
                            (1e21, "1000000000000000000000"), (30.0090027, "30.0090027")):
            self.assertEqual(p2p.plain_float(value), text)

    def test_keys_that_share_a_locator_are_known_to_each_other(self):
        other = p2p.OtherPack(XML_PACK.replace("field uid @id string", "field type @id string\nfield uid @id string"),
                              small_model(), "tag/pack.def")
        shares = other.keys_sharing_a_locator()
        self.assertEqual((shares["type"], shares["uid"], shares["lat"]), ({"uid"}, {"type"}, set()))


class CarriedKeysTest(unittest.TestCase):
    """--cross-text reads its text back with the other pack. A pack may read one
    locator into several keys; the extra key is no loss and no key of the source."""

    def setUp(self):
        text = XML_PACK.replace("field uid @id string", "field type @id string\nfield uid @id string")
        self.other = p2p.OtherPack(text.replace("default speed_ms 0\n", ""), small_model(), "tag/pack.def")

    def test_a_key_read_from_the_locator_of_a_carried_key_is_left_out(self):
        ent = {"uid": "u-1", "lat": 1.5, "lon": 2.5, "course": 90.0}
        seen = self.other.decode(self.other.encode(ent))
        self.assertEqual(seen["type"], "u-1")           # the pack fills it from @id
        carried = p2p.carried_keys(self.other, ent, seen, "--cross-text tag")
        self.assertEqual(carried, {"uid": "u-1", "lat": 1.5, "lon": 2.5})

    def test_a_key_that_comes_back_with_another_value_is_refused(self):
        with self.assertRaisesRegex(p2p.GenError, "--cross-text tag: key lat does not survive"):
            p2p.carried_keys(self.other, {"uid": "u", "lat": 1.5}, {"uid": "u", "lat": 2.5}, "--cross-text tag")

    def test_a_key_from_nowhere_is_refused(self):
        with self.assertRaisesRegex(p2p.GenError, "key speed_ms does not survive"):
            p2p.carried_keys(self.other, {"uid": "u"}, {"uid": "u", "speed_ms": 0.0}, "--cross-text tag")

    def test_a_key_at_a_shared_locator_with_another_value_is_refused(self):
        with self.assertRaisesRegex(p2p.GenError, "key type does not survive"):
            p2p.carried_keys(self.other, {"uid": "u"}, {"uid": "u", "type": "other"}, "--cross-text tag")


class CrossTextSharedLocatorTest(FixtureCase):
    def test_a_run_against_a_pack_that_reads_one_locator_into_two_keys_completes(self):
        rel = "packs/tag-xml/pack.def"
        self.write(rel, self.read(rel).replace("field   uid      @id          string",
                                               "field   uid      @id          string\n"
                                               "field   type     @id          string"))
        self.run_ok(depot_args(self.tmp))
        out = json.loads(self.read("packs/depot/vectors/gen-depot-to-tag-xml.json"))
        back = json.loads(self.read("packs/tag-xml/vectors/gen-tag-xml-to-depot.json"))
        # a vector states what decode of its own `from` format yields: depot does not decode `type`
        # from this message; tag-xml decodes it from @id
        self.assertNotIn("type", out["model"])
        self.assertEqual(back["model"]["type"], back["model"]["uid"])
        with open(os.path.join(EXPECTED, "packs", "depot", "vectors", "gen-depot-to-tag-xml.json"),
                  encoding="utf-8") as fh:
            expected = json.load(fh)
        self.assertEqual(out, expected, "the vector out of depot is the one of the pack with one key at @id")
        self.assertIn("| `tag-xml` | `parcel_report` | `hae` `lat` `lon` `time_ms` `uid` |",
                      self.read("packs/depot/pack.md"))


class ModelTest(TempDirCase):
    def test_would_derive_follows_the_derive_lines_by_presence(self):
        motion = ('module motion\nversion 1\ndistribution public\nsource s\nkey east float -\nkey north float -\n'
                  'derive speed_ms hypot motion.east motion.north\nderive course bearing motion.east motion.north\n'
                  'derive motion.east east_of speed_ms course\n')
        model = small_model(motion)
        self.assertEqual(p2p.would_derive(model, {"motion.east", "motion.north"}), {"speed_ms", "course"})
        self.assertEqual(p2p.would_derive(model, {"motion.east"}), set())
        self.assertEqual(p2p.would_derive(model, {"speed_ms", "course"}), {"motion.east"})
        self.assertEqual(p2p.would_derive(model, {"motion.east", "motion.north", "speed_ms", "course"}), set())

    def test_load_model_loads_a_module_after_the_module_it_uses(self):
        import genio
        self.write("model/core.def", CORE)
        self.write("model/a.def", "module a\nversion 1\ndistribution public\nsource s\nuses z\nkey k float -\n"
                                  "derive a.k copy z.v\n")
        self.write("model/z.def", "module z\nversion 1\ndistribution public\nsource s\nkey v float -\n")
        model = p2p.load_model(genio.Output(self.tmp))
        self.assertEqual(list(model.modules), ["core", "z", "a"])

    def test_load_model_reads_a_module_the_run_wrote_also_in_check_mode(self):
        import genio
        self.write("model/core.def", CORE)
        self.write("model/m.def", "module m\nversion 1\ndistribution public\nsource s\nkey old float -\n")
        out = genio.Output(self.tmp, check=True)
        out.write("model/m.def", "module m\nversion 1\ndistribution public\nsource s\nkey new float -\n")
        self.assertEqual(list(p2p.load_model(out).modules["m"].keys), ["new"])

    def test_load_model_refuses_a_directory_with_no_core_and_a_module_whose_uses_is_missing(self):
        import genio
        self.write("model/m.def", "module m\nversion 1\ndistribution public\nsource s\nkey k float -\n")
        with self.assertRaisesRegex(p2p.GenError, "there is no module `core`"):
            p2p.load_model(genio.Output(self.tmp))
        self.write("model/core.def", CORE)
        self.write("model/n.def", "module n\nversion 1\ndistribution public\nsource s\nuses gone\nkey k float -\n")
        with self.assertRaises(gtcheck.CheckError) as caught:
            p2p.load_model(genio.Output(self.tmp))
        self.assertEqual((caught.exception.kind, caught.exception.label), ("unknown-module", "model/n.def"))


class VectorModelTest(unittest.TestCase):
    ENT = {"uid": "u", "lat": 2.0, "level": 3,
           "points": [{"level": 1, "tag": "a", "word": "w", "tags": [{"tag": "x"}]}, {"level": 2}]}

    def test_model_text_is_the_canonical_text_of_a_value(self):
        self.assertEqual([p2p.model_text(v) for v in (2.0, 2.5, -0.0, 7, "x", 1e-07)],
                         ["2", "2.5", "0", "7", "x", "1e-07"])

    def test_flat_model_states_keys_then_lists_with_counts_and_the_first_keys_of_each_item(self):
        self.assertEqual(p2p.flat_model(self.ENT, values=2), {
            "uid": "u", "lat": "2", "level": "3", "points.#": "2",
            "points[0].level": "1", "points[0].tag": "a",       # the first two keys; `word` is left out
            "points[0].tags.#": "1", "points[0].tags[0].tag": "x",
            "points[1].level": "2"})
        self.assertIn("points[0].word", p2p.flat_model(self.ENT))

    def test_model_lookup_reads_what_flat_model_writes(self):
        for key, text in p2p.flat_model(self.ENT).items():
            self.assertEqual(p2p.model_text(p2p.model_lookup(self.ENT, key)), text, key)
        self.assertEqual(p2p.model_lookup(self.ENT, "tags.#"), "absent")
        self.assertIsNone(p2p.model_lookup(self.ENT, "points[2].level"))
        self.assertIsNone(p2p.model_lookup(self.ENT, "course"))

    def test_within_compares_lists_item_by_item_on_the_keys_the_part_holds(self):
        whole = self.ENT["points"]
        self.assertTrue(p2p.within([{"level": 1, "tags": [{"tag": "x"}]}, {}], whole))
        self.assertFalse(p2p.within([{"level": 1}], whole))                 # another number of items
        self.assertFalse(p2p.within([{"level": 9}, {"level": 2}], whole))
        self.assertFalse(p2p.within([{"course": 1.0}, {}], whole))          # a key the whole lacks


class CheckVectorsTest(TempDirCase):
    """check_vectors proves every vector of the pack directory; each test
    breaks one statement of a vector."""

    VECTOR = {"name": "t", "from": "small", "to": "small", "input": "0a0175" + "1202" + "2007",
              "expect": "0a0175" + "1202" + "2007", "model": {"@kind": "point", "uid": "u"}}

    def check(self, **changes):
        import genio
        self.write("packs/small/vectors/01-t.json", json.dumps(dict(self.VECTOR, **changes)))
        pack = p2p.load_protobuf_pack(SMALL_PACK, small_model(), "small/pack.def")
        return p2p.check_vectors(genio.Output(self.tmp), "packs/small/vectors", "small", pack, None)

    def test_a_vector_that_holds_is_counted(self):
        self.assertEqual(self.check(), 1)

    def test_a_wrong_kind_a_wrong_value_a_missing_key_and_wrong_bytes_are_refused_with_the_file(self):
        for changes, message in (
                ({"model": {"@kind": "note"}}, "selected kind point, vector says note"),
                ({"model": {"uid": "v"}}, "model key uid is 'u', vector says v"),
                ({"model": {"lat": "1"}}, "model key lat not decoded"),
                ({"expect": "0a0175"}, "same-format round trip differs"),
                ({"from": "other"}, "vector is not from small")):
            with self.assertRaises(p2p.GenError) as caught:
                self.check(**changes)
            self.assertEqual(str(caught.exception), "packs/small/vectors/01-t.json: " + message)

    def test_a_model_marked_complete_is_left_to_an_engine_that_derives(self):
        self.assertEqual(self.check(model={"@kind": "point", "@complete": True, "speed_ms": "5"}), 1)


class SeveralKeysOnOnePathTest(TempDirCase):
    """--map given twice for one path (0.5 ruling 16, as packs/cot-xml binds
    @uid to track.scoped_id and uid): one line per shared key, in --map order,
    then the raw key."""

    def setUp(self):
        super().setUp()
        shutil.copytree(os.path.join(INPUT, "model"), os.path.join(self.tmp, "model"))
        self.proto = self.write("proto/fix.proto", 'syntax = "proto3";\n'
                                'message Fix { string id = 1; double lat = 2; double lon = 3; }\n')

    def argv(self, *extra):
        return ["--proto", self.proto, "--envelope", "Fix", "--format", "fix", "--module", "fix",
                "--out", self.tmp, "--source", "a test", "--no-comments",
                "--map", "1=type", "--map", "1=uid", "--map", "2=lat", "--map", "3=lon"] + list(extra)

    def test_each_key_has_a_line_in_map_order_before_the_raw_key(self):
        self.run_ok(self.argv())
        model = gtcheck.Model().load_dir(os.path.join(self.tmp, "model"))
        pack = gtcheck.load_pack_file(os.path.join(self.tmp, "packs", "fix", "pack.def"), model)
        at = [f.key for f in pack.common + [l for k in pack.kinds for l in k.lines] if f.d == "field" and f.loc == "1"]
        self.assertEqual(at, ["type", "uid", "fix.fix_id"])

    def test_the_round_trip_vector_holds_the_value_under_every_key(self):
        self.run_ok(self.argv())
        with open(os.path.join(self.tmp, "packs", "fix", "vectors", "gen-01-fix-roundtrip.json"),
                  encoding="utf-8") as fh:
            model = json.load(fh)["model"]
        self.assertEqual(model["type"], model["uid"])
        self.assertEqual(model["uid"], model["fix.fix_id"])

    def test_pack_md_lists_every_key_and_says_which_path_carries_several(self):
        self.run_ok(self.argv())
        md = self.read("packs/fix/pack.md")
        self.assertIn("| `type` | `1` | `Fix.id` (string) |", md)
        self.assertIn("| `uid` | `1` | `Fix.id` (string) |", md)
        self.assertIn("`1` carries more than one shared key", md)

    def test_one_key_per_path_says_nothing_of_several(self):
        self.run_ok(["--proto", self.proto, "--envelope", "Fix", "--format", "fix", "--module", "fix",
                     "--out", self.tmp, "--source", "a test", "--no-comments", "--map", "1=uid"])
        self.assertNotIn("more than one shared key", self.read("packs/fix/pack.md"))

    def test_a_second_run_with_check_finds_nothing_to_change(self):
        self.run_ok(self.argv())
        self.run_ok(self.argv("--check"))


if __name__ == "__main__":
    unittest.main()
