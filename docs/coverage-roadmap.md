# Format coverage

Status: Written. This page lists the public formats the library covers and the
public formats it does not yet cover, with what each uncovered format needs.

A format is reached through a wire type (an engine's codec for a family of
encodings) and a pack (the format's data files). The wire types the engines
have are `xml`, `geojson`, `json`, `protobuf` and `bits`. A format marked "not
built" either needs only a pack, or needs an engine feature that the last table
on this page lists.

## Tracks, sensors and situational awareness

| Format | Wire type | Status | Open-source codecs to compare with |
|---|---|---|---|
| Cursor on Target (CoT) event XML | `xml` | Built: pack `cot-xml` | pytak, node-cot, taky |
| CoT protobuf (TAK protocol version 1) | `protobuf` | Built: pack `cot-protobuf`, 2 message kinds. Converts to and from CoT XML on the 13 keys the two share. The stream framing is outside the pack | takproto |
| GeoJSON (IETF RFC 7946) | `geojson` | Built: pack `geojson` | GDAL/OGR |
| SAPIENT (BSI Flex 335) | `protobuf` | Built: packs `sapient` (v2.0) and `sapient-v1` (v1.0), 9 message kinds each, generated from the published protobuf files | dstl/SAPIENT-Proto-Files |
| Integrated Sensor Architecture (ISA) | `protobuf`, `xml` | Built: packs `isa` and `isa-message` (IPL 3.7), `isa-ipl1` (IPL 1.6), `isa-xml` (IPL 4.7) | |
| Canonical Track v2 (open-billie) | `json` | Built: pack `canonical-track-v2` | USAREUR-AF/open-billie |
| NATO Vector Graphics (NVG) 1.5 | `xml` | Built: pack `nvg`, point only. Other geometry types are not built | |
| ASTERIX | `bits`, sequential | 27 categories built from machine-readable definitions (001, 002, 004, 007 to 011, 015 to 021, 023, 025, 032, 034, 048, 062 to 065, 150, 205, 240, 247), one record per block; several records per block and item lists selected by a value are not built | asterix-specs, jASTERIX, asterix4py |
| STANAG 4607 GMTI | `bits` | Not built | pentlandedge/s4607 |
| STANAG 4676 ISR tracking | `xml` | Not built | |
| NFFI (STANAG 5527) | `xml` | Not built | |

## Command and control message catalogs

| Format | Wire type | Status |
|---|---|---|
| Universal Command and Control Interface (UCI) 2.6 | `xml` | Built: pack `uci`, 725 message kinds, generated from the published XML schema |
| Autonomy Government Reference Architecture (A-GRA) 6.0a | `xml` | Built: pack `a-gra`, 860 message kinds, generated from the published XML schema |
| MIM / JC3IEDM | `xml` | Not built |

## Aviation, maritime and unmanned systems

| Format | Wire type | Status | Open-source codecs to compare with |
|---|---|---|---|
| ADS-B on Mode S extended squitter | `bits` | Built: pack `adsb`, 29 message kinds of downlink format 17, raw field values. Position needs two paired messages and is outside the pack | pyModeS, dump1090, readsb |
| NMEA 2000 parameter groups | `bits` | Built: pack `nmea2000`, 473 of the 647 definitions in the CANboat database. `packs/nmea2000/pack.md` lists what the others need | CANboat |
| MAVLink 2, common message set | `bits` | Built: pack `mavlink2`, 235 message kinds at full payload length. Trimmed payloads and the checksum need framing | pymavlink |
| ASTM F3411 Remote ID | `bits` | Built: pack `remote-id`, 8 message kinds including the Message Pack | opendroneid-core-c |
| AIS / AIVDM | six-bit armor | Not built. Needs the six-bit armor wire | pyais, libais, gpsd |
| NMEA 0183 | text grammar | Not built. Needs the text-grammar wire | pynmea2 |
| KLV / MISB ST 0601 | type-length-value | Not built. Needs the type-length-value wire | klvdata |
| NITF / NSIF | type-length-value | Not built. Needs the type-length-value wire | GDAL, NITRO |
| GPX 1.1 | `xml` | Built: pack `gpx`, 3 message kinds (waypoint, route point, track point), the first point of a document | GDAL/OGR, gpxpy |
| KML 2.2 Placemark | `xml` | Built: pack `kml`, 2 message kinds; the coordinate text is carried whole until a text-split transform exists | GDAL/OGR |
| GML | `xml` | Not built. Needs XML namespaces and prefixes, and a text-split transform for `pos` | GDAL/OGR |
| FIXM Core 4.3 | `xml` | Not built. Needs XML namespaces and prefixes (two namespaces in one document), and a text-split transform for `pos` | |
| AIXM 5.1.1 | `xml` | Not built. Needs XML namespaces and prefixes, including namespaced attributes (`gml:id`, `xlink:href`) | |

## Formats whose specification is not public

A format whose specification is not public is supported in the same way: as a
pack and, where needed, a model module. That pack is kept in a private overlay
repository and is not in this one ([boundary.md](boundary.md)). The engines in
this repository run an overlay's packs unchanged, and such a format converts to
and from every public format through the public model modules.

Overlays are maintained for these families. The table gives each family's
public designation only; no layout of any of them is in this repository.

| Family | Public designation | Wire |
|---|---|---|
| J-series tactical data link messages | MIL-STD-6016, STANAG 5516 | `bits` |
| Joint range extension, application protocol C | MIL-STD-3011, STANAG 5616 | `bits` |
| Situation awareness data link | | `bits` |
| Interface definitions of individual sensor and command systems | each under its owner's terms | `protobuf`, `json` |

An overlay is shared only with a party that is itself entitled to hold the
specification it was written from, under that specification's distribution
terms and the law that applies to it. To ask about one, open an issue in this
repository titled "overlay access" that names the family and your organization
and gives no technical detail. The maintainers answer through an official
channel, not in the issue.

## Engine features that formats above need

| Feature | Status | Needed by |
|---|---|---|
| Sequential layouts in `bits` (presence fields, repeats, extensible items, stated lengths) | Built | ASTERIX |
| Text-grammar wire (delimited or positional text records) | Built (spec 0.10, `wire text`) | NMEA 0183 |
| Type-length-value wire | Designed | KLV / MISB ST 0601, NITF |
| Six-bit armor wire (ASCII-armored bit payloads) | Designed | AIS / AIVDM |
| Layered wires and framing (declared lengths, trimmed payloads, checksums) | Designed | MAVLink frames, NMEA 2000 fast-packet transport |

[roadmap.md](roadmap.md) lists these with the other designed additions to the
pack language.

## Related work

- GDAL/OGR converts between geospatial formats through one driver model.
- MAVLink generates codecs for many languages from one XML message definition.
- CANboat describes NMEA 2000 parameter groups as data.
- [first-bite](https://github.com/USAREUR-AF/first-bite) decodes fixed-layout
  binary messages from JSON dictionaries.

goat-transformers applies the same idea, formats as data, to conversion between
formats of different families, with one independent engine per language.
