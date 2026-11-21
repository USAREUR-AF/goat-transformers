# knx-cemi-dpt9

A KNX cEMI L_Data frame (pack `knx-cemi`, same layout up to the TPDU) whose group value is read
as a datapoint of type 9. Which DPT a group address carries is installation configuration, so the
caller chooses this pack. Restated from calimero-core (GPL-2.0 with the Classpath Exception; facts
only); the KNX Standard was not used.

## The value

DPT 9 (2-byte float): value = 0.01 x M x 2^E, with a 12-bit two's-complement mantissa M whose sign bit stands apart from its other 11 bits and a 4-bit exponent E. The pack keeps the sign, the exponent and the 11 mantissa bits as raw keys: no transform computes 0.01 x M x 2^E. Missing: a transform for this float form (and for a mantissa split around the exponent).

A GroupValueRead carries no value: the value key is absent.

## Not mapped

No shared key (see `knx-cemi`).
