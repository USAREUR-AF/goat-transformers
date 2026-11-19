# Pack: nmea2000-seq

NMEA 2000 parameter groups (PGNs) that hold a repeating field set, generated from the CANboat
PGN database (`canboat/canboat` `docs/canboat.json` at commit `d82b7fbc64cd1ed97ccbc6926ff44bf29e0dbe37`, CANboat 9.2.0, Apache License 2.0) by
`tools/gen/canboat2pack.py`, the generator of pack `nmea2000`. Do not edit `pack.def`, `model/n2k.def`
or the vectors by hand; change the generator and run it again.

Status: Built. Generated from the database; the generator checks every vector with its own
codec, written from `spec/engine-spec.md` and not from an engine.

## Why a second pack

A repeating field set needs `group <list> count <len>` of the sequential layout (spec 0.8),
and `layout` holds for a whole pack. Pack `nmea2000` stays fixed-layout and byte-identical; this
pack holds the definitions the sequential layout can state. Both use module `n2k`.
The two packs accept disjoint messages: a kind here is generated only when its match
values conflict with those of every kind of the same PGN in `nmea2000`, so a reader may try
either pack first. A fixed-layout PGN is `no-kind` here (vector `e02`).

## Message convention

As pack `nmea2000`: 3 bytes of PGN, little-endian, then the payload after fast-packet
reassembly. The lines are read in order from the first bit, least significant bit first
(`bit_order lsb`). The message ends after the last item; it is as long as CANboat's fields
make it, trailing reserved bits included.

## What is mapped

| | Count |
|---|---|
| kinds | 15 |
| distinct PGNs | 15 |
| lists in module `n2k` | 15 |
| keys added to module `n2k` by this pack | 58 |
| vectors | 33 |

| Kind | PGN | CANboat id | Description | List (one item per) |
|---|---|---|---|---|
| `pgn126208_nmea_acknowledge_group_function` | 126208 | `nmeaAcknowledgeGroupFunction` | NMEA - Acknowledge group function | `n2k.pgn126208_number_of_parameters` (numberOfParameters) |
| `pgn126720_airmar_calibrate_speed` | 126720 | `airmarCalibrateSpeed` | Airmar: Calibrate Speed | `n2k.pgn126720_number_of_pairs_of_data_points` (numberOfPairsOfDataPoints) |
| `pgn126987` | 126987 | `alertThreshold` | Alert Threshold [CANboat: incomplete] | `n2k.pgn126987_number_of_parameters` (numberOfParameters) |
| `pgn126988` | 126988 | `alertValue` | Alert Value [CANboat: incomplete] | `n2k.pgn126988_number_of_parameters` (numberOfParameters) |
| `pgn127503` | 127503 | `acInputStatus` | AC Input Status | `n2k.pgn127503_number_of_lines` (numberOfLines) |
| `pgn127504` | 127504 | `acOutputStatus` | AC Output Status | `n2k.pgn127504_number_of_lines` (numberOfLines) |
| `pgn129029` | 129029 | `gnssPositionData` | GNSS Position Data | `n2k.pgn129029_reference_stations` (referenceStations) |
| `pgn129540` | 129540 | `gnssSatsInView` | GNSS Sats in View | `n2k.pgn129540_sats_in_view` (satsInView) |
| `pgn129816` | 129816 | `aisAcknowledgeBinary` | AIS Acknowledge (Binary) [CANboat: incomplete] | `n2k.pgn129816_number_of_acknowledgments` (numberOfAcknowledgments) |
| `pgn130564` | 130564 | `lightingDeviceEnumeration` | Lighting Device Enumeration [CANboat: incomplete] | `n2k.pgn130564_number_of_devices` (numberOfDevices) |
| `pgn130565` | 130565 | `lightingColorSequence` | Lighting Color Sequence [CANboat: incomplete] | `n2k.pgn130565_color_count` (colorCount) |
| `pgn130817_maretron_annunciator_capabilities` | 130817 | `maretronAnnunciatorCapabilities` | Maretron: Annunciator Capabilities [CANboat: incomplete] | `n2k.pgn130817_number_of_tones` (numberOfTones) |
| `pgn130820_fusion_settings` | 130820 | `fusionSettings` | Fusion: Settings [CANboat: incomplete] | `n2k.pgn130820_count` (count) |
| `pgn130826_maretron_switch_indicator_status` | 130826 | `maretronSwitchIndicatorStatus` | Maretron: Switch Indicator Status [CANboat: incomplete] | `n2k.pgn130826_number_of_status_fields` (numberOfStatusFields) |
| `pgn130944` | 130944 | `airmarPost` | Airmar: POST [CANboat: incomplete] | `n2k.pgn130944_number_of_id_test_result_pairs_to_follow` (numberOfIdTestResultPairsToFollow) |

