#!/usr/bin/env python3
"""Write the NGA Maritime Safety Information packs from archived API responses.

The NGA MSI web API (https://msi.nga.mil/api) answered 503 on 2026-11-20 and no
OpenAPI document of it is archived. The Internet Archive holds responses of four of
its endpoints. Each response is one JSON object with one member, an array of
records; this script reads those responses (tools/gen/nga-msi-run.sh fetches them
and checks their SHA-256) and writes one pack per record type:

    nga-msi-asam            /api/publications/asam                       member `asam`
    nga-msi-broadcast-warn  /api/publications/broadcast-warn             member `broadcast-warn`
    nga-msi-ngalol          /api/publications/ngalol/lights-buoys        member `ngalol`
    nga-msi-wpi             /api/publications/world-port-index           member `ports`

A message of a pack is one record (one element of that array), wire `json`. A
record member is mapped when the archived records show its JSON type: `int` when
every non-null value is an integer, `float` when every one is a number and one
has a fraction, `string` when every one is a string. A member that is null in
every archived record shows no type and is left to residue (a null member is
absent on the json wire, so it is not carried; a non-null value is carried as
residue text). Field lines follow the members' order in the responses, so a
record in that order converts to itself unchanged.

Shared keys: `lat` and `lon` from the numeric position members of ASAM and WPI
records (MAP below; the evidence is in each pack.md). Every other key is a raw key
of the pack's own module.

The vectors use records written for this repository with the archived member
order and types; no archived record is copied. Expected bytes follow from the
json wire's canonical output (spec/engine-spec.md 0.5): mapped members in line
order, then residue in input order, null members dropped. The script imports no
goat-transformers engine. Python 3 standard library only.

Usage: python3 -I tools/gen/nga-msi2pack.py [--check] <sources> <goat-transformers checkout>
"""
import argparse
import collections
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

READ_ON = "2026-11-20"
WAYBACK = "https://web.archive.org/web/%sid_/%s"

# (pack suffix, module, title, endpoint, array member, [(file, timestamp, url, sha256 of
# the decompressed body)])
SOURCES = [
    ("asam", "ngaasam", "Anti-Shipping Activity Messages (ASAM)", "/api/publications/asam", "asam", [
        ("asam.json", "20230927174507",
         "https://msi.nga.mil/api/publications/asam?filter=none&sort=date&output=html",
         "6e9e6c4242411d3ed4f40c6a50c63da5225d0321234a912e07be3491f63c1868")]),
    ("broadcast-warn", "ngabwarn", "Broadcast navigational warnings", "/api/publications/broadcast-warn",
     "broadcast-warn", [
        ("bw.json", "20261022102238",
         "https://msi.nga.mil/api/publications/broadcast-warn?output=json&navArea=P&msgYear=2023&msgNumber=1779&status=all",
         "2e6dfbd0c5b80ec9239f0417a2c28ee120aad00beacee8a2806d0ec6f34ce249")]),
    ("ngalol", "ngalol", "List of Lights, lights and buoys", "/api/publications/ngalol/lights-buoys", "ngalol", [
        ("lol.json", "20260914160540",
         "https://msi.nga.mil/api/publications/ngalol/lights-buoys?volume=110&featureNumber=11636&includeRemovals=false&output=json",
         "afff43b1ef950559a7b0b8645ec32fb932e2be6297da9982b9611d63afe0d1d9"),
        ("lol2.json", "20260914160555",
         "https://msi.nga.mil/api/publications/ngalol/lights-buoys?volume=110&featureNumber=11668&includeRemovals=false&output=json",
         "a486fbd7ded63555c9999faa08b3e5765d12d9f9beb1ea74236e2ec72ecc3120"),
        ("lol3.json", "20260914160623",
         "https://msi.nga.mil/api/publications/ngalol/lights-buoys?volume=110&featureNumber=11672&includeRemovals=false&output=json",
         "87553ba4d22ba5728606c528e4182e0549467f8370e9a8281ba992704f238387"),
        ("lol4.json", "20260910224550",
         "https://msi.nga.mil/api/publications/ngalol/lights-buoys?volume=114&featureNumber=1220&includeRemovals=false&output=html",
         "546d0420aba6f89a589e421ccda7ecdf05da4c610a28bdc0339eec01433b0608")]),
    ("wpi", "ngawpi", "World Port Index", "/api/publications/world-port-index", "ports", [
        ("wpi.json", "20250222063435",
         "https://msi.nga.mil/api/publications/world-port-index?indexNumber=12370&output=json",
         "676d0d7ac80c33a302a96d87293b1389ad37c6c97c30f3b850092b5d61cd9736"),
        ("wpi2.json", "20260124043107",
         "https://msi.nga.mil/api/publications/world-port-index?countryName=Costa%20Rica&output=html",
         "6f42f6db08175cf8ce046ff3ef8c46144d495288dc203a8901206cf6f076928f"),
        ("wpi3.json", "20260124043522",
         "https://msi.nga.mil/api/publications/world-port-index?countryName=Venezuela&output=html",
         "1b820bc8faace47fcede3d125e57b618eff5d80c3ab3b91b11496058945bd749")]),
]

