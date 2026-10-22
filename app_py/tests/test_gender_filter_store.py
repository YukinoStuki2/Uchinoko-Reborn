# test_gender_filter_store.py -- dev#336(性別限定)ラボ機能の永続化ロジック
# (app_py\gender_filter_store.py)の単体テスト。tkinter非依存。
#
# equipment_filter_store.pyのテスト慣例(app_py\tests\
# test_equipment_select_dialog_dev165.py 節1「選択状態の永続化+状態
# サマリ」)を踏襲するが、選択は単一値("Male"/"Female"/None)であり
# チェックリストのコード集合ではない点が異なる。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import gender_filter_store as gfs  # noqa: E402
import i18n  # noqa: E402


def test_default_state_is_none_and_inactive(tmp_path):
    app_root = str(tmp_path)
    assert gfs.load_selected_gender(app_root) is None
    assert gfs.is_active(app_root) is False
    assert gfs.state_summary(app_root) is None


def test_save_then_load_round_trip_male(tmp_path):
    app_root = str(tmp_path)
    gfs.save_selected_gender(app_root, "Male")
    assert gfs.load_selected_gender(app_root) == "Male"
    assert gfs.is_active(app_root) is True


def test_save_then_load_round_trip_female(tmp_path):
    app_root = str(tmp_path)
    gfs.save_selected_gender(app_root, "Female")
    assert gfs.load_selected_gender(app_root) == "Female"
    assert gfs.is_active(app_root) is True


def test_save_none_resets_to_default(tmp_path):
    app_root = str(tmp_path)
    gfs.save_selected_gender(app_root, "Male")
    assert gfs.is_active(app_root) is True
    gfs.save_selected_gender(app_root, None)
    assert gfs.load_selected_gender(app_root) is None
    assert gfs.is_active(app_root) is False


def test_reset_clears_selection(tmp_path):
    app_root = str(tmp_path)
    gfs.save_selected_gender(app_root, "Female")
    assert gfs.is_active(app_root) is True
    gfs.reset(app_root)
    assert gfs.load_selected_gender(app_root) is None
    assert gfs.is_active(app_root) is False


def test_invalid_value_is_stored_as_none():
    """安全側: 未知の値("Both"等の不正な文字列)は保存時にNoneへ丸められる
    (壊れた保存を作らない)。"""
    import tempfile
    with tempfile.TemporaryDirectory() as app_root:
        gfs.save_selected_gender(app_root, "Robot")
        assert gfs.load_selected_gender(app_root) is None


def test_corrupt_state_file_falls_back_to_none(tmp_path):
    app_root = str(tmp_path)
    with open(gfs._state_path(app_root), "w", encoding="utf-8") as f:
        f.write("{ this is not valid json")
    assert gfs.load_selected_gender(app_root) is None


def test_missing_gender_key_falls_back_to_none(tmp_path):
    app_root = str(tmp_path)
    import json
    with open(gfs._state_path(app_root), "w", encoding="utf-8") as f:
        json.dump({"unexpected": "shape"}, f)
    assert gfs.load_selected_gender(app_root) is None


def test_state_summary_male_and_female_differ():
    import tempfile
    with tempfile.TemporaryDirectory() as app_root_m:
        gfs.save_selected_gender(app_root_m, "Male")
        summary_m = gfs.state_summary(app_root_m, lang="en")
    with tempfile.TemporaryDirectory() as app_root_f:
        gfs.save_selected_gender(app_root_f, "Female")
        summary_f = gfs.state_summary(app_root_f, lang="en")
    assert summary_m is not None
    assert summary_f is not None
    assert summary_m != summary_f


def test_negative_control_no_state_file_means_default(tmp_path):
    """負の対照: ファイル自体が存在しない(初回起動)状態でも既定値
    (両方=None)として振る舞うこと。equipment_filter_store.pyと同じ
    「ファイル不在=既定」契約。"""
    app_root = str(tmp_path)
    assert not os.path.exists(gfs._state_path(app_root))
    assert gfs.load_selected_gender(app_root) is None
    assert gfs.is_active(app_root) is False
