# workarea.py -- dev#662: DPI awareness宣言 + 作業領域(タスクバー除く)クランプ計算。
#
# 背景(issue #662): 1080p+表示スケール125%(ノートPC既定で多い)環境で、
# tkinterがDPI非対応のままだと物理ピクセル換算でウィンドウ下端(問い合わせ
# ボタン等)が画面外へはみ出し操作不能になる。実証クラス: KSP4JVH6(C#旧版
# v2.0.0、1080p画面で問い合わせボタンが画面外)。C#版(app\DiveToPalworld.cs/
# app.manifest)はDPI awareness宣言を意図的に持たない
# (app.manifest冒頭コメント: 「DPI/OS互換シム等、挙動に影響しうる追加要素は
# 入れない」)ため、本ファイルはC#版からの移植ではなく新規の防御機構である
# (CLAUDE.md「GUIパリティ系はC#が正」の対象外、worktree進捗ログ参照)。
#
# tkinter(ui.main_window)への依存を一切持たない純ロジックとして切り出してある
# (受入条件③: 実画面を開かない単体テストで検証できるようにするため)。
from __future__ import annotations

import ctypes
import os
from typing import NamedTuple, Optional

# _build_widgets()が組み立てるコンテンツの基準サイズ(旧固定 root.geometry("1100x930")
# と同じ値。DESIGN.md §4.2の絶対座標place()群はこのサイズを前提に書かれている)。
#
# dev#551(2026-08-02): CONTENT_HEIGHTを930から900へ縮小。オーナー実機確認で
# 「フッターの空白エリアが広い」と指摘された(issue #551 指摘1)。本ファイルの
# place()絶対座標群のうち最も下にある要素はupdateNowButton(main_window.py
# _build_widgets() `update_now_button.place(x=12, y=848, width=130, height=22)`、
# 下端870px。更新通知が無い間は非表示)で、900pxならこれより30px下の余白で
# 収まる(通常時に最も下まで表示されるreportButton/autoApplyCheck系は下端
# 814pxなので余白86px)。旧930pxの余白116〜60pxから縮めた値で、report_button
# など既存要素はどれも新しい900pxの内側に収まっている(test_workarea.py
# test_report_button_within_content_height_boundが両方向で検証)。
# こだわり設定パネルの開閉に応じた追加の高さ調整(パネル1個ぶんの
# 縮小・復元)はmain_window.py側(_KODAWARI_PANEL_DELTA)がこの値を土台に
# 行う(dev#551 指摘2、workarea.py自体はこだわり状態を知らない純ロジックの
# ままにするため、ここでは変更しない)。
CONTENT_WIDTH = 1100
CONTENT_HEIGHT = 900

# 作業領域ぎりぎりに合わせるとウィンドウの境界線自体がタスクバーへわずかに
# 重なる環境が観測されているため、安全側に余裕を持たせる(px)。
SAFETY_MARGIN = 8

# 極端に小さい作業領域(異常値・テスト用の偽装値)でもウィンドウとして最低限
# 意味を持つ高さは確保する。
MIN_WINDOW_HEIGHT = 150

# SystemParametersInfoW の SPI_GETWORKAREA (winuser.h)
_SPI_GETWORKAREA = 0x0030
# SetProcessDpiAwareness (shcore.dll) の PROCESS_SYSTEM_DPI_AWARE
# (Per-Monitor V2ではなくSystem DPI Awareを選ぶ理由: tkinterはPer-Monitor DPI変更
# 通知(WM_DPICHANGED)に対応しておらず、モニタ間移動時の再レイアウトが必要になる
# Per-Monitor対応は本issueのKISS方針(「最小の方法」)に合わない。System DPI Aware
# はプロセス起動時の1回宣言のみで済み、複数モニタでもプライマリ側のスケールに
# 合わせて物理ピクセルで正しく描画される=今回のバグクラスへの対処として十分)。
_PROCESS_SYSTEM_DPI_AWARE = 1


