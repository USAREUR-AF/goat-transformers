# knx-cemi-dpt14

A KNX cEMI L_Data frame (pack `knx-cemi`, same layout up to the TPDU) whose group value is read
as a datapoint of type 14. Which DPT a group address carries is installation configuration, so the
caller chooses this pack. Restated from calimero-core (GPL-2.0 with the Classpath Exception; facts
only); the KNX Standard was not used.

## The value

DPT 14 (4-byte float): an IEEE 754 single, big-endian, `f32`. The unit depends on the sub-type (14.xxx) the installation assigns, so the key is raw.

A GroupValueRead carries no value: the value key is absent.

## Not mapped

No shared key (see `knx-cemi`).
