#!/usr/bin/env python3
"""Derive the vectors of the geopackage-geometry-be, geopackage-geometry-le,
wms-capabilities and cityjson packs without an engine.

Python 3 standard library only; imports nothing from engines/. Every expected
message is built here from a description of its values and the layout the
source states, by the canonical rules of spec/engine-spec.md:

- GeoPackage geometry blobs (OGC 12-128r19, clause 2.1.3): magic "GP",
  version 0, flags (reserved, X, Y, E, B from the most significant bit), a
  signed 32-bit srs_id and E's envelope doubles in the byte order flag B
  states, then WKB (OGC 06-103r4, clause 8.2): a byte order byte (0 big, 1
  little), a 32-bit type (1 Point), x and y as doubles. struct packs them.
  A blob's encoded length is the furthest byte of the lines outside any gate
  block, of the blocks that hold and of their gate locators (Version 0.17,
  Encode); the bytes of a WKB other than a two-dimensional Point are not
  written.
- bits output: lowercase hex, no separators (Version 0.2).
- xml: no declaration; attributes in field-line order, then residue in input
  order; mapped elements in line order, a group at its line's position; a
  child element no line maps is dropped; empty elements self-closing
  (Canonicalisation, rulings 6 and 10 of 0.1.1 and 0.5, Version 0.7).
- json: mapped and `when` members in line order, a nested object at its first
  line; then residue members of that object in input order; arrays outside a
  group are not carried; floats shortest round trip, plain notation
  (Version 0.5, The json wire; ruling 3 of 0.1.1).
- geojson: type, geometry (null without lat or lon), properties in field-line
  order of packs/geojson/pack.def, then id.

Usage:
  python3 -I tools/gen/ogc-geo-vectors.py <checkout>          write the vectors
  python3 -I tools/gen/ogc-geo-vectors.py <checkout> --check  exit 1 when a file differs
"""
import json
import os
import struct
import sys
from decimal import Decimal

SOURCE = "derived by tools/gen/ogc-geo-vectors.py from the standard and spec/engine-spec.md; no engine run"
REF_GPKG = "OGC 12-128r19 (GeoPackage 1.4.0) clause 2.1.3 Geometry Encoding, Table 5 flags byte; OGC 06-103r4 clause 8.2 WKB"
REF_WMS = "OGC 06-042 (WMS 1.3.0) clause 7.2.4 service metadata and Annex E schema element order"
REF_CJ = "CityJSON Specifications 2.0.1, sections 1 CityJSON Object, 4 Transform Object, 5 Metadata, 7.2 CityJSONFeature"

LON, LAT = 11.576124, 48.137154


def canon_float(x):
    x = float(x)
    if x == 0:
        return "0"
    r = repr(x)
    if "e" in r or "E" in r:
        r = format(Decimal(r), "f")
    if r.endswith(".0"):
        r = r[:-2]
    return r


def vec(name, frm, to, inp, expect=None, error=None, model=None, ref=""):
    v = {"name": name, "from": frm, "to": to, "input": inp}
    if error is None:
        v["expect"] = expect
    else:
        v["expect_error"] = error
    if model is not None:
        v["model"] = model
    v["source"] = SOURCE
    v["reference"] = ref
    return v


# -- GeoPackage geometry blobs ----------------------------------------------

ENV_KEYS = {
    0: [],
    1: ["min_x", "max_x", "min_y", "max_y"],
    2: ["min_x", "max_x", "min_y", "max_y", "min_z", "max_z"],
    3: ["min_x", "max_x", "min_y", "max_y", "min_m", "max_m"],
    4: ["min_x", "max_x", "min_y", "max_y", "min_z", "max_z", "min_m", "max_m"],
}


def gpkg_header(little, srs, env_code=0, env=None, empty=0, extended=0):
    o = "<" if little else ">"
    flags = (extended << 5) | (empty << 4) | (env_code << 1) | (1 if little else 0)
    b = b"GP" + bytes([0, flags]) + struct.pack(o + "i", srs)
    for k in ENV_KEYS[env_code]:
        b += struct.pack(o + "d", env[k])
    return b


def wkb_point(little, x, y):
    o = "<" if little else ">"
    return bytes([1 if little else 0]) + struct.pack(o + "I", 1) + struct.pack(o + "dd", x, y)


