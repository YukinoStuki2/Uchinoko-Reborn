# dt_flag_head_hide_store.py -- dev#1258(WP-E、2026-08-09オーナー裁定)
# ラボ機能「差替え中装備のみ頭OFF」の選択状態永続化ロジック(tkinter非依存)。
#
# equipment_filter_store.py/headequip_filter_store.pyと同じ理由(pipeline_runner.py
# がヘッドレス経路からもimportできるよう、tkinterをimportするui\側とは
# 分離する)。本機能は単一の真偽値トグルのみのため、他の2ストアと違い
# リスト保存ではなくbool 1個を保存する最小構成。
#
# **意味論**: True(=ON)がラボ機能の「有効」状態で、v2.6.0までの既定
# (dev#1198のDTフラグ方式、bIsFullBodyEquipment)に切り替える。
# False(=OFF、既定)は、Head/Hairを常時空スタブ化する新既定(dev#1258で
# 反転したパイプライン既定、work\rd_1258\PROPOSAL.md参照)のまま何もしない。
from __future__ import annotations

import json
import os
import sys
from typing import Optional

_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402

LAB_FEATURE_ID = "dt_flag_head_hide"
_STATE_FILENAME = "settings_lab_dt_flag_head_hide.json"


def _state_path(app_root: str) -> str:
    return os.path.join(app_root, _STATE_FILENAME)


def load_enabled(app_root: str) -> bool:
    """保存済みのON/OFF状態。ファイル不在/壊れている/形式が違う場合は
    False(=既定=OFF=新既定のスタブ方式のまま、安全側)。"""
    path = _state_path(app_root)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        enabled = data.get("enabled")
        if isinstance(enabled, bool):
            return enabled
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        pass
    return False


def save_enabled(app_root: str, enabled: bool) -> None:
    """書き込み失敗は握りつぶす(equipment_filter_store.pyと同じ方針)。"""
    path = _state_path(app_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"enabled": bool(enabled)}, f,
                      ensure_ascii=False, indent=1)
    except OSError:
        pass


def reset(app_root: str) -> None:
    """dev#1186レジストリ記述子の「既定値リセット関数」。既定値=OFF。"""
    save_enabled(app_root, False)


def is_active(app_root: str) -> bool:
    """ラボ機能が既定から変更されているか(=ON状態か)。"""
    return load_enabled(app_root)


def state_summary(app_root: str, lang: Optional[str] = None) -> Optional[str]:
    """dev#1186レジストリ記述子の「状態サマリ関数」。OFF(既定)ならNone、
    ONなら短い概要(lab_window.py側が『有効: <この文字列>』へ整形する
    想定)。単一の真偽値トグルなので固定文言のみ。"""
    if not load_enabled(app_root):
        return None
    return i18n.S("LabDtFlagHeadHideSummary", lang)
