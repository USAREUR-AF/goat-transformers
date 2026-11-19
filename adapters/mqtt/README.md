# goat-adapters-mqtt

Status: Built. 8 tests pass against a broker that runs inside the test. It has
not been run against a broker product.

MQTT as an input and an output of `goat-xf-pipe`, with no dependency: the
client is written from the MQTT 3.1.1 specification (OASIS Standard, 29 October
2014) with the standard library.

```bash
cargo build --release -p goat-adapters-mqtt
goat-xf-pipe-mqtt --packs packs --packs-only \
  --from-format cot-xml --in 'mqtt://broker.example/cot/#' \
  --out mqtt://broker.example/geo/tracks --to-format geojson
```

URI: `mqtt://<host>[:<port>]/<topic>[?client=<id>&user=<name>&password-env=<VARIABLE>&keepalive=<seconds>]`

| Part | Means |
|---|---|
| port | default 1883 |
| topic | as `--in`, a topic filter (`+` and `#` allowed); as `--out`, one topic |
| `client` | the client identifier; default a generated one of at most 23 characters |
| `user`, `password-env` | the user name, and the name of the environment variable that holds the password. A password is not written in a URI |
| `keepalive` | seconds, default 60. A subscription sends a ping at half this interval and stops with `mqtt-timeout` when the broker is silent for twice it |

One publication is one message. A framing stated with `--in-frame` applies
inside each publication.

| Implemented | Not implemented |
|---|---|
| CONNECT with a clean session, user name and password | TLS |
| SUBSCRIBE to one topic filter at QoS 0 | QoS 1 and 2 |
| PUBLISH at QoS 0, not retained | retained messages, wills |
| PINGREQ on an idle subscription | session resumption, reconnection, MQTT 5 |

At QoS 0 the broker does not confirm a publication, so `converted` counts
messages the broker's connection accepted, not messages a subscriber received.
