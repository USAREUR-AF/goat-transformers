#!/usr/bin/env python3
"""The hand-written vectors of packs gtfs-realtime-entity, gtfs-realtime, sparkplug-b and
meshtastic, and two vectors from geojson into gtfs-realtime-entity.

Python standard library only; it imports no engine and no generator. Each message is
written here field by field with a protobuf encoder of a few lines (varint, zig-zag is not
needed, fixed32, fixed64, length-delimited). The expected output of each vector is worked
out from the rules of spec/engine-spec.md, not by running a conversion:

- protobuf output is canonical (0.3): only mapped fields, ascending field numbers inside
  every message and every item, so an input written in that order with mapped fields only
  is its own expected output, and a field no line maps is left out;
- a pfloat value is the IEEE-754 single nearest to the model float (0.3), widened back to
  a double on decode;
- geojson output (Canonicalisation) has the members in the order of packs/geojson's
  `field` lines inside the layout `type`, `geometry`, `properties`, `id`, and numbers in
  their shortest round-trip form (Python's repr of a double is that form).

Run after tools/gen/protobuf-public-run.sh:

  python3 -I tools/gen/protobuf-public-vectors.py [--out DIR] [--check]

With --check nothing is written and the exit status is 1 when a committed vector
is not what this script writes.
"""
import json
import os
import struct
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402


SINK = None
WRITTEN = {}


