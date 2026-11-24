# goat-transformers (Python)

The Python engine of [goat-transformers](https://github.com/USAREUR-AF/goat-transformers):
it converts messages between formats that are described by data files (packs).
Python 3.9 or later, standard library only.

```
pip install "git+https://github.com/USAREUR-AF/goat-transformers@v0.8.0#subdirectory=engines/python"
```

```python
from goat_transformers import Engine

engine = Engine.from_dir("vendor/goat/packs", packs_only=["cot-xml", "geojson"])
geojson = engine.convert("cot-xml", "geojson", cot_event)   # bytes in, bytes out
```

The package holds the engine. The packs are data: `tools/goat-pkg bundle` in
the repository writes the ones you name, and the model modules they use, to a
directory you vendor or ship as package data. `docs/using.md` in the repository
shows the whole path. `goat-xf-py` is the command-line tool (Version 0.23, the command-line contract).

## The library API

Status: Built. Exported by `goat_transformers`; bytes go in and bytes come out.

| Call | Does |
|---|---|
| `Engine.from_dir(packs_dir, models_dir=None, max_distribution="controlled", packs_only=None, profile=None, with_inner=False)` | loads every `<models_dir>/*.def` (default: `model` beside `packs_dir`), then every `<packs_dir>/<format>/pack.def`; with `packs_only`, only the named packs and the modules they use (with `with_inner`, also the packs their `inner` lines name, transitively, Version 0.34); with `profile`, only the modules and packs of that licence profile (Licence profiles, below) |
| `load_dir(packs_dir, models_dir=None, packs_only=None, profile=None)` | `from_dir` on an existing engine: what is loaded stays, and the load is bounded by the engine's distribution limit. With `profile`, an engine that already holds a controlled module or pack refuses the load, `distribution-refused`, before anything is read (Licence profiles, below) |
| `Engine(max_distribution=..., max_items=100000)`, `load_model(text, source=...)`, `load(text, source=...)` | an empty engine; load one model module, then one pack, from text. A second pack with a loaded `format` name is `duplicate-format`, and the first stays loaded |
| `set_max_items(n)` | the limit on list items one decode holds, over every list at every level (ruling 7 of 0.11); 0 or more, 100,000 by default. Going over it is `malformed-wire`; `encode` is not limited |
| `formats()`, `pack(fmt)`, `model_keys(fmt)` | the loaded format names; one parsed pack; the keys a pack maps |
| `decode(fmt, data, max_items=None)` | message to `Entity` (`fields`, `lists`, `residue`, `kind`, `inner_kind`); `max_items` sets the limit for this call. `inner_kind` is the `(format, kind name)` the pack of an `inner` line selected (Version 0.34), or None |
| `encode(fmt, entity)` | `Entity` to message; the kind is the one `kind` names when it names `fmt`, else the one `inner_kind` names, else the first whose `requires` hold |
| `convert(from_fmt, to_fmt, data, context=None, max_items=None)` | decode, fill the keys the input lacks from `context`, derive, encode; `from`, then `to`, is checked before the input is read |
| `complete(entity, context=None)` | the middle steps of `convert` on an entity: fill from `context`, then apply the `derive` lines |
| `capability(from_fmt, to_fmt)` | `{"from", "to", "carried", "dropped", "grade"}`, grade `full`, `partial` or `none` |
| `capability_matrix()` | `capability` for every ordered pair of distinct loaded formats |

A `context` value is text read as the key's declared type, or a value of that
type. Run from the repository root with `event.xml` holding the input of
`packs/cot-xml/vectors/01-track-to-geojson.json`, this prints the comments:

```python
from goat_transformers import Engine, GTError, UndeclaredKey

engine = Engine.from_dir("packs", packs_only=["cot-xml", "geojson"])
cot = open("event.xml", "rb").read()

entity = engine.decode("cot-xml", cot)
print(entity.fields["callsign"], entity.fields["time_ms"])     # GATOR 1614456000000
geojson = engine.encode("geojson", entity)
print(engine.convert("cot-xml", "geojson", cot) == geojson)     # True
out = engine.convert("geojson", "cot-xml", geojson, {"stale_ms": "1614456180000"})
print(b'stale="2021-02-27T20:03:00.000Z"' in out)               # True
engine.complete(entity, {"stale_ms": 1614456180000})
print(entity.fields["stale_ms"])                                # 1614456180000
print(engine.capability("cot-xml", "geojson")["grade"])         # partial
print(len(engine.capability_matrix()))                          # 2
try:
    engine.convert("geojson", "cot-xml", geojson, {"no_such_key": "1"})
except UndeclaredKey as e:
    print(e)    # undeclared-key: context key no_such_key is declared by no loaded module
try:
    engine.convert("cot-xml", "geojson", b"<event")
except GTError as e:
    print(e.code)                                               # malformed-wire

e2 = Engine()
for m in ("core", "track"):
    e2.load_model(open("model/%s.def" % m).read(), source=m + ".def")
e2.load(open("packs/demo-track-json/pack.def").read())
print(e2.formats())                                             # ['demo-track-json']
```

Errors. Every error is a subclass of `GTError`. Its `code` is the error kind,
and its message begins with that kind and a colon, then the text, then
`[format=…]`, `[locator=…]` and `[detail=…]` where they apply.

| Class | `code` |
|---|---|
| `UnterminatedQuote`, `UnknownDirective`, `UnknownTransform`, `UnknownWire`, `BadLocator`, `BadDirective` | `unterminated-quote`, `unknown-directive`, `unknown-transform`, `unknown-wire`, `bad-locator`, `bad-directive` |
| `MissingFormat`, `MissingVersion`, `MissingWire`, `MissingModule`, `DuplicateFormat` | `missing-format`, `missing-version`, `missing-wire`, `missing-module`, `duplicate-format` |
| `InvalidPack`, `InvalidModel` | not raised: the base classes of the load failures of a pack text and of a module text (spec 0.11, ruling 5) |
| `MissingDistribution`, `MissingSource`, `DistributionRefused`, `DistributionViolation` | `missing-distribution`, `missing-source`, `distribution-refused`, `distribution-violation` |
| `UnknownModule`, `ModuleNotUsed`, `DuplicateModule`, `DuplicateKey`, `DuplicateKind` | `unknown-module`, `module-not-used`, `duplicate-module`, `duplicate-key`, `duplicate-kind` |
| `UndeclaredKey`, `KeyTypeMismatch` | `undeclared-key`, `key-type-mismatch` |
| `UnknownFormat`, `NoKind`, `MalformedWire`, `MissingRoot` | `unknown-format`, `no-kind`, `malformed-wire`, `missing-root` |
| `BadLicence` | `bad-licence`: a licence file that cannot be read as Version 0.29, ruling 1 says, or a `profile` not one of the three |
| `TransformDecodeFailure`, `TransformEncodeFailure` | `transform-decode` (with `entity`, the fields that decoded, and `absent`), `transform-encode` |
| `DuplicateField` | `duplicate-field`; withdrawn in version 0.6, kept as a name, not raised |

Also exported: `Entity`, `Item`, `Pack`, `load_pack`, `parse_pack_text`, `Key`,
`Module`, `Derive`, `load_model_file`, `parse_model_text`, and `PROFILES`, the
three profile names.

### Licence profiles

Status: Built (Version 0.29). `Engine.from_dir(..., profile=p)`, with `p` one
of `open`, `open+copyleft` and `everything`, loads only what that profile
holds. Before any module is loaded it reads `<packs_dir>/../licences.toml`
(the flags of each licence), then, for every module file of `models_dir`
(`core.def` first, then the others in byte order of name), its licence in
`<file>.license` and its `module` and `uses` lines. Each pack, as it is
reached, has its licence read from `<packs_dir>/<dir>/REUSE.toml`. A missing
licence file means `Apache-2.0`; a missing `licences.toml` means a table of
`Apache-2.0` alone. A module's profile is the widest of its licence's and
those of the modules it uses; a pack's, the widest of its licence's, `core`'s
and its `uses`'. A module or pack the profile does not hold is not loaded, as
if it were not there; a pack is skipped before it is parsed. A licence file
that cannot be read by the exact line forms of the specification is
`bad-licence`, and so is a `profile` that is not one of the three, before
anything is read. Without `profile` no licence file is read and loading is as
before. With a profile, `engine.licences` maps each loaded format to
`(directory, licence, profile)` of its pack.

Version 0.93: a module file or `pack.def` is in a profile only when it is
shown public: one of its lines is exactly `distribution`, spaces or tabs,
`public`, no other line begins with `distribution` once its double quotes and
end spaces are removed, and it holds no NUL, no U+FEFF and no carriage return
other than before a line feed or at its end. Any other such file, whatever its
licence (an unreadable or non-UTF-8 one included), is in no profile, and so is
whatever uses it; a `core` that is not shown public leaves no pack. A load
with a profile sets the engine's distribution limit to `public` (also when
`controlled` was asked for), for that load and every later one: a controlled
text loaded later with `load` or `load_model`, or a later `load_dir` without a
profile, is `distribution-refused`, and `set_max_distribution("controlled")`
afterwards is no error and has no effect. The order: a profile not one of the
three is `bad-licence` with the limit unchanged; then an engine that already
holds a controlled module or pack is `distribution-refused`; both leave the
limit unchanged and load nothing; then the limit is `public`, and
stays so when the load fails later. The engine reads a module file and a
`pack.def` once for its profile and again to load it, so a file that changed
in between to `controlled` is `distribution-refused`.

