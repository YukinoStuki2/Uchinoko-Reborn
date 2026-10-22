# test_main_window_kodawari_layout.py -- dev#551受入条件の実証テスト。
#
# 背景: オーナー実機確認(2026-08-01、issue #551)で2点指摘された。
#   1. フッターの空白エリアが広い(下部の余白が間延びしている)
#   2. 「こだわり設定」パネルが開閉状態に関わらず領域を常時確保している
#      (閉じているときは畳んでウィンドウを詰めるのが望ましい)
#
# main_window.py の layout_content_area()(#25)を、こだわりパネルの開閉に
# 応じてウィンドウの高さ・フッター行(パクリスト以下)のy座標を実際に変える
# 方式へ書き換えた(_KODAWARI_PANEL_DELTA/_FOOTER_OPEN_GEOMETRY参照)。
# 本ファイルはその受入条件そのもの(開いた状態は従来どおり、閉じた状態は
# ウィンドウ高・フッターy座標の両方が実際に縮む)を検証する。
#
# ウィンドウ高の検証方法について(重要): conftest.py の hidden_root は
# root.withdraw()済みの共有session fixtureだが、実測したところ「withdraw済み
# のToplevelは、最初の1回のgeometry()呼び出しだけがwinfo_height()/geometry()
# のgetterに反映され、2回目以降の書き換えはgetterに反映されない」という
# Tk側の挙動がある(本ファイル開発時にpython -c での再現実験で確認済み。
# 開閉を2回以上切り替える本テストの用途には winfo_height() 読み戻しが使えない)。
# そのため、`root.geometry` をレコーダーで横取りし、layout_content_area()が
# 実際に何を要求したか(渡した文字列)を直接記録して検証する
# (`_capture_geometry_calls`)。tkの実ウィンドウは一切表示しない
# (hidden_root、common brief契約どおり)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import main_window as mw  # noqa: E402
from ui import workarea  # noqa: E402


def _make_fake_self(root, app_root: str) -> mw.MainWindow:
    """test_main_window_lang_combo.pyの`_make_fake_self`と同じ、
    MainWindow.__init__を経由せず_build_widgets()だけを実行するための
    最小フェイクインスタンス(既存の慣例をそのまま踏襲)。"""
    self = mw.MainWindow.__new__(mw.MainWindow)
    self.root = root
    self.app_root = app_root
    self.widgets = {}
    self._tooltips = []
    return self


def _capture_geometry_calls(monkeypatch, root) -> list:
    """`root.geometry(spec)` の呼び出しを記録しつつ、実際の呼び出しにも
    委譲するレコーダーを仕込む(モジュールdocstring参照: withdraw済みroot
    のgetterは複数回の書き換えを反映しないため、要求された文字列そのものを
    ここで直接記録する)。"""
    calls: list[str] = []
    real_geometry = root.geometry

    def recorder(spec=None):
        if spec is None:
            return real_geometry()
        calls.append(spec)
        return real_geometry(spec)

    monkeypatch.setattr(root, "geometry", recorder)
    return calls


def _height_of(geometry_spec: str) -> int:
    """"1100x816" 形式の文字列から高さ(816)だけを取り出す。"""
    return int(geometry_spec.split("x")[1])


# ---------------------------------------------------------------------------
# 正の対照: 受入条件そのもの
# ---------------------------------------------------------------------------


