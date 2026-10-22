# test_drop_bones_dialog_dev1277.py -- dev#1277(ボーンでメッシュ削除の
# 選択式化)ラボ機能。
#
# app_py\ui\drop_bones_dialog.py の単体テスト。柱:
#   1. query_bone_catalog(): VRM/prefab/未対応拡張子/ファイル不在のあらゆる
#      経路で例外を投げず、構造化結果(ok/source/detail/bones)へ落ちること
#   2. ダイアログ本体(実Toplevel、hidden_root経由)の配線: チェックリスト
#      構築・OK/Cancelの保存/非保存・フォールバック(手入力)モード
#   3. ラボ憲章④(既定=全チェックOFF=削除リスト空、mesh_delete等とは
#      チェックの向きが逆)+負の対照(1つ入れると job設定に届く非既定状態)
#   4. 「プレビュー更新」ボタン(WP1のtrigger_preview配線パターンと同型)
#
# 実tk.Tk()は作らない(conftest.pyの共有hidden_root、既存慣例踏襲)。
from __future__ import annotations

import json
import os
import struct
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)
_REPO_ROOT = os.path.dirname(_APP_PY_DIR)

import i18n  # noqa: E402
from ui import drop_bones_dialog as dbd  # noqa: E402

VRM_SAMPLE_DIR = os.path.join(_REPO_ROOT, "test", "vrm")


# ---------------------------------------------------------------------------
# 1. query_bone_catalog(): 経路別ディスパッチ
# ---------------------------------------------------------------------------

def test_catalog_query_no_avatar_falls_back(tmp_path):
    result = dbd.query_bone_catalog(str(tmp_path), str(tmp_path), "")
    assert result["ok"] is False
    assert result["bones"] == []


def test_catalog_query_missing_file_falls_back(tmp_path):
    result = dbd.query_bone_catalog(
        str(tmp_path), str(tmp_path), str(tmp_path / "does_not_exist.vrm"))
    assert result["ok"] is False


def test_catalog_query_unsupported_extension_falls_back(tmp_path):
    fbx_path = tmp_path / "model.fbx"
    fbx_path.write_bytes(b"dummy")
    result = dbd.query_bone_catalog(str(tmp_path), str(tmp_path), str(fbx_path))
    assert result["ok"] is False
    assert result["source"] == "none"


def test_catalog_query_corrupt_vrm_falls_back(tmp_path):
    fake = tmp_path / "corrupt.vrm"
    fake.write_bytes(b"not a real glb file at all, just some padding bytes")
    result = dbd.query_bone_catalog(str(tmp_path), str(tmp_path), str(fake))
    assert result["ok"] is False
    assert result["source"] == "vrm"


def test_catalog_query_real_vrm0_sample():
    path = os.path.join(VRM_SAMPLE_DIR, "AliciaSolid_vrm-0.51.vrm")
    if not os.path.exists(path):
        import pytest
        pytest.skip(f"sample VRM not found: {path}")
    result = dbd.query_bone_catalog(str(VRM_SAMPLE_DIR), str(VRM_SAMPLE_DIR), path)
    assert result["ok"] is True
    assert result["source"] == "vrm"
    assert "Hips" in result["bones"]


def test_catalog_query_prefab_without_export_falls_back(tmp_path):
    import pipeline_runner
    fake_prefab = tmp_path / "avatar.prefab"
    fake_prefab.write_text("dummy", encoding="utf-8")
    work_root = tmp_path / "work"
    result = dbd.query_bone_catalog(str(tmp_path), str(work_root), str(fake_prefab))
    assert result["ok"] is False
    assert result["source"] == "prefab"
    out_dir = pipeline_runner.resolve_unity_export_out_dir(str(work_root), str(fake_prefab))
    assert out_dir  # 解決自体は失敗しない(ファイルが無いだけ)


def test_catalog_query_prefab_reads_bones_sidecar(tmp_path):
    import pipeline_runner
    fake_prefab = tmp_path / "avatar.prefab"
    fake_prefab.write_text("dummy", encoding="utf-8")
    work_root = tmp_path / "work"
    out_dir = pipeline_runner.resolve_unity_export_out_dir(str(work_root), str(fake_prefab))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "bones.json"), "w", encoding="utf-8") as f:
        json.dump({"format": "divetopalworld-bones-1", "fbx": "a.fbx",
                    "bones": ["Hips", "Spine", "Head"]}, f)

    result = dbd.query_bone_catalog(str(tmp_path), str(work_root), str(fake_prefab))
    assert result["ok"] is True
    assert result["source"] == "prefab"
    assert result["bones"] == ["Hips", "Spine", "Head"]


