# test_support_dialog_full_log_attachment.py -- dev#921全ログ添付版の
# 「表示=送信」受入条件(2026-08-03オーナー追加裁定)。
#
# オーナー原文:
#   「送付ログは現状のUIそのままで全部表示し『一応ユーザーが事前に承認した』
#   体を保つこと」
#   「ユーザーの目に触れないまま、裏で追加のログが送られる形にしてはならない」
#   「表示するのも伏字化後のもの(生パスを画面に出すな)」
#
# 実装: app_py\ui\support_dialog.py の show_confirm_stage() が、診断文
# (ctx.build_diagnostics_text())に加えて work_root配下の全ログ(伏字化済み、
# inquiry.build_layer2_attachment_block経由)を同じlog_edit_box(tkinter.Text、
# 送信前にユーザーが読める・編集できる)へ書き込む。on_ok() は
# log_edit_box.get(...) をそのまま送信対象にする(添付を裏で取得し直さない)
# ため、「画面に出た内容」と「送信される内容」は構造的に一致する。
#
# 実tkウィンドウは開かない: conftest.pyの共有hidden_root(withdraw済み)を使う
# (test_error_next_action.pyの既存の慣例を踏襲)。
from __future__ import annotations

import base64
import gzip
import json
import os
import sys
import time

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import inquiry  # noqa: E402
from ui import support_dialog  # noqa: E402


def _find_button(widget, text: str):
    for child in widget.winfo_children():
        import tkinter as tk

        if isinstance(child, tk.Button) and child.cget("text") == text:
            return child
        found = _find_button(child, text)
        if found is not None:
            return found
    return None


def _find_text_widget(widget):
    import tkinter as tk

    for child in widget.winfo_children():
        if isinstance(child, tk.Text):
            return child
        found = _find_text_widget(child)
        if found is not None:
            return found
    return None