def gpkg_model(srs, env_code=0, env=None, empty=0, x=None, y=None):
    m = {"@kind": "geometry", "gpkg.extended": "0", "gpkg.empty": str(empty),
         "gpkg.envelope": str(env_code), "gpkg.srs_id": str(srs)}
    for k in ENV_KEYS[env_code]:
        m["gpkg." + k] = canon_float(env[k])
    if x is not None:
        m["gpkg.x"] = canon_float(x)
        m["gpkg.y"] = canon_float(y)
        if srs == 4326:
            m["lon"] = canon_float(x)
            m["lat"] = canon_float(y)
    absent = []
    if x is None:
        absent += ["gpkg.x", "gpkg.y"]
    if x is None or srs != 4326:
        absent += ["lat", "lon"]
    if absent:
        m["@absent"] = absent
    return m


def geojson_point(lon, lat):
    return ('{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":{}}'
            % (canon_float(lon), canon_float(lat)))


def gpkg_vectors(little):
    me = "geopackage-geometry-le" if little else "geopackage-geometry-be"
    other = "geopackage-geometry-be" if little else "geopackage-geometry-le"
    tag = "little-endian" if little else "big-endian"
    h = lambda b: b.hex()
    env1 = {"min_x": LON, "max_x": LON, "min_y": LAT, "max_y": LAT}
    out = {}

    blob = gpkg_header(little, 4326) + wkb_point(little, LON, LAT)
    out["01-point-roundtrip"] = vec(
        "point-roundtrip", me, me, h(blob), h(blob), model=gpkg_model(4326, x=LON, y=LAT),
        ref=REF_GPKG + "; %s header, no envelope, srs_id 4326, a WKB Point; x and y bound to lon and lat" % tag)

    blob = gpkg_header(little, 4326, 1, env1) + wkb_point(little, LON, LAT)
    out["02-point-envelope-roundtrip"] = vec(
        "point-envelope-roundtrip", me, me, h(blob), h(blob), model=gpkg_model(4326, 1, env1, x=LON, y=LAT),
        ref=REF_GPKG + "; envelope code 1 (x and y bounds, 32 bytes): the WKB starts at byte 40")

    px, py = 1288648.5, 6130000.25
    blob = gpkg_header(little, 3857) + wkb_point(little, px, py)
    out["03-projected-point-roundtrip"] = vec(
        "projected-point-roundtrip", me, me, h(blob), h(blob), model=gpkg_model(3857, x=px, y=py),
        ref=REF_GPKG + "; srs_id 3857 is not WGS 84 geographic: x and y kept as gpkg.x and gpkg.y, lat and lon absent")

    blob = gpkg_header(little, 4326) + wkb_point(little, LON, LAT)
    out["04-point-to-geojson"] = vec(
        "point-to-geojson", me, "geojson", h(blob), geojson_point(LON, LAT), model=gpkg_model(4326, x=LON, y=LAT),
        ref=REF_GPKG + "; clause 2.1.3 axis order: x is longitude, y is latitude; Requirement 11: srs_id 4326 is EPSG 4326 WGS 84; packs/geojson/pack.def")

    out["05-point-from-geojson"] = vec(
        "%s-point-from-geojson" % me, "geojson", me, geojson_point(LON, LAT), h(blob),
        model={"lat": canon_float(LAT), "lon": canon_float(LON)},
        ref=REF_GPKG + "; with no gpkg key in the entity the gates write X 0, Y 0, E 0, srs_id 4326, WKB byte order and type 1 (Version 0.17, Encode step 3)")

    env4 = {"min_x": LON, "max_x": LON, "min_y": LAT, "max_y": LAT,
            "min_z": -12.5, "max_z": 519.5, "min_m": 0, "max_m": 1000.25}
    blob = gpkg_header(little, 4326, 4, env4) + wkb_point(little, LON, LAT)
    blob_o = gpkg_header(not little, 4326, 4, env4) + wkb_point(not little, LON, LAT)
    out["06-xyzm-envelope-to-%s" % ("be" if little else "le")] = vec(
        "xyzm-envelope-to-" + ("be" if little else "le"), me, other, h(blob), h(blob_o),
        model=gpkg_model(4326, 4, env4, x=LON, y=LAT),
        ref=REF_GPKG + "; envelope code 4 (64 bytes, x y z m bounds), WKB at byte 72; the same values written in the other byte order (header flag B and WKB byte order)")

    blob = gpkg_header(not little, 4326) + wkb_point(not little, LON, LAT)
    out["07-other-byte-order-is-no-kind"] = vec(
        "other-byte-order-is-no-kind", me, me, h(blob), error="no-kind",
        ref=REF_GPKG + "; flag B of the other byte order fails this pack's common `when`")

    bad = b"GQ" + gpkg_header(little, 4326)[2:] + wkb_point(little, LON, LAT)
    out["08-bad-magic-is-no-kind"] = vec(
        "bad-magic-is-no-kind", me, me, h(bad), error="no-kind",
        ref=REF_GPKG + "; the magic must be the ASCII bytes G and P")

    out["09-truncated-header-is-malformed"] = vec(
        "truncated-header-is-malformed", me, me, h(gpkg_header(little, 4326)[:7]), error="malformed-wire",
        ref=REF_GPKG + "; srs_id runs past the input (Version 0.5, fields that run past their word)")

    o = "<" if little else ">"
    ring = struct.pack(o + "I", 4) + struct.pack(o + "8d", 0, 0, 1, 0, 1, 1, 0, 0)
    poly = bytes([1 if little else 0]) + struct.pack(o + "II", 3, 1) + ring
    blob = gpkg_header(little, 4326) + poly
    out["11-polygon-header-only"] = vec(
        "polygon-header-only", me, me, h(blob), h(gpkg_header(little, 4326)),
        model=gpkg_model(4326),
        ref=REF_GPKG + "; a WKB Polygon (type 3) is not read: the Point gate does not hold, its block writes nothing and its gate locator does not count toward the length (Version 0.17, Encode step 5 and ruling 14), so the output is the 8-byte header")

    nan = float("nan")
    nanpt = bytes([1 if little else 0]) + struct.pack(("<" if little else ">") + "I", 1) + \
        (bytes.fromhex("000000000000f87f") * 2 if little else bytes.fromhex("7ff8000000000000") * 2)
    blob = gpkg_header(little, 4326, empty=1) + nanpt
    out["10-empty-point-header-only"] = vec(
        "empty-point-header-only", me, me, h(blob), h(gpkg_header(little, 4326, empty=1)),
        model=gpkg_model(4326, empty=1),
        ref=REF_GPKG + "; Requirement 152: an empty Point has Y 1, E 0 and NaN coordinates; the WKB is read only when Y is 0, so the output is the 8-byte header")
    return out