def enable_dpi_awareness() -> None:
    """起動最早期(tk.Tk()生成より前)に一度だけ呼ぶ想定(呼び出し元: main.py)。

    Windows専用。shcore.SetProcessDpiAwareness(System DPI Aware)を試み、
    失敗時(Windows 8.1未満等)はuser32.SetProcessDPIAware()へフォールバックする。
    非Windows環境・API呼び出し失敗のいずれでも例外を握って何もしない
    (この防御機構自体がGUI起動を止めてはならない、CLAUDE.md「失敗しても起動を
    止めない」方針と同じ)。tk.Tk()生成後に呼んでも効果が無い(Tcl/Tkは最初の
    ウィンドウ生成時にプロセスのDPI awareness状態を読み取るため)。
    """
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(_PROCESS_SYSTEM_DPI_AWARE)  # type: ignore[attr-defined]
        return
    except Exception:  # noqa: BLE001
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def get_work_area() -> Optional[tuple[int, int]]:
    """プライマリモニタの作業領域(タスクバー等を除く)を(幅, 高さ)の物理px
    タプルで返す。取得できない場合(非Windows・API失敗)はNone。

    enable_dpi_awareness()を先に呼んでおくことが前提(呼んでいないプロセスでは
    DPI非対応時のスケーリングにより、実際の描画と数値がずれた値になりうる。
    それでも失敗はしない=呼び出し順を守らなくてもクラッシュはしない設計)。
    """
    if os.name != "nt":
        return None
    try:
        rect = _RECT()
        ok = ctypes.windll.user32.SystemParametersInfoW(  # type: ignore[attr-defined]
            _SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
        )
        if not ok:
            return None
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return None
        return width, height
    except Exception:  # noqa: BLE001
        return None


class ClampResult(NamedTuple):
    window_width: int
    window_height: int
    needs_scroll: bool


def compute_clamp(
    work_area: Optional[tuple[int, int]],
    content_width: int = CONTENT_WIDTH,
    content_height: int = CONTENT_HEIGHT,
    margin: int = SAFETY_MARGIN,
) -> ClampResult:
    """作業領域の実測値から、実際に使うウィンドウ寸法を決める(受入条件②の
    ロジック本体、実画面非依存の純関数)。

    幅(window_width)は常に content_width のまま変更しない: DESIGN.md §4.2の
    place()絶対座標は右端でもx=1070程度までしか使っておらず、幅方向で
    実機が足りなくなる環境は現実的に考えにくい。issue #662の実証クラス
    (KSP4JVH6)も1080p画面の**高さ方向**の切れであり、幅側には対応する水平
    スクロールの仕組みを用意していない(用意すればかえって「クランプした
    のに到達手段が無い」領域を作ってしまう)。KISS方針(issue本文の
    「高さクランプ+スクロール」)に合わせ、高さのみをクランプ対象にする。

    - work_area が None(非Windows・取得失敗)なら、従来どおり
      content_height を固定採用し、needs_scroll=False
      (安全側=挙動不変。取得できない環境で誤ってウィンドウを縮める方が害が
      大きいと判断)。
    - work_area が取れて、かつ content_height より作業領域の高さが小さい
      場合のみウィンドウ高さを作業領域(-margin)に合わせて縮小し、
      needs_scroll=True を返す(呼び出し側はこのフラグでスクロール可能な
      コンテナを組み立てる)。
    - 作業領域の高さが content_height 以上に十分ある場合は縮小せず、
      needs_scroll=False(見た目を変えない)。
    """
    if work_area is None:
        return ClampResult(content_width, content_height, False)

    avail_h = max(0, work_area[1] - margin)
    win_h = min(content_height, avail_h) if avail_h > 0 else content_height
    win_h = max(win_h, MIN_WINDOW_HEIGHT)

    needs_scroll = win_h < content_height
    return ClampResult(content_width, win_h, needs_scroll)
