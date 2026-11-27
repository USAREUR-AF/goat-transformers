#!/usr/bin/env python3
"""golden-takproto: golden vectors for packs/cot-protobuf and packs/cot-xml from
takproto, a reference TAK Protocol Version 1 codec (shared-model hardening,
item 2: meaning is tested against an implementation outside this project, not
only engine agreement).

takproto converts Cursor on Target XML to a TAK protobuf message (its function
xml2proto) and parses one back (parse_proto), with the protobuf runtime as its
serializer. Its inputs here are CoT XML events: the one in takproto's own test
suite (tests/test_functions.py of the pinned sdist, refused unless the sdist's
SHA-256 is the one below), whose recorded protobuf bytes are also checked, and
the events in INPUTS below, written for this script so that every field
takproto maps is set at least once. Two kinds of vector are written:

  golden-pb-<n>.json   cot-protobuf to cot-protobuf, for every input:
      input    the TakMessage takproto writes (the 3-byte mesh header removed;
               the pack reads the bare message), lowercase hex
      expect   the same message in canonical form: takproto's message with any
               empty sub-message cleared, serialized by the protobuf runtime.
               takproto marks a sub-message present when it sets a field to its
               default value (a track with speed 0 and course 0); proto3 writes
               no field at its default, decode reads no key from an empty
               sub-message, and encode writes none
      model    "@kind" cot_event and every field takproto set, under the
               takproto module's keys, and the shared keys: time_ms (sendTime),
               hae, ce and le when set and not 9999999, and "@absent" for each
               of the three that is 9999999, the value CoT uses for not known

  golden-xml-<n>.json  cot-xml to cot-protobuf, for the inputs that hold only
      what both packs bind (RULE below): input the event as written, expect
      takproto's message in canonical form, model the shared keys cot-xml
      decodes, with the values takproto read

Every input has time and start, equal. The pack writes time_ms at both
sendTime and startTime, so an event with one of them, or with two that differ,
does not return unchanged (pack.md of cot-protobuf states it); build() refuses
such an input rather than skipping it.

  source    takproto, its version and the input's origin; no engine is run

takproto is MIT-licensed; it is run, not copied: none of its code is in this
repository. The recorded bytes of its test message enter as an input only.

Usage (takproto 3.0.1 and protobuf importable, as tools/gen/golden-takproto.txt
pins them with their hashes):

  python3 -I tools/gen/golden-takproto.py [--cache DIR]           write
  python3 -I tools/gen/golden-takproto.py --check [--cache DIR]   exit 1 when a
                                                                  vector differs
"""
import argparse
import ast
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKS = os.path.join(ROOT, "packs")
TAKPROTO = "3.0.1"
SDIST = ("https://files.pythonhosted.org/packages/source/t/takproto/takproto-3.0.1.tar.gz",
         "1a76c13d32783029dc64aaff9cd297abcd3f7ba3083225e82edd876d543ea476")
TEST_FILE = "takproto-3.0.1/tests/test_functions.py"
MESH = b"\xbf\x01\xbf"
SENTINEL = 9999999.0

