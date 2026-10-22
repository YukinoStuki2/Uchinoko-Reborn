# test_unity_export_stacktrace_dev696.py -- dev#696受入条件:
#   Unity輸出が失敗したとき、失敗箇所を特定できる情報(スタックトレース)が
#   ユーザーの「ログをコピー」(診断テキスト)に残ること。
#
# 背景: 退役C#版(app\DiveToPalworld.cs)のログ抜粋正規表現
#   `D2P:|Exception:|error CS\d|UnityException`
# は「一致した行そのものだけ」を拾い、Unityのスタックトレース行
# (`  at Class.Method (...) in <file>:line`、いずれのキーワードにも一致しない)を
# 文脈ごと落としていた(dev#518診断ログの決め手不足の根因)。
#
# 調査結果(C:\P\Work\DiveToPalworld\work\wp_696_progress.md §1):
# py版(app_py)はこの独自フィルタを一切持たない。
# pipeline_runner.ProcessHandle._read_loop()はps1子プロセスのstdoutを1行ずつ
# そのままon_lineへ渡し、main_window._on_pipeline_line()は##PROGRESS##/
# ##AVATAR_WARNING##行だけを個別処理し、それ以外は無条件でself._log(clean)へ
# 落ちてlog_box(=_build_diagnostics_text()の材料そのもの)へ追記される。
# つまりpy版はキーワード一致行だけを拾う独自ロジックを持たない
# (=旧C#版の穴を構造的に踏んでいない)。
#
# このテストは「py版アプリ側の透過性」を固定する回帰防止テスト。将来
# 誰かが旧C#版のような「キーワード一致行だけ拾う」フィルタを_on_pipeline_line
# 付近に再導入すると、このテストが真っ先に赤くなる。
#
# 実tkウィンドウは一切開かない(test_gui_log_robustness.pyと同じくフェイクself)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pipeline_runner as pr  # noqa: E402
from ui import main_window as mw  # noqa: E402


class _FakeLogBox:
    """tkinter.Text互換の最小フェイク。実ウィジェットは一切生成しない。"""

    def __init__(self) -> None:
        self.inserted: list[str] = []

    def configure(self, **_kwargs) -> None:
        return None

    def insert(self, _index: str, text: str) -> None:
        self.inserted.append(text)

    def see(self, _index: str) -> None:
        return None

    def get(self, _start: str, _end: str) -> str:
        return "".join(self.inserted)


class _FakeSelfForPipelineLine:
    """MainWindow._on_pipeline_lineを束縛せずに呼ぶための最小self。
    Unity輸出フェーズ相当(_active_phase=PHASE_UNITY_EXPORT)で使う。"""

    def __init__(self) -> None:
        self.log_box = _FakeLogBox()
        self._active_phase = pr.PHASE_UNITY_EXPORT
        self._unity_export_last_output_at = None
        self._pipeline_warnings: list[str] = []
        self._active_handle = None
        self._early_preview_loaded_this_run = False
        self.widgets: dict = {}

    def _log(self, text: str, *, gui: bool = True) -> None:
        # 実アプリのMainWindow._logを直接束縛して使う(print()経由の副作用も
        # 含めて本番と同じ経路を通す。cp932/None等の防御は別テストの対象なので
        # ここではsys.stdoutに触らない単純な経路を想定)。
        mw.MainWindow._log(self, text, gui=gui)


# ---------------------------------------------------------------------------
# dev#696が問題にしていた「Unityのスタックトレース行」の実例(dev#518診断ログ・
# export_from_unity.ps1のExcerpt出力形式を模したもの)。
# いずれの行も旧C#版の正規表現 D2P:|Exception:|error CS\d|UnityException の
# どれにも一致しない(意図的に「一致しない行」だけを選んでいる)。
# ---------------------------------------------------------------------------
_STACK_TRACE_LINES_NO_KEYWORD_MATCH = [
    "  at UnityEditor.Formats.Fbx.Exporter.ModelExporter.ExportObjects "
    "(UnityEngine.Object[] objects) [0x00010] in <hash>:0",
    "  at UnityEditor.Formats.Fbx.Exporter.ModelExporter.ExportObject "
    "(System.String filePath, UnityEngine.Object singleObject) [0x00034] in <hash>:0",
    "  at System.Reflection.MethodBaseInvoker.InvokeWithNoArgs "
    "(System.Object obj, BindingFlags invokeAttr) [0x00000] in <filename unknown>:0",
    "  at DiveToPalworldExporter.ExportUnifiedFbx (UnityEngine.GameObject target, "
    "System.String path) [0x00120] in Assets/Editor/D2P_TempExporter/DiveToPalworldExporter.cs:1020",
    "  --- End of inner exception stack trace ---",
]


def _simulate_export_from_unity_failure_excerpt() -> list[str]:
    """export_from_unity.ps1のExcerpt出力(dev#696修正後、-Context 0,40)を
    模した行列。1行ずつProcessHandle._read_loopが渡すのと同じ粒度にしてある。"""
    lines = [
        "Export failed - see log: C:\\work\\out\\unity_export.log",
        "--- Excerpt around the failure (full text is in the log file above) ---",
        "NullReferenceException: Object reference not set to an instance of an object",
    ]
    lines.extend(_STACK_TRACE_LINES_NO_KEYWORD_MATCH)
    lines.append("--- End of excerpt ---")
    return lines


