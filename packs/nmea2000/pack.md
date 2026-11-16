# Pack: nmea2000

NMEA 2000 parameter groups (PGNs), generated from the CANboat PGN database
(`canboat/canboat` `docs/canboat.json` at commit `d82b7fbc64cd1ed97ccbc6926ff44bf29e0dbe37`, CANboat 9.2.0, Apache License 2.0) by
`tools/gen/canboat2pack.py`. Do not edit `pack.def`, `model/n2k.def` or the vectors by hand;
change the generator and run it again.

Status: Built. Generated from the database; every engine runs every vector in `vectors/` in
the conformance suite.

## Message convention

An NMEA 2000 payload travels in CAN frames whose 29-bit identifier carries the PGN, and the
pack language has no CAN framing. A message of this pack is therefore:

1. 3 bytes: the PGN, little-endian;
2. the payload: the 8 data bytes of a single-frame PGN, or the payload of a fast-packet PGN
   after reassembly (sequence and frame counters and the length byte removed).

Priority, source address and destination address are not part of the message. The pack is
`wire bits`, `bit_order lsb`, `word_bytes 1`; every locator is `0:<bit offset>:<len>` and a
payload field sits at CANboat's `BitOffset` + 24. Input and output are hex text.

## What is mapped

| | Count |
|---|---|
| PGN definitions in the source | 647 |
| kinds in `pack.def` | 473 |
| distinct PGNs with at least one kind | 268 |
| not mapped: repeating field sets | 60 |
| not mapped: variable-length or conditionally placed fields | 63 |
| not mapped: catch-all definitions for a range of PGNs | 8 |
| not mapped: not distinguishable from another definition of the same PGN | 1 |
| not mapped: no field the pack language can carry | 42 |
| keys in module `n2k` | 1564 |
| vectors | 478 (473 same-format round trips, 5 to `geojson`) |

One kind per fixed-layout PGN definition, named `pgn<number>`, with the CANboat definition id
appended where the source holds several definitions for that PGN. Each kind has
`when 0:0:24 <pgn>` and one more `when` per CANboat field with a fixed `Match` value
(manufacturer code, industry code, function and message codes). Kinds of one PGN are ordered
with the most matched bits first, so the first kind that holds is the most specific one.
Two definitions of one PGN are told apart only by these values: a definition whose match
values also hold for another definition's messages, with no order that separates them, has
no kind.
A `Match` field is written by its `when` line and is not a model key.

Field rules:

| CANboat field | Transform | Model type |
|---|---|---|
| NUMBER, TIME, DURATION with `Resolution` other than 1 | `uscale:<resolution>` or, when `Signed`, `sscale:<resolution>`; a decimal resolution is written as a fraction in lowest terms (1e-7 is `1/10000000`, 0.002 is `1/500`); a resolution CANboat derived from pi and printed to 13 or more digits stays a decimal | float, CANboat's unit |
| any numeric field with `Offset` | `uscale:<resolution>:<offset>` (the raw value is unsigned; value = raw x resolution + offset) | float |
| NUMBER, DATE, MMSI, PGN, ISO_NAME, ADDRESS with resolution 1 | `uint`, or `twos` when `Signed` | int |
| LOOKUP, INDIRECT_LOOKUP, BITLOOKUP, FIELD_INDEX | `uint` (the wire integer, not the lookup name) | int |
| FLOAT | `f32` | float |
| STRING_FIX | `ascii` | string |
| BINARY of 64 bits or fewer | `uint` | int |
| RESERVED, SPARE | not mapped | |

Every raw value goes to module `n2k` (`model/n2k.def`). A field id that agrees across all its
uses on model type, unit, resolution, offset and lookup table is one key (`n2k.sid`,
`n2k.wind_speed`). Where uses disagree, each PGN gets its own key `n2k.pgn<number>_<id>`, and
where definitions of one PGN disagree, `n2k.<kind name>_<id>`.

`requires` of a kind lists up to six of its `n2k` keys, those used by the fewest kinds; a kind
with no `n2k` key lists its core keys. 86 kinds share their `requires` list with another kind;
for those, an encode from another format selects the first in pack order.

