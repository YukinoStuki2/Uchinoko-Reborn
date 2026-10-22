# -*- coding: utf-8 -*-
"""WP-B2(dev#1198): vp_dt_row_select.py の単体テスト。

正本設計書: work/rd_1198_wpb/PROPOSAL.md §3(行選定ロジック)。

dev#1218(B2緊急修正): 旧版はPalworld実DataTableのUAssetAPI JSONダンプ抜粋
(pipeline/py/testdata/dt_rows_sample.json)を静的fixtureとして同梱していたが、
①provenance attestationで未分類のため由来分類ゲートFAIL ②プロジェクトの
権利方針(noue開発の動機は権利回避。Palworld由来データをリポに同梱しない)に
反していたため、完全に架空の合成データへ置き換えた。WP-B1(dt_flag_patcher.py、
PR #1213)が採った流儀と同じく、フィクスチャは静的データファイルを持たず、
本テストファイル内の _build_synthetic_dt() が実行時に組み立てる(架空の
行名・SKパス文字列のみで構成、Palworld由来のバイト列は一切含まない)。

検証意図(WP指示書 §10.2 の再現対象)は行数・構造で維持する:
  - Weave(旧Cloth001相当)絞りジョブ → Weave系15行
  - Onyx(旧IronArmor相当)系16行(比較用、Cold系だけ末尾番号が`_1`始まりの
    非対称命名という実データの構造的特徴を再現)
  - AmberMail(旧CopperArmor相当): 表示名と内部SK参照名が異なるケース
    (表示名からの推測は禁止という設計意図の再現)
  - 負の対照: 注入SKに対応しない行が選ばれないこと

実行: python -m pytest pipeline\\py\\test_vp_dt_row_select.py -q

opt-inの実データ突き合わせテスト(test_load_real_dump_smoke_opt_in)は、
開発機ローカルに実DTのUAssetAPI JSONダンプがある場合のみ実行される
(無ければskip)。実データも実行結果もこのテストファイルには含まれない
(構造的なスモーク検証のみ、行名・SKパス文字列は一切assertしない)。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_dt_row_select as m  # noqa: E402

# UEパッケージパスの共通祖先プレフィックス。vp_dt_row_select._UE_PACKAGE_PREFIX
# と同一の値(モジュール本体のパス正規化がこのプレフィックスを剥がす前提の
# ため、合成データ側もこの規約に合わせる必要がある。値自体はPalworld実データ
# ではなく、パイプラインのマウント規約〈テンプレート相対パス〉を表す定数)。
_PKG_PREFIX = "/Game/Pal/Model/Character/"


def _outfit_pkg(gender, base_name, variant_suffix=""):
    """Player/Outfit配下の架空SKパッケージ名を組み立てる。

    実データの構造(work/rd_1198/dump/...の調査で確認)を再現する: フォルダ名は
    常にbase_name(バリアント接尾辞なし)で、アセット名(ファイル名側)だけに
    variant_suffix("_v02"/"_v03"等)が付く。これが `_headequip_pkg`と対になる
    行選定ロジックの正規化対象(normalize_dt_package_path/normalize_target_rel)
    が実際に揃える座標系。"""
    folder = f"SK_Player_{gender}_Outfit_{base_name}"
    asset = f"SK_Player_{gender}_Outfit_{base_name}{variant_suffix}"
    return f"{_PKG_PREFIX}Player/Outfit/{folder}/{asset}"


def _headequip_pkg(sk_name):
    """Player/HeadEquip配下の架空SKパッケージ名を組み立てる。"""
    return f"{_PKG_PREFIX}Player/HeadEquip/{sk_name}/SK_{sk_name}"


def _row(name, pkgs):
    """1行分のUAssetAPI風JSON(SkeletalMeshMapプロパティのみ)を組み立てる。
    pkgs: パッケージ名(文字列)のリスト。空リストならSkeletalMeshMapプロパティ
    自体を持たない行(load_dt_rows_from_uassetapi_json()がsk_rel_paths=空集合
    として読む)。"""
    value = []
    if pkgs:
        value.append({
            "Name": "SkeletalMeshMap",
            "Value": [
                [
                    {"Name": "SkeletalMeshMap", "Value": "Dummy"},
                    {
                        "Name": "SkeletalMeshMap",
                        "Value": {
                            "AssetPath": {
                                "PackageName": pkg,
                                "AssetName": pkg.split("/")[-1],
                            },
                            "SubPathString": None,
                        },
                    },
                ]
                for pkg in pkgs
            ],
        })
    return {"Name": name, "Value": value}


def _outfit_row(name, base_name, variant_suffix="", genders=("Female", "Male")):
    return _row(name, [_outfit_pkg(g, base_name, variant_suffix) for g in genders])


def _build_synthetic_dt():
    """完全に架空のDT行データ(41行相当の構造を模した、Palworld実データを
    一切含まない合成テーブル)を組み立てる。

    グループ構成(すべて架空の名称):
      - Default_BaseBody / Default_BaseHead: 既定行(後者はSkeletalMeshMap無し)
      - WeaveMantle系15行 + WeaveCap(頭防具、Weave001系のtargetsには反応しない)
      - OnyxCuirass系16行 + OnyxHelm(頭防具、Onyx001系のtargetsには反応しない)
      - AmberMail/AmberHelm: 表示名トラップ(内部SK名はQuartz001、AmberHelmは
        別の頭防具SKを指すため混入しない)
      - Phantom001_Armor/Phantom002_Armor: 他のどのtargetsにも一致しない
        無関係行(「既にTrueな行が紛れ込まない」ことの負の対照用)
      - PeltCloak/PeltHelm: 無関係の代表行(PeltHelmは2つの異なる頭防具SKを
        持つ、実データの「1行が複数の異なるSKを参照しうる」構造の再現)
    """
    rows = []
    rows.append(_outfit_row("Default_BaseBody", "OldWeave001"))
    rows.append(_row("Default_BaseHead", []))

    rows.append(_row("WeaveCap", [_headequip_pkg("HeadGear101")]))
    rows.append(_outfit_row("WeaveMantle", "Weave001"))
    rows.append(_outfit_row("WeaveMantleHeat", "Weave001", "_v02"))
    rows.append(_outfit_row("WeaveMantleCold", "Weave001", "_v03"))
    for n in (2, 3, 4, 5):
        rows.append(_outfit_row(f"WeaveMantle_{n}", "Weave001"))
    for n in (2, 3, 4, 5):
        rows.append(_outfit_row(f"WeaveMantleHeat_{n}", "Weave001", "_v02"))
    for n in (2, 3, 4, 5):
        rows.append(_outfit_row(f"WeaveMantleCold_{n}", "Weave001", "_v03"))

    rows.append(_row("OnyxHelm", [_headequip_pkg("HeadGear102")]))
    rows.append(_outfit_row("OnyxCuirass", "Onyx001"))
    # OnyxCuirassHeat: 実データの非対称命名(女性側だけ末尾に`_2`が付く揺れ)を
    # 再現する。表示名から推測せずSK名で機械的に一致させる理由の実例。
    rows.append(_row("OnyxCuirassHeat", [
        _outfit_pkg("Female", "Onyx001", "_v02_2"),
        _outfit_pkg("Male", "Onyx001", "_v02"),
    ]))
    rows.append(_outfit_row("OnyxCuirassCold", "Onyx001", "_v03"))
    for n in (2, 3, 4, 5):
        rows.append(_outfit_row(f"OnyxCuirass_{n}", "Onyx001"))
    # OnyxCuirassCold系は`_1`始まり(他系列は`_2`始まり)という非対称。
    for n in (1, 2, 3, 4, 5):
        rows.append(_outfit_row(f"OnyxCuirassCold_{n}", "Onyx001", "_v03"))
    for n in (2, 3, 4, 5):
        rows.append(_row(f"OnyxCuirassHeat_{n}", [
            _outfit_pkg("Female", "Onyx001", "_v02_2"),
            _outfit_pkg("Male", "Onyx001", "_v02"),
        ]))

    rows.append(_outfit_row("AmberMail", "Quartz001"))
    rows.append(_row("AmberHelm", [_headequip_pkg("HeadGear103")]))

    rows.append(_row("Phantom001_Armor", [_outfit_pkg("Male", "Phantom001", "_v01")]))
    rows.append(_row("Phantom002_Armor", [_outfit_pkg("Male", "Phantom001", "_v02")]))

    rows.append(_outfit_row("PeltCloak", "Ranger001"))
    rows.append(_row("PeltHelm", [
        _headequip_pkg("HeadGear104"),
        _headequip_pkg("HeadGear105"),
    ]))

    return {"Exports": [{"Table": {"Data": rows}}]}


@pytest.fixture(scope="module")
def fixture_path(tmp_path_factory):
    """合成DT行データをテスト実行時にJSONへ書き出し、そのパスを返す。
    静的データファイルをリポジトリへ持たない(dev#1218)。"""
    tmp_dir = tmp_path_factory.mktemp("dt_rows_synthetic")
    path = tmp_dir / "dt_rows_synthetic.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_build_synthetic_dt(), f, ensure_ascii=False)
    return str(path)


# ---------------------------------------------------------------------------
# normalize_*: 正規化の純粋関数
# ---------------------------------------------------------------------------


def test_normalize_dt_package_path_strips_prefix():
    assert (
        m.normalize_dt_package_path(
            "/Game/Pal/Model/Character/Player/Outfit/"
            "SK_Player_Female_Outfit_Weave001/SK_Player_Female_Outfit_Weave001"
        )
        == "Player/Outfit/SK_Player_Female_Outfit_Weave001/SK_Player_Female_Outfit_Weave001"
    )


def test_normalize_target_rel_strips_extension_and_backslash():
    assert (
        m.normalize_target_rel(
            "Player\\Outfit\\SK_Player_Female_Outfit_Weave001\\SK_Player_Female_Outfit_Weave001.uexp"
        )
        == "Player/Outfit/SK_Player_Female_Outfit_Weave001/SK_Player_Female_Outfit_Weave001"
    )


def test_normalize_target_rel_leaves_non_sk_extension_untouched():
    """負の対照: 対象拡張子(.uexp/.uasset)以外は素通し(誤って中身を削らない)。"""
    assert m.normalize_target_rel("Player/Outfit/README.txt") == "Player/Outfit/README.txt"


# ---------------------------------------------------------------------------
# select_full_body_equipment_rows(): 本体ロジック(正の対照)
# ---------------------------------------------------------------------------


def _weave_targets():
    """Weave絞りジョブを模した targets_rel
    (build_pak_from_avatar._run_sk_injection() の戻り値と同形式:
    テンプレート相対・拡張子付き・両性別)。"""
    targets = []
    for gender in ("Female", "Male"):
        for suffix in ("", "_v02", "_v03"):
            targets.append(
                f"Player/Outfit/SK_Player_{gender}_Outfit_Weave001/"
                f"SK_Player_{gender}_Outfit_Weave001{suffix}.uexp"
            )
    return targets


def _onyx_targets():
    """比較用: Onyx系(内部SK名はOnyx001、_v02のみ末尾に`_2`が付く命名の
    揺れがある——これも表示名から推測せずSK名から機械抽出する理由の実例)。"""
    targets = []
    for gender in ("Female", "Male"):
        for suffix in ("", "_v02_2", "_v03"):
            targets.append(
                f"Player/Outfit/SK_Player_{gender}_Outfit_Onyx001/"
                f"SK_Player_{gender}_Outfit_Onyx001{suffix}.uexp"
            )
    return targets


def test_select_weave_job_yields_15_rows(fixture_path):
    """正の対照: 「Weave絞りジョブ→Weave系15行」という構造(旧Cloth001絞りの
    構造を架空データで再現)を、行選定ロジックが機械的に再現する。"""
    rows = m.load_dt_rows_from_uassetapi_json(fixture_path)
    selected = m.select_full_body_equipment_rows(rows, _weave_targets())
    expected = {
        "WeaveMantle", "WeaveMantleHeat", "WeaveMantleCold",
        "WeaveMantle_2", "WeaveMantle_3", "WeaveMantle_4", "WeaveMantle_5",
        "WeaveMantleHeat_2", "WeaveMantleHeat_3", "WeaveMantleHeat_4", "WeaveMantleHeat_5",
        "WeaveMantleCold_2", "WeaveMantleCold_3", "WeaveMantleCold_4", "WeaveMantleCold_5",
    }
    assert set(selected) == expected
    assert len(selected) == 15
    # WeaveCap(頭防具、Outfit系のtargetsとは無関係)は絶対混入しない
    assert "WeaveCap" not in selected


def test_select_onyx_job_yields_16_rows(fixture_path):
    """正の対照(比較用): Onyx系16行。OnyxCuirassCold系だけ末尾番号が
    `_1`始まり(他系列は`_2`始まり)という命名の非対称構造で16行ちょうど
    一致することを確認する。"""
    rows = m.load_dt_rows_from_uassetapi_json(fixture_path)
    selected = m.select_full_body_equipment_rows(rows, _onyx_targets())
    expected = {
        "OnyxCuirass", "OnyxCuirassHeat", "OnyxCuirassCold",
        "OnyxCuirass_2", "OnyxCuirass_3", "OnyxCuirass_4", "OnyxCuirass_5",
        "OnyxCuirassCold_1", "OnyxCuirassCold_2", "OnyxCuirassCold_3", "OnyxCuirassCold_4", "OnyxCuirassCold_5",
        "OnyxCuirassHeat_2", "OnyxCuirassHeat_3", "OnyxCuirassHeat_4", "OnyxCuirassHeat_5",
    }
    assert set(selected) == expected
    assert len(selected) == 16
    # OnyxHelm(頭防具)は絶対混入しない
    assert "OnyxHelm" not in selected


def test_select_display_name_trap_internal_name_mismatch(fixture_path):
    """正の対照: 表示名"AmberMail"の内部SK参照名は実際には"Quartz001"であり、
    "Amber001"という名のSKは存在しない(架空データで再現した表示名トラップ)。
    行選定がSK名(パス)を機械的に見ているなら、Quartz001系targets_relを
    渡したときにAmberMailが正しく選ばれる(表示名で"Amber"を検索していたら
    絶対に選ばれない)。"""
    rows = m.load_dt_rows_from_uassetapi_json(fixture_path)
    targets = [
        "Player/Outfit/SK_Player_Female_Outfit_Quartz001/"
        "SK_Player_Female_Outfit_Quartz001.uexp",
        "Player/Outfit/SK_Player_Male_Outfit_Quartz001/"
        "SK_Player_Male_Outfit_Quartz001.uexp",
    ]
    selected = m.select_full_body_equipment_rows(rows, targets)
    assert "AmberMail" in selected
    assert "AmberHelm" not in selected  # 頭防具側は別SKなので不選定


# ---------------------------------------------------------------------------
# 負の対照
# ---------------------------------------------------------------------------


def test_select_unrelated_target_selects_nothing_negative_control(fixture_path):
    """負の対照: どの行のSkeletalMeshMapとも一致しないSKパスを渡すと、
    何も選ばれない(fixtureに存在しない架空のSK名)。"""
    rows = m.load_dt_rows_from_uassetapi_json(fixture_path)
    selected = m.select_full_body_equipment_rows(
        rows,
        [
            "Player/Outfit/SK_Player_Female_Outfit_NonExistent999/"
            "SK_Player_Female_Outfit_NonExistent999.uexp"
        ],
    )
    assert selected == []


def test_select_empty_targets_selects_nothing_negative_control(fixture_path):
    """負の対照: targets_relが空なら何も選ばれない。"""
    rows = m.load_dt_rows_from_uassetapi_json(fixture_path)
    assert m.select_full_body_equipment_rows(rows, []) == []


def test_select_headequip_target_does_not_leak_into_outfit_rows_negative_control(fixture_path):
    """負の対照: 頭防具系のSK(WeaveCapが参照するHeadGear101)を
    targets_relに入れても、Outfit系の行(WeaveMantle等)は一切選ばれない
    (SkeletalMeshMapが実際に指す資産が違うため、混入しない)。"""
    rows = m.load_dt_rows_from_uassetapi_json(fixture_path)
    selected = m.select_full_body_equipment_rows(
        rows, ["Player/HeadEquip/HeadGear101/SK_HeadGear101.uexp"]
    )
    assert selected == ["WeaveCap"]


def test_select_does_not_touch_unrelated_rows_negative_control(fixture_path):
    """負の対照: 他のどのtargetsにも一致しない無関係行(Phantom系)は、
    そのSKが注入対象に含まれない限り選定結果に現れない(選定ロジックは
    現在値を見ておらずSkeletalMeshMap一致だけで判定するため、無関係な
    targets_relでPhantom系が誤って混入しないことを確認する)。"""
    rows = m.load_dt_rows_from_uassetapi_json(fixture_path)
    selected = m.select_full_body_equipment_rows(rows, _weave_targets())
    assert "Phantom001_Armor" not in selected
    assert "Phantom002_Armor" not in selected


# ---------------------------------------------------------------------------
# opt-in: 開発機ローカルの実DTダンプとの構造的スモーク突き合わせ
# ---------------------------------------------------------------------------

# work/ はgitignore対象(Palworldの実データを含みうる)。ここでの参照は
# ファイル名(調査成果物の置き場所の慣習)のみで、実データ自体はこの
# テストファイルにもリポジトリにも含まれない。無ければ自動skip。
_REAL_DUMP_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "work", "rd_1198", "dump",
    "DT_CharacterCreationMeshPresetTable_Equipments_full.json",
)


def test_load_real_dump_smoke_opt_in():
    """opt-in: 開発機ローカルに実DTのUAssetAPI JSONダンプがある場合のみ、
    load_dt_rows_from_uassetapi_json()が実データフォーマットを例外なく
    読めることだけを確認する(構造的スモーク)。行名・SKパス文字列は
    一切assertしない——このテストが検証するのは合成fixtureが依拠する
    JSONスキーマの読み取りが実データでも通ることであり、行選定の内容は
    上の合成データ側テストが担う。"""
    real_path = os.path.normpath(_REAL_DUMP_PATH)
    if not os.path.isfile(real_path):
        pytest.skip("開発機ローカルの実DTダンプが無い環境(work/rd_1198/dump/...)")
    rows = m.load_dt_rows_from_uassetapi_json(real_path)
    assert len(rows) > 0
    assert any(row.sk_rel_paths for row in rows)
    # 正規化後は先頭のUEパッケージプレフィックスが剥がれていること
    # (normalize_dt_package_path()が機能していることの構造確認)
    for row in rows:
        for p in row.sk_rel_paths:
            assert not p.startswith("/Game/"), (row.name, p)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