Each kind is:

1. `when 24 <pgn>`, then a `when` for every leading CANboat field with a fixed `Match` value.
   A reserved field between two match fields is a `when` of all ones: CANboat states that
   reserved bits shall be 1, and spec 0.8 lets only `when` lines come before a kind's other
   lines. A message whose reserved bits there are not all ones is `no-kind`.
2. The fields before the repeating set, in order. A RESERVED field is `const <len> <all ones>`
   and a SPARE field `pad <len>`, so encode writes what NMEA 2000 requires (pack `nmea2000`
   writes zeros there).
3. `group n2k.<list> count <len>`: the CANboat count field is the group's count. It is not a
   model key; encode writes the number of items.

Field transforms, key naming and `when` ordering follow pack `nmea2000` (its `pack.md`). An item
field reuses a key of module `n2k` where the key's type, unit, resolution, offset and lookup
agree; otherwise it gets a new key under the same naming rule. No existing key is renamed or
retyped. `requires` lists up to five rare top-level keys and the kind's list.

## Core keys

| Kind | Core keys | Evidence |
|---|---|---|
| `pgn129029` | `lat` `sscale:1/10000000000000000`, `lon` `sscale:1/10000000000000000` | the rule and evidence of pack `nmea2000`: CANboat fields `latitude` and `longitude`, unit `deg`, signed, resolution 1e-16; NMEA 2000 states the datum in PGN 129044, which neither pack reads |

- `hae`: not mapped. PGN 129029 describes its altitude as "referenced to WGS-84" and carries
  a separate geoidal separation; the database does not say the height is above the
  ellipsoid, so it stays a key of module `n2k`.

## Not mapped, and what each needs

Every definition with a repeating field set or a variable-length field that has no kind in
either pack, with the addition to the pack language that would state it. Fast-packet and ISO
transport reassembly stay outside both packs (layered wires and framing: designed, not built).

