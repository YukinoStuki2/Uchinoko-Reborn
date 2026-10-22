# test_multi_avatar_pak_dialog_notify_survives_language_change_dev1320.py --
# dev#1320受入試験。
#
# 症状(2026-08-10 オーナー実機報告): マルチアバターPAK合成の実行中に
# GUIのlanguage設定を変更すると、バックエンドは完走するのに完了msgboxが
# 表示されない。
#
# 機序(本ファイルが立証する構造): multi_avatar_pak_dialog.py
# show_multi_avatar_pak_dialog()は i18n.register(dlg, "LabFeatureMultiAvatarPak",
# _refresh_catalog_on_language_change) を登録しており、言語切替のたびに
# render()が呼ばれてcontainer配下(status_var/create_btn含む)を全部
# destroy()して作り直す。一方 _on_create() の worker() は render()時点の
# status_var/create_btnをクロージャで直接キャプチャしており、
# dlg.after(0, on_ok)(またはon_fail/on_unavailable)がそのdestroy済み
# ウィジェットへ触れるとTclErrorが起き、その行より後にある
# messagebox.showinfo/showerrorまで到達しない(tkinterのafterコールバック内
# 未捕捉例外は握りつぶされるだけでアプリはクラッシュしない=「通知だけが
# 静かに消える」)。
#
# 修正: _on_create()内の状態復帰処理(status_var.set/create_btn.config)を
# 個別にtry/except tk.TclErrorで保護し、messagebox表示はそれらの成否に
# 依存させない(multi_avatar_pak_dialog.py _safe_reset_controls()参照)。
#
# 試験方式(同期スレッド代替): worker()は本来threading.Thread(daemon=True)で
# 別スレッド実行されるが、Python 3.13のtkinterはmainloop()が回っていない
# 状態で非メインスレッドからdlg.after()を呼ぶと
# 「RuntimeError: main thread is not in main loop」を投げる(pytestは
# mainloop()を回さない)。これは試験ハーネスの制約であり dev#1320 の症状
# ではないため、mapd.threading.Threadを「同一(メイン)スレッドで同期的に
# target()を呼ぶだけの代替」に差し替える。これにより、言語切替
# (i18n.apply_language)をrun_compose呼び出しの内側(=worker()実行中)で
# 同期的に起こすことができ、実スレッドを使わずに同じ競合構造
# (render()時点のウィジェット参照が、その後の同一worker()内のdlg.after()
# コールバックから参照される)を再現できる。
#
# 実tkウィンドウは開かない(既存test_multi_avatar_pak_dialog_ui_dev1170.pyと
# 同じ、conftest.hidden_root=withdraw済み1個を使い回す流儀)。
from __future__ import annotations

import os
import sys
import tempfile
import time
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

_PUMP_TIMEOUT_S = 5.0
_PUMP_INTERVAL_S = 0.02


class _SyncThread:
    """threading.Threadの代替: start()を呼んだその場(呼び出し元と同じ
    メインスレッド)でtarget()を同期実行する。dlg.after()の登録がTkを
    作ったスレッドと一致するため、mainloop()無しのpytest環境でも
    RuntimeError('main thread is not in main loop')を踏まない。"""

    def __init__(self, target=None, daemon=None, **_kw) -> None:
        self._target = target

    def start(self) -> None:
        if self._target is not None:
            self._target()


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


def _make_ctx(app_root, work_root):
    # dev#1328統合: on_ok()がここのapply_pak_pathを呼んで自動適用を試みる
    # ようになった(_apply_after_compose)。未配線(None)のままだと「適用失敗」
    # 扱いでshowwarning経路に落ち、本ファイルが検証したいdev#1320の
    # 「通知到達」自体は成立するがmessagebox種別が変わってしまう。ここでは
    # 常に成功する薄いフェイクを注入し、dev#1320本来の対象(on_ok内のTclError
    # 保護後にmessagebox.showinfoまで届くか)をそのまま検証できるようにする。
    return mapd.MultiAvatarPakContext(
        app_root=app_root, work_root=work_root, palworld_pak=None, lang="ja",
        apply_pak_path=lambda pak_path, avatar_name: True,
    )


