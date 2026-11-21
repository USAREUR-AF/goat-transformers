# Erlang engine

An independent, clean-room implementation of the gt engine, written from
`spec/` and `packs/` only (OTP stdlib, no rebar3 deps).

## Build and test

```
./build.sh        # erlc -o ebin src/*.erl (every wire; --wires: below)
./run_tests       # loads ../../model and ../../packs, runs every vector
```

| Test | Command (repository root) | Measured (2026-11-21) |
|---|---|---|
| conversion vectors | `cd engines/erlang && ./run_tests` | 23610/23610 |
| load vectors | same run | 1402/1402 |
| capability vectors | same run | 18/18 |
| malformed inputs | same run | 154133/154133 |
| concurrent conversions (Version 0.25) | same run | 521/521 |
| benchmark (Version 0.25) | `engines/erlang/bench.sh` | 16 vectors, 16 packs (below) |
| tool vectors (Versions 0.23, 0.29) | `python3 -I tools/tool-vectors.py -- engines/erlang/goat-xf.sh` | 135/135 |
| reduced build (Version 0.24) | `engines/erlang/reduced_check.sh` | 8374/8374 vectors; every bits, protobuf, text, tlv and cbor pack `unknown-wire` (below) |

`./run_tests` compiles on first use if `ebin/` is empty, prints every failure as
`FAIL <pack>/<vector>: <why>`, then prints
`vectors: N/N passed` (conversion vectors), `load vectors: N/N passed`
(`packs/conformance/load-vectors/`, with `pack` or `packs`) and
`capability vectors: N/N passed` (`packs/conformance/capability-vectors/`),
then `malformed inputs: N/N passed`, then `concurrent conversions: N/N
passed` (below), and exits non-zero on any failure. A
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
`conformance-tlv*`, `conformance-armor*`, `conformance-sixbit*`,
`conformance-uper*` and `conformance-cbor*`, cuts
it short at prefixes (every length when the input has at most 16 bytes, else 8
lengths spread evenly) and replaces single bytes (at most 8 positions spread
evenly, each with the next byte of a fixed table), and converts each result as
the vector converts. It then runs fixed cases of rulings 36 to 40 on the
`conformance-malformed-*` packs and `conformance-groups-protobuf`, and fixed
cases of the `tlv` wire on `conformance-tlv` and `conformance-tlv-fixed`, and
fixed cases of six-bit armor (0.14) on `conformance-armor` and
`conformance-armor-seq`, and fixed cases of hostile CBOR (0.28) on
`conformance-cbor` and `conformance-cbor-array`: nesting through arrays, maps
and tags far past the depth limit of 64, declared lengths up to 2^64-1 with
no bytes behind them, indefinite items with no break, misplaced chunks and
breaks, invalid UTF-8 and equal keys. A case passes when `convert` returns bytes or raises
`error:{convert_error, Kind, Message}` with a named `Kind` and a `Message`
beginning with the kind and a colon. The cases are a fixed function of the
vectors, so two runs make the same ones.
The concurrent check (rulings 1b and 1c of 0.25) takes the first two
conversion vectors of each `conformance-*` pack, those that convert and those
that fail, loads the packs they name into one instance and keeps it in a
`persistent_term`, so that every process reads the same instance without a
copy. Each case is converted alone in a new process for its reference
result; then four processes, started together, each convert every case on
that instance, each in its own order (the list rotated), so that every
conversion comes after conversions of other messages, failed ones included,
while the other processes convert. A case passes when all four give the
reference result: the same bytes, or the same error kind and message.
`./run_tests <packs> [<model>]` runs against other directories; the model
directory defaults to the one beside `<packs>`.

## Parse once, and the benchmark (engine-spec Version 0.25)

An engine instance is an immutable map (`gt_engine:new/0` and the loaders
return a new one), so what a load computes stays with the instance for its
life and no conversion can change it. Kept since load (ruling 1a):

| Kept | Where |
|---|---|
| every model module, parsed | `modules` of the instance (`gt_model:parse/1` once per module) |
| every pack, parsed and checked | `packs` of the instance (`gt_pack:parse/1` once per pack) |
| the kinds by name, and (xml) by root element | `kind_index`, `root_index` of the pack |
| each kind's scope: the common lines, then the kind's | `scope` of the kind |
| the plan of each scope (`gt_engine:scope_plan/2`) | `plan` of the kind; `plan` of the pack without kinds |
| the plan of each `group` body (xml, json, geojson) | `plan` of the body |

A plan is what a wire computes from the lines of a scope alone: on xml,
json and geojson the locators the lines map (residue on decode) and the
values `const` and valued `when` lines fix (encode); on xml also where
`element` lines make elements; on tlv the nested sets the lines walk into,
the places they name (residue), the order of each set's items and the lines
of each item (encode, `gt_tlv:plan/1`). The bits, protobuf and text wires
read their lines as they are; no plan is kept for them. The writer's check
for characters XML cannot hold uses a pattern compiled once per node
(`persistent_term`), which depends on nothing loaded.

