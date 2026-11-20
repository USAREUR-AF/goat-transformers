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
| `Engine.from_dir(packs_dir, models_dir=None, max_distribution="controlled", packs_only=None)` | loads every `<models_dir>/*.def` (default: `model` beside `packs_dir`), then every `<packs_dir>/<format>/pack.def`; with `packs_only`, only the named packs and the modules they use |
| `Engine(max_distribution=..., max_items=100000)`, `load_model(text, source=...)`, `load(text, source=...)` | an empty engine; load one model module, then one pack, from text. A second pack with a loaded `format` name is `duplicate-format`, and the first stays loaded |
| `set_max_items(n)` | the limit on list items one decode holds, over every list at every level (ruling 7 of 0.11); 0 or more, 100,000 by default. Going over it is `malformed-wire`; `encode` is not limited |
| `formats()`, `pack(fmt)`, `model_keys(fmt)` | the loaded format names; one parsed pack; the keys a pack maps |
| `decode(fmt, data, max_items=None)` | message to `Entity` (`fields`, `lists`, `residue`, `kind`); `max_items` sets the limit for this call |
| `encode(fmt, entity)` | `Entity` to message |
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
| `TransformDecodeFailure`, `TransformEncodeFailure` | `transform-decode` (with `entity`, the fields that decoded, and `absent`), `transform-encode` |
| `DuplicateField` | `duplicate-field`; withdrawn in version 0.6, kept as a name, not raised |

Also exported: `Entity`, `Item`, `Pack`, `load_pack`, `parse_pack_text`, `Key`,
`Module`, `Derive`, `load_model_file`, `parse_model_text`.

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
| `help`, `-h`, `--help` | the usage, on standard output |

| Option | Of | Means |
|---|---|---|
| `--packs <dir>` | all four | the packs directory (default `$GT_PACKS`, else `packs`) |
| `--models <dir>` | all four | the model module directory (default: the `--packs` text followed by `/../model`); every `*.def` in it is loaded |
| `--packs-only <name>[,<name>...]` | all four | load only these subdirectories of `--packs`, in the order given |
| `--max-items <n>` | all four | the limit on list items one decode holds (default 100000) |
| `--max-distribution public\|controlled` | all four | refuse modules and packs above this distribution (default `controlled`) |
| `--set <key>=<value>` | `convert` | a caller-supplied model key, read as the key's declared type; repeatable |
| `--from`, `--to` | `convert`, `capability` | the source and target formats |

Every option takes its value as the next argument; `--opt=value`, an
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

## Test

Status: Measured. The `python` job of `.github/workflows/conformance.yml` runs,
in `engines/python`:

```
PYTHONPATH=src python -m unittest discover -s tests
```

It loads every pack and model module. One run on 2026-11-20 gave
`Ran 242 tests … FAILED (failures=1)`: the one failure is the conversion
vector `usgs-earthquake/vectors/04-event-to-cot-xml.json` (the engine writes
an empty `<detail/>` the vector does not hold), which fails in the library and
not in the tool.

| Test file | Covers |
|---|---|
| `test_vectors.py` | every conversion vector of every pack (17628 of 2687 packs, 17627 passed), with its `max_items` and its `model` values read by the grammar of their key's type; every load vector, with `pack` or `packs` (862, all passed); every capability vector (18, all passed) |
| `test_malformed.py` | the input of every conversion vector cut and changed (103161 damaged inputs, none raised anything but a named error); rulings 35 to 39 |
| `test_bits.py`, `test_kinds.py`, `test_rules.py`, `test_groups.py`, `test_seq.py`, `test_rulings08.py`, `test_engine.py` | the bits wire, kinds and the json wire, mapping rules, groups, sequential layouts, rulings 16 to 30 of 0.8, `packs_only`, grammar and residue, the exit status of the tool |
| `tools/tool-vectors.py`, run from the repository root as `python3 -I tools/tool-vectors.py -- engines/python/goat-xf-py.py` | every tool vector of `packs/conformance/tool-vectors` (97, all passed): the command-line contract of Version 0.23 |

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
