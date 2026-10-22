# test_headequip_select_dialog_dev277.py -- dev#277第1弾④(頭装備切り替え)。
#
# app_py\ui\headequip_select_dialog.py の単体テスト。equipment_select_dialog
# のdev165テストと同じ骨格だが、**チェックの意味論が反転している**ことを
# 中心に据える:
#   equipment_filter    : チェックON=注入対象に含める。既定=全ON。
#   headequip_toggle: チェックON=表示する。既定=全OFF。
#
# 実tk.Tk()は作らない(conftest.pyの共有hidden_root、既存慣例踏襲)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import headequip_select_dialog as hed  # noqa: E402


# ---------------------------------------------------------------------------
# 1. 選択状態の永続化 + 状態サマリ(ラボ憲章④: 既定=空=全部非表示)
# ---------------------------------------------------------------------------

def test_default_state_is_empty_and_inactive(tmp_path):
    app_root = str(tmp_path)
    assert hed.load_selected_codes(app_root) == []
    assert hed.is_active(app_root) is False
    assert hed.state_summary(app_root) is None


def test_save_then_load_round_trip(tmp_path):
    app_root = str(tmp_path)
    hed.save_selected_codes(app_root, ["HeadEquip002", "HeadEquip001", "HeadEquip001"])
    loaded = hed.load_selected_codes(app_root)
    assert loaded == ["HeadEquip001", "HeadEquip002"]  # 重複除去+ソート済み
    assert hed.is_active(app_root) is True


def test_reset_clears_selection(tmp_path):
    app_root = str(tmp_path)
    hed.save_selected_codes(app_root, ["HeadEquip001"])
    assert hed.is_active(app_root) is True
    hed.reset(app_root)
    assert hed.load_selected_codes(app_root) == []
    assert hed.is_active(app_root) is False


def test_state_summary_reflects_count(tmp_path):
    app_root = str(tmp_path)
    hed.save_selected_codes(app_root, ["HeadEquip001", "HeadEquip002", "HeadEquip003"])
    summary = hed.state_summary(app_root, lang="en")
    assert summary is not None
    assert "3" in summary


def test_corrupt_state_file_falls_back_to_empty(tmp_path):
    app_root = str(tmp_path)
    with open(hed._state_path(app_root), "w", encoding="utf-8") as f:
        f.write("{ this is not valid json")
    assert hed.load_selected_codes(app_root) == []


def test_registry_descriptor_shape():
    d = hed.LAB_REGISTRY_DESCRIPTOR
    assert d["id"] == "headequip_toggle"
    assert isinstance(d["name_key"], str)
    for lang in i18n.LANGS:
        assert i18n.S(d["name_key"], lang) and not i18n.S(d["name_key"], lang).startswith("??")
    assert callable(d["state_summary"])
    assert callable(d["open_dialog"])
    assert callable(d["reset"])


# ---------------------------------------------------------------------------
# 2. query_headequip_catalog(): あらゆる失敗経路でフォールバック(例外なし)
# ---------------------------------------------------------------------------

def test_catalog_query_with_missing_manifest_falls_back(tmp_path):
    result = hed.query_headequip_catalog(str(tmp_path), None, "ja")
    assert result["ok"] is False
    assert result["codes"] == []
    assert "noue_template_manifest.json not found" in result["detail"]


def test_catalog_query_with_missing_script_falls_back(tmp_path):
    app_root = tmp_path / "app_root"
    pipeline_py = app_root / "pipeline" / "py"
    pipeline_py.mkdir(parents=True)
    (pipeline_py / "noue_template_manifest.json").write_text("{}")
    result = hed.query_headequip_catalog(str(app_root), None, "ja")
    assert result["ok"] is False
    assert "vp_headequip_names.py not found" in result["detail"]


