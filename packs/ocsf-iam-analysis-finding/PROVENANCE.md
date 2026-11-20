# Provenance of the ocsf-iam-analysis-finding pack

`tools/gen/ocsf2pack.py` reads the files below, resolves the class `iam_analysis_finding` into a JSON
Schema of structure only and passes it to `tools/gen/jsonschema2pack.py`. The files are
not kept in this repository. Read on 2026-11-20.

| | |
|---|---|
| Document | Open Cybersecurity Schema Framework (OCSF) 1.9.0, event class `iam_analysis_finding` |
| Publisher | OCSF, a Series of LF Projects, LLC |
| Repository | https://github.com/ocsf/ocsf-schema at tag `1.9.0`, commit `856d462bd20dc46cc1ffed2dfffe3b91ef0fbeba` |

| File | SHA-256 |
|---|---|
| `LICENSE` | `0cec06e0e55fbc3dc5cee4fca9b607f66cb8f4e4dbcf3b3c013594dd156732e9` |
| `NOTICE` | `990c6fa8d244c2334708b526d923cee8b4853a26fdd2c4f310e39d7c51fc4347` |
| `categories.json` | `4ee3a5f8906c4bc49014e4da28a8bb9666cced4af944e3fab85777381bfb70cc` |
| `dictionary.json` | `d05f472d58802524679a03ad77ae1ac6b9eb2135013931bad15926da65e8d42d` |
| `events/base_event.json` | `53782cf02a503d7c5559fa9bedb7d60d742b0fa68c46aa958ab9481cd8a53095` |
| `events/findings/finding.json` | `4b3a8ac6476dbbe0a6b5eb8cec71eb5110b840505d50dc1c2a3bf275597ade66` |
| `events/findings/iam_analysis_finding.json` | `0df8bb01b82acf8a200a0b7f01ec3212010f3affabb19c1825f65c8a29606e49` |
| `objects/_entity.json` | `3bf4fe72d690fadbf3611784776f3a6befcefe3eb38f7f0cf7c3f33666933eeb` |
| `objects/_resource.json` | `6d619f19f3e84c8567c2feac06471cee2c0e88a98f846109e6c42df9c6b3cd63` |
| `objects/access_analysis_result.json` | `00e5ac6d8e74ab41d92f8794a3061b93b42672564fa043ff6602ca9388d3914b` |
| `objects/account.json` | `59fcb6ade67c7d2843e2b4c8bc75559212fa35142babdf1c2845a0448d39585c` |
| `objects/additional_restriction.json` | `5149927ad51c476694847f48a85659c7803bab59e8404b0741a062b1cbb22437` |
| `objects/agent.json` | `788fc14c89cd158aad44449ba120743f836bc014a06be38f2a9d4f94bab49e85` |
| `objects/analytic.json` | `0cf80acf55851c087281a4f13c273eba2f95ad0700c352734696e2e2b92bf45a` |
| `objects/application.json` | `98850869e242082afa739e03d46267a2bdea65fcad9bab699f2ef0bac2e558f7` |
| `objects/attack.json` | `0112fe3d6f3580917721ad9b3e8f2e31f784b53ad3d4905c2ccd0a1c4f2c0983` |
| `objects/cis_control.json` | `e252f49b88da4b0522836991339c4b64f90be817d7eb03a41b82fe6ec12e95b1` |
| `objects/cpu_info.json` | `1561b7696ca20c1a8be7ca2b8f427a1f023ef0f79ac6ce3a954cb5754a6a8bcc` |
| `objects/d3f_tactic.json` | `18643200bcdc32c5dbbfbfb44449410c9dfe1a90722a65003c5cb36f77301397` |
| `objects/d3f_technique.json` | `06269d5df15e3d24ca1e28cf3244377f1e1ff4a56da0be66c64a95d06bf89fac` |
| `objects/d3fend.json` | `8fcda52e0762c64af5c9ba03ca45012a027e494b1355a0e4f21d621cd7ced428` |
| `objects/device.json` | `a85202d96ebfb8a1d51ea449d865a23e8387f5c648cfe7233c00d83723a8d64d` |
| `objects/device_hw_info.json` | `b02b2c809fa33001b3c57d9818be834757cccd241e19d449d5da9230ca3acdf4` |
| `objects/display.json` | `76ada52a0517f4f3002291bf6703ac7daf29662d7e7f9acddeccd593dd46b819` |
| `objects/edge.json` | `6a27f1aded6e93c822983b78fc9a3feb9c092ef36b455859ba4d39740ea8f304` |
| `objects/endpoint.json` | `71a0c6e4a3c265776aa8626b2b98e5a8f7b51c778279ff87c03f1f221c8b69df` |
| `objects/enrichment.json` | `c218e3e54593f88bdd03c39f07432d1672bac9be7bf96f5f39fea3dd05148cf6` |
| `objects/extension.json` | `e1b782e36c922ea9827e6e751540eaca2a3ccb9e8599cc14f81d1b192af5f1e1` |
| `objects/feature.json` | `937440e5ba963289320f3c3e0499f2e9aaab8ce9cabaf34ed7b7c09680c97142` |
| `objects/finding_info.json` | `21f6bf0213abb502a3d9fd7ef3b42f257727eec520bb7ee30d39f57f589450ea` |
| `objects/fingerprint.json` | `b44efe37e5c06da4ad1b99cd10fe9a687f739972cc148ce0528e9ddc234b64d9` |
| `objects/gpu_info.json` | `bcbe58f66b28de483766559cd652e2fd013d546976374c5baa67eed57de5ef99` |
| `objects/graph.json` | `d787f81a5c24c2edcf88c58e4bbaa3c50cab6f0e27cb9ad59adb9f0bd502de0a` |
| `objects/group.json` | `ec45c3ff664c9e62d543a8f5cb4610d8365486a979f9199615826d7025eca669` |
| `objects/identity_activity_metrics.json` | `09d337d000b6ae0597bdaf7c043f92623dd226a2c15f3fe9f2e268b7f7b1d3c2` |
| `objects/image.json` | `6e2c9b9bfd2b691d574fe7e90b716742301401e4c46b5daf06444eee7fe458a0` |
| `objects/kb_article.json` | `12cee0979881ed4921e0d7ad7d1f68882395232dc1347abf260b774d5e4f2dc0` |
| `objects/key_value_object.json` | `02f377b4ede5ee867dbb59823187b79e0b40b959dbc77570aaf6a764d1259269` |
| `objects/keyboard_info.json` | `e7ee36c0ebbfb06cf7a8b238507445100b1409c8e2b0287a6c8d9bb34136de82` |
| `objects/kill_chain_phase.json` | `bbdf88272166a4b3fd1145556e7c00c2599ff42f26c3b73cc78d28d604a7efb3` |
| `objects/ldap_person.json` | `8f071391281b51f3df174ecd77ec62fc3e2ed1977c6aa0d4f7f34eb08946c310` |
| `objects/location.json` | `43c89155e8bfb7f996a1e681321abaa1fed9ec37ea183ee1c23984c014244f8b` |
| `objects/logger.json` | `3fed6372b2b737d1e2bcecbe6de3e1fffc809bd1f11f721d5819c880281e0597` |
| `objects/metadata.json` | `84e6216890acb328f2eed4bf2872ca777a41dc2927ea2f6dfb59fb24b3c61921` |
| `objects/mitigation.json` | `69240a6be670b4a44cc4da5bbac156f568ddec0b91e84fcf6323aa7669f07254` |
| `objects/network_interface.json` | `cf5bee6ad3b8d326126c03eb79f4a208008da2506150c488c25aa0d7b7de71d2` |
| `objects/node.json` | `9f6c1335702d0b0e6ff42c25e98282d3da10e33d9a295686d672663f1ee5c6a6` |
| `objects/note.json` | `4d253147fe47e89098ec0df2514b3210a8521350b5d6f16e24048888077c7c56` |
| `objects/object.json` | `4f7af225e3d3b280f387cab142759230266eb4b9d5b8e771747eecce72fc6329` |
| `objects/observable.json` | `ddc596bee75ac65fc4ed7bd5908f02d39790aef7ffd6984bddfcd678d608ab47` |
| `objects/organization.json` | `1433edee463948772952c84811e3f756e2389d23d5a11fdd5b189678f37327eb` |
| `objects/os.json` | `2ab58aec573ede9fcd3e3b21ab9eb6902f2277f28ba6936eaa4a200f5d087f4f` |
| `objects/package.json` | `4be3b2d8e1cad55ca757463050ca540710ead3a95abe83a3fe6ad8a973c661e7` |
| `objects/peripheral_device.json` | `2713eba2e8754a5f8a53edbf28b0cd21d5985d9da19aacf9d568d141c976fdd0` |
| `objects/permission_analysis_result.json` | `739d633a68525636a5bf0e10b6893dc13727ff4fc074dcfd2a025850342e81ab` |
| `objects/policy.json` | `83394f2cc0f40b53d418b1575fe9f667bcd161c0aaf362093fd0f632a7183a18` |
| `objects/port_info.json` | `1975a438e1adf198337fdcf61d666c6699b50c7c03d161dd545b6d684db5912d` |
| `objects/privilege_attack_info.json` | `573bef8904e2caf102328b71fd127c7dff93fbbce7d3241fc30479940877c257` |
| `objects/privilege_info.json` | `0cf9466f607eb8c5689cd827fe0f4ae3946dbac01e4215945dccb148133c1c41` |
| `objects/product.json` | `d98a4216de4378ea992dc5fa86b8dd28accddba6a1c7ef8e04362cbdca5d1d2a` |
| `objects/programmatic_credential.json` | `b82424676d2719f6b12975969df242b6ebfe3b6ce4be0fed1d4b6354595e3f98` |
| `objects/related_event.json` | `a3775041ade2942ec97e85228485b298cf45cc0e4dd0e8fd63c65b4df356dc64` |
| `objects/remediation.json` | `2a719936ad219ab9ce053b824f41c9d0d0fd1fbeca2578fc80df919039813c7e` |
| `objects/reporter.json` | `c8d5e06696e5bf3b892238ec26ee411be35721c2abcb72068d5d4d162c763507` |
| `objects/reputation.json` | `6e273aad1526254e679a4a75102184e2afe8e840f162ec063a886a8b9b6954f4` |
| `objects/resource_details.json` | `b1a229196e69d003e6a21eeb2b2bfd3fc7ac41ac5cc70b40afc083876970b575` |
| `objects/sbom.json` | `5edb29f09b93c15377104faa2f985cb8664bee4794caf2219075dc8b98eb1551` |
| `objects/sensor_info.json` | `6dc97ee9ab62f1d825997b8039c8762d61f73866f7139c3691cf876be247e182` |
| `objects/service_privilege_analysis.json` | `7a82ebc38550c2890f2c1e278a82e9d258be2d7d3d685829d2c34f1415e642d7` |
| `objects/software_component.json` | `15ec586360754e3361efe55dcd993250f28f1ca156871b5eb3e40f0fc0e7bb8e` |
| `objects/sub_technique.json` | `7a42d95f3cceed9c62e0e18f946c9505ee907c33adee9777e9498c3ecc70e52e` |
| `objects/tactic.json` | `9ab49a13e4c534e61c48964767328a78c3456e122eb46787ef4b7e08567a4966` |
| `objects/technique.json` | `7680aff7b0f1a2cbe3d9a68f5ac1bd77fd1ad2ba00009d34a869d2b76b47fc00` |
| `objects/timespan.json` | `69ef23b42a4381b5f1374fc322f11bbd434dfb1ed23cbcdd52e62d8760fa77fd` |
| `objects/trait.json` | `1c8cf20dece411249c3ec8ec127742c91a4105ea98ad6eff9b31b11f48bf920f` |
| `objects/transformation_info.json` | `b8c5250161e6579b7d51be5408eba926e0e09ba74a61259f33fd6af1fd626eb8` |
| `objects/url.json` | `6ca421a92fac5404c4db363c1cf67627229a726a326457158b1f1be5eab45727` |
| `objects/user.json` | `2e157a5cecca36b960c08ab576ea89a3bc5874efe66fd4f38801e81c7e670f34` |
| `objects/vendor_attributes.json` | `d3dce70af4d3605f77c3ff62148c7ad844ccfd50c5564dc81838e7152a81b553` |
| `profiles/cloud.json` | `c1b1c20c26e9070d4453c106923fdbc28f4626e0ab309ac4f904638ab13aa80a` |
| `profiles/container.json` | `385e13ea4e311a7de8c9d0c24d6fe3a0c00ae31e89e1bf21b04519168554c803` |
| `profiles/data_classification.json` | `2e7e09f7c5530a2c21cc529b36322e84e49cdb50779a0558ac15146f19854dff` |
| `profiles/datetime.json` | `64855006242487ae4be21e6dec20bbe21b4d0c700744b7b4bf574aca8d626096` |
| `profiles/host.json` | `52266671b749e6f36f1683aead85af78f9626b5e0aaaac7137ca0a8cc2e79f70` |
| `profiles/incident.json` | `cecda7d50b41b73811c36937565b2bc1b3de67e2038720c306b2781da6000b6c` |
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
