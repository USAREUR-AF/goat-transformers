## What the message is

The pack's message is one message of the Waymo Open Dataset schema of the type named above, in
its protobuf encoding: a part of a perception `Frame` or a motion `Scenario` (calibrations,
labels, boxes, range images, map features, tracks), a challenge submission, a metrics result or
a configuration of the dataset's tools. The packs `waymo-frame` and `waymo-scenario`
(`tools/gen/protobuf-4-run.sh`) read the two record types of the dataset's files; these packs
read the other messages of the same schema at the same commit.

The schema files were read for names, field numbers and types only (`--no-comments`), from the
part of the repository under the Apache License 2.0, outside `src/waymo_open_dataset/wdl_limited`.
No value of the dataset itself was used: the vectors are made by the generator or written by hand,
with made-up values.

## Everything raw

Poses are 4x4 transforms and positions are metres in the frame of the vehicle, of a sensor or of
the scenario's own origin; boxes, keypoints and map features are in those frames. The schema
states no latitude and longitude, so no field is bound to a shared key and the packs convert to no
other format. Every field the protobuf wire can state is a raw key of the pack's own module.

- `bytes` fields (images, compressed range images, lidar data, encoded tokens) have no transform
  and are not carried.
- Times are integers of microseconds since the epoch or counts of steps, raw: `time_ms` is
  milliseconds and the protobuf wire has no integer scale.
- Messages that contain themselves stop the walk where the type would recur; paths below depth 6
  are not walked (pack.md counts them).
- Messages with no field the protobuf wire can state have no pack: `CameraName` and `LaserName`
  (wrappers of an enum), `CameraSegmentation`, `Segmentation`, `EgoIntent` and `MatcherProto`
  (enum wrappers), `CompressedRangeImage` (bytes only) and `occupancy_flow.Waypoint`.
