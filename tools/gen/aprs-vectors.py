#!/usr/bin/env python3
"""Write the vectors of packs/aprs from records built here, with the expected
values derived by this program from the APRS Protocol Reference 1.0.1 layout
(no engine is run; the records are invented for the vectors, not taken from
the reference). Python 3 standard library only.

Usage: python3 -I tools/gen/aprs-vectors.py [<checkout>]   (default: this checkout)

Every record is a TNC2 monitor line SOURCE>DEST,PATH:INFO. The round-trip
vectors expect the record back unchanged (spec 0.10, ruling 1: no terminator,
fields as the pack writes them); `model` holds the parts this program cuts from
the information field by the reference's columns.
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..")) if len(sys.argv) < 2 else sys.argv[1]
OUT = os.path.join(ROOT, "packs", "aprs", "vectors")
HDR = "N0CALL-7>APZ001,WIDE1-1,WIDE2-1"     # N0CALL is the conventional placeholder call


def uncompressed(lat, ns, table, lon, ew, code):
    assert len(lat) == 7 and len(lon) == 8 and lat[4] == "." and lon[5] == "."
    return lat + ns + table + lon + ew + code


def unc_model(info, off):
    p = info[off:off + 19]
    return [("aprs.lat_text", p[0:7].rstrip(" ")), ("aprs.lat_hemisphere", p[7]), ("aprs.symbol_table", p[8]),
            ("aprs.lon_text", p[9:17].rstrip(" ")), ("aprs.lon_hemisphere", p[17]), ("aprs.symbol_code", p[18])]


def cmp_model(info, off):
    p = info[off:off + 13]
    return [("aprs.symbol_table", p[0]), ("aprs.lat_base91", p[1:5]), ("aprs.lon_base91", p[5:9]),
            ("aprs.symbol_code", p[9]), ("aprs.compressed_cs", p[10:12].rstrip(" ")), ("aprs.compression_type", p[12])]


CASES = []


def case(name, kind, info, model, source):
    CASES.append((name, kind, HDR + ":" + info, model, source))


pos = uncompressed("3754.21", "N", "/", "12226.40", "W", ">")
case("rt-position", "position", "!" + pos + "en route", [("aprs.header", HDR)] + unc_model("!" + pos, 1),
     "an uncompressed position report without time stamp (data type !)")
case("rt-position-messaging", "position-messaging", "=" + pos, unc_model("=" + pos, 1),
     "the same position from a station with messaging (data type =)")
amb = uncompressed("3754.  ", "N", "/", "12226.  ", "W", "-")
case("rt-position-ambiguity", "position", "!" + amb, unc_model("!" + amb, 1),
     "position ambiguity: the last two digits of each minutes field are spaces; the dots remain")
ts = "181530z"
case("rt-position-time", "position-time", "/" + ts + pos + "078/012",
     [("aprs.timestamp", ts)] + unc_model("/" + ts + pos, 8),
     "a position with a day-hour-minute zulu time stamp, then a course/speed extension kept in aprs.info")
ts2 = "093011h"
case("rt-position-time-messaging", "position-time-messaging", "@" + ts2 + pos,
     [("aprs.timestamp", ts2)] + unc_model("@" + ts2 + pos, 8), "an hour-minute-second time stamp (data type @)")
comp = "/" + "4Jq9" + "Rs(T" + ">" + "C1" + "G"
case("rt-compressed", "compressed", "!" + comp + " mobile", cmp_model("!" + comp, 1),
     "a compressed position: table, four base-91 characters each of latitude and longitude, code, cs, type")
case("rt-compressed-messaging", "compressed-messaging", "=" + comp, cmp_model("=" + comp, 1), "compressed, data type =")
case("rt-compressed-time", "compressed-time", "/" + ts + comp, [("aprs.timestamp", ts)] + cmp_model("/" + ts + comp, 8),
     "compressed, with a time stamp")
case("rt-compressed-time-messaging", "compressed-time-messaging", "@" + ts2 + comp,
     [("aprs.timestamp", ts2)] + cmp_model("@" + ts2 + comp, 8), "compressed, time stamp, data type @")
obj = "WATERSTN1" + "*" + ts
case("rt-object", "object", ";" + obj + pos + "aid station",
     [("aprs.object_name", "WATERSTN1"), ("aprs.object_state", "*"), ("aprs.timestamp", ts)] + unc_model(";" + obj + pos, 18),
     "a live object with an uncompressed position")
obj2 = "TENT 3   " + "_" + ts
case("rt-object-compressed", "object-compressed", ";" + obj2 + comp,
     [("aprs.object_name", "TENT 3"), ("aprs.object_state", "_")] + cmp_model(";" + obj2 + comp, 18),
     "a killed object with a compressed position; the name's padding is trimmed in the model")
case("rt-status", "status", ">net control on air", [("aprs.info", ">net control on air")], "a status report")
CASES.append(("rt-message", "message", HDR + "::BLN1     :field day saturday{42",
              [("aprs.addressee_field", "BLN1     "), ("aprs.addressee", "BLN1"), ("aprs.message_text", "field day saturday{42")],
              "a message: the identifier is a colon, so field 1 is empty; addressee padded to nine, then the text"))
CASES.append(("rt-message-colon-in-text", "message", HDR + "::N0CALL-9 :meet at 10:30",
              [("aprs.message_text", "meet at 10")],
              "a colon in the message text starts a further field: it is residue, written back unchanged"))
case("rt-position-colon-in-comment", "position", "!" + pos + "see you at 2:15",
     unc_model("!" + pos, 1) + [("aprs.info", "!" + pos + "see you at 2")],
     "a colon in a comment: aprs.info ends there and the rest is residue, written back")


def vec(name, inp, expect=None, model=None, error=None, source=None):
    v = collections.OrderedDict([("name", "aprs-" + name), ("from", "aprs"), ("to", "aprs")])
    if source:
        v["source"] = "tools/gen/aprs-vectors.py: " + source
    v["input"] = inp
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    return v


def main():
    os.makedirs(OUT, exist_ok=True)
    files = []
    for name, kind, rec, model, source in CASES:
        m = collections.OrderedDict([("@kind", kind)] + list(model))
        files.append((name, vec(name, rec, rec, m, source=source)))
    rec = HDR + ":!" + pos
    files.append(("rt-terminator", vec("rt-terminator", rec + "\r\n", rec, collections.OrderedDict([("@kind", "position")]),
                                         source="a CR LF at the end is removed on decode and not written (spec 0.10, step 1)")))
    files.append(("err-unknown-type", vec("err-unknown-type", HDR + ":T#005,123,045,000,255,000,00000000", error="no-kind",
                                           source="a telemetry report (data type T): no kind of this pack")))
    files.append(("err-control-character", vec("err-control-character", HDR + ":>status\x07", error="malformed-wire",
                                                source="a character outside 0x20 to 0x7E (spec 0.10, step 2)")))
    keep = {"%s.json" % n for n, _ in files}
    for f in os.listdir(OUT):
        if f.endswith(".json") and f not in keep:
            os.remove(os.path.join(OUT, f))
    for n, v in files:
        assert v["from"] == "aprs"
        with open(os.path.join(OUT, n + ".json"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps(v, indent=2) + "\n")
    print("aprs-vectors: %d vectors" % len(files))


if __name__ == "__main__":
    main()
