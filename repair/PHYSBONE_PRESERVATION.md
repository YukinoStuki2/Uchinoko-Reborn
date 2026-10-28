# PhysBone preservation in Uchinoko Reborn

The old converter lost movement at two separate points. It disabled every
PhysBone with a rotated Angle constraint. It also replaced a root's rest
direction with the direction to a selected child, which differs for branching
chains and other valid rigs. That artificial rotation caused the existing
posture checks to reject otherwise usable physics components.

The root placement now copies the source root's actual head and tail. The
Blender placement and shared-skeleton calculation use the same resolver.
Missing or zero-length source segments retain the previous fallback. Merged
groups retain their full span. Position, weight, pivot and posture checks remain
enabled with their original thresholds.

For an Angle constraint with half-angle `a`, the converter calculates the full
angle `r` of Unity's Z-X-Y Euler rotation. That rotation angle bounds the change
in any bone axis. A rest-centred cone with half-angle `a - r` is wholly inside
the original cone, by the spherical triangle inequality. Only a positive
result is enabled automatically. This conservative bound avoids assuming a
particular axis convention in the imported skeleton. Invalid or locked inputs
cannot accidentally become KawaiiPhysics's zero-angle, unlimited setting.

Hinge and Polar constraints still require explicit selection. Their manual
compatibility mode uses a rest-centred cone capped at 15 degrees and at the
source limits. It does not reproduce the original directional constraint or
PhysBone colliders. Existing motion controls can reduce the resulting angle;
they cannot enlarge the conversion's positive angular bound.

The existing cooked animation templates still provide nine independent physics
nodes. No nodes were fabricated, and unrelated components are not merged to
evade this limit. Bone-chain fitting may reduce the number of independently
simulated segments. Full VRC physics equivalence is not claimed.

Each conversion writes `converted/sway_coverage_<gender>.json`, including
source component counts, actual final active components, explicit disabled
components, unsupported limits, capacity overflow and placement exclusions.
Globally disabling physics replaces the previous coverage report, preventing
stale success counts from surviving a later conversion.

## Validation

Targeted regression command (run from the repository root with Python and
NumPy installed):

```text
python -B -X utf8 -m pytest tests/repair/test_physbone_limit_preservation.py tests/repair/test_sway_root_rest_direction.py tests/repair/test_sway_coverage.py pipeline/py/test_sway_chain_defaults.py pipeline/py/test_sway_hub_wire.py pipeline/py/test_sway_hub.py pipeline/py/test_sway_hub_placement.py tests/repair/test_sway_degrade_retry.py -q -p no:cacheprovider
```

The angular regression was observed failing before the fix (offset Angle
components disabled and manual Hinge/Polar limits unlimited). The root-direction
regression reproduced a 27-degree error before the fix and now preserves the
root axis. A seeded matrix-based test verifies that sampled points on converted
cones remain inside source cones for arbitrary imported axes.

Additional allocator suite command:

```text
python -B -X utf8 -m pytest pipeline/py/test_sway_allocator.py -q -p no:cacheprovider -k "not lab_assignments_absent_is_pure_automatic and not lab_override_can_force_exclude and not lab_override_can_force_include_biased_chain and not acceptance_comodo and not acceptance_flathaori and not acceptance_flatapron"
```

The six excluded tests require upstream fixture files absent from the source
repository (`physbones_comodo.json`, `physbones_flathaori.json`,
`physbones_flatapron.json`). They are not counted as passing. Public synthetic
GUI fixtures remain unchanged; expectations now account for eight additional
Angle constraints becoming eligible automatically.

```text
python -B -X utf8 -m pytest app_py/tests/test_sway_pb_catalog_wp_w2c.py app_py/tests/test_sway_style_dialog_pbunit_wp_w2c.py app_py/tests/test_sway_chain_override_store_default_enabled_map_dev1572.py -q -p no:cacheprovider
```
