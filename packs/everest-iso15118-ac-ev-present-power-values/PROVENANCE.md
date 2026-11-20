SPDX licence: Apache-2.0

# Provenance of the everest-iso15118-ac-ev-present-power-values pack

`tools/gen/everest2pack.py` reads the types files below, turns their references into
references between JSON documents and passes `AcEvPresentPowerValues` of `types/iso15118.yaml` to
`tools/gen/jsonschema2pack.py`; from the interface files it reads only which types they
publish as vars. The files are not kept in this repository. Read on 2026-11-20.

| | |
|---|---|
| Document | EVerest everest-core 2026.02.2, type `AcEvPresentPowerValues` of `types/iso15118.yaml` |
| Publisher | EVerest project (LF Energy) |
| Repository | https://github.com/EVerest/everest-core at tag `2026.02.2`, commit `45dba2c049223d05beb7611c75d59f6639c46ee0` |
| Download | `https://raw.githubusercontent.com/EVerest/everest-core/45dba2c049223d05beb7611c75d59f6639c46ee0/types/iso15118.yaml` |

| File | SHA-256 |
|---|---|
| `types/authorization.yaml` | `1731d780f2d127afc882fcfed268066ac4763f77fd1f630f5141f9ae22b18700` |
| `types/board_support_common.yaml` | `ea432a42c12d25548331666fa399e6fb8477c332795ad764757f64396620966f` |
| `types/charger_information.yaml` | `a1965c83245f012b21e5b96b1b0ffdb9e891c90ff9bf05b376acb615add4e6c0` |
| `types/dc_external_derate.yaml` | `d5a01bd02cbe22d4e05da39dfc534e00287939e0d8c1faa90122110a89ce767c` |
| `types/display_message.yaml` | `943864fe458ce04da31fb7001dce9a3529fa2dc11d9a415f95814712dd4a5d18` |
| `types/energy.yaml` | `82b8d902618eb3927a7e34e8a641cb2a69db93e404c2b61320c62eab3c290d91` |
| `types/energy_price_information.yaml` | `b2284d75a2fc695150cb72e7262b4efa11a05b11b1cca382451643a9bb2be624` |
| `types/error_history.yaml` | `6c49548f8020e807ca17f710d6cb69e53399b9da4ed2aaa5247dd695f42c3b50` |
| `types/ev_board_support.yaml` | `34faaae360f86fa2977c4f20c0f350cb86f7669513d972dc9558c95a62c652a1` |
| `types/evse_board_support.yaml` | `ab1fae1c0a60edbc6ab61fc57f938e31b3d9e54300af528dd80eee5312e3979d` |
| `types/evse_manager.yaml` | `5259d1e4f273a84540c9cb6981afde9d58024a32bee2bb282c34f01e6967e753` |
| `types/evse_security.yaml` | `a80c92d4663bda33412bd32788ba446bc0eafeebcddad706db38e1f988bd133b` |
| `types/iso15118.yaml` | `955e056aaf1ef5bfeeed77a0e5febd58f2493352b6645a1788f0b8afe96f263c` |
| `types/iso15118_vas.yaml` | `291e8329f8adb12c9653057f16a723d73fba1ebfe8a147985b4aed93072c5c5c` |
| `types/isolation_monitor.yaml` | `45d98b5072fa5d02a476860fe7d45a7b02f8a05eb6be94327f32dbe159d4ec40` |
| `types/money.yaml` | `4a7001c50216fcf96caac4fe16db17e23ce5149d000be1de4ac1f0135f5bdb0b` |
| `types/ocpp.yaml` | `2181f239b0366de85189dbe6cc210ad6b3ab7b6bdeb9ea8aad20fe4410b93bd7` |
| `types/payment_terminal.yaml` | `e079f22ed6f7bdde5e47eb1daba554c293530dc1788a086ed56ab75407fde2f4` |
| `types/power_supply_DC.yaml` | `852e9b617eedeb5a4d3b512c97b4c5e119502deb80c839f93cfa13f74a6a47d2` |
| `types/powermeter.yaml` | `486450f1d9bfcf010eefed9550c5544cf1fb05b3aba695b1edfc5469a3801846` |
| `types/reservation.yaml` | `44c2df61101574f6824b14a58f493e1e3175bbb325886bfd70955ccb973e77b6` |
| `types/serial_comm_hub_requests.yaml` | `a98f8197754d208bbb16aa22a3b1e169ed65aacae6e7e0c74638c6f0c5858b3c` |
| `types/session_cost.yaml` | `20013fc2f5c875212f9bc57ec3ff7a1a29bae9f1341eb2638e981f2a45a7a0c4` |
| `types/slac.yaml` | `67cef1d0e02e189b64b3e4afb6e5d8e0a152143a19266aefbc313c3f723da330` |
| `types/system.yaml` | `3b37e52da971d823e64bdad94d815a79816930588d3ad0a7d0eb5312cdbaa92f` |
| `types/temperature.yaml` | `4c0af04b3cece98f1309779c69dd61f3895c5cc7e0274a1c4d681155141d2cc4` |
| `types/text_message.yaml` | `f0b61d652646d875b7f32e3ccc77972059a4dc21b6dbfbe6dcc5dddbea498d86` |
| `types/uk_random_delay.yaml` | `45dd729db0bc445175d422fba18fb0a38e5b92202f9e4664a15656ed9987dbd0` |
| `types/units.yaml` | `8c50a45d1ec5e817f97d1e90c7bea050c7df7401c38067568a6f87cef1d2e6e2` |
| `types/units_signed.yaml` | `2cf1cd5c551cd55d7aee99e127efca9f805aa735caaa65a3ebf29d39a0762d18` |
| `interfaces/ISO15118_charger.yaml` | `43f294e80d00e127d3e7f06c83607cc688a5afd550d175d75a60c719375a752c` |
| `interfaces/ISO15118_ev.yaml` | `a6376a3c9ec1401c7785cf7163865a777c1e4241861fe4270d11dddbbe98b2c3` |
| `interfaces/ISO15118_vas.yaml` | `c3212751e51fdf508af9c1d86d968bf7ecaa4bbf81430aa24fdc6dd86c3cba00` |
| `interfaces/ac_rcd.yaml` | `3faf5c199216a09953470a1a63e27e9a7b369a5a2bef538c406f0574ca4de465` |
| `interfaces/auth.yaml` | `835403f7b562ba79d9d9795e4e9279b005af023939294fcb3b6d50afb95fd606` |
| `interfaces/auth_token_provider.yaml` | `a408de2a8330e2e8b148879a2a31c37106d51ae823cb855e33d7bf5c9e44d8ab` |
| `interfaces/auth_token_validator.yaml` | `d4632713b49c9c4e20cf7e8d4d56de256ecff4a1a242897ca272479fd96c326e` |
| `interfaces/bank_session_token_provider.yaml` | `cb24c85b539ef158e0b6a3fdcd509c0c6e354d033d0daee5babd24669cc8a55e` |
| `interfaces/car_simulator.yaml` | `a0e3de7966dfff262d0ae656878261affcba633e1af4b1b1eecaf0b177105716` |
| `interfaces/charger_information.yaml` | `40a79ab5c4622574503b338bbbaec044f2f42dbf1a94cf3f3fa23d8b4b81c678` |
| `interfaces/connector_lock.yaml` | `5c2a746ba04eaf96657f98673927aa88038c209d8b845ad7b248d14e1d930234` |
| `interfaces/dc_external_derate.yaml` | `f58cbe25be6f84c910238c7df9a2ed6199ca9a05ef38684f63ea8e1567f34cc0` |
| `interfaces/debug_json.yaml` | `7c78ec933e10aad49c80b46db22940ff8785ffb394cd07f3b765e728bf073a4f` |
| `interfaces/display_message.yaml` | `c840e9ac1983952d905d1ae7ce4fa179ccc6b7e90d9aeb4c685af1ea95a5b83f` |
| `interfaces/empty.yaml` | `7e21dd4a7c1ea0ab8fed227294a1fb4c4a3fb04ddde59f510e5e6423a9869908` |
| `interfaces/energy.yaml` | `b26b12e00ffb925268b5aa9056267bae499f1e60f975135c25f35bcb0673a65f` |
| `interfaces/energy_manager.yaml` | `a4dff20536f45029ba39b16138b8a422c599dbc14fc7fbffd20265a717b6a264` |
| `interfaces/energy_price_information.yaml` | `bd6c7632c06e471401155f4586563c72f9f2c10d04216bcf35a2e7b914e88650` |
| `interfaces/error_history.yaml` | `2b275797a7990976f5d4ee16c498190a03bc3e754adda04e58f0d34de18549a8` |
| `interfaces/ev_board_support.yaml` | `2c726868fa0378218794908e8797290a9ad56be5c97e2897e9e3bc96ee28d8ea` |
| `interfaces/ev_manager.yaml` | `873cecdc6c97d9a2bebbe26811da471ad5ab6ccbcb280dea9392425e277e41b3` |
| `interfaces/ev_slac.yaml` | `66337f6d746a653e1a5390852f568a095bab856b182f501fc001c89fa25d242a` |
| `interfaces/evse_board_support.yaml` | `38b5d3500edd37eaf07211189ea0c68692825eb869ad30a392bb678e5bd8c210` |
| `interfaces/evse_manager.yaml` | `d28992f21d217a0567aa429ef5ca821e75906361f3a7d29003ffa40057d674d4` |
| `interfaces/evse_security.yaml` | `e75f400204f7843cc39a0785618fa52d0348653a163f4e67a78304b5511a2dcf` |
| `interfaces/example.yaml` | `d3fafbb64ac44ebd39d4842297fb9a9fa22a251b1497c52903ee015cf6847b9e` |
| `interfaces/example_error_framework.yaml` | `4671df51b6824ca8cc780fc967d22918d9b781520d4ad72eeb484d54ddd84484` |
| `interfaces/example_user.yaml` | `9c003a7101c1562e11cb77aa29d7bd1f19cc0f2bed6bcd7050b9d5df38eee750` |
| `interfaces/external_energy_limits.yaml` | `e54e8b2c323073e62e072841a31f615501b22b26d461a421e9f83876b40c9d5b` |
| `interfaces/generic_error.yaml` | `2c42fc5484a06adec5d9565bb7f36bd38146cc15a22f9614fa7b77d7b88991ce` |
| `interfaces/iso15118_extensions.yaml` | `cb1c8b4b241009e8107d56149d7ec26990678de2e39d4e625ed727ebd86f1d2d` |
| `interfaces/isolation_monitor.yaml` | `ade92191ca86270b61f1b8719067dc862f011c8a6f21c22201ec9dc4aeebcd62` |
| `interfaces/kvs.yaml` | `ff1063af525b301fd846190ed426175896dbbeb394fba06bc1d41be1f8b46df0` |
| `interfaces/ocpp.yaml` | `46a82fad56f8437d8567da9a1b7c4013ffa8eca9db187e034d02beda49673733` |
| `interfaces/ocpp_1_6_charge_point.yaml` | `6a28817e11d3f61f8fbc9178c03d27abd2f353926d1a8c3fbe15264bc289ffb0` |
| `interfaces/ocpp_data_transfer.yaml` | `dec8974ba68bf9ef20ba68616873f714bd0a3255c6ea28fefc6f5c524666aebe` |
| `interfaces/over_voltage_monitor.yaml` | `e900756a2058fca6c24434ac153c34afdf109ad582ca33c5aad0a725b70ddbfa` |
| `interfaces/payment_terminal.yaml` | `b0e6d97968e4ddaaed4bbcb776de577345ad1f4dc384cf3b6ad5d521f9dbbed3` |
| `interfaces/power.yaml` | `408e2ceccff04dacadd2f49427c9ee3239e08a6f0e7921b79428f7fe8fa786a8` |
| `interfaces/power_supply_DC.yaml` | `7cc64002367143c4898589610739acd80063962e97a1456f66897b0856f916b3` |
| `interfaces/powermeter.yaml` | `6d456d996d3760968c824cd4d42f0cc948663a4522dc890bd742e04d04196ed2` |
| `interfaces/reservation.yaml` | `f742304394c327354fd6480dd46d1c7bfe03034e8d48a5a605c42dd89e034f1c` |
| `interfaces/serial_communication_hub.yaml` | `aa24a736ef26ef75c1018d83c9dbb39cbc8d199fd692c971e516bd65d6bf9824` |
| `interfaces/session_cost.yaml` | `8421e84a49cc36317fd4c0458c8683be7ef088fea47b1a632c76f86e1a191020` |
| `interfaces/slac.yaml` | `973bb6d035e7ada95a0a589e0c1453000d37f637cecac53af5c12afe73be05e7` |
| `interfaces/solar_forecast.yaml` | `4d4a5db2706769d7c63ae3df1234ac96c6d37a604b3b9bfc035ab93480bceb5d` |
| `interfaces/system.yaml` | `4a5eb3f88d7934c3b7d0945aed369e4a6d95028a2c97d4e3090a0f73c1e0dcaf` |
| `interfaces/test_control.yaml` | `d56361f4d63a0d9edc900490717fd75dd9a2f454ac74a239f89d602a221ceaba` |
| `interfaces/tibber_price_forecast.yaml` | `e8b814658d8e9af17fda04caa6fab2ac49614d97630e4f056be366a6e471d76d` |
| `interfaces/uk_random_delay.yaml` | `1c2f75ba15d4d5f9a2b1eb4d48ef98a0ba1747deaf9341c8ca610f6fda7c99c1` |
| `LICENSE` | `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4` |

## License

The repository's `LICENSE` is the Apache License, Version 2.0; it opens:

> Apache License
> Version 2.0, January 2004
> http://www.apache.org/licenses/

The pack restates the type's structure (member names, types, nesting) with keys of this
project's naming and takes no description text. It is not endorsed by the EVerest project.
