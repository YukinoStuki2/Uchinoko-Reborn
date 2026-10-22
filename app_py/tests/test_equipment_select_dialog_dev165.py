# test_equipment_select_dialog_dev165.py -- dev#165(装備限定)ラボ機能。
#
# app_py\ui\equipment_select_dialog.py の単体テスト。3つの柱:
#   1. 選択状態の永続化(load/save/reset)+状態サマリ関数(ラボ憲章④:
#      未選択=既定=state_summary()がNone)
#   2. query_equipment_catalog(): pipeline\py\vp_equipment_names.py への
#      subprocess呼び出しが失敗するあらゆる経路(pak未解決/スクリプト不在/
#      起動失敗/非0終了/JSON壊れ)で例外を投げず、ok=Falseの構造化結果へ
#      落ちること(=装備選択ダイアログの「抽出失敗時は内部コード表示へ
#      フォールバック」要件の、GUI層での対応部分)
#   3. ダイアログ本体(実Toplevel、hidden_root経由)の配線: チェックリストの
#      構築・検索フィルタ・OK/Cancelの保存/非保存
#
# 実tk.Tk()は作らない(conftest.pyの共有hidden_root、既存慣例踏襲)。
from __future__ import annotations

import json
import os
import sys
import tempfile

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import equipment_select_dialog as esd  # noqa: E402


# ---------------------------------------------------------------------------
# 1. 選択状態の永続化 + 状態サマリ
# ---------------------------------------------------------------------------

def test_default_state_is_empty_and_inactive(tmp_path):
    app_root = str(tmp_path)
    assert esd.load_selected_codes(app_root) == []
    assert esd.is_active(app_root) is False
    assert esd.state_summary(app_root) is None


def test_save_then_load_round_trip(tmp_path):
    app_root = str(tmp_path)
    esd.save_selected_codes(app_root, ["Hunter001", "Bronze001", "Bronze001"])
    loaded = esd.load_selected_codes(app_root)
    assert loaded == ["Bronze001", "Hunter001"]  # 重複除去+ソート済み
    assert esd.is_active(app_root) is True


def test_reset_clears_selection(tmp_path):
    app_root = str(tmp_path)
    esd.save_selected_codes(app_root, ["Bronze001"])
    assert esd.is_active(app_root) is True
    esd.reset(app_root)
    assert esd.load_selected_codes(app_root) == []
    assert esd.is_active(app_root) is False


def test_state_summary_reflects_count():
    with tempfile.TemporaryDirectory() as app_root:
        esd.save_selected_codes(app_root, ["Bronze001", "Hunter001", "Iron001"])
        summary = esd.state_summary(app_root, lang="en")
        assert summary is not None
        assert "3" in summary


def test_corrupt_state_file_falls_back_to_empty(tmp_path):
    app_root = str(tmp_path)
    with open(esd._state_path(app_root), "w", encoding="utf-8") as f:
        f.write("{ this is not valid json")
    assert esd.load_selected_codes(app_root) == []


def test_registry_descriptor_shape():
    d = esd.LAB_REGISTRY_DESCRIPTOR
    assert d["id"] == "equipment_filter"
    assert isinstance(d["name_key"], str)
    # name_keyはi18n辞書に実在し、全言語で空でないこと
    for lang in i18n.LANGS:
        assert i18n.S(d["name_key"], lang) and not i18n.S(d["name_key"], lang).startswith("??")
    assert callable(d["state_summary"])
    assert callable(d["open_dialog"])
    assert callable(d["reset"])


# ---------------------------------------------------------------------------
# 2. query_equipment_catalog(): あらゆる失敗経路でフォールバック(例外なし)
# ---------------------------------------------------------------------------

def test_catalog_query_with_no_pak_falls_back():
    result = esd.query_equipment_catalog("C:\\fake_app_root", None, "ja")
    assert result["ok"] is False
    assert result["codes"] == []
    assert result["names"] == {}
    assert "not resolved" in result["detail"]


