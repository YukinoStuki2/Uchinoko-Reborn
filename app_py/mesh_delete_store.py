# mesh_delete_store.py -- dev#1168前半(メッシュ削除)ラボ機能の選択状態
# 永続化ロジック(tkinter非依存)。
#
# equipment_filter_store.py/headequip_filter_store.py(dev#165/dev#277第1弾④)
# と同型。pipeline_runner.py(ヘッドレスのパイプライン起動経路、tkinter未導入
# python環境からも読み込まれる。lu_export.py即死の再発防止)が直接importできる
# よう、tkinterをimportするui\mesh_delete_dialog.pyとは分離する。
#
# **意味論(2026-08-09 オーナー指示「名前一覧出してチェックはずすときえる」)**:
#   ダイアログのチェックボックスは「チェックON=残す」「チェックOFF=削除」。
#   保存する値は**削除する側**(=チェックOFFにしたメッシュ名の集合)。
#   equipment_filter(チェックON=注入対象に含める、既定=全ON)と同じ
#   「空リスト/ファイル不在=既定値」の保存形式だが、ここでの空リストは
#   そのまま「削除対象なし」を意味する(装備限定のように「全ON=空リストへ
#   変換する」特別な符号化は不要——ダイアログ側が計算した「削除対象名の集合」
#   をそのまま保存するだけでよい)。
#
# **保存スコープ=アバター単位(2026-08-09 指揮者裁定、dev#1281残論点)**:
#   メッシュ名はシェイプキー(shapekey_filter_store.py)と同様に入力アバター
#   自身の構造に依存する(装備限定/頭装備切替のようなPalworld側固定カタログ
#   ではない)。保存値をアバター非依存のまま永続化すると、別アバターへ
#   切り替えたときに偶然名前が一致するメッシュへ誤爆しうる(dev#1281論点)。
#   そのためshapekey_filter_store.pyと同じ「直前に編集したavatar_pathとの組」
#   方式を採用する: 読み出し側(load_deleted_names)は現在のavatar_pathと
#   一致する場合のみ値を返し、不一致(別アバター編集時の残留)は既定値
#   (空リスト)として扱う。
#
# **移行**: 旧スキーマ(2026-08-09時点、avatar_pathキー無しでdeletedのみを
# 全アバター横断で保持していたもの)の残留ファイルは新スキーマの読み出しで
# avatar_pathキー不在→既定値扱いとなり自然に読み捨てられる(ラボ品質、
# 移行処理は実装しない——指揮者裁定「読み捨てでよい」)。
from __future__ import annotations

import json
import os
import sys
from typing import List, Optional

_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))

if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402

LAB_FEATURE_ID = "mesh_delete"
_STATE_FILENAME = "settings_lab_mesh_delete.json"


def _state_path(app_root: str) -> str:
    return os.path.join(app_root, _STATE_FILENAME)


def _norm_avatar_path(avatar_path: str) -> str:
    if not avatar_path:
        return ""
    try:
        return os.path.normcase(os.path.abspath(avatar_path))
    except (OSError, ValueError):
        return os.path.normcase(avatar_path)


def load_deleted_names(app_root: str, avatar_path: str) -> List[str]:
    """保存済みの「削除する」メッシュ名一覧(ソート済み、重複無し)。ファイル
    不在/壊れている/形式が違う場合、および保存時のavatar_pathが現在の
    avatar_pathと一致しない(別アバター編集時の残留)場合はいずれも
    空リスト(=ラボ憲章④の既定値=削除無し、安全側)。"""
    path = _state_path(app_root)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    if _norm_avatar_path(data.get("avatar_path", "")) != _norm_avatar_path(avatar_path):
        return []
    names = data.get("deleted")
    if isinstance(names, list):
        return sorted({n for n in names if isinstance(n, str) and n})
    return []


def save_deleted_names(app_root: str, avatar_path: str, names: List[str]) -> None:
    """namesが空なら「未実装状態と同一」を意味するファイル内容を書く
    (ファイル自体は残すが deleted=[] かつ avatar_path="" とする——次回
    load_deleted_namesは空リストを返すので挙動は「ファイル不在」と等価)。
    書き込み失敗は握りつぶす(equipment_filter_store.pyと同じ方針、設定保存の
    失敗で画面を止めない)。"""
    cleaned = sorted({n for n in names if n})
    path = _state_path(app_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"avatar_path": _norm_avatar_path(avatar_path) if cleaned else "",
                 "deleted": cleaned},
                f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def reset(app_root: str) -> None:
    """dev#1186レジストリ記述子の「既定値リセット関数」。ラボ窓の
    『全てのラボ機能を無効化』ボタンから呼ばれる想定。avatar_path問わず
    全消去する(既定値=削除無し・空)。"""
    path = _state_path(app_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"avatar_path": "", "deleted": []}, f, ensure_ascii=False)
    except OSError:
        pass


def is_active(app_root: str, avatar_path: str) -> bool:
    """ラボ機能が既定から変更されているか(=現在のアバターに対して1件以上
    削除指定済みか)。"""
    return bool(load_deleted_names(app_root, avatar_path))


def state_summary(app_root: str, avatar_path: str, lang: Optional[str] = None) -> Optional[str]:
    """dev#1186レジストリ記述子の「状態サマリ関数」。無効(未指定/別アバター
    の残留)ならNone、有効なら短い概要(lab_window.py側が『有効: <この文字列>』
    へ整形する想定)。"""
    n = len(load_deleted_names(app_root, avatar_path))
    if n == 0:
        return None
    return i18n.S("LabMeshDeleteSummaryFormat", lang).format(n)