## Core keys

| Kind | PGN | Core keys |
|---|---|---|
| `pgn127233` | Man Overboard Notification | `lat` `sscale:1/10000000`, `lon` `sscale:1/10000000`, `speed_ms` `uscale:1/100` |
| `pgn129025` | Position, Rapid Update | `lat` `sscale:1/10000000`, `lon` `sscale:1/10000000` |
| `pgn129026` | COG & SOG, Rapid Update | `speed_ms` `uscale:1/100` |
| `pgn129038` | AIS Class A Position Report | `lon` `sscale:1/10000000`, `lat` `sscale:1/10000000`, `speed_ms` `uscale:1/100` |
| `pgn129039` | AIS Class B Position Report | `lon` `sscale:1/10000000`, `lat` `sscale:1/10000000`, `speed_ms` `uscale:1/100` |
| `pgn129040` | AIS Class B Extended Position Report | `lon` `sscale:1/10000000`, `lat` `sscale:1/10000000`, `speed_ms` `uscale:1/100` |
| `pgn129793` | AIS UTC and Date Report | `lon` `sscale:1/10000000`, `lat` `sscale:1/10000000` |
| `pgn129798` | AIS SAR Aircraft Position Report | `lon` `sscale:1/10000000`, `lat` `sscale:1/10000000`, `speed_ms` `uscale:1/10` |
| `pgn129813` | AIS Long-Range Broadcast Message | `lon` `sscale:1/10000000`, `lat` `sscale:1/10000000`, `speed_ms` `uscale:1/100` |
| `pgn130577` | Direction Data | `speed_ms` `uscale:1/100` |

- `lat` / `lon`: only a definition with exactly one latitude and one longitude field, ids
  `latitude` and `longitude`, in degrees at resolution 1e-7 or 1e-16. Waypoint, destination,
  station, corner and delta positions stay in `n2k`. NMEA 2000 states the datum in a separate
  PGN (129044); the pack does not read it.
- `speed_ms`: the field `sog` in m/s.
- `course`: no kind maps it. Every fixed-layout course-over-ground field either sits beside a
  reference selector (`cogReference`: true or magnetic) or has no stated reference in the
  database, so it stays `n2k.cog` in radians. The generator maps `course` with the factor
  resolution x 180/pi when a definition states a true-north reference and has no selector.
- `hae`: no kind maps it. No fixed-layout altitude field is stated to be above the WGS84
  ellipsoid (PGN 129029 says "referenced to WGS-84" and is not fixed-layout).

## What the pack language cannot express yet

- **"Not available" values.** NMEA 2000 marks a missing value with all bits set (and uses
  the next values down for "out of range" and "reserved"). There is no way to say so in
  `pack.def`: an all-ones field decodes as a number (`0xFFFF` at resolution 0.01 is 655.35),
  and an absent model key encodes as zero bits, not all ones.
- **Reserved and spare bits.** NMEA 2000 sets them to 1; `encode` writes 0 in every bit no
  field covers. A real message with reserved bits set does not round-trip byte-identically.
- **Trailing bytes.** The message ends at the last mapped or `when` bit, rounded up to a
  byte. A definition that ends in reserved fields encodes shorter than its NMEA 2000 length
  (PGN 129026 encodes 3 + 6 bytes, not 3 + 8). Decode accepts the full length.
- **Repeating field sets and variable-length fields** (STRING_LAU, STRING_LZ, VARIABLE,
  BINARY of variable size, key/length/value fields, fields placed after any of these). These
  need the future groups addition; the definitions are listed below.
- **PGN ranges.** A `when` compares for equality, so CANboat's catch-all definitions for a
  range of PGNs (proprietary ranges) have no kind.
- **CAN framing**: identifier, priority, addresses, fast-packet and ISO transport reassembly.
- **Opaque fields over 64 bits and DECIMAL fields.** 15 kinds leave such a field unmapped:

