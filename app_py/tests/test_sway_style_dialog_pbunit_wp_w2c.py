# test_sway_style_dialog_pbunit_wp_w2c.py -- dev#1508 列車計画W2c(揺れもの
# 一覧のPB単位表示化・段1)。app_py\ui\sway_style_dialog.py の統合テスト
# (実tk窓は開かない、conftest.pyの共有hidden_root+実messagebox呼び出し
# ブロックの既存慣例に従う)。
#
# 正本: .devonly\docs\sway\sway_pbunit_design\DESIGN.md §4-5 / .devonly\docs\sway\sway_wrapup\SPEC.md §2。
# 既存 test_sway_style_dialog_wp_sway_panel.py (--sampleモード中心) は段1でも
# 全緑のまま(サンプルデータは1:1変換のため旧粒度のまま――
# test_sway_pb_catalog_wp_w2c.py::test_sample_pb_units_matches_legacy_sample_
# chains_count_and_anchors参照)。本ファイルは**サンプルではない実データ経路**
# (prefabサイドカーJSON)でのみ確認できる、段1の核心的な新挙動
# (多房PBの1行化・$GUID尾の表示削り・「特殊ボーンを強制セットアップ」)
# を対象にする。
from __future__ import annotations

import json
import os
import sys
import tkinter as tk

import pytest

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)
_ROOT_DIR = os.path.dirname(_APP_PY_DIR)

import i18n  # noqa: E402
import sway_styles_store as store  # noqa: E402
from ui import sway_style_dialog as dlg_mod  # noqa: E402

_FLATHAORI_FIXTURE = os.path.join(
    _ROOT_DIR, "pipeline", "py", "testdata", "sway_allocator", "physbones_flathaori.json")


@pytest.fixture(autouse=True)
def _sway_style_picker_visible_for_this_module():
    """dev#1572(2026-08-19、第2便の過修正の是正、本WP)の是正で「ゆれかた」
    編集UIは既定非表示になったが(sway_style_dialog._SWAY_STYLE_PICKER_
    VISIBLE、既定False)、本ファイルは「特殊ボーンを強制セットアップ」等
    そのロジック自体(コードとして温存)の正しさを検証する回帰テストである
    ため、このモジュールのテストに限りフラグをTrueへ上書きする
    (test_sway_style_dialog_wp_sway_panel.pyの同名フィクスチャと同じ方式)。"""
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


def _all_buttons_containing(root, substr):
    return [w for w in _walk(root) if isinstance(w, tk.Button) and substr in w.cget("text")]


def _write_prefab_sidecar(tmp_path, physbones_doc: dict) -> str:
    """avatar_path(.prefab)とそのUnity輸出先サイドカー(physbones.json)を
    tmp_path配下に用意し、avatar_pathを返す(query_sway_pb_units()の
    prefab経路: work_root/<basename>_export/physbones.json)。"""
    avatar_path = tmp_path / "myavatar.prefab"
    avatar_path.write_text("", encoding="utf-8")
    out_dir = tmp_path / "myavatar_export"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "physbones.json").write_text(
        json.dumps(physbones_doc, ensure_ascii=False), encoding="utf-8")
    return str(avatar_path)


def _make_ctx(app_root, work_root, avatar_path):
    return dlg_mod.SwayStyleContext(
        app_root=app_root, work_root=work_root, avatar_path=avatar_path,
        sample_mode=False,
    )


# ---------------------------------------------------------------------------
# 1. 多房PBが1行にまとまること(段1の核心)。
# ---------------------------------------------------------------------------

def test_multi_chain_pb_shows_as_a_single_row_not_two(hidden_root, tmp_path):
    doc = {
        "format": "divetopalworld-physbones-1",
        "physbones": [{
            "anchor": "Hips", "pb_object_name": "Skirt",
            "chains": [["Skirt_F_01", "Skirt_F_02"], ["Skirt_B_01", "Skirt_B_02"]],
        }],
    }
    avatar_path = _write_prefab_sidecar(tmp_path, doc)
    ctx = _make_ctx(str(tmp_path), str(tmp_path), avatar_path)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        skirt_buttons = _all_buttons_containing(dlg, "Skirt")
        assert len(skirt_buttons) == 1, (
            "多房PB(Skirt、前後2房)が2行に割れている(旧粒度への退行)")
        label = skirt_buttons[0].cget("text")
        # 「(房2本)」相当の補足表示が付くこと。
        assert i18n.S("LabSwayStyleChainCountFormat").format(2) in label
    finally:
        dlg.destroy()