def _pump_until(dlg, predicate, timeout_s=_PUMP_TIMEOUT_S):
    """dlg.after(0, ...)で積まれたコールバックが処理されるまで、明示的に
    Tkのイベントキューをポンプする(mainloop()は回していないため)。
    条件を満たすかタイムアウトまで、短い間隔でupdate()を呼び続ける。"""
    deadline = time.time() + timeout_s
    while not predicate() and time.time() < deadline:
        dlg.update()
        time.sleep(_PUMP_INTERVAL_S)
    return predicate()


def _open_main_screen(hidden_root, app_root, work_root, monkeypatch):
    _make_saved_entry(work_root, entry_id="Alicia")
    store.save_assignments(app_root, {"Bronze001": "Alicia"})
    fake_catalog = {"ok": True, "source": "test", "detail": "",
                     "codes": ["Bronze001"], "names": {"Bronze001": "Bronze Armor"}}
    monkeypatch.setattr(
        mapd.equipment_select_dialog, "query_equipment_catalog",
        lambda *a, **k: fake_catalog)
    dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, _make_ctx(app_root, work_root))
    return dlg


def test_compose_success_notice_survives_language_change_during_compose_dev1320(
    hidden_root, monkeypatch
):
    """本丸: 合成の実行中に言語変更が起きても、完了msgboxが必ず表示される。"""
    app_root = tempfile.mkdtemp(prefix="d2p_map_notify_")
    work_root = tempfile.mkdtemp(prefix="d2p_map_notify_work_")
    orig_lang = i18n.current_lang
    i18n.set_language("ja")
    monkeypatch.setattr(mapd.threading, "Thread", _SyncThread)
    try:
        dlg = _open_main_screen(hidden_root, app_root, work_root, monkeypatch)
        try:
            monkeypatch.setattr(mapd.simpledialog, "askstring", lambda *a, **k: "FusionA")

            def fake_run_compose(work_root_, job, log=None, python_exe=None):
                # 合成「実行中」に言語変更が起きる(オーナー実機報告の再現)。
                # apply_language()は登録済みコールバック
                # (_refresh_catalog_on_language_change)経由でrender()を呼び、
                # containerの子(status_var/create_btnを含む)を全部作り直す。
                # ここでcreate_btn/status_var(worker()がクロージャで
                # キャプチャした変数)は既にdestroy済みになる。
                i18n.apply_language("en")
                i18n.apply_language("ja")
                # dev#1328統合: on_ok()がcompose_result["pak_path"]を自動適用
                # (_apply_after_compose)へ渡すようになったため、成功系フェイクは
                # pak_pathを含む戻り値を返す(空だと「未生成」扱いで適用がスキップ
                # されshowwarning経路に落ちてしまう)。
                return {"pak_path": os.path.join(work_root_, "FusionA_PlayerSwap_P.pak")}

            monkeypatch.setattr(mapd.multi_avatar_pak_compose, "run_compose", fake_run_compose)

            shown: list[tuple[str, str]] = []
            monkeypatch.setattr(
                mapd.messagebox, "showinfo",
                lambda title, msg: shown.append((title, msg)))

            create_btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnCreate"))
            assert create_btn is not None
            create_btn.invoke()  # _SyncThread経由でworker()が同期的に完走する

            assert _pump_until(dlg, lambda: len(shown) > 0), (
                "dev#1320再発: 合成実行中の言語変更後、完了msgboxが表示されなかった"
            )
            # dev#1328統合: 成功文言は「作成+適用」の統合済みメッセージへ変更
            # (_make_ctxがapply_pak_path=常に成功のフェイクを注入しているため)。
            assert shown[0][1] == i18n.S("LabMultiAvatarPakCreateAndApplySuccess")
        finally:
            dlg.destroy()
    finally:
        i18n.set_language(orig_lang)


