# test_lab_window_disable_all_closes_open_dialogs_dev1343.py -- dev#1343
# (2026-08-10 オーナー実機報告「マルチアバターウィンドウ開いてる状態で
# 『全てのラボ機能無効化』をおすとリセットされない」)。
#
# 横断調査の結論(詳細: work/NOTES.md): 全7ラボ機能ダイアログ
# (drop_bones/equipment_filter/headequip_toggle/mesh_delete/
# dt_flag_head_hide/shapekey/multi_avatar_pak)は共通して「開いた時点で
# 永続ストアの現在値を1回だけメモリへスナップショットし、OK/プレビュー
# 保存(または装備クリックのような即時保存)が起きたときにそのスナップ
# ショットをそのままディスクへ書き戻す」設計になっている。「全てのラボ
# 機能を無効化」でディスク側を既定値へ戻しても、開いたままのダイアログは
# それに気づかず、後から保存操作を行うと古いスナップショットが書き戻されて
# リセットが巻き戻る。
#
# 修正(lab_window.py open_lab_window()): 「全無効化」ボタンは、開いている
# 全てのラボ機能ダイアログを先にdestroy()してからreset_all_features()を
# 呼ぶ(7ダイアログファイル自体は無改変)。
#
# 本ファイルの構成:
#   1. 全7機能について: 「設定...」でダイアログを開いたまま「全ての
#      ラボ機能を無効化」を押すと、①ダイアログがdestroyされる ②ストアが
#      既定へ戻ることを機械判定(修正の直接検証)
#   2. 負の対照2件(drop_bones/multi_avatar_pak): 「ダイアログを閉じずに
#      ストアだけをリセットする」(=dev#1343修正前の_disable_all()と同じ
#      経路)と、開いたままのダイアログの保存操作が古いスナップショットを
#      書き戻し、リセットが巻き戻ることを再現する。全7機能が同一の実装
#      パターン(NOTES.md調査表)であるため、代表2件(オーナー実機報告の
#      当事者=multi_avatar_pak、最も単純なOK型=drop_bones)で検出力を示す。
#
# 実tk.Tk()は作らない(conftest.pyの共有hidden_root、既存慣例踏襲)。
from __future__ import annotations

import os
import sys
import tempfile
import tkinter as tk
from unittest import mock

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import multi_avatar_pak_store as map_store  # noqa: E402
from ui import dt_flag_head_hide_dialog as dfd  # noqa: E402
from ui import equipment_select_dialog as esd  # noqa: E402
from ui import headequip_select_dialog as hed  # noqa: E402
from ui import lab_window  # noqa: E402
from ui import mesh_delete_dialog as mdd  # noqa: E402
from ui import multi_avatar_pak_dialog as mapd  # noqa: E402
from ui import shapekey_select_dialog as skd  # noqa: E402

# ---------------------------------------------------------------------------
# 共通ヘルパー(test_lab_window_ui.py/test_multi_avatar_pak_dialog_ui_dev1170.py
# と同じ流儀)
# ---------------------------------------------------------------------------


class _FakeSelf:
    """lab_window.pyの各機能アダプタが要求する最小のself。app_root/work_root
    はテストごとに専用tempdirを持つ(store間の汚染防止)。widgets["vrmBox"]は
    意図的に空文字のまま(未選択扱い=mesh_delete/shapekeyのカタログ取得は
    フォールバックへ落ちる、既存test_lab_window_ui.pyと同じ意図)。"""

    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self.widgets = {
            "dropBonesBox": tk.Entry(root),
            "vrmBox": tk.Entry(root),
        }
        self.app_root = tempfile.mkdtemp(prefix="d2p_lab_test_dev1343_")
        self.work_root = tempfile.mkdtemp(prefix="d2p_lab_test_dev1343_work_")


def _find_children(widget, cls):
    found = []
    for child in widget.winfo_children():
        if isinstance(child, cls):
            found.append(child)
        found.extend(_find_children(child, cls))
    return found


def _find_button(widget, text: str):
    for btn in _find_children(widget, tk.Button):
        if btn.cget("text") == text:
            return btn
    return None


def _find_button_startswith(widget, prefix: str):
    for btn in _find_children(widget, tk.Button):
        if btn.cget("text").startswith(prefix):
            return btn
    return None


def _find_entry(widget):
    entries = _find_children(widget, tk.Entry)
    return entries[0] if entries else None


def _feature_index(feature_id: str) -> int:
    return [f.feature_id for f in lab_window.LAB_FEATURES].index(feature_id)


