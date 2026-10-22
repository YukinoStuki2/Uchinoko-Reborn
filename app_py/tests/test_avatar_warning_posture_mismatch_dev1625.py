# test_avatar_warning_posture_mismatch_dev1625.py -- dev#1625(2026-08-21
# オーナー裁定)の告知結線の検証。
#
# 背景: pipeline\blender\step02_retarget.py が姿勢不一致ハブを切除すると
# `sway_exclusions_{gender}.json`へ"posture mismatch (dev#1625)"タグ付き
# エントリを記録する。pipeline\py\convert_noue.py(Phase 2-6)がそれを
# 読み直して新規##AVATAR_WARNING##を出す(convert.ps1のPhase 1リレーは
# 表示用にSelect-Stringで行を間引いており、step02側で直接printしても
# 呼び出し元へ届かないため——実機検証で発覚、詳細はstep02_retarget.pyの
# 該当コメントとwork\wp_1625_notes\NOTES.md)。この##AVATAR_WARNING##が、
# 既存の仕組み(pipeline_runner.py::_AVATAR_WARNING_TEMPLATES、
# app_py\ui\main_window.py::_on_pipeline_line())どおり翻訳され、
# 結果表示(_pipeline_warnings、完了ダイアログのポップアップ用リスト)まで
# 届くことを、既存のtest_untranslated_gui_dev939.pyと同じ型で確認する
# (convert_noue.py側の生成条件自体はこのファイルの対象外——
# app_py側の翻訳・配線だけを検証する)。
#
# 切除が0件の変換ではこのマーカー自体が出ない(=告知なし)ことは、
# convert_noue.pyの生成条件(_dev1625_posture_mismatch_chain_count>0の
# ときだけprint)そのものが保証する——本ファイルは「出た場合に正しく
# 翻訳・配線されるか」を検証する(受入条件の後半、切除ロジック自体の負の
# 対照は tests\coverage\test_step02_sway_posture_cull_dev1625.py 側で担保:
# 閾値以下の不一致はfailed_bone_reasonsに一切現れず、sway_exclusions_
# {gender}.jsonにdev#1625タグ自体が記録されない)。
#
# tkの実ウィンドウは一切開かない(禁止領域「ホスト画面への干渉禁止」厳守)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import pipeline_runner as pr  # noqa: E402
from ui import main_window as mw  # noqa: E402


def setup_function(_fn) -> None:
    i18n.set_language("ja")


def teardown_function(_fn) -> None:
    i18n.set_language("ja")


_RAW = (
    "Some sway (jiggle) physics chains were disabled because the source "
    "bone's posture did not match its donor closely enough (8 chain(s))"
)
_EXPECTED_JA = (
    "アバターとの姿勢の差が大きすぎたため、一部の揺れ物理が"
    "無効化されました(8 chain(s))"
)


def test_posture_mismatch_warning_translates_to_japanese():
    assert pr.translate_avatar_warning(_RAW, lang="ja") == _EXPECTED_JA


def test_posture_mismatch_warning_english_is_identity():
    # 原文自体が英語テンプレートのため、en訳は原文と一致する。
    assert pr.translate_avatar_warning(_RAW, lang="en") == _RAW


def test_posture_mismatch_warning_all_five_languages_present_and_distinct():
    for lang in i18n.LANGS:
        text = pr.translate_avatar_warning(_RAW, lang=lang)
        assert text, f"{lang} が空(未実装/データ欠落)"
        if lang != "en":
            assert text != _RAW, f"{lang}: 翻訳されず原文のまま(退行)"


# ---------------------------------------------------------------------------
# 配線の実証: _on_pipeline_line()経由で_pipeline_warningsへ翻訳済み文言が
# 積まれ、ログ欄には引き続き英語の生行が残ること(dev#690の教訓を踏襲)。
# ---------------------------------------------------------------------------


class _FakeBusyBarDict(dict):
    pass


class _FakeSelfForPipelineLine:
    def __init__(self) -> None:
        self.widgets = {
            "busyBar": _FakeBusyBarDict({"mode": "indeterminate", "value": 0}),
            "statusLabel": type("L", (), {"config": lambda self, **kw: None})(),
        }
        self._active_handle = None
        self._early_preview_loaded_this_run = False
        self._pipeline_warnings: list[str] = []
        self.logged: list[str] = []

    def _log(self, text: str) -> None:
        self.logged.append(text)

    _set_busy_bar_mode = mw.MainWindow._set_busy_bar_mode
    _on_pipeline_line = mw.MainWindow._on_pipeline_line
    _set_status = mw.MainWindow._set_status


def test_on_pipeline_line_translates_posture_mismatch_warning_for_popup_list():
    i18n.set_language("ja")
    fake_self = _FakeSelfForPipelineLine()
    fake_self._on_pipeline_line(f"##AVATAR_WARNING## {_RAW}")
    assert fake_self._pipeline_warnings == [_EXPECTED_JA]
    # ログ欄は引き続き英語の生行(##AVATAR_WARNING##つき)のまま
    assert fake_self.logged == [f"##AVATAR_WARNING## {_RAW}"]


def test_no_cull_means_no_warning_line_negative_control():
    """負の対照: 切除0件の変換ログには##AVATAR_WARNING##(このテンプレート)
    自体が一切出ない想定を、通常の進捗行を流し込んでも
    _pipeline_warningsに何も積まれないことで確認する(告知は
    「マーカーが出た場合だけ翻訳・配線される」仕組みであり、マーカー自体の
    生成条件はpipeline\\blender\\step02_retarget.py側=このテストの対象外)。"""
    i18n.set_language("ja")
    fake_self = _FakeSelfForPipelineLine()
    fake_self._on_pipeline_line("[step02] sway_source_gate: PASS (23/23 bone(s))")
    assert fake_self._pipeline_warnings == []