Nothing observable changes (1b). The instance holds no state a conversion
writes; a decode keeps its item count and first field failure in the
process dictionary and erases them when it ends, failed or not, and the
sequential encoder erases its own entry the same way. An instance can be
used from any number of processes at once (1c): it is one term, read and
never written; a caller that wants the processes to share it without a copy
keeps it in a `persistent_term`, as the concurrent check of `./run_tests`
does.

Loading reads each file once (1d): `gt_engine:model_texts/1` reads every
module file of a directory once and gives the module order (core first, each
module after those it uses) with the texts; `load_dir/3`, `load_packs/4`,
the command-line tool and the conformance runner load those texts.
`load_packs/4` reads each named `pack.def` once and takes the `uses` lines
from that text. A second load of the same directory into the same instance
is `duplicate-module` (or `duplicate-format`), as before.

The benchmark (ruling 2), from the repository root:

```
engines/erlang/bench.sh                     # bench/set.json
engines/erlang/bench.sh <set.json>          # another set
```

It builds the engine first if `ebin/` is empty (the build's own lines go to
standard error) and runs `src/gt_bench.erl`. The repository root is the
directory above the set's directory, so it can be started from anywhere.
It loads into one new instance, with `gt_engine:load_packs/4`, the packs the
set's vectors name (their `from` and `to` formats, in order of first
appearance, each from `packs/<format>/pack.def`) and the modules those use,
and times that load; then for each vector, in order, it converts the
vector's input (with its `context`, if any) once, compares the output with
`expect` byte for byte, then converts it `iterations` times and times that.
Standard output holds only the lines of ruling 2c; a vector whose output
differs stops the run with a message on standard error and exit status 1.

Measured (2026-11-21, one machine, 16 cores, `nice -n 10`, under a load
average of 15 to 30 from other work: the numbers are informative only,
ruling 2d). Before is the engine of 0.24 with the same `gt_bench.erl`, run
alternately with the 0.25 engine; each figure is the lower of two runs.

| Vector | 0.24, ns per conversion | 0.25, ns per conversion |
|---|---|---|
| `packs/cot-xml/vectors/01-track-to-geojson.json` | 432689 | 255890 |
| `packs/geojson/vectors/01-geojson-to-cot.json` | 600138 | 349273 |
| `packs/canonical-track-v2/vectors/02-to-cot-xml.json` | 822873 | 511801 |
| `packs/sapient/vectors/01-sapient-to-geojson.json` | 202952 | 158294 |
| `packs/cot-protobuf/vectors/01-event-to-cot-xml.json` | 657561 | 351052 |
| `packs/isa/vectors/01-isa-to-geojson.json` | 559124 | 452137 |
| `packs/uci/vectors/gen-001-access_assessment-roundtrip.json` | 5379023 | 3052401 |
| `packs/a-gra/vectors/gen-001-access_assessment-roundtrip.json` | 4508492 | 2582278 |
| `packs/nmea2000/vectors/rt-pgn59392.json` | 6744 | 21903 |
| `packs/mavlink2/vectors/rt-00000-heartbeat.json` | 58754 | 53978 |
| `packs/asterix-cat062/vectors/12-to-canonical-track-v2-with-context.json` | 342312 | 414872 |
| `packs/remote-id/vectors/09-basic-id-upstream-test-bytes-to-geojson.json` | 66509 | 52537 |
| `packs/adsb/vectors/01-identification-tc1-roundtrip.json` | 86789 | 73496 |
| `packs/nmea0183/vectors/40-rmc-to-geojson.json` | 156050 | 131761 |
| `packs/dhcpv6-options/vectors/01-solicit-options-round-trip.json` | 1233570 | 129159 |
| load of the 15 packs and their modules | 13.8 s | 10.1 s |
| load of every pack (`load_dir/3`, 3946 packs, 2624 modules) | 67.3 s | 58.1 s |

The 0.25 changes do not touch the bits wire: the nmea2000, mavlink2,
asterix-cat062, remote-id and adsb rows differ by the noise of the machine
(nmea2000 measured 6744 and 24546 ns before, 21903 and 59464 after). The
xml writer's compiled pattern accounts for most of the gain on xml output,
the kept plans for the rest, and the tlv plan for dhcpv6-options. The
load is faster because each module file is read and scanned for its head
once instead of three times.

## Builds with fewer wires (engine-spec Version 0.24)

A build names its set of wires with `build.sh --wires`; with no `--wires`
it has all eight (xml, geojson, json, bits, protobuf, text, tlv, and cbor
of Version 0.28, ruling 38) and compiles every module of `src/`, as before.
`cbor` is named like the others: `--wires ...,cbor` keeps it, and a list
without it compiles `gt_cbor` out and passes `-Dno_wire_cbor`.

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
| cbor | `gt_cbor`, `gt_hex` | none (dispatch and hex input only) |

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
each `pack.def`), all must pass; loads every pack on bits, protobuf, text,
tlv and cbor, each must be `unknown-wire` with the wire named and the reason in the
message; loads a pack whose `wire` is `nowire`, which must be `unknown-wire`
without that reason. It then prints the size of both builds, the `.beam`
files `build.sh` writes, and exits non-zero on any failure.

Measured (2026-11-21, one machine):

