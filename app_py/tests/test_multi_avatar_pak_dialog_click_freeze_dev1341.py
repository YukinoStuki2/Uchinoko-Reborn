# test_multi_avatar_pak_dialog_click_freeze_dev1341.py -- dev#1341受入試験。
#
# 症状(2026-08-10深夜、オーナー実機報告、dev#1337(PR #1338)適用後の再試験):
# 「試したけどやっぱりこれだめだわ。まだプチフリーズする。ボタン押したときの
# UXが悪い」。
#
# オーナー原則(受入基準の根、dev#1341本文+深夜の追加裁定):
#   1. クリックの本質は「装備IDとアバターIDをメモリ上の対応表に関連付ける
#      だけ」——本来1msもかからない。
#   2. 「他に必要な処理がある」という反論は却下される。UIスレッドと同期で
#      実行していること自体が欠陥であり、非同期化(遅延書き込み・アイドル時
#      実行)でUI応答から切り離すこと。
#
# 計測(work\wp_1341_1342\NOTES.md、修正前d96e220時点):
#   装備コード150件・ライブラリ8件で30回連続クリックした区間計時の結果、
#   1クリックあたり平均111ms。うちsave_assignments()(ディスク書き込み)は
#   0.5ms(0.5%)に過ぎず、残り99.5%(約110ms)はrender()による
#   ウィジェット全再構築(container.winfo_children()の全destroy+
#   _render_main()の全ボタン再生成)だった。支配項はディスクI/Oではない。
#
# 修正: on_click_equipment()をrender()呼び出しから完全に切り離し、影響する
# 装備ボタン1個だけをconfig()で更新する差分描画にする。永続化(ディスク
# 書き込み)はダイアログクローズ時(WM_DELETE_WINDOW/Closeボタン共通の
# _on_close())へ遅延する。
#
# 受入は3点(いずれも構造の機械判定、ウォールクロック閾値は使わない):
#   a. クリック経路でファイルI/O(open())が一切発生しないこと+負の対照
#   b. クリック経路でウィジェット破棄・再生成が発生しない
#      (_render_main()の呼び出し回数が増えない)こと+負の対照
#   c. クローズ時に初めてディスクへ反映される(遅延書き込み)こと+負の対照
#      (クローズしなければディスクは古いままであることの直接確認)
#
# 実tkウィンドウは開かない(既存test群と同じ、conftest.hidden_root=
# withdraw済み1個を使い回す流儀)。
from __future__ import annotations

import builtins
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


def _setup_main_screen(hidden_root, codes):
    """メイン画面(装備を塗れる状態)まで開いたダイアログを返す。3件の装備・
    2件のライブラリを用意し、装備は最初すべて未設定にする。"""
    app_root = tempfile.mkdtemp(prefix="d2p_freeze_")
    work_root = tempfile.mkdtemp(prefix="d2p_freeze_work_")
    _make_saved_entry(work_root, entry_id="Alicia")
    _make_saved_entry(work_root, entry_id="Bob")
    # メイン画面へ直行させるため、ダミー割当を1件仕込んでおく(dev#1170の
    # 「assignmentsが空ならsetup画面」判定を回避する定石、他テストと同じ)。
    store.save_assignments(app_root, {codes[0]: "Bob"})

    fake_catalog = {"ok": True, "source": "test", "detail": "",
                     "codes": codes, "names": {}}
    patcher = mock.patch.object(
        mapd.equipment_select_dialog, "query_equipment_catalog", return_value=fake_catalog)
    patcher.start()
    dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, _make_ctx(app_root, work_root))
    return dlg, app_root, work_root, patcher


# ---------------------------------------------------------------------------
# a. クリック経路のファイルI/Oゼロ
# ---------------------------------------------------------------------------