# CoT XML events written for this script (origin "golden-takproto INPUTS"). Each sets
# fields takproto maps: event attributes, point, and the detail elements it reads
# (contact, __group, precisionlocation, status, takv, track) or keeps as text (others).
INPUTS = [
    # a full event, time and start equal, every point value set
    '<event version="2.0" uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" '
    'start="2021-02-27T20:00:00.000Z" stale="2021-02-27T20:03:00.000Z" how="m-g">'
    '<point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/>'
    '<detail><contact callsign="GATOR"/><track course="270" speed="40.25"/></detail></event>',
    # southern and eastern hemisphere, whole-number point values, no stale
    '<event version="2.0" uid="J-01335" type="a-h-G" time="2021-02-27T20:00:00.000Z" '
    'start="2021-02-27T20:00:00.000Z" how="h-e"><point lat="-33.8688" lon="151.2093" hae="58" ce="10" le="15"/>'
    '<detail><contact callsign="KOALA"/></detail></event>',
    # no detail, values with many decimals
    '<event version="2.0" uid="J-1" type="a-f-G" time="2021-02-27T20:00:00.000Z" '
    'start="2021-02-27T20:00:00.000Z" stale="2021-02-27T20:05:00.000Z" how="m-g">'
    '<point lat="0.000123456789" lon="-179.999999999" hae="-0.25" ce="0.125" le="1234.5678"/></event>',
    # track alone in the detail
    '<event version="2.0" uid="J-2" type="a-f-A" time="2021-02-27T19:59:00.000Z" start="2021-02-27T19:59:00.000Z" '
    'stale="2021-02-27T20:09:00.000Z" how="m-g"><point lat="1.5" lon="2.5" hae="3.5" ce="4.5" le="5.5"/>'
    '<detail><track course="359.75" speed="250.5"/></detail></event>',
    # point values not known (9999999), times without fraction
    '<event version="2.0" uid="KX7" type="a-f-G" time="2025-06-15T15:06:43Z" start="2025-06-15T15:06:43Z" '
    'stale="2025-06-15T15:16:43Z" how="m-g"><point lat="64.8378" lon="-147.7164" hae="136.5" ce="9999999" '
    'le="9999999"/><detail><contact callsign="KX7"/></detail></event>',
    # access, qos and opex
    '<event version="2.0" uid="ACC-1" type="a-n-G" time="2024-01-02T03:04:05.678Z" '
    'start="2024-01-02T03:04:05.678Z" stale="2024-01-02T03:14:05.678Z" how="m-g" access="Undefined" '
    'qos="1-r-c" opex="e-exercise"><point lat="48.137154" lon="11.576124" hae="519" ce="12" le="20"/>'
    '</event>',
    # contact endpoint, group, status, takv, precision location, track
    '<event version="2.0" uid="ANDROID-0123456789" type="a-f-G-U-C" time="2023-05-06T07:08:09.100Z" '
    'start="2023-05-06T07:08:09.100Z" stale="2023-05-06T07:14:09.100Z" how="m-g">'
    '<point lat="38.8895" lon="-77.0353" hae="12.25" ce="4.9" le="9999999"/>'
    '<detail><contact endpoint="192.0.2.10:4242:tcp" callsign="FALCON"/><__group name="Cyan" role="Team Member"/>'
    '<precisionlocation geopointsrc="GPS" altsrc="GPS"/><status battery="87"/>'
    '<takv device="Example Phone" platform="ATAK-CIV" os="34" version="5.2.0"/>'
    '<track speed="1.75" course="123.5"/></detail></event>',
    # detail elements takproto keeps as text
    '<event version="2.0" uid="R-77" type="a-u-A" time="2022-11-12T13:14:15.000Z" start="2022-11-12T13:14:15.000Z" '
    'stale="2022-11-12T13:19:15.000Z" how="m-r"><point lat="51.5007" lon="-0.1246" hae="350" ce="50" le="25"/>'
    '<detail><remarks>radar contact</remarks><__radar rcs_m2="0.25"/></detail></event>',
    # a GeoChat event: takproto puts the sender in takControl.contactUid and the detail as text
    '<event version="2.0" uid="GeoChat.ANDROID-42.All Chat Rooms.1a2b" type="b-t-f" time="2024-07-08T09:10:11.000Z" '
    'start="2024-07-08T09:10:11.000Z" stale="2024-07-09T09:10:11.000Z" how="h-g-i-g-o">'
    '<point lat="0" lon="0" hae="9999999" ce="9999999" le="9999999"/>'
    '<detail><remarks source="BAO.F.ATAK.ANDROID-42" to="All Chat Rooms">hello</remarks></detail></event>',
    # zero track, which takproto writes as an empty track sub-message
    '<event version="2.0" uid="J-0" type="a-f-S" time="2020-01-01T00:00:00.000Z" start="2020-01-01T00:00:00.000Z" '
    'stale="2020-01-01T00:05:00.000Z" how="m-g"><point lat="10.25" lon="-20.5" hae="0.5" ce="3" le="4"/>'
    '<detail><contact callsign="ZERO"/><track speed="0.0" course="0.0"/></detail></event>',
]

# takproto field -> takproto module key of packs/cot-protobuf
EVENT_KEYS = [("type", "cot_event_type"), ("access", "cot_event_access"), ("qos", "cot_event_qos"),
              ("opex", "cot_event_opex"), ("uid", "cot_event_uid"), ("sendTime", "cot_event_send_time"),
              ("startTime", "cot_event_start_time"), ("staleTime", "cot_event_stale_time"),
              ("how", "cot_event_how"), ("lat", "cot_event_lat"), ("lon", "cot_event_lon"),
              ("hae", "cot_event_hae"), ("ce", "cot_event_ce"), ("le", "cot_event_le")]
