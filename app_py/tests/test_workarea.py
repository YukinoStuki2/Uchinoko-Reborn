# test_workarea.py -- dev#662受入条件③: 実画面不要のロジックテスト
# (ui/workarea.py は tkinter に一切依存しない純ロジックとして切り出してある
# ため、本ファイルは tk.Tk() は元より tkinter そのものすら import しない)。
#
# 対象: py版GUI(app_py/ui/main_window.py)の起動時ウィンドウ寸法が、
# 1080p+表示スケール125%等の狭い作業領域(タスクバー除く)でも
# report_button(#21「問い合わせ」ボタン、main_window.py _build_widgets()内
# `report_button.place(x=890, y=760, width=180, height=28)`)へ必ず到達
# できることの検証。実証済みfailure class: KSP4JVH6(C#旧版v2.0.0、1080p画面で
# 問い合わせボタンが画面外)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

from ui import workarea  # noqa: E402

# main_window.py _build_widgets() の report_button.place() 実測値
# (dev#662着手時点。座標がずれた場合はこの定数も追随させること)。
_REPORT_BUTTON_Y = 760
_REPORT_BUTTON_HEIGHT = 28
_REPORT_BUTTON_BOTTOM = _REPORT_BUTTON_Y + _REPORT_BUTTON_HEIGHT  # 788


# ---------------------------------------------------------------------------
# compute_clamp: 通常環境では挙動不変
# ---------------------------------------------------------------------------


def test_compute_clamp_keeps_fixed_size_on_plenty_work_area():
    """1920x1080デスクトップ相当(タスクバー引いても十分)では、従来固定値
    (1100x930)のまま・needs_scroll=Falseで、見た目を一切変えない。"""
    work_area = (1920, 1040)
    result = workarea.compute_clamp(work_area)
    assert result == workarea.ClampResult(workarea.CONTENT_WIDTH, workarea.CONTENT_HEIGHT, False)


def test_compute_clamp_falls_back_to_fixed_size_when_work_area_unknown():
    """work_area取得不能(None、非Windows・API失敗)は安全側=従来どおり
    (挙動不変)。取れない環境で誤って縮める方が害が大きい、という設計判断。"""
    result = workarea.compute_clamp(None)
    assert result == workarea.ClampResult(workarea.CONTENT_WIDTH, workarea.CONTENT_HEIGHT, False)


def test_compute_clamp_never_shrinks_window_width():
    """幅はクランプ対象外(workarea.compute_clamp docstring参照: DESIGN.mdの
    place()絶対座標は右端でもx=1070程度までしか使わず、幅方向の水平スクロール
    手段を用意していないため、幅を縮めると到達不能な領域を作ってしまう)。
    極端に狭い作業領域でも window_width は常に CONTENT_WIDTH のまま。"""
    result = workarea.compute_clamp((500, 1040))
    assert result.window_width == workarea.CONTENT_WIDTH


# ---------------------------------------------------------------------------
# compute_clamp: 狭い作業領域での防御(受入条件②の本体)
# ---------------------------------------------------------------------------


def test_compute_clamp_engages_scroll_when_work_area_too_short():
    """issue #662が想定する1080p+125%スケール相当(作業領域高さがcontentの
    930pxに足りない)では、ウィンドウ高さを作業領域に収め、needs_scroll=True
    を返して呼び出し側にスクロール可能なコンテナの構築を要求する。"""
    work_area = (1280, 700)
    result = workarea.compute_clamp(work_area)
    assert result.needs_scroll is True
    assert result.window_height < workarea.CONTENT_HEIGHT
    assert result.window_height <= 700 - workarea.SAFETY_MARGIN


def test_compute_clamp_never_goes_below_minimum_height():
    """異常値(極端に小さいwork_area、テスト用の偽装値含む)でもウィンドウが
    潰れて操作すらできない高さにはしない、という下限保証。"""
    result = workarea.compute_clamp((800, 10))
    assert result.window_height == workarea.MIN_WINDOW_HEIGHT
    assert result.needs_scroll is True


# ---------------------------------------------------------------------------
# 負の対照: 防御(クランプ+needs_scroll)が無いとreport_buttonは到達不能、
# 防御があれば到達可能になる、を機械的に示す(受入条件③)。
# ---------------------------------------------------------------------------


def test_report_button_unreachable_without_clamp_negative_control():
    """負の対照: 「防御なし」(旧実装=常にCONTENT_HEIGHT固定・スクロール無し)
    を模した計算だと、report_buttonの下端(788px)が作業領域の外に出てしまう
    (到達不能)ケースが実在することを、まずこのテスト自身が確認する。
    この前提が崩れていたら、そもそもissue #662の再現条件(の模擬)が成立して
    いないので、以降の「防御あり」比較に意味が無い。"""
    cramped_work_area = (1280, 700)

    # 旧実装(防御なし)を模した計算: ウィンドウは常にCONTENT_HEIGHT固定で
    # スクロール手段が無いため、可視域は work_area の高さで頭打ちになる。
    legacy_visible_bottom = min(workarea.CONTENT_HEIGHT, cramped_work_area[1])
    assert legacy_visible_bottom < _REPORT_BUTTON_BOTTOM, (
        "前提不成立: この作業領域では旧実装でもreport_buttonに届いてしまう"
        "(テストのcramped_work_area値を見直すこと)"
    )


def test_report_button_reachable_with_clamp_and_scroll():
    """上のnegative controlと同じcramped_work_areaで、新実装
    (compute_clamp+needs_scroll)ならreport_buttonへ到達できることを示す。
    到達可能性の根拠: needs_scroll=Trueのときcontentフレームの
    scrollregionはCONTENT_HEIGHT(930)分確保される(main_window.py
    _build_content_container()参照)。ウィンドウ自体の可視高さ
    (window_height)より下にある座標も、Scrollbar操作でviewport内へ
    持ってこられる=「必ず到達できる」の実体。"""
    cramped_work_area = (1280, 700)
    result = workarea.compute_clamp(cramped_work_area)

    # 可視域(クランプ後のウィンドウ高さ)だけではreport_buttonの下端に
    # 届かない、という状況そのものは変わらない(だからneeds_scrollが立つ)。
    assert result.window_height < _REPORT_BUTTON_BOTTOM
    # しかしneeds_scroll=Trueが立っており、呼び出し側(main_window.py)は
    # これを見てCanvas+Scrollbarでラップする契約になっている
    # (_build_content_container()のneeds_scroll分岐)。
    assert result.needs_scroll is True


def test_report_button_within_content_height_bound():
    """report_button自体がCONTENT_HEIGHT(930)の範囲内に収まっている前提を
    固定する(そうでなければscrollregion=CONTENT_HEIGHTでも届かない)。"""
    assert _REPORT_BUTTON_BOTTOM <= workarea.CONTENT_HEIGHT


# ---------------------------------------------------------------------------
# enable_dpi_awareness / get_work_area: 失敗しても起動を止めない
# ---------------------------------------------------------------------------


def test_enable_dpi_awareness_does_not_raise():
    """Windows専用APIの呼び出しだが、失敗しても例外を外へ漏らさない
    (main.pyの起動シーケンスを止めてはならない、という設計契約)。"""
    workarea.enable_dpi_awareness()  # 例外が出ないことそのものが受入条件


def test_get_work_area_returns_none_or_positive_tuple():
    """非Windows/API失敗時はNone、成功時は(幅, 高さ)ともに正の整数、以外の
    戻り値は仕様違反(compute_clampがNoneチェック以外を想定していないため)。"""
    result = workarea.get_work_area()
    if result is not None:
        width, height = result
        assert width > 0
        assert height > 0
