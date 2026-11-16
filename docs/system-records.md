# System records and the options query

Status: Written. The record format, the site file, the store loader and the
query (`tools/goat-options`) are Built. Synchronizing stores between
organizations is Not built.

The library already knows which formats convert to which and what carries
(`goat-xf matrix --detail`). It knows nothing about systems: which sensor or
application emits or accepts which format, over which transport, in which
version. A **system record** states that, one plain-text file per system. Given
a system that produces data and a system that needs it, `tools/goat-options`
lists every way the data can get from one to the other, with the status and
evidence of each step. It lists options. It does not rank them or name a
preferred one.

## Who uses it and for what

A person planning coverage asks "which of these sensors can feed that
consumer, and how". A program asks the same question and draws its own picture
of the answer. The query answers both from the same JSON; `--table` prints it
for a person.

The answer has three kinds of option, by status:

| Status | Means for a claim in a record | Means for a library conversion |
|---|---|---|
| `proven` | run against the real system; `evidence=` says where that is recorded | a record states it was run on real data (`converts ... via=goat-transformers status=proven`) |
| `available` | in hand now (fielded version, interface document held), not yet run against the real system | both packs are loaded and the pair shares model keys; this is the default |
| `forthcoming` | announced by the system's owner for a version not yet in hand | |
| `unknown` | nobody has said | |

## Three parts

| Part | What it is | Where |
|---|---|---|
| A record | one `.rec` file per system: what it emits, accepts or converts, and the status of each claim | a store: any directory of `.rec` files |
| The query | every path between two systems or formats, from the records and the packs | `tools/goat-options` |
| A site file | one `.site` file: what is on hand at one site, and which consumers it intends to feed | at the site; it never leaves unless its owner sends it |

### A record

A record is a list of lines, one statement per line. It uses the tokenizer of
`pack.def` (`spec/engine-spec.md`): whitespace separates tokens, double quotes
group a token, `#` at the start of a token begins a comment. A claim line names
one or two formats and then `name=value` attributes.

This is `examples/stores/sketch/radar-1.rec`, complete:

```
record   1
system   example/radar-1
name     "Example radar 1 (fictional)"
kind     sensor
by       example-org
date     2026-11-16
note     "A short-range radar on a sensor node. Publishes plots and tracks only."

emits    asterix-cat048  transport=zenoh  version=1.x  status=proven     evidence="example: fictional trial log 01"
emits    asterix-cat062  transport=zenoh  version=2.0  status=forthcoming note="announced by its maker for version 2.0"
```

| Keyword | Value | Use |
|---|---|---|
| `record` | `1` | the version of this record format |
| `system` | the system's identifier, `<maker>/<system>` | the key records merge on. Required; a file without it is reported and not used |
| `name`, `kind`, `by`, `date` | text | `kind` is free text: `sensor`, `edge consumer`, `application`, `translator`, anything. `by` is who wrote the record |
| `note` | text | repeatable |
| `emits <format>` | | the system publishes this format |
| `accepts <format>` | | the system subscribes to or reads this format |
| `speaks <format>` | | the system uses this format and the source does not say in which direction; the query treats it as both and marks every path that rests on it `direction: unstated` |
| `converts <from> <to>` | | the system turns one format into the other. With `via=<converter>`, the record states that another converter did it on this system's data; `via=goat-transformers` names the library |

A format is a pack name (`sapient`, `cot-xml`) where a pack exists, and any
other name where none does (`"example rf-1 json"`). Names match without regard
to case. A name with no pack takes part in direct paths and in `converts`
claims; the library cannot convert it.

Claim attributes: `status` (above), `evidence` (a pointer: a document number, a
path in the owner's store, a URL), `version` (the version of the system the
claim applies to), `transport` (`zenoh`, `udp`, a bus, a serial line), `note`.

