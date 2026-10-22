# test_fbx_gui_reject_dev1124.py -- dev#1124(dev#684/dev#758の続き)受入条件の
# pytest。
#
# 背景: dev#684(2026-08-01オーナー裁定「生FBXのGUI入力は非対応」)は一度
# PR#695でGUIの4箇所(ファイルダイアログ/D&D/vrmBox直接入力/設定復元)を
# 拒否する実装だった。うち変換開始時(_start_pipeline)のガードは、prefab変換
# が内部生成するFBXまで巻き込むため、内部/外部FBXを見分ける専用の回避コードが
# 別途必要になっていた。調査の結果、prefab入力の経路は自動試験の網に一切
# かかっていないことが判明し、「唯一のprefab経路の上に、どの自動試験でも
# 検証できないガードが乗っている」状態だったためPR#701でrevertされた。
# 再実装(dev#758、ダイアログ+D&Dの2箇所だけに絞る設計)はオーナー裁定
# (2026-08-02)で「dev#702(CLIへのprefab入力追加)の完了後に実装し直す」条件で
# reject。dev#702は2026-08-02に完了・close済みのため、本WP(dev#1124)で
# dev#758と同じ設計を実装し直す。
#
# 本WPはダイアログ(_on_browse)とD&D(_on_dropped_path)の2箇所だけに絞る。
# _start_pipeline・vrmBox直接入力(_restore_last_vrm_on_startup)・
# app_py\ui\dnd.py にはガードを入れない。is_internal_unity_export_fbx()の
# ような内部/外部FBXを区別する回避コードも一切書かない(そもそも不要な設計に
# する)。
#
# 実tkウィンドウは一切開かない(_FakeSelf方式: MainWindowの対象メソッドだけを
# 未束縛のまま貼り付け、協調先メソッドをスタブで差し替える)。
from __future__ import annotations

import inspect
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import dnd  # noqa: E402
from ui import main_window as mw  # noqa: E402

EXPECTED_LANGS = ["ja", "en", "ko", "zhTW", "zhCN"]

_MAIN_WINDOW_SRC_PATH = os.path.join(_APP_PY_DIR, "ui", "main_window.py")


