# test_shapekey_select_dialog_dev1168.py -- dev#1168(シェイプキー)ラボ機能。
#
# app_py\ui\shapekey_select_dialog.py の単体試験。実tk.Tk()は作らない
# (conftest.pyの共有hidden_root、既存慣例踏襲)。
#
# 柱:
#   1. resolve_catalog(): 拡張子で分岐(.vrm/.prefab/非対応)、prefabは
#      pipeline_runner.resolve_unity_export_out_dir()経由でサイドカーへ到達
#   2. ダイアログ本体: メッシュ一覧構築・検索フィルタ・スライダーでの値変更・
#      OK保存/Cancel非保存
#   3. ラボ憲章④: 既定(スライダーを一切動かさずOK)ではjob["shape_keys"]の
#      元になるload_config()が空を返すこと(=キー不在と等価)
#   4. LAB_REGISTRY_DESCRIPTORの形
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import pipeline_runner  # noqa: E402
from ui import shapekey_select_dialog as skd  # noqa: E402


# ---------------------------------------------------------------------------
# 1. resolve_catalog(): 拡張子による分岐
# ---------------------------------------------------------------------------

def test_resolve_catalog_no_avatar_selected():
    result = skd.resolve_catalog("C:\\app", "C:\\work", "")
    assert result["ok"] is False
    assert result["meshes"] == {}


def test_resolve_catalog_unsupported_extension(tmp_path):
    result = skd.resolve_catalog(str(tmp_path), str(tmp_path), "C:\\avatar.fbx")
    assert result["ok"] is False
    assert "unsupported" in result["detail"]


def test_resolve_catalog_vrm_delegates_to_shapekey_catalog(monkeypatch, tmp_path):
    calls = []

    def _fake_catalog_from_vrm(path):
        calls.append(path)
        return {"ok": True, "detail": "ok", "meshes": {"Body": ["smile"]}}

    monkeypatch.setattr(skd.shapekey_catalog, "catalog_from_vrm", _fake_catalog_from_vrm)
    vrm_path = str(tmp_path / "avatar.vrm")
    result = skd.resolve_catalog(str(tmp_path), str(tmp_path), vrm_path)
    assert calls == [vrm_path]
    assert result["meshes"] == {"Body": ["smile"]}


def test_resolve_catalog_prefab_reads_sidecar_next_to_export(monkeypatch, tmp_path):
    """prefab経路: resolve_unity_export_out_dir()が指すout_dir配下の
    shape_keys.jsonを読みに行くこと(lu_export.pyのmaterial_map.json等と
    同じ置き場所)。"""
    prefab_path = str(tmp_path / "avatar.prefab")
    work_root = str(tmp_path / "work")
    out_dir = pipeline_runner.resolve_unity_export_out_dir(work_root, prefab_path)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "shape_keys.json"), "w", encoding="utf-8") as f:
        json.dump({"format": "divetopalworld-shapekeys-1", "fbx": "a.fbx",
                    "meshes": {"Body": ["smile"]}}, f)

    result = skd.resolve_catalog(str(tmp_path), work_root, prefab_path)
    assert result["ok"] is True
    assert result["meshes"] == {"Body": ["smile"]}


def test_resolve_catalog_prefab_missing_sidecar_falls_back(tmp_path):
    """負の対照: サイドカー(旧輸出物、本WPより前にエクスポート済み)が
    無い場合は例外にならずok=Falseへ落ちる。"""
    prefab_path = str(tmp_path / "avatar.prefab")
    work_root = str(tmp_path / "work")
    result = skd.resolve_catalog(str(tmp_path), work_root, prefab_path)
    assert result["ok"] is False
    assert result["meshes"] == {}


# ---------------------------------------------------------------------------
# 2. ダイアログ本体(実Toplevel、hidden_root経由)
# ---------------------------------------------------------------------------

def _fake_catalog(**overrides):
    base = {"ok": True, "detail": "ok",
            "meshes": {"Body": ["smile", "blink", "wink"], "Hair": ["wave"]}}
    base.update(overrides)
    return base


