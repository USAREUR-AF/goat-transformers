# The public and controlled boundary

Status: Built. The engine checks are in all seven engines and fixed by load
vectors; `tools/boundary-gate` runs on this repository in CI.

This repository holds only what is written from public sources: the engines, the
specification, the public model modules and the packs for formats whose
specification is public. A model module or pack written from a specification
that is not public is kept in a private overlay repository that pins this one
by commit. The engines run both kinds unchanged.

## What marks a file

Every model module (`model/<module>.def`) and every pack (`packs/<format>/pack.def`)
carries two things:

```
distribution  public            # or: controlled
source        "IETF RFC 7946"   # the document it was written from; repeatable
```

A file with no `distribution` line or no `source` line does not load.

## What the engine enforces

| Rule | Error |
|---|---|
| A `public` pack uses only `public` modules | `distribution-violation` |
| A `controlled` pack may use `public` and `controlled` modules | loads |
| An engine started with `--max-distribution public` loads nothing `controlled` | `distribution-refused` |

A controlled format therefore converts to and from every public format through
the public modules, and the public modules cannot acquire a key that exists only
in a controlled standard: such a key is declared in a controlled module, and a
controlled module is never in this repository.

## What the gate enforces on this repository

`tools/boundary-gate` reads every tracked file and exits non-zero on any
finding. A file it cannot read is a finding.

| Check | Refuses |
|---|---|
| `marking` | a module or pack that is not `distribution public`, or has no `source` |
| `closure` | a pack that uses a module not in `model/`, or maps a key its module does not declare |
| `filetype` | any file type not on the allowlist: documents, spreadsheets, archives, binaries |
| `phrase` | text carrying the handling marking of a restricted document |
| `hygiene` | a local absolute path under a home directory, the name of a private organization, or an email address |
| `needle` | text containing a string from a private overlay's needle list |

A line that carries `boundary-allow: <reason>` is exempt from the `phrase` and
`hygiene` checks. Nothing exempts a line from the `needle` check.

The first five run anywhere, including CI. The `needle` check needs a list that
only a private overlay can build (its field names, labels and reference
numbers), so it runs where that overlay is present. An overlay that wants this
check supplies `tools/needles.py`, which prints one needle per line:

```
needles="$(mktemp)"
python3 -I "$GOAT_XF_OVERLAY/tools/needles.py" > "$needles"
python3 -I tools/boundary-gate --needles "$needles" --require-needles
```

`tools/hooks/pre-push` runs those commands before every push and refuses the
push when the needle list cannot be built. `GOAT_XF_OVERLAY` is the path of the
overlay checkout; the default is a directory named `goat-transformers-overlay`
beside this repository. A contributor with no overlay does not install the
hook. To install it:

```
ln -sf ../../tools/hooks/pre-push .git/hooks/pre-push
```

## The private overlay

An overlay repository has the same shape as this one for the parts it adds:

```
core.ref        the commit of this repository it builds against
model/          controlled model modules
packs/          controlled packs
assemble.sh     copies this repository at core.ref, then model/ and packs/ over it
```

The assembled tree is where the engines, the vectors and the package
configurator run. A public worked example with fictional content is
[goat-transformers-overlay-example](https://github.com/USAREUR-AF/goat-transformers-overlay-example).
