# Provenance of the ArduPilot inputs of tools/gen/aplog2pack.py

Written by `aplog2pack.py --commit`; every later run checks the files against it. The
generator scans every .cpp and .h file of ArduCopter, ArduPlane, Rover, ArduSub,
AntennaTracker and libraries (not tests or examples); the table lists the files a
definition comes from, the format table and the licence files. Date read: 2026-11-19.

| Fact | Value |
|---|---|
| Repository | https://github.com/ArduPilot/ardupilot |
| Tag | `Copter-4.6.2` |
| Commit | `1ebd4d996e8b6bbeb1462a9655c00aa861d5beef` |

| Path | SHA-256 |
|---|---|
| `AntennaTracker/Log.cpp` | `6cfbc7558ed3a0dd13c560c06e09df77c8dac1838339454241d104e0c4d94a97` |
| `ArduCopter/Log.cpp` | `2b9e18bf90ea17dc3e8544c92beffdf474cd9ecbe2c3d7b592394000f8508846` |
| `ArduCopter/land_detector.cpp` | `b921661ebc4f9fffb80f6fadb3db86b4e2f99ec6cc04092e805fb29ef2ab498a` |
| `ArduCopter/mode_flowhold.cpp` | `5380563ad68c6b3ae85f9baf3a2238e9f78c6eaa23f3ce5f9d6e134ebeb6b550` |
| `ArduCopter/mode_throw.cpp` | `ca7c3b71992389c5185384e2d02ac01aec5d56636e9b14dcc9a2fea82ab1b4a1` |
| `ArduCopter/toy_mode.cpp` | `e7c1d7f40cec1230d6fae0c850cbb833ca7601fb891523986bea37674e4f1a08` |
| `ArduPlane/Log.cpp` | `1d3f02d47b53265758d2e615756a7b18249fbddeeeeaf0ee955eb60c6d5a2da4` |
| `ArduPlane/quadplane.cpp` | `ce1b0b2bc19b1427866ab1c8bd8a19cb2a42dbcdadd7e113ceef6a91ee9d7792` |
| `ArduPlane/systemid.cpp` | `1d76e65b1a444b1385f3fea1bd18715d2728ed7890ea4e85b54f2eb5242b9480` |
| `ArduSub/Log.cpp` | `409b6070b6deeb273b742bb5ed1c09399a209cdc116a5eddb784abb6f42bf655` |
| `COPYING.txt` | `8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903` |
| `README.md` | `9081d51b98fcfeae22adf5cb7553699fc25365c24f0f7ddcd3cc174a4735e3d4` |
| `Rover/Log.cpp` | `74645b69a21139735056012e16ba0fe6f3cd30f3551165c3d2dba5ce8a0aac38` |
| `Rover/cruise_learn.cpp` | `d71a79476ee77f9fba4660c65a24a834fb5d433d970f7eda12fdcf257b4da1f8` |
| `Rover/mode_dock.cpp` | `9936e952e8cbb5a8afe92301823dc4ae5fd9a5c50e70c60e6becbb95ac813d3f` |
| `libraries/AC_AttitudeControl/ControlMonitor.cpp` | `eb776f4d42d3c3f6eb7bccbf88ce15313a890bc18c8bb9c3bb21a81adbb73d71` |
| `libraries/AC_AttitudeControl/LogStructure.h` | `f5abec74031dc012825b06416391cc84e71ca314540a0301bdf5d99af6938948` |
| `libraries/AC_AutoTune/AC_AutoTune_Heli.cpp` | `b9d346ec0b0b613e9fce8604a148f818fa889b676a81e40835da188ff5116f2c` |
| `libraries/AC_AutoTune/AC_AutoTune_Multi.cpp` | `d1adc832ec2d6fabac53465d6dea4d04929f2a089f62ebdddd0a0910d0086e95` |
| `libraries/AC_Autorotation/AC_Autorotation.cpp` | `e2d6540d83864942731a80820f9e3519fb0acd080c5f8f655ee20bc90d49a02b` |
| `libraries/AC_Avoidance/LogStructure.h` | `4c377fa1766c118cb0765a651221c220eeb43b78dbd23a9678839925a8b34f51` |
| `libraries/AC_CustomControl/AC_CustomControl.cpp` | `393740b9b85665ad94cfef50b6aa74b77cd185d1e55bbe777baf047a43182723` |
| `libraries/AC_Fence/AC_Fence.cpp` | `09630cb82622f1f9c2244eb8cc6f1883231579600a6ef6dec2355c9dc30f0ce4` |
| `libraries/AC_Fence/LogStructure.h` | `5511b926bcb058f279f0bf23f9805a9c9b9b9a8b0292a4c47f5a86643dd437a3` |
| `libraries/AC_PrecLand/LogStructure.h` | `090bb593bc1a4a250595bf503073c8f98cba7f8bae090b176cd2441806654ebe` |
| `libraries/AP_AHRS/AP_AHRS_DCM.cpp` | `779699d398edcfbf3a0cc87348df24d5b5e31c9bbc79bccee17d0d918cce5a26` |
| `libraries/AP_AHRS/LogStructure.h` | `7834873a8e288e72fa73ec568a4d902adbf145e398f483d1f0e7dcbcaf0c90bd` |
| `libraries/AP_AIS/LogStructure.h` | `d38af98187303a5b5d9819942b85bb2715b4fce3ab1dae09052bcc1395e525e5` |
| `libraries/AP_Airspeed/AP_Airspeed.cpp` | `908b4d728e61ce5a2e14cc7d8f99f7d4cfe8b7ebb0abad4c1a963b11bca8fceb` |
| `libraries/AP_Baro/AP_Baro_ICM20789.cpp` | `c7028137d85b1d5ffd1ea4d2b1f882f8f37bf7768f4b9defe92394e33f4fbf9b` |
| `libraries/AP_Baro/LogStructure.h` | `e463a9bd8c3d0058a52fe324c4a4646c198d1f15b221ec735fa68e666eb6babf` |
| `libraries/AP_BattMonitor/AP_BattMonitor_Logging.cpp` | `9539d60ba48513116be9312964dc3c1cb0d3d2b1752dee6d4ecadf4788e01bbb` |
| `libraries/AP_BattMonitor/LogStructure.h` | `646686019667018daab4cd4a67cc7bfd51db8d2f64937b744848af290acaae6b` |
| `libraries/AP_Beacon/LogStructure.h` | `013f0fbeea189863a8dae8e727e7aaf3d139468a823ea6f504d7f80ff3ddfb8d` |
| `libraries/AP_BoardConfig/IMU_heater.cpp` | `2941516f465d3ec64cdf89c017ad24a7a55f302cf52f49e0edff13a07e91dda1` |
| `libraries/AP_CANManager/LogStructure.h` | `1b867ce29ed74c8979f13a98e3f8284221e00779b3607f1fd0f3c9c6c8d56f12` |
| `libraries/AP_Camera/LogStructure.h` | `13310a63e4d1d98daa84421db68f50ae1289af40b69d7290f0ebbf714d8c43e7` |
| `libraries/AP_Compass/AP_Compass_DroneCAN.cpp` | `d6ab72071cd6fac933e0311845525a088aa22994d4a5c3bac85105ca7264ff45` |
| `libraries/AP_Compass/AP_Compass_MMC3416.cpp` | `3e9892262c12e6eb31c9a6bc2938aa35e2fa72730a89818f54b303df4539e72f` |
| `libraries/AP_DAL/LogStructure.h` | `936dd61d9688a72071a0a5a4c0a7c9a4762954167dd0e1f56200ce3a158b3b04` |
| `libraries/AP_DroneCAN/AP_DroneCAN.cpp` | `2f51e3624c8351424227b45d5694b52a7c3dd3c57a292d7e9ab8a0a8ebf313b1` |
| `libraries/AP_DroneCAN/AP_DroneCAN_DNA_Server.cpp` | `5005ae04a3b062c99f4b8664220023c7f87bcbb57330283905a35fd9a3af8a72` |
| `libraries/AP_EFI/AP_EFI.cpp` | `ba6955bc507e5797ddac19aad609a8d48072aab7f7e6439c766ddcc018d0c587` |
| `libraries/AP_EFI/AP_EFI_Serial_Hirth.cpp` | `411d9b85e6f3943f9a81bc98e5ab4cd222425050324cc14932dff4d5c38da2b8` |
| `libraries/AP_ESC_Telem/AP_ESC_Telem.cpp` | `61f0883754e6b43ce562a459205dfe0df21b31acb26e8bd3b33b18f278321e76` |
| `libraries/AP_ESC_Telem/LogStructure.h` | `f0a8d4fea876daa021f926f7d083c6000d8b4cf6a44bab395e747dab6adce2ba` |
| `libraries/AP_ExternalAHRS/AP_ExternalAHRS.cpp` | `9182235094f4a4110c7d80ac3838f3fd543276deba4d608a29d2329f88b3eb45` |
| `libraries/AP_ExternalAHRS/AP_ExternalAHRS_InertialLabs.cpp` | `f15a2d2ae0bc7fa12ee06bc9e1a795c65e4cfdbc43bf1e1dce40efd364c96bd7` |
| `libraries/AP_ExternalAHRS/AP_ExternalAHRS_VectorNav.cpp` | `a44df8dc789f238fbbc15332b56c2d3ae504b2135cc8de4025520c2ad1b3acbe` |
| `libraries/AP_Follow/AP_Follow.cpp` | `347d58d6579482d2afa0e97607cd898bda7a5310a118483e7dca5612c7f8144d` |
| `libraries/AP_GPS/AP_GPS.cpp` | `2d189b71b8a681a78db97e619ba866582e93afbd15c2dd6b2eea7e48f29843d9` |
| `libraries/AP_GPS/AP_GPS_UBLOX.cpp` | `b5cb636867b879d137eff1682cfc7519adb72a7900e17d96fd1e4add739356c8` |
| `libraries/AP_GPS/GPS_Backend.cpp` | `dc7b58f8dc63bfd3b5018a08e142b092e5e2dd1364b18d42be646d6582507812` |
| `libraries/AP_GPS/LogStructure.h` | `6d1d8dfa48ec75be314b0e3ab426b0e887ff3ebcc4d4f6e3e7ff03f2422f3892` |
| `libraries/AP_GPS/LogStructure_SBP.h` | `0c5304595254520fe934bcebd97161f66f0cf5b87b444773f0b31b65322ac382` |
| `libraries/AP_Generator/AP_Generator_IE_2400.cpp` | `81c257f674a157d2928b9c2b42ef854b8ac7b7b22c3ac2bad7cd0a01abac5b92` |
| `libraries/AP_Generator/AP_Generator_RichenPower.cpp` | `54347f6efeb8981da624830407986fbe798ba227c014a57ce094cd5bcc17d924` |
| `libraries/AP_GyroFFT/AP_GyroFFT.cpp` | `6da4f37287207e7f10830a5fccb66845ec17717eabba2e3c9e937306ea2bbe90` |
| `libraries/AP_HAL/LogStructure.h` | `4d5c4c40814163c8301c8cf4b4c09a0218defcf1e12fe2546b448026f66972ba` |
| `libraries/AP_HAL_ChibiOS/LogStructure.h` | `99a40c72de89f4f46bbadff10cf66f271f1b6a13a90c942fe8a2b3728d47dc81` |
| `libraries/AP_HAL_ChibiOS/Scheduler.cpp` | `32a37e5287f9a679e2259e3a3efba2c46965b2cde83222ac8149daf75bcde652` |
| `libraries/AP_HAL_SITL/HAL_SITL_Class.cpp` | `f280785e385befc624a4728828929672b4cb9d8dbe446f419b9d8de8ab3935f0` |
| `libraries/AP_IOMCU/AP_IOMCU.cpp` | `16972db22fdf2f9dccf4bd38b83b2a45709bdd5bf479e30cf8282bf198c8b1a4` |
| `libraries/AP_InertialSensor/AP_InertialSensor_Backend.cpp` | `e05b188a5f52654595e17811a405f3800c1d7e0653d4ffa4afb00d03c8604646` |
| `libraries/AP_InertialSensor/AP_InertialSensor_Logging.cpp` | `0dbad29b56742c8a7facaf93513b83363237a56f8e1c129e2e98838e9464c468` |
| `libraries/AP_InertialSensor/AP_InertialSensor_tempcal.cpp` | `ecb60a362aa838b64c0ecf9cb3d267c045ad51703a76bc4af555cf3b4d07fd95` |
| `libraries/AP_InertialSensor/LogStructure.h` | `0765be741c896c879b85df7216935f86b5c6682437d63b012a2d15315970e91f` |
| `libraries/AP_Landing/AP_Landing_Slope.cpp` | `03138e9f9a229093158935d988aa112b33411c3e2b2f2eeb8f29ace64dc8b187` |
| `libraries/AP_Landing/LogStructure.h` | `4904e2a30fea262921ed96d4c8d55201d13b8409de27c3093f51a66123659b40` |
| `libraries/AP_LandingGear/AP_LandingGear.cpp` | `3d9481137c01f8f17890fee0b464987be6aa1bc9ded8fadd76265a273754cc9e` |
| `libraries/AP_Logger/AP_Logger.cpp` | `500975a7fc371e894932584bcf5b06bfdf64e465fc7b24f1e4e9e94117502c5b` |
| `libraries/AP_Logger/LogStructure.h` | `61c27059585e9d5cd0482a07fee3fae5c695b55be7415d426deca85eb82b2d0a` |
| `libraries/AP_Math/SCurve.cpp` | `8d0adc870dfef14109983391a5b8cd20530e1bbc7fbad0040ddab13c83259919` |
| `libraries/AP_Mission/LogStructure.h` | `88ad5fa275bd2ea8322a58ff80b6ec14471c200451e02a6000f7fd5558664024` |
| `libraries/AP_Motors/AP_MotorsHeli_RSC.cpp` | `b96582d45da09fcde7fcf720c7e5800c52ec08fca69077aeea043de47a8bc1e3` |
| `libraries/AP_Motors/AP_MotorsHeli_Swash.cpp` | `cbe726725909631b1909a7cbac77ac9a8f6f8f9ff6d132851e27cffdf0dc0d2f` |
| `libraries/AP_Mount/LogStructure.h` | `5aa8690fe4a8194a13013e532b0be57b6e77a62c7eab6dfb153648b8340b784a` |
| `libraries/AP_Mount/SoloGimbal.cpp` | `9a351f7ee244752389cfd8079e7a887fc2eed8dc7f1584dd521dfb55864af3aa` |
| `libraries/AP_NavEKF/LogStructure.h` | `038ab0ac9dab1db361b910768026eda94ca5948aea60a35e5af483eb31cc351b` |
| `libraries/AP_NavEKF2/LogStructure.h` | `0126f565d2b6febf63b929bacd7aacb34612d1b6d6bb3d17b3024f10323e9cda` |
| `libraries/AP_NavEKF3/LogStructure.h` | `cf5f015e9ad0b5bec454d96dba32926f7f1196cc3563cefb8f60431c9334da83` |
| `libraries/AP_OpticalFlow/AP_OpticalFlow_Calibrator.cpp` | `2fddba6a496a8ae2961ef9543bd5d34165db5e244078d644c7bc665a8c5fcc99` |
| `libraries/AP_Proximity/LogStructure.h` | `5a67c7bd64b4dcf8ed9909d14f074ae5be8d49c3f358bbd89add487eac8ebc67` |
| `libraries/AP_Quicktune/AP_Quicktune.cpp` | `5173818befad1d6d33abafa55e0eaca8462c8204405929b4d129168bfccb8ee2` |
| `libraries/AP_RCProtocol/AP_RCProtocol_Backend.cpp` | `32d949b66a768c3365d62f31db95040dc1f01f1571bc774530024499eed71aa7` |
| `libraries/AP_RPM/LogStructure.h` | `0c215a66d8e2d4b42fd5f13c1091bb58de98ca44053897490a5be81aa21598b4` |
| `libraries/AP_RTC/AP_RTC.cpp` | `470ccca798c683b525877ca66f0ca94ad95a2066e7d922161d72f547b1a82d9f` |
| `libraries/AP_Relay/AP_Relay.cpp` | `95037d54b5f1076e157ad59c4fad9520e1a07e0ca87defb724a20adb1ae11075` |
| `libraries/AP_Soaring/AP_Soaring.cpp` | `84b9f08b576e1e80be515aa1b38e628aff3312a448bdae402df2587b1e4667c7` |
| `libraries/AP_Soaring/Variometer.cpp` | `4cb0bd55bac2fbf6e9cc1e1c0139ba63f399ba059bcc64d1588ca7b1587081ae` |
| `libraries/AP_SurfaceDistance/AP_SurfaceDistance.cpp` | `3423dd9a7a1cf8f44bcdd089a51f6bdf80453f6d13f7c0872e8e9a95e5d785a0` |
| `libraries/AP_TECS/AP_TECS.cpp` | `fb0e0d0f5b65f617fc55b68c79ab32d17749a91348b66956a2d36bd8945de860` |
| `libraries/AP_TemperatureSensor/AP_TemperatureSensor_Backend.cpp` | `290fcec05cff5120cab5a01956af1111838c996b4c4b3e2b91b9a9712a001656` |
| `libraries/AP_Torqeedo/AP_Torqeedo_TQBus.cpp` | `1672b3caffac48a42f11d3ee76e1e29dd7df3f4469fbe45f267acff3107f99cf` |
| `libraries/AP_Tuning/AP_Tuning.cpp` | `d446e7439221f254af2cc37e4da9bb4f103957c0ceebe740d7c50a44786e9daa` |
| `libraries/AP_VisualOdom/LogStructure.h` | `b22faa07a37f7f2a1334abccabf96b7a05486a7f2737070d2f27a4cd23f174e1` |
| `libraries/AP_Volz_Protocol/AP_Volz_Protocol.cpp` | `0f1517869ede6f3471af77d81f132e4a6a405aa418f47e910901482ad778799a` |
| `libraries/AP_WindVane/AP_WindVane.cpp` | `b939ba8c34d331a1105099fbaead40dc2a0f5e3993c15268c2fa4ed7bd6f3c47` |
| `libraries/Filter/HarmonicNotchFilter.cpp` | `eb274e60714b8e036de9599a85001d84f15505060d17fb73e55b7e145c61021c` |
| `libraries/GCS_MAVLink/GCS_Common.cpp` | `38aea668e19d8c741961f78d3149a99344051f357c326afe78a35191327641c3` |
| `libraries/RC_Channel/RC_Channel.cpp` | `d8e8a8b78648d7b8e1483c63ce4c50ae51d0b98a0e5bf29c86bb8852e7ebc3fd` |
| `libraries/SITL/SIM_AirSim.cpp` | `f0b12a5687019a460e4bfab71e1dd65a79e28d6f400702b6cebb2b53a313a8e5` |
| `libraries/SITL/SIM_Aircraft.cpp` | `a3913dc083b04350233cc55f2ed2a5ab5699d982caf9c4f414bee0f3af3a837a` |
| `libraries/SITL/SIM_Blimp.cpp` | `c6a57bf38edc68bbf371b53eca57f4120ca73c56522bcdec79545987d95f07eb` |
| `libraries/SITL/SIM_Glider.cpp` | `7806d8bd22d35ce75391cc10e1e697f7a5407fbbabfc78efe1401dcdb0350a82` |
| `libraries/SITL/SIM_JSON.cpp` | `79ac7198d9d9b0fc6c1a959167e6e9925c7fb9b16338d3ee971f7591dbc9fe05` |
| `libraries/SITL/SIM_JSON_Master.cpp` | `8938c2eb450d37e3d46a51d03bf486b63b179314d4547be5bea5073e0b274408` |
| `libraries/SITL/SIM_SlungPayload.cpp` | `fe83581f359bc722334f84bd1e3475f0ec6018e4e6908de2bb6e1d51410db256` |

License: GNU General Public License, version 3 (`COPYING.txt`, `README.md`). See any
`packs/ardupilot-log-*/PROVENANCE.md`.
