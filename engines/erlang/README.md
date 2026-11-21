# Erlang engine

An independent, clean-room implementation of the gt engine, written from
`spec/` and `packs/` only (OTP stdlib, no rebar3 deps).

## Build and test

```
./build.sh        # erlc -o ebin src/*.erl (every wire; --wires: below)
./run_tests       # loads ../../model and ../../packs, runs every vector
```

| Test | Command (repository root) | Measured (2026-11-20) |
|---|---|---|
| conversion vectors | `cd engines/erlang && ./run_tests` | 20307/20307 |
| load vectors | same run | 1166/1166 |
| capability vectors | same run | 18/18 |
| malformed inputs | same run | 113331/113331 |
| tool vectors (Version 0.23) | `python3 -I tools/tool-vectors.py -- engines/erlang/goat-xf.sh` | 95/95 |
| reduced build (Version 0.24) | `engines/erlang/reduced_check.sh` | 6849/6849 vectors; every bits, protobuf, text and tlv pack `unknown-wire` (below) |

`./run_tests` compiles on first use if `ebin/` is empty, prints every failure as
`FAIL <pack>/<vector>: <why>`, then prints
`vectors: N/N passed` (conversion vectors), `load vectors: N/N passed`
(`packs/conformance/load-vectors/`, with `pack` or `packs`) and
`capability vectors: N/N passed` (`packs/conformance/capability-vectors/`),
then `malformed inputs: N/N passed`, and exits non-zero on any failure. A
conversion vector's `max_items` sets the limit on list items for that vector,
and a `model` value its grammar refuses (ruling 2c of 0.11) fails the vector.
A vector whose format is not loaded is run, and pins `unknown-format`.
It also loads one pack alone through `gt_engine:load_packs/4` and runs that
pack's vectors on the engine it gives (`named load: ...`). To pick that pack
it lists the vector files once and checks each pack against its own files.
Until 2026-11 it listed every pack's vectors again for each pack (packs x
packs): with 2249 packs and 16231 vectors that one check took about 535 of
the 580 s of a run. It now takes about 6 s and the whole run about 44 s
(`nice -n 10`, one machine, 16 cores). Nothing is sampled: every vector and
every check still runs, so there is no switch for a full run.
The malformed-input check takes the input of the first five conversion vectors
of each pack and of every vector of the packs `conformance-malformed-*`,
`conformance-tlv*`, `conformance-armor*` and `conformance-sixbit*`, cuts
it short at prefixes (every length when the input has at most 16 bytes, else 8
lengths spread evenly) and replaces single bytes (at most 8 positions spread
evenly, each with the next byte of a fixed table), and converts each result as
the vector converts. It then runs fixed cases of rulings 36 to 40 on the
`conformance-malformed-*` packs and `conformance-groups-protobuf`, and fixed
cases of the `tlv` wire on `conformance-tlv` and `conformance-tlv-fixed`, and
fixed cases of six-bit armor (0.14) on `conformance-armor` and
`conformance-armor-seq`. A case passes when `convert` returns bytes or raises
`error:{convert_error, Kind, Message}` with a named `Kind` and a `Message`
beginning with the kind and a colon. The cases are a fixed function of the
vectors, so two runs make the same ones.
`./run_tests <packs> [<model>]` runs against other directories; the model
directory defaults to the one beside `<packs>`.

## Builds with fewer wires (engine-spec Version 0.24)

A build names its set of wires with `build.sh --wires`; with no `--wires`
it has all seven (xml, geojson, json, bits, protobuf, text, tlv) and
compiles every module of `src/`, as before.

```
./build.sh                                   # every wire, into ebin/
./build.sh --wires xml,json,geojson          # only these wires, into ebin/
./build.sh --wires bits --out <dir>          # into <dir> instead of ebin/
```

A wire not named is left out twice over: its modules are not compiled, and
the code of `gt_engine` and `gt_pack` that only it needs is compiled out,
because `build.sh` passes `-Dno_wire_<wire>` to `erlc` for it
(`src/gt_wires.hrl` turns those into `-if` blocks). The modules of each wire:

| Wire | Modules | Also in `gt_engine` |
|---|---|---|
| xml | `gt_xml` | locators, groups, residue, the element writer |
| json | `gt_json` (shared with geojson) | members, residue, the object writer |
| geojson | `gt_json` (shared with json) | Feature reading and writing, and the member and JSON-value reading it shares with json; a geojson build without json compiles out the json object writer, residue and number check |
| bits | `gt_bits`, `gt_seq`, `gt_hex` | fixed layouts, gate blocks, six-bit armor, the bits transforms; the sequential layout and `encoding uper` are in `gt_seq` |
| protobuf | `gt_protobuf`, `gt_hex` | paths, packed lists, the writer tree, the protobuf transforms |
| text | `gt_text` | none (dispatch only) |
| tlv | `gt_tlv`, `gt_hex` | the bits transforms, which a `tlv` value uses |

