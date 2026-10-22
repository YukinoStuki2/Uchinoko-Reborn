# -*- coding: utf-8 -*-
"""dev#1170 WP-1: pak_manager.py側の中間物ライブラリ再エクスポート
(list_library_entries/entry_has_library)と、「作成済みMOD一覧」エントリ
削除(delete_avatar_artifacts)が中間物(job_dir/library/)を道連れ削除する
ことの検証(オーナー確定仕様「エントリと中間物は1:1の運命共同体」)。

save_library()自体の詳細(manifest内容・SK/アトラスのコピー)は
tests\\dev1170_avatar_library\\test_vp_avatar_library.py が担う。本ファイルは
「app_py側から到達できること」と「削除連動」だけに閉じる。
"""
from __future__ import annotations

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
    base = f"SK_Player_Female_Outfit_Cloth001"
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


# --------------------------------------------------------------- 再エクスポート


def test_list_library_entries_reexports_vp_avatar_library(tmp_path):
    work_root, job_dir, out_pak = _make_saved_entry(tmp_path)
    entries = pak_manager.list_library_entries(work_root)
    assert len(entries) == 1
    assert entries[0]["entry_id"] == "Alicia"
    assert entries[0]["has_library"] is True
    assert entries[0]["pak_path"] == out_pak


def test_entry_has_library_reexports_vp_avatar_library(tmp_path):
    work_root, job_dir, out_pak = _make_saved_entry(tmp_path)
    assert pak_manager.entry_has_library(job_dir) is True
    assert pak_manager.entry_has_library(str(tmp_path / "work" / "NoSuchEntry")) is False


# --------------------------------------------------------------- 削除連動


def test_delete_avatar_artifacts_removes_library_too(tmp_path):
    """エントリ削除→中間物も削除(オーナー確定仕様)。job_dir全体を
    shutil.rmtree()する既存のdelete_avatar_artifacts()が、library/を
    job_dir直下へ置くだけで自動的に道連れにできることの確認(追加配線なし)。
    """
    work_root, job_dir, out_pak = _make_saved_entry(tmp_path)
    lib_dir = val.library_dir(job_dir)
    assert os.path.isdir(lib_dir)  # 削除前は実在する(前提の確認)

    pak_manager.delete_avatar_artifacts(job_dir)

    assert not os.path.isdir(job_dir)
    assert not os.path.isdir(lib_dir)


def test_deleting_a_different_entry_leaves_this_librarys_untouched(tmp_path):
    """負の対照: 別エントリを削除しても、このエントリの中間物は無傷
    (道連れ削除がjob_dir単位に正しくスコープされていることの確認)。"""
    work_root, job_dir, out_pak = _make_saved_entry(tmp_path, entry_id="Alicia")
    _, other_job_dir, _ = _make_saved_entry(tmp_path, entry_id="Bob")

    pak_manager.delete_avatar_artifacts(other_job_dir)

    assert not os.path.isdir(other_job_dir)
    assert os.path.isdir(job_dir)
    assert val.has_library(job_dir) is True
