# test_multi_avatar_pak_dialog_color_stability_dev1337.py -- dev#1337受入試験。
#
# 症状(2026-08-10 オーナー実機報告、v2.9.0公開直後の実使用): マルチアバター
# PAK作成ダイアログで左ペイン(装備)をクリックするたびに ①ライブラリの色が
# 変わる ②プチフリーズする。
#
# 機序(本ファイルが立証する構造、詳細はC:\P\Work\DiveToPalworld\work\wp_1337
# \NOTES.md): _render_main() は再描画のたびに
# `avatar_color_map(used_entry_ids(assignments))` を計算し直していた。
# used_entry_ids() は sorted(assignments.keys()) の先頭に出てくる装備コード順
# でentry_idを並べる純粋関数のため、どの装備をどのアバターへ塗るかで
# entry_idの出現順(=色の割当順)がシフトし、同じアバターでも塗るたびに
# 色が入れ替わっていた。加えて render() は呼ばれるたびに
# _store.load_assignments() でディスクを再読みしていた(assign_many()が
# 既に保存直後の対応表を返しているのに、それを捨てて読み直す冗長I/O)。
#
# 修正: 色は show_multi_avatar_pak_dialog() 側でダイアログを開いた時点の
# selectable(固定済みライブラリ一覧)から1回だけ計算し、以後は
# _render_main() へパラメータとして渡す。assignmentsもin-memory状態として
# 保持し、assign_many()/default_fill()の戻り値で直接更新することで、
# render()内での再読み込みを撤廃する。
#
# 実tkウィンドウは開かない(既存test_multi_avatar_pak_dialog_ui_dev1170.pyと
# 同じ、conftest.hidden_root=withdraw済み1個を使い回す流儀)。
from __future__ import annotations

import os
import sys
import tempfile
import tkinter as tk
from unittest import mock

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

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


def _make_saved_entry(work_root, entry_id):
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


# ---------------------------------------------------------------------------
# ①正の対照: 左ペイン操作を繰り返しても色割当マッピングが不変
# ---------------------------------------------------------------------------


def test_library_colors_stay_stable_across_equipment_paint_clicks(hidden_root):
    """初期状態でAlicia/Bobの2色が割り当たった状態から、Bobを選んで
    Aliciaが使っていたコードを1件塗り替える。修正前のアルゴリズム
    (avatar_color_map(used_entry_ids(assignments)))だと、この操作で
    「対応表に登場するentry_id集合」からAliciaが一時的に消えるため
    Bobの色がAliciaの色(パレット0番目)へシフトしてしまう
    (下の負の対照テストで再現・立証)。修正後はselectable(開時固定の
    ライブラリ一覧)だけを入力にするため、この操作の前後で両者の色は
    一切変わらない。"""
    app_root = tempfile.mkdtemp(prefix="d2p_map_color_")
    work_root = tempfile.mkdtemp(prefix="d2p_map_color_work_")
    _make_saved_entry(work_root, entry_id="Alicia")
    _make_saved_entry(work_root, entry_id="Bob")
    store.save_assignments(app_root, {"A_code": "Alicia", "Z_code": "Bob"})

    fake_catalog = {"ok": True, "source": "test", "detail": "",
                     "codes": ["A_code", "Z_code"], "names": {}}
    with mock.patch.object(
        mapd.equipment_select_dialog, "query_equipment_catalog", return_value=fake_catalog
    ):
        dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, _make_ctx(app_root, work_root))
        try:
            alicia_btn = _find_button(dlg, "Alicia")
            bob_btn = _find_button(dlg, "Bob")
            assert alicia_btn is not None and bob_btn is not None
            alicia_color_before = alicia_btn.cget("bg")
            bob_color_before = bob_btn.cget("bg")
            assert alicia_color_before != bob_color_before, (
                "前提不成立: AliciaとBobの初期色が別れていない"
            )

            # Bobを選んで、AliciaのA_codeをBobへ塗り替える
            # (対応表からAliciaが一時的に消える操作)
            bob_btn.invoke()
            eq_btn = _find_button_startswith(dlg, "A_code")
            assert eq_btn is not None
            eq_btn.invoke()

            # 続けてもう一度、今度はAliciaへ選び直して別コードを塗る
            # (色が往復して安定しているかも見る)
            alicia_btn_2 = _find_button(dlg, "Alicia")
            assert alicia_btn_2 is not None
            alicia_btn_2.invoke()
            eq_btn2 = _find_button_startswith(dlg, "Z_code")
            assert eq_btn2 is not None
            eq_btn2.invoke()

            alicia_btn_after = _find_button(dlg, "Alicia")
            bob_btn_after = _find_button(dlg, "Bob")
            assert alicia_btn_after is not None and bob_btn_after is not None
            assert alicia_btn_after.cget("bg") == alicia_color_before, (
                "dev#1337再発: 装備を塗るたびにAliciaの色が変わった"
            )
            assert bob_btn_after.cget("bg") == bob_color_before, (
                "dev#1337再発: 装備を塗るたびにBobの色が変わった"
            )
        finally:
            dlg.destroy()


