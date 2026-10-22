# test_pipeline_runner_shapekeys_dev1168.py -- dev#1168(シェイプキー)ラボ機能。
#
# pipeline_runner.write_job()がjob["shape_keys"]を組み立てる配線の単体試験。
# ラボ憲章④(既定値のときは未実装状態と完全に同一)の柱:
#   (a) shapekey_filter_store未設定(既定)なら job に "shape_keys" キー自体が
#       出ない(キー不在=既定値、equipment_filter/headequip_showと同じ設計)
#   (b) 現在のvrm_pathに対して設定済みならjob["shape_keys"]へそのまま反映
#   (c) 別アバターに対する残留設定は反映されない(shapekey_filter_store自身の
#       avatar_path一致判定に委譲、ここではwrite_job()がそれをそのまま
#       尊重していることだけを確認する)
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pipeline_runner as pr  # noqa: E402
import shapekey_filter_store  # noqa: E402


def _make_app_root(tmp_path, with_blender=True, with_addon=True):
    app_root = tmp_path / "app_root"
    app_root.mkdir()
    if with_blender:
        blender_dir = app_root / "tools" / "blender-4.3.2-windows-x64"
        blender_dir.mkdir(parents=True)
        (blender_dir / "blender.exe").write_bytes(b"")
    if with_addon:
        (app_root / "third_party").mkdir()
        (app_root / "third_party" / "VRM_Addon_for_Blender-Extension-4_4_0.zip").write_bytes(b"")
    return str(app_root)


def _make_vrm(tmp_path, name="MyAvatar.vrm"):
    vrm = tmp_path / name
    vrm.write_bytes(b"")
    return str(vrm)


def test_write_job_omits_shape_keys_key_by_default(tmp_path):
    app_root = _make_app_root(tmp_path)
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert "shape_keys" not in job, "未設定(既定)なのにjob['shape_keys']キーが出ている"


def test_write_job_includes_shape_keys_when_configured_for_current_avatar(tmp_path):
    app_root = _make_app_root(tmp_path)
    vrm_path = _make_vrm(tmp_path)
    shapekey_filter_store.save_config(
        app_root, vrm_path, {"Body": {"smile": 0.5, "blink": 1.0}})

    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), vrm_path)
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)

    assert job.get("shape_keys") == {"Body": {"smile": 0.5, "blink": 1.0}}


def test_write_job_ignores_config_saved_for_a_different_avatar(tmp_path):
    """負の対照: 別アバターに対して保存された設定は、今回のvrm_pathでは
    一切反映されない(誤爆防止、shapekey_filter_storeのavatar_path一致判定
    をwrite_job()がそのまま尊重していることの確認)。"""
    app_root = _make_app_root(tmp_path)
    other_vrm = _make_vrm(tmp_path, "Other.vrm")
    shapekey_filter_store.save_config(app_root, other_vrm, {"Body": {"smile": 1.0}})

    current_vrm = _make_vrm(tmp_path, "Current.vrm")
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), current_vrm)
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)

    assert "shape_keys" not in job


def test_write_job_shape_keys_key_absent_when_all_values_are_zero(tmp_path):
    """負の対照: 値が全て0(=save_config()側で保存自体されない)なら、
    やはりjob["shape_keys"]は出ない。"""
    app_root = _make_app_root(tmp_path)
    vrm_path = _make_vrm(tmp_path)
    shapekey_filter_store.save_config(app_root, vrm_path, {"Body": {"smile": 0.0}})

    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), vrm_path)
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)

    assert "shape_keys" not in job


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