def test_catalog_query_with_missing_pak_file_falls_back(tmp_path):
    result = esd.query_equipment_catalog(
        str(tmp_path), str(tmp_path / "does_not_exist.pak"), "ja")
    assert result["ok"] is False
    assert result["codes"] == []


def test_catalog_query_with_missing_script_falls_back(tmp_path):
    app_root = tmp_path / "app_root"
    app_root.mkdir()
    fake_pak = tmp_path / "Pal-Windows.pak"
    fake_pak.write_bytes(b"x" * 16)
    result = esd.query_equipment_catalog(str(app_root), str(fake_pak), "ja")
    assert result["ok"] is False
    assert "vp_equipment_names.py not found" in result["detail"]


def test_catalog_query_against_real_pipeline_script_on_fake_pak(tmp_path):
    """app_root配下に本物のpipeline\\pyディレクトリ構成を再現し(このリポジトリの
    ものをそのまま指す)、偽のpakを渡してsubprocess経路まで実際に走らせる
    (=展開失敗を模擬したフォールバックの結合試験)。ok=Falseへ落ちること、
    例外が呼び出し元へ漏れないことを確認する。"""
    repo_root = os.path.dirname(os.path.dirname(_APP_PY_DIR))
    fake_pak = tmp_path / "Pal-Windows.pak"
    fake_pak.write_bytes(b"not a real pak" * 20)
    cache_dir = tmp_path / "cache"

    result = esd.query_equipment_catalog(
        repo_root, str(fake_pak), "ja", cache_dir=str(cache_dir), timeout=30)
    assert result["ok"] is False
    assert result["codes"] == []
    assert result["names"] == {}


def test_catalog_query_subprocess_crash_is_caught(monkeypatch, tmp_path):
    app_root = tmp_path / "app_root"
    pipeline_py = app_root / "pipeline" / "py"
    pipeline_py.mkdir(parents=True)
    (pipeline_py / "vp_equipment_names.py").write_text("import sys; sys.exit(3)\n")
    fake_pak = tmp_path / "Pal-Windows.pak"
    fake_pak.write_bytes(b"x" * 16)

    result = esd.query_equipment_catalog(str(app_root), str(fake_pak), "ja")
    assert result["ok"] is False
    assert "exited with 3" in result["detail"]


def test_catalog_query_unparsable_output_is_caught(tmp_path):
    app_root = tmp_path / "app_root"
    pipeline_py = app_root / "pipeline" / "py"
    pipeline_py.mkdir(parents=True)
    (pipeline_py / "vp_equipment_names.py").write_text(
        "print('this is not json')\n")
    fake_pak = tmp_path / "Pal-Windows.pak"
    fake_pak.write_bytes(b"x" * 16)

    result = esd.query_equipment_catalog(str(app_root), str(fake_pak), "ja")
    assert result["ok"] is False
    assert "unparsable" in result["detail"]


def test_catalog_query_success_path(tmp_path):
    """正常系(subprocessが期待どおりのJSONを吐く場合)の配線確認。実locres
    解析はvp_equipment_names.py側の単体テストの責務なので、ここではCLIの
    出力契約(最終行がJSON)だけをスタブで再現する。"""
    app_root = tmp_path / "app_root"
    pipeline_py = app_root / "pipeline" / "py"
    pipeline_py.mkdir(parents=True)
    payload = {"ok": True, "source": "locres", "detail": "ok",
               "locres_path": "dummy.locres",
               "names": {"Bronze001": "Bronze Armor"},
               "codes": ["Bronze001", "Hunter001"]}
    (pipeline_py / "vp_equipment_names.py").write_text(
        "import json\nprint(json.dumps(" + repr(payload) + "))\n")
    fake_pak = tmp_path / "Pal-Windows.pak"
    fake_pak.write_bytes(b"x" * 16)

    result = esd.query_equipment_catalog(str(app_root), str(fake_pak), "ja")
    assert result["ok"] is True
    assert result["codes"] == ["Bronze001", "Hunter001"]
    assert result["names"] == {"Bronze001": "Bronze Armor"}


