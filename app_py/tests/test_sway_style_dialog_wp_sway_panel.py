# test_sway_style_dialog_wp_sway_panel.py -- ラボ「ゆれかた」統合パネル
# (work\wp_sway_panel\BRIEF.md、SPEC.md §2)。app_py\ui\sway_style_dialog.py の
# ダイアログ本体テスト(実tk.Tk()は作らない、conftest.pyの共有hidden_root、
# 既存sway_chain_dialog/lab_raw_sway_params_dialogのテスト慣例踏襲)。
#
# 2026-08-16 WP wp_sway_panel_layout(オーナーHumanTest実試遊フィードバック)
# で全面改修: レイアウト(下部ボタン列・名前入力欄が常時可視)+
# UI方式(行ごとのドロップダウンを廃止し、multi_avatar_pak_dialog.pyと
# 同型のスポイト&ペースト方式へ変更)。
#
# **環境上の注記(座標検証について)**: この実行環境ではtk.Toplevelが実際に
# 画面へマップされない(hidden_root経由のToplevelはwinfo_width()/height()や
# focus_get()が実測値を返さず、常に1やFalseになることを本WP実装時に確認
# 済み――既存テストでもwinfo_rootx/y系の実座標検証は使われていない
# [test_apply_offset_position_preserves_existing_size は子ウィジェットの
# 無い素のToplevelでのみ動作する特殊ケース])。そのため「ボタン列が可視領域
# 内にある」ことは、実座標ではなく**tkinterのpackジオメトリマネージャが
# 保証する構造**(`pack_slaves()`が返す挿入順で、常時可視にしたい要素が
# 伸縮する一覧領域より先に置かれていること)を機械検査することで代替する
# ――pack()は「先に挿入した子がcavityの優先権を持つ」ため、この順序さえ
# 保たれていれば、実際のウィンドウがどれだけ小さくなっても後続の伸縮領域
# 側だけが縮み、先に挿入した固定要素は必ず確保される(Tkの公式に文書化
# された挙動)。コーディネータ指示「既存hidden_root流儀で座標検証等、
# 実装しやすい形でよい」に基づく実装者判断、REPORT.md記載。
from __future__ import annotations

import os
import sys
import tkinter as tk

import pytest

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import sway_styles_store as store  # noqa: E402
from ui import sway_style_dialog as dlg_mod  # noqa: E402

AVATAR = "C:\\fake.vrm"


@pytest.fixture(autouse=True)
def _sway_style_picker_visible_for_this_module():
    """dev#1572(2026-08-19、第2便の過修正の是正、本WP): 製品としては
    「ゆれかた」編集UI(ゆれかた一覧ピッカー・CRUD・生パラメータスライダー・
    「筆」機構)を画面から隠している(sway_style_dialog._SWAY_STYLE_PICKER_
    VISIBLE、既定False)が、本ファイルはそのロジック自体(隠されている間も
    コードとして温存されている)の正しさを検証する回帰テスト群である。
    このモジュールのテストに限りフラグをTrueへ上書きし、実行後は必ず
    元の値へ戻す(他モジュールのテスト[隠蔽の証明側]に影響させない)。"""
    original = dlg_mod._SWAY_STYLE_PICKER_VISIBLE
    dlg_mod._SWAY_STYLE_PICKER_VISIBLE = True
    try:
        yield
    finally:
        dlg_mod._SWAY_STYLE_PICKER_VISIBLE = original


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


def _find_entries(root):
    return [w for w in _walk(root) if type(w) is tk.Entry]


def _make_ctx(app_root, sample_mode=True, avatar_path=AVATAR):
    return dlg_mod.SwayStyleContext(
        app_root=app_root, work_root=app_root, avatar_path=avatar_path,
        sample_mode=sample_mode,
    )


# ---------------------------------------------------------------------------
# 1. i18n / レジストリ記述子。
# ---------------------------------------------------------------------------

