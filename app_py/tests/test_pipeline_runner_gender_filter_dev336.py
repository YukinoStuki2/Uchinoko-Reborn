# test_pipeline_runner_gender_filter_dev336.py -- dev#336(性別限定)。
#
# 2026-08-08 オーナー裁定「性別限定はラボ第1弾に搭載しない」(構造制約:
# DT行フラグが性別共通で除外性別の首なしが必然)により、UIレジストリ
# (app_py\ui\lab_window.py)と対にして app_py\pipeline_runner.py の
# write_job() から genders 配線自体を無効化した(gh issue view 336
# --repo pandrabox/DiveToPalworld-dev の2026-08-08コメント参照)。
#
# このファイルはもともと「F2ラボ窓の選択がjob["genders"]へ伝播すること」
# を検証していたが、UI除去後は逆に「gender_filter_store側へ選択が残って
# いても、job["genders"]は一切書かれないこと」(=既定値のときは未実装
# 状態と完全に同一というラボ憲章④の裏返し。ここではラボ機能自体が非搭載
# なので常に未実装状態)を検証する内容へ反転する。
#
# 既存の test_pipeline_runner.py と同じ fixture 流儀
# (_make_app_root/_make_vrm相当)をこのファイル内に複製する(既存ファイルへの
# 変更を避け、並行WPとの衝突を構造的に避ける方針。lab-devスキル指示
# 「並行WP衝突の構造的回避」を踏襲)。
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import gender_filter_store  # noqa: E402
import pipeline_runner as pr  # noqa: E402


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


def _write_and_load_job(app_root, tmp_path):
    job_json_path = pr.write_job(app_root, str(tmp_path / "work"), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        return json.load(f)


def test_default_no_lab_selection_omits_genders_key(tmp_path):
    """state file不在(=何も保存されていない、素の既定)なら
    job.jsonにgendersキーが一切出ないこと(=convert_noue.py側の既存既定
    解決 job.get("genders") or ["Male","Female"] にそのまま乗る)。"""
    app_root = _make_app_root(tmp_path)
    job = _write_and_load_job(app_root, tmp_path)
    assert "genders" not in job


def test_stale_male_selection_does_not_propagate_to_job(tmp_path):
    """dev#336裁定反映の直接根拠: gender_filter_store側にMale選択が
    残っていても(UIが無くなった後もstate fileだけ残るケースの模擬)、
    write_job()はそれを読まず job["genders"] は一切書かれないこと。"""
    app_root = _make_app_root(tmp_path)
    gender_filter_store.save_selected_gender(app_root, "Male")
    job = _write_and_load_job(app_root, tmp_path)
    assert "genders" not in job


def test_stale_female_selection_does_not_propagate_to_job(tmp_path):
    app_root = _make_app_root(tmp_path)
    gender_filter_store.save_selected_gender(app_root, "Female")
    job = _write_and_load_job(app_root, tmp_path)
    assert "genders" not in job


def test_negative_control_reset_after_selection_still_omits_key(tmp_path):
    """負の対照: reset()してもしなくても、job["genders"]は書かれない
    (配線そのものが無いことの確認。reset()呼び出し自体は
    gender_filter_store側の機能として引き続き有効)。"""
    app_root = _make_app_root(tmp_path)
    gender_filter_store.save_selected_gender(app_root, "Male")
    gender_filter_store.reset(app_root)
    job = _write_and_load_job(app_root, tmp_path)
    assert "genders" not in job
