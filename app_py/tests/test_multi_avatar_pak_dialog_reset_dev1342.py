# test_multi_avatar_pak_dialog_reset_dev1342.py -- dev#1342受入試験。
#
# 要望(2026-08-10深夜、オーナー指示): 「ああ後せっかくなんで「リセット」
# ボタンもつけといて」。マルチアバターPAK作成ダイアログに、装備→アバターの
# 対応表を既定状態へ1クリックで戻す「リセット」ボタンを追加する。
#
# 指揮者解釈(WP指示書に明記、逸脱として記録): issue本文は「既定割当
# (default_fill相当)へ戻す」と表現しているが、実装ではmulti_avatar_pak_
# store.reset()が定義する「既定値=未設定(空)」(dev#1186レジストリ記述子の
# 「既定値リセット関数」、同モジュールのreset()docstring参照)と同じ意味で
# 採用する。根拠: ①store.py側に元々 `reset = _store.reset`
# のエイリアスが用意されていた(lab_window.pyのラボ共通リセットから実際に
# 呼ばれている、_wire_multi_avatar_pak_summary参照)——「既定」の語義は
# このモジュール内で既に統一されている。②default_fill()は「どのアバターで
# 埋めるか」という追加入力(entry_id)を要求するため、確認無しの1クリックで
# 完結する動作にはなり得ない。③受入基準dの「リセット後の割当=既定と一致」
# という文言も、store.reset()の言う「既定=空」とそのまま整合する。
#
# 実装: 「リセット」ボタンを押すと、メモリ上のassignmentsを即座に空へ戻す
# (確認ダイアログなし、issue本文「確認ダイアログなしの即時実行(KISS)」)。
# dev#1341の原則どおり、ここでもディスクへの同期書き込みは行わない
# (クローズ時の遅延書き込みに乗る)。空へ戻ると画面は自動的に
# _render_setup()(「設定開始」画面)へ遷移する。
#
# 実tkウィンドウは開かない(既存test群と同じ、conftest.hidden_root=
# withdraw済み1個を使い回す流儀)。confest.py._block_real_dialogsが全テスト
# へ自動適用され、messagebox.*系は「呼ばれたら例外」に差し替わっている
# ——これを逆手に取り、「リセットで例外が飛ばない」こと自体が
# 「確認ダイアログを一切呼んでいない」ことの直接証明になる。
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
import multi_avatar_pak_store as store  # noqa: E402
from ui import multi_avatar_pak_dialog as mapd  # noqa: E402

_ROOT_DIR = os.path.dirname(_APP_PY_DIR)
_PIPELINE_PY_DIR = os.path.join(_ROOT_DIR, "pipeline", "py")
if _PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_PY_DIR)
import vp_avatar_library as val  # noqa: E402
import vp_equipment_avatar as vea  # noqa: E402


def _fake_extract_atlas(pak_path, out_png_path):
    os.makedirs(os.path.dirname(out_png_path), exist_ok=True)
    with open(out_png_path, "wb") as f:
        f.write(b"FAKE_ATLAS")
    return out_png_path


def _make_saved_entry(work_root, entry_id="Alicia"):
    job_dir = os.path.join(work_root, entry_id)
    build_dir = os.path.join(job_dir, "build")
    outfit_dir = os.path.join(build_dir, "noue_work", "variant", "Player", "Outfit")
    base = "SK_Player_Female_Outfit_Cloth001"
    d = os.path.join(outfit_dir, base)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, base + ".uasset"), "wb") as f:
        f.write(b"UA")
    with open(os.path.join(d, base + ".uexp"), "wb") as f:
        f.write(b"UE")
    os.makedirs(build_dir, exist_ok=True)
    out_pak = os.path.join(build_dir, f"{entry_id}_PlayerSwap_P.pak")
    with open(out_pak, "wb") as f:
        f.write(b"PAK")
    job = {"vrm_path": "", "avatar_name": entry_id, "genders": ["Female", "Male"]}
    with mock.patch.object(vea, "extract_avatar_atlas_png", side_effect=_fake_extract_atlas):
        val.save_library(job, job_dir, out_pak, os.path.join(build_dir, "noue_work"))
    return job_dir


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