# -- WMS 1.3.0 capabilities ---------------------------------------------------

WMS_NS = "http://www.opengis.net/wms"
XLINK = "http://www.w3.org/1999/xlink"


def wms_doc(extra_root="", service_extra="", layer_extra=""):
    return (
        '<WMS_Capabilities xmlns="%s" version="1.3.0" updateSequence="17"%s>'
        '<Service><Name>WMS</Name><Title>Relief and roads</Title><Abstract>Shaded relief with a road overlay.</Abstract>'
        '<KeywordList><Keyword>relief</Keyword><Keyword>roads</Keyword></KeywordList>'
        '<OnlineResource xmlns:xlink="%s" xlink:type="simple" xlink:href="https://maps.example.org/wms"/>'
        '<ContactInformation><ContactPersonPrimary><ContactPerson>Map Desk</ContactPerson><ContactOrganization>Example Mapping Office</ContactOrganization></ContactPersonPrimary>'
        '<ContactPosition>Operator</ContactPosition>'
        '<ContactAddress><AddressType>postal</AddressType><Address>1 Grid Street</Address><City>Springfield</City><StateOrProvince>North</StateOrProvince><PostCode>12345</PostCode><Country>Nowhere</Country></ContactAddress>'
        '<ContactVoiceTelephone>+1 555 0100</ContactVoiceTelephone></ContactInformation>'
        '<Fees>none</Fees><AccessConstraints>none</AccessConstraints><LayerLimit>16</LayerLimit><MaxWidth>4096</MaxWidth><MaxHeight>4096</MaxHeight>%s</Service>'
        '<Capability><Request>'
        '<GetCapabilities><Format>text/xml</Format><DCPType><HTTP><Get><OnlineResource xmlns:xlink="%s" xlink:href="https://maps.example.org/wms?"/></Get></HTTP></DCPType></GetCapabilities>'
        '<GetMap><Format>image/png</Format><Format>image/jpeg</Format><DCPType><HTTP><Get><OnlineResource xmlns:xlink="%s" xlink:href="https://maps.example.org/wms?"/></Get></HTTP></DCPType></GetMap>'
        '</Request><Exception><Format>XML</Format><Format>INIMAGE</Format></Exception>'
        '<Layer queryable="0"><Title>All layers</Title><CRS>CRS:84</CRS><CRS>EPSG:4326</CRS>'
        '<EX_GeographicBoundingBox><westBoundLongitude>5.5</westBoundLongitude><eastBoundLongitude>15.25</eastBoundLongitude>'
        '<southBoundLatitude>47</southBoundLatitude><northBoundLatitude>55.125</northBoundLatitude></EX_GeographicBoundingBox>'
        '<BoundingBox CRS="EPSG:4326" minx="47" miny="5.5" maxx="55.125" maxy="15.25"/>%s'
        '<Layer queryable="1" opaque="1"><Name>relief</Name><Title>Shaded relief</Title><Abstract>Hill shading.</Abstract>'
        '<EX_GeographicBoundingBox><westBoundLongitude>5.5</westBoundLongitude><eastBoundLongitude>15.25</eastBoundLongitude>'
        '<southBoundLatitude>47</southBoundLatitude><northBoundLatitude>55.125</northBoundLatitude></EX_GeographicBoundingBox>'
        '<MaxScaleDenominator>5000000</MaxScaleDenominator></Layer>'
        '<Layer queryable="0"><Name>roads</Name><Title>Roads</Title>'
        '<EX_GeographicBoundingBox><westBoundLongitude>6</westBoundLongitude><eastBoundLongitude>15</eastBoundLongitude>'
        '<southBoundLatitude>47.5</southBoundLatitude><northBoundLatitude>55</northBoundLatitude></EX_GeographicBoundingBox>'
        '<MinScaleDenominator>1000</MinScaleDenominator></Layer>'
        '</Layer></Capability></WMS_Capabilities>'
    ) % (WMS_NS, extra_root, XLINK, service_extra, XLINK, XLINK, layer_extra)