# ---------------------------------------------------------------------------
# (1) 正の対照: キーワードに一致しないスタックトレース行も、他の行と同じく
#     全てログ欄(=診断テキストの材料)へ透過すること
# ---------------------------------------------------------------------------


def test_stack_trace_lines_reach_log_box_verbatim():
    fake_self = _FakeSelfForPipelineLine()
    failure_lines = _simulate_export_from_unity_failure_excerpt()

    for line in failure_lines:
        mw.MainWindow._on_pipeline_line(fake_self, line)

    logged_text = "".join(fake_self.log_box.inserted)

    for line in failure_lines:
        assert line in logged_text, (
            "dev#696回帰: 行がログ欄(=診断テキストの材料)へ届いていない: " + repr(line)
        )

    # とくにキーワード非一致のスタックトレース行(旧C#版なら丸ごと消えていた行)を
    # 個別に強調して検証する。
    for stack_line in _STACK_TRACE_LINES_NO_KEYWORD_MATCH:
        for keyword in ("D2P:", "Exception:", "error CS", "UnityException"):
            assert keyword not in stack_line, (
                "テストデータ不備: このスタックトレース行はキーワード'"
                + keyword + "'に一致してしまっている(意図的な非一致サンプルでなければ"
                "旧C#版バグとの対比にならない): " + repr(stack_line)
            )
        assert stack_line in logged_text, (
            "dev#696の症状そのものが再発している: キーワードに一致しないスタック"
            "トレース行がログ欄から欠落した: " + repr(stack_line)
        )


# ---------------------------------------------------------------------------
# (2) 負の対照(受入条件2、必須): 正常終了時にはこの追加出力が現れず、
#     ログが無意味に肥大しないこと
# ---------------------------------------------------------------------------


def test_normal_success_output_has_no_excerpt_block():
    fake_self = _FakeSelfForPipelineLine()
    success_lines = [
        "D2P: prefab解決 path=Assets/Avatar.prefab guid=abcdef1234567890",
        "D2P: NDMFベイク完了",
        "D2P: PostBakeサニタイズ完了、12件除去",
        "D2P_EXPORT_DONE C:\\work\\out",
        "",
        "Export complete: C:\\work\\out",
    ]

    for line in success_lines:
        mw.MainWindow._on_pipeline_line(fake_self, line)

    logged_text = "".join(fake_self.log_box.inserted)

    for banned in (
        "Excerpt around the failure",
        "End of excerpt",
        "Export failed",
        "NullReferenceException",
    ):
        assert banned not in logged_text, (
            "負の対照が破れている: 正常終了なのに失敗時専用の文言が"
            "ログへ現れている: " + repr(banned)
        )

    # 通常出力自体はそのまま残ること(透過そのものは失敗時専用の挙動ではない)
    for line in success_lines:
        if line:
            assert line in logged_text


# ---------------------------------------------------------------------------
# (3) export_from_unity.ps1側: Context行数がしきい値以上であること
#     (dev#696対応: 15->40。「絞りすぎて元の穴を再現しない」ことの構造的な担保)
# ---------------------------------------------------------------------------


def test_export_from_unity_ps1_context_lines_are_generous_enough():
    ps1_path = os.path.join(
        os.path.dirname(_APP_PY_DIR), "pipeline", "cli", "export_from_unity.ps1"
    )
    assert os.path.isfile(ps1_path), "export_from_unity.ps1が無い: " + ps1_path
    with open(ps1_path, encoding="utf-8") as f:
        content = f.read()

    import re

    # dev#1262: 「Exception|error CS」固定文字列だったパターンに
    # 「conflicts with|immutable folder」(UniVRM二重導入検出、export_from_unity.ps1
    # のコメント参照)が追加された。パターン文字列全体は`"([^"]+)"`で緩く受け止め、
    # 元のdev#696受入条件(Exception/error CSが引き続き含まれる・Context行数が
    # 十分)だけを厳密に検査する。
    m = re.search(r'Select-String -LiteralPath \$log -Pattern "([^"]+)" -Context 0,(\d+)', content)
    assert m, (
        "export_from_unity.ps1の失敗時Excerpt抽出(Select-String -Context)行が"
        "見つからない(実装が変わった?正規表現の更新が必要)"
    )
    pattern_str = m.group(1)
    for required in ("Exception", "error CS"):
        assert required in pattern_str, (
            "dev#696: Excerpt抽出パターンから'{}'が消えている(コンパイルエラー/"
            "例外の検出漏れになる): {!r}".format(required, pattern_str)
        )
    context_after = int(m.group(2))
    assert context_after >= 30, (
        "dev#696: -Contextの後続行数が{}に減っている(15行だった旧値相当まで"
        "戻すと、Reflection越しの深いコールスタックで実際の発生箇所に届く前に"
        "打ち切られる=元の穴が再現する)。増やす分には問題ないが、30行未満への"
        "縮小は根拠を示すこと".format(context_after)
    )


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