def _make_ctx(app_root, work_root):
    return mapd.MultiAvatarPakContext(
        app_root=app_root, work_root=work_root, palworld_pak=None, lang="ja",
    )


def _open_main_screen_with_assignment(hidden_root, codes=("Bronze001", "Cloth002")):
    app_root = tempfile.mkdtemp(prefix="d2p_reset_")
    work_root = tempfile.mkdtemp(prefix="d2p_reset_work_")
    _make_saved_entry(work_root, entry_id="Alicia")
    store.save_assignments(app_root, {c: "Alicia" for c in codes})

    fake_catalog = {"ok": True, "source": "test", "detail": "",
                     "codes": list(codes), "names": {}}
    patcher = mock.patch.object(
        mapd.equipment_select_dialog, "query_equipment_catalog", return_value=fake_catalog)
    patcher.start()
    dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, _make_ctx(app_root, work_root))
    return dlg, app_root, work_root, patcher


# ---------------------------------------------------------------------------
# リセットボタンの存在・文言
# ---------------------------------------------------------------------------


def test_reset_button_exists_on_main_screen_with_correct_label(hidden_root):
    dlg, app_root, work_root, patcher = _open_main_screen_with_assignment(hidden_root)
    try:
        btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnReset"))
        assert btn is not None, "リセットボタンが見つからない"
    finally:
        dlg.destroy()
        patcher.stop()


def test_reset_button_label_follows_language_dictionary(hidden_root):
    assert i18n.S("LabMultiAvatarPakBtnReset", "ja") == "リセット"
    assert i18n.S("LabMultiAvatarPakBtnReset", "en") == "Reset"


# ---------------------------------------------------------------------------
# d. リセット後の割当=既定(空)と一致 + 負の対照
# ---------------------------------------------------------------------------


def test_d_reset_clears_assignments_to_default_and_returns_to_setup_screen(hidden_root):
    """リセットを押すと、割当が既定(=空、store.reset()と同じ定義)へ戻り、
    画面は「設定開始」(setup)画面へ遷移する(空の対応表 = setup画面という
    既存のrender()分岐そのものが検出根拠になる)。"""
    dlg, app_root, work_root, patcher = _open_main_screen_with_assignment(hidden_root)
    try:
        # 前提: 現在はメイン画面(作成ボタンがある)。
        assert _find_button(dlg, i18n.S("LabMultiAvatarPakBtnCreate")) is not None

        reset_btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnReset"))
        assert reset_btn is not None
        reset_btn.invoke()  # 確認ダイアログなしの即時実行(KISS)

        # setup画面(「設定開始」ボタン)へ戻ったこと=対応表が既定(空)に
        # なったことの直接証拠(dev#1170のrender()分岐: 空ならsetup、
        # 非空ならmain)。
        assert _find_button(dlg, i18n.S("LabMultiAvatarPakBtnSetup")) is not None
        assert _find_button(dlg, i18n.S("LabMultiAvatarPakBtnCreate")) is None
    finally:
        try:
            dlg.destroy()
        except tk.TclError:
            pass
        patcher.stop()


