"""Tests for tools/goat-pkg (docs/package-configurator.md). Standard library only:

    python3 -I -m unittest discover -s tools/tests

Most tests run the tool on a small invented tree in a temporary directory: two
packs and four model modules, one of which no pack uses. A few run it on this
repository, to hold the tool to the answers of the Python engine.
"""
import hashlib
import importlib
import io
import json
import os
import sys
import tarfile
import unittest
from unittest import mock

from support import ENGINE_SRC, REPO, TempTree, have_git, load_tool, run_main

pkg = load_tool("goat-pkg")

sys.path.insert(0, ENGINE_SRC)
from goat_transformers import Engine  # noqa: E402

HEAD = 'version 0.1.0\ndistribution public\nsource "an invented public document"\n'
FILES = {
    "LICENSE": "license text\n",
    "NOTICE": "notice text\n",
    "engines/rust/Cargo.toml": '[package]\nname = "x"\nversion = "1.2.3"\n',
    "model/core.def": "module core\n" + HEAD + (
        'key uid string - "identifier"\nkey lat float deg "latitude"\n'
        'key lon float deg "longitude"\nkey callsign string - "name"\n'),
    # `extra` uses `shape`; no pack uses `unused`.
    "model/shape.def": "module shape\n" + HEAD + 'key label string - "label"\nlist points "points of a shape"\n',
    "model/extra.def": "module extra\n" + HEAD + 'uses shape\nkey note string - "note"\n',
    "model/unused.def": "module unused\n" + HEAD + 'key spare string - "spare"\n',
    "packs/alpha/pack.def": "format alpha\n" + HEAD + (
        "wire json\nfield uid id string\nfield lat lat float\nfield lon lon float\nfield callsign name string\n"),
    "packs/alpha/pack.md": "notes\n",
    "packs/alpha/vectors/one.json": "{}\n",
    # The directory is not named after the format; the format name and two
    # locators hold a `#` inside double quotes; fields are in kinds and a group.
    "packs/beta-dir/pack.def": 'format "beta#2"   # the name holds a number sign\n' + HEAD + (
        "uses extra\nuses shape\nwire json\n"
        'field uid "id#text" string\n'
        "kind located\nwhen shape located\nrequires lat lon\n"
        "field lat lat float\nfield lon lon float\n"
        "group shape.points points\n"
        '  field shape.label "name #1" string\n'
        "end\n"
        "kind bare\nwhen shape bare\n"
        'field extra.note "note # not a comment" string\n'),
    "packs/conformance/load-vectors/one.json": "{}\n",
    "packs/not-a-pack/readme.md": "no pack.def here\n",
}
BETA_KEYS = ["uid", "lat", "lon", "shape.points[]", "shape.points[].shape.label", "extra.note"]


class PkgCase(unittest.TestCase):
    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        env = mock.patch.dict(os.environ, self.tree.env, clear=True)
        env.start()
        self.addCleanup(env.stop)
        for rel, text in FILES.items():
            self.tree.write(rel, text)
        self.out = os.path.join(self.tree.beside, "out")

    def run_pkg(self, *argv, root=None):
        return run_main(pkg.main, *argv, root=root or self.tree.root)

    def ok(self, *argv, root=None):
        code, out, err = self.run_pkg(*argv, root=root)
        self.assertEqual((code, err), (0, ""), out)
        return out

    def refused(self, *argv):
        """The command exits 1, prints nothing, and says why. -> the reason"""
        code, out, err = self.run_pkg(*argv)
        self.assertEqual((code, out), (1, ""), err)
        self.assertTrue(err.startswith("error: "), err)
        return err

    def plan(self, *argv, formats="alpha"):
        return json.loads(self.ok("plan", "--formats", formats, "--json", *argv))

    def files_in(self, directory):
        found = []
        for folder, _, names in os.walk(directory):
            found += [os.path.relpath(os.path.join(folder, n), directory).replace(os.sep, "/") for n in names]
        return sorted(found)


