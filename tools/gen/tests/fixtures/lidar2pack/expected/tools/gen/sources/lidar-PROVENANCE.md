# Provenance of the inputs of tools/gen/lidar2pack.py

Written by `lidar2pack.py --commit-*`; every later run checks the files against it.
Date read: 2026-11-20.

| Source | Repository | Ref | Commit |
|---|---|---|---|
| ouster | https://github.com/ouster-lidar/ouster-sdk | `v0` | `1111111111111111111111111111111111111111` |
| velodyne | https://github.com/ros-drivers/velodyne | `v0` | `2222222222222222222222222222222222222222` |
| gpsimu | https://github.com/ros-drivers/velodyne | `branch` | `3333333333333333333333333333333333333333` |

| Source | Path | SHA-256 |
|---|---|---|
| ouster | `LICENSE` | `6b742b263cdb39fc0d9b2d06f2f3a903f923790b28e2ea0298f44fe2bec5f732` |
| ouster | `ouster_core/src/parsing.cpp` | `0b8b45f0c332ae998feb222918b68258bb8a27ca5d895cadde43c93db071c6da` |
| ouster | `ouster_core/include/ouster/core/defaults.h` | `c3af70cfed6132a9e89ab2014b9088cc536e3ff8ff4362d96d8f75eea81fbae0` |
| ouster | `ouster_core/include/ouster/core/impl/lidar_frame_impl.h` | `6d81232c832ebd1a0089b52ca2962280af1e3dbe3f0c5fb14a13238029678e79` |
| velodyne | `LICENSE` | `2fc1eaddfc0a355eaf36025d3bce61dffbe0a84b9e709421135f44d7a69cf6f6` |
| velodyne | `velodyne_pointcloud/include/velodyne_pointcloud/rawdata.hpp` | `20a16a07a6f46ae2243f821a6ffb43ff5e7eede8eefc9d05a15451b0ce92c3bb` |
| velodyne | `velodyne_pointcloud/src/lib/rawdata.cpp` | `2ddc2e4a34d2257219c505e6e82d5a1d6c2927a2271d9997e82354bf3d624b65` |
| velodyne | `velodyne_driver/include/velodyne_driver/time_conversion.hpp` | `449425081cca27aeb9e82acb4805a37a38fa9e40a5362f532befd419ba7eea3b` |
| gpsimu | `COPYING` | `fe4d9db732e23f82d356a2ac4cd7e8b5573059417622312a41af0feda131d1f8` |
| gpsimu | `velodyne_gps_imu/src/gpsimu_driver.h` | `7577e5ec72ee06d71c9774b25fdb5e91bcc4613b148959876240605eb2cf2920` |
| gpsimu | `velodyne_gps_imu/src/gpsimu_driver.cc` | `6421d5abf489203688283f27d6929970afd9f9b2c90ad4d47d509599b7e4cf10` |
