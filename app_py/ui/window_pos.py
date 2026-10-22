# window_pos.py -- 子ウィンドウ(Toplevel)を親窓に重ねる位置へ出すための
# 共通ヘルパー(2026-08-08、オーナー官能検査中の指摘対応)。
#
# オーナー指摘: 「ラボサブウィンドウが画面の左上に出るのが使いにくい。
# メインに重なるように」。tk.Toplevel()は既定でウィンドウマネージャ任せの
# 位置(環境によっては常に画面左上)に出るため、親窓の座標へ固定オフセットを
# 足した位置を明示的にgeometry()で指定する。
#
# offset_position()は純関数(tkinter非依存の整数計算のみ)でテストできる。
# apply_offset_position()がtk.Toplevel/tk.Misc実物への配線(GUI起動が要る側)。

from __future__ import annotations

import tkinter as tk
from typing import Tuple

# ラボ窓・装備限定ダイアログ・drop_bonesダイアログの全てで共通に使う既定値。
# 「メインに重なるように」という要望であって正確な位置合わせの要求ではない
# ため(ラボ憲章②「雑な実装でよい」も踏まえ)、キリのよい固定値で足りる。
DEFAULT_OFFSET = 40


def offset_position(parent_x: int, parent_y: int, offset: int = DEFAULT_OFFSET) -> Tuple[int, int]:
    """親窓の左上座標(winfo_rootx()/winfo_rooty()相当)にoffsetを足した、
    子窓の左上座標を返す。GUI非依存の純関数。マルチモニタ構成で親のx/yが
    負値になるケースもそのまま加算するだけでよい(offsetは常に正の値で
    「少し右下にずらしてメインへ重ねる」意図)。"""
    return parent_x + offset, parent_y + offset


def apply_offset_position(dlg: tk.Misc, parent: tk.Misc, offset: int = DEFAULT_OFFSET) -> None:
    """dlg(tk.Toplevel)を親窓に重なる位置へ移動する。

    既にdlg.geometry("WxH")でサイズを指定してある場合でも、本関数が呼ぶのは
    位置だけを表す"+X+Y"形式なので、既存のサイズ指定を上書きしない
    (Tkのgeometry()は"+X+Y"のみを渡すと現在のサイズを保ったまま位置だけ
    動かす)。

    parent.winfo_rootx()/winfo_rooty()の取得に失敗した場合(親が既に破棄
    済み等)は静かに何もしない(ラボ機能の付随処理であり、位置決めの失敗で
    ダイアログ自体を開けなくしてはならない)。"""
    try:
        parent.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
    except tk.TclError:
        return
    x, y = offset_position(px, py, offset)
    dlg.geometry(f"+{x}+{y}")
