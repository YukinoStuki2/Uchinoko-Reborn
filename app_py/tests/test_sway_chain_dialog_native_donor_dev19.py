# test_sway_chain_dialog_native_donor_dev19.py -- dev#19 native-donor-rule WP
# (issue #19、2026-08-14夜オーナー最終裁定)の単体テスト。
#
# ラボ「揺れもの詳細設定」(app_py\ui\sway_chain_dialog.py)の既定チェック
# 状態が、pipeline\py\sway_identify.py の同定結果(尻尾・耳=ON、その他=OFF)
# と一致すること、保存済み上書き(sway_chain_override_store)があれば常に
# 同定結果より優先されることを確認する。実tk.Tk()は作らない
# (_merge_working_set()はtkinter非依存の純粋関数)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

from ui import sway_chain_dialog as scd  # noqa: E402


# SAMPLE_CHAINS(scd.SAMPLE_CHAINS)は「尻尾1・耳2(L/R)・髪1・スカート2」を
# 網羅する既存の開発確認用データで、本テストの正/負の対照としてそのまま
# 使える(データの意味づけは変えない、読み取りのみ)。


def _by_name(entry):
    return entry["bones"][-1]


def test_default_enabled_matches_identification_tail_and_ear_on():
    working = scd._merge_working_set(scd.SAMPLE_CHAINS, [])
    enabled_by_name = {_by_name(e): e["enabled"] for e in working}
    assert enabled_by_name["Tail_03"] is True
    assert enabled_by_name["EarL_02"] is True
    assert enabled_by_name["EarR_02"] is True


def test_default_enabled_matches_identification_skirt_and_hair_off():
    working = scd._merge_working_set(scd.SAMPLE_CHAINS, [])
    enabled_by_name = {_by_name(e): e["enabled"] for e in working}
    assert enabled_by_name["HairBack_04"] is False
    assert enabled_by_name["Skirt_F_02"] is False
    assert enabled_by_name["Skirt_B_02"] is False


def test_saved_override_enabled_wins_over_identification_default():
    """明示ON上書きがあれば、同定が既定OFFの鎖(スカート)でも対象化される。"""
    skirt_entry = next(c for c in scd.SAMPLE_CHAINS if _by_name(c) == "Skirt_F_02")
    override = [{
        "bones": skirt_entry["bones"], "enabled": True, "hardness": "follow",
        "manual": False,
    }]
    working = scd._merge_working_set(scd.SAMPLE_CHAINS, override)
    enabled_by_name = {_by_name(e): e["enabled"] for e in working}
    assert enabled_by_name["Skirt_F_02"] is True


def test_saved_override_disabled_wins_over_identification_default():
    """明示OFF上書きがあれば、同定が既定ONの鎖(尻尾)でも除外される。"""
    tail_entry = next(c for c in scd.SAMPLE_CHAINS if _by_name(c) == "Tail_03")
    override = [{
        "bones": tail_entry["bones"], "enabled": False, "hardness": "follow",
        "manual": False,
    }]
    working = scd._merge_working_set(scd.SAMPLE_CHAINS, override)
    enabled_by_name = {_by_name(e): e["enabled"] for e in working}
    assert enabled_by_name["Tail_03"] is False