def test_catalog_query_prefab_corrupt_bones_sidecar_falls_back(tmp_path):
    import pipeline_runner
    fake_prefab = tmp_path / "avatar.prefab"
    fake_prefab.write_text("dummy", encoding="utf-8")
    work_root = tmp_path / "work"
    out_dir = pipeline_runner.resolve_unity_export_out_dir(str(work_root), str(fake_prefab))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "bones.json"), "w", encoding="utf-8") as f:
        f.write("{ not valid json")

    result = dbd.query_bone_catalog(str(tmp_path), str(work_root), str(fake_prefab))
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 2. ダイアログ本体(実Toplevel、hidden_root経由)
# ---------------------------------------------------------------------------

def _count_checkbuttons(widget):
    import tkinter as tk
    n = 0
    for child in widget.winfo_children():
        if isinstance(child, tk.Checkbutton):
            n += 1
        n += _count_checkbuttons(child)
    return n


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


def _find_label_by_text(widget, text):
    import tkinter as tk
    for child in widget.winfo_children():
        if isinstance(child, tk.Label) and child.cget("text") == text:
            return child
        found = _find_label_by_text(child, text)
        if found is not None:
            return found
    return None


def _fake_catalog_result(**overrides):
    base = {"ok": True, "source": "vrm", "detail": "ok",
            "bones": ["Hips", "Tail1", "Tail2"]}
    base.update(overrides)
    return base


class _FakeBackingStore:
    """main_window.pyのdropBonesBox Entryの代わり(get/set呼び出し回数の
    検証も兼ねる、実tkinterウィジェットに依存しない単体試験用フェイク)。"""

    def __init__(self, initial: str = ""):
        self.text = initial
        self.changed_calls = 0

    def get(self) -> str:
        return self.text

    def set(self, text: str) -> None:
        self.text = text

    def on_changed(self) -> None:
        self.changed_calls += 1


def _make_ctx(store: _FakeBackingStore, tmp_path, avatar_path="C:\\fake.vrm",
              trigger_preview=None):
    return dbd.DropBonesContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path=avatar_path,
        get_current_text=store.get, set_current_text=store.set,
        on_changed=store.on_changed, trigger_preview=trigger_preview)


