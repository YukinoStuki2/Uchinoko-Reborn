# -*- coding: utf-8 -*-
"""dev#1494: fast_repack.py(「影のみ更新(高速)」)がDTテーブル(dev#1198)・
sway ABP(dev#19)を持ち越さず壊れたpakを出力する不具合の単体テスト
(実報告C8B8RH4W)。

正本(issue本文): fast_repack.pyの再利用資産一覧に live_template/variant/
atlas/mat_override はあるが DT(dev#1198)/sway ABP(dev#19)が無く、影のみ
更新後のpakがpreflight G13/G14に落ちる。fail-open裁定(dev#1230)により
壊れたpakがそのまま出荷されていた。

検証する内容:
  1) `_reuse_dt_patch()`: 直前フル変換が work\\dt_patch\\ へ書いたDT
     patched .uasset/.uexpをそのまま持ち越し、正しいCOMMON_MOUNT相対パス
     (DT_PREFIX)を組み立てること(正)。dt_patchが無い/不完全ならフェイル
     クローズ(ERR_NO_FULL_BUILD)で停止すること(負の対照)。
  2) `_rebuild_sway_abp()`: job(dict)のsway_intensityに応じて
     sway_abp_build.sway_abp_pak_entries()を呼び、実テンプレ
     (pipeline\\py\\sway_abp_templates\\、リポジトリ同梱の実物)から
     非空のエントリを返すこと(正)。job=None/sway無効なら空リストを
     返すこと。ビルド失敗はSystemExitへ変換されること(負の対照)。
  3) end-to-end: fast_repack.main()の合流ロジック(common_mount_files ==
     to_common_mount_body_files(final_files) + dt_files + sway_abp_files)
     を再現し、実際にvp_pakwrite.build_pak()したpakをvp_core.
     read_pak_entries()で読み戻し、DTのrelパスとsway ABPエントリが
     ファイル一覧レベルで実在することを機械検査する。**負の対照**:
     dt_files/sway_abp_filesを合流させない(=修正前の壊れた挙動を
     再現した)pakでは、同じ検査が確実に検出すること
     (preflight_pak.check_sway_abp_presence()を実際に流用)。

実行: python -m pytest pipeline\\py\\test_wp_1494_fastrepack_dt_sway_carryover.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fast_repack  # noqa: E402
import vp_core  # noqa: E402
import vp_pakwrite  # noqa: E402
import sway_abp_build  # noqa: E402
import preflight_pak  # noqa: E402


def _write(path, content: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


DT_PACKAGE_NAME = fast_repack.build_pak_from_avatar.DT_PACKAGE_NAME


# ---------------------------------------------------------------------------
# 1) _reuse_dt_patch()
# ---------------------------------------------------------------------------


def _make_dt_patch_dir(base):
    dt_dir = os.path.join(base, "dt_patch")
    uasset_bytes = os.urandom(256)
    uexp_bytes = os.urandom(512)
    _write(os.path.join(dt_dir, DT_PACKAGE_NAME + ".uasset"), uasset_bytes)
    _write(os.path.join(dt_dir, DT_PACKAGE_NAME + ".uexp"), uexp_bytes)
    return dt_dir, uasset_bytes, uexp_bytes


def test_reuse_dt_patch_carries_over_cached_bytes_with_correct_rel(tmp_path):
    dt_dir, uasset_bytes, uexp_bytes = _make_dt_patch_dir(str(tmp_path))

    entries = fast_repack._reuse_dt_patch(dt_dir, ())

    assert len(entries) == 2
    (uasset_src, uasset_rel), (uexp_src, uexp_rel) = entries
    # rel_pathはbuild_pak_from_avatar._run_dt_patch()と全く同じ式で
    # 組み立てられていること(フル変換と持ち越しでpak内パスが食い違わない
    # ことの保証)。
    assert uasset_rel == vp_pakwrite.normalize_rel(
        DT_PACKAGE_NAME + ".uasset", vp_pakwrite.DT_PREFIX)
    assert uexp_rel == vp_pakwrite.normalize_rel(
        DT_PACKAGE_NAME + ".uexp", vp_pakwrite.DT_PREFIX)
    # 再計算(Palworld本体pakの読み直し)をせず、キャッシュのバイトを
    # そのまま指していること。
    with open(uasset_src, "rb") as f:
        assert f.read() == uasset_bytes
    with open(uexp_src, "rb") as f:
        assert f.read() == uexp_bytes


def test_reuse_dt_patch_negative_control_missing_dir_fails_closed(tmp_path):
    """負の対照: 直前フル変換がdt_patchを作っていない(dev#1198より前/
    壊れたキャッシュ)場合、黙ってDT無しのpakを出さずフェイルクローズする。"""
    dt_dir = os.path.join(str(tmp_path), "dt_patch")  # 実在しない

    with pytest.raises(SystemExit) as exc:
        fast_repack._reuse_dt_patch(dt_dir, ())
    assert fast_repack.ERR_NO_FULL_BUILD in str(exc.value)


def test_reuse_dt_patch_negative_control_partial_files_fails_closed(tmp_path):
    """負の対照: 片方のファイル(.uexpだけ)が欠けている壊れたキャッシュ。"""
    dt_dir = os.path.join(str(tmp_path), "dt_patch")
    _write(os.path.join(dt_dir, DT_PACKAGE_NAME + ".uexp"), b"only uexp")
    # .uassetは書かない

    with pytest.raises(SystemExit) as exc:
        fast_repack._reuse_dt_patch(dt_dir, ())
    assert fast_repack.ERR_NO_FULL_BUILD in str(exc.value)


# ---------------------------------------------------------------------------
# 2) _rebuild_sway_abp()
# ---------------------------------------------------------------------------


def test_rebuild_sway_abp_returns_none_when_job_is_none(tmp_path):
    """--job-dir単独指定(job.json無し)時はフル変換側もこのフェーズを
    実行できていないので、同じく何も付加しない。"""
    assert fast_repack._rebuild_sway_abp(None, str(tmp_path)) == []


def test_rebuild_sway_abp_disabled_returns_empty_list(tmp_path):
    for intensity in (None, "none", "unknown-value"):
        job = {"sway_intensity": intensity} if intensity is not None else {}
        assert fast_repack._rebuild_sway_abp(job, str(tmp_path)) == []


def test_rebuild_sway_abp_enabled_uses_real_templates_and_returns_entries(tmp_path):
    """正: リポジトリ同梱の実テンプレ(pipeline\\py\\sway_abp_templates\\)を
    使い、フル変換と同じ公開関数(sway_abp_build.sway_abp_pak_entries)で
    非空のエントリを再構築すること。"""
    job = {"sway_intensity": "normal"}
    entries = fast_repack._rebuild_sway_abp(job, str(tmp_path))
    assert len(entries) > 0
    assert os.path.isdir(os.path.join(str(tmp_path), "sway_abp"))
    for abs_path, rel in entries:
        assert os.path.isfile(abs_path)
        assert "Imp_Cloth" in rel and "ABP_" in rel


def test_rebuild_sway_abp_wraps_build_error_as_system_exit(tmp_path, monkeypatch):
    """負の対照: sway_abp_build側が失敗したら、黙ってスキップせず
    SystemExitへ変換して変換全体を止めること(DTと同じ「想定外は停止」方針)。"""
    def _boom(job, out_dir, **kw):
        raise sway_abp_build.SwayAbpBuildError("boom (test)")

    monkeypatch.setattr(sway_abp_build, "sway_abp_pak_entries", _boom)
    job = {"sway_intensity": "normal"}
    with pytest.raises(SystemExit) as exc:
        fast_repack._rebuild_sway_abp(job, str(tmp_path))
    assert "dev#19" in str(exc.value)


# ---------------------------------------------------------------------------
# 3) end-to-end: pak内容の機械検査(ファイル一覧レベル)+負の対照
# ---------------------------------------------------------------------------


def _build_minimal_body_pak(tmp_path, dt_files, sway_abp_files):
    """fast_repack.main()のcommon_mount_files組み立てを縮小再現する:
    to_common_mount_body_files(final_files) の結果へ dt_files/sway_abp_files
    を合流させ、build_pak(mount_point=COMMON_MOUNT)する(main()の実配線と
    1対1対応、CLAUDE.md「受入試験はリリースゲートに任せる」原則どおり
    実変換は行わず組み立てロジックだけを検査する)。"""
    src_dir = tmp_path / "src"
    body_src = str(src_dir / "SK_Player_Male_Body.uexp")
    _write(body_src, os.urandom(128))
    final_files = [(body_src, "Player/Body/Male/SK_Player_Male_Body.uexp")]

    common_mount_files = vp_pakwrite.to_common_mount_body_files(final_files)
    common_mount_files = common_mount_files + dt_files + sway_abp_files

    out_pak = str(tmp_path / "out_P.pak")
    vp_pakwrite.build_pak(common_mount_files, out_pak, mount_point=vp_pakwrite.COMMON_MOUNT)
    return out_pak


def test_end_to_end_pak_contains_dt_and_sway_entries_after_carryover(tmp_path):
    """正の対照: dev#1494修正どおりdt_files/sway_abp_filesを合流させると、
    出力pakにDTのrelパスとsway ABPエントリ(G14が数える"Imp_Cloth"/"ABP_"
    形式)が両方とも実在する。"""
    dt_dir, _uasset, _uexp = _make_dt_patch_dir(str(tmp_path / "build" / "noue_work"))
    dt_files = fast_repack._reuse_dt_patch(dt_dir, ())
    job = {"sway_intensity": "hard"}
    sway_abp_files = fast_repack._rebuild_sway_abp(job, str(tmp_path / "build" / "noue_work"))
    assert sway_abp_files, "sway ABP entries must be non-empty for this test to be meaningful"

    out_pak = _build_minimal_body_pak(tmp_path, dt_files, sway_abp_files)
    mount, entries = vp_core.read_pak_entries(out_pak)
    assert mount == vp_pakwrite.COMMON_MOUNT

    dt_rel_uasset = vp_pakwrite.normalize_rel(DT_PACKAGE_NAME + ".uasset", vp_pakwrite.DT_PREFIX)
    dt_rel_uexp = vp_pakwrite.normalize_rel(DT_PACKAGE_NAME + ".uexp", vp_pakwrite.DT_PREFIX)
    assert dt_rel_uasset in entries, "DT .uasset missing from pak file listing (dev#1198 regression)"
    assert dt_rel_uexp in entries, "DT .uexp missing from pak file listing (dev#1198 regression)"

    # G14と全く同じ判定ロジックを実際に流用してpak内容を検査する。
    ok, detail = preflight_pak.check_sway_abp_presence(job, entries)
    assert ok, f"G14-equivalent check failed after carryover: {detail}"


def test_end_to_end_negative_control_pre_fix_behavior_is_detected(tmp_path):
    """負の対照: 修正前のfast_repack.py(dt_files/sway_abp_filesを一切
    合流させない挙動)を模したpakでは、同じ検査が確実にFAILを検出する
    こと(=このテストがdev#1494のバグを再現し、かつ検出できることの証明)。"""
    job = {"sway_intensity": "hard"}
    out_pak = _build_minimal_body_pak(tmp_path, dt_files=[], sway_abp_files=[])
    mount, entries = vp_core.read_pak_entries(out_pak)

    dt_rel_uasset = vp_pakwrite.normalize_rel(DT_PACKAGE_NAME + ".uasset", vp_pakwrite.DT_PREFIX)
    dt_rel_uexp = vp_pakwrite.normalize_rel(DT_PACKAGE_NAME + ".uexp", vp_pakwrite.DT_PREFIX)
    assert dt_rel_uasset not in entries
    assert dt_rel_uexp not in entries

    ok, detail = preflight_pak.check_sway_abp_presence(job, entries)
    assert not ok, "the pre-fix (no carryover) pak must be detected as broken by G14"
    assert "sway ABP entries in pak=0" in detail
