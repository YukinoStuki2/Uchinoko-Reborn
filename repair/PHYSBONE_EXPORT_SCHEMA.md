# PhysBone source preservation

`unity/DiveToPalworldExporter.cs` writes additive revision 2 fields while retaining
the `divetopalworld-physbones-1` format and existing scalar parameters and chains.
Capture occurs after NDMF/Modular Avatar baking and final unique bone naming, before
SDK components are stripped. Existing exports remain readable by old consumers.

The top-level `source` records the Unity version, owning VRChat base package
version when available, and PhysBone assembly version. `params.version` retains
the component's SDK behavior version. `integration_type` and `immobile_type`
remain explicit: Advanced mode interprets `spring` as momentum, not Simplified
mode's spring setting.

## Curves

`params.curves` has these keys, read by reflection from the actual SDK fields:

| JSON key | SDK field |
| --- | --- |
| pull, spring, stiffness, gravity | pullCurve, springCurve, stiffnessCurve, gravityCurve |
| gravity_falloff, immobile | gravityFalloffCurve, immobileCurve |
| max_angle_x, max_angle_z | maxAngleXCurve, maxAngleZCurve |
| limit_rotation_x, limit_rotation_y, limit_rotation_z | limitRotationXCurve, limitRotationYCurve, limitRotationZCurve |
| radius | radiusCurve |
| stretch_motion, max_stretch, max_squish | stretchMotionCurve, maxStretchCurve, maxSquishCurve |

Each present curve has `keys`, `pre_wrap`, `post_wrap`, and `samples`. Each key
retains time, value, in/out tangent, in/out weight, and integer weighted mode.
Infinite step tangents use JSON strings `"Infinity"` / `"-Infinity"`; finite values
remain numbers. Samples are evaluated by Unity, including weighted tangents.
Sampling times are the sorted union of 0..1 at 1/16 intervals, original key times
within 0..1, and all actual source SDK force/transform ratios. This retains exact
values at source joints instead of approximating a narrow curve peak through a
uniform grid. Invalid nonfinite evaluated values are `null`.

A missing SDK field or null curve is `null`. An existing curve with no keys is
`keys: []` with samples equal to 1, because VRChat treats it as the default
constant multiplier. It is not Unity's empty-curve `Evaluate()` result of zero.

## Bone geometry and depth

`params.geometry` includes:

- `coordinate_system: unity_world_lh_yup_meters`.
- `max_chain_index`, `endpoint_nonzero`, and `ratio_source` (`sdk` or null).
- `transforms`: name, parent, depth, force_ratio, transform_ratio, world position
  and quaternion, world `lossy_scale`, local position, local quaternion, and local scale.
- `chains`: bone names including the anchor, world segment lengths, total length,
  and the leaf's endpoint world position and length. No virtual bone is inserted.

The exporter invokes the SDK's `CalcBoneRatio` and `CalcTransformRatio`, temporarily
setting and then restoring the export clone's nonserialized `maxBoneChainIndex`.
It never initializes or runs the SDK simulator. Source depth, not cumulative
physical length, controls these curves. The SDK 3.10.5 assembly confirms force
ratio uses `depth / (max_index + nonzero_endpoint - 1)` (zero for a nonpositive
divisor) and transform ratio uses `depth / (max_index + nonzero_endpoint)`, both
clamped to 0..1. Consumers should prefer exported SDK values.

Ignore Transforms removes entire subtrees. When the SDK field
`ignoreOtherPhysBones` is true, another component's root subtree is also removed,
matching the SDK's hierarchy enumeration. First/Average/Ignore multi-child modes
remain source metadata; the exporter does not pretend those solvers are identical
to a leaf-chain solver. Component enabled/active state is recorded on each entry.
The legacy omission of components without any descendant chain remains; a
root-only component with an endpoint requires corresponding allocator support.

## Validation

`tests/repair/test_unity_physbone_export_integration.py` compiles the production
exporter in an isolated real Unity 2022.3 project. It checks weighted curves,
original peak coordinates, empty and missing curves, infinite tangents, excluded
subtrees, SDK-depth samples, nonuniform lengths, transformed endpoints, and
restoration of SDK metadata. The fixture uses SDK-shaped test components and
does not redistribute VRChat assemblies or avatar assets.

Opt in with `UCHINOKO_TEST_UNITY_EDITOR` pointing at an installed Unity Editor,
then run that test with pytest. The ordinary bridge regression suite additionally
checks editor reuse, owned script updates, and preservation of local edits.

Source version and SDK field availability are retained in each export.
Keeping this metadata enables parameter conversion; it does not equate
the VRChat and Palworld physics solvers.
