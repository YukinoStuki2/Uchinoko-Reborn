# test_lab_window_multi_avatar_pak_dev1170.py -- dev#1170 WP-3(マルチアバターPAK
# 作成)のラボ窓レジストリ結線の単体試験(ロジック層のみ、GUI起動不要)。
#
# 検証対象:
#   1. LAB_FEATURES にマルチアバターPAK作成が1件登録されていること
#   2. reset_default()が実際にstoreをリセットすること
#   3. status_summary()がstoreの状態を正しく反映すること
#   4. オーナー確定仕様⑨「ラボ共通警告への合流は不要」: 対応表が非既定
#      (割当あり)でも、any_feature_active()はFalseのままであること
#      (=affects_conversion=Falseで警告集約から除外されている)
from __future__ import annotations

import os
import sys
import tempfile

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import multi_avatar_pak_store as store  # noqa: E402
from ui import lab_window  # noqa: E402


class _FakeEntry:
    def __init__(self, text: str = "") -> None:
        self._text = text

    def delete(self, _start, _end) -> None:
        self._text = ""

    def insert(self, _index, text: str) -> None:
        self._text += text

    def get(self) -> str:
        return self._text


class _FakeSelf:
    """test_lab_window_logic.py の _FakeSelf と同型(dropBonesBox付き)。
    any_feature_active()/reset_all_features()がLAB_FEATURES全機能の
    status_summary/reset_defaultを呼ぶため、drop_bones分のwidgetsも要る。"""

    def __init__(self, drop_bones_text: str = "") -> None:
        self.widgets = {"dropBonesBox": _FakeEntry(drop_bones_text)}
        self.app_root = tempfile.mkdtemp(prefix="d2p_lab_test_")
        self.work_root = tempfile.mkdtemp(prefix="d2p_lab_test_work_")


def _find_feature():
    for feature in lab_window.LAB_FEATURES:
        if feature.feature_id == "multi_avatar_pak":
            return feature
    raise AssertionError("multi_avatar_pak feature not registered in LAB_FEATURES")


# ---------------------------------------------------------------------------
# 登録確認
# ---------------------------------------------------------------------------


def test_multi_avatar_pak_feature_is_registered():
    feature = _find_feature()
    assert feature.name_key == "LabFeatureMultiAvatarPak"


def test_multi_avatar_pak_feature_declares_affects_conversion_false():
    feature = _find_feature()
    assert feature.affects_conversion is False


def test_other_features_default_affects_conversion_true():
    # 既存5機能は無変更(affects_conversion省略=既定True)であることの確認。
    # dev#1368(出力先フォルダを開く)もjob設定に一切触れないアクションのみの
    # 機能のためaffects_conversion=Falseを明示しており、multi_avatar_pakと
    # 同じ理由でここでは対象外にする(本テストの意図=「job設定に触れる既存
    # 機能が無変更であること」の確認であり、「Falseは1機能限定」ではない)。
    for feature in lab_window.LAB_FEATURES:
        if feature.feature_id in ("multi_avatar_pak", "output_folder"):
            continue
        assert feature.affects_conversion is True, feature.feature_id


# ---------------------------------------------------------------------------
# status_summary / reset_default
# ---------------------------------------------------------------------------


def test_status_summary_none_when_default():
    self = _FakeSelf()
    feature = _find_feature()
    assert feature.status_summary(self) is None


def test_status_summary_reports_when_assignments_present():
    self = _FakeSelf()
    store.save_assignments(self.app_root, {"Bronze001": "Alicia"})
    feature = _find_feature()
    assert feature.status_summary(self) is not None


def test_reset_default_clears_store():
    self = _FakeSelf()
    store.save_assignments(self.app_root, {"Bronze001": "Alicia"})
    feature = _find_feature()
    feature.reset_default(self)
    assert store.is_active(self.app_root) is False


# ---------------------------------------------------------------------------
# オーナー確定仕様⑨: ラボ共通警告への非合流(核心の検証)
# ---------------------------------------------------------------------------


def test_any_feature_active_stays_false_when_only_multi_avatar_pak_is_non_default():
    self = _FakeSelf("")  # drop_bones等は全て既定のまま
    store.save_assignments(self.app_root, {"Bronze001": "Alicia", "Cloth002": "Bob"})

    # 対応表自体は非既定であることの前提確認
    feature = _find_feature()
    assert feature.status_summary(self) is not None

    # だがラボ共通警告(any_feature_active)には合流しない
    assert lab_window.any_feature_active(self) is False


def test_any_feature_active_true_when_another_feature_is_non_default_alongside():
    self = _FakeSelf("Bone_L")  # drop_bonesは非既定
    store.save_assignments(self.app_root, {"Bronze001": "Alicia"})  # こちらも非既定
    # drop_bones側の非既定が効いて警告は出る(マルチアバターPAK単体の話に
    # 巻き込まれて警告全体が死んでいないことの確認)
    assert lab_window.any_feature_active(self) is True


def test_reset_all_features_also_resets_multi_avatar_pak_store():
    self = _FakeSelf("")
    store.save_assignments(self.app_root, {"Bronze001": "Alicia"})
    lab_window.reset_all_features(self)
    assert store.is_active(self.app_root) is False


# ---------------------------------------------------------------------------
# 負の対照: 検出力の証明
# ---------------------------------------------------------------------------


def test_negative_control_affects_conversion_true_would_leak_into_warning():
    """負の対照: affects_conversion=Trueのまま(オーナー確定仕様⑨の配線を
    忘れた場合を模擬)だと、マルチアバターPAK単体の非既定状態でも
    any_feature_activeがTrueになってしまうことを確認する(=⑨の検出力の
    前提が壊れていないことの証明)。"""
    self = _FakeSelf("")
    store.save_assignments(self.app_root, {"Bronze001": "Alicia"})

    broken_features = [
        (f if f.feature_id != "multi_avatar_pak"
         else lab_window.LabFeature(
             feature_id=f.feature_id, name_key=f.name_key,
             status_summary=f.status_summary, open_dialog=f.open_dialog,
             reset_default=f.reset_default, affects_conversion=True,  # バグを模擬
         ))
        for f in lab_window.LAB_FEATURES
    ]

    import unittest.mock as mock
    with mock.patch.object(lab_window, "LAB_FEATURES", broken_features):
        assert lab_window.any_feature_active(self) is True, (
            "前提不成立: affects_conversion=Trueに戻しても警告が出ないままになる"
            "(negative controlの模擬方法を見直すこと)"
        )