def _write(path, content=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


_FAKE_PROJECT_PATH = r"C:\UnityP\SampleProjectName\Assets\Avatar\SampleAvatar.prefab"


def _make_ctx(*, get_attachment_log_text, transport=None, base_url="https://example.invalid"):
    return support_dialog.SupportContext(
        tool_version="test",
        lang="ja",
        channel="dev",
        get_os_description=lambda: "Windows 11",
        get_avatar_name=lambda: "SampleAvatar.prefab",
        get_status_text=lambda: "idle",
        build_diagnostics_text=lambda: "diag base text (no secrets)",
        get_attachment_log_text=get_attachment_log_text,
        transport=transport,
        base_url=base_url,
    )


# ---------------------------------------------------------------------------
# 受入ゲート: 送信されるものが、すべて送信前のUI表示に含まれていること
# ---------------------------------------------------------------------------


def test_confirm_stage_displays_masked_attachment_in_log_box(hidden_root, tmp_path):
    job_dir = str(tmp_path / "work" / "SampleAvatar")
    _write(
        os.path.join(job_dir, "build", "logs", "convert_noue.log"),
        "processing asset at " + _FAKE_PROJECT_PATH + "\ndone\n",
    )

    def get_attachment():
        return inquiry.build_work_dir_attachment_text(labeled_dirs=[("work", job_dir)])

    ctx = _make_ctx(get_attachment_log_text=get_attachment)
    state = support_dialog.SupportDialogState()
    dlg = support_dialog.show_support_dialog(hidden_root, state, ctx)
    try:
        open_btn = _find_button(dlg, i18n.S("BtnOpenInquiryForm"))
        assert open_btn is not None
        open_btn.invoke()

        box = _find_text_widget(dlg)
        assert box is not None
        displayed = box.get("1.0", "end-1c")

        # 診断文(第1層)は表示される
        assert "diag base text" in displayed
        # 添付(第2層、work_root配下のログ)も同じ画面に表示される
        assert "processing asset at" in displayed
        assert "done" in displayed
        # 伏字化済みであること(生パスは出ない、構造情報は出る)
        assert _FAKE_PROJECT_PATH not in displayed
        assert "SampleProjectName" not in displayed
        assert "ext=.prefab" in displayed
        assert inquiry._ATTACHMENT_BEGIN_MARKER in displayed
    finally:
        dlg.destroy()


def test_negative_control_masking_disabled_leaks_into_display(hidden_root, monkeypatch, tmp_path):
    """負の対照: マスキングを無効化すると、上のテストと同じ操作で生パスが
    画面表示にそのまま出ることを確認する(検出力の実測)。"""
    job_dir = str(tmp_path / "work" / "SampleAvatar")
    _write(
        os.path.join(job_dir, "build", "logs", "convert_noue.log"),
        "processing asset at " + _FAKE_PROJECT_PATH + "\n",
    )

    def get_attachment():
        return inquiry.build_work_dir_attachment_text(labeled_dirs=[("work", job_dir)])

    monkeypatch.setattr(support_dialog.inquiry, "sanitize_for_clipboard", lambda s: s)

    ctx = _make_ctx(get_attachment_log_text=get_attachment)
    state = support_dialog.SupportDialogState()
    dlg = support_dialog.show_support_dialog(hidden_root, state, ctx)
    try:
        open_btn = _find_button(dlg, i18n.S("BtnOpenInquiryForm"))
        open_btn.invoke()
        box = _find_text_widget(dlg)
        displayed = box.get("1.0", "end-1c")
        assert _FAKE_PROJECT_PATH in displayed, (
            "負の対照が成立しない: マスキング無効化でも生パスが表示に現れなかった"
        )
    finally:
        dlg.destroy()


def test_sent_payload_matches_displayed_text_exactly(hidden_root, tmp_path):
    """本WPの中核受入ゲート: 「送信されるものが、すべて送信前のUI表示に
    含まれていること」+「表示と送信内容が一致していること(表示は要約で送信は
    全文、のようなズレを作らない)」の実測。on_ok()はlog_edit_boxの中身
    そのものを送信対象にする(添付を裏で再取得しない)ため、表示文字列を
    sanitize_for_clipboardへ通したものと、実際に送信されたgzip復号後の文字列が
    完全一致することを確認する。"""
    job_dir = str(tmp_path / "work" / "SampleAvatar")
    export_dir = str(tmp_path / "work" / "SampleAvatar_export")
    _write(
        os.path.join(job_dir, "build", "logs", "convert_noue.log"),
        "processing asset at " + _FAKE_PROJECT_PATH + "\ndone\n",
    )
    _write(os.path.join(export_dir, "unity_export.log"), "unity export ok\n")

    def get_attachment():
        return inquiry.build_work_dir_attachment_text(
            labeled_dirs=[("work", job_dir), ("unity_export", export_dir)]
        )

    calls: list[str] = []

    def fake_transport(url, payload_json, user_agent, timeout):
        calls.append(payload_json)
        return json.dumps({"id": "abc123", "view_url": "https://example.invalid/r/abc123"})

    ctx = _make_ctx(get_attachment_log_text=get_attachment, transport=fake_transport)
    state = support_dialog.SupportDialogState()
    dlg = support_dialog.show_support_dialog(hidden_root, state, ctx)
    try:
        open_btn = _find_button(dlg, i18n.S("BtnOpenInquiryForm"))
        open_btn.invoke()

        box = _find_text_widget(dlg)
        displayed = box.get("1.0", "end-1c")
        assert "unity export ok" in displayed  # 事前チェック: 添付が確かに表示されている

        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        assert ok_btn is not None
        ok_btn.invoke()

        deadline = time.time() + 5.0
        while not calls and time.time() < deadline:
            hidden_root.update()
            time.sleep(0.01)
        assert calls, "transport(送信)が時間内に呼ばれなかった"

        payload_json = calls[0]
        data = json.loads(payload_json)
        decoded = gzip.decompress(base64.b64decode(data["log_gzip_b64"])).decode("utf-8")

        # 送信された内容は、表示されていた文字列をsanitize_for_clipboardへ
        # 通したもの(冪等: 既に伏字化済みなので再適用しても不変のはず)と一致する
        expected = inquiry.sanitize_for_clipboard(displayed)
        assert decoded == expected
        # 生パスは送信物にも一切残っていない(表示側だけでなく送信側でも確認)
        assert _FAKE_PROJECT_PATH not in decoded
        assert "unity export ok" in decoded
    finally:
        dlg.destroy()


def test_send_succeeds_with_zero_log_files(hidden_root, tmp_path):
    """受入ゲート③: ログファイルが1つも無い場合でも問い合わせ送信自体は
    成功すること(UIレベル)。"""
    missing_dir = str(tmp_path / "no_such_avatar")

    def get_attachment():
        return inquiry.build_work_dir_attachment_text(labeled_dirs=[("work", missing_dir)])

    calls: list[str] = []

    def fake_transport(url, payload_json, user_agent, timeout):
        calls.append(payload_json)
        return json.dumps({"id": "xyz789", "view_url": "https://example.invalid/r/xyz789"})

    ctx = _make_ctx(get_attachment_log_text=get_attachment, transport=fake_transport)
    state = support_dialog.SupportDialogState()
    dlg = support_dialog.show_support_dialog(hidden_root, state, ctx)
    try:
        open_btn = _find_button(dlg, i18n.S("BtnOpenInquiryForm"))
        open_btn.invoke()

        box = _find_text_widget(dlg)
        displayed = box.get("1.0", "end-1c")
        assert inquiry._ATTACHMENT_BEGIN_MARKER not in displayed  # 添付ブロックは付かない

        ok_btn = _find_button(dlg, i18n.S("BtnOk"))
        ok_btn.invoke()

        deadline = time.time() + 5.0
        while not calls and time.time() < deadline:
            hidden_root.update()
            time.sleep(0.01)
        assert calls, "ログ0件でも送信(transport呼び出し)自体は成功するはず"

        data = json.loads(calls[0])
        decoded = gzip.decompress(base64.b64decode(data["log_gzip_b64"])).decode("utf-8")
        assert "diag base text" in decoded
    finally:
        dlg.destroy()


def test_attachment_fetch_exception_does_not_block_dialog(hidden_root):
    """取得コールバック自体が例外を出しても、確認画面の表示・送信続行を
    止めない(dev#921「失敗しても壊さない」方針の踏襲)。"""

    def boom():
        raise RuntimeError("synthetic attachment fetch failure (test double)")

    logged: list[str] = []
    ctx = support_dialog.SupportContext(
        tool_version="test",
        lang="ja",
        channel="dev",
        get_os_description=lambda: "Windows 11",
        get_avatar_name=lambda: "a.vrm",
        get_status_text=lambda: "idle",
        build_diagnostics_text=lambda: "diag base text",
        get_attachment_log_text=boom,
        append_log=lambda msg: logged.append(msg),
    )
    state = support_dialog.SupportDialogState()
    dlg = support_dialog.show_support_dialog(hidden_root, state, ctx)
    try:
        open_btn = _find_button(dlg, i18n.S("BtnOpenInquiryForm"))
        open_btn.invoke()
        box = _find_text_widget(dlg)
        displayed = box.get("1.0", "end-1c")
        assert "diag base text" in displayed
        assert any("attachment log unavailable" in m for m in logged)
    finally:
        dlg.destroy()


# ---------------------------------------------------------------------------
# 応答性の実測(オーナー追加指示「表示が重くなる懸念があれば実測して報告せよ」)
# ---------------------------------------------------------------------------


def test_measured_ui_insert_and_mask_performance_is_reasonable(hidden_root, tmp_path, capsys):
    """実測: 本WPで実際の変換出力(release_cert実測)を計測した代表的な
    非バイナリ・非.gzファイル群の合計サイズ(約1MB、39ファイル)相当の
    合成データを使い、show_confirm_stage一式(ディスク収集+行単位マスキング
    +tkinter.Text挿入)の所要時間を計測する。しきい値は「明らかに固まっていない
    ことの検知」用の緩いガード(5秒)で、実測値は標準出力へ残す
    (pytest -s / 完了報告に転記)。"""
    job_dir = str(tmp_path / "work" / "SampleAvatar")
    # 実測(本WP、release_cert相当ジョブディレクトリ、.gz除外後): 39ファイル
    # 合計約1.07MB。同等の分布で合成データを作る(内容は架空)。
    import random

    random.seed(20260803)
    total_target_bytes = 1_070_000
    file_count = 39
    per_file = total_target_bytes // file_count
    for i in range(file_count):
        line = f"log line {i} sample diagnostic content padding xxxxxxxxxxxxxxxxxxxxxx\n"
        repeat = max(1, per_file // len(line))
        content = line * repeat
        _write(os.path.join(job_dir, "build", "logs", f"synthetic_{i}.log"), content)

    def get_attachment():
        return inquiry.build_work_dir_attachment_text(labeled_dirs=[("work", job_dir)])

    ctx = _make_ctx(get_attachment_log_text=get_attachment)
    state = support_dialog.SupportDialogState()
    dlg = support_dialog.show_support_dialog(hidden_root, state, ctx)
    try:
        open_btn = _find_button(dlg, i18n.S("BtnOpenInquiryForm"))
        t0 = time.perf_counter()
        open_btn.invoke()
        elapsed = time.perf_counter() - t0

        box = _find_text_widget(dlg)
        displayed = box.get("1.0", "end-1c")
        with capsys.disabled():
            print(
                f"\n[perf] show_confirm_stage (collect+mask+Text insert) for "
                f"~{total_target_bytes / 1024:.0f}KB synthetic work dir "
                f"({file_count} files): {elapsed:.3f}s, displayed_len="
                f"{len(displayed)} chars"
            )
        assert elapsed < 5.0, (
            f"show_confirm_stage took {elapsed:.3f}s for ~1MB of synthetic logs "
            "(threshold 5.0s) -- investigate before shipping"
        )
    finally:
        dlg.destroy()
