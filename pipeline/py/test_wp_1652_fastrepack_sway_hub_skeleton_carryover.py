# -*- coding: utf-8 -*-
"""dev#1652: fast_repack.py(「影のみ更新(高速)」)が揺れ有効アバターの
共有骨格reparentパッチ(dev#1508、SK_PalHuman_Skeleton)を持ち越さず、
揺れが実際に壊れたpakを出荷する不具合の単体テスト。

正本(issue本文): 影のみ更新(materials_only repack)後のpakは揺れABP
エントリ(dev#19、G14)は40件含むが、SK_PalHuman_Skeleton(sway-hub共有
骨格パッチ、dev#1508)のエントリは0件のまま。フル変換時の成果物
build\\noue_work\\sway_hub_reparent\\SK_PalHuman_Skeleton.uasset/.uexp は
ディスクに実在するのに、fast_repack.pyがこれを一度も参照していなかった
(dev#1494はDT/sway ABPの2資産だけを対象にしており、後発のsway_hub_
reparent(dev#1508)は対象外のまま残っていた)。

検証する内容:
  1) `_reuse_sway_hub_reparent()`: 直前フル変換が work\\sway_hub_reparent\\
     へ書いたパッチ済み.uasset/.uexpをそのまま持ち越し、正しいCOMMON_MOUNT
     相対パス(BODY_PREFIX、"Skeleton/Human/"配下)を組み立てること(正)。
     揺れ無効/ハブ割当0件(ファイル自体が無い)なら空リストを返すこと
     (負の対照: 揺れ無効アバターの挙動が変わらないことの保証)。
     片方だけ存在する(壊れたキャッシュ)ならフェイルクローズすること。
  2) end-to-end: fast_repack.main()の合流ロジック(common_mount_files ==
     to_common_mount_body_files(final_files) + dt_files + sway_abp_files +
     sway_hub_files)を再現し、実際にvp_pakwrite.build_pak()したpakを
     vp_core.read_pak_entries()で読み戻し、SK_PalHuman_Skeletonのrelパスが
     ファイル一覧レベルで実在することを機械検査する。**負の対照**:
     sway_hub_filesを合流させない(=dev#1652の修正前の壊れた挙動を再現
     した)pakでは、同じ検査が確実に検出すること。

実行: python -m pytest pipeline\\py\\test_wp_1652_fastrepack_sway_hub_skeleton_carryover.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fast_repack  # noqa: E402
import vp_core  # noqa: E402
import vp_pakwrite  # noqa: E402


def _write(path, content: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


SK_NAME = fast_repack.build_pak_from_avatar.SWAY_HUB_SK_PACKAGE_NAME


def _expected_rel(ext):
    return vp_pakwrite.normalize_rel(
        "Skeleton/Human/" + SK_NAME + ext, vp_pakwrite.BODY_PREFIX)


# ---------------------------------------------------------------------------
# 1) _reuse_sway_hub_reparent()
# ---------------------------------------------------------------------------


def _make_sway_hub_dir(base):
    stage_dir = os.path.join(base, "sway_hub_reparent")
    uasset_bytes = os.urandom(256)
    uexp_bytes = os.urandom(512)
    _write(os.path.join(stage_dir, SK_NAME + ".uasset"), uasset_bytes)
    _write(os.path.join(stage_dir, SK_NAME + ".uexp"), uexp_bytes)
    return uasset_bytes, uexp_bytes


def test_reuse_sway_hub_reparent_carries_over_cached_bytes_with_correct_rel(tmp_path):
    """正: 揺れ有効アバターのキャッシュ(両ファイルとも実在)を、
    build_pak_from_avatar._run_sway_hub_reparent_patch()と全く同じ
    rel_path式でCOMMON_MOUNT合流用に持ち越す。"""
    uasset_bytes, uexp_bytes = _make_sway_hub_dir(str(tmp_path))

    entries = fast_repack._reuse_sway_hub_reparent(str(tmp_path), ())

    assert len(entries) == 2
    (uasset_src, uasset_rel), (uexp_src, uexp_rel) = entries
    assert uasset_rel == _expected_rel(".uasset")
    assert uexp_rel == _expected_rel(".uexp")
    with open(uasset_src, "rb") as f:
        assert f.read() == uasset_bytes
    with open(uexp_src, "rb") as f:
        assert f.read() == uexp_bytes


def test_reuse_sway_hub_reparent_disabled_avatar_returns_empty_list(tmp_path):
    """負の対照: 揺れ無効(またはハブ割当0件)アバターは、フル変換自身が
    このフェーズをno-opにしてファイルを書かない。空リストを返し、
    「影のみ更新」の挙動を変えないこと。"""
    # tmp_path 配下に sway_hub_reparent\ 自体を作らない(=揺れ無効を再現)
    assert fast_repack._reuse_sway_hub_reparent(str(tmp_path), ()) == []


def test_reuse_sway_hub_reparent_negative_control_partial_files_fails_closed(tmp_path):
    """負の対照: 片方のファイル(.uexpだけ)が欠けている壊れたキャッシュ。"""
    stage_dir = os.path.join(str(tmp_path), "sway_hub_reparent")
    _write(os.path.join(stage_dir, SK_NAME + ".uexp"), b"only uexp")
    # .uassetは書かない

    with pytest.raises(SystemExit) as exc:
        fast_repack._reuse_sway_hub_reparent(str(tmp_path), ())
    assert fast_repack.ERR_NO_FULL_BUILD in str(exc.value)


# ---------------------------------------------------------------------------
# 2) end-to-end: pak内容の機械検査(ファイル一覧レベル)+負の対照
# ---------------------------------------------------------------------------


def _build_minimal_body_pak(tmp_path, sway_hub_files):
    """fast_repack.main()のcommon_mount_files組み立て(dt_files/
    sway_abp_files/sway_hub_filesの合流)のうち、本WPが追加した
    sway_hub_files分だけを縮小再現する(DT/sway ABPはdev#1494の既存
    テストで既に検査済みのため、本WPでは新規追加分に絞る)。"""
    src_dir = tmp_path / "src"
    body_src = str(src_dir / "SK_Player_Male_Body.uexp")
    _write(body_src, os.urandom(128))
    final_files = [(body_src, "Player/Body/Male/SK_Player_Male_Body.uexp")]

    common_mount_files = vp_pakwrite.to_common_mount_body_files(final_files)
    common_mount_files = common_mount_files + sway_hub_files

    out_pak = str(tmp_path / "out_P.pak")
    vp_pakwrite.build_pak(common_mount_files, out_pak, mount_point=vp_pakwrite.COMMON_MOUNT)
    return out_pak


def test_end_to_end_pak_contains_sway_hub_skeleton_entries_after_carryover(tmp_path):
    """正の対照: dev#1652修正どおりsway_hub_filesを合流させると、
    出力pakにSK_PalHuman_Skeletonのuasset/uexpが両方とも実在する
    (issue本文のG3b/G15が読む相対パス)。"""
    _make_sway_hub_dir(str(tmp_path / "build" / "noue_work"))
    sway_hub_files = fast_repack._reuse_sway_hub_reparent(
        str(tmp_path / "build" / "noue_work"), ())
    assert len(sway_hub_files) == 2

    out_pak = _build_minimal_body_pak(tmp_path, sway_hub_files)
    mount, entries = vp_core.read_pak_entries(out_pak)
    assert mount == vp_pakwrite.COMMON_MOUNT

    assert _expected_rel(".uasset") in entries, (
        "SK_PalHuman_Skeleton .uasset missing from pak file listing (dev#1508/dev#1652 regression)")
    assert _expected_rel(".uexp") in entries, (
        "SK_PalHuman_Skeleton .uexp missing from pak file listing (dev#1508/dev#1652 regression)")


def test_end_to_end_negative_control_sway_disabled_avatar_has_no_skeleton_entries(tmp_path):
    """負の対照: 揺れ無効アバター(sway_hub_reparent\\が存在しない)では、
    _reuse_sway_hub_reparent()が空リストを返し、pakにSK_PalHuman_Skeleton
    エントリが一切入らないこと(=揺れ無効アバターの挙動は本修正で変わら
    ない、dev#1652が明示的に要求する回帰対照)。"""
    sway_hub_files = fast_repack._reuse_sway_hub_reparent(
        str(tmp_path / "build" / "noue_work"), ())
    assert sway_hub_files == []

    out_pak = _build_minimal_body_pak(tmp_path, sway_hub_files)
    mount, entries = vp_core.read_pak_entries(out_pak)

    assert _expected_rel(".uasset") not in entries
    assert _expected_rel(".uexp") not in entries


def test_end_to_end_negative_control_pre_fix_behavior_is_detected(tmp_path):
    """負の対照: 修正前のfast_repack.py(sway_hub_filesを一切合流させ
    ない、dev#1652のバグそのもの)を模した、揺れ有効アバターのpakでは、
    同じ検査が確実にFAILを検出すること(=このテストがdev#1652のバグを
    再現し、かつ検出できることの証明)。"""
    # 揺れ有効アバターのキャッシュは実在する(=フル変換は完了している)
    # が、main()側がsway_hub_filesを合流させ忘れた(修正前)状況を再現。
    _make_sway_hub_dir(str(tmp_path / "build" / "noue_work"))

    out_pak = _build_minimal_body_pak(tmp_path, sway_hub_files=[])
    mount, entries = vp_core.read_pak_entries(out_pak)

    assert _expected_rel(".uasset") not in entries, (
        "this test must reproduce the dev#1652 bug (missing skeleton entries)")
    assert _expected_rel(".uexp") not in entries, (
        "this test must reproduce the dev#1652 bug (missing skeleton entries)")