`gt_engine`, `gt_pack`, `gt_model`, `gt_num`, `gt_derive`, `gt_iso` and
`gt_cli` are in every build. `gt_pack` still reads every directive of the
pack language, but a pack whose `wire` is a wire the build left out stops at
line check 6 (5b of 0.11) with `unknown-wire: <wire>: this build does not
have the <wire> wire`; a `wire` value that is no wire stays
`unknown-wire: <value>`. The conformance runner `gt_test` reads vectors with
`gt_json`, so it is built, and `./run_tests` runs, only when the set holds
json or geojson. For a rebar3 build, `{erl_opts, [{d, no_wire_bits}, ...]}`
compiles the same code out of `gt_engine` and `gt_pack`; rebar3 still
compiles every module of `src/`.

The reduced-build check, from the repository root:

```
engines/erlang/reduced_check.sh
```

It builds the engine with every wire into `engines/erlang/_build/full/ebin`
and with xml, json and geojson into `engines/erlang/_build/reduced/ebin`
(`ebin/` is left alone), and on the reduced build: loads every pack on those
three wires, all must load; runs every conversion vector whose `from` and
`to` packs are on those wires (the wire and format read from the text of
each `pack.def`), all must pass; loads every pack on bits, protobuf, text and
tlv, each must be `unknown-wire` with the wire named and the reason in the
message; loads a pack whose `wire` is `nowire`, which must be `unknown-wire`
without that reason. It then prints the size of both builds, the `.beam`
files `build.sh` writes, and exits non-zero on any failure.

Measured (2026-11-20, one machine, `nice -n 10`):

| Check | Result |
|---|---|
| conversion vectors on xml, json and geojson | 6849/6849 passed |
| packs on bits refused as `unknown-wire` | 1632/1632 |
| packs on protobuf refused as `unknown-wire` | 695/695 |
| packs on text refused as `unknown-wire` | 71/71 |
| packs on tlv refused as `unknown-wire` | 9/9 |
| `wire nowire` | `unknown-wire`, without the reason |
| full build, 7 wires | 344048 bytes, 16 `.beam` files |
| reduced build, xml, json and geojson | 225776 bytes, 10 `.beam` files (65% of full) |

Both sizes count `gt_cli` and the conformance runner `gt_test`, which every
build with json or geojson holds.

## Command-line tool (engine-spec Version 0.23)

`goat-xf.sh` is the tool of the command-line contract. Build once with
`./build.sh`, then start it from anywhere; CI calls it from the repository root
as `engines/erlang/goat-xf.sh`. It runs `erl -noshell -pa <its dir>/ebin -s gt_cli main
-extra <arguments>`, so every argument reaches `src/gt_cli.erl` unread by `erl`.

```
engines/erlang/goat-xf.sh convert --from <format> --to <format> [--set <key>=<value>]... <options>
engines/erlang/goat-xf.sh list-formats <options>
engines/erlang/goat-xf.sh capability --from <format> --to <format> <options>
engines/erlang/goat-xf.sh matrix <options>
engines/erlang/goat-xf.sh help
```

`<options>`, in any order, each at most once: `--packs <dir>` (default
`packs`, relative to the current directory), `--models <dir>` (default the
`--packs` text followed by `/../model`), `--packs-only <name>[,<name>...]`,
`--max-items <n>` (default 100000), `--max-distribution public|controlled`
(default `controlled`). The tool has no options of its own (`--x-...`).

Exit status 0 on success; 1 on a load or call failure, standard error's first
line being the failure's message, which begins with the kind and a colon; 2 on
a usage error, found before anything is loaded. An unreadable `--packs` (a kind
the contract does not give) is reported as `packs-unreadable: ...`.
`convert` reads standard input to its end (hex text for the `bits`, `protobuf`
and `tlv` wires) and writes the result with nothing added; `--set` values form
the context. `list-formats`, `capability` and `matrix` write the tab-separated
lines of the contract. `help`, `-h` and `--help` print the usage.

All modules of `--models` are loaded (core first, each after those it uses),
then the packs: the `--packs-only` names in the order given, or every
directory of `--packs` not beginning with `.` whose `pack.def` is a regular
file, in byte order of name.

## As a dependency

`rebar.config` and `src/goat_transformers.app.src` make the engine the rebar3
application `goat_transformers`; `docs/using.md` has the dependency line. The
build and the tests above do not use rebar3.