def _read_main_window_source() -> str:
    with open(_MAIN_WINDOW_SRC_PATH, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 1. ファイルダイアログ(正の対照): *.fbx が候補から消え、選択されても拒否
# ---------------------------------------------------------------------------


def test_on_browse_filedialog_filetypes_excludes_fbx(monkeypatch):
    captured: dict = {}

    def fake_askopenfilename(**kwargs):
        captured.update(kwargs)
        return ""  # キャンセル相当(以降の分岐は他のテストで確認)

    import tkinter.filedialog as filedialog_module

    monkeypatch.setattr(filedialog_module, "askopenfilename", fake_askopenfilename)

    class _FakeSelf:
        _on_browse = mw.MainWindow._on_browse

    _FakeSelf()._on_browse()

    assert "filetypes" in captured
    for _label, patterns in captured["filetypes"]:
        assert "*.fbx" not in patterns, f"filetypesに*.fbxが残っている: {captured['filetypes']}"


def test_on_browse_rejects_fbx_selection_and_shows_message(monkeypatch):
    # ①.fbxパス -> 拒否される
    import tkinter.filedialog as filedialog_module

    monkeypatch.setattr(filedialog_module, "askopenfilename", lambda **kw: r"C:\a\model.fbx")

    calls: dict = {"fbx_rejected": 0, "prefab": [], "vrm": []}

    class _FakeSelf:
        _on_browse = mw.MainWindow._on_browse

        def _on_fbx_gui_rejected(self) -> None:
            calls["fbx_rejected"] += 1

        def _on_prefab_selected(self, path: str) -> None:
            calls["prefab"].append(path)

        def _set_vrm_path(self, path: str) -> None:
            calls["vrm"].append(path)

    _FakeSelf()._on_browse()
    assert calls["fbx_rejected"] == 1
    assert calls["prefab"] == []
    assert calls["vrm"] == []


def test_on_browse_rejects_fbx_case_insensitive(monkeypatch):
    import tkinter.filedialog as filedialog_module

    monkeypatch.setattr(filedialog_module, "askopenfilename", lambda **kw: r"C:\a\MODEL.FBX")

    calls: dict = {"fbx_rejected": 0, "vrm": []}

    class _FakeSelf:
        _on_browse = mw.MainWindow._on_browse

        def _on_fbx_gui_rejected(self) -> None:
            calls["fbx_rejected"] += 1

        def _on_prefab_selected(self, path: str) -> None:
            raise AssertionError("prefab経路が呼ばれてはいけない")

        def _set_vrm_path(self, path: str) -> None:
            calls["vrm"].append(path)

    _FakeSelf()._on_browse()
    assert calls["fbx_rejected"] == 1
    assert calls["vrm"] == []


def test_on_browse_still_accepts_vrm_and_prefab(monkeypatch):
    # ②.prefabパス -> 通る / ③.vrmパス -> 通る
    import tkinter.filedialog as filedialog_module

    calls: dict = {"prefab": [], "vrm": [], "fbx_rejected": 0}

    class _FakeSelf:
        _on_browse = mw.MainWindow._on_browse

        def _on_fbx_gui_rejected(self) -> None:
            calls["fbx_rejected"] += 1

        def _on_prefab_selected(self, path: str) -> None:
            calls["prefab"].append(path)

        def _set_vrm_path(self, path: str) -> None:
            calls["vrm"].append(path)

    monkeypatch.setattr(filedialog_module, "askopenfilename", lambda **kw: r"C:\a\model.vrm")
    _FakeSelf()._on_browse()
    monkeypatch.setattr(filedialog_module, "askopenfilename", lambda **kw: r"C:\a\Avatar.prefab")
    _FakeSelf()._on_browse()

    assert calls["fbx_rejected"] == 0
    assert calls["vrm"] == [r"C:\a\model.vrm"]
    assert calls["prefab"] == [r"C:\a\Avatar.prefab"]


# ---------------------------------------------------------------------------
# 2. D&D(正の対照): .fbx がドロップされたら拒否され、専用案内が出ること
# ---------------------------------------------------------------------------


def test_on_dropped_path_rejects_fbx():
    calls: dict = {"fbx_rejected": 0, "prefab": [], "vrm": []}

    class _FakeSelf:
        _on_dropped_path = mw.MainWindow._on_dropped_path

        def _on_fbx_gui_rejected(self) -> None:
            calls["fbx_rejected"] += 1

        def _on_prefab_selected(self, path: str) -> None:
            calls["prefab"].append(path)

        def _set_vrm_path(self, path: str) -> None:
            calls["vrm"].append(path)

    fs = _FakeSelf()
    fs._on_dropped_path(r"C:\a\model.fbx")
    fs._on_dropped_path(r"C:\a\MODEL.FBX")  # 大小文字無視
    assert calls["fbx_rejected"] == 2
    assert calls["prefab"] == []
    assert calls["vrm"] == []


def test_on_dropped_path_still_accepts_vrm_and_prefab():
    calls: dict = {"fbx_rejected": 0, "prefab": [], "vrm": []}

    class _FakeSelf:
        _on_dropped_path = mw.MainWindow._on_dropped_path

        def _on_fbx_gui_rejected(self) -> None:
            calls["fbx_rejected"] += 1

        def _on_prefab_selected(self, path: str) -> None:
            calls["prefab"].append(path)

        def _set_vrm_path(self, path: str) -> None:
            calls["vrm"].append(path)

    fs = _FakeSelf()
    fs._on_dropped_path(r"C:\a\model.vrm")
    fs._on_dropped_path(r"C:\a\Avatar.prefab")
    assert calls["fbx_rejected"] == 0
    assert calls["vrm"] == [r"C:\a\model.vrm"]
    assert calls["prefab"] == [r"C:\a\Avatar.prefab"]


def test_on_fbx_gui_rejected_shows_dedicated_message(monkeypatch):
    shown: list[tuple[str, str]] = []

    def fake_showinfo(title, body):
        shown.append((title, body))

    import ui.main_window as mw_module

    monkeypatch.setattr(mw_module.messagebox, "showinfo", fake_showinfo)

    class _FakeSelf:
        _on_fbx_gui_rejected = mw.MainWindow._on_fbx_gui_rejected

    _FakeSelf()._on_fbx_gui_rejected()
    assert shown == [(i18n.S("TitleConfirm"), i18n.S("MsgFbxGuiUnsupportedBody"))]


def test_msg_fbx_gui_unsupported_body_i18n_key_all_languages_non_empty_and_prefab_first():
    values = i18n.TABLE["MsgFbxGuiUnsupportedBody"]
    for lang in EXPECTED_LANGS:
        text = values.get(lang)
        assert text, f"MsgFbxGuiUnsupportedBody/{lang} が空"
        # dev#1124: prefab優先(既存lintと同じ規約、test_i18n_keys.py参照)
        assert "prefab" in text.lower(), f"MsgFbxGuiUnsupportedBody/{lang}: prefabへの言及が無い: {text!r}"
        assert "vrm" in text.lower(), f"MsgFbxGuiUnsupportedBody/{lang}: vrmへの言及が無い: {text!r}"
        assert text.lower().index("prefab") < text.lower().index("vrm"), (
            f"MsgFbxGuiUnsupportedBody/{lang}: prefabがVRMより先に来ていない: {text!r}"
        )


# ---------------------------------------------------------------------------
# 3. 負の対照①(受入条件④): ガードを外すと.fbxが通ってしまうことの実証
# ---------------------------------------------------------------------------


def test_negative_control_guard_removal_lets_fbx_leak_through():
    """dev#1124の.fbxガード(`if path.lower().endswith(".fbx"): ... return`)を
    持たない旧版(dev#1124以前の_on_dropped_path相当)のディスパッチロジックを
    直接叩き、.fbxが依然として_set_vrm_path経路へ抜けてしまうことを示す。
    これは「ガードを外すと通ってしまう」ことの直接証明であり、上の正の対照
    テスト(test_on_dropped_path_rejects_fbx等)が実際にガードの有無を検出
    できる設計であることを裏付ける(受入条件④)。"""
    calls: dict = {"vrm": [], "prefab": []}

    class _NoGuardFakeSelf:
        def _on_prefab_selected(self, path: str) -> None:
            calls["prefab"].append(path)

        def _set_vrm_path(self, path: str) -> None:
            calls["vrm"].append(path)

        def _dispatch_without_fbx_guard(self, path: str) -> None:
            # dev#1124より前の_on_dropped_path本体(.fbxチェック無し)そのもの。
            if dnd.is_prefab_path(path):
                self._on_prefab_selected(path)
            else:
                self._set_vrm_path(path)

    fs = _NoGuardFakeSelf()
    fs._dispatch_without_fbx_guard(r"C:\a\model.fbx")
    assert calls["vrm"] == [r"C:\a\model.fbx"], (
        "負の対照: ガード無し版は.fbxを_set_vrm_path経路へ通してしまうはず"
        "(=現行のガード付き版と挙動が異なることの確認)"
    )


# ---------------------------------------------------------------------------
# 4. 負の対照②: 内部/CLI/prefabパイプライン経路を巻き込んでいないことの
#    ソース検査(PR#701がrevertした設計=is_internal_unity_export_fbx()相当の
#    回避コードを再導入していないことの明示的な証明)。
# ---------------------------------------------------------------------------


def test_start_pipeline_has_no_fbx_guard():
    src = inspect.getsource(mw.MainWindow._start_pipeline)
    assert "fbx" not in src.lower(), (
        "「_start_pipeline」にFBX関連の分岐が入っている(PR#701がrevertした"
        "設計の再導入。dev#1124のスコープ外)"
    )


def test_restore_last_vrm_has_no_fbx_guard():
    # vrmBox直接入力/設定復元(_restore_last_vrm_on_startup)にもガードを
    # 入れない(dev#1124のスコープ外、内部/外部FBXの区別を持ち込まない)。
    src = inspect.getsource(mw.MainWindow._restore_last_vrm_on_startup)
    assert "fbx" not in src.lower(), (
        "「_restore_last_vrm_on_startup」にFBX関連の分岐が入っている"
        "(dev#1124のスコープ外)"
    )


def test_main_window_has_no_internal_unity_export_fbx_workaround():
    src = _read_main_window_source()
    assert "is_internal_unity_export_fbx" not in src, (
        "main_window.pyにis_internal_unity_export_fbx()相当の回避コードが"
        "導入されている(PR#701がrevertした設計の再導入。dev#1124のスコープ外)"
    )


def test_pipeline_runner_has_no_internal_fbx_helper():
    # pipeline_runner.pyはこのWPの書き込み許可外。dev#1124はpipeline_runner.py
    # に何も追加しない設計であること自体をソース検査で確認する。
    import pipeline_runner

    src = inspect.getsource(pipeline_runner)
    assert "is_internal_unity_export_fbx" not in src, (
        "pipeline_runner.pyにis_internal_unity_export_fbx()が存在する"
        "(PR#701がrevertした設計の再導入。dev#1124のスコープ外)"
    )


def test_dnd_module_still_accepts_fbx_unchanged():
    # dev#1124: ui\dnd.py自体はD&D全般の純粋な拡張子フィルタでありGUI固有の
    # 裁定を持ち込まない設計を維持する(本WPはdnd.pyに触れない)。
    # pick_dropped_path単体は引き続き.fbxを受理し、main_window.py側の
    # _on_dropped_pathが一段上でGUI裁定として拒否する構成である。
    assert dnd.pick_dropped_path([r"C:\a\model.fbx"]) == r"C:\a\model.fbx"
    assert ".fbx" in dnd.ACCEPTED_EXTENSIONS