def test_kodawari_open_keeps_legacy_footer_geometry(hidden_root, tmp_path, monkeypatch):
    """受入条件「開いた状態で従来と同じ要素配置が保たれる」: こだわり設定を
    開いた状態でlayout_content_area()を呼ぶと、フッター行(pakList等)の
    y座標がdev#551着手前の絶対座標(_FOOTER_OPEN_GEOMETRY、旧`.place()`
    実測値そのまま)と完全一致し、要求されるウィンドウ高もOPEN基準
    (workarea.CONTENT_HEIGHT)のままであること。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        geometry_calls = _capture_geometry_calls(monkeypatch, hidden_root)
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)

        self._kodawari_open = True
        mw.MainWindow.layout_content_area(self)

        for key, geo in mw._FOOTER_OPEN_GEOMETRY.items():
            if key in ("updateLabel", "updateNowButton"):
                continue  # 既定非表示、本テストの対象外(別テストで扱う)
            info = self.widgets[key].place_info()
            assert int(info["y"]) == geo["y"], (
                f"{key}: 開いた状態のy座標が従来値({geo['y']})と一致しない"
                f"(実際: {info['y']})。受入条件「開時は従来どおり」に反する"
            )
        assert _height_of(geometry_calls[-1]) == workarea.CONTENT_HEIGHT
    finally:
        i18n.clear_registry()


def test_kodawari_closed_shrinks_window_height(hidden_root, tmp_path, monkeypatch):
    """受入条件「こだわり設定は閉時に領域が畳まれ、ウィンドウ高が縮む」の
    ウィンドウ高側。既定状態(こだわり設定=閉、self._kodawari_open=False)は
    OPEN基準(workarea.CONTENT_HEIGHT)より_KODAWARI_PANEL_DELTA分だけ
    要求ウィンドウ高が小さくなり、開いた状態へ戻すと元の高さに復帰する
    ことを検証する。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        geometry_calls = _capture_geometry_calls(monkeypatch, hidden_root)
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)
        assert self._kodawari_open is False  # 既定値の前提確認

        mw.MainWindow.layout_content_area(self)  # 既定(閉)
        closed_height = _height_of(geometry_calls[-1])

        self._kodawari_open = True
        mw.MainWindow.layout_content_area(self)
        open_height = _height_of(geometry_calls[-1])

        assert open_height == workarea.CONTENT_HEIGHT
        assert closed_height == workarea.CONTENT_HEIGHT - mw._KODAWARI_PANEL_DELTA
        assert closed_height < open_height, (
            "こだわり設定を閉じてもウィンドウ高が変わらない"
            "(issue #551 指摘2が再発している)"
        )

        # 再度閉じれば、元の縮んだ高さへちゃんと戻ること(往復の対称性)。
        self._kodawari_open = False
        mw.MainWindow.layout_content_area(self)
        assert _height_of(geometry_calls[-1]) == closed_height
    finally:
        i18n.clear_registry()


def test_kodawari_closed_shifts_footer_widgets_up(hidden_root, tmp_path, monkeypatch):
    """受入条件「こだわり設定は閉時に領域が畳まれ...(または下部要素が
    詰まる)」のフッターy座標側。パクリスト(pakList)・問い合わせボタン
    (reportButton)のy座標が、閉時はopen座標より_KODAWARI_PANEL_DELTA分
    だけ小さく(上に)なることを検証する。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        _capture_geometry_calls(monkeypatch, hidden_root)
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)

        mw.MainWindow.layout_content_area(self)  # closed (既定)
        closed_pak_y = int(self.widgets["pakList"].place_info()["y"])
        closed_report_y = int(self.widgets["reportButton"].place_info()["y"])

        self._kodawari_open = True
        mw.MainWindow.layout_content_area(self)  # open
        open_pak_y = int(self.widgets["pakList"].place_info()["y"])
        open_report_y = int(self.widgets["reportButton"].place_info()["y"])

        assert open_pak_y == mw._FOOTER_OPEN_GEOMETRY["pakList"]["y"]
        assert open_report_y == mw._FOOTER_OPEN_GEOMETRY["reportButton"]["y"]
        assert closed_pak_y == open_pak_y - mw._KODAWARI_PANEL_DELTA
        assert closed_report_y == open_report_y - mw._KODAWARI_PANEL_DELTA
        # 上の2行は「今のmw._KODAWARI_PANEL_DELTAの値なりに一致する」ことしか
        # 見ておらず、delta自体が0に壊れていても数式上は成立してしまう
        # (自己言及的で検出力が無い)。実際に「閉じたら開いているときより
        # 上に動く」ことそのものをハードコードで確かめる行を separately 置く
        # (負の対照test_negative_control_zero_delta_reproduces_the_original_bug
        # 参照。デルタを0へ壊すとこの2行こそが赤くなる)。
        assert closed_pak_y < open_pak_y, (
            "こだわり設定を閉じてもpakListのy座標が変わらない"
            "(issue #551 指摘2が再現している)"
        )
        assert closed_report_y < open_report_y, (
            "こだわり設定を閉じてもreportButtonのy座標が変わらない"
            "(issue #551 指摘2が再現している)"
        )
    finally:
        i18n.clear_registry()


def test_report_button_stays_within_clamped_window_when_closed(hidden_root, tmp_path, monkeypatch):
    """dev#662のクランプ機構(作業領域クランプ+スクロール)への副作用が無い
    ことの確認。「こだわり設定=閉」の縮んだウィンドウでも、report_button
    (#21 問い合わせボタン)は必ずウィンドウの要求高の範囲内に収まる
    (下端がウィンドウ外へ押し出されない、CLAUDE.md dev#661の実測事故
    クラスの再発防止確認)。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        geometry_calls = _capture_geometry_calls(monkeypatch, hidden_root)
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)
        mw.MainWindow.layout_content_area(self)  # closed (既定)

        closed_height = _height_of(geometry_calls[-1])
        report_info = self.widgets["reportButton"].place_info()
        report_bottom = int(report_info["y"]) + int(report_info["height"])

        assert report_bottom <= closed_height, (
            f"report_buttonの下端({report_bottom})が閉時の要求ウィンドウ高"
            f"({closed_height})の外に出てしまった"
        )
    finally:
        i18n.clear_registry()


