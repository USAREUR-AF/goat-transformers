# goat-transformers

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/hub-dark.svg">
  <img src="docs/figures/hub-light.svg" width="760" alt="Public formats, among them Cursor on Target, GeoJSON, SAPIENT, MAVLink 2, NMEA 2000, ADS-B, Remote ID and 27 ASTERIX categories, each connect to one shared model in the center. A dashed outer ring holds formats kept in a private overlay, which connect to the same shared model.">
</picture>

goat-transformers converts a message in any supported format to any other
supported format, and each format is a data file that seven independently
written engines read and must agree on, byte for byte. Below, the 25 bytes a
drone broadcasts become a tactical-map event and a ship-instrument message, and
no engine holds code for any of the three formats.

[![conformance](https://github.com/USAREUR-AF/goat-transformers/actions/workflows/conformance.yml/badge.svg)](https://github.com/USAREUR-AF/goat-transformers/actions/workflows/conformance.yml)
[![REUSE](https://img.shields.io/badge/REUSE-compliant-green.svg)](LICENSING.md)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**2,531 formats · 13,663 message kinds · 17,628 conversion vectors · 7 engines**, counted
by [`tools/repo-stats`](tools/repo-stats).

```console
$ echo 122624160b42bf241b6ed1b4b69808ac0870086b53150e0200 | goat-xf convert --from remote-id --to cot-xml
<event version="2.0" type="a-u-X"><point lat="45.539309" lon="-122.966389" hae="110" ce="9999999" le="9999999"/><detail/></event>
$ echo 122624160b42bf241b6ed1b4b69808ac0870086b53150e0200 | goat-xf convert --from remote-id --to nmea2000
01f80142bf241b6ed1b4b6
$ goat-xf convert --from canonical-track-v2 --to asterix-cat062 --set cat062.sac=1 --set cat062.sic=7 < track.json
3e001f9b0d1001075460100000000000000000ffce00110137810101000050
```

Commands 1 and 2: an ASTM F3411 Remote ID Location message becomes a Cursor on Target (CoT) event (`9999999` is CoT's "not known") and NMEA 2000 parameter group 129025.\
Command 3: a track in JSON becomes 31 bytes of ASTERIX Category 062, equal byte for byte to the output of a hand-written encoder ([the table below](#conversions-and-what-carries)).


## The idea in five sentences

1. A format is a data file, called a **pack**: one line for each field says
   where the value sits in the message and which key of the model it fills.
2. There is one **shared model**: a set of typed keys in fixed units (degrees,
   meters, meters per second, milliseconds since 1970).
3. A conversion decodes the source message to the model and encodes the model
   to the target, so any format converts to any other and N formats need N
   packs, not N×N converters.
4. Seven **engines** (Rust, Go, Python, Java, C++, Erlang, Zig) each read the
   same packs; each is written from the specification and the test messages,
   never from another engine's source, and all seven must produce the same output for
   every test message.
5. Packs written from public sources are in this repository; a pack for a
   format whose specification is not public is kept in a private **overlay**
   that the same engines read.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/journey-dark.svg">
  <img src="docs/figures/journey-light.svg" width="760" alt="Three values of a 25-byte Remote ID Location message, latitude, longitude and height, are read by three field lines of the remote-id pack into the model keys lat, lon and hae, then written by three field lines of the cot-xml pack as attributes of the point element of a Cursor on Target event.">
</picture>

## What the repository holds

Counted from the tree by `python3 -I tools/repo-stats`.

| | Count |
|---|---:|
| Formats | 2,531 |
| Message kinds (one message layout of a format, such as one MAVLink message or one NMEA 2000 parameter group) | 13,663 |
| Typed keys in the shared model, in 1,531 modules | 249,773 |
| Lists in the shared model (parts of a message that repeat) | 26,619 |
| Conversion vectors (an input message and the exact expected output) | 17,628 |
| Load vectors (a pack that must load, or must be refused with a named error) | 862 |
| Synthetic formats that exercise each rule of the specification | 156 |
| Wire types (an engine's codec for a family of encodings): `xml`, `json`, `geojson`, `protobuf`, `bits`, `text`, `tlv` | 7 |
| Engines, each using only its language's standard library | 7 |
| WebAssembly module of the Rust engine, small build, no imports | 376,470 bytes |

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/catalog-dark.svg">
  <img src="docs/figures/catalog-light.svg" width="760" alt="Every public format, grouped into 62 families in 11 domains: air, land vehicles, sea, space, uncrewed systems and robots, C2 and tactical, sensors, transport, IoT, networks, and maps, weather and alerts. Each family is a tile with its number of packs, from ArduPilot DataFlash log, PX4 ULog, Space Data Standards and Cyphal with hundreds each, to single-pack formats such as GDL 90, AIS and CAP. Synthetic conformance and demo packs are not shown.">
</picture>

The figure is drawn from `packs/` by `python3 -I tools/catalog-figure.py`; `tools/catalog-families.json` names the family and domain of each pack.

| Pack | Format | Wire | Message kinds |
|---|---|---|---:|
| `cot-xml` | Cursor on Target event XML | `xml` | 1 |
| `cot-protobuf` | TAK protocol version 1, the protobuf form of a Cursor on Target event | `protobuf` | 2 |
| `geojson` | GeoJSON Feature (IETF RFC 7946) | `geojson` | 1 |
| `nvg` | NATO Vector Graphics 1.5, point | `xml` | 1 |
| `canonical-track-v2` | Canonical Track v2 of [open-billie](https://github.com/USAREUR-AF/open-billie) | `json` | 1 |
| `geo-track-v1` | GeoTrackV1, the display track of [goatstuff](https://github.com/USAREUR-AF/goatstuff)'s map | `json` | 1 |
| `sapient` | SAPIENT, BSI Flex 335 v2.0 | `protobuf` | 9 |
| `sapient-v1` | SAPIENT, BSI Flex 335 v1.0 | `protobuf` | 9 |
| `c2sim` | C2SIM (SISO-STD-019-2020), position report | `xml` | 1 |
| `isa` | Integrated Sensor Architecture, IPL 3.7 `Event` | `protobuf` | 1 |
| `isa-message` | Integrated Sensor Architecture, IPL 3.7 message union | `protobuf` | 7 |
| `isa-ipl1` | Integrated Sensor Architecture, IPL 1.6 message union | `protobuf` | 7 |
| `isa-xml` | Integrated Sensor Architecture, IPL 4.7 XML form | `xml` | 7 |
| `uci` | Universal Command and Control Interface (UCI) 2.6 | `xml` | 725 |
| `a-gra` | Autonomy Government Reference Architecture (A-GRA) 6.0a | `xml` | 860 |
| `uci-2.5` | UCI 2.5, the message set of Open Mission Systems 2.5 | `xml` | 722 |
| `nmea2000` | NMEA 2000 parameter groups, from the CANboat database | `bits` | 473 |
| `nmea2000-seq` | NMEA 2000 parameter groups with counted repeating sets, from the CANboat database | `bits`, sequential | 15 |
| `mavlink2` | MAVLink 2, common message set | `bits` | 235 |
| `mavlink2-ardupilotmega` … `mavlink2-uavionix` | 13 MAVLink 2 dialects, each the messages its own definition file adds, generated by `tools/gen/mavlink2pack.py` | `bits` | 153 in all |
| `adsb` | ADS-B on Mode S extended squitter (downlink format 17) | `bits` | 32 |
| `adsb-df18` | ADS-B on Mode S extended squitter downlink format 18 (non-transponder ADS-B, TIS-B, ADS-R), layouts from pyModeS | `bits` | 32 |
| `asterix-cat062` | ASTERIX Category 062 system track, written by hand | `bits` | 1 |
| `asterix-cat001` … `asterix-cat247`, `asterix-cat062-full` | 27 ASTERIX categories, 001 to 247, each generated by `tools/gen/asterix2pack.py` from the machine-readable category definitions of `zoranbosnjak/asterix-specs`, every item of the category's first item list | `bits` | 1 each |
| `asterix-cat021-ed023`, `asterix-cat021-ed026` | ASTERIX Category 021 editions 0.23 and 0.26, still sent by ADS-B ground stations, generated the same way | `bits` | 1 each |
| `remote-id` | ASTM F3411 Remote ID (OpenDroneID) | `bits` | 8 |
| `drip` | DRIP authentication formats (IETF RFC 9575): Link, Wrapper, Manifest | `bits` | 28 |
| `ais-binary` | AIS binary application messages of types 6 and 8 with fixed layouts | `armor` | 21 |
| `dbc-<file>`, 90 packs | CAN DBC files of opendbc, read as SocketCAN frames, generated by `tools/gen/dbc2pack.py` | `bits` | 4,905 in all |
| `dbc-tesla-model3` | Tesla Model 3 / Model Y CAN DBC | `bits` | 393 |
| `px4-ulog-<topic>`, 301 packs | PX4 uORB topics as ULog data, generated by `tools/gen/uorb2pack.py` | `bits` | 1 each |
| `sbp-<package>`, 22 packs | Swift Navigation Binary Protocol, generated by `tools/gen/sbp2pack.py` | `bits` | 144 in all |
| `ubx-<class>`, 14 packs | u-blox UBX messages, generated by `tools/gen/ubx2pack.py` | `bits` | 205 in all |
| `rtcm3` | RTCM 3 message bodies, generated by `tools/gen/rtcm2pack.py` from pyrtcm | `bits` | 75 |
| `sbf-<group>`, 17 packs | Septentrio SBF blocks, generated by `tools/gen/sbf2pack.py` from pysbf2 | `bits` | 83 in all |
| `arsdk-<feature>`, 44 packs | Parrot ARSDK commands and events, generated by `tools/gen/arsdk2pack.py` | `bits` | 654 in all |
| `ardupilot-log-<name>`, 342 packs | ArduPilot DataFlash log messages, generated by `tools/gen/aplog2pack.py` | `bits` | 1 each |
| `ipv4-header`, `ipv6-header`, `udp-header`, `tcp-header`, `icmp-header`, `ntp-header`, `dns-header` | IETF protocol headers | `bits` | 1 or more each |
| `rtp-header`, `rtcp-header`, `arp-ipv4-ethernet`, `gre-header`, `vxlan-header`, `mpls-label-entry`, `igmpv2`, `sctp-common-header`, `bfd-control` | IETF protocol headers: fixed parts, the RTP CSRC list and RTCP report blocks | `bits` | 1 or more each |
| `igmpv3`, `icmpv6-header` | IGMPv3 query and report, ICMPv6 header and fixed message bodies | `bits` | 2 and 9 |
| `coap-header`, `tls-record-header`, `dtls-record-header`, `bgp-header`, `ospfv2-header`, `vrrpv3-ipv4`, `vrrpv3-ipv6`, `ripv2-header`, `geneve-header` | CoAP, TLS and DTLS record, BGP-4, OSPFv2, VRRPv3, RIPv2 and Geneve headers | `bits` | 1 or more each |
| `dhcpv6-options`, `edns0-options` | DHCPv6 and EDNS(0) option areas | `tlv` | 1 each |
| `nitf-file-header`, `nitf-image-subheader`, `nitf-tre-<tre>` (30) | NITF 2.1 headers and TREs | `text` | 1 or more each |
| `gpsd-json` | gpsd JSON protocol | `json` | 16 |
| `nmea0183` | NMEA 0183 sentences: 23 standard, any talker, and 21 proprietary sentences that gpsd parses | `text` | 45 |
| `gpx` | GPX 1.1, the first waypoint, route point or track point | `xml` | 3 |
| `kml` | KML 2.2 Placemark | `xml` | 2 |
| `sparkplug-b` | MQTT Sparkplug B payload | `protobuf` | 1 |
| `gtfs-realtime` | GTFS Realtime feed message | `protobuf` | 1 |
| `gtfs-realtime-entity` | GTFS Realtime feed entity (vehicle position, trip update, alert, …) | `protobuf` | 6 |
| `gtfs-<file>`, 31 packs | GTFS Schedule, one data row of each of 31 files, columns in the reference's order | `text` | 1 each |
| `gbfs-<version>-<file>`, 84 packs | GBFS bikeshare feeds, versions 1.0 to 3.0 | `json` | 1 each |
| `gofs-<file>`, 8 packs | GOFS on-demand transit feeds | `json` | 1 each |
| `meshtastic` | Meshtastic MQTT service envelope | `protobuf` | 1 |
| `meshtastic-<payload>`, 11 packs | Meshtastic application payloads | `protobuf` | 1 each |
| `otlp-*`, `gnmi-*`, `openxc-vehicle-message`, `geobuf`, `waymo-frame`, `waymo-scenario` | OpenTelemetry, gNMI, OpenXC, geobuf and Waymo protobuf messages | `protobuf` | 1 or more each |
| `ccsds-ndm-xml` | CCSDS Navigation Data Messages, XML (OPM, OMM, OEM, OCM, CDM, TDM, AEM, APM, ACM, RDM) | `xml` | 10 |
| `sds-<name>`, 297 packs | Space Data Standards (OMM, OEM, CDM, TDM, EOP and others), JSON form | `json` | 1 each |
| `stix-<type>`, 39 packs | STIX 2.1 objects | `json` | 1 each |
| `cloudevents` | CloudEvents 1.0.2 JSON event | `json` | 1 |
| `openc2-lang`, `openc2-slpf` | OpenC2 1.1 language and SLPF profile commands and responses | `json` | 2 each |
| `cacao-playbook` | CACAO Security Playbooks 2.0 playbook | `json` | 1 |
| `ocsf-<class>`, 79 packs | OCSF 1.9.0 event classes | `json` | 1 each |
| `ecs-event` | Elastic Common Schema 9.5.0 event document | `json` | 1 |
| `ccsds-space-packet`, `ccsds-tm-frame`, `ccsds-tc-frame`, `ccsds-aos-frame`, `ccsds-clcw` | CCSDS space packet and transfer frame primary headers, and the link control word | `bits` | 7 in all |
| `ros2-<package>`, 78 packs | ROS 2 messages as rosbridge JSON: common_interfaces, rcl, tf2, vision, radar, gps, geographic, marine, mavros, nav2, control, moveit, px4, autoware, ublox, novatel, foxglove, lidar and camera drivers, Open-RMF, TIER IV, generated by `tools/gen/ros2msg2pack.py` from the `.msg` files | `json` | 1,099 in all |
| `cap` | OASIS Common Alerting Protocol 1.2 | `xml` | 1 |
| `readsb-aircraft` | One aircraft object of the readsb / dump1090-fa JSON output | `json` | 1 |
| `readsb-aircraft-json` | The readsb / dump1090-fa `aircraft.json` file | `json` | 1 |
| `dronecan-<type>`, 133 packs | DroneCAN (UAVCAN v0) data types and service halves, generated by `tools/gen/dsdl2pack.py` from the DSDL definitions | `bits` | 1 or more each |
| `mds` | Mobility Data Specification 2.0 | `json` | 5 |
| `osi-<message>`, 12 packs | ASAM OSI v3.8.0 messages (SensorView, SensorData, GroundTruth, TrafficUpdate and others), generated by proto2pack | `protobuf` | 1 each |
| `dis7` | DIS 7 (IEEE 1278.1) PDUs, generated by `tools/gen/dis2pack.py` from the open-dis descriptions | `bits` | 17 |
| `stac-item` | STAC Item 1.1.0, Point geometry | `geojson` | 1 |
| `wzdx-device`, `wzdx-device-4.0`, `wzdx-device-4.1`, `wzdx-*-feed*` | WZDx 4.0 to 4.2 device features and feeds | `geojson`, `json` | 1 each |
| `nws-*`, 18 packs | National Weather Service weather.gov API objects | `geojson`, `json` | 1 each |
| `gdl90` | GDL 90 message payloads with the ForeFlight extension | `bits` | 7 |
| `foxglove-location-fix` | Foxglove LocationFix | `protobuf` | 1 |
| `osm-pbf-blob-header`, `osm-pbf-header`, `osm-pbf-primitive` | OpenStreetMap PBF blocks | `protobuf` | 1 each |
| `mvt` | Mapbox Vector Tile 2.1 | `protobuf` | 1 |
| `valhalla` | Valhalla routing API | `protobuf` | 1 |
| `tesla-fleet-telemetry` | Tesla Fleet Telemetry payload | `protobuf` | 1 |
| `tesla-fleet-alerts`, `-connectivity`, `-errors`, `-metrics` | Tesla Fleet Telemetry records | `protobuf` | 1 each |
| `foxglove-location-fixes` | Foxglove LocationFixes, a list of LocationFix | `protobuf` | 1 |
| `foxglove-proto-*`, 46 packs | Foxglove schemas, protobuf form | `protobuf` | 1 each |
| `apollo-*`, 48 packs | Baidu Apollo common messages (GNSS, INS, localization, perception, prediction, planning, chassis, control, routing; chassis details, GNSS receiver, radar, perception, HD map) | `protobuf` | 1 each |
| `kuksa-val-v1-*`, `kuksa-val-v2-*`, 8 packs | Eclipse KUKSA.val API messages | `protobuf` | 1 each |
| `cyphal-<type>-<major>-<minor>`, 250 packs | Cyphal (UAVCAN v1) data types, generated by `tools/gen/dsdl2pack.py --cyphal` | `bits` | 1 or more each |
| `netex-service-frame`, `netex-site-frame`, `netex-timetable-frame`, `netex-service-calendar-frame` | NeTEx frames in a CompositeFrame (CEN/TS 16614), generated by `tools/gen/xsd2pack.py` | `xml` | 1 each |
| `sdm-<subject>-<model>`, 93 packs | FIWARE Smart Data Models (NGSI key-values), generated by `tools/gen/jsonschema2pack.py` | `json` | 1 each |
`asterix-cat062` maps the seven items a track encoder writes and binds them to
the shared track keys; it is the pack to convert a track into.
`asterix-cat062-full` is the generated pack for the same category and reads all
29 items of a record.

Each pack's `pack.md` states what the pack maps and what it leaves unmapped.
[docs/coverage-roadmap.md](docs/coverage-roadmap.md) lists the public formats
that have no pack and what each one needs.

## Conversions, and what carries

Two formats convert to each other exactly the keys that both map. The engine
reports this for every pair of loaded formats (`goat-xf matrix --detail`): which
keys carry, and which the target has no field for. Every row below was run with
the command-line tool on a message from the pack's own vectors.

| From | To | What carries |
|---|---|---|
| Remote ID Location, 25 bytes | CoT event XML | `lat`, `lon`, `hae` |
| MAVLink 2 `GLOBAL_POSITION_INT`, the position message of a drone autopilot | NMEA 2000 parameter group 129025: `01f801d04d6b0830b294f7` | `lat`, `lon` |
| NATO Vector Graphics point, XML | GeoJSON Feature | all 4 keys the source maps |
| CoT event XML | CoT protobuf (TAK protocol version 1) | 13 of the 14 keys the source maps |
| Canonical Track v2, JSON | ASTERIX Category 062, 31 bytes: `3e001f9b0d10…0050` | position, height, velocity east and north, 4 status flags. The caller supplies the two site codes. The bytes equal the ones the hand-written encoder of open-billie writes for the same track |
| Canonical Track v2, JSON | CoT event XML | identity, type, time, position, and course and speed, which the model computes from the velocity vector |

The last row is a rule of the model, not of either pack: `model/track.def`
derives `course` and `speed_ms` from `track.vel_east_ms` and
`track.vel_north_ms`, so every format that carries a velocity vector converts to
every format that carries course and speed.

A value that only the caller knows is supplied with the call:

```console
$ goat-xf convert --from canonical-track-v2 --to asterix-cat062 --set cat062.sac=1 --set cat062.sic=7 < track.json
3e001f9b0d1001075460100000000000000000ffce00110137810101000050
```

## From formats to systems: which options exist

> [!IMPORTANT]
> **Work in progress.** The first version is Built: the record format, the
> query and a fictional example are in this repository. The record format is
> expected to change as records of real systems are written by more than one
> owner ([what is expected to change](docs/system-records.md#expected-to-change)).

Everything above answers a question about formats. People who plan coverage ask
about systems: this radar, that display, the translator on the sensor node. A
**system record** is a short text file that says what one system emits, accepts
or converts, and how well established each claim is. `tools/goat-options` joins
the records with the packs and lists every way data can get from a producing
system to a consuming one.

```console
$ python3 -I tools/goat-options paths --store examples/stores/sketch --from example/radar-1 --to example/edge-display --table
example/radar-1 -> example/edge-display
  conv  status       route                                                 keys
  1     available    asterix-cat048 --[goat-transformers]--> cot-protobuf  1 carried, 143 lost
  1     available    asterix-cat048 --[goat-transformers]--> geojson       1 carried, 143 lost
  1     forthcoming  asterix-cat062 --[goat-transformers]--> cot-protobuf  3 carried, 15 lost
  1     forthcoming  asterix-cat062 --[goat-transformers]--> geojson       3 carried, 15 lost
```

A fictional radar reaches a fictional display four ways. Two are available
today and carry one key. Two wait for an output format the radar's maker has
announced for its next version, and carry three.

- **It lists options and does not choose.** Each path shows its own status
  (`proven`, `available`, `forthcoming`, `unknown`) and the evidence behind it.
  Paths are not ranked, and no path is named as preferred.
- **It is machine-readable first.** The output is JSON; `--table` prints it for
  a person. How to display the answer is left to whoever reads it.
- **Each owner keeps its own records.** A store is a directory of text files.
  The query reads several stores at once and shows which owner said what.
  Records of real systems belong in private stores
  ([docs/private-store.md](docs/private-store.md)); this repository holds
  fictional examples only.
- **A site file says what is on hand.** The same query then answers for one
  place: which of these paths can be used here with the systems present.

The design, the record format and a worked example are in
[docs/system-records.md](docs/system-records.md).

## Add a format without writing code

This is the complete pack for a NATO Vector Graphics point,
[`packs/nvg/pack.def`](packs/nvg/pack.def):

```
format   nvg                                # the name used with --from and --to
version  0.1.0
distribution public                         # public, or controlled (overlay only)
source  "NATO Vector Graphics 1.5 XSD (NATO ACT, public)"   # the document it was written from
wire     xml                                # the codec: xml, json, geojson, protobuf or bits
root     nvg                                # the root element
field   lon       point/@x        float     # model key, place in the message, transform
field   lat       point/@y        float
field   callsign  point/@label    string
field   type      point/@symbol   string
```

and this is the message it describes:

```xml
<nvg><point x="11.2" y="48.137" label="ALPHA" symbol="app6a:SFGPUCI----D"/></nvg>
```

With that file in `packs/nvg/`, all seven engines convert NVG points to and
from every other loaded format:

```console
$ echo '<nvg><point x="11.2" y="48.137" label="ALPHA" symbol="app6a:SFGPUCI----D"/></nvg>' | goat-xf convert --from nvg --to geojson
{"type":"Feature","geometry":{"type":"Point","coordinates":[11.2,48.137]},"properties":{"type":"app6a:SFGPUCI----D","callsign":"ALPHA"}}
```

The pack language also states binary layouts by bit range, scale factors,
several message kinds chosen by values in the message, constants, defaults,
value tables, repeating groups, and fields whose presence or length the message
itself states ([spec/engine-spec.md](spec/engine-spec.md)). A pack for a large
message catalog is generated from the catalog's own machine-readable definition
(a protobuf file, an XML schema, the CANboat database, the MAVLink message
definitions) by the generators in [`tools/gen/`](tools/gen).

## Why open

- **One definition per format.** A gap or an error in a pack is corrected in
  one file, and every user of that format, in every language, has the
  correction at the next update.
- **The owner of a format can keep its pack.** A pack is a text file that
  mirrors the format's specification, so the organization that writes the
  specification (a vendor, a standards body, a program office) can maintain the
  pack directly by pull request. The people who know the format keep it
  correct, and the users of the format do not each re-implement it.
- **Nothing about a format is inside a product.** The field positions, units
  and rules are readable text with a named source. The engines are Apache-2.0
  and use only standard libraries.
- **A new format reaches everything at once.** One pack makes a format
  convertible to and from every format already present, in all seven
  languages, in the browser and in a static binary.

## Who checks it

| Check | What it does |
|---|---|
| Seven independent engines | Each engine is written from [`spec/`](spec) and the vectors, never from another engine's source, so a defect in one engine shows as a difference from the other six |
| Conversion vectors | Every engine runs every vector and must reproduce the expected output byte for byte. Expected bytes are derived independently of the engines: from the format's specification, its reference implementation, or a generator that computes them itself |
| Load vectors | A pack that breaks a rule must be refused by every engine with the same named error |
| CI | [`.github/workflows/conformance.yml`](.github/workflows/conformance.yml) builds each engine and runs every vector on it, on every change; a change merges when every check passes |
| Boundary gate | `python3 -I tools/boundary-gate` reads every file and refuses a pack with no public marking or no named source, and file types that could hold a restricted document ([docs/boundary.md](docs/boundary.md)) |

## Use it

Try the command-line tool. This needs a Rust toolchain and nothing else.

```bash
git clone https://github.com/USAREUR-AF/goat-transformers
cd goat-transformers/engines/rust
cargo build --release
echo 122624160b42bf241b6ed1b4b69808ac0870086b53150e0200 \
  | ./target/release/goat-xf convert --from remote-id --to cot-xml
./target/release/goat-xf list-formats
```

Embed an engine in your own language. Each is a library with no dependency
beyond the standard library; `engines/<language>` holds it and
[CONTRIBUTING.md](CONTRIBUTING.md) lists the build and test command of each.

| Your code is in | Use |
|---|---|
| Rust, Go, Python, Java, C++, Erlang, Zig | the native engine in `engines/rust`, `go`, `python`, `java`, `cpp`, `erlang`, `zig` |
| JavaScript or TypeScript, in Node or a browser | the WebAssembly module and its wrapper in [`bindings/wasm`](bindings/README.md) |
| C, or any language that can call C (C#, Swift, and others) | the C library in [`bindings/c`](bindings/README.md) |
| Firmware with no operating system and no heap, `bits` formats only | a plan compiled ahead of time and the `no_std` engine in [`embedded/`](docs/embedded.md) |

In Python, for example:

```python
from goat_transformers import Engine          # PYTHONPATH=engines/python/src

engine = Engine.from_dir("packs", "model")    # the packs directory, the model directory
engine.convert("remote-id", "cot-xml", "122624160b42bf241b6ed1b4b69808ac0870086b53150e0200")
```

[docs/using.md](docs/using.md) states how to install and call the library from each language.

goat-transformers is pre-1.0: the pack language and the engine interfaces can
still change.

## Make exactly what you need

A pack loads on its own, so a deployment carries only the formats it uses.
`--packs-only` loads the named packs and leaves the rest unread; every engine's
command-line tool has it, and a library caller has the same choice.

```bash
goat-xf convert --from remote-id --to cot-xml --packs-only remote-id,cot-xml < message.hex
```

`tools/goat-pkg plan` takes the formats, the language, the runtime, the
operating system and the processor architecture, and prints the smallest
package: the engine, only the named packs, the wire types they use, the build
command, and what carries between the named formats. Part of its output:

```console
$ tools/goat-pkg plan --formats remote-id,cot-xml --language rust --runtime wasm
engine:      engines/rust
packs:       remote-id, cot-xml   (only these)
wires used:  bits, xml   (a minimal engine build can exclude the rest)
build:       cargo build --release --lib --target wasm32-unknown-unknown
```

The Rust and Go engines build to one static binary with no shared library, and
to WebAssembly; the Java engine is a jar
([docs/package-configurator.md](docs/package-configurator.md)).

## Private formats

A pack for a format whose specification is not public is kept in a private
overlay repository, which names the commit of this repository it builds with
and adds its own packs; the engines read both unchanged, and such a format
converts to and from every public format through the shared model. Every pack
is marked `distribution public` or `distribution controlled`, and an engine
started with `--max-distribution public` loads nothing marked `controlled`.

[goat-transformers-overlay-example](https://github.com/USAREUR-AF/goat-transformers-overlay-example)
is a worked overlay with fictional content, [docs/boundary.md](docs/boundary.md)
states the rules and the checks, and
[docs/coverage-roadmap.md](docs/coverage-roadmap.md#formats-whose-specification-is-not-public)
states how such formats are covered.

## Working with an AI assistant

[AGENTS.md](AGENTS.md) gives an assistant the layout, the rules and the
commands of this repository. [`.claude/skills/`](.claude/skills) holds
step-by-step procedures (add a format, generate packs from a schema, convert a
message, build a minimal package, write an overlay, review a pack, extend the
pack language) and [`.claude/agents/`](.claude/agents) holds the roles the
project uses when several assistants work at once.

## Layout

```
spec/        the engine specification, the shared model, the vector format
model/       the shared model's modules, one file each
packs/       one directory per format: pack.def, pack.md, vectors/
engines/     one directory per language
bindings/    the Rust engine as a C library and as a WebAssembly module
adapters/    transports around the Rust engine: goat-xf-pipe over files, TCP, UDP, serial, MQTT
examples/    fictional system records and a site file for tools/goat-options
tools/       goat-pkg, goat-options, boundary-gate, repo-stats, and the pack generators in gen/
docs/        design, language guidance, decision records, format coverage, the package planner
```

## Contributing, security, license

[CONTRIBUTING.md](CONTRIBUTING.md) states how to run the conformance suite and
how to add a pack, a wire type or an engine. The design is
[docs/design.md](docs/design.md). Report a vulnerability through
[SECURITY.md](SECURITY.md).

Apache License 2.0 ([LICENSE](LICENSE)). Portions written by U.S. Federal
government employees within the scope of their employment are not subject to
copyright in the United States ([INTENT.md](INTENT.md)). [NOTICE](NOTICE) lists
the third-party sources the packs were written from.

### Licences of the packs, and build profiles

The code and the restatements of message formats are Apache-2.0. A format whose
source allows less is still included, labelled with its real licence, so that a
build can leave it out. Each pack has one SPDX licence, given in
[REUSE.toml](REUSE.toml) ([REUSE](https://reuse.software): `reuse lint`, SBOM
and licence scanners read it); [licences.toml](licences.toml) gives each
licence its flags (commercial use, share-alike, attribution, field of use); a
pack's profile follows from those and from the modules it uses.

| Profile | Holds |
|---|---|
| `open` (the default) | commercial use permitted, no share-alike, no field-of-use restriction |
| `open+copyleft` | `open`, and share-alike packs |
| `everything` | every public pack, also non-commercial, unknown and field-of-use |

[LICENSING.md](LICENSING.md) lists every pack outside `open` and why;
[licences.json](licences.json) is the same for machines.
`tools/goat-pkg plan|bundle|archive --profile <profile>` builds from one
profile; `python3 -I tools/licences.py --list --profile <profile>` lists its
packs.
