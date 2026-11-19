"""Tests of tools/gen/canboat2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_canboat2pack*.py'

The fixture under fixtures/canboat2pack/ was written for these tests from the
public layout of a CANboat `canboat.json` file (a `PGNs` array of definitions,
each with `Fields`). Its definitions are invented (PGN 65280 and 65300 to 65308,
ids starting with `lab`), except three whose ids and field ids the generator's
cross-format vectors name: PGN 129025, 129026 and 129038, written here with only
the members the generator reads. `input/sources/LICENSE` is a text written for
the test. `input/sources/PROVENANCE.md` is what the generator writes for those
two files with `--commit 1111111111111111111111111111111111111111`; one test
checks that it still writes exactly that. No test uses the network.
"""
import support

import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import gtcheck
import canboat2pack as c

FIXTURE = os.path.join(support.FIXTURES, "canboat2pack")
INPUT = os.path.join(FIXTURE, "input")
EXPECTED = os.path.join(FIXTURE, "expected")
COMMIT = "1" * 40
PACK = "packs/nmea2000/pack.def"
MODULE = "model/n2k.def"


# ---------------------------------------------------------------- helpers

def field(ident, field_type="NUMBER", length=8, offset=0, **members):
    """One `Fields` entry. `length`/`offset` of None leave the member out."""
    f = {"Id": ident, "FieldType": field_type}
    if length is not None:
        f["BitLength"] = length
    if offset is not None:
        f["BitOffset"] = offset
    f.update(members)
    return f


def definition(pgn, ident, fields, **members):
    d = {"PGN": pgn, "Id": ident, "Description": "test " + ident, "Complete": True, "Fields": fields}
    d.update(members)
    return d


def database(*definitions):
    return c.parse_database(json.dumps({"Version": "0", "PGNs": list(definitions)}), "db.json")


def source_field(**members):
    """A parsed SourceField of a one-field definition."""
    members.setdefault("ident", "value")
    return database(definition(65000, "one", [field(**members)])).definitions[0].fields[0]


def kinds_of(*definitions):
    kinds, unmapped = c.classify(database(*definitions).definitions)
    return kinds, unmapped


def load(module_text, pack_text):
    """(Module, Pack) through gtcheck with the repository's own model/core.def."""
    model = gtcheck.Model()
    with open(os.path.join(support.REPO, "model", "core.def"), encoding="utf-8") as fh:
        model.add(fh.read(), "model/core.def")
    module = model.add(module_text, MODULE)
    return module, gtcheck.load_pack(pack_text, model, PACK)


def pack_of(text):
    """Codec kinds of a small bits pack over a module with keys i (int), x (float), s (string)."""
    module = 'module t\nversion 0.1.0\ndistribution public\nsource "test"\nkey i int -\nkey x float -\nkey s string -\n'
    header = 'format t\nversion 0.1.0\ndistribution public\nsource "test"\nuses t\nwire bits\nbit_order lsb\nword_bytes 1\n'
    model = gtcheck.Model()
    model.add(c.core_module_text(), "core")
    model.add(module, "t.def")
    return c.codec_kinds(gtcheck.load_pack(header + text, model, "t/pack.def"))


class Workdir(unittest.TestCase):
    """A temporary output root holding a copy of the fixture input."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = support.copy_tree(INPUT, os.path.join(self._tmp.name, "out"))

    def run_gen(self, *argv):
        return support.run_main(c.main, ["--out", self.out] + list(argv))

    def path(self, rel):
        return os.path.join(self.out, *rel.split("/"))

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8") as fh:
            return fh.read()

    def write(self, rel, text):
        with open(self.path(rel), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    def rewrite_database(self, change):
        """Apply `change(db dict)` to sources/canboat.json."""
        db = json.loads(self.read("sources/canboat.json"))
        change(db)
        self.write("sources/canboat.json", json.dumps(db, indent=1))

    def definition(self, db, ident):
        return next(d for d in db["PGNs"] if d["Id"] == ident)


# ---------------------------------------------------------------- the generator as a whole

class GoldenTest(Workdir):
    def test_fixture_database_gives_the_expected_tree(self):
        status, stdout, stderr = self.run_gen()
        self.assertEqual((status, stderr), (0, ""))
        support.assert_same_tree(self, EXPECTED, self.out, ignore=("sources/",))
        self.assertIn("kinds generated: 9 (8 distinct PGNs)", stdout)
        self.assertIn("self-check: passed", stdout)

    def test_second_run_over_its_own_output_changes_nothing(self):
        self.assertEqual(self.run_gen()[0], 0)
        first = support.tree(self.out)
        self.assertEqual(self.run_gen()[0], 0)
        self.assertEqual(support.tree(self.out), first)

    def test_commit_option_writes_the_provenance_of_the_two_source_files_without_a_download(self):
        before = self.read("sources/PROVENANCE.md")
        os.remove(self.path("sources/PROVENANCE.md"))
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("no download without --fetch")):
            status, _, stderr = self.run_gen("--commit", COMMIT)
        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual(self.read("sources/PROVENANCE.md"), before)
        # 267 bytes is the size of the fixture LICENSE; the row is what CONTRIBUTING.md asks of a pack
        self.assertIn("| `LICENSE` | repository path `LICENSE`, 267 bytes, sha256 `", before)

    def test_vector_file_of_an_earlier_run_is_removed(self):
        os.makedirs(self.path("packs/nmea2000/vectors"))
        self.write("packs/nmea2000/vectors/rt-pgn1.json", "{}\n")
        self.write("packs/nmea2000/vectors/notes.txt", "kept\n")
        self.assertEqual(self.run_gen()[0], 0)
        self.assertFalse(os.path.exists(self.path("packs/nmea2000/vectors/rt-pgn1.json")))
        self.assertTrue(os.path.exists(self.path("packs/nmea2000/vectors/notes.txt")))

    def test_same_bytes_when_the_members_of_every_json_object_are_in_reverse_order(self):
        text = self.read("sources/canboat.json")
        reverse = json.loads(text, object_pairs_hook=lambda pairs: dict(reversed(pairs)))
        self.assertNotEqual(list(reverse), list(json.loads(text)))
        self.write("sources/canboat.json", json.dumps(reverse))
        self.assertEqual(self.run_gen()[0], 0)
        support.assert_same_tree(self, EXPECTED, self.out, ignore=("sources/",))

    def test_same_bytes_under_two_hash_seeds(self):
        script = os.path.join(support.GEN, "canboat2pack.py")
        for seed in ("1", "4242"):
            out = support.copy_tree(INPUT, os.path.join(self._tmp.name, "seed" + seed))
            env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1")
            done = subprocess.run([sys.executable, script, "--out", out], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual((done.returncode, done.stderr), (0, b""))
            support.assert_same_tree(self, EXPECTED, out, ignore=("sources/",))


class CheckModeTest(Workdir):
    def test_check_on_a_fresh_output_passes_and_writes_nothing(self):
        self.assertEqual(self.run_gen()[0], 0)
        before = support.tree(self.out)
        status, _, stderr = self.run_gen("--check")
        self.assertEqual(status, 0)
        self.assertIn("--check: ok", stderr)
        self.assertEqual(support.tree(self.out), before)

    def test_check_on_an_empty_output_fails_and_writes_nothing(self):
        before = support.tree(self.out)
        status, _, stderr = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("packs/nmea2000/pack.def is missing", stderr)
        self.assertEqual(support.tree(self.out), before)

    def test_check_names_a_file_with_one_changed_byte_and_leaves_it(self):
        self.assertEqual(self.run_gen()[0], 0)
        rel = "packs/nmea2000/vectors/rt-pgn65301.json"
        self.write(rel, self.read(rel).replace('"n2k.sid": "', '"n2k.sid": "9', 1))
        before = support.tree(self.out)
        status, _, stderr = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn(rel + " differs at line", stderr)
        self.assertEqual(support.tree(self.out), before)

    def test_check_reports_a_stale_vector_file_and_a_changed_provenance(self):
        self.assertEqual(self.run_gen()[0], 0)
        self.write("packs/nmea2000/vectors/rt-pgn1.json", "{}\n")
        self.write("sources/LICENSE", self.read("sources/LICENSE") + "one more line\n")
        status, _, stderr = self.run_gen("--check", "--commit", COMMIT)
        self.assertEqual(status, 1)
        self.assertIn("rt-pgn1.json is not written by the generator", stderr)
        self.assertIn("sources/PROVENANCE.md differs", stderr)

    def test_fetch_is_a_usage_error_with_check_or_without_commit_and_downloads_nothing(self):
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("must not download")):
            self.assertEqual(self.run_gen("--fetch", "--commit", COMMIT, "--check")[0], 2)
            self.assertEqual(self.run_gen("--fetch")[0], 2)

    def test_fetch_downloads_both_files_of_the_commit_with_curl(self):
        with mock.patch.object(subprocess, "run") as run:
            self.assertEqual(self.run_gen("--fetch", "--commit", COMMIT)[0], 0)
        urls = [call.args[0][-1] for call in run.call_args_list]
        self.assertEqual(urls, [
            "https://raw.githubusercontent.com/canboat/canboat/%s/docs/canboat.json" % COMMIT,
            "https://raw.githubusercontent.com/canboat/canboat/%s/LICENSE" % COMMIT])
        first = run.call_args_list[0].args[0]
        self.assertEqual(first[:2], ["curl", "-fsSL"])        # -f: an HTTP error is a failure, not a saved page
        self.assertEqual(first[first.index("-o") + 1], self.path("sources/canboat.json"))
        self.assertIn("--max-time", first)


class LoadedOutputTest(unittest.TestCase):
    """The expected tree, loaded by gtcheck against the repository's core module."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(EXPECTED, *MODULE.split("/")), encoding="utf-8") as fh:
            module_text = fh.read()
        with open(os.path.join(EXPECTED, *PACK.split("/")), encoding="utf-8") as fh:
            cls.module, cls.pack = load(module_text, fh.read())
        cls.kinds = {k.name: k for k in cls.pack.kinds}

    def node(self, kind, key):
        return next(n for n in gtcheck.walk(self.kinds[kind].lines, "field") if n.key == key)

    def test_pack_header_is_the_bits_wire_lsb_with_one_byte_words(self):
        p = self.pack
        self.assertEqual((p.format, p.wire, p.layout, p.bit_order, p.word_bytes, p.distribution),
                         ("nmea2000", "bits", "fixed", "lsb", 1, "public"))
        self.assertEqual(p.uses, ["core", "n2k"])
        self.assertEqual(len(p.sources), 2)

    def test_kinds_are_in_pgn_order_with_the_more_specific_definition_first(self):
        self.assertEqual([k.name for k in self.pack.kinds], [
            "pgn65300_lab_engine_sample_detailed", "pgn65300_lab_engine_sample",
            "pgn65301", "pgn65302", "pgn65303", "pgn65308", "pgn129025", "pgn129026", "pgn129038"])

    def test_every_kind_starts_with_a_when_on_the_24_bit_pgn(self):
        for kind in self.pack.kinds:
            first = kind.lines[0]
            self.assertEqual((first.d, first.start, first.bits), ("when", 0, 24), kind.name)
            self.assertEqual(first.value, kind.name[3:].split("_")[0], kind.name)

    def test_match_fields_become_when_lines_at_bit_offset_plus_24(self):
        whens = [(n.loc, n.value) for n in self.kinds["pgn65300_lab_engine_sample_detailed"].lines if n.d == "when"]
        self.assertEqual(whens, [("0:0:24", "65300"), ("0:24:11", "1999"), ("0:37:3", "4"), ("0:40:3", "2")])

    def test_signed_scaled_field_crossing_a_byte_boundary(self):
        n = self.node("pgn65300_lab_engine_sample_detailed", "n2k.trim_angle")
        self.assertEqual((n.loc, n.start, n.bits, n.tr, n.targs), ("0:48:13", 48, 13, "sscale", ("1/10000",)))
        self.assertEqual(self.module.units["trim_angle"], "rad")

    def test_unsigned_field_with_an_offset(self):
        n = self.node("pgn65300_lab_engine_sample_detailed", "n2k.coolant_temperature")
        self.assertEqual((n.loc, n.tr, n.targs), ("0:64:8", "uscale", ("1/2", "-40")))

    def test_reserved_spare_and_match_fields_are_not_model_keys(self):
        for name in self.module.keys:
            self.assertNotRegex(name, "reserved|spare|manufacturer|industry|sample_mode")

    def test_position_and_speed_go_to_core_keys(self):
        self.assertEqual([(n.key, n.tr, n.targs) for n in self.kinds["pgn129025"].lines if n.d == "field"],
                         [("lat", "sscale", ("1/10000000",)), ("lon", "sscale", ("1/10000000",))])
        self.assertEqual(self.kinds["pgn129025"].requires, ["lat", "lon"])
        self.assertEqual(self.node("pgn129026", "speed_ms").targs, ("1/100",))
        self.assertEqual(self.node("pgn129026", "n2k.cog").targs, ("1/10000",))   # beside cogReference: stays raw

    def test_no_scale_factor_in_the_pack_has_an_exponent(self):
        for n in gtcheck.walk([line for k in self.pack.kinds for line in k.lines], "field"):
            for arg in n.targs:
                self.assertNotRegex(arg, "[eE]", n)

    def test_a_key_that_begins_with_a_digit_is_declared_and_mapped(self):
        self.assertEqual(self.module.keys["2nd_sensor"], "int")
        self.assertEqual(self.node("pgn65301", "n2k.2nd_sensor").loc, "0:80:7")

    def test_pack_md_lists_each_unmapped_definition_under_its_reason(self):
        with open(os.path.join(EXPECTED, "packs", "nmea2000", "pack.md"), encoding="utf-8") as fh:
            md = fh.read()
        for row in ("| 65310 | `labRouteLimits` | Lab: route limits | repeating field set whose count (field 2) is not directly before the set (field 4) |",
                    "| 65305 | `labDeviceName` | Lab: device name | STRING_LAU |",
                    "| 65280 | `labProprietaryRange` | Lab: catch-all for a proprietary range | catch-all definition for a range of PGNs |",
                    "| 65307 | `labAlphaReport` | Lab: report, first reading of the layout | same match values as definition labBetaReport |",
                    "| 65306 | `labHeartbeatMarker` | Lab: marker with no value | fields: LOOKUP (match), RESERVED |",
                    "| `pgn65303` | `signature` | BINARY of 72 bits (no transform carries more than 64 opaque bits) |",
                    "| `pgn65303` | `partNumber` | DECIMAL (two decimal digits per byte; no transform) |"):
            self.assertIn(row, md)


