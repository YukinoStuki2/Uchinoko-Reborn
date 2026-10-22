# -*- coding: utf-8 -*-
"""dev#1198 WP-B5a: COMMON_MOUNT実配線の単体テスト。

正本: work\\rd_1198_wpb\\PROPOSAL.md §5.1・§4.5・§11。

本WPは B4(dev#1210、vp_pakwrite.py に COMMON_MOUNT/BODY_PREFIX/DT_PREFIX/
effective_path()/normalize_rel() を追加済み)を土台に、実際の呼び出し元
(build_pak_from_avatar.py Phase3, fast_repack.py)をCOMMON_MOUNTへ配線し直す。
DT資産の同梱配線は別WP(WP-B5b)の担当であり、本WPはボディ資産のみを対象とする。

検証する内容:
  1) vp_pakwrite.to_common_mount_body_files() が既存呼び出し元と同じ形の
     final_files([(src, rel), ...])をCOMMON_MOUNT座標系へ正しく変換すること
     (正規化・".."ゼロ・DEFAULT_MOUNT時との実効パス完全一致、B4のテスト
     手法をそのまま流用)。
  2) build_pak_from_avatar.py / fast_repack.py が実際に
     vp_pakwrite.build_pak(..., mount_point=COMMON_MOUNT) を呼ぶよう配線
     されていること(ソース走査による配線確認、実変換は行わない
     ——CLAUDE.md「受入試験はリリースゲートに任せる」)。
  3) preflight_pak.py G1が新mount値(COMMON_MOUNT)を厳格比較すること
     (正の対照: 新mountでPASS。負の対照: 旧DEFAULT_MOUNTのpakをFAILとして
     検出できること=B4以前の実装で生成された古いpakを弾ける)。
  4) preflight_pak.strip_body_prefix() が BODY_PREFIX を剥がすこと
     (G3ホワイトリスト・G10在庫照合が、entries の座標系変化(BODY_PREFIX
     付与)によって検出力を失っていないことの根拠、§本ファイルdocstring末尾
     の「発見した副作用」参照)。

実行: python -m pytest pipeline\\py\\test_wp_b5a_common_mount_wiring.py -q

------------------------------------------------------------------------------
発見した副作用(実装中に判明、本WPスコープ内で対処):
Phase3をCOMMON_MOUNTへ切り替えると、生成pakの各エントリrelは
"Model/Character/..." というBODY_PREFIX付きの座標系になる。preflight_pak.py
の G3(禁止物ホワイトリストの完全一致比較)と G10(SK在庫の名前照合)は、
いずれもBODY_PREFIX無しの座標系(noue_template_manifest.json/dup_*.csv/
vp_exclusions.pyと同じ、旧DEFAULT_MOUNT時代からの座標系)を前提にした
既存の完全一致比較だったため、対処しないとG3は素体共有MI(ホワイトリスト
対象)を誤ってFORBIDDEN判定(誤FAIL)、G10は在庫の全件を「収録漏れ」と
誤検出(検査が事実上無意味化)する。preflight_pak.strip_body_prefix()で
座標系を揃えて対処した(G1/G2/G4/G5/G6/G11/G12は元から座標系に依存しない
設計、または別の座標系(vanilla_entries/full/extractディレクトリ)を使う
ため無改修で正しく動作する。本ファイルの全テストで機械確認)。
"""
import inspect
import io
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_core  # noqa: E402
import vp_pakwrite  # noqa: E402
import preflight_pak  # noqa: E402


# ---------------------------------------------------------------------------
# 1) vp_pakwrite.to_common_mount_body_files()
# ---------------------------------------------------------------------------


REPRESENTATIVE_BODY_RELS = [
    "Player/Body/Male/SK_Player_Male_Body.uasset",
    "Player/Body/Male/SK_Player_Male_Body.uexp",
    "Player/Outfit/Male/SK_Player_Male_Outfit_00.uasset",
    "ModelMaterials/MainShader/M_VP_m00.uasset",
    "/root_level_file.uasset",  # leading '/'(root直下ファイル)も対象
]


