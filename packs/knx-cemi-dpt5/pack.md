# knx-cemi-dpt5

A KNX cEMI L_Data frame (pack `knx-cemi`, same layout up to the TPDU) whose group value is read
as a datapoint of type 5. Which DPT a group address carries is installation configuration, so the
caller chooses this pack. Restated from calimero-core (GPL-2.0 with the Classpath Exception; facts
only); the KNX Standard was not used.

## The value

DPT 5 (8-bit unsigned): one data byte. It is read as a float key (`uscale:1`), so that module `knx` derives `knx.dpt5_scaling_percent` (DPT 5.001, raw x 100/255) and `knx.dpt5_angle_deg` (DPT 5.003, raw x 360/255) with `scale`. Only the raw value is written back; the derived keys are not encoded.

A GroupValueRead carries no value: the value key is absent.

## Not mapped

No shared key (see `knx-cemi`).