def test_a_equipment_click_path_performs_zero_file_io(hidden_root):
    """左ペインの装備クリック(選択済みアバターへ塗る操作)を複数回行っても、
    builtins.open()が一切呼ばれないこと(=いかなる経路のファイルI/Oも
    ゼロ、store層の特定関数だけを見張るより広い検出網)。"""
    codes = ["Bronze001", "Cloth002", "Plastic003"]
    dlg, app_root, work_root, patcher = _setup_main_screen(hidden_root, codes)
    try:
        avatar_btn = _find_button(dlg, "Alicia")
        assert avatar_btn is not None
        avatar_btn.invoke()  # 右ペインの選択操作自体もクリックだが、
        # ディスクへは一切触れない操作(selected_stateのみ更新)なので、
        # 以降のopen()監視の対象区間に含めても問題ない。

        orig_open = builtins.open
        open_calls: list[str] = []

        def spy_open(file, *a, **k):
            path_str = os.fspath(file) if hasattr(file, "__fspath__") else str(file)
            open_calls.append(path_str)
            return orig_open(file, *a, **k)

        with mock.patch.object(builtins, "open", side_effect=spy_open):
            for code in codes:
                eq_btn = _find_button_startswith(dlg, code)
                assert eq_btn is not None, f"equipment button for {code} not found"
                eq_btn.invoke()

        assert open_calls == [], (
            f"dev#1341再発: 装備クリック経路でopen()が{len(open_calls)}回呼ばれた: "
            f"{open_calls}"
        )
    finally:
        try:
            dlg.destroy()
        except tk.TclError:
            pass
        patcher.stop()


def test_negative_control_a_calling_old_assign_many_directly_does_perform_file_io(tmp_path):
    """負の対照(検出力の証明): dev#1341修正前のクリックハンドラが実際に
    呼んでいた_store.assign_many()を直接呼び出すと、open()監視に確実に
    引っかかることを確認する(=上の正のテストが「たまたま何も見ていない」
    のではなく、旧実装なら確実に検出できることの裏付け)。"""
    app_root = str(tmp_path)
    orig_open = builtins.open
    open_calls: list[str] = []

    def spy_open(file, *a, **k):
        path_str = os.fspath(file) if hasattr(file, "__fspath__") else str(file)
        open_calls.append(path_str)
        return orig_open(file, *a, **k)

    with mock.patch.object(builtins, "open", side_effect=spy_open):
        store.assign_many(app_root, "Alicia", ["Bronze001"])

    assert open_calls, (
        "前提不成立: 旧実装相当のassign_many()呼び出しでもopen()が検出されなかった"
        "(負の対照の検出力を見直すこと)"
    )


# ---------------------------------------------------------------------------
# b. クリック経路でウィジェット全再構築が起きないこと
# ---------------------------------------------------------------------------


