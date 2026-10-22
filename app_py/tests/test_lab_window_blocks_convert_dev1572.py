# test_lab_window_blocks_convert_dev1572.py -- dev#1551/dev#1572
# (ラボ窓ブロック、2026-08-18オーナー最終裁定)。
#
# 背景: ラボの各設定パネル(統合パネル「ゆれかた」等)はOK押下時のみ
# 永続ストア/バッキングウィジェットへ反映される設計のため、パネルを
# 開いたまま値を変え、閉じずにフル変換を実行すると画面上の変更が
# job.jsonへ一切反映されない事故が起きた(実測: sway_chain_overrides
# キー不在のままjob.jsonが書かれた)。
#
# 修正: ラボ系サブウィンドウ(ラボ窓本体+機能別設定ダイアログ)が1つでも
# 開いている間、メイン窓のconvertButton(フル変換開始ボタン)を強制的に
# disabledにする(ダイアログ案内方式ではない、オーナー明示却下済み)。
# 全部閉じたら通常のゲート判定(鮮度/blenderReady/work_root_failed)へ
# 復帰する。
#
# 受入条件(WP指示書どおり):
#   ①ダイアログopen中 -> ボタンdisabled
#   ②close後 -> enabled復活
#   ③複数ダイアログを開いて片方だけ閉じた場合はまだdisabled
#
# 2階層で検証する:
#   (A) ロジック層: _on_lab_subwindow_opened()/_on_lab_subwindow_closed()/
#       _refresh_convert_button_freshness()のカウンタ配線そのもの
#       (束縛前self、tk不要)
#   (B) ウィジェット層: ui\lab_window.py の open_lab_window()/機能別
#       ダイアログが実際に<Destroy>イベント経由でこれらのフックを正しく
#       呼ぶこと(hidden_root、実tk.Toplevelだがwithdraw済みで非表示、
#       既存のtest_lab_window_ui.pyと同じ流儀)
from __future__ import annotations

import os
import sys
import tempfile
import tkinter as tk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import lab_window  # noqa: E402
from ui import main_window as mw  # noqa: E402


# ---------------------------------------------------------------------------
# フェイク部品(test_button_gates.py._FakeButton/_FakeEntry/_FakeSelfForGates
# と同型。lab_window.open_lab_window()が要求するapp_root/work_root/
# widgets["dropBonesBox"](実tk.Entry)を追加で持つ)。
# ---------------------------------------------------------------------------


class _FakeButton:
    """tkinter.Button互換の最小フェイク(config(state=...)のみ)。"""

    def __init__(self) -> None:
        self.state: str | None = None

    def config(self, **kwargs) -> None:
        if "state" in kwargs:
            self.state = kwargs["state"]

    def __getitem__(self, key):
        return None

    def __setitem__(self, key, value) -> None:
        return None


class _FakeEntry:
    """tkinter.Entry互換の最小フェイク(.get()のみ)。"""

    def __init__(self, text: str = "") -> None:
        self._text = text

    def get(self) -> str:
        return self._text


class _FakeSelfForLabBlock:
    """MainWindow.__init__を経由しない束縛前self。convertButtonゲート
    (test_button_gates.py._FakeSelfForGatesと同型)+lab_window.pyが要求する
    app_root/work_root/widgets["dropBonesBox"](実tk.Entry、hidden_root配下)
    を併せ持つ。"""

    _refresh_convert_button_freshness = mw.MainWindow._refresh_convert_button_freshness
    _on_lab_subwindow_opened = mw.MainWindow._on_lab_subwindow_opened
    _on_lab_subwindow_closed = mw.MainWindow._on_lab_subwindow_closed
    _maybe_refresh_convert_button_after_lab_change = (
        mw.MainWindow._maybe_refresh_convert_button_after_lab_change
    )
    _set_status = mw.MainWindow._set_status

    def __init__(self, root: tk.Misc, vrm_path: str = "", fresh: bool = True) -> None:
        self.root = root
        self._is_pipeline_running = False
        self._blender_ready = True
        self._work_root_failed = False
        self._active_handle = None
        self._lab_subwindow_open_count = 0
        self._fresh = fresh
        self.app_root = tempfile.mkdtemp(prefix="d2p_labblock_test_")
        self.work_root = tempfile.mkdtemp(prefix="d2p_labblock_test_work_")
        self.widgets = {
            "convertButton": _FakeButton(),
            "vrmBox": _FakeEntry(vrm_path),
            "statusLabel": _FakeButton(),
            "dropBonesBox": tk.Entry(root),
        }

    def _is_preview_fresh(self, _vrm_path: str) -> bool:
        return self._fresh


