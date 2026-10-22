# test_univrm_dup_detection_dev1262.py -- dev#1262受入条件:
#   Unityエクスポート失敗ログから「UniVRMの二重導入」(UPMパッケージ版
#   com.vrmc.univrm と Assets/VRM/ 配下への手動導入版の共存によるGUID衝突)を
#   検出し、専用の案内メッセージへ差し替えること。
#
# 正本: dev issue #1262(実報告4YYV28PZのログ抜粋・規約調査結果込み)、
# LICENSE_SURVEY: C:\P\Work\DiveToPalworld\work\rd_1262\LICENSE_SURVEY.md
#
# 実tkウィンドウは一切開かない(test_unity_export_stacktrace_dev696.py/
# test_prefab_gui_cache.pyと同じフェイクself方式)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pipeline_runner as pr  # noqa: E402
from ui import main_window as mw  # noqa: E402


# ---------------------------------------------------------------------------
# 実報告4YYV28PZ(issue #1262本文からの引用)のログ抜粋。実際に検出発火の
# きっかけとなった生のUnityログ形式。
# ---------------------------------------------------------------------------
_REAL_REPORT_4YYV28PZ_EXCERPT = (
    "'Packages/com.vrmc.univrm/Runtime/Format/VRMException.cs' conflicts with:\n"
    "'Assets/VRM/Runtime/Format/VRMException.cs' (current owner)\n"
    "...assign a new GUID because the asset is in an immutable folder. "
    "The asset will be ignored.\n"
)

# dev#696テストが使うのと同型の「無関係な失敗」の実例(スタックトレース。
# UniVRM二重導入とは無関係な失敗ログでの誤検出が無いことの負の対照に使う)。
_UNRELATED_FAILURE_EXCERPT = (
    "Export failed - see log: C:\\work\\out\\unity_export.log\n"
    "--- Excerpt around the failure (full text is in the log file above) ---\n"
    "NullReferenceException: Object reference not set to an instance of an object\n"
    "  at DiveToPalworldExporter.ExportUnifiedFbx (UnityEngine.GameObject target, "
    "System.String path) [0x00120] in Assets/Editor/D2P_TempExporter/"
    "DiveToPalworldExporter.cs:1020\n"
    "--- End of excerpt ---\n"
)


# ===========================================================================
# 1) pipeline_runner.detect_univrm_duplicate_install: 純関数の単体テスト
# ===========================================================================


def test_detects_real_report_4yyv28pz_excerpt():
    assert pr.detect_univrm_duplicate_install(_REAL_REPORT_4YYV28PZ_EXCERPT) is True


def test_negative_control_unrelated_failure_does_not_fire():
    assert pr.detect_univrm_duplicate_install(_UNRELATED_FAILURE_EXCERPT) is False


def test_negative_control_empty_and_none_do_not_fire():
    assert pr.detect_univrm_duplicate_install("") is False
    assert pr.detect_univrm_duplicate_install(None) is False


def test_negative_control_generic_guid_conflict_without_univrm_markers_does_not_fire():
    # UniVRM名指しでない、無関係パッケージ同士のGUID衝突(4条件のうち
    # com.vrmc.univrm/Assets/VRMへの言及が無い)では発火しないことの証明
    # (「conflicts with」「immutable folder」だけでは誤検出しない=UniVRM特異的)。
    text = (
        "'Packages/com.example.other/Foo.cs' conflicts with:\n"
        "'Assets/OtherPlugin/Foo.cs' (current owner)\n"
        "...assign a new GUID because the asset is in an immutable folder. "
        "The asset will be ignored.\n"
    )
    assert pr.detect_univrm_duplicate_install(text) is False


def test_negative_control_univrm_mention_alone_without_conflict_does_not_fire():
    # UniVRMへの言及自体はあっても、衝突(conflicts with/immutable folder)を
    # 伴わない普通のログでは発火しないことの証明。
    text = "Importing package com.vrmc.univrm from Assets/VRM ... done.\n"
    assert pr.detect_univrm_duplicate_install(text) is False


def test_requires_all_four_markers_individually():
    # 4条件のうち1つでも欠けたら発火しないことを個別に確認する。
    full = _REAL_REPORT_4YYV28PZ_EXCERPT
    assert pr.detect_univrm_duplicate_install(full) is True

    no_upm = full.replace("com.vrmc.univrm", "com.example.other")
    assert pr.detect_univrm_duplicate_install(no_upm) is False

    no_manual = full.replace("Assets/VRM", "Assets/OtherFolder")
    assert pr.detect_univrm_duplicate_install(no_manual) is False

    no_conflict = full.replace("conflicts with", "coexists with")
    assert pr.detect_univrm_duplicate_install(no_conflict) is False

    no_immutable = full.replace("immutable folder", "read-only area")
    assert pr.detect_univrm_duplicate_install(no_immutable) is False


