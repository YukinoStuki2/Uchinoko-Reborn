# Curved and nested PhysBone chains

A curved source chain exposed two comparison defects and a limitation of the existing
cooked physics backend. This repair leaves the 16.5-degree posture cutoff,
weight tolerances, pivot validation and nine-node capacity unchanged.

The first tail group merges `tail.001` through `tail.004`. Placement correctly
uses the first head and last tail as the donor span, but the old precheck
compared that donor with the last source bone alone. The original source
geometry reproduces a 22.9679577769-degree difference despite correct placement.
The precheck and final source gate now derive the expected full span from the
independent source snapshot and the ordered fitting boundaries. The regression
exercised the production precheck and failed with the original 22.97-degree
exclusion before the fix. A rotated donor still fails the original cutoff.

Nested components also overlap the parent's source inventory. The existing
source-to-donor mapper resolves each source to its final owner, while the old
weight gate still summed all original parent members. Effective source groups
now partition ownership consistently, retaining independent source weights as
the baseline. If a child owns the parent's old geometry representative, another
source on the parent donor carries the check for the original span. Accidental
collisions between unrelated donor groups still fail validation.

Independent child physics nodes in this backend attach to humanoid ancestors.
That would leave the tail tips attached to the pelvis while the main tail
moves. Selected components fully nested in a selected parent therefore follow
the parent's simulator as a compatibility mode. Containment requires every
ordered child path to occur inside an ordered parent path, with a distinct
descendant root and a strictly smaller source-bone set. Names and partial
overlap do not qualify. This happens after capacity selection; released slots
do not enable unrelated overflow components.

Coverage reports keep the child component and its settings, marking it
`nested_follow_parent`, with `parent_unit_key` and
`independent_parameters_applied: false`. Child-specific constraints and motion
settings are not independently simulated. Explicitly disabling the parent
allows the selected child to run independently on a subsequent conversion.
If a parent fails a later placement check, the child is reported as
`nested_parent_unavailable`; retries do not fabricate an unbuilt child node.

Validation commands, from the repository root:

```text
python -B -X utf8 -m pytest tests/repair/test_sway_merged_rest_direction.py tests/repair/test_sway_nested_component_weights.py tests/repair/test_sway_nested_follow_parent.py tests/repair/test_sway_degrade_retry.py tests/repair/test_sway_root_rest_direction.py tests/repair/test_sway_coverage.py pipeline/py/test_sway_source_gate.py pipeline/py/test_sway_hub.py pipeline/py/test_sway_hub_wire.py pipeline/py/test_sway_hub_placement.py pipeline/py/test_sway_hub_tuft_merge.py pipeline/py/test_sway_pivot_axiom.py -q -p no:cacheprovider
```

The optional model integration check retained seven independent components and two
components following the main tail. Both gender variants passed all 68 source
bone checks and all seven pivot checks. Conversion and topology checks cannot
replace observing the resulting motion in the game.