# ---------------------------------------------------------------------------
# 3. ダイアログ本体の配線(実Toplevel、hidden_root経由)
# ---------------------------------------------------------------------------

def _fake_catalog_result(**overrides):
    base = {"ok": True, "source": "locres", "detail": "ok", "locres_path": "x",
            "codes": ["Bronze001", "Hunter001", "Iron001"],
            "names": {"Bronze001": "Bronze Armor", "Hunter001": "Hunter Suit"}}
    base.update(overrides)
    return base


def _count_checkbuttons(widget):
    import tkinter as tk
    n = 0
    for child in widget.winfo_children():
        if isinstance(child, tk.Checkbutton):
            n += 1
        n += _count_checkbuttons(child)
    return n


def test_dialog_builds_checklist_from_catalog(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(esd, "query_equipment_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = esd.EquipmentSelectContext(
        app_root=str(tmp_path), palworld_pak="C:\\fake.pak", lang="ja")
    dlg = esd.show_equipment_select_dialog(hidden_root, ctx)
    try:
        assert _count_checkbuttons(dlg) == 3
    finally:
        dlg.destroy()


def test_dialog_shows_hint_label_dev165_owner_20260808(hidden_root, monkeypatch, tmp_path):
    """2026-08-08 オーナー指示: 装備限定ダイアログには説明ラベルが存在しな
    かった(頭装備切替ダイアログには既にあった)。同じ流儀(dlg直下にLabel、
    i18n.register()で言語切替に追従)で新設した説明ラベルの存在と、言語切替
    への追従を確認する。"""
    monkeypatch.setattr(esd, "query_equipment_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = esd.EquipmentSelectContext(
        app_root=str(tmp_path), palworld_pak="C:\\fake.pak", lang="ja")
    i18n.set_language("ja")
    dlg = esd.show_equipment_select_dialog(hidden_root, ctx)
    try:
        texts = _all_label_texts(dlg)
        assert any(i18n.S("LabEquipmentFilterHint", "ja") == t for t in texts)
        i18n.apply_language("en")
        try:
            texts_en = _all_label_texts(dlg)
            assert any(i18n.S("LabEquipmentFilterHint", "en") == t for t in texts_en)
        finally:
            i18n.apply_language("ja")
    finally:
        dlg.destroy()


def test_dialog_preselects_previously_saved_codes(hidden_root, monkeypatch, tmp_path):
    esd.save_selected_codes(str(tmp_path), ["Bronze001"])
    monkeypatch.setattr(esd, "query_equipment_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = esd.EquipmentSelectContext(
        app_root=str(tmp_path), palworld_pak="C:\\fake.pak", lang="ja")
    dlg = esd.show_equipment_select_dialog(hidden_root, ctx)
    try:
        # OKを押した時点の保存内容がpre-selectionを含んでいること
        ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    finally:
        pass
    assert esd.load_selected_codes(str(tmp_path)) == ["Bronze001"]


def _all_checkbuttons(widget):
    import tkinter as tk
    out = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Checkbutton):
            out.append(child)
        out.extend(_all_checkbuttons(child))
    return out


def _is_checked(widget, cb):
    """Checkbutton(cb)に紐づくBooleanVarの現在値をwidget経由で読む。"""
    varname = cb.cget("variable")
    return bool(int(widget.getvar(varname)))


# ---------------------------------------------------------------------------
# 3a. ラボ憲章④(2026-08-08 第3弾「装備フィルタのチェック意味論変更」):
#     既定(未カスタマイズ)状態は「全ON」で表示し、既定のままOKを押すと
#     job設定にequipment_filterキーが一切出ない状態(=空リスト)が保存される
#     こと。負の対照として、1つでもOFFにすればキーが出る非既定状態になる
#     ことも併せて固定する(equipment_filter_store.load_selected_codes()の
#     戻り値がpipeline_runner.pyのjob["equipment_filter"]配線の唯一の入力
#     ——空リスト=キー不在、なので、ここでの「空リスト保存」の確認が
#     そのままjob設定不変の証明になる)。
# ---------------------------------------------------------------------------

