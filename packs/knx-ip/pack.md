# knx-ip

KNXnet/IP over UDP: the 6-byte header (header length, protocol version 0x10, service type, total
length) and, by service type, the body: a routing indication (0x0530, a cEMI frame), a tunneling
request (0x0420, the 4-byte connection header then a cEMI frame) or a tunneling acknowledge
(0x0421, the connection header with a status). The cEMI frame is laid out as in `knx-cemi`, with
its data as bytes. The total length is `length 16 whole`. Restated from calimero-core
(GPL-2.0 with the Classpath Exception; facts only); the KNX Standard was not used.

## Not mapped

- In the cEMI frame, a TPDU of one octet (NPDU length 0, as the transport-layer control frames use; calimero reads
  a TPDU of the NPDU length plus one) is `malformed-wire`: the APCI lines do not fit the
  extent (`2900bce011050a030080` on Rust). Reading the APCI only when the TPDU is longer than
  one octet needs a condition on the length, which a `length` block does not give.
- Other services (search, description, connect, connection state, disconnect, device
  configuration, routing busy and lost message, KNX IP Secure) are `no-kind`.
- No shared key.
