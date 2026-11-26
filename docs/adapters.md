# Transport adapters

Status: Built. The crates `adapters/core`, `adapters/std` and `adapters/mqtt`
are built and tested in CI. `adapters/zenoh` is built and its two tests pass
on a development host; CI does not build it (its `README.md` says why).

An adapter lets a user state "messages arrive on X and leave on Y" as a command
line, with no code of their own. The engine is unchanged: it converts one
message to one message and knows nothing about sockets, files or streams.

```bash
goat-xf-pipe --packs packs --packs-only \
  --from-format cot-xml --in udp://:4242 \
  --out tcp-listen://:9000 --to-format geojson --out-frame newline
```

## What an adapter is and is not

An adapter moves bytes and finds message boundaries. It has three parts:

| Part | Does | Trait or type |
|---|---|---|
| Source | receives bytes from a transport and yields one message at a time | `Source` |
| Framer | states how one message is delimited on a stream | `Framer` |
| Sink | takes one converted message and sends it | `Sink` |

The pipeline (`adapters/core/src/pipeline.rs`) joins them: for each message from
the source it calls the engine's `convert_text(from, to, message, context)` and
gives the result to each sink. When the input format is a carrier whose `inner`
line reads a run of messages (`inner <format> run`, engine-spec 0.92, such as a
JREAP-C block of several J-series messages), it calls `convert_run` instead:
each message of the run is one output frame, counted in `converted` and in
`goat_xf_pipe_messages_out_total`, and a message that fails is counted and
reported with its place in the run while the others are delivered. With
`--packs-only`, the packs that the `inner` lines of a named pack name are loaded
with it.

An adapter does not read, change or select fields. Everything about the content
of a message is in a pack. An adapter does not guess: the format of the input,
the format of each output and the framing of every stream are stated by the
user. An adapter keeps no messages: there is no queue and no retry, so a
message is delivered when it is converted or it is counted as failed.

## How this keeps the core minimal

The engine in `engines/rust` has no dependency and no knowledge of this
directory. The dependency points one way:

```
engines/rust            the engine: text in, text out, no dependency
  ^
adapters/core           traits, framers, pipeline; standard library only
  ^
adapters/std            stdin, files, directories, TCP, UDP, serial; the goat-xf-pipe tool; standard library only
  ^             ^
adapters/mqtt   adapters/zenoh     one crate per transport; a third-party dependency lives only in its own crate
```

A user who links the engine compiles none of this. A user who builds
`goat-xf-pipe` compiles the engine and two crates that use only the standard
library. A transport that needs a third-party crate is its own crate with its
own tool (`goat-xf-pipe-zenoh`), so its dependencies reach nobody who did not
ask for that transport. `adapters/zenoh` is outside the `adapters/` workspace,
so building the workspace never resolves or fetches them.

The engine takes and returns text, and gives a binary message (a `bits` or
`protobuf` wire) as hexadecimal text. The pipeline does that conversion, so a
transport carries the real bytes of a binary format. The option `hex` on a
framing keeps the hexadecimal text on the transport.

## Endpoints

`--in` takes one endpoint. `--out` takes one endpoint and can be given several
times; each output has its own target format and framing.

| URI | As `--in` | As `--out` | Framing if not stated |
|---|---|---|---|
| `stdin:` | standard input, to its end | | must be stated |
| `stdout:` | | standard output | must be stated |
| `file:<path>` | the file, to its end | the file, created or emptied; `?append=1` adds to it | must be stated |
| `dir:<path>` | every regular file whose name does not begin with `.`, once, in byte order of name | one new file for each message | `whole` |
| `tcp://<host>:<port>` | connect and read until the peer closes | connect and write | must be stated |
| `tcp-listen://[<host>]:<port>` | accept up to 64 connections; each is its own framed stream | accept up to 64 clients; each gets every message | must be stated |
| `udp://[<host>]:<port>` | bind that port (every local address when the host is empty) | send to that host and port | `whole` |
| `udp://<group>:<port>?iface=<address>` | join the multicast group on that interface | send to the group from that local address; `?ttl=<n>` | `whole` |
| `serial:<device>` | read the device file | write the device file | must be stated |
| `mqtt://<host>[:<port>]/<topic>` | subscribe to the topic filter (`goat-xf-pipe-mqtt`) | publish on the topic | `whole` |
| `zenoh:<key expression>` | subscribe (`goat-xf-pipe-zenoh`) | put on the key | `whole` |

Notes on single endpoints:

