# Pack: lorawan-phypayload

A LoRaWAN PHYPayload, the radio frame's payload as a gateway or a network server sees it. Wire `bits`,
`layout sequential`, `bit_order msb`; DevAddr, NetID and the counters are little-endian (`swap`). No
kinds: MType chooses the layout. Written by `tools/gen/lpwan2-pack.py`.

## What is mapped

- **MHDR**: MType, the three RFU bits, Major.
- **Join request** (0): JoinEUI, DevEUI, DevNonce, MIC.
- **Join accept** (1): encrypted as a whole (its MIC too), so octets.
- **Data frames** (2-5): FHDR: DevAddr, FCtrl (ADR, ADRACKReq, ACK, FPending or ClassB, and FOptsLen as
  the count of FOpts), FCnt, FOpts; then FPort, FRMPayload and MIC as one list of octets.
- **Rejoin request** (6): type 0 and 2 (NetID, DevEUI, RJcount0, MIC), type 1 (JoinEUI, DevEUI, RJcount1,
  MIC).
- **Proprietary** (7) and anything else: octets.

EUIs and the MIC are hexadecimal text of their octets in wire order (EUIs low octet first, as sent).

## Shared keys

None.

## Not mapped

- **FPort, FRMPayload and the MIC apart**: the MIC is the last four octets of the frame and FPort is
  present only when octets remain before it, so the three are one list; a pack line for "all but the
  last four octets" does not exist. In a frame without FPort (vector 04) the list is the MIC alone.
- **The MIC computed** (AES-CMAC) and FRMPayload or join accept decrypted: keys are outside the message.
- **FOpts as MAC commands**: octets; each command's length depends on its CID and the direction.
- **The full 32-bit frame counter**: only the low 16 bits are sent.
- **LoRaWAN 1.1 FOpts encryption**, the class B beacon, relay frames.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one PHYPayload.

## Vectors

`tools/gen/lpwan2-vectors.py`, without an engine: a join request; an encrypted join accept; an unconfirmed
uplink; a confirmed downlink with FOpts and no FPort; rejoin requests of types 0 and 1; a proprietary
frame; a cut header (`malformed-wire`).