def test_verified_version_label_open_matches_footer_geometry(hidden_root, tmp_path, monkeypatch):
    """dev#551是正(issue #551 2026-08-02 WSB検証コメント)の受入条件その1:
    こだわり設定を開いた状態では、verifiedVersionLabel(#26, dev#495)の
    y座標が_FOOTER_OPEN_GEOMETRYの宣言値(旧来の絶対座標=878)と一致し、
    見た目が従来から変わらないこと。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)

        self._kodawari_open = True
        mw.MainWindow.layout_content_area(self)

        info = self.widgets["verifiedVersionLabel"].place_info()
        assert int(info["y"]) == mw._FOOTER_OPEN_GEOMETRY["verifiedVersionLabel"]["y"]
    finally:
        i18n.clear_registry()


def test_verified_version_label_stays_within_window_when_closed(hidden_root, tmp_path, monkeypatch):
    """dev#551是正の受入条件その2(本題): こだわり設定が既定(閉)の状態でも、
    verifiedVersionLabelの下端が要求ウィンドウ高の範囲内に収まること
    (work\\wsb_gui_bundle_20260802\\RESULT.mdで実測された「閉状態では
    ラベルがウィンドウの82px下=画面外に配置され完全に非表示になる」の再発
    防止確認)。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        geometry_calls = _capture_geometry_calls(monkeypatch, hidden_root)
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)
        assert self._kodawari_open is False  # 既定値の前提確認

        mw.MainWindow.layout_content_area(self)  # closed (既定)
        closed_height = _height_of(geometry_calls[-1])

        info = self.widgets["verifiedVersionLabel"].place_info()
        label_bottom = int(info["y"]) + int(info["height"])

        assert label_bottom <= closed_height, (
            f"verifiedVersionLabelの下端({label_bottom})が閉時の要求"
            f"ウィンドウ高({closed_height})の外に出てしまった"
            "(issue #551 2026-08-02コメントの実測不具合が再発している)"
        )
        # y座標そのものも閉時はdeltaぶん上に詰まっていること(他フッター
        # 項目と同じ扱いになっている確認)。
        assert int(info["y"]) == (
            mw._FOOTER_OPEN_GEOMETRY["verifiedVersionLabel"]["y"] - mw._KODAWARI_PANEL_DELTA
        )
    finally:
        i18n.clear_registry()


