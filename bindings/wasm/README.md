# @usareur-af/goat-transformers

[goat-transformers](https://github.com/USAREUR-AF/goat-transformers) converts
messages between formats that are described by data files (packs). This package
is its Rust reference engine as a WebAssembly module with no imports, and a
hand-written wrapper with TypeScript types. It has no dependencies.

The package is attached to each GitHub Release as
`usareur-af-goat-transformers-<version>.tgz`; it is not on the npm registry.

```
npm install https://github.com/USAREUR-AF/goat-transformers/releases/download/v0.8.0/usareur-af-goat-transformers-0.8.0.tgz
```

Node, with packs on disk:

```js
import { loadTree } from "@usareur-af/goat-transformers/node";

const gt = await loadTree("vendor/goat", ["cot-xml", "geojson"]);
console.log(gt.convert("cot-xml", "geojson", cotEvent));
```

A browser, or any host that reads the texts itself:

```js
import { GoatTransformers } from "@usareur-af/goat-transformers";

const gt = await GoatTransformers.load(wasmBytes);   // "@usareur-af/goat-transformers/goat_transformers.wasm"
gt.loadModel(coreDefText);                           // core first, then the other modules
gt.loadPack(packDefText);
```

The package holds the engine. The packs are data: `tools/goat-pkg bundle` in
the repository writes the ones you name, and the model modules they use, to a
directory you vendor. `docs/using.md` in the repository shows the whole path.
