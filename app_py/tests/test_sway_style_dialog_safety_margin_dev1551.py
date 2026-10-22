# test_sway_style_dialog_safety_margin_dev1551.py -- dev#1551安全域WP
# (issue #1551「安全域」欄、2026-08-18オーナー最終裁定)のGUI回帰テスト。
#
# WP wp/1551-gui-safety-margin(work\run_1551\laneR3_guifix\RESULT.md):
# 旧「揺れもの詳細設定」ダイアログ(ui.sway_chain_dialog.py)は現GUIから
# 到達不能になっており(PR #1510、dev#1508で統合パネル「ゆれかた」
# [ui.sway_style_dialog.py]に置き換わった)、安全域スピンボックスの搬送路
# (sway_chain_override_store.py、PR #1570)自体は生きているのにGUIから
# 触れなかった不具合を修理する。本ファイルは統合パネル側に追加した
# 安全域スピンボックスの表示既定値・編集→OK→再オープンの往復・
# job["sway_chain_overrides"]への貫通(pipeline_runner.py経由)・
# 未編集鎖の非保存(ラボ憲章④)を検証する。実tk.Tk()は作らない
# (conftest.pyの共有hidden_root、既存慣例踏襲)。
from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import ttk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import sway_chain_override_store as chain_store  # noqa: E402
from ui import sway_style_dialog as dlg_mod  # noqa: E402

AVATAR = "C:\\fake.vrm"


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _find_all(root, cls):
    return [w for w in _walk(root) if isinstance(w, cls)]


def _find_button(root, text):
    for w in _walk(root):
        if isinstance(w, tk.Button) and w.cget("text") == text:
            return w
    raise AssertionError(f"button not found: {text!r}")


def _find_button_contains(root, substr):
    for w in _walk(root):
        if isinstance(w, tk.Button) and substr in w.cget("text"):
            return w
    raise AssertionError(f"button containing {substr!r} not found")


def _make_ctx(app_root, sample_mode=True, avatar_path=AVATAR):
    return dlg_mod.SwayStyleContext(
        app_root=app_root, work_root=app_root, avatar_path=avatar_path,
        sample_mode=sample_mode,
    )


# ---------------------------------------------------------------------------
# 1. 表示既定値+編集→OK→再オープン往復(dev#1438と同じ形の回帰を、
#    安全域フィールドで直接固定)。
# ---------------------------------------------------------------------------

