# equipment_filter_store.py -- dev#165(装備限定)ラボ機能の選択状態
# 永続化ロジック(tkinter非依存)。
#
# 背景(2026-08-08 緊急修正): app_py\ui\equipment_select_dialog.py が
# モジュール冒頭で `import tkinter as tk` するため、pipeline_runner.py
# (ヘッドレスのパイプライン起動経路。lu_export.py 等 tkinter の無い
# python環境からも読み込まれる)が equipment_select_dialog を直接
# importすると、tkinter未導入環境で ModuleNotFoundError: No module
# named 'tkinter' を起こして即死する
# (症状: convert.ps1 が [D2P_LU_NO_RESULT] で失敗)。
#
# 本モジュールは load_selected_codes()/save_selected_codes() など
# 「選択状態の保存・読み出しロジック」のみを tkinter 非依存の形で
# 切り出したもの。ui\equipment_select_dialog.py はこちらを import して
# 使う(UI層 → store層の一方向依存)。pipeline_runner.py は本モジュール
# のみを import する(ui\equipment_select_dialog.py を import しない)。
from __future__ import annotations

import json
import os
from typing import List, Optional

_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))

# app_py直下でi18nをimportできるよう、sys.pathへの追加はmain_window.py等
# 既存呼び出し元が既に行っている前提(pipeline_runner.py/equipment_select_dialog.py
# と同じ流儀)。本モジュール単体でも動くよう念のため追加しておく。
import sys  # noqa: E402

if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402

LAB_FEATURE_ID = "equipment_filter"
_STATE_FILENAME = "settings_lab_equipment_filter.json"


# ---------------------------------------------------------------------------
# 選択状態の永続化(app_root直下の平文JSON。settings.pyのUTF-8/Trim流儀に
# 合わせるが、settings.pyの書き込み許可(§2.8の4ファイル限定)には含まれない
# ためファイルを分け、本モジュールが単独で読み書きする)。
# 未選択(空リスト/ファイル不在)=ラボ憲章④の既定値=従来どおり全装備。
# ---------------------------------------------------------------------------

def _state_path(app_root: str) -> str:
    return os.path.join(app_root, _STATE_FILENAME)


def load_selected_codes(app_root: str) -> List[str]:
    """保存済みの選択装備コード一覧(ソート済み、重複無し)。ファイル不在/
    壊れている/形式が違う場合は空リスト(=未選択=既定値、安全側)。"""
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
    """codesが空なら「未選択」を意味するファイル内容を書く(ファイル自体は
    残すが selected=[] とする——次回 load_selected_codes は空リストを返す
    ので挙動は「ファイル不在」と等価)。書き込み失敗は握りつぶす
    (settings.py _write_text と同じ方針、設定保存の失敗で画面を止めない)。"""
    path = _state_path(app_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"selected": sorted({c for c in codes if c})}, f,
                      ensure_ascii=False, indent=1)
    except OSError:
        pass


def reset(app_root: str) -> None:
    """dev#1186レジストリ記述子の「既定値リセット関数」。ラボ窓の
    『全てのラボ機能を無効化』ボタンから呼ばれる想定。既定値=未選択(空)。"""
    save_selected_codes(app_root, [])


def is_active(app_root: str) -> bool:
    """ラボ機能が既定から変更されているか(=1件以上選択済みか)。
    dev#1186の警告文表示条件(1つでも非既定のとき表示)の判定に使う想定。"""
    return bool(load_selected_codes(app_root))


def state_summary(app_root: str, lang: Optional[str] = None) -> Optional[str]:
    """dev#1186レジストリ記述子の「状態サマリ関数」。無効(未選択)なら
    None、有効なら短い概要(lab_window.py側が『有効: <この文字列>』へ整形
    する想定、dev#1186コメント2「状態列に『有効: 3着』の形で概要を表示する
    ため、本機能は選択数のサマリ文字列を提供すること」)。"""
    n = len(load_selected_codes(app_root))
    if n == 0:
        return None
    return i18n.S("LabEquipmentFilterSummaryFormat", lang).format(n)