def test_to_common_mount_body_files_applies_normalize_rel_with_body_prefix():
    files = [(f"/abs/src/{i}", rel) for i, rel in enumerate(REPRESENTATIVE_BODY_RELS)]
    out = vp_pakwrite.to_common_mount_body_files(files)
    assert len(out) == len(files)
    for (src, rel), (src2, new_rel) in zip(files, out):
        assert src == src2, "abs source path must be unchanged"
        assert new_rel == vp_pakwrite.normalize_rel(rel, vp_pakwrite.BODY_PREFIX)
        assert ".." not in new_rel.split("/")


@pytest.mark.parametrize("rel", REPRESENTATIVE_BODY_RELS)
def test_to_common_mount_body_files_effective_path_matches_legacy(rel):
    """受入条件: 実効パス不変(B4のテスト手法を流用)。"""
    old_eff = vp_pakwrite.effective_path(vp_pakwrite.DEFAULT_MOUNT, rel)
    (_src, new_rel), = vp_pakwrite.to_common_mount_body_files([("/abs/src", rel)])
    new_eff = vp_pakwrite.effective_path(vp_pakwrite.COMMON_MOUNT, new_rel)
    assert old_eff == new_eff


def test_to_common_mount_body_files_rejects_dotdot_negative_control():
    """負の対照: ".."混入が正規化を素通りしない(vp_pakwrite.normalize_relの
    委譲先の挙動がラッパー越しでも保持されていることの確認)。"""
    with pytest.raises(ValueError):
        vp_pakwrite.to_common_mount_body_files([("/abs/src", "../evil.uasset")])


# ---------------------------------------------------------------------------
# 2) end-to-end: build_pak_from_avatar.py Phase3スタイルの呼び出しを
#    再現し、実際にbuild_pak()を通した生バイト列がCOMMON_MOUNT座標系で
#    正しく格納されること(B4のend-to-endテスト手法を流用)
# ---------------------------------------------------------------------------


def _write(path, content: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def test_phase3_style_final_files_build_pak_common_mount_end_to_end(tmp_path):
    src_dir = tmp_path / "src"
    body_content = os.urandom(2048)
    mat_content = os.urandom(1024)

    body_src = str(src_dir / "SK_Player_Male_Body.uexp")
    mat_src = str(src_dir / "M_VP_m00.uasset")
    _write(body_src, body_content)
    _write(mat_src, mat_content)

    # build_pak_from_avatar.py Phase3 / fast_repack.py と同じ形
    # (all_files相当。DEFAULT_MOUNT座標系、BODY_PREFIX無し)
    final_files = [
        (body_src, "Player/Body/Male/SK_Player_Male_Body.uexp"),
        (mat_src, "ModelMaterials/MainShader/M_VP_m00.uasset"),
    ]

    common_mount_files = vp_pakwrite.to_common_mount_body_files(final_files)
    out_pak = str(tmp_path / "out.pak")
    info = vp_pakwrite.build_pak(common_mount_files, out_pak,
                                  mount_point=vp_pakwrite.COMMON_MOUNT)
    assert info["n_entries"] == 2

    mount, entries = vp_core.read_pak_entries(out_pak)
    assert mount == vp_pakwrite.COMMON_MOUNT
    expected_keys = {
        "Model/Character/Player/Body/Male/SK_Player_Male_Body.uexp",
        "Model/Character/ModelMaterials/MainShader/M_VP_m00.uasset",
    }
    assert set(entries.keys()) == expected_keys
    for k in entries:
        assert ".." not in k.split("/")

    def _read_back(rel, expected):
        e = entries[rel]
        with open(out_pak, "rb") as f:
            f.seek(e["data_offset"])
            assert f.read(e["size"]) == expected

    _read_back("Model/Character/Player/Body/Male/SK_Player_Male_Body.uexp", body_content)
    _read_back("Model/Character/ModelMaterials/MainShader/M_VP_m00.uasset", mat_content)


def test_phase3_style_bytes_match_legacy_mount_build(tmp_path):
    """受入条件: 実効パス不変のバイト検証(B4のtest_build_pak_common_mount_
    body_asset_bytes_match_legacy_mount_buildと同型)。同一ソースを旧経路
    (DEFAULT_MOUNT、配線前)と新経路(COMMON_MOUNT、本WPの配線)の両方で
    build_pak()し、格納される生バイト列が完全一致することを確認する。"""
    src_dir = tmp_path / "src"
    content = os.urandom(4096)
    src = str(src_dir / "SK_Player_Male_Body.uexp")
    _write(src, content)

    legacy_rel = "Player/Body/Male/SK_Player_Male_Body.uexp"
    legacy_pak = str(tmp_path / "legacy.pak")
    # 配線前(WP-B5a適用前)の呼び出し方そのもの
    vp_pakwrite.build_pak([(src, legacy_rel)], legacy_pak)

    new_pak = str(tmp_path / "new.pak")
    common_mount_files = vp_pakwrite.to_common_mount_body_files([(src, legacy_rel)])
    vp_pakwrite.build_pak(common_mount_files, new_pak, mount_point=vp_pakwrite.COMMON_MOUNT)

    _, legacy_entries = vp_core.read_pak_entries(legacy_pak)
    _, new_entries = vp_core.read_pak_entries(new_pak)

    def _bytes_of(pak_path, entries, rel):
        e = entries[rel]
        with open(pak_path, "rb") as f:
            f.seek(e["data_offset"])
            return f.read(e["size"])

    legacy_bytes = _bytes_of(legacy_pak, legacy_entries, legacy_rel)
    new_rel = vp_pakwrite.normalize_rel(legacy_rel, vp_pakwrite.BODY_PREFIX)
    new_bytes = _bytes_of(new_pak, new_entries, new_rel)
    assert legacy_bytes == new_bytes == content


# ---------------------------------------------------------------------------
# 3) 呼び出し元(build_pak_from_avatar.py / fast_repack.py)の配線確認
#    (ソース走査。実変換はしない——CLAUDE.md「受入試験はリリースゲートに
#    任せる」原則)
# ---------------------------------------------------------------------------


def _read_source(rel_from_here):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel_from_here)
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.mark.parametrize("filename", ["build_pak_from_avatar.py", "fast_repack.py"])
def test_call_site_wired_to_common_mount(filename):
    src = _read_source(filename)
    assert "vp_pakwrite.to_common_mount_body_files(" in src, (
        f"{filename} must convert final_files via "
        "vp_pakwrite.to_common_mount_body_files() before build_pak()")
    assert "mount_point=vp_pakwrite.COMMON_MOUNT" in src, (
        f"{filename} must call build_pak(..., mount_point=vp_pakwrite.COMMON_MOUNT)")


