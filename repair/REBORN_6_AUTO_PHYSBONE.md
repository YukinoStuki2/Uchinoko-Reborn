# Reborn.6: source-driven physics and environment lighting

New conversions default to `sway_adaptation: physbone-v1`. Existing jobs retain
their saved manual preset. Explicit per-component motion overrides still take
precedence. No avatar names or hair/tail category presets are used by this mode.

Unity exports version, integration type, 15 parameter curves with Unity-evaluated
samples, SDK depth ratios, and world geometry/scale. Final placement maps parent
segment settings to the child's simulated endpoint and remaps depth samples to
target arc length. Physics response uses continuous derived coefficients.
Neutral-pose gravity is fitted only where representable; unsupported fits are
reported. Radius includes the real torso fit and output size.

The planner tries to retain each active representative chain without dropping
other baseline active components. Native template capacity is still finite.
Branches and nested components may share their parent's simulation; colliders,
endpoint-only components, stretch, and arbitrary source constraints are not
fully converted. Reports disclose these limits rather than claiming equality
with Unity. See `docs/PHYSBONE_RESPONSE_MAPPING.md` and
`repair/PHYSBONE_EXPORT_SCHEMA.md`.

Cooked animation blueprints now support all six parameter curves with variable
key counts. Patches update tagged property and export sizes; malformed inputs
fail closed. Full conversion and fast repack load both final gender manifests,
check their input fingerprints and complete node inventory, and reject stale
or mismatched records.

New material defaults use environment lighting: shadow lift 0, BaseColor 1,
Emissive Texture Intensity 0. Zero is explicitly written to clear cached
emission. Existing explicit lift/unlit settings remain available. The old
default used 70% texture emission, explaining persistent brightness in shadows.

## Verification

Synthetic regressions cover coefficient mapping, exported curves,
geometry scale, cooked-curve round trips and stale-manifest rejection.
Optional integration inputs are documented in [validation](VALIDATION.md).
Visual lighting and motion still require testing in the game.