class RepositoryPackTest(unittest.TestCase):
    """The committed nmea2000 pack, read from the repository and not regenerated."""

    def test_committed_pack_loads_and_every_committed_vector_decodes_and_encodes_to_its_expect(self):
        def text(*rel):
            with open(os.path.join(support.REPO, *rel), encoding="utf-8") as fh:
                return fh.read()
        module, pack = load(text("model", "n2k.def"), text("packs", "nmea2000", "pack.def"))
        codec = c.codec_kinds(pack)
        vdir = os.path.join(support.REPO, "packs", "nmea2000", "vectors")
        names = sorted(n for n in os.listdir(vdir) if n.endswith(".json"))
        vectors = [(n, json.loads(text("packs", "nmea2000", "vectors", n))) for n in names]
        self.assertEqual(len([v for _, v in vectors if v["to"] == "nmea2000"]), len(pack.kinds))
        c.check_vectors(codec, vectors)
        c.check_kind_order(codec)
        seq_codec = c.seq_codec_kinds(load(text("model", "n2k.def"), text("packs", "nmea2000-seq", "pack.def"))[1])
        c.check_module_keys_used(module, codec, seq_codec)

    def test_committed_sequential_pack_loads_and_every_committed_vector_holds(self):
        def text(*rel):
            with open(os.path.join(support.REPO, *rel), encoding="utf-8") as fh:
                return fh.read()
        _, pack = load(text("model", "n2k.def"), text("packs", "nmea2000-seq", "pack.def"))
        codec = c.seq_codec_kinds(pack)
        vdir = os.path.join(support.REPO, "packs", "nmea2000-seq", "vectors")
        vectors = [(n, json.loads(text("packs", "nmea2000-seq", "vectors", n)))
                   for n in sorted(os.listdir(vdir)) if n.endswith(".json")]
        for fn, v in vectors:
            data = bytes.fromhex(v["input"])
            if "expect_error" in v:
                with self.assertRaisesRegex(c.GenError, "^%s$" % v["expect_error"]):
                    c.seq_decode(codec, data)
                continue
            sel, ent = c.seq_decode(codec, data)
            self.assertEqual(sel.name, v["model"]["@kind"], fn)
            if v["to"] == "nmea2000-seq":
                self.assertEqual(c.seq_encode(sel, ent).hex(), v["expect"], fn)
            else:
                self.assertEqual(c.geojson_text(ent), v["expect"], fn)
        self.assertEqual({v["model"]["@kind"] for _, v in vectors if v["to"] == "nmea2000-seq" and "model" in v},
                         {k.name for k in pack.kinds})

    def test_built_in_core_key_table_is_that_of_the_repository_core_module(self):
        path = os.path.join(support.REPO, "model", "core.def")
        with open(path, encoding="utf-8") as fh:
            c.check_core_def(fh.read(), path)

    def test_core_def_with_another_key_type_is_refused(self):
        text = c.core_module_text().replace("key lat float", "key lat string")
        with self.assertRaisesRegex(c.GenError, r"core\.def: the core keys built into the generator differ \(lat float, lat string\)"):
            c.check_core_def(text, "core.def")


class RefusalTest(Workdir):
    def refused(self, *argv):
        status, stdout, stderr = self.run_gen(*argv)
        self.assertEqual(status, 1)
        self.assertEqual(stderr.count("\n"), 1, stderr)
        self.assertTrue(stderr.startswith("canboat2pack: "), stderr)
        self.assertNotIn("self-check: passed", stdout)
        self.assertFalse(os.path.exists(self.path(PACK)))
        return stderr

    def test_json_that_does_not_parse_names_the_file_and_the_line(self):
        self.write("sources/canboat.json", '{\n "PGNs": [\n  {"PGN": 1},\n  oops\n ]\n}\n')
        self.assertRegex(self.refused(), r"sources.canboat\.json:4: not JSON: ")

    def test_missing_member_names_the_file_the_json_path_and_the_definition(self):
        self.rewrite_database(lambda db: self.definition(db, "labTankLevel")["Fields"][1].pop("FieldType"))
        self.assertRegex(self.refused(), r"sources.canboat\.json: PGNs\[3\]\.Fields\[1\]\.FieldType "
                                         r"\(PGN 65301 labTankLevel\): is missing; expected a string")

    def test_mistyped_member_names_what_was_found(self):
        self.rewrite_database(lambda db: self.definition(db, "labPressure")["Fields"][0].update(BitLength="8"))
        self.assertIn("PGNs[4].Fields[0].BitLength (PGN 65302 labPressure): expected an integer, found a string",
                      self.refused())

    def test_definition_without_a_pgn_number_is_named_by_its_position(self):
        self.rewrite_database(lambda db: db["PGNs"][2].pop("PGN"))
        self.assertIn("canboat.json: PGNs[2].PGN: is missing; expected an integer", self.refused())

    def test_database_without_a_pgns_array_is_refused(self):
        self.write("sources/canboat.json", '{"Version": "1"}')
        self.assertIn("canboat.json: PGNs: is missing; expected an array", self.refused())

    def test_offset_whose_range_minimum_does_not_confirm_it_is_refused(self):
        self.rewrite_database(
            lambda db: self.definition(db, "labEngineSampleDetailed")["Fields"][7].update(RangeMin=0))
        self.assertIn("PGNs[2].Fields[7] (PGN 65300 labEngineSampleDetailed): field coolantTemperature "
                      "has Offset -40 but RangeMin 0", self.refused())

    def test_match_value_that_does_not_fit_its_field_is_refused(self):
        self.rewrite_database(lambda db: self.definition(db, "labEngineSample")["Fields"][2].update(Match=8))
        self.assertIn("Match value of industryCode does not fit its field", self.refused())

    def test_unknown_field_type_is_refused_and_not_dropped(self):
        self.rewrite_database(lambda db: self.definition(db, "labPressure")["Fields"][1].update(FieldType="TENSOR"))
        self.assertIn("PGNs[4].Fields[1] (PGN 65302 labPressure): unhandled CANboat field type TENSOR", self.refused())

    def test_two_field_ids_of_one_definition_that_give_one_key_name_are_refused(self):
        def change(db):
            self.definition(db, "labPressure")["Fields"][2]["Id"] = "Pressure"
        self.rewrite_database(change)
        self.assertRegex(self.refused(), r"labPressure\): key \S*pressure declared with two signatures")

    def test_database_without_a_definition_the_cross_format_vectors_name_is_refused(self):
        self.rewrite_database(lambda db: db["PGNs"].remove(self.definition(db, "cogSogRapidUpdate")))
        self.assertIn("cross-format vector x03-pgn129026-to-geojson: definition cogSogRapidUpdate has no kind",
                      self.refused())

    def test_no_provenance_and_no_commit_is_refused(self):
        os.remove(self.path("sources/PROVENANCE.md"))
        self.assertRegex(self.refused(), r"PROVENANCE\.md: cannot read: .*; give --commit <sha>")

    def test_provenance_without_a_commit_row_is_refused(self):
        self.write("sources/PROVENANCE.md", "| commit: | `abc` |\n")
        self.assertIn("PROVENANCE.md: no `| commit: |", self.refused())

    def test_short_commit_is_refused(self):
        self.assertIn("--commit takes a full 40-character SHA", self.refused("--commit", "1111111"))

    def test_missing_database_says_how_to_download_it_and_does_not_download(self):
        os.remove(self.path("sources/canboat.json"))
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("must not download")):
            self.assertRegex(self.refused("--commit", COMMIT),
                             r"canboat\.json: cannot read: .*; download it with --commit <sha> --fetch")

    def test_failed_download_is_one_line_with_the_url(self):
        failure = subprocess.CalledProcessError(22, ["curl"])
        with mock.patch.object(subprocess, "run", side_effect=failure):
            self.assertIn("/docs/canboat.json: download failed", self.refused("--fetch", "--commit", COMMIT))


