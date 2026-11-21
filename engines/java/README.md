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
`encode` and `complete` work on an `Entity`. `capability(from, to)` gives the
capability report of a pair of formats (grade, carried and dropped keys), and
`setMaxItems(n)` sets the limit on list items of one decode (default
100,000). A failure is a `GtException` (unchecked) whose `kind()` is the error
name of the specification.

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

The tool follows the command-line contract of
[spec/engine-spec.md](../../spec/engine-spec.md), Version 0.23: the same
arguments, output and exit status as the tool of every other engine. Build it
with `./build.sh` (it writes the jar only when every test passes), then start
it from the repository root with

```
engines/java/goat-xf-java.sh <subcommand> [<option> <value>]...
```

which runs `java -jar engines/java/build/goat-transformers-0.8.0.jar`, the
class `goat.transformers.Cli`. The launcher sets `LC_ALL=C.UTF-8` when the
locale is not a UTF-8 one, because the JVM decodes its arguments with the
locale's character set and the contract's command line is UTF-8.

| Subcommand | Does |
|---|---|
| `convert --from F --to T [--set KEY=VALUE]...` | reads standard input to its end, writes the converted message with nothing added (hex text for the `bits`, `protobuf` and `tlv` wires) |
| `list-formats` | one `<format> TAB <version> TAB <wire>` line per loaded pack, in byte order of format |
| `capability --from F --to T` | the capability report of the pair as one matrix line |
| `matrix` | the header `from TAB to TAB grade TAB carried TAB dropped`, then one line per ordered pair of loaded formats |
| `help`, `-h`, `--help` | the usage on standard output |

| Option | Meaning | Default |
|---|---|---|
| `--packs DIR` | the directory whose subdirectories are packs | `packs`, in the working directory |
| `--models DIR` | the model modules; every `.def` file is loaded | the `--packs` text followed by `/../model` |
| `--packs-only NAME[,NAME...]` | load only these subdirectories of `--packs`, in this order | every pack directory |
| `--max-items N` | the limit on list items of one decode | 100000 |
| `--max-distribution public\|controlled` | refuse modules and packs marked above the limit | `controlled` |

Each option is given at most once, except `--set`. Exit status 0 is success;
1 is a load or call failure, and the first line of standard error begins with
the error kind and a colon (an unreadable `--packs` without `--packs-only` begins with `io:`; with it, the first name is `unknown-format`); 2 is a
usage error, checked before anything is loaded. With `--packs-only` the tool
reads the model directory once and each named pack once. This tool has no
`--x-` options. Measured from the repository root:

```
$ engines/java/goat-xf-java.sh list-formats --packs packs --packs-only geojson,cot-xml
cot-xml	0.6.0	xml
geojson	0.1.0	geojson
$ echo '{}' | engines/java/goat-xf-java.sh convert --from geojson --to nope --packs packs --packs-only geojson
unknown-format: no pack loaded for format nope [format=nope locator=-]
```

## Builds with fewer wires

A build can carry the codecs of only some wires (spec Version 0.24). Name the
set with `--wires`, a comma-separated subset of `xml`, `geojson`, `json`,
`bits`, `protobuf`, `text` and `tlv`:

```bash
./build.sh --wires xml,json,geojson     # no --wires (or --wires all): all seven
```

The core sources (`src/main/java`: the pack language, the model, the engine,
the command-line tool) are in every build. Each wire's codec is a directory
`src/wire/<wire>/`, compiled only when the wire is in the set, and `build.sh`
generates the class `Wires` that names the set and the codec of each wire in it,
so the jar holds no class of a wire outside the set. `src/wire/json-tree` (JSON
objects through the lines of a scope) is compiled with `json` or `geojson`: a
build with `geojson` needs nothing of the `json` wire. The sequential layout,
six-bit armor and `encoding uper` are part of `bits`.

In a reduced build a pack whose `wire` is a wire the build lacks does not load:
`unknown-wire` at the `wire` line, with a message that names the wire and says
this build does not have it (`wire "bits" is a wire of the specification, but
this build does not have it (this build has xml, geojson, json)`). A `wire`
value that is no wire stays `unknown wire "..."`. `Engine.wires()` returns the
set of the build. A build with fewer than seven wires does not run the test
suite, whose unit checks need every wire; the reduced-build check is its test.
`--out DIR` writes the build somewhere other than `build/`; `--no-test` skips
the test suite of a full build.

### The reduced-build check

One command, from the repository root:

```bash
engines/java/reduced-check.sh            # optional argument: a packs directory
```

It builds the full jar and the jar with `xml`, `json` and `geojson` under
`build/reduced-check/`, checks that the reduced jar holds no class of the
`bits`, `protobuf`, `text` or `tlv` codecs, and runs
`goat.transformers.ReducedCheck` (compiled against the reduced build only) on
the reduced jar:

- every conversion vector whose `from` and `to` packs are on the three wires,
  with every pack on those wires loaded;
- the capability vectors between formats on the three wires, and the load
  vectors none of whose packs is on another wire of the specification;
- one pack each on `bits`, `protobuf`, `text` and `tlv`: `unknown-wire`, the
  wire named in the message, and the format then `unknown-format`; and a
  `wire` value that is no wire, plain `unknown-wire`.

It prints the size of both jars and exits non-zero on any failure. Measured
with `nice -n 10` on this tree:

```
reduced jar: no class of the bits, protobuf, text or tlv codecs
build wires: xml, geojson, json
conversion vectors: 6849/6849 passed (1070 packs on xml, geojson, json; 13458 vectors on other wires not run)
capability vectors: 16/16 passed (those between formats on wires of the build)
load vectors: 378/378 passed (those with no pack on a wire this build lacks)
unknown-wire: bits (pack adsb): unknown-wire: .../packs/adsb/pack.def:18: wire "bits" is a wire of the specification, but this build does not have it (this build has xml, geojson, json) [format=adsb locator=-]
unknown-wire: protobuf (pack apollo-ch): ...
unknown-wire: text (pack conformance-cond-text): ...
unknown-wire: tlv (pack conformance-cond-tlv): ...
unknown-wire loads: 4/4 passed
unknown-wire: nowire (no wire of the specification): unknown-wire: nowire-check:3: unknown wire "nowire" [format=nowire-check locator=-]
OK
jar size, all seven wires:       306094 bytes
jar size, xml, json and geojson: 233325 bytes, 76% of the full jar
```

The jar shrinks by a quarter, not more, because the pack reader stays whole:
a pack on `xml` gets the same named errors in every build (ruling 1b), and
the checks it runs on any pack (the parameters of every transform, a gate
line, the lines of `layout sequential`) are the pack language, not a codec.

## Test

CI runs one command, in this directory:

```bash
./build.sh            # optional argument: a packs directory, default ../../packs
```

The reduced-build check is a second command, run from the repository root:
`engines/java/reduced-check.sh` (see [Builds with fewer wires](#builds-with-fewer-wires)).

It compiles the main and test sources with `-Xlint:all -Werror`, then runs
`goat.transformers.TestRunner`, which loads every model module and every pack
and runs:

- every conversion vector under `packs/*/vectors/`;
- every load vector under `packs/conformance/load-vectors/`;
- every capability vector under `packs/conformance/capability-vectors/`;
- the unit checks of `UnitTests`: rulings of the specification, `loadOnly`
  and the `--packs-only` option of the tool, malformed-input checks (deep
  nesting, XML declarations, number forms), and a sweep that feeds damaged
  copies of every conversion vector's input to `decode` and `convert` and
  requires each failure to be a `GtException` with a named kind: never
  another exception.

It prints each failure and exits non-zero on any. Measured with
`nice -n 10 ./build.sh` on this tree (14028 vectors, 1761 packs):

```
conversion vectors: 14028/14028 passed (1761 packs, 679 model modules)
load vectors: 512/512 passed
capability vectors: 18/18 passed
packs-only: loadOnly checked for 48 of 1761 packs, 24061 ms (GOAT_SWEEP_FULL=1 for all)
malformed input sweep: 1468191 inputs over 14028 of 14028 conversion vectors (49 damaged copies each) and 1761 packs of 6 wires, 1103663 named errors, 0 defects, 13860 ms (GOAT_SWEEP_FULL=1 for the full sweep)
unit checks: 733/733 passed
OK
```

`./build.sh` takes 52 s in all.

The tool vectors (`packs/conformance/tool-vectors/`, spec Version 0.23) run
against the tool, after `./build.sh` has written the jar, from the repository
root:

```
$ python3 -I tools/tool-vectors.py -- engines/java/goat-xf-java.sh
tool vectors: 97/97 passed
```

| Test | Command | Measured |
|---|---|---|
| tool vectors | `python3 -I tools/tool-vectors.py -- engines/java/goat-xf-java.sh` | 97/97 passed, 5 min 31 s for 95 vectors on an idle machine (each run starts a JVM and loads every model module) |

### The bounded sweep and `GOAT_SWEEP_FULL=1`

The sweep is bounded, and its size does not depend on the number of packs:

- Each conversion vector gets at most 50 damaged copies, and each one is
  given to `decode` and to `convert`. Every kind of damage is used at least
  once per vector: a cut at a prefix, the last byte cut, one byte replaced by
  any byte, one byte replaced by a byte of the input's own alphabet, and one
  bit flipped. The seed comes from the vector's file name, so a vector is
  damaged the same way in every run whatever else is loaded.
- One damaged copy of each vector is also decoded by other packs. The packs
  rotate over every loaded pack, so every pack decodes damaged input,
  including a pack with no vectors. One pack of each wire is added, so every
  wire reads damaged input of every wire. A check fails if any loaded pack
  or wire was never fed.
- The total is about 1,500,000 inputs (`SWEEP_BUDGET`). When there are more
  vectors than that allows, the damaged copies per vector shrink to 5. Past
  that point, the first vector of every pack is kept and the others are
  sampled by seed.

`loadOnly` reads the whole `model` directory on each call, which is about
0.5 s here. So `--packs-only` loading is checked one pack at a time for a
fixed sample of 48 packs: the first of each wire, the pack with the most
`uses` lines, and the rest chosen by seed.

`GOAT_SWEEP_FULL=1 ./build.sh` runs the full checks for a deliberate deep run.
These are the earlier sweep, which gives a damaged copy of every vector to
every pack, and `loadOnly` for every pack. Measured with
`GOAT_SWEEP_FULL=1 nice -n 10 ./build.sh` on the same tree:

```
packs-only: loadOnly checked for 1761 of 1761 packs, 731380 ms
malformed input sweep (full): 26151719 inputs over 14028 vectors and 1761 packs, 23270288 named errors, 0 defects, 131951 ms
unit checks: 2444/2444 passed
OK
```

That run takes 14 min 38 s in all. Before the sweep was bounded, the plain
`./build.sh` took 13 min 50 s with 26,151,719 sweep inputs. The one-pack
`loadOnly` loop took most of that time, about 12 minutes, and the sweep about
2 minutes. Both grow with the number of packs.

## Where to read next

- [spec/engine-spec.md](../../spec/engine-spec.md): the pack grammar, the wire
  types, decode, encode and errors this engine implements.
- [docs/using.md](../../docs/using.md): using each engine as a library or a
  tool.
