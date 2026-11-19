#!/usr/bin/env python3
"""Write the vectors of the GTFS Schedule packs (gtfs-agency, gtfs-stops, ...).

Each pack reads one data row of one GTFS file, with the columns in the order
the GTFS Schedule Reference lists them (google/transit, Apache-2.0, commit
2ce6aa7, gtfs/spec/en/reference.md). This script holds its own copy of those
column lists, builds each row from values written for these vectors, and works
out the decoded values and the GeoJSON and CoT forms by the rules of
spec/engine-spec.md (0.10, the text wire) and of those packs. It reads no
pack.def and calls no goat-transformers engine.

Inputs: none; every value is stated in this file. The same run always gives
the same bytes. With --check nothing is written and the exit status is 1 when a
committed file differs from what this script writes.

Usage: python3 -I tools/gen/gtfs-vectors.py [--out DIR] [--check]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

# column order of each file, as the reference lists it (type: s string, i int, f float)
COLUMNS = {
    "agency": "agency_id agency_name agency_url agency_timezone agency_lang agency_phone agency_fare_url "
              "agency_email cemv_support:i",
    "stops": "stop_id stop_code stop_name tts_stop_name stop_desc stop_lat:f stop_lon:f zone_id stop_url "
             "location_type:i parent_station stop_timezone wheelchair_boarding:i level_id platform_code stop_access:i",
    "routes": "route_id agency_id route_short_name route_long_name route_desc route_type:i route_url route_color "
              "route_text_color route_sort_order:i continuous_pickup:i continuous_drop_off:i network_id cemv_support:i",
    "trips": "route_id service_id trip_id trip_headsign trip_short_name direction_id:i block_id shape_id "
             "wheelchair_accessible:i bikes_allowed:i cars_allowed:i safe_duration_factor:f safe_duration_offset:f",
    "stop-times": "trip_id arrival_time departure_time stop_id location_group_id location_id stop_sequence:i "
                  "stop_headsign start_pickup_drop_off_window end_pickup_drop_off_window pickup_type:i "
                  "drop_off_type:i continuous_pickup:i continuous_drop_off:i shape_dist_traveled:f timepoint:i "
                  "pickup_booking_rule_id drop_off_booking_rule_id",
    "calendar": "service_id monday:i tuesday:i wednesday:i thursday:i friday:i saturday:i sunday:i start_date end_date",
    "calendar-dates": "service_id date exception_type:i",
    "shapes": "shape_id shape_pt_lat:f shape_pt_lon:f shape_pt_sequence:i shape_dist_traveled:f",
    "frequencies": "trip_id start_time end_time headway_secs:i exact_times:i",
    "transfers": "from_stop_id to_stop_id from_route_id to_route_id from_trip_id to_trip_id transfer_type:i "
                 "min_transfer_time:i",
    "pathways": "pathway_id from_stop_id to_stop_id pathway_mode:i is_bidirectional:i length:f traversal_time:i "
                "stair_count:i max_slope:f min_width:f signposted_as reversed_signposted_as",
    "levels": "level_id level_index:f level_name",
    "feed-info": "feed_publisher_name feed_publisher_url feed_lang default_lang feed_start_date feed_end_date "
                 "feed_version feed_contact_email feed_contact_url",
    "attributions": "attribution_id agency_id route_id trip_id organization_name is_producer:i is_operator:i "
                    "is_authority:i attribution_url attribution_email attribution_phone",
}
# the shared keys a pack binds, by column: core key first (engine-spec 0.5 ruling 16)
SHARED = {"stops": {"stop_id": "uid", "stop_name": "callsign", "stop_lat": "lat", "stop_lon": "lon"},
          "shapes": {"shape_pt_lat": "lat", "shape_pt_lon": "lon"}}


def cols(pack):
    out = []
    for c in COLUMNS[pack].split():
        name, _, t = c.partition(":")
        out.append((name, t or "s"))
    return out


def num(x):
    """Shortest round-trip decimal, plain notation (engine-spec 0.1.1 ruling 3)."""
    if x == int(x) and abs(x) < 2 ** 53:
        return str(int(x))
    r = repr(float(x))
    assert "e" not in r and "E" not in r
    return r


def row(pack, values):
    """The row text: every column in order, empty where no value is given."""
    names = [n for n, _ in cols(pack)]
    assert set(values) <= set(names), set(values) - set(names)
    return ",".join(values.get(n, "") for n in names)


def model(pack, values):
    m = {}
    types = dict(cols(pack))
    for n, text in values.items():
        if text == "":
            continue
        t = types[n]
        v = text if t == "s" else str(int(text)) if t == "i" else num(float(text))
        m["gtfs." + n] = v
        if n in SHARED.get(pack, {}):
            m[SHARED[pack][n]] = v
    return m


def geojson(lat, lon, uid=None, callsign=None):
    props = '{"callsign":%s}' % json.dumps(callsign) if callsign is not None else "{}"
    s = '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":%s' % (num(lon), num(lat), props)
    return s + (',"id":%s}' % json.dumps(uid) if uid is not None else "}")


def cot(lat, lon, uid=None, callsign=None):
    attrs = ['version="2.0"'] + (['uid="%s"' % uid] if uid is not None else []) + ['type="a-u-X"']
    point = '<point lat="%s" lon="%s" hae="9999999" ce="9999999" le="9999999"/>' % (num(lat), num(lon))
    detail = '<detail><contact callsign="%s"/></detail>' % callsign if callsign is not None else ""
    return "<event %s>%s%s</event>" % (" ".join(attrs), point, detail)


REF = "GTFS Schedule Reference (google/transit, commit 2ce6aa7), %s; row written by tools/gen/gtfs-vectors.py"

ROWS = {
    "agency": {"agency_id": "ag1", "agency_name": "Example Transit", "agency_url": "https://transit.example.org",
               "agency_timezone": "Europe/Berlin", "agency_lang": "de", "agency_phone": "+49 30 1234567",
               "cemv_support": "1"},
    "stops": {"stop_id": "S100", "stop_code": "100", "stop_name": "Central Station", "stop_lat": "52.525",
              "stop_lon": "13.369", "zone_id": "A", "location_type": "1", "wheelchair_boarding": "1",
              "platform_code": ""},
    "routes": {"route_id": "R1", "agency_id": "ag1", "route_short_name": "1", "route_long_name": "Airport Line",
               "route_type": "3", "route_color": "0039A6", "route_text_color": "FFFFFF", "route_sort_order": "10"},
    "trips": {"route_id": "R1", "service_id": "WD", "trip_id": "T1", "trip_headsign": "Airport", "direction_id": "0",
              "shape_id": "SH1", "wheelchair_accessible": "1", "bikes_allowed": "2", "safe_duration_factor": "1.5",
              "safe_duration_offset": "120"},
    "stop-times": {"trip_id": "T1", "arrival_time": "25:35:00", "departure_time": "25:36:30", "stop_id": "S100",
                   "stop_sequence": "7", "pickup_type": "0", "drop_off_type": "1", "shape_dist_traveled": "1234.5",
                   "timepoint": "1"},
    "calendar": {"service_id": "WD", "monday": "1", "tuesday": "1", "wednesday": "1", "thursday": "1",
                 "friday": "1", "saturday": "0", "sunday": "0", "start_date": "20260101", "end_date": "20261231"},
    "calendar-dates": {"service_id": "WD", "date": "20261225", "exception_type": "2"},
    "shapes": {"shape_id": "SH1", "shape_pt_lat": "52.5251", "shape_pt_lon": "13.3694", "shape_pt_sequence": "3",
               "shape_dist_traveled": "250.75"},
    "frequencies": {"trip_id": "T1", "start_time": "06:00:00", "end_time": "09:30:00", "headway_secs": "600",
                    "exact_times": "0"},
    "transfers": {"from_stop_id": "S100", "to_stop_id": "S200", "transfer_type": "2", "min_transfer_time": "180"},
    "pathways": {"pathway_id": "P1", "from_stop_id": "S100", "to_stop_id": "S101", "pathway_mode": "2",
                 "is_bidirectional": "1", "length": "12.5", "traversal_time": "30", "stair_count": "-20",
                 "signposted_as": "Platform 3"},
    "levels": {"level_id": "L-1", "level_index": "-1", "level_name": "Underground"},
    "feed-info": {"feed_publisher_name": "Example Transit", "feed_publisher_url": "https://transit.example.org",
                  "feed_lang": "de", "feed_start_date": "20260101", "feed_end_date": "20261231",
                  "feed_version": "2026.1"},
    "attributions": {"attribution_id": "A1", "agency_id": "ag1", "organization_name": "Example Data Co",
                     "is_producer": "1", "is_operator": "0", "is_authority": "0"},
}


def build_vectors():
    out = {}
    for pack, values in ROWS.items():
        p = "gtfs-" + pack
        r = row(pack, values)
        out.setdefault(p, []).append({
            "name": pack + "-round-trip", "from": p, "to": p, "input": r, "expect": r,
            "model": model(pack, values), "source": "constructed",
            "reference": REF % ("columns of %s.txt in the reference's order" % pack.replace("-", "_"))})
    st = ROWS["stops"]
    r = row("stops", st)
    lat, lon = float(st["stop_lat"]), float(st["stop_lon"])
    out["gtfs-stops"] += [
        {"name": "stops-to-geojson", "from": "gtfs-stops", "to": "geojson", "input": r,
         "expect": geojson(lat, lon, uid="S100", callsign="Central Station"), "source": "constructed",
         "reference": REF % "stop_lat and stop_lon are WGS 84 decimal degrees (Field Types, Latitude and "
                            "Longitude); stop_id as id and stop_name as callsign; geojson canonical form by hand"},
        {"name": "stops-to-cot-xml", "from": "gtfs-stops", "to": "cot-xml", "input": r,
         "expect": cot(lat, lon, uid="S100", callsign="Central Station"), "source": "constructed",
         "reference": REF % "cot-xml canonical form by hand from its pack"},
        {"name": "geojson-to-stops", "from": "geojson", "to": "gtfs-stops",
         "input": '{"type":"Feature","geometry":{"type":"Point","coordinates":[-0.1276,51.5072,11]},'
                  '"properties":{"callsign":"Riverside"},"id":"S7"}',
         "expect": row("stops", {"stop_id": "S7", "stop_name": "Riverside", "stop_lat": "51.5072",
                                 "stop_lon": "-0.1276"}),
         "source": "constructed",
         "reference": REF % "id, callsign and the point become stop_id, stop_name, stop_lat and stop_lon; the "
                            "altitude has no column; every other column is empty, all 16 are written"},
        {"name": "stops-short-row-reads-the-first-columns", "from": "gtfs-stops", "to": "gtfs-stops",
         "input": "S5,,Market,,,48.1,11.5",
         "expect": row("stops", {"stop_id": "S5", "stop_name": "Market", "stop_lat": "48.1", "stop_lon": "11.5"}),
         "model": {"uid": "S5", "lat": "48.1", "lon": "11.5"}, "source": "constructed",
         "reference": REF % "a row whose file has only the first seven columns: the others are absent, and "
                            "encode writes all 16"},
        {"name": "stops-header-row-is-not-a-row", "from": "gtfs-stops", "to": "gtfs-stops",
         "input": ",".join(n for n, _ in cols("stops")), "expect_error": "transform-decode",
         "source": "constructed",
         "reference": "the header row of stops.txt: its stop_lat column holds the text 'stop_lat', not a "
                      "number, so the row does not decode"},
        {"name": "stops-non-ascii-name-is-malformed", "from": "gtfs-stops", "to": "gtfs-stops",
         "input": "S9,,Café Platz,,,48.1,11.5", "expect_error": "malformed-wire", "source": "constructed",
         "reference": "GTFS text is UTF-8; the text wire accepts characters 0x20 to 0x7E only "
                      "(engine-spec 0.10, Reading a record, step 2)"},
    ]
    sh = ROWS["shapes"]
    out["gtfs-shapes"].append(
        {"name": "shapes-to-geojson", "from": "gtfs-shapes", "to": "geojson", "input": row("shapes", sh),
         "expect": geojson(float(sh["shape_pt_lat"]), float(sh["shape_pt_lon"])), "source": "constructed",
         "reference": REF % "one shape point as a GeoJSON point; shape_id is not an entity id (many rows share "
                            "it), so it is not uid"})
    return out


def build(out):
    written = {}
    for pack, vecs in build_vectors().items():
        vdir = "packs/%s/vectors" % pack
        names = set()
        for i, v in enumerate(vecs, 1):
            rel = "%s/%02d-%s.json" % (vdir, i, v["name"])
            names.add(rel.split("/")[-1])
            out.write(rel, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        for old in out.listdir(vdir):
            if old not in names:
                out.remove(vdir + "/" + old)
        written[pack] = len(vecs)
    return written


def main(argv=None):
    return genio.vector_main("gtfs-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