class Formats(PkgCase):
    def test_lists_each_format_with_its_wire_and_the_keys_the_engine_reports(self):
        self.assertEqual(self.ok("formats").splitlines(), [
            "alpha   wire=json      fields=uid, lat, lon, callsign",
            "beta#2  wire=json      fields=" + ", ".join(BETA_KEYS),
        ])

    def test_keys_are_those_of_the_engine_for_every_pack_of_this_repository(self):
        engine = Engine.from_dir(os.path.join(REPO, "packs"), os.path.join(REPO, "model"))
        listed = {}
        for line in self.ok("formats", root=REPO).splitlines():
            name, rest = line.split(None, 1)
            listed[name] = rest.split("fields=", 1)[1]
        self.assertEqual(listed, {f: ", ".join(engine.model_keys(f)) for f in engine.formats()})

    def test_a_tree_with_no_packs_is_an_error(self):
        empty = os.path.join(self.tree.beside, "empty")
        os.makedirs(empty)
        code, out, _ = self.run_pkg("formats", root=empty)
        self.assertEqual(code, 1)
        self.assertIn("no packs found", out)

    def test_a_pack_that_does_not_load_is_named_and_left_out(self):
        self.tree.write("packs/broken/pack.def", "format broken\nno-such-directive 1\n")
        code, out, err = self.run_pkg("formats")
        self.assertEqual(code, 0)
        self.assertEqual([line.split()[0] for line in out.splitlines()], ["alpha", "beta#2"])
        self.assertIn("warning: packs/broken does not load and is left out", err)


