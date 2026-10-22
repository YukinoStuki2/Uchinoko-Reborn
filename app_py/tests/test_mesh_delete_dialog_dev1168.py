# test_mesh_delete_dialog_dev1168.py -- dev#1168前半(メッシュ削除)ラボ機能。
#
# app_py\ui\mesh_delete_dialog.py の単体テスト。柱:
#   1. vrm_mesh_names(): 実サンプルVRM(test\vrm\配下)からのメッシュ名抽出
#   2. query_mesh_catalog(): VRM/prefab/未対応拡張子/ファイル不在のあらゆる
#      経路で例外を投げず、構造化結果(ok/source/detail/names)へ落ちること
#   3. ダイアログ本体(実Toplevel、hidden_root経由)の配線: チェックリスト
#      構築・OK/Cancelの保存/非保存・フォールバック(手入力)モード
#   4. ラボ憲章④(既定=全チェックON=削除リスト空)+負の対照
#      (1つ外すとjob設定に届く非既定状態になる)
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
_REPO_ROOT = os.path.dirname(_APP_PY_DIR)  # app_pyの直上=リポジトリ(worktree)ルート

import i18n  # noqa: E402
from ui import mesh_delete_dialog as mdd  # noqa: E402

VRM_SAMPLE_DIR = os.path.join(_REPO_ROOT, "test", "vrm")


# ---------------------------------------------------------------------------
# 1. vrm_mesh_names(): 実サンプルVRMからのメッシュ名抽出
# ---------------------------------------------------------------------------

def test_vrm_mesh_names_seed_san():
    path = os.path.join(VRM_SAMPLE_DIR, "Seed-san.vrm")
    if not os.path.exists(path):
        import pytest
        pytest.skip(f"sample VRM not found: {path}")
    names = mdd.vrm_mesh_names(path)
    assert "hair" in names
    assert "head" in names
    assert len(names) == len(set(names))  # 重複無し


def test_vrm_mesh_names_vita_vrm1():
    path = os.path.join(VRM_SAMPLE_DIR, "VitaVRM1.0.vrm")
    if not os.path.exists(path):
        import pytest
        pytest.skip(f"sample VRM not found: {path}")
    names = mdd.vrm_mesh_names(path)
    assert set(names) == {"Face", "Body", "Hair"}


def test_vrm_mesh_names_rejects_non_glb_file(tmp_path):
    fake = tmp_path / "not_a_vrm.vrm"
    fake.write_bytes(b"this is not a glb container" * 4)
    try:
        mdd.vrm_mesh_names(str(fake))
        assert False, "should have raised"
    except ValueError:
        pass


def test_vrm_mesh_names_rejects_truncated_header(tmp_path):
    fake = tmp_path / "too_small.vrm"
    fake.write_bytes(b"glTF")
    try:
        mdd.vrm_mesh_names(str(fake))
        assert False, "should have raised"
    except ValueError:
        pass


def _make_fake_glb(tmp_path, doc):
    payload = json.dumps(doc).encode("utf-8")
    # 4バイト境界パディング(仕様上は必要、テスト用途では簡略化して素の
    # 長さをそのまま書く。パーサ側はpaddingを要求しないため問題ない)
    header = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(payload))
    chunk_header = struct.pack("<I4s", len(payload), b"JSON")
    path = tmp_path / "synthetic.vrm"
    path.write_bytes(header + chunk_header + payload)
    return str(path)


def test_vrm_mesh_names_uses_node_name_over_mesh_name(tmp_path):
    doc = {
        "meshes": [{"name": "MeshData0"}],
        "nodes": [{"name": "Body", "mesh": 0}],
    }
    path = _make_fake_glb(tmp_path, doc)
    assert mdd.vrm_mesh_names(path) == ["Body"]


def test_vrm_mesh_names_falls_back_to_mesh_name_when_node_unnamed(tmp_path):
    doc = {
        "meshes": [{"name": "MeshData0"}],
        "nodes": [{"mesh": 0}],
    }
    path = _make_fake_glb(tmp_path, doc)
    assert mdd.vrm_mesh_names(path) == ["MeshData0"]


def test_vrm_mesh_names_skips_nodes_without_mesh(tmp_path):
    doc = {
        "meshes": [{"name": "Body"}],
        "nodes": [{"name": "SomeBone"}, {"name": "Body", "mesh": 0}],
    }
    path = _make_fake_glb(tmp_path, doc)
    assert mdd.vrm_mesh_names(path) == ["Body"]