def test_default_state_shows_all_checkboxes_checked(hidden_root, monkeypatch, tmp_path):
    """未カスタマイズ(初回)状態でダイアログを開くと、全チェックボックスが
    ON(=全装備が有効、既定の見た目どおり)であること。"""
    monkeypatch.setattr(esd, "query_equipment_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = esd.EquipmentSelectContext(
        app_root=str(tmp_path), palworld_pak="C:\\fake.pak", lang="ja")
    dlg = esd.show_equipment_select_dialog(hidden_root, ctx)
    try:
        cbs = _all_checkbuttons(dlg)
        assert len(cbs) == 3
        assert all(_is_checked(dlg, cb) for cb in cbs), "既定状態は全チェックONのはず"
    finally:
        dlg.destroy()


def test_default_ok_without_changes_saves_empty_state_dev165_charter4(
    hidden_root, monkeypatch, tmp_path
):
    """④本体: 既定(全ON)のままOKを押しても、保存される選択状態は空
    (=job["equipment_filter"]キーが出ない既定値)であること。"""
    monkeypatch.setattr(esd, "query_equipment_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = esd.EquipmentSelectContext(
        app_root=str(tmp_path), palworld_pak="C:\\fake.pak", lang="ja")
    dlg = esd.show_equipment_select_dialog(hidden_root, ctx)
    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    assert esd.load_selected_codes(str(tmp_path)) == []
    assert esd.is_active(str(tmp_path)) is False
    assert esd.state_summary(str(tmp_path)) is None


def test_negative_control_unchecking_one_produces_non_default_state(
    hidden_root, monkeypatch, tmp_path
):
    """負の対照: 全ON状態から1つだけOFFにしてOKすると、job設定にキーが
    出る非既定状態(3件中2件が選択済み)が保存されること。"""
    monkeypatch.setattr(esd, "query_equipment_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = esd.EquipmentSelectContext(
        app_root=str(tmp_path), palworld_pak="C:\\fake.pak", lang="ja")
    dlg = esd.show_equipment_select_dialog(hidden_root, ctx)

    cbs = _all_checkbuttons(dlg)
    assert len(cbs) == 3
    cbs[0].invoke()  # 全ONから1つだけOFFにする

    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    saved = esd.load_selected_codes(str(tmp_path))
    assert len(saved) == 2  # 3件中1件除外=2件が絞り込み対象として保存される
    assert esd.is_active(str(tmp_path)) is True


def test_all_off_is_blocked_from_saving(hidden_root, monkeypatch, tmp_path):
    """全OFF(「すべて解除」→OK)は保存されずに弾かれること(ラボ憲章②の
    枠内で簡便な実装=警告して保存不可)。ダイアログはOK後も残ったまま
    (=保存も破棄もしていない=まだ選択をやり直せる)。"""
    monkeypatch.setattr(esd, "query_equipment_catalog",
                         lambda *a, **k: _fake_catalog_result())
    warnings = []
    monkeypatch.setattr(esd.messagebox, "showwarning",
                         lambda *a, **k: warnings.append(a))
    ctx = esd.EquipmentSelectContext(
        app_root=str(tmp_path), palworld_pak="C:\\fake.pak", lang="ja")
    dlg = esd.show_equipment_select_dialog(hidden_root, ctx)
    try:
        clear_btn = _find_button_by_text(dlg, i18n.S("LabEquipmentFilterClearAll"))
        clear_btn.invoke()
        ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()

        assert warnings, "全OFFでOKを押しても警告が出ていない"
        # 何も保存されていない(既定値=空リストのまま、変更前の状態を保つ)
        assert esd.load_selected_codes(str(tmp_path)) == []
        assert dlg.winfo_exists(), "全OFFのOKでダイアログが閉じてしまっている"
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 3b. カタログ取得完全失敗時にOKで保存済み選択が空上書きされるバグの修正
#     (PR #1202本文「既知の既存挙動」)。full_codes(=set(codes))が空だと
#     chosen(空集合、check_varsが1件も無いので常に空)と一致し、旧実装は
#     「全ON=既定」判定に誤ってヒットして save_selected_codes(app_root, [])
#     を呼んでいた。カタログが取れない=判断材料が無い状態でユーザーの
#     既存設定を壊してはならない、という原則の固定。
# ---------------------------------------------------------------------------

