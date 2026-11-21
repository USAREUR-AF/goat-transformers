# knx-cemi

A KNX cEMI L_Data frame (standard frame): what a KNXnet/IP routing indication or tunneling request
carries, and what USB and serial KNX interfaces exchange. The data of the frame is kept as bytes;
the `knx-cemi-dpt*` packs read it as one datapoint type. Restated from calimero-core (GPL-2.0 with
the Classpath Exception; facts only, PROVENANCE.md); the KNX Standard is a paid document and was
not used.

## Layout

`bits`, `layout sequential`, `bit_order msb`. Message code (0x11 L_Data.req, 0x29 L_Data.ind,
0x2E L_Data.con); additional information as a length and bytes; control field 1 (frame format,
repeat, broadcast, priority, acknowledge request, confirm) and control field 2 (address type,
hop count, extended frame format) bit by bit; the source individual address as area, line and
device; the 16-bit destination; the NPDU length (the TPDU's length minus one, `length 8 bytes
plus -1`); the TPDU: the 6-bit transport control, the 4-bit application service (APCI: 0 read,
1 response, 2 write) across the two first bytes, the six data bits in the second byte, then the
data bytes to the end of the NPDU.

## Not mapped

- Extended frames (control field 1 bit 7 = 0) and cEMI messages other than L_Data are read with
  the same layout; calimero refuses them, and their data may not be what this layout reads.
- No shared key: KNX carries building-automation values, addressed by group addresses whose
  meaning is configuration, not part of the frame.
- The meaning of the data depends on the datapoint type the installation assigns to the group
  address: `knx-cemi-dpt1`, `-dpt5`, `-dpt9`, `-dpt14` read the four common ones.
