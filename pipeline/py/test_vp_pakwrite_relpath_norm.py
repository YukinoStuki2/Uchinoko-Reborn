# -*- coding: utf-8 -*-
"""dev#1198 WP-B4: vp_pakwrite.py の rel_path正規化・mount一括昇格の単体テスト。

背景(正本: work\\rd_1198_wpb\\PROPOSAL.md §5.1、実証: work\\rd_1198_dtreach\\
PROGRESS.md): pakエンジンはFullDirectoryIndex内のentry側dirname文字列を
".."解決なしでmountへ単純連結する。旧DEFAULT_MOUNT(".../Model/Character/")は
ボディ資産専用の狭いmountで、DataTable配下など別系統のパスをentry側の
".."で上位へ逃がそうとすると実効パスに".."が残ったまま解決されず、
そのファイルへの変更がエンジンから無視される(dev#1198頭部問題の根本原因)。

本テストは vp_pakwrite.py に追加した COMMON_MOUNT/BODY_PREFIX/DT_PREFIX/
effective_path()/normalize_rel() が:
  1) 既存ボディ資産の実効パスをリグレッションなく再現できること(等価性)
  2) DT系別系統パスをentry側".."ゼロで正しく到達させられること(正の対照)
  3) ".."混入を検出して例外送出すること(負の対照)
  4) build_pak()自体(コア実装は無改修)を通した end-to-end でも上記が
     成立すること
を検証する。

本WPは書き込み許可がvp_pakwrite.py+テストに限定されており、
build_pak_from_avatar.py Phase3等の実際の呼び出し元は未改修のまま
(=DEFAULT_MOUNT・既存呼び出しの挙動は本WPで一切変わらない)。本テストは
その前提(新API群は既存呼び出し元の挙動に影響しない)も確認する。

実行: python -m pytest pipeline\\py\\test_vp_pakwrite_relpath_norm.py -q
"""
import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_core  # noqa: E402
import vp_pakwrite  # noqa: E402


# 実際のボディ資産・DT資産の代表的なrel_pathを、既存の運用パス体系に沿って
# 選定(work\\rd_1198_dtreach\\build_dtreach_pak.py と同じ実在パスパターン)。
REPRESENTATIVE_BODY_RELS = [
    "Player/Body/Male/SK_Player_Male_Body.uasset",
    "Player/Body/Male/SK_Player_Male_Body.uexp",
    "Player/Outfit/Male/SK_Player_Male_Outfit_00.uasset",
    "ModelMaterials/MainShader/M_VP_m00.uasset",
    "/root_level_file.uasset",  # leading '/' (root直下ファイル)も対象
]

DT_REL_UASSET = "DT_CharacterCreationMeshPresetTable_Equipments.uasset"
DT_REL_UEXP = "DT_CharacterCreationMeshPresetTable_Equipments.uexp"

VANILLA_DT_PHYSICAL = (
    "Pal/Content/Pal/DataTable/CharacteCreation/"
    "DT_CharacterCreationMeshPresetTable_Equipments"
)


# ---------------------------------------------------------------------------
# モジュール定数の自己整合性
# ---------------------------------------------------------------------------


def test_common_mount_plus_body_prefix_equals_legacy_default_mount():
    """COMMON_MOUNT + BODY_PREFIX は旧DEFAULT_MOUNTと文字列として完全一致
    しなければならない(=COMMON_MOUNT体系への移行がボディ資産の実効パスに
    対してリグレッション不可能であることの定義そのもの)。"""
    assert vp_pakwrite.COMMON_MOUNT + vp_pakwrite.BODY_PREFIX == vp_pakwrite.DEFAULT_MOUNT


def test_existing_default_mount_and_build_pak_signature_untouched():
    """本WPは既存呼び出し元(build_pak_from_avatar.py Phase3, fast_repack.py)
    が使うDEFAULT_MOUNT定数値そのもの、およびbuild_pak()のデフォルト引数を
    変更していないことの負の対照(=呼び出し元を書き換えていないため、
    暗黙のDEFAULT_MOUNT依存呼び出しは本WP適用後も従来どおり動作する)。"""
    assert vp_pakwrite.DEFAULT_MOUNT == "../../../Pal/Content/Pal/Model/Character/"
    import inspect
    sig = inspect.signature(vp_pakwrite.build_pak)
    assert sig.parameters["mount_point"].default == vp_pakwrite.DEFAULT_MOUNT


# ---------------------------------------------------------------------------
# normalize_rel(): 正規化ヘルパーの単体テスト
# ---------------------------------------------------------------------------


def test_normalize_rel_prefixes_and_strips_leading_slash():
    assert (vp_pakwrite.normalize_rel("SK_Foo.uasset", vp_pakwrite.BODY_PREFIX)
            == "Model/Character/SK_Foo.uasset")
    # leading '/' は剥がしてから連結する
    assert (vp_pakwrite.normalize_rel("/SK_Foo.uasset", vp_pakwrite.BODY_PREFIX)
            == "Model/Character/SK_Foo.uasset")


