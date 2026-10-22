# test_inquiry_dev1102_unity_export_attachment_gate.py -- dev#1102単体テスト。
#
# 背景(実報告KRFHQR2K、v2.3.13): MainWindow._read_full_log_attachment_text()は
# unity_exportディレクトリの添付可否を「vrmBoxが埋まっているか」(=vrm_path)
# だけで判定していた。vrmBoxはUnity輸出**成功後**にしか埋まらない
# (_on_unity_export_exit()はcode!=0の失敗時に_set_vrm_pathを呼ばずreturnする、
# main_window.py L.2943-2966参照)ため、輸出失敗時は必ずゲートが偽になり、
# 原因究明に最も必要なunity_export.logがそもそも添付候補にすら入らなかった
# (dev#921「二層化添付」の第2層がこの分岐だけ空振り)。
#
# 修正(第1版・master-writerレビューで退行指摘→是正): unity_exportディレクトリの
# 収集条件を「_pending_prefab_export_path があればそれを優先(今セッションで
# 輸出を試みた場合、成功/失敗問わず最新の試行) → 無ければ従来どおり vrm_path
# へフォールバック」の2段判定にする。
#
# 第1版(_pending_prefab_export_path単独)は、_on_prefab_selected()を経由せず
# vrmBoxだけが正当に埋まる2経路(キャッシュ鮮度ヒット早期return/
# _restore_last_vrm_on_startup())で、前回成功セッション由来のunity_export.log
# を取りこぼす退行を生んでいた。フォールバックにより、今セッションで輸出を
# 試みていない(復元・キャッシュヒットのみの)場合は旧実装と同じ挙動に戻る。
#
# 実tkウィンドウは開かない: 既存test_guard_dialogs.py/test_prefab_gui_cache.pyと
# 同じ「フェイクself」流儀(mw.MainWindow.__new__()で束縛前selfを作り、
# 必要な属性だけ後付けする)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pipeline_runner as pr  # noqa: E402
from ui import main_window as mw  # noqa: E402


class _FakeEntry:
    """tkinter.Entry互換の最小フェイク(.get()のみ、既存test_guard_dialogs.py
    の_FakeEntryと同じ形)。"""

    def __init__(self, text: str = "") -> None:
        self._text = text

    def get(self) -> str:
        return self._text


def _bare_window():
    """__init__を通さずMainWindowインスタンスだけ得る(既存の慣例)。"""
    return mw.MainWindow.__new__(mw.MainWindow)


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


_PREFAB_PATH = r"C:\UnityP\SampleProject\Assets\Avatar\SampleAvatar.prefab"


def _make_fake(tmp_path, *, vrm_box_text: str, pending_prefab_export_path):
    fake = _bare_window()
    fake.widgets = {"vrmBox": _FakeEntry(vrm_box_text)}
    fake.work_root = str(tmp_path / "work_root")
    fake.app_root = str(tmp_path / "app_root")
    os.makedirs(fake.work_root, exist_ok=True)
    os.makedirs(fake.app_root, exist_ok=True)
    fake._pending_prefab_export_path = pending_prefab_export_path
    return fake


# ---------------------------------------------------------------------------
# (a) 輸出失敗状態(vrmBox空+unity_export.log存在)で添付一覧にunity_export.log
#     が含まれる -- 本WPの中核受入ゲート
# ---------------------------------------------------------------------------


def test_unity_export_log_attached_when_export_failed_and_vrmbox_empty(tmp_path):
    export_dir = pr.resolve_unity_export_out_dir(str(tmp_path / "work_root"), _PREFAB_PATH)
    _write(
        os.path.join(export_dir, "unity_export.log"),
        "UnityEditor.BuildFailedException: synthetic export failure (dev#1102 test)\n",
    )

    fake = _make_fake(
        tmp_path,
        vrm_box_text="",  # 輸出失敗時、_on_unity_export_exit()は_set_vrm_pathを
        # 呼ばないため、vrmBoxはこの検体では一度も埋まっていない
        # (初回輸出失敗を想定)。
        pending_prefab_export_path=_PREFAB_PATH,
    )

    result = mw.MainWindow._read_full_log_attachment_text(fake)

    assert result is not None
    assert "synthetic export failure" in result
    assert "unity_export/unity_export.log" in result