def _make_real_vrm(tmp_path) -> str:
    vrm = tmp_path / "a.vrm"
    vrm.write_bytes(b"")
    return str(vrm)


# ---------------------------------------------------------------------------
# (A) ロジック層: カウンタ配線そのもの(tk不要)
# ---------------------------------------------------------------------------


def test_lab_subwindow_opened_forces_convert_button_disabled(hidden_root, tmp_path):
    """①: ラボ系サブウィンドウが1つ開けば(カウンタ>0)、他のゲート
    (blenderReady/fresh等)を全て満たしていてもconvertButtonは強制
    disabled。"""
    self = _FakeSelfForLabBlock(hidden_root, vrm_path=_make_real_vrm(tmp_path), fresh=True)
    # 前提: ラボ非開状態では通常どおりnormalになる(この後の対照)。
    mw.MainWindow._refresh_convert_button_freshness(self)
    assert self.widgets["convertButton"].state == "normal"

    self._on_lab_subwindow_opened()
    assert self._lab_subwindow_open_count == 1
    assert self.widgets["convertButton"].state == "disabled"


def test_lab_subwindow_closed_restores_normal_gate_when_count_reaches_zero(
    hidden_root, tmp_path
):
    """②: 開いたサブウィンドウを閉じてカウンタが0に戻れば、通常のゲート
    判定(鮮度True)へ復帰しconvertButtonがnormalへ戻る。"""
    self = _FakeSelfForLabBlock(hidden_root, vrm_path=_make_real_vrm(tmp_path), fresh=True)
    self._on_lab_subwindow_opened()
    assert self.widgets["convertButton"].state == "disabled"

    self._on_lab_subwindow_closed()
    assert self._lab_subwindow_open_count == 0
    assert self.widgets["convertButton"].state == "normal"


def test_lab_subwindow_two_open_one_closed_still_disabled(hidden_root, tmp_path):
    """③: 複数サブウィンドウを開いて片方だけ閉じた場合、カウンタは1のまま
    残るのでconvertButtonは依然disabled。"""
    self = _FakeSelfForLabBlock(hidden_root, vrm_path=_make_real_vrm(tmp_path), fresh=True)
    self._on_lab_subwindow_opened()  # 1つ目
    self._on_lab_subwindow_opened()  # 2つ目
    assert self._lab_subwindow_open_count == 2
    assert self.widgets["convertButton"].state == "disabled"

    self._on_lab_subwindow_closed()  # 1つ目だけ閉じる
    assert self._lab_subwindow_open_count == 1
    assert self.widgets["convertButton"].state == "disabled", (
        "片方閉じただけではまだdisabledのはず"
    )

    self._on_lab_subwindow_closed()  # 残り1つも閉じる
    assert self._lab_subwindow_open_count == 0
    assert self.widgets["convertButton"].state == "normal"


def test_lab_subwindow_closed_count_never_goes_negative(hidden_root):
    """負の対照: 開いていないのに閉じ通知だけが来ても(何らかの二重発火)、
    カウンタは0未満に潜らない(下限保護)。"""
    self = _FakeSelfForLabBlock(hidden_root)
    self._on_lab_subwindow_closed()
    assert self._lab_subwindow_open_count == 0


def test_lab_subwindow_gate_takes_priority_over_other_gates(hidden_root):
    """負の対照: blenderReady=Falseやwork_root_failed=Trueのときと同じく、
    ラボ開放中は他のゲート状態に関わらず一貫してdisabled(hasVrm=False
    でも例外を出さず素直にdisabledになることの確認)。"""
    self = _FakeSelfForLabBlock(hidden_root, vrm_path="", fresh=False)
    self._on_lab_subwindow_opened()
    assert self.widgets["convertButton"].state == "disabled"


# ---------------------------------------------------------------------------
# (B) ウィジェット層: lab_window.py の実際の<Destroy>配線
# ---------------------------------------------------------------------------


def test_open_lab_window_itself_disables_convert_button_and_closing_restores(
    hidden_root, tmp_path
):
    """①②の統合版: ラボ窓本体(open_lab_window())を開いた瞬間に
    convertButtonがdisabledになり、×で閉じれば(destroy())normalへ復帰する
    ことを、実際の<Destroy>バインド経由で確認する。"""
    i18n.set_language("ja")
    self = _FakeSelfForLabBlock(hidden_root, vrm_path=_make_real_vrm(tmp_path), fresh=True)
    mw.MainWindow._refresh_convert_button_freshness(self)
    assert self.widgets["convertButton"].state == "normal"

    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        assert self._lab_subwindow_open_count == 1
        assert self.widgets["convertButton"].state == "disabled"
    finally:
        dlg.destroy()
        hidden_root.update()

    assert self._lab_subwindow_open_count == 0
    assert self.widgets["convertButton"].state == "normal"