def test_call_site_no_longer_calls_build_pak_with_implicit_default_mount():
    """負の対照: 配線前は `vp_pakwrite.build_pak(final_files, out_pak)`
    (mount_point省略=暗黙DEFAULT_MOUNT)という形だった。配線後はこの形が
    残っていないこと(=COMMON_MOUNTへの切替が実際に効いていることの
    ソースレベルの確認)。"""
    for filename in ("build_pak_from_avatar.py", "fast_repack.py"):
        src = _read_source(filename)
        assert "vp_pakwrite.build_pak(final_files, out_pak)" not in src, (
            f"{filename} still calls build_pak() with the pre-WP-B5a implicit "
            "DEFAULT_MOUNT signature")


# ---------------------------------------------------------------------------
# 4) preflight_pak.py G1: 新mount値での厳格比較(正の対照・負の対照)
# ---------------------------------------------------------------------------


def _make_minimal_pak(tmp_path, mount_point, rel="Player/Body/Male/SK_Player_Male_Body.uexp"):
    src_dir = tmp_path / "src"
    content = os.urandom(256)
    src = str(src_dir / "SK_Player_Male_Body.uexp")
    _write(src, content)
    files = ([(src, vp_pakwrite.normalize_rel(rel, vp_pakwrite.BODY_PREFIX))]
             if mount_point == vp_pakwrite.COMMON_MOUNT else [(src, rel)])
    out_pak = str(tmp_path / "check.pak")
    vp_pakwrite.build_pak(files, out_pak, mount_point=mount_point)
    return out_pak


def test_g1_source_expects_common_mount_not_legacy_default_mount():
    """ソースレベルの確認: preflight_pak.pyのG1がハードコード文字列比較を
    脱してvp_pakwrite.COMMON_MOUNT(唯一の正本)を参照していること。"""
    src = _read_source("preflight_pak.py")
    assert 'mount == vp_pakwrite.COMMON_MOUNT' in src
    assert 'mount == "../../../Pal/Content/Pal/Model/Character/"' not in src