| Check | Result |
|---|---|
| conversion vectors on xml, json and geojson | 8374/8374 passed |
| packs on bits refused as `unknown-wire` | 1835/1835 |
| packs on protobuf refused as `unknown-wire` | 876/876 |
| packs on text refused as `unknown-wire` | 86/86 |
| packs on tlv refused as `unknown-wire` | 11/11 |
| packs on cbor refused as `unknown-wire` | 7/7 |
| `wire nowire` | `unknown-wire`, without the reason |
| full build, 8 wires | 419392 bytes, 19 `.beam` files |
| reduced build, xml, json and geojson | 263048 bytes, 12 `.beam` files (62% of full) |

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
engines/erlang/goat-xf.sh licences [--json] <options>
engines/erlang/goat-xf.sh help
```

`<options>`, in any order, each at most once: `--packs <dir>` (default
`packs`, relative to the current directory), `--models <dir>` (default the
`--packs` text followed by `/../model`), `--packs-only <name>[,<name>...]`,
`--max-items <n>` (default 100000), `--max-distribution public|controlled`
(default `controlled`), `--profile open|open+copyleft|everything` (default
none; Version 0.29, below). `licences` also takes `--json`, the one option
without a value. The tool has no options of its own (`--x-...`).

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

## Licence profiles (engine-spec Version 0.29)

`src/gt_licence.erl` reads, by the exact line forms of ruling 1 and with no
TOML library, `licences.toml` (the `--packs` text followed by
`/../licences.toml`), each module's `<models>/<file>.def.license` and each
pack's `<packs>/<dir>/REUSE.toml`, and computes the profile of every licence,
module and pack (ruling 2). A missing file is `Apache-2.0` (or the one-row
default table); any other failure is a load failure of kind `bad-licence`.

With `--profile`, the table and every module file's licence, `module` and
`uses` lines are read before any module is loaded (core.def first, then byte
order of file name); a module or pack the profile does not hold is skipped as
if it were not there. A pack's licence and `uses` lines are read when it is
reached, after the `--packs-only` name checks, so a skipped pack is never
parsed. Without `--profile` no licence file is read and loading is unchanged,
except for `licences`, which always reads them.

`licences` writes one line per loaded pack in byte order of directory name:
directory, format, licence and the pack's own profile (`none` for a pack in
no profile), tab-separated; with `--json`, `{"packs":[...]}` on one line.
A `--profile` value other than the three names is usage error 11 (exit 2).

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
E  = gt_engine:load_dir(gt_engine:new(), "packs", "model", open),   % with a profile
E  = gt_engine:load_packs(gt_engine:new(), "packs", Names, "model", <<"open+copyleft">>),
```

`load_dir/4` and `load_packs/5` take a licence profile as a last argument
(Version 0.29): `none` loads as `load_dir/3` and `load_packs/4` do and reads
no licence file; `open`, `open+copyleft` or `everything` (atom, string or
binary) loads only the modules and packs that profile holds, the table read
from `PacksDir ++ "/../licences.toml"`. Any other value raises
`'bad-licence'` before anything is read, as does a licence file that cannot
be read by the forms of ruling 1.

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
`length`, `key`, `checksum sum16` and `checksum crc32` (0.27); hex text in and out; residue is
`{[Tag], Hex}`, every occurrence of an unnamed tag), `cbor` (Version 0.28:
one RFC 8949 data item, `tag <n>`, integer, text and `[i]` path steps, groups
over arrays; hex text in and out; residue is `{Path, Bytes}`, each unmapped
item as it stood, written back with the core deterministic encoding).

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
- `src/gt_iso.erl`   — ISO 8601 <-> epoch ms (`Z`, `z` or an offset in; `Z` out), for
  `iso8601_ms`, `iso8601_short` (0.18) and `iso8601_s` (0.26, whole seconds out, the
  milliseconds dropped).
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
  BER-OID or fixed tags, BER or fixed lengths, the `sum16` and `crc32` (0.27) checksums, kinds on
  the top set, nested sets read when a line walks into them, the integer, scale,
  float, `utf8` and `hex` transforms, residue, and writing each set in line
  order with its residue after.
- `src/gt_cbor.erl`  — the `cbor` wire (Version 0.28): path, `when`/`const` value
  and `tag` forms and the checks after the file; a CBOR reader (well-formedness,
  depth 64, lengths checked before anything is taken, UTF-8 per chunk, equal
  keys) and the core deterministic writer; kinds, the type checks of Reading
  step 8, the seven transforms, groups over arrays, residue, and writing with
  the gaps of ruling 23.
- `src/gt_engine.erl`— engine instance and load checks, kind selection, decode /
  encode / complete / convert on every wire, groups and lists, residue,
  typemap, value tables, transforms.
- `src/gt_test.erl`  — conformance runner and the malformed-input check.
- `src/gt_licence.erl` — licence files, profiles and the skipping of modules and packs (Version 0.29).
- `src/gt_cli.erl`   — the command-line tool (Version 0.23, `--profile` and `licences` of 0.29), started by `goat-xf.sh`.
- `src/gt_bench.erl` — the benchmark (Version 0.25), started by `bench.sh`.
