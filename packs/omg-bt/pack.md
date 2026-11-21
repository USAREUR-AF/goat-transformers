# omg-bt

The object OpenMQTTGateway publishes on `<base>/<gateway>/BTtoMQTT/<address>` (or the shared
`BTtoMQTT` topic) for one BLE advertisement it received. Licence Apache-2.0 (a layout restated
from GPL-3.0 firmware, no code copied).

## Message convention

One JSON object. The raw members: `id` (the advertiser's address, colon-separated hexadecimal),
`mac_type` and `adv_type` (numbers), `name` (when advertised), `manufacturerdata`, `servicedata`
(hexadecimal text) and `servicedatauuid`, `rssi` (dBm) and `txpower` (dBm, when advertised).
When the gateway's decoder recognises the device it adds `brand`, `model`, `model_id`, `type` (a
device class such as `THB`, `BBQ`, `BCON`) and the decoded readings, whose names depend on the
device: this pack maps the common ones, `tempc`, `tempf` (degrees C and F), `hum` (percent),
`batt` (percent) and `volt` (V).

## Shared keys

None. The gateway sends no time, and `id` is the address of the advertiser, which can be random
and change (privacy addresses); it is not bound to core `uid`.

## Raw keys

Every member named above, under module `omg`, with the JSON type the gateway writes.

## Not mapped, and why

- Decoded readings other than the five above (`pm25`, `co2`, `lux`, `moi`, `wgt`, `steps` and
  many others) are residue: the decoder defines a property set per device model, and the pack
  maps fixed member names only.
- The gateway can be configured (`pubadvdata`) to leave the raw advertisement data out; the pack
  requires no member.
- Members written in a decoder as arrays are not carried.