def wms_canonical(root_residue):
    # Field-line order of packs/wms-capabilities/pack.def; unmapped children
    # (OnlineResource, DCPType, BoundingBox) dropped; root residue after the
    # mapped attributes.
    bbox = lambda w, e, s, n: (
        '<EX_GeographicBoundingBox><westBoundLongitude>%s</westBoundLongitude><eastBoundLongitude>%s</eastBoundLongitude>'
        '<southBoundLatitude>%s</southBoundLatitude><northBoundLatitude>%s</northBoundLatitude></EX_GeographicBoundingBox>'
        % (w, e, s, n))
    return (
        '<WMS_Capabilities xmlns="%s" version="1.3.0" updateSequence="17"%s>'
        '<Service><Name>WMS</Name><Title>Relief and roads</Title><Abstract>Shaded relief with a road overlay.</Abstract>'
        '<KeywordList><Keyword>relief</Keyword><Keyword>roads</Keyword></KeywordList>'
        '<ContactInformation><ContactPersonPrimary><ContactPerson>Map Desk</ContactPerson><ContactOrganization>Example Mapping Office</ContactOrganization></ContactPersonPrimary>'
        '<ContactPosition>Operator</ContactPosition>'
        '<ContactAddress><AddressType>postal</AddressType><Address>1 Grid Street</Address><City>Springfield</City><StateOrProvince>North</StateOrProvince><PostCode>12345</PostCode><Country>Nowhere</Country></ContactAddress>'
        '<ContactVoiceTelephone>+1 555 0100</ContactVoiceTelephone></ContactInformation>'
        '<Fees>none</Fees><AccessConstraints>none</AccessConstraints><LayerLimit>16</LayerLimit><MaxWidth>4096</MaxWidth><MaxHeight>4096</MaxHeight></Service>'
        '<Capability><Request><GetMap><Format>image/png</Format><Format>image/jpeg</Format></GetMap></Request>'
        '<Exception><Format>XML</Format><Format>INIMAGE</Format></Exception>'
        '<Layer queryable="0"><Title>All layers</Title><CRS>CRS:84</CRS><CRS>EPSG:4326</CRS>%s'
        '<Layer queryable="1" opaque="1"><Name>relief</Name><Title>Shaded relief</Title><Abstract>Hill shading.</Abstract>%s'
        '<MaxScaleDenominator>5000000</MaxScaleDenominator></Layer>'
        '<Layer queryable="0"><Name>roads</Name><Title>Roads</Title>%s<MinScaleDenominator>1000</MinScaleDenominator></Layer>'
        '</Layer></Capability></WMS_Capabilities>'
    ) % (WMS_NS, root_residue, bbox("5.5", "15.25", "47", "55.125"), bbox("5.5", "15.25", "47", "55.125"),
         bbox("6", "15", "47.5", "55"))


