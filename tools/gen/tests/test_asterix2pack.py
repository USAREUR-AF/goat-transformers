"""Tests of tools/gen/asterix2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_asterix2pack*.py'

The fixture under fixtures/asterix2pack/ is a synthetic category 250 written for these tests in
the JSON form the generator reads; it describes no real system. `input/` is what the generator
reads, `expected/` the tree it must write.
"""
import support  # noqa: F401  (first: puts tools/gen on the path)

import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction

import gtcheck
import asterix2pack as a2p

FIXTURE = os.path.join(support.FIXTURES, "asterix2pack")
INPUT = os.path.join(FIXTURE, "input")
EXPECTED = os.path.join(FIXTURE, "expected")
DEFINITION = "sources/asterix-specs/cat250-1.10.json"
PACK = "packs/asterix-cat250/pack.def"
MODULE = "model/cat250.def"


# -- a definition in the JSON form of the source, built in a few words -------------------------

def tagged(tag, contents=None):
    return {"tag": tag, "contents": contents}


RAW = tagged("ContentRaw")


def element(bits, content=RAW):
    return tagged("Element", {"bitSize": bits, "rule": tagged("ContextFree", content)})


def quantity(signed, lsb, unit):
    return tagged("ContentQuantity", {"signedness": tagged("Signed" if signed else "Unsigned"),
                                      "lsb": lsb, "unit": unit})


def integer(signed):
    return tagged("ContentInteger", {"signedness": tagged("Signed" if signed else "Unsigned")})


def n_int(i):
    return tagged("NumInt", i)


def n_div(a, b):
    return tagged("NumDiv", {"numerator": a, "denominator": b})


def n_pow2(e):
    return tagged("NumPow", {"base": 2, "exponent": e})


def item(name, title, variation, definition="", remark=None):
    return {"name": name, "title": title, "rule": tagged("ContextFree", variation),
            "documentation": {"definition": definition, "description": None, "remark": remark}}


def member(name, title, variation):
    return tagged("Item", item(name, title, variation))


def spare(bits):
    return tagged("Spare", bits)


def group(*members):
    return tagged("Group", list(members))


def definition(items, number=250):
    return tagged("AsterixBasic", {
        "category": number, "edition": {"major": 1, "minor": 0}, "date": {"year": 2020, "month": 1, "day": 2},
        "title": "Test Category", "catalogue": items,
        "uap": tagged("Uap", [tagged("UapItem", it["name"]) for it in items])})


def plan_of(items, pinned=None):
    return a2p.plan_category(a2p.Cat(definition(items), "cat250-1.0.json", "specs/x.json"), pinned)


def pack_lines(plan):
    """The lines of the generated pack from `presence f fx` on, comments and indentation removed."""
    lines = [line.split("#")[0].strip() for line in a2p.emit_pack(plan, "0" * 40).split("\n")]
    lines = [" ".join(line.split()) for line in lines if line]
    return lines[lines.index("presence f fx") + 1:]


def fields_of(plan):
    return {n["ident"]: n for e in plan.mapped() for n, _ in a2p.walk_fields(e["nodes"])}


POSITION = ("Position in WGS-84 Co-ordinates", "Position of the target in WGS-84 co-ordinates.")
TIME_OF_DAY = ("Time of Day", "Absolute time stamping, as UTC time of day.")


def position(name, bits, exponent, remark=None):
    lsb = n_div(n_int(180), n_pow2(exponent))
    return item(name, POSITION[0], group(member("LAT", "Latitude", element(bits, quantity(True, lsb, "°"))),
                                         member("LON", "Longitude", element(bits, quantity(True, lsb, "°")))),
                POSITION[1], remark)


def time_of_day(name):
    return item(name, TIME_OF_DAY[0], element(24, quantity(False, n_div(n_int(1), n_pow2(7)), "s")), TIME_OF_DAY[1])


# -- running the generator ------------------------------------------------------------------------

