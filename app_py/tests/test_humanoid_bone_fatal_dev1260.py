# test_humanoid_bone_fatal_dev1260.py -- dev#1260: 必須Humanoidボーンが
# 解決できないFATALを「未割当」/「衝突」の2分類でGUI言語に翻訳して見せる
# ことの単体テスト(実報告CN23H3S5/R5PEK47D再検証、オーナー裁定2026-08-09)。
#
# アーキテクチャ(dev#1261の##AVATAR_FATAL## no_meshと同型):
#   1. pipeline\blender\vp_bl.py::humanoid_map_from_json() が必須ボーン未充足
#      でdie()する直前に、classify_missing_bone_reason()の結果に応じて
#      `##AVATAR_FATAL## humanoid_bone_unassigned` または
#      `##AVATAR_FATAL## humanoid_bone_collision` を出す
#      (ソーステキストレベルの検証はtests\coverage\
#      test_bone_collision_diag_dev1260.pyが担当、vp_bl.pyはbpy依存で
#      この環境から単体importできないため)。
#   2. app_py\pipeline_runner.py の parse_avatar_fatal()/translate_avatar_fatal()
#      が2つの新コードをi18n key(MsgHumanoidBoneUnassignedFatal/
#      MsgHumanoidBoneCollisionFatal、5言語)へ翻訳する。
#   3. main_window.py側の配線(_on_pipeline_line/_on_pipeline_exit)は
#      コード非依存の汎用実装(dev#1261で実装済み)であり、本WPで変更していない
#      ことを負の対照で確認する(test_no_mesh_fatal_dev1261.pyの該当試験が
#      既にno_meshで担保しているため、ここでは重複させずi18n/翻訳層に絞る)。
from __future__ import annotations

import os
import sys

import pytest

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import pipeline_runner as pr  # noqa: E402

EXPECTED_LANGS = ["ja", "en", "ko", "zhTW", "zhCN"]
NEW_KEYS = ("MsgHumanoidBoneUnassignedFatal", "MsgHumanoidBoneCollisionFatal")
NEW_CODES = ("humanoid_bone_unassigned", "humanoid_bone_collision")


# ---------------------------------------------------------------------------
# 1. i18n辞書: 2つの新規キーが5言語とも非空であること
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", NEW_KEYS)
def test_new_fatal_keys_exist_all_languages_non_empty(key):
    assert key in i18n.TABLE, f"{key} がi18n.TABLEに無い"
    for lang in EXPECTED_LANGS:
        assert i18n.TABLE[key].get(lang), f"{key}/{lang} が空"


def test_unassigned_message_mentions_configure_avatar_guidance():
    # dev#233以来の対処導線(Rig > Configure Avatar)と揃えている
    en_text = i18n.S("MsgHumanoidBoneUnassignedFatal", lang="en")
    assert "Configure Avatar" in en_text
    assert "Rig" in en_text


def test_collision_message_matches_vp_dup_guidance_tone():
    # vp_dup_armature.GUIDANCE_TEXT(dev#1225でユーザー非難文言を撤廃済み)と
    # 同じ語彙("multiple skeletons"、ユーザーへの改変依頼を含まない)を使う
    en_text = i18n.S("MsgHumanoidBoneCollisionFatal", lang="en")
    assert "multiple skeletons" in en_text
    assert "Armature" in en_text


@pytest.mark.parametrize("key", NEW_KEYS)
def test_new_fatal_keys_ja_do_not_use_forbidden_export_wording(key):
    # CLAUDE.md/dev#1263: 「輸出」は禁止語(正: エクスポート)。この2文言は
    # そもそもexport概念を含まないため、"輸出"が出現しないことを機械検査する
    ja_text = i18n.S(key, lang="ja")
    assert "輸出" not in ja_text


def test_collision_message_does_not_blame_the_user():
    # dev#1225: 「余分な」「削除してください」等、ユーザーのアバターを
    # 咎める/改変を依頼する語彙が無いこと(GUIDANCE_TEXT同様の中立文言)
    for lang in EXPECTED_LANGS:
        text = i18n.S("MsgHumanoidBoneCollisionFatal", lang=lang)
        assert "余分" not in text
        assert "delete" not in text.lower()
        assert "remove" not in text.lower()


# ---------------------------------------------------------------------------
# 2. pipeline_runner: マーカー解析・翻訳の単体テスト(no_meshと同型)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", NEW_CODES)
def test_parse_avatar_fatal_new_codes(code):
    assert pr.parse_avatar_fatal(f"##AVATAR_FATAL## {code}") == code


@pytest.mark.parametrize(
    "code,key",
    list(zip(NEW_CODES, NEW_KEYS)),
)
def test_translate_avatar_fatal_new_codes_ja(code, key):
    assert pr.translate_avatar_fatal(code, lang="ja") == i18n.S(key, lang="ja")


@pytest.mark.parametrize(
    "code,key",
    list(zip(NEW_CODES, NEW_KEYS)),
)
def test_translate_avatar_fatal_new_codes_en(code, key):
    assert pr.translate_avatar_fatal(code, lang="en") == i18n.S(key, lang="en")


def test_translate_avatar_fatal_unknown_code_still_falls_back_to_code_itself():
    # 負の対照: 本WPが辞書を拡張しても、未知コードのフォールバック方針
    # (##AVATAR_WARNING##系と同じ「情報を落とさず原文のまま返す」)は不変
    assert pr.translate_avatar_fatal("__no_such_code_dev1260__", lang="ja") == (
        "__no_such_code_dev1260__"
    )


def test_no_mesh_code_still_works_after_dict_extension():
    # 負の対照: dev#1261のno_meshマーカーが、本WPでの辞書拡張により
    # 壊れていないこと
    assert pr.translate_avatar_fatal("no_mesh", lang="ja") == (
        "メッシュが見つかりませんでした。入力ファイルが壊れていないかご確認ください"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
