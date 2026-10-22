# test_multi_avatar_pak_dialog_ui_dev1170.py -- dev#1170 WP-3(マルチアバターPAK
# 作成)ダイアログのウィジェット層の最小スモーク試験。
#
# ラボ憲章②「GUI実起動を伴う重い試験は課さない」(指示書の明示要求)に沿い、
# ここでは「例外なく組み立てられること」+「必須要素が存在すること」だけを
# 軽く確認する(equipment_select_dialog.py/mesh_delete_dialog.py等の既存
# ダイアログのような網羅的ウィジェット試験は行わない)。実tkウィンドウは
# 表示しない(conftest.pyの共有hidden_root、withdraw済み)。
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


def test_setup_screen_shows_start_button_when_library_has_entries(hidden_root):
    app_root = tempfile.mkdtemp(prefix="d2p_map_test_")
    work_root = tempfile.mkdtemp(prefix="d2p_map_test_work_")
    _make_saved_entry(work_root, entry_id="Alicia")

    dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, _make_ctx(app_root, work_root))
    try:
        btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnSetup"))
        assert btn is not None
    finally:
        dlg.destroy()


def test_setup_screen_shows_empty_notice_when_library_has_no_entries(hidden_root):
    app_root = tempfile.mkdtemp(prefix="d2p_map_test_")
    work_root = tempfile.mkdtemp(prefix="d2p_map_test_work_")  # 空のまま

    dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, _make_ctx(app_root, work_root))
    try:
        # 「設定開始」ボタン自体が出ない(選べるエントリが無いため)
        btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnSetup"))
        assert btn is None
        labels = [w.cget("text") for w in _find_children(dlg, tk.Label)]
        assert i18n.S("LabMultiAvatarPakSetupNoEntries") in labels
    finally:
        dlg.destroy()


def test_main_screen_shown_when_assignments_already_present(hidden_root):
    app_root = tempfile.mkdtemp(prefix="d2p_map_test_")
    work_root = tempfile.mkdtemp(prefix="d2p_map_test_work_")
    _make_saved_entry(work_root, entry_id="Alicia")
    store.save_assignments(app_root, {"Bronze001": "Alicia"})

    dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, _make_ctx(app_root, work_root))
    try:
        # 設定開始ボタンではなく、作成ボタンが出ること(メイン画面へ直行)
        assert _find_button(dlg, i18n.S("LabMultiAvatarPakBtnSetup")) is None
        assert _find_button(dlg, i18n.S("LabMultiAvatarPakBtnCreate")) is not None
        assert _find_button(dlg, i18n.S("BtnClose")) is not None
    finally:
        dlg.destroy()


def test_picking_avatar_in_setup_default_fills_and_switches_to_main_screen(hidden_root):
    app_root = tempfile.mkdtemp(prefix="d2p_map_test_")
    work_root = tempfile.mkdtemp(prefix="d2p_map_test_work_")
    _make_saved_entry(work_root, entry_id="Alicia")

    # ctx.palworld_pak=None(このテストではPalworld実体を用意しない)だと
    # 装備カタログが空になり、default_fill()が「割り当てる装備が無い」ため
    # 対応表が空のままになってしまう(setup画面のまま循環する、既知の
    # フォールバック挙動——equipment_select_dialog.pyの「カタログ0件」と
    # 同じ土俵)。ここでは「選んだら割り当てられる」こと自体を検証したいため、
    # カタログ取得だけ固定値へ差し替える。
    fake_catalog = {"ok": True, "source": "test", "detail": "",
                     "codes": ["Bronze001", "Cloth002"], "names": {}}
    with mock.patch.object(
        mapd.equipment_select_dialog, "query_equipment_catalog", return_value=fake_catalog
    ):
        dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, _make_ctx(app_root, work_root))
        try:
            setup_btn = _find_button(dlg, i18n.S("LabMultiAvatarPakBtnSetup"))
            assert setup_btn is not None
            setup_btn.invoke()  # 「設定開始」→ アバター選択リストが出る

            pick_btn = _find_button(dlg, "Alicia")
            assert pick_btn is not None
            pick_btn.invoke()  # アバターを選ぶ → default_fill相当 → メイン画面へ

            # dev#1341: ここではまだメモリ上のみ(遅延書き込み)。ディスクは
            # まだ古いまま(=未設定)であることを先に確認しておく
            # (「即座に書いていない」ことの直接検証)。
            assert store.is_active(app_root) is False
            assert _find_button(dlg, i18n.S("LabMultiAvatarPakBtnCreate")) is not None

            # dev#1341: ダイアログを閉じて初めてディスクへ反映される
            # (WM_DELETE_WINDOW/Closeボタン共通の_on_close()経由)。
            # dlg.destroy()を直接呼ぶだけではWM_DELETE_WINDOWハンドラは
            # 発火しない(Pythonの.destroy()呼び出しとウィンドウマネージャ
            # からの閉じるイベントは別経路)ため、実際に画面へ出ている
            # 「Close」ボタンをクリックして検証する(ユーザー操作の実態と
            # 一致させる)。
            close_btn = _find_button(dlg, i18n.S("BtnClose"))
            assert close_btn is not None
            close_btn.invoke()
            assert store.is_active(app_root) is True
            assert store.load_assignments(app_root) == {
                "Bronze001": "Alicia", "Cloth002": "Alicia",
            }
        finally:
            try:
                dlg.destroy()
            except tk.TclError:
                pass