- `dir:` as an output names each file `<prefix><sequence, six digits>.<ext>`.
  The options are `?prefix=`, `?ext=` (default `msg`) and `?name=origin`, which
  names the file after the input file it came from (`a.xml` gives `a.geojson`).
  A file is written under a temporary name and renamed, and an existing file is
  never replaced.
- `tcp-listen:` as an output does not keep a message for a client that has not
  connected yet: with no client the message fails with `no-client`. A client
  that does not take a message within 5 seconds is closed.
- `serial:` opens the device as a file. The line settings are set outside the
  tool, for example `stty -F /dev/ttyUSB0 115200 raw -echo` on Linux. Unix only.
- `udp:` multicast uses the standard library's `join_multicast_v4`. For IPv6
  the group is written in brackets and `iface` is the interface index. The
  standard library cannot set address reuse, so two processes cannot bind the
  same group and port.
- An option the endpoint does not have is refused, not ignored.

## Framing

A stream has no message boundaries, so the user states them with `--in-frame`
and `--out-frame`. Nothing is inferred from the content.

| Framing | One message is |
|---|---|
| `newline` | one line. The line ends at LF; a CR before it is removed; an empty line is not a message; a last line with no LF is a message |
| `len:<N>:<be\|le>` | a length of N bytes (1, 2, 4 or 8) in that byte order, then that many bytes. The length counts the message only |
| `fixed:<N>` | exactly N bytes |
| `start:<byte>:len:<N>:<be\|le>` | a start byte, a length of N bytes, then that many bytes. Bytes before a start byte are skipped and reported as `frame-desync` |
| `start:<byte>:len:<N>:<be\|le>:total` | the same, but the length counts the whole frame from the start byte, and the whole frame is the message. An ASTERIX category 062 data block is `start:0x3e:len:2:be:total` |
| `at:<K>:len:<N>:<be\|le>:<whole\|rest>` | a length of N bytes at offset K of each frame, with no start byte: `whole` when it counts the whole frame, `rest` when it counts the bytes after the length field. The whole frame is the message. A stream of JREAP-C application blocks on TCP, whose length is octets 2 and 3 of the header and counts the whole block, is `at:2:len:2:be:whole`. With no start byte a stream cannot resynchronize: a length shorter than its own field, or above `max`, skips one byte and is reported as `frame-desync` |
| `mavlink2` | MAVLink 2 frames: STX `0xFD`, the 10-byte header, the payload, the checksum and an optional signature. A payload trimmed of trailing zero bytes is zero-filled to its message's full length, which the adapter reads from the `mavlink2` packs it loads, and LEN is rewritten, so the pack decodes it. Bytes before an STX are skipped; MAVLink 1 frames and unknown message ids pass through unchanged. The checksum is not checked |
| `whole` | the whole unit: one datagram, one file, one publication, or one XML or JSON document read to the end of the input. Also written `datagram`, `file` or `document` |

Two options follow a framing after a comma:

| Option | Means |
|---|---|
| `max=<bytes>` | the largest message; default 16777216. A larger one is an error, so a framer's buffer is bounded |
| `hex` | a binary message is hexadecimal text inside the frame, for example `newline,hex` |

A framing other than `whole` on a `udp:`, `dir:`, `mqtt:` or `zenoh:` endpoint
applies inside each datagram, file or publication.

## Failure

A message that does not convert is never passed through and never dropped
without a record.

- Each failure is counted under the engine's error name (`malformed-wire`,
  `no-kind`, `transform-decode`, ...) or the adapter's (`frame-truncated`,
  `frame-oversize`, `frame-desync`, `not-utf8`, `no-client`, `io`, ...). An
  engine error that has no name is counted as `unnamed`.
- Each failure is printed on stderr with the message number, where the message
  came from and the full error. After 10 failures of one name, further ones of
  that name are counted and not printed.
- `--on-error skip` (the default) goes on with the next message. `--on-error
  stop` stops at the first failure.
- A status line is printed on stderr every 10 seconds (`--status-every`):
  `in=3 converted=2 failed=1 [malformed-wire=1] 20s`. `in` counts messages
  received. `converted` and `failed` count per output, so one message to two
  outputs adds two.
- Wrong settings are refused before the first message: a format with no pack,
  a `--set` key that no loaded module declares, a framing that is missing.

| Exit status | Means |
|---|---|
| 0 | the input ended; every message was converted and delivered |
| 1 | stopped on a failure |
| 2 | the command line or the configuration is wrong |
| 3 | the input ended; some messages failed and were skipped |

