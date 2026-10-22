# test_lab_window_sway_style_open_dev1551.py -- dev#1551安全域WP
# (work\run_1551\laneR3_guifix\RESULT.md、WP受入ゲート2「実GUIで開けることの
# 証明」)当時は、統合パネル「ゆれかた」(app_py\ui\sway_style_dialog.py)が
# ui\lab_window.py経由(実際のGUIフロー: ラボ窓を開く->行の「設定」ボタンを
# 押す->open_dialog())で開けることを検証していた。
#
# **dev#1572(2026-08-18裁定「かたさが配線されていない問題」)がこの前提を
# 一時的に上書きした**: 鎖ごとの「ゆれかた」統合パネルへの入口(ラボ窓の行)
# ごとLAB_FEATURESから除去する形で隠蔽が実装された(PR#1584、第2便)。
#
# **2026-08-19訂正(第2便の過修正の是正、本WP)**: しかしこのパネルは
# 旧「揺れもの詳細設定」(チェインON/OFF+安全域スピンボックス)を吸収済み
# だったため、入口を丸ごと消すと安全域の設定手段まで画面から消えてしまう
# (オーナー実測)。本WPでSWAY_STYLE_FEATUREをLAB_FEATURESへ復帰させ、
# 「ゆれかた」関連ウィジェットの隠蔽はパネル内部
# (ui\sway_style_dialog.py、_SWAY_STYLE_PICKER_VISIBLE定数)側で行う方式へ
# 改めた。本ファイルはdev#1551時代の「ラボ窓経由で到達可能であること」の
# 証明を復活させる(acceptance条件1: LAB_FEATURESに含まれることのテスト)。
# 「ゆれかた」関連ウィジェットの到達不能性テストは
# test_sway_style_dialog_hides_style_ui_dev1572.py が担う。
#
# 実tkウィンドウは表示しない(conftest.pyの共有hidden_root、既存慣例踏襲)。
from __future__ import annotations

import os
import sys
import tempfile
import tkinter as tk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import lab_window  # noqa: E402


class _FakeSelf:
    """lab_window.open_lab_window()が要求する最小のself
    (test_lab_window_ui.py._FakeSelfと同じ流儀)。"""

    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        box = tk.Entry(root)
        box.insert(0, "C:\\fake.vrm")
        self.widgets = {"vrmBox": box}
        self.app_root = tempfile.mkdtemp(prefix="d2p_lab_test_")
        self.work_root = tempfile.mkdtemp(prefix="d2p_lab_test_work_")
        self._dev_sample_sway = True


def _find_children(widget, cls):
    found = []
    for child in widget.winfo_children():
        if isinstance(child, cls):
            found.append(child)
        found.extend(_find_children(child, cls))
    return found


def test_sway_style_feature_restored_in_lab_features_registry():
    """dev#1572是正WPの受入条件そのもの(acceptance条件1): SWAY_STYLE_
    FEATURE記述子はコードとして温存されており(定義自体は削除しない)、
    かつラボ窓が実際に描画するLAB_FEATURESリストに含まれる
    (feature_idで比較。安全域スピンボックスへの唯一の入口のため)。"""
    assert hasattr(lab_window, "SWAY_STYLE_FEATURE"), (
        "SWAY_STYLE_FEATURE定義自体が削除されている")
    registered_ids = {f.feature_id for f in lab_window.LAB_FEATURES}
    assert lab_window.SWAY_STYLE_FEATURE.feature_id in registered_ids, (
        "SWAY_STYLE_FEATUREがLAB_FEATURESから外れている"
        "(安全域スピンボックスへの入口が画面から消えてしまう、第2便の過修正)")


def test_sway_style_dialog_row_reachable_from_lab_window(hidden_root):
    """ラボ窓に「揺れもの詳細設定(安全域)」行(LabFeatureSwayStyles)が
    存在し、「設定」ボタン経由で統合パネルを開けること(dev#1551時代の
    検証を復活。本WPでLAB_FEATURESへ復帰させたため)。"""
    i18n.set_language("ja")
    fake_self = _FakeSelf(hidden_root)
    lab_dlg = lab_window.open_lab_window(fake_self, hidden_root)
    try:
        row_label_text = i18n.S("LabFeatureSwayStyles")
        labels = _find_children(lab_dlg, tk.Label)
        target_label = next(
            (w for w in labels if w.cget("text") == row_label_text), None)
        assert target_label is not None, (
            f"ラボ窓に{row_label_text!r}行が見つからない"
            "(安全域スピンボックスへの入口が到達不能なまま)")

        # 「設定」ボタンは全ラボ機能で同じ文言のため、target_labelと同じ
        # grid行のボタンを選ぶ(単純な文言一致だと先頭のdrop_bones行の
        # ボタンを誤って掴んでしまう)。
        target_row = target_label.grid_info()["row"]
        buttons = _find_children(lab_dlg, tk.Button)
        configure_btn = next(
            (b for b in buttons
             if b.cget("text") == i18n.S("BtnLabConfigure")
             and b.grid_info().get("row") == target_row),
            None,
        )
        assert configure_btn is not None, "対象行の「設定」ボタンが見つからない"
        configure_btn.invoke()

        sub_dialogs = [
            w for w in lab_dlg.winfo_children()
            if isinstance(w, tk.Toplevel)
        ]
        assert sub_dialogs, "「設定」ボタンを押しても統合パネルが開かれない"
        for d in sub_dialogs:
            d.destroy()
    finally:
        lab_dlg.destroy()
        i18n.set_language("ja")
