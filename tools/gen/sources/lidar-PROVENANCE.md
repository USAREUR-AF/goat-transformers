# Provenance of the inputs of tools/gen/lidar2pack.py

Written by `lidar2pack.py --commit-*`; every later run checks the files against it.
Date read: 2026-11-20.

| Source | Repository | Ref | Commit |
|---|---|---|---|
| ouster | https://github.com/ouster-lidar/ouster-sdk | `v1.0.1` | `46b7bceee7995914e2f3f3facf4d78418335b2d7` |
| velodyne | https://github.com/ros-drivers/velodyne | `2.5.1` | `0f2a3bb1dde4fa91cbafad8a3f9f89b66c2a1350` |
| gpsimu | https://github.com/ros-drivers/velodyne | `gps_imu` | `7f52dd39747a9f4d43c95c31a5c66f26ae9ae71a` |

| Source | Path | SHA-256 |
|---|---|---|
| ouster | `LICENSE` | `a4bbe45cd35bbe91e1f64f47595ce69a99a3ac07bfb590382bde7156c81b0276` |
| ouster | `ouster_core/src/parsing.cpp` | `aacdc9897b209fe13c2f7d98913ad8b7fa616b5ab554c6f3e7db04f4f6d2ecb0` |
| ouster | `ouster_core/include/ouster/core/defaults.h` | `b0db82ab2794d8786d2370c3d5d7e02ee7c2256115778919fc847ee55abdec47` |
| ouster | `ouster_core/include/ouster/core/impl/lidar_frame_impl.h` | `809458964a1d269df8403ac292b73f1d6ea1313786fd2c8b90a8fb51d60e44d2` |
| velodyne | `LICENSE` | `ae42f8149e6911748be854d45baf96740dee6d721f20eba8c93a449e3b1b3dd9` |
| velodyne | `velodyne_pointcloud/include/velodyne_pointcloud/rawdata.hpp` | `e58fa9a3326ea887b6d99b7a808c38d33794f95d7d4ea7da725edbc73938b96a` |
| velodyne | `velodyne_pointcloud/src/lib/rawdata.cpp` | `0e0ee1579b2553fc37f8cfa9121d901b8234a7bc7647b84a3e07f6f74e665e95` |
| velodyne | `velodyne_driver/include/velodyne_driver/time_conversion.hpp` | `865c8c434ef469c598fce38c68277b80ff551f01284b11e5c1b2f4d9fc02a5f4` |
| gpsimu | `COPYING` | `fa58565b853d84ba2182dae2918fbc291253a079c639b79c76534bba14b22b18` |
| gpsimu | `velodyne_gps_imu/src/gpsimu_driver.h` | `4dc26315d3c0b5da5cf1a68f4b770dbe5dc030cdc7172c222960c4c6d439e4a2` |
| gpsimu | `velodyne_gps_imu/src/gpsimu_driver.cc` | `2c046b0a259747c9e0e002b730a50fa1e29c5cf6c1848c87e4cf17780fcbe671` |