def test_compose_failure_notice_survives_language_change_during_compose_dev1320(
    hidden_root, monkeypatch
):
    """失敗系(on_fail経路)も同様に通知が生き残ること。"""
    app_root = tempfile.mkdtemp(prefix="d2p_map_notify_fail_")
    work_root = tempfile.mkdtemp(prefix="d2p_map_notify_fail_work_")
    orig_lang = i18n.current_lang
    i18n.set_language("ja")
    monkeypatch.setattr(mapd.threading, "Thread", _SyncThread)
    try:
        dlg = _open_main_screen(hidden_root, app_root, work_root, monkeypatch)
        try:
            monkeypatch.setattr(mapd.simpledialog, "askstring", lambda *a, **k: "FusionB")

            def fake_run_compose(work_root_, job, log=None, python_exe=None):
                i18n.apply_language("en")
                i18n.apply_language("ja")
                raise RuntimeError("boom-dev1320")

            monkeypatch.setattr(mapd.multi_avatar_pak_compose, "run_compose", fake_run_compose)

            shown_errors: list[tuple[str, str]] = []
            monkeypatch.setattr(
                mapd.messagebox, "showerror",
                lambda title, msg: shown_errors.append((title, msg)))

            create_btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnCreate"))
            assert create_btn is not None
            create_btn.invoke()

            assert _pump_until(dlg, lambda: len(shown_errors) > 0), (
                "dev#1320再発: 合成失敗時も、言語変更後は失敗通知が表示されなかった"
            )
        finally:
            dlg.destroy()
    finally:
        i18n.set_language(orig_lang)


def test_negative_control_success_notice_shown_without_language_change_dev1320(
    hidden_root, monkeypatch
):
    """負の対照: 言語変更を挟まない通常経路では、修正前後を問わず完了msgboxが
    表示されること(このアサーションが崩れていたら、上のレース自体を正しく
    検出できていない=試験ハーネスの前提が壊れている)。"""
    app_root = tempfile.mkdtemp(prefix="d2p_map_notify_ctrl_")
    work_root = tempfile.mkdtemp(prefix="d2p_map_notify_ctrl_work_")
    orig_lang = i18n.current_lang
    i18n.set_language("ja")
    monkeypatch.setattr(mapd.threading, "Thread", _SyncThread)
    try:
        dlg = _open_main_screen(hidden_root, app_root, work_root, monkeypatch)
        try:
            monkeypatch.setattr(mapd.simpledialog, "askstring", lambda *a, **k: "FusionC")
            # dev#1328統合: on_ok()がcompose_result["pak_path"]を自動適用
            # (_apply_after_compose)へ渡すようになったため、pak_pathを含む
            # 戻り値を返す(空だと適用スキップでshowwarning経路に落ちる)。
            monkeypatch.setattr(
                mapd.multi_avatar_pak_compose, "run_compose",
                lambda work_root_, job, log=None, python_exe=None: {
                    "pak_path": os.path.join(work_root_, "FusionC_PlayerSwap_P.pak")})

            shown: list[tuple[str, str]] = []
            monkeypatch.setattr(
                mapd.messagebox, "showinfo",
                lambda title, msg: shown.append((title, msg)))

            create_btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnCreate"))
            assert create_btn is not None
            create_btn.invoke()

            assert _pump_until(dlg, lambda: len(shown) > 0), (
                "言語変更を挟まない通常経路でも完了msgboxが表示されない"
                "(試験ハーネス自体の前提が崩れている)"
            )
            # dev#1328統合: 成功文言は「作成+適用」の統合済みメッセージへ変更
            # (_make_ctxがapply_pak_path=常に成功のフェイクを注入しているため)。
            assert shown[0][1] == i18n.S("LabMultiAvatarPakCreateAndApplySuccess")
        finally:
            dlg.destroy()
    finally:
        i18n.set_language(orig_lang)