class Plan(PkgCase):
    def test_json_schema(self):
        self.assertEqual(self.plan(formats="alpha,beta#2"), {
            "constraints": {
                "formats": ["alpha", "beta#2"], "language": "rust", "runtime": "native",
                "linkage": "static", "os": "linux", "arch": "x86_64",
            },
            "package": {
                "engine": "engines/rust",
                "packs": ["packs/alpha", "packs/beta-dir"],
                "wires_used": ["json"],
                "wire_switch": "cargo build --release --no-default-features --features json",
                "build_command": "cargo build --release --target x86_64-unknown-linux-musl",
                "profile": "open",
            },
            "convertibility": [
                {"from": "alpha", "to": "beta#2", "carried": ["uid", "lat", "lon"], "dropped": ["callsign"],
                 "grade": "partial"},
                {"from": "beta#2", "to": "alpha", "carried": ["uid", "lat", "lon"],
                 "dropped": ["shape.points[]", "shape.points[].shape.label", "extra.note"], "grade": "partial"},
            ],
        })

    def test_text_output(self):
        self.assertEqual(self.ok("plan", "--formats", "alpha,beta#2", "--language", "go").splitlines(), [
            "# Minimum package for: alpha, beta#2",
            "#   go / native / linkage=static / linux / x86_64",
            "",
            "engine:      engines/go",
            "packs:       alpha, beta-dir   (only these)",
            "wires used:  json",
            "wires only:  go build -tags goat_wires,goat_wire_json ./cmd/goat-xf   (spec 0.24: the other wires' codecs left out)",
            "build:       CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./cmd/goat-xf",
            "profile:     open   (LICENSING.md)",
            "",
            "convertibility among the requested formats:",
            "         alpha -> beta#2       PARTIAL carries [uid, lat, lon]  (drops callsign: beta#2 has no field for them)",
            ("        beta#2 -> alpha        PARTIAL carries [uid, lat, lon]"
             "  (drops shape.points[], shape.points[].shape.label, extra.note: alpha has no field for them)"),
        ])

    def test_convertibility_is_the_capability_report_of_the_engine(self):
        formats = ["cot-xml", "geojson", "demo-kinds-bits", "conformance-groups-json"]
        engine = Engine.from_dir(os.path.join(REPO, "packs"), os.path.join(REPO, "model"), packs_only=formats)
        planned = json.loads(self.ok("plan", "--formats", ",".join(formats), "--json", root=REPO))
        self.assertEqual(
            planned["convertibility"], [engine.capability(a, b) for a in formats for b in formats if a != b])
        self.assertEqual(planned["package"]["wires_used"], ["bits", "geojson", "json", "xml"])

    def test_a_plan_holds_the_packs_inner_lines_name_and_carries_their_keys(self):
        # spec 0.34: conformance-inner-length frames a conformance-inner-seq
        # message; the package needs that pack to decode it, and the keys it
        # maps carry to conformance-inner-fixed through it
        formats = ["conformance-inner-length", "conformance-inner-fixed"]
        planned = json.loads(self.ok("plan", "--formats", ",".join(formats), "--json", root=REPO))
        self.assertEqual(planned["constraints"]["formats"], formats)
        self.assertEqual(planned["package"]["packs"], [
            "packs/conformance-inner-length", "packs/conformance-inner-fixed", "packs/conformance-inner-seq"])
        engine = Engine.from_dir(os.path.join(REPO, "packs"), os.path.join(REPO, "model"), packs_only=formats,
                                 with_inner=True)
        self.assertEqual(
            planned["convertibility"], [engine.capability(a, b) for a in formats for b in formats if a != b])
        there = planned["convertibility"][0]
        self.assertEqual((there["grade"], there["carried"]), ("partial", ["probe.x", "probe.y", "probe.z"]))

    def test_an_inner_line_naming_no_pack_of_the_tree_adds_none(self):
        planned = json.loads(self.ok("plan", "--formats", "conformance-inner-missing", "--json", root=REPO))
        self.assertEqual(planned["package"]["packs"], ["packs/conformance-inner-missing"])

    def test_one_format_has_no_pairs_and_a_repeated_format_counts_once(self):
        self.assertEqual(self.plan(formats="alpha")["convertibility"], [])
        self.assertEqual(self.plan(formats=" alpha, ,alpha")["constraints"]["formats"], ["alpha"])

    def test_an_unknown_format_is_refused_and_the_available_ones_are_listed(self):
        err = self.refused("plan", "--formats", "alpha,nope,beta-dir")
        self.assertEqual(err, "error: formats not available: nope, beta-dir\navailable: alpha, beta#2\n")

    def test_no_format_named_is_refused(self):
        self.assertIn("(none named)", self.refused("plan", "--formats", " , "))

    def test_an_unsupported_language_and_runtime_pair_is_refused(self):
        for language, runtime in (("java", "native"), ("python", "wasm"), ("rust", "jvm"), ("go", "browser")):
            with self.subTest(language=language, runtime=runtime):
                err = self.refused("plan", "--formats", "alpha", "--language", language, "--runtime", runtime)
                self.assertIn("error: %s has no %s runtime target yet" % (language, runtime), err)
                self.assertIn("java/jvm", err)

    def test_an_unknown_language_is_a_wrong_command_line(self):
        code, _, err = self.run_pkg("plan", "--formats", "alpha", "--language", "cobol")
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", err)

    def test_build_command_names_a_target_that_exists(self):
        cases = {
            ("rust", "static", "linux", "x86_64"): "cargo build --release --target x86_64-unknown-linux-musl",
            ("rust", "static", "linux", "arm64"): "cargo build --release --target aarch64-unknown-linux-musl",
            ("rust", "dynamic", "linux", "aarch64"): "cargo build --release --target aarch64-unknown-linux-gnu",
            ("rust", "dynamic", "darwin", "x86_64"): "cargo build --release --target x86_64-apple-darwin",
            ("rust", "dynamic", "macos", "arm64"): "cargo build --release --target aarch64-apple-darwin",
            ("rust", "dynamic", "windows", "amd64"): "cargo build --release --target x86_64-pc-windows-msvc",
            ("zig", "static", "linux", "x86_64"): "zig build -Dtarget=x86_64-linux-musl -Doptimize=ReleaseSmall",
            ("zig", "dynamic", "linux", "aarch64"): "zig build -Dtarget=aarch64-linux-gnu -Doptimize=ReleaseSmall",
            ("zig", "dynamic", "darwin", "arm64"): "zig build -Dtarget=aarch64-macos -Doptimize=ReleaseSmall",
            ("zig", "dynamic", "windows", "x86_64"): "zig build -Dtarget=x86_64-windows-gnu -Doptimize=ReleaseSmall",
            ("go", "static", "darwin", "arm64"): "CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build ./cmd/goat-xf",
            ("go", "dynamic", "linux", "x86_64"): "GOOS=linux GOARCH=amd64 go build ./cmd/goat-xf",
            ("go", "static", "freebsd", "riscv64"): "CGO_ENABLED=0 GOOS=freebsd GOARCH=riscv64 go build ./cmd/goat-xf",
            ("cpp", "static", "linux", "x86_64"):
                "cmake -DCMAKE_EXE_LINKER_FLAGS=-static -S engines/cpp -B build && cmake --build build",
            ("cpp", "dynamic", "darwin", "arm64"): "cmake -S engines/cpp -B build && cmake --build build",
        }
        for (language, linkage, os_name, arch), command in cases.items():
            with self.subTest(language=language, linkage=linkage, os=os_name, arch=arch):
                planned = self.plan("--language", language, "--linkage", linkage, "--os", os_name, "--arch", arch)
                self.assertEqual(planned["package"]["build_command"], command)
                # the constraints are reported as the caller wrote them
                self.assertEqual((planned["constraints"]["os"], planned["constraints"]["arch"]), (os_name, arch))

    def test_a_static_build_on_darwin_is_refused_not_invented(self):
        # There is no musl target for darwin, and `-static` does not link there.
        for language in ("rust", "zig", "cpp"):
            for os_name in ("darwin", "macos"):
                with self.subTest(language=language, os=os_name):
                    err = self.refused(
                        "plan", "--formats", "alpha", "--language", language, "--os", os_name, "--linkage", "static")
                    self.assertEqual(err, (
                        "error: %s/native has no static build for --os darwin\n"
                        "static builds are stated for: linux; try --linkage dynamic\n") % language)

    def test_an_operating_system_with_no_stated_target_is_refused(self):
        err = self.refused("plan", "--formats", "alpha", "--os", "plan9", "--linkage", "dynamic")
        self.assertEqual(err, (
            "error: rust/native has no dynamic build for --os plan9\n"
            "dynamic builds are stated for: darwin, linux, windows\n"))

    def test_linkage_and_machine_do_not_apply_to_a_runtime_that_abstracts_them(self):
        planned = self.plan("--runtime", "wasm", "--os", "darwin", "--linkage", "static")
        self.assertEqual(planned["constraints"]["linkage"], "any")
        self.assertEqual(
            planned["package"]["build_command"], "cargo build --release --lib --target wasm32-unknown-unknown")
        self.assertEqual(self.plan("--language", "java", "--runtime", "jvm")["constraints"]["linkage"], "any")

    def test_every_stated_build_is_a_complete_command(self):
        for (language, runtime), builds in pkg.BUILD.items():
            for linkage in builds:
                stated = pkg.TARGETS.get((language, linkage), {"linux": ""})
                for os_name in stated:
                    with self.subTest(language=language, runtime=runtime, linkage=linkage, os=os_name):
                        _, command = pkg.build_command(language, runtime, linkage, os_name, "aarch64")
                        self.assertNotRegex(command, r"[{}]")
                        self.assertNotIn("darwin-musl", command)

    def test_a_named_pack_that_does_not_load_with_its_modules_is_refused(self):
        # a key its modules do not declare: the pack is in a profile, and fails at load
        self.tree.write("packs/alpha/pack.def", FILES["packs/alpha/pack.def"] + "field nosuchkey k string\n")
        err = self.refused("plan", "--formats", "alpha")
        self.assertIn("error: the named packs do not load: undeclared-key", err)

    def test_a_named_pack_that_uses_a_missing_module_is_in_no_profile(self):
        # spec 0.93 ruling 2: for a tool, a pack whose uses names no module file has the profile none
        self.tree.write("packs/alpha/pack.def", FILES["packs/alpha/pack.def"] + "uses absent\n")
        for profile in ("open", "everything"):
            err = self.refused("plan", "--formats", "alpha", "--profile", profile)
            self.assertIn("packs/alpha, uses module absent, which no module file names", err)

    def test_a_pack_that_does_not_parse_is_not_available(self):
        self.tree.write("packs/alpha/pack.def", "format alpha\nno-such-directive 1\n")
        code, out, err = self.run_pkg("plan", "--formats", "alpha")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("warning: packs/alpha does not load", err)
        self.assertIn("error: formats not available: alpha", err)


