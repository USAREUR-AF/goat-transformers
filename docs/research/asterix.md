# ASTERIX: notes for a pack author

Status: Written. No ASTERIX pack exists; a pack needs presence-indicated items
([../roadmap.md](../roadmap.md)). These notes are read from the public
specifications and are a starting point for the pack author, who checks every
value against the edition the pack names.

EUROCONTROL ASTERIX (All-Purpose Structured EUROCONTROL Surveillance Information
Exchange). The specifications are public at https://www.eurocontrol.int/asterix.
A machine-readable form to check a pack against is the asterix-specs project
(https://zoranbosnjak.github.io/asterix-specs/). Record the exact edition in
each pack: editions change, and some are not backward compatible (category 021
edition 2.6 to 2.7).

## Framing and FSPEC (all categories)

- Data block: 1 byte CAT + 2 bytes LEN (big-endian, includes CAT+LEN) + records
  of that category. All multi-byte fields big-endian.
- Each record starts with an FSPEC: per octet, top 7 bits are presence flags for
  the next seven items in UAP order; bit 1 (FX) = another FSPEC octet follows.
- UAP (User Application Profile): the per-category ordered table mapping each
  FSPEC bit to a Data Item and its length rule. A pack treats UAP as a table.
- Item shapes: fixed, extended (FX-chained), repetitive (REP count + copies),
  compound (presence subfield + subfields). Signed = two's complement.

## Category key items (field, bytes, scale)

Cat 048 monoradar target (EUROCONTROL-SPEC-0149-4): I048/040 measured position
polar RHO=1/256 NM, THETA=360/2^16 deg; I048/161 track number 12-bit; I048/140
time 1/128 s; I048/200 velocity GS=2^-14 NM/s, heading 360/2^16 deg; I048/220
ICAO 24-bit; I048/240 callsign 8x6-bit; I048/070 Mode-3/A; I048/090 Mode C FL 1/4.

Cat 062 system track (Part 9): I062/105 WGS-84 lat/lon 180/2^25 deg two's
complement; I062/040 track number 16-bit; I062/070 time 1/128 s; I062/185
velocity Cartesian Vx/Vy 0.25 m/s; I062/136 measured FL; I062/380 compound holds
ICAO address and derived data.

Cat 034 radar service (Part 2b): no target reports; I034/000 message type enum,
I034/020 sector 360/2^8 deg, I034/120 sensor site position.

Cat 021 ADS-B (Part 12): I021/130 WGS-84 180/2^23 deg, I021/131 high-res
180/2^30; I021/080 ICAO addr; I021/073 time 1/128 s; I021/160 ground vector;
I021/170 callsign.

Cat 010 surface (Part 7): I010/040 polar RHO in meters; I010/041 WGS-84
180/2^25; I010/161 track number; I010/200/202 velocity.

Cat 240/241 video/technical: framing not target-model; 240 carries video spokes,
241 is non-standard range (not on the ASTERIX website).

Document scheme: legacy SUR.ET1.ST05.2000-STD-<part>-01; current
EUROCONTROL-SPEC-0149-<part> (4=048, 9=062, 2b=034, 7=010, 12=021).
