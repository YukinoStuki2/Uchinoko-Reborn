# -*- coding: utf-8 -*-
"""dev#1170 WP-3: pak_manager.py側のマルチアバターPAK作成向けAPI
(entry_is_multi_avatar/partition_library_entries_for_multi_avatar_pak)の単体
試験。

_make_saved_entry()はtest_pak_manager_avatar_library_dev1170.py(WP-1)と同じ
フィクスチャ流儀の複製(既存ファイルへの変更を避け、並行WPとの衝突を構造的に
避ける方針、lab-devスキル指示の踏襲)。
"""
from __future__ import annotations

import json
import os
import sys
from unittest import mock

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pak_manager  # noqa: E402

_ROOT_DIR = os.path.dirname(_APP_PY_DIR)
_PIPELINE_PY_DIR = os.path.join(_ROOT_DIR, "pipeline", "py")
if _PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_PY_DIR)
import vp_avatar_library as val  # noqa: E402
import vp_equipment_avatar as vea  # noqa: E402


def _fake_extract_atlas(pak_path, out_png_path):
    os.makedirs(os.path.dirname(out_png_path), exist_ok=True)
    with open(out_png_path, "wb") as f:
        f.write(b"FAKE_ATLAS")
    return out_png_path


def _make_saved_entry(tmp_path, work_root_name="work", entry_id="Alicia"):
    work_root = str(tmp_path / work_root_name)
    job_dir = os.path.join(work_root, entry_id)
    build_dir = os.path.join(job_dir, "build")
    outfit_dir = os.path.join(build_dir, "noue_work", "variant", "Player", "Outfit")
    base = "SK_Player_Female_Outfit_Cloth001"
    d = os.path.join(outfit_dir, base)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, base + ".uasset"), "wb") as f:
        f.write(b"UA")
    with open(os.path.join(d, base + ".uexp"), "wb") as f:
        f.write(b"UE")
    os.makedirs(build_dir, exist_ok=True)
    out_pak = os.path.join(build_dir, f"{entry_id}_PlayerSwap_P.pak")
    with open(out_pak, "wb") as f:
        f.write(b"PAK")
    job = {"vrm_path": "", "avatar_name": entry_id, "genders": ["Female", "Male"]}
    with mock.patch.object(vea, "extract_avatar_atlas_png", side_effect=_fake_extract_atlas):
        val.save_library(job, job_dir, out_pak, os.path.join(build_dir, "noue_work"))
    return work_root, job_dir, out_pak


def _make_entry_without_library(tmp_path, work_root_name="work", entry_id="Legacy"):
    """中間物保存より前の旧エントリを模擬する(pak本体はあるがlibrary/が無い)。"""
    work_root = str(tmp_path / work_root_name)
    job_dir = os.path.join(work_root, entry_id)
    build_dir = os.path.join(job_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    out_pak = os.path.join(build_dir, f"{entry_id}_PlayerSwap_P.pak")
    with open(out_pak, "wb") as f:
        f.write(b"PAK")
    return work_root, job_dir, out_pak


def _mark_multi_avatar(job_dir):
    """manifest.jsonに"multi_avatar": trueを立てる(WP-2合成エンジンが
    書く想定のフラグを模擬)。"""
    manifest_path = val.manifest_path(job_dir)
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["multi_avatar"] = True
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# entry_is_multi_avatar
# ---------------------------------------------------------------------------


def test_entry_is_multi_avatar_false_for_normal_entry(tmp_path):
    _work_root, job_dir, _pak = _make_saved_entry(tmp_path)
    assert pak_manager.entry_is_multi_avatar(job_dir) is False


def test_entry_is_multi_avatar_true_when_flagged(tmp_path):
    _work_root, job_dir, _pak = _make_saved_entry(tmp_path)
    _mark_multi_avatar(job_dir)
    assert pak_manager.entry_is_multi_avatar(job_dir) is True


def test_entry_is_multi_avatar_false_when_no_manifest(tmp_path):
    _work_root, job_dir, _pak = _make_entry_without_library(tmp_path)
    assert pak_manager.entry_is_multi_avatar(job_dir) is False


def test_entry_is_multi_avatar_false_for_nonexistent_job_dir(tmp_path):
    assert pak_manager.entry_is_multi_avatar(str(tmp_path / "NoSuchEntry")) is False


# ---------------------------------------------------------------------------
# partition_library_entries_for_multi_avatar_pak
# ---------------------------------------------------------------------------


def test_partition_separates_selectable_and_grayed(tmp_path):
    work_root, job_dir_a, _ = _make_saved_entry(tmp_path, entry_id="Alicia")
    _, job_dir_legacy, _ = _make_entry_without_library(tmp_path, entry_id="Legacy")

    entries = pak_manager.list_library_entries(work_root)
    flags = {e["job_dir"]: pak_manager.entry_is_multi_avatar(e["job_dir"]) for e in entries}
    selectable, grayed = pak_manager.partition_library_entries_for_multi_avatar_pak(entries, flags)

    assert [e["entry_id"] for e in selectable] == ["Alicia"]
    assert [e["entry_id"] for e in grayed] == ["Legacy"]


def test_partition_excludes_multi_avatar_flagged_entries_from_both_lists(tmp_path):
    work_root, job_dir_a, _ = _make_saved_entry(tmp_path, entry_id="Alicia")
    _, job_dir_multi, _ = _make_saved_entry(tmp_path, entry_id="ComposedMod")
    _mark_multi_avatar(job_dir_multi)

    entries = pak_manager.list_library_entries(work_root)
    flags = {e["job_dir"]: pak_manager.entry_is_multi_avatar(e["job_dir"]) for e in entries}
    selectable, grayed = pak_manager.partition_library_entries_for_multi_avatar_pak(entries, flags)

    ids = {e["entry_id"] for e in selectable} | {e["entry_id"] for e in grayed}
    assert "ComposedMod" not in ids
    assert "Alicia" in {e["entry_id"] for e in selectable}


def test_partition_handles_empty_entries():
    selectable, grayed = pak_manager.partition_library_entries_for_multi_avatar_pak([], {})
    assert selectable == []
    assert grayed == []


def test_partition_missing_flag_entry_defaults_to_not_multi_avatar():
    # multi_avatar_flagsに載っていないjob_dirはFalse扱い(安全側デフォルト)
    entries = [{"job_dir": "/some/job", "has_library": True, "entry_id": "X"}]
    selectable, grayed = pak_manager.partition_library_entries_for_multi_avatar_pak(entries, {})
    assert [e["entry_id"] for e in selectable] == ["X"]
    assert grayed == []


# ---------------------------------------------------------------------------
# 負の対照: 検出力の証明
# ---------------------------------------------------------------------------


def test_negative_control_flag_read_ignoring_manifest_misses_true_flag(tmp_path):
    """負の対照: manifestを読まず常にFalseを返す壊れた実装だと、フラグが
    立っていても検出できないことを確認する(正のtest_entry_is_multi_avatar_
    true_when_flaggedの検出力の前提が壊れていないことの証明)。"""
    _work_root, job_dir, _pak = _make_saved_entry(tmp_path)
    _mark_multi_avatar(job_dir)

    def _broken_entry_is_multi_avatar(_job_dir):
        return False  # 実際のバグを模擬(manifestを見ない)

    assert pak_manager.entry_is_multi_avatar(job_dir) is True
    assert _broken_entry_is_multi_avatar(job_dir) is False, (
        "前提不成立: 壊れた実装でもTrueを返してしまう"
        "(negative controlの模擬方法を見直すこと)"
    )