def test_normalize_rel_rejects_dotdot_segments_negative_control():
    """負の対照: rel_pathに".."セグメントが混入していたら、正規化の目的
    (entry側".."ゼロ)に反する静かな回帰として確実に検出・拒否される。"""
    with pytest.raises(ValueError):
        vp_pakwrite.normalize_rel("../evil.uasset", vp_pakwrite.BODY_PREFIX)
    with pytest.raises(ValueError):
        vp_pakwrite.normalize_rel("a/../b.uasset", vp_pakwrite.DT_PREFIX)


def test_normalize_rel_allows_normal_relative_subpaths():
    """負の対照の裏: ".."を含まない通常の相対パスは従来どおり通る
    (過剰検出になっていないことの確認)。"""
    assert (vp_pakwrite.normalize_rel("Male/SK_Outfit_00.uasset", vp_pakwrite.BODY_PREFIX)
            == "Model/Character/Male/SK_Outfit_00.uasset")


# ---------------------------------------------------------------------------
# 受入条件1: 既存ボディ資産の実効パスが変更前後でバイト同一(文字列レベル)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rel", REPRESENTATIVE_BODY_RELS)
def test_body_asset_effective_path_unchanged_by_common_mount_migration(rel):
    """代表的なボディ資産rel_pathについて、
    「旧mount(DEFAULT_MOUNT)+旧rel」の実効パス と
    「新mount(COMMON_MOUNT)+BODY_PREFIX付与rel」の実効パス が
    完全一致することを機械アサートする(work\\rd_1198_dtreach で実証済みの
    検証方法をそのまま踏襲)。"""
    old_eff = vp_pakwrite.effective_path(vp_pakwrite.DEFAULT_MOUNT, rel)
    new_rel = vp_pakwrite.normalize_rel(rel, vp_pakwrite.BODY_PREFIX)
    new_eff = vp_pakwrite.effective_path(vp_pakwrite.COMMON_MOUNT, new_rel)
    assert old_eff == new_eff


# ---------------------------------------------------------------------------
# 受入条件2: DTのような別系統パスのエントリが".."なしで正しく載る(正の対照)
# ---------------------------------------------------------------------------


def test_dt_asset_rel_path_contains_no_dotdot_positive_control():
    """正の対照: DT_PREFIXで正規化したDTエントリのrel_path自体には
    ".."が一切含まれない(mount側の".../"エスケープとは別物であることに
    注意——ここで検査するのはentry側のrel文字列のみ)。"""
    rel = vp_pakwrite.normalize_rel(DT_REL_UASSET, vp_pakwrite.DT_PREFIX)
    assert ".." not in rel.split("/")
    assert rel == "DataTable/CharacteCreation/" + DT_REL_UASSET


def test_dt_asset_effective_path_reaches_vanilla_datatable_location():
    """正の対照: COMMON_MOUNT + DT_PREFIX付与relの実効パスが、vanilla正パス
    (Pal/Content/Pal/DataTable/CharacteCreation/...)に定数プレフィックス
    "../../../"を足しただけの値と完全一致する(work\\rd_1198_dtreach\\
    PROGRESS.md の判定式そのもの)。"""
    for rel_name, ext in ((DT_REL_UASSET, "uasset"), (DT_REL_UEXP, "uexp")):
        rel = vp_pakwrite.normalize_rel(rel_name, vp_pakwrite.DT_PREFIX)
        eff = vp_pakwrite.effective_path(vp_pakwrite.COMMON_MOUNT, rel)
        expected = "../../../" + VANILLA_DT_PHYSICAL + "." + ext
        assert eff == expected, (eff, expected)


# ---------------------------------------------------------------------------
# 受入条件3: build_pak()を通したend-to-end(実際のpakバイト列での検証)
# ---------------------------------------------------------------------------


