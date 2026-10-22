# test_mesh_delete_store_dev1168.py -- dev#1168前半(メッシュ削除)ラボ機能。
#
# app_py\mesh_delete_store.py の単体テスト(永続化ロジック本体、tkinter非依存)。
# 柱: 未使用時=既定=state_summary()がNone(ラボ憲章④)、save/load往復、
# reset、壊れたファイルからの安全なフォールバック、
# **保存スコープ=アバター単位(dev#1281残論点、指揮者裁定)**:
# 別アバターへ切り替えると保存済みの削除指定が一切適用されないこと
# (誤爆防止の中核仕様、shapekey_filter_store.pyの前例と同型)。
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import mesh_delete_store as mds  # noqa: E402


def test_default_state_is_empty_and_inactive(tmp_path):
    app_root = str(tmp_path)
    avatar = str(tmp_path / "avatar.vrm")
    assert mds.load_deleted_names(app_root, avatar) == []
    assert mds.is_active(app_root, avatar) is False
    assert mds.state_summary(app_root, avatar) is None


def test_save_then_load_round_trip_for_same_avatar(tmp_path):
    app_root = str(tmp_path)
    avatar = str(tmp_path / "avatar.vrm")
    mds.save_deleted_names(app_root, avatar, ["Beret", "Ribbon", "Ribbon"])
    loaded = mds.load_deleted_names(app_root, avatar)
    assert loaded == ["Beret", "Ribbon"]  # 重複除去+ソート済み
    assert mds.is_active(app_root, avatar) is True


def test_reset_clears_selection(tmp_path):
    app_root = str(tmp_path)
    avatar = str(tmp_path / "avatar.vrm")
    mds.save_deleted_names(app_root, avatar, ["Beret"])
    assert mds.is_active(app_root, avatar) is True
    mds.reset(app_root)
    assert mds.load_deleted_names(app_root, avatar) == []
    assert mds.is_active(app_root, avatar) is False


def test_state_summary_reflects_count(tmp_path):
    app_root = str(tmp_path)
    avatar = str(tmp_path / "avatar.vrm")
    mds.save_deleted_names(app_root, avatar, ["Beret", "Ribbon", "Hat"])
    summary = mds.state_summary(app_root, avatar, lang="en")
    assert summary is not None
    assert "3" in summary


def test_corrupt_state_file_falls_back_to_empty(tmp_path):
    app_root = str(tmp_path)
    avatar = str(tmp_path / "avatar.vrm")
    with open(mds._state_path(app_root), "w", encoding="utf-8") as f:
        f.write("{ this is not valid json")
    assert mds.load_deleted_names(app_root, avatar) == []
    assert mds.is_active(app_root, avatar) is False


def test_state_file_wrong_shape_falls_back_to_empty(tmp_path):
    app_root = str(tmp_path)
    avatar = str(tmp_path / "avatar.vrm")
    with open(mds._state_path(app_root), "w", encoding="utf-8") as f:
        json.dump({"avatar_path": mds._norm_avatar_path(avatar), "deleted": "not-a-list"}, f)
    assert mds.load_deleted_names(app_root, avatar) == []


def test_saved_file_content_shape(tmp_path):
    app_root = str(tmp_path)
    avatar = str(tmp_path / "avatar.vrm")
    mds.save_deleted_names(app_root, avatar, ["Beret"])
    with open(mds._state_path(app_root), encoding="utf-8") as f:
        data = json.load(f)
    assert data == {"avatar_path": mds._norm_avatar_path(avatar), "deleted": ["Beret"]}


# ---------------------------------------------------------------------------
# 保存スコープ=アバター単位(dev#1281残論点、指揮者裁定)。
# ---------------------------------------------------------------------------

def test_different_avatar_path_is_treated_as_default(tmp_path):
    """負の対照(誤爆防止の中核仕様): アバターAで削除指定した内容は、
    アバターBの読み出しには一切適用されない(既定値=空リスト扱い)。"""
    app_root = str(tmp_path)
    avatar_a = str(tmp_path / "avatar_a.vrm")
    avatar_b = str(tmp_path / "avatar_b.vrm")
    mds.save_deleted_names(app_root, avatar_a, ["Beret"])

    assert mds.load_deleted_names(app_root, avatar_a) == ["Beret"]
    assert mds.load_deleted_names(app_root, avatar_b) == []
    assert mds.is_active(app_root, avatar_b) is False
    assert mds.state_summary(app_root, avatar_b) is None


def test_switching_avatar_then_back_does_not_resurrect_other_avatars_setting(tmp_path):
    """アバターAで設定→アバターBに切り替え(空)→アバターAへ戻ると、
    Aの設定は単一ファイル方式のため既に上書きされていないかぎり残る
    (avatar_path組がAのままなら見える)。Bで何も保存しなければAの値は
    そのまま残っている(Bの操作がAの残留設定へ影響しないことの確認)。"""
    app_root = str(tmp_path)
    avatar_a = str(tmp_path / "avatar_a.vrm")
    avatar_b = str(tmp_path / "avatar_b.vrm")
    mds.save_deleted_names(app_root, avatar_a, ["Beret"])

    # Bへ切り替え: Bは空(既定値)であること
    assert mds.load_deleted_names(app_root, avatar_b) == []

    # Aへ戻る: Aの設定はまだ見える(Bの読み出しはファイルへ書き込んでいない)
    assert mds.load_deleted_names(app_root, avatar_a) == ["Beret"]


def test_avatar_path_normalization_handles_case_and_slashes(tmp_path):
    """Windowsのパス比較は大文字小文字・スラッシュ種を区別しない前提
    (os.path.normcase)。保存時と読み出し時で表記ゆれがあっても一致すること。"""
    app_root = str(tmp_path)
    avatar_dir = tmp_path / "sub"
    avatar_dir.mkdir()
    avatar_file = avatar_dir / "Avatar.vrm"
    avatar_file.write_bytes(b"x")

    mds.save_deleted_names(app_root, str(avatar_file), ["Beret"])

    variant = str(avatar_file).replace("\\", "/")
    assert mds.load_deleted_names(app_root, variant) == ["Beret"]


def test_registry_descriptor_shape():
    from ui import mesh_delete_dialog as mdd
    d = mdd.LAB_REGISTRY_DESCRIPTOR
    assert d["id"] == "mesh_delete"
    assert isinstance(d["name_key"], str)
    for lang in i18n.LANGS:
        assert i18n.S(d["name_key"], lang) and not i18n.S(d["name_key"], lang).startswith("??")
    assert callable(d["state_summary"])
    assert callable(d["open_dialog"])
    assert callable(d["reset"])


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
