# Export while Unity remains open

Uchinoko Reborn can export a saved prefab from a project that is already open in
Unity 2022.3. It reuses that Editor through a small local bridge. Other Unity
projects may remain open as well. No Unity installation or project copy is needed.

1. Save the avatar's **prefab** changes in Unity.
2. Select that prefab in Uchinoko Reborn as usual.
3. On the first export, focus Unity once so it imports the bridge. If you disabled
   Auto Refresh, use **Assets > Refresh** (`Ctrl+R`). Subsequent exports reuse it.

The exporter processes a temporary copy in an isolated preview scene. It does not
save your scene, close the Editor, alter the project's lock, or export unsaved
Hierarchy/Prefab Mode edits. Leave Play mode before exporting. Compilation errors
must be fixed in Unity first. The Editor is busy during the synchronous export;
continue editing after completion.

The bridge adds three small scripts and an ownership record under
`Assets/Editor/UchinokoRebornBridge`. It uses the existing conversion pipeline,
including PhysBone extraction. If Unity's FBX Exporter is missing, the running
Editor's package manager installs version 4.2.1 once and keeps it installed.
Bridge updates preserve backups under `Library/UchinokoRebornBridge/backups` and
refuse to overwrite locally edited bridge scripts. Project assets are not copied.

To remove the bridge, run this from the Reborn source directory with Python:

```powershell
python app_py/unity_editor_bridge.py --project "D:\MyAvatarProject" --remove
```

This removes only owned, unmodified bridge files. It preserves unrelated files,
diagnostics/backups, and the FBX Exporter package. Refresh Unity afterwards.

## Validation

The lock regression test runs the real PowerShell entry point while Windows holds
an exclusive `UnityLockfile`: the former version fails with “Close Unity”; the
updated version routes the export to the running Editor. Automated tests also
cover ownership checks, cancellation cleanup, simultaneous clients, saved-prefab
boundaries, request identity, and output validation.

A local Unity 2022.3.22f1 Editor integration test uses a separate, minimal project
and a generated humanoid prefab. It verifies a successful FBX/sidecar export while
the Editor stays open, an unsaved test scene remains unsaved, a clean scene stays
clean, and no temporary root objects remain. A separate run keeps Prefab Mode
open with unsaved edits intact. The user's open avatar project is not used
or modified by that test. This is not a claim that every third-party Editor plugin
supports running its bake operation from a preview scene.
