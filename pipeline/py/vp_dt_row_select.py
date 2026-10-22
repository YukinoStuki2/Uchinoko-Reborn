"""WP-B2(dev#1198): bIsFullBodyEquipment=True化すべきDataTable行の選定ロジック。

設計の正本: work/rd_1198_wpb/PROPOSAL.md §3。

表示名からの推測は禁止する。過去に「金属アーマー」という表示名から
Copper系だと誤同定し、実際のパッチ対象はIronArmor系だった事件
(work/rd_1198_flagtest/PROGRESS.md)があるため、行選定は必ず
DT行のSkeletalMeshMapフィールドが参照するSK名(SoftObjectPath)と、
実際に注入が成功したSK(targets_rel、build_pak_from_avatar.pyの
_run_sk_injection()が返す)との**機械的な一致**で行う。

対象行 = { row | row.SkeletalMeshMap の少なくとも1つのエントリの
           SoftObjectPath が、targets_rel のいずれかと一致する }

WP-B1(DTバイナリパッチャ本体)とは疎結合。本モジュールは「行名の
リスト」を返すだけで、DT自体の読み書き・パッチャの呼び出しは一切
行わない(PROPOSAL §10.2 WP-B2の書き込み許可の注記どおり)。

dev#1198 WP-B5b追記: 本番のDT行読み取り経路は本モジュールの
load_dt_rows_from_uexp()で配線する(下記)。load_dt_rows_from_uassetapi_json()
は開発/テスト専用のまま変更しない。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import FrozenSet, Iterable, List

import dt_flag_patcher

# DT行のSkeletalMeshMapに現れるUEパッケージパスの、noueパイプライン相対
# パスへの共通祖先プレフィックス。build_pak_from_avatar.py の
# _run_sk_injection() が targets_rel を作るときの基準ディレクトリ
# (template直下)と、DT側パッケージパスの "/Game/Pal/Model/Character/"
# 以降が一致する(PROPOSAL §5.1のmount共通祖先化と対応する対応関係)。
_UE_PACKAGE_PREFIX = "/Game/Pal/Model/Character/"

_SK_FILE_EXTENSIONS = (".uexp", ".uasset")


@dataclass(frozen=True)
class DtEquipmentRow:
    """DT_CharacterCreationMeshPresetTable_Equipments の1行。

    Attributes:
        name: 行名(RowName、例 "IronArmorCold")。
        sk_rel_paths: SkeletalMeshMapの全エントリ(性別ごとの複数エントリを
            含む)の参照先を、normalize_target_rel()と同じ座標系(拡張子なし、
            "/"区切り、テンプレート相対、例
            "Player/Outfit/SK_Player_Female_Outfit_Cloth001/
            SK_Player_Female_Outfit_Cloth001")へ正規化した集合。
    """

    name: str
    sk_rel_paths: FrozenSet[str]


def normalize_dt_package_path(package_name: str) -> str:
    """DT行のSoftObjectPath.AssetPath.PackageName
    (例 "/Game/Pal/Model/Character/Player/Outfit/
    SK_Player_Female_Outfit_Cloth001/SK_Player_Female_Outfit_Cloth001")を、
    targets_relと同じ座標系
    ("Player/Outfit/SK_Player_Female_Outfit_Cloth001/
    SK_Player_Female_Outfit_Cloth001")へ正規化する。

    プレフィックスが一致しない(_UE_PACKAGE_PREFIXで始まらない)パスは、
    Player配下ではないアセット(将来のDTスキーマ変更等)を意味しうるため、
    そのまま(スラッシュ正規化のみ)返す——一致対象として選ばれることは
    ないが、例外にはしない(§2.3の「想定外なら停止」はDT書き込み側
    〈WP-B1〉の責務であり、本関数は読み取り専用の正規化に徹する)。
    """
    p = package_name.strip().replace("\\", "/")
    if p.startswith(_UE_PACKAGE_PREFIX):
        p = p[len(_UE_PACKAGE_PREFIX):]
    return p


def normalize_target_rel(rel_path: str) -> str:
    """build_pak_from_avatar._run_sk_injection() が返す targets_rel の
    1要素(例 "Player/Outfit/SK_Player_Female_Outfit_Cloth001/
    SK_Player_Female_Outfit_Cloth001.uexp")を、DT側と同じ座標系
    (拡張子なし)へ正規化する。"""
    p = rel_path.strip().replace("\\", "/")
    root, ext = os.path.splitext(p)
    if ext.lower() in _SK_FILE_EXTENSIONS:
        return root
    return p


def select_full_body_equipment_rows(
    dt_rows: Iterable[DtEquipmentRow],
    targets_rel: Iterable[str],
) -> List[str]:
    """PROPOSAL §3の選定式そのもの。

    dt_rows中の各行について、その行のSkeletalMeshMapが参照するSK
    (両方の性別エントリを含む)のいずれかが、targets_rel(実際に注入が
    成功したSKの集合)に含まれていれば、その行名を選定する。

    表示名やRowNameの命名規則からの推測は一切行わない
    (パスの完全一致のみで判定する)。

    Args:
        dt_rows: DtEquipmentRowのイテラブル(DT全行、順序は元のDT行順を
            想定するが本関数は順序に依存しない)。
        targets_rel: 実際に注入が成功したSKのtemplate相対パス
            (build_pak_from_avatar._run_sk_injection()の戻り値そのもの)。

    Returns:
        選定された行名のリスト。dt_rowsの列挙順を保ち、重複は含まない。
        targets_relが空、またはどの行にも一致しない場合は空リスト
        (負の対照: 注入SKに対応しない行は選ばれない)。
    """
    target_set = {normalize_target_rel(t) for t in targets_rel}
    selected: List[str] = []
    for row in dt_rows:
        if row.sk_rel_paths & target_set:
            selected.append(row.name)
    return selected


def load_dt_rows_from_uassetapi_json(json_path: str) -> List[DtEquipmentRow]:
    """開発/テスト用ローダ。

    work/rd_1198/dump/DT_CharacterCreationMeshPresetTable_Equipments_full.json
    のような、UAssetAPI(.NET、開発機限定の調査ツール)でJSONダンプした
    DT全行データから DtEquipmentRow 列を組み立てる。

    **これは本番経路ではない**。本番のDT読み取りはWP-B1が実装する専用
    Pythonバイナリパッチャが担う(UAssetAPI/.NETは出荷物に含めない、
    PROPOSAL §2.2の裁定)。本関数は行選定ロジック単体を、既存の調査
    成果物(JSONダンプ)を入力として検証するためだけに存在する
    (WP-B1完了後、本番呼び出し元はWP-B1が提供する別のローダから
    DtEquipmentRowを組み立てる想定——本モジュールとは疎結合)。

    Args:
        json_path: UAssetAPIのJSONダンプファイルへのパス。

    Returns:
        DT全行から組み立てた DtEquipmentRow のリスト(DT行順)。
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    rows_raw = data["Exports"][0]["Table"]["Data"]
    rows: List[DtEquipmentRow] = []
    for row in rows_raw:
        sk_paths = set()
        for prop in row.get("Value", []) or []:
            if prop.get("Name") != "SkeletalMeshMap":
                continue
            for pair in prop.get("Value", []) or []:
                if len(pair) < 2:
                    continue
                val = pair[1].get("Value")
                if not val:
                    continue
                pkg = (val.get("AssetPath", {}) or {}).get("PackageName")
                if pkg:
                    sk_paths.add(normalize_dt_package_path(pkg))
        rows.append(DtEquipmentRow(name=row["Name"], sk_rel_paths=frozenset(sk_paths)))
    return rows


def load_dt_rows_from_uexp(uexp_bytes: bytes, names: List[str]) -> List[DtEquipmentRow]:
    """dev#1198 WP-B5b: **本番のDT行読み取り経路**。

    load_dt_rows_from_uassetapi_json()と異なり、UAssetAPI(.NET、開発機限定の
    調査ツール)のJSONダンプを一切経由しない。WP-B1が実装した専用Python
    バイナリパーサ(dt_flag_patcher.parse_rows())が、実行時にユーザーの
    Palworld pakから抽出したDTのuexpバイト列を直接解析し、各行の
    SkeletalMeshMapが参照するPackageNameをデコードする(dt_flag_patcher.py
    dev#1198 WP-B5b追記部分)。本関数はその結果を
    normalize_dt_package_path()で正規化し、select_full_body_equipment_rows()
    が期待する座標系のDtEquipmentRow列へ組み立てるだけの薄いアダプタ。

    呼び出し元(build_pak_from_avatar.py Phase 3.5)は、実行時にユーザーの
    Palworld pakから抽出した本物のDTのuexpバイト列と、対応する.uassetの
    NameMap(vp_core.read_names()の戻り値)をそのまま渡す。

    Args:
        uexp_bytes: DT_CharacterCreationMeshPresetTable_Equipments.uexpの
            バイト列(ユーザーのPalworld pakから実行時抽出したもの、無改変)。
        names: 対応する.uassetのNameMap(vp_core.read_names()の戻り値と同じ
            並び)。

    Returns:
        DT全行から組み立てた DtEquipmentRow のリスト(DT行順)。

    Raises:
        dt_flag_patcher.DtStructureError: DTのバイト構造が想定
            (dt_flag_patcher._EXPECTED_FRAGMENT等)と食い違った場合。
            Palworld本体アップデート等で構造が変わった可能性があり、
            黙ってスキップせず変換全体を止めるためのシグナル
            (PROPOSAL §2.3、この行選定にも同じ規律を適用する)。
    """
    rows = dt_flag_patcher.parse_rows(uexp_bytes, names)
    return [
        DtEquipmentRow(
            name=row.name,
            sk_rel_paths=frozenset(
                normalize_dt_package_path(p) for p in row.sk_package_names
            ),
        )
        for row in rows
    ]
