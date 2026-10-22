# test_lab_window_no_gender_dev336.py -- dev#336(性別限定)UI除去の受入根拠。
#
# 2026-08-08 オーナー裁定「性別限定はラボ第1弾に搭載しない」(dev#336の
# 2026-08-08コメント。構造制約: DT行フラグが性別共通で除外性別の首なしが
# 必然)を受け、app_py\ui\lab_window.py のラボ機能レジストリ(LAB_FEATURES)
# から性別限定機能(gender_select_dialog.LAB_FEATURE_ID="gender_filter")を
# 除去した。本ファイルはその除去自体を機械的に固定する。
#
# 「出ないこと」の検証は、ただ空集合を主張するだけでは意味が薄い(実装漏れで
# LAB_FEATURESごと壊れていても"gender_filterが無い"は真になってしまう)ため、
# 負の対照として「他の既存機能(drop_bones/装備限定/頭装備切り替え、および
# PR #1264/dev#1168前半で追加されたメッシュ削除)は引き続き出ていること」も
# 同時に固定し、検出力があることを示す。件数の絶対値ではなく「4機能以上」
# (今後の追加を妨げない)+個別IDの存在で検証する。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

from ui import equipment_select_dialog  # noqa: E402
from ui import gender_select_dialog  # noqa: E402  (LAB_FEATURE_ID定数の参照のみ。ダイアログ自体は開かない)
from ui import headequip_select_dialog  # noqa: E402
from ui import lab_window  # noqa: E402


def test_gender_filter_feature_id_is_absent_from_registry():
    """本題: 性別限定(gender_filter)はレジストリに存在しないこと。"""
    feature_ids = {f.feature_id for f in lab_window.LAB_FEATURES}
    assert gender_select_dialog.LAB_FEATURE_ID not in feature_ids
    assert "gender_filter" not in feature_ids


def test_negative_control_other_three_features_still_present():
    """負の対照: gender_filterの不在は「レジストリが正しく機能している
    証拠」であって「レジストリごと壊れている副作用」ではないことを、
    他の既存機能が引き続き出ていることで示す(2026-08-09 PR #1264で
    メッシュ削除が追加され4機能目になったため、件数は絶対値ではなく
    下限で確認する)。"""
    feature_ids = {f.feature_id for f in lab_window.LAB_FEATURES}
    assert "drop_bones" in feature_ids
    assert equipment_select_dialog.LAB_FEATURE_ID in feature_ids
    assert headequip_select_dialog.LAB_FEATURE_ID in feature_ids
    assert len(lab_window.LAB_FEATURES) >= 4


def test_lab_window_module_does_not_import_gender_select_dialog_symbol():
    """lab_window.py自体がgender_select_dialogモジュールへの結線シンボル
    (GENDER_FILTER_FEATURE等)を持たないこと(モジュール属性レベルの確認。
    importでの結線復活を検出できる)。"""
    assert not hasattr(lab_window, "GENDER_FILTER_FEATURE")
    assert not hasattr(lab_window, "gender_select_dialog")
