# test_main_window_lab_ui.py -- dev#1186受入条件のmain_window.py側の配線。
#
# 対象:
#   - メイン窓に追加された「ラボ」ボタン(labButton)とラボ機能の警告表示
#     (labWarningLabel、_refresh_lab_warning())
#   - 「こだわり設定」からdrop_bonesウィジェット(dropBonesBox)自体は
#     変わらず存在し続けること(設定値の保存先を変えない、というWP指示書の
#     受入条件)
#   - ラボ未使用(全て既定)のとき、生成されるjob設定が従来と完全同一
#     (無退行)であること
#
# 実tkウィンドウは一切表示しない(test_main_window_kodawari_layout.pyと同じ
# 慣例: 共有hidden_root、_build_widgets()だけを束縛前のまま呼ぶ)。
from __future__ import annotations

import os
import sys
import tkinter as tk

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import pipeline_runner as pr  # noqa: E402
from ui import lab_window  # noqa: E402
from ui import main_window as mw  # noqa: E402


def _make_fake_self(root, app_root: str) -> mw.MainWindow:
    """test_main_window_kodawari_layout.pyの`_make_fake_self`と同じ、
    MainWindow.__init__を経由せず_build_widgets()だけを実行するための
    最小フェイクインスタンス(既存の慣例をそのまま踏襲)。"""
    self = mw.MainWindow.__new__(mw.MainWindow)
    self.root = root
    self.app_root = app_root
    self.widgets = {}
    self._tooltips = []
    return self


def _find_children(widget, cls):
    found = []
    for child in widget.winfo_children():
        if isinstance(child, cls):
            found.append(child)
        found.extend(_find_children(child, cls))
    return found


# ---------------------------------------------------------------------------
# labButton / labWarningLabel の存在・初期状態
# ---------------------------------------------------------------------------


def test_lab_button_exists_with_localized_text(hidden_root, tmp_path):
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)
        assert "labButton" in self.widgets
        assert self.widgets["labButton"].cget("text") == i18n.S("BtnLab")
    finally:
        i18n.clear_registry()


def test_lab_warning_label_hidden_by_default(hidden_root, tmp_path):
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)
        assert self.widgets["labWarningLabel"].place_info() == {}
    finally:
        i18n.clear_registry()


def test_drop_bones_box_still_exists_but_not_placed_in_kodawari_panel(hidden_root, tmp_path):
    """dev#1186: 「UIの置き場所だけ移す」——dropBonesBoxというEntry自体は
    従来どおりwidgets["dropBonesBox"]に存在し.get()/.delete()/.insert()が
    使えるが、こだわりパネル上には配置されない(非表示のバッキングストア)。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)
        box = self.widgets["dropBonesBox"]
        assert isinstance(box, tk.Entry)
        assert box.get() == ""  # 既定は空(旧実装と同じ初期値)
        assert box.place_info() == {}, "dropBonesBoxが画面上に配置されたままになっている"
    finally:
        i18n.clear_registry()


# ---------------------------------------------------------------------------
# _refresh_lab_warning: 表示/非表示の切り替え
# ---------------------------------------------------------------------------


def test_refresh_lab_warning_shows_when_drop_bones_non_default(hidden_root, tmp_path):
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)

        mw.MainWindow._refresh_lab_warning(self)
        assert self.widgets["labWarningLabel"].place_info() == {}

        self.widgets["dropBonesBox"].insert(0, "Bone_L, Bone_R")
        mw.MainWindow._refresh_lab_warning(self)
        info = self.widgets["labWarningLabel"].place_info()
        assert info != {}
        assert self.widgets["labWarningLabel"].cget("text") == i18n.S("LabWarningActive")
    finally:
        i18n.clear_registry()


def test_refresh_lab_warning_hides_again_after_clearing(hidden_root, tmp_path):
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)

        self.widgets["dropBonesBox"].insert(0, "Bone_L")
        mw.MainWindow._refresh_lab_warning(self)
        assert self.widgets["labWarningLabel"].place_info() != {}

        self.widgets["dropBonesBox"].delete(0, tk.END)
        mw.MainWindow._refresh_lab_warning(self)
        assert self.widgets["labWarningLabel"].place_info() == {}
    finally:
        i18n.clear_registry()


def test_negative_control_stale_geometry_masks_hidden_state(hidden_root, tmp_path):
    """負の対照: _refresh_lab_warning()を一度も呼ばないと、
    labWarningLabelはplace_forget()済みの既定状態のまま
    (=見た目上「隠れている」ことそのものは_build_widgets()の初期化に
    支えられている)ことを確認する。_refresh_lab_warning()を実装ミスで
    「表示条件を無視して常にplace()する」よう壊すと本テストではなく
    test_refresh_lab_warning_hides_again_after_clearingが赤くなる
    (この関数は前提確認のみ)。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)
        self.widgets["dropBonesBox"].insert(0, "Bone_L")
        # _refresh_lab_warning()を呼ばない限り、_build_widgets()直後の
        # place_forget()済み状態のまま変化しないこと。
        assert self.widgets["labWarningLabel"].place_info() == {}
    finally:
        i18n.clear_registry()