# ---------------------------------------------------------------- parse

class ParseDatabaseTest(unittest.TestCase):
    def test_members_the_database_leaves_out_read_as_absent(self):
        f = source_field(field_type="LOOKUP", length=4, LookupEnumeration="T")
        self.assertEqual((f.resolution, f.offset, f.unit, f.range_min, f.range_max), (None,) * 5)
        self.assertEqual((f.signed, f.has_match, f.variable_length, f.lookup, f.label), (False, False, False, "T", "value"))

    def test_each_of_the_four_lookup_members_names_the_lookup_table(self):
        for member in ("LookupEnumeration", "LookupBitEnumeration", "LookupIndirectEnumeration",
                       "LookupFieldTypeEnumeration"):
            self.assertEqual(source_field(**{member: "TABLE"}).lookup, "TABLE", member)

    def test_boolean_is_not_accepted_as_a_bit_length(self):
        with self.assertRaisesRegex(c.GenError, r"Fields\[0\]\.BitLength \(PGN 65000 one\): expected an integer, found true or false"):
            source_field(length=True)

    def test_negative_bit_offset_is_refused(self):
        with self.assertRaisesRegex(c.GenError, r"db\.json: PGNs\[0\]\.Fields\[0\]\.BitOffset \(PGN 65000 one\): is negative"):
            source_field(offset=-1)

    def test_catch_all_definition_needs_no_fields_member(self):
        d = definition(65280, "range", [], Fallback=True)
        del d["Fields"]
        self.assertEqual(database(d).definitions[0].fields, [])

    def test_top_level_array_is_refused(self):
        with self.assertRaisesRegex(c.GenError, "db.json: expected an object at the top, found an array"):
            c.parse_database("[]", "db.json")

    def test_gen_error_text_is_file_line_message(self):
        self.assertEqual(str(c.GenError("what", "a.json", 7)), "a.json:7: what")
        self.assertEqual(str(c.GenError("what", "a.json")), "a.json: what")
        self.assertEqual(str(c.GenError("what")), "what")

    def test_read_commit_takes_the_sha_of_the_commit_row(self):
        text = "| repository | x |\n| commit: | `%s` |\n" % ("ab" * 20)
        self.assertEqual(c.read_commit(text, "P.md"), "ab" * 20)


# ---------------------------------------------------------------- names and numbers

class SnakeTest(unittest.TestCase):
    def test_camel_case_ids_become_lower_case_with_underscores(self):
        self.assertEqual(c.snake("cogReference"), "cog_reference")
        self.assertEqual(c.snake("aisClassAPositionReport"), "ais_class_aposition_report")
        self.assertEqual(c.snake("sid"), "sid")

    def test_runs_of_other_characters_become_one_underscore_and_ends_are_trimmed(self):
        self.assertEqual(c.snake("wind-speed"), "wind_speed")
        self.assertEqual(c.snake("wind  speed (max)"), "wind_speed_max")
        self.assertEqual(c.snake("_tank__level_"), "tank_level")

    def test_leading_digit_is_kept(self):
        self.assertEqual(c.snake("2ndSensor"), "2nd_sensor")

    def test_ids_that_differ_only_in_case_or_separator_give_one_name(self):
        self.assertEqual({c.snake(i) for i in ("tankLevel", "tank_level", "TankLevel", "tank level")}, {"tank_level"})


class FactorTextTest(unittest.TestCase):
    def test_decimal_resolution_is_written_as_a_fraction_in_lowest_terms(self):
        # engine-spec 0.5 ruling 1: an exact ratio is written <num>/<den>
        for res, want in ((1e-07, "1/10000000"), (0.01, "1/100"), (0.0001, "1/10000"), (0.004, "1/250"),
                          (0.002, "1/500"), (0.5, "1/2"), (2.5, "5/2"), (3.125e-08, "1/32000000"),
                          (1e-16, "1/10000000000000000")):
            self.assertEqual(c.factor_text(res), want, res)

    def test_whole_resolution_is_written_as_an_integer(self):
        self.assertEqual(c.factor_text(1), "1")
        self.assertEqual(c.factor_text(100.0), "100")
        self.assertEqual(c.factor_text(3600), "3600")

    def test_resolution_printed_from_pi_stays_a_decimal(self):
        # 0.0174532925199 is pi/180 cut to 13 digits: as a fraction its numerator has 12 digits
        self.assertEqual(c.factor_text(0.0174532925199), "0.0174532925199")
        self.assertEqual(c.factor_text(5.72957795131e-05), "0.0000572957795131")

    def test_fraction_whose_denominator_is_not_a_double_stays_a_decimal(self):
        # 10**23 is not exactly a double, so den as a double would not be the written den
        self.assertEqual(c.factor_text(1e-23), "0." + "0" * 22 + "1")

    def test_no_factor_text_has_an_exponent(self):
        for res in (1e-07, 3.125e-08, 1e-16, 1e-23, 5.72957795131e-05, 1e-09, 1e20, 123456789.0):
            self.assertRegex(c.factor_text(res), r"\A[0-9]+(?:\.[0-9]+|/[0-9]+)?\Z", res)

    def test_factor_text_reads_back_to_the_resolution(self):
        for res in (1e-07, 0.01, 0.004, 2.5, 3.125e-08, 0.0174532925199):
            num, den = c.parse_factor(c.factor_text(res))
            self.assertEqual(num if den is None else num / den, res)
            self.assertEqual(gtcheck.parse_factor(c.factor_text(res)) is not None, True)


class PlainTest(unittest.TestCase):
    def test_small_and_large_floats_are_written_without_an_exponent(self):
        self.assertEqual(c.plain(1e-07), "0.0000001")
        self.assertEqual(c.plain(3.125e-08), "0.00000003125")
        self.assertEqual(c.plain(1e16), "10000000000000000")
        self.assertEqual(c.plain(1.5e17), "150000000000000000")

    def test_whole_floats_have_no_fraction_part_and_zero_has_no_sign(self):
        self.assertEqual(c.plain(100.0), "100")
        self.assertEqual(c.plain(-40.0), "-40")
        self.assertEqual(c.plain(-0.0), "0")
        self.assertEqual(c.plain(7), "7")

    def test_shortest_text_that_reads_back_to_the_same_double(self):
        self.assertEqual(c.plain(0.1), "0.1")
        self.assertEqual(c.plain(-273.15), "-273.15")
        self.assertEqual(float(c.plain(0.0001 * 180.0 / math.pi)), 0.0001 * 180.0 / math.pi)


class ScaleTest(unittest.TestCase):
    def test_parse_factor_gives_doubles_for_a_fraction_and_one_double_for_a_decimal(self):
        self.assertEqual(c.parse_factor("1/10000000"), (1.0, 10000000.0))
        self.assertEqual(c.parse_factor("5/2"), (5.0, 2.0))
        self.assertEqual(c.parse_factor("0.5"), (0.5, None))

    def test_round_half_away_from_zero(self):
        for q, want in ((0.5, 1), (-0.5, -1), (1.5, 2), (-1.5, -2), (2.5, 3), (-2.5, -3),
                        (0.49, 0), (-0.49, 0), (2.4, 2), (-2.6, -3), (0.0, 0)):
            self.assertEqual(c.round_half_away(q), want, q)

    def test_fraction_decode_divides_so_the_result_is_the_nearest_double(self):
        # 525000000 / 10000000 is exactly 52.5. 13 / 10000000 is the double nearest to
        # 1.3e-06; the product 13 * 1e-07 is another double, which is why ruling 1 divides.
        self.assertEqual(c.scale_decode(525000000, (1.0, 1e7), 0.0), 52.5)
        self.assertEqual(c.scale_decode(13, (1.0, 1e7), 0.0), 1.3e-06)
        self.assertNotEqual(c.scale_decode(13, (1e-07, None), 0.0), 1.3e-06)

    def test_offset_is_added_after_scaling_and_removed_before(self):
        # raw 16 at 1/2 degree per step from -40: 16 / 2 - 40 = -32
        self.assertEqual(c.scale_decode(16, (1.0, 2.0), -40.0), -32.0)
        self.assertEqual(c.scale_encode(-32.0, (1.0, 2.0), -40.0), 16)

    def test_encode_rounds_a_half_step_away_from_zero_on_both_sides(self):
        # 0.25 at 1/2 per step is half a step
        self.assertEqual(c.scale_encode(0.25, (1.0, 2.0), 0.0), 1)
        self.assertEqual(c.scale_encode(-0.25, (1.0, 2.0), 0.0), -1)
        self.assertEqual(c.scale_encode(0.2, (1.0, 2.0), 0.0), 0)
        self.assertEqual(c.scale_encode(-33.75, (1.0, 1e7), 0.0), -337500000)

    def test_decimal_factor_multiplies_and_divides(self):
        self.assertEqual(c.scale_decode(4, (2.5, None), 0.0), 10.0)
        self.assertEqual(c.scale_encode(10.0, (2.5, None), 0.0), 4)


# ---------------------------------------------------------------- plan