| Kind | Field | Reason |
|---|---|---|
| `pgn126720_seatalk1_pilot_mode` | `unknown2` | BINARY of 80 bits (no transform carries more than 64 opaque bits) |
| `pgn126720_seatalk1_keystroke` | `unknownData` | BINARY of 112 bits (no transform carries more than 64 opaque bits) |
| `pgn126720_maretron_proprietary_configuration` | `payload` | BINARY of 1728 bits (no transform carries more than 64 opaque bits) |
| `pgn130816_bep_marine_czone_zcf_bus_distribution` | `data` | BINARY of 1600 bits (no transform carries more than 64 opaque bits) |
| `pgn130818_simnet_reprogram_data` | `data` | BINARY of 1736 bits (no transform carries more than 64 opaque bits) |
| `pgn130819_maretron_alert_transmission` | `maretronExtension` | BINARY of 128 bits (no transform carries more than 64 opaque bits) |
| `pgn130820_bep_marine_czone_alarm_string_response` | `string` | BINARY of 1736 bits (no transform carries more than 64 opaque bits) |
| `pgn130822_navico_udb_database_bulk_report2` | `data` | BINARY of 1728 bits (no transform carries more than 64 opaque bits) |
| `pgn130822_navico_udb_database_bulk_report4` | `data` | BINARY of 1728 bits (no transform carries more than 64 opaque bits) |
| `pgn130822_maretron_alert_control` | `maretronExtension` | BINARY of 128 bits (no transform carries more than 64 opaque bits) |
| `pgn130823_navico_boat_speed_polar_table` | `data` | BINARY of 1728 bits (no transform carries more than 64 opaque bits) |
| `pgn130825_mercury_command_response` | `data` | BINARY of 240 bits (no transform carries more than 64 opaque bits) |
| `pgn130826_mercury_bam_digital_data_proxy` | `data` | BINARY of 256 bits (no transform carries more than 64 opaque bits) |
| `pgn130846_furuno_motion_sensor_status_extended` | `data` | BINARY of 200 bits (no transform carries more than 64 opaque bits) |
| `pgn130921` | `data` | BINARY of 1752 bits (no transform carries more than 64 opaque bits) |

- **String padding.** `ascii` strips trailing NUL bytes only and refuses bytes above 0x7E.
  NMEA 2000 devices also pad fixed strings with 0xFF or `@`; 0xFF padding is a decode error.
- **Lookup names.** Lookups are carried as integers; the pack language has no value table for
  a `bits` field.
- **64-bit unsigned values.** `uint` on a 64-bit field (ISO NAME) with the top bit set
  decodes to the negative integer with the same bit pattern.

## Kinds from definitions CANboat marks incomplete

389 of the 473 kinds come from definitions with `Complete: false` (CANboat states fields, field
lengths, resolutions or lookups may be missing or wrong). They carry `[CANboat: incomplete]`
in the comment above the kind in `pack.def`.

## Vectors

- `rt-<kind>.json`: one same-format round trip per kind. The generator packs the bytes itself
  from values inside each field's range that survive scaling exactly; unmapped bits are 0 and
  the message has the encoded length, so the round trip is byte-identical. `model` holds
  `@kind` and every decoded key.
- `x01-pgn129025-to-geojson.json`, `x02-pgn129025-south-west-to-geojson.json`, `x03-pgn129026-to-geojson.json`, `x04-pgn129026-magnetic-cog-to-geojson.json`, `x05-pgn129038-ais-class-a-to-geojson.json`: conversions to `geojson`, with the expected text
  written by hand from the canonical GeoJSON rules and checked by the generator against its
  own codec. PGN 129029 has no vector: it has a repeating field set and no kind.

Vectors hold lowercase hex text in `input` / `expect`.

## Definitions not mapped

### Repeating field sets (60)

These need the future groups addition.

