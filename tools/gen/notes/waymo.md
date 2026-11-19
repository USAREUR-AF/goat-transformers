## What the message is

The pack's message is one Waymo Open Dataset message of the type named above, as a record of the
dataset's files holds it: a `Frame` of the perception data (sensor calibrations, images and lidar
returns, labels, the vehicle pose) or a `Scenario` of the motion data (object tracks, map features,
traffic signal states). The schema files are those of the repository outside the `wdl_limited`
directory, under the Apache License, Version 2.0; no file of `wdl_limited` was read, and no message
or value of the dataset itself was used: the vectors are made by the generator or written by hand.

## Everything raw

Poses are 4x4 matrices and positions are metres in the frame of the vehicle or of the scenario's
own map origin; the schema states no latitude or longitude. Images, lidar returns and compressed
data are `bytes`, which no transform reads. No field is a shared key and the packs convert to no
other format.
