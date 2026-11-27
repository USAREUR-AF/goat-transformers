# xtce-bogussat2-processor-config-table

The containers of the XTCE database BogusSAT-2.xml (https://github.com/CesarCoelho/xtcetools @14b7f51c5) that extend `Processor_Config_Table`, as one
`layout sequential` `bits` pack written by `tools/gen/xtce2pack.py`. Each concrete
container is a message kind. Its restriction criteria, and those of its bases,
are `when ... at <offset> as <key>` lines on the bits they compare, so the kind is
selected by them on decode and chosen by those keys on encode; the compared
bits are a `pad` in the kind, since the `as` key holds them.

| Kind | Fields | Selected by | Not mapped from |
|---|---:|---|---|
| `processor_1_config_table` | 7 | `sc001_onboard_processor_config_table_processor_id` = 1 | an entry at a stated location |
| `processor_2_config_table` | 7 | `sc001_onboard_processor_config_table_processor_id` = 2 | an entry at a stated location |
| `processor_3_config_table` | 7 | `sc001_onboard_processor_config_table_processor_id` = 3 | an entry at a stated location |

Floats and texts are written as zero bits in the round-trip vectors, which
check the bytes and the integer, boolean and enumerated keys.

Do not edit `pack.def`, `PROVENANCE.md`, the module or the `rt-*` vectors by hand:
change the generator or its inputs and run it again. The `derived-*` vectors
were derived by hand from the database and the specification, with no engine
and not by the generator, which keeps them.