```python
engine = Engine.from_dir("packs", packs_only=["cot-xml", "geojson"], profile="open")
```

## The command-line tool `goat-xf-py`

Status: Built. The tool follows the command-line contract of the
specification (`spec/engine-spec.md`, Version 0.23): the same arguments,
output and exit status as the tool of every other engine. Nothing is built.
From a checkout, start it from the repository root as

```
engines/python/goat-xf-py.py <subcommand> ...
```

(a launcher that puts `engines/python/src` on the import path). Installed with
pip, the same tool is `goat-xf-py`, and `python3 -m goat_transformers` starts it too.

| Subcommand | Does |
|---|---|
| `convert --from <format> --to <format> [--set <key>=<value>]...` | reads standard input to its end, writes the result on standard output with nothing added (a hex wire's result as lower-case hex text, no line feed) |
| `list-formats` | one line per loaded pack, in byte order of format name: format, version, wire, separated by tabs |
| `capability --from <format> --to <format>` | the capability report of the pair as one line: from, to, grade, carried, dropped, separated by tabs, the entries of a list joined by a space |
| `matrix` | the header `from	to	grade	carried	dropped`, then one such line per ordered pair of loaded formats, a format with itself included |
| `licences [--json]` | one line per loaded pack, in byte order of its directory name: directory, format, licence and the pack's own profile (`none` for a pack in no profile), separated by tabs; with `--json`, `{"packs":[{"pack":…,"format":…,"licence":…,"profile":…},…]}` on one line. It always reads the licence files (Version 0.29, ruling 4c) |
| `help`, `-h`, `--help` | the usage, on standard output |

| Option | Of | Means |
|---|---|---|
| `--packs <dir>` | all five | the packs directory (default `$GT_PACKS`, else `packs`) |
| `--models <dir>` | all five | the model module directory (default: the `--packs` text followed by `/../model`); every `*.def` in it is loaded |
| `--packs-only <name>[,<name>...]` | all five | load only these subdirectories of `--packs`, in the order given |
| `--max-items <n>` | all five | the limit on list items one decode holds (default 100000) |
| `--max-distribution public\|controlled` | all five | refuse modules and packs above this distribution (default `controlled`; beside `--profile` always `public`, Version 0.93) |
| `--profile open\|open+copyleft\|everything` | all five | load only the modules and packs of this licence profile (default: none, everything loads); any other value is a usage error |
| `--json` | `licences` | the output as JSON; the one option that takes no value |
| `--set <key>=<value>` | `convert` | a caller-supplied model key, read as the key's declared type; repeatable |
| `--from`, `--to` | `convert`, `capability` | the source and target formats |

Every option but `--json` takes its value as the next argument; `--opt=value`, an
abbreviation or an option given twice is a usage error. Exit status: 0 on
success; 1 on a load failure or a call failure, with standard output empty and
standard error's first line the error's message, `<kind>: ...`; 2 on a usage
error, checked before anything is loaded. Run from `engines/python`, with
`feature.json` holding the input of `packs/geojson/vectors/01-geojson-to-cot.json`:

```
$ ./goat-xf-py.py list-formats --packs ../../packs --packs-only cot-xml,geojson
cot-xml	0.6.0	xml
geojson	0.1.0	geojson
$ ./goat-xf-py.py convert --from geojson --to cot-xml --packs ../../packs --packs-only cot-xml,geojson --set stale_ms=1614456180000 < feature.json
<event version="2.0" uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" start="2021-02-27T20:00:00.000Z" stale="2021-02-27T20:03:00.000Z" how="m-g"><point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/><detail><contact callsign="GATOR"/></detail></event>
```

## Builds with fewer wires

Status: Built. Version 0.24 of the specification (ruling 1). The switch is
the build script `build.py`: it copies the package and leaves out the modules
of every wire not named, so the reduced package does not carry their code.
From the repository root:

```
python3 -I engines/python/build.py                            # all eight wires
python3 -I engines/python/build.py --wires xml,json,geojson   # only these
python3 -I engines/python/build.py --wires bits --out /tmp/gx # elsewhere
```

`--wires` takes a comma-separated set from `xml`, `geojson`, `json`, `bits`,
`protobuf`, `text`, `tlv`, `cbor`; without it the build has all eight, as the source
tree and `pip install` from the repository have. The build writes
`<out>/src/goat_transformers/` (put `<out>/src` on the import path) and a
wheel, `<out>/dist/goat_transformers-<version>-py3-none-any.whl`, for
`pip install`. `<out>` defaults to `engines/python/build/wires-<set>`. The
copy's `_build.py` names the set; `goat_transformers._build.WIRES` reads it.

| Wire | Modules left out without it |
|---|---|
| `xml` | `wire_xml` |
| `geojson` | `wire_geojson` |
| `json` | `wire_json` |
| `bits` | `wire_bits` (with six-bit armor), `wire_seq` and `seqdef` (the sequential layout), `uper` (`encoding uper`) |
| `protobuf` | `wire_protobuf` |
| `text` | `wire_text` |
| `tlv` | `wire_tlv` |
| `cbor` | `wire_cbor` (Version 0.28, ruling 38) |
| `json` and `geojson` both | `jsonio`, the JSON reader and writer they share; `geojson` needs nothing of `wire_json` |
| `bits`, `protobuf`, `tlv` and `cbor` all | `octets`, hex input and the `utf8` and `hex` octet transforms |

Everything else (the pack and module parsers, the transforms, the engine, the
tool) is in every build. A reduced build behaves for a pack on a wire it has
exactly as the full build. A pack whose `wire` is a wire it does not have is
`unknown-wire` at line check 6, with the message
`unknown-wire: wire 'bits' is a wire of the specification that this build does
not have (this build has: xml, geojson, json) at …`; a `wire` value that is no
wire is `unknown-wire: unknown wire 'morse' (known: …)` as before. The
parameters of the `text` transforms (`dec:…`, `dm:…`, `hms:…`) are checked by
line check 7 on every wire, so that check is in every build.

### The reduced-build check

Status: Measured. From the repository root:

```
python3 -I engines/python/reduced-build-check.py
```

It builds the engine with all eight wires and with `xml`, `json` and
`geojson`, then, in a fresh interpreter on the reduced package: checks that
the left-out modules are absent and never imported; loads every model module
and every pack on the three wires; runs every conversion vector whose `from`
and `to` packs are on them, and every load vector whose packs name no other
wire of the specification; loads one pack on `bits` (and one sequential
`bits` pack), `protobuf`, `text`, `tlv` and `cbor`, each of which must be
`unknown-wire` naming the wire and saying this build does not have it; and
compares `model_keys` of every loaded format and the capability report of
every converted pair with the full build. It prints the sizes and exits 1 on
any failure. `--wires <set>` checks another set the same way.

One run on 2026-11-21: 1713 packs loaded; 8374 of the 23610 conversion
vectors run, 8374 passed; 394 load vectors run, 394 passed; the six
`unknown-wire` loads and the load of `wire morse` as specified; `model_keys`
of 1713 formats and the capability report of 192 pairs the same in both
builds. Sizes:

| Build | Wheel | Package source |
|---|---|---|
| all eight wires | 166235 bytes | 588298 bytes, 25 modules |
| `xml`, `json`, `geojson` | 89815 bytes (54%) | 310616 bytes, 16 modules |

## Parse once, and the benchmark

Status: Built (Version 0.25). An `Engine` keeps, for its whole life, every
model module and pack it parsed at load, and the layouts worked out from them:
the scope of each kind and group body (`Plan`), and, the first time a scope
is used, the facts its wire needs (the bits a `bits` scope reaches, the
fields a `text` scope addresses, the tags a `tlv` scope names, where an `xml`
scope writes each locator). A conversion parses nothing it loaded. Each kept
layout is built whole and only then stored, so one engine can be used from
several threads at once and every conversion gives the result of a new engine
(`tests/test_parse_once.py`). A load reads each module and pack file once.

The benchmark (ruling 2), run from the repository root:

```
python3 -I engines/python/bench.py              # bench/set.json
python3 -I engines/python/bench.py <set.json>   # another set
```

It loads the packs the set's vectors name (`from` and `to`) and the modules
they use into one engine, converts each vector's input once and compares it
with `expect` (a difference stops the run, exit status 1, the reason on
standard error), then converts it `iterations` times. Standard output holds one
line `{"vector": …, "iterations": …, "ns_per_op": …}` per vector, then
`{"load": <packs>, "ns": …}`, and nothing else. The numbers belong to one
machine at one time; nothing fails on them.

## Test

Status: Measured. The `python` job of `.github/workflows/conformance.yml` runs,
in `engines/python`:

```
PYTHONPATH=src python -m unittest discover -s tests
```

It loads every pack and model module. One run on 2026-11-21 gave
`Ran 288 tests … OK`.

| Test file | Covers |
|---|---|
| `test_vectors.py` | every conversion vector of every pack (23610, all passed), with its `max_items` and its `model` values read by the grammar of their key's type; every load vector, with `pack` or `packs` (1402, all passed); every capability vector (18, all passed) |
| `test_malformed.py` | the input of every conversion vector cut and changed (139556 damaged inputs from 23607 vectors over 4528 packs, none raised anything but a named error); rulings 35 to 39; on the `cbor` wire (0.28) random bytes, deep nesting through arrays, maps and tags, huge declared lengths, unending indefinite items and hostile residue on encode |
| `test_bits.py`, `test_kinds.py`, `test_rules.py`, `test_groups.py`, `test_seq.py`, `test_rulings08.py`, `test_engine.py` | the bits wire, kinds and the json wire, mapping rules, groups, sequential layouts, rulings 16 to 30 of 0.8, `packs_only`, grammar and residue, the exit status of the tool; the `iso8601_s` transform of Version 0.26 (whole seconds written, milliseconds dropped; valid on `xml`, `geojson`, `json` and `text` only, no parameter, an `int` key only) |
| `test_whenas30.py` | Version 0.30, what `convert` cannot reach: a kind or item kind recorded on the entity skips the implicit term, writes the held value or the first listed value, and is `transform-encode` for a held value its `when` does not match (ruling 25); a 64-bit label with the top bit set decodes negative and encodes back (ruling 7); `when 8 1 as as` is `bad-directive` (ruling 31) |
| `test_lookahead33.py` | Version 0.33, what the vectors do not reach: overlapping windows, a written window overwritten without a check and a standing one leaving held bits (ruling 26); a switch on an `as` key a window binds (ruling 22) and on a field a window wrote; a partial window in the `msb`, `lsb` and `msb-lsb` bit orders |
| `test_licences.py` | Version 0.29: `Engine.from_dir` with each profile on the fixture trees of `packs/conformance/tool-fixtures/licences-*`, a profile not one of the three, and the line forms of ruling 1 (`REUSE.toml`, `.def.license`, `licences.toml`) and the profiles of ruling 2 on temporary trees |
| `test_controlled93.py` | Version 0.93: the forms of ruling 1 (shown public), a controlled pack, module and `core` under a public licence (ruling 2), and the distribution limit of rulings 5 and 6: `public` beside `controlled`, a file changed to `controlled` between its two reads, set before and after, a later direct load and a later load without a profile, an engine already holding a controlled module or pack, and the order of the errors |
| `test_parse_once.py` | Version 0.25, ruling 1: the cases of `bench/set.json` (each input whole, cut and changed, `expect` converted back, decodes) give a new engine's result on an engine that converted the others, and from eight threads at once on one new engine; a load opens each file once |
| `reduced-build-check.py`, run from the repository root as `python3 -I engines/python/reduced-build-check.py` | a build with `xml`, `json` and `geojson` only (Version 0.24; "Builds with fewer wires" above) |
| `tools/tool-vectors.py`, run from the repository root as `python3 -I tools/tool-vectors.py -- engines/python/goat-xf-py.py` | every tool vector of `packs/conformance/tool-vectors` (179, all passed): the command-line contract of Version 0.23 and the licence profiles of Versions 0.29 and 0.93 |

The same job then installs the package with pip, writes a bundle of `cot-xml`
and `geojson` with `tools/goat-pkg bundle`, and checks that `Engine.from_dir`
and `goat-xf-py list-formats` load it.

## Tools that use this engine

- `tools/goat-options` imports this engine from `engines/python/src` and reads
  the packs through `Engine.from_dir` and `Engine.capability` to report what
  carries and what is dropped on each conversion path.
- `tools/goat-pkg bundle --embed python` writes a Python module whose
  `engine()` returns `Engine.from_dir` over the bundled packs, found through
  `importlib.resources`. `tools/goat-pkg` itself does not import the engine.