# ===========================================================================
# 2) main_window._on_unity_export_exit: 検出結果に応じたメッセージ差し替え
# ===========================================================================


class _FakeLogBox:
    """tkinter.Text互換の最小フェイク(test_unity_export_stacktrace_dev696.pyと
    同型)。get("1.0", "end-1c")だけ使う。"""

    def __init__(self, text: str) -> None:
        self._text = text

    def get(self, _start: str, _end: str) -> str:
        return self._text


def _bare_window_for_exit(log_text):
    fake = mw.MainWindow.__new__(mw.MainWindow)
    fake._pending_prefab_export_path = "C:\\fake\\avatar.prefab"
    fake._active_handle = None
    fake._set_running_ui_state = lambda *a, **k: None
    status_calls = []
    fake._set_status = lambda fn: status_calls.append(fn)
    fake._status_calls = status_calls
    if log_text is not None:
        fake.log_box = _FakeLogBox(log_text)
    return fake


def test_unity_export_exit_shows_univrm_specific_message_when_detected(monkeypatch):
    fake = _bare_window_for_exit(_REAL_REPORT_4YYV28PZ_EXCERPT)
    error_calls = []
    monkeypatch.setattr(mw.messagebox, "showerror", lambda *a: error_calls.append(a))

    mw.MainWindow._on_unity_export_exit(fake, 1)

    assert len(error_calls) == 1
    title, body = error_calls[0]
    assert body == mw.i18n.S("MsgUnityExportErrorUnivrmDupBody")
    assert body != mw.i18n.S("MsgUnityExportErrorBody")


def test_unity_export_exit_negative_control_shows_generic_message_for_unrelated_failure(
    monkeypatch,
):
    """負の対照: UniVRM二重導入以外の失敗では、従来どおり汎用メッセージのまま。"""
    fake = _bare_window_for_exit(_UNRELATED_FAILURE_EXCERPT)
    error_calls = []
    monkeypatch.setattr(mw.messagebox, "showerror", lambda *a: error_calls.append(a))

    mw.MainWindow._on_unity_export_exit(fake, 1)

    assert len(error_calls) == 1
    title, body = error_calls[0]
    assert body == mw.i18n.S("MsgUnityExportErrorBody")


def test_unity_export_exit_negative_control_missing_log_box_falls_back_to_generic(
    monkeypatch,
):
    """負の対照: log_box属性が無いフェイクself(既存test_prefab_gui_cache.py等)
    でも例外にならず、従来どおり汎用メッセージへ倒れること(dev#1262の追加が
    既存テストを壊していないことの実証)。"""
    fake = _bare_window_for_exit(None)
    error_calls = []
    monkeypatch.setattr(mw.messagebox, "showerror", lambda *a: error_calls.append(a))

    mw.MainWindow._on_unity_export_exit(fake, 1)

    assert len(error_calls) == 1
    title, body = error_calls[0]
    assert body == mw.i18n.S("MsgUnityExportErrorBody")


# ===========================================================================
# 3) export_from_unity.ps1: Excerpt抽出パターンにconflicts with/immutable
#    folderが追加され、GUI/診断ログへ到達できることの構造的な担保
# ===========================================================================


def test_export_from_unity_ps1_excerpt_pattern_includes_univrm_conflict_markers():
    ps1_path = os.path.join(
        os.path.dirname(_APP_PY_DIR), "pipeline", "cli", "export_from_unity.ps1"
    )
    assert os.path.isfile(ps1_path), "export_from_unity.ps1が無い: " + ps1_path
    with open(ps1_path, encoding="utf-8") as f:
        content = f.read()

    import re

    m = re.search(r'Select-String -LiteralPath \$log -Pattern "([^"]+)" -Context 0,(\d+)', content)
    assert m, "Excerpt抽出のSelect-String行が見つからない"
    pattern_str = m.group(1)
    for required in ("conflicts with", "immutable folder"):
        assert required in pattern_str, (
            "dev#1262: Excerpt抽出パターンに'{}'が追加されていない"
            "(UniVRM二重導入のGUID衝突行がログ欄へ届かない): {!r}".format(
                required, pattern_str
            )
        )


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