| PGN | CANboat id | Description | Detail |
|---|---|---|---|
| 126208 | `nmeaAcknowledgeGroupFunction` | NMEA - Acknowledge group function | repeating field set |
| 126208 | `nmeaCommandGroupFunction` | NMEA - Command group function | repeating field set |
| 126208 | `nmeaReadFieldsGroupFunction` | NMEA - Read Fields group function | repeating field set |
| 126208 | `nmeaReadFieldsReplyGroupFunction` | NMEA - Read Fields reply group function | repeating field set |
| 126208 | `nmeaRequestGroupFunction` | NMEA - Request group function | repeating field set |
| 126208 | `nmeaWriteFieldsGroupFunction` | NMEA - Write Fields group function | repeating field set |
| 126208 | `nmeaWriteFieldsReplyGroupFunction` | NMEA - Write Fields reply group function | repeating field set |
| 126464 | `pgnListTransmitAndReceive` | PGN List (Transmit and Receive) | repeating field set |
| 126720 | `airmarCalibrateSpeed` | Airmar: Calibrate Speed | repeating field set |
| 126987 | `alertThreshold` | Alert Threshold | repeating field set |
| 126988 | `alertValue` | Alert Value | repeating field set |
| 127503 | `acInputStatus` | AC Input Status | repeating field set |
| 127504 | `acOutputStatus` | AC Output Status | repeating field set |
| 129029 | `gnssPositionData` | GNSS Position Data | repeating field set |
| 129285 | `navigationRouteWpInformation` | Navigation - Route/WP Information | repeating field set |
| 129540 | `gnssSatsInView` | GNSS Sats in View | repeating field set |
| 129796 | `aisAcknowledge` | AIS Acknowledge | repeating field set |
| 129805 | `aisDataLinkManagementMessage` | AIS Data Link Management Message | repeating field set |
| 129808 | `dscCallInformation` | DSC Call Information | repeating field set |
| 129808 | `dscDistressAcknowledgementOrRelay` | DSC Distress Acknowledgement or Relay | repeating field set |
| 129808 | `dscDistressCallInformation` | DSC Distress Call Information | repeating field set |
| 129812 | `aisMultiSlotBinaryMessageDeprecated` | AIS Multi Slot Binary Message (Deprecated) | repeating field set |
| 129816 | `aisAcknowledgeBinary` | AIS Acknowledge (Binary) | repeating field set |
| 130064 | `routeAndWpServiceDatabaseList` | Route and WP Service - Database List | repeating field set |
| 130065 | `routeAndWpServiceRouteList` | Route and WP Service - Route List | repeating field set |
| 130067 | `routeAndWpServiceRouteWpNamePosition` | Route and WP Service - Route - WP Name & Position | repeating field set |
| 130068 | `routeAndWpServiceRouteWpName` | Route and WP Service - Route - WP Name | repeating field set |
| 130069 | `routeAndWpServiceXteLimitNavigationMethod` | Route and WP Service - XTE Limit & Navigation Method | repeating field set |
| 130070 | `routeAndWpServiceWpComment` | Route and WP Service - WP Comment | repeating field set |
| 130071 | `routeAndWpServiceRouteComment` | Route and WP Service - Route Comment | repeating field set |
| 130072 | `routeAndWpServiceDatabaseComment` | Route and WP Service - Database Comment | repeating field set |
| 130073 | `routeAndWpServiceRadiusOfTurn` | Route and WP Service - Radius of Turn | repeating field set |
| 130074 | `routeAndWpServiceWpListWpNamePosition` | Route and WP Service - WP List - WP Name & Position | repeating field set |
| 130562 | `lightingScene` | Lighting Scene | repeating field set |
| 130564 | `lightingDeviceEnumeration` | Lighting Device Enumeration | repeating field set |
| 130565 | `lightingColorSequence` | Lighting Color Sequence | repeating field set |
| 130571 | `libraryDataGroup` | Library Data Group | repeating field set |
| 130573 | `supportedSourceData` | Supported Source Data | repeating field set |
| 130574 | `supportedZoneData` | Supported Zone Data | repeating field set |
| 130581 | `zoneConfigurationDeprecated` | Zone Configuration (deprecated) | repeating field set |
| 130583 | `availableAudioEqPresets` | Available Audio EQ presets | repeating field set |
| 130584 | `availableBluetoothAddresses` | Available Bluetooth addresses | repeating field set |
| 130817 | `maretronAnnunciatorCapabilities` | Maretron: Annunciator Capabilities | repeating field set |
| 130820 | `fusionSettings` | Fusion: Settings | repeating field set |
| 130822 | `navicoUdbDatabaseObjectDump` | Navico: UDB Database, Object Dump | repeating field set |
| 130822 | `navicoUdbDatabaseSettingsDump` | Navico: UDB Database, Settings Dump | repeating field set |
| 130822 | `navicoUdbDatabaseTableDump11` | Navico: UDB Database, Table Dump | repeating field set |
| 130822 | `navicoUdbDatabaseTableDump12` | Navico: UDB Database, Table Dump | repeating field set |
| 130822 | `navicoUdbDatabaseTableDump13` | Navico: UDB Database, Table Dump | repeating field set |
| 130822 | `navicoUdbDatabaseTableDump14` | Navico: UDB Database, Table Dump | repeating field set |
| 130822 | `navicoUdbDatabaseTableDump15` | Navico: UDB Database, Table Dump | repeating field set |
| 130822 | `navicoUdbDatabaseTableDump18` | Navico: UDB Database, Table Dump | repeating field set |
| 130823 | `navicoDataTypeSourceDirectory` | Navico: Data Type Source Directory | repeating field set |
| 130823 | `navicoDataTypeSourceDirectoryFullReport` | Navico: Data Type Source Directory, Full Report | repeating field set |
| 130824 | `bGKeyValueData` | B&G: key-value data | repeating field set |
| 130824 | `mercuryEngineKeyValueData` | Mercury: Engine Key-Value Data | repeating field set |
| 130826 | `maretronSwitchIndicatorStatus` | Maretron: Switch Indicator Status | repeating field set |
| 130845 | `furunoMultiSatsInViewExtended` | Furuno: Multi Sats In View Extended | repeating field set |
| 130852 | `navicoDiagnosticData` | Navico: Diagnostic Data | repeating field set |
| 130944 | `airmarPost` | Airmar: POST | repeating field set |