def test_b_equipment_click_path_does_not_rebuild_widgets(hidden_root):
    """装備クリックのたびに_render_main()(=左右ペインの全ウィジェット
    destroy+再生成)が再度呼ばれないこと。呼び出し回数をスパイで直接数える
    (ウォールクロックではなく構造そのものを見る)。"""
    codes = ["Bronze001", "Cloth002", "Plastic003"]
    app_root = tempfile.mkdtemp(prefix="d2p_freeze_b_")
    work_root = tempfile.mkdtemp(prefix="d2p_freeze_b_work_")
    _make_saved_entry(work_root, entry_id="Alicia")
    store.save_assignments(app_root, {codes[0]: "Alicia"})

    fake_catalog = {"ok": True, "source": "test", "detail": "", "codes": codes, "names": {}}
    orig_render_main = mapd._render_main

    with mock.patch.object(
        mapd.equipment_select_dialog, "query_equipment_catalog", return_value=fake_catalog
    ), mock.patch.object(
        mapd, "_render_main", wraps=orig_render_main
    ) as spy_render_main:
        dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, _make_ctx(app_root, work_root))
        try:
            # dev#1170既知挙動: 開時にi18n.register()が現在言語で1回setterを
            # 自動起動するため、_render_main()は開いた時点で2回(初回描画+
            # 言語登録に伴う再描画)呼ばれる(dev1337テストの同種コメント
            # 参照)。ここでは絶対値を固定せず、この開時分を基準値として
            # 記録し、以降の装備クリックで増えないことだけを見る。
            calls_after_open = spy_render_main.call_count
            assert calls_after_open >= 1

            avatar_btn = _find_button(dlg, "Alicia")
            assert avatar_btn is not None
            avatar_btn.invoke()

            eq_button_identities_before = {
                code: id(_find_button_startswith(dlg, code)) for code in codes
            }

            for code in codes:
                eq_btn = _find_button_startswith(dlg, code)
                assert eq_btn is not None, f"equipment button for {code} not found"
                eq_btn.invoke()

            assert spy_render_main.call_count == calls_after_open, (
                f"dev#1341再発: 装備クリック{len(codes)}回で_render_main()が"
                f"{spy_render_main.call_count - calls_after_open}回追加で呼ばれた"
                "(ウィジェット全再構築が残っている)"
            )

            # 生成されたボタンオブジェクトそのものが同一であること
            # (destroy+再生成なら別オブジェクトになる)。
            for code in codes:
                after_id = id(_find_button_startswith(dlg, code))
                assert after_id == eq_button_identities_before[code], (
                    f"装備{code}のボタンが別オブジェクトに置き換わった"
                    "(destroy+再生成が発生した)"
                )
        finally:
            dlg.destroy()


def test_negative_control_b_render_call_count_detects_rebuild_when_forced(hidden_root):
    """負の対照(検出力の証明): 実際に_render_main()をもう一度呼べば、上の
    テストと同じ計測手法(呼び出し回数のスパイ)がそれを検出できることを
    確認する(=検出網が「何が起きても素通りする」ザルではないことの裏付け)。"""
    codes = ["Bronze001"]
    app_root = tempfile.mkdtemp(prefix="d2p_freeze_b_neg_")
    work_root = tempfile.mkdtemp(prefix="d2p_freeze_b_neg_work_")
    _make_saved_entry(work_root, entry_id="Alicia")
    store.save_assignments(app_root, {codes[0]: "Alicia"})

    fake_catalog = {"ok": True, "source": "test", "detail": "", "codes": codes, "names": {}}
    orig_render_main = mapd._render_main

    with mock.patch.object(
        mapd.equipment_select_dialog, "query_equipment_catalog", return_value=fake_catalog
    ), mock.patch.object(
        mapd, "_render_main", wraps=orig_render_main
    ) as spy_render_main:
        dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, _make_ctx(app_root, work_root))
        try:
            calls_after_open = spy_render_main.call_count
            # 修正前相当の「クリックのたびにrender()を呼ぶ」動きを模擬する。
            # show_multi_avatar_pak_dialog()内部のrender()は直接掴めないため、
            # 代わりに新しいToplevelを同じ経路でもう1個開き直すことで
            # _render_main()の呼び出しを1回強制的に増やす。
            dlg2 = mapd.show_multi_avatar_pak_dialog(hidden_root, _make_ctx(app_root, work_root))
            try:
                assert spy_render_main.call_count != calls_after_open, (
                    "前提不成立: 追加の_render_main()呼び出しが検出されなかった"
                    "(負の対照の検出力を見直すこと)"
                )
            finally:
                dlg2.destroy()
        finally:
            dlg.destroy()


# ---------------------------------------------------------------------------
# c. 永続化はクローズ時の遅延書き込み
# ---------------------------------------------------------------------------


