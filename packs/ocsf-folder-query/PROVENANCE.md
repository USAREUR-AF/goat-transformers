# Provenance of the ocsf-folder-query pack

`tools/gen/ocsf2pack.py` reads the files below, resolves the class `folder_query` into a JSON
Schema of structure only and passes it to `tools/gen/jsonschema2pack.py`. The files are
not kept in this repository. Read on 2026-11-20.

| | |
|---|---|
| Document | Open Cybersecurity Schema Framework (OCSF) 1.9.0, event class `folder_query` |
| Publisher | OCSF, a Series of LF Projects, LLC |
| Repository | https://github.com/ocsf/ocsf-schema at tag `1.9.0`, commit `856d462bd20dc46cc1ffed2dfffe3b91ef0fbeba` |

| File | SHA-256 |
|---|---|
| `LICENSE` | `0cec06e0e55fbc3dc5cee4fca9b607f66cb8f4e4dbcf3b3c013594dd156732e9` |
| `NOTICE` | `990c6fa8d244c2334708b526d923cee8b4853a26fdd2c4f310e39d7c51fc4347` |
| `categories.json` | `4ee3a5f8906c4bc49014e4da28a8bb9666cced4af944e3fab85777381bfb70cc` |
| `dictionary.json` | `d05f472d58802524679a03ad77ae1ac6b9eb2135013931bad15926da65e8d42d` |
| `events/base_event.json` | `53782cf02a503d7c5559fa9bedb7d60d742b0fa68c46aa958ab9481cd8a53095` |
| `events/discovery/discovery_result.json` | `cf26505e28050c2ff2c25eee67a8d71fb68de1da481d1f79b69b402aa5648ecc` |
| `events/discovery/folder_query.json` | `8167b0ac66c593813c928821ac8e02b135a1bb3b121ee3e53668ea53f5b91e30` |
| `objects/_entity.json` | `3bf4fe72d690fadbf3611784776f3a6befcefe3eb38f7f0cf7c3f33666933eeb` |
| `objects/account.json` | `59fcb6ade67c7d2843e2b4c8bc75559212fa35142babdf1c2845a0448d39585c` |
| `objects/agent.json` | `788fc14c89cd158aad44449ba120743f836bc014a06be38f2a9d4f94bab49e85` |
| `objects/autonomous_system.json` | `f580b27be5a9545d2e3ef96b2a5e386b746bacd8313e37199cd74984421af152` |
| `objects/certificate.json` | `685f84d863af83762270d9ddaf97f343d9607d05e27aae96b37e34057744e432` |
| `objects/cpu_info.json` | `1561b7696ca20c1a8be7ca2b8f427a1f023ef0f79ac6ce3a954cb5754a6a8bcc` |
| `objects/device.json` | `a85202d96ebfb8a1d51ea449d865a23e8387f5c648cfe7233c00d83723a8d64d` |
| `objects/device_hw_info.json` | `b02b2c809fa33001b3c57d9818be834757cccd241e19d449d5da9230ca3acdf4` |
| `objects/digital_signature.json` | `109dbb7386198fe65fe478cf09f588859b98c39f38ae55e60731ad83cbbf2424` |
| `objects/display.json` | `76ada52a0517f4f3002291bf6703ac7daf29662d7e7f9acddeccd593dd46b819` |
| `objects/download_info.json` | `243b5f162f6b2fd92f6adafbac864cd26cd4a5dd8ce8ae2ba83c29a6959d52ba` |
| `objects/encryption_details.json` | `5c62f3de6558e670f8e14d91aaaac16ea5b7bb7748f5593890c44992f16d1b8f` |
| `objects/endpoint.json` | `71a0c6e4a3c265776aa8626b2b98e5a8f7b51c778279ff87c03f1f221c8b69df` |
| `objects/enrichment.json` | `c218e3e54593f88bdd03c39f07432d1672bac9be7bf96f5f39fea3dd05148cf6` |
| `objects/extension.json` | `e1b782e36c922ea9827e6e751540eaca2a3ccb9e8599cc14f81d1b192af5f1e1` |
| `objects/feature.json` | `937440e5ba963289320f3c3e0499f2e9aaab8ce9cabaf34ed7b7c09680c97142` |
| `objects/file.json` | `d1d9dee932b73798858b9eabe6120a89b9c2c18b1eaedd0cdc51debfb1ebd753` |
| `objects/fingerprint.json` | `b44efe37e5c06da4ad1b99cd10fe9a687f739972cc148ce0528e9ddc234b64d9` |
| `objects/gpu_info.json` | `bcbe58f66b28de483766559cd652e2fd013d546976374c5baa67eed57de5ef99` |
| `objects/group.json` | `ec45c3ff664c9e62d543a8f5cb4610d8365486a979f9199615826d7025eca669` |
| `objects/image.json` | `6e2c9b9bfd2b691d574fe7e90b716742301401e4c46b5daf06444eee7fe458a0` |
| `objects/key_value_object.json` | `02f377b4ede5ee867dbb59823187b79e0b40b959dbc77570aaf6a764d1259269` |
| `objects/keyboard_info.json` | `e7ee36c0ebbfb06cf7a8b238507445100b1409c8e2b0287a6c8d9bb34136de82` |
| `objects/ldap_person.json` | `8f071391281b51f3df174ecd77ec62fc3e2ed1977c6aa0d4f7f34eb08946c310` |
| `objects/location.json` | `43c89155e8bfb7f996a1e681321abaa1fed9ec37ea183ee1c23984c014244f8b` |
| `objects/logger.json` | `3fed6372b2b737d1e2bcecbe6de3e1fffc809bd1f11f721d5819c880281e0597` |
| `objects/metadata.json` | `84e6216890acb328f2eed4bf2872ca777a41dc2927ea2f6dfb59fb24b3c61921` |
| `objects/network_endpoint.json` | `34813369c744b2dd9f98e46473ce70e5433c75bdb7224a32a83458831447e04a` |
| `objects/network_interface.json` | `cf5bee6ad3b8d326126c03eb79f4a208008da2506150c488c25aa0d7b7de71d2` |
| `objects/network_proxy.json` | `0a75b121c7158e5693261b1c61b3ace902d2b79d29004d8e018645cf93dfd08e` |
| `objects/object.json` | `4f7af225e3d3b280f387cab142759230266eb4b9d5b8e771747eecce72fc6329` |
| `objects/observable.json` | `ddc596bee75ac65fc4ed7bd5908f02d39790aef7ffd6984bddfcd678d608ab47` |
| `objects/organization.json` | `1433edee463948772952c84811e3f756e2389d23d5a11fdd5b189678f37327eb` |
| `objects/os.json` | `2ab58aec573ede9fcd3e3b21ab9eb6902f2277f28ba6936eaa4a200f5d087f4f` |
| `objects/peripheral_device.json` | `2713eba2e8754a5f8a53edbf28b0cd21d5985d9da19aacf9d568d141c976fdd0` |
| `objects/policy.json` | `83394f2cc0f40b53d418b1575fe9f667bcd161c0aaf362093fd0f632a7183a18` |
| `objects/port_info.json` | `1975a438e1adf198337fdcf61d666c6699b50c7c03d161dd545b6d684db5912d` |
| `objects/product.json` | `d98a4216de4378ea992dc5fa86b8dd28accddba6a1c7ef8e04362cbdca5d1d2a` |
| `objects/programmatic_credential.json` | `b82424676d2719f6b12975969df242b6ebfe3b6ce4be0fed1d4b6354595e3f98` |
| `objects/query_info.json` | `69d12e00535c16ab77b2d57633edf4dde8fb0f627f67ac816c3b958bac43c295` |
| `objects/reporter.json` | `c8d5e06696e5bf3b892238ec26ee411be35721c2abcb72068d5d4d162c763507` |
| `objects/reputation.json` | `6e273aad1526254e679a4a75102184e2afe8e840f162ec063a886a8b9b6954f4` |
| `objects/san.json` | `6c04818d2a268d381d1c87eeaba96314f9dca2b5dedfcf8919d1c371c9d115e1` |
| `objects/timespan.json` | `69ef23b42a4381b5f1374fc322f11bbd434dfb1ed23cbcdd52e62d8760fa77fd` |
| `objects/transformation_info.json` | `b8c5250161e6579b7d51be5408eba926e0e09ba74a61259f33fd6af1fd626eb8` |
| `objects/url.json` | `6ca421a92fac5404c4db363c1cf67627229a726a326457158b1f1be5eab45727` |
| `objects/user.json` | `2e157a5cecca36b960c08ab576ea89a3bc5874efe66fd4f38801e81c7e670f34` |
| `profiles/cloud.json` | `c1b1c20c26e9070d4453c106923fdbc28f4626e0ab309ac4f904638ab13aa80a` |
| `profiles/container.json` | `385e13ea4e311a7de8c9d0c24d6fe3a0c00ae31e89e1bf21b04519168554c803` |
| `profiles/data_classification.json` | `2e7e09f7c5530a2c21cc529b36322e84e49cdb50779a0558ac15146f19854dff` |
| `profiles/datetime.json` | `64855006242487ae4be21e6dec20bbe21b4d0c700744b7b4bf574aca8d626096` |
| `profiles/host.json` | `52266671b749e6f36f1683aead85af78f9626b5e0aaaac7137ca0a8cc2e79f70` |
| `profiles/osint.json` | `bf9db659caf618e6ab9f467be0e26cac162cd15874b465de6eb348769ec5c03a` |
| `profiles/record_integrity.json` | `c6f1159a32f806ff21995c82cce28032fb2a80d23559d926722d587719cbbcb0` |
| `profiles/security_control.json` | `218e6c2fec3e436f8f7ebbcb9c5e241a7d3e36ce987b961c1fc1226dfa36d0cd` |

## License

The repository's `LICENSE` (SHA-256 `0cec06e0e55fbc3dc5cee4fca9b607f66cb8f4e4dbcf3b3c013594dd156732e9`) is the Apache License, Version 2.0; it opens:

> Apache License
> Version 2.0, January 2004
> http://www.apache.org/licenses/

Its `NOTICE` (SHA-256 `990c6fa8d244c2334708b526d923cee8b4853a26fdd2c4f310e39d7c51fc4347`), which the license asks to be carried with derivative works, in full:

> Open Cybersecurity Schema Framework
>
> Copyright © OCSF a Series of LF Projects, LLC
> For web site terms of use, trademark policy and other project policies please see https://lfprojects.org.
>
> This project includes the ICD Schema developed by Symantec, a division of Broadcom.
>
> Licensed under the Apache 2 license.
> Refer to the Apache 2 license in the file LICENSE.

The pack restates the class's structure (attribute names, types, nesting) with keys of
this project's naming. It takes no description, caption or enum text of the schema. It
is not endorsed by the OCSF project.