def _open_feature_dialog_via_configure_button(dlg: tk.Toplevel, feature_id: str) -> tk.Toplevel:
    """ラボ窓(dlg)の「設定...」ボタン群のうち、feature_idの行にあたるものを
    クリックし、新規に現れたサブダイアログ(Toplevel)を返す。「設定...」は
    全機能行で同一文字列のため、LAB_FEATURESの並び順(=行の並び順)で
    位置照合する。"""
    idx = _feature_index(feature_id)
    before_ids = {id(c) for c in dlg.winfo_children() if isinstance(c, tk.Toplevel)}
    configure_buttons = [
        b for b in _find_children(dlg, tk.Button)
        if b.cget("text") == i18n.S("BtnLabConfigure")
    ]
    assert len(configure_buttons) == len(lab_window.LAB_FEATURES)
    configure_buttons[idx].invoke()
    after = [
        c for c in dlg.winfo_children()
        if isinstance(c, tk.Toplevel) and id(c) not in before_ids
    ]
    assert len(after) == 1, f"設定...クリックでサブダイアログが1つ生成されていない: {after}"
    return after[0]


def _click_disable_all(dlg: tk.Toplevel) -> None:
    btn = _find_button(dlg, i18n.S("BtnLabDisableAll"))
    assert btn is not None
    btn.invoke()


# ---------------------------------------------------------------------------
# 1. 全7機能: 「設定...」で開いたまま「全てのラボ機能を無効化」→
#    ①ダイアログがdestroyされる ②ストアが既定へ戻る
# ---------------------------------------------------------------------------


def test_disable_all_closes_open_dialog_and_resets_drop_bones_dev1343(hidden_root):
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root)
    self.widgets["dropBonesBox"].insert(0, "Bone_L")
    assert lab_window.drop_bones_status_summary(self) is not None

    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        sub_dlg = _open_feature_dialog_via_configure_button(dlg, "drop_bones")
        assert sub_dlg.winfo_exists()

        _click_disable_all(dlg)

        assert not sub_dlg.winfo_exists(), "全無効化を押してもダイアログが閉じられていない"
        assert lab_window.drop_bones_status_summary(self) is None, (
            "全無効化してもストアが既定に戻っていない")
    finally:
        dlg.destroy()


def test_disable_all_closes_open_dialog_and_resets_equipment_filter_dev1343(
    hidden_root, monkeypatch
):
    i18n.set_language("ja")
    monkeypatch.setattr(lab_window.pak_manager, "paks_dir_quiet", lambda *a, **k: None)
    self = _FakeSelf(hidden_root)
    esd.save_selected_codes(self.app_root, ["Bronze001"])
    assert lab_window._equipment_filter_status_summary(self) is not None

    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        sub_dlg = _open_feature_dialog_via_configure_button(dlg, "equipment_filter")
        assert sub_dlg.winfo_exists()

        _click_disable_all(dlg)

        assert not sub_dlg.winfo_exists(), "全無効化を押してもダイアログが閉じられていない"
        assert lab_window._equipment_filter_status_summary(self) is None, (
            "全無効化してもストアが既定に戻っていない")
    finally:
        dlg.destroy()


def test_disable_all_closes_open_dialog_and_resets_headequip_toggle_dev1343(
    hidden_root, monkeypatch
):
    i18n.set_language("ja")
    monkeypatch.setattr(lab_window.pak_manager, "paks_dir_quiet", lambda *a, **k: None)
    self = _FakeSelf(hidden_root)
    hed.save_selected_codes(self.app_root, ["HeadEquip001"])
    assert lab_window._headequip_toggle_status_summary(self) is not None

    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        sub_dlg = _open_feature_dialog_via_configure_button(dlg, "headequip_toggle")
        assert sub_dlg.winfo_exists()

        _click_disable_all(dlg)

        assert not sub_dlg.winfo_exists(), "全無効化を押してもダイアログが閉じられていない"
        assert lab_window._headequip_toggle_status_summary(self) is None, (
            "全無効化してもストアが既定に戻っていない")
    finally:
        dlg.destroy()


def test_disable_all_closes_open_dialog_and_resets_mesh_delete_dev1343(hidden_root):
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root)
    # avatar="" (vrmBox未選択)と揃える -- _mesh_delete_status_summary()が
    # 読むavatarも同じく空文字。
    mdd.save_deleted_names(self.app_root, "", ["MeshA"])
    assert lab_window._mesh_delete_status_summary(self) is not None

    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        sub_dlg = _open_feature_dialog_via_configure_button(dlg, "mesh_delete")
        assert sub_dlg.winfo_exists()

        _click_disable_all(dlg)

        assert not sub_dlg.winfo_exists(), "全無効化を押してもダイアログが閉じられていない"
        assert lab_window._mesh_delete_status_summary(self) is None, (
            "全無効化してもストアが既定に戻っていない")
    finally:
        dlg.destroy()