# ---------------------------------------------------------------------------
# dev#1170 バグ修正(2026-08-09 オーナー実機確認3件)
# ---------------------------------------------------------------------------


def test_equipment_names_follow_language_switch_dev1170(hidden_root, monkeypatch):
    """バグ修正1: 「Multi-Avatar PAKの装備名がLanguage Englishにしても日本語の
    まま」。equipment_select_dialog.py
    .test_checkbox_names_follow_language_switch_dev165_datatable と同じ観測
    パターン(query_equipment_catalog()をlang引数ごとに違う名前を返すfakeへ
    差し替え、i18n.apply_language()前後で表示名が切り替わることを確認)。
    修正前はダイアログを開いた瞬間のctx.langで一度だけdisplayを組み立てて
    おり、この検証は失敗する(検出力の証明)。"""
    app_root = tempfile.mkdtemp(prefix="d2p_map_test_")
    work_root = tempfile.mkdtemp(prefix="d2p_map_test_work_")
    store.save_assignments(app_root, {"Bronze001": "Alicia"})

    def _fake_by_lang(_app_root, _pak, lang, **_k):
        names_by_lang = {
            "ja": {"Bronze001": "銅の鎧"},
            "en": {"Bronze001": "Bronze Armor"},
        }
        return {"ok": True, "source": "test", "detail": "",
                "codes": ["Bronze001"], "names": names_by_lang.get(lang, {})}

    monkeypatch.setattr(mapd.equipment_select_dialog, "query_equipment_catalog", _fake_by_lang)
    orig_lang = i18n.current_lang
    i18n.set_language("ja")
    try:
        ctx = mapd.MultiAvatarPakContext(
            app_root=app_root, work_root=work_root, palworld_pak="C:\\fake.pak", lang="ja")
        dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, ctx)
        try:
            assert _find_button(dlg, "銅の鎧 -> Alicia") is not None

            i18n.apply_language("en")
            try:
                assert _find_button(dlg, "Bronze Armor -> Alicia") is not None
                assert _find_button(dlg, "銅の鎧 -> Alicia") is None
            finally:
                i18n.apply_language("ja")
        finally:
            dlg.destroy()
    finally:
        i18n.set_language(orig_lang)