### Variable-length or conditionally placed fields (63)

These need the future groups addition.

| PGN | CANboat id | Description | Detail |
|---|---|---|---|
| 61184 | `victronVeCanRegister` | Victron: VE.Can Register | DYNAMIC_FIELD_VALUE |
| 126720 | `fusionSetDeviceName` | Fusion: Set Device Name | STRING_LZ |
| 126720 | `fusionSetZoneName` | Fusion: Set Zone Name | STRING_LZ |
| 126985 | `alertText` | Alert Text | STRING_LAU |
| 126998 | `configurationInformation` | Configuration Information | STRING_LAU |
| 127498 | `engineParametersStatic` | Engine Parameters, Static | STRING_LAU |
| 128520 | `trackedTargetData` | Tracked Target Data | STRING_LAU |
| 129041 | `aisAidsToNavigationAtonReport` | AIS Aids to Navigation (AtoN) Report | STRING_LAU |
| 129792 | `aisDgnssBroadcastBinaryMessage` | AIS DGNSS Broadcast Binary Message | BINARY of variable size |
| 129795 | `aisAddressedBinaryMessage` | AIS Addressed Binary Message | BINARY of variable size |
| 129797 | `aisBinaryBroadcastMessage` | AIS Binary Broadcast Message | BINARY of variable size |
| 129801 | `aisAddressedSafetyRelatedMessage` | AIS Addressed Safety Related Message | STRING_LAU |
| 129802 | `aisSafetyRelatedBroadcastMessage` | AIS Safety Related Broadcast Message | STRING_LAU |
| 129811 | `aisSingleSlotBinaryMessageDeprecated` | AIS Single Slot Binary Message (Deprecated) | BINARY of variable size |
| 129814 | `aisSingleSlotBinaryMessage` | AIS Single Slot Binary Message | BINARY of variable size |
| 129815 | `aisMultiSlotBinaryMessage` | AIS Multi Slot Binary Message | BINARY of variable size |
| 130060 | `label` | Label | STRING_LAU |
| 130066 | `routeAndWpServiceRouteWpListAttributes` | Route and WP Service - Route/WP-List Attributes | STRING_LAU |
| 130320 | `tideStationData` | Tide Station Data | STRING_LAU |
| 130321 | `salinityStationData` | Salinity Station Data | STRING_LAU |
| 130322 | `currentStationData` | Current Station Data | STRING_LAU |
| 130323 | `meteorologicalStationData` | Meteorological Station Data | STRING_LAU |
| 130324 | `mooredBuoyStationData` | Moored Buoy Station Data | STRING_LAU |
| 130330 | `lightingSystemSettings` | Lighting System Settings | STRING_LAU |
| 130561 | `lightingZone` | Lighting Zone | STRING_LAU |
| 130563 | `lightingDevice` | Lighting Device | STRING_LAU |
| 130566 | `lightingProgram` | Lighting Program | STRING_LAU |
| 130568 | `entertainmentDiagnosticStatus` | Entertainment - Diagnostic Status | STRING_LAU |
| 130570 | `libraryDataFile` | Library Data File | STRING_LAU |
| 130572 | `libraryDataSearch` | Library Data Search | STRING_LAU |
| 130575 | `entertainmentParentalControlStatus` | Entertainment - Parental Control Status | STRING_LAU |
| 130816 | `furunoStatusAndVersionReport` | Furuno: Status and Version Report | STRING_LAU |
| 130816 | `sonichubAlbum` | SonicHub: Album | STRING_LZ |
| 130816 | `sonichubAmRadio` | SonicHub: AM Radio | STRING_LZ |
| 130816 | `sonichubArtist` | SonicHub: Artist | STRING_LZ |
| 130816 | `sonichubFmRadio` | SonicHub: FM Radio | STRING_LZ |
| 130816 | `sonichubMenuItem` | SonicHub: Menu Item | STRING_LZ |
| 130816 | `sonichubSourceList` | SonicHub: Source List | STRING_LZ |
| 130816 | `sonichubTrack` | SonicHub: Track | STRING_LZ |
| 130818 | `maretronLabel` | Maretron: Label | STRING_LAU |
| 130820 | `fusionAlbumName` | Fusion: Album Name | STRING_LZ |
| 130820 | `fusionArtistName` | Fusion: Artist Name | STRING_LZ |
| 130820 | `fusionDeviceName` | Fusion: Device Name | STRING_LZ |
| 130820 | `fusionMarineTuner` | Fusion: Marine Tuner | STRING_LZ |
| 130820 | `fusionMenuItem` | Fusion: Menu Item | STRING_LZ |
| 130820 | `fusionRdsData` | Fusion: RDS Data | STRING_LZ |
| 130820 | `fusionSiriusxmArtist` | Fusion: SiriusXM Artist | STRING_LZ |
| 130820 | `fusionSiriusxmCategory` | Fusion: SiriusXM Category | STRING_LZ |
| 130820 | `fusionSiriusxmChannel` | Fusion: SiriusXM Channel | STRING_LZ |
| 130820 | `fusionSiriusxmContentInfo` | Fusion: SiriusXM Content Info | STRING_LZ |
| 130820 | `fusionSiriusxmPresets` | Fusion: SiriusXM Presets | BINARY of variable size |
| 130820 | `fusionSiriusxmTitle` | Fusion: SiriusXM Title | STRING_LZ |
| 130820 | `fusionSource` | Fusion: Source | STRING_LZ |
| 130820 | `fusionTrackName` | Fusion: Track Name | STRING_LZ |
| 130820 | `fusionTuner` | Fusion: Tuner | STRING_LZ |
| 130820 | `fusionZoneName` | Fusion: Zone Name | STRING_LZ |
| 130821 | `maretronAlertText` | Maretron: Alert Text | STRING_LAU |
| 130822 | `navicoConfigurationSet` | Navico: Configuration Set | DYNAMIC_FIELD_VALUE |
| 130834 | `maretronSmsStatus` | Maretron: SMS Status | STRING_LAU |
| 130835 | `maretronSmsTextMessage` | Maretron: SMS Text Message | STRING_LAU |
| 130845 | `simnetKeyValue` | Simnet: Key Value | DYNAMIC_FIELD_VALUE |
| 130846 | `simnetParameterSet` | Simnet: Key Value - Long | DYNAMIC_FIELD_VALUE |
| 130847 | `navicoAsciiIdentifier` | Navico: ASCII Identifier | STRING_LZ |