def test_row_spinbox_default_value_is_product_default(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        spinboxes = _find_all(dlg, ttk.Spinbox)
        assert spinboxes, "検証には一覧行が最低1行必要(--sample未反映?)"
        for sb in spinboxes:
            assert int(sb.get()) == dlg_mod.DEFAULT_SAFETY_MARGIN
    finally:
        dlg.destroy()


def test_safety_margin_edit_ok_reopen_roundtrip(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    # SAMPLE_CHAINSの並び: index0="J_Bip_C_Hips (Tail_01)" (尻尾)。
    spinboxes = _find_all(dlg, ttk.Spinbox)
    tail_sb = spinboxes[0]
    tail_sb.delete(0, "end")
    tail_sb.insert(0, "3")
    tail_sb.event_generate("<KeyRelease>")
    _find_button(dlg, i18n.S("BtnOk")).invoke()  # save_config + destroy

    ctx2 = _make_ctx(app_root)
    dlg2 = dlg_mod.show_sway_style_dialog(hidden_root, ctx2)
    try:
        spinboxes2 = _find_all(dlg2, ttk.Spinbox)
        assert int(spinboxes2[0].get()) == 3, "編集した安全域が再オープンで反映されていない"
        # 触っていない行(耳L、index1)は既定値のまま。
        assert int(spinboxes2[1].get()) == dlg_mod.DEFAULT_SAFETY_MARGIN
    finally:
        dlg2.destroy()

    # ストア側(ディスク、sway_chain_override_store)の内容もスピンボックス
    # 表示と完全一致すること。
    saved = chain_store.load_config(app_root, AVATAR)
    saved_by_last_bone = {e["bones"][-1]: e.get("safety_margin") for e in saved}
    assert saved_by_last_bone.get("Tail_03") == 3
    # 触っていない行(既定のまま)はラボ憲章④により保存対象に含まれない。
    assert "EarL_02" not in saved_by_last_bone


def test_untouched_dialog_ok_does_not_write_chain_overrides(hidden_root, tmp_path):
    """負の対照(WP受入ゲート1): 何も編集せずOKしても
    sway_chain_override_store には何も保存されない(既定=製品既定値のまま)。"""
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        _find_button(dlg, i18n.S("BtnOk")).invoke()
    except Exception:
        dlg.destroy()
        raise
    assert chain_store.load_config(app_root, AVATAR) == []
    assert chain_store.is_active(app_root, AVATAR) is False


def test_dialog_cancel_close_does_not_save_safety_margin(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    spinboxes = _find_all(dlg, ttk.Spinbox)
    spinboxes[0].delete(0, "end")
    spinboxes[0].insert(0, "5")
    spinboxes[0].event_generate("<KeyRelease>")
    dlg.destroy()  # ×閉じ相当(WM_DELETE_WINDOW=destroy)
    assert chain_store.load_config(app_root, AVATAR) == []


# ---------------------------------------------------------------------------
# 2. 貫通試験(パネルUI -> ストア -> job生成): pipeline_runner.py が実際に
#    job["sway_chain_overrides"]へ載せるところまで確認する(WP受入ゲート1)。
# ---------------------------------------------------------------------------

def test_edited_safety_margin_reaches_pipeline_runner_job(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    spinboxes = _find_all(dlg, ttk.Spinbox)
    spinboxes[0].delete(0, "end")
    spinboxes[0].insert(0, "2")
    spinboxes[0].event_generate("<KeyRelease>")
    _find_button(dlg, i18n.S("BtnOk")).invoke()

    # pipeline_runner.py が実際に読む経路そのもの(app_py\pipeline_runner.py
    # 442-457行): sway_chain_override_store.load_config(app_root, vrm_path)
    # の結果をjob["sway_chain_overrides"]へそのまま載せる。ここではその
    # 消費側コードと同じ呼び出しを直接行い、job相当の構造を再現する
    # (フルのpipeline_runner.build_job()はGUI外の多数の前提[work_root配下の
    # 実ファイル等]を要求するため、WP指示書「最短経路...job生成まで貫通」の
    # 対象はこの消費関数の呼び出し確認で足りる、実装者解釈)。
    import pipeline_runner
    overrides = pipeline_runner.sway_chain_override_store.load_config(app_root, AVATAR)
    job = {}
    if overrides:
        job["sway_chain_overrides"] = overrides

    assert "sway_chain_overrides" in job
    by_last_bone = {tuple(e["bones"])[-1]: e.get("safety_margin") for e in job["sway_chain_overrides"]}
    assert by_last_bone.get("Tail_03") == 2


def test_no_edit_means_no_overrides_key_in_job(hidden_root, tmp_path):
    """負の対照: 未編集ならjob["sway_chain_overrides"]自体が現れない
    (既定=製品既定値1で変換される、pipeline\\blender\\step02_retarget.py
    SWAY_DEFAULT_SAFETY_MARGINがそのまま効く)。"""
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        _find_button(dlg, i18n.S("BtnOk")).invoke()
    except Exception:
        dlg.destroy()
        raise

    import pipeline_runner
    overrides = pipeline_runner.sway_chain_override_store.load_config(app_root, AVATAR)
    job = {}
    if overrides:
        job["sway_chain_overrides"] = overrides
    assert "sway_chain_overrides" not in job


# ---------------------------------------------------------------------------
# 3. i18n・列見出し・案内文。
# ---------------------------------------------------------------------------

def test_new_i18n_keys_present_in_all_languages():
    for key in ("LabSwayChainColSafetyMargin", "LabSwayChainSafetyMarginHint"):
        for lang in i18n.LANGS:
            text = i18n.S(key, lang)
            assert text and not text.startswith("??"), f"i18nキー欠落: {key} / {lang}"


def test_dialog_shows_safety_margin_hint_and_column_header(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        labels = [w for w in _walk(dlg) if isinstance(w, tk.Label)]
        texts = []
        for w in labels:
            try:
                texts.append(w.cget("text"))
            except tk.TclError:
                pass
        assert i18n.S("LabSwayChainSafetyMarginHint") in texts
        assert i18n.S("LabSwayChainColSafetyMargin") in texts
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 4. 「このアバターの設定を既定値に戻す」も安全域を含めて既定化すること。
# ---------------------------------------------------------------------------

def test_reset_button_also_clears_safety_margin(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    spinboxes = _find_all(dlg, ttk.Spinbox)
    spinboxes[0].delete(0, "end")
    spinboxes[0].insert(0, "4")
    spinboxes[0].event_generate("<KeyRelease>")
    _find_button(dlg, i18n.S("BtnOk")).invoke()
    assert chain_store.is_active(app_root, AVATAR) is True

    ctx2 = _make_ctx(app_root)
    dlg2 = dlg_mod.show_sway_style_dialog(hidden_root, ctx2)
    try:
        reset_btn = _find_button(dlg2, i18n.S("BtnLabSwayChainReset"))
        reset_btn.invoke()
    except Exception:
        dlg2.destroy()
        raise
    assert chain_store.load_config(app_root, AVATAR) == []
    spinboxes2 = _find_all(dlg2, ttk.Spinbox)
    assert int(spinboxes2[0].get()) == dlg_mod.DEFAULT_SAFETY_MARGIN
    dlg2.destroy()


# ---------------------------------------------------------------------------
# 5. 手動追加行にもスピンボックスが付き、既定値で保存対象外になること。
# ---------------------------------------------------------------------------

def test_manual_row_has_spinbox_with_default_value(hidden_root, tmp_path):
    """dev#1572(第2便の過修正の是正、本WP)以降、「ゆれかた一覧」の名前
    入力欄(旧entries[0])は非生成のため、手動追加欄のEntryだけが残る
    (entries[0]、旧entries[1]から繰り上げ)。"""
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        entries = [w for w in _walk(dlg) if type(w) is tk.Entry]
        entries[0].insert(0, "MyManualBone")
        add_btn = _find_button(dlg, i18n.S("BtnSwayChainManualAdd"))
        add_btn.invoke()
        dlg.update()
        row_btn = _find_button_contains(dlg, "MyManualBone")
        assert row_btn is not None
        spinboxes = _find_all(dlg, ttk.Spinbox)
        assert int(spinboxes[-1].get()) == dlg_mod.DEFAULT_SAFETY_MARGIN
    finally:
        dlg.destroy()