LICENCE = "LicenseRef-NGA-MSI"
SPDX_NOTE = ("US Government work: NGA states it claims no copyright in the nautical products on "
             "msi.nga.mil; a product that names NGA must carry NGA's disclaimer "
             "(LICENSES/LicenseRef-NGA-MSI.txt)")


# Members bound to shared-model keys, per pack. Evidence (stated in pack.md): NGA is the
# custodian of WGS 84 and publishes its maritime safety and charting products on it, and
# in every archived record these numbers agree with the record's own degrees-minutes
# text to within one minute of arc.
MAP = {"asam": {"latitude": "lat", "longitude": "lon"},
       "wpi": {"ycoord": "lat", "xcoord": "lon"}}
# The degrees-minutes text each bound pair is checked against: (member of latitude text,
# member of longitude text); the same member holds both for ASAM.
DMS_TEXT = {"asam": ("position", "position"), "wpi": ("latitude", "longitude")}
POS_SAMPLE = {"lat": [6.5, -12.25, 48.125, 0.5], "lon": [3.25, -77.5, 11.75, -0.5]}


def dms_values(text):
    """Signed degrees of every d°m's"H group in a text, in order."""
    out = []
    for g in re.finditer(r"(\d+)\u00b0(\d+)'([\d.]+)\"([NSEW])", text or ""):
        v = int(g[1]) + int(g[2]) / 60 + float(g[3]) / 3600
        out.append(-v if g[4] in "SW" else v)
    return out


def check_agreement(suffix, recs):
    """Stop unless every record's bound numbers agree with its text within 1 arc-minute."""
    bound = MAP.get(suffix)
    if not bound:
        return
    inv = {v: k for k, v in bound.items()}
    tlat, tlon = DMS_TEXT[suffix]
    for r in recs:
        if tlat == tlon:
            vals = dms_values(r.get(tlat))
            want = vals if len(vals) == 2 else None
        else:
            a, b = dms_values(r.get(tlat)), dms_values(r.get(tlon))
            want = [a[0], b[0]] if len(a) == 1 and len(b) == 1 else None
        got = [r.get(inv["lat"]), r.get(inv["lon"])]
        if want is None or None in got or max(abs(got[0] - want[0]), abs(got[1] - want[1])) > 1 / 60:
            raise SystemExit("nga-msi2pack: %s: a record's position numbers do not agree with its text: %r"
                             % (suffix, got))


def snake(name):
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name.replace("-", "_"))
    return re.sub(r"_+", "_", s).lower()


