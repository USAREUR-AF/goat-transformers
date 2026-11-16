# Languages: use any, converge on Rust

Status: Written. This page is guidance, not a rule. Nothing here is checked by
CI and no contribution is refused for the language it is written in.

## The position

The library exists in seven languages, and every one of them is a first-class,
fully conformant engine. Use whichever fits your problem. The project itself
follows a deliberate strategy of diverging and then converging: it allows
creative problem solving in any language, and it prefers Rust for the stable
establishment of code that is performance critical, safety critical, or has to
run on every platform (WebAssembly and micro-containers).

## Diverge: any language is welcome

A format is data, and every engine reads the same packs and passes the same
vectors. So the language is a free choice at the point of use:

- Use the engine in the language your system is already written in. A Python
  service, a Go command-line tool, a Java application and an Erlang node each
  get a native library with no foreign-function boundary.
- Explore in the language you think fastest in. A new wire type, a new
  transform or a new idea for the pack language can start in any engine. A
  working sketch in one language is a real contribution.
- Write a new engine. The specification and the vectors are the whole contract
  (`spec/`), and an eighth language is welcome on the same terms as the seven.

The engines are written independently from the specification, never from each
other, so each one also checks the others: a defect in one shows up as a
disagreement on a vector (`spec/interop-and-sharing.md`). More languages make
that check stronger.

## Converge: what settles in Rust

When something has proven itself and needs to become the dependable form that
others build on, the project settles it in Rust:

| What | Why Rust |
|---|---|
| The reference engine | New specification versions are implemented and ruled on here first, then in the other engines from the specification |
| Per-message hot paths | Predictable memory and no runtime pauses under sustained throughput |
| Code where a memory error is a safety or security problem | Memory safety without a garbage collector |
| The form that runs everywhere | One source builds a fully static binary for a scratch container or a micro virtual machine, a C library for hosts in other languages, and a WebAssembly module with no imports (`bindings/`) |

Converging does not retire the other engines. They stay conformant and stay
supported; converging only names where the project puts its own effort when a
thing has to be fast, safe and portable at once.

## How this follows from the goat engineering principles

This library is part of the goat project and takes its engineering principles
from there. The principles are the source; what is specific to this library is
how they apply to a codebase whose purpose is to exist in many languages.

| goat principle | Here |
|---|---|
| Pick the language that fits the job; the test is workload shape. A per-byte or per-packet hot path, or code that lives inside another data-path process, is Rust; request-shaped services, tools and glue use the language that is quickest and simplest for them (goatcore ADR 0112) | A message conversion on a data path is the hot-path shape, so the settled engine is Rust. A converter inside a request-shaped service or a tool is free to use that service's language |
| Earned complexity: every layer must solve a named problem at a cost below its value | Seven engines earn their cost as independent checks on one specification, and as native libraries for seven kinds of host. A second implementation of the same thing in the same language would not |
| Simplest technology that achieves the value | Each engine uses only its language's standard library. A format is a text file, not generated code |
| A fast probe first, then a slow codification (the fast and slow steps of the goat workflow) | Diverging is the probe: try the idea in any language. Converging is the codification: specification text, vectors, the Rust reference, then the other engines |
| Holistic consistency over a parallel mechanism | One specification, one set of packs and one set of vectors serve every language; nothing is defined per language |

## In practice

- Choosing an engine for a deployment: `tools/goat-pkg plan` takes your
  language, runtime, operating system and architecture and returns the smallest
  package (`docs/package-configurator.md`).
- No native engine for your language: embed the Rust engine through the C
  library or the WebAssembly module in `bindings/`.
- Proposing a change to the pack language: bring it in any engine, with
  vectors. It becomes part of the specification when the vectors are agreed
  and the engines reproduce them.