def test_disable_all_closes_open_dialog_and_resets_dt_flag_head_hide_dev1343(hidden_root):
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root)
    dfd.save_enabled(self.app_root, True)
    assert lab_window._dt_flag_head_hide_status_summary(self) is not None

    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        sub_dlg = _open_feature_dialog_via_configure_button(dlg, "dt_flag_head_hide")
        assert sub_dlg.winfo_exists()

        _click_disable_all(dlg)

        assert not sub_dlg.winfo_exists(), "全無効化を押してもダイアログが閉じられていない"
        assert lab_window._dt_flag_head_hide_status_summary(self) is None, (
            "全無効化してもストアが既定に戻っていない")
    finally:
        dlg.destroy()


def test_disable_all_closes_open_dialog_and_resets_shapekey_dev1343(hidden_root):
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root)
    skd.save_config(self.app_root, "", {"Body": {"smile": 1.0}})
    assert lab_window._shapekey_status_summary(self) is not None

    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        sub_dlg = _open_feature_dialog_via_configure_button(dlg, "shape_keys")
        assert sub_dlg.winfo_exists()

        _click_disable_all(dlg)

        assert not sub_dlg.winfo_exists(), "全無効化を押してもダイアログが閉じられていない"
        assert lab_window._shapekey_status_summary(self) is None, (
            "全無効化してもストアが既定に戻っていない")
    finally:
        dlg.destroy()


def test_disable_all_closes_open_dialog_and_resets_multi_avatar_pak_dev1343(
    hidden_root, monkeypatch
):
    """オーナー実機報告そのもの(マルチアバターPAKダイアログ)の直接検証。"""
    i18n.set_language("ja")
    monkeypatch.setattr(lab_window.pak_manager, "paks_dir_quiet", lambda *a, **k: None)
    self = _FakeSelf(hidden_root)
    map_store.save_assignments(self.app_root, {"Bronze001": "SomeEntry"})
    assert lab_window._multi_avatar_pak_status_summary(self) is not None

    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        sub_dlg = _open_feature_dialog_via_configure_button(dlg, "multi_avatar_pak")
        assert sub_dlg.winfo_exists()

        _click_disable_all(dlg)

        assert not sub_dlg.winfo_exists(), "全無効化を押してもダイアログが閉じられていない"
        assert lab_window._multi_avatar_pak_status_summary(self) is None, (
            "全無効化してもストアが既定に戻っていない")
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 2. 負の対照: 「ダイアログを閉じずにストアだけをリセットする」
#    (=dev#1343修正前の_disable_all()と同じ経路)だと、開いたままの
#    ダイアログの保存操作が古いスナップショットを書き戻し、リセットが
#    巻き戻ることを再現する(=このテスト群の検出力そのものの証明)。
# ---------------------------------------------------------------------------


def test_negative_control_drop_bones_reset_without_closing_lets_stale_ok_undo_it_dev1343(
    hidden_root,
):
    i18n.set_language("ja")
    self = _FakeSelf(hidden_root)
    self.widgets["dropBonesBox"].insert(0, "Bone_L")

    # lab_window.open_lab_window()の「設定...」ボタン経由ではなく、
    # 意図的にダイアログを直接開く(open_sub_dialogsの追跡対象にせず、
    # 「全無効化」で自動的に閉じられない状況を作るため)。
    dlg = lab_window.open_drop_bones_dialog(self, hidden_root, lambda: None)
    try:
        # ダイアログはこの時点で"Bone_L"をスナップショット済み(カタログ
        # 取得失敗によるフォールバックのカンマ区切り手入力Entryに反映)。

        # ダイアログを閉じずに、ストアだけを外部からリセットする
        # (dev#1343修正前の_disable_all()が実際にやっていたこと)。
        lab_window.reset_all_features(self)
        assert self.widgets["dropBonesBox"].get() == "", (
            "reset_all_features自体は正しくリセットしている")

        # ユーザーが(古いスナップショットを見せたままの)ダイアログのOKを
        # 押すと、古い値がそのまま書き戻される。
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        assert ok_btn is not None
        ok_btn.invoke()

        assert self.widgets["dropBonesBox"].get() == "Bone_L", (
            "ダイアログを閉じずにリセットした場合、古いスナップショットの"
            "書き戻しでリセットが巻き戻るはず(この再現がテストの検出力)")
    finally:
        try:
            dlg.destroy()
        except tk.TclError:
            pass


