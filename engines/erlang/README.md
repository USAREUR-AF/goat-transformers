# Erlang engine

An independent, clean-room implementation of the gt engine, written from
`spec/` and `packs/` only (OTP stdlib, no rebar3 deps).

## Build and test

```
./build.sh        # erlc -o ebin src/*.erl
./run_tests       # loads ../../model and ../../packs, runs every vector
```

`./run_tests` compiles on first use if `ebin/` is empty, prints every failure as
`FAIL <pack>/<vector>: <why>`, then prints
`vectors: N/N passed` (conversion vectors) and `load vectors: N/N passed`
(`packs/conformance/load-vectors/`), and exits non-zero on any failure.
`./run_tests <packs> [<model>]` runs against other directories; the model
directory defaults to the one beside `<packs>`.

## Engine instance

```
E0 = gt_engine:new(),                               % limit: controlled
E1 = gt_engine:set_max_distribution(E0, public),    % optional
E2 = gt_engine:load_model(E1, ModuleText),          % modules first
E3 = gt_engine:load_pack(E2, PackText),
E  = gt_engine:load_dir(gt_engine:new(), "packs"),  % model/*.def, then packs
```

A refused load raises `error:{load_error, Kind, Message}`; `Kind` is the
specification's error kind as an atom (`'undeclared-key'`, `'duplicate-kind'`,
`'bad-directive'`, `'key-type-mismatch'`) and `Message` begins with the kind
and a colon.

## Conversion (engine-spec Version 0.7)

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
`swap`, `trim`, `optional`), `protobuf`. Pack rules: `const`, `default`, `map`
tables with `via`, one key at several locators, and `group` blocks (common, in
a kind, nested) on every wire: xml sibling elements, json and geojson arrays,
protobuf repeated fields with packed scalars, bits items counted by a locator
or a fixed number. Model integers are 64-bit
two's complement; a model float is always finite.

## Layout

- `src/gt_pack.erl`  — `pack.def` parser (grammar, comment rule, named errors).
- `src/gt_model.erl` — model module parser (`model/<module>.def`), `list` and `derive` lines included.
- `src/gt_derive.erl` — the derivation functions and the derivation pass.
- `src/gt_num.erl`   — number parsing and canonical float text (ruling 3).
- `src/gt_iso.erl`   — ISO 8601 <-> epoch ms (`Z`, `z` or an offset in; `Z` out).
- `src/gt_xml.erl`   — XML reader + canonical writer.
- `src/gt_json.erl`  — JSON reader (member order preserved) and canonical writer.
- `src/gt_bits.erl`  — hex text and bit-range access, both bit orders.
- `src/gt_protobuf.erl` — protobuf wire reader and canonical writer.
- `src/gt_engine.erl`— engine instance and load checks, kind selection, decode /
  encode / complete / convert on every wire, groups and lists, residue,
  typemap, value tables, transforms.
- `src/gt_test.erl`  — conformance runner.