def test_catalog_query_against_real_pipeline_script_no_pak(tmp_path):
    """app_rootに本物のpipeline\\pyディレクトリ(このリポジトリのもの)を
    指し、palworld_pak未解決のままsubprocess経路を実際に走らせる。
    装備限定と異なり、pak未解決でもcodesは取れる(manifest由来の固定
    カタログのため)ことを確認する——ok=Trueだがnamesは空。

    注意: _APP_PY_DIR は既に repo_root/app_py を指す(このテストファイルは
    app_py/tests/ 配下にあるためdirnameを2回適用済み)。equipment_select_
    dialogの同種テストが dirname をもう1回余分に適用しているのは実は
    off-by-one(1階層上の親ディレクトリを指してしまい、スクリプト不在の
    フォールバック経路をたまたま踏んでいるだけ、ok=Falseの主張と偶然
    整合していたに過ぎない)——本テストではdirname 1回だけで正しい
    repo_root を得る。"""
    repo_root = os.path.dirname(_APP_PY_DIR)
    cache_dir = tmp_path / "cache"

    result = hed.query_headequip_catalog(
        repo_root, None, "ja", cache_dir=str(cache_dir), timeout=30)
    assert result["ok"] is True
    assert len(result["codes"]) == 64
    assert result["names"] == {}


def test_catalog_query_subprocess_crash_is_caught(tmp_path):
    app_root = tmp_path / "app_root"
    pipeline_py = app_root / "pipeline" / "py"
    pipeline_py.mkdir(parents=True)
    (pipeline_py / "noue_template_manifest.json").write_text("{}")
    (pipeline_py / "vp_headequip_names.py").write_text("import sys; sys.exit(3)\n")

    result = hed.query_headequip_catalog(str(app_root), None, "ja")
    assert result["ok"] is False
    assert "exited with 3" in result["detail"]


def test_catalog_query_unparsable_output_is_caught(tmp_path):
    app_root = tmp_path / "app_root"
    pipeline_py = app_root / "pipeline" / "py"
    pipeline_py.mkdir(parents=True)
    (pipeline_py / "noue_template_manifest.json").write_text("{}")
    (pipeline_py / "vp_headequip_names.py").write_text(
        "print('this is not json')\n")

    result = hed.query_headequip_catalog(str(app_root), None, "ja")
    assert result["ok"] is False
    assert "unparsable" in result["detail"]


def test_catalog_query_success_path(tmp_path):
    app_root = tmp_path / "app_root"
    pipeline_py = app_root / "pipeline" / "py"
    pipeline_py.mkdir(parents=True)
    (pipeline_py / "noue_template_manifest.json").write_text("{}")
    payload = {"ok": True, "source": "locres", "detail": "ok",
               "locres_path": "dummy.locres",
               "names": {"HeadEquip001": "Straw Hat"},
               "codes": ["HeadEquip001", "HeadEquip002"]}
    (pipeline_py / "vp_headequip_names.py").write_text(
        "import json\nprint(json.dumps(" + repr(payload) + "))\n")

    result = hed.query_headequip_catalog(str(app_root), None, "ja")
    assert result["ok"] is True
    assert result["codes"] == ["HeadEquip001", "HeadEquip002"]
    assert result["names"] == {"HeadEquip001": "Straw Hat"}


# ---------------------------------------------------------------------------
# 3. ダイアログ本体の配線(実Toplevel、hidden_root経由)
# ---------------------------------------------------------------------------

def _fake_catalog_result(**overrides):
    base = {"ok": True, "source": "locres", "detail": "ok", "locres_path": "x",
            "codes": ["HeadEquip001", "HeadEquip002", "HeadEquip003"],
            "names": {"HeadEquip001": "Straw Hat", "HeadEquip002": "Iron Helm"}}
    base.update(overrides)
    return base


def _empty_catalog_result(**overrides):
    base = {"ok": False, "source": "none", "detail": "boom", "codes": [], "names": {}}
    base.update(overrides)
    return base


def _all_checkbuttons(widget):
    import tkinter as tk
    out = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Checkbutton):
            out.append(child)
        out.extend(_all_checkbuttons(child))
    return out


def _is_checked(widget, cb):
    varname = cb.cget("variable")
    return bool(int(widget.getvar(varname)))


def _find_button_by_text(widget, text):
    import tkinter as tk
    for child in widget.winfo_children():
        if isinstance(child, tk.Button) and child.cget("text") == text:
            return child
        found = _find_button_by_text(child, text)
        if found is not None:
            return found
    return None