NEW_I18N_KEYS = [
    "LabFeatureSwayStyles", "LabSwayStyleDialogTitle", "LabSwayStyleHint",
    "LabSwayStyleStylesSectionLabel", "LabSwayStyleStylesHint",
    "LabSwayStyleChainsSectionLabel", "LabSwayStyleChainsHint",
    "LabSwayStyleParamWdl", "LabSwayStyleParamWdr",
    "LabSwayStyleParamPitch", "LabSwayStyleParamRoll", "LabSwayStyleParamYaw",
    "LabSwayStyleSlotFormat", "LabSwayStyleSlotHint",
    "LabSwayStyleCurrentPaintFormat",
    "BtnLabSwayStyleBulkApply", "BtnLabSwayStyleCreate",
    "BtnLabSwayStyleRename", "BtnLabSwayStyleDuplicate", "LabSwayStyleNewNameLabel",
    "LabSwayStyleNameEmptyError", "LabSwayStyleNameReservedError",
    "LabSwayStyleNameDuplicateError",
    "LabSwayStyleMigratedNameFormat", "LabSwayStyleSummaryFormat",
]


def test_all_new_i18n_keys_present_in_all_languages():
    for key in NEW_I18N_KEYS:
        for lang in i18n.LANGS:
            text = i18n.S(key, lang)
            assert text and not text.startswith("??"), f"i18nキー欠落: {key} / {lang}"


def test_max_custom_reached_error_key_no_longer_exists():
    assert "LabSwayStyleMaxCustomReachedError" not in i18n.TABLE


def test_wd_hint_label_key_no_longer_exists():
    assert "LabSwayStyleWdHint" not in i18n.TABLE


def test_custom_count_label_key_no_longer_exists():
    assert "LabSwayStyleCustomCountFormat" not in i18n.TABLE


def test_col_style_header_key_no_longer_exists():
    """2026-08-16 WP wp_sway_panel_layout: 行ごとのドロップダウン廃止に伴い、
    列見出し「ゆれかた」(LabSwayStyleColStyle)も不要になった(スポイト&
    ペースト方式ではボタン1個の表示に統合され、列という概念が無い)。"""
    assert "LabSwayStyleColStyle" not in i18n.TABLE


def test_wdl_wdr_labels_are_meaning_based_not_left_right():
    for lang in i18n.LANGS:
        wdl_text = i18n.S("LabSwayStyleParamWdl", lang)
        wdr_text = i18n.S("LabSwayStyleParamWdr", lang)
        assert "慣性" not in wdl_text and "慣性" not in wdr_text
        assert "左" not in wdl_text and "右" not in wdr_text
    assert i18n.S("LabSwayStyleParamWdl", "ja") == "移動追従"
    assert i18n.S("LabSwayStyleParamWdr", "ja") == "回転追従"


def test_panel_name_is_sway_chain_detail_not_sway_style():
    """dev#1572(2026-08-19是正WP)で「揺れもの詳細設定(安全域)」へ改名
    (タスク指示#4: パネル内が実質「安全域」設定のみになったため)。
    旧名"揺れもの詳細"はもう名乗らない(過去の"ゆれかた"名を引きずらない)。"""
    assert i18n.S("LabFeatureSwayStyles", "ja") == "揺れもの詳細設定(安全域)"
    assert i18n.S("LabSwayStyleDialogTitle", "ja") == "揺れもの詳細設定(安全域)"
    assert "安全域" in i18n.S("LabFeatureSwayStyles", "ja")


def test_chains_section_label_is_sway_list_not_chain_list():
    assert i18n.S("LabSwayStyleChainsSectionLabel", "ja") == "揺れもの一覧"


def test_registry_descriptor_shape():
    d = dlg_mod.LAB_REGISTRY_DESCRIPTOR
    assert d["id"] == "sway_styles"
    assert d["name_key"] == "LabFeatureSwayStyles"
    assert callable(d["state_summary"])
    assert callable(d["open_dialog"])
    assert callable(d["reset"])


# ---------------------------------------------------------------------------
# 2. ダイアログが開けること(BRIEF受入ゲート5)+④無退行(OKするだけでは
#    何も保存されない)+負の対照(1行だけ塗るとjobに現れる)。
# ---------------------------------------------------------------------------

def test_dialog_opens_with_sample_data(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        assert dlg.winfo_exists()
        buttons = _find_all(dlg, tk.Button)
        # 4種の組み込み(なし/やわらかめ/ふつう/かため)+6件のSAMPLE_CHAINS行。
        assert len(buttons) >= 10
    finally:
        dlg.destroy()


def test_dialog_opens_with_empty_catalog(hidden_root, tmp_path):
    """アバター未選択/カタログ空でもクラッシュしない(空状態の正規表示)。"""
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=False, avatar_path="C:\\does_not_exist.vrm")
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        assert dlg.winfo_exists()
    finally:
        dlg.destroy()