def test_unity_export_log_attached_when_export_failed_and_vrmbox_stale(tmp_path):
    """輸出失敗時、vrmBoxが「今セッションで前回成功した別アバター」の値の
    まま残っているケース(2回目以降の失敗)でも、_pending_prefab_export_path
    (今セッションの最新の輸出試行)が優先され、今回失敗したprefabの
    unity_export.logが(前回成功アバター側のディレクトリではなく)正しく
    添付されること。両方のディレクトリに別内容のログを置き、pending側の
    内容だけが現れ・vrm_path側の内容は現れないことまで確認する
    (単に「vrm_path側にログが無い」からpending側が使われただけ、という
    弱い検証を避ける、master-writerレビュー指摘の強化)。"""
    stale_vrm_path = str(tmp_path / "PreviouslySucceededAvatar.prefab")
    stale_export_dir = pr.resolve_unity_export_out_dir(
        str(tmp_path / "work_root"), stale_vrm_path
    )
    _write(
        os.path.join(stale_export_dir, "unity_export.log"),
        "STALE previous-session success log (must NOT appear, dev#1102 test)\n",
    )
    export_dir = pr.resolve_unity_export_out_dir(str(tmp_path / "work_root"), _PREFAB_PATH)
    _write(
        os.path.join(export_dir, "unity_export.log"),
        "synthetic second export failure (dev#1102 test)\n",
    )

    fake = _make_fake(
        tmp_path,
        vrm_box_text=stale_vrm_path,
        pending_prefab_export_path=_PREFAB_PATH,
    )

    result = mw.MainWindow._read_full_log_attachment_text(fake)

    assert result is not None
    assert "synthetic second export failure" in result
    assert "unity_export/unity_export.log" in result
    assert "STALE previous-session success log" not in result


# ---------------------------------------------------------------------------
# (b) 成功時の従来挙動が不変
# ---------------------------------------------------------------------------


def test_unity_export_log_still_attached_on_success(tmp_path):
    """輸出成功後は_set_vrm_path(prefab_path)によりvrmBox==prefab_pathになる
    (main_window.py L.2966)。この従来経路でもunity_export.logの添付は
    引き続き機能すること(退行なし)。"""
    export_dir = pr.resolve_unity_export_out_dir(str(tmp_path / "work_root"), _PREFAB_PATH)
    _write(os.path.join(export_dir, "unity_export.log"), "unity export ok\n")

    fake = _make_fake(
        tmp_path,
        vrm_box_text=_PREFAB_PATH,  # 成功後、_set_vrm_pathがvrmBoxへ設定した値
        pending_prefab_export_path=_PREFAB_PATH,
    )

    result = mw.MainWindow._read_full_log_attachment_text(fake)

    assert result is not None
    assert "unity export ok" in result
    assert "unity_export/unity_export.log" in result


# ---------------------------------------------------------------------------
# (b') 復元・キャッシュヒットセッション相当: 今セッションで輸出を試みて
#      いない(_pending_prefab_export_path未設定)場合、従来どおり
#      vrm_pathへフォールバックして添付されること(master-writerレビューで
#      指摘された退行の是正対象そのもの)。
# ---------------------------------------------------------------------------