class Workdir(unittest.TestCase):
    """A temporary output root that holds a copy of the fixture input."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asterix2pack-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out = support.copy_tree(INPUT, os.path.join(self.tmp, "out"))
        self.addCleanup(setattr, a2p, "curl", a2p.curl)
        a2p.curl = self.no_network

    def no_network(self, url, dest):
        self.fail("the generator tried to download %s" % url)

    def run_gen(self, *argv):
        return support.run_main(a2p.main, ["--out", self.out] + list(argv))

    def path(self, rel):
        return os.path.join(self.out, *rel.split("/"))

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8") as fh:
            return fh.read()

    def write(self, rel, text):
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        with open(self.path(rel), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    def edit_definition(self, change):
        d = json.loads(self.read(DEFINITION))
        change(d["contents"])
        self.write(DEFINITION, json.dumps(d))

    def catalogue_item(self, contents, name):
        return next(it for it in contents["catalogue"] if it["name"] == name)


class GoldenTree(Workdir):
    def test_fixture_input_gives_the_expected_tree(self):
        status, stdout, stderr = self.run_gen()
        self.assertEqual((status, stderr), (0, ""))
        self.assertIn("self-check: 9 vectors replayed, 1 packs", stdout)
        support.assert_same_tree(self, EXPECTED, self.out, ignore=("sources/",))

    def test_second_run_over_its_own_output_changes_nothing(self):
        self.run_gen()
        first = support.tree(self.out)
        self.assertEqual(self.run_gen()[0], 0)
        self.assertEqual(support.tree(self.out), first)

    def test_check_passes_on_fresh_output_and_writes_nothing(self):
        self.run_gen()
        before = support.tree(self.out)
        status, _, stderr = self.run_gen("--check")
        self.assertEqual(status, 0, stderr)
        self.assertIn("--check: ok, 14 file(s)", stderr)
        self.assertEqual(support.tree(self.out), before)

    def test_check_names_the_file_that_differs_and_leaves_the_tree_alone(self):
        self.run_gen()
        text = self.read(PACK)
        self.write(PACK, text.replace("uscale:1/128", "uscale:1/129"))
        self.write("packs/asterix-cat250/vectors/99-left-by-an-earlier-run.json", "{}\n")
        os.remove(self.path(MODULE))
        before = support.tree(self.out)
        status, _, stderr = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("--check: %s differs at line 36" % PACK, stderr)
        self.assertIn("--check: %s is missing" % MODULE, stderr)
        self.assertIn("99-left-by-an-earlier-run.json is not written by the generator and would be removed", stderr)
        self.assertEqual(support.tree(self.out), before)

    def test_check_on_an_empty_output_writes_nothing(self):
        status, _, stderr = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("%s is missing" % PACK, stderr)
        self.assertFalse(os.path.exists(self.path("packs")))

    def test_a_vector_of_an_earlier_run_is_removed(self):
        self.write("packs/asterix-cat250/vectors/99-left-by-an-earlier-run.json", "{}\n")
        self.write("packs/asterix-cat250/vectors/notes.txt", "kept: not a vector\n")
        self.run_gen()
        names = os.listdir(self.path("packs/asterix-cat250/vectors"))
        self.assertNotIn("99-left-by-an-earlier-run.json", names)
        self.assertIn("notes.txt", names)

    def test_generated_module_and_pack_load_in_gtcheck(self):
        self.run_gen()
        model = gtcheck.Model()
        for name in ("core", "track"):
            with open(os.path.join(support.REPO, "model", name + ".def"), encoding="utf-8") as fh:
                model.add(fh.read(), name)
        module = model.add(self.read(MODULE), MODULE)
        pack = gtcheck.load_pack(self.read(PACK), model, PACK)
        self.assertEqual((pack.wire, pack.layout, pack.bit_order), ("bits", "sequential", "msb"))
        self.assertEqual(pack.uses, ["core", "cat250"])
        self.assertEqual([k.name for k in pack.kinds], ["record"])
        when, length, presence = pack.kinds[0].lines[:3]
        self.assertEqual((when.d, when.bits, when.value), ("when", 8, "250"))
        self.assertEqual((length.d, length.bits, length.whole), ("length", 16, True))
        self.assertEqual((presence.name, presence.bits), ("f", "fx"))
        fields = {f.key: f for f in gtcheck.walk(pack.kinds[0].lines, "field")}
        self.assertEqual((fields["lat"].bits, fields["lat"].tr, fields["lat"].targs), (24, "sscale", ("45/2097152",)))
        self.assertEqual(fields["lat"].also, [("cat250.i020_lat", None)])
        self.assertEqual((fields["hae"].tr, fields["hae"].targs, fields["hae"].also), ("sscale", ("381/200",), []))
        self.assertEqual(fields["cat250.i110"].tr, "ascii")
        frns = [n.conds[0][2] for n in pack.kinds[0].lines if n.d == "if"]
        self.assertEqual(frns, [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 16, 17])    # 8 spare, 15 too wide, 18 RFS
        self.assertEqual(module.keys["i030"], "float")
        self.assertEqual(module.units["i040_roc"], "ft/min")
        self.assertEqual(list(module.lists), ["i070", "i080"])
        self.assertEqual([(d.target, d.function, d.arguments) for d in module.derives],
                         [("cat250.i030", "day_seconds", ["time_ms"])])

    def test_names_file_keeps_pinned_names_and_is_sorted(self):
        self.run_gen()
        names = json.loads(self.read("tools/gen/names/asterix-cat250.json"))
        self.assertEqual(names["130"], "report_class")                  # the pinned name, not i130
        self.assertIn("999/GONE", names)                                # an item no longer in the definition
        self.assertEqual(list(names), sorted(names))
        self.assertIn("key   report_class", self.read(MODULE))

    def test_output_does_not_depend_on_member_order_of_the_definition(self):
        self.run_gen()
        first = support.tree(self.out)

        def reverse(value):
            if isinstance(value, dict):
                return {k: reverse(value[k]) for k in reversed(list(value))}
            return [reverse(v) for v in value] if isinstance(value, list) else value

        def change(contents):
            contents["catalogue"].reverse()
        self.edit_definition(change)
        self.write(DEFINITION, json.dumps(reverse(json.loads(self.read(DEFINITION)))))
        self.assertEqual(self.run_gen()[0], 0)
        second = support.tree(self.out)
        stated = "packs/asterix-cat250/PROVENANCE.md"                   # states the SHA-256 of the definition
        self.assertEqual({k: v for k, v in first.items() if k not in (stated, DEFINITION)},
                         {k: v for k, v in second.items() if k not in (stated, DEFINITION)})

    def test_output_does_not_depend_on_the_hash_seed(self):
        for seed in ("1", "4242"):
            out = support.copy_tree(INPUT, os.path.join(self.tmp, "seed-" + seed))
            env = dict(os.environ, PYTHONHASHSEED=seed)
            done = subprocess.run([sys.executable, "-I", os.path.join(support.GEN, "asterix2pack.py"), "--out", out],
                                  env=env, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            support.assert_same_tree(self, EXPECTED, out, ignore=("sources/",))


class CommandLine(Workdir):
    def test_commit_records_every_source_file_without_downloading(self):
        os.remove(self.path("sources/PROVENANCE.md"))
        status, _, stderr = self.run_gen("--commit", "c" * 40)
        self.assertEqual(status, 0, stderr)
        text = self.read("sources/PROVENANCE.md")
        with open(self.path(DEFINITION), "rb") as fh:
            data = fh.read()
        self.assertIn("| `cat250-1.10.json` | `specs/cat250/cats/cat1.10/definition.json` | `cccccccccccc` | %d | `%s` |"
                      % (len(data), hashlib.sha256(data).hexdigest()), text)
        self.assertIn("| `LICENSE` | `LICENSE` | `bbbbbbbbbbbb` |", text)      # at the commit gitrev.txt states
        self.assertEqual(a2p.read_commits(text), ("c" * 40, "b" * 40))
        self.assertIn("commit " + "c" * 40, self.read(PACK))

    def test_commit_with_a_missing_source_file_is_refused_and_names_fetch(self):
        os.remove(self.path(DEFINITION))
        status, _, stderr = self.run_gen("--commit", "c" * 40)
        self.assertEqual(status, 1)
        self.assertIn("asterix2pack: %s: is missing; --commit with --fetch downloads the sources" % DEFINITION, stderr)

    def test_fetch_downloads_each_file_at_its_commit(self):
        calls = []
        a2p.curl = lambda url, dest: calls.append((url, os.path.relpath(dest, self.out).replace(os.sep, "/")))
        status, _, stderr = self.run_gen("--commit", "c" * 40, "--fetch")
        self.assertEqual(status, 0, stderr)
        base = "https://raw.githubusercontent.com/zoranbosnjak/asterix-specs/"
        self.assertEqual(calls, [
            (base + "c" * 40 + "/manifest.json", "sources/asterix-specs/manifest.json"),
            (base + "c" * 40 + "/gitrev.txt", "sources/asterix-specs/gitrev.txt"),
            (base + "b" * 40 + "/LICENSE", "sources/asterix-specs/LICENSE"),
            (base + "c" * 40 + "/specs/cat250/cats/cat1.10/definition.json", DEFINITION)])

    def test_fetch_is_refused_with_check_and_without_commit(self):
        for argv in (["--commit", "c" * 40, "--fetch", "--check"], ["--fetch"]):
            status, _, stderr = self.run_gen(*argv)
            self.assertEqual(status, 2, argv)
            self.assertIn("--fetch", stderr)

    def test_missing_out_is_a_usage_error(self):
        self.assertEqual(support.run_main(a2p.main, [])[0], 2)

    def test_help_states_inputs_outputs_and_exit_status(self):
        status, stdout, _ = support.run_main(a2p.main, ["--help"])
        self.assertEqual(status, 0)
        for text in ("sources/asterix-specs/manifest.json", "packs/asterix-cat<NNN>/pack.def", "Exit status", "--check"):
            self.assertIn(text, stdout)

    def test_a_category_the_manifest_does_not_hold_is_reported(self):
        status, stdout, stderr = self.run_gen("--cats", "250,251")
        self.assertEqual(status, 1)
        self.assertIn("asterix2pack: sources/asterix-specs/manifest.json: holds no category 251", stderr)
        self.assertTrue(os.path.exists(self.path(PACK)))                # category 250 is still written

    def test_built_in_tables_agree_with_the_repository(self):
        """`core`, `track`, `geojson` and `canonical-track-v2` as the generator holds them."""
        a2p.check_lib(support.REPO)
        status, _, stderr = self.run_gen("--lib", support.REPO)
        self.assertEqual(status, 0, stderr)

    def test_lib_that_differs_from_the_built_in_tables_is_refused(self):
        lib = os.path.join(self.tmp, "lib")
        for rel in ("model/core.def", "model/track.def", "packs/geojson/pack.def", "packs/canonical-track-v2/pack.def"):
            os.makedirs(os.path.dirname(os.path.join(lib, rel)), exist_ok=True)
            shutil.copy(os.path.join(support.REPO, rel), os.path.join(lib, rel))
        with open(os.path.join(lib, "model", "track.def"), "a", encoding="utf-8") as fh:
            fh.write("key  added_later  int  -  \"a key the generator does not know\"\n")
        status, _, stderr = self.run_gen("--lib", lib)
        self.assertEqual(status, 1)
        self.assertIn("asterix2pack: model/track.def: of --lib differs from the built-in table TRACK_KEYS", stderr)


class Refusals(Workdir):
    def assert_refused(self, *messages):
        status, stdout, stderr = self.run_gen()
        self.assertEqual(status, 1)
        for message in messages:
            self.assertIn(message, stderr)
        return stdout

    def test_definition_that_is_not_json_names_file_and_line(self):
        self.write(DEFINITION, '{"tag": "AsterixBasic",\n "contents": {\n  "category": 250,,\n}}\n')
        self.assert_refused("asterix2pack: %s:3: not JSON" % DEFINITION)

    def test_unknown_variation_names_file_and_item(self):
        def change(contents):
            self.catalogue_item(contents, "130")["rule"]["contents"] = tagged("Mystery")
        self.edit_definition(change)
        self.assert_refused("asterix2pack: %s: item 130: unknown variation tag Mystery" % DEFINITION)

    def test_item_that_is_not_a_whole_number_of_octets_names_file_and_item(self):
        def change(contents):
            members = self.catalogue_item(contents, "040")["rule"]["contents"]["contents"]
            members[1]["contents"] = 3                                  # the spare: 4 bits -> 3
        self.edit_definition(change)
        self.assert_refused("asterix2pack: %s: item 040: the item is 31 bits, not a whole number of octets" % DEFINITION)

    def test_extended_part_that_is_not_a_whole_octet_with_its_extension_bit(self):
        def change(contents):
            parts = self.catalogue_item(contents, "060")["rule"]["contents"]["contents"]
            parts[2]["contents"] = 5                                    # the spare of the first part
        self.edit_definition(change)
        self.assert_refused("item 060: part 1 of the extended item, with its extension bit, is 9 bits")

    def test_uap_item_missing_from_the_catalogue(self):
        def change(contents):
            contents["uap"]["contents"].append(tagged("UapItem", "777"))
        self.edit_definition(change)
        self.assert_refused("%s: the UAP names item 777, which the catalogue does not hold" % DEFINITION)

    def test_file_that_is_not_a_category_definition(self):
        self.write(DEFINITION, '{"tag": "Something", "contents": {}}\n')
        self.assert_refused("%s: not a category definition (the tag is Something)" % DEFINITION)

    def test_missing_provenance_without_commit(self):
        os.remove(self.path("sources/PROVENANCE.md"))
        self.assert_refused("asterix2pack: sources/PROVENANCE.md: cannot be read")

    def test_refused_category_leaves_no_files_and_keeps_its_names_file(self):
        self.run_gen()
        self.assertTrue(os.path.exists(self.path(PACK)))

        def change(contents):
            self.catalogue_item(contents, "130")["rule"]["contents"] = tagged("Mystery")
        self.edit_definition(change)
        stdout = self.assert_refused("unknown variation tag")
        self.assertIn("cat250  NOT GENERATED", stdout)
        left = [rel for rel in support.tree(self.out) if not rel.startswith("sources/")]
        self.assertEqual(left, ["tools/gen/names/asterix-cat250.json"])


# -- pure functions --------------------------------------------------------------------------------

class Helpers(unittest.TestCase):
    def test_plain_writes_no_exponent_and_no_trailing_zero(self):
        self.assertEqual(a2p.plain(1524.0), "1524")
        self.assertEqual(a2p.plain(0.0), "0")
        self.assertEqual(a2p.plain(-0.65625), "-0.65625")
        self.assertEqual(a2p.plain(1e-7), "0.0000001")
        self.assertEqual(a2p.plain(1e22), "10000000000000000000000")
        self.assertEqual(a2p.plain(47.499990463256836), "47.499990463256836")
        self.assertEqual(a2p.plain(7), "7")

    def test_round_half_away_from_zero(self):
        self.assertEqual([a2p.round_half_away(x) for x in (0.5, -0.5, 2.5, -2.5, 2.4, -2.4, 0.0)],
                         [1, -1, 3, -3, 2, -2, 0])

    def test_frac_text_is_an_integer_or_a_fraction(self):
        self.assertEqual(a2p.frac_text(Fraction(180, 1 << 23)), "45/2097152")
        self.assertEqual(a2p.frac_text(Fraction(25)), "25")

    def test_fold_gives_one_line_of_ascii(self):
        self.assertEqual(a2p.fold('café °  x\n"q" :math:`x^2` ☃'), "cafe  deg x 'q' x^2 ?")
        self.assertEqual(a2p.fold(None), "")

    def test_edition_1_10_is_newer_than_1_9(self):
        self.assertEqual(max(["1.9", "1.10", "1.2"], key=a2p.edition_key), "1.10")
        self.assertEqual(a2p.definition_files([{"category": "007", "cats": ["1.9", "1.10"]}]),
                         [(7, "cat007-1.10.json", "specs/cat007/cats/cat1.10/definition.json")])

    def test_manifest_of_another_shape_is_refused_naming_the_file(self):
        with self.assertRaises(a2p.GenError) as c:
            a2p.definition_files([{"category": "007"}])
        self.assertEqual(c.exception.file, "sources/asterix-specs/manifest.json")

    def test_gen_error_text_is_file_line_message(self):
        self.assertEqual(str(a2p.GenError("what", file="a/b.json", line=3)), "a/b.json:3: what")
        self.assertEqual(str(a2p.GenError("what", file="a/b.json")), "a/b.json: what")
        self.assertEqual(str(a2p.GenError("what")), "what")

    def test_numbers_of_the_definition_are_exact(self):
        self.assertEqual(a2p.num(n_div(n_int(180), n_pow2(23))), Fraction(45, 2097152))
        self.assertEqual(a2p.num(n_pow2(-14)), Fraction(1, 16384))
        self.assertEqual(a2p.num(n_div(n_div(n_int(1), n_int(4)), n_pow2(3))), Fraction(1, 32))
        with self.assertRaises(a2p.GenError):
            a2p.num(tagged("NumReal", 0.5))

    def test_fixed_bits_counts_members_and_spares(self):
        g = group(member("A", "", element(16)), spare(4), member("B", "", group(member("C", "", element(12)))))
        self.assertEqual(a2p.fixed_bits(g), 32)
        self.assertEqual(a2p.fixed_bits(element(7)), 7)
        self.assertIsNone(a2p.fixed_bits(tagged("Extended", [member("A", "", element(7)), None])))
        self.assertIsNone(a2p.fixed_bits(group(member("A", "", tagged("Explicit")))))

    def test_rule_bits_of_a_dependent_rule_needs_one_size(self):
        def dependent(default, case):
            return tagged("Dependent", {"path": [["000"]], "default": default, "cases": [[[1], case]]})
        self.assertEqual(a2p.rule_bits(dependent(element(16), group(member("A", "", element(8)), spare(8)))), 16)
        self.assertIsNone(a2p.rule_bits(dependent(element(16), element(24))))

    def test_to_bits_is_msb_first_and_twos_complement(self):
        self.assertEqual(a2p.to_bits(5, 3), "101")
        self.assertEqual(a2p.to_bits(-3, 12), "111111111101")
        self.assertEqual(a2p.to_bits(0x1FF, 8), "11111111")
        self.assertEqual(a2p.to_bits(9, 0), "")

    def test_fx_octets_number_bits_from_one_seven_per_octet(self):
        self.assertEqual(a2p.fx_octets(set()), "00000000")              # one octet at least
        self.assertEqual(a2p.fx_octets({1}), "10000000")
        self.assertEqual(a2p.fx_octets({7}), "00000010")
        self.assertEqual(a2p.fx_octets({8}), "00000001" "10000000")      # bit 8 is the first of octet 2
        self.assertEqual(a2p.fx_octets({1, 15}), "10000001" "00000001" "10000000")
        self.assertEqual(a2p.fx_octets({14}), "00000001" "00000010")     # no all-zero octet after the second


class PlanOfADefinition(unittest.TestCase):
    def test_quantity_is_a_scale_with_an_exact_fraction_and_integer_is_uint_or_twos(self):
        plan = plan_of([item("010", "Values", group(
            member("U", "", element(8, quantity(False, n_div(n_int(360), n_pow2(8)), "°"))),
            member("S", "", element(8, quantity(True, n_pow2(-7), "NM"))),
            member("IU", "", element(8, integer(False))),
            member("IS", "", element(8, integer(True)))))])
        f = fields_of(plan)
        self.assertEqual([f["010/" + k]["tr"] for k in ("U", "S", "IU", "IS")],
                         ["uscale:45/32", "sscale:1/128", "uint", "twos"])
        self.assertEqual(plan.keys["i010_u"], ("float", "deg", "I250/010/U (Values). LSB 45/32 deg"))
        self.assertEqual(plan.keys["i010_is"][:2], ("int", "-"))

    def test_height_in_feet_is_bound_to_hae_with_the_foot_folded_into_the_scale(self):
        plan = plan_of([item("050", "Geometric Height", element(16, quantity(True, n_div(n_int(25), n_int(4)), "ft")),
                             "Height above the WGS-84 ellipsoid.")])
        self.assertEqual(a2p.FT, Fraction(381, 1250))
        self.assertEqual(pack_lines(plan), ["if f.1", "field hae 16 sscale:381/200", "end"])   # 25/4 * 381/1250
        self.assertEqual(dict(plan.keys), {})                           # no raw key: one field cannot hold feet and metres
        self.assertEqual(plan.bindings[0]["how"], "factor 381/1250 folded into the scale")

    def test_ground_speed_units_are_converted_to_metres_per_second(self):
        def speed(lsb, unit):
            plan = plan_of([item("040", "Movement", group(member("GS", "Ground Speed", element(16, quantity(False, lsb, unit)))))])
            return pack_lines(plan)[1:-1]
        self.assertEqual(speed(n_int(1), "kt"), ["field speed_ms 16 uscale:463/900"])          # 1852/3600
        self.assertEqual(speed(n_pow2(-14), "NM/s"), ["field speed_ms 16 uscale:463/4096"])     # 1852/16384
        self.assertEqual(speed(n_div(n_int(1), n_int(4)), "m/s"),
                         ["field speed_ms 16 uscale:1/4", "also cat250.i040_gs"])              # same unit: both keys

    def test_signed_speed_and_speed_inside_a_compound_item_are_not_bound(self):
        signed = plan_of([item("040", "Movement", group(member("GS", "Ground Speed", element(16, quantity(True, n_int(1), "kt")))))])
        self.assertEqual(signed.bindings, [])
        nested = plan_of([item("040", "Movement", tagged("Compound", [
            item("GS", "Ground Speed", element(16, quantity(False, n_int(1), "kt")))]))])
        self.assertEqual(nested.bindings, [])
        self.assertIn("field cat250.i040_gs 16 uscale:1", pack_lines(nested))

    def test_finest_position_is_bound_and_the_other_feeds_lat_lon_through_derive(self):
        plan = plan_of([position("020", 24, 23), position("025", 32, 30)])
        f = fields_of(plan)
        self.assertEqual((f["025/LAT"]["key"], f["025/LAT"]["also"]), ("lat", ["cat250.i025_lat"]))
        self.assertEqual(f["020/LAT"]["key"], "cat250.i020_lat")
        self.assertEqual(plan.derives, [("lat", "copy", ["cat250.i020_lat"]), ("lon", "copy", ["cat250.i020_lon"])])

    def test_position_whose_content_depends_on_the_message_type_is_not_bound(self):
        plan = plan_of([position("020", 24, 23, remark="The content depends on the message type.")])
        self.assertEqual(plan.bindings, [])

    def test_time_of_day_is_derived_only_when_the_category_has_one(self):
        self.assertEqual(plan_of([time_of_day("030")]).derives, [("cat250.i030", "day_seconds", ["time_ms"])])
        self.assertEqual(plan_of([time_of_day("030"), time_of_day("035")]).derives, [])

    def test_cartesian_velocity_with_stated_axes_uses_the_track_module(self):
        lsb = n_pow2(-2)
        plan = plan_of([item("185", "Calculated Track Velocity (Cartesian)", group(
            member("VX", "", element(16, quantity(True, lsb, "m/s"))), member("VY", "", element(16, quantity(True, lsb, "m/s")))),
            "Velocity.", "The y-axis points to the Geographical North at the location of the target.")])
        self.assertEqual(plan.uses, ["track"])
        self.assertEqual(pack_lines(plan)[1:-1], ["field track.vel_east_ms 16 sscale:1/4", "also cat250.i185_vx",
                                                  "field track.vel_north_ms 16 sscale:1/4", "also cat250.i185_vy"])
        self.assertIn("uses       track\nuses       cat250\n", a2p.emit_pack(plan, "0" * 40))

    def test_spare_bits_are_pad_and_never_a_key(self):
        plan = plan_of([item("040", "Two", group(member("A", "", element(3)), spare(5), member("B", "", element(8))))])
        self.assertEqual(pack_lines(plan), ["if f.1", "field cat250.i040_a 3 uint", "pad 5", "field cat250.i040_b 8 uint", "end"])
        self.assertEqual(list(plan.keys), ["i040_a", "i040_b"])

    def test_extended_item_is_a_chain_with_fx_after_each_part(self):
        ext = tagged("Extended", [member("A", "", element(7)), None, spare(3), member("B", "", element(4)), None])
        self.assertEqual(pack_lines(plan_of([item("060", "Status", ext)])),
                         ["if f.1", "chain", "field cat250.i060_a 7 uint", "fx", "pad 3", "field cat250.i060_b 4 uint", "fx", "end", "end"])
        last_part_has_no_extension = tagged("Extended", [member("A", "", element(7)), None, member("B", "", element(8))])
        self.assertEqual(pack_lines(plan_of([item("060", "Status", last_part_has_no_extension)]))[1:-1],
                         ["chain", "field cat250.i060_a 7 uint", "fx", "field cat250.i060_b 8 uint", "end"])

    def test_repetitive_items_are_groups_with_the_count_width_of_the_definition(self):
        def rep(kind, variation):
            return tagged("Repetitive", {"type": kind, "variation": variation})
        one = plan_of([item("070", "Offsets", rep(tagged("RepetitiveRegular", {"byteSize": 1}), group(member("DX", "", element(8)))))])
        self.assertEqual(pack_lines(one)[1:-1], ["group cat250.i070 count 8", "field cat250.i070_dx 8 uint", "end"])
        two = plan_of([item("070", "Offsets", rep(tagged("RepetitiveRegular", {"byteSize": 2}), element(16)))])
        self.assertEqual(pack_lines(two)[1:-1], ["group cat250.i070 count 16", "field cat250.i070_val 16 uint", "end"])
        fx = plan_of([item("080", "Codes", rep(tagged("RepetitiveFx"), element(7)))])
        self.assertEqual(pack_lines(fx)[1:-1], ["group cat250.i080 fx", "field cat250.i080_val 7 uint", "end"])
        self.assertEqual(dict(fx.lists), {"i080": "I250/080: Codes, one item per repetition"})
        self.assertEqual(a2p.order_of_names(fx), ["i080", "i080_val"])  # the list before the key of its items

    def test_compound_item_is_a_nested_presence_and_skips_unused_slots(self):
        comp = tagged("Compound", [item("A", "First", element(8)), None, item("C", "Third", group(spare(4), member("N", "", element(4))))])
        self.assertEqual(pack_lines(plan_of([item("090", "Data", comp)])),
                         ["if f.1", "presence p090 fx", "if p090.1", "field cat250.i090_a 8 uint", "end",
                          "if p090.3", "pad 4", "field cat250.i090_c_n 4 uint", "end", "end"])

    def test_table_content_is_the_raw_value_with_the_table_in_the_meaning(self):
        plan = plan_of([item("130", "Class", element(8, tagged("ContentTable", [[0, "Unknown"], [1, "Aircraft"]])))])
        self.assertEqual(pack_lines(plan)[1], "field cat250.i130 8 uint")
        self.assertEqual(plan.keys["i130"], ("int", "-", "I250/130: Class. 0 = Unknown, 1 = Aircraft"))

    def test_strings_ascii_is_a_string_key_and_other_alphabets_are_raw(self):
        def string(kind):
            return tagged("ContentString", tagged(kind))
        plan = plan_of([item("110", "Names", group(member("A", "", element(48, string("StringAscii"))),
                                                   member("I", "", element(48, string("StringICAO"))),
                                                   member("O", "", element(12, string("StringOctal"))), spare(4)))])
        self.assertEqual(pack_lines(plan)[1:4], ["field cat250.i110_a 48 ascii", "field cat250.i110_i 48 uint", "field cat250.i110_o 12 uint"])
        self.assertEqual(plan.keys["i110_a"][0], "string")
        odd = plan_of([item("010", "Ok", element(8)), item("110", "Name", element(12, string("StringAscii")))])
        self.assertEqual(odd.entries[1]["reason"], "an ASCII string of 12 bits")

    def test_item_that_cannot_be_described_is_left_out_and_releases_its_names(self):
        plan = plan_of([item("010", "Ok", element(8)),
                        item("150", "Wide", group(member("A", "", element(8)), member("W", "", element(72))))])
        self.assertEqual(plan.entries[1]["nodes"], None)
        self.assertEqual(plan.entries[1]["reason"], "an element of 72 bits (a field holds at most 64)")
        self.assertEqual(plan.names, {"010": "i010"})
        self.assertEqual(pack_lines(plan), ["if f.1", "field cat250.i010 8 uint", "end"])

    def test_dependent_structure_of_one_size_is_written_as_its_default(self):
        rule = tagged("Dependent", {"path": [["000"]], "default": element(16), "cases": [[[1], group(member("A", "", element(16)))]]})
        it = dict(item("140", "Detail", None), rule=rule)
        plan = plan_of([it])
        self.assertEqual(pack_lines(plan)[1], "field cat250.i140 16 uint")
        self.assertTrue(plan.keys["i140"][2].endswith("Raw value: the structure depends on the value of 000"))
        rule["contents"]["cases"][0][1] = element(24)
        self.assertIn("cases of different sizes", plan_of([item("010", "Ok", element(8)), it]).entries[1]["reason"])

    def test_pinned_name_wins_over_the_derived_name(self):
        plan = plan_of([item("010", "Source", group(member("SAC", "", element(8)), member("SIC", "", element(8))))],
                       pinned={"010/SAC": "area_code", "900": "of_an_earlier_edition"})
        self.assertEqual(pack_lines(plan)[1:3], ["field cat250.area_code 8 uint", "field cat250.i010_sic 8 uint"])
        self.assertEqual(plan.names_file(), {"010/SAC": "area_code", "010/SIC": "i010_sic", "900": "of_an_earlier_edition"})
        self.assertEqual(a2p.emit_names({"b": "y", "a": "x"}), '{\n "a": "x",\n "b": "y"\n}')

    def test_two_item_paths_that_fold_to_one_key_are_refused_until_one_is_pinned(self):
        items = [item("010", "Collide", group(member("A_B", "", element(8)), member("A", "", group(member("B", "", element(8))))))]
        with self.assertRaises(a2p.GenError) as c:
            plan_of(items)
        self.assertIn("item 010: key name i010_a_b for both 010/A_B and 010/A/B", str(c.exception))
        self.assertEqual(c.exception.file, "sources/asterix-specs/cat250-1.0.json")
        plan = plan_of(items, pinned={"010/A/B": "i010_a_sub_b"})
        self.assertEqual(sorted(plan.keys), ["i010_a_b", "i010_a_sub_b"])

    def test_pinned_name_that_is_not_a_key_name_is_refused(self):
        with self.assertRaises(a2p.GenError) as c:
            plan_of([item("010", "Source", element(8))], pinned={"010": "Not-A-Key"})
        self.assertIn("gives the key name 'Not-A-Key'", str(c.exception))

    def test_category_with_nothing_to_map_is_refused(self):
        with self.assertRaises(a2p.GenError) as c:
            plan_of([item("150", "Wide", element(72)), item("SP", "Special", tagged("Explicit"))])
        self.assertIn("no item of the UAP can be mapped", str(c.exception))

    def test_first_uap_is_taken_and_the_others_are_named(self):
        d = definition([item("010", "Source", element(8)), item("020", "Other", element(8))])
        d["contents"]["uap"] = tagged("Uaps", {"cases": [["plot", [tagged("UapItem", "010")]], ["track", [tagged("UapItem", "020")]]],
                                              "selector": {"item": ["000"]}})
        cat = a2p.Cat(d, "cat250-1.0.json", "specs/x.json")
        self.assertEqual(cat.uap, [tagged("UapItem", "010")])
        self.assertIn("2 UAPs (`plot`, `track`), selected by the value of item 000. The pack holds the first, `plot`", cat.uap_note)

    def test_category_62_takes_the_names_that_leave_the_hand_written_pack_alone(self):
        cat = a2p.Cat(definition([item("010", "Source", element(8))], number=62), "cat062-1.0.json", "specs/x.json")
        self.assertEqual((cat.format, cat.module), ("asterix-cat062-full", "cat062full"))

    def test_stray_bits_names_the_part_that_is_not_whole_octets(self):
        field = dict(t="field", bits=7)
        self.assertIsNone(a2p.stray_bits([dict(t="group", mode="fx", body=[field])]))
        self.assertEqual(a2p.stray_bits([dict(t="group", mode="count", body=[field])]), (7, "one repetition"))
        self.assertEqual(a2p.stray_bits([dict(t="compound", subs=[(1, "A", "", [dict(t="pad", bits=3)])])]),
                         (3, "subfield A: the item"))


class RawRecords(unittest.TestCase):
    """The writer of vector inputs: bytes from the plan, without the pack."""

    def setUp(self):
        self.plan = a2p.plan_category(a2p.load_category(INPUT, "cat250-1.10.json", "specs/x.json"), {})
        self.fields = fields_of(self.plan)

    def test_field_that_crosses_a_byte_boundary_after_a_spare(self):
        nodes = self.plan.entries[3]["nodes"]                           # I250/040: GS 16, spare 4, ROC 12
        bits = a2p.raw_enc(nodes, {"speed_ms": 0x0200, "cat250.i040_roc": -3})
        self.assertEqual("%08x" % int(bits, 2), "02000ffd")

    def test_block_has_category_length_fspec_and_items_in_frn_order(self):
        rec = {"cat250.i010_sac": 1, "cat250.i010_sic": 2, "cat250.i080": [{"cat250.i080_val": 3}, {"cat250.i080_val": 100}]}
        # CAT 250; LEN 9; FSPEC: FRN 1 and an extension bit, then FRN 9 = bit 2 of octet 2; 0102; 3+FX, 100
        self.assertEqual(a2p.raw_block(self.plan, rec), "fa0009" "8140" "0102" "07c8")

    def test_extended_item_stops_at_its_last_part_with_a_value(self):
        nodes = self.plan.entries[5]["nodes"]                           # I250/060
        self.assertEqual(a2p.raw_enc(nodes, {"cat250.i060_typ": 1, "cat250.i060_src": 2}), "11000000")
        self.assertEqual(a2p.raw_enc(nodes, {"cat250.i060_cnf": 5}), "00000001" "10100000")

    def test_compound_item_sets_only_the_subfields_with_a_value(self):
        nodes = self.plan.entries[9]["nodes"]                           # I250/090: AMP is bit 1, WIN bit 3
        self.assertEqual(a2p.raw_enc(nodes, {"cat250.i090_win_num": 7}), "00100000" "00000111")

    def test_nice_value_survives_the_scale_round_trip(self):
        lat = self.fields["020/LAT"]
        raw = a2p.nice(47.5)(lat)
        self.assertEqual(raw, 2213660)                                  # round(47.5 * 2097152 / 45)
        self.assertEqual(a2p.plain(a2p.raw_value(lat, raw)), "47.499990463256836")
        self.assertEqual(a2p.model_to_raw(lat, a2p.raw_value(lat, raw)), raw)

    def test_nice_value_is_halved_until_it_fits_a_narrow_field(self):
        narrow = dict(self.fields["020/LAT"], bits=16)
        self.assertEqual(a2p.nice(47.5)(narrow), 17294)                 # 47.5 / 128, the first half that fits
        with self.assertRaises(a2p.GenError):
            a2p.model_to_raw(narrow, 47.5)

    def test_picked_values_fit_their_fields_and_survive_the_round_trip(self):
        rec = {}
        a2p.Picker().fill([n for e in self.plan.mapped() for n in e["nodes"]], rec)
        seen_negative = False
        for n in self.fields.values():
            holder = rec if n["key"] in rec else rec[next(k for k in rec if isinstance(rec[k], list))][0]
            v = holder.get(n["key"])
            if v is None or n["kind"] == "ascii":
                continue
            low, high = (-(1 << (n["bits"] - 1)), (1 << (n["bits"] - 1)) - 1) if n["signed"] else (0, (1 << n["bits"]) - 1)
            self.assertTrue(low <= v <= high and v != 0, (n["ident"], v))
            seen_negative = seen_negative or v < 0
            if n["frac"] is not None:
                self.assertEqual(a2p.model_to_raw(n, a2p.raw_value(n, v)), v, n["ident"])
        self.assertTrue(seen_negative)

    def test_picker_gives_minus_one_for_a_signed_field_of_one_bit(self):
        pk = a2p.Picker()
        self.assertEqual([pk.value(dict(bits=1, signed=True, kind="twos")) for _ in range(4)], [-1, -1, -1, -1])


# -- the codec, on the pack the fixture expects -----------------------------------------------------

def load_expected_pack():
    model = a2p.shared_model()
    with open(os.path.join(EXPECTED, *MODULE.split("/")), encoding="utf-8") as fh:
        module = a2p.load_module(model, fh.read(), MODULE)
    with open(os.path.join(EXPECTED, *PACK.split("/")), encoding="utf-8") as fh:
        return model, module, a2p.load_pack(model, fh.read(), PACK), None


class Codec(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.module, cls.pack, _ = load_expected_pack()

    # A record worked by hand from the fixture definition:
    #   fa          CAT 250
    #   0015        LEN 21
    #   97 60       FSPEC: FRN 1, 4, 6, 7 and FX; then FRN 9, 10 (bits 2 and 3 of octet 2)
    #   01 02       I250/010  SAC 1, SIC 2
    #   0200 0 ffd  I250/040  GS 512 * 463/4096 m/s = 57.875; spare 4; ROC -3 * 25/4 = -18.75
    #   c1 b2       I250/060  TYP 1, SRC 2, spare, FX 1; CNF 5, AGE 9, FX 0
    #   01 ff 02    I250/070  one repetition: DX -1, DY 2
    #   07 c8       I250/080  3 with FX 1, 100 with FX 0
    #   a0 fe 07    I250/090  subfields 1 and 3: AMP -2; spare 4, NUM 7
    RECORD = "fa0015" "9760" "0102" "02000ffd" "c1b2" "01ff02" "07c8" "a0fe07"
    KEYS = {"cat250.i010_sac": 1, "cat250.i010_sic": 2, "speed_ms": 57.875, "cat250.i040_roc": -18.75,
            "cat250.i060_typ": 1, "cat250.i060_src": 2, "cat250.i060_cnf": 5, "cat250.i060_age": 9,
            "cat250.i090_amp": -2.0, "cat250.i090_win_num": 7}
    LISTS = {"cat250.i070": [({"cat250.i070_dx": -1, "cat250.i070_dy": 2}, {})],
             "cat250.i080": [({"cat250.i080_val": 3}, {}), ({"cat250.i080_val": 100}, {})]}

    def decode(self, hx):
        return a2p.seq_decode(self.pack, hx)

    def assert_wire_error(self, kind, hx):
        with self.assertRaises(a2p.WireError) as c:
            self.decode(hx)
        self.assertEqual(c.exception.kind, kind)

    def test_hand_built_record_decodes_to_the_stated_values(self):
        self.assertEqual(self.decode(self.RECORD), (self.KEYS, self.LISTS))

    def test_hand_built_values_encode_to_the_same_bytes(self):
        self.assertEqual(a2p.seq_encode(self.pack, dict(self.KEYS), self.LISTS), self.RECORD)

    def test_raw_writer_and_codec_agree_on_the_hand_built_record(self):
        plan = a2p.plan_category(a2p.load_category(INPUT, "cat250-1.10.json", "specs/x.json"), {"130": "report_class"})
        rec = {"cat250.i010_sac": 1, "cat250.i010_sic": 2, "speed_ms": 512, "cat250.i040_roc": -3,
               "cat250.i060_typ": 1, "cat250.i060_src": 2, "cat250.i060_cnf": 5, "cat250.i060_age": 9,
               "cat250.i070": [{"cat250.i070_dx": -1, "cat250.i070_dy": 2}],
               "cat250.i080": [{"cat250.i080_val": 3}, {"cat250.i080_val": 100}],
               "cat250.i090_amp": -2, "cat250.i090_win_num": 7}
        self.assertEqual(a2p.raw_block(plan, rec), self.RECORD)

    def test_fspec_bit_that_no_if_names_is_malformed_wire(self):
        self.assert_wire_error("malformed-wire", "fa0006" "0180" "00")          # FRN 8, the spare FRN

    def test_compound_presence_bit_of_an_unused_slot_is_malformed_wire(self):
        self.assert_wire_error("malformed-wire", "fa0006" "0120" "40")          # FRN 10, subfield 2

    def test_another_category_is_no_kind(self):
        self.assert_wire_error("no-kind", "fb0006" "80" "0102")

    def test_input_shorter_than_len_is_malformed_wire_and_longer_is_ignored(self):
        self.assert_wire_error("malformed-wire", "fa0006" "80" "01")
        ent, lists = self.decode("fa0006" "80" "0102" "ffff")                  # a second record is not read
        self.assertEqual(ent, {"cat250.i010_sac": 1, "cat250.i010_sic": 2})
        self.assertEqual(a2p.seq_encode(self.pack, ent, lists), "fa0006" "80" "0102")

    def test_extended_item_with_extension_bit_zero_leaves_later_keys_absent(self):
        ent, lists = self.decode("fa0005" "04" "c0")
        self.assertEqual(ent, {"cat250.i060_typ": 1, "cat250.i060_src": 2})
        self.assertEqual(a2p.seq_encode(self.pack, ent, lists), "fa0005" "04" "c0")

    def test_extension_bit_set_on_the_last_part_is_malformed_wire(self):
        self.assert_wire_error("malformed-wire", "fa0006" "04" "c1b3")

    def test_shared_key_on_the_field_line_wins_over_the_raw_key_on_encode(self):
        ent = {"lat": 45.0, "cat250.i020_lat": 0.0, "lon": 0.0}
        hx = a2p.seq_encode(self.pack, ent, {})
        self.assertEqual(hx, "fa000a" "40" "200000" "000000")                   # 45 degrees = 2^21 * 45/2097152
        self.assertEqual(self.decode(hx)[0], {"lat": 45.0, "cat250.i020_lat": 45.0, "lon": 0.0, "cat250.i020_lon": 0.0})

    def test_uint_of_64_bits_with_the_top_bit_set_is_the_negative_integer(self):
        hx = "fa000e" "010140" "ffffffffffffffff"                               # FRN 16
        self.assertEqual(self.decode(hx), ({"cat250.i160": -1}, {}))
        self.assertEqual(a2p.seq_encode(self.pack, {"cat250.i160": -1}, {}), hx)

    def test_ascii_drops_trailing_nul_and_refuses_control_bytes(self):
        self.assertEqual(self.decode("fa000b" "0110" "414200000000")[0], {"cat250.i110": "AB"})    # FRN 11
        self.assert_wire_error("transform-decode", "fa000b" "0110" "411f00000000")
        with self.assertRaises(a2p.WireError) as c:
            a2p.seq_encode(self.pack, {"cat250.i110": "SEVENCH"}, {})
        self.assertEqual(c.exception.kind, "transform-encode")

    def test_value_that_does_not_fit_its_field_is_transform_encode(self):
        for ent in ({"cat250.i010_sac": 256}, {"cat250.i040_roc": 2048 * 6.25}, {"speed_ms": -1.0}):
            with self.assertRaises(a2p.WireError) as c:
                a2p.seq_encode(self.pack, ent, {})
            self.assertEqual(c.exception.kind, "transform-encode", ent)

    def test_explicit_item_is_read_over_and_not_written(self):
        ent, lists = self.decode("fa000b" "810120" "0102" "03aabb")             # FRN 1 and FRN 17: length 3, two octets
        self.assertEqual(ent, {"cat250.i010_sac": 1, "cat250.i010_sic": 2})
        self.assertEqual(a2p.seq_encode(self.pack, ent, lists), "fa0006" "80" "0102")

    def test_count_larger_than_the_bits_left_is_malformed_wire(self):
        self.assert_wire_error("malformed-wire", "fa0005" "02" "ff")            # FRN 7: 255 repetitions, no octet left

    def test_derives_fill_absent_targets_only(self):
        derives = a2p.all_derives(self.model)
        ent = a2p.apply_derives({"time_ms": 86400000 + 43200125, "track.vel_east_ms": 3.0, "track.vel_north_ms": 4.0,
                                 "speed_ms": 9.0}, derives)
        self.assertEqual(ent["cat250.i030"], 43200.125)
        self.assertEqual(ent["speed_ms"], 9.0)                                  # present: not replaced by hypot
        self.assertAlmostEqual(ent["course"], 36.86989764584402)

    def test_track_time_is_read_as_epoch_milliseconds(self):
        self.assertEqual(a2p.iso8601_ms("1970-01-02T00:00:00.5Z"), 86400500)
        self.assertEqual(a2p.iso8601_ms("2025-10-29T12:00:00.125Z"), 1761739200125)


class Icao6(unittest.TestCase):
    """`chars:icao6` (engine-spec 0.15) in the generator's own codec, for the callsign binding."""

    class Field:
        tr, bits = "chars", 48

    def test_characters_decode_and_trailing_spaces_go(self):
        # K L M 1 0 2 3 space: 11 12 13 49 48 50 51 32
        v = 0
        for c in (11, 12, 13, 49, 48, 50, 51, 32):
            v = (v << 6) | c
        self.assertEqual(a2p.t_decode(self.Field, v), "KLM1023")
        self.assertEqual(a2p.t_encode(self.Field, "KLM1023"), v)

    def test_a_code_outside_the_set_is_transform_decode(self):
        with self.assertRaises(a2p.WireError) as c:
            a2p.t_decode(self.Field, 27 << 42)
        self.assertEqual(c.exception.kind, "transform-decode")

    def test_text_the_set_cannot_hold_is_transform_encode(self):
        for text in ("klm", "ABCDEFGHI", "A#"):
            with self.assertRaises(a2p.WireError) as c:
                a2p.t_encode(self.Field, text)
            self.assertEqual(c.exception.kind, "transform-encode")


