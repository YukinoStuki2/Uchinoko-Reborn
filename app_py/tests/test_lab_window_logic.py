# test_lab_window_logic.py -- dev#1186受入条件のロジック層(GUI起動不要)部分。
#
# 対象: ui\lab_window.py の any_feature_active()/reset_all_features()と
# drop_bones機能のstatus_summary/reset_default。
#
# 受入条件(WP指示書より):
#   - ラボ未使用(全て既定)のとき、ロジック層は「非既定=None(無効)」を
#     返すこと
#   - 警告表示の条件(1つでも非既定→表示 / 全無効化ボタン→消える)を
#     ロジック層の単体テストで固定する(GUI起動不要の形に切ること)
#
# 実tkinter widgetは一切使わない(tk.Entry互換の最小フェイクのみ)。
from __future__ import annotations

import os
import sys
import tempfile

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import lab_window  # noqa: E402


class _FakeEntry:
    """tk.Entry互換の最小フェイク(delete/insert/get)。
    test_main_window_restore.py の _FakeEntry と同じ流儀。"""

    def __init__(self, text: str = "") -> None:
        self._text = text

    def delete(self, _start, _end) -> None:
        self._text = ""

    def insert(self, _index, text: str) -> None:
        self._text += text

    def get(self) -> str:
        return self._text


class _FakeSelf:
    """lab_window.py の各関数が要求する最小のself(widgets辞書のみ)。
    _on_drop_bones_changedはgetattrガードで呼ばれるかどうかテストできる
    よう、呼ばれた回数を数えるオプションのフックとして持たせる。

    app_root: dev#165(装備限定)結線後、any_feature_active()/
    reset_all_features()がequipment_filter機能のstatus_summary/
    reset_defaultも呼ぶため、equipment_select_dialog.state_summary()/
    reset()が読み書きするapp_rootが必要になった。テストごとに空の一時
    ディレクトリを割り当てる(状態ファイル不在=未選択=既定値、テスト間の
    汚染も無い)。"""

    def __init__(self, drop_bones_text: str = "") -> None:
        self.widgets = {"dropBonesBox": _FakeEntry(drop_bones_text)}
        self.drop_bones_changed_calls = 0
        self.app_root = tempfile.mkdtemp(prefix="d2p_lab_test_")

    def _on_drop_bones_changed(self) -> None:
        self.drop_bones_changed_calls += 1


# ---------------------------------------------------------------------------
# drop_bones_status_summary
# ---------------------------------------------------------------------------


def test_drop_bones_status_summary_none_when_default_empty():
    self = _FakeSelf("")
    assert lab_window.drop_bones_status_summary(self) is None


def test_drop_bones_status_summary_none_when_whitespace_and_commas_only():
    # ","や空白だけの入力は「実質空」であり既定と区別できてはならない
    # (split(",")で空文字列だけが残るケース)。
    self = _FakeSelf(" , , ")
    assert lab_window.drop_bones_status_summary(self) is None


def test_drop_bones_status_summary_counts_bones_when_set():
    self = _FakeSelf("Bone_L, Bone_R, Tail")
    summary = lab_window.drop_bones_status_summary(self)
    assert summary is not None
    assert summary == i18n.F("LabStatusDropBonesCountFormat", 3)


# ---------------------------------------------------------------------------
# drop_bones_reset_default
# ---------------------------------------------------------------------------


def test_drop_bones_reset_default_clears_value_and_calls_hook():
    self = _FakeSelf("Bone_L, Bone_R")
    lab_window.drop_bones_reset_default(self)
    assert self.widgets["dropBonesBox"].get() == ""
    assert self.drop_bones_changed_calls == 1


def test_drop_bones_reset_default_tolerates_missing_hook():
    # _on_drop_bones_changedを持たないself(main_window.py以外からの呼び出し
    # や単体テストのフェイク)でも例外を出さないこと。
    class _NoHookSelf:
        def __init__(self) -> None:
            self.widgets = {"dropBonesBox": _FakeEntry("Bone_L")}

    self = _NoHookSelf()
    lab_window.drop_bones_reset_default(self)
    assert self.widgets["dropBonesBox"].get() == ""


# ---------------------------------------------------------------------------
# any_feature_active / reset_all_features -- 警告表示の条件そのもの
# ---------------------------------------------------------------------------


def test_any_feature_active_false_when_all_default():
    self = _FakeSelf("")
    assert lab_window.any_feature_active(self) is False


def test_any_feature_active_true_when_drop_bones_set():
    self = _FakeSelf("Bone_L")
    assert lab_window.any_feature_active(self) is True


def test_reset_all_features_makes_any_feature_active_false_again():
    self = _FakeSelf("Bone_L, Bone_R")
    assert lab_window.any_feature_active(self) is True
    lab_window.reset_all_features(self)
    assert lab_window.any_feature_active(self) is False


# ---------------------------------------------------------------------------
# 負の対照: 検出力の証明
# ---------------------------------------------------------------------------


def test_negative_control_broken_reset_leaves_warning_active(monkeypatch):
    """負の対照: reset_defaultが実際には何もしない(壊れた)実装だと、
    「全無効化ボタン→消える」という受入条件が満たされなくなることを
    まず確認する(この前提が崩れていたら、上の正のテストにも検出力が無い)。"""
    self = _FakeSelf("Bone_L")

    def _broken_reset(_self) -> None:
        pass  # 何もしない(実際のバグを模擬)

    monkeypatch.setattr(
        lab_window,
        "LAB_FEATURES",
        [
            lab_window.LabFeature(
                feature_id="drop_bones",
                name_key="LabFeatureDropBones",
                status_summary=lab_window.drop_bones_status_summary,
                open_dialog=lab_window.open_drop_bones_dialog,
                reset_default=_broken_reset,
            )
        ],
    )
    assert lab_window.any_feature_active(self) is True
    lab_window.reset_all_features(self)
    assert lab_window.any_feature_active(self) is True, (
        "前提不成立: 壊れたreset_defaultなのにany_feature_activeがFalseに"
        "なってしまう(negative controlの模擬方法を見直すこと)"
    )


def test_negative_control_status_summary_always_none_hides_active_state(monkeypatch):
    """負の対照: status_summaryが常にNoneを返す(壊れた)実装だと、
    実際には非既定な状態でもany_feature_activeがFalseになってしまう
    (=警告が出るべきなのに出ない)ことを確認する。"""
    self = _FakeSelf("Bone_L")

    monkeypatch.setattr(
        lab_window,
        "LAB_FEATURES",
        [
            lab_window.LabFeature(
                feature_id="drop_bones",
                name_key="LabFeatureDropBones",
                status_summary=lambda _self: None,
                open_dialog=lab_window.open_drop_bones_dialog,
                reset_default=lab_window.drop_bones_reset_default,
            )
        ],
    )
    # dropBonesBoxの中身自体は非既定のままだが、壊れたstatus_summaryのせいで
    # any_feature_activeがFalseへ倒れてしまうことを確認する。
    assert self.widgets["dropBonesBox"].get() == "Bone_L"
    assert lab_window.any_feature_active(self) is False, (
        "前提不成立: 壊れたstatus_summaryなのにany_feature_activeがTrueに"
        "なってしまう(negative controlの模擬方法を見直すこと)"
    )
