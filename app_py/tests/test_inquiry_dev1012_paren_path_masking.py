# test_inquiry_dev1012_paren_path_masking.py -- dev#1012: 括弧を含むパスが
# 前半だけマスクされ後半が生のまま残る問題(PR #1010レビュー中に発見)の
# app_py\inquiry.py側回帰試験。tests\path_privacy\test_path_privacy_dev1012.py
# の app_py 独立実装側(_GENERIC_PATH_RE)に対する対になるテスト。
#
# 実在の個人情報は一切含まない。
from __future__ import annotations

import os
import sys

import pytest

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import inquiry  # noqa: E402


def test_program_files_x86_fully_masked():
    """dev#1012の再現そのもの: 括弧を含むパスの後半が生で残らないこと。"""
    line = r"Installed at C:\Program Files (x86)\Foo\bar.exe on this machine"
    result = inquiry.sanitize_for_clipboard(line)
    assert r"C:\Program Files (x86)\Foo\bar.exe" not in result
    assert r"Files (x86)\Foo\bar.exe" not in result, (
        "dev#1012が再発している(括弧を含むパスの後半が生で残っている): "
        "result=" + repr(result)
    )
    assert "Installed at" in result
    assert "on this machine" in result


def test_apostrophe_username_fully_masked():
    """走査で見つけた追加の漏洩: アポストロフィを含むユーザー名。"""
    line = r"C:\Users\O'Brien\Documents\avatar.vrm loaded ok"
    result = inquiry.sanitize_for_clipboard(line)
    assert r"C:\Users\O'Brien\Documents\avatar.vrm" not in result
    assert r"Brien\Documents\avatar.vrm" not in result, (
        "アポストロフィ入りユーザー名が漏洩している: result=" + repr(result)
    )
    assert "loaded ok" in result


def test_dev873_prose_preservation_not_regressed():
    """負の対照(核): dev#1012の修理でdev873の「散文を飲み込まない」方向が
    再退行していないこと(両方向のバランス確認)。"""
    line = (
        r"UnityException: something failed at C:\Users\foo\bar.fbx "
        r"because of xyz"
    )
    result = inquiry.sanitize_for_clipboard(line)
    assert "because of xyz" in result, (
        "dev#873が再退行している(例外メッセージ本文が再び消えた): "
        "result=" + repr(result)
    )
    assert r"C:\Users\foo\bar.fbx" not in result


def test_stack_trace_signature_not_regressed():
    line = (
        r"C:\Fake\Project\unity_export.log:3618:  at UnityEditor.Formats."
        r"Fbx.Exporter.ModelExporter.GetExportData "
        r"(UnityEngine.GameObject go, UnityEditor.Formats.Fbx.Exporter."
        r"IExportOptions exportOptions) [0x0014f] in .\Library\PackageCache"
        r"\com.unity.formats.fbx@4.2.1\Editor\FbxExporter.cs:3393"
    )
    result = inquiry.sanitize_for_clipboard(line)
    assert (
        "at UnityEditor.Formats.Fbx.Exporter.ModelExporter.GetExportData "
        "(UnityEngine.GameObject go, UnityEditor.Formats.Fbx.Exporter."
        "IExportOptions exportOptions) [0x0014f] in .\\Library\\PackageCache"
        "\\com.unity.formats.fbx@4.2.1\\Editor\\FbxExporter.cs:3393"
    ) in result


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