def _find_button_by_text(widget, text):
    import tkinter as tk
    for child in widget.winfo_children():
        if isinstance(child, tk.Button) and child.cget("text") == text:
            return child
        found = _find_button_by_text(child, text)
        if found is not None:
            return found
    return None


def _all_scales(widget):
    import tkinter as tk
    out = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Scale):
            out.append(child)
        out.extend(_all_scales(child))
    return out


def _all_label_texts(widget):
    import tkinter as tk
    out = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            out.append(child.cget("text"))
        out.extend(_all_label_texts(child))
    return out


def _find_canvas(widget):
    import tkinter as tk
    for child in widget.winfo_children():
        if isinstance(child, tk.Canvas):
            return child
        found = _find_canvas(child)
        if found is not None:
            return found
    return None


def test_dialog_builds_mesh_list_and_key_sliders(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(skd, "resolve_catalog", lambda *a, **k: _fake_catalog())
    ctx = skd.ShapeKeySelectContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\a.vrm")
    dlg = skd.show_shapekey_select_dialog(hidden_root, ctx)
    try:
        assert list(dlg.nametowidget(".").winfo_children()) is not None  # smoke
        # 既定選択(Body)ぶんのスライダーが3枚(smile/blink/wink)描画される
        assert len(_all_scales(dlg)) == 3
    finally:
        dlg.destroy()


def test_dialog_default_ok_saves_nothing_dev1168_charter4(hidden_root, monkeypatch, tmp_path):
    """④本体: スライダーを一切動かさずOKを押しても、保存される設定は空
    (=job["shape_keys"]キーが出ない既定値)であること。"""
    monkeypatch.setattr(skd, "resolve_catalog", lambda *a, **k: _fake_catalog())
    ctx = skd.ShapeKeySelectContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\a.vrm")
    dlg = skd.show_shapekey_select_dialog(hidden_root, ctx)
    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    assert skd.load_config(str(tmp_path), "C:\\a.vrm") == {}
    assert skd.is_active(str(tmp_path), "C:\\a.vrm") is False


def test_negative_control_moving_a_slider_produces_non_default_state(
    hidden_root, monkeypatch, tmp_path
):
    """負の対照: 1つでもスライダーを動かしてOKすると、job設定にキーが出る
    非既定状態が保存されること。"""
    monkeypatch.setattr(skd, "resolve_catalog", lambda *a, **k: _fake_catalog())
    ctx = skd.ShapeKeySelectContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\a.vrm")
    dlg = skd.show_shapekey_select_dialog(hidden_root, ctx)

    scales = _all_scales(dlg)
    assert len(scales) == 3
    scales[0].set(0.8)

    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    saved = skd.load_config(str(tmp_path), "C:\\a.vrm")
    assert saved, "スライダーを動かしたのに何も保存されていない"
    assert skd.is_active(str(tmp_path), "C:\\a.vrm") is True


def test_dialog_cancel_does_not_save(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(skd, "resolve_catalog", lambda *a, **k: _fake_catalog())
    ctx = skd.ShapeKeySelectContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\a.vrm")
    dlg = skd.show_shapekey_select_dialog(hidden_root, ctx)

    scales = _all_scales(dlg)
    scales[0].set(0.8)
    cancel_btn = _find_button_by_text(dlg, i18n.S("BtnCancel"))
    cancel_btn.invoke()

    assert skd.load_config(str(tmp_path), "C:\\a.vrm") == {}


def test_dialog_search_filters_but_keeps_changed_keys_visible(hidden_root, monkeypatch, tmp_path):
    """検索絞り込み+「変更済みキーは常時表示」の確認: smileを非0にしてから
    無関係な検索語を入れても、smileの行だけは表示され続ける。"""
    monkeypatch.setattr(skd, "resolve_catalog", lambda *a, **k: _fake_catalog())
    ctx = skd.ShapeKeySelectContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\a.vrm")
    dlg = skd.show_shapekey_select_dialog(hidden_root, ctx)
    try:
        dlg.update_idletasks()
        # smileへ値を入れる(Bodyメッシュの1枚目 = smile、_fake_catalog()の並び順)
        scales = _all_scales(dlg)
        assert len(scales) == 3
        scales[0].set(0.6)

        # マッチしない検索語を入れる -> 通常は全部隠れるはずだが、smileは
        # 変更済みなので残る
        search_entries = [w for w in dlg.winfo_children()]
        import tkinter as tk

        def _find_entry(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Entry):
                    return child
                found = _find_entry(child)
                if found is not None:
                    return found
            return None

        entry = _find_entry(dlg)
        entry.delete(0, tk.END)
        entry.insert(0, "zzz_no_such_key")
        dlg.update()

        remaining = _all_scales(dlg)
        assert len(remaining) == 1, "検索に一致せず値も既定のキーが残っている"
    finally:
        dlg.destroy()


def test_dialog_shows_hint(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(skd, "resolve_catalog", lambda *a, **k: _fake_catalog())
    ctx = skd.ShapeKeySelectContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\a.vrm")
    dlg = skd.show_shapekey_select_dialog(hidden_root, ctx)
    try:
        texts = _all_label_texts(dlg)
        assert any(i18n.S("LabShapeKeysHint") == t for t in texts)
    finally:
        dlg.destroy()


def test_canvas_window_width_tracks_canvas_configure_dev1273(hidden_root, monkeypatch, tmp_path):
    """dev#1275実機報告(オーナー、v2.7.0 HumanTest): シェイプキーのスライダーで
    値を0.5より大きくしようとすると見切れる。

    原因: canvas内に埋め込んだスクロール用フレーム(inner)の幅がcanvas自身の
    描画幅に束縛されていなかった。ラベル(width=28文字)+スライダー
    (length=280px)の合計自然幅がcanvasの可視幅(mesh_frame/スクロールバー分を
    差し引いた残り)を上回っており、スライダーのトラック右側(=値が大きい側、
    実測ではおよそ0.5超に相当)がcanvasの描画域外にはみ出して操作・視認が
    できなくなっていた。

    修正: canvas <Configure> でcreate_window済みのinner windowの幅を canvas
    自身の実測幅へ追従させた(shapekey_select_dialog.py
    _on_canvas_configure)。スライダーはfill="x", expand=Trueで伸縮可能なため、
    innerの幅がcanvas幅に収まればスライダーもその残り幅に収まり、右端が
    canvasの可視幅を超えなくなる。

    実際のピクセル幅(winfo_width等)はhidden_root(実画面に一切表示しない
    withdraw済みTk)配下では確定しない(このプロジェクトの「実tk窓を開かない」
    契約どおり、ウィンドウが画面へマップされないため)。そのため、合成
    <Configure>イベント(event_generate)でcanvasの実測幅ぶんの通知を模擬し、
    埋め込みwindow item の -width オプションがその値へ追従することを直接
    検証する(itemconfig経由でTkが実際に子windowをその幅へ収める仕組み)。

    負の対照: 本修正を当てる前のコード(canvas.bind("<Configure>", ...)が
    無い状態)で同じ手順を実行すると、item widthは初期値"0"のまま変化しない
    ことを実装時に手元で確認済み(git stash差し戻しでの実測、完了報告に記載)。
    """
    monkeypatch.setattr(skd, "resolve_catalog", lambda *a, **k: _fake_catalog())
    ctx = skd.ShapeKeySelectContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\a.vrm")
    dlg = skd.show_shapekey_select_dialog(hidden_root, ctx)
    try:
        dlg.update_idletasks()
        canvas = _find_canvas(dlg)
        assert canvas is not None, "canvas widget not found in dialog tree"

        items = canvas.find_all()
        assert len(items) == 1, "expected exactly one embedded window item on the canvas"
        window_item = items[0]
        assert canvas.type(window_item) == "window"

        before = canvas.itemcget(window_item, "width")
        assert before in ("0", ""), f"unexpected initial item width: {before!r}"

        canvas.event_generate("<Configure>", width=300, height=200)
        dlg.update()
        after = canvas.itemcget(window_item, "width")
        assert after == "300", (
            f"embedded scroll frame should track the canvas's own width via "
            f"<Configure> (before={before!r}, after={after!r})"
        )
    finally:
        dlg.destroy()


def test_dialog_shows_catalog_unavailable_notice_when_empty(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(
        skd, "resolve_catalog",
        lambda *a, **k: {"ok": False, "detail": "boom", "meshes": {}})
    ctx = skd.ShapeKeySelectContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\a.vrm")
    dlg = skd.show_shapekey_select_dialog(hidden_root, ctx)
    try:
        texts = _all_label_texts(dlg)
        assert any(i18n.S("LabShapeKeysCatalogUnavailableNotice") == t for t in texts)
        assert not _all_scales(dlg)
    finally:
        dlg.destroy()


def test_dialog_preloads_previously_saved_values(hidden_root, monkeypatch, tmp_path):
    skd.save_config(str(tmp_path), "C:\\a.vrm", {"Body": {"blink": 0.9}})
    monkeypatch.setattr(skd, "resolve_catalog", lambda *a, **k: _fake_catalog())
    ctx = skd.ShapeKeySelectContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\a.vrm")
    dlg = skd.show_shapekey_select_dialog(hidden_root, ctx)
    try:
        # OKだけ押す(変更しない) -> 元の値がそのまま保存され続けること
        ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()
    finally:
        pass
    assert skd.load_config(str(tmp_path), "C:\\a.vrm") == {"Body": {"blink": 0.9}}


# ---------------------------------------------------------------------------
# 3b. dev#1277: 「プレビュー更新」ボタン(保存はするがダイアログを閉じず、
#    trigger_previewコールバックを起動する)
# ---------------------------------------------------------------------------

def test_preview_button_saves_and_triggers_callback_without_closing(
    hidden_root, monkeypatch, tmp_path
):
    monkeypatch.setattr(skd, "resolve_catalog", lambda *a, **k: _fake_catalog())
    calls = []
    ctx = skd.ShapeKeySelectContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\a.vrm",
        trigger_preview=lambda: calls.append("preview"))
    dlg = skd.show_shapekey_select_dialog(hidden_root, ctx)
    try:
        scales = _all_scales(dlg)
        assert len(scales) == 3
        scales[0].set(0.7)

        preview_btn = _find_button_by_text(dlg, i18n.S("BtnPreviewUpdate"))
        assert preview_btn is not None, "プレビュー更新ボタンが見つからない"
        preview_btn.invoke()

        # 保存された(OKと同じ保存経路)
        saved = skd.load_config(str(tmp_path), "C:\\a.vrm")
        assert saved, "プレビュー更新でスライダー値が保存されていない"
        # trigger_previewが1回だけ呼ばれた
        assert calls == ["preview"]
        # ダイアログは閉じていない(OKと違う点)
        assert dlg.winfo_exists(), "プレビュー更新でダイアログが閉じてしまっている"
    finally:
        dlg.destroy()


def test_preview_button_is_safe_when_trigger_preview_is_none(
    hidden_root, monkeypatch, tmp_path
):
    """負の対照: trigger_preview未設定(既定None)でも例外を投げずに保存だけ
    行われること(main window抜きの単体試験・旧経路との後方互換)。"""
    monkeypatch.setattr(skd, "resolve_catalog", lambda *a, **k: _fake_catalog())
    ctx = skd.ShapeKeySelectContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\a.vrm")
    assert ctx.trigger_preview is None
    dlg = skd.show_shapekey_select_dialog(hidden_root, ctx)
    try:
        scales = _all_scales(dlg)
        scales[0].set(0.4)
        preview_btn = _find_button_by_text(dlg, i18n.S("BtnPreviewUpdate"))
        preview_btn.invoke()  # 例外が出ないことそのものが検証対象

        saved = skd.load_config(str(tmp_path), "C:\\a.vrm")
        assert saved
        assert dlg.winfo_exists()
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 4. LAB_REGISTRY_DESCRIPTOR
# ---------------------------------------------------------------------------

def test_registry_descriptor_shape():
    d = skd.LAB_REGISTRY_DESCRIPTOR
    assert d["id"] == "shape_keys"
    assert isinstance(d["name_key"], str)
    for lang in i18n.LANGS:
        assert i18n.S(d["name_key"], lang) and not i18n.S(d["name_key"], lang).startswith("??")
    assert callable(d["state_summary"])
    assert callable(d["open_dialog"])
    assert callable(d["reset"])


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