# ---------------------------------------------------------------------------
# ②負の対照: 検出力の証明+「開き直しは再計算されてよい」ことの確認
# ---------------------------------------------------------------------------


def test_negative_control_pre_fix_algorithm_reshuffles_color_on_repaint():
    """修正前のアルゴリズム(avatar_color_map(used_entry_ids(assignments)))を
    純粋関数レベルで直接再現し、上のGUIテストと同じ塗り替え操作
    (Aliciaが使っていたコードをBobへ塗り替える)の前後で、実際に色が
    入れ替わることを示す(=上の正の対照は、この壊れたアルゴリズムに
    差し替えると失敗する、という検出力の証明)。"""
    before = {"A_code": "Alicia", "Z_code": "Bob"}
    after = {"A_code": "Bob", "Z_code": "Bob"}  # BobへA_codeを塗り替えた後

    old_colors_before = store.avatar_color_map(store.used_entry_ids(before))
    old_colors_after = store.avatar_color_map(store.used_entry_ids(after))

    assert old_colors_before.get("Bob") != old_colors_after.get("Bob"), (
        "前提不成立: 修正前アルゴリズムを再現しても色がシフトしなかった"
        "(負の対照の再現条件を見直すこと)"
    )
    assert old_colors_before.get("Alicia") is not None
    # 修正後のafter時点ではAliciaはassignmentsに登場しないため、
    # 旧アルゴリズムだとAliciaの色情報自体が消える(グレー既定色にフォール
    # バックする)。これも「色が消える」というシャッフルの一種。
    assert "Alicia" not in old_colors_after

    # 修正後の実装(selectableの固定列挙順のみに依存)は、同じ塗り替えを
    # 経てもAlicia/Bobの色を保持したまま変えない。
    fixed_colors_before = store.avatar_color_map(["Alicia", "Bob"])
    fixed_colors_after = store.avatar_color_map(["Alicia", "Bob"])
    assert fixed_colors_before == fixed_colors_after


def test_negative_control_reopening_dialog_recomputes_colors(hidden_root):
    """負の対照(裏返し): 「開いた時点で固定」はダイアログの生存期間内だけの
    仮定であり、開き直せば再計算されてよい(オーナー承認済みの仕様)。
    ライブラリの列挙順が変われば、開き直した新しいダイアログでは異なる
    色になり得ることを確認する(=colorsを全実行を通じて完全固定して
    しまう壊れた実装——例えばモジュールグローバルにキャッシュする実装—
    ではないことの検出)。"""
    app_root = tempfile.mkdtemp(prefix="d2p_map_reopen_")
    work_root = tempfile.mkdtemp(prefix="d2p_map_reopen_work_")
    _make_saved_entry(work_root, entry_id="Alicia")
    _make_saved_entry(work_root, entry_id="Bob")
    store.save_assignments(app_root, {"A_code": "Alicia"})

    fake_catalog = {"ok": True, "source": "test", "detail": "",
                     "codes": ["A_code"], "names": {}}
    orig_list_entries = mapd.pak_manager.list_library_entries
    order_state = {"reversed": False}

    def fake_list_entries(work_root_):
        entries = orig_list_entries(work_root_)
        return list(reversed(entries)) if order_state["reversed"] else entries

    with mock.patch.object(
        mapd.equipment_select_dialog, "query_equipment_catalog", return_value=fake_catalog
    ), mock.patch.object(
        mapd.pak_manager, "list_library_entries", side_effect=fake_list_entries
    ):
        dlg1 = mapd.show_multi_avatar_pak_dialog(hidden_root, _make_ctx(app_root, work_root))
        alicia_color_1 = _find_button(dlg1, "Alicia").cget("bg")
        bob_color_1 = _find_button(dlg1, "Bob").cget("bg")
        dlg1.destroy()

        order_state["reversed"] = True
        dlg2 = mapd.show_multi_avatar_pak_dialog(hidden_root, _make_ctx(app_root, work_root))
        alicia_color_2 = _find_button(dlg2, "Alicia").cget("bg")
        bob_color_2 = _find_button(dlg2, "Bob").cget("bg")
        dlg2.destroy()

    assert (alicia_color_1, bob_color_1) != (alicia_color_2, bob_color_2), (
        "開き直してライブラリの列挙順を変えても色配列が全く変わらない"
        "(colorsがダイアログ呼び出しごとに再計算されていない=モジュール"
        "グローバルへの過剰キャッシュ等を疑う)"
    )


# ---------------------------------------------------------------------------
# ③クリックハンドラにライブラリ走査・ファイルI/Oが残っていないこと
# ---------------------------------------------------------------------------


