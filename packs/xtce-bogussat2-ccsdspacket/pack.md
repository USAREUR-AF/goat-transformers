# xtce-bogussat2-ccsdspacket

The containers of the XTCE database BogusSAT-2.xml (https://github.com/CesarCoelho/xtcetools @14b7f51c5) that extend `CCSDSPacket`, as one
`layout sequential` `bits` pack written by `tools/gen/xtce2pack.py`. Each concrete
container is a message kind. Its restriction criteria, and those of its bases,
are `when ... at <offset> as <key>` lines on the bits they compare, so the kind is
selected by them on decode and chosen by those keys on encode; the compared
bits are a `pad` in the kind, since the `as` key holds them.

| Kind | Fields | Selected by | Not mapped from |
|---|---:|---|---|
| `ecss_service_1_subservice_1` | 5 | `ccsds_packet_id_version` = 0, `ccsds_packet_id_type` = 0, `ccsds_packet_id_sec_hdr_flag` = 1, `ccsds_packet_id_apid` = 100, `pus_data_field_header_spare1` = 0, `pus_data_field_header_version` = 1, `pus_data_field_header_spare4` = 0, `pus_data_field_header_service` = 1, `pus_data_field_header_subservice` = 1 | an entry with an include condition |
| `ecss_service_1_subservice_2` | 5 | `ccsds_packet_id_version` = 0, `ccsds_packet_id_type` = 0, `ccsds_packet_id_sec_hdr_flag` = 1, `ccsds_packet_id_apid` = 100, `pus_data_field_header_spare1` = 0, `pus_data_field_header_version` = 1, `pus_data_field_header_spare4` = 0, `pus_data_field_header_service` = 1, `pus_data_field_header_subservice` = 2 | an entry with an include condition |
| `ecss_service_6_subservice_6` | 5 | `ccsds_packet_id_version` = 0, `ccsds_packet_id_type` = 0, `ccsds_packet_id_sec_hdr_flag` = 1, `ccsds_packet_id_apid` = 100, `pus_data_field_header_spare1` = 0, `pus_data_field_header_version` = 1, `pus_data_field_header_spare4` = 0, `pus_data_field_header_service` = 6, `pus_data_field_header_subservice` = 6 | an entry with an include condition |
| `ccsds_space_packet1` | 9 | `ccsds_packet_id_version` = 0, `ccsds_packet_id_type` = 0, `ccsds_packet_id_sec_hdr_flag` = 0, `ccsds_packet_id_apid` = 1 |  |
| `ccsds_space_packet2` | 4 | `ccsds_packet_id_version` = 0, `ccsds_packet_id_type` = 0, `ccsds_packet_id_sec_hdr_flag` = 0, `ccsds_packet_id_apid` = 2 | an entry with an include condition |
| `ccsds_space_packet3` | 3 | `ccsds_packet_id_version` = 0, `ccsds_packet_id_type` = 0, `ccsds_packet_id_sec_hdr_flag` = 0, `ccsds_packet_id_apid` = 3 | a string whose size is not fixed |
| `ccsds_space_packet4` | 4 | `ccsds_packet_id_version` = 0, `ccsds_packet_id_type` = 0, `ccsds_packet_id_sec_hdr_flag` = 0, `ccsds_packet_id_apid` = 4 | an entry with an include condition |
| `ccsds_space_packet5` | 5 | `ccsds_packet_id_version` = 0, `ccsds_packet_id_type` = 0, `ccsds_packet_id_sec_hdr_flag` = 0, `ccsds_packet_id_apid` = 5 | an entry with an include condition |
| `ccsds_space_packet6` | 5 | `ccsds_packet_id_version` = 0, `ccsds_packet_id_type` = 0, `ccsds_packet_id_sec_hdr_flag` = 0, `ccsds_packet_id_apid` = 6 | binary encoding of EnumeratedParameterType |

Containers left out, with the reason:

- `ECSS_SpacePacket1`: criterion on pus_structure_id, which no entry before it lays out
- `ECSS_SpacePacket2`: criterion on pus_structure_id, which no entry before it lays out

Floats and texts are written as zero bits in the round-trip vectors, which
check the bytes and the integer, boolean and enumerated keys.

Do not edit `pack.def`, `PROVENANCE.md`, the module or the `rt-*` vectors by hand:
change the generator or its inputs and run it again. The `derived-*` vectors
were derived by hand from the database and the specification, with no engine
and not by the generator, which keeps them.