def test_vrm_mesh_names_dedups_duplicate_names(tmp_path):
    doc = {
        "meshes": [{"name": "A"}, {"name": "A"}],
        "nodes": [{"name": "A", "mesh": 0}, {"name": "A", "mesh": 1}],
    }
    path = _make_fake_glb(tmp_path, doc)
    assert mdd.vrm_mesh_names(path) == ["A"]


# ---------------------------------------------------------------------------
# 2. query_mesh_catalog(): あらゆる経路で例外を投げず構造化結果へ落ちる
# ---------------------------------------------------------------------------

def test_catalog_query_no_avatar_falls_back(tmp_path):
    result = mdd.query_mesh_catalog(str(tmp_path), str(tmp_path), "")
    assert result["ok"] is False
    assert result["names"] == []


def test_catalog_query_missing_file_falls_back(tmp_path):
    result = mdd.query_mesh_catalog(
        str(tmp_path), str(tmp_path), str(tmp_path / "does_not_exist.vrm"))
    assert result["ok"] is False
    assert result["names"] == []


def test_catalog_query_unsupported_extension_falls_back(tmp_path):
    fake = tmp_path / "avatar.fbx"
    fake.write_bytes(b"x" * 16)
    result = mdd.query_mesh_catalog(str(tmp_path), str(tmp_path), str(fake))
    assert result["ok"] is False
    assert "unsupported" in result["detail"]


def test_catalog_query_corrupt_vrm_falls_back(tmp_path):
    fake = tmp_path / "avatar.vrm"
    fake.write_bytes(b"not a real vrm file" * 4)
    result = mdd.query_mesh_catalog(str(tmp_path), str(tmp_path), str(fake))
    assert result["ok"] is False
    assert result["source"] == "vrm"
    assert result["names"] == []


def test_catalog_query_real_vrm_sample():
    path = os.path.join(VRM_SAMPLE_DIR, "Seed-san.vrm")
    if not os.path.exists(path):
        import pytest
        pytest.skip(f"sample VRM not found: {path}")
    result = mdd.query_mesh_catalog(_REPO_ROOT, _REPO_ROOT, path)
    assert result["ok"] is True
    assert result["source"] == "vrm"
    assert "hair" in result["names"]


def test_catalog_query_prefab_without_export_falls_back(tmp_path):
    fake_prefab = tmp_path / "avatar.prefab"
    fake_prefab.write_text("fake prefab")
    result = mdd.query_mesh_catalog(str(tmp_path), str(tmp_path), str(fake_prefab))
    assert result["ok"] is False
    assert result["source"] == "prefab"
    assert "material_map.json not found" in result["detail"]


def test_catalog_query_prefab_reads_material_map(tmp_path):
    work_root = tmp_path / "work"
    fake_prefab = tmp_path / "avatar.prefab"
    fake_prefab.write_text("fake prefab")
    out_dir = work_root / "avatar_export"
    out_dir.mkdir(parents=True)
    (out_dir / "material_map.json").write_text(json.dumps({
        "format": "divetopalworld-materials-1",
        "fbx": "avatar.fbx",
        "meshes": {"Body": [], "Beret": []},
    }), encoding="utf-8")
    result = mdd.query_mesh_catalog(str(tmp_path), str(work_root), str(fake_prefab))
    assert result["ok"] is True
    assert result["source"] == "prefab"
    assert set(result["names"]) == {"Body", "Beret"}


def test_catalog_query_prefab_corrupt_material_map_falls_back(tmp_path):
    work_root = tmp_path / "work"
    fake_prefab = tmp_path / "avatar.prefab"
    fake_prefab.write_text("fake prefab")
    out_dir = work_root / "avatar_export"
    out_dir.mkdir(parents=True)
    (out_dir / "material_map.json").write_text("{ not valid json", encoding="utf-8")
    result = mdd.query_mesh_catalog(str(tmp_path), str(work_root), str(fake_prefab))
    assert result["ok"] is False
    assert result["source"] == "prefab"


# ---------------------------------------------------------------------------
# 3. ダイアログ本体(実Toplevel、hidden_root経由)
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


def _all_label_texts(widget):
    import tkinter as tk
    out = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            out.append(child.cget("text"))
        out.extend(_all_label_texts(child))
    return out


def _fake_catalog_result(**overrides):
    base = {"ok": True, "source": "vrm", "detail": "ok",
            "names": ["Body", "Hair", "Beret"]}
    base.update(overrides)
    return base


def test_dialog_builds_checklist_from_catalog(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _fake_catalog_result())
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm")
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)
    try:
        assert _count_checkbuttons(dlg) == 3
    finally:
        dlg.destroy()