DETAIL_KEYS = [("xmlDetail", None, "detail_xml_detail"),
               ("contact", "endpoint", "detail_contact_endpoint"), ("contact", "callsign", "detail_contact_callsign"),
               ("group", "name", "detail_group_name"), ("group", "role", "detail_group_role"),
               ("precisionLocation", "geopointsrc", "detail_precision_location_geopointsrc"),
               ("precisionLocation", "altsrc", "detail_precision_location_altsrc"),
               ("status", "battery", "detail_status_battery"),
               ("takv", "device", "detail_takv_device"), ("takv", "platform", "detail_takv_platform"),
               ("takv", "os", "detail_takv_os"), ("takv", "version", "detail_takv_version"),
               ("track", "speed", "detail_track_speed"), ("track", "course", "detail_track_course")]
CONTROL_KEYS = [("minProtoVersion", "tak_control_min_proto_version"),
                ("maxProtoVersion", "tak_control_max_proto_version"), ("contactUid", "tak_control_contact_uid")]

# RULE for golden-xml vectors: what packs/cot-xml decodes to a key that packs/cot-protobuf
# writes, and nothing else. Event attributes among EVENT_ATTRS; time and start both set and
# equal (cot-xml reads both into time_ms, cot-protobuf writes time_ms at sendTime and
# startTime); hae, ce and le all set (cot-xml fills 9999999 for one not given, takproto writes
# none); no point or track value 0 (cot-xml decodes it and cot-protobuf writes it, as its pack.md
# says; a proto3 writer such as takproto's leaves a 0 out); detail children only contact
# (callsign alone) and track.
EVENT_ATTRS = {"version", "uid", "type", "time", "start", "stale", "how"}


def fetch_sdist(cache):
    os.makedirs(cache, exist_ok=True)
    local = os.path.join(cache, SDIST[1] + ".tar.gz")
    if not os.path.exists(local):
        with urllib.request.urlopen(SDIST[0], timeout=60) as r:
            data = r.read()
        with open(local, "wb") as fh:
            fh.write(data)
    data = open(local, "rb").read()
    if hashlib.sha256(data).hexdigest() != SDIST[1]:
        raise SystemExit("golden-takproto: the takproto sdist's SHA-256 is not %s" % SDIST[1])
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        return t.extractfile(TEST_FILE).read().decode("utf-8")