def _write(path, content: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def test_build_pak_common_mount_end_to_end_body_and_dt_coexist(tmp_path):
    """COMMON_MOUNTでbuild_pak()を実際に呼び、ボディ1件+DT2件を同居させた
    pakを構築 -> vp_core.read_pak_entries/read_pak_index で読み戻し、
    (a) mountがCOMMON_MOUNTであること
    (b) 各entryのpath(=FullDirectoryIndexキー)に".."が含まれないこと
    (c) mount+entry を単純連結(エンジンの実測挙動、rd_1198_dtreachの
        H2仮説どおり".."解決なしの文字列連結)した実効パスが、
        posixpath.normpathした理論値と一致すること(=entry側が既に
        クリーンなので単純連結でも正規化と同じ結果になる、正の対照)
    (d) 元ファイルのバイト内容がread_pak_entriesのdata_offset位置に
        バイト同一で書き込まれていること
    を確認する(build_pak()のコア実装は本WPで無改修——EOFを含む全体配線が
    正しく動くことの証明)。"""
    src_dir = tmp_path / "src"
    body_content = b"BODY-ASSET-BYTES-0123456789"
    dt_uasset_content = b"DT-UASSET-BYTES-ABCDEF"
    dt_uexp_content = b"DT-UEXP-BYTES-GHIJKL"

    body_src = str(src_dir / "SK_Player_Male_Body.uasset")
    dt_uasset_src = str(src_dir / DT_REL_UASSET)
    dt_uexp_src = str(src_dir / DT_REL_UEXP)
    _write(body_src, body_content)
    _write(dt_uasset_src, dt_uasset_content)
    _write(dt_uexp_src, dt_uexp_content)

    body_rel = vp_pakwrite.normalize_rel(
        "Player/Body/Male/SK_Player_Male_Body.uasset", vp_pakwrite.BODY_PREFIX)
    dt_uasset_rel = vp_pakwrite.normalize_rel(DT_REL_UASSET, vp_pakwrite.DT_PREFIX)
    dt_uexp_rel = vp_pakwrite.normalize_rel(DT_REL_UEXP, vp_pakwrite.DT_PREFIX)

    files = [
        (body_src, body_rel),
        (dt_uasset_src, dt_uasset_rel),
        (dt_uexp_src, dt_uexp_rel),
    ]
    out_pak = str(tmp_path / "out.pak")
    info = vp_pakwrite.build_pak(files, out_pak, mount_point=vp_pakwrite.COMMON_MOUNT)
    assert info["n_entries"] == 3

    mount, entries = vp_core.read_pak_entries(out_pak)
    assert mount == vp_pakwrite.COMMON_MOUNT

    assert set(entries.keys()) == {body_rel, dt_uasset_rel, dt_uexp_rel}
    for path in entries:
        assert ".." not in path.split("/"), path

    import posixpath as _pp
    for path in entries:
        # (c) 単純連結(実測エンジン挙動) == normpath理論値(entry側が既に
        #     クリーンなので両者は必ず一致する)
        naive_concat = mount + path
        assert naive_concat == _pp.normpath(naive_concat)

    def _read_back(rel, expected):
        e = entries[rel]
        assert e["compression"] == 0
        with open(out_pak, "rb") as f:
            f.seek(e["data_offset"])
            data = f.read(e["size"])
        assert data == expected, rel

    _read_back(body_rel, body_content)
    _read_back(dt_uasset_rel, dt_uasset_content)
    _read_back(dt_uexp_rel, dt_uexp_content)

    dt_eff = vp_pakwrite.effective_path(mount, dt_uasset_rel)
    assert dt_eff == "../../../" + VANILLA_DT_PHYSICAL + ".uasset"


def test_build_pak_common_mount_body_asset_bytes_match_legacy_mount_build(tmp_path):
    """同一ソースファイルを (旧DEFAULT_MOUNT+無加工rel) と
    (COMMON_MOUNT+BODY_PREFIX付与rel) の両方式でbuild_pak()し、格納される
    生バイト列が完全一致することを確認する(=経路(mount/rel構成)を変えても
    ペイロード自体は無改変で運ばれる、というリグレッション不可能性の
    最終的な機械証拠。受入条件「既存ボディ資産の実効パスが変更前後で
    バイト同一」を、rel文字列だけでなく実データのバイト一致でも裏付ける)。
    """
    src_dir = tmp_path / "src"
    content = os.urandom(4096)
    src = str(src_dir / "SK_Player_Male_Body.uexp")
    _write(src, content)

    legacy_rel = "Player/Body/Male/SK_Player_Male_Body.uexp"
    legacy_pak = str(tmp_path / "legacy.pak")
    vp_pakwrite.build_pak([(src, legacy_rel)], legacy_pak,
                           mount_point=vp_pakwrite.DEFAULT_MOUNT)

    new_rel = vp_pakwrite.normalize_rel(legacy_rel, vp_pakwrite.BODY_PREFIX)
    new_pak = str(tmp_path / "new.pak")
    vp_pakwrite.build_pak([(src, new_rel)], new_pak,
                           mount_point=vp_pakwrite.COMMON_MOUNT)

    _, legacy_entries = vp_core.read_pak_entries(legacy_pak)
    _, new_entries = vp_core.read_pak_entries(new_pak)

    def _bytes_of(pak_path, entries, rel):
        e = entries[rel]
        with open(pak_path, "rb") as f:
            f.seek(e["data_offset"])
            return f.read(e["size"])

    legacy_bytes = _bytes_of(legacy_pak, legacy_entries, legacy_rel)
    new_bytes = _bytes_of(new_pak, new_entries, new_rel)
    assert legacy_bytes == new_bytes == content
    assert hashlib.sha1(legacy_bytes).hexdigest() == hashlib.sha1(new_bytes).hexdigest()
