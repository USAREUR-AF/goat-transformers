## Evidence for the shared keys

- `lat`, `lon`, `hae` (`position.lat`, `position.lon`, `position.h`): the Basic target uses the
  EPSG 4979 outer frame (conformance clause), WGS 84 geographic 3D: latitude and longitude in
  degrees and ellipsoidal height in metres. `h` is that height: `hae`.

## What is not carried

The orientation, a unit quaternion (`quaternion`), is a raw key: it is the attitude of the pose in the local tangent plane
frame at the position, which the shared model has no key for (`course` is a direction of
motion, not an attitude).
