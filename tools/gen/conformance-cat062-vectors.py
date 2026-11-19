#!/usr/bin/env python3
"""Write the vectors of the pack `asterix-cat062` and the vectors that convert
`canonical-track-v2` to it.

The blocks named OB_* are outputs of the CAT062 encoder of USAREUR-AF/open-billie
(runtime/rust/translator/src/cat062.rs, Apache-2.0, commit 19fccdb), produced
by running its `encode_for_kid` on the `sample()` track of its tests and on
variants of it. The first two are the cases its tests assert. Every other
expected value is worked out here from EUROCONTROL-SPEC-0149-9 Edition 1.21
and the pack layout. Nothing calls a goat-transformers engine.

Inputs: none; every value is stated in this file. Writes, under --out, the
vector files named above. The same run always gives the same bytes. With
--check nothing is written and the exit status is 1 when a committed file
differs from what this script writes.

Usage: python3 -I tools/gen/conformance-cat062-vectors.py [--out DIR] [--check]
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402



def build(sink):
    """Write every vector through the Output `sink`; {pack: number of files}."""
    written = {}

    CAT, CT = "asterix-cat062", "canonical-track-v2"
    OB = "USAREUR-AF/open-billie runtime/rust/translator/src/cat062.rs (Apache-2.0), commit 19fccdb"


    def vec(pack, num, name, frm, to, inp, expect=None, error=None, model=None, context=None, reference=None):
        d = {"name": name, "from": frm, "to": to, "input": inp}
        if context is not None:
            d["context"] = context
        if error:
            d["expect_error"] = error
        else:
            d["expect"] = expect
        if model:
            d["model"] = model
        if reference:
            d["source"] = OB
            d["reference"] = reference
        sink.write("packs/%s/vectors/%s" % (pack, "%02d-%s.json" % (num, name)), json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written[pack] = written.get(pack, 0) + 1


    def hx(s):
        return s.replace(" ", "")


    def num(x):
        """A model float in the text a vector holds."""
        return repr(float(x)) if x != int(x) else str(int(x))


    # --------------------------------------------------------------------------
    # Blocks the open-billie encoder writes (SAC 1, SIC 7 as the node default)
    # --------------------------------------------------------------------------
    # sample(): trackId 311, 2025-10-29T12:00:00.123Z, position 0 0 152.4 m,
    # velocity -12.5 east 4.25 north, confirmed, no other flag
    OB_SAMPLE = hx("3e 001f 9b0d10 0107 546010 00000000 00000000 ffce 0011 0137 81010100 0050")
    # sample() with simulated, confirmed false, coasting and finalUpdate
    OB_STATUS = hx("3e 001f 9b0d10 0107 546010 00000000 00000000 ffce 0011 0137 83c10180 0050")
    # sample() without velocity and without altitude
    OB_BARE = hx("3e 0018 990c 0107 546010 00000000 00000000 0137 81010100")
    # trackId 4095, 2026-03-01T23:59:59.250Z, position 56.9496 24.1052 -100 m,
    # velocity 250.75 east -3.5 north
    OB_RIGA = hx("3e 001f 9b0d10 0107 a8bfa0 00a1fd6f 004490df 03eb fff2 0fff 81010100 ffcc")
    # sample() at -33.9461 -151.1772, no velocity, headerSimulated
    OB_SOUTH = hx("3e 001b 990d10 0107 546010 ff9f7134 fe51fc1f 0137 81810100 0050")

    LSB = 180.0 / 2 ** 25         # I062/105
    FT = 381.0 / 200.0            # I062/130: 6.25 ft in metres


    def s32(h):
        v = int(h, 16)
        return v - (1 << 32) if v & (1 << 31) else v


    # ==========================================================================
    # asterix-cat062: decode and same-format round trip
    # ==========================================================================
    # FSPEC 9b 0d 10: FRN 1, 4, 5, 7 and the extension bit; FRN 12, 13 and the
    # extension bit; FRN 18. Time 0x546010 = 5529616 / 128 = 43200.125 s. Vx -50,
    # Vy 17 quarter metres per second. Status 81 01 01 00: MON 1, CNF 0
    # (confirmed), three extensions, every other bit 0. Altitude 80 * 1.905 m.
    vec(CAT, 1, "open-billie-sample-roundtrip", CAT, CAT, OB_SAMPLE, OB_SAMPLE,
        model={"@kind": "track", "cat062.sac": "1", "cat062.sic": "7", "cat062.time_of_day_s": "43200.125", "lat": "0", "lon": "0",
               "track.vel_east_ms": "-12.5", "track.vel_north_ms": "4.25", "cat062.track_number": "311", "cat062.mon": "1",
               "cat062.cnf": "0", "cat062.sim": "0", "cat062.tse": "0", "cat062.cst": "0",
               "track.confirmed": "1", "track.simulated": "0", "track.final_update": "0", "track.coasting": "0", "hae": num(80 * FT)},
        reference="the block of the test encodes_minimal_cat062_uap_record_with_optional_items")
    # status 83 c1 01 80: CNF 1 (tentative), SIM 1, TSE 1, CST 1
    vec(CAT, 2, "open-billie-status-bits-roundtrip", CAT, CAT, OB_STATUS, OB_STATUS,
        model={"cat062.mon": "1", "cat062.cnf": "1", "cat062.sim": "1", "cat062.tse": "1", "cat062.cst": "1",
               "track.confirmed": "0", "track.simulated": "1", "track.final_update": "1", "track.coasting": "1"},
        reference="the block of the test maps_simulation_confirmation_coasting_and_final_update_status_bits")
    # FSPEC 99 0c: FRN 1, 4, 5 and the extension bit; FRN 12, 13
    vec(CAT, 3, "open-billie-no-velocity-no-altitude-roundtrip", CAT, CAT, OB_BARE, OB_BARE,
        model={"cat062.track_number": "311", "track.confirmed": "1", "lat": "0"},
        reference="encode_for_kid on sample() with velocity and altitude_m set to None")
    vec(CAT, 4, "open-billie-position-velocity-and-negative-altitude-roundtrip", CAT, CAT, OB_RIGA, OB_RIGA,
        model={"cat062.time_of_day_s": num(0xA8BFA0 / 128.0), "lat": repr(0x00A1FD6F * LSB), "lon": repr(0x004490DF * LSB),
               "track.vel_east_ms": "250.75", "track.vel_north_ms": "-3.5", "cat062.track_number": "4095", "hae": num(-52 * FT)},
        reference="encode_for_kid on sample() with trackId 4095, observedAt 2026-03-01T23:59:59.250Z, position 56.9496 24.1052 -100 m, velocity 250.75 east -3.5 north")
    vec(CAT, 5, "open-billie-southern-and-western-position-roundtrip", CAT, CAT, OB_SOUTH, OB_SOUTH,
        model={"lat": repr(s32("ff9f7134") * LSB), "lon": repr(s32("fe51fc1f") * LSB), "track.simulated": "1", "hae": num(80 * FT)},
        reference="encode_for_kid on sample() at -33.9461 -151.1772 with no velocity and headerSimulated true")
    # A status of one octet, 80: MON 1, CNF 0, no extension. SIM, TSE and CST are
    # absent after decode. Their flags have defaults, and a key with a default
    # counts as present: encode writes the first part and three extents. LEN goes
    # from 21 to 24.
    SHORT = hx("3e 0015 990c 0107 546010 00000000 00000000 0137 80")
    vec(CAT, 6, "status-of-one-octet-is-written-with-the-default-extents", CAT, CAT, SHORT, OB_BARE,
        model={"cat062.mon": "1", "cat062.cnf": "0", "track.confirmed": "1"})
    # A status of the first part and all six extents. Extents four to six are
    # read and hold no key; no line after the third extent has a present key, so
    # encode ends the item there. LEN goes from 27 to 24.
    vec(CAT, 7, "status-extents-four-to-six-read-and-not-written", CAT, CAT,
        hx("3e 001b 990c 0107 546010 00000000 00000000 0137 81010101010100"), OB_BARE, model={"track.coasting": "0"})
    # FSPEC a0: FRN 1 and FRN 3 (I062/015). No `if` block names fspec.3
    vec(CAT, 8, "item-the-pack-does-not-map", CAT, CAT, hx("3e 0007 a0 0107 05"), error="malformed-wire")
    vec(CAT, 9, "category-is-not-62", CAT, CAT, "30" + OB_SAMPLE[2:], error="no-kind")
    # LEN says 31 octets and 30 are given
    vec(CAT, 10, "block-shorter-than-len", CAT, CAT, OB_SAMPLE[:-2], error="malformed-wire")
    # octets after the data block are not read
    vec(CAT, 11, "input-beyond-len-is-ignored", CAT, CAT, OB_SAMPLE + OB_BARE, OB_SAMPLE, model={"hae": num(80 * FT)})

    # to canonical-track-v2: the caller supplies what CAT062 does not hold
    T0 = datetime.datetime(2025, 10, 29, 12, 0, 0, 123000, tzinfo=datetime.timezone.utc)
    T0_MS = str(int(T0.timestamp()) * 1000 + 123)
    vec(CAT, 12, "to-canonical-track-v2-with-context", CAT, CT, OB_SAMPLE,
        '{"apiVersion":"billie.dev/track-v2","kind":"Track","trackId":"311","sourceId":"sensor-a","trackGeneration":"generation-1",'
        '"simulated":false,"confirmed":true,"coasting":false,"finalUpdate":false,"observedAt":"2025-10-29T12:00:00.123Z",'
        '"position":{"latitudeDeg":0,"longitudeDeg":0,"altitudeM":152.4},"velocity":{"eastMps":-12.5,"northMps":4.25}}',
        context={"uid": "311", "track.source_id": "sensor-a", "track.generation": "generation-1", "time_ms": T0_MS})
    # without them the target has no kind the entity satisfies
    vec(CAT, 13, "to-canonical-track-v2-without-context", CAT, CT, OB_SAMPLE, error="no-kind")

    # ==========================================================================
    # canonical-track-v2 to asterix-cat062, against the open-billie encoder. The
    # caller supplies SAC and SIC. model/cat062.def derives the time of day from
    # observedAt, the track number from trackId and SIM from the three flags.
    # ==========================================================================
    CTX = {"cat062.sac": "1", "cat062.sic": "7"}


    def track(**over):
        """The `sample()` track of the open-billie tests as Canonical Track v2."""
        t = {
            "apiVersion": "billie.dev/track-v2", "kind": "Track", "trackId": "311", "sourceId": "sensor-a",
            "trackGeneration": "generation-1", "testData": False, "headerSimulated": False, "simulated": False,
            "confirmed": True, "coasting": False, "finalUpdate": False, "observedAt": "2025-10-29T12:00:00.123Z",
            "position": {"latitudeDeg": 0.0, "longitudeDeg": 0.0, "altitudeM": 152.4},
            "velocity": {"eastMps": -12.5, "northMps": 4.25, "upMps": 1.5},
            "classification": "uas", "confidence": 0.87,
            "positionUncertainty": {"sigmaEastM": 3.2, "sigmaNorthM": 2.8, "sigmaUpM": 6.1},
        }
        for k, v in over.items():
            if v is None:
                del t[k]
            else:
                t[k] = v
        return json.dumps(t, separators=(",", ":"))


    SAME = "byte for byte the block the open-billie encoder writes for this track"
    # 12:00:00.123 is 43200.123 s; times 128 and rounded, 5529616 = 0x546010
    vec(CT, 24, "to-asterix-cat062-open-billie-sample", CT, CAT, track(), OB_SAMPLE, context=CTX, reference=SAME,
        model={"@complete": True, "cat062.time_of_day_s": "43200.123", "cat062.track_number": "311", "cat062.sim": "0"})
    vec(CT, 25, "to-asterix-cat062-status-bits", CT, CAT, track(simulated=True, confirmed=False, coasting=True, finalUpdate=True), OB_STATUS,
        context=CTX, reference=SAME)
    vec(CT, 26, "to-asterix-cat062-no-velocity-no-altitude", CT, CAT,
        track(velocity=None, position={"latitudeDeg": 0.0, "longitudeDeg": 0.0}), OB_BARE, context=CTX, reference=SAME)
    # the pack computes x * 2^25 / 180 and the encoder x * (2^25 / 180): the same
    # integer for these values
    for deg, raw in ((56.9496, 0x00A1FD6F), (24.1052, 0x004490DF)):
        assert round(deg * 2 ** 25 / 180) == raw == round(deg * (2 ** 25 / 180.0))
    vec(CT, 27, "to-asterix-cat062-position-velocity-and-negative-altitude", CT, CAT,
        track(trackId="4095", observedAt="2026-03-01T23:59:59.250Z", position={"latitudeDeg": 56.9496, "longitudeDeg": 24.1052, "altitudeM": -100.0},
              velocity={"eastMps": 250.75, "northMps": -3.5}), OB_RIGA, context=CTX, reference=SAME)
    # headerSimulated is true and simulated is false: SIM is 1, from `any`
    vec(CT, 28, "to-asterix-cat062-header-simulated-sets-sim", CT, CAT,
        track(headerSimulated=True, velocity=None, position={"latitudeDeg": -33.9461, "longitudeDeg": -151.1772, "altitudeM": 152.4}),
        OB_SOUTH, context=CTX, reference=SAME, model={"@complete": True, "cat062.sim": "1", "track.simulated": "0"})
    # simulated, coasting, finalUpdate, testData and headerSimulated are absent:
    # the defaults of the pack write them 0, in the first part and three extents
    vec(CT, 29, "to-asterix-cat062-absent-flags-write-the-defaults", CT, CAT,
        track(simulated=None, coasting=None, finalUpdate=None, testData=None, headerSimulated=None, velocity=None,
              position={"latitudeDeg": 0.0, "longitudeDeg": 0.0}), OB_BARE, context=CTX, reference=SAME)
    # no SAC and SIC: the kind's `requires` do not hold
    vec(CT, 30, "to-asterix-cat062-without-context", CT, CAT, track(), error="no-kind")
    # confirmed is absent: I062/080 cannot say confirmed or tentative
    vec(CT, 31, "to-asterix-cat062-without-confirmed", CT, CAT, track(confirmed=None), error="no-kind", context=CTX)
    # trackId is not a decimal number: no track number
    vec(CT, 32, "to-asterix-cat062-track-id-that-is-not-a-number", CT, CAT, track(trackId="track-311"), error="no-kind", context=CTX)

    return written


def main(argv=None):
    return genio.vector_main('conformance-cat062-vectors.py', __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
