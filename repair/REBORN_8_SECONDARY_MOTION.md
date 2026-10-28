# Reborn.8 general secondary motion

Automatic PhysBone conversion now fills node slots released by nested-component compaction before donor wiring begins. Legacy callers retain the earlier cutoff. Import snapshots, wiring, prechecks, final gates and coverage use the same selection. The initial rejected set stays frozen during degradation; no later retry can activate an unwired component.

Explicit source `enabled=false` or `active_in_hierarchy=false` is retained and cannot be re-enabled by a conversion style override. Missing fields remain backward compatible. Same-anchor components are not collapsed by name.

Angle constraints now follow the SDK CalcLimitAxis: EulerXYZ rotates local +Y, followed by alignment onto the segment. The allowed rest-centred inner cone subtracts axis tilt, not the quaternion's full rotation angle. Y twist therefore no longer unnecessarily disables a component. Hinge/Polar and source colliders are still not equivalent conversions.

The adaptation fingerprint includes revision 2 so fast repack rejects stale parameter manifests after mapping/selection rules change. Full conversion is required.

Synthetic tests cover nested allocation, inactive components, same-anchor
identities and independently calculated cone axes. Directional constraints,
branch merging and missing colliders remain documented limitations; see
[secondary motion limits](SECONDARY_MOTION_LIMITATIONS.md).
