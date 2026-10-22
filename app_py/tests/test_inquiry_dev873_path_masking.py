# test_inquiry_dev873_path_masking.py -- dev#873: 汎用パスマスク正規表現が
# 例外メッセージ本文ごと握りつぶす問題(実報告X65FG73S、v2.3.6)の回帰試験。
#
# 経緯: 修理版のリファレンス実装はpipeline\py\path_privacy.pyに
# GENERIC_PATH_RE/mask_generic_paths_in_text()として用意され
# (tests\path_privacy\test_path_privacy_dev873.pyで検証済み)、当初
# app_py\inquiry.py本体への配線は別レーン(dev#921 GUI結線PR #1006/#1008)との
# ファイル衝突を避けるため保留されていた。#1008マージ後にMasterライターが
# 配線した(2026-08-03)。このファイルは元々「配線待ちを忘れないための
# xfail(strict=True)トリップワイヤ」だったが、配線完了に伴い通常のPASS必須
# テストへ格上げした。
#
# 実在の個人情報は一切含まない(X65FG73Sの実ログを個人情報を除いて一般化した
# 形のみを使う)。
from __future__ import annotations

import os
import sys

import pytest

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import inquiry  # noqa: E402


def test_issue_negative_control_type_name_and_prose_currently_lost():
    """dev#873のissue本文にある受入対照そのもの。修理前は例外の型名の
    直後(パス埋め込み以降)の説明文が丸ごと消えていた。"""
    line = (
        r"UnityException: something failed at C:\Users\foo\bar.fbx "
        r"because of xyz"
    )
    result = inquiry.sanitize_for_clipboard(line)
    assert "because of xyz" in result, (
        "dev#873の配線が壊れている(例外メッセージ本文が再び消えた): "
        "result=" + repr(result)
    )


def test_real_world_repro_x65fg73s_pattern_currently_lost():
    """実報告X65FG73S(v2.3.6)を個人情報を含まない形へ一般化した再現。
    export_from_unity.ps1のExcerptが出す `<ログパス>:<行番号>:Exception: <本文>`
    形式の行で、修理前は行全体が `<path len=X ...>` へ丸ごと潰れ、
    行番号・例外メッセージともに一切残らなかった。"""
    line = (
        r"C:\Fake\Project\Assets\Editor\D2P_TempExporter\work\unity_export.log"
        r":6653:Exception: Humanoid setup avatar not found"
    )
    result = inquiry.sanitize_for_clipboard(line)
    assert "Exception: Humanoid setup avatar not found" in result, (
        "dev#873の配線が壊れている(例外メッセージ本文が再び消えた): "
        "result=" + repr(result)
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
