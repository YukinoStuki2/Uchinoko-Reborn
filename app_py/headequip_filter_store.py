# headequip_filter_store.py -- dev#277第1弾④(頭装備切り替え)ラボ機能の
# 選択状態永続化ロジック(tkinter非依存)。
#
# equipment_filter_store.py(dev#165)と同型。pipeline_runner.py(ヘッドレス
# のパイプライン起動経路、tkinter未導入python環境からも読み込まれる)が
# 直接importできるよう、tkinterをimportするui\headequip_select_dialog.pyとは
# 分離する(equipment_filter_store.pyの2026-08-08緊急修正と同じ理由、
# lu_export.py即死の再発を避ける)。
#
# **意味論が装備限定(equipment_filter)と反転している点に注意**:
#   equipment_filter: チェックON=注入対象に含める(絞り込み)。既定=全ON
#                      (絞り込み無し=空リスト保存)。
#   headequip_toggle: チェックON=表示する(スタブ生成をスキップ)。
#                      既定=全OFF(空リスト=何も表示しない=現状どおり)。
# 両者とも「空リスト/ファイル不在=既定値」という保存形式は共通だが、
# 空リストが意味する既定挙動は正反対(装備限定=絞り込み無し、頭装備切替=
# 表示切替無し)。呼び出し側(live_template.py)のドキュメントも参照。
from __future__ import annotations

import json
import os
import sys
from typing import List, Optional

_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402

LAB_FEATURE_ID = "headequip_toggle"
_STATE_FILENAME = "settings_lab_headequip_toggle.json"


def _state_path(app_root: str) -> str:
    return os.path.join(app_root, _STATE_FILENAME)


def load_selected_codes(app_root: str) -> List[str]:
    """保存済みの「表示する」頭装備コード一覧(ソート済み、重複無し)。
    ファイル不在/壊れている/形式が違う場合は空リスト(=既定値=全部
    非表示、安全側)。"""
    path = _state_path(app_root)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        codes = data.get("selected")
        if isinstance(codes, list):
            return sorted({c for c in codes if isinstance(c, str) and c})
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        pass
    return []


def save_selected_codes(app_root: str, codes: List[str]) -> None:
    """codesが空なら「既定(全部非表示)」を意味するファイル内容を書く
    (ファイル自体は残すが selected=[] とする)。書き込み失敗は握りつぶす
    (equipment_filter_store.pyと同じ方針)。"""
    path = _state_path(app_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"selected": sorted({c for c in codes if c})}, f,
                      ensure_ascii=False, indent=1)
    except OSError:
        pass


def reset(app_root: str) -> None:
    """dev#1186レジストリ記述子の「既定値リセット関数」。ラボ窓の
    『全てのラボ機能を無効化』ボタンから呼ばれる想定。既定値=未選択(空、
    =全部非表示)。"""
    save_selected_codes(app_root, [])


def is_active(app_root: str) -> bool:
    """ラボ機能が既定から変更されているか(=1件以上表示指定済みか)。"""
    return bool(load_selected_codes(app_root))


def state_summary(app_root: str, lang: Optional[str] = None) -> Optional[str]:
    """dev#1186レジストリ記述子の「状態サマリ関数」。無効(未選択=全部
    非表示)ならNone、有効なら短い概要(lab_window.py側が『有効: <この
    文字列>』へ整形する想定)。"""
    n = len(load_selected_codes(app_root))
    if n == 0:
        return None
    return i18n.S("LabHeadEquipToggleSummaryFormat", lang).format(n)
