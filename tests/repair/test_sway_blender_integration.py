"""Opt-in real Blender regression; does not build a PAK or touch the source app.

Set UCHINOKO_BLENDER_FIXTURE to an external fixture directory and
UCHINOKO_BLENDER_OUTPUT to a new, empty evidence directory. The fixture must
contain fixed/ (animation-free step01), end_to_end_safe_sway/vanilla/, and
expected_checks.json with positive source_bones, pivots and unique_donors counts.
Avatar files and expected model-specific counts are deliberately not shipped.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(not os.environ.get("UCHINOKO_BLENDER_FIXTURE"),
                    reason="requires an explicitly supplied external Blender fixture")
def test_keeps_valid_dynamics_without_model_specific_overrides():
    fixture = Path(os.environ["UCHINOKO_BLENDER_FIXTURE"])
    output = Path(os.environ["UCHINOKO_BLENDER_OUTPUT"])
    expected = json.loads((fixture / 'expected_checks.json').read_text(encoding='utf8'))
    assert all(type(expected.get(key)) is int and expected[key] > 0
               for key in ('source_bones', 'pivots', 'unique_donors'))
    assert not output.exists(), "Use a fresh directory; preserve earlier evidence"
    output.mkdir(parents=True)
    shutil.copytree(fixture / "fixed" / "converted", output / "converted")
    shutil.copytree(fixture / "end_to_end_safe_sway" / "vanilla", output / "vanilla")
    atlas = output / "build" / "atlas"
    atlas.mkdir(parents=True)
    shutil.copy2(fixture / "fixed" / "build" / "atlas" / "step01_sway_snapshot.json", atlas)
    job = json.loads((fixture / "fixed" / "job.json").read_text(encoding="utf-8"))
    job.pop("sway_chain_overrides", None)
    job.pop("sway_manual", None)
    job.update(sway_enable=True, sway_intensity="normal", job_dir=str(output))
    job_path = output / "job.json"
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "D2P_NOUE_TEMPLATE_ROOT", "D2P_LAYER_CACHE"):
        env.pop(key, None)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PYTHONUTF8="1",
               PYTHONIOENCODING="utf-8", BLENDER_USER_RESOURCES=str(output / "blender_user"),
               TEMP=str(output / "temp"), TMP=str(output / "temp"))
    (output / "temp").mkdir()
    report = {"no_model_specific_overrides": True, "stages": []}
    for gender in ("Female", "Male"):
        command = [job["paths"]["blender_exe"], "--background", "--factory-startup",
                   "--disable-autoexec", "--python-use-system-env", "-t", "1",
                   "--python-exit-code", "1", "--python",
                   str(ROOT / "pipeline" / "blender" / "step02_retarget.py"),
                   "--", str(job_path), gender]
        started = time.monotonic()
        with (output / f"step02_{gender.lower()}.log").open("wb") as log:
            result = subprocess.run(command, cwd=output, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=180)
        stage = {"gender": gender, "exit_code": result.returncode,
                 "seconds": round(time.monotonic() - started, 2)}
        report["stages"].append(stage)
        (output / "result.json").write_text(json.dumps(report, indent=2))
        assert result.returncode == 0, f"see {output}/step02_{gender.lower()}.log"
        def read(stem):
            return json.loads((output / "converted" / f"{stem}_{gender.lower()}.json")
                              .read_text(encoding="utf-8"))
        gate = read("sway_source_gate")
        pivot = read("sway_pivot_axiom")
        exclusions = read("sway_exclusions")
        donors = read("sway_source_donor_map")
        stage.update(source_gate=gate, pivot_gate=pivot, exclusions=exclusions,
                     unique_donors=len(set(donors.values())))
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
        assert gate["ok"] and gate["checked"] == expected['source_bones']
        assert pivot["ok"] and pivot["checked"] == expected['pivots']
        assert not exclusions["fully_disabled"]
        # Retain independently established source counts instead of blessing
        # whatever count the converter happened to emit during this run.
        assert len(set(donors.values())) == expected['unique_donors']
        assert not ({"head", "spine_03"} & set(donors.values()))
