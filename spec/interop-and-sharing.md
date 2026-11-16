# Code sharing and cross-language interop

Status: Written. Version 0.1.

Two kinds of sharing, kept separate on purpose. Blurring them trades away the
redundancy the polyglot design exists to buy.

## Within a language: one shared core

Each language has exactly one engine library. Every pack, every transformer and
every consumer in that language calls it. The library holds: the dictionary
interpreter, the mapping interpreter, the shared model, the transform function
set, and the framers. A format is data (`packs/<format>/`), never new engine
code, so a new format costs data files and vectors, not a code change in each
consumer.

Layout per language:

```
engines/<lang>/        the one shared core library
consumers link that library; packs/ is shared across all languages
```

## Across languages: independent engines, verified against each other

Rust, Go, Python, Java, C++, Erlang and Zig each implement the engine natively, from
`spec/engine-spec.md` and the vectors — never from another engine's source. They
exist so that a defect in one is caught by the others: all engines run all
vectors, and they are run against each other on generated inputs. For this to
work the native engines must stay independent and must not call one another.

## Across languages: FFI and embedding, for shipping only

The Rust reference compiles to a C ABI (`cdylib`) and to WebAssembly. A program
in C++, Python, Java or another language that does not want to carry a second
native engine can embed the Rust engine through that ABI instead of writing its
own. This is a packaging convenience.

The rule that keeps redundancy intact: **FFI is allowed for deployment; the
vector cross-check always runs the independent native engines against each
other, never one engine calling another.** An embedded Rust engine and a native
Go engine are two shipping options over the same packs and vectors; they are not
a substitute for the independent Go engine in the cross-check.

| Path | Purpose | Counts as a cross-check voice |
|---|---|---|
| Native engine per language | correctness by independence | yes |
| Rust C ABI / WASM embedded elsewhere | one binary, fewer rewrites | no |

## What is genuinely shared across all languages

- `packs/` — dictionaries, mappings, overrides, vectors. One copy, all languages.
- `spec/` — the engine specification and shared model. One source of truth.
- The conformance vectors — the single definition of correct behaviour.

Engine source is not shared across languages. That is the point.