def _all_label_texts(widget):
    import tkinter as tk
    out = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            out.append(child.cget("text"))
        out.extend(_all_label_texts(child))
    return out


def test_dialog_builds_checklist_from_catalog(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(hed, "query_headequip_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = hed.HeadEquipSelectContext(
        app_root=str(tmp_path), palworld_pak=None, lang="ja")
    dlg = hed.show_headequip_select_dialog(hidden_root, ctx)
    try:
        assert len(_all_checkbuttons(dlg)) == 3
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 3a. 受入の柱(オーナー原文): 既定(未カスタマイズ)状態は「全チェックOFF」
#     で表示すること(equipment_filterの「全ON」既定と正反対)。
# ---------------------------------------------------------------------------

def test_default_state_shows_all_checkboxes_unchecked(hidden_root, monkeypatch, tmp_path):
    """受入の柱: 未カスタマイズ(初回)状態でダイアログを開くと、全チェック
    ボックスがOFF(=全頭装備が非表示、オーナー原文『デフォルトは全てOFF』
    どおり)であること。equipment_select_dialogの『空=全ONトリック』が
    ここには存在しないことの直接証拠。"""
    monkeypatch.setattr(hed, "query_headequip_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = hed.HeadEquipSelectContext(
        app_root=str(tmp_path), palworld_pak=None, lang="ja")
    dlg = hed.show_headequip_select_dialog(hidden_root, ctx)
    try:
        cbs = _all_checkbuttons(dlg)
        assert len(cbs) == 3
        assert not any(_is_checked(dlg, cb) for cb in cbs), "既定状態は全チェックOFFのはず"
    finally:
        dlg.destroy()


def test_default_ok_without_changes_saves_empty_state(hidden_root, monkeypatch, tmp_path):
    """受入の柱: 既定(全OFF)のままOKを押しても、保存される選択状態は空
    (=job["headequip_show"]キーが出ない既定値=全頭装備が従来どおり
    スタブ生成される)であること。"""
    monkeypatch.setattr(hed, "query_headequip_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = hed.HeadEquipSelectContext(
        app_root=str(tmp_path), palworld_pak=None, lang="ja")
    dlg = hed.show_headequip_select_dialog(hidden_root, ctx)
    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    assert hed.load_selected_codes(str(tmp_path)) == []
    assert hed.is_active(str(tmp_path)) is False
    assert hed.state_summary(str(tmp_path)) is None


def test_negative_control_checking_one_produces_non_default_state(
    hidden_root, monkeypatch, tmp_path
):
    """負の対照: 全OFF状態から1つだけONにしてOKすると、job設定にキーが
    出る非既定状態(1件だけ選択済み=表示対象)が保存されること。"""
    monkeypatch.setattr(hed, "query_headequip_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = hed.HeadEquipSelectContext(
        app_root=str(tmp_path), palworld_pak=None, lang="ja")
    dlg = hed.show_headequip_select_dialog(hidden_root, ctx)

    cbs = _all_checkbuttons(dlg)
    assert len(cbs) == 3
    cbs[0].invoke()  # 全OFFから1つだけONにする

    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    saved = hed.load_selected_codes(str(tmp_path))
    assert len(saved) == 1
    assert hed.is_active(str(tmp_path)) is True


def test_all_off_ok_is_allowed_no_warning(hidden_root, monkeypatch, tmp_path):
    """負の対照(equipment_filterとの意味論差の直接証拠): 頭装備切り替えは
    全OFFが既定かつ正しい状態なので、equipment_filterの『全OFF警告』に
    相当する警告は一切出ず、素直に空リストが保存されてダイアログが
    閉じること。"""
    monkeypatch.setattr(hed, "query_headequip_catalog",
                         lambda *a, **k: _fake_catalog_result())
    warnings = []
    monkeypatch.setattr(hed.messagebox, "showwarning",
                         lambda *a, **k: warnings.append(a))
    ctx = hed.HeadEquipSelectContext(
        app_root=str(tmp_path), palworld_pak=None, lang="ja")
    dlg = hed.show_headequip_select_dialog(hidden_root, ctx)
    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    assert warnings == [], "頭装備切り替えの全OFFは既定値であり、警告は不要"
    assert hed.load_selected_codes(str(tmp_path)) == []
    assert not dlg.winfo_exists()


def test_dialog_ok_with_empty_catalog_preserves_saved_selection(
    hidden_root, monkeypatch, tmp_path
):
    """正: カタログ取得が完全失敗(codes=[])した状態でOKを押しても、
    以前保存済みの選択がそのまま残ること(equipment_select_dialogの
    dev1210修正と同じ保護)。"""
    hed.save_selected_codes(str(tmp_path), ["HeadEquip001"])
    monkeypatch.setattr(hed, "query_headequip_catalog",
                         lambda *a, **k: _empty_catalog_result())
    ctx = hed.HeadEquipSelectContext(
        app_root=str(tmp_path), palworld_pak=None, lang="ja")
    dlg = hed.show_headequip_select_dialog(hidden_root, ctx)
    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()
    assert not dlg.winfo_exists()

    assert hed.load_selected_codes(str(tmp_path)) == ["HeadEquip001"]


def test_dialog_shows_catalog_unavailable_notice_when_codes_empty(
    hidden_root, monkeypatch, tmp_path
):
    monkeypatch.setattr(hed, "query_headequip_catalog",
                         lambda *a, **k: _empty_catalog_result())
    ctx = hed.HeadEquipSelectContext(
        app_root=str(tmp_path), palworld_pak=None, lang="ja")
    dlg = hed.show_headequip_select_dialog(hidden_root, ctx)
    try:
        texts = _all_label_texts(dlg)
        assert any(i18n.S("LabHeadEquipToggleCatalogUnavailableNotice") == t for t in texts)
        assert not any(i18n.S("LabHeadEquipToggleFallbackNotice") == t for t in texts)
    finally:
        dlg.destroy()


def test_dialog_shows_fallback_notice_when_extraction_failed(hidden_root, monkeypatch, tmp_path):
    """実測(2026-08-08、実Palworld pakで確認): 現状は常にこの経路
    (ok=False, names={}, codes非空)を通る——Game.locresが空のため。"""
    monkeypatch.setattr(
        hed, "query_headequip_catalog",
        lambda *a, **k: _fake_catalog_result(ok=False, names={}))
    ctx = hed.HeadEquipSelectContext(
        app_root=str(tmp_path), palworld_pak=None, lang="ja")
    dlg = hed.show_headequip_select_dialog(hidden_root, ctx)
    try:
        texts = _all_label_texts(dlg)
        assert any(i18n.S("LabHeadEquipToggleFallbackNotice") == t for t in texts)
        assert len(_all_checkbuttons(dlg)) == 3
    finally:
        dlg.destroy()


def test_dialog_cancel_does_not_save(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(hed, "query_headequip_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = hed.HeadEquipSelectContext(
        app_root=str(tmp_path), palworld_pak=None, lang="ja")
    dlg = hed.show_headequip_select_dialog(hidden_root, ctx)

    _all_checkbuttons(dlg)[0].invoke()
    cancel_btn = _find_button_by_text(dlg, i18n.S("BtnCancel"))
    cancel_btn.invoke()

    assert hed.load_selected_codes(str(tmp_path)) == []


def test_dialog_follows_language_switch(hidden_root, monkeypatch, tmp_path):
    """言語切替のobserver化: 開いているダイアログのタイトル・ボタン文言が
    i18n.apply_language()の呼び出しに追従すること。"""
    i18n.set_language("ja")
    monkeypatch.setattr(hed, "query_headequip_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = hed.HeadEquipSelectContext(
        app_root=str(tmp_path), palworld_pak=None, lang="ja")
    dlg = hed.show_headequip_select_dialog(hidden_root, ctx)
    try:
        assert dlg.title() == i18n.S("LabHeadEquipToggleDialogTitle", "ja")
        i18n.apply_language("en")
        try:
            assert dlg.title() == i18n.S("LabHeadEquipToggleDialogTitle", "en")
            assert _find_button_by_text(dlg, i18n.S("BtnOk", "en")) is not None
        finally:
            i18n.apply_language("ja")
    finally:
        dlg.destroy()