def test_single_chain_pb_has_no_strand_count_suffix(hidden_root, tmp_path):
    doc = {
        "format": "divetopalworld-physbones-1",
        "physbones": [{
            "anchor": "Neck", "pb_object_name": "Scarf",
            "chains": [["Scarf_01", "Scarf_02"]],
        }],
    }
    avatar_path = _write_prefab_sidecar(tmp_path, doc)
    ctx = _make_ctx(str(tmp_path), str(tmp_path), avatar_path)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        btn = _find_button_contains(dlg, "Scarf")
        assert i18n.S("LabSwayStyleChainCountFormat").format(1) not in btn.cget("text")
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 2. $GUID尾が表示から削られること(表示のみ、保存キーは生のまま)。
# ---------------------------------------------------------------------------

def test_guid_tail_is_stripped_from_display_but_not_from_saved_bones(hidden_root, tmp_path):
    guid_anchor = "Lower Arm.L.001$8aba0be2-2624-4628-8e98-ee7c23bd55fc"
    doc = {
        "format": "divetopalworld-physbones-1",
        "physbones": [{"anchor": guid_anchor, "chains": [["Lower Arm.L.002"]]}],
    }
    avatar_path = _write_prefab_sidecar(tmp_path, doc)
    ctx = _make_ctx(str(tmp_path), str(tmp_path), avatar_path)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        # pb_object_nameが無いのでanchorへフォールバック、GUID尾は削られる。
        btn = _find_button_contains(dlg, "Lower Arm.L.001")
        assert "8aba0be2" not in btn.cget("text")

        hard_btn = _find_button(dlg, i18n.S("SwayIntensityHard"))
        hard_btn.invoke()
        dlg.update()
        btn.invoke()
        dlg.update()
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    # 保存データ(bones配列)は生の名前(GUID込み)のまま。
    override = store.get_job_override(str(tmp_path), avatar_path)
    assert override is not None
    assert any(guid_anchor in a["bones"] for a in override["assignments"])


# ---------------------------------------------------------------------------
# 3. fan-out書き込み(1行=1PB、複数房ぶんの鎖単位assignmentsとして保存)。
# ---------------------------------------------------------------------------

def test_painting_multi_chain_row_fans_out_to_all_chains_on_save(hidden_root, tmp_path):
    doc = {
        "format": "divetopalworld-physbones-1",
        "physbones": [{
            "anchor": "Hips", "pb_object_name": "Skirt",
            "chains": [["Skirt_F_01", "Skirt_F_02"], ["Skirt_B_01", "Skirt_B_02"]],
        }],
    }
    avatar_path = _write_prefab_sidecar(tmp_path, doc)
    ctx = _make_ctx(str(tmp_path), str(tmp_path), avatar_path)
    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        soft_btn = _find_button(dlg, i18n.S("SwayIntensitySoft"))
        soft_btn.invoke()
        dlg.update()
        row_btn = _find_button_contains(dlg, "Skirt")
        row_btn.invoke()
        dlg.update()
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise
    override = store.get_job_override(str(tmp_path), avatar_path)
    assert override is not None
    assignments = override["assignments"]
    # 段1: ストアのスキーマは鎖単位のまま。1PB(2房)を塗る=2件のassignments。
    assert len(assignments) == 2
    bones_sets = {tuple(a["bones"]) for a in assignments}
    assert ("Hips", "Skirt_F_01", "Skirt_F_02") in bones_sets
    assert ("Hips", "Skirt_B_01", "Skirt_B_02") in bones_sets
    assert all(a["style"] == "soft" for a in assignments)