There is no queue between the source and the sinks. The pipeline is one thread
that handles one message at a time, so a slow output slows the input. The only
buffers are one read of at most 64 KiB, one message per framer, and the
operating system's socket buffers.

## Options

| Option | Means |
|---|---|
| `--packs <dir>` | the packs directory |
| `--models <dir>` | the model modules; default `model/` beside the packs directory |
| `--packs-only` | load only the packs of the formats this command names, and only the model modules they use |
| `--max-distribution public\|controlled` | as `goat-xf` |
| `--from-format <format>`, `--in <uri>`, `--in-frame <framing>` | the input |
| `--out <uri>`, `--to-format <format>`, `--out-frame <framing>` | an output. `--to-format` and `--out-frame` before the first `--out` are the default for every output; after an `--out` they apply to that output |
| `--set <key>=<value>` | a model key the input does not carry, as `goat-xf convert --set` |
| `--set-receive-time <key>` | give this integer model key the time the message was received, in epoch milliseconds, when the message has no value for it |
| `--on-error skip\|stop`, `--status-every <seconds>` | see Failure |
| `--config <file>` | read options from a file |

A configuration file holds the same options, one per line, without the dashes.
A `#` at the start of a line or after white space starts a comment; a value
with a space or a `#` in it is written in double quotes.

```
# CoT events from the radio network, as GeoJSON for the map and as files
from-format cot-xml
packs       packs
packs-only
in          udp://239.2.3.1:6969?iface=192.0.2.7
on-error    skip

out         tcp-listen://:9000
  to-format geojson
  out-frame newline

out         "dir:archive?ext=xml&prefix=cot-"
  to-format cot-xml
```

Measured on the packs of this repository, release build: loading every pack and
model module takes about 14 seconds of processor time (the same as `goat-xf`),
and `--packs-only` with two formats takes less than 0.1 second.

## Worked examples

The output below is copied from runs of the release build in this repository.

### 1. Cursor on Target over UDP, GeoJSON lines for TCP clients

```bash
goat-xf-pipe --packs packs --packs-only --status-every 2 \
  --from-format cot-xml --in udp://127.0.0.1:4242 \
  --out tcp-listen://127.0.0.1:9000 --to-format geojson --out-frame newline
```

A client connected to port 9000, and three datagrams were sent to port 4242.
The second datagram was cut short. The client received two lines:

```json
{"type":"Feature","geometry":{"type":"Point","coordinates":[-85.9578182,30.0090027,-42.6]},"properties":{"type":"a-f-G-U-C","time_ms":1614456000000,"how":"m-g","ce":45.3,"le":99.5,"callsign":"GATOR"},"id":"J-01334"}
{"type":"Feature","geometry":{"type":"Point","coordinates":[-85.9578182,30.0090027,-42.6]},"properties":{"type":"a-f-G-U-C","time_ms":1614456000000,"how":"m-g","ce":45.3,"le":99.5,"callsign":"GATOR"},"id":"J-01335"}
```

stderr:

```
goat-xf-pipe: cot-xml from udp://127.0.0.1:4242 -> geojson to tcp-listen://127.0.0.1:9000; on-error skip
goat-xf-pipe: FAILED message 2 from 127.0.0.1:59408 -> geojson: malformed-wire: xml: unexpected end in tag <point>
goat-xf-pipe: in=3 converted=2 failed=1 [malformed-wire=1] 2s
```

### 2. A file of length-prefixed ASTERIX blocks, to two outputs

`blocks.bin` holds five ASTERIX category 062 data blocks (the inputs of vectors
01 to 05 of `packs/asterix-cat062`), each after a 2-byte big-endian length.
ASTERIX carries no track source, generation or date, so `--set` supplies the
first two and `--set-receive-time` supplies the time.

```bash
goat-xf-pipe --packs packs --packs-only \
  --from-format asterix-cat062 --in file:blocks.bin --in-frame len:2:be \
  --set uid=311 --set track.source_id=sensor-a --set track.generation=generation-1 \
  --set-receive-time time_ms \
  --out file:tracks.jsonl --to-format canonical-track-v2 --out-frame newline \
  --out 'dir:geo?ext=geojson&prefix=trk-' --to-format geojson
```

stderr, and the exit status 0:

```
goat-xf-pipe: asterix-cat062 from file:blocks.bin -> canonical-track-v2 to file:tracks.jsonl, geojson to dir:geo?ext=geojson&prefix=trk-; on-error skip
goat-xf-pipe: done: in=5 converted=10 failed=0 0s
```

