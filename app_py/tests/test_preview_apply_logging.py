# test_preview_apply_logging.py -- dev#1103受入条件(実報告TFVNM33V)。
#
# 背景: 変換成功・preflight PASS・Blender側render_preview.pyもOKなのに、
# GUIのプレビューが表示されないという報告に対し、GUI側
# `_apply_previews`/`_set_preview_widget`(main_window.py)が成功時に一切
# ログを残さない設計だったため、「表示を試みて成功した」のか「そもそも
# 試みなかった(静かに未反映)」のかがログから区別できないと判明した。
#
# 本ファイルは、`_apply_previews`が呼ばれるたびに front/side それぞれに
# ついて「適用したか・no-opならその理由」を必ず1行残すことを検証する
# (実tk画像デコードは_set_preview_widgetの担当領域であり、本ファイルは
# その手前の分岐ロジック=「何を試みたか」のログ粒度だけを対象にする。
# フェイクselfで_set_preview_widget自体をスタブ化し、実tkウィンドウは
# 一切開かない、既存test_main_window_restore.pyと同じ流儀)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

from ui import main_window as mw  # noqa: E402


class _FakeSelf:
    """MainWindow._apply_previewsを束縛前のまま呼ぶための最小フェイクself
    (既存test_main_window_restore.pyの手法を踏襲)。_set_preview_widgetは
    実tk.PhotoImageデコードを伴うため、呼び出し記録だけのスタブに差し替える
    (試験対象は_apply_previews内のno-op判定・ログ出力ロジックのみ)。"""

    _apply_previews = mw.MainWindow._apply_previews

    def __init__(self) -> None:
        self.logs: list[str] = []
        self.set_calls: list[tuple[str, str]] = []

    def _log(self, text: str) -> None:
        self.logs.append(text)

    def _set_preview_widget(self, widget_key: str, image_path: str) -> None:
        self.set_calls.append((widget_key, image_path))


def test_apply_previews_both_present_calls_widget_and_logs_applied_true():
    """正の対照: front/side双方が解決済みなら、両方ともウィジェット反映が
    呼ばれ、no-opログは出ず、サマリ行はfront=True side=Trueになる。"""
    self = _FakeSelf()
    self._apply_previews({"front": "/x/front.png", "side": "/x/side.png"})

    assert self.set_calls == [
        ("previewFront", "/x/front.png"),
        ("previewSide", "/x/side.png"),
    ]
    assert not any("no-op" in line for line in self.logs)
    assert any("applied: front=True side=True" in line for line in self.logs)


def test_apply_previews_missing_files_are_noop_with_reason_in_log():
    """(b) プレビューファイル欠落時(load_previewsがNoneを返した場合)、
    ウィジェット反映は一切呼ばれず、front/sideそれぞれについてno-opの理由が
    ログへ写ること。これが本WPの核心(「試みて成功」と「静かに未反映」を
    ログだけで区別できるようにする)。"""
    self = _FakeSelf()
    self._apply_previews({"front": None, "side": None})

    assert self.set_calls == []
    front_noop = [line for line in self.logs if "no-op front" in line]
    side_noop = [line for line in self.logs if "no-op side" in line]
    assert len(front_noop) == 1
    assert len(side_noop) == 1
    assert "front=None" in front_noop[0]
    assert "side=None" in side_noop[0]
    assert any("applied: front=False side=False" in line for line in self.logs)


def test_apply_previews_partial_mix_logs_one_noop_and_one_applied():
    """front有り/side無しの混在(例: Female専用生成でsideファイルだけ何らかの
    理由で欠けたケース)でも、front側は適用されside側だけno-opログが残る
    ことを確認する(全か無かではなく、キー単位で独立に判定されること)。"""
    self = _FakeSelf()
    self._apply_previews({"front": "/x/front.png", "side": None})

    assert self.set_calls == [("previewFront", "/x/front.png")]
    assert not any("no-op front" in line for line in self.logs)
    assert any("no-op side" in line for line in self.logs)
    assert any("applied: front=True side=False" in line for line in self.logs)