def _empty_catalog_result(**overrides):
    base = {"ok": False, "source": "none", "detail": "boom", "codes": [], "names": {}}
    base.update(overrides)
    return base


def test_dialog_ok_with_empty_catalog_preserves_saved_selection_dev1210(
    hidden_root, monkeypatch, tmp_path
):
    """正: カタログ取得が完全失敗(codes=[])した状態でOKを押しても、
    以前保存済みの選択がそのまま残ること(空リストで上書きされない)。"""
    esd.save_selected_codes(str(tmp_path), ["Bronze001", "Hunter001"])
    monkeypatch.setattr(esd, "query_equipment_catalog",
                         lambda *a, **k: _empty_catalog_result())
    ctx = esd.EquipmentSelectContext(
        app_root=str(tmp_path), palworld_pak="C:\\fake.pak", lang="ja")
    dlg = esd.show_equipment_select_dialog(hidden_root, ctx)
    try:
        ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
        # OKでダイアログは閉じる(保存はしないが、開いたままにはしない)
        assert not dlg.winfo_exists()
    finally:
        pass

    assert esd.load_selected_codes(str(tmp_path)) == ["Bronze001", "Hunter001"]


def test_negative_control_ok_with_normal_catalog_still_saves_dev1210(
    hidden_root, monkeypatch, tmp_path
):
    """負の対照: カタログ取得が正常(codes非空)なら、従来どおりOKで
    保存が行われること(=上の修正がカタログ正常時の保存経路を壊していない
    ことの確認)。"""
    esd.save_selected_codes(str(tmp_path), ["Bronze001", "Hunter001", "Iron001"])
    monkeypatch.setattr(esd, "query_equipment_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = esd.EquipmentSelectContext(
        app_root=str(tmp_path), palworld_pak="C:\\fake.pak", lang="ja")
    dlg = esd.show_equipment_select_dialog(hidden_root, ctx)

    cbs = _all_checkbuttons(dlg)
    assert len(cbs) == 3
    cbs[0].invoke()  # 1つOFFにする(3件中1件除外=2件が保存されるはず)

    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    saved = esd.load_selected_codes(str(tmp_path))
    assert len(saved) == 2
    assert saved != ["Bronze001", "Hunter001", "Iron001"]


def test_dialog_shows_catalog_unavailable_notice_when_codes_empty(
    hidden_root, monkeypatch, tmp_path
):
    """codes=[]のとき、カタログ取得失敗を示す通知ラベルが表示されること
    (LabEquipmentFilterFallbackNoticeとは別キー。codes非空・names空の
    フォールバック表示と区別する)。"""
    monkeypatch.setattr(esd, "query_equipment_catalog",
                         lambda *a, **k: _empty_catalog_result())
    ctx = esd.EquipmentSelectContext(
        app_root=str(tmp_path), palworld_pak="C:\\fake.pak", lang="ja")
    dlg = esd.show_equipment_select_dialog(hidden_root, ctx)
    try:
        texts = _all_label_texts(dlg)
        assert any(i18n.S("LabEquipmentFilterCatalogUnavailableNotice") == t for t in texts)
        assert not any(i18n.S("LabEquipmentFilterFallbackNotice") == t for t in texts)
    finally:
        dlg.destroy()