class MapFieldTest(unittest.TestCase):
    def test_signed_field_with_a_resolution_is_sscale_in_the_database_unit(self):
        f = source_field(length=13, Resolution=0.0001, Signed=True, Unit="rad")
        self.assertEqual(c.map_field(f), ("field", "sscale:1/10000", "float", "rad"))

    def test_unsigned_field_with_a_resolution_is_uscale(self):
        f = source_field(length=16, Resolution=0.01, Signed=False, Unit="m/s")
        self.assertEqual(c.map_field(f), ("field", "uscale:1/100", "float", "m/s"))

    def test_resolution_one_absent_or_null_is_an_integer(self):
        self.assertEqual(c.map_field(source_field(Resolution=1, Signed=True)), ("field", "twos", "int", "-"))
        self.assertEqual(c.map_field(source_field(Resolution=1)), ("field", "uint", "int", "-"))
        self.assertEqual(c.map_field(source_field()), ("field", "uint", "int", "-"))
        self.assertEqual(c.map_field(source_field(Resolution=None, Signed=True)), ("field", "twos", "int", "-"))

    def test_offset_gives_uscale_with_the_offset_as_second_argument(self):
        f = source_field(Resolution=0.5, Offset=-40, RangeMin=-40, Unit="C")
        self.assertEqual(c.map_field(f), ("field", "uscale:1/2:-40", "float", "C"))
        f = source_field(Resolution=1, Offset=-273.15, RangeMin=-273.15)
        self.assertEqual(c.map_field(f), ("field", "uscale:1:-273.15", "float", "-"))

    def test_offset_zero_is_no_offset(self):
        self.assertEqual(c.map_field(source_field(Resolution=0.1, Offset=0, RangeMin=5))[1], "uscale:1/10")

    def test_reserved_and_spare_never_become_a_field(self):
        self.assertEqual(c.map_field(source_field(field_type="RESERVED")), ("skip",))
        self.assertEqual(c.map_field(source_field(field_type="SPARE", Resolution=0.1)), ("skip",))

    def test_match_field_is_a_when_value_whatever_its_type(self):
        self.assertEqual(c.map_field(source_field(field_type="LOOKUP", length=11, Match=1999)), ("when", 1999))
        self.assertEqual(c.map_field(source_field(length=3, Match=7)), ("when", 7))
        with self.assertRaisesRegex(c.GenError, "does not fit"):
            c.map_field(source_field(length=3, Match=8))

    def test_lookups_dates_and_addresses_are_the_wire_integer(self):
        for ft in ("LOOKUP", "INDIRECT_LOOKUP", "BITLOOKUP", "FIELD_INDEX", "DATE", "MMSI", "PGN", "ISO_NAME", "ADDRESS"):
            self.assertEqual(c.map_field(source_field(field_type=ft, length=16))[1:3], ("uint", "int"), ft)

    def test_types_no_transform_carries_are_declined_with_a_reason(self):
        self.assertEqual(c.map_field(source_field(length=65))[0], "no")
        self.assertEqual(c.map_field(source_field(length=0))[0], "no")
        self.assertEqual(c.map_field(source_field(field_type="FLOAT", length=64)), ("no", "FLOAT of 64 bits"))
        self.assertEqual(c.map_field(source_field(field_type="STRING_FIX", length=12))[0], "no")
        self.assertEqual(c.map_field(source_field(field_type="STRING_FIX", length=2048))[0], "no")
        self.assertEqual(c.map_field(source_field(field_type="BINARY", length=72))[0], "no")
        self.assertEqual(c.map_field(source_field(field_type="DECIMAL", length=16))[0], "no")

    def test_float_string_and_short_binary(self):
        self.assertEqual(c.map_field(source_field(field_type="FLOAT", length=32, Unit="V")), ("field", "f32", "float", "V"))
        self.assertEqual(c.map_field(source_field(field_type="STRING_FIX", length=2040)), ("field", "ascii", "string", "-"))
        self.assertEqual(c.map_field(source_field(field_type="BINARY", length=64)), ("field", "uint", "int", "-"))


class VariableReasonTest(unittest.TestCase):
    def reason(self, d):
        return c.variable_reason(database(d).definitions[0])

    def test_fixed_layout_definition_has_no_reason(self):
        self.assertIsNone(self.reason(definition(1, "a", [field("x"), field("r", "RESERVED", 8, 8)])))

    def test_repeating_field_set_is_declined(self):
        d = definition(1, "a", [field("x")], RepeatingFieldSet2Size=1)
        self.assertEqual(self.reason(d), ("repeating", "repeating field set"))

    def test_variable_length_types_are_listed_once_each_in_sorted_order(self):
        d = definition(1, "a", [field("x"), field("s", "STRING_LZ", None, 8), field("t", "STRING_LAU", None, None),
                                field("u", "STRING_LZ", None, None), field("b", "BINARY", 8, None, BitLengthVariable=True),
                                field("n", "NUMBER", None, None)])
        self.assertEqual(self.reason(d), ("variable", "BINARY of variable size, NUMBER without a length, STRING_LAU, STRING_LZ"))

    def test_fixed_length_field_without_an_offset_is_conditionally_placed(self):
        d = definition(1, "a", [field("x"), field("y", offset=None)])
        self.assertEqual(self.reason(d), ("variable", "field position depends on a condition"))

    def test_catch_all_definition_is_a_pgn_range_before_anything_else(self):
        d = definition(1, "a", [field("s", "STRING_LAU", None, None)], Fallback=True, RepeatingFieldSet1Size=1)
        self.assertEqual(self.reason(d)[0], "pgn-range")


class LocatorTest(unittest.TestCase):
    """Fields at CANboat bit offsets 0, 3, 8 and 13 of the payload."""

    def setUp(self):
        fields = [field("a", length=3, offset=0), field("b", length=5, offset=3),
                  field("c", length=5, offset=8), field("d", length=20, offset=13)]
        kinds, _ = kinds_of(definition(65000, "one", fields))
        self.kind = kinds[0]

    def test_locator_is_word_zero_bit_offset_plus_24_and_the_length(self):
        self.assertEqual([f.locator for f in self.kind.fields], ["0:24:3", "0:27:5", "0:32:5", "0:37:20"])

    def test_fields_land_on_the_hand_worked_payload_bytes(self):
        raw = {"a": 0b101, "b": 0b10010, "c": 0b00111, "d": 0xABCDE}
        data = c.pack_message(self.kind, {f: raw[f.id] for f in self.kind.fields})
        # PGN 65000 = 0x00FDE8, little-endian: e8 fd 00
        # payload byte 0: b (10010) above a (101)                      = 10010101 = 0x95
        # payload byte 1: low 3 bits of d (0xE = 1110 -> 110) above c  = 11000111 = 0xc7
        # d = 0xABCDE >> 3 = 0x1579B for the next 17 bits              = 9b 57 and the low bit of the last byte
        self.assertEqual(data.hex(), "e8fd00" "95" "c7" "9b57" "01")
        for f in self.kind.fields:
            self.assertEqual(c.get_bits(data, f.pos, f.len), raw[f.id], f.id)


class RelationTest(unittest.TestCase):
    def test_match_bits_are_the_value_bits_from_the_low_bit_up(self):
        # 5 = 0b101 at bit 24
        self.assertEqual(c.match_bits({(24, 3): 5}), {24: 1, 25: 0, 26: 1})

    def test_relations_between_match_sets(self):
        head = {(24, 11): 1999}
        more = {(24, 11): 1999, (40, 3): 2}
        self.assertEqual(c.relation(head, dict(head)), "equal")
        self.assertEqual(c.relation(more, head), "super")
        self.assertEqual(c.relation(head, more), "sub")
        self.assertEqual(c.relation(head, {(24, 11): 1998}), "conflict")
        self.assertEqual(c.relation(head, {(40, 3): 2}), "incomparable")
        self.assertEqual(c.relation({}, {}), "equal")
        self.assertEqual(c.relation({}, head), "sub")

    def test_match_sets_are_compared_bit_by_bit_not_field_by_field(self):
        # one 16-bit match that holds 600 in its low 11 bits and 4 in bits 13..15
        wide = {(24, 16): 600 | (4 << 13)}
        self.assertEqual(c.relation(wide, {(24, 11): 600}), "super")
        self.assertEqual(c.relation(wide, {(37, 3): 4}), "super")
        self.assertEqual(c.relation(wide, {(37, 3): 5}), "conflict")
        self.assertEqual(c.relation({(24, 11): 600, (35, 2): 0, (37, 3): 4}, wide), "equal")


def head(mfr, *more):
    """Match fields of a proprietary definition: 11 bits manufacturer, 2 reserved, 3 industry."""
    fields = [field("manufacturerCode", "LOOKUP", 11, 0, Match=mfr), field("reserved", "RESERVED", 2, 11),
              field("industryCode", "LOOKUP", 3, 13, Match=4)]
    at = 16
    for f in more:
        f = dict(f, BitOffset=at)
        at += f["BitLength"]
        fields.append(f)
    return fields


class ClassifyTest(unittest.TestCase):
    def test_single_definition_of_a_pgn_is_named_by_the_number_alone(self):
        kinds, unmapped = kinds_of(definition(65001, "onlyOne", [field("x")]))
        self.assertEqual(([k.name for k in kinds], unmapped), (["pgn65001"], []))
        self.assertEqual(kinds[0].whens, [(0, 24, 65001, "PGN")])

    def test_more_specific_variant_comes_first_whatever_the_source_order(self):
        generic = definition(65002, "generic", head(7, field("r", "RESERVED", 8), field("x")))
        specific = definition(65002, "specificOne", head(7, field("fn", length=8, Match=3), field("y")))
        for order in ((generic, specific), (specific, generic)):
            kinds, unmapped = kinds_of(*order)
            self.assertEqual([k.name for k in kinds], ["pgn65002_specific_one", "pgn65002_generic"])
            self.assertEqual(unmapped, [])

    def test_variants_with_conflicting_match_values_keep_source_order(self):
        a = definition(65003, "second", head(9, field("x")))
        b = definition(65003, "first", head(8, field("x")))
        kinds, _ = kinds_of(a, b)
        self.assertEqual([k.name for k in kinds], ["pgn65003_second", "pgn65003_first"])

    def test_two_variants_with_the_same_match_set_are_both_refused(self):
        a = definition(65004, "a", head(7, field("x")))
        b = definition(65004, "b", head(7, field("y")))
        other = definition(65004, "other", head(8, field("z")))
        kinds, unmapped = kinds_of(a, b, other)
        self.assertEqual([k.name for k in kinds], ["pgn65004_other"])
        self.assertEqual([(u.id, u.reason, u.detail) for u in unmapped],
                         [("a", "indistinguishable", "same match values as definition b"),
                          ("b", "indistinguishable", "same match values as definition a")])

    def test_variants_whose_match_sets_overlap_without_containment_are_refused(self):
        a = definition(65005, "a", [field("m", length=8, offset=0, Match=1), field("x", offset=16)])
        b = definition(65005, "b", [field("n", length=8, offset=8, Match=1), field("y", offset=16)])
        kinds, unmapped = kinds_of(a, b)
        self.assertEqual(kinds, [])
        self.assertEqual({u.reason for u in unmapped}, {"indistinguishable"})
        self.assertIn("neither set contains the other", unmapped[0].detail)

    def test_generic_variant_is_refused_when_the_more_specific_definition_has_no_kind(self):
        generic = definition(65006, "generic", head(7, field("x")))
        variable = definition(65006, "specific", head(7, field("fn", length=8, Match=3),
                                                      field("s", "STRING_LAU", 8, BitLengthVariable=True)))
        kinds, unmapped = kinds_of(generic, variable)
        self.assertEqual(kinds, [])
        self.assertEqual([(u.id, u.reason) for u in unmapped], [("specific", "variable"), ("generic", "indistinguishable")])
        self.assertIn("unmapped, more specific definition specific", unmapped[1].detail)

    def test_sibling_with_a_match_field_at_a_variable_position_refuses_the_kind(self):
        fixed = definition(65007, "fixed", head(7, field("x")))
        floating = definition(65007, "floating", [field("s", "STRING_LAU", None, 0), field("m", length=8, offset=None, Match=1)])
        kinds, unmapped = kinds_of(fixed, floating)
        self.assertEqual(kinds, [])
        self.assertIn("match field at a variable position", unmapped[-1].detail)

    def test_catch_all_definition_does_not_count_as_a_second_definition_of_its_pgn(self):
        kinds, unmapped = kinds_of(definition(65008, "range", [field("x")], Fallback=True),
                                   definition(65008, "real", [field("x")]))
        self.assertEqual([k.name for k in kinds], ["pgn65008"])
        self.assertEqual([u.reason for u in unmapped], ["pgn-range"])

    def test_definition_with_only_match_and_reserved_fields_has_no_kind(self):
        kinds, unmapped = kinds_of(definition(65009, "marker", head(7)))
        self.assertEqual(kinds, [])
        self.assertEqual((unmapped[0].reason, unmapped[0].detail), ("no-field", "fields: LOOKUP (match), RESERVED, LOOKUP (match)"))

    def test_every_definition_is_a_kind_or_is_listed_as_unmapped(self):
        with open(os.path.join(INPUT, "sources", "canboat.json"), encoding="utf-8") as fh:
            db = c.parse_database(fh.read(), "canboat.json")
        plan = c.make_plan(db)
        self.assertEqual(sorted([k.id for k in plan.kinds] + [k.id for k in plan.seq] + [u.id for u in plan.unmapped]),
                         sorted(d.id for d in db.definitions))