def test_dialog_ok_without_change_keeps_defaults(hidden_root, tmp_path):
    """④無退行: カタログにnative-donor既定ONの鎖が無い状態(空カタログ)で
    開いて何も変更せずOKしても、ストアは既定のままであること。"""
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=False, avatar_path="C:\\does_not_exist.vrm")
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    assert store.load_custom_styles(app_root) == {}
    assert store.load_assignments(app_root, "C:\\does_not_exist.vrm") == []
    assert store.is_active(app_root, "C:\\does_not_exist.vrm") is False
    assert store.get_job_override(app_root, "C:\\does_not_exist.vrm") is None


def test_dialog_open_with_sample_data_migrates_native_donor_defaults_but_only_persists_on_ok(
    hidden_root, tmp_path,
):
    """SAMPLE_CHAINSの尻尾/耳はnative-donor既定ONのため、ダイアログを開いた
    時点で working set にはマイグレーション結果(SPEC.md §2「旧ONの鎖」)が
    反映される。ただし**ディスクへ書き込まれるのはOKを押したときだけ**。"""
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        assert not os.path.exists(store._state_path(app_root))  # noqa: SLF001
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    assert store.is_active(app_root, AVATAR) is True
    assignments = store.load_assignments(app_root, AVATAR)
    assert len(assignments) >= 2


def test_negative_control_painting_one_row_then_ok_appears_in_store(hidden_root, tmp_path):
    """負の対照: 「かため」をクリックして筆に持ち、行を1つクリックして塗り、
    OKすると、ストア/job双方に現れる。"""
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        hard_btn = _find_button(dlg, i18n.S("SwayIntensityHard"))
        hard_btn.invoke()
        dlg.update()
        spine_row_btn = _find_button_contains(dlg, "J_Bip_C_Spine2")
        spine_row_btn.invoke()
        dlg.update()
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    assert store.is_active(app_root, AVATAR) is True
    override = store.get_job_override(app_root, AVATAR)
    assert override is not None
    assert any(a["style"] == "hard" for a in override["assignments"])


