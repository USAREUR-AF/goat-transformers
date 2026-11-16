---
name: write-an-overlay
description: Support a message format whose specification is not public (restricted, licensed, vendor-held or otherwise not publishable) by writing its pack in a private overlay repository that builds on goat-transformers, without putting anything from that specification into the public repository. Use when asked to add a restricted, controlled, proprietary or private format, to set up an overlay repository, to mark distribution, to assemble an overlay tree, or to set up the needle gate that keeps overlay terms out of the public repository.
---

# Write an overlay

A pack written from a specification restates that specification's field
layout. If the specification cannot be published, neither can the pack. Such
packs live in a separate private repository, an **overlay**, that pins this
repository by commit and adds only model modules and packs. The engines are
not copied or changed. `docs/boundary.md` states the rules; the worked example
with fictional content is
https://github.com/USAREUR-AF/goat-transformers-overlay-example.

## Before anything: where you are working

- Never create, paste or stage any part of a non-public specification, pack,
  vector, field name or example message in the public goat-transformers
  checkout, in an issue, a pull request, a commit message or a branch name.
- Confirm with the person that they are entitled to hold the specification and
  that the overlay repository is private with access limited to the people
  allowed to hold that material. Do not decide this yourself.
- Work only in the overlay checkout and in an assembled tree outside both
  repositories.

## 1. Start from the example's shape

```
core.ref        the full commit id of goat-transformers the overlay builds with
model/          controlled model modules
packs/          controlled packs, each with pack.md and vectors/
tools/vectors.py   computes the expected bytes of the vectors without an engine
tools/needles.py   prints the overlay's distinctive terms, one per line (you add this; the example has none)
assemble.sh     builds the assembled tree; refuses to replace a library file
check.sh        assembles, runs the tests, shows a public-only engine refuses the tree
PROVENANCE.md   the rights basis and handling of the packs
```

Copy the example repository's `assemble.sh`, `check.sh` and layout into a new
private repository. Replace the three fictional formats with your own. Fill in
`PROVENANCE.md`: who authored the overlay, under what authority, the handling
that applies, and that packs are written from the source and no file of the
source is copied in.

## 2. Mark distribution

Every overlay module and pack carries:

```
distribution  controlled
source        "<the document it was written from>"
```

What the engines enforce:

| Rule | Error |
|---|---|
| a `public` pack uses only `public` modules | `distribution-violation` |
| a `controlled` pack may use `public` and `controlled` modules | loads |
| an engine started with `--max-distribution public` loads nothing `controlled` | `distribution-refused` |

So: bind position, time and identity to the public keys (`lat`, `lon`,
`time_ms`, `uid`, the `track` keys) and the format converts to and from every
public format. Declare a key that exists only in your format in an overlay
module, never as a proposal for a public module: the public model must not
gain a key that exists only in a non-public standard.

## 3. Write the packs

The steps of the `add-a-format` skill apply unchanged (choose the wire, write
`pack.def`, bind with evidence, derive vectors independently, write `pack.md`),
with `distribution controlled`. Compute expected bytes in `tools/vectors.py`,
which imports no engine; `python3 tools/vectors.py --check` confirms the
vector files equal what it computes.

A pack name or module name that the library already has is refused by
`assemble.sh`: choose names of your own.

## 4. Assemble and run

```bash
./assemble.sh --core-dir <goat-transformers checkout> <new empty directory>
cd <that directory>/engines/rust && cargo build --release
./target/release/goat-xf list-formats                       # library and overlay formats
./target/release/goat-xf list-formats --max-distribution public
# error … distribution-refused: model module `<yours>` is controlled, this engine loads public only
```

Without `--core-dir`, `assemble.sh` fetches the library at the commit in
`core.ref`. `./check.sh` does all of it and ends with `check: ok`. The
assembled tree is a build product: never commit it, and delete it when done.
`tools/goat-pkg plan`, run inside the assembled tree, plans packages that
include the overlay's formats.

A new library version: write the new commit id into `core.ref`, run
`./check.sh`. A needed engine feature: propose it in the public repository in
general terms, with a synthetic `conformance-*` format that shows the rule and
names nothing from your specification (`extend-the-pack-language`).

## 5. The needle gate

People who work in both repositories can leak a term by habit. The needle
check stops it. `tools/needles.py` in the overlay prints one distinctive term
per line: the overlay's field names, message names, labels and document
numbers that do not occur in public material. The public repository's gate
then refuses any tracked text that contains one:

```bash
needles="$(mktemp)"
python3 -I "$GOAT_XF_OVERLAY/tools/needles.py" > "$needles"
python3 -I tools/boundary-gate --needles "$needles" --require-needles
```

Run from the public checkout; `GOAT_XF_OVERLAY` is the path of the overlay
checkout. Install the hook that runs it before every push of the public
repository, in each clone of a person who has the overlay:

```bash
ln -sf ../../tools/hooks/pre-push .git/hooks/pre-push
```

The hook refuses the push when the needle list cannot be built. No line
comment exempts a needle. The needle file is written to a temporary file and
never committed anywhere.

Choose needles that are specific. A common word (`status`, `track`) would
refuse public text; a term that is distinctive to the specification is the
kind to list.

## 6. What may go back to the public repository

- A defect in an engine, described with a synthetic pack and vector.
- A general pack-language rule, with synthetic vectors.
- Nothing else. When unsure whether a detail is public, treat it as not
  public and ask the person.