def wms_vectors():
    me = "wms-capabilities"
    out = {}
    root_extra = ' xmlns:xlink="%s"' % XLINK
    model = {
        "@kind": "capabilities",
        "wms.update_sequence": "17",
        "wms.title": "Relief and roads",
        "wms.abstract": "Shaded relief with a road overlay.",
        "wms.keywords.#": "2",
        "wms.keywords[1].wms.keyword": "roads",
        "wms.contact_person": "Map Desk",
        "wms.contact_organization": "Example Mapping Office",
        "wms.contact_city": "Springfield",
        "wms.layer_limit": "16",
        "wms.max_width": "4096",
        "wms.getmap_formats.#": "2",
        "wms.getmap_formats[0].wms.format": "image/png",
        "wms.exception_formats[1].wms.format": "INIMAGE",
        "wms.layer_title": "All layers",
        "wms.layer_crs.#": "2",
        "wms.layer_crs[1].wms.crs": "EPSG:4326",
        "wms.layer_west": "5.5",
        "wms.layer_north": "55.125",
        "wms.layers.#": "2",
        "wms.layers[0].wms.name": "relief",
        "wms.layers[0].wms.queryable": "1",
        "wms.layers[0].wms.max_scale": "5000000",
        "wms.layers[1].wms.south": "47.5",
        "wms.layers[1].wms.min_scale": "1000",
        "@absent": ["lat", "lon"],
    }
    out["01-capabilities-roundtrip"] = vec(
        "capabilities-roundtrip", me, me, wms_doc(root_extra), wms_canonical(root_extra), model=model,
        ref=REF_WMS + "; mapped elements in schema order; OnlineResource (xlink attributes), DCPType, GetCapabilities and BoundingBox are not mapped and dropped; the root attribute xmlns:xlink is residue")

    doc = wms_doc().replace('version="1.3.0"', 'version="1.1.1"')
    out["02-other-version-is-no-kind"] = vec(
        "other-version-is-no-kind", me, me, doc, error="no-kind",
        ref=REF_WMS + "; the root's version attribute must be 1.3.0")

    doc = wms_doc().replace('<WMS_Capabilities xmlns="%s"' % WMS_NS,
                            '<wms:WMS_Capabilities xmlns:wms="%s"' % WMS_NS).replace(
        "</WMS_Capabilities>", "</wms:WMS_Capabilities>")
    out["03-prefixed-root-is-no-kind"] = vec(
        "prefixed-root-is-no-kind", me, me, doc, error="no-kind",
        ref=REF_WMS + "; the xml wire compares element names as written: the root wms:WMS_Capabilities is not WMS_Capabilities, and in a pack with kinds a root that matches no kind is no-kind (ruling 11 of 0.6)")

    doc = wms_doc().replace("<LayerLimit>16</LayerLimit>", "<LayerLimit>sixteen</LayerLimit>")
    out["04-layer-limit-not-integer"] = vec(
        "layer-limit-not-integer", me, me, doc, error="transform-decode",
        ref=REF_WMS + "; LayerLimit is a positive integer")
    return out


# -- CityJSON 2.0 -------------------------------------------------------------

