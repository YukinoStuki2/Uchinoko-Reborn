# Reborn 13: conservative garment roots

The optional **Conservative skirt (experimental)** setting requires automatic
PhysBone conversion and a full rebuild. It defaults off. A failed experimental
build no longer retries with all secondary motion disabled.

The previous allocator correctly rejected Polar constraints that cannot be
represented by a symmetric KawaiiPhysics cone. Simply enabling those components
would also consume the nine slots already used by hair, tails and accessories.
This mode accepts a compatible family of real, enabled sibling skirt PhysBones
below the hips. It preserves independent pivots and every source joint, then
adds an unweighted simulation endpoint to each chain. Branching, animated,
stretching, overlapping or incompatible families remain rejected with a reason.

The extra simulator uses the existing evaluated tenth node in the cooked male
cloth graph. The female variant uses that graph after validating the shared
interface and all nine existing node settings. Only self names change; native
graph exports are retained. `AdditionalRootBones` supplies separate roots, not
one shared moving hub. Source-derived response curves are bounded to at most
three degrees per segment; gravity, wind and unconverted collisions are disabled.
Unity's Polar direction frames and thigh colliders are **not** equivalent in
this mode. Visible motion and clipping still require game testing.

New donors are original leaf bones, disjoint from existing allocations and
protected native player mesh bones, including headgear missing from the conversion
template. This inventory is read from the user's game PAK; unreadable or incomplete
inputs stop the experimental conversion. Their indices preserve parent-before-child order
in the shared skeleton. Source positions and weights receive a separate final
gate; complete subtrees, including unweighted tips, must survive mesh cooking.
PAM 1.0.33 or newer recognizes and privately renames the additional roots.

Validation performed with a local licensed prefab and cooked templates:

- 24 independent skirt chains, 96 weighted source joints, 120 target bones.
- Both genders passed source position, direction, weight and fixed-pivot checks.
- Existing nine components retained their parameters, curves and bone layout.
- All twenty cloth templates passed graph/node preservation and array parsing.
- Full model PAK passed preflight, including mesh and shared-skeleton checks.
- Synthetic regressions cover malformed metadata, stale repacking, donor
  collisions, float32 curve coordinates and preservation of simulation tips.

No prefab, exported texture, model, game template, path setting or build cache
belongs in the source repository. Native game validation remains outstanding.
