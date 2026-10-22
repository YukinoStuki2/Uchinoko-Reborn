# test_avatar_warning_diagnostics.py -- dev#690 受入条件1・2の実証。
#
# 背景(問い合わせKFRHNTTK、韓国語、「色が正しく表示されない」):
#   pipeline/py/convert_noue.py が出す ##AVATAR_WARNING## 行(色情報取得失敗の
#   直接診断行)は、旧main_window.py _on_pipeline_line() では
#   _pipeline_warnings リストへ積んだ直後に return しており、log_box
#   (=「ログをコピー」ボタンが読む _build_diagnostics_text() の材料)に
#   一切残らなかった。結果、ユーザーが送れる唯一の情報である診断テキストに
#   色診断の材料が構造的に載らず、この問い合わせは再送を依頼しても無駄な
#   状態のまま human フラグで止まっていた。
#
# 正: app\DiveToPalworld.cs AppendLog() L.2874-2879(AvatarWarnMark一致後も
#   returnせずlogBox.AppendTextへ落ちる)。本ファイルはmain_window.py側の
#   修正(_on_pipeline_line内のreturn削除)が、実際に
#   _build_diagnostics_text() の出力へ反映されることを、本物のtk.Text
#   (非表示ルート、画面には一切表示しない)を通して確認する。
#
# tkの実ウィンドウは表示しない(root.withdraw()、common brief契約どおり)。
from __future__ import annotations

import os
import sys
import tkinter as tk

import pytest

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import main_window as mw  # noqa: E402


class _FakeWidget:
    """vrmBox/statusLabel用の最小フェイク(.get()/.cget()のみ使用)。"""

    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def cget(self, key: str) -> str:
        return self._value

    def config(self, **kwargs) -> None:
        if "text" in kwargs:
            self._value = kwargs["text"]


# dev#672: hidden_root フィクスチャは conftest.py の session スコープ共有版を
# 使う(本ファイル単独のmodule scope fixtureは撤去)。tk.Tk()の生成・破棄を
# 同一プロセス内で複数回行うとTclインタプリタの再初期化がまれに失敗する
# 問題(test_main_window_lang_combo.pyで観測)は、本ファイルだけmodule scope
# に留めても他ファイルのtk.Tk()生成と合算されて再現し続けたため、
# app_py/tests全体で共有root1個に絞ることで解消した(詳細はconftest.py)。


@pytest.fixture
def fake_self(hidden_root):
    """_build_diagnostics_text()と_on_pipeline_line()を実行するための最小
    フェイクインスタンス。log_boxだけは本物のtk.Text(非表示ルート配下)を
    使う -- _log()がconfigure/insert/see/getをTclの実セマンティクスで呼ぶため、
    フェイクでスタブし直すより実物の方が安全(挙動の見落としを防げる)。"""
    log_box = tk.Text(hidden_root)
    try:
        self = mw.MainWindow.__new__(mw.MainWindow)
        self.log_box = log_box
        self.widgets = {
            "vrmBox": _FakeWidget("C:\\avatars\\sample.vrm"),
            "statusLabel": _FakeWidget("converting..."),
        }
        self._paks_dir_cache = None
        self.app_root = os.path.dirname(_APP_PY_DIR)
        self._pipeline_warnings = []
        self._active_handle = None
        self._early_preview_loaded_this_run = False
        # main_window.MainWindowの実メソッドをそのまま束縛する
        self._log = mw.MainWindow._log.__get__(self, mw.MainWindow)
        self._get_os_description = mw.MainWindow._get_os_description.__get__(self, mw.MainWindow)
        self._current_os_culture_name = mw.MainWindow._current_os_culture_name.__get__(
            self, mw.MainWindow
        )
        self._build_diagnostics_text = mw.MainWindow._build_diagnostics_text.__get__(
            self, mw.MainWindow
        )
        self._on_pipeline_line = mw.MainWindow._on_pipeline_line.__get__(self, mw.MainWindow)
        self._set_busy_bar_mode = lambda *_a, **_k: None  # busyBar未使用のため無害化
        # ##PROGRESS##マーカー分岐がwidgets["busyBar"]["value"]へ代入するため、
        # dictを最小フェイクとして渡す(busyBarモード自体の検証はtest_busy_bar_
        # progress.pyの担当。ここでは診断テキストへ漏れないことだけを見る)。
        self.widgets["busyBar"] = {}
        yield self
    finally:
        log_box.destroy()


def test_avatar_warning_reaches_diagnostics_text(fake_self):
    """受入条件1: ##AVATAR_WARNING##を含む出力があったとき、
    _build_diagnostics_text()の結果にその警告文が含まれる。"""
    fake_self._on_pipeline_line(
        "##AVATAR_WARNING## Color information for some materials could not be "
        "retrieved, so they may not display correctly (material=Body)"
    )
    text = fake_self._build_diagnostics_text()
    assert (
        "Color information for some materials could not be retrieved, so they "
        "may not display correctly (material=Body)" in text
    )


def test_no_warning_leaves_diagnostics_text_without_warning_residue(fake_self):
    """受入条件2(負の対照): 警告が1件も出ていないときは、診断テキストに
    警告セクションの残骸やダミー行が現れない。"""
    fake_self._on_pipeline_line("normal progress line, nothing unusual")
    text = fake_self._build_diagnostics_text()
    assert "AVATAR_WARNING" not in text
    assert "##AVATAR_WARNING##" not in text
    # ダミーの警告見出し等を追加実装していないこと(要件は「既存ログに素直に
    # 混ざる」以上の演出を求めていない)
    assert "warning" not in text.lower()


def test_progress_marker_still_absent_from_diagnostics_text(fake_self):
    """負の対照(要件4): ##PROGRESS##行は本修正後も診断テキストの
    Execution Log部分に出ない(dev#690はAVATAR_WARNING分岐のみを直す)。"""
    fake_self._on_pipeline_line("##PROGRESS## 55 retarget")
    text = fake_self._build_diagnostics_text()
    assert "##PROGRESS##" not in text
    assert "PROGRESS" not in text
