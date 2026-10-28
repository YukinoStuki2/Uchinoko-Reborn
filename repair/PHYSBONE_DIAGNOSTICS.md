# Dynamic-bone conversion diagnostics

Full conversion writes `converted/动态骨骼诊断报告.txt` and
`converted/sway_summary.json`. The existing completion-warning route displays a
short localized summary in Chinese, Traditional Chinese, English, Japanese or
Korean, with the text-report path. The raw `SWAY_REPORT_V1` JSON marker remains in
the conversion log for diagnosis; older English warning markers still translate.

The report combines the final `sway_coverage_<gender>.json` with older exclusion
records. Coverage wins when an earlier allocation exclusion no longer describes
the final component. Source `unit_key` identifies a component across genders:
one tail rejected for both male and female is one source component, with two
gender-specific results. Different components sharing an anchor remain separate.

Independent node allocation and final verification are separate. The report reads
`sway_source_gate_<gender>.json` and `sway_pivot_axiom_<gender>.json`; missing,
malformed or zero-check results are unknown, not a pass. A failed check lists its
failed/checked counts, at most three affected bones and three reasons per bone,
and the complete JSON path. Allocated nodes alone do not prove working physics.

Components that follow a selected parent are explicitly shown as
`nested_follow_parent`. They move using the parent's simulation, do not consume an
independent node, and do not apply their own parameters independently. Components
without an initial independent slot are reported separately; later consolidation
or safety exclusions can leave unused capacity without automatically filling it.
Disabled and unweighted components are informational. Unsupported constraints,
missing allocation, posture, pivot and weight exclusions each have different
effects and recommendations. The report never advises loosening a safety
threshold to hide a geometry or weight problem.

Invalid diagnostic rows, counters and duplicate source IDs make coverage unknown.
A failed report write produces a translated notice and logs the error; it does
not turn an otherwise completed model conversion into a failure. If the text
report cannot be saved, the dialog does not present its intended path as a saved
artifact. Share the text report, summary, coverage/exclusion/final-check JSONs and
conversion log; reproducing source hierarchy problems can also require the Unity
export. No personal model data is checked into the regression fixtures.

Validation uses a minimal curved-chain posture example (22.97 degrees against
a 16.5-degree cull limit), with neutral synthetic names for unrelated components.
Tests exercise report generation, per-gender preservation, distinct source IDs,
late final-gate failure, corrupt data, read-only destinations, and the actual
`MainWindow._on_pipeline_line` route to the translated completion list and raw log.