def cj_vectors():
    me = "cityjson"
    out = {}
    inp = ('{"type":"CityJSON","version":"2.0",'
           '"transform":{"scale":[0.001,0.001,0.001],"translate":[84710.1,446846,-5.3]},'
           '"metadata":{"identifier":"b6a1c0de-0000-4000-8000-000000000001","referenceSystem":"https://www.opengis.net/def/crs/EPSG/0/7415",'
           '"title":"Two buildings","referenceDate":"2024-03-01","geographicalExtent":[84710.1,446846,-5.3,84757.1,446944,40.9],'
           '"pointOfContact":{"contactName":"Survey Office","emailAddress":"survey at example dot org","contactType":"organization","role":"custodian","website":"https://survey.example.org","address":{"locality":"Delft"}}},'
           '"CityObjects":{"b1":{"type":"Building","attributes":{"storeys":3,"roofType":"flat"},"geometry":[{"type":"Solid","lod":"1","boundaries":[[[[0,1,2,3]]]]}]}},'
           '"vertices":[[0,0,0],[1000,0,0],[1000,1000,0],[0,1000,0]]}')
    exp = ('{"type":"CityJSON","version":"2.0",'
           '"transform":{"scale":[0.001,0.001,0.001],"translate":[84710.1,446846,-5.3]},'
           '"metadata":{"title":"Two buildings","identifier":"b6a1c0de-0000-4000-8000-000000000001","referenceDate":"2024-03-01",'
           '"referenceSystem":"https://www.opengis.net/def/crs/EPSG/0/7415",'
           '"geographicalExtent":[84710.1,446846,-5.3,84757.1,446944,40.9],'
           '"pointOfContact":{"contactName":"Survey Office","emailAddress":"survey at example dot org","role":"custodian","website":"https://survey.example.org","contactType":"organization","address":{"locality":"Delft"}}},'
           '"CityObjects":{"b1":{"type":"Building","attributes":{"storeys":3,"roofType":"flat"}}}}')
    out["01-city-model-roundtrip"] = vec(
        "city-model-roundtrip", me, me, inp, exp,
        model={"@kind": "city-model",
               "cityjson.scale.#": "3", "cityjson.scale[0].cityjson.component": "0.001",
               "cityjson.translate[2].cityjson.component": "-5.3",
               "cityjson.title": "Two buildings",
               "cityjson.reference_system": "https://www.opengis.net/def/crs/EPSG/0/7415",
               "cityjson.extent.#": "6", "cityjson.extent[5].cityjson.component": "40.9",
               "cityjson.contact_name": "Survey Office", "cityjson.contact_role": "custodian",
               "@absent": ["lat", "lon", "uid"]},
        ref=REF_CJ + "; scalar members of CityObjects are residue; the geometry array and the vertices array are not carried (arrays outside a group, Version 0.5)")

    inp = ('{"type":"CityJSONFeature","id":"b1",'
           '"CityObjects":{"b1":{"type":"Building","attributes":{"storeys":3}}},'
           '"vertices":[[0,0,0],[1000,0,0]]}')
    exp = '{"type":"CityJSONFeature","id":"b1","CityObjects":{"b1":{"type":"Building","attributes":{"storeys":3}}}}'
    out["02-feature-roundtrip"] = vec(
        "feature-roundtrip", me, me, inp, exp, model={"@kind": "feature", "uid": "b1"},
        ref=REF_CJ + "; section 7.2: id is the identifier of the feature's parent City Object; vertices are not carried")

    out["03-feature-to-geojson"] = vec(
        "feature-to-geojson", me, "geojson", inp, '{"type":"Feature","geometry":null,"properties":{},"id":"b1"}',
        model={"@kind": "feature", "uid": "b1"},
        ref=REF_CJ + "; the id carries as uid; no position is bound, so the geometry is null (packs/geojson/pack.def)")

    out["04-other-version-is-no-kind"] = vec(
        "other-version-is-no-kind", me, me,
        '{"type":"CityJSON","version":"1.1","transform":{"scale":[1,1,1],"translate":[0,0,0]},"CityObjects":{},"vertices":[]}',
        error="no-kind", ref=REF_CJ + "; section 1: version holds the minor version; this pack reads 2.0")

    out["05-from-geojson-feature"] = vec(
        "cityjson-from-geojson-feature", "geojson", me, '{"type":"Feature","geometry":null,"properties":{},"id":"b7"}',
        '{"type":"CityJSONFeature","id":"b7"}', model={"uid": "b7"},
        ref=REF_CJ + "; the kind is chosen by `requires uid`; CityObjects and vertices cannot be written (pack.md)")
    return out


def main():
    gt = sys.argv[1]
    check = "--check" in sys.argv[2:]
    sets = [("geopackage-geometry-be", gpkg_vectors(False)),
            ("geopackage-geometry-le", gpkg_vectors(True)),
            ("wms-capabilities", wms_vectors()),
            ("cityjson", cj_vectors())]
    bad = 0
    for pack, vs in sets:
        for fn, v in vs.items():
            # A vector lives under its `from` pack; one that converts into this
            # pack from another is packs/<from>/vectors/to-<pack>-<name>.json.
            if v["from"] == pack:
                path = os.path.join(gt, "packs", pack, "vectors", fn + ".json")
            else:
                path = os.path.join(gt, "packs", v["from"], "vectors", "to-%s-%s.json" % (pack, fn))
            text = json.dumps(v, indent=2, ensure_ascii=False) + "\n"
            if check:
                try:
                    cur = open(path, encoding="utf-8").read()
                except OSError:
                    cur = None
                if cur != text:
                    print("differs: " + os.path.relpath(path, gt))
                    bad += 1
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
    if check:
        print("ogc-geo-vectors: %s" % ("ok" if not bad else "%d differ" % bad))
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
