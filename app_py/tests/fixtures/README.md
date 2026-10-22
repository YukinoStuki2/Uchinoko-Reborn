# Public synthetic test data

`physbones_synthetic_35.json` is invented test data for the published PhysBone sidecar schema. It contains no exported model data, private names, geometry or creator assets. It is provided under the repository MIT license.

It exercises the catalog and hidden Tk dialog through their actual JSON-reading paths:

- 10 hinge units, 8 polar units and 8 angle units with an offset cone center: 26 units requiring forced setup.
- 5 unlimited units (with deliberately irrelevant rotation values) and 4 centered angle units: 9 ordinary units.
- 35 components total, with mixed single and multiple chains. The catalog must keep one row per component and the dialog must process all 26 biased rows, even above the legacy 9-slot limit.

The original upstream tests referred to a missing `physbones_flathaori.json` derived from a private model. The public tests now name and use this artificial fixture explicitly. This preserves the testable catalog/dialog contracts, not a claim that the original model has been revalidated. The Reborn conversion pipeline is unchanged.