### Catch-all definitions for a range of PGNs (8)

| PGN | CANboat id | Description | Detail |
|---|---|---|---|
| 59392 | `0xe8000xee00StandardizedSingleFrameAddressed` | 0xE800-0xEE00: Standardized single-frame addressed | catch-all definition for a range of PGNs |
| 61184 | `0xef00ManufacturerProprietarySingleFrameAddressed` | 0xEF00: Manufacturer Proprietary single-frame addressed | catch-all definition for a range of PGNs |
| 61440 | `0xf0000xfeffStandardizedSingleFrameNonAddressed` | 0xF000-0xFEFF: Standardized single-frame non-addressed | catch-all definition for a range of PGNs |
| 65280 | `0xff000xffffManufacturerProprietarySingleFrameNonAddressed` | 0xFF00-0xFFFF: Manufacturer Proprietary single-frame non-addressed | catch-all definition for a range of PGNs |
| 126208 | `0x1ed000x1ee00StandardizedFastPacketAddressed` | 0x1ED00 - 0x1EE00: Standardized fast-packet addressed | catch-all definition for a range of PGNs |
| 126720 | `0x1ef00ManufacturerProprietaryFastPacketAddressed` | 0x1EF00: Manufacturer Proprietary fast-packet addressed | catch-all definition for a range of PGNs |
| 126976 | `0x1f0000x1feffStandardizedMixedSingleFastPacketNonAddressed` | 0x1F000-0x1FEFF: Standardized mixed single/fast packet non-addressed | catch-all definition for a range of PGNs |
| 130816 | `0x1ff000x1ffffManufacturerSpecificFastPacketNonAddressed` | 0x1FF00-0x1FFFF: Manufacturer Specific fast-packet non-addressed | catch-all definition for a range of PGNs |

