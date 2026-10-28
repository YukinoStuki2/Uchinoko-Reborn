# PhysBone response mapping

The automatic converter matches a continuous, local motion response. It does
not claim that PhysBone and KawaiiPhysics are the same solver. The formulas in
`pipeline/py/sway_response.py` are independently derived from their endpoint
updates and require no VRChat SDK at runtime.

## Scope and sources

The coefficient match applies at **60 simulation steps per second**, for a fixed
pivot, small angular displacement, constant bone length, and no gravity,
collision, or active angular constraint. Outside these conditions it is an
approximation. This is substantially narrower than reproducing an entire
avatar's dynamics.

Primary sources inspected:

1. [VRChat PhysBones documentation](https://creators.vrchat.com/common-components/physbones/),
   [official documentation source](https://github.com/vrchat-community/creator-docs/blob/main/Docs/docs/common-components/physbones.md),
   blob `1af5a4fbcf78a6553df893753079b55506f59616` retrieved 2026-10-24.
2. Locally installed VRChat SDK Base **3.10.3**, `VRC.Dynamics.dll`, SHA-256
   `34177c7d681783c9c0b25727b763d920d34fc3f9619b5edc48a765ff19de3243`.
   Relevant methods: `VRCPhysBoneBase.CalcBoneRatio`, `CalcTransformRatio`,
   `CalcPull`, `CalcSpring`, `CalcStiffness`, `SafeEvaluate`, and
   `PhysBoneManager.PhysBoneJob.SolveChain` / `UpdateRootsJob.Execute`.
   The SDK's implementation was inspected locally; its implementation is not
   included in this repository.
3. [KawaiiPhysics v1.18 simulation source](https://github.com/pafuhana1213/KawaiiPhysics/blob/20241201-v1.18.0/Plugins/KawaiiPhysics/Source/KawaiiPhysics/Private/AnimNode_KawaiiPhysics.cpp),
   `Simulate`, `UpdatePhysicsSettingsOfModifyBones`, `CalcBoneLength`,
   `UpdateSkelCompMove`, `AdjustByAngleLimit`, `ApplySimulateResult`.
   Also checked against [v1.19.1](https://github.com/pafuhana1213/KawaiiPhysics/blob/20250718-v1.19.1/Plugins/KawaiiPhysics/Source/KawaiiPhysics/Private/AnimNode_KawaiiPhysics.cpp).
   The exact KawaiiPhysics version embedded in Palworld is not established.

The formulas below are mathematical descriptions, not copied solver code.

## Continuous response coefficients

Let `p` be the sampled PhysBone Pull, `m` its sampled Spring/Momentum, and `s`
its sampled Stiffness. Values are clamped to `[0, 1]` as in the SDK. Describe a
small endpoint displacement by

```text
u_next = a * (rest - position) + b * u_previous
```

At 60 Hz KawaiiPhysics first damps velocity, then pulls the resulting point
toward its pose. Consequently

```text
a = KP_Stiffness
b = (1 - KP_Stiffness) * (1 - KP_Damping)

KP_Stiffness = a
KP_Damping  = 1 - b / (1 - a)
```

When `a=1`, `b=0`; damping is immaterial because the pull erases the velocity.
Use the finite value `KP_Damping=1`.

| Source mode | a | b |
| --- | --- | --- |
| Simplified, versions 1.0 and 1.1 | `(1 - 0.99*m) * p` | `0.99*m` |
| Advanced, version 1.0 | `p / (1+s)` | `m * (1-p) / (1+s)` |
| Advanced, version 1.1 | `(1-s) * p` | `(1-s) * m * (1-p)` |

The old Advanced orientation term enlarges the direction before normalizing
it; linearizing that normalization around rest introduces `1/(1+s)`. Version
1.1 instead blends the proposed direction toward the previous direction, which
reduces the whole local step by `1-s`. Simplified ignores `s`. These differences
are why copying PB Stiffness to KP Stiffness is incorrect.

`response_coefficients(params)` returns both the KP scalars and `pull_gain`,
`velocity_retention`, source/resolved version and integration mode, status,
reference FPS, and warnings. Unknown source version explicitly falls back to
the 1.1 approximation; unknown integration explicitly falls back to Simplified.
Invalid or missing numeric inputs use SDK constructor defaults of 0.2. These
fallbacks must remain visible in the conversion report.

## Curves: sample source depth, then remap to target length

VRChat curve values are multipliers of the corresponding scalar; empty curves
evaluate as 1. Pull, Spring, Stiffness, Immobile, and Gravity Falloff are clamped
to `[0,1]` after multiplication. Gravity is signed and is not clamped by its
calculation method; radius and angle use their respective nonnegative handling.

For maximum hierarchy depth `D`, bone depth `i`, and `E=1` when a nonzero
Endpoint Position adds an endpoint:

```text
PB force/angle sample t = clamp01(i / (D + E - 1))
                         or 0 if the denominator is <= 0
PB radius sample t     = clamp01(i / (D + E))
```

The maximum is over the component's traversed hierarchy, not a separate maximum
for each branch. Ignore Transforms and Ignore Other PhysBones affect traversal.
The SDK samples a segment's radius at both its beginning and its endpoint.

KawaiiPhysics uses a different coordinate:

```text
KP t = cumulative reference bone length from root / maximum cumulative length
```

Do not copy curve time coordinates. Evaluate Unity curves at each source
sample (preferably in Unity, preserving weighted tangents and interpolation),
derive that sample's response coefficients, then create KP curve samples at
the matching target length coordinates. A long bone and a short bone each add
one step to PB depth but different amounts to KP length.

There is also an endpoint offset: PB parameters belong to the bone whose
**endpoint** is simulated; KP parameters belong to the **child position** that
rotates its parent. Therefore the first simulated KP child receives the source
root bone's parameters, and the final unweighted KP endpoint receives the last
source bone's parameters. Sampling the same-named donor would shift the curve
by one segment. KP root position is fixed; its own force settings are unused.

Do not average incompatible source components just because they receive one
node. Multiple target branches sharing the same length coordinate cannot carry
different values in one KP curve. Preserve separate nodes or report the loss.

## Immobile and frame timing

For actor translation by `+delta`, KP computes component movement as `-delta`:
WorldDampingLocation=0 cancels the local translation and preserves world
position (full inertia); 1 lets the point move with the actor (no translation
inertia). Thus direct `wdl=Immobile` has the correct direction for matching
the explicit movement-suppression term.

PB **World** mode suppresses scene-root translation only. A corresponding KP
approximation uses `wdl=Immobile, wdr=0`. PB **AllMotion** uses the root bone's
parent transform, including local skeleton animation; KP component-space
world damping cannot exactly reproduce that. `wdl=wdr=Immobile` only matches
the actor-movement part. Advanced PB Stiffness further affects moving-pivot
response, so the fixed-pivot coefficient match does not remove this difference.

The SDK schedules 60 Hz steps, at most six per render update. Fractional
remaining steps interpolate motion and retain the previous full-step state.
KP v1.18/v1.19 evaluates per animation update: its pull gain is
`1 - (1 - stiffness) ** (TargetFramerate * delta_time)`, but velocity damping
is still applied once per update as `(1-damping)`. Merely setting
TargetFramerate=60 does not turn KP into a 60 Hz fixed-step solver. Static
coefficients cannot match PB at every render rate. Validation should include
30, 60, and 120 FPS and distinguish numerical stability from visual equality.

## Features without direct scalar equivalence

| PhysBone feature | Why a direct copy fails |
| --- | --- |
| Gravity 1.0 | A segment-length-scaled directional contribution per simulation step, rather than an acceleration in centimetres per second squared. |
| Gravity 1.1 | Blends the target resting direction toward signed world down; requires positive Pull to move. KP Gravity adds constant acceleration before pull. |
| Gravity Falloff | Changes gravity according to current orientation relative to the captured rest-down direction. KP has no equivalent scalar or gravity curve in the inspected node. |
| Rotated cone / Hinge / Polar limits | KP LimitAngle is a cone around pose direction; its PlanarConstraint is tied to coordinate axes. Different constraint frames or asymmetric axes need explicit geometry handling. |
| Zero angle | PB zero may mean locked; KP zero means unlimited and must not be copied for a locked cone. |
| Stretch / Squish / Stretch Motion | KP restores the pose segment length after constraints; PB can change segment length. |
| Colliders / grab / pose | Require shape, frame, topology, and interaction conversion; no response coefficient can reproduce them. |
| MultiChild Average / First | PB's branch behavior is different from KP, whose inspected implementation only rotates parents with at most one effective child. |
| Animated rest pose | PB Is Animated explicitly changes rest transforms. A static replacement skeleton has no source animation channels unless separately transferred. |

In particular, assigning every node zero gravity is a safety heuristic, not
source reproduction. Assigning `-980 * source_gravity` is also not justified.
A nonzero source gravity/falloff needs a clearly labelled approximation or a
solver extension; it must not be silently reported as a preserved parameter.

## Optional neutral-pose gravity approximation

`sway_gravity.fit_gravity(samples, source_version)` implements a deliberately
limited static fit for known PB 1.1 components. It returns the approximation
status and warnings alongside `gravity_z`; it does not change source rest
transforms or claim to preserve dynamic gravity falloff.

At initialization the SDK captures world down in each source bone's local
coordinates. At that same neutral pose, transforming it back to world space
gives world down, so the falloff factor becomes `1 - falloff`. Full falloff
therefore gives zero neutral gravity exactly.

Let `n_i` be the final segment's rest unit direction, `L_i` its length in
centimetres, `a_i` its derived KP pull gain, and `d=(0,0,-1)` world down in UE:

```text
e_i = source_gravity_i * (1 - source_gravity_falloff_i)
t_i = normalize((1 - abs(e_i)) * n_i + e_i * d)
c_i = (1 - a_i) / (2 * 60^2)
P_i = I - t_i * transpose(t_i)
```

KP's static normalized endpoint balance requires
`P_i (a_i L_i n_i + c_i G d) = 0`, where `G` is acceleration toward world down.
For one shared node minimize the sum of squared residuals across its segments:

```text
G = -sum(c_i * a_i * L_i * dot(P_i n_i, P_i d))
      / sum(c_i^2 * dot(P_i d, P_i d))
GravityZ = -G
```

This derives force from actual geometry and response coefficients. It is not
an empirical universal multiplier. A relative residual above 0.1 rejects the
fit, as do non-finite or underdetermined solutions, an opposite resulting
direction, invalid geometry, and a target outside the cooked cone. PB 1.0 or
unknown versions return explicit zero fallback. Positive source gravity with
zero pull cannot move a PB 1.1 bone, so that sample's neutral target remains its
rest direction. Conflicting targets within one node cannot be silently averaged
and reported as equivalent.

Even an exact static fit changes initial acceleration and transient behavior.
It is valid only for the captured neutral pose at the stated rate. A node that
needs different gravity for different segments or changing falloff with pose
requires richer runtime support for a closer match. The report must retain
these warnings. The fitted acceleration must not be silently clamped by a
separate legacy manual-control range.

## Verification

`tests/repair/test_sway_response.py` independently simulates unit-length PB and
KP steps in 2D. It compares 240-step small-angle responses for both integration
modes and versions, and numerical Jacobians for independently measured pull and
velocity gains. Additional cases cover continuity, full pull, unknown metadata,
non-finite values, and clamping. Run:

```text
python -B -m pytest tests/repair/test_sway_response.py -q -p no:cacheprovider
```

Passing these tests validates the scoped coefficient derivation. It does not
validate a particular model's topology, parameter export, cooked curve bytes,
runtime animation instance, or visual behavior; those require separate checks.

`tests/repair/test_sway_gravity.py` independently evolves the KP endpoint for
3000 iterations and compares its final direction with the PB neutral target.
It also checks scale dependence, shared-node residuals, full falloff, zero pull,
unsupported source versions, cone conflicts, and degenerate input.