def test_dialog_cancel_does_not_save(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(esd, "query_equipment_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = esd.EquipmentSelectContext(
        app_root=str(tmp_path), palworld_pak="C:\\fake.pak", lang="ja")
    dlg = esd.show_equipment_select_dialog(hidden_root, ctx)

    import tkinter as tk

    def all_checkbuttons(widget):
        out = []
        for child in widget.winfo_children():
            if isinstance(child, tk.Checkbutton):
                out.append(child)
            out.extend(all_checkbuttons(child))
        return out

    all_checkbuttons(dlg)[0].invoke()
    cancel_btn = _find_button_by_text(dlg, i18n.S("BtnCancel"))
    cancel_btn.invoke()

    assert esd.load_selected_codes(str(tmp_path)) == []


def test_dialog_shows_fallback_notice_when_extraction_failed(hidden_root, monkeypatch, tmp_path):
    """抽出は失敗したがカタログ(内部コード)は取れた状態
    (ok=False, names={}, codes非空)で、フォールバック通知ラベルが出ること。"""
    monkeypatch.setattr(
        esd, "query_equipment_catalog",
        lambda *a, **k: _fake_catalog_result(ok=False, names={}))
    ctx = esd.EquipmentSelectContext(
        app_root=str(tmp_path), palworld_pak="C:\\fake.pak", lang="ja")
    dlg = esd.show_equipment_select_dialog(hidden_root, ctx)
    try:
        texts = _all_label_texts(dlg)
        assert any(i18n.S("LabEquipmentFilterFallbackNotice") == t for t in texts)
        # フォールバック時はコード自体がそのままチェックリストの表示名になる
        assert _count_checkbuttons(dlg) == 3
    finally:
        dlg.destroy()


def test_dialog_follows_language_switch(hidden_root, monkeypatch, tmp_path):
    """2026-08-08 第3弾「言語切替のobserver化」: 開いている装備限定ダイアログの
    タイトル・ボタン文言が i18n.apply_language() の呼び出しに追従すること。"""
    i18n.set_language("ja")
    monkeypatch.setattr(esd, "query_equipment_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = esd.EquipmentSelectContext(
        app_root=str(tmp_path), palworld_pak="C:\\fake.pak", lang="ja")
    dlg = esd.show_equipment_select_dialog(hidden_root, ctx)
    try:
        assert dlg.title() == i18n.S("LabEquipmentFilterDialogTitle", "ja")
        i18n.apply_language("en")
        try:
            assert dlg.title() == i18n.S("LabEquipmentFilterDialogTitle", "en")
            assert _find_button_by_text(dlg, i18n.S("BtnOk", "en")) is not None
            assert _find_button_by_text(
                dlg, i18n.S("LabEquipmentFilterSelectAll", "en")) is not None
        finally:
            i18n.apply_language("ja")
    finally:
        dlg.destroy()


def test_checkbox_names_follow_language_switch_dev165_datatable(
    hidden_root, monkeypatch, tmp_path
):
    """2026-08-08 第4弾(DataTable直接解決): 開いている装備限定ダイアログの
    「チェックボックスの表示名」自体(第3弾で対応済みのタイトル・ボタン文言とは
    別)も、メイン窓側の言語切替(i18n.apply_language())に追従して更新される
    こと。query_equipment_catalog()へ渡されるlang引数ごとに異なる表示名を
    返すfakeで、ja→enの切替前後を確認する。"""
    def _fake_by_lang(_app_root, _pak, lang, **_k):
        names_by_lang = {
            "ja": {"Bronze001": "銅の鎧", "Hunter001": "毛皮の服"},
            "en": {"Bronze001": "Bronze Armor", "Hunter001": "Hunter Suit"},
        }
        return {"ok": True, "source": "datatable", "detail": "ok", "locres_path": None,
                "codes": ["Bronze001", "Hunter001", "Iron001"],
                "names": names_by_lang.get(lang, {})}

    monkeypatch.setattr(esd, "query_equipment_catalog", _fake_by_lang)
    i18n.set_language("ja")
    ctx = esd.EquipmentSelectContext(
        app_root=str(tmp_path), palworld_pak="C:\\fake.pak", lang="ja")
    dlg = esd.show_equipment_select_dialog(hidden_root, ctx)
    try:
        cbs_before = {cb.cget("text") for cb in _all_checkbuttons(dlg)}
        assert cbs_before == {"銅の鎧", "毛皮の服", "Iron001"}

        i18n.apply_language("en")
        try:
            cbs_after = {cb.cget("text") for cb in _all_checkbuttons(dlg)}
            assert cbs_after == {"Bronze Armor", "Hunter Suit", "Iron001"}
        finally:
            i18n.apply_language("ja")
    finally:
        dlg.destroy()


def _find_canvas(widget):
    import tkinter as tk
    for child in widget.winfo_children():
        if isinstance(child, tk.Canvas):
            return child
        found = _find_canvas(child)
        if found is not None:
            return found
    return None


def test_mousewheel_scrolls_canvas_when_over_canvas(hidden_root, monkeypatch, tmp_path):
    """dev#165第2弾補修: canvas自体の上でホイールを回すとyview_scroll()が
    正しい方向・単位で呼ばれること(delta負=下方向スクロール=+1 unit,
    delta正=上方向スクロール=-1 unit)。"""
    monkeypatch.setattr(esd, "query_equipment_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = esd.EquipmentSelectContext(
        app_root=str(tmp_path), palworld_pak="C:\\fake.pak", lang="ja")
    dlg = esd.show_equipment_select_dialog(hidden_root, ctx)
    try:
        canvas = _find_canvas(dlg)
        assert canvas is not None
        dlg.update_idletasks()
        dlg.update()
        calls = []
        monkeypatch.setattr(canvas, "yview_scroll",
                             lambda n, what: calls.append((n, what)))

        canvas.event_generate("<MouseWheel>", delta=-120)
        dlg.update()
        assert calls[-1] == (1, "units")

        calls.clear()
        canvas.event_generate("<MouseWheel>", delta=120)
        dlg.update()
        assert calls[-1] == (-1, "units")
    finally:
        dlg.destroy()


def test_mousewheel_scrolls_canvas_when_over_checkbutton(hidden_root, monkeypatch, tmp_path):
    """dev#165第2弾補修の本題: チェックボタン(canvas上に重なる別ウィジェット)
    にカーソルがある状態でホイールを回してもスクロールが効くこと
    (canvas単体へのbindだけでは効かない、という負の対照の裏返し)。"""
    monkeypatch.setattr(esd, "query_equipment_catalog",
                         lambda *a, **k: _fake_catalog_result())
    ctx = esd.EquipmentSelectContext(
        app_root=str(tmp_path), palworld_pak="C:\\fake.pak", lang="ja")
    dlg = esd.show_equipment_select_dialog(hidden_root, ctx)
    try:
        canvas = _find_canvas(dlg)
        import tkinter as tk

        def all_checkbuttons(widget):
            out = []
            for child in widget.winfo_children():
                if isinstance(child, tk.Checkbutton):
                    out.append(child)
                out.extend(all_checkbuttons(child))
            return out

        cbs = all_checkbuttons(dlg)
        assert cbs
        dlg.update_idletasks()
        dlg.update()
        calls = []
        monkeypatch.setattr(canvas, "yview_scroll",
                             lambda n, what: calls.append((n, what)))

        cbs[0].event_generate("<MouseWheel>", delta=-120)
        dlg.update()
        assert calls, "wheel over a checkbutton should still scroll the list"
        assert calls[-1] == (1, "units")
    finally:
        dlg.destroy()


def test_negative_control_no_mousewheel_binding_means_no_scroll_call(hidden_root):
    """負の対照: もし<MouseWheel>のbindが無ければ、event_generateしても
    yview_scrollは一切呼ばれない(=このテストの検出力そのものの確認)。
    実装を直接検査するのではなく、素のCanvas(bind無し、show_equipment_
    select_dialog()を経由しない)で同じ手順を踏んでも呼ばれないことを示す。
    tk.Tk()は新規生成しない(dev#672契約、共有hidden_rootを使う)。"""
    import tkinter as tk
    c = tk.Canvas(hidden_root)
    c.pack()
    calls = []
    c.yview_scroll = lambda n, what: calls.append((n, what))  # bind未設定
    c.event_generate("<MouseWheel>", delta=-120)
    hidden_root.update()
    c.destroy()
    assert calls == []


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
