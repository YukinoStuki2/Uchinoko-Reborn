"""Actual Unity evaluation/serialization; opt in with a local Unity 2022.3 path.

No SDK assemblies or user assets are copied. The fixture creates a temporary
project and uses the production exporter with SDK-shaped test components.
UCHINOKO_TEST_UNITY_PROJECT optionally reuses an explicitly marked fixture
project across red/green runs; it never accepts an existing avatar project.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app_py"))
import unity_editor_bridge as bridge


@pytest.mark.skipif(not os.environ.get("UCHINOKO_TEST_UNITY_EDITOR"), reason="Requires a local Unity Editor")
def test_curves_and_geometry_survive_real_unity_export(tmp_path):
    editor = Path(os.environ["UCHINOKO_TEST_UNITY_EDITOR"])
    project = Path(os.environ.get("UCHINOKO_TEST_UNITY_PROJECT", tmp_path / "PhysBoneExport")).resolve()
    marker = project / ".uchinoko-physbone-test-project"
    if project.exists() and any(project.iterdir()):
        assert marker.is_file() and marker.read_text(encoding="utf-8") == "physbone-export-fixture-v1\n", \
            "Refusing to modify an existing non-fixture Unity project"
    project.mkdir(parents=True, exist_ok=True)
    marker.write_text("physbone-export-fixture-v1\n", encoding="utf-8")
    (project / "Assets/Editor").mkdir(parents=True, exist_ok=True)
    (project / "ProjectSettings").mkdir(exist_ok=True)
    (project / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 2022.3.22f1\n")
    (project / "Packages").mkdir(exist_ok=True)
    (project / "Packages/manifest.json").write_text(json.dumps({"dependencies": {
        "com.unity.modules.animation": "1.0.0", "com.unity.modules.physics": "1.0.0",
        "com.unity.modules.jsonserialize": "1.0.0", "com.unity.modules.imgui": "1.0.0",
        "com.unity.modules.imageconversion": "1.0.0",
    }}))
    bridge.install_bridge(project, ROOT)
    shutil.copyfile(Path(__file__).with_name("unity_physbone_export_fixture.cs"),
                    project / "Assets/Editor/UchinokoPhysBoneExportFixture.cs")
    output = project / "probe-output"
    # A red run must not consume a prior successful run's stale sidecars.
    for name in ("physbones.json", "expected.json"):
        (output / name).unlink(missing_ok=True)
    log = tmp_path / "unity.log"
    result = subprocess.run([str(editor), "-batchmode", "-nographics", "-projectPath", str(project),
                             "-executeMethod", "UchinokoPhysBoneExportFixture.Run", "-quit", "-logFile", str(log)],
                            timeout=240, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log_text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else "Unity did not create its log"
    assert result.returncode == 0, f"Unity exit {result.returncode}: {log_text[-16000:]}"
    assert "UCHINOKO_PHYSBONE_DESTROYED_OTHER_ROOT_READY" in log_text
    assert "UCHINOKO_PHYSBONE_EXPORT_PROBE_OK" in log_text
    assert (output / "physbones.json").is_file(), "Destroyed sibling root must not discard every PhysBone"
    data = json.loads((output / "physbones.json").read_text(encoding="utf-8"))
    expected = json.loads((output / "expected.json").read_text(encoding="utf-8"))
    assert expected["indexRestored"], "Do not leave SDK instance metadata mutated"
    assert expected["destroyedRootIsUnityNull"] and expected["destroyedRootHasManagedReference"]
    assert expected["destroyedRootFieldPreserved"], "Export must not mutate the SDK root reference"
    assert data["schema_revision"] == 2
    pb = next(item for item in data["physbones"] if item["anchor"] == "Anchor")
    fallback = next(item for item in data["physbones"] if item["anchor"] == "OtherRoot")
    assert fallback["anchor_explicit_root"] is False
    assert fallback["chains"] == [["OtherTip"]], "A destroyed explicit root falls back to the live component transform"
    assert pb["chains"] == [["Segment1", "Segment2", "Segment3", "Segment4"]]
    assert pb["enabled"] is True and pb["active_in_hierarchy"] is True
    params = pb["params"]
    assert params["version"] == "Version_1_1"
    assert params["integration_type"] == "Advanced"
    assert params["ignore_other_physbones"] is True
    curves = params["curves"]
    assert curves["pull"]["keys"] == []
    assert {point["value"] for point in curves["pull"]["samples"]} == {1}
    assert curves["gravity"] is None, "Absent SDK fields are not empty/default curves"
    spring = curves["spring"]
    assert spring["keys"][0]["weighted_mode"] == 3
    assert spring["keys"][0]["out_weight"] == pytest.approx(.7)
    assert spring["pre_wrap"] == "ClampForever" and spring["post_wrap"] == "Loop"
    samples = {round(point["time"], 5): point["value"] for point in spring["samples"]}
    assert samples[.2] == pytest.approx(expected["weightedAtPointTwo"])
    assert samples[.23] == pytest.approx(.8), "Keep original narrow peak coordinates"
    assert curves["max_angle_x"]["keys"][0]["out_tangent"] == "Infinity"
    geometry = params["geometry"]
    assert geometry["max_chain_index"] == 4 and geometry["endpoint_nonzero"] is True
    assert geometry["ratio_source"] == "sdk"
    transforms = {item["name"]: item for item in geometry["transforms"]}
    assert transforms["Segment1"]["force_ratio"] == pytest.approx(.25)
    assert transforms["Segment1"]["transform_ratio"] == pytest.approx(.2)
    assert transforms["Segment4"]["depth"] == 4
    assert transforms["Segment1"]["lossy_scale"] == pytest.approx([2, 2, 2])
    chain = geometry["chains"][0]
    assert chain["segment_lengths"] == pytest.approx([.02, .6, .2, .4], abs=1e-6)
    assert chain["total_length"] == pytest.approx(1.22, abs=1e-6)
    assert chain["endpoint_world"] == pytest.approx([expected["endpointWorld"][axis] for axis in "xyz"])
