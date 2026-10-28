# Long-chain segment preservation

Reborn.5 adds an opt-in `preserve_segments: true` field to the existing
per-component chain overrides. The motion editor persists it independently of
the scalar motion profile. Existing conversions keep their old behavior.

The legacy native-hub allocator compressed a long source chain to the small
native donor inventory even when hundreds of unused skeleton bones remained.
A long source chain can otherwise collapse to only a few donor joints. Increasing motion amplitude cannot restore those missing joints.

For supported shared hubs with a native descendant chain, the new path reserves
the baseline allocations of other components, then extends the chosen chain
with existing free bones in increasing skeleton-index order. Common humanoid
bones, physics roots and their reserved descendants, and known animated bones
are excluded. At least one unweighted terminal is retained. Unsupported slots
or insufficient inventory reject the whole component with a diagnostic.

The mesh builder now includes the entire explicitly preserved final subtree,
including its unweighted terminal. Weight-only discovery previously omitted
that terminal and requested a legacy synthetic leaf instead. This change is
scoped to opted-in subtrees and does not delete existing mesh bones. Incomplete
sidecars and failed preserved-chain reparent operations fail clearly.

Coverage reports show source joints, independent donor mappings, unweighted
terminals, remaining merged branches, and whether preservation was effective.
Regression commands:

```text
python -B -m pytest tests/repair/test_sway_preserve_segments.py tests/repair/test_sway_preserve_mesh_chain.py tests/repair/test_sway_coverage.py tests/repair/test_sway_report.py -q -p no:cacheprovider
python -B -m pytest app_py/tests/test_sway_motion_controls_reborn.py -q -p no:cacheprovider
```

This remains experimental until observed in game. The known-animation exclusion
list is historical evidence, not an exhaustive list of every animation track.
Secondary branches still merge into a representative chain; nested components
follow their parent, and VRC colliders/solver behavior are not reproduced.
Static topology and parameter checks establish eligibility for simulation,
not the resulting amplitude or visual softness.
