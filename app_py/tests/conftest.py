# conftest.py -- dev#672: 実tk.Tk()ルートをapp_py/tests全体で1つだけに絞る。
#
# 背景(dev#672): test_main_window_lang_combo.py の
# test_lang_combo_survives_without_current_call が、単独実行では常にPASSする
# のに `pytest app_py/tests` の全体実行時だけ稀に
#   _tkinter.TclError: invalid command name "tcl_findLibrary"
# または
#   _tkinter.TclError: Can't find a usable tk.tcl in the following directories: ...
# でERRORになるフレークだった(全体実行10回中1〜2回程度の頻度で実測)。
#
# 実測で切り分けた汚染の実体: 同一プロセス内で tk.Tk() を複数回
# 生成・破棄すると、CPython 3.13 + Tcl/Tk 8.6(Windows)側の内部状態
# (Tclライブラリ探索に使うグローバル状態と見られる)がまれに壊れ、
# 2回目以降の tk.Tk() 生成が失敗する。dev#672着手前は
# test_main_window_lang_combo.py が関数スコープの hidden_root フィクスチャで
# テストごとに tk.Tk() を生成・破棄しており(1ファイルだけで3回)、
# さらに test_avatar_warning_diagnostics.py(dev#690)も独自にモジュール
# スコープで別個の tk.Tk() を生成していたため、app_py/tests全体では
# 常に複数回の tk.Tk() 生成が発生していた。
# test_avatar_warning_diagnostics.py側は既にdev#690の時点でモジュール
# スコープ化する回避策を取っていた(同ファイルの過去コメント参照)が、
# 「ファイルごとに1つ」に留めても複数ファイルが合算されればプロセス内の
# 生成回数は1を超え、フレークは消えなかった(実測: 本ファイル導入前に
# モジュールスコープのみの状態でも10回中1回再現)。
#
# 対処: 実tk.Tk()を必要とするテストファイル間で共有する、session スコープの
# hidden_root フィクスチャをここに集約し、app_py/tests 全体を通じて
# tk.Tk() の生成を「プロセス全体で最大1回」に絞る。各テストはこの共有root
# の子として毎回新しいウィジェットを作るだけなので(_make_fake_self等が
# 毎回新しいself/widgets辞書を用意する既存の流儀のまま)、rootを使い回して
# もテスト間の独立性は損なわれない。
#
# 画面には一切表示しない(root.withdraw()、common brief契約どおり)。
#
# dev#855: 実ダイアログのホスト画面漏出を構造で塞ぐ。
#
# 事故(2026-08-02): 並行レーンが追加したテストが tkinter.messagebox をモック
# し忘れ、pytest実行中に実ダイアログをオーナーの作業機へ表示した(応答待ちで
# フルスイートが10分超に伸びる副作用も実測)。指示書に「実tk窓を開かない」と
# 明記した上で発生したため、規律ではなく仕組みで止める。
#
# 対処1: tkinter.messagebox / tkinter.filedialog の呼び出し系関数を、
# autouseフィクスチャで既定「呼ばれたら例外」スタブへ差し替える。テストが
# 意図して monkeypatch.setattr(...) で個別に上書きした場合は、その上書きが
# このフィクスチャの後(テスト本体内)に実行されるため、素直に優先される
# (monkeypatch は同一テスト内で共有される1インスタンスであり、後勝ち)。
# したがって「モックし忘れ」だけが赤になり、意図的なモックは従来どおり通る。
#
# 対処2: 実tk.Tk()の二重生成を検出する(dev#672の「プロセス全体で最大1回」
# という既存契約を、conftest.hidden_root任せの慣習からアサーションへ格上げ)。
# hidden_root自体が唯一の正規の呼び出し元であり、これは壊さない。
#
# dev#899: このガードはtkinter.Tk.__init__というプロセス全体で共有される
# クラス属性を書き換える。従来はモジュール直下で無条件に適用し、二度と
# 元へ戻していなかったため、`pytest -q`(フルスイート)でapp_py/tests
# より後に収集される他ディレクトリ(tests/i18n_lint, tests/shipcheck等)
# のテストが正規に実tk.Tk()を生成しようとしても、この使い回しの
# パッチが残っていて誤って「2つ目」判定されエラーになっていた(実行順
# 依存のテスト間汚染。app_py/tests単体実行やtests/i18n_lint単体実行では
# 再現しない=このconftest.pyが読み込まれないため)。
#
# 対処: pytest のローカルconftest.pyフック(pytest_runtest_setup /
# pytest_runtest_teardown)はそのconftest.pyが置かれたディレクトリ配下の
# テストに対してのみ発火する(pytestの文書化された挙動)。これを使い、
# パッチの適用範囲を「app_py/tests のテストが実行されている間だけ」に
# 厳密に絞る。次のテスト(nextitem)がapp_py/tests配下でなくなった時点
# (=このディレクトリの実行区間を抜ける時点、または全テスト終了時)で
# 即座に元のtk.Tk.__init__へ復元する。
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import pytest