def test_negative_control_multi_avatar_pak_reset_without_closing_lets_click_undo_it_dev1343(
    hidden_root,
):
    """オーナー実機報告の機序そのもの: OKボタン不要、装備を1回クリックする
    だけで古い割当が書き戻る(multi_avatar_pak_dialogは他の6機能よりも
    再現の閾値が低い、work/NOTES.md調査表参照)。"""
    i18n.set_language("ja")
    app_root = tempfile.mkdtemp(prefix="d2p_lab_test_dev1343_neg_")
    work_root = tempfile.mkdtemp(prefix="d2p_lab_test_dev1343_neg_work_")
    map_store.save_assignments(app_root, {"Bronze001": "Alicia", "Cloth002": "Alicia"})

    fake_catalog = {"ok": True, "source": "test", "detail": "",
                     "codes": ["Bronze001", "Cloth002"], "names": {}}
    self = _FakeSelf(hidden_root)
    self.app_root = app_root
    self.work_root = work_root

    with mock.patch.object(
        mapd.equipment_select_dialog, "query_equipment_catalog", return_value=fake_catalog
    ), mock.patch.object(mapd.pak_manager, "list_library_entries", return_value=[
        {"entry_id": "Alicia", "job_dir": os.path.join(work_root, "Alicia"),
         "avatar_name": "Alicia"},
    ]), mock.patch.object(mapd.pak_manager, "entry_is_multi_avatar", return_value=False), \
         mock.patch.object(mapd.pak_manager, "partition_library_entries_for_multi_avatar_pak",
                            return_value=(
                                [{"entry_id": "Alicia",
                                  "job_dir": os.path.join(work_root, "Alicia"),
                                  "avatar_name": "Alicia"}],
                                [],
                            )):
        # lab_window._open_multi_avatar_pak_dialog()経由ではなく直接開く
        # (open_sub_dialogsの追跡対象外にするため、上のdrop_bones負の対照と
        # 同じ意図)。
        ctx = mapd.MultiAvatarPakContext(
            app_root=app_root, work_root=work_root, palworld_pak=None, lang="ja")
        dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, ctx)
        try:
            # ダイアログは開いた時点でassignments_state["data"]へ
            # {"Bronze001": "Alicia", "Cloth002": "Alicia"} をスナップショット
            # 済み(main画面、右ペインにAliciaボタンが出ている状態)。

            # ダイアログを閉じずに、ストアだけを外部からリセットする。
            lab_window.reset_all_features(self)
            assert map_store.load_assignments(app_root) == {}, (
                "reset_all_features自体は正しくストアをリセットしている")

            # ユーザーが(古いスナップショットを見せたままの)ダイアログで
            # 右ペインのアバターを選び、装備を1件クリックする。
            avatar_btn = _find_button(dlg, "Alicia")
            assert avatar_btn is not None
            avatar_btn.invoke()
            eq_btn = _find_button_startswith(dlg, "Bronze001")
            assert eq_btn is not None
            eq_btn.invoke()

            # dev#1341(遅延書き込み)適用後: クリック直後はメモリ上の
            # 関連付けのみで、ディスクへはまだ反映されない
            # (assign_many()の同期I/Oが撤廃されたため)。
            assert map_store.load_assignments(app_root) == {}, (
                "dev#1341以降、クリック直後にディスクへ即時反映されるはずが"
                "ない(遅延書き込みの前提が崩れている)")

            # …しかし、このダイアログを閉じる(dev#1341の正規クローズ経路
            # ="Close"ボタン=WM_DELETE_WINDOWと同じ_on_close())と、
            # 保留中の(古いスナップショットに基づく)編集がまとめて
            # ディスクへ書き戻され、ディスク上のリセットが巻き戻ってしまう
            # (=「ダイアログをdestroy()で先に閉じずに全無効化すると
            # リセットされない」という、dev#1343が防いでいるリスクの実体。
            # dev#1341はこの巻き戻りの発火点をクリック時→クローズ時へ
            # 移しただけで、リスク自体は消えていない)。
            close_btn = _find_button(dlg, i18n.S("BtnClose"))
            assert close_btn is not None
            close_btn.invoke()

            assert map_store.is_active(app_root) is True, (
                "この巻き戻りが再現しないなら、このテストの検出力が無いことになる")
        finally:
            try:
                dlg.destroy()
            except tk.TclError:
                pass