def test_dialog_shows_hint(hidden_root, monkeypatch, tmp_path):
    # オーナー裁定(2026-08-09): ダイアログの説明は機能説明のみ
    # (「実験的機能・サポート対象外」等の但し書きは書かない、ラボ共通警告が
    # 一括で担う)。かつてここにあったLabMeshDeleteExperimentalWarningの
    # 表示アサーションは、そのキー自体の削除に伴い本テストから除去した。
    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _fake_catalog_result())
    i18n.set_language("ja")
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm")
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)
    try:
        texts = _all_label_texts(dlg)
        assert any(i18n.S("LabMeshDeleteHint", "ja") == t for t in texts)
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 4. ラボ憲章④: 既定=全チェックON。既定のままOKで削除リストは空
#    (job["drop_meshes"]キーが出ない状態)。負の対照: 1つ外すと非既定になる。
# ---------------------------------------------------------------------------

def test_default_state_shows_all_checkboxes_checked(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _fake_catalog_result())
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm")
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)
    try:
        cbs = _all_checkbuttons(dlg)
        assert len(cbs) == 3
        assert all(_is_checked(dlg, cb) for cb in cbs), "既定状態は全チェックONのはず"
    finally:
        dlg.destroy()


def test_default_ok_without_changes_saves_empty_state_dev1168_charter4(
    hidden_root, monkeypatch, tmp_path
):
    """④本体: 既定(全ON)のままOKを押しても、保存される削除リストは空
    (=job["drop_meshes"]キーが出ない既定値)であること。"""
    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _fake_catalog_result())
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm")
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)
    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    assert mdd.load_deleted_names(str(tmp_path), "C:\\fake.vrm") == []
    assert mdd.is_active(str(tmp_path), "C:\\fake.vrm") is False
    assert mdd.state_summary(str(tmp_path), "C:\\fake.vrm") is None


def test_negative_control_unchecking_one_produces_non_default_state_and_reaches_job(
    hidden_root, monkeypatch, tmp_path
):
    """負の対照: 全ON状態から1つだけOFF(=削除指定)にしてOKすると、
    job設定にキーが出る非既定状態が保存され、パイプライン(pipeline_runner.
    write_job())まで届くこと(保存スコープ=アバター単位、dev#1281残論点:
    write_job()に渡すvrm_pathがダイアログで編集したavatar_pathと一致する
    必要がある)。"""
    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _fake_catalog_result())
    avatar_path = os.path.join(str(tmp_path), "dummy.vrm")
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path=avatar_path)
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)

    cbs = _all_checkbuttons(dlg)
    assert len(cbs) == 3
    cbs[0].invoke()  # 全ONから1つだけOFF(=削除指定)にする

    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    saved = mdd.load_deleted_names(str(tmp_path), avatar_path)
    assert len(saved) == 1
    assert mdd.is_active(str(tmp_path), avatar_path) is True

    # job設定への到達確認(pipeline_runner.write_job()経由、同一avatar_path)
    import pipeline_runner
    work_root = os.path.join(str(tmp_path), "work")
    job_json_path = pipeline_runner.write_job(
        str(tmp_path), work_root, avatar_path)
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert job.get("drop_meshes") == saved


def test_scope_isolation_other_avatar_job_gets_no_drop_meshes_key(
    hidden_root, monkeypatch, tmp_path
):
    """保存スコープ=アバター単位(dev#1281残論点)の分離確認: アバターAで
    削除指定を保存しても、write_job()に別アバターBのvrm_pathを渡すと
    job.jsonにdrop_meshesキーが一切出ないこと(誤爆防止の中核仕様、
    shapekey_filter_storeの前例と同型)。"""
    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _fake_catalog_result())
    avatar_a = os.path.join(str(tmp_path), "avatar_a.vrm")
    avatar_b = os.path.join(str(tmp_path), "avatar_b.vrm")
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path=avatar_a)
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)

    cbs = _all_checkbuttons(dlg)
    cbs[0].invoke()  # アバターAで1件削除指定
    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    assert len(mdd.load_deleted_names(str(tmp_path), avatar_a)) == 1
    # アバターBからは見えない(既定値扱い)
    assert mdd.load_deleted_names(str(tmp_path), avatar_b) == []

    import pipeline_runner
    work_root = os.path.join(str(tmp_path), "work")
    job_json_path = pipeline_runner.write_job(str(tmp_path), work_root, avatar_b)
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert "drop_meshes" not in job