### Not distinguishable from another definition of the same PGN (1)

| PGN | CANboat id | Description | Detail |
|---|---|---|---|
| 126720 | `airmarAddressableMultiFrame` | Airmar: Addressable Multi-Frame | its match values also hold for the unmapped, more specific definition airmarCalibrateSpeed |

### No field the pack language can carry (42)

| PGN | CANboat id | Description | Detail |
|---|---|---|---|
| 65286 | `airmarBootStateRequest` | Airmar: Boot State Request | fields: LOOKUP (match), RESERVED, LOOKUP (match), RESERVED |
| 65287 | `simnetConfigureTemperatureSensor` | Simnet: Configure Temperature Sensor | fields: LOOKUP (match), RESERVED, LOOKUP (match), RESERVED |
| 65289 | `simnetTrimTabSensorCalibration` | Simnet: Trim Tab Sensor Calibration | fields: LOOKUP (match), RESERVED, LOOKUP (match), RESERVED |
| 65290 | `simnetPaddleWheelSpeedConfiguration` | Simnet: Paddle Wheel Speed Configuration | fields: LOOKUP (match), RESERVED, LOOKUP (match), RESERVED |
| 65292 | `simnetClearFluidLevelWarnings` | Simnet: Clear Fluid Level Warnings | fields: LOOKUP (match), RESERVED, LOOKUP (match), RESERVED |
| 65293 | `simnetLgc2000Configuration` | Simnet: LGC-2000 Configuration | fields: LOOKUP (match), RESERVED, LOOKUP (match), RESERVED |
| 65480 | `simnetAutopilotMode` | Simnet: Autopilot Mode | fields: LOOKUP (match), RESERVED, LOOKUP (match), RESERVED |
| 126720 | `airmarMasterReset` | Airmar: Master Reset | fields: LOOKUP (match), RESERVED, LOOKUP (match), LOOKUP (match), RESERVED |
| 126720 | `fusionRequestStatus` | Fusion: Request Status | fields: LOOKUP (match), RESERVED, LOOKUP (match), LOOKUP (match) |
| 126720 | `lumishoreProprietary` | Lumishore: Proprietary | fields: LOOKUP (match), RESERVED, LOOKUP (match), BINARY |
| 130816 | `hondaEngineStatus` | Honda: Engine Status | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130818 | `bepMarineProprietaryPgn130818` | BEP Marine: Proprietary PGN 130818 | fields: LOOKUP (match), RESERVED, LOOKUP (match), BINARY |
| 130819 | `simnetRequestReprogram` | Simnet: Request Reprogram | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130821 | `bepMarineProprietaryPgn130821` | BEP Marine: Proprietary PGN 130821 | fields: LOOKUP (match), RESERVED, LOOKUP (match), BINARY |
| 130826 | `bepMarineProprietaryPgn130826` | BEP Marine: Proprietary PGN 130826 | fields: LOOKUP (match), RESERVED, LOOKUP (match), BINARY |
| 130828 | `simnetSetSerialNumber` | Simnet: Set Serial Number | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130830 | `suzukiEngineData` | Suzuki: Engine Data | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130831 | `maretronUniversalConfigurationFp` | Maretron: Universal Configuration FP | fields: LOOKUP (match), RESERVED, LOOKUP (match), BINARY |
| 130831 | `suzukiEngineAndStorageDeviceConfig` | Suzuki: Engine and Storage Device Config | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130832 | `simnetFuelUsedHighResolution` | Simnet: Fuel Used - High Resolution | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130834 | `simnetEngineAndTankConfiguration` | Simnet: Engine and Tank Configuration | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130835 | `simnetSetEngineAndTankConfiguration` | Simnet: Set Engine and Tank Configuration | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130837 | `simnetFuelFlowTurbineConfiguration` | Simnet: Fuel Flow Turbine Configuration | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130837 | `suzukiEngineSensorData` | Suzuki: Engine Sensor Data | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130838 | `maretronBnwas` | Maretron: BNWAS | fields: LOOKUP (match), RESERVED, LOOKUP (match), BINARY |
| 130838 | `simnetFluidLevelWarning` | Simnet: Fluid Level Warning | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130838 | `suzukiFuelManagement` | Suzuki: Fuel Management | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130839 | `simnetPressureSensorConfiguration` | Simnet: Pressure Sensor Configuration | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130841 | `maretronCanFrameForwarding` | Maretron: CAN Frame Forwarding | fields: LOOKUP (match), RESERVED, LOOKUP (match), BINARY |
| 130843 | `maretronWindlassControlCommand` | Maretron: Windlass Control Command | fields: LOOKUP (match), RESERVED, LOOKUP (match), BINARY |
| 130843 | `simnetSonarStatusFrequencyAndDspVoltage` | Simnet: Sonar Status, Frequency and DSP Voltage | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130844 | `carlingProprietary` | Carling: Proprietary | fields: LOOKUP (match), RESERVED, LOOKUP (match), BINARY |
| 130845 | `maretronDcEnergy` | Maretron: DC Energy | fields: LOOKUP (match), RESERVED, LOOKUP (match), BINARY |
| 130846 | `maretronBatteryAmpHourRecord` | Maretron: Battery Amp Hour Record | fields: LOOKUP (match), RESERVED, LOOKUP (match), BINARY |
| 130849 | `navicoProprietaryFp` | Navico: Proprietary FP | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130945 | `yamahaEngineData` | Yamaha: Engine Data | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130946 | `yamahaEngineData2` | Yamaha: Engine Data 2 | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130947 | `yamahaEngineData3` | Yamaha: Engine Data 3 | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 130951 | `yamahaEngineData4` | Yamaha: Engine Data 4 | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 131008 | `yamahaEngineData5` | Yamaha: Engine Data 5 | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 131011 | `yamahaEngineData6` | Yamaha: Engine Data 6 | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
| 131012 | `yamahaEngineData7` | Yamaha: Engine Data 7 | fields: LOOKUP (match), RESERVED, LOOKUP (match) |