def test_negative_control_label_missing_from_geometry_dict_goes_offscreen(
    hidden_root, tmp_path, monkeypatch
):
    """負の対照: verifiedVersionLabelを_FOOTER_OPEN_GEOMETRYから意図的に
    除外する(=is修正前の実際のバグ、dev#799時点でこのキーが辞書に無かった
    状態そのもの)と、上の正のテスト
    (test_verified_version_label_stays_within_window_when_closed)が検出
    しようとしている壊れ方——閉状態でラベルの下端がウィンドウ外に押し出される
    ——が実際に再現することを確認する。この前提が崩れていたら、上の正の
    テストには検出力が無いことになる。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        geometry_calls = _capture_geometry_calls(monkeypatch, hidden_root)
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)
        assert self._kodawari_open is False

        broken_geometry = {
            k: v for k, v in mw._FOOTER_OPEN_GEOMETRY.items() if k != "verifiedVersionLabel"
        }
        monkeypatch.setattr(mw, "_FOOTER_OPEN_GEOMETRY", broken_geometry)

        mw.MainWindow.layout_content_area(self)  # closed (既定) だが辞書からは除外済み
        closed_height = _height_of(geometry_calls[-1])

        info = self.widgets["verifiedVersionLabel"].place_info()
        label_bottom = int(info["y"]) + int(info["height"])

        assert label_bottom > closed_height, (
            "前提不成立: verifiedVersionLabelを辞書から除外したのに閉時の"
            "ウィンドウ内に収まってしまう(negative controlの模擬方法を"
            "見直すこと)"
        )
    finally:
        i18n.clear_registry()


def test_update_notice_uses_current_kodawari_delta_when_shown(hidden_root, tmp_path, monkeypatch):
    """dev#551で新設した_show_update_notice()側の配線: 更新通知を表示する
    瞬間に、その時点のこだわり状態(閉=deltaあり)を反映した座標へ配置される
    こと。反映していないと、パネルが閉じてウィンドウが縮んでいる間に通知が
    出た場合、縮んだウィンドウの外(見えない場所)へ配置されてしまう。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        geometry_calls = _capture_geometry_calls(monkeypatch, hidden_root)
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)
        mw.MainWindow.layout_content_area(self)  # closed (既定)
        closed_height = _height_of(geometry_calls[-1])

        mw.MainWindow._show_update_notice(self, "v9.9.9")

        label_info = self.widgets["updateLabel"].place_info()
        button_info = self.widgets["updateNowButton"].place_info()
        assert int(label_info["y"]) == (
            mw._FOOTER_OPEN_GEOMETRY["updateLabel"]["y"] - mw._KODAWARI_PANEL_DELTA
        )
        button_bottom = int(button_info["y"]) + int(button_info["height"])
        assert button_bottom <= closed_height, (
            "更新通知ボタンの下端が、閉時の縮んだウィンドウの外に出てしまった"
        )
    finally:
        i18n.clear_registry()


# ---------------------------------------------------------------------------
# 負の対照: 詰め処理(delta計算)を意図的に無効化すると、上のテストが
# 検出しようとしている壊れ方(issue #551 指摘2そのもの)が実際に
# 再現することの確認。
# ---------------------------------------------------------------------------


def test_negative_control_zero_delta_reproduces_the_original_bug(hidden_root, tmp_path, monkeypatch):
    """負の対照(test_workarea.pyのnegative control形式を踏襲): モジュール
    レベル定数`_KODAWARI_PANEL_DELTA`を意図的に0固定にする(=dev#551着手前の
    実際の不具合、こだわりパネルの開閉がウィンドウ高・フッターy座標に
    一切影響しない状態を再現する)と、上の正のテスト
    (test_kodawari_closed_shrinks_window_height)が検出しようとしている
    壊れ方——開閉でウィンドウ高もフッターy座標も変わらない——が実際に
    再現することを、まずこの負の対照自身で確認する。この前提が崩れて
    いたら、上の正のテストにも検出力が無いことになる。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        geometry_calls = _capture_geometry_calls(monkeypatch, hidden_root)
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)
        assert self._kodawari_open is False

        monkeypatch.setattr(mw, "_KODAWARI_PANEL_DELTA", 0)

        mw.MainWindow.layout_content_area(self)  # closed (既定) だが delta=0
        closed_height = _height_of(geometry_calls[-1])
        closed_pak_y = int(self.widgets["pakList"].place_info()["y"])

        self._kodawari_open = True
        mw.MainWindow.layout_content_area(self)
        open_height = _height_of(geometry_calls[-1])
        open_pak_y = int(self.widgets["pakList"].place_info()["y"])

        assert closed_height == open_height, (
            "前提不成立: delta=0に壊したのに閉/開でウィンドウ高が変わって"
            "しまう(negative controlの模擬方法を見直すこと)"
        )
        assert closed_pak_y == open_pak_y, (
            "前提不成立: delta=0に壊したのに閉/開でpakListのy座標が変わって"
            "しまう(negative controlの模擬方法を見直すこと)"
        )
    finally:
        i18n.clear_registry()
