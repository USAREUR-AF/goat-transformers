# The Java engine

This directory is one of the seven independent engines of goat-transformers.
It was written from [`spec/`](../../spec/) and the conformance vectors only,
and uses only the Java standard library. It needs JDK 17: `build.sh` compiles
with `javac --release 17`, and the `java` job of
[`conformance.yml`](../../.github/workflows/conformance.yml) runs it on
Temurin 17. The package is `goat.transformers`; the jar's automatic module
name is the same.

## Use as a library

`./build.sh` compiles the engine, runs every test (see [Test](#test)) and,
when they pass, writes `build/goat-transformers-0.8.0.jar`: the engine classes
and nothing else. Each release carries the same file
([docs/using.md](../../docs/using.md#java)). Put it on the class path, and
ship the `packs/` and `model/` directories (or only the packs you load) beside
your program.

The main class is `Engine`. `Engine.load(packsDir)` loads every model module
of `<packsDir>/../model` and every pack; `Engine.loadOnly(packsDir, names)`
loads only the named packs, with `core` and the model modules their `uses`
lines need. Both have a form that takes a models directory and a
`Distribution` limit. `convert(from, to, text)` and
`convert(from, to, text, context)` return the encoded message; `decode`,
`encode` and `complete` work on an `Entity`. A failure is a `GtException`
(unchecked) whose `kind()` is the error name of the specification.

```java
import goat.transformers.Engine;
import goat.transformers.GtException;
import java.nio.file.Path;
import java.util.List;

public class Convert {
    public static void main(String[] args) {
        // Loads model/core.def, the modules the two packs use, and the two packs.
        Engine engine = Engine.loadOnly(Path.of("vendor/goat/packs"), List.of("geojson", "cot-xml"));
        String feature = "{\"type\":\"Feature\",\"geometry\":{\"type\":\"Point\","
                + "\"coordinates\":[-85.9578182,30.0090027,-42.6]},\"properties\":{\"type\":\"a-f-G-U-C\","
                + "\"time_ms\":1614456000000,\"how\":\"m-g\",\"ce\":45.3,\"le\":99.5,\"callsign\":\"GATOR\"},"
                + "\"id\":\"J-01334\"}";
        try {
            System.out.println(engine.convert("geojson", "cot-xml", feature));
        } catch (GtException ex) {
            System.err.println(ex.kind() + " " + ex.getMessage());
        }
    }
}
```

Measured from a scratch directory outside the repository, with the jar in
`lib/` and copies of `packs/` and `model/` in `vendor/goat/`:

```
$ javac -cp lib/goat-transformers-0.8.0.jar Convert.java
$ java -cp lib/goat-transformers-0.8.0.jar:. Convert
<event version="2.0" uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" start="2021-02-27T20:00:00.000Z" how="m-g"><point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/><detail><contact callsign="GATOR"/></detail></event>
```

## Command-line tool

`java -jar build/goat-transformers-0.8.0.jar` runs `goat.transformers.Cli`.

| Subcommand | Does |
|---|---|
| `convert --from FORMAT --to FORMAT` | reads a message on stdin, writes the converted message on stdout |
| `list-formats` | prints one `<format> <version> <wire>` line per loaded pack |

| Option | Meaning |
|---|---|
| `--packs DIR` | the packs directory; required (this tool has no default) |
| `--models DIR` | the model modules; default `<packs>/../model` |
| `--packs-only NAME[,NAME...]` | load only the named packs, with the model modules they need |
| `--max-distribution public\|controlled` | refuse modules and packs marked above the limit; default `controlled` |
| `--set KEY=VALUE` | `convert` only, repeatable: supply a model key the source does not carry |

Exit codes: 0 success, 1 engine error (printed as `error: <kind>: ...`),
2 usage (the usage text is printed on stderr). Measured from this directory:

```
$ java -jar build/goat-transformers-0.8.0.jar list-formats --packs ../../packs --packs-only geojson,cot-xml
cot-xml 0.2.0 xml
geojson 0.1.0 geojson
$ echo '{}' | java -jar build/goat-transformers-0.8.0.jar convert --from geojson --to nope --packs ../../packs --packs-only geojson
error: unknown-format: no pack loaded for format nope [format=nope locator=-]
```

## Test

CI runs one command, in this directory:

```bash
./build.sh            # optional argument: a packs directory, default ../../packs
```

It compiles the main and test sources with `-Xlint:all -Werror`, then runs
`goat.transformers.TestRunner`, which loads every model module and every pack
and runs:

- every conversion vector under `packs/*/vectors/`;
- every load vector under `packs/conformance/load-vectors/`;
- the unit checks of `UnitTests`: rulings of the specification, `loadOnly`
  and the `--packs-only` option of the tool, malformed-input checks (deep
  nesting, XML declarations, number forms), and a sweep that feeds
  truncated and byte-changed copies of every vector's input to `decode` and
  `convert` and requires each failure to be a `GtException` with a named
  kind.

It prints each failure and exits non-zero on any. Measured with
`nice -n 10 ./build.sh` on this tree:

```
conversion vectors: 3299/3299 passed (96 packs, 43 model modules)
load vectors: 314/314 passed
malformed input sweep: 637847 inputs over 3299 vectors and 96 packs, 591698 named errors, 0 defects
unit checks: 741/741 passed
OK
```

## Where to read next

- [spec/engine-spec.md](../../spec/engine-spec.md): the pack grammar, the wire
  types, decode, encode and errors this engine implements.
- [docs/using.md](../../docs/using.md): using each engine as a library or a
  tool.
