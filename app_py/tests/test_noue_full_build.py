# test_noue_full_build.py -- dev#648受入条件。
#
# 対象issue: dev#648(HasNoueFullBuild()未移植)。
# app\DiveToPalworld.cs L.2452-2466 の HasNoueFullBuild() を
# app_py\noue_full_build.py へ移植したことの単体試験。
#
# HasNoueFullBuild()の判定対象(移植元コメントL.2437-2451どおり):
#   <workRoot>/<SanitizeName(vrmの拡張子抜きファイル名)>/build/ 配下に
#     - noue_work/variant ディレクトリ
#     - atlas ディレクトリ
#     - noue_mat_override ディレクトリ
#   の3つが全て存在し、かつ build_provenance.json ファイルが存在すること。
# vrmBox(vrm_path)が空文字ならディレクトリを見るまでもなく即False。
#
# 純関数モジュール(tkinter非依存)なので実tk窓は開かない。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import noue_full_build  # noqa: E402


def _make_full_build(work_root: str, vrm_path: str) -> str:
    """C#版が要求する3ディレクトリ+build_provenance.jsonの最小構成を作る。
    戻り値はbuildディレクトリの絶対パス。"""
    build = noue_full_build.build_dir_path(work_root, vrm_path)
    os.makedirs(os.path.join(build, "noue_work", "variant"), exist_ok=True)
    os.makedirs(os.path.join(build, "atlas"), exist_ok=True)
    os.makedirs(os.path.join(build, "noue_mat_override"), exist_ok=True)
    with open(
        os.path.join(build, "build_provenance.json"), "w", encoding="utf-8"
    ) as fh:
        fh.write("{}")
    return build


def test_build_dir_path_matches_sanitized_name_under_build(tmp_path):
    work_root = str(tmp_path)
    vrm = os.path.join(str(tmp_path), "MyAvatar!!.vrm")
    build = noue_full_build.build_dir_path(work_root, vrm)
    assert build == os.path.join(work_root, "MyAvatar", "build")


def test_has_noue_full_build_true_when_all_present(tmp_path):
    work_root = str(tmp_path)
    vrm = os.path.join(str(tmp_path), "avatar.vrm")
    _make_full_build(work_root, vrm)
    assert noue_full_build.has_noue_full_build(work_root, vrm) is True


def test_has_noue_full_build_false_when_empty_vrm_path(tmp_path):
    # vrmBox.Text.Trim()が空文字ならディレクトリを見るまでもなく即False。
    work_root = str(tmp_path)
    assert noue_full_build.has_noue_full_build(work_root, "") is False
    assert noue_full_build.has_noue_full_build(work_root, "   ") is False


def test_has_noue_full_build_false_when_build_dir_entirely_absent(tmp_path):
    # 負の対照: 一度も変換していないアバター(buildディレクトリ自体が無い)。
    work_root = str(tmp_path)
    vrm = os.path.join(str(tmp_path), "never_converted.vrm")
    assert noue_full_build.has_noue_full_build(work_root, vrm) is False


def test_has_noue_full_build_false_when_variant_dir_missing(tmp_path):
    # 負の対照: 3ディレクトリのうちnoue_work/variantだけ欠けている
    # (中断した変換の残骸を模擬)。
    work_root = str(tmp_path)
    vrm = os.path.join(str(tmp_path), "avatar.vrm")
    build = _make_full_build(work_root, vrm)
    import shutil

    shutil.rmtree(os.path.join(build, "noue_work", "variant"))
    assert noue_full_build.has_noue_full_build(work_root, vrm) is False


def test_has_noue_full_build_false_when_atlas_dir_missing(tmp_path):
    # 負の対照: atlasディレクトリだけ欠けている。
    work_root = str(tmp_path)
    vrm = os.path.join(str(tmp_path), "avatar.vrm")
    build = _make_full_build(work_root, vrm)
    import shutil

    shutil.rmtree(os.path.join(build, "atlas"))
    assert noue_full_build.has_noue_full_build(work_root, vrm) is False


def test_has_noue_full_build_false_when_mat_override_dir_missing(tmp_path):
    # 負の対照: noue_mat_overrideディレクトリだけ欠けている。
    work_root = str(tmp_path)
    vrm = os.path.join(str(tmp_path), "avatar.vrm")
    build = _make_full_build(work_root, vrm)
    import shutil

    shutil.rmtree(os.path.join(build, "noue_mat_override"))
    assert noue_full_build.has_noue_full_build(work_root, vrm) is False


def test_has_noue_full_build_false_when_provenance_file_missing(tmp_path):
    # 負の対照: 3ディレクトリは揃っているがbuild_provenance.jsonだけ無い
    # (C#版コメントどおり、「途中で中断した変換の残骸」の典型パターン)。
    work_root = str(tmp_path)
    vrm = os.path.join(str(tmp_path), "avatar.vrm")
    build = _make_full_build(work_root, vrm)
    os.remove(os.path.join(build, "build_provenance.json"))
    assert noue_full_build.has_noue_full_build(work_root, vrm) is False


def test_has_noue_full_build_uses_different_avatar_name_isolation(tmp_path):
    # あるアバターがフル変換済みでも、別名のアバターは無関係(未変換のまま)。
    work_root = str(tmp_path)
    vrm_a = os.path.join(str(tmp_path), "avatar_a.vrm")
    vrm_b = os.path.join(str(tmp_path), "avatar_b.vrm")
    _make_full_build(work_root, vrm_a)
    assert noue_full_build.has_noue_full_build(work_root, vrm_a) is True
    assert noue_full_build.has_noue_full_build(work_root, vrm_b) is False
