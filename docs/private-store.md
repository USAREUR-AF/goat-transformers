# Keeping a private store of system records

Status: Written. The tools it names are Built.

A private store is a directory of system records (`.rec` files,
[system-records.md](system-records.md)) about real systems, kept in a private
repository. This repository never holds one. Which real system speaks which
format, in which version, with what evidence, is sensitive even when every
format is public, so a private store is handled like a private overlay
([boundary.md](boundary.md)): shared only with parties entitled to it, through
channels its owner chooses.

## Where it lives

Put the store in the private overlay repository beside its packs, or in a
repository of its own:

```
<private repository>/
  stores/<owner>/          one directory per owner: that owner's records only
    <maker>/<system>.rec   any layout below the owner directory; the tool reads every .rec
  sites/                   optional; a site file usually stays at its site, not here
```

Keeping the store in the overlay means the query sees the overlay's packs: run
it in the assembled tree (`./assemble.sh`), or point it at the tree:

```
python3 -I <library>/tools/goat-options summary \
    --store stores/<owner> --packs <assembled tree>/packs --models <assembled tree>/model
```

## Writing records

- One file per system per owner. Use the system's identifier, `<maker>/<system>`
  in lowercase, as the `system` line; another owner describing the same system
  uses the same identifier, and the records merge on it.
- Write `by` and `date` in every file. They are the provenance every claim
  carries in the query's output.
- Give each claim a `status`. Write `proven` only with `evidence=` pointing at
  the record of the run: a test report number, a path in the owner's own
  repository. `check` warns on `proven` without evidence.
- Where a pack exists, write the pack's format name (`goat-xf list-formats`),
  so the library's conversions join up. Where none exists, write the name the
  system's interface document uses, the same way in every record.
- Write `speaks` when the source says a system uses a format but not in which
  direction. Change it to `emits` or `accepts` when that is known.
- Leave out what is not known. A missing field is not an error.

Run `check --strict` before committing; it exits 1 on a warning:

```
python3 -I <library>/tools/goat-options check --store stores/<owner> --strict --table
```

## Generating records from a catalog

An organization that already keeps a per-system catalog with front matter
(fields such as the data standards a system uses, its interface type and the
state of its interface documents) can generate a store from it rather than
write one by hand. The generator belongs in the private repository, next to the
catalog's own mapping of its standard names to pack names. Regenerate rather
than edit generated files, as with packs (`CONTRIBUTING.md`).

## Combining stores

Pass several stores to one query; they merge by identifier, and nothing in one
replaces anything in another:

```
python3 -I <library>/tools/goat-options paths \
    --store stores/owner-a --store stores/owner-b --store <received store> \
    --from <maker>/<system> --to <maker>/<system> --table
```

A store received from another owner is copied in as its own directory and not
edited. A correction goes back to that owner, or into a record of your own
about the same system, which then appears beside theirs.

## Before anything leaves the private repository

- Records and site files never go into a public repository, issue, pull request
  or commit message.
- The public repository's boundary gate refuses text from the overlay's needle
  list (`tools/needles.py`). A private store's identifiers can be added to that
  list so a slip into the public repository is refused at push:
  `boundary-gate --needles` treats each line as a needle.
- `summary` prints counts only. Counts are the form in which a store's coverage
  can be reported outside the store.