def test_reopening_after_multi_chain_save_reconciles_back_to_a_single_row(hidden_root, tmp_path):
    """段1の往復性: 保存(fan-out)→再オープン(reconcile)で、依然として
    1行=1styleとして復元されること(2度目に開いても多房が割れて見えない)。"""
    doc = {
        "format": "divetopalworld-physbones-1",
        "physbones": [{
            "anchor": "Hips", "pb_object_name": "Skirt",
            "chains": [["Skirt_F_01", "Skirt_F_02"], ["Skirt_B_01", "Skirt_B_02"]],
        }],
    }
    avatar_path = _write_prefab_sidecar(tmp_path, doc)
    ctx = _make_ctx(str(tmp_path), str(tmp_path), avatar_path)
    dlg1 = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        soft_btn = _find_button(dlg1, i18n.S("SwayIntensitySoft"))
        soft_btn.invoke()
        dlg1.update()
        _find_button_contains(dlg1, "Skirt").invoke()
        dlg1.update()
        _find_button(dlg1, i18n.S("BtnOk")).invoke()
    except Exception:
        dlg1.destroy()
        raise

    dlg2 = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        skirt_buttons = _all_buttons_containing(dlg2, "Skirt")
        assert len(skirt_buttons) == 1
        assert i18n.S("SwayIntensitySoft") in skirt_buttons[0].cget("text")
    finally:
        dlg2.destroy()


# ---------------------------------------------------------------------------
# 4. 「特殊ボーンを強制セットアップ」ボタン(2026-08-16オーナー口述指定)。
# ---------------------------------------------------------------------------