| PGN | CANboat id | Description | Reason | Needs |
|---|---|---|---|---|
| 59392 | `0xe8000xee00StandardizedSingleFrameAddressed` | 0xE800-0xEE00: Standardized single-frame addressed | catch-all definition for a range of PGNs | a `when` that holds for a range of values |
| 61184 | `0xef00ManufacturerProprietarySingleFrameAddressed` | 0xEF00: Manufacturer Proprietary single-frame addressed | catch-all definition for a range of PGNs | a `when` that holds for a range of values |
| 61184 | `victronVeCanRegister` | Victron: VE.Can Register | DYNAMIC_FIELD_VALUE | a value whose type and length follow from an earlier key field |
| 61440 | `0xf0000xfeffStandardizedSingleFrameNonAddressed` | 0xF000-0xFEFF: Standardized single-frame non-addressed | catch-all definition for a range of PGNs | a `when` that holds for a range of values |
| 65280 | `0xff000xffffManufacturerProprietarySingleFrameNonAddressed` | 0xFF00-0xFFFF: Manufacturer Proprietary single-frame non-addressed | catch-all definition for a range of PGNs | a `when` that holds for a range of values |
| 126208 | `0x1ed000x1ee00StandardizedFastPacketAddressed` | 0x1ED00 - 0x1EE00: Standardized fast-packet addressed | catch-all definition for a range of PGNs | a `when` that holds for a range of values |
| 126208 | `nmeaCommandGroupFunction` | NMEA - Command group function | repeating field set, and a VARIABLE field | a field laid out as a field of the PGN another field names: an indirect layout |
| 126208 | `nmeaReadFieldsGroupFunction` | NMEA - Read Fields group function | repeating field set, and a VARIABLE field | a field laid out as a field of the PGN another field names: an indirect layout |
| 126208 | `nmeaReadFieldsReplyGroupFunction` | NMEA - Read Fields reply group function | repeating field set, and a VARIABLE field | a field laid out as a field of the PGN another field names: an indirect layout |
| 126208 | `nmeaRequestGroupFunction` | NMEA - Request group function | repeating field set, and a VARIABLE field | a field laid out as a field of the PGN another field names: an indirect layout |
| 126208 | `nmeaWriteFieldsGroupFunction` | NMEA - Write Fields group function | repeating field set, and a VARIABLE field | a field laid out as a field of the PGN another field names: an indirect layout |
| 126208 | `nmeaWriteFieldsReplyGroupFunction` | NMEA - Write Fields reply group function | repeating field set, and a VARIABLE field | a field laid out as a field of the PGN another field names: an indirect layout |
| 126464 | `pgnListTransmitAndReceive` | PGN List (Transmit and Receive) | repeating field set with no count field: it repeats to the end of the message | a group that repeats to the end of the message (or of a `length` extent) |
| 126720 | `0x1ef00ManufacturerProprietaryFastPacketAddressed` | 0x1EF00: Manufacturer Proprietary fast-packet addressed | catch-all definition for a range of PGNs | a `when` that holds for a range of values |
| 126720 | `airmarAddressableMultiFrame` | Airmar: Addressable Multi-Frame | its match values also hold for the more specific definition airmarCalibrateSpeed, which pack nmea2000-seq maps; the two packs accept disjoint messages | fixed-layout and sequential kinds in one pack (a `layout` per kind), so one kind order covers both |
| 126720 | `fusionSetDeviceName` | Fusion: Set Device Name | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 126720 | `fusionSetZoneName` | Fusion: Set Zone Name | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 126976 | `0x1f0000x1feffStandardizedMixedSingleFastPacketNonAddressed` | 0x1F000-0x1FEFF: Standardized mixed single/fast packet non-addressed | catch-all definition for a range of PGNs | a `when` that holds for a range of values |
| 126985 | `alertText` | Alert Text | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 126998 | `configurationInformation` | Configuration Information | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 127498 | `engineParametersStatic` | Engine Parameters, Static | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 128520 | `trackedTargetData` | Tracked Target Data | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 129041 | `aisAidsToNavigationAtonReport` | AIS Aids to Navigation (AtoN) Report | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 129285 | `navigationRouteWpInformation` | Navigation - Route/WP Information | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 129792 | `aisDgnssBroadcastBinaryMessage` | AIS DGNSS Broadcast Binary Message | BINARY of variable size | an opaque field whose bit length an earlier field states |
| 129795 | `aisAddressedBinaryMessage` | AIS Addressed Binary Message | BINARY of variable size | an opaque field whose bit length an earlier field states |
| 129796 | `aisAcknowledge` | AIS Acknowledge | repeating field set with no count field: it repeats to the end of the message | a group that repeats to the end of the message (or of a `length` extent) |
| 129797 | `aisBinaryBroadcastMessage` | AIS Binary Broadcast Message | BINARY of variable size | an opaque field whose bit length an earlier field states |
| 129801 | `aisAddressedSafetyRelatedMessage` | AIS Addressed Safety Related Message | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 129802 | `aisSafetyRelatedBroadcastMessage` | AIS Safety Related Broadcast Message | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 129805 | `aisDataLinkManagementMessage` | AIS Data Link Management Message | repeating field set with no count field: it repeats to the end of the message | a group that repeats to the end of the message (or of a `length` extent) |
| 129808 | `dscCallInformation` | DSC Call Information | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 129808 | `dscDistressAcknowledgementOrRelay` | DSC Distress Acknowledgement or Relay | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 129808 | `dscDistressCallInformation` | DSC Distress Call Information | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 129811 | `aisSingleSlotBinaryMessageDeprecated` | AIS Single Slot Binary Message (Deprecated) | BINARY of variable size | an opaque field whose bit length an earlier field states |
| 129812 | `aisMultiSlotBinaryMessageDeprecated` | AIS Multi Slot Binary Message (Deprecated) | repeating field set, and a BINARY of variable size field | an opaque field whose bit length an earlier field states |
| 129814 | `aisSingleSlotBinaryMessage` | AIS Single Slot Binary Message | BINARY of variable size | an opaque field whose bit length an earlier field states |
| 129815 | `aisMultiSlotBinaryMessage` | AIS Multi Slot Binary Message | BINARY of variable size | an opaque field whose bit length an earlier field states |
| 130060 | `label` | Label | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130064 | `routeAndWpServiceDatabaseList` | Route and WP Service - Database List | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130065 | `routeAndWpServiceRouteList` | Route and WP Service - Route List | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130066 | `routeAndWpServiceRouteWpListAttributes` | Route and WP Service - Route/WP-List Attributes | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130067 | `routeAndWpServiceRouteWpNamePosition` | Route and WP Service - Route - WP Name & Position | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130068 | `routeAndWpServiceRouteWpName` | Route and WP Service - Route - WP Name | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130069 | `routeAndWpServiceXteLimitNavigationMethod` | Route and WP Service - XTE Limit & Navigation Method | repeating field set whose count (field 2) is not directly before the set (field 4) | a `count` taken from a field read earlier, not from the bits at the cursor |
| 130070 | `routeAndWpServiceWpComment` | Route and WP Service - WP Comment | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130071 | `routeAndWpServiceRouteComment` | Route and WP Service - Route Comment | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130072 | `routeAndWpServiceDatabaseComment` | Route and WP Service - Database Comment | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130073 | `routeAndWpServiceRadiusOfTurn` | Route and WP Service - Radius of Turn | repeating field set whose count (field 2) is not directly before the set (field 6) | a `count` taken from a field read earlier, not from the bits at the cursor |
| 130074 | `routeAndWpServiceWpListWpNamePosition` | Route and WP Service - WP List - WP Name & Position | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130320 | `tideStationData` | Tide Station Data | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130321 | `salinityStationData` | Salinity Station Data | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130322 | `currentStationData` | Current Station Data | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130323 | `meteorologicalStationData` | Meteorological Station Data | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130324 | `mooredBuoyStationData` | Moored Buoy Station Data | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130330 | `lightingSystemSettings` | Lighting System Settings | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130561 | `lightingZone` | Lighting Zone | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130562 | `lightingScene` | Lighting Scene | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130563 | `lightingDevice` | Lighting Device | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130566 | `lightingProgram` | Lighting Program | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130568 | `entertainmentDiagnosticStatus` | Entertainment - Diagnostic Status | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130570 | `libraryDataFile` | Library Data File | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130571 | `libraryDataGroup` | Library Data Group | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130572 | `libraryDataSearch` | Library Data Search | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130573 | `supportedSourceData` | Supported Source Data | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130574 | `supportedZoneData` | Supported Zone Data | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130575 | `entertainmentParentalControlStatus` | Entertainment - Parental Control Status | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130581 | `zoneConfigurationDeprecated` | Zone Configuration (deprecated) | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130583 | `availableAudioEqPresets` | Available Audio EQ presets | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130584 | `availableBluetoothAddresses` | Available Bluetooth addresses | repeating field set, and a STRING_LAU field | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130816 | `0x1ff000x1ffffManufacturerSpecificFastPacketNonAddressed` | 0x1FF00-0x1FFFF: Manufacturer Specific fast-packet non-addressed | catch-all definition for a range of PGNs | a `when` that holds for a range of values |
| 130816 | `furunoStatusAndVersionReport` | Furuno: Status and Version Report | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130816 | `sonichubAlbum` | SonicHub: Album | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130816 | `sonichubAmRadio` | SonicHub: AM Radio | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130816 | `sonichubArtist` | SonicHub: Artist | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130816 | `sonichubFmRadio` | SonicHub: FM Radio | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130816 | `sonichubMenuItem` | SonicHub: Menu Item | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130816 | `sonichubSourceList` | SonicHub: Source List | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130816 | `sonichubTrack` | SonicHub: Track | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130818 | `maretronLabel` | Maretron: Label | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130820 | `fusionAlbumName` | Fusion: Album Name | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130820 | `fusionArtistName` | Fusion: Artist Name | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130820 | `fusionDeviceName` | Fusion: Device Name | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130820 | `fusionMarineTuner` | Fusion: Marine Tuner | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130820 | `fusionMenuItem` | Fusion: Menu Item | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130820 | `fusionRdsData` | Fusion: RDS Data | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130820 | `fusionSiriusxmArtist` | Fusion: SiriusXM Artist | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130820 | `fusionSiriusxmCategory` | Fusion: SiriusXM Category | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130820 | `fusionSiriusxmChannel` | Fusion: SiriusXM Channel | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130820 | `fusionSiriusxmContentInfo` | Fusion: SiriusXM Content Info | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130820 | `fusionSiriusxmPresets` | Fusion: SiriusXM Presets | BINARY of variable size | an opaque field whose bit length an earlier field states |
| 130820 | `fusionSiriusxmTitle` | Fusion: SiriusXM Title | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130820 | `fusionSource` | Fusion: Source | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130820 | `fusionTrackName` | Fusion: Track Name | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130820 | `fusionTuner` | Fusion: Tuner | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130820 | `fusionZoneName` | Fusion: Zone Name | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130821 | `maretronAlertText` | Maretron: Alert Text | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130822 | `navicoConfigurationSet` | Navico: Configuration Set | DYNAMIC_FIELD_VALUE | a value whose type and length follow from an earlier key field |
| 130822 | `navicoUdbDatabaseObjectDump` | Navico: UDB Database, Object Dump | repeating field set, and a DYNAMIC_FIELD_VALUE field | a value whose type and length follow from an earlier key field |
| 130822 | `navicoUdbDatabaseSettingsDump` | Navico: UDB Database, Settings Dump | repeating field set, and a DYNAMIC_FIELD_VALUE field | a value whose type and length follow from an earlier key field |
| 130822 | `navicoUdbDatabaseTableDump11` | Navico: UDB Database, Table Dump | repeating field set with no count field: it repeats to the end of the message | a group that repeats to the end of the message (or of a `length` extent) |
| 130822 | `navicoUdbDatabaseTableDump12` | Navico: UDB Database, Table Dump | repeating field set with no count field: it repeats to the end of the message | a group that repeats to the end of the message (or of a `length` extent) |
| 130822 | `navicoUdbDatabaseTableDump13` | Navico: UDB Database, Table Dump | repeating field set with no count field: it repeats to the end of the message | a group that repeats to the end of the message (or of a `length` extent) |
| 130822 | `navicoUdbDatabaseTableDump14` | Navico: UDB Database, Table Dump | repeating field set with no count field: it repeats to the end of the message | a group that repeats to the end of the message (or of a `length` extent) |
| 130822 | `navicoUdbDatabaseTableDump15` | Navico: UDB Database, Table Dump | repeating field set with no count field: it repeats to the end of the message | a group that repeats to the end of the message (or of a `length` extent) |
| 130822 | `navicoUdbDatabaseTableDump18` | Navico: UDB Database, Table Dump | repeating field set with no count field: it repeats to the end of the message | a group that repeats to the end of the message (or of a `length` extent) |
| 130823 | `navicoDataTypeSourceDirectory` | Navico: Data Type Source Directory | repeating field set, and a DYNAMIC_FIELD_VALUE field | a value whose type and length follow from an earlier key field |
| 130823 | `navicoDataTypeSourceDirectoryFullReport` | Navico: Data Type Source Directory, Full Report | repeating field set, and a DYNAMIC_FIELD_VALUE field | a value whose type and length follow from an earlier key field |
| 130824 | `bGKeyValueData` | B&G: key-value data | repeating field set, and a DYNAMIC_FIELD_VALUE field | a value whose type and length follow from an earlier key field |
| 130824 | `mercuryEngineKeyValueData` | Mercury: Engine Key-Value Data | repeating field set, and a DYNAMIC_FIELD_VALUE field | a value whose type and length follow from an earlier key field |
| 130834 | `maretronSmsStatus` | Maretron: SMS Status | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130835 | `maretronSmsTextMessage` | Maretron: SMS Text Message | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 130845 | `furunoMultiSatsInViewExtended` | Furuno: Multi Sats In View Extended | repeating field set with no count field: it repeats to the end of the message | a group that repeats to the end of the message (or of a `length` extent) |
| 130845 | `simnetKeyValue` | Simnet: Key Value | DYNAMIC_FIELD_VALUE | a value whose type and length follow from an earlier key field |
| 130846 | `simnetParameterSet` | Simnet: Key Value - Long | DYNAMIC_FIELD_VALUE | a value whose type and length follow from an earlier key field |
| 130847 | `navicoAsciiIdentifier` | Navico: ASCII Identifier | STRING_LZ | text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) |
| 130852 | `navicoDiagnosticData` | Navico: Diagnostic Data | repeating field set, and a DYNAMIC_FIELD_VALUE field | a value whose type and length follow from an earlier key field |