def test_paint_selection_persists_across_multiple_equipment_clicks(hidden_root):
    """バグ修正3: 「1回クリックしてから複数のEquipmentを連続してクリックして
    適応できること」「1回やるごとにクリアされちゃう」。右ペインでアバターを
    1回選択したあと、左ペインの装備を連続して3件クリックし、全部同じ
    アバターへ塗られること(オーナー確定仕様④「ペンキ方式:...連続して複数
    可能」の直接検証)。事前の割当はダミーID("X")にしておき、クリック後に
    3件とも実際に選んだアバターへ書き換わっていることで「選択が生きたまま
    複数回効いた」ことを検出する(1クリック目しか効かない壊れた実装だと、
    2件目・3件目は"X"のまま残り、この検証は失敗する)。"""
    app_root = tempfile.mkdtemp(prefix="d2p_map_test_")
    work_root = tempfile.mkdtemp(prefix="d2p_map_test_work_")
    _make_saved_entry(work_root, entry_id="Alicia")
    store.save_assignments(
        app_root, {"Bronze001": "X", "Cloth002": "X", "Plastic003": "X"})

    fake_catalog = {"ok": True, "source": "test", "detail": "",
                     "codes": ["Bronze001", "Cloth002", "Plastic003"], "names": {}}
    with mock.patch.object(
        mapd.equipment_select_dialog, "query_equipment_catalog", return_value=fake_catalog
    ):
        dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, _make_ctx(app_root, work_root))
        try:
            avatar_btn = _find_button(dlg, "Alicia")
            assert avatar_btn is not None
            avatar_btn.invoke()  # 右ペインで1回選択

            for code in ["Bronze001", "Cloth002", "Plastic003"]:
                # dev#1341: クリックのたびに全ウィジェットが作り直される
                # 挙動は撤廃した(差分描画)。同じボタン参照を使い回せるが、
                # 念のため既存の探索方式のまま(dlgから再取得)にしておく
                # ——これは同一オブジェクトが見つかることの確認にもなる。
                eq_btn = _find_button_startswith(dlg, code)
                assert eq_btn is not None, f"equipment button for {code} not found"
                eq_btn.invoke()
                # dev#1341: クリック直後、メモリ上(=ボタンのラベル)には
                # 即座に反映される(ディスクはまだ未反映)。
                assert eq_btn.cget("text").endswith("-> Alicia")

            # 最後のクリック後も右ペインのアバター選択(sunken表示)が
            # 維持されていること(=次にまた装備を塗り続けられる状態)。
            avatar_btn_after = _find_button(dlg, "Alicia")
            assert avatar_btn_after is not None
            assert avatar_btn_after.cget("relief") == "sunken"

            # dev#1341: ディスクへの反映はクローズ時(Closeボタン経由の
            # _on_close())。
            close_btn = _find_button(dlg, i18n.S("BtnClose"))
            assert close_btn is not None
            close_btn.invoke()
            assert store.load_assignments(app_root) == {
                "Bronze001": "Alicia", "Cloth002": "Alicia", "Plastic003": "Alicia",
            }
        finally:
            try:
                dlg.destroy()
            except tk.TclError:
                pass


def test_negative_control_reselecting_avatar_between_each_click_still_works(hidden_root):
    """負の対照の補強: 「毎回選び直せば塗れる」旧来の使い方(1クリックごとに
    右ペインを選び直す)は修正後も引き続き動くことを確認する(連続塗りの
    追加が、単発の選び直しフローを壊していないことの回帰確認)。"""
    app_root = tempfile.mkdtemp(prefix="d2p_map_test_")
    work_root = tempfile.mkdtemp(prefix="d2p_map_test_work_")
    _make_saved_entry(work_root, entry_id="Alicia")
    store.save_assignments(app_root, {"Bronze001": "X", "Cloth002": "X"})

    fake_catalog = {"ok": True, "source": "test", "detail": "",
                     "codes": ["Bronze001", "Cloth002"], "names": {}}
    with mock.patch.object(
        mapd.equipment_select_dialog, "query_equipment_catalog", return_value=fake_catalog
    ):
        dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, _make_ctx(app_root, work_root))
        try:
            for code in ["Bronze001", "Cloth002"]:
                avatar_btn = _find_button(dlg, "Alicia")
                assert avatar_btn is not None
                avatar_btn.invoke()
                eq_btn = _find_button_startswith(dlg, code)
                assert eq_btn is not None
                eq_btn.invoke()

            # dev#1341: ディスクへの反映はクローズ時(Closeボタン経由の
            # _on_close())。
            close_btn = _find_button(dlg, i18n.S("BtnClose"))
            assert close_btn is not None
            close_btn.invoke()
            assert store.load_assignments(app_root) == {
                "Bronze001": "Alicia", "Cloth002": "Alicia",
            }
        finally:
            try:
                dlg.destroy()
            except tk.TclError:
                pass
