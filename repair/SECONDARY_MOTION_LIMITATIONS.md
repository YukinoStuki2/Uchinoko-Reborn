# Secondary motion limitations and tree-preservation design

This document records conversion boundaries and a proposed interface.
It does not certify in-game behavior or include private model evidence.

Hair, ears, scarves, clothing, ribbons, and tails must use the same PhysBone
conversion rules. Source version, integration mode, geometry, curves, limits,
and collider data determine the result. Avatar names and body-part labels must
not select hidden strength multipliers. User adjustments should be explicit
overrides of that shared mapping.

Primary source references and solver assumptions are recorded in
[PHYSBONE_RESPONSE_MAPPING.md](../docs/PHYSBONE_RESPONSE_MAPPING.md).
Local SDK inspection files and avatar exports are not redistributed.

## Angle cones: measure axis displacement, not total rotation

The inspected SDK first aligns local +Y to the rest bone vector. It composes
that alignment with `Unity.Mathematics.quaternion.EulerXYZ(limitRotation)` and
uses the resulting +Y direction as the Angle cone axis. The common alignment
preserves angles, so the offset from the unmodified rest direction is:

```text
delta = angle(+Y, EulerXYZ(x, y, z) * +Y)
cos(delta) = cos(x) cos(z) + sin(x) sin(y) sin(z)
inner_cone = sampled_max_angle_x - delta
```

Angles inside the trigonometric formula are radians. Clamp the dot product to
`[-1, 1]` before `acos`. Reject nonfinite input. The old total-quaternion-angle
bound used Unity `Quaternion.Euler` Z-X-Y semantics; it both measured the wrong
quantity and assumed a different Euler convention from this SDK method.

A pure Y twist does not tilt an Angle cone. The baseline `SideD.001` has an
Angle of 30 degrees and rotation `[0, 90, 0]`: its axis offset is zero, although
the old bound rejected it. Correcting this mathematical rule can make that
component eligible; allocation and placement still need to succeed.

This correction barely changes the scarf root:

| Quantity at source root | Degrees |
| --- | ---: |
| Source maximum, `61 * 0.120568156` | 7.354657516 |
| Old bound for `[5, 0, 5]` | 7.069945578 |
| Actual SDK cone-axis offset | 7.066574389 |
| Old rest-centred inner cone | 0.284711938 |
| Correct rest-centred inner cone | 0.288083127 |

The scarf's small root movement is consequently not cured by the axis fix.
Its source cone is tilted almost to the edge of the unmodified rest direction.
A rest-centred inner cone is a conservative approximation of that offset cone;
matching the source's full directional range needs a backend that can retain
the offset constraint frame. Do not enlarge its angle by a scarf-specific
factor. Zero in KawaiiPhysics means unlimited, so a locked or unsupported
source constraint must never become zero merely to make it move.

Acceptance for this rule: compare arbitrary finite rotations with an
independent EulerXYZ matrix implementation; verify pure Y twist, mixed-axis
rotations, zero/invalid input, and sampled curves. Preserve a test for the
baseline scarf calculation and a test for a generic 30-degree cone with a
90-degree Y twist. Those fixtures need no avatar-name branching.

## Scarf tree: currently active, but branches are collapsed

The source `muffler.001` component contains a shared chain
`muffler.001 -> muffler.002 -> muffler.003`, followed by three separate
three-bone fringe branches. That is **12 unique bones including the root**.
The baseline report's `source_bones=15` sums the three paths without the root,
counting their shared section repeatedly; it is not a unique-bone count.

Both genders map the 12 source bones to six independent weighted donor bones.
Each depth of fringe A, B, and C shares one donor transform. Three more donor
bones are unweighted chain endpoints. The `preserved=true` flag refers to the
six-bone representative path; it does not mean all three branches survive.
The current behavior comes from [select_tuft_representative](../pipeline/py/sway_hub.py)
and `expand_tuft_weight_mapping`: only the representative branch provides
geometry, and the other branches share its depth-based weight mapping.

There is a separate semantic loss. The source uses `multi_child_type=Ignore`.
At `muffler.003`, which has three children, the inspected SDK leaves that
branch-point transform unsimulated while its descendants continue through
their own chains. The representative-chain conversion instead treats one
fringe as its only continuation. It therefore loses both branch independence
and the source branch-point behavior. The source mode must be represented
explicitly; blindly splitting each path into an independent root would also
be wrong because the common moving parent must remain shared.

Actual cooked scarf settings agree between genders: stiffness 0.108, damping
approximately 0.8896861, movement/rotation damping 0.2, zero gravity, no wind,
and no sphere/capsule limits or limit assets. Source gravity is 0.5 with
falloff 1.0; zero is the existing neutral-pose fit, not preservation of its
orientation-dependent response. One source collider was exported as metadata
but is not reproduced in the cooked node.

