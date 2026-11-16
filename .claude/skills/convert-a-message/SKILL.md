---
name: convert-a-message
description: Convert a message between two formats with goat-transformers, from the command line or from a library, and diagnose a conversion that fails or loses a value. Use when asked to convert, translate or transcode a message (CoT, GeoJSON, SAPIENT, MAVLink, NMEA 2000, ADS-B, ASTERIX, Remote ID, UCI and others), to find what carries between two formats, to supply a value the input lacks, or to explain an error such as no-kind, malformed-wire, transform-decode, transform-encode or undeclared-key.
---

# Convert a message

## 1. Build the command-line tool once

```bash
cd engines/rust && cargo build --release && cd ../..
X=engines/rust/target/release/goat-xf
```

`goat-xf` reads a message on standard input and writes the converted message.
A binary format (`bits`, `protobuf` wire) is hex text on both sides.

## 2. Load only the packs you need

A conversion needs its two packs. `--packs-only` names the packs to load from
the packs directory; every command then sees only those formats.

```bash
P="--packs packs --packs-only remote-id,cot-xml,nmea2000"
$X list-formats $P
```

Without `--packs-only` the tool loads every pack of the directory.

## 3. Convert

```bash
echo 122624160b42bf241b6ed1b4b69808ac0870086b53150e0200 | $X convert --from remote-id --to cot-xml $P
# <event version="2.0" type="a-u-X"><point lat="45.539309" lon="-122.966389" hae="110" ce="9999999" le="9999999"/></event>

echo 122624160b42bf241b6ed1b4b69808ac0870086b53150e0200 | $X convert --from remote-id --to nmea2000 $P
# 01f80142bf241b6ed1b4b6
```

The names for `--from` and `--to` are the directory names under `packs/`.
Every pack has example inputs in `packs/<format>/vectors/*.json` (the `input`
member).

## 4. Supply a value the input does not carry

Some targets need a value only the caller knows: the stale time of a CoT
event, the two site codes of an ASTERIX record, a node identifier. Give it as
a model key with `--set`, repeatable:

```bash
$X convert --from canonical-track-v2 --to asterix-cat062 \
   --set cat062.sac=1 --set cat062.sic=7 \
   --packs packs --packs-only canonical-track-v2,asterix-cat062 < track.json
```

A context value never replaces a value the input carries. The key must be
declared by a loaded module (`model/*.def`) and hold the key's type. Each
pack's `pack.md` states which keys the caller supplies.

## 5. Read the capability report before trusting a pair

```bash
$X matrix $P                       # F, P or . for every pair
$X matrix --detail $P | grep -- 'remote-id -> cot-xml'
```

`carries` lists the keys both packs map; `dropped` lists the keys of the source
the target has no field for. `FULL` means every key the source maps has a place
in the target. Derived keys do not appear in the report: the model computes
`course` and `speed_ms` from a velocity vector, and the reverse
(`derive` lines in `model/track.def`), so those can reach the target when the
report does not list them.

For a catalog format one detail line is very long. Always filter it with
`grep`, and cut it (`| cut -c1-400`) before reading.

## 6. Diagnose from the named error

Every failure starts with a name and a colon.

| Error | Meaning | What to do |
|---|---|---|
| `no pack loaded for format` | the name is not among the loaded packs | `list-formats`; add the name to `--packs-only` |
| `no-kind` on decode | no message kind's `when` values match the input | the input is another message type, another version, or has framing the pack leaves out; read "message convention" in `pack.md` |
| `no-kind` on encode: "the entity has the required keys of no kind" | the target needs keys the source did not provide | read the `requires` lines of the target's `pack.def`; supply the missing keys with `--set`, or accept that this pair does not convert |
| `malformed-wire` | the input is not valid for the wire: bad hex, truncated, not XML or JSON | check the bytes; remove transport framing |
| `missing-root` | XML whose root element is not the pack's `root` | the input is a different document type |
| `transform-decode` | a field's value cannot be read by its transform; the message names the key and the place | the input breaks the format, or the pack's transform is wrong for it |
| `transform-encode` | a model value does not fit the target field (out of range, too long, no table entry) | the target cannot represent this value |
| `undeclared-key` with `--set` | no loaded module declares that key | check the spelling against `model/*.def`; load the pack that uses that module |
| `key-type-mismatch` with `--set` | the value cannot be read as the key's type | give a number for an `int` or `float` key |
| `distribution-refused` | the engine was limited with `--max-distribution public` and met a `controlled` file | intended; remove the limit only where controlled formats are allowed |

An error raised while loading (`undeclared-key`, `key-type-mismatch`,
`bad-directive`, `missing-source`) names the pack file: it is a defect in the
pack, not in the message.

## 7. From a library

Python, standard library only:

```python
# PYTHONPATH=engines/python/src
from goat_transformers import Engine

engine = Engine.from_dir("packs", "model", packs_only=["remote-id", "cot-xml"])
out = engine.convert("remote-id", "cot-xml", "122624160b42bf241b6ed1b4b69808ac0870086b53150e0200")
entity = engine.decode("remote-id", "122624160b42bf241b6ed1b4b69808ac0870086b53150e0200")
```

`convert` takes an optional fourth argument, the context. `decode` returns the
model entity; `encode(format, entity)` writes one. The other engines offer the
same operations under their language's conventions; each engine's tests are
the usage examples (`engines/<language>/`). JavaScript and C use the Rust
engine through `bindings/` (`bindings/README.md` has both interfaces).

## 8. When a value is wrong, not missing

Decode the input alone and look at the model. A vector's `model` member shows
the expected keys for a known input. If the model value is right and the
output is wrong, the target pack is the place to look; if the model value is
wrong, the source pack. Check the unit first: every key has one fixed unit
(`spec/shared-model.md`).