By addition:

| Addition | Definitions |
|---|---|
| text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) | 46 |
| text whose length a preceding byte states, followed by a zero byte (a counted `ascii`) | 25 |
| a value whose type and length follow from an earlier key field | 11 |
| a group that repeats to the end of the message (or of a `length` extent) | 10 |
| a `when` that holds for a range of values | 8 |
| an opaque field whose bit length an earlier field states | 8 |
| a field laid out as a field of the PGN another field names: an indirect layout | 6 |
| a `count` taken from a field read earlier, not from the bits at the cursor | 2 |
| fixed-layout and sequential kinds in one pack (a `layout` per kind), so one kind order covers both | 1 |

Pack `nmea2000` also lists definitions with no field the pack language can carry, and the
limits both packs share ("not available" values, lookup names, 64-bit unsigned values).

## Vectors

- `rt-<kind>.json`: a round trip with two items; `rt-<kind>-no-items.json`: the list present
  and empty. The generator packs the bytes from CANboat's field list, not from `pack.def`,
  with values inside each field's range that survive scaling exactly, and decodes them with
  its own codec of the `pack.def` text. `model` holds `@kind`, every key, `<list>.#` and every
  item value.
- `x01-pgn129029-to-geojson.json`: GNSS Position Data at 52.5 N, 4.5 E; `expect` written by
  hand (raw / 10^16, exact in doubles) and checked against the codec.
- `e01-pgn129029-count-beyond-the-input.json`: the count states one item more than the input
  holds: `malformed-wire` (spec 0.8 ruling 14 and Errors).
- `e02-fixed-layout-pgn-is-no-kind.json`: a PGN 129025 message is `no-kind` here.

Vectors hold lowercase hex text in `input` / `expect`.