class ShapeCheck(unittest.TestCase):
    """The output invariants that are narrower than the load rules of the specification."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(EXPECTED, *MODULE.split("/")), encoding="utf-8") as fh:
            cls.module_text = fh.read()
        with open(os.path.join(EXPECTED, *PACK.split("/")), encoding="utf-8") as fh:
            cls.pack_text = fh.read()

    def refusal(self, old, new, module_extra=""):
        self.assertIn(old, self.pack_text)
        model = a2p.shared_model()
        module = a2p.load_module(model, self.module_text + module_extra, MODULE)
        pack = a2p.load_pack(model, self.pack_text.replace(old, new, 1), PACK)   # gtcheck accepts it
        with self.assertRaises(a2p.GenError) as c:
            a2p.check_shape(pack, module)
        return c.exception

    def test_expected_pack_passes(self):
        model, module, pack, _ = load_expected_pack()
        a2p.check_shape(pack, module)

    def test_field_option_is_refused_with_file_and_line(self):
        e = self.refusal("field  cat250.i010_sac  8  uint", "field  cat250.i010_sac  8  uint  swap")
        self.assertEqual((e.file, e.line), (PACK, 26))
        self.assertIn("a field with an option", e.message)

    def test_scale_with_an_offset_is_refused(self):
        self.assertIn("the scale `1/128:5`", self.refusal("uscale:1/128", "uscale:1/128:5").message)

    def test_presence_of_a_fixed_number_of_bits_is_refused(self):
        self.assertIn("presence", self.refusal("presence f fx", "presence f 21").message)

    def test_transform_the_codec_does_not_implement_is_refused(self):
        self.assertIn("the transform `linscale`",
                      self.refusal("field  cat250.i030  24  uscale:1/128", "field  cat250.i030  24  linscale:10:20").message)

    def test_second_kind_is_refused(self):
        self.assertIn("2 kinds", self.refusal("if f.13 ", "kind other\nwhen 8 7\npresence f fx\nif f.13 ").message)

    def test_lsb_bit_order_is_refused(self):
        self.assertIn("bit_order lsb", self.refusal("bit_order  msb", "bit_order  lsb").message)

    def test_derive_function_the_codec_does_not_apply_is_refused(self):
        e = self.refusal("presence f fx", "presence f fx", module_extra="derive  cat250.i030  neg  cat250.i040_roc\n")
        self.assertEqual(e.file, MODULE)
        self.assertIn("the derive function `neg`", e.message)

    def test_gtcheck_refusal_becomes_a_gen_error_with_file_and_line(self):
        model = a2p.shared_model()
        a2p.load_module(model, self.module_text, MODULE)
        with self.assertRaises(a2p.GenError) as c:
            a2p.load_pack(model, self.pack_text.replace("cat250.i010_sac", "cat250.nothing"), PACK)
        self.assertEqual(str(c.exception), "%s:26: undeclared-key: `cat250.nothing`: module `cat250` does not declare `nothing`" % PACK)


class OtherEditions(Workdir):
    """OTHER_EDITIONS: an older edition written beside the newest as asterix-cat<NNN>-ed<edition>.
    The fixture's category 250 stands in for CAT021: edition 1.9 is made an other edition, with a
    definition whose I250/010 differs from that of 1.10."""

    OLDER = "sources/asterix-specs/cat250-1.9.json"

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, a2p, "OTHER_EDITIONS", a2p.OTHER_EDITIONS)
        a2p.OTHER_EDITIONS = {250: ["1.9"]}
        d = json.loads(self.read(DEFINITION))
        d["contents"]["edition"] = {"major": 1, "minor": 9}
        self.write(self.OLDER, json.dumps(d))

    def test_edition_tag_has_the_minor_number_in_two_digits(self):
        self.assertEqual([a2p.edition_tag(e) for e in ("0.23", "0.26", "1.9", "2.10")],
                         ["ed023", "ed026", "ed109", "ed210"])

    def test_other_edition_is_its_own_pack_and_module_and_the_newest_is_unchanged(self):
        status, stdout, stderr = self.run_gen()
        self.assertEqual(status, 0, stderr)
        support.assert_same_tree(self, EXPECTED, self.out,
                                 ignore=("sources/", "packs/asterix-cat250-ed109/", "model/cat250ed109.def",
                                         "tools/gen/names/asterix-cat250-ed109.json",
                                         "packs/canonical-track-v2/vectors/gen-to-asterix-cat250-ed109.json"))
        track = json.loads(self.read("packs/canonical-track-v2/vectors/gen-to-asterix-cat250-ed109.json"))
        self.assertEqual((track["from"], track["to"]), ("canonical-track-v2", "asterix-cat250-ed109"))
        self.assertIn("asterix-cat250-ed109  edition 1.9", stdout)
        pack = self.read("packs/asterix-cat250-ed109/pack.def")
        self.assertIn("format     asterix-cat250-ed109\n", pack)
        self.assertIn("uses       cat250ed109\n", pack)
        self.assertIn("cat250ed109.i010_sac", pack)
        self.assertIn("module", self.read("model/cat250ed109.def"))
        md = self.read("packs/asterix-cat250-ed109/pack.md")
        self.assertIn("This is an older edition of the category, written beside the pack `asterix-cat250` of the newest", md)
        prov = self.read("packs/asterix-cat250-ed109/PROVENANCE.md")
        with open(self.path(self.OLDER), "rb") as fh:
            self.assertIn(hashlib.sha256(fh.read()).hexdigest(), prov)
        self.assertTrue(os.path.exists(self.path("tools/gen/names/asterix-cat250-ed109.json")))

    def test_check_covers_the_other_edition(self):
        self.assertEqual(self.run_gen()[0], 0)
        rel = "packs/asterix-cat250-ed109/pack.md"
        self.write(rel, self.read(rel) + "edited\n")
        status, _, stderr = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn(rel, stderr)

    def test_fetch_downloads_the_other_edition_after_the_newest_and_provenance_lists_it(self):
        calls = []
        a2p.curl = lambda url, dest: calls.append(os.path.relpath(dest, self.out).replace(os.sep, "/"))
        status, _, stderr = self.run_gen("--commit", "c" * 40, "--fetch")
        self.assertEqual(status, 0, stderr)
        self.assertEqual(calls[-2:], [DEFINITION, self.OLDER])
        text = self.read("sources/PROVENANCE.md")
        self.assertIn("| edition taken | for each category the newest edition `manifest.json` lists; also category 250 edition 1.9 |", text)
        self.assertIn("| `cat250-1.9.json` | `specs/cat250/cats/cat1.9/definition.json` | `cccccccccccc` |", text)

    def test_an_edition_the_manifest_does_not_list_is_refused(self):
        a2p.OTHER_EDITIONS = {250: ["0.1"]}
        status, _, stderr = self.run_gen()
        self.assertEqual(status, 1)
        self.assertIn("asterix2pack: sources/asterix-specs/manifest.json: lists no edition 0.1 of category 250", stderr)


def two_uaps(track_prefix=("010", "020")):
    """A category 1 (SWITCHED_UAPS) of two UAPs chosen by 020/TYP: `plot` holds 010, 020, 040 and
    `track` 010, 020, 161, 040."""
    items = [item("010", "Source", element(8)),
             item("020", "Descriptor", group(member("TYP", "Type", element(1)), spare(7))),
             item("040", "Plot Value", element(8)),
             item("161", "Track Number", element(16))]
    d = definition(items, number=1)
    uap = lambda names: [tagged("UapItem", n) for n in names]
    d["contents"]["uap"] = tagged("Uaps", {"cases": [["plot", uap(["010", "020", "040"])],
                                                     ["track", uap(list(track_prefix) + ["161", "040"])]],
                                           "selector": {"item": ["020", "TYP"], "cases": [[0, "plot"], [1, "track"]]}})
    return a2p.Cat(d, "cat001-1.0.json", "specs/x.json")


class SwitchedUaps(unittest.TestCase):
    """A category of SWITCHED_UAPS: one kind, the common items, then `switch` on the selecting key."""

    @classmethod
    def setUpClass(cls):
        cls.plan = a2p.plan_category(two_uaps())
        model = a2p.shared_model()
        module = a2p.load_module(model, a2p.emit_module(cls.plan, "0" * 40), "model/cat001.def")
        cls.pack = a2p.load_pack(model, a2p.emit_pack(cls.plan, "0" * 40), "packs/asterix-cat001/pack.def")
        a2p.check_shape(cls.pack, module)

    def test_common_items_then_a_switch_with_the_first_uap_under_else(self):
        self.assertEqual(pack_lines(self.plan), [
            "if f.1", "field cat001.i010 8 uint", "end",
            "if f.2", "field cat001.i020_typ 1 uint", "pad 7", "end",
            "switch cat001.i020_typ",
            "case 1", "if f.3", "field cat001.i161 16 uint", "end", "if f.4", "field cat001.i040 8 uint", "end",
            "else", "if f.3", "field cat001.i040 8 uint", "end",
            "end"])

    def test_the_selecting_value_picks_the_layout_and_no_item_reads_the_first_uap(self):
        decode = lambda hx: a2p.seq_decode(self.pack, hx)[0]
        self.assertEqual(decode("010008" "e0" "05" "80" "0102"), {"cat001.i010": 5, "cat001.i020_typ": 1, "cat001.i161": 258})
        self.assertEqual(decode("010007" "e0" "05" "00" "07"), {"cat001.i010": 5, "cat001.i020_typ": 0, "cat001.i040": 7})
        self.assertEqual(decode("010006" "a0" "05" "07"), {"cat001.i010": 5, "cat001.i040": 7})
        self.assertEqual(decode("010007" "d0" "05" "80" "07"), {"cat001.i010": 5, "cat001.i020_typ": 1, "cat001.i040": 7})

    def test_fspec_bit_only_the_other_uap_names_is_malformed_wire(self):
        with self.assertRaises(a2p.WireError) as c:
            a2p.seq_decode(self.pack, "010007" "d0" "05" "00" "07")       # plot, FRN 4: only track maps it
        self.assertEqual(c.exception.kind, "malformed-wire")

    def test_encode_takes_the_case_from_the_value_written(self):
        enc = lambda ent: a2p.seq_encode(self.pack, ent, {})
        self.assertEqual(enc({"cat001.i010": 5, "cat001.i020_typ": 1, "cat001.i161": 258, "cat001.i040": 7}), "010009" "f0" "05" "80" "0102" "07")
        self.assertEqual(enc({"cat001.i010": 5, "cat001.i020_typ": 0, "cat001.i161": 258, "cat001.i040": 7}), "010007" "e0" "05" "00" "07")
        self.assertEqual(enc({"cat001.i010": 5, "cat001.i161": 258, "cat001.i040": 7}), "010006" "a0" "05" "07")

    def test_raw_writer_follows_the_uap_of_the_selecting_value(self):
        rec = {"cat001.i010": 5, "cat001.i020_typ": 1, "cat001.i161": 258, "cat001.i040": 7}
        self.assertEqual(a2p.raw_block(self.plan, rec), "010009" "f0" "05" "80" "0102" "07")
        del rec["cat001.i020_typ"]
        self.assertEqual(a2p.raw_block(self.plan, rec), "010006" "a0" "05" "07")

    def test_every_vector_replays(self):
        g = a2p.generate(two_uaps(), {}, "0" * 40, "0" * 40, "0" * 64)
        model = a2p.shared_model()
        a2p.load_module(model, g.files["model/cat001.def"], "model/cat001.def")
        packs = {"asterix-cat001": a2p.load_pack(model, g.files["packs/asterix-cat001/pack.def"], "p")}
        names = [json.loads(t)["name"] for t in g.vectors.values()]
        self.assertIn("track-every-mapped-item-roundtrip", names)
        self.assertIn("without-i020-reads-uap-plot-roundtrip", names)
        self.assertIn("uap-plot-record-with-an-frn-only-uap-track-maps", names)
        for text in g.vectors.values():
            a2p.replay(json.loads(text), packs, a2p.all_derives(model))

    def test_uaps_that_differ_before_the_selecting_item_are_refused(self):
        with self.assertRaises(a2p.GenError) as c:
            a2p.plan_category(two_uaps(track_prefix=("020", "010")))
        self.assertIn("the selecting item 020 does not stand at one FRN in every UAP", str(c.exception))


class CommittedPacks(unittest.TestCase):
    """The generated ASTERIX packs of the repository, read without regenerating them: all of them
    load in gtcheck with the shape the codec reads, and every one of their vectors replays."""

    def test_every_committed_generated_pack_loads_and_every_vector_replays(self):
        model = a2p.shared_model()
        packs = {}
        formats = sorted(os.path.basename(os.path.dirname(p))
                         for p in glob.glob(os.path.join(support.REPO, "packs", "asterix-cat*", "pack.def")))
        formats.remove("asterix-cat062")                                # the hand-written pack is not this generator's
        self.assertGreaterEqual(len(formats), 27)

        def text(*rel):
            with open(os.path.join(support.REPO, *rel), encoding="utf-8") as fh:
                return fh.read()
        modules = {}
        for fmt in formats:
            # asterix-cat021-ed023 -> cat021ed023 (OTHER_EDITIONS)
            name = "cat062full" if fmt == "asterix-cat062-full" else fmt.replace("asterix-", "").replace("-", "")
            modules[fmt] = a2p.load_module(model, text("model", name + ".def"), "model/%s.def" % name)
        for fmt in formats:
            packs[fmt] = a2p.load_pack(model, text("packs", fmt, "pack.def"), "packs/%s/pack.def" % fmt)
            a2p.check_shape(packs[fmt], modules[fmt])
        derives = a2p.all_derives(model)
        replayed = 0
        for fmt in formats:
            paths = sorted(glob.glob(os.path.join(support.REPO, "packs", fmt, "vectors", "*.json")))
            paths += glob.glob(os.path.join(support.REPO, "packs", "canonical-track-v2", "vectors", "gen-to-%s.json" % fmt))
            self.assertTrue(paths, fmt)
            for path in paths:
                with open(path, encoding="utf-8") as fh:
                    a2p.replay(json.load(fh), packs, derives)
                replayed += 1
        self.assertGreaterEqual(replayed, 185)

    def test_replay_refuses_a_vector_whose_expected_bytes_are_wrong(self):
        model, _, pack, _ = load_expected_pack()
        v = {"name": "x", "from": "asterix-cat250", "to": "asterix-cat250", "input": "fa0006800102", "expect": "fa0006800103"}
        with self.assertRaises(a2p.GenError) as c:
            a2p.replay(v, {"asterix-cat250": pack}, a2p.all_derives(model))
        self.assertIn("got fa0006800102, the vector expects fa0006800103", str(c.exception))
        v.update(expect="fa0006800102", model={"cat250.i010_sic": "3"})
        with self.assertRaises(a2p.GenError) as c:
            a2p.replay(v, {"asterix-cat250": pack}, a2p.all_derives(model))
        self.assertIn("model key cat250.i010_sic is 2, the vector expects 3", str(c.exception))


if __name__ == "__main__":
    unittest.main()