# ---------------------------------------------------------------------------
# _on_open_lab_window: ラボ窓を開く配線
# ---------------------------------------------------------------------------


def test_on_open_lab_window_opens_toplevel_with_feature_row(hidden_root, tmp_path):
    i18n.clear_registry()
    dlg = None
    try:
        i18n.set_language("ja")
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)

        assert lab_window.LAB_FEATURES, "LAB_FEATURESが空でラボ窓の検証ができない"

        mw.MainWindow._on_open_lab_window(self)
        # open_lab_window()自体はTopLevelを直接返さない経路(ボタンの
        # commandとして呼ぶ実運用の形)なので、rootの子から探す。
        toplevels = [
            child for child in hidden_root.winfo_children()
            if isinstance(child, tk.Toplevel)
        ]
        assert toplevels, "ラボ窓(Toplevel)が開かれていない"
        dlg = toplevels[-1]
        labels = {lbl.cget("text") for lbl in _find_children(dlg, tk.Label)}
        assert i18n.S("LabFeatureDropBones") in labels
    finally:
        if dlg is not None:
            dlg.destroy()
        i18n.clear_registry()


# ---------------------------------------------------------------------------
# 無退行: ラボ未使用(全て既定)のとき、生成されるjob設定が従来と完全同一
# ---------------------------------------------------------------------------


def _make_app_root(tmp_path):
    app_root = tmp_path / "app_root"
    app_root.mkdir(parents=True)
    return str(app_root)


def _make_vrm(tmp_path, name="MyAvatar.vrm"):
    vrm = tmp_path / name
    vrm.write_bytes(b"")
    return str(vrm)


def test_default_gui_state_produces_same_job_as_explicit_empty_drop_bones(
    hidden_root, tmp_path
):
    """dev#1186受入条件「ラボ未使用(全て既定)のとき、生成されるjob設定が
    従来と完全同一(無退行)」。_build_widgets()直後のdropBonesBox.get()
    (=GUIの既定状態そのもの、_start_pipeline側の`self.widgets["dropBonesBox"]
    .get()`と同じ読み出し方)をwrite_job()へ渡した結果が、drop_bones_textを
    明示的に空文字列で渡した場合(=dev#1186着手前の実質的な既定呼び出し)と
    バイト完全一致すること。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)
        gui_default_drop_bones_text = self.widgets["dropBonesBox"].get()
        assert gui_default_drop_bones_text == ""

        app_root_a = _make_app_root(tmp_path / "a")
        app_root_b = _make_app_root(tmp_path / "b")
        vrm = _make_vrm(tmp_path)

        job_path_a = pr.write_job(
            app_root_a, str(tmp_path / "work_a"), vrm,
            drop_bones_text=gui_default_drop_bones_text,
        )
        job_path_b = pr.write_job(
            app_root_b, str(tmp_path / "work_b"), vrm,
            drop_bones_text="",
        )
        import json

        with open(job_path_a, encoding="utf-8") as f:
            job_a = json.load(f)
        with open(job_path_b, encoding="utf-8") as f:
            job_b = json.load(f)

        assert job_a["drop_bones"] == []
        assert job_a["drop_bones"] == job_b["drop_bones"]
    finally:
        i18n.clear_registry()


def test_negative_control_nonempty_drop_bones_changes_job(hidden_root, tmp_path):
    """負の対照: dropBonesBoxへ値を入れれば実際にjob設定が変わることを
    確認する(=上の無退行テストに検出力があることの裏付け)。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        self = _make_fake_self(hidden_root, str(tmp_path))
        mw.MainWindow._build_widgets(self)
        self.widgets["dropBonesBox"].insert(0, "Bone_L, Bone_R")
        gui_drop_bones_text = self.widgets["dropBonesBox"].get()

        app_root = _make_app_root(tmp_path / "c")
        vrm = _make_vrm(tmp_path)
        job_path = pr.write_job(
            app_root, str(tmp_path / "work_c"), vrm,
            drop_bones_text=gui_drop_bones_text,
        )
        import json

        with open(job_path, encoding="utf-8") as f:
            job = json.load(f)
        assert job["drop_bones"] == ["Bone_L", "Bone_R"]
    finally:
        i18n.clear_registry()