def number(ident, offset, **members):
    members.setdefault("Resolution", 1)
    return field(ident, "NUMBER", 16, offset, **members)


class AssignKeysTest(unittest.TestCase):
    def plan(self, *definitions):
        kinds, _ = kinds_of(*definitions)
        return kinds, c.assign_keys(kinds)

    def keys_of(self, kind):
        return [f.key for f in kind.fields]

    def test_field_id_that_agrees_everywhere_is_one_key_listing_its_pgns(self):
        kinds, keys = self.plan(definition(65001, "a", [number("sid", 0)]), definition(65002, "b", [number("sid", 0)]))
        self.assertEqual([self.keys_of(k) for k in kinds], [["n2k.sid"], ["n2k.sid"]])
        self.assertEqual((list(keys), keys["sid"].pgns), (["sid"], [65001, 65002]))

    def test_field_id_with_two_resolutions_gets_one_key_per_pgn(self):
        kinds, keys = self.plan(definition(65001, "a", [number("pressure", 0, Resolution=0.1)]),
                                definition(65002, "b", [number("pressure", 0, Resolution=1, Signed=True)]),
                                definition(65003, "c", [number("pressure", 0, Resolution=0.1)]))
        self.assertEqual([self.keys_of(k) for k in kinds],
                         [["n2k.pgn65001_pressure"], ["n2k.pgn65002_pressure"], ["n2k.pgn65003_pressure"]])
        self.assertEqual((keys["pgn65001_pressure"].type, keys["pgn65002_pressure"].type), ("float", "int"))

    def test_definitions_of_one_pgn_that_disagree_get_a_key_per_kind(self):
        kinds, keys = self.plan(definition(65001, "low", head(7, number("rate", 0, Resolution=0.1))),
                                definition(65001, "high", head(8, number("rate", 0, Resolution=0.01))))
        self.assertEqual([self.keys_of(k) for k in kinds], [["n2k.pgn65001_low_rate"], ["n2k.pgn65001_high_rate"]])

    def test_units_and_lookup_tables_are_part_of_the_agreement(self):
        kinds, _ = self.plan(definition(65001, "a", [number("level", 0, Unit="%")]),
                             definition(65002, "b", [number("level", 0, Unit="m")]),
                             definition(65003, "c", [field("mode", "LOOKUP", 4, 0, LookupEnumeration="A")]),
                             definition(65004, "d", [field("mode", "LOOKUP", 4, 0, LookupEnumeration="B")]))
        self.assertEqual([self.keys_of(k)[0] for k in kinds],
                         ["n2k.pgn65001_level", "n2k.pgn65002_level", "n2k.pgn65003_mode", "n2k.pgn65004_mode"])

    def test_bit_length_is_not_part_of_the_agreement(self):
        kinds, keys = self.plan(definition(65001, "a", [field("instance", length=8)]),
                                definition(65002, "b", [field("instance", length=4)]))
        self.assertEqual(list(keys), ["instance"])

    def test_two_source_names_that_sanitize_to_one_key_share_it_when_they_agree(self):
        kinds, keys = self.plan(definition(65001, "a", [number("tankLevel", 0, Resolution=0.004)]),
                                definition(65002, "b", [number("tank_level", 0, Resolution=0.004)]))
        self.assertEqual((list(keys), keys["tank_level"].pgns), (["tank_level"], [65001, 65002]))

    def test_two_source_names_that_sanitize_to_one_key_get_distinct_keys_when_they_disagree(self):
        a = definition(65001, "a", [number("windSpeed", 0, Resolution=0.01)])
        b = definition(65002, "b", [number("wind-speed", 0, Resolution=0.1)])
        for order in ((a, b), (b, a)):
            kinds, keys = self.plan(*order)
            self.assertEqual(sorted(keys), ["pgn65001_wind_speed", "pgn65002_wind_speed"])
            self.assertEqual({k.pgn: self.keys_of(k) for k in kinds},
                             {65001: ["n2k.pgn65001_wind_speed"], 65002: ["n2k.pgn65002_wind_speed"]})

    def test_two_ids_of_one_definition_that_sanitize_to_one_key_are_refused(self):
        with self.assertRaisesRegex(c.GenError, r"PGN 65001 a\): kind pgn65001 maps key n2k\.tank_level twice"):
            self.plan(definition(65001, "a", [number("tankLevel", 0), number("tank_level", 16)]))

    def test_requires_lists_the_six_keys_fewest_kinds_use_in_field_order(self):
        names = ["sid", "b", "c", "d", "e", "f", "g", "h"]
        wide = definition(65001, "wide", [number(n, 16 * i) for i, n in enumerate(names)])
        others = [definition(65002 + i, "o%d" % i, [number(n, 0)]) for i, n in enumerate(["sid", "sid", "d"])]
        kinds, _ = self.plan(wide, *others)
        # sid is used by 3 kinds and d by 2: the six rarest of the eight leave those two out
        self.assertEqual(kinds[0].requires, ["n2k.b", "n2k.c", "n2k.e", "n2k.f", "n2k.g", "n2k.h"])

    def test_kind_with_only_core_keys_requires_them(self):
        sog = number("sog", 0, Resolution=0.01, Unit="m/s")
        kinds, keys = self.plan(definition(65001, "a", [sog]), definition(65002, "b", [number("x", 0)]))
        self.assertEqual((kinds[0].requires, self.keys_of(kinds[0])), (["speed_ms"], ["speed_ms"]))
        self.assertEqual(list(keys), ["x"])


def position(ident, quantity, offset, **members):
    f = field(ident, "NUMBER", 32, offset, Resolution=1e-07, Signed=True, Unit="deg", PhysicalQuantity=quantity)
    f.update(members)
    return f


class CoreMappingTest(unittest.TestCase):
    def core(self, *fields):
        kinds, _ = kinds_of(definition(65001, "a", list(fields)))
        return {f.id: v for f, v in c.core_mapping(kinds[0]).items()}

    def test_one_latitude_and_one_longitude_in_degrees_are_lat_and_lon(self):
        got = self.core(position("latitude", "GEOGRAPHICAL_LATITUDE", 0), position("longitude", "GEOGRAPHICAL_LONGITUDE", 32))
        self.assertEqual(got, {"latitude": ("lat", "sscale:1/10000000"), "longitude": ("lon", "sscale:1/10000000")})

    def test_second_latitude_field_keeps_every_position_in_the_module(self):
        got = self.core(position("latitude", "GEOGRAPHICAL_LATITUDE", 0), position("longitude", "GEOGRAPHICAL_LONGITUDE", 32),
                        position("waypointLatitude", "GEOGRAPHICAL_LATITUDE", 64))
        self.assertEqual(got, {})

    def test_position_in_another_unit_or_resolution_is_not_a_core_position(self):
        lon = position("longitude", "GEOGRAPHICAL_LONGITUDE", 32)
        self.assertEqual(self.core(position("latitude", "GEOGRAPHICAL_LATITUDE", 0, Unit="rad"), lon), {})
        self.assertEqual(self.core(position("latitude", "GEOGRAPHICAL_LATITUDE", 0, Resolution=1e-06), lon), {})
        self.assertEqual(self.core(position("latitude", "GEOGRAPHICAL_LATITUDE", 0, Signed=False), lon), {})

    def test_sog_in_metres_per_second_is_speed_ms_and_a_signed_or_knots_sog_is_not(self):
        self.assertEqual(self.core(number("sog", 0, Resolution=0.01, Unit="m/s")), {"sog": ("speed_ms", "uscale:1/100")})
        self.assertEqual(self.core(number("sog", 0, Resolution=0.01, Unit="kn")), {})
        self.assertEqual(self.core(number("sog", 0, Resolution=0.01, Unit="m/s", Signed=True)), {})

    def test_cog_stated_true_with_no_reference_field_is_course_in_degrees(self):
        got = self.core(number("cog", 0, Resolution=0.0001, Unit="rad", Name="COG True"))
        # radians to degrees: 0.0001 * 180 / pi per step
        self.assertEqual(got, {"cog": ("course", "uscale:0.005729577951308233")})
        self.assertEqual(float(got["cog"][1].split(":")[1]), 0.0001 * 180.0 / math.pi)

    def test_cog_beside_a_reference_selector_or_without_the_word_true_stays_in_the_module(self):
        cog = number("cog", 16, Resolution=0.0001, Unit="rad", Name="COG True")
        self.assertEqual(self.core(field("cogReference", "LOOKUP", 2, 0), cog), {})
        self.assertEqual(self.core(number("cog", 0, Resolution=0.0001, Unit="rad", Name="COG", Description="untrue")), {})

    def test_altitude_stated_above_the_ellipsoid_is_hae(self):
        alt = field("altitude", "NUMBER", 32, 0, Resolution=0.01, Signed=True, Unit="m")
        self.assertEqual(self.core(dict(alt, Description="Height above the WGS84 Ellipsoid")), {"altitude": ("hae", "sscale:1/100")})
        self.assertEqual(self.core(dict(alt, Description="Altitude")), {})
        self.assertEqual(self.core(alt), {})


# ---------------------------------------------------------------- emit

