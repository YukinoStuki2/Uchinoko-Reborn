# Fixed model output directory

The main window has an **Output directory…** button beside the automatic-apply
option, with the current path shown next to it. Its dialog provides an editable
path, Browse, Open folder and Save and use. Saving validates the destination,
persists the preference first, then refreshes the model list and previews.
Changing the preference does not move existing files. Conversion, Unity export
and cache preparation must finish before switching.

The shared preference is a UTF-8 absolute path in
`%APPDATA%/UchinokoReborn/settings_workroot.txt`. `LOCALAPPDATA` and then
`~/.config/UchinokoReborn` provide platform fallbacks for the configuration
directory. `UCHINOKO_REBORN_SETTINGS_DIR` explicitly overrides its directory for
portable deployments and isolated tests. The preference has no application
version in its path. Save failures retain the previous live setting; malformed
or inaccessible configured destinations block conversion instead of quietly
writing to the installation's `res/work`.

Each model keeps its own job subdirectory and its corresponding `<name>_export`
directory under the selected root. Job generation, prefab exports, preview
freshness/restoration, model listing, diagnostics, and warm-cache job preparation
use the same active root. The launcher's explicit `D2P_SHARED_CACHE` remains the
common cache override used by the physics pipeline, warm-up and cache cleanup;
equipment-name caches now follow the same rule, so selecting a model directory
does not create a second large shared cache when that override is present.

Historical model directories may be represented by directory junctions. They
remain readable for previews, settings restoration and package import. Conversion
and Unity export refuse to overwrite such entries and ask for a new model name
or another output directory. Automatic conversion retry never cleans a linked
job. Deleting a linked model removes only its library entry, preserving the
external target. Delete target validation uses lexical absolute paths rather than
resolving a junction into its historical location.

`tests/repair/test_fixed_output_directory.py` exercises a real Tk settings dialog
through job writing, Unity-export arguments, listing and restoration; it checks
cross-version startup, invalid preferences, write failures, busy transitions,
common-cache agreement, and real Windows junction read/write/delete boundaries.