def test_c_assignments_persist_to_disk_only_after_close(hidden_root):
    """装備を塗った直後はディスク未反映、Closeボタン(_on_close()、
    WM_DELETE_WINDOWとも共通経路)を押して初めてディスクへ反映されること。"""
    codes = ["Bronze001", "Cloth002"]
    dlg, app_root, work_root, patcher = _setup_main_screen(hidden_root, codes)
    try:
        avatar_btn = _find_button(dlg, "Alicia")
        assert avatar_btn is not None
        avatar_btn.invoke()

        eq_btn = _find_button_startswith(dlg, "Cloth002")
        assert eq_btn is not None
        eq_btn.invoke()

        # クローズ前: ディスクは古いまま(Bob割当のみ、Cloth002未反映)。
        on_disk_before = store.load_assignments(app_root)
        assert on_disk_before.get("Cloth002") != "Alicia", (
            "前提不成立: クローズ前なのにディスクへ即座に反映されている"
            "(遅延書き込みになっていない)"
        )

        close_btn = _find_button(dlg, i18n.S("BtnClose"))
        assert close_btn is not None
        close_btn.invoke()

        on_disk_after = store.load_assignments(app_root)
        assert on_disk_after.get("Cloth002") == "Alicia", (
            "dev#1341再発: Closeボタンを押してもディスクへ反映されなかった"
        )
    finally:
        try:
            dlg.destroy()
        except tk.TclError:
            pass
        patcher.stop()


def test_c_window_x_protocol_also_flushes(hidden_root):
    """ウィンドウの「X」(WM_DELETE_WINDOWプロトコル)経由でも同じ_on_close()
    が呼ばれ、ディスクへ反映されること(Closeボタンだけの特別扱いでは
    ないことの確認)。programmatic close: WM_DELETE_WINDOWハンドラの
    Tclコマンド名を取得し、tk.call()で直接起動する(実ウィンドウ操作は
    行わない、ホスト画面への干渉禁止の方針に沿う)。"""
    codes = ["Bronze001", "Cloth002"]
    dlg, app_root, work_root, patcher = _setup_main_screen(hidden_root, codes)
    try:
        avatar_btn = _find_button(dlg, "Alicia")
        assert avatar_btn is not None
        avatar_btn.invoke()
        eq_btn = _find_button_startswith(dlg, "Cloth002")
        assert eq_btn is not None
        eq_btn.invoke()

        assert store.load_assignments(app_root).get("Cloth002") != "Alicia"

        close_cmd = dlg.protocol("WM_DELETE_WINDOW")
        assert close_cmd, "WM_DELETE_WINDOWハンドラが登録されていない"
        dlg.tk.call(close_cmd)

        assert store.load_assignments(app_root).get("Cloth002") == "Alicia", (
            "dev#1341再発: WM_DELETE_WINDOW(ウィンドウの閉じるボタン相当)"
            "経由ではディスクへ反映されなかった"
        )
    finally:
        try:
            dlg.destroy()
        except tk.TclError:
            pass
        patcher.stop()


def test_negative_control_c_without_closing_disk_stays_stale(hidden_root):
    """負の対照: ダイアログを閉じずに放置した場合、ディスクは古いまま
    (=書き込みが本当にクローズに紐付いていることの直接確認。仮に実装が
    「クリックのたびに毎回書く」旧実装へ後退していたら、このテストは
    そもそも成立しなくなる=検出力の証明でもある)。"""
    codes = ["Bronze001", "Cloth002"]
    dlg, app_root, work_root, patcher = _setup_main_screen(hidden_root, codes)
    try:
        avatar_btn = _find_button(dlg, "Alicia")
        assert avatar_btn is not None
        avatar_btn.invoke()
        eq_btn = _find_button_startswith(dlg, "Cloth002")
        assert eq_btn is not None
        eq_btn.invoke()

        # 閉じずに放置(ダイアログは開いたまま)。
        on_disk = store.load_assignments(app_root)
        assert on_disk.get("Cloth002") != "Alicia", (
            "前提不成立/dev#1341再発: クローズしていないのにディスクへ"
            "反映されてしまっている"
        )
    finally:
        try:
            dlg.destroy()
        except tk.TclError:
            pass
        patcher.stop()