**Nothing unknown is refused.** A keyword the tool does not read, an attribute
it does not read and a status outside the four are kept in the output and
listed by `check`. A status outside the four counts as `unknown` in a path's
status. The only line that is not used is one that cannot be tokenized (an
unclosed quote).

### The query

`goat-options paths` takes a source and a consumer, each a system identifier or
a format name, and lists every path with up to two conversions
(`--max-conversions`):

| Path | From the formats the source emits to the formats the consumer accepts |
|---|---|
| direct | the same format at both ends |
| one conversion | a library conversion between two formats, or a `converts` claim of a system |
| two conversions | two steps, at most one of them the library's |

Two library conversions in a row are not listed: the library converts any
loaded format to any other in one step through its model, so that pair is
already listed as one step. No format repeats within a path.

For a library step, what carries and what is lost is the library's capability
report for that pair (`Engine.capability` in the Python engine; it agrees with
`goat-xf matrix --detail` on every pair the two were compared on). For a path
of library steps the tool gives the keys that carry end to end. For a step made
by a system, the record says nothing about keys, so `carried` and `lost` are
`null`. A catalog format's own module (for example `isa.*`) has keys no other
family maps, so they appear as lost when converting to another family.

Each path has a status: the least established status among its steps,
including the source's `emits` claim and the consumer's `accepts` claim. It
describes that one path's evidence. Paths are not compared with each other;
they are listed by number of conversions and then by name, so the output is
stable. When several records make the same claim, the step's status is the most
established of them, and every claim is listed with the store, file, line and
author it came from.

```
tools/goat-options paths --store examples/stores/sketch \
    --from example/rf-1 --to example/c2-app --table
```

```
example/rf-1 -> example/c2-app
  conv  status     route                                                                                                       keys        on hand
  2     proven     example rf-1 json --[example/node-translator]--> canonical-track-v2 --[example/node-translator]--> cot-xml  not stated
  2     available  example rf-1 json --[example/node-translator]--> canonical-track-v2 --[goat-transformers]--> cot-xml        not stated
  2     available  example rf-1 json --[example/node-translator]--> canonical-track-v2 --[example/node-translator]--> sapient  not stated
  2     available  example rf-1 json --[example/node-translator]--> canonical-track-v2 --[goat-transformers]--> sapient        not stated
```

The same query without `--table` prints JSON. One path, shortened:

```json
{
 "conversions": 2,
 "formats": ["example rf-1 json", "canonical-track-v2", "cot-xml"],
 "status": "proven",
 "from": {"system": "example/rf-1", "format": "example rf-1 json",
          "claim": {"claim": "emits", "status": "proven", "version": "1.4", "transport": "udp",
                    "evidence": "example: fictional bench capture 07",
                    "source": {"store": "examples/stores/sketch", "file": "rf-1.rec", "by": "example-org", "line": 9}}},
 "steps": [
  {"from": "example rf-1 json", "to": "canonical-track-v2", "via": "example/node-translator",
   "status": "proven", "claims": ["..."], "grade": null, "carried": null, "lost": null},
  {"from": "canonical-track-v2", "to": "cot-xml", "via": "example/node-translator",
   "status": "proven", "claims": ["..."], "grade": null, "carried": null, "lost": null}
 ],
 "to": {"system": "example/c2-app", "format": "cot-xml", "claim": {"...": "..."}},
 "carried": null,
 "lost": null
}
```

A library step carries the report itself, for example
`{"via": "goat-transformers", "status": "available", "grade": "partial",
"carried": ["uid", "type", "time_ms", ...], "lost": ["..."]}`. `--keys count`
replaces each key list with its length.

Other commands:

| Command | Prints |
|---|---|
| `goat-options systems --store DIR` | the merged records, each claim with its provenance and whether a pack exists for its format |
| `goat-options site --store DIR FILE.site` | every path for every `feed` line of a site file, each part marked on hand or not |
| `goat-options summary --store DIR` | counts only: systems, producers, consumers, formats, and producer and consumer pairs by the most established status any of their paths has |
| `goat-options check --store DIR [--strict]` | everything the reader could not use or had to read as `unknown`; `--strict` exits 1 on a warning |