class Bundle(PkgCase):
    def bundle(self, *argv, formats="alpha"):
        self.ok("bundle", "--formats", formats, "--out", self.out, *argv)
        with open(os.path.join(self.out, "manifest.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_holds_only_the_named_pack_and_the_modules_it_needs(self):
        manifest = self.bundle(formats="alpha")
        self.assertEqual(
            self.files_in(self.out), ["LICENSE", "NOTICE", "manifest.json", "model/core.def", "packs/alpha/pack.def"])
        self.assertEqual((manifest["formats"], manifest["packs"], manifest["modules"]), (["alpha"], ["alpha"], ["core"]))

    def test_holds_the_modules_that_used_modules_use_each_after_those_it_uses(self):
        manifest = self.bundle(formats="beta#2,alpha")
        self.assertEqual(manifest["formats"], ["beta#2", "alpha"])
        self.assertEqual(manifest["packs"], ["beta-dir", "alpha"])
        self.assertEqual(manifest["modules"], ["core", "shape", "extra"])
        self.assertEqual(self.files_in(os.path.join(self.out, "model")), ["core.def", "extra.def", "shape.def"])

    def test_manifest_records_the_version_and_the_sha256_of_every_file(self):
        manifest = self.bundle(formats="alpha")
        self.assertEqual(manifest["library"], "goat-transformers")
        self.assertEqual(manifest["version"], "1.2.3")
        self.assertEqual(sorted(manifest["sha256"]), ["LICENSE", "NOTICE", "model/core.def", "packs/alpha/pack.def"])
        for rel, digest in manifest["sha256"].items():
            self.assertEqual(digest, hashlib.sha256(FILES[rel].encode()).hexdigest(), rel)

    def test_outside_a_git_checkout_the_commit_is_not_known(self):
        manifest = self.bundle()
        self.assertEqual((manifest["commit"], manifest["modified"]), (None, None))

    @unittest.skipUnless(have_git(), "git is not installed")
    def test_in_a_git_checkout_the_commit_and_whether_the_packs_differ_from_it(self):
        self.tree.git("init", "-q")
        self.tree.git("add", "--all")
        self.tree.git("-c", "user.name=t", "-c", "user.email=t", "commit", "-q", "--no-gpg-sign", "-m", "all")
        head = self.tree.git("rev-parse", "HEAD").strip()
        manifest = self.bundle()
        self.assertEqual((manifest["commit"], manifest["modified"]), (head, False))
        self.tree.write("docs/unrelated.md", "not part of a bundle\n")
        self.assertEqual(self.bundle()["modified"], False)
        self.tree.write("model/core.def", FILES["model/core.def"] + 'key hae float m "height"\n')
        self.assertEqual(self.bundle()["modified"], True)

    def test_loads_in_the_python_engine_and_converts(self):
        self.bundle(formats="alpha,beta#2")
        engine = Engine.from_dir(os.path.join(self.out, "packs"), os.path.join(self.out, "model"))
        self.assertEqual(engine.formats(), ["alpha", "beta#2"])
        self.assertEqual(engine.model_keys("beta#2"), BETA_KEYS)
        message = b'{"id":"a-1","lat":1.5,"lon":2.5,"name":"n"}'
        self.assertEqual(json.loads(engine.convert("alpha", "alpha", message)), json.loads(message))
        self.assertEqual(
            json.loads(engine.convert("alpha", "beta#2", message)),
            {"id#text": "a-1", "shape": "located", "lat": 1.5, "lon": 2.5})

    def test_the_bundle_ci_writes_from_this_repository_loads(self):
        self.ok("bundle", "--formats", "cot-xml,geojson", "--out", self.out, root=REPO)
        engine = Engine.from_dir(os.path.join(self.out, "packs"), os.path.join(self.out, "model"))
        self.assertEqual(engine.formats(), ["cot-xml", "geojson"])
        with open(os.path.join(self.out, "manifest.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertEqual(manifest["modules"], list(engine.models))
        self.assertEqual(sorted(manifest["sha256"]), [f for f in self.files_in(self.out) if f != "manifest.json"])

    def test_a_bundle_of_an_outer_format_holds_its_inner_pack_and_decodes_the_payload(self):
        self.ok("bundle", "--formats", "conformance-inner-length", "--out", self.out, root=REPO)
        with open(os.path.join(self.out, "manifest.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertEqual(manifest["formats"], ["conformance-inner-length"])
        self.assertEqual(manifest["packs"], ["conformance-inner-length", "conformance-inner-seq"])
        engine = Engine.from_dir(os.path.join(self.out, "packs"), os.path.join(self.out, "model"))
        self.assertEqual(engine.formats(), ["conformance-inner-length", "conformance-inner-seq"])
        # packs/conformance-inner-length/vectors/01: n=9, then 3 bytes of a
        # conformance-inner-seq message of kind a (x=2, y=3), then w=10
        message = b"09030102030a"
        self.assertEqual(engine.convert("conformance-inner-length", "conformance-inner-length", message), message)
        self.assertEqual(engine.convert("conformance-inner-length", "conformance-inner-seq", message), b"010203")

    def test_writing_again_replaces_model_and_packs_and_nothing_else(self):
        self.bundle(formats="beta#2")
        kept = os.path.join(self.out, "keep.txt")
        with open(kept, "w", encoding="utf-8") as fh:
            fh.write("the caller's own file\n")
        self.bundle(formats="alpha")
        self.assertEqual(self.files_in(self.out), [
            "LICENSE", "NOTICE", "keep.txt", "manifest.json", "model/core.def", "packs/alpha/pack.def"])

    def test_an_unknown_format_writes_nothing(self):
        self.refused("bundle", "--formats", "alpha,nope", "--out", self.out)
        self.assertFalse(os.path.exists(self.out))

    def test_embed_rust_loads_modules_then_packs_in_loading_order(self):
        manifest = self.bundle("--embed", "rust", formats="beta#2,alpha")
        with open(os.path.join(self.out, "goat_packs.rs"), encoding="utf-8") as fh:
            source = fh.read()
        self.assertEqual([line.strip() for line in source.splitlines() if "include_str!" in line], [
            'engine.load_model(include_str!("model/core.def"))?;',
            'engine.load_model(include_str!("model/shape.def"))?;',
            'engine.load_model(include_str!("model/extra.def"))?;',
            'engine.load_def(include_str!("packs/beta-dir/pack.def"))?;',
            'engine.load_def(include_str!("packs/alpha/pack.def"))?;',
        ])
        self.assertIn("pub fn engine() -> Result<goat_transformers::Engine, goat_transformers::Error> {", source)
        self.assertEqual(manifest["sha256"]["goat_packs.rs"], hashlib.sha256(source.encode()).hexdigest())

    def test_embed_go_names_the_package_and_the_packs(self):
        self.bundle("--embed", "go", "--package", "mypacks", formats="beta#2,alpha")
        with open(os.path.join(self.out, "goatpacks.go"), encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn("\npackage mypacks\n", source)
        self.assertIn("//go:embed model packs\nvar Tree embed.FS\n", source)
        self.assertIn('var Packs = []string{"beta-dir", "alpha"}\n', source)

    def test_embed_python_is_a_package_whose_engine_holds_the_bundle(self):
        self.out = os.path.join(self.tree.beside, "goatbundle")
        self.bundle("--embed", "python", formats="beta#2,alpha")
        with mock.patch.object(sys, "path", [self.tree.beside] + sys.path):
            try:
                bundle = importlib.import_module("goatbundle")
                self.assertEqual(bundle.PACKS, ["beta-dir", "alpha"])
                self.assertEqual(bundle.engine().formats(), ["alpha", "beta#2"])
            finally:
                sys.modules.pop("goatbundle", None)

    def test_every_embed_at_once_and_a_repeated_one_once(self):
        manifest = self.bundle("--embed", "rust", "--embed", "go", "--embed", "python", "--embed", "rust")
        self.assertEqual(
            [f for f in manifest["sha256"] if "/" not in f],
            ["LICENSE", "NOTICE", "goat_packs.rs", "goatpacks.go", "__init__.py"])


class Archive(PkgCase):
    def archive(self, *argv):
        path = os.path.join(self.tree.beside, "packs.tar.gz")
        out = self.ok("archive", "--out", path, *argv)
        with open(path, "rb") as fh:
            data = fh.read()
        self.assertIn("%d bytes" % len(data), out)
        return data

    def members(self, data):
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            return tar.getmembers(), {m.name: tar.extractfile(m).read() for m in tar.getmembers()}

    def test_holds_every_module_and_pack_without_the_vectors(self):
        members, content = self.members(self.archive())
        self.assertEqual([m.name for m in members], [
            "LICENSE", "NOTICE", "model/core.def", "model/extra.def", "model/shape.def", "model/unused.def",
            "packs/alpha/pack.def", "packs/alpha/pack.md", "packs/beta-dir/pack.def", "packs/not-a-pack/readme.md",
        ])
        for name, data in content.items():
            self.assertEqual(data, FILES[name].encode(), name)

    def test_vectors_on_request(self):
        names = [m.name for m in self.members(self.archive("--vectors"))[0]]
        self.assertIn("packs/alpha/vectors/one.json", names)
        self.assertIn("packs/conformance/load-vectors/one.json", names)
        self.assertEqual(names, sorted(names))

    def test_prefix_is_a_directory_every_member_is_under(self):
        for prefix in ("goat-1.2.3", "/goat-1.2.3/"):
            names = [m.name for m in self.members(self.archive("--prefix", prefix))[0]]
            self.assertTrue(all(n.startswith("goat-1.2.3/") for n in names), names)
            self.assertIn("goat-1.2.3/model/core.def", names)

    def test_members_carry_no_time_no_owner_and_one_mode(self):
        for member in self.members(self.archive())[0]:
            self.assertEqual(
                (member.mtime, member.uid, member.gid, member.uname, member.gname, member.mode),
                (0, 0, 0, "", "", 0o644), member.name)

    def test_the_same_tree_gives_the_same_bytes(self):
        first = self.archive()
        for rel in ("model/core.def", "packs/alpha/pack.def"):
            os.utime(os.path.join(self.tree.root, rel), (1, 1))
        self.assertEqual(self.archive(), first)
        self.tree.write("model/core.def", FILES["model/core.def"] + 'key hae float m "height"\n')
        self.assertNotEqual(self.archive(), first)


REUSE = """version = 1

[[annotations]]
path = "**"
precedence = "override"
SPDX-FileCopyrightText = "2026 test"
SPDX-License-Identifier = "Apache-2.0"

"""
LICENCES = """[licences."Apache-2.0"]
commercial = "yes"
share_alike = false
attribution = true
field_of_use = []
distribution = "public"

[licences."CC-BY-NC-SA-4.0"]
commercial = "no"
share_alike = true
attribution = true
field_of_use = []
distribution = "public"
"""


class Profiles(PkgCase):
    """--profile: the module `shape` is CC-BY-NC-SA-4.0, so `extra`, which uses
    it, and the pack beta-dir, which uses both, are only in `everything`."""

    def setUp(self):
        super().setUp()
        self.tree.write("REUSE.toml", REUSE)
        self.tree.write("licences.toml", LICENCES)
        # a module's licence is in its own companion file (spec 0.29, 1b)
        self.tree.write("model/shape.def.license", "SPDX-FileCopyrightText: 2026 test\n"
                        "SPDX-License-" + "Identifier: CC-BY-NC-SA-4.0\n")
        self.tree.write("packs/alpha/vectors/to-beta.json", '{"from": "alpha", "to": "beta#2"}\n')

    def archive(self, *argv):
        path = os.path.join(self.tree.beside, "p.tar.gz")
        self.ok("archive", "--out", path, "--vectors", *argv)
        with tarfile.open(path, mode="r:gz") as tar:
            return tar.getnames()

    def test_open_archive_leaves_out_the_pack_its_modules_and_the_vectors_that_name_it(self):
        names = self.archive()
        for gone in ("packs/beta-dir/pack.def", "model/shape.def", "model/extra.def",
                     "packs/alpha/vectors/to-beta.json"):
            self.assertNotIn(gone, names)
        for kept in ("packs/alpha/pack.def", "packs/alpha/vectors/one.json", "model/core.def",
                     "REUSE.toml", "licences.toml"):
            self.assertIn(kept, names)

    def test_everything_archive_keeps_all(self):
        names = self.archive("--profile", "everything")
        for kept in ("packs/beta-dir/pack.def", "model/shape.def", "packs/alpha/vectors/to-beta.json"):
            self.assertIn(kept, names)
        self.assertEqual(names, sorted(names))

    def test_plan_and_bundle_refuse_a_pack_outside_the_profile(self):
        for argv in (("plan", "--formats", "alpha,beta#2"),
                     ("bundle", "--formats", "beta#2", "--out", self.out),
                     ("plan", "--formats", "beta#2", "--profile", "open+copyleft")):
            err = self.refused(*argv)
            self.assertIn("packs/beta-dir, uses module", err)
        self.assertFalse(os.path.exists(self.out))
        self.assertEqual(self.plan("--profile", "everything", formats="alpha,beta#2")["package"]["profile"],
                         "everything")

    def test_bundle_carries_the_licence_files_and_its_profile(self):
        self.ok("bundle", "--formats", "beta#2", "--out", self.out, "--profile", "everything")
        files = self.files_in(self.out)
        self.assertIn("REUSE.toml", files)
        self.assertIn("licences.toml", files)
        with open(os.path.join(self.out, "manifest.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["profile"], "everything")

    def test_a_pack_that_is_not_shown_public_is_in_no_profile(self):
        """Spec 0.93: its licence (here the default, Apache-2.0) does not put it
        in a profile; even `everything` leaves it out."""
        text = FILES["packs/alpha/pack.def"]
        self.assertIn("distribution public", text)
        self.tree.write("packs/alpha/pack.def", text.replace("distribution public", "distribution controlled"))
        for profile in ("open", "open+copyleft", "everything"):
            names = self.archive("--profile", profile)
            self.assertNotIn("packs/alpha/pack.def", names, profile)
            self.assertIn("packs/beta-dir/pack.def" if profile == "everything" else "model/core.def", names)
            err = self.refused("plan", "--formats", "alpha", "--profile", profile)
            self.assertIn("packs/alpha, is not shown public", err)

    def test_the_plan_request_takes_a_profile(self):
        self.assertEqual(pkg.plan_request("formats=a").profile, "open")
        self.assertEqual(pkg.plan_request("formats=a&profile=everything").profile, "everything")
        with self.assertRaises(ValueError):
            pkg.plan_request("formats=a&profile=closed")


class WireSwitch(unittest.TestCase):
    def test_each_language_names_its_switch(self):
        got = {lang: pkg.wire_switch(lang, {"xml", "bits"}) for lang in pkg.WIRE_SWITCH}
        self.assertEqual(got["rust"], "cargo build --release --no-default-features --features xml,bits")
        self.assertEqual(got["go"], "go build -tags goat_wires,goat_wire_xml,goat_wire_bits ./cmd/goat-xf")
        self.assertEqual(got["zig"], "zig build cli -Dwires=xml,bits")
        self.assertIn("-DGT_WIRES=xml,bits", got["cpp"])

    def test_every_wire_needs_no_switch(self):
        self.assertIsNone(pkg.wire_switch("rust", set(pkg.WIRES)))


class CommandLine(PkgCase):
    def test_a_command_is_required(self):
        code, _, err = self.run_pkg()
        self.assertEqual(code, 2)
        self.assertIn("required", err)

    def test_the_default_tree_is_the_repository_the_tool_is_in(self):
        code, out, _ = run_main(pkg.main, "plan", "--formats", "remote-id,cot-xml", "--runtime", "wasm")
        self.assertEqual(code, 0)
        self.assertIn("packs:       remote-id, cot-xml   (only these)", out)
        self.assertIn("wires used:  bits, xml\n", out)
        self.assertIn("wires only:  cargo build --release --no-default-features --features xml,bits", out)


if __name__ == "__main__":
    unittest.main()


class ServeTest(PkgCase):
    """`serve`: the planner over HTTP, on the invented tree, on a free port."""

    def setUp(self):
        super().setUp()
        import threading
        self.server = pkg.make_server(self.tree.root, "127.0.0.1", 0, log_requests=False)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.shutdown)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def get(self, path):
        """-> (status, content type, body as text)"""
        import urllib.error
        import urllib.request
        try:
            with urllib.request.urlopen(self.base + path, timeout=10) as r:
                return r.status, r.headers["Content-Type"], r.read().decode()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.headers["Content-Type"], e.read().decode()

    def test_a_plan_is_the_json_of_plan_json(self):
        status, kind, body = self.get("/plan?formats=alpha,beta%232&language=go&os=darwin&linkage=dynamic")
        self.assertEqual((status, kind), (200, "application/json; charset=utf-8"))
        self.assertEqual(json.loads(body), self.plan("--language", "go", "--os", "darwin", "--linkage", "dynamic",
                                                     formats="alpha,beta#2"))

    def test_the_defaults_are_those_of_plan(self):
        self.assertEqual(json.loads(self.get("/plan?formats=alpha")[2]), self.plan())

    def test_formats_lists_each_format_its_wire_and_keys(self):
        status, _, body = self.get("/formats")
        self.assertEqual(status, 200)
        listed = {f["format"]: f for f in json.loads(body)}
        self.assertEqual(sorted(listed), ["alpha", "beta#2"])
        self.assertEqual(listed["beta#2"]["keys"], BETA_KEYS)
        self.assertEqual(listed["alpha"]["wire"], "json")

    def test_a_request_that_cannot_be_met_is_422_and_says_why(self):
        status, _, body = self.get("/plan?formats=gamma")
        self.assertEqual(status, 422)
        self.assertIn("formats not available: gamma", json.loads(body)["error"])
        status, _, body = self.get("/plan?formats=alpha&language=java&runtime=wasm")
        self.assertEqual(status, 422)
        self.assertIn("java has no wasm runtime target", json.loads(body)["error"])

    def test_a_wrong_field_is_400(self):
        for query, why in (
            ("language=go", "field formats is required"),
            ("formats=alpha&colour=red", "unknown field: colour"),
            ("formats=alpha&formats=beta%232", "field formats is given 2 times"),
            ("formats=alpha&language=cobol", "language cobol is not one of"),
            ("formats=alpha&linkage=partial", "linkage partial is not static or dynamic"),
        ):
            with self.subTest(query):
                status, _, body = self.get("/plan?" + query)
                self.assertEqual(status, 400)
                self.assertIn(why, json.loads(body)["error"])

    def test_a_long_query_is_refused(self):
        self.assertEqual(self.get("/plan?formats=" + "a" * (pkg.MAX_QUERY + 1))[0], 414)

    def test_the_form_and_an_unknown_path(self):
        status, kind, body = self.get("/")
        self.assertEqual((status, kind), (200, "text/html; charset=utf-8"))
        self.assertIn("<option>zig</option>", body)
        self.assertEqual(self.get("/nothing")[0], 404)

    def test_the_tree_is_read_once_at_start(self):
        self.tree.write("packs/late/pack.def", "format late\n" + HEAD + "wire json\nfield uid id string\n")
        self.assertEqual(self.get("/plan?formats=late")[0], 422)

    def test_a_tree_with_no_pack_is_refused_at_start(self):
        empty = TempTree()
        self.addCleanup(empty.cleanup)
        with self.assertRaises(pkg.Unmet):
            pkg.make_server(empty.root, "127.0.0.1", 0)