def test_dialog_builds_checklist_from_catalog(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(dbd, "query_bone_catalog", lambda *a, **k: _fake_catalog_result())
    store = _FakeBackingStore()
    dlg = dbd.show_drop_bones_dialog(hidden_root, _make_ctx(store, tmp_path))
    try:
        assert _count_checkbuttons(dlg) == 3
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 3. ラボ憲章④: 既定=全チェックOFF(mesh_delete等と向きが逆)。既定のまま
#    OKで保存されるテキストは空。負の対照: 1つ入れると非既定になる。
# ---------------------------------------------------------------------------

def test_default_state_shows_all_checkboxes_unchecked(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(dbd, "query_bone_catalog", lambda *a, **k: _fake_catalog_result())
    store = _FakeBackingStore()
    dlg = dbd.show_drop_bones_dialog(hidden_root, _make_ctx(store, tmp_path))
    try:
        cbs = _all_checkbuttons(dlg)
        assert len(cbs) == 3
        assert not any(_is_checked(dlg, cb) for cb in cbs), (
            "既定状態は全チェックOFFのはず(drop_bonesは'チェック=削除'のため"
            "mesh_delete等と逆)")
    finally:
        dlg.destroy()


def test_default_ok_without_changes_saves_empty_text_dev1277_charter4(
    hidden_root, monkeypatch, tmp_path
):
    monkeypatch.setattr(dbd, "query_bone_catalog", lambda *a, **k: _fake_catalog_result())
    store = _FakeBackingStore()
    dlg = dbd.show_drop_bones_dialog(hidden_root, _make_ctx(store, tmp_path))
    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    assert store.text == ""
    assert store.changed_calls == 1


def test_negative_control_checking_one_produces_non_default_state_and_reaches_job(
    hidden_root, monkeypatch, tmp_path
):
    monkeypatch.setattr(dbd, "query_bone_catalog", lambda *a, **k: _fake_catalog_result())
    store = _FakeBackingStore()
    avatar_path = os.path.join(str(tmp_path), "dummy.vrm")
    dlg = dbd.show_drop_bones_dialog(hidden_root, _make_ctx(store, tmp_path, avatar_path))

    cbs = _all_checkbuttons(dlg)
    assert len(cbs) == 3
    cbs[0].invoke()  # 全OFFから1つだけON(=削除指定)にする

    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    assert store.text != ""
    dropped = [n for n in store.text.split(",") if n]
    assert len(dropped) == 1

    # job設定への到達確認(pipeline_runner.write_job()経由、既存の
    # drop_bones_text.split(",")配線は変えていない)。
    import pipeline_runner
    work_root = os.path.join(str(tmp_path), "work")
    job_json_path = pipeline_runner.write_job(
        str(tmp_path), work_root, avatar_path, drop_bones_text=store.text)
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job.get("drop_bones") == dropped


def test_negative_control_default_state_produces_no_job_key(
    hidden_root, monkeypatch, tmp_path
):
    monkeypatch.setattr(dbd, "query_bone_catalog", lambda *a, **k: _fake_catalog_result())
    store = _FakeBackingStore()
    dlg = dbd.show_drop_bones_dialog(hidden_root, _make_ctx(store, tmp_path))
    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    import pipeline_runner
    work_root = os.path.join(str(tmp_path), "work")
    job_json_path = pipeline_runner.write_job(
        str(tmp_path), work_root, os.path.join(str(tmp_path), "dummy.vrm"),
        drop_bones_text=store.text)
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job.get("drop_bones") == []


def test_all_selected_is_blocked_from_saving(hidden_root, monkeypatch, tmp_path):
    """全ON(=全ボーン削除)は保存されずに弾かれること(mesh_delete_dialog.py
    の「全OFF警告」と対称の安全弁)。ダイアログはOK後も残ったまま。"""
    monkeypatch.setattr(dbd, "query_bone_catalog", lambda *a, **k: _fake_catalog_result())
    warnings = []
    monkeypatch.setattr(dbd.messagebox, "showwarning",
                         lambda *a, **k: warnings.append(a))
    store = _FakeBackingStore()
    dlg = dbd.show_drop_bones_dialog(hidden_root, _make_ctx(store, tmp_path))
    try:
        select_all_btn = _find_button_by_text(dlg, i18n.S("LabEquipmentFilterSelectAll"))
        select_all_btn.invoke()
        ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()

        assert warnings, "全ONでOKを押しても警告が出ていない"
        assert store.text == "", "全ON警告が出たのに保存されている"
        assert dlg.winfo_exists(), "全ONのOKでダイアログが閉じてしまっている"
    finally:
        dlg.destroy()


def test_dialog_cancel_does_not_save(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(dbd, "query_bone_catalog", lambda *a, **k: _fake_catalog_result())
    store = _FakeBackingStore()
    dlg = dbd.show_drop_bones_dialog(hidden_root, _make_ctx(store, tmp_path))

    cbs = _all_checkbuttons(dlg)
    cbs[0].invoke()
    cancel_btn = _find_button_by_text(dlg, i18n.S("BtnCancel"))
    cancel_btn.invoke()

    assert store.text == ""


# ---------------------------------------------------------------------------
# 4. 「プレビュー更新」ボタン(WP1のtrigger_preview配線パターンと同型)
# ---------------------------------------------------------------------------

def test_preview_button_saves_and_triggers_callback_without_closing(
    hidden_root, monkeypatch, tmp_path
):
    monkeypatch.setattr(dbd, "query_bone_catalog", lambda *a, **k: _fake_catalog_result())
    calls = []
    store = _FakeBackingStore()
    dlg = dbd.show_drop_bones_dialog(
        hidden_root, _make_ctx(store, tmp_path, trigger_preview=lambda: calls.append("preview")))
    try:
        cbs = _all_checkbuttons(dlg)
        cbs[0].invoke()  # 1件削除指定にする

        preview_btn = _find_button_by_text(dlg, i18n.S("BtnPreviewUpdate"))
        assert preview_btn is not None, "プレビュー更新ボタンが見つからない"
        preview_btn.invoke()

        assert store.text != ""
        assert calls == ["preview"]
        assert dlg.winfo_exists(), "プレビュー更新でダイアログが閉じてしまっている"
    finally:
        dlg.destroy()


def test_preview_button_is_safe_when_trigger_preview_is_none(
    hidden_root, monkeypatch, tmp_path
):
    """負の対照: trigger_preview未設定(既定None)でも例外を投げずに保存だけ
    行われること。"""
    monkeypatch.setattr(dbd, "query_bone_catalog", lambda *a, **k: _fake_catalog_result())
    store = _FakeBackingStore()
    ctx = _make_ctx(store, tmp_path)
    assert ctx.trigger_preview is None
    dlg = dbd.show_drop_bones_dialog(hidden_root, ctx)
    try:
        cbs = _all_checkbuttons(dlg)
        cbs[0].invoke()
        preview_btn = _find_button_by_text(dlg, i18n.S("BtnPreviewUpdate"))
        preview_btn.invoke()  # 例外が出ないことそのものが検証対象

        assert store.text != ""
        assert dlg.winfo_exists()
    finally:
        dlg.destroy()


def test_preview_button_all_selected_is_blocked_like_ok(hidden_root, monkeypatch, tmp_path):
    """負の対照: 全ONでプレビュー更新を押しても、on_okと同じ警告で弾かれ
    保存されないこと(骨格全損防止の枠はプレビュー経路でも同じ)。"""
    monkeypatch.setattr(dbd, "query_bone_catalog", lambda *a, **k: _fake_catalog_result())
    warnings = []
    monkeypatch.setattr(dbd.messagebox, "showwarning",
                         lambda *a, **k: warnings.append(a))
    calls = []
    store = _FakeBackingStore()
    dlg = dbd.show_drop_bones_dialog(
        hidden_root, _make_ctx(store, tmp_path, trigger_preview=lambda: calls.append("preview")))
    try:
        select_all_btn = _find_button_by_text(dlg, i18n.S("LabEquipmentFilterSelectAll"))
        select_all_btn.invoke()
        preview_btn = _find_button_by_text(dlg, i18n.S("BtnPreviewUpdate"))
        preview_btn.invoke()

        assert warnings
        assert store.text == ""
        assert calls == [], "全ON警告が出たのにtrigger_previewが呼ばれている"
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 5. フォールバック(カンマ区切り手入力)モード
# ---------------------------------------------------------------------------

def test_checklist_mode_does_not_show_catalog_unavailable_notice(
    hidden_root, monkeypatch, tmp_path
):
    """dev#1289追送(オーナー指摘): 一覧(チェックリスト)が表示できている
    ときは、カタログ取得失敗時専用の案内文を出さないこと。"""
    monkeypatch.setattr(dbd, "query_bone_catalog", lambda *a, **k: _fake_catalog_result())
    store = _FakeBackingStore()
    dlg = dbd.show_drop_bones_dialog(hidden_root, _make_ctx(store, tmp_path))
    try:
        notice = _find_label_by_text(
            dlg, i18n.S("LabDropBonesCatalogUnavailableNotice"))
        assert notice is None, (
            "チェックリストが出ているのにカタログ取得失敗の案内文が表示されている")
    finally:
        dlg.destroy()


def test_fallback_mode_shows_catalog_unavailable_notice(hidden_root, monkeypatch, tmp_path):
    """負の対照: カタログ取得に失敗した手入力フォールバック時は、その状況
    専用の案内文を表示すること。"""
    monkeypatch.setattr(
        dbd, "query_bone_catalog",
        lambda *a, **k: {"ok": False, "source": "none", "detail": "no avatar", "bones": []})
    store = _FakeBackingStore()
    dlg = dbd.show_drop_bones_dialog(hidden_root, _make_ctx(store, tmp_path))
    try:
        notice = _find_label_by_text(
            dlg, i18n.S("LabDropBonesCatalogUnavailableNotice"))
        assert notice is not None, (
            "フォールバック時なのにカタログ取得失敗の案内文が表示されていない")
    finally:
        dlg.destroy()


def test_fallback_mode_when_catalog_unavailable(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(
        dbd, "query_bone_catalog",
        lambda *a, **k: {"ok": False, "source": "none", "detail": "no avatar", "bones": []})
    store = _FakeBackingStore(initial="OldBone1,OldBone2")
    dlg = dbd.show_drop_bones_dialog(hidden_root, _make_ctx(store, tmp_path))
    try:
        assert _count_checkbuttons(dlg) == 0, "フォールバック時はチェックリストを出さない"
        ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
        assert ok_btn is not None
        ok_btn.invoke()
        # 手入力欄の初期値(既存store値)がそのまま保存される(未編集のOK)
        assert store.text == "OldBone1,OldBone2"
    finally:
        dlg.destroy()


def test_fallback_mode_preview_button_saves_without_closing(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(
        dbd, "query_bone_catalog",
        lambda *a, **k: {"ok": False, "source": "none", "detail": "no avatar", "bones": []})
    calls = []
    store = _FakeBackingStore()
    dlg = dbd.show_drop_bones_dialog(
        hidden_root, _make_ctx(store, tmp_path, trigger_preview=lambda: calls.append("preview")))
    try:
        preview_btn = _find_button_by_text(dlg, i18n.S("BtnPreviewUpdate"))
        assert preview_btn is not None
        preview_btn.invoke()
        assert calls == ["preview"]
        assert dlg.winfo_exists()
    finally:
        dlg.destroy()


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