All commands take `--packs` and `--models` (default: this repository's), so the
query runs against an assembled overlay tree and sees the overlay's packs.
`--max-distribution public` loads no controlled pack.

### The site file

A site file says what is on hand at one site and what the site intends to feed.
`examples/sites/forward.site`:

```
record   1
site     example-forward-site
by       example-org
date     2026-11-16

have     example/radar-1
have     example/rf-1
have     example/camera-1
have     example/edge-display
have     example/c2-app
have     example/node-translator
have     goat-transformers

feed     example/edge-display
feed     example/c2-app        from=example/rf-1
```

`have` names a system on hand; `have goat-transformers` says the library is
deployed. `feed <consumer>` asks for every path to that consumer from every
system on hand; `from=` narrows it to one source. `goat-options site` answers
every `feed` line and marks the source, the consumer and each converter of
every path `on_hand: true` or `false`. A `have` with no record is reported, so
the site sees which of its systems nobody has described.

The site file is read from its path and goes nowhere. The records it is
combined with are whatever stores the site passes with `--store`.

## Public and private stores

A store is a directory of `.rec` files. The query takes any number of them
(`--store` repeatable) and merges them at load time. Files are never edited to
merge.

| Store | Holds | Where |
|---|---|---|
| `examples/stores/sketch` | fictional systems reproducing a community sketch: four sensors, an edge consumer, two applications and a translator on one Zenoh mesh | this repository |
| a private store | records of real systems | a private repository, never this one ([private-store.md](private-store.md)) |

This repository holds the record format, the query and fictional examples
only. A record of a real fielded system, even one whose formats are all public,
is kept in a private store: which system speaks what is itself the sensitive
fact. `tools/boundary-gate` checks `.rec` and `.site` files like every other
tracked file.

## Records from several owners

Each nation or organization keeps its own store and shares what it chooses.
Three rules keep stores mergeable without conflict:

- **The identifier names the system, not the author.** `<maker>/<system>`,
  lowercase. Two owners describing the same system use the same identifier, and
  their records merge on it.
- **Nothing replaces anything.** Merged, a system keeps every name, kind, note
  and claim from every record, each claim with its store, file, line, `by` and
  `date`. Two owners who disagree on a status are both shown.
- **One owner, one file.** No two owners write the same file; a shared
  collection is directories side by side, copied, not edited. The answer does
  not depend on the order the stores are given (a test checks this).

The direction this leaves open, and does not build: a store that carries
signed records, an exchange of stores between organizations, and a `same-as`
line linking two identifiers that turn out to name one system.

## Deliberately left out

| Left out | Because |
|---|---|
| Ranking, scoring or a preferred path | the tool reports options and evidence; the choice is the person's, with context the tool does not have |
| A server, a database engine, a schema that refuses unknown fields | a directory of text files can be copied, merged and version-controlled; that is the first database |
| Synchronization between organizations | identifiers, provenance and file-per-owner keep it possible; how coalitions exchange stores is not decided |
| Transport bridging | transports are reported per claim, and a direct path whose two ends name different transports is marked `transports_differ`; the tool does not plan a bridge |
| Version ranges | `version` is text, reported as written |
| Aliases between format names | two owners who write the same format differently do not match; the `check` listing shows names with no pack, which is where such a pair appears |
| Coverage per message kind | the capability report is per format; a claim covers the whole format |

## Tests

`python3 -I -m unittest discover -s tools/tests`: the tokenizer, records kept
when unknown, merging without loss and independent of order, direct,
one-conversion and two-conversion paths on the sketch, the library step equal
to `Engine.capability`, no two library steps in a row, site on-hand marking,
the sketch's summary counts, and a check that no output of the tool contains a
ranking word (`recommend`, `best`, `prefer`, `should`, `optimal`, `score`,
`rank`).