class EmitTest(unittest.TestCase):
    def test_quotes_and_line_breaks_cannot_end_a_quoted_token(self):
        self.assertEqual(c.q('a "b"\nc'), "\"a 'b' c\"")
        self.assertEqual(gtcheck.tokenize("source " + c.q('say "x" # y')), ["source", "say 'x' # y"])

    def test_unit_with_a_space_or_a_leading_hash_is_quoted(self):
        self.assertEqual(c.unit_token("m/s"), "m/s")
        self.assertEqual(c.unit_token("dB re 1 V"), '"dB re 1 V"')
        self.assertEqual(c.unit_token("#count"), '"#count"')

    def test_description_with_a_line_break_or_a_hash_stays_one_comment_line_and_the_pack_loads(self):
        db = database(definition(65001, "a", [field("x")], Description='two\nlines "q" # | x', Complete=False))
        plan = c.make_plan(db)
        pack_text = c.emit_pack(plan.kinds, COMMIT, db)
        self.assertIn('\n# PGN 65001 a: two lines "q" # | x [CANboat: incomplete]\nkind      pgn65001\n', pack_text)
        _, pack = load(c.emit_module(plan.keys, COMMIT, db), pack_text)
        self.assertEqual([k.name for k in pack.kinds], ["pgn65001"])

    def test_module_line_states_type_unit_label_field_type_and_at_most_four_pgns(self):
        defs = [definition(65001 + i, "d%d" % i, [field("mode", "LOOKUP", 4, 0, Name="Mode", LookupEnumeration="M")])
                for i in range(6)]
        db = database(*defs)
        text = c.emit_module(c.make_plan(db).keys, COMMIT, db)
        self.assertIn('key  mode  int     -         "Mode; CANboat LOOKUP M; PGN 65001, 65002, 65003, 65004 and 2 more"\n', text)

    def test_unmapped_table_replaces_the_column_separator_in_a_description(self):
        db = database(definition(65001, "a", [field("x")]),
                      definition(65002, "b", [field("x")], Description="one | two", RepeatingFieldSet1Size=1))
        plan = c.make_plan(db)
        md = c.emit_pack_md(plan.kinds, plan.unmapped, plan.keys, db, COMMIT, 1, [])
        self.assertIn("| 65002 | `b` | one / two | repeating field set with no count field: "
                      "it repeats to the end of the message |", md)
        self.assertIn("### Catch-all definitions for a range of PGNs (0)\n\nNone.\n", md)


# ---------------------------------------------------------------- codec

class GetBitsTest(unittest.TestCase):
    # bytes 0xB4 0x69 0xC3 = 10110100 01101001 11000011; bit 0 is the low bit of the first byte
    DATA = bytes([0xB4, 0x69, 0xC3])

    def test_field_inside_the_first_byte(self):
        self.assertEqual(c.get_bits(self.DATA, 0, 3), 0b100)
        self.assertEqual(c.get_bits(self.DATA, 3, 5), 0b10110)

    def test_field_crossing_one_byte_boundary(self):
        # bits 3..7 of byte 0 (22) are the low 5 bits, all of byte 1 (105) the next 8
        self.assertEqual(c.get_bits(self.DATA, 3, 13), 105 * 32 + 22)

    def test_byte_aligned_field(self):
        self.assertEqual(c.get_bits(self.DATA, 8, 8), 0x69)

    def test_field_at_bit_13_crossing_into_the_third_byte(self):
        # bits 5..7 of byte 1 (0b011) are the low 3 bits, all of byte 2 (195) the next 8
        self.assertEqual(c.get_bits(self.DATA, 13, 11), 195 * 8 + 3)

    def test_field_crossing_two_byte_boundaries(self):
        # bits 6..7 of byte 0 (0b10), byte 1 (105), bits 0..1 of byte 2 (0b11)
        self.assertEqual(c.get_bits(self.DATA, 6, 12), 0b10 + 105 * 4 + 0b11 * 1024)


class CodecTest(unittest.TestCase):
    def test_first_kind_whose_when_lines_hold_is_selected(self):
        kinds = pack_of("kind a\nwhen 0:0:8 1\nwhen 0:8:4 2\nfield t.i 0:12:4 uint\n"
                        "kind b\nwhen 0:0:8 1\nfield t.i 0:8:8 uint\n")
        self.assertEqual(c.decode(kinds, bytes([1, 0x52]))[0].name, "a")
        k, ent = c.decode(kinds, bytes([1, 0x53]))
        self.assertEqual((k.name, dict(ent)), ("b", {"t.i": 0x53}))

    def test_message_no_kind_matches_and_message_too_short_are_refused(self):
        kinds = pack_of("kind a\nwhen 0:0:8 1\nfield t.i 0:8:16 uint\n")
        with self.assertRaisesRegex(c.GenError, "no-kind"):
            c.decode(kinds, bytes([2, 0, 0]))
        with self.assertRaisesRegex(c.GenError, "malformed-wire"):
            c.decode(kinds, bytes([1, 0]))

    def test_twos_sign_extends_from_the_field_length(self):
        kinds = pack_of("kind a\nwhen 0:0:8 1\nfield t.i 0:8:13 twos\n")
        # 13 bits all ones is -1; 0x1000 is the most negative value
        self.assertEqual(c.decode(kinds, bytes([1, 0xFF, 0x1F]))[1]["t.i"], -1)
        self.assertEqual(c.decode(kinds, bytes([1, 0x00, 0x10]))[1]["t.i"], -4096)
        self.assertEqual(c.encode(kinds[0], {"t.i": -1}), bytes([1, 0xFF, 0x1F]))

    def test_uint_of_64_bits_with_the_top_bit_set_is_the_negative_integer(self):
        # engine-spec 0.5 ruling 2
        kinds = pack_of("kind a\nwhen 0:0:8 1\nfield t.i 0:8:64 uint\n")
        data = bytes([1]) + b"\x00" * 7 + b"\x80"
        self.assertEqual(c.decode(kinds, data)[1]["t.i"], -(1 << 63))
        self.assertEqual(c.encode(kinds[0], {"t.i": -(1 << 63)}), data)

    def test_scaled_value_outside_the_field_is_refused_on_encode(self):
        kinds = pack_of("kind a\nwhen 0:0:8 1\nfield t.x 0:8:8 uscale:1/2:-40\n")
        k = kinds[0]
        # 8 unsigned bits at 1/2 from -40 hold -40 .. 87.5
        self.assertEqual(c.encode(k, {"t.x": 87.5}), bytes([1, 255]))
        self.assertEqual(c.encode(k, {"t.x": -40.0}), bytes([1, 0]))
        for x in (88.0, -40.5):
            with self.assertRaisesRegex(c.GenError, "transform-encode: t.x"):
                c.encode(k, {"t.x": x})

    def test_signed_scaled_range_is_asymmetric(self):
        kinds = pack_of("kind a\nwhen 0:0:8 1\nfield t.x 0:8:8 sscale:1/10\n")
        self.assertEqual(c.encode(kinds[0], {"t.x": -12.8}), bytes([1, 0x80]))
        with self.assertRaisesRegex(c.GenError, "transform-encode"):
            c.encode(kinds[0], {"t.x": 12.8})

    def test_ascii_strips_trailing_nul_and_refuses_other_padding(self):
        kinds = pack_of("kind a\nwhen 0:0:8 1\nfield t.s 0:8:32 ascii\n")
        self.assertEqual(c.decode(kinds, b"\x01AB\x00\x00")[1]["t.s"], "AB")
        self.assertEqual(c.encode(kinds[0], {"t.s": "AB"}), b"\x01AB\x00\x00")
        with self.assertRaisesRegex(c.GenError, "transform-decode: ascii"):
            c.decode(kinds, b"\x01AB\xff\xff")
        with self.assertRaisesRegex(c.GenError, "transform-encode: ascii"):
            c.encode(kinds[0], {"t.s": "ABCDE"})

    def test_absent_keys_encode_as_zero_bits(self):
        kinds = pack_of("kind a\nwhen 0:0:8 7\nfield t.i 0:8:8 uint\nfield t.x 0:16:8 uscale:1/2\n")
        self.assertEqual(c.encode(kinds[0], {"t.x": 1.5}), bytes([7, 0, 3]))

    def test_when_value_replaces_the_bits_of_a_field_that_covers_it(self):
        kinds = pack_of("kind a\nwhen 0:0:8 7\nfield t.i 0:0:16 uint\n")
        self.assertEqual(c.encode(kinds[0], {"t.i": 0x12FF}), bytes([7, 0x12]))

    def test_when_past_the_end_of_the_message_does_not_hold_even_for_value_zero(self):
        kinds = pack_of("kind long\nwhen 0:0:8 1\nwhen 0:16:8 0\nfield t.i 0:8:8 uint\n"
                        "kind short\nwhen 0:0:8 1\nfield t.i 0:8:8 uint\n")
        self.assertEqual(c.decode(kinds, bytes([1, 5]))[0].name, "short")
        self.assertEqual(c.decode(kinds, bytes([1, 5, 0]))[0].name, "long")

    def test_common_lines_apply_to_every_kind(self):
        kinds = pack_of("when 0:0:4 9\nfield t.i 0:4:4 uint\nkind a\nwhen 0:8:8 1\nfield t.x 0:16:8 uscale:1/2\n")
        self.assertEqual(kinds[0].whens, [(0, 4, 9), (8, 8, 1)])
        self.assertEqual(dict(c.decode(kinds, bytes([0x39, 1, 4]))[1]), {"t.i": 3, "t.x": 2.0})

    def test_pack_line_the_codec_does_not_cover_is_refused_with_its_line(self):
        with self.assertRaisesRegex(c.GenError, r"t/pack\.def:11: the codec of canboat2pack does not read this field \(transform `linscale`"):
            pack_of("kind a\nwhen 0:0:8 1\nfield t.x 0:8:8 linscale:127:180\n")
        with self.assertRaisesRegex(c.GenError, r"t/pack\.def:11: .* a `const` line"):
            pack_of("kind a\nwhen 0:0:8 1\nconst 0:8:8 3\nfield t.i 0:16:8 uint\n")

    def test_geojson_text_is_canonical(self):
        self.assertEqual(c.geojson_text({"lat": 52.5, "lon": 4.5, "speed_ms": 6.5, "n2k.sid": 1}),
                         '{"type":"Feature","geometry":{"type":"Point","coordinates":[4.5,52.5]},"properties":{"speed_ms":6.5}}')
        self.assertEqual(c.geojson_text({"lat": 1.0}), '{"type":"Feature","geometry":null,"properties":{}}')


# ---------------------------------------------------------------- vectors

class VectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(INPUT, "sources", "canboat.json"), encoding="utf-8") as fh:
            cls.db = c.parse_database(fh.read(), "canboat.json")
        cls.plan = c.make_plan(cls.db)
        cls.kinds = {k.name: k for k in cls.plan.kinds}
        _, pack = c.load_output(c.emit_module(cls.plan.keys, COMMIT, cls.db), c.emit_pack(cls.plan.kinds, COMMIT, cls.db))
        cls.codec = c.codec_kinds(pack)

    def test_pack_message_equals_a_message_packed_by_hand(self):
        k = self.kinds["pgn65300_lab_engine_sample_detailed"]
        raw = {"engineInstance": 14, "trimAngle": 1849, "coolantTemperature": 16, "fuelRate": 31096}
        data = c.pack_message(k, {f: raw[f.id] for f in k.fields})
        # PGN 65300 = 0x00FF14, little-endian:                       14 ff 00
        # manufacturer 1999 = 0x7CF in bits 24..34, industry 4 in bits 37..39:   cf 87
        # mode 2 in bits 40..42, engine instance 14 in bits 43..47 (14 << 3 | 2):  72
        # trim 1849 = 0x0739 in bits 48..60:                              39 07
        # coolant 16 in bits 64..71:                                      10
        # fuel rate 31096 = 0x7978 in bits 72..87:                        78 79
        self.assertEqual(data.hex(), "14ff00" "cf87" "72" "3907" "10" "7879")
        kind, ent = c.decode(self.codec, data)
        self.assertEqual(kind.name, k.name)
        self.assertEqual(dict(ent), {"n2k.engine_instance": 14, "n2k.trim_angle": 0.1849, "n2k.coolant_temperature": -32.0,
                                     "n2k.pgn65300_lab_engine_sample_detailed_fuel_rate": 3109.6})

    def test_message_ends_at_the_last_mapped_bit_rounded_up_to_a_byte(self):
        # labEngineSample: last field ends at bit 68, the 20 reserved bits after it are not written
        k = self.kinds["pgn65300_lab_engine_sample"]
        self.assertEqual(len(c.pack_message(k, {})), 9)
        self.assertEqual(c.pack_message(k, {}).hex(), "14ff00cf87" + "00" * 4)

    def test_generic_message_is_not_taken_for_the_more_specific_kind(self):
        k = self.kinds["pgn65300_lab_engine_sample"]
        self.assertEqual(c.decode(self.codec, c.pack_message(k, c.pick_values(k)))[0].name, k.name)

    def test_picked_values_are_in_range_never_all_ones_and_survive_scaling(self):
        for k in self.plan.kinds:
            vals = c.pick_values(k)
            self.assertEqual(set(vals), set(k.fields))
            for f, v in vals.items():
                self.assertTrue(0 <= v < (1 << f.len), (k.name, f.id))
                if f.len > 1 and f.transform != "ascii":
                    self.assertNotEqual(v, (1 << f.len) - 1, (k.name, f.id))
            data = c.pack_message(k, vals)
            kind, ent = c.decode(self.codec, data)
            self.assertEqual(c.encode(kind, ent), data, k.name)

    def _two_kinds_of_one_pgn(self):
        """A generic kind with one 8-bit field at payload bit 0, and a sibling
        that stands before it and matches a value in those same bits."""
        class Record:       # the attributes pick_values reads, and hashable as the real classes are
            def __init__(self, **members):
                self.__dict__.update(members)

        src = Record(range_min=None, range_max=None)
        field = Record(id="code", pos=c.PGN_BITS, len=8, transform="uint", src=src)
        pgn = (0, c.PGN_BITS, 65310, "PGN")
        generic = Record(name="pgn65310", pgn=65310, whens=[pgn], fields=[field])

        def sibling(value):
            return Record(name="pgn65310_special", pgn=65310, fields=[], whens=[pgn, (c.PGN_BITS, 8, value, "code")])
        return generic, field, sibling

    def test_a_picked_value_never_equals_the_match_value_of_an_earlier_kind_of_the_pgn(self):
        generic, field, sibling = self._two_kinds_of_one_pgn()
        first = c.pick_values(generic)[field]
        # the sibling matches exactly the value the generic kind would pick first
        vals = c.pick_values(generic, [sibling(first)])
        self.assertNotEqual(vals[field], first)
        self.assertTrue(0 < vals[field] < 255)
        self.assertIsNone(c._selected_before(generic, vals, [sibling(first)]))
        self.assertEqual(c.pick_values(generic, [sibling(first)]), vals, "the second choice is repeatable")

    def test_an_earlier_kind_that_does_not_match_leaves_the_first_choice(self):
        generic, field, sibling = self._two_kinds_of_one_pgn()
        first = c.pick_values(generic)[field]
        self.assertEqual(c.pick_values(generic, [sibling(first ^ 1)])[field], first)

    def test_picked_values_respect_the_range_the_database_states(self):
        k = self.kinds["pgn65300_lab_engine_sample"]
        vals = {f.id: v for f, v in c.pick_values(k).items()}
        self.assertTrue(1 <= vals["engineInstance"] <= 30)          # RangeMax 30 in an 8-bit field
        k = self.kinds["pgn129038"]
        vals = {f.id: v for f, v in c.pick_values(k).items()}
        self.assertTrue(-900000000 < vals["latitude"] - (vals["latitude"] >> 31 << 32) < 900000000)   # +-90 degrees

    def test_picked_values_depend_only_on_kind_name_and_field_id(self):
        k = self.kinds["pgn65301"]
        again = c.make_plan(self.db)
        other = next(x for x in again.kinds if x.name == "pgn65301")
        self.assertEqual([c.pick_values(k)[f] for f in k.fields], [c.pick_values(other)[f] for f in other.fields])

    def test_roundtrip_vector_states_every_decoded_key_as_plain_text(self):
        k = self.kinds["pgn65303"]
        ck = next(x for x in self.codec if x.name == "pgn65303")
        v = c.roundtrip_vector(k, self.codec, ck)
        self.assertEqual((v["name"], v["from"], v["to"], v["input"]), ("pgn65303-roundtrip", "nmea2000", "nmea2000", v["expect"]))
        self.assertEqual(list(v["model"]), ["@kind", "n2k.label", "n2k.gain", "n2k.date", "n2k.time"])
        for text in v["model"].values():
            self.assertIsInstance(text, str)
            self.assertNotRegex(text, r"\d[eE][-+]?\d")

    def test_cross_vector_input_is_the_hand_packed_position(self):
        by_id = {k.id: k for k in self.plan.kinds}
        v = c.cross_vector(c.CROSS[1], by_id, self.codec)
        # PGN 129025 = 0x01F801. As 32-bit two's complement, little-endian:
        # -337500000 = 2**32 - 337500000 = 3957467296 = 0xEBE228A0
        # -1512500000 = 2**32 - 1512500000 = 2782467296 = 0xA5D914E0
        self.assertEqual(v["input"], "01f801" "a028e2eb" "e014d9a5")
        self.assertEqual(v["model"], {"@kind": "pgn129025", "lat": "-33.75", "lon": "-151.25"})
        self.assertEqual(json.loads(v["expect"])["geometry"]["coordinates"], [-151.25, -33.75])

    def test_cross_vector_whose_hand_written_expect_is_wrong_is_refused(self):
        by_id = {k.id: k for k in self.plan.kinds}
        name, ident, raw, expect = c.CROSS[0]
        with self.assertRaisesRegex(c.GenError, "hand-written expect differs from the codec"):
            c.cross_vector((name, ident, raw, expect.replace("52.5", "52.6")), by_id, self.codec)

    def test_check_vectors_refuses_a_changed_model_value_and_a_kind_without_a_round_trip(self):
        files, _ = c.build_vectors(self.plan.kinds, self.codec)
        vectors = [(fn, json.loads(text)) for fn, text in files]
        c.check_vectors(self.codec, vectors)
        with self.assertRaisesRegex(c.GenError, "kinds without a round-trip vector: .'pgn129025'"):
            c.check_vectors(self.codec, [v for v in vectors if v[0] != "rt-pgn129025.json"])
        fn, v = vectors[0]
        key = next(k for k in v["model"] if k != "@kind")
        changed = dict(v, model=dict(v["model"], **{key: "1" + v["model"][key]}))
        with self.assertRaisesRegex(c.GenError, "vector %s: %s" % (fn, key)):
            c.check_vectors(self.codec, [(fn, changed)] + vectors[1:])


class OutputInvariantTest(unittest.TestCase):
    def test_kinds_in_an_order_that_hides_the_specific_one_are_refused(self):
        kinds = pack_of("kind generic\nwhen 0:0:24 65300\nwhen 0:24:8 1\nfield t.i 0:40:8 uint\n"
                        "kind specific\nwhen 0:0:24 65300\nwhen 0:24:8 1\nwhen 0:32:8 2\nfield t.i 0:40:8 uint\n")
        with self.assertRaisesRegex(c.GenError, "kinds generic and specific cannot be told apart in this order"):
            c.check_kind_order(kinds)
        c.check_kind_order(list(reversed(kinds)))

    def test_field_that_overlaps_a_when_or_ends_past_the_message_is_refused(self):
        src, _ = kinds_of(definition(65300, "a", [field("m", length=8, offset=0, Match=1), field("x", offset=8)], Length=2))
        src[0].name = "a"
        good = "kind a\nwhen 0:0:24 65300\nwhen 0:24:8 1\nrequires t.i\nfield t.i 0:32:8 uint\n"
        c.check_kind_shapes(pack_of(good), src)
        with self.assertRaisesRegex(c.GenError, "kind a: overlapping bit ranges"):
            c.check_kind_shapes(pack_of(good.replace("0:32:8", "0:28:8")), src)
        with self.assertRaisesRegex(c.GenError, r"kind a: a bit range ends at 48, past the message \(40 bits\)"):
            c.check_kind_shapes(pack_of(good.replace("0:32:8", "0:40:8")), src)
        with self.assertRaisesRegex(c.GenError, "kind a: first when is not its PGN"):
            c.check_kind_shapes(pack_of(good.replace("65300", "65301")), src)

    def test_generated_text_that_breaks_a_load_rule_is_reported_with_file_and_line(self):
        module = 'module n2k\nversion 0.1.0\ndistribution public\nsource "t"\nkey a int -\n'
        pack = ('format nmea2000\nversion 0.1.0\ndistribution public\nsource "t"\nuses n2k\nwire bits\n'
                'bit_order lsb\nword_bytes 1\nkind k\nwhen 0:0:24 1\nfield n2k.a 0:24:8 uscale:1/2\n')
        with self.assertRaisesRegex(c.GenError, r"generated file does not load: packs/nmea2000/pack\.def:11: key-type-mismatch"):
            c.load_output(module, pack)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- the sequential pack nmea2000-seq

SEQ_PACK = "packs/nmea2000-seq/pack.def"


def repeating(pgn, ident, fields, start, count, size=None, **members):
    """A definition with one repeating field set from field `start` to the last field."""
    members.update(RepeatingFieldSet1Size=size if size is not None else len(fields) - start + 1,
                   RepeatingFieldSet1StartField=start)
    if count is not None:
        members["RepeatingFieldSet1CountField"] = count
    return definition(pgn, ident, fields, **members)