def jtype(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "string"
    return type(v).__name__


def survey(records):
    """[(member, transform or None, non-null count, total)] in first-appearance order."""
    order, seen = [], collections.defaultdict(set)
    for r in records:
        for m, v in r.items():
            if m not in order:
                order.append(m)
            if v is not None:
                seen[m].add(jtype(v))
    out = []
    for m in order:
        t = seen[m]
        if not t:
            tr = None
        elif t == {"int"}:
            tr = "int"
        elif t <= {"int", "float"}:
            tr = "float"
        elif t == {"string"}:
            tr = "string"
        else:
            raise SystemExit("nga-msi2pack: member %s has mixed types %s" % (m, sorted(t)))
        n = sum(1 for r in records if r.get(m) is not None)
        out.append((m, tr, n, len(records)))
    return out


def sample(m, tr, i):
    """A value written for the vectors, of the member's type."""
    if tr == "int":
        return 100 + i
    if tr == "float":
        return [12.5, -45.25, 0.125, 3.75][i % 4]
    return "%s %s" % (m.upper()[:12], "A" if i % 2 == 0 else "B")


def canon(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def build_pack(suffix, module, title, endpoint, member, files, recs, out):
    fmt = "nga-msi-" + suffix
    members = survey(recs)
    mapped = [(m, tr) for m, tr, n, t in members if tr]
    unmapped = [m for m, tr, n, t in members if not tr]
    bound = MAP.get(suffix, {})
    keys = {}
    for m, tr in mapped:
        if m in bound:
            continue
        k = snake(m)
        if k in keys.values():
            raise SystemExit("nga-msi2pack: two members give key %s" % k)
        keys[m] = k
    src_line = "NGA Maritime Safety Information API, %s, record member `%s`, from responses archived by the Internet Archive (%s); member names and JSON types" % (endpoint, member, ", ".join(ts for _, ts, _, _ in files))
    # module
    ktype = {"int": "int", "float": "float", "string": "string"}
    mod = ["# The %s module: the members of one NGA MSI %s record. Public. Generated by" % (module, title),
           "# tools/gen/nga-msi2pack.py; edit the generator, not this file. packs/%s/pack.md." % fmt,
           "module        %s" % module, "version       0.1.0", "distribution  public",
           "source        \"%s\"" % src_line]
    w = max(len(k) for k in keys.values())
    for m, tr in mapped:
        if m in bound:
            continue
        mod.append("key  %-*s  %-6s  -  \"the record's %s member as the response gives it (JSON %s)\""
                   % (w, keys[m], ktype[tr], m, "number" if tr in ("int", "float") else "string"))
    out.write("model/%s.def" % module, "\n".join(mod) + "\n")
    # pack
    pk = ["# NGA MSI %s: one record of the %s response. Public. Generated by" % (title, endpoint),
          "# tools/gen/nga-msi2pack.py; edit the generator, not this file. What is mapped and what",
          "# is not: pack.md.",
          "format        %s" % fmt, "version       0.1.0", "distribution  public",
          "source        \"%s\"" % src_line,
          "source        \"License: %s (%s)\"" % (LICENCE, SPDX_NOTE),
          "uses          %s" % module, "wire          json"]
    w2 = max(len(m) for m, _ in mapped)

    def key_of(m):
        return bound[m] if m in bound else "%s.%s" % (module, keys[m])
    for m, tr in mapped:
        pk.append("field  %-*s  %-*s  %s" % (len(module) + 1 + w, key_of(m), w2, m, tr))
    out.write("packs/%s/pack.def" % fmt, "\n".join(pk) + "\n")

    # vectors
    def rec(i, nulls=(), extra=None):
        r = {}
        for m, tr, n, t in members:
            if m in nulls or tr is None:
                r[m] = None
            elif m in bound:
                r[m] = POS_SAMPLE[bound[m]][i % 4]
            else:
                r[m] = sample(m, tr, i)
        if extra:
            r.update(extra)
        return r

    def expect_of(r):
        # mapped members in line order (null ones absent), then residue in input order:
        # members no line maps whose value is a scalar other than null
        e = {}
        for m, tr in mapped:
            if r.get(m) is not None:
                e[m] = r[m]
        for m, v in r.items():
            if m not in keys and m not in bound and v is not None and not isinstance(v, (list, dict)):
                e[m] = v
        return e

    def model_of(r):
        mo = {}
        for m, tr in mapped:
            v = r.get(m)
            if v is None:
                continue
            mo[key_of(m)] = v if isinstance(v, str) else canon(v)
        return mo

    src = "derived by tools/gen/nga-msi2pack.py from the json wire's canonical output (spec/engine-spec.md 0.5); no engine run"
    ref = "NGA MSI %s records as archived (%s); the record is written for this repository" % (endpoint, member)
    vecs = []
    r = rec(0)
    vecs.append({"name": "record-roundtrip", "from": fmt, "to": fmt, "input": canon(r), "expect": canon(expect_of(r)),
                 "model": model_of(r), "source": src,
                 "reference": ref + "; every member in the archived order; members null in every archived record are null here and are not carried"})
    first_str = next(m for m, tr in mapped if tr == "string")
    r = rec(1, nulls=(first_str,), extra={"extraMember": "kept", "extraFlag": True})
    m2 = model_of(r)
    m2["@absent"] = [key_of(first_str)]
    vecs.append({"name": "null-and-unknown-members", "from": fmt, "to": fmt, "input": canon(r),
                 "expect": canon(expect_of(r)), "model": m2, "source": src,
                 "reference": ref + "; a null member is absent and not written; members the pack does not map (two added here) are residue and are written back after the mapped ones"})
    r = rec(2)
    inv = {v: k for k, v in bound.items()}
    if bound:
        geo = {"type": "Point", "coordinates": [r[inv["lon"]], r[inv["lat"]]]}
        note = "; the numeric position members are lat and lon (pack.md) and carry as the Point; no other key has a geojson line"
    else:
        geo, note = None, "; no shared key is bound (pack.md), so nothing carries to geojson and geometry is null"
    vecs.append({"name": "record-to-geojson", "from": fmt, "to": "geojson", "input": canon(r),
                 "expect": canon({"type": "Feature", "geometry": geo, "properties": {}}), "source": src,
                 "model": {"lat": canon(r[inv["lat"]]), "lon": canon(r[inv["lon"]])} if bound else None,
                 "reference": ref + note})
    if vecs[-1]["model"] is None:
        del vecs[-1]["model"]
    num = next(((m, tr) for m, tr in mapped if tr in ("int", "float")), None)
    if num:
        r = rec(3)
        r[num[0]] = "not a number"
        vecs.append({"name": "wrong-type-is-transform-decode", "from": fmt, "to": fmt, "input": canon(r),
                     "expect_error": "transform-decode", "source": src,
                     "reference": ref + "; %s is a JSON number in every archived record; a string there fails its %s transform" % (num[0], num[1])})
    vdir = "packs/%s/vectors" % fmt
    names = set()
    for i, v in enumerate(vecs, 1):
        rel = "%s/gen-%02d-%s.json" % (vdir, i, v["name"])
        names.add(rel.rsplit("/", 1)[1])
        out.write(rel, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
    for old in out.listdir(vdir):
        if old not in names:
            out.remove(vdir + "/" + old)
    # a vector lives in the pack that owns its input (spec/vector-format.md)
    cross = "packs/geojson/vectors/to-%s-geojson-to-record.json" % fmt
    if bound:
        lat, lon = 48.125, -0.5
        out.write(cross, json.dumps({
            "name": "%s-geojson-to-record" % fmt, "from": "geojson", "to": fmt,
            "input": canon({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                            "properties": {"callsign": "NOT CARRIED"}, "id": "x-1"}),
            "expect": canon({inv["lat"]: lat, inv["lon"]: lon}),
            "source": src.replace("json wire's canonical output", "json wire's canonical output and packs/geojson/pack.def"),
            "reference": ref.replace("; the record is written for this repository", "") +
            "; lat and lon are written to %s and %s, the only lines whose keys a GeoJSON Feature carries; id and callsign have no line in this pack" % (inv["lat"], inv["lon"])},
            indent=2, ensure_ascii=False) + "\n")
    elif out.exists(cross):
        out.remove(cross)

    # pack.md
    md = ["# %s" % fmt, "",
          "NGA Maritime Safety Information, %s: one record of the response of `%s`. Public. Generated by `tools/gen/nga-msi2pack.py` through `tools/gen/nga-msi-run.sh`; module `%s` (`model/%s.def`). Licence %s (PROVENANCE.md)." % (title, endpoint, module, module, LICENCE), "",
          "## Message convention", "",
          "The endpoint answers one JSON object whose member `%s` is an array of records. A message of this pack is one element of that array: one JSON object, wire `json`. The caller takes the records out of the array; the envelope is not a message." % member, "",
          "## Source", "",
          "No API description was available: `https://msi.nga.mil/api` answered 503 on %s and no OpenAPI document of it is archived. The pack is built from %d archived response(s) of the endpoint, %d record(s) in all (PROVENANCE.md lists them with their SHA-256). A member's type is the JSON type its non-null values have in those records." % (READ_ON, len(files), len(recs)), "",
          "## Shared-model keys", ""]
    if bound:
        inv0 = {v: k for k, v in bound.items()}
        md += ["| Member | Key | Evidence |", "|---|---|---|",
               "| `%s` | `lat` | degrees of latitude, WGS 84 (below) |" % inv0["lat"],
               "| `%s` | `lon` | degrees of longitude, WGS 84 (below) |" % inv0["lon"], "",
               "Evidence. The archived responses give the members as JSON numbers with no unit or datum, so the binding rests on two things: NGA is the custodian of WGS 84 and publishes its maritime safety and charting products on it (the basis the maintainers accepted for this binding); and in every archived record (%d) the two numbers agree with the record's own degrees-minutes text to within one minute of arc, so the unit is decimal degrees, north and east positive." % len(recs), "",
               "Other members:", ""]
    else:
        md += ["None bound. The responses name their members and show their JSON types but state no meaning, unit, datum or time base, and AGENTS.md binds a shared key only on a statement of the same meaning and unit. In particular:", ""]
    notes = {
        "asam": "`position` is the same position as degrees-minutes text, kept as a string; `date` is a calendar date with no time or zone, not bound to `time_ms`; `reference` names a report, not a moving entity, and is not bound to `uid`.",
        "broadcast-warn": "positions are inside the free text of `text`; `issueDate` and `cancelDate` are written as day, hour, minute, `Z`, month and year in one text (`DDHHMMZ MON YYYY`), which no transform reads; they are strings.",
        "ngalol": "`position` is degrees-minutes-seconds text of two lines; `heightFeetMeters` holds two numbers in one text; they are strings.",
        "wpi": "`latitude` and `longitude` are the same position as degrees-minutes text, kept as strings; `portNumber` identifies a port, not a moving entity, and is not bound to `uid`.",
    }
    md += ["- " + notes[suffix], "",
           "## Members", "", "| Member | Key | Transform | Non-null in archived records |", "|---|---|---|---|"]
    for m, tr, n, t in members:
        md.append("| `%s` | %s | %s | %d of %d |" % (m, "`%s`" % key_of(m) if tr else "not mapped", tr or "-", n, t))
    md += ["", "## Not mapped", ""]
    if unmapped:
        md.append("- Members null in every archived record show no type: %s. A non-null value of one is residue: carried back into this format, not to another." % ", ".join("`%s`" % m for m in unmapped))
    md += ["- The response envelope and the query parameters of the endpoint.",
           "- Types: a member whose real type differs from the archived one (an integer where the archive shows text) fails with `transform-decode`. The packs are as complete as the archived responses; an OpenAPI document of the API, when it is reachable, should replace this survey.",
           "- Member values are carried as written: codes (`Y`, `N`, `U`, area letters) are not expanded.", "",
           "## Vectors", "", "| File | Case |", "|---|---|"]
    for i, v in enumerate(vecs, 1):
        md.append("| `gen-%02d-%s` | %s |" % (i, v["name"], v["reference"].split("; ", 1)[-1]))
    out.write("packs/%s/pack.md" % fmt, "\n".join(md) + "\n")

    # PROVENANCE.md
    pv = ["# Provenance of the %s pack" % fmt, "", "SPDX licence: %s" % LICENCE, "",
          "`tools/gen/nga-msi-run.sh` fetches the archived responses below and checks their SHA-256; `tools/gen/nga-msi2pack.py` reads them. No response is kept in this repository and no record of them is copied: the vectors are records written for this repository. Read on %s." % READ_ON, "",
          "| | |", "|---|---|",
          "| Publisher | National Geospatial-Intelligence Agency (NGA), Maritime Safety Information, https://msi.nga.mil |",
          "| Endpoint | `https://msi.nga.mil%s` |" % endpoint,
          "| Live API on %s | HTTP 503; no OpenAPI document reachable or archived |" % READ_ON, "",
          "| Archived response (Internet Archive) | SHA-256 of the body |", "|---|---|"]
    for f, ts, url, h in files:
        pv.append("| `%s` | `%s` |" % (WAYBACK % (ts, url), h))
    pv += ["", "The SHA-256 is that of the response body after removing its gzip content encoding.", "",
           "## Licence", "",
           "NGA's page Commercial Use Warning (`https://msi.nga.mil/api/pageContent/getByTitle?pageTitle=Commercial%20Use%20Warning`, archived 2026-08-11) states that NGA claims no copyright or other intellectual property right in the nautical products posted on the site for public use. It prohibits using NGA's name, seal or initials to imply NGA approval, and requires a product that includes NGA's name or implies an association with NGA to carry a disclaimer, quoted in `LICENSES/LicenseRef-NGA-MSI.txt`.", "",
           "The pack carries the licence `%s`, defined there. This pack is not approved, authorized or endorsed by NGA (see the disclaimer)." % LICENCE, ""]
    out.write("packs/%s/PROVENANCE.md" % fmt, "\n".join(pv) + "\n")
    return fmt, len(mapped), len(unmapped), len(vecs)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nga-msi2pack", description=__doc__.split("\n\n")[0])
    ap.add_argument("sources", help="directory holding the decompressed archived responses")
    ap.add_argument("checkout", help="the goat-transformers checkout to write into")
    ap.add_argument("--check", action="store_true", help="write nothing; compare with the checkout")
    args = ap.parse_args(argv)
    out = genio.Output(args.checkout, check=args.check)
    for suffix, module, title, endpoint, member, files in SOURCES:
        recs = []
        for f, ts, url, h in files:
            p = os.path.join(args.sources, f)
            with open(p, "rb") as fh:
                b = fh.read()
            if hashlib.sha256(b).hexdigest() != h:
                print("nga-msi2pack: %s: SHA-256 is not %s" % (f, h), file=sys.stderr)
                return 1
            recs += json.loads(b.decode("utf-8"))[member]
        check_agreement(suffix, recs)
        r = build_pack(suffix, module, title, endpoint, member, files, recs, out)
        if not args.check:
            print("%s: %d members mapped, %d not, %d vectors" % r)
    return out.report("nga-msi2pack")


if __name__ == "__main__":
    sys.exit(main())