## Engine instance

```
E0 = gt_engine:new(),                               % limit: controlled
E1 = gt_engine:set_max_distribution(E0, public),    % optional
E2 = gt_engine:load_model(E1, ModuleText),          % modules first
E3 = gt_engine:load_pack(E2, PackText),
E4 = gt_engine:set_max_items(E3, 1000),             % optional: list items per decode
                                                    % (default 100000, ruling 7 of 0.11)
{Grade, Carried, Dropped} = gt_engine:capability(E4, From, To),   % ruling 6 of 0.11
E  = gt_engine:load_dir(gt_engine:new(), "packs"),  % model/*.def (core first, each
                                                    % module after those it uses), then packs
E  = gt_engine:load_packs(gt_engine:new(), "packs", % only the packs named, and only the
                          [<<"cot-xml">>, <<"geojson">>]),   % modules they need
```

`load_packs(Engine, PacksDir, Names)` reads `PacksDir/<name>/pack.def` for each
name (a binary or a string), in the order given, and loads before them `core`,
the modules of their `uses` lines and the modules those use, each once and
after the modules it uses. A module the engine already holds is not loaded
again, so the call can be repeated to add packs. `load_packs/4` and
`load_dir/3` take the model directory as a last argument; it defaults to
`PacksDir/../model`. A name with no `pack.def` raises a load error of kind
`'unknown-format'`, a module with no file `'unknown-module'`.

A refused load raises `error:{load_error, Kind, Message}`; `Kind` is the
specification's error kind as an atom (`'undeclared-key'`, `'duplicate-kind'`,
`'bad-directive'`, `'key-type-mismatch'`) and `Message` begins with the kind
and a colon. Every kind of ruling 5 of 0.11 is raised (`unknown-directive`,
`unknown-transform`, `unknown-wire`, `bad-locator`, `missing-format`,
`missing-version`, `missing-wire`, `missing-module`, `missing-root`,
`unterminated-quote`, `duplicate-format`), each line checked in the order of
ruling 5b and every other cause after the file is read. A module is checked
in the order of ruling 29 of 0.8:
`missing-distribution`, `missing-source`, `distribution-refused`,
`unknown-module`, `distribution-violation`, the `derive` checks,
`duplicate-module`.

## Conversion (engine-spec Version 0.8)

```
Out    = gt_engine:convert(E, <<"cot-xml">>, <<"geojson">>, Bytes),
Out2   = gt_engine:convert(E, From, To, Bytes, #{<<"stale_ms">> => <<"1614456180250">>}),
Entity = gt_engine:decode(E, <<"cot-xml">>, Bytes),   % binary in
Full   = gt_engine:complete(E, Entity, Context),      % context keys, then derivations
Bytes2 = gt_engine:encode(E, <<"cot-xml">>, Full),    % binary out
Keys   = gt_engine:model_keys(gt_engine:pack(E, <<"cot-xml">>)),
```

`convert` takes format names: it decodes, clears the kind unless both names are
equal, fills absent keys from the context, applies the `derive` lines of the
loaded modules, and encodes. With equal names and no context the middle two
steps are skipped. The context is a map or a list of `{Key, Value}`, values in
string form; `none` (or `convert/4`) means no context.

`Entity` is `#{model, lists, residue, src, kind}`: model keys are binaries
(`<<"track.confidence">>`), string values binaries, `kind` is `undefined` or
`{FormatName, KindName}`. `lists` maps a list name to its items
(`#{<<"track.identifiers">> => [Item]}`); an item is `#{model, lists}`, with
keys and nested lists as an entity has them and no residue or kind. A list
that is present and empty is `[]`; an absent list has no entry. `model_keys`
names a list `<list>[]` and an item key `<list>[].<key>`. A failed conversion
raises `error:{convert_error, Kind, Message}` with `Kind` one of `'no-kind'`,
`'missing-root'`, `'malformed-wire'`, `'transform-decode'`, `'transform-encode'`,
`'undeclared-key'`, `'key-type-mismatch'` (the last two for a context key) and
`Message` beginning with the kind and a colon. Wires: `xml` (a root per kind),
`geojson`, `json`, `bits` (`bit_order lsb | msb`, fields past their word,
`swap`, `trim`, `optional`), `protobuf`, `text` (Version 0.10: `delimiter`,
`start`, `checksum none | nmea`; input and output are the record's text, never
trimmed; residue is keyed by field index; the `absent` field option of
Version 0.9 is `bad-directive` on it, ruling 16 of 0.10), `tlv` (Version 0.13: `tag`,
`length`, `key`, `checksum sum16`; hex text in and out; residue is
`{[Tag], Hex}`, every occurrence of an unnamed tag).

