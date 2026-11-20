# The landing page

`site/` is one static page for GitHub Pages. It has no build step for the page
itself, no framework, and it loads nothing from another site: no fonts, no
scripts, no analytics.

| File | What it is |
|---|---|
| `index.html` | the page |
| `assets/site.css` | the styles, light and dark by `prefers-color-scheme` |
| `assets/demo.mjs` | the copy buttons and the demo |
| `assets/hero.mjs` | plays the conversion drawn in the first screen, one pack line at a time (a still frame with reduced motion or JavaScript off) |
| `assets/journey.svg`, `assets/model-bus.svg`, `assets/icon.svg` | the two figures and the tab icon |
| `build.sh`, `bundle.py` | write `assets/engine/` from the tree and check the page against it |
| `assets/engine/` | generated, not kept in git (`site/.gitignore`) |
| `assets/figures/` | the README's hub figure, `docs/figures/hub-light.svg` and `hub-dark.svg`, copied by `bundle.py` on every build; not kept in git |

## The demo runs the library

The demo is the library's own WebAssembly module (`bindings/wasm`) on nine
packs. `site/build.sh` writes everything it needs into `assets/engine/`:

| File | From |
|---|---|
| `goat_transformers_wasm.wasm` | `bindings/wasm`, `cargo build --profile small --target wasm32-unknown-unknown` |
| `goat_transformers.mjs` | `bindings/wasm/goat_transformers.mjs`, copied |
| `packs/<format>.def` | `packs/<format>/pack.def`, copied |
| `model/<module>.def` | `model/<module>.def`, copied, for the modules those packs use |
| `bundle.json` | the sample of each format (the `input` of a named vector), what carries between each pair (`goat-xf matrix --detail`), and what `goat-xf convert` prints for each sample |
| `manifest.json` | the library commit, and the size and SHA-256 of every file above |

The module is a binary, so it is not committed: the workflow builds it. To
change the demo's formats or samples, edit the `DEMO` list at the top of
`bundle.py`.

## Preview

```
site/build.sh
python3 -m http.server 8000 --directory site
```

Open `http://localhost:8000/`. The page must be served over HTTP: a browser
does not load a WebAssembly module or a script module from a `file:` address.
Without `assets/engine/` the page still shows one conversion as static text,
which is also what a reader with JavaScript off sees.

`build.sh` needs a Rust toolchain with the `wasm32-unknown-unknown` target
(`rustup target add wasm32-unknown-unknown`), `python3` and `git`.
`site/build.sh --clean` also deletes the two cargo `target` directories when
it is done.

## The page cannot drift from the tree

`build.sh` ends with a check and exits non-zero when it fails:

- every element of `index.html` marked `data-stat="<name>"` states a number
  counted from the tree (`formats`, `message_kinds`, `conversion_vectors`,
  `pair_converters`), from `tools/repo-stats`, the counter of the top-level
  README; the footnotes of the page give the command behind each number. The
  counts move with every pack, so a difference is printed as a note, and the
  counts pull request after each merge wave updates them with the README's:
  `python3 -I site/bundle.py --counts-only --write`, then `--counts-only`,
  which fails while one differs (it needs no module built);
- the two outputs shown near the top of the page must be what `goat-xf` prints
  for the same input;
- the hub figure is copied from `docs/figures/` on every build, so it is the
  README's drawing; the page must show both files, and its alt text must be the
  README's;
- the drawing in the first screen must be the tree's: its bytes are the input
  of `packs/remote-id/vectors/02-location-roundtrip.json`, each pack line it
  quotes is a line of `packs/remote-id/pack.def` or `packs/cot-xml/pack.def`,
  the integer of each step is what its locator reads from those bytes, the
  value is the vector's `model` value, the faint text behind it is lines of
  those two packs, and its output is what `goat-xf` prints.

The size of the WebAssembly module depends on the compiler version, so a
different size is reported and not refused; the page reads the size of the
module it loaded from `bundle.json`.

When a number changes, edit `index.html` to the new value and run `build.sh`
again. The two figures are images and are not checked: `model-bus.svg` states
the packs and message kinds of thirteen families (as
`tools/catalog-families.json` groups them), and `journey.svg` quotes three
`field` lines of `packs/remote-id/pack.def` and `packs/cot-xml/pack.def`;
compare them with the tree when those packs change.

## Publishing

`.github/workflows/pages.yml` runs `build.sh` on every pull request that
touches `site/`, and on a push to main also deploys `site/` with
`actions/deploy-pages`. The deploy job runs only when the repository's Pages
source is set to "GitHub Actions" (Settings, Pages); until a repository owner
sets it, the page is built and checked and the deploy job is skipped.
`tools/boundary-gate` allows `.html` and `.css` files under `site/` only.
