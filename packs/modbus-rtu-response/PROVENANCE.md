# Provenance: modbus-rtu-response pack

Read on 2026-11-21. No source file is copied into this tree. The documents are linked for download
from https://www.modbus.org/modbus-specifications without a login.

| Source | Where | SHA-256 |
|---|---|---|
| Modbus Organization, MODBUS Application Protocol Specification V1.1b3 | https://www.modbus.org/file/secure/modbusprotocolspecification.pdf | `f80d0d7132fd035104c3f21b01026470e3310ca3d8d493d9a9737d0d32ad2eb1` |
| Modbus Organization, MODBUS over Serial Line Specification and Implementation Guide V1.02 | https://www.modbus.org/file/secure/modbusoverserial.pdf | `85a91e278b26d68c94a2f61a5300cd39c9e4c855034833f391abc6541fbdf7e5` |

## Licence

The documents state no licence and no copyright line. The Modbus Organization's legal page says:
"Copyright © 2005 Modbus Organization, Inc. All Rights Reserved", that the content of the website is
copyrighted by the organization, and that no permission is granted to use its names and trademarks
other than for non-commercial, informational purposes. The Application Protocol notes that MODBUS
is a registered trademark of Schneider Automation Inc.

This pack restates the frame and PDU layouts (field order, sizes, codes) in its own words; no text or
table of the documents is copied. Because no licence is stated it is labelled `LicenseRef-unstated`
(REUSE.toml in this directory; model/modbus.def.license for the module). The vectors are frames built
by `tools/gen/modbus-vectors.py` from values chosen there; their expected bytes are derived there,
without an engine.
