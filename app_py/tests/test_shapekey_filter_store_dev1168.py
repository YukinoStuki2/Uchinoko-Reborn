# test_shapekey_filter_store_dev1168.py -- dev#1168(シェイプキー)ラボ機能。
#
# app_py\shapekey_filter_store.py の単体試験(tkinter非依存)。柱:
#   1. 既定(未設定)はload_config()==空dict/is_active()==False/state_summary()
#      ==None(ラボ憲章④)
#   2. save/load往復、0値・非数値は保存されない
#   3. avatar_pathが保存時と異なる場合は既定値扱い(誤爆防止の中核仕様)
#   4. reset()で全消去
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import shapekey_filter_store as sfs  # noqa: E402


def test_default_state_is_empty_and_inactive(tmp_path):
    app_root = str(tmp_path)
    avatar = str(tmp_path / "avatar.vrm")
    assert sfs.load_config(app_root, avatar) == {}
    assert sfs.is_active(app_root, avatar) is False
    assert sfs.state_summary(app_root, avatar) is None


def test_save_then_load_round_trip_for_same_avatar(tmp_path):
    app_root = str(tmp_path)
    avatar = str(tmp_path / "avatar.vrm")
    sfs.save_config(app_root, avatar, {"Body": {"smile": 0.5, "blink": 1.0}})

    loaded = sfs.load_config(app_root, avatar)
    assert loaded == {"Body": {"smile": 0.5, "blink": 1.0}}
    assert sfs.is_active(app_root, avatar) is True


def test_zero_and_non_numeric_values_are_not_saved(tmp_path):
    app_root = str(tmp_path)
    avatar = str(tmp_path / "avatar.vrm")
    sfs.save_config(app_root, avatar, {
        "Body": {"smile": 0.0, "blink": 0.7, "bad": "not_a_number"},
    })
    loaded = sfs.load_config(app_root, avatar)
    assert loaded == {"Body": {"blink": 0.7}}


def test_mesh_that_ends_up_with_no_values_is_dropped(tmp_path):
    app_root = str(tmp_path)
    avatar = str(tmp_path / "avatar.vrm")
    sfs.save_config(app_root, avatar, {"Body": {"smile": 0.0}, "Hair": {"wave": 0.3}})
    loaded = sfs.load_config(app_root, avatar)
    assert loaded == {"Hair": {"wave": 0.3}}
    assert "Body" not in loaded


def test_different_avatar_path_is_treated_as_default(tmp_path):
    """負の対照(誤爆防止の中核仕様): 別アバターへ切り替えると、保存済みの
    値が同名メッシュ/キーであっても一切適用されない(既定値扱い)。"""
    app_root = str(tmp_path)
    avatar_a = str(tmp_path / "avatar_a.vrm")
    avatar_b = str(tmp_path / "avatar_b.vrm")
    sfs.save_config(app_root, avatar_a, {"Body": {"smile": 1.0}})

    assert sfs.load_config(app_root, avatar_a) == {"Body": {"smile": 1.0}}
    assert sfs.load_config(app_root, avatar_b) == {}
    assert sfs.is_active(app_root, avatar_b) is False


def test_reset_clears_regardless_of_avatar(tmp_path):
    app_root = str(tmp_path)
    avatar = str(tmp_path / "avatar.vrm")
    sfs.save_config(app_root, avatar, {"Body": {"smile": 1.0}})
    assert sfs.is_active(app_root, avatar) is True

    sfs.reset(app_root)

    assert sfs.load_config(app_root, avatar) == {}
    assert sfs.is_active(app_root, avatar) is False


def test_corrupt_state_file_falls_back_to_empty(tmp_path):
    app_root = str(tmp_path)
    avatar = str(tmp_path / "avatar.vrm")
    with open(sfs._state_path(app_root), "w", encoding="utf-8") as f:
        f.write("{ not valid json")
    assert sfs.load_config(app_root, avatar) == {}


def test_state_summary_counts_total_keys_across_meshes(tmp_path):
    app_root = str(tmp_path)
    avatar = str(tmp_path / "avatar.vrm")
    sfs.save_config(app_root, avatar, {
        "Body": {"smile": 0.5, "blink": 1.0},
        "Hair": {"wave": 0.3},
    })
    summary = sfs.state_summary(app_root, avatar, lang="en")
    assert summary is not None
    assert "3" in summary


def test_avatar_path_normalization_handles_case_and_slashes(tmp_path):
    """Windowsのパス比較は大文字小文字・スラッシュ種を区別しない前提
    (os.path.normcase)。保存時と読み出し時で表記ゆれがあっても一致すること。"""
    app_root = str(tmp_path)
    avatar_dir = tmp_path / "sub"
    avatar_dir.mkdir()
    avatar_file = avatar_dir / "Avatar.vrm"
    avatar_file.write_bytes(b"x")

    sfs.save_config(app_root, str(avatar_file), {"Body": {"smile": 1.0}})

    variant = str(avatar_file).replace("\\", "/")
    assert sfs.load_config(app_root, variant) == {"Body": {"smile": 1.0}}


def test_registry_ids_and_i18n_keys_are_sane():
    assert sfs.LAB_FEATURE_ID == "shape_keys"
    # state_summaryが参照するi18nキーが5言語とも非空であること
    for lang in i18n.LANGS:
        assert i18n.S("LabShapeKeysSummaryFormat", lang)
        assert not i18n.S("LabShapeKeysSummaryFormat", lang).startswith("??")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
