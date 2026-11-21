# Provenance: shelly-rpc-response

Written by hand from the Shelly Gen2+ device API documentation. No page or part of a page is
copied into this tree; the example frames of the documentation are not used, and every vector
value is this repository's own.

| | |
|---|---|
| Site | https://shelly-api-docs.shelly.cloud/gen2/ (Allterco Robotics), built from an unpublished source |
| Pages | `General/RPCProtocol`, `General/Notifications`, `ComponentsAndServices/Switch`, `ComponentsAndServices/Cover`, `ComponentsAndServices/Input`, `ComponentsAndServices/Temperature`, `ComponentsAndServices/Sys` |
| Version | the pages as served on the date read; they describe firmware up to 2.0 |
| Date read | 2026-11-21 |

## Licence

The footer of every page reads, in substance, copyright 2026 Allterco Robotics, and nothing more.
The site has no terms of use, licence or legal notice page, and no public repository of the
documentation was found. No licence is stated, so this pack is labelled `LicenseRef-unstated`
(rule 17 of the pack brief). The pages are published without a login for the purpose of building
clients of the devices.

## What this repository takes

The frame members of the JSON-RPC 2.0 protocol as Shelly uses it (`id`, `src`, `dst`, `method`,
`params`, `result`, `error`), the notification methods and the `ts` member, the component keys
(`<type>:<id>`) and the member names, types and units of the status objects listed in pack.md.

## Attribution

Frame and status member names from the Shelly Gen2+ device API documentation,
https://shelly-api-docs.shelly.cloud/gen2/ (read 2026-11-21). Copyright Allterco Robotics. No
licence stated (LicenseRef-unstated). Names restated; no text or examples copied.

## SHA-256

The pages as fetched (HTML):

```
c422ff106a9deb75601bc8c3758a01aa04c45aa1dbc9b278db92d9c3081ce65e  General_RPCProtocol.html
d92f3d5b0f421d471000a61847b0548252c2278f57ab9c10f4513059b0c45227  General_Notifications.html
8f7dc4212c8cbaa8368fd86aec063d5612a512818a631d45baaaeedbdbab7bf5  ComponentsAndServices_Switch.html
302355dfb2f7db8e12a08b59cc067c9c34d6e752880efe839f737ab6fcd1897e  ComponentsAndServices_Cover.html
8d1e3d17cfc3a0cfd18e00a45d154e2156f8926f0f10b679d9d4d2b95daa19a2  ComponentsAndServices_Input.html
36e99b2392f7478b3d344aeec4b0f43170c013827466e644680c5903b658d688  ComponentsAndServices_Temperature.html
f693f506792ce0342758c542d235221e95cc4ca442754918988dbab04306e8c1  ComponentsAndServices_Sys.html
```