def test_message(src):
    """takproto's test event and its recorded mesh bytes, from test_xml2proto_default."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "test_xml2proto_default":
            xml = rec = None
            for st in ast.walk(node):
                if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name):
                    if st.targets[0].id == "t_xml":
                        xml = st.value.value
                    elif st.targets[0].id == "t_ba":
                        rec = st.value.args[0].value
            return xml.strip(), rec
    raise SystemExit("golden-takproto: test_xml2proto_default not found in %s" % TEST_FILE)


def canonical(msg):
    """The message with every empty sub-message cleared, serialized."""
    m = type(msg)()
    m.CopyFrom(msg)

    def clear(x):
        for fd, val in list(x.ListFields()):
            if fd.message_type is not None and not fd.is_repeated:
                clear(val)
                if val.ByteSize() == 0:
                    x.ClearField(fd.name)
    clear(m)
    return m.SerializeToString()


def num(v):
    return repr(float(v)) if isinstance(v, float) else str(v)


def pb_model(msg):
    ev, ctl, m = msg.cotEvent, msg.takControl, {"@kind": "cot_event"}
    for f, k in CONTROL_KEYS:
        if getattr(ctl, f):
            m["takproto." + k] = num(getattr(ctl, f))
    for f, k in EVENT_KEYS:
        if getattr(ev, f):
            m["takproto." + k] = num(getattr(ev, f))
    for sub, f, k in DETAIL_KEYS:
        v = getattr(ev.detail, sub) if f is None else getattr(getattr(ev.detail, sub), f)
        if v:
            m["takproto." + k] = num(v)
    m.update(shared(msg))
    return m


def shared(msg):
    """The shared keys the fields give without a choice."""
    ev, m = msg.cotEvent, {}
    for f, k in (("uid", "uid"), ("type", "type"), ("how", "how"), ("lat", "lat"), ("lon", "lon"),
                 ("staleTime", "stale_ms")):
        if getattr(ev, f):
            m[k] = num(getattr(ev, f))
    m["time_ms"] = str(ev.sendTime)
    unknown = []
    for f in ("hae", "ce", "le"):
        v = getattr(ev, f)
        if v == SENTINEL:
            unknown.append(f)
        elif v:
            m[f] = num(v)
    if ev.detail.contact.callsign:
        m["callsign"] = ev.detail.contact.callsign
    if ev.detail.track.speed:
        m["speed_ms"] = num(ev.detail.track.speed)
    if ev.detail.track.course:
        m["course"] = num(ev.detail.track.course)
    if unknown:
        m["@absent"] = unknown
    return m


def in_rule(xml):
    import xml.etree.ElementTree as ET
    e = ET.fromstring(xml)
    if not set(e.attrib) <= EVENT_ATTRS or e.get("time") is None or e.get("time") != e.get("start"):
        return False
    p = e.find("point")
    if p is None or any(p.get(a) is None or float(p.get(a)) == 0 for a in ("lat", "lon", "hae", "ce", "le")):
        return False
    d = e.find("detail")
    for c in ([] if d is None else list(d)):
        if c.tag == "track":
            if any(float(v) == 0 for v in c.attrib.values()):
                return False
            continue
        if c.tag != "contact" or set(c.attrib) != {"callsign"}:
            return False
    return True


def build(takproto, cache):
    xml0, rec0 = test_message(fetch_sdist(cache))
    if bytes(takproto.xml2proto(xml0)) != rec0:
        raise SystemExit("golden-takproto: takproto %s does not write its own recorded test bytes" % TAKPROTO)
    inputs = [(xml0, "the event of test_xml2proto_default, takproto %s sdist %s" % (TAKPROTO, TEST_FILE))]
    inputs += [(x, "golden-takproto INPUTS[%d]" % i) for i, x in enumerate(INPUTS)]
    vecs, nx = {}, 0
    for n, (xml, origin) in enumerate(inputs, 1):
        mesh = bytes(takproto.xml2proto(xml))
        if mesh[:3] != MESH:
            raise SystemExit("golden-takproto: no mesh header on %s" % origin)
        msg = takproto.parse_proto(mesh)
        if not msg.cotEvent.sendTime or msg.cotEvent.sendTime != msg.cotEvent.startTime:
            raise SystemExit("golden-takproto: %s has no time and start, or they differ" % origin)
        wire, canon = mesh[3:].hex(), canonical(msg).hex()
        src = ("takproto %s: xml2proto of %s, read back by parse_proto (github.com/snstac/takproto). Written by "
               "tools/gen/golden-takproto.py; no engine is run." % (TAKPROTO, origin))
        name = "golden-pb-%d" % n
        vecs[name + ".json"] = {
            "name": name, "from": "cot-protobuf", "to": "cot-protobuf", "input": wire, "expect": canon,
            "model": pb_model(msg), "source": src,
            "reference": "The TakMessage takproto (MIT) writes for the event, without its mesh header; expect is that "
                         "message with any empty sub-message cleared, serialized by the protobuf runtime."
                         + ("" if wire == canon else " Here the input carries an empty sub-message."),
        }
        if in_rule(xml):
            nx += 1
            name = "golden-xml-%d" % nx
            vecs[name + ".json"] = {
                "name": name, "from": "cot-xml", "to": "cot-protobuf", "input": xml, "expect": canon,
                "model": shared(msg), "source": src,
                "reference": "The TakMessage takproto (MIT) writes for the event, in canonical form; the event holds "
                             "only what cot-xml and cot-protobuf both bind (RULE in tools/gen/golden-takproto.py).",
            }
    return vecs


def text(vec):
    return json.dumps(vec, indent=1, ensure_ascii=False) + "\n"


def where(name):
    return os.path.join(PACKS, "cot-protobuf" if name.startswith("golden-pb-") else "cot-xml", "vectors", name)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="golden-takproto", description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--cache", default=os.path.join(os.path.expanduser("~"), ".cache", "golden-takproto"))
    args = ap.parse_args(argv)
    try:
        import takproto
        from importlib.metadata import version
        if version("takproto") != TAKPROTO:
            raise ImportError(version("takproto"))
    except ImportError as e:
        print("golden-takproto: takproto %s is not importable (%s); pip install --require-hashes -r "
              "tools/gen/golden-takproto.txt" % (TAKPROTO, e), file=sys.stderr)
        return 1
    vecs = build(takproto, args.cache)
    have = set()
    for p, pre in (("cot-protobuf", "golden-pb-"), ("cot-xml", "golden-xml-")):
        have |= {n for n in os.listdir(os.path.join(PACKS, p, "vectors")) if n.startswith(pre) and n.endswith(".json")}
    if args.check:
        bad = sorted(n for n in set(vecs) | have
                     if n not in vecs or n not in have or open(where(n), encoding="utf-8").read() != text(vecs[n]))
        if bad:
            print("golden-takproto: %d vector(s) differ from what takproto writes: %s" % (len(bad), ", ".join(bad[:10])),
                  file=sys.stderr)
            return 1
        print("golden-takproto: --check: ok, %d vectors" % len(vecs))
        return 0
    for n in have - set(vecs):
        os.remove(where(n))
    for n, v in vecs.items():
        with open(where(n), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text(v))
    print("golden-takproto: wrote %d vectors" % len(vecs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