Acceptance for future tree support: preserve all 12 unique source-bone
identities and the three parent-child branches, retain independent fringe
motion, honor Ignore at the fork, and keep the shared attachment continuous.
The conversion report must identify any merged branch, omitted collision, or
approximated force. A per-segment rest-pose and motion check is required in
addition to a successful build; visual checks must include both genders,
preview and gameplay, standing and locomotion.

## Coverage and backend limits

The saved baseline has 70 source components. Both genders report 7 active,
11 capacity overflows, 46 unsupported limits, 2 nested followers, and 4 with
no weighted descendants. Five source entries are disabled alternative
components; the baseline allocator did not honor their exported activation
flags. They must be distinguished from genuinely eligible missing dynamics.

Among the original head-attached components, 5 are active, 7 exceed capacity,
6 fail constraint conversion, and 4 have no weighted descendants. Among the
36 body-clothing/ribbon components, only the scarf is active; the other 35
fail constraint conversion. There is no separately identifiable ear PhysBone
in this source metadata. Donor names containing `ear` are reused for other
head-attached source chains and do not prove source ears are simulated.

The cooked templates provide **nine available independent allocation slots**.
The baseline truncates candidates before removing two nested followers, so
two slots remain unused. Refilling capacity can improve coverage without
increasing that budget; it cannot preserve dozens of independent components
or turn a single chain into a faithful tree. Parent containment, unique
ownership, and ordering must be resolved before the final capacity decision.

Directional limits remain another constraint: 31 source Polar and 7 positive
Hinge entries are excluded in this baseline. Four ribbon entries lie exactly
on their offset Angle cone boundary even using the correct axis calculation.
A single symmetric rest-centred cone cannot reproduce these constraints.
Any bounded compatibility approximation must remain explicit in the report.
None of these exclusions justifies converting an unsupported constraint into
unlimited motion.

Source collider geometry/frames, dynamic gravity falloff, interactions, and
First/Average multi-child behavior require more than scalar parameter fitting.
The current coefficient match is scoped to 60 Hz near-rest response; refer to
the response-mapping document for its assumptions and FPS differences.

## Proposed minimum interface for tree preservation

This is a design boundary, not an implemented API. Keep the existing shared
PhysBone parameter mapping and give it an explicit topology description:

1. `read_source_tree(component, geometry) -> SourcePhysicsTree`
   preserves a component identity distinct from its anchor name, enabled and
   active flags, source behavior version, parent links, rest transforms,
   weights, endpoint position, SDK depth/ratio samples, multi-child mode,
   constraints, and collider references. It returns unique bones rather than
   repeated root-to-leaf path counts. Missing data is recorded explicitly.
2. `plan_tree(tree, backend_capabilities, available_slots) -> MotionPlan`
   assigns stable source-bone ownership and target parent links, identifies
   simulated segments and unsimulated branch points, and chooses node
   boundaries. The plan reports required capacity, merged or unsupported
   branches, and collider/constraint approximations before writing assets.
   Shared ancestry cannot be duplicated into competing physics nodes.
3. `sample_tree_profile(tree, plan, target_geometry) -> NodeProfiles`
   reuses the same source version/integration/curve formulas for every part.
   Source force ratios belong to the simulated source segment; target curve
   coordinates use actual target length. If two branches require incompatible
   values at the same target curve coordinate, the planner must separate them
   where supported or report a downgrade. Averaging silently is not faithful.
4. `emit_and_validate(plan, profiles) -> CoverageReport`
   emits assets and independently reads back target parents, rest transforms,
   bone ownership, roots, sampled constraints, and collision references.
   Reports distinguish `unique_source_bones`, `independent_target_bones`,
   `source_branches`, `independent_branches`, `merged_branches`, and each
   unsupported feature. Legacy path-count fields may remain for compatibility.

`backend_capabilities` must describe actual support: independent node budget,
tree-shaped donor topology, parent rotation at forks, linked-node attachment,
per-node curve expressiveness, offset/directional limits, and collider types.
KawaiiPhysics recursively visiting children does not by itself prove faithful
First/Average behavior. Gate support on inspected solver behavior and a
reproducible fixture, not on the existence of a field.

Minimum fixtures are: a serial chain, a three-branch tree with a shared stem,
nested components with distinct parameters, duplicate anchor names with
different identities/activation states, and branches with unequal lengths and
different curve samples. Exercise Ignore, First, and Average separately.
Keep capacity bounded and verify no repeated model scanning or per-frame Lua
repair is introduced. Actual game validation must cover 30/60/120 FPS and
animation transitions; static asset checks cannot certify equivalent dynamics.

Until those conditions pass, describe the output as representative-chain
conversion with reported losses. No automatic converter can truthfully promise
perfect Unity motion for all parts while those capabilities remain absent.
