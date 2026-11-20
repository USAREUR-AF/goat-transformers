# Provenance of the ocsf-compliance-finding pack

`tools/gen/ocsf2pack.py` reads the files below, resolves the class `compliance_finding` into a JSON
Schema of structure only and passes it to `tools/gen/jsonschema2pack.py`. The files are
not kept in this repository. Read on 2026-11-20.

| | |
|---|---|
| Document | Open Cybersecurity Schema Framework (OCSF) 1.9.0, event class `compliance_finding` |
| Publisher | OCSF, a Series of LF Projects, LLC |
| Repository | https://github.com/ocsf/ocsf-schema at tag `1.9.0`, commit `856d462bd20dc46cc1ffed2dfffe3b91ef0fbeba` |

| File | SHA-256 |
|---|---|
| `LICENSE` | `0cec06e0e55fbc3dc5cee4fca9b607f66cb8f4e4dbcf3b3c013594dd156732e9` |
| `NOTICE` | `990c6fa8d244c2334708b526d923cee8b4853a26fdd2c4f310e39d7c51fc4347` |
| `categories.json` | `4ee3a5f8906c4bc49014e4da28a8bb9666cced4af944e3fab85777381bfb70cc` |
| `dictionary.json` | `d05f472d58802524679a03ad77ae1ac6b9eb2135013931bad15926da65e8d42d` |
| `events/base_event.json` | `53782cf02a503d7c5559fa9bedb7d60d742b0fa68c46aa958ab9481cd8a53095` |
| `events/findings/compliance_finding.json` | `241256c1d116b9b11eeeb51d702081c60d33a13c9bf06fe933bd08f9905ca02e` |
| `events/findings/finding.json` | `4b3a8ac6476dbbe0a6b5eb8cec71eb5110b840505d50dc1c2a3bf275597ade66` |
| `objects/_entity.json` | `3bf4fe72d690fadbf3611784776f3a6befcefe3eb38f7f0cf7c3f33666933eeb` |
| `objects/_resource.json` | `6d619f19f3e84c8567c2feac06471cee2c0e88a98f846109e6c42df9c6b3cd63` |
| `objects/account.json` | `59fcb6ade67c7d2843e2b4c8bc75559212fa35142babdf1c2845a0448d39585c` |
| `objects/actor.json` | `22b4a9e218a9ababbe49b1634e164d0369cd880de5aa174893f5b83430509028` |
| `objects/agent.json` | `788fc14c89cd158aad44449ba120743f836bc014a06be38f2a9d4f94bab49e85` |
| `objects/ai_agent.json` | `2e98f43848090d32d102397c4751cffd095e1efa58138f96f0f83ab0071fdc65` |
| `objects/ai_model.json` | `35cb0a4f734b2111357fdcf0c18b70dac22978be9e225f7f74a92b97e38140a5` |
| `objects/analytic.json` | `0cf80acf55851c087281a4f13c273eba2f95ad0700c352734696e2e2b92bf45a` |
| `objects/api.json` | `0619ad7f407ee908fe2d04b979f7f033c42ebaf72eaf4bcdd53764ad5c99edf4` |
| `objects/application.json` | `98850869e242082afa739e03d46267a2bdea65fcad9bab699f2ef0bac2e558f7` |
| `objects/assessment.json` | `2ed22886f131a58cb2e1a67317cc3aa124106c4bbc0558e73d1473ca78d5858d` |
| `objects/attack.json` | `0112fe3d6f3580917721ad9b3e8f2e31f784b53ad3d4905c2ccd0a1c4f2c0983` |
| `objects/auth_factor.json` | `2f0d055621f4204767acca112d5bf3820576afbf545d69c817dc9c060247bf27` |
| `objects/authorization.json` | `72417d96a6b1064e87fae7638b1ece8324dae86d514ed0bb7c229f0aa3c4261a` |
| `objects/autonomous_system.json` | `f580b27be5a9545d2e3ef96b2a5e386b746bacd8313e37199cd74984421af152` |
| `objects/certificate.json` | `685f84d863af83762270d9ddaf97f343d9607d05e27aae96b37e34057744e432` |
| `objects/check.json` | `f952dbad7cf950d687e37d3d87ec6a3ec9a596763a2392851a1b737bd2597d06` |
| `objects/cis_control.json` | `e252f49b88da4b0522836991339c4b64f90be817d7eb03a41b82fe6ec12e95b1` |
| `objects/compliance.json` | `073b15607bbe2baac54dcc66aa186ec87096f2350e5cbe2dfdff86d2d540d29e` |
| `objects/container.json` | `a07308ce54d1714217cf0865f02a332b0408f5bf070cd504e78e5520d35ec6f9` |
| `objects/cpu_info.json` | `1561b7696ca20c1a8be7ca2b8f427a1f023ef0f79ac6ce3a954cb5754a6a8bcc` |
| `objects/d3f_tactic.json` | `18643200bcdc32c5dbbfbfb44449410c9dfe1a90722a65003c5cb36f77301397` |
| `objects/d3f_technique.json` | `06269d5df15e3d24ca1e28cf3244377f1e1ff4a56da0be66c64a95d06bf89fac` |
| `objects/d3fend.json` | `8fcda52e0762c64af5c9ba03ca45012a027e494b1355a0e4f21d621cd7ced428` |
| `objects/database.json` | `57fb2f53f6c99adb30a0be1bf8fa3abd53af36bf7890c4dc8e1d9b00bf3e044e` |
| `objects/databucket.json` | `35a3b314668070a21f29277bb20c792581d4e42b94a093bd81e23f56a0c7f6f4` |
| `objects/device.json` | `a85202d96ebfb8a1d51ea449d865a23e8387f5c648cfe7233c00d83723a8d64d` |
| `objects/device_hw_info.json` | `b02b2c809fa33001b3c57d9818be834757cccd241e19d449d5da9230ca3acdf4` |
| `objects/digital_signature.json` | `109dbb7386198fe65fe478cf09f588859b98c39f38ae55e60731ad83cbbf2424` |
| `objects/display.json` | `76ada52a0517f4f3002291bf6703ac7daf29662d7e7f9acddeccd593dd46b819` |
| `objects/dns_query.json` | `31ad9413337f0676593dd8f0618089a5deba7ea159ce282b3e2810dc5957b7c4` |
| `objects/download_info.json` | `243b5f162f6b2fd92f6adafbac864cd26cd4a5dd8ce8ae2ba83c29a6959d52ba` |
| `objects/edge.json` | `6a27f1aded6e93c822983b78fc9a3feb9c092ef36b455859ba4d39740ea8f304` |
| `objects/email.json` | `1fc49476979f3f26b1689900966573e207f647f9c486126cb09d934bdc48d859` |
| `objects/encryption_details.json` | `5c62f3de6558e670f8e14d91aaaac16ea5b7bb7748f5593890c44992f16d1b8f` |
| `objects/endpoint.json` | `71a0c6e4a3c265776aa8626b2b98e5a8f7b51c778279ff87c03f1f221c8b69df` |
| `objects/enrichment.json` | `c218e3e54593f88bdd03c39f07432d1672bac9be7bf96f5f39fea3dd05148cf6` |
| `objects/environment_variable.json` | `07bfa20a6f5a60578a08795dadcc309331801bb9085054c502db45dfb7f822b3` |
| `objects/evidences.json` | `46f16771822571be84a499636cbdef1a77cccbbebea6e959cda13e4f62b59b94` |
| `objects/extension.json` | `e1b782e36c922ea9827e6e751540eaca2a3ccb9e8599cc14f81d1b192af5f1e1` |
| `objects/feature.json` | `937440e5ba963289320f3c3e0499f2e9aaab8ce9cabaf34ed7b7c09680c97142` |
| `objects/file.json` | `d1d9dee932b73798858b9eabe6120a89b9c2c18b1eaedd0cdc51debfb1ebd753` |
| `objects/finding_info.json` | `21f6bf0213abb502a3d9fd7ef3b42f257727eec520bb7ee30d39f57f589450ea` |
| `objects/fingerprint.json` | `b44efe37e5c06da4ad1b99cd10fe9a687f739972cc148ce0528e9ddc234b64d9` |
| `objects/gpu_info.json` | `bcbe58f66b28de483766559cd652e2fd013d546976374c5baa67eed57de5ef99` |
| `objects/graph.json` | `d787f81a5c24c2edcf88c58e4bbaa3c50cab6f0e27cb9ad59adb9f0bd502de0a` |
| `objects/group.json` | `ec45c3ff664c9e62d543a8f5cb4610d8365486a979f9199615826d7025eca669` |
| `objects/http_header.json` | `a98bd6e63425ec8e1e602f04bade724b791a0be205ab846d8cb82b155db8d01e` |
| `objects/http_request.json` | `1fec9207cff14d7e8cb877947e5ff71e0cc307727960e19427ebfab6a425c113` |
| `objects/http_response.json` | `a3735ebe6ee7a14b71e0a64011a3c3398f4f7b09b8d5850fe5adc954039b1384` |
| `objects/iam_role.json` | `aab1b6bdf3b13360265f8a07098e8c644b358db0dacc27937633f8a6eb9807d9` |
| `objects/idp.json` | `f5267f2f7e6fc5a1d3293b419d1958cba13a3b293011626fe79f6a7060a8c171` |
| `objects/image.json` | `6e2c9b9bfd2b691d574fe7e90b716742301401e4c46b5daf06444eee7fe458a0` |
| `objects/ja4_fingerprint.json` | `9d8f24bcd449b9b926476e067784e3a0cebe8a94420b476029866af2dba7cabd` |
| `objects/job.json` | `9a6c299e3e98656ac863f49ea4a0822b7b5f1acb19bc2ea16ea2af0d9290c31a` |
| `objects/job_action.json` | `865a0a93c714778d7b8347efa718e3302ce528f11927fbf32c8218c7da77974f` |
| `objects/job_trigger.json` | `6dcc2898747211d711019624ff94d3aeacfb073bd8c0ec97a309cd47cfe0c2e3` |
| `objects/kb_article.json` | `12cee0979881ed4921e0d7ad7d1f68882395232dc1347abf260b774d5e4f2dc0` |
| `objects/key_value_object.json` | `02f377b4ede5ee867dbb59823187b79e0b40b959dbc77570aaf6a764d1259269` |
| `objects/keyboard_info.json` | `e7ee36c0ebbfb06cf7a8b238507445100b1409c8e2b0287a6c8d9bb34136de82` |
| `objects/kill_chain_phase.json` | `bbdf88272166a4b3fd1145556e7c00c2599ff42f26c3b73cc78d28d604a7efb3` |
| `objects/ldap_person.json` | `8f071391281b51f3df174ecd77ec62fc3e2ed1977c6aa0d4f7f34eb08946c310` |
| `objects/location.json` | `43c89155e8bfb7f996a1e681321abaa1fed9ec37ea183ee1c23984c014244f8b` |
| `objects/logger.json` | `3fed6372b2b737d1e2bcecbe6de3e1fffc809bd1f11f721d5819c880281e0597` |
| `objects/long_string.json` | `7884e0a71333a0283a0d0e0918a2442426f60051246e2de5151eaae47f8932cd` |
| `objects/metadata.json` | `84e6216890acb328f2eed4bf2872ca777a41dc2927ea2f6dfb59fb24b3c61921` |
| `objects/mitigation.json` | `69240a6be670b4a44cc4da5bbac156f568ddec0b91e84fcf6323aa7669f07254` |
| `objects/network_connection_info.json` | `1781cbafd387eb58aa3282aa0faccfa1ac46edf9968d6602901794446608a961` |
| `objects/network_endpoint.json` | `34813369c744b2dd9f98e46473ce70e5433c75bdb7224a32a83458831447e04a` |
| `objects/network_interface.json` | `cf5bee6ad3b8d326126c03eb79f4a208008da2506150c488c25aa0d7b7de71d2` |
| `objects/network_proxy.json` | `0a75b121c7158e5693261b1c61b3ace902d2b79d29004d8e018645cf93dfd08e` |
| `objects/node.json` | `9f6c1335702d0b0e6ff42c25e98282d3da10e33d9a295686d672663f1ee5c6a6` |
| `objects/note.json` | `4d253147fe47e89098ec0df2514b3210a8521350b5d6f16e24048888077c7c56` |
| `objects/object.json` | `4f7af225e3d3b280f387cab142759230266eb4b9d5b8e771747eecce72fc6329` |
| `objects/observable.json` | `ddc596bee75ac65fc4ed7bd5908f02d39790aef7ffd6984bddfcd678d608ab47` |
| `objects/organization.json` | `1433edee463948772952c84811e3f756e2389d23d5a11fdd5b189678f37327eb` |
| `objects/os.json` | `2ab58aec573ede9fcd3e3b21ab9eb6902f2277f28ba6936eaa4a200f5d087f4f` |
| `objects/package.json` | `4be3b2d8e1cad55ca757463050ca540710ead3a95abe83a3fe6ad8a973c661e7` |
| `objects/peripheral_device.json` | `2713eba2e8754a5f8a53edbf28b0cd21d5985d9da19aacf9d568d141c976fdd0` |
| `objects/policy.json` | `83394f2cc0f40b53d418b1575fe9f667bcd161c0aaf362093fd0f632a7183a18` |
| `objects/port_info.json` | `1975a438e1adf198337fdcf61d666c6699b50c7c03d161dd545b6d684db5912d` |
| `objects/process.json` | `89c9d17be56706b1eec9e52f180b45338feb0c580e3aba51564c2a9144d75148` |
| `objects/process_entity.json` | `6b28a51eab6b552e0af40c5df5c1e5a750e6920387def7603a267544d92cd1c7` |
| `objects/product.json` | `d98a4216de4378ea992dc5fa86b8dd28accddba6a1c7ef8e04362cbdca5d1d2a` |
| `objects/programmatic_credential.json` | `b82424676d2719f6b12975969df242b6ebfe3b6ce4be0fed1d4b6354595e3f98` |
| `objects/related_event.json` | `a3775041ade2942ec97e85228485b298cf45cc0e4dd0e8fd63c65b4df356dc64` |
| `objects/remediation.json` | `2a719936ad219ab9ce053b824f41c9d0d0fd1fbeca2578fc80df919039813c7e` |
| `objects/reporter.json` | `c8d5e06696e5bf3b892238ec26ee411be35721c2abcb72068d5d4d162c763507` |
| `objects/reputation.json` | `6e273aad1526254e679a4a75102184e2afe8e840f162ec063a886a8b9b6954f4` |
| `objects/request.json` | `fd5d8f00611dbd4cb5ce8bbfb6c8b92e834aaaaaa4ee47ad0160b44a53698767` |
| `objects/resource_details.json` | `b1a229196e69d003e6a21eeb2b2bfd3fc7ac41ac5cc70b40afc083876970b575` |
| `objects/response.json` | `6390a17515a3977b5c41f55f2b9cfc1b5349d94cefa7d83f597b5fe80239dade` |
| `objects/san.json` | `6c04818d2a268d381d1c87eeaba96314f9dca2b5dedfcf8919d1c371c9d115e1` |
| `objects/sbom.json` | `5edb29f09b93c15377104faa2f985cb8664bee4794caf2219075dc8b98eb1551` |
| `objects/scim.json` | `35c53a410d58fdb042c0af1e0665f61680769907efa2dd90673995d88ebcc0bd` |
| `objects/script.json` | `1642416e0b333796e30f1d854eb378d7ef86658dadc6265c092835c2b21369ab` |
| `objects/sensor_info.json` | `6dc97ee9ab62f1d825997b8039c8762d61f73866f7139c3691cf876be247e182` |
| `objects/service.json` | `57b7c7e312e4b7cdd166c6083a362393ab6f36b7d1251bf6e3251d96a092864d` |
| `objects/session.json` | `d517cb8417522d95e4435bcd27ebc55ef9aa082b9abe5ec1ad79ac3b3947a010` |
| `objects/software_component.json` | `15ec586360754e3361efe55dcd993250f28f1ca156871b5eb3e40f0fc0e7bb8e` |
| `objects/sso.json` | `36c8995ae05f6d84db1690e04966b3a7f5cf2ace4c51e6510cc69e2bf9794672` |
| `objects/sub_technique.json` | `7a42d95f3cceed9c62e0e18f946c9505ee907c33adee9777e9498c3ecc70e52e` |
| `objects/tactic.json` | `9ab49a13e4c534e61c48964767328a78c3456e122eb46787ef4b7e08567a4966` |
| `objects/technique.json` | `7680aff7b0f1a2cbe3d9a68f5ac1bd77fd1ad2ba00009d34a869d2b76b47fc00` |
| `objects/timespan.json` | `69ef23b42a4381b5f1374fc322f11bbd434dfb1ed23cbcdd52e62d8760fa77fd` |
| `objects/tls.json` | `9ab2f4b6030bb84eb0f1e3643a08a75a0fba3220a0d4c5decaf64d639eb09b97` |
| `objects/tls_extension.json` | `187b1138e752066244a9bad7f5fe4afe36f70726c3c1080959ceb3932e8971e2` |
| `objects/token.json` | `616691caf68f03c80cdbfdcb046d16ea9071ac15debd677dba5467539b87ce34` |
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