def test_negative_control_default_state_produces_no_job_key(
    hidden_root, monkeypatch, tmp_path
):
    """負の対照の裏: 既定(全ON)のままOKすると、job.jsonにdrop_meshesキーが
    一切出ないこと(ラボ憲章④、未実装状態と完全同一)。"""
    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _fake_catalog_result())
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm")
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)
    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    import pipeline_runner
    work_root = os.path.join(str(tmp_path), "work")
    job_json_path = pipeline_runner.write_job(
        str(tmp_path), work_root, os.path.join(str(tmp_path), "dummy.vrm"))
    with open(job_json_path, encoding="utf-8") as f:
        job = json.load(f)
    assert "drop_meshes" not in job


def test_all_off_is_blocked_from_saving(hidden_root, monkeypatch, tmp_path):
    """全OFF(=全メッシュ削除)は保存されずに弾かれること(equipment_select_
    dialogと同じ枠)。ダイアログはOK後も残ったまま。"""
    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _fake_catalog_result())
    warnings = []
    monkeypatch.setattr(mdd.messagebox, "showwarning",
                         lambda *a, **k: warnings.append(a))
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm")
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)
    try:
        clear_btn = _find_button_by_text(dlg, i18n.S("LabEquipmentFilterClearAll"))
        clear_btn.invoke()
        ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()

        assert warnings, "全OFFでOKを押しても警告が出ていない"
        assert mdd.load_deleted_names(str(tmp_path), "C:\\fake.vrm") == []
        assert dlg.winfo_exists(), "全OFFのOKでダイアログが閉じてしまっている"
    finally:
        dlg.destroy()


def test_dialog_cancel_does_not_save(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _fake_catalog_result())
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm")
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)

    cbs = _all_checkbuttons(dlg)
    cbs[0].invoke()
    cancel_btn = _find_button_by_text(dlg, i18n.S("BtnCancel"))
    cancel_btn.invoke()

    assert mdd.load_deleted_names(str(tmp_path), "C:\\fake.vrm") == []


# ---------------------------------------------------------------------------
# 3b. dev#1277: 「プレビュー更新」ボタン(チェックリストモード)。保存は
#    するがダイアログは閉じず、trigger_previewコールバックを起動する。
# ---------------------------------------------------------------------------

def test_preview_button_saves_and_triggers_callback_without_closing(
    hidden_root, monkeypatch, tmp_path
):
    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _fake_catalog_result())
    calls = []
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm",
        trigger_preview=lambda: calls.append("preview"))
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)
    try:
        cbs = _all_checkbuttons(dlg)
        cbs[0].invoke()  # 1件削除指定にする

        preview_btn = _find_button_by_text(dlg, i18n.S("BtnPreviewUpdate"))
        assert preview_btn is not None, "プレビュー更新ボタンが見つからない"
        preview_btn.invoke()

        assert len(mdd.load_deleted_names(str(tmp_path), "C:\\fake.vrm")) == 1
        assert calls == ["preview"]
        assert dlg.winfo_exists(), "プレビュー更新でダイアログが閉じてしまっている"
    finally:
        dlg.destroy()


def test_preview_button_is_safe_when_trigger_preview_is_none(
    hidden_root, monkeypatch, tmp_path
):
    """負の対照: trigger_preview未設定(既定None)でも例外を投げずに保存だけ
    行われること。"""
    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _fake_catalog_result())
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm")
    assert ctx.trigger_preview is None
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)
    try:
        cbs = _all_checkbuttons(dlg)
        cbs[0].invoke()
        preview_btn = _find_button_by_text(dlg, i18n.S("BtnPreviewUpdate"))
        preview_btn.invoke()  # 例外が出ないことそのものが検証対象

        assert len(mdd.load_deleted_names(str(tmp_path), "C:\\fake.vrm")) == 1
        assert dlg.winfo_exists()
    finally:
        dlg.destroy()


def test_preview_button_all_off_is_blocked_like_ok(hidden_root, monkeypatch, tmp_path):
    """負の対照: 全OFFでプレビュー更新を押しても、on_okと同じ警告で弾かれ
    保存されないこと(アバター全損防止の枠はプレビュー経路でも同じ)。"""
    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _fake_catalog_result())
    warnings = []
    monkeypatch.setattr(mdd.messagebox, "showwarning",
                         lambda *a, **k: warnings.append(a))
    calls = []
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm",
        trigger_preview=lambda: calls.append("preview"))
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)
    try:
        clear_btn = _find_button_by_text(dlg, i18n.S("LabEquipmentFilterClearAll"))
        clear_btn.invoke()
        preview_btn = _find_button_by_text(dlg, i18n.S("BtnPreviewUpdate"))
        preview_btn.invoke()

        assert warnings, "全OFFでプレビュー更新を押しても警告が出ていない"
        assert mdd.load_deleted_names(str(tmp_path), "C:\\fake.vrm") == []
        assert calls == [], "全OFF警告で弾かれたのにtrigger_previewが呼ばれている"
        assert dlg.winfo_exists()
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 3c. dev#1277: フォールバック(手入力)モードの「プレビュー更新」ボタン
# ---------------------------------------------------------------------------