_THIS_DIR = Path(__file__).resolve().parent

_real_tk_init = tk.Tk.__init__
_tk_create_count = {"n": 0}
_guard_state = {"installed": False}


def _guarded_tk_init(self, *args, **kwargs):
    _tk_create_count["n"] += 1
    if _tk_create_count["n"] > 1:
        raise AssertionError(
            "dev#855: app_py/tests 内で2つ目の実tk.Tk()が生成されようと"
            "した。tk.Tk()はこのconftest.pyのhidden_rootフィクスチャ経由の"
            "1回だけに絞る契約(dev#672)。新規テストはhidden_rootを使うか、"
            "fake-self/withdraw方式(既存テストの流儀)に従うこと。"
        )
    return _real_tk_init(self, *args, **kwargs)


def _install_tk_guard() -> None:
    if not _guard_state["installed"]:
        tk.Tk.__init__ = _guarded_tk_init
        _guard_state["installed"] = True


def _uninstall_tk_guard() -> None:
    if _guard_state["installed"]:
        tk.Tk.__init__ = _real_tk_init
        _guard_state["installed"] = False
        _tk_create_count["n"] = 0


def _item_under_this_dir(item) -> bool:
    if item is None:
        return False
    try:
        path = Path(str(item.fspath)).resolve()
    except Exception:
        return False
    try:
        path.relative_to(_THIS_DIR)
        return True
    except ValueError:
        return False


def pytest_runtest_setup(item):  # noqa: ARG001 -- pytest hook signature
    # このフックはapp_py/tests配下のテストに対してのみ発火する(pytest local
    # conftest.pyフックの仕様)。他ディレクトリのテスト実行中は一切触らない。
    _install_tk_guard()


def pytest_runtest_teardown(item, nextitem):  # noqa: ARG001
    # 次のテストがapp_py/tests配下でなければ(=このディレクトリの実行区間を
    # 抜ける、または全テスト終了)、ただちに素のtk.Tk.__init__へ復元する。
    if not _item_under_this_dir(nextitem):
        _uninstall_tk_guard()


# --- 対処1: messagebox / filedialog の「呼ばれたら例外」スタブ ---
_MESSAGEBOX_FUNCS = (
    "showinfo",
    "showwarning",
    "showerror",
    "askyesno",
    "askquestion",
    "askokcancel",
    "askretrycancel",
    "askyesnocancel",
)
_FILEDIALOG_FUNCS = (
    "askopenfilename",
    "askopenfilenames",
    "askopenfile",
    "askopenfiles",
    "asksaveasfilename",
    "asksaveasfile",
    "askdirectory",
)


def _raise_stub(qualname: str):
    def _stub(*args, **kwargs):
        raise AssertionError(
            f"dev#855: 実 tkinter.{qualname}() がテスト中にモックされずに"
            "呼ばれようとした(=モックし忘れ)。オーナーの作業機へ実ダイアログ"
            "を出す事故の再発防止のため、既定で例外にしている。このテストが"
            "意図してダイアログ呼び出しを検証したいなら、"
            "monkeypatch.setattr(mw.messagebox, \"...\", ...) 等で明示的に"
            "モックすること。"
        )

    return _stub


@pytest.fixture(autouse=True)
def _block_real_dialogs(monkeypatch):
    """既定で全テストに適用: 実messagebox/filedialogの呼び出しを例外化する。

    意図的にモックしたいテストは、このフィクスチャの後(テスト本体内)で
    monkeypatch.setattr(...) すれば普通に上書きできる(monkeypatchは同一
    テスト内で共有される1インスタンスで、後から設定した値が有効になる)。
    """
    for name in _MESSAGEBOX_FUNCS:
        if hasattr(messagebox, name):
            monkeypatch.setattr(messagebox, name, _raise_stub(f"messagebox.{name}"))
    for name in _FILEDIALOG_FUNCS:
        if hasattr(filedialog, name):
            monkeypatch.setattr(filedialog, name, _raise_stub(f"filedialog.{name}"))
    yield


@pytest.fixture(scope="session")
def hidden_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()