def test_unity_export_log_attached_via_vrm_path_fallback_when_no_pending_attempt(tmp_path):
    """_restore_last_vrm_on_startup()(起動時、settings_lastvrm.txtから
    _set_vrm_path経由で復元。_on_prefab_selected()を一切経由しないため
    _pending_prefab_export_pathはNoneのまま)や、_on_prefab_selected()冒頭の
    キャッシュ鮮度ヒット早期return(Unity再起動を省略し_set_vrm_path
    だけ呼ぶ、main_window.py L.2916-2920)を模した状態:
    _pending_prefab_export_path=None・vrmBoxには前回成功セッションの
    prefabパスが入っている。今セッションでは輸出を試みていないため、
    vrm_pathへフォールバックして前回成功時のunity_export.logが従来どおり
    添付されること(第1版のpending単独ゲートだとここが欠落していた)。"""
    export_dir = pr.resolve_unity_export_out_dir(str(tmp_path / "work_root"), _PREFAB_PATH)
    _write(
        os.path.join(export_dir, "unity_export.log"),
        "previous session success log (restore/cache-hit, dev#1102 test)\n",
    )

    fake = _make_fake(
        tmp_path,
        vrm_box_text=_PREFAB_PATH,  # 復元/キャッシュヒットでvrmBoxへ設定済み
        pending_prefab_export_path=None,  # 今セッションでは輸出を一切試みていない
    )

    result = mw.MainWindow._read_full_log_attachment_text(fake)

    assert result is not None
    assert "previous session success log" in result
    assert "unity_export/unity_export.log" in result


# ---------------------------------------------------------------------------
# (c) 負の対照: unity_export.logが存在しない場合に空添付でクラッシュしない
# ---------------------------------------------------------------------------


def test_no_crash_when_no_export_ever_attempted(tmp_path):
    """一度もUnity輸出を試みていない(_pending_prefab_export_pathがNone、
    かつvrmBoxも空)状態では、unity_exportディレクトリへの参照自体を
    作らず、例外も出さないこと。"""
    fake = _make_fake(tmp_path, vrm_box_text="", pending_prefab_export_path=None)

    result = mw.MainWindow._read_full_log_attachment_text(fake)

    # launch.logも存在しないため添付候補が0件になり、Noneへ落ちる
    # (inquiry.build_work_dir_attachment_textの既存契約どおり)。
    assert result is None


def test_no_crash_when_export_dir_missing_on_disk(tmp_path):
    """_pending_prefab_export_pathは設定されているが、対応するディレクトリが
    ディスク上にまだ存在しない(輸出プロセスが起動直後にクラッシュした等)
    場合でも、例外を出さず空扱いで続行すること(dev#921「失敗しても壊さない」
    方針の踏襲)。"""
    fake = _make_fake(
        tmp_path,
        vrm_box_text="",
        pending_prefab_export_path=_PREFAB_PATH,
    )
    # 意図的にexport_dirを作らない(os.walk対象ディレクトリ不在)。

    result = mw.MainWindow._read_full_log_attachment_text(fake)

    # 例外を投げずに完走すること自体が受入条件(結果がNoneでも空文字列でもよい)。
    assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# 負の対照(構造): 旧実装相当(vrm_path単独ゲート)へ戻すと本テストが検出する
# ことの確認 -- 「意図的に壊すと検出される」ことの実測。
# ---------------------------------------------------------------------------


def test_negative_control_old_vrmbox_only_gate_would_miss_the_log(tmp_path):
    """旧実装の再現: vrm_pathが空ならunity_exportディレクトリを一切見ない
    ロジックを、このテストファイル内でその場で再現し、dev#1102の実バグが
    (a)のテストのassertを実際に落とすことを確認する(検出力の実測)。
    本体側(main_window.py)は変更しない、テスト内だけの検証用複製。"""
    export_dir = pr.resolve_unity_export_out_dir(str(tmp_path / "work_root"), _PREFAB_PATH)
    _write(
        os.path.join(export_dir, "unity_export.log"),
        "synthetic export failure (negative control)\n",
    )

    import inquiry

    def _old_buggy_logic(vrm_path: str, work_root: str) -> str | None:
        labeled_dirs: list[tuple[str, str]] = []
        if vrm_path:  # dev#1102修正前と同じ、vrm_path単独ゲート
            export_dir_inner = pr.resolve_unity_export_out_dir(work_root, vrm_path)
            labeled_dirs.append(("unity_export", export_dir_inner))
        text = inquiry.build_work_dir_attachment_text(labeled_dirs=labeled_dirs)
        return text or None

    result = _old_buggy_logic("", str(tmp_path / "work_root"))

    assert result is None, (
        "負の対照が成立しない: 旧実装相当のvrm_path単独ゲートで"
        "unity_export.logが取得できてしまった(このテストは旧バグの再現用)"
    )
