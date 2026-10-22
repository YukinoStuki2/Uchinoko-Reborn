# test_pipeline_runner_multi_avatar_pak_isolation_dev1170.py -- dev#1170 WP-3
# (マルチアバターPAK作成)のラボ憲章④受入試験。
#
# オーナー確定仕様(issue #1170、2026-08-09対話): 「マルチアバターPAK作成」は
# メインパネルの通常変換(job.json/pipeline_runner.write_job())に一切接続
# しない設計。本ファイルはその無退行を機械的に固定する。
#
# test_pipeline_runner_gender_filter_dev336.py と同じfixture流儀
# (_make_app_root/_make_vrm相当をこのファイル内に複製、既存ファイルへの
# 変更を避け並行WPとの衝突を構造的に避ける方針)。
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import multi_avatar_pak_store as store  # noqa: E402
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


def _write_and_load_job(app_root, tmp_path, work_dirname="work"):
    job_json_path = pr.write_job(app_root, str(tmp_path / work_dirname), _make_vrm(tmp_path))
    with open(job_json_path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 構造的検査: pipeline_runner.py が本機能のstoreをそもそもimportしない
# ---------------------------------------------------------------------------


def test_pipeline_runner_source_does_not_import_multi_avatar_pak_store():
    """本WPの書き込み許可はapp_py配下(ui新規ダイアログ・ストア新規等)
    +pak_manager.py+i18n_data.jsonに限られ、pipeline_runner.pyは対象外
    (=そもそも配線できない設計)。ソースを直接走査して、将来うっかり
    importが足された場合に検出できるようにしておく。"""
    pr_path = os.path.join(_APP_PY_DIR, "pipeline_runner.py")
    with open(pr_path, encoding="utf-8") as f:
        source = f.read()
    assert "multi_avatar_pak_store" not in source
    assert "multi_avatar_pak_dialog" not in source
    assert "multi_avatar_pak_compose" not in source


# ---------------------------------------------------------------------------
# 出力不変(バイト完全一致相当、辞書の完全一致で検査)
# ---------------------------------------------------------------------------


def test_job_json_identical_regardless_of_multi_avatar_pak_store_state(tmp_path):
    app_root = _make_app_root(tmp_path)

    baseline = _write_and_load_job(app_root, tmp_path, work_dirname="work_baseline")

    store.save_assignments(app_root, {"Bronze001": "Alicia", "Cloth002": "Bob"})
    with_state = _write_and_load_job(app_root, tmp_path, work_dirname="work_with_state")

    assert with_state == baseline


def test_job_json_has_no_multi_avatar_pak_related_keys(tmp_path):
    app_root = _make_app_root(tmp_path)
    store.save_assignments(app_root, {"Bronze001": "Alicia"})
    job = _write_and_load_job(app_root, tmp_path)
    for key in job:
        assert "multi_avatar" not in key.lower()
        assert "assignments" != key.lower()


def test_negative_control_reset_after_populated_state_still_matches_baseline(tmp_path):
    """負の対照: reset()してもしなくても出力は同じ(=そもそも読まれていない
    ことの直接証明。resetが効いたから一致した、という別解釈を潰す)。"""
    app_root = _make_app_root(tmp_path)

    baseline = _write_and_load_job(app_root, tmp_path, work_dirname="work_baseline")

    store.save_assignments(app_root, {"Bronze001": "Alicia"})
    store.reset(app_root)
    after_reset = _write_and_load_job(app_root, tmp_path, work_dirname="work_after_reset")

    store.save_assignments(app_root, {"Bronze001": "Alicia"})
    after_populated_again = _write_and_load_job(
        app_root, tmp_path, work_dirname="work_after_populated_again")

    assert after_reset == baseline
    assert after_populated_again == baseline