def test_d_reset_result_matches_store_reset_definition_of_default(hidden_root):
    """「既定」の定義がstore.reset()と一致することを、実際に両方の経路を
    比較して確認する: ダイアログのリセット→クローズで得られる状態と、
    store.reset()を直接呼んだ状態が、同じapp_rootに対して同じ
    load_assignments()結果(空dict)を返す。"""
    dlg, app_root, work_root, patcher = _open_main_screen_with_assignment(hidden_root)
    try:
        reset_btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnReset"))
        assert reset_btn is not None
        reset_btn.invoke()

        # dev#1342: リセット後は_render_setup()(「設定開始」画面)へ
        # 遷移しており、この画面にはCloseボタンが無い(_render_setup()の
        # 既存仕様、dev#1170)。ウィンドウの「X」(WM_DELETE_WINDOW)相当を
        # programmaticに起動して閉じる(ホスト画面への干渉禁止の方針に
        # 沿い、実ウィンドウ操作はしない)。
        close_cmd = dlg.protocol("WM_DELETE_WINDOW")
        assert close_cmd
        dlg.tk.call(close_cmd)

        via_reset_button = store.load_assignments(app_root)
    finally:
        try:
            dlg.destroy()
        except tk.TclError:
            pass
        patcher.stop()

    # 比較対象: 同じ初期状態から store.reset() を直接呼んだ場合。
    app_root2 = tempfile.mkdtemp(prefix="d2p_reset_cmp_")
    store.save_assignments(app_root2, {"Bronze001": "Alicia", "Cloth002": "Alicia"})
    store.reset(app_root2)
    via_store_reset = store.load_assignments(app_root2)

    assert via_reset_button == via_store_reset == {}


def test_negative_control_d_broken_reset_leaves_assignments_unchanged(hidden_root):
    """負の対照(検出力の証明): リセットボタンのcommandを「何もしない」
    壊れた実装に差し替えると、割当が既定(空)に戻らず、上のテストが
    失敗する状況を再現できることを確認する(=正のテストが実際に
    「戻っていない」ケースを検出できることの裏付け)。"""
    dlg, app_root, work_root, patcher = _open_main_screen_with_assignment(hidden_root)
    try:
        reset_btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnReset"))
        assert reset_btn is not None
        # 壊れたcommand(何もしない)へ差し替える。
        reset_btn.config(command=lambda: None)
        reset_btn.invoke()

        # 壊れた実装では画面遷移が起きない(メイン画面のまま)。
        assert _find_button(dlg, i18n.S("LabMultiAvatarPakBtnSetup")) is None, (
            "前提不成立: 壊れたリセットでもsetup画面へ遷移してしまった"
            "(負の対照の模擬方法を見直すこと)"
        )
        assert _find_button(dlg, i18n.S("LabMultiAvatarPakBtnCreate")) is not None
    finally:
        try:
            dlg.destroy()
        except tk.TclError:
            pass
        patcher.stop()


# ---------------------------------------------------------------------------
# dev#1341の原則の継承: リセットも同期ディスクI/O禁止・遅延書き込み
# ---------------------------------------------------------------------------


def test_reset_does_not_write_to_disk_synchronously(hidden_root):
    """リセットボタンを押した直後は、まだディスクへ書き込まれていないこと
    (dev#1341と同じ遅延書き込みの原則)。"""
    dlg, app_root, work_root, patcher = _open_main_screen_with_assignment(hidden_root)
    try:
        before = store.load_assignments(app_root)
        assert before != {}

        reset_btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnReset"))
        assert reset_btn is not None
        reset_btn.invoke()

        after_reset_before_close = store.load_assignments(app_root)
        assert after_reset_before_close == before, (
            "dev#1341原則違反: リセットが即座にディスクへ同期書き込みした"
            "(クローズ時の遅延書き込みになっていない)"
        )
    finally:
        try:
            dlg.destroy()
        except tk.TclError:
            pass
        patcher.stop()


# ---------------------------------------------------------------------------
# 確認ダイアログなしの即時実行(KISS)
# ---------------------------------------------------------------------------


def test_reset_shows_no_confirmation_dialog(hidden_root):
    """リセットは確認ダイアログなしの即時実行であること。conftest.py
    ._block_real_dialogs(autouse)がmessagebox.*系を「呼ばれたら例外」に
    差し替えているため、reset_btn.invoke()が例外を投げずに完了すること
    自体が「確認ダイアログを一切呼んでいない」ことの直接証明になる。"""
    dlg, app_root, work_root, patcher = _open_main_screen_with_assignment(hidden_root)
    try:
        reset_btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnReset"))
        assert reset_btn is not None
        reset_btn.invoke()  # 例外が飛べばテスト自体が失敗する
    finally:
        try:
            dlg.destroy()
        except tk.TclError:
            pass
        patcher.stop()
