# Validation and source release checks

Public regressions use synthetic data. Run from a clean source checkout:

```powershell
python -m pytest tests/repair -q -p no:cacheprovider
python -m pytest app_py/tests -q -p no:cacheprovider
```

Optional integration checks require a separately installed Unity Editor,
licensed runtime templates, or explicitly supplied private Blender fixtures.
Missing optional inputs must be reported as skipped rather than passing.
No avatar files, conversion outputs, model catalogues or personal settings
are provided in this repository. Private validation notes remain outside Git.

`test_clean_source_build.py` exercises the real local builder with synthetic
private settings and model records inserted in its inputs. It verifies that a
fresh installation has an empty model library and no inherited source paths.
`test_local_source_update.py` checks source-only updates, ownership boundaries
and rollback while preserving an existing user's settings and models.

For a locally built installation, run `repair/smoke_local.py` with its path.
That check covers interpreter/Tk initialization, isolated runtime paths and
source hashes. It does not launch a conversion or validate gameplay.

Blender geometry, source-bone, pivot, cooked-asset and static-preview checks
cannot establish the in-game animation or physical response. Validate walk/run,
turns, equipment, previews and different frame rates separately before release.
