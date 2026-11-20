# knx-cemi-dpt1

A KNX cEMI L_Data frame (pack `knx-cemi`, same layout up to the TPDU) whose group value is read
as a datapoint of type 1. Which DPT a group address carries is installation configuration, so the
caller chooses this pack. Restated from calimero-core (GPL-2.0 with the Classpath Exception; facts
only); the KNX Standard was not used.

## The value

DPT 1 (1-bit, boolean): the value is the low bit of the six data bits in the second TPDU byte; the five bits above it are a raw key.

A GroupValueRead carries no value: the value key is absent.

## Not mapped

No shared key (see `knx-cemi`).