def _load_flathaori_doc() -> dict:
    with open(_FLATHAORI_FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def test_force_setup_button_i18n_key_and_label():
    assert i18n.S("BtnLabSwayStyleForceSetup", "ja") == "特殊ボーンを強制セットアップ"
    for lang in i18n.LANGS:
        text = i18n.S("BtnLabSwayStyleForceSetup", lang)
        assert text and not text.startswith("??")


def test_force_setup_warning_message_exact_japanese_text():
    assert i18n.S("LabSwayStyleForceSetupWarning", "ja") == (
        "この設定はラボの中でもとくに壊れやすく、"
        "キャラクターの見た目を大きく破損する恐れがあります。"
        "重力を+に設定するとおちつくことがあります。"
    )


def test_force_setup_creates_styles_and_assigns_biased_rows(hidden_root, tmp_path, monkeypatch):
    """flatHaori系fixture(偏向26行)で、ボタンがゆれかた生成+割当を行う
    こと。メッセージダイアログはconftest.pyの既定ブロックを明示的に
    monkeypatchして経路の呼び出しだけを確認する(実ダイアログは開かない)。"""
    doc = _load_flathaori_doc()
    avatar_path = _write_prefab_sidecar(tmp_path, doc)
    ctx = _make_ctx(str(tmp_path), str(tmp_path), avatar_path)

    shown = []
    monkeypatch.setattr(
        dlg_mod.messagebox, "showwarning",
        lambda title, message, **kw: shown.append((title, message)))

    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        force_btn = _find_button(dlg, i18n.S("BtnLabSwayStyleForceSetup"))
        force_btn.invoke()
        dlg.update()
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise

    # メッセージダイアログ経路が呼ばれたこと(タイトル・本文とも正しい文言)。
    assert len(shown) == 1
    assert shown[0][0] == i18n.S("LabSwayStyleForceSetupTitle")
    assert shown[0][1] == i18n.S("LabSwayStyleForceSetupWarning")

    custom = store.load_custom_styles(str(tmp_path))
    auto_names = [n for n in custom if n.startswith(i18n.S("LabSwayStyleForceSetupNameFormat").split("{0}")[0])]
    assert len(auto_names) == 26, f"偏向26行ぶんの自動生成ゆれかたが期待どおりでない: {len(auto_names)}"

    override = store.get_job_override(str(tmp_path), avatar_path)
    assert override is not None
    used_styles = {a["style"] for a in override["assignments"]}
    assert used_styles & set(auto_names), "自動生成ゆれかたが行へ割り当てられていない"


def test_force_setup_generated_values_correspond_to_pb_actual_values(hidden_root, tmp_path, monkeypatch):
    """生成された「ゆれかた」の値が、対応する偏向PBの実値(max_angle_x/
    limit_rotation)に対応していること(値の対応の確認)。"""
    doc = {
        "format": "divetopalworld-physbones-1",
        "physbones": [{
            "anchor": "Spine.002", "pb_object_name": "Hakama",
            "chains": [["Spine.003", "Spine.004"]],
            "params": {
                "pull": 0.3, "spring": 0.2, "stiffness": 0.2, "gravity": 0,
                "gravity_falloff": 0, "immobile": 0, "immobile_type": "AllMotion",
                "limit_type": "Hinge", "max_angle_x": 40.0, "max_angle_z": 40.0,
                "limit_rotation": [-42.0, 0.0, 0.0], "radius": 0,
            },
        }],
    }
    avatar_path = _write_prefab_sidecar(tmp_path, doc)
    ctx = _make_ctx(str(tmp_path), str(tmp_path), avatar_path)
    monkeypatch.setattr(dlg_mod.messagebox, "showwarning", lambda *a, **kw: None)

    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        force_btn = _find_button(dlg, i18n.S("BtnLabSwayStyleForceSetup"))
        force_btn.invoke()
        dlg.update()
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise

    custom = store.load_custom_styles(str(tmp_path))
    assert len(custom) == 1
    params = next(iter(custom.values()))
    assert params["limit_angle"] == 40.0
    assert params["fake_pitch"] == -42.0
    assert params["fake_roll"] == 0.0
    assert params["fake_yaw"] == 0.0


def test_force_setup_ignores_slot_count_and_still_applies_over_9(hidden_root, tmp_path, monkeypatch):
    """スロット数(n/9)はこのボタンでは検査も阻止もしない(2026-08-16
    オーナー指定「カウントも一応無視」)。flatHaoriは偏向26行あり、
    容量9を大きく超えても全行に適用されること。"""
    doc = _load_flathaori_doc()
    avatar_path = _write_prefab_sidecar(tmp_path, doc)
    ctx = _make_ctx(str(tmp_path), str(tmp_path), avatar_path)
    monkeypatch.setattr(dlg_mod.messagebox, "showwarning", lambda *a, **kw: None)

    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        force_btn = _find_button(dlg, i18n.S("BtnLabSwayStyleForceSetup"))
        force_btn.invoke()
        dlg.update()
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise

    custom = store.load_custom_styles(str(tmp_path))
    assert len(custom) == 26  # 容量9を大きく超えても全26行に適用される


def test_force_setup_skips_unbiased_and_manual_rows(hidden_root, tmp_path, monkeypatch):
    """無偏向の行(limitType None)や手動行には触らない(対象は偏向行のみ)。"""
    doc = {
        "format": "divetopalworld-physbones-1",
        "physbones": [{
            "anchor": "Tail_Root", "pb_object_name": "Tail",
            "chains": [["Tail_01", "Tail_02"]],
            "params": {
                "pull": 0.348, "spring": 0.49, "stiffness": 0.2, "gravity": 0,
                "gravity_falloff": 0, "immobile": 0.335, "immobile_type": "AllMotion",
                "limit_type": "None", "max_angle_x": 45.0, "max_angle_z": 45.0,
                "limit_rotation": [0.0, 0.0, 0.0], "radius": 0.0005,
            },
        }],
    }
    avatar_path = _write_prefab_sidecar(tmp_path, doc)
    ctx = _make_ctx(str(tmp_path), str(tmp_path), avatar_path)
    monkeypatch.setattr(dlg_mod.messagebox, "showwarning", lambda *a, **kw: None)

    dlg = dlg_mod.show_sway_style_dialog(hidden_root, ctx)
    try:
        manual_entries = [w for w in _walk(dlg) if type(w) is tk.Entry]
        manual_entries[1].insert(0, "MyManualBone")
        add_btn = _find_button(dlg, i18n.S("BtnSwayChainManualAdd"))
        add_btn.invoke()
        dlg.update()

        force_btn = _find_button(dlg, i18n.S("BtnLabSwayStyleForceSetup"))
        force_btn.invoke()
        dlg.update()
        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    except Exception:
        dlg.destroy()
        raise

    # 無偏向のTail行/手動行はどちらも自動生成の対象にならない
    # (custom_stylesが空のまま)。
    custom = store.load_custom_styles(str(tmp_path))
    assert custom == {}
