---
name: review-a-pack
description: Review a goat-transformers pack (pack.def, pack.md, PROVENANCE.md, vectors, model module) for correctness, provenance and public status. Use when asked to review, audit or check a pack or a pull request that adds or changes one, when the owner of a format (a vendor, a standards body, a program) wants to confirm the pack matches the specification, or before merging generated packs.
---

# Review a pack

The review answers four questions: may this be public, does it say what the
specification says, do the vectors prove it, and does it harm anything that
already works. Report findings as a list, each with the file and line and the
sentence of the specification it rests on. Do not fix silently.

Set up a quick load of the pack under review:

```bash
cd engines/rust && cargo build --release && cd ../..
P="--packs packs --packs-only <format>,geojson,cot-xml"; X=engines/rust/target/release/goat-xf
$X list-formats $P
```

## 1. Public status and provenance

- [ ] `distribution public` and one or more `source` lines in `pack.def` and
      in any new `model/<module>.def`.
- [ ] Every source is a public document, named precisely: title, edition or
      commit, address. The license of each is stated in `PROVENANCE.md` and
      allows this use. If the license is unclear or restrictive, stop and ask
      a person.
- [ ] `PROVENANCE.md` gives, for each source file, where to obtain it, the
      version or commit, and the SHA-256. The source has an entry in
      `tools/notice/entries/<name>.txt`.
- [ ] No source file is in the tree (no schema, no standard document), and no
      passage of a standard is copied into `pack.md` or comments.
- [ ] `python3 -I tools/boundary-gate` prints `boundary-gate: ok`.
- [ ] Nothing in the change reads as coming from a non-public edition of the
      format (fields or values the public source does not have). If something
      does, stop and ask.

## 2. The pack against the specification

Take the specification and check a sample of fields in every message kind,
and every field bound to a shared key:

- [ ] Position: locator, length and bit order match the specification
      (`bit_order`, `word_bytes`, `swap`). For `bits`, no two fields of one
      kind overlap unless stated.
- [ ] Transform and unit: the model unit is the key's fixed unit
      (`model/core.def`: degrees, meters, meters per second, epoch
      milliseconds). The scale factor is exact, written as a fraction where
      the decimal is not exact. Signed fields use `twos` or `sscale`.
- [ ] Meaning: a field bound to a `core` or `track` key means what the key
      means: WGS 84, height above the ellipsoid for `hae`, true course for
      `course`, UTC for `time_ms`. A field with a different meaning has a raw
      key of the format's own module. `pack.md` gives the evidence.
- [ ] Kinds: each `when` set selects exactly the messages of that kind; a more
      specific kind comes before a general one; `requires` lists what encode
      needs.
- [ ] Constants, defaults and value tables (`const`, `default`, `map`) match
      the specification's fixed values, "unknown" values and code lists.
- [ ] `pack.md` states what is not mapped and why, and the message convention
      (which bytes are one message; what framing is left out).

## 3. The model module, when the pack adds or changes one

- [ ] No existing key is renamed, retyped or removed
      (`git diff main -- model/`).
- [ ] New keys of a public module are not specific to one format unless the
      module is that format's own.
- [ ] A generated pack was regenerated, not edited: its names file under
      `tools/gen/names/` changed only by additions.

## 4. The vectors

- [ ] There is a same-format round trip per kind, a conversion to another
      format and one from another format.
- [ ] Each `expect` has a stated origin (`source`, `reference`, or the
      generator that computed it) that is independent of the engines. Check
      two or three by hand from the specification: decode the bytes yourself
      and compare with `model` and `expect`.
- [ ] Edge values are present: zero, negative, the ends of a range, an
      "unknown" value, an error case with `expect_error`.
- [ ] No vector was changed to make an engine pass
      (`git diff main -- packs/*/vectors`): a changed `expect` needs a reason
      in the specification.

Run one vector through the engine and compare with its `expect`:

```bash
python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['input'])" packs/<format>/vectors/<file>.json \
  | $X convert --from <format> --to <to> $P
```

## 5. What it does to the other formats

```bash
$X matrix $P | awk -F'\t' '$1 == "<format>" || $2 == "<format>"' | cut -c1-300
```

- [ ] The keys that carry to and from `geojson` and `cot-xml` are the ones the
      pack's notes claim.
- [ ] All seven engines pass every vector (`AGENTS.md`, Commands, or the
      `conformance` checks on the pull request). A pack that only the
      reference engine accepts is not done.

## 6. Documents

- [ ] The format has its row in `docs/coverage-roadmap.md` and in the pack
      table of `README.md`, and the counts in `README.md` equal
      `python3 -I tools/repo-stats`.
- [ ] Status words are exact: built, measured, designed, not built.

## For the owner of the format

You know the specification better than any reviewer. The most valuable checks
are section 2 (meaning and units of the fields bound to shared keys) and
section 4 (two vectors worked by hand from your own reference messages). A
correction is a pull request that changes the `field` line and adds the vector
that would have caught it.