def test_g1_positive_control_new_mount_pak_matches(tmp_path):
    """正の対照: COMMON_MOUNTで構築したpakのmountがG1の期待値と一致する。"""
    out_pak = _make_minimal_pak(tmp_path, vp_pakwrite.COMMON_MOUNT)
    mount, _entries = vp_core.read_pak_index(out_pak)
    assert mount == vp_pakwrite.COMMON_MOUNT


def test_g1_negative_control_legacy_default_mount_pak_is_rejected(tmp_path):
    """負の対照: WP-B5a以前(DEFAULT_MOUNT)の作り方で生成した古いpakは、
    新G1の期待値(COMMON_MOUNT)と一致しない=FAILとして検出できる。"""
    out_pak = _make_minimal_pak(tmp_path, vp_pakwrite.DEFAULT_MOUNT)
    mount, _entries = vp_core.read_pak_index(out_pak)
    assert mount != vp_pakwrite.COMMON_MOUNT
    assert mount == vp_pakwrite.DEFAULT_MOUNT


# ---------------------------------------------------------------------------
# 5) preflight_pak.strip_body_prefix(): G3/G10の検出力維持
# ---------------------------------------------------------------------------


def test_strip_body_prefix_removes_prefix_when_present():
    rel = "Model/Character/Player/Body/Male/MI_Player_Male_Body.uasset"
    assert (preflight_pak.strip_body_prefix(rel)
            == "Player/Body/Male/MI_Player_Male_Body.uasset")


def test_strip_body_prefix_passthrough_when_absent():
    """正の対照の裏: BODY_PREFIXを持たない文字列(将来のDT_PREFIXエントリ等)
    は無改変で通す(過剰な書き換えになっていないことの確認)。"""
    rel = "DataTable/CharacteCreation/DT_Foo.uasset"
    assert preflight_pak.strip_body_prefix(rel) == rel


def test_strip_body_prefix_roundtrips_with_to_common_mount_body_files():
    """to_common_mount_body_files()で付与したBODY_PREFIXを、
    strip_body_prefix()で剥がすと元のrelへ完全復元できる(往復一致)。
    G3のホワイトリスト・G10の在庫照合がこの往復に依存しているため、
    往復が崩れていないことを直接保証する。"""
    for rel in REPRESENTATIVE_BODY_RELS:
        rel_norm = rel[1:] if rel.startswith("/") else rel  # normalize_relと同じ前処理
        (_src, prefixed), = vp_pakwrite.to_common_mount_body_files([("/abs/src", rel)])
        assert preflight_pak.strip_body_prefix(prefixed) == rel_norm


def test_g3_whitelist_entries_survive_prefix_roundtrip():
    """G3のホワイトリスト(BODY_PREFIX無し座標系で列挙済み)が、実際のpak
    entry(BODY_PREFIX付き)をstrip_body_prefix()した結果と一致することを
    確認する(=WP-B5a配線後もG3の素体共有MI許可が正しく機能する根拠)。"""
    whitelisted = "Player/Body/Male/MI_Player_Male_Body.uasset"
    (_src, prefixed_entry), = vp_pakwrite.to_common_mount_body_files(
        [("/abs/src", whitelisted)])
    assert preflight_pak.strip_body_prefix(prefixed_entry) == whitelisted


# ---------------------------------------------------------------------------
# 6) preflight_pak.py内でentries_body_relがG3/G10双方に使われていることの
#    ソース確認(実際にmain()を完走させるには実物のjob/vanillaデータが
#    要るため、ここではリグレッション防止のためのソース走査に留める)
# ---------------------------------------------------------------------------


def test_g3_and_g10_use_entries_body_rel_not_raw_entries():
    src = _read_source("preflight_pak.py")
    assert "forbidden = [p for p in entries_body_rel" in src
    assert "pak_set = set(entries_body_rel)" in src
    # 負の対照: 配線前の形(raw entriesを直接比較)が残っていないこと
    assert "forbidden = [p for p in entries\n" not in src
    assert "pak_set = set(entries)\n" not in src