Malformed input (engine-spec "Malformed input (0.8)", rulings 35 to 40): no
input makes `decode` or `convert` raise anything but `convert_error`. The
readers raise their own tagged errors (`{xml_malformed, Why}`,
`{json_malformed, Why}`, `{hex_malformed, Why}`, `{protobuf_malformed, Why}`)
and `decode` reports each as `'malformed-wire'`. xml elements and json or
geojson arrays and objects nest at most 64 deep. The json reader follows the
RFC 8259 grammar for numbers, escapes and control characters. Hex text holds
hex digits and whitespace (space, tab, CR, LF) only, an even number of digits.
A protobuf message is checked whole: varints of at most ten bytes with a
tenth byte of 0 or 1, in a packed field too, lengths and fixed-width values
inside their message, wire types 0, 1, 2 and 5 only, field numbers 1 to
2^29-1. An xml input with a document type declaration anywhere is refused;
the only entities are the five predefined ones and numeric character
references of decimal or hexadecimal digits that name a character XML 1.0
allows. A json `\u` escape that is half of a surrogate pair is refused. A failure no reader or writer names is still a
`convert_error` (`'malformed-wire'` from `decode`, `'transform-encode'` after
it) whose message holds `[unclassified:`; the conformance runner fails a case
that produces one. No atom is made from input.

Pack rules: `const`, `default`, `map`
tables with `via`, one key at several locators, and `group` blocks (common, in
a kind, nested) on every wire: xml sibling elements, json and geojson arrays,
protobuf repeated fields with packed scalars, bits items counted by a locator
or a fixed number. Model integers are 64-bit
two's complement; a model float is always finite.

A `bits` pack with `layout sequential` (Version 0.8) is read and written at a
cursor: `field`, `const`, `pad`, `align` and `when` by bit length; `also`
keys on a field; `presence <name> <n> | fx` with `if` blocks and `!` bits;
`opt`; groups `count`, `while`, `more` and `fx`; `chain` with `fx` lines;
`length` blocks and `length ... whole`; items by kind. An item of a group
whose body holds kinds also has `kind => {FormatName, KindName}`. A model
module may hold `uses` lines, and `derive` has the functions `day_seconds`,
`any`, `not`, `parse_int` and `text_of`. Rulings 16 to 34 of 0.8 are
implemented as the specification states them.

## Layout

- `src/gt_pack.erl`  — `pack.def` parser (grammar, comment rule, named errors).
- `src/gt_model.erl` — model module parser (`model/<module>.def`), `list` and `derive` lines included.
- `src/gt_derive.erl` — the derivation functions and the derivation pass.
- `src/gt_num.erl`   — number parsing and canonical float text (ruling 3).
- `src/gt_iso.erl`   — ISO 8601 <-> epoch ms (`Z`, `z` or an offset in; `Z` out).
- `src/gt_xml.erl`   — XML reader + canonical writer.
- `src/gt_json.erl`  — JSON reader (member order preserved) and canonical writer.
- `src/gt_bits.erl`  — bit-range access, both bit orders, and six-bit armor.
- `src/gt_hex.erl`   — hex text, the input and output of bits, protobuf and tlv.
- `src/gt_wires.hrl` — the wires of a build (Version 0.24): `-Dno_wire_<wire>` to `?W_<WIRE>`.
- `src/gt_protobuf.erl` — protobuf wire reader and canonical writer.
- `src/gt_seq.erl`   — decode and encode of a `layout sequential` pack.
- `src/gt_text.erl`  — the `text` wire (Version 0.10): reading a record (terminator,
  printable check, start, `nmea` checksum, split), field, column and pair locators,
  the `int:<w>`, `dec`, `dm`, `hms` and `hms_dmy` transforms, residue by field
  index, groups of `item <n>` fields, and writing a record (padding, trailing
  `optional` fields, checksum).
- `src/gt_tlv.erl`   — the `tlv` wire (Version 0.13): the key and the set's length,
  BER-OID or fixed tags, BER or fixed lengths, the `sum16` checksum, kinds on
  the top set, nested sets read when a line walks into them, the integer, scale,
  float, `utf8` and `hex` transforms, residue, and writing each set in line
  order with its residue after.
- `src/gt_engine.erl`— engine instance and load checks, kind selection, decode /
  encode / complete / convert on every wire, groups and lists, residue,
  typemap, value tables, transforms.
- `src/gt_test.erl`  — conformance runner and the malformed-input check.
- `src/gt_cli.erl`   — the command-line tool (Version 0.23), started by `goat-xf.sh`.