def seq_plan_of(*definitions):
    """The plan of these definitions and one plain fixed-layout definition (a plan needs a
    kind of the fixed pack)."""
    return c.make_plan(database(definition(65019, "anchor", [field("x")]), *definitions))


class SeqPlanTest(unittest.TestCase):
    def detail(self, d):
        return c.seq_plan(database(d).definitions[0])[1]

    def test_count_directly_before_the_set_gives_a_kind_with_one_counted_group(self):
        plan = seq_plan_of(repeating(65020, "log", [field("n", offset=0), field("code", offset=8),
                                                     field("value", length=16, offset=16)], start=2, count=1))
        self.assertEqual([k.name for k in plan.seq], ["pgn65020"])
        k = plan.seq[0]
        self.assertEqual((k.count_len, k.count_id, k.list), (8, "n", "pgn65020_n"))
        self.assertEqual([f.id for f in k.item_fields], ["code", "value"])
        self.assertEqual(plan.unmapped, [])

    def test_what_the_language_cannot_state_is_named(self):
        cases = [
            (repeating(65021, "a", [field("x", offset=0), field("y", offset=8)], start=2, count=None),
             "repeating field set with no count field: it repeats to the end of the message"),
            (repeating(65022, "b", [field("n", offset=0), field("r", offset=8), field("y", offset=16)], start=3, count=1),
             "repeating field set whose count (field 1) is not directly before the set (field 3)"),
            (repeating(65023, "c", [field("n", offset=0), field("t", "STRING_LAU", None, 8)], start=2, count=1),
             "repeating field set, and a STRING_LAU field"),
            (repeating(65024, "d", [field("n", offset=0), field("y", offset=8), field("z", offset=16)], start=2, count=1, size=1),
             "fields follow the repeating field set"),
            (repeating(65025, "e", [field("n", offset=0, Signed=True), field("y", offset=8)], start=2, count=1),
             "repeating field set whose count field is not an unsigned integer"),
            (repeating(65026, "f", [field("n", offset=0), field("y", offset=8)], start=2, count=1,
                       RepeatingFieldSet2Size=1, RepeatingFieldSet2StartField=2),
             "two repeating field sets"),
        ]
        for d, want in cases:
            self.assertEqual(self.detail(d), want)

    def test_reserved_between_match_values_is_a_when_of_all_ones_and_after_them_a_const(self):
        fields = [field("manufacturerCode", "LOOKUP", 11, 0, Match=999), field("reserved", "RESERVED", 2, 11),
                  field("industryCode", "LOOKUP", 3, 13, Match=4), field("reserved4", "RESERVED", 70, 16),
                  field("spare5", "SPARE", 2, 86), field("n", offset=88), field("y", offset=96)]
        k = c.seq_plan(database(repeating(65027, "g", fields, start=7, count=6)).definitions[0])[0]
        self.assertEqual([(l, v) for _, l, v, _ in k.whens], [(24, 65027), (11, 999), (2, 3), (3, 4)])
        self.assertEqual(k.lines, [("const", 64, (1 << 64) - 1), ("const", 6, 63), ("pad", 2)])

    def test_match_value_after_a_data_field_is_not_a_kind(self):
        fields = [field("x", offset=0), field("code", "LOOKUP", 8, 8, Match=3), field("n", offset=16), field("y", offset=24)]
        self.assertEqual(self.detail(repeating(65028, "h", fields, start=4, count=3)),
                         "a match value follows a data field (a kind's `when` lines come first)")

    def test_kind_whose_messages_a_fixed_kind_also_accepts_is_not_mapped(self):
        # the fixed kind is the more specific one, so it keeps its kind in nmea2000; the
        # repeating definition would also accept its messages, so it gets none in nmea2000-seq
        fixed = definition(65029, "plain", [field("code", "LOOKUP", 8, 0, Match=1),
                                            field("sub", "LOOKUP", 8, 8, Match=2), field("x", offset=16)])
        rep = repeating(65029, "rep", [field("code", "LOOKUP", 8, 0, Match=1), field("n", offset=8), field("y", offset=16)],
                        start=3, count=2)
        plan = seq_plan_of(fixed, rep)
        self.assertEqual(plan.seq, [])
        why = next(u for u in plan.unmapped if u.id == "rep")
        self.assertEqual((why.reason, why.detail), ("indistinguishable",
                         "a message can satisfy its match values and those of kind pgn65029_plain of pack nmea2000"))

    def test_conflicting_match_values_keep_both_packs(self):
        fixed = definition(65030, "plain", [field("code", "LOOKUP", 8, 0, Match=1), field("x", offset=8)])
        rep = repeating(65030, "rep", [field("code", "LOOKUP", 8, 0, Match=2), field("n", offset=8), field("y", offset=16)],
                        start=3, count=2)
        plan = seq_plan_of(fixed, rep)
        self.assertEqual(([k.name for k in plan.kinds], [k.name for k in plan.seq]),
                         (["pgn65019", "pgn65030_plain"], ["pgn65030_rep"]))

    def test_item_field_reuses_an_agreeing_key_and_never_changes_one_of_the_fixed_pack(self):
        fixed = definition(65031, "plain", [field("level", offset=0, Resolution=0.5), field("mode", "LOOKUP", 8, 8)])
        rep = repeating(65032, "rep", [field("n", offset=0), field("level", offset=8, Resolution=0.5),
                                        field("mode", "LOOKUP", 16, 16, LookupEnumeration="OTHER")], start=2, count=1)
        db = database(fixed, rep)
        plan = c.make_plan(db)
        self.assertEqual([f.key for f in plan.seq[0].item_fields], ["n2k.level", "n2k.pgn65032_mode"])
        alone = c.make_plan(database(fixed))
        text = c.emit_module(plan.keys, COMMIT, db, plan.seq_keys, plan.seq_lists)
        self.assertTrue(text.startswith(c.emit_module(alone.keys, COMMIT, db).rstrip("\n")))
        self.assertIn("\nlist  pgn65032_n  ", text)


class SeqCodecTest(unittest.TestCase):
    """The expected sequential pack of the fixture, read by the codec."""

    @classmethod
    def setUpClass(cls):
        def text(rel):
            with open(os.path.join(EXPECTED, *rel.split("/")), encoding="utf-8") as fh:
                return fh.read()
        cls.pack = load(text(MODULE), text(SEQ_PACK))[1]
        cls.codec = c.seq_codec_kinds(cls.pack)

    def test_pack_header_is_the_bits_wire_lsb_sequential(self):
        self.assertEqual((self.pack.format, self.pack.wire, self.pack.layout, self.pack.bit_order),
                         ("nmea2000-seq", "bits", "sequential", "lsb"))

    def test_hand_packed_message_with_two_items(self):
        # PGN 65304 = 0x00ff18, little-endian; count 2; item 1: code 5, value -1.50 (raw -150 =
        # 0xff6a); item 2: code 7, value 2.50 (raw 250 = 0x00fa); 16-bit values little-endian
        data = bytes.fromhex("18ff00" "02" "05" "6aff" "07" "fa00")
        kind, ent = c.seq_decode(self.codec, data)
        self.assertEqual(kind.name, "pgn65304")
        items = ent["n2k.pgn65304_entries"]
        self.assertEqual([(i["n2k.entry_code"], i["n2k.entry_value"]) for i in items], [(5, -1.5), (7, 2.5)])
        self.assertEqual(c.seq_encode(kind, ent), data)

    def test_present_empty_list_is_a_count_of_zero(self):
        kind, ent = c.seq_decode(self.codec, bytes.fromhex("18ff0000"))
        self.assertEqual(ent["n2k.pgn65304_entries"], [])
        self.assertEqual(c.seq_encode(kind, ent).hex(), "18ff0000")

    def test_count_beyond_the_input_is_malformed_and_a_when_beyond_it_is_no_kind(self):
        with self.assertRaisesRegex(c.GenError, "^malformed-wire$"):
            c.seq_decode(self.codec, bytes.fromhex("18ff0002056aff"))
        with self.assertRaisesRegex(c.GenError, "^no-kind$"):
            c.seq_decode(self.codec, bytes.fromhex("18ff"))

    def test_reserved_bits_between_match_values_must_be_ones(self):
        # PGN 65309 = 0x00ff1d; manufacturer 999 in 11 bits, reserved 0b11, industry 4:
        # 999 | 3 << 11 | 4 << 13 = 0x9be7, little-endian e7 9b; count 0
        kind, _ = c.seq_decode(self.codec, bytes.fromhex("1dff00e79b00"))
        self.assertEqual(kind.name, "pgn65309")
        with self.assertRaisesRegex(c.GenError, "^no-kind$"):
            c.seq_decode(self.codec, bytes.fromhex("1dff00e78300"))        # reserved bits 0b00

    def test_fixed_layout_message_is_no_kind(self):
        with self.assertRaisesRegex(c.GenError, "^no-kind$"):
            c.seq_decode(self.codec, c.FIXED_LAYOUT_MESSAGE)


class SeqOutputTest(Workdir):
    def test_database_without_a_counted_repeating_set_writes_no_sequential_pack(self):
        self.rewrite_database(lambda db: db.update(PGNs=[d for d in db["PGNs"] if d["Id"] not in
                                                         ("labLogEntries", "labCalibrationPairs", "gnssPositionData")]))
        status, stdout, stderr = self.run_gen()
        self.assertEqual((status, stderr), (0, ""))
        self.assertFalse(os.path.exists(self.path("packs/nmea2000-seq")))
        self.assertIn("nmea2000-seq kinds: 0", stdout)
        self.assertIn("These need the future groups addition.", self.read("packs/nmea2000/pack.md"))
        self.assertNotIn("\nlist ", self.read("model/n2k.def"))

    def test_check_reports_a_stale_vector_of_the_sequential_pack(self):
        self.assertEqual(self.run_gen()[0], 0)
        self.write("packs/nmea2000-seq/vectors/rt-pgn1.json", "{}\n")
        status, _, stderr = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("packs/nmea2000-seq/vectors/rt-pgn1.json is not written by the generator", stderr)

    def test_hand_written_position_vector_and_the_error_vectors(self):
        self.assertEqual(self.run_gen()[0], 0)
        v = json.loads(self.read("packs/nmea2000-seq/vectors/x01-pgn129029-to-geojson.json"))
        self.assertEqual(v["expect"], '{"type":"Feature","geometry":{"type":"Point","coordinates":[4.5,52.5]},"properties":{}}')
        e = json.loads(self.read("packs/nmea2000-seq/vectors/e01-pgn129029-count-beyond-the-input.json"))
        self.assertEqual(e["expect_error"], "malformed-wire")
        e = json.loads(self.read("packs/nmea2000-seq/vectors/e02-fixed-layout-pgn-is-no-kind.json"))
        self.assertEqual((e["input"], e["expect_error"]), (c.FIXED_LAYOUT_MESSAGE.hex(), "no-kind"))