def test_equipment_click_handler_has_no_library_rescan_or_redundant_file_io_dev1337(
    hidden_root,
):
    """左ペインの装備クリックのたびに、ライブラリ一覧
    (pak_manager.list_library_entries)・装備カタログ
    (equipment_select_dialog.query_equipment_catalog)の再取得が起きない
    こと、かつ multi_avatar_pak_store.load_assignments()/save_assignments()
    の呼び出しが**一切**発生しないこと(=ディスクI/Oゼロ)を、呼び出し回数で
    直接検証する。

    dev#1341で基準を再度引き締めた: PR #1338(本テストの初出時点)は
    1クリックあたりload_assignments()が2回(assign_many内+render内の
    冗長読み直し)発生していたのを1回(assign_many内のみ)へ削減したのみで、
    その1回の存在自体(=クリックのたびに同期ディスクI/Oが発生する構造)は
    残っていた(オーナー実機報告「まだプチフリーズする」)。dev#1341では
    クリック経路からassign_many()呼び出し自体を排除し、メモリ上の直接更新
    +クローズ時の遅延書き込みへ変えたため、load/save双方とも装備クリックの
    間は0回であることまで要求する(work\\wp_1341_1342\\NOTES.md計測参照:
    支配項はディスクI/Oではなくウィジェット全再構築だったため、I/O自体は
    元々1クリック1ms未満だったが、「クリック経路にI/Oが同居していること
    自体が設計欠陥」というオーナー原則(dev#1341)によりゼロへ)。"""
    app_root = tempfile.mkdtemp(prefix="d2p_map_io_")
    work_root = tempfile.mkdtemp(prefix="d2p_map_io_work_")
    _make_saved_entry(work_root, entry_id="Alicia")
    store.save_assignments(
        app_root, {"Bronze001": "Alicia", "Cloth002": "Alicia", "Plastic003": "Alicia"})

    fake_catalog = {"ok": True, "source": "test", "detail": "",
                     "codes": ["Bronze001", "Cloth002", "Plastic003"], "names": {}}
    catalog_calls = {"n": 0}
    library_calls = {"n": 0}
    load_calls = {"n": 0}
    save_calls = {"n": 0}

    def counting_catalog(*_a, **_k):
        catalog_calls["n"] += 1
        return fake_catalog

    orig_list_entries = mapd.pak_manager.list_library_entries

    def counting_list_entries(work_root_):
        library_calls["n"] += 1
        return orig_list_entries(work_root_)

    orig_load = store.load_assignments

    def counting_load(app_root_):
        load_calls["n"] += 1
        return orig_load(app_root_)

    orig_save = store.save_assignments

    def counting_save(app_root_, assignments_):
        save_calls["n"] += 1
        return orig_save(app_root_, assignments_)

    with mock.patch.object(
        mapd.equipment_select_dialog, "query_equipment_catalog", side_effect=counting_catalog
    ), mock.patch.object(
        mapd.pak_manager, "list_library_entries", side_effect=counting_list_entries
    ), mock.patch.object(
        mapd._store, "load_assignments", side_effect=counting_load
    ), mock.patch.object(
        mapd._store, "save_assignments", side_effect=counting_save
    ):
        dlg = mapd.show_multi_avatar_pak_dialog(hidden_root, _make_ctx(app_root, work_root))
        try:
            # 装備カタログはダイアログ開時に2回呼ばれる(初回取得+
            # i18n.register()が登録直後に現在言語で1回setterを自動起動する
            # 既存挙動、dev#1170由来・本WPの対象外)。ここではその開時分を
            # 基準値として記録し、以後の左ペインクリックで増えないことだけを
            # 検証する。ライブラリ一覧はそのような追加起動フックが無いため
            # 開時ちょうど1回。
            calls_after_open_catalog = catalog_calls["n"]
            assert calls_after_open_catalog >= 1
            assert library_calls["n"] == 1
            calls_after_open_load = load_calls["n"]
            calls_after_open_save = save_calls["n"]

            avatar_btn = _find_button(dlg, "Alicia")
            assert avatar_btn is not None
            avatar_btn.invoke()

            codes = ["Bronze001", "Cloth002", "Plastic003"]
            for code in codes:
                eq_btn = _find_button_startswith(dlg, code)
                assert eq_btn is not None, f"equipment button for {code} not found"
                eq_btn.invoke()
                # クリックのたびにライブラリ走査が一切増えないこと
                assert catalog_calls["n"] == calls_after_open_catalog, (
                    f"装備{code}のクリックで装備カタログが再取得された"
                )
                assert library_calls["n"] == 1, (
                    f"装備{code}のクリックでライブラリ一覧が再走査された"
                )

            # dev#1341: 装備クリック経路ではload_assignments()/
            # save_assignments()とも一切呼ばれないこと(=ファイルI/Oゼロ)。
            assert load_calls["n"] == calls_after_open_load, (
                f"装備クリック{len(codes)}回でload_assignments()が"
                f"{load_calls['n'] - calls_after_open_load}回呼ばれた"
                "(dev#1341再発: クリック経路にディスク読み込みが残っている)"
            )
            assert save_calls["n"] == calls_after_open_save, (
                f"装備クリック{len(codes)}回でsave_assignments()が"
                f"{save_calls['n'] - calls_after_open_save}回呼ばれた"
                "(dev#1341再発: クリック経路にディスク書き込みが残っている)"
            )
        finally:
            dlg.destroy()
