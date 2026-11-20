# Provenance of the vss-vehicle pack

`tools/gen/vss2pack.py` reads the files below (the `type`, `datatype`, `instances` and
`instantiate` keys of their nodes, no text), expands the instances into 1382 signals, builds a
JSON Schema of the tree as a document and passes it to `tools/gen/jsonschema2pack.py`. The
files are not kept in this repository. Read on 2026-11-20.

| | |
|---|---|
| Document | COVESA Vehicle Signal Specification (VSS) v6.1, the signal tree |
| Publisher | COVESA (Connected Vehicle Systems Alliance) |
| Repository | https://github.com/COVESA/vehicle_signal_specification at tag `v6.1`, commit `2817646d1808fc7c470c0432fc7f4ed685e5c9e3` |
| Download | `https://raw.githubusercontent.com/COVESA/vehicle_signal_specification/2817646d1808fc7c470c0432fc7f4ed685e5c9e3/spec/VehicleSignalSpecification.vspec` and the files it includes |

| File | SHA-256 |
|---|---|
| `spec/ADAS/ADAS.vspec` | `6bd917bf71b89e21502d6ff9ed5b73946db308bac5dff27a78877c7672f53d3a` |
| `spec/Body/Body.vspec` | `f2a5179a54c5544774c933deb8c12fb878e48fbfa954c76d48ffe4e2a1548884` |
| `spec/Body/BrakeLights.vspec` | `90d4d95aa96d3eb3d759c56ee6f1da0e0734f14a7e428c40163c0d290d756b67` |
| `spec/Body/ExteriorMirrors.vspec` | `33380ef4f5ebe221bd2329d35f0b885e2be26310652d24730b050e12b15b124c` |
| `spec/Body/SignalingLights.vspec` | `48cfc34733a7d12c7f3526bb7e12e2268f1e69dee9a0713322a401ec34eeda17` |
| `spec/Body/StaticLights.vspec` | `3b61169e15696550e00c13ed0939422126d7cdab9c8fbef1806a9c6b1529daa2` |
| `spec/Body/WiperSystem.vspec` | `a7e96a9ce7d2f7221db509c16e59ddeb2fe13920bb3fa2cb2a6cfc847c3f2ac5` |
| `spec/Cabin/Cabin.vspec` | `bff513cd820de0ae98103f55bd95ab4e42201f94be7a2e32d1e01da05fb3b1f6` |
| `spec/Cabin/HVAC.vspec` | `4ab5efb91db5dd0f642591ce6d4fc5ae611d0c3fb13094c02b5c87a322c5b98d` |
| `spec/Cabin/Infotainment.vspec` | `fd345d9b22e0a99a0d0a781c176349c0a378a22090e017cc8383c5efec4c4610` |
| `spec/Cabin/InteriorLights.vspec` | `79c9d4aa01beeaddf92aff9b9d37dd1e420213273fd0aae6aec47828c74a5587` |
| `spec/Cabin/Seat.vspec` | `3f04db034559f2b0d4ff80305f2b69e64c7e845df66d8a308fdd62b6b3a5bb2d` |
| `spec/Cabin/Seat/Massage.vspec` | `d612014e7705d639e80e522834a54dd4c85cec2f858e7a53cf6e63ac1e58de9f` |
| `spec/Cabin/SingleConfigurableLight.vspec` | `f34053104c76a315cd98f3f4417edb63ef10a3e893c786ddb4c5004f1d2a90a4` |
| `spec/Cabin/SingleDoor.vspec` | `1de34b5929ae900033433b6e6a170ab8aa2f74b4947cc1978aea290115c6c1b2` |
| `spec/Cabin/SingleHVACStation.vspec` | `4982d7730c3de1c1d21e1d07dba3812fb817d35446a056c6390e8b6dccb78d7c` |
| `spec/Chassis/Chassis.vspec` | `f1663461fb9eb23ea0496e9571dfd4260efd5b2c11ae0772dfbd69ddc567b8e3` |
| `spec/Chassis/Wheel.vspec` | `3ce2ffc910928271fc245729e28b1b8f607a56afdd6a61828b5a30da61649e27` |
| `spec/Driver/Driver.vspec` | `a9610e321b1b8ec22d13a8fc444599ba847922faaf4fd22cbfcf27a026b5d7c8` |
| `spec/Powertrain/CombustionEngine.vspec` | `03dde4adb2e3156442c83b326ec48f8fb869dd2d540ecf1a027a1220e9737658` |
| `spec/Powertrain/ElectricMotor.vspec` | `2b4ee75dd6dc9ebeceb6f4fc2f505a092cd925f2ac7d6ba99e2efbcd1d606c4b` |
| `spec/Powertrain/EngineCoolant.vspec` | `61fb7e078dee00f7283b05b58fa6aa9c279cb71a693c028d475c9587fa607227` |
| `spec/Powertrain/FuelSystem.vspec` | `416b9758238c286936f00a14d6542f5b924b3c9ced038df47fc865d2c56c393f` |
| `spec/Powertrain/Powertrain.vspec` | `598e4dbda2f275add69add11691541ffc66c2c47a5b1a4db72ba187bad6c0203` |
| `spec/Powertrain/RangeExtender.vspec` | `2ac4f0d7fe4ac8634e22b5da2078cde13a82cf6b9b1834a276f8aad9abf475c0` |
| `spec/Powertrain/TractionBattery.vspec` | `0be13e8ebe8a4bff479449ce96e2e5cbea2d0c8f557652ac6f7f142d193885fd` |
| `spec/Powertrain/TractionBattery/BatteryConditioning.vspec` | `135f7bbb0f0ceba3de9346da6d21a42051f73528ad00f765db806321b63f6bff` |
| `spec/Powertrain/Transmission.vspec` | `c9559f66a2cfd0d9445e8d44bc3571177bb3dab51d8efd725d599ef836e18184` |
| `spec/Safety/Safety.vspec` | `cceacce1f35d554e3c20f8abe89ef0cb081bb06c2ba24124ff2ddece2030fbcc` |
| `spec/Vehicle/Battery.vspec` | `bf4a10f1fa1fc97f3c85e0ad3a22b5f4150cef393ca318e688e0b57c25d1e641` |
| `spec/Vehicle/Connectivity.vspec` | `49e167e0c203da21151c2818b6251ee423edc6d4d171172b6c3cadfcb75d1f46` |
| `spec/Vehicle/ControlUnit/ControlUnit.vspec` | `a3ed6526fe8f81363abf3c0ae3448d6d3ac31b6235476492a710284efc262f26` |
| `spec/Vehicle/ControlUnit/Generic.vspec` | `5905c695d6285ab289f4088a044f8e7bd95e4d4327f8c1f11e552cfb2567481c` |
| `spec/Vehicle/ControlUnit/Health/Health.vspec` | `46daf57d016a7f58d53b9a339316ed463da305652ba96c953b4bb170ffacc531` |
| `spec/Vehicle/ControlUnit/Health/Network/Network.vspec` | `de4bf29a4e5cf8f8595d1e14d022f71e4024021cc9dd5a2a621a5a4155482ee8` |
| `spec/Vehicle/ControlUnit/Health/Network/NetworkStatus.vspec` | `2d7901c971960e1f96b8886405e162f7999d28ab713609ae9c8bb8a7af01f442` |
| `spec/Vehicle/ControlUnit/Health/Resources/Resources.vspec` | `25a78f9b8bc1fb2b2eb37f3a1ccb083b7bb84453bb5647b2a5b38c8a7c0bcb3b` |
| `spec/Vehicle/ControlUnit/Health/SWSupervision/SWSupervision.vspec` | `bde18a6cc407e0d5edfd0ef1b6bbb09736f492449e7d074fa6a46382b5c3b697` |
| `spec/Vehicle/Diagnostics.vspec` | `d86169815d5fc63d064af744ce9014486a31ac432f9bfd0e5d58211cc15b8136` |
| `spec/Vehicle/Exterior.vspec` | `d4f058e808521bbedfe9ddb39f7d421fd6c2d80005621ea26e3c7bd96630d16b` |
| `spec/Vehicle/MotionManagement.vspec` | `709cc62dbff986b09a6595dfa510b4331149220cc3f47215ed6401e475dd2113` |
| `spec/Vehicle/MotionManagement/Brake.vspec` | `d2744045946adc127a1ce832862b16fee7c500bb37334ff525fb7bc27d0f7356` |
| `spec/Vehicle/MotionManagement/Brake/Axle.vspec` | `dc36d5a6c65b3063c5881cf3fbb967cf611c0b8587d6a1b9b634b665f084b9f2` |
| `spec/Vehicle/MotionManagement/Brake/Axle/Wheel.vspec` | `a03896927b070233c3e712cf1c3845eb0725fffe73f6c05e7da016e4a2526837` |
| `spec/Vehicle/MotionManagement/ElectricAxle.vspec` | `f2ec2869ce7ce39237a0981033c513fbfa6877e07eef92d06685f8dc26f05be3` |
| `spec/Vehicle/MotionManagement/Steering.vspec` | `226b07a6fdd1791e6f3676ecab2798256722db92ef2dcc14fb146f11090baf40` |
| `spec/Vehicle/MotionManagement/Steering/FrontAxle.vspec` | `ddcb43f107fc98ba5ea549f4923980bfc929f032b085aeeb84d11888a038a07f` |
| `spec/Vehicle/MotionManagement/Steering/RearAxle.vspec` | `0030a85fd54d78898efb236ee69d280c50147c76284ebc26a4766c55331010c1` |
| `spec/Vehicle/MotionManagement/Steering/SteeringWheel.vspec` | `f13ba31a4b20f4e6ebde0c4e8564ea3657a4d906569b8e5324c95c1b28d9b869` |
| `spec/Vehicle/MotionManagement/Suspension.vspec` | `8078ee698511122a206e2eaf9a77cd46d40713bfd0275677d1b6d5fd1e0d47d1` |
| `spec/Vehicle/MotionManagement/Suspension/Axle.vspec` | `7a405e2ac56711ae89a5fa03579386f224da128459335f1683ac64d9b3290699` |
| `spec/Vehicle/MotionManagement/Suspension/Axle/Wheel.vspec` | `98ecc1efefd927b1b8f3cc97188413edddb7b479bf29f4adc6cd055a0b891a0f` |
| `spec/Vehicle/Occupant.vspec` | `a756c3c30b685080eec6ae91439a30a3d3297285504c7a7bbc6d2f385d6a5276` |
| `spec/Vehicle/Occupant/HeadPosition.vspec` | `f0f30ad63ad3594dea9c2a01ee6741376a4583aee249f471b7781598c4cd284f` |
| `spec/Vehicle/Occupant/MidEyeGaze.vspec` | `c83c55d62ae9494ee4195267bb5310e0b712f03d4cca10f36d1db33e117bf313` |
| `spec/Vehicle/Service.vspec` | `fd2b04e43cdec13e4acec932beeec685b47b2aebc4db3aabef1c5e1836048bac` |
| `spec/Vehicle/Vehicle.vspec` | `f6ddce151cb9007436428ca686a24a41399ad8921b9dadd85b41b19ba1710ff7` |
| `spec/VehicleSignalSpecification.vspec` | `d50b06de941f61b24844a4b0f900b77212f15a8843a41ef58512a3975d6ae78c` |
| `spec/include/AirComposition.vspec` | `4cd08b107c9e85ac9b92d285b0a1430b45c2c4322bf6685669d2743980f81809` |
| `spec/include/Identifier.vspec` | `2beaad76382f483513a04acb52040927cf12abe013b5d28f0ddf26c4776c9cc2` |
| `spec/include/ItemFanSpeed.vspec` | `b5b62053ca9ee6eaf5e5b07e2d5473071311c7fa280de39fc24adfedbb7dac6a` |
| `spec/include/ItemHeatingCooling.vspec` | `69996d93d5c6712a4f3ea6b005fa8bd06d38a44610b687d67d9e332f5e146bba` |
| `spec/include/LockableMovableItem.vspec` | `96b955622192a6a704aef2c248265f0d81ec6d17600ba34857553d6ab5a6d5f6` |
| `spec/include/MovableItem.vspec` | `807642d8f1ef1503a49b31887efc7e43546cdaef84bd65c983f46db993d6913a` |
| `spec/include/PowerOptimize.vspec` | `8a173aeeaa77e38f4d4a869ce1bb5be03d1526ae57865022a9e9013767145bb1` |
| `LICENSE` | `1f256ecad192880510e84ad60474eab7589218784b9a50bc7ceee34c2b91f1d5` |

## License

`LICENSE` is the Mozilla Public License, Version 2.0. Its title, and the notice each vspec
file carries in its header (in full, the file's own words):

> Mozilla Public License Version 2.0
>
> Copyright (c) 2016 Contributors to COVESA
>
> This program and the accompanying materials are made available under the
> terms of the Mozilla Public License 2.0 which is available at
> https://www.mozilla.org/en-US/MPL/2.0/
>
> SPDX-License-Identifier: MPL-2.0

The pack is not a copy or a modification of the vspec files: it restates the tree's
structure (node names, data types, the expansion of instances) with keys of this
project's naming and takes no description, comment or allowed-value text. It is not
endorsed by COVESA.