`tracks.jsonl` has five lines. The fourth:

```json
{"apiVersion":"billie.dev/track-v2","kind":"Track","trackId":"311","sourceId":"sensor-a","trackGeneration":"generation-1","simulated":false,"confirmed":true,"coasting":false,"finalUpdate":false,"observedAt":"2026-11-16T10:21:10.114Z","position":{"latitudeDeg":56.94960057735443,"longitudeDeg":24.105200171470642,"altitudeM":-99.06},"velocity":{"eastMps":250.75,"northMps":-3.5}}
```

`geo/` holds `trk-000001.geojson` to `trk-000005.geojson`. The second:

```json
{"type":"Feature","geometry":{"type":"Point","coordinates":[0,0,152.4]},"properties":{"time_ms":1794824470113,"course":288.7780332224455,"speed_ms":13.202745926510893},"id":"311"}
```

### 3. Hexadecimal text on standard input, one message that fails

Two Remote ID messages as hexadecimal text, one per line. The second is 5 bytes
and a Remote ID message is 25.

```bash
printf '%s\n' 02223132333435363738393031323334353637383930000000 0222313233 \
  | goat-xf-pipe --packs packs --packs-only \
      --from-format remote-id --in stdin: --in-frame newline,hex \
      --out stdout: --to-format geojson --out-frame newline
```

stdout:

```json
{"type":"Feature","geometry":null,"properties":{},"id":"12345678901234567890"}
```

stderr, and the exit status 3:

```
goat-xf-pipe: remote-id from stdin: -> geojson to stdout:; on-error skip
goat-xf-pipe: FAILED message 2 -> geojson: malformed-wire: format `remote-id`: input is 5 bytes, need 25 (25 words of 1)
goat-xf-pipe: done, WITH FAILURES: in=2 converted=1 failed=1 [malformed-wire=1] 0s
```

### 4. Blocks whose length is inside the header

An ASTERIX data block starts with a 1-byte category, then a 2-byte big-endian
length that counts the whole block. With no start byte to look for, the framing
is `at:1:len:2:be:whole`: a length of 2 bytes, big-endian, at offset 1, that
counts the whole frame. `two-cat011.bin` holds the input of vector 07 of
`packs/asterix-cat011` twice. Each copy is 20 bytes, starting with `0b 0014`.

```bash
printf '0b0014092021c71c72a9111111000464b2c34c60%.0s' 1 2 | xxd -r -p > two-cat011.bin
goat-xf-pipe --packs packs --packs-only \
  --from-format asterix-cat011 --in file:two-cat011.bin --in-frame at:1:len:2:be:whole \
  --out stdout: --to-format geojson --out-frame newline
```

stdout, the vector's `expect` once per block:

```json
{"type":"Feature","geometry":{"type":"Point","coordinates":[-122.25000000558794,47.50000001862645]},"properties":{"callsign":"AFR2041"}}
{"type":"Feature","geometry":{"type":"Point","coordinates":[-122.25000000558794,47.50000001862645]},"properties":{"callsign":"AFR2041"}}
```

stderr, and the exit status 0:

```
goat-xf-pipe: asterix-cat011 from file:two-cat011.bin -> geojson to stdout:; on-error skip
goat-xf-pipe: done: in=2 converted=2 failed=0 0s
```

`start:0x0b:len:2:be:total` reads the same file. Use `at:` when the frame has
no byte to search for: a JREAP-C application block on TCP is
`at:2:len:2:be:whole`.

### 5. A carrier of several messages

One input message can hold a run of messages (`inner <format> run`,
[docs/using.md](using.md), "A carrier that holds several messages"). The input
is vector 01 of `packs/conformance-run-c-xy`: one carrier with two messages.

```bash
echo 040102030409 | goat-xf-pipe --packs packs --packs-only \
  --from-format conformance-run-c-xy --in stdin: --in-frame newline,hex \
  --out stdout: --to-format conformance-run-json --out-frame newline
```

stdout, one frame per message:

```json
{"w":9,"x":1,"y":2}
{"w":9,"x":3,"y":4}
```

stderr, and the exit status 0. One message in, two converted:

```
goat-xf-pipe: conformance-run-c-xy from stdin: -> conformance-run-json to stdout:; on-error skip
goat-xf-pipe: done: in=1 converted=2 failed=0 0s
```

`--packs-only` loads `conformance-run-in-xy` as well, because the carrier's
`inner` line names it.

## Writing a new adapter

A new transport is a `Source`, a `Sink`, or both, from `goat-adapters-core`:

```rust
pub trait Source: Send {
    /// One message, `Idle` when nothing arrived within a short timeout, or `End`.
    fn recv(&mut self) -> Result<Recv, AdapterError>;
    fn describe(&self) -> String;
}

pub trait Sink: Send {
    /// One converted message, without framing. Returns when the transport has taken it.
    fn send(&mut self, bytes: &[u8], meta: &Meta) -> Result<(), AdapterError>;
    fn flush(&mut self) -> Result<(), AdapterError> { Ok(()) }
    fn describe(&self) -> String;
}

pub trait Framer: Send {
    fn push(&mut self, bytes: &[u8]);
    fn next(&mut self) -> Result<Option<Vec<u8>>, AdapterError>;
    fn finish(&mut self) -> Result<Option<Vec<u8>>, AdapterError>;
    fn wrap(&self, msg: &[u8], out: &mut Vec<u8>) -> Result<(), AdapterError>;
}
```

The rules an adapter follows:

1. A source yields a `Message`: the bytes of exactly one message, the time it
   was received, where it came from (`origin`), and any model keys only the
   adapter knows (`context`, given to the engine with `--set`).
2. A source on a socket sets a read timeout of about 200 ms and returns
   `Recv::Idle` when it passes, so the pipeline can stop while no message
   arrives.
3. A transport with its own message boundaries (a datagram, a publication)
   gives each unit to `frame::frame_unit` with the stated framer; the default
   is `whole`. A stream reads into `Framer::push` and yields from
   `Framer::next`, then calls `Framer::finish` at the end of the stream.
4. An error has a short name (`AdapterError::kind`) and says whether the
   adapter can continue (`fatal`). An adapter never returns a message it could
   not frame.
5. No unbounded buffer. Keep at most the messages of one read.

To add the transport to the command line, put it in its own crate, implement
`goat_adapters_std::uri::Scheme` (a scheme name, a line of help, `source` and
`sink` from a parsed URI), and write a `main` of one statement:

```rust
fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    std::process::exit(goat_adapters_std::cli::run("goat-xf-pipe-mqtt", &args, &[&goat_adapters_mqtt::Mqtt]));
}
```

The tool then has every option and endpoint of `goat-xf-pipe` and the new
scheme. `adapters/mqtt` is the worked example: one file of about 400 lines, no dependency.

A new framing is a `Framer` and a line in `Framing::parse`
(`adapters/core/src/frame.rs`).

## The crates

| Crate | Holds | Dependencies | Status |
|---|---|---|---|
| `adapters/core` (`goat-adapters-core`) | `Source`, `Sink`, `Message`, `AdapterError`; the framers and `Framing::parse`; `Formats` (the engine and which formats are binary); `Pipeline`, `Stats`, `OnError` | the engine | Built, 14 tests |
| `adapters/std` (`goat-adapters-std`) | the standard-library endpoints, URI parsing, the command line as a function, the `goat-xf-pipe` tool | `goat-adapters-core` | Built, 29 tests |
| `adapters/mqtt` (`goat-adapters-mqtt`) | MQTT 3.1.1 at QoS 0 over plain TCP, written from the OASIS specification; `goat-xf-pipe-mqtt` | `goat-adapters-std` | Built, 8 tests against a broker inside the test; not run against a broker product |
| `adapters/zenoh` (`goat-adapters-zenoh`) | a Zenoh subscriber and `put`; `goat-xf-pipe-zenoh` | `goat-adapters-std`, `zenoh` 1.9.0 | Built, 2 tests; not built in CI |

Build and test:

```bash
cd adapters
cargo test                                   # core, std, mqtt
cargo build --release -p goat-adapters-std   # target/release/goat-xf-pipe
```

Measured: `goat-xf-pipe`, release build with link-time optimization and symbols
removed, is 1,181,088 bytes on `x86_64-unknown-linux-gnu`.

## Not built

- Reconnection of a TCP or MQTT connection that closes. The source ends or the
  run stops, and a supervisor restarts the tool.
- Watching a directory for new files. `dir:` reads the files present at start.
- TLS on TCP and MQTT. The standard library has none; such a transport is a
  separate crate under the rule above.
- MQTT QoS 1 and 2, retained messages and MQTT 5.
- A final summary when the tool is interrupted with a signal. The standard
  library has no signal handling; the periodic status line is the record.
- Framings for formats whose boundary needs more than a start byte and a
  length, such as byte stuffing or a checksum. `docs/design.md` lists "framed
  binary" as a designed wire type.