def test_open_lab_window_reopen_via_singleton_guard_does_not_double_count(
    hidden_root, tmp_path
):
    """負の対照: シングルトンガード(既存ラボ窓が生きていればlift/
    focus_forceのみ)経由の再呼び出しは、新規生成ではないので二重カウント
    しない。"""
    i18n.set_language("ja")
    self = _FakeSelfForLabBlock(hidden_root, vrm_path=_make_real_vrm(tmp_path), fresh=True)
    dlg1 = lab_window.open_lab_window(self, hidden_root)
    dlg2 = lab_window.open_lab_window(self, hidden_root)  # シングルトンガードで同一Toplevel
    try:
        assert dlg1 is dlg2
        assert self._lab_subwindow_open_count == 1
    finally:
        dlg1.destroy()
        hidden_root.update()
    assert self._lab_subwindow_open_count == 0


def test_configure_dialog_opened_from_lab_window_disables_convert_button(
    hidden_root, tmp_path
):
    """①: ラボ窓経由で機能別設定ダイアログ(「設定...」ボタン)を開くと、
    ラボ窓自身の分と合わせてconvertButtonがdisabledになる(_open()closure
    内の実配線を経由する検証、drop_bonesダイアログ本体の中身は別テストが
    担当するのでここでは開閉の数え上げのみを見る)。"""
    i18n.set_language("ja")
    self = _FakeSelfForLabBlock(hidden_root, vrm_path=_make_real_vrm(tmp_path), fresh=True)
    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        configure_buttons = [
            b for b in _find_children(dlg, tk.Button)
            if b.cget("text") == i18n.S("BtnLabConfigure")
        ]
        assert configure_buttons, "設定...ボタンが見つからない"
        assert self._lab_subwindow_open_count == 1  # ラボ窓本体のみ

        configure_buttons[0].invoke()  # 先頭機能(drop_bones)の設定ダイアログを開く
        assert self._lab_subwindow_open_count == 2
        assert self.widgets["convertButton"].state == "disabled"
    finally:
        dlg.destroy()
        hidden_root.update()
    assert self._lab_subwindow_open_count == 0
    assert self.widgets["convertButton"].state == "normal"


def test_two_configure_dialogs_open_close_one_still_disabled(hidden_root, tmp_path):
    """③そのもの: ラボ窓から機能別設定ダイアログを2つ開き(先頭機能を
    2回開く——多重起動を禁止する仕組みは無い、drop_bonesダイアログの
    「死んだ参照を間引く」コメント参照)、片方だけ閉じてもまだdisabled、
    残り両方(ダイアログ2個+ラボ窓本体)を閉じて初めてnormalへ戻ることを
    確認する。"""
    i18n.set_language("ja")
    self = _FakeSelfForLabBlock(hidden_root, vrm_path=_make_real_vrm(tmp_path), fresh=True)
    dlg = lab_window.open_lab_window(self, hidden_root)
    try:
        configure_buttons = [
            b for b in _find_children(dlg, tk.Button)
            if b.cget("text") == i18n.S("BtnLabConfigure")
        ]
        configure_buttons[0].invoke()
        configure_buttons[0].invoke()
        assert self._lab_subwindow_open_count == 3  # ラボ窓本体+ダイアログ2個

        sub_dialogs = [
            w for w in dlg.winfo_children()
            if isinstance(w, tk.Toplevel)
        ]
        assert len(sub_dialogs) == 2, "drop_bonesダイアログが2個開いているはず"

        sub_dialogs[0].destroy()
        hidden_root.update()
        assert self._lab_subwindow_open_count == 2
        assert self.widgets["convertButton"].state == "disabled", (
            "片方閉じただけではまだdisabledのはず"
        )

        sub_dialogs[1].destroy()
        hidden_root.update()
        assert self._lab_subwindow_open_count == 1  # ラボ窓本体のみ残る
        assert self.widgets["convertButton"].state == "disabled"
    finally:
        dlg.destroy()
        hidden_root.update()
    assert self._lab_subwindow_open_count == 0
    assert self.widgets["convertButton"].state == "normal"


def _find_children(widget, cls):
    found = []
    for child in widget.winfo_children():
        if isinstance(child, cls):
            found.append(child)
        found.extend(_find_children(child, cls))
    return found