def test_fallback_preview_button_saves_and_triggers_callback_without_closing(
    hidden_root, monkeypatch, tmp_path
):
    import tkinter as tk

    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _empty_catalog_result())
    calls = []
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm",
        trigger_preview=lambda: calls.append("preview"))
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)
    try:
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
        entry.insert(0, "Beret, Ribbon")

        preview_btn = _find_button_by_text(dlg, i18n.S("BtnPreviewUpdate"))
        assert preview_btn is not None, "フォールバックモードにプレビュー更新ボタンが無い"
        preview_btn.invoke()

        assert mdd.load_deleted_names(str(tmp_path), "C:\\fake.vrm") == ["Beret", "Ribbon"]
        assert calls == ["preview"]
        assert dlg.winfo_exists(), "プレビュー更新でダイアログが閉じてしまっている"
    finally:
        dlg.destroy()


def test_dialog_preselects_previously_saved_deletions(hidden_root, monkeypatch, tmp_path):
    mdd.save_deleted_names(str(tmp_path), "C:\\fake.vrm", ["Beret"])
    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _fake_catalog_result())
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm")
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)
    try:
        cbs = _all_checkbuttons(dlg)
        beret_cb = next(cb for cb in cbs if cb.cget("text") == "Beret")
        assert _is_checked(dlg, beret_cb) is False
        others = [cb for cb in cbs if cb.cget("text") != "Beret"]
        assert all(_is_checked(dlg, cb) for cb in others)
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 5. フォールバック(カンマ区切り手入力)モード: カタログ取得失敗時
# ---------------------------------------------------------------------------

def _empty_catalog_result(**overrides):
    base = {"ok": False, "source": "none", "detail": "boom", "names": []}
    base.update(overrides)
    return base


def test_fallback_mode_shown_when_catalog_unavailable(hidden_root, monkeypatch, tmp_path):
    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _empty_catalog_result())
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm")
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)
    try:
        assert _count_checkbuttons(dlg) == 0
        texts = _all_label_texts(dlg)
        assert any(i18n.S("LabMeshDeleteCatalogUnavailableNotice") == t for t in texts)
    finally:
        dlg.destroy()


def test_fallback_mode_saves_manual_comma_separated_names(hidden_root, monkeypatch, tmp_path):
    import tkinter as tk

    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _empty_catalog_result())
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm")
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)

    def _find_entry(widget):
        for child in widget.winfo_children():
            if isinstance(child, tk.Entry):
                return child
            found = _find_entry(child)
            if found is not None:
                return found
        return None

    entry = _find_entry(dlg)
    assert entry is not None
    entry.delete(0, tk.END)
    entry.insert(0, "Beret, Ribbon")

    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    assert mdd.load_deleted_names(str(tmp_path), "C:\\fake.vrm") == ["Beret", "Ribbon"]


def test_fallback_mode_ok_with_empty_entry_saves_empty(hidden_root, monkeypatch, tmp_path):
    mdd.save_deleted_names(str(tmp_path), "C:\\fake.vrm", ["Old"])
    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _empty_catalog_result())
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm")
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)

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
    ok_btn = _find_button_by_text(dlg, i18n.S("BtnOk"))
    ok_btn.invoke()

    assert mdd.load_deleted_names(str(tmp_path), "C:\\fake.vrm") == []


def test_dialog_follows_language_switch(hidden_root, monkeypatch, tmp_path):
    i18n.set_language("ja")
    monkeypatch.setattr(mdd, "query_mesh_catalog", lambda *a, **k: _fake_catalog_result())
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake.vrm")
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)
    try:
        assert dlg.title() == i18n.S("LabMeshDeleteDialogTitle", "ja")
        i18n.apply_language("en")
        try:
            assert dlg.title() == i18n.S("LabMeshDeleteDialogTitle", "en")
        finally:
            i18n.apply_language("ja")
    finally:
        dlg.destroy()