def test_dialog_cancel_close_does_not_save(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    dlg.destroy()
    assert store.load_custom_styles(app_root) == {}
    assert store.load_assignments(app_root, AVATAR) == []
    assert not os.path.exists(store._state_path(app_root))  # noqa: SLF001


# ---------------------------------------------------------------------------
# 3. スポイト&ペースト方式(2026-08-16オーナーUI変更指示)。
# ---------------------------------------------------------------------------

def test_picking_style_shows_sunken_relief_and_current_paint_label(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        soft_btn = _find_button(dlg, i18n.S("SwayIntensitySoft"))
        soft_btn.invoke()
        dlg.update()
        assert str(soft_btn.cget("relief")) == "sunken"
        paint_labels = [w for w in _walk(dlg) if isinstance(w, tk.Label)
                         and i18n.S("LabSwayStyleCurrentPaintFormat").split("{0}")[0]
                         in w.cget("text")]
        assert paint_labels
        assert paint_labels[0].cget("text") == i18n.S(
            "LabSwayStyleCurrentPaintFormat").format(i18n.S("SwayIntensitySoft"))
    finally:
        dlg.destroy()


def test_paint_row_assigns_current_brush_and_updates_label(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        normal_btn = _find_button(dlg, i18n.S("SwayIntensityNormal"))
        normal_btn.invoke()
        dlg.update()
        row_btn = _find_button_contains(dlg, "J_Bip_C_Spine2")
        row_btn.invoke()
        dlg.update()
        row_btn2 = _find_button_contains(dlg, "J_Bip_C_Spine2")
        assert i18n.S("SwayIntensityNormal") in row_btn2.cget("text")
        assert "->" in row_btn2.cget("text")
    finally:
        dlg.destroy()


def test_painting_with_none_clears_a_previously_assigned_row(hidden_root, tmp_path):
    """「なし」を筆に持てば、クリックで揺れを外せる(消しゴム)。"""
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        # 尻尾はnative-donor既定ONで既に"ふつう"が塗られている想定。
        tail_btn_before = _find_button_contains(dlg, "J_Bip_C_Hips (Tail_01)")
        assert "->" in tail_btn_before.cget("text")
        none_btn = _find_button(dlg, i18n.S("SwayIntensityNone"))
        none_btn.invoke()
        dlg.update()
        tail_btn_before.invoke()
        dlg.update()
        tail_btn_after = _find_button_contains(dlg, "J_Bip_C_Hips (Tail_01)")
        assert "->" not in tail_btn_after.cget("text")
    finally:
        dlg.destroy()


def test_paint_row_without_holding_brush_is_a_no_op(hidden_root, tmp_path):
    """何も筆を持っていない状態で行をクリックしても何も起きない
    (multi_avatar_pak_dialog.on_click_equipment()と同じ安全側)。"""
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        row_btn = _find_button_contains(dlg, "J_Bip_C_Spine2")
        assert "->" not in row_btn.cget("text")
        row_btn.invoke()
        dlg.update()
        row_btn2 = _find_button_contains(dlg, "J_Bip_C_Spine2")
        assert "->" not in row_btn2.cget("text")
    finally:
        dlg.destroy()


def test_bulk_apply_paints_all_rows_with_current_brush(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        hard_btn = _find_button(dlg, i18n.S("SwayIntensityHard"))
        hard_btn.invoke()
        dlg.update()
        bulk_btn = _find_button(dlg, i18n.S("BtnLabSwayStyleBulkApply"))
        bulk_btn.invoke()
        dlg.update()
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    override = store.get_job_override(app_root, AVATAR)
    assert override is not None
    assert all(a["style"] == "hard" for a in override["assignments"])
    assert len(override["assignments"]) == 6  # SAMPLE_CHAINS件数


def test_bulk_apply_without_brush_is_a_no_op(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        bulk_btn = _find_button(dlg, i18n.S("BtnLabSwayStyleBulkApply"))
        bulk_btn.invoke()
        dlg.update()
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    # native-donor既定ON(尻尾/耳)の移行分だけが残り、それ以外は変化なし。
    override = store.get_job_override(app_root, AVATAR)
    assert override is not None
    assert len(override["assignments"]) == 3


def test_manual_add_uses_current_brush(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        soft_btn = _find_button(dlg, i18n.S("SwayIntensitySoft"))
        soft_btn.invoke()
        dlg.update()
        manual_entries = _find_entries(dlg)
        # entries[0] = ゆれかた名エントリ、entries[1] = 手動追加のボーン名。
        manual_entries[1].insert(0, "MyManualBone")
        add_btn = _find_button(dlg, i18n.S("BtnSwayChainManualAdd"))
        add_btn.invoke()
        dlg.update()
        row_btn = _find_button_contains(dlg, "MyManualBone")
        assert i18n.S("SwayIntensitySoft") in row_btn.cget("text")
    finally:
        dlg.destroy()


def test_manual_add_without_brush_defaults_to_none(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        manual_entries = _find_entries(dlg)
        manual_entries[1].insert(0, "MyManualBone2")
        add_btn = _find_button(dlg, i18n.S("BtnSwayChainManualAdd"))
        add_btn.invoke()
        dlg.update()
        row_btn = _find_button_contains(dlg, "MyManualBone2")
        assert "->" not in row_btn.cget("text")
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 4. ゆれかた一覧: 新規作成/複製/改名/削除。
# ---------------------------------------------------------------------------

def test_create_custom_style_then_ok_persists_definition(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        entries = _find_entries(dlg)
        name_entry = entries[0]
        name_entry.insert(0, "MyCustom")
        create_btn = _find_button(dlg, i18n.S("BtnLabSwayStyleCreate"))
        create_btn.invoke()
        dlg.update()
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    custom = store.load_custom_styles(app_root)
    assert "MyCustom" in custom
    assert custom["MyCustom"] == {k: 0.0 for k in store.STYLE_PARAM_KEYS}


def test_create_immediately_appears_as_pickable_and_paintable(hidden_root, tmp_path):
    """回帰テスト(2026-08-16オーナー実物目視で発覚したドロップダウンの
    バグの精神を引き継ぐ): 新規作成したカスタムが即座にピッカー・
    塗り対象として使えること。"""
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        entries = _find_entries(dlg)
        entries[0].insert(0, "FreshOne")
        create_btn = _find_button(dlg, i18n.S("BtnLabSwayStyleCreate"))
        create_btn.invoke()
        dlg.update()
        fresh_btn = _find_button(dlg, "FreshOne")
        fresh_btn.invoke()
        dlg.update()
        row_btn = _find_button_contains(dlg, "J_Bip_C_Spine2")
        row_btn.invoke()
        dlg.update()
        row_btn2 = _find_button_contains(dlg, "J_Bip_C_Spine2")
        assert "FreshOne" in row_btn2.cget("text")
    finally:
        dlg.destroy()


def test_create_duplicate_name_shows_error_and_does_not_overwrite(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        entries = _find_entries(dlg)
        name_entry = entries[0]
        create_btn = _find_button(dlg, i18n.S("BtnLabSwayStyleCreate"))
        for _ in range(2):
            name_entry.delete(0, "end")
            name_entry.insert(0, "Dup")
            create_btn.invoke()
            dlg.update()
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    custom = store.load_custom_styles(app_root)
    assert list(custom.keys()) == ["Dup"]


def test_create_reserved_name_is_rejected(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        entries = _find_entries(dlg)
        name_entry = entries[0]
        name_entry.insert(0, "soft")
        create_btn = _find_button(dlg, i18n.S("BtnLabSwayStyleCreate"))
        create_btn.invoke()
        dlg.update()
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    assert store.load_custom_styles(app_root) == {}


def test_duplicate_builtin_creates_custom_with_same_params(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        hard_btn = _find_button(dlg, i18n.S("SwayIntensityHard"))
        hard_btn.invoke()
        dlg.update()
        entries = _find_entries(dlg)
        entries[0].insert(0, "HardCopy")
        dup_btn = _find_button(dlg, i18n.S("BtnLabSwayStyleDuplicate"))
        dup_btn.invoke()
        dlg.update()
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    custom = store.load_custom_styles(app_root)
    assert custom["HardCopy"] == store.BUILTIN_STYLE_PARAMS["hard"]


def test_duplicate_none_is_allowed_and_yields_zero_params(hidden_root, tmp_path):
    """「なし」も複製元として選べる(全ゼロのカスタムができる、実装者解釈:
    禁止する積極的理由が無いため許容、REPORT.md記載)。"""
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        none_btn = _find_button(dlg, i18n.S("SwayIntensityNone"))
        none_btn.invoke()
        dlg.update()
        entries = _find_entries(dlg)
        entries[0].insert(0, "BlankCopy")
        dup_btn = _find_button(dlg, i18n.S("BtnLabSwayStyleDuplicate"))
        dup_btn.invoke()
        dlg.update()
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    custom = store.load_custom_styles(app_root)
    assert custom["BlankCopy"] == {k: 0.0 for k in store.STYLE_PARAM_KEYS}


def test_delete_custom_style_resets_referencing_rows_to_none(hidden_root, tmp_path):
    app_root = str(tmp_path)
    store.save_state(app_root, AVATAR, {"Temp": {k: 0.0 for k in store.STYLE_PARAM_KEYS}},
                      [{"bones": ["J_Bip_C_Hips", "Tail_01", "Tail_02", "Tail_03"],
                        "style": "Temp"}])
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        temp_btn = _find_button(dlg, "Temp")
        temp_btn.invoke()
        dlg.update()
        delete_btn = _find_button(dlg, i18n.S("BtnRemoveManualChain"))
        delete_btn.invoke()
        dlg.update()
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    assert store.load_custom_styles(app_root) == {}
    assert store.load_assignments(app_root, AVATAR) == []


def test_builtin_sliders_are_disabled_and_none_too(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        scales = _find_all(dlg, tk.Scale)
        assert len(scales) == len(store.STYLE_PARAM_KEYS)
        # 初期状態(何も選んでいない)は無効。
        assert all(str(s.cget("state")) == "disabled" for s in scales)
        none_btn = _find_button(dlg, i18n.S("SwayIntensityNone"))
        none_btn.invoke()
        dlg.update()
        assert all(str(s.cget("state")) == "disabled" for s in scales)
        hard_btn = _find_button(dlg, i18n.S("SwayIntensityHard"))
        hard_btn.invoke()
        dlg.update()
        assert all(str(s.cget("state")) == "disabled" for s in scales)
    finally:
        dlg.destroy()


def test_custom_sliders_are_editable(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        entries = _find_entries(dlg)
        entries[0].insert(0, "Editable1")
        create_btn = _find_button(dlg, i18n.S("BtnLabSwayStyleCreate"))
        create_btn.invoke()
        dlg.update()
        scales = _find_all(dlg, tk.Scale)
        assert all(str(s.cget("state")) == "normal" for s in scales)
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 5. スロット計算(行=PBコンポーネント単位、dev#1551で統合廃止)。
# ---------------------------------------------------------------------------

def test_slot_label_counts_each_row_independently_dev1551(hidden_root, tmp_path):
    """hub前提だった箇所の追従(dev#1551、2026-08-17オーナー裁定「hubを
    廃止し1chainあたり1KPノードへ移行する」): 旧実装はanchorが同じ行を
    1スロットへdedupしていた(SAMPLE_CHAINSはanchor 3種: Hips x3, Head x2,
    Spine2 x1 -> 旧期待値3)が、dev#1551で複数コンポーネントの統合機構
    自体が廃止されたため、行ごとに独立してスロットを消費する
    (`pipeline\\py\\sway_allocator.build_groups()`のdev#1551対応と同じ
    規約)——期待値はSAMPLE_CHAINSの全行数である6になる。"""
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        hard_btn = _find_button(dlg, i18n.S("SwayIntensityHard"))
        hard_btn.invoke()
        dlg.update()
        bulk_btn = _find_button(dlg, i18n.S("BtnLabSwayStyleBulkApply"))
        bulk_btn.invoke()
        dlg.update()
        # SAMPLE_CHAINSは6行(anchorはHips x3, Head x2, Spine2 x1の3種)、
        # dev#1551ではdedupしないので6行=6スロット消費として数える。
        slot_labels = [w for w in _walk(dlg) if isinstance(w, tk.Label)
                       and i18n.S("LabSwayStyleSlotFormat").split("{0}")[0] in w.cget("text")]
        assert slot_labels, "スロットラベルが見つからない"
        assert slot_labels[0].cget("text") == i18n.S("LabSwayStyleSlotFormat").format(6)
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 6. レイアウト規約(2026-08-16オーナーHumanTest実試遊フィードバック):
#    下部ボタン列・「ゆれかた一覧」の名前入力欄+CRUD操作域・「揺れもの一覧」
#    のフッター(スロット表示/一括塗り/手動追加)は、それぞれの伸縮する
#    一覧領域よりも**先**にpack()され、常時可視のcavity優先権を持つこと。
#    モジュールdocstring上部の「環境上の注記」参照(実座標が取れない環境の
#    ため、pack_slaves()の挿入順で構造的に検査する)。
# ---------------------------------------------------------------------------

def test_bottom_button_bar_is_packed_first_with_side_bottom(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        slaves = dlg.pack_slaves()
        assert len(slaves) >= 1
        bottom = slaves[0]
        assert bottom.pack_info().get("side") == "bottom"
        # 残りの兄弟はすべてbottomより後にpackされている(=cavity優先権が
        # bottomにある)。念のため、伸縮するセクション(expand=1)が
        # bottomより前に来ていないことも確認する(負の対照: もし後退して
        # 一覧を先にpackする実装へ戻れば、このテストで検出される)。
        for s in slaves[1:]:
            assert s.pack_info().get("side") != "bottom" or s is bottom
        expand_siblings = [s for s in slaves if int(s.pack_info().get("expand", 0))]
        assert expand_siblings, "expand=Trueの一覧セクションが見当たらない"
        assert slaves.index(bottom) < min(slaves.index(s) for s in expand_siblings)
        # 実際に含むボタン(OK/キャンセル/リセット)を確認。
        ok_btn = _find_button(bottom, i18n.S("BtnOk"))
        assert ok_btn is not None
    finally:
        dlg.destroy()


def test_styles_section_crud_area_is_packed_before_scrollable_body(hidden_root, tmp_path):
    """2026-08-16オーナーHumanTest実試遊バグ「ゆれかた一覧の名前入力欄に
    カーソルが当たらない」の回帰テスト: 名前入力欄を含むcrud_areaが、
    伸縮するstyles_body(ピッカー+スライダー)より先にside="bottom"で
    packされていること。"""
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        slaves = dlg.pack_slaves()
        styles_frame = [s for s in slaves if isinstance(s, tk.LabelFrame)][0]
        inner_slaves = styles_frame.pack_slaves()
        crud_candidates = [s for s in inner_slaves if s.pack_info().get("side") == "bottom"]
        assert crud_candidates, "crud_area(side=bottom)が見つからない"
        crud_area = crud_candidates[0]
        expand_siblings = [s for s in inner_slaves if int(s.pack_info().get("expand", 0))]
        assert expand_siblings, "styles_body(expand=1)が見つからない"
        assert inner_slaves.index(crud_area) < min(
            inner_slaves.index(s) for s in expand_siblings)
        entries = _find_entries(crud_area)
        assert entries, "名前入力欄がcrud_area配下に見つからない"
    finally:
        dlg.destroy()


def test_chains_section_footer_is_packed_before_scrollable_rows(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        slaves = dlg.pack_slaves()
        chains_frame = [s for s in slaves if isinstance(s, tk.LabelFrame)][1]
        inner_slaves = chains_frame.pack_slaves()
        footer_candidates = [s for s in inner_slaves if s.pack_info().get("side") == "bottom"]
        assert footer_candidates, "footer_area(side=bottom)が見つからない"
        footer_area = footer_candidates[0]
        expand_siblings = [s for s in inner_slaves if int(s.pack_info().get("expand", 0))]
        assert expand_siblings, "rows_pane(expand=1)が見つからない"
        assert inner_slaves.index(footer_area) < min(
            inner_slaves.index(s) for s in expand_siblings)
        # フッターには一括塗り+手動追加が含まれる。
        assert _find_button(footer_area, i18n.S("BtnLabSwayStyleBulkApply")) is not None
        assert _find_button(footer_area, i18n.S("BtnSwayChainManualAdd")) is not None
    finally:
        dlg.destroy()


def test_dialog_has_minsize_set(hidden_root, tmp_path):
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        min_w, min_h = dlg.minsize()
        assert min_w > 0 and min_h > 0
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 7. 名前入力欄フォーカス可能性(2026-08-16オーナーHumanTest実試遊バグ
#    「ゆれかた一覧の名前入力欄にカーソルが当たらない」の直接回帰テスト)。
# ---------------------------------------------------------------------------

def test_style_name_entry_is_normal_state_and_accepts_focus_without_error(hidden_root, tmp_path):
    """原因調査(コード+実挙動、コーディネータ指示どおり): ソース上
    (app_py\\ui\\sway_style_dialog.py)には name_entry へ
    state="disabled"/state="readonly" を設定する箇所は無く、実挙動としても
    state="normal"であることを直接確認する。フォーカス移譲
    (focus_set())が例外なく完了することも確認する――実座標/実フォーカスの
    検証がこの実行環境で機能しないことはモジュールdocstring上部の
    「環境上の注記」のとおりで、focus_get()による転送先の実証はできないが、
    「state=normalであること」+「6.の構造テストでcrud_areaが常にcavity
    優先権を持つこと」の組み合わせで、旧不具合(一覧領域に押し出されて
    実質到達不能になっていたこと)の再発を機械的に防止する。"""
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        entries = _find_entries(dlg)
        name_entry = entries[0]
        assert str(name_entry.cget("state")) == "normal"
        assert str(name_entry.cget("takefocus")) not in ("0",)
        name_entry.focus_set()
        dlg.update()  # 例外を送出しないことの確認そのものがアサーション。
        # 実際に文字入力できること(disabled/readonlyならinsert()自体が
        # 効かない、またはTclErrorになる)。
        name_entry.insert(0, "FocusCheck")
        assert name_entry.get() == "FocusCheck"
    finally:
        dlg.destroy()


def test_style_name_entry_is_direct_child_of_crud_area_not_nested_in_scroll_canvas(
    hidden_root, tmp_path,
):
    """名前入力欄が、伸縮する一覧領域(Canvas配下の内部Frame)ではなく、
    常時可視が保証されたcrud_area配下に直接あることを確認する(旧不具合の
    構造的原因そのものの再発防止――旧実装はこの入力欄を一覧セクション全体の
    構築が終わった後に一覧と同じ並びでpackしていた)。"""
    app_root = str(tmp_path)
    ctx = _make_ctx(app_root, sample_mode=True)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        entries = _find_entries(dlg)
        name_entry = entries[0]
        parent = dlg.nametowidget(name_entry.winfo_parent())  # name_row
        grandparent = dlg.nametowidget(parent.winfo_parent())  # crud_area
        assert grandparent.pack_info().get("side") == "bottom"
    finally:
        dlg.destroy()