def build(sink):
    """Write every vector through the Output `sink`; {pack: number of files}."""
    global SINK
    SINK = sink
    WRITTEN.clear()
    # --- encoder -----------------------------------------------------------------

    def varint(n):
        n &= (1 << 64) - 1          # a negative int32 or int64 is ten bytes (two's complement)
        out = bytearray()
        while True:
            b = n & 0x7F
            n >>= 7
            if n:
                out.append(b | 0x80)
            else:
                out.append(b)
                return bytes(out)


    def key(num, wt):
        return varint(num << 3 | wt)


    def V(num, n):                  # varint field
        return key(num, 0) + varint(n)


    def F32(num, x):                # fixed32 holding an IEEE-754 single
        return key(num, 5) + struct.pack("<f", x)


    def U32(num, n):                # fixed32 holding an unsigned integer
        return key(num, 5) + struct.pack("<I", n)


    def F64(num, x):
        return key(num, 1) + struct.pack("<d", x)


    def L(num, *parts):             # length-delimited: a submessage of parts, or bytes
        body = b"".join(p.encode("utf-8") if isinstance(p, str) else p for p in parts)
        return key(num, 2) + varint(len(body)) + body


    def S(num, text):
        return L(num, text.encode("utf-8"))


    def single(x):
        """The double a pfloat decode yields for the model float x."""
        return struct.unpack("<f", struct.pack("<f", x))[0]


    def num(x):
        """A double as geojson writes it: shortest round-trip, integral values with no point
        only when the double is integral and written so by the shortest form."""
        r = repr(x)
        return r[:-2] if r.endswith(".0") else r


    def write(pack, name, frm, to, inp, expect=None, error=None, model=None, context=None):
        v = {"name": name, "from": frm, "to": to, "input": inp}
        if context is not None:
            v["context"] = context
        if error is None:
            v["expect"] = expect
        else:
            v["expect_error"] = error
        if model:
            v["model"] = model
        SINK.write("packs/%s/vectors/%s.json" % (pack, name), json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        WRITTEN[pack] = WRITTEN.get(pack, 0) + 1


    # --- gtfs-realtime-entity ------------------------------------------------------

    LAT, LON, SPEED, BEARING = 52.52, 13.405, 8.5, 90.0
    TS = 1700000000

    position = L(2, F32(1, LAT), F32(2, LON), F32(3, BEARING), F32(5, SPEED))
    descriptor = L(8, S(1, "bus-7"), S(2, "42"))
    vehicle = L(4, position, V(5, TS), descriptor)
    entity = S(1, "e1") + vehicle

    write("gtfs-realtime-entity", "01-vehicle-to-geojson-single-precision", "gtfs-realtime-entity", "geojson",
          entity.hex(),
          expect='{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},'
                 '"properties":{"callsign":"42","speed_ms":%s},"id":"bus-7"}'
                 % (num(single(LON)), num(single(LAT)), num(single(SPEED))),
          model={"@kind": "vehicle", "uid": "bus-7", "callsign": "42", "lat": repr(single(LAT)),
                 "lon": repr(single(LON)), "speed_ms": "8.5", "gtfsrt.id": "e1",
                 "gtfsrt.position_bearing": "90", "gtfsrt.vehicle_timestamp": str(TS)})

    write("gtfs-realtime-entity", "02-vehicle-roundtrip", "gtfs-realtime-entity", "gtfs-realtime-entity",
          entity.hex(), expect=entity.hex(),
          model={"@kind": "vehicle", "uid": "bus-7", "gtfsrt.vehicle_vehicle_id": "bus-7"})

    # A field in an extension range of Position (1000, varint) has no line: it is dropped.
    with_ext = S(1, "e1") + L(4, L(2, F32(1, LAT), F32(2, LON), F32(3, BEARING), F32(5, SPEED), V(1000, 7)),
                              V(5, TS), descriptor)
    write("gtfs-realtime-entity", "03-extension-field-dropped", "gtfs-realtime-entity", "gtfs-realtime-entity",
          with_ext.hex(), expect=entity.hex())

    # --- geojson into gtfs-realtime-entity ----------------------------------------

    gj = ('{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},'
          '"properties":{"callsign":"42","speed_ms":8.5},"id":"bus-7"}' % (num(LON), num(LAT)))
    # FeedEntity.id comes from the context; the shared keys go to their lines of kind vehicle.
    out = S(1, "e1") + L(4, L(2, F32(1, LAT), F32(2, LON), F32(5, SPEED)), L(8, S(1, "bus-7"), S(2, "42")))
    write("geojson", "91-to-gtfs-realtime-entity-id-from-context", "geojson", "gtfs-realtime-entity", gj,
          expect=out.hex(), context={"gtfsrt.id": "e1"},
          model={"uid": "bus-7", "lat": "52.52", "lon": "13.405"})

    write("geojson", "92-to-gtfs-realtime-entity-no-position", "geojson", "gtfs-realtime-entity",
          '{"type":"Feature","geometry":null,"properties":{"callsign":"42"},"id":"bus-7"}',
          error="no-kind", model={"uid": "bus-7", "callsign": "42"})

    # --- gtfs-realtime (FeedMessage) -----------------------------------------------

    feed = (L(1, S(1, "2.0"), V(2, 0), V(3, TS))
            + L(2, S(1, "e1"), L(4, L(2, F32(1, LAT), F32(2, LON)), L(8, S(1, "bus-7"))))
            + L(2, S(1, "e2"), L(4, L(2, F32(1, 48.25), F32(2, 16.375)), L(8, S(1, "tram-3")))))
    write("gtfs-realtime", "01-feed-two-vehicles-roundtrip", "gtfs-realtime", "gtfs-realtime",
          feed.hex(), expect=feed.hex(),
          model={"gtfsrt.header_gtfs_realtime_version": "2.0", "gtfsrt.header_incrementality": "0",
                 "gtfsrt.header_timestamp": str(TS), "gtfsrt.feed_message_entity.#": "2",
                 "gtfsrt.feed_message_entity[0].gtfsrt.feed_entity_id": "e1",
                 "gtfsrt.feed_message_entity[1].gtfsrt.feed_entity_vehicle_vehicle_id": "tram-3",
                 "gtfsrt.feed_message_entity[1].gtfsrt.feed_entity_vehicle_position_latitude": "48.25"})

    # --- sparkplug-b -----------------------------------------------------------------

    T = 1700000000000
    m1 = L(2, S(1, "Temperature"), V(2, 1), V(3, T), V(4, 9), F32(12, 21.5))     # datatype 9: Float
    m2 = L(2, V(2, 2), V(3, T), V(4, 11), V(14, 1))                                # datatype 11: Boolean
    pay_in = V(1, T) + m1 + m2 + V(3, 3) + L(5, b"\x01\x02")                       # body: bytes, no line
    pay_out = V(1, T) + m1 + m2 + V(3, 3)
    write("sparkplug-b", "01-data-roundtrip-body-dropped", "sparkplug-b", "sparkplug-b",
          pay_in.hex(), expect=pay_out.hex(),
          model={"sparkplug.payload_timestamp": str(T), "sparkplug.payload_seq": "3",
                 "sparkplug.payload_metrics.#": "2",
                 "sparkplug.payload_metrics[0].sparkplug.metric_name": "Temperature",
                 "sparkplug.payload_metrics[0].sparkplug.metric_float_value": "21.5",
                 "sparkplug.payload_metrics[1].sparkplug.metric_alias": "2",
                 "sparkplug.payload_metrics[1].sparkplug.metric_boolean_value": "1"})

    # --- meshtastic --------------------------------------------------------------------

    def packet(with_unmapped):
        parts = []
        if with_unmapped:
            parts.append(U32(1, 0xA1B2C3D4))                    # from: fixed32, no line
        dec = [V(1, 1)] + ([S(2, "hi")] if with_unmapped else [])   # portnum 1; payload: bytes, no line
        parts += [L(4, *dec), F32(8, 6.25), V(9, 3), V(12, -90), V(15, 3)]
        return L(1, *parts)


    env_in = packet(True) + S(2, "LongFast") + S(3, "!a1b2c3d4")
    env_out = packet(False) + S(2, "LongFast") + S(3, "!a1b2c3d4")
    write("meshtastic", "01-envelope-negative-rssi-fixed32-dropped", "meshtastic", "meshtastic",
          env_in.hex(), expect=env_out.hex(),
          model={"meshtastic.packet_rx_rssi": "-90", "meshtastic.packet_rx_snr": "6.25",
                 "meshtastic.packet_decoded_portnum": "1", "meshtastic.service_envelope_channel_id": "LongFast"})
    return dict(WRITTEN)


def main(argv=None):
    return genio.vector_main("protobuf-public-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
