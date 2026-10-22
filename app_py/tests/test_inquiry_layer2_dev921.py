# test_inquiry_layer2_dev921.py -- dev#921 第2層(全文gzip添付)の受入条件。
#
# issue #921: Unity輸出ログを二層化する。第1層(本文要約)は
# pipeline\cli\export_from_unity.ps1 側(tests\unity_export_tail_priority\
# test_unity_export_tail_priority_dev921.py で検証済み)。本ファイルは第2層
# (unity_export.log全文をgzipで添付する)を対象とする。
#
# 実装: app_py\inquiry.py の mask_full_log_for_attachment /
# build_layer2_attachment_block / build_report_payload_json(attachment_log_text
# キーワード引数を追加)。
#
# 最重要の受入条件(issue #921コメント、2026-08-02オーナー指摘を受けた設計):
#   「負の対照(伏字化漏れ検出): 実ログを入力に、出力へ絶対パス・ユーザー名・
#   ドライブ文字つきパスが1つも残っていないことを機械検査する」
# これを本ファイルの中心に置く。マスキング処理そのものは新規に書き起こさず、
# 既存の inquiry.sanitize_for_clipboard(app_py\inquiry.py、既にlog_gzip_b64
# 送信経路で使われている実装)を再利用する。
from __future__ import annotations

import base64
import gzip
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import inquiry  # noqa: E402


# ---------------------------------------------------------------------------
# フィクスチャ: dev#921 issue本文が引用する実例に近い構造の「合成」ログ。
# 実ユーザーのログではなく、完全に架空の値のみで構成する(既存test_inquiry.py
# の"実在の個人情報は使わない"方針を踏襲)。
# ---------------------------------------------------------------------------

_FAKE_PROJECT_PATH = r"C:\UnityP\SampleProjectName\Assets\Avatar\SampleAvatar.prefab"
_FAKE_ASSET_PATH = r"D:\Users\SampleTaro\Documents\MyAvatarWork\Chocolat_kisekae (4).prefab"
_FAKE_UNC_PATH = r"\\BUILDSERVER\share\SampleHanako\SteamLibrary\common\Palworld\Pal-Windows.pak"


def _fake_username() -> str:
    # 実行環境のUSERNAMEを使う(sanitize_for_clipboardのcase3/既存test_inquiry.py
    # と同じ理由: 実際にこの環境のUSERNAME環境変数を伏せられるかを検証するため)。
    return os.environ.get("USERNAME") or os.environ.get("USER") or ""


def _build_synthetic_full_log() -> str:
    user = _fake_username()
    lines = [
        "D2P: prefab解決 path=Assets/Avatar.prefab guid=abcdef1234567890",
        "Unity project path: " + _FAKE_PROJECT_PATH,
        "Loading asset: " + _FAKE_ASSET_PATH,
        "UNC share reference: " + _FAKE_UNC_PATH,
    ]
    if len(user) > 3:
        lines.append("Running as user: " + user + " on this machine")
    lines.append("NullReferenceException: Object reference not set to an instance of an object")
    lines.append(
        "  at DiveToPalworldExporter.ExportUnifiedFbx (UnityEngine.GameObject target, "
        "System.String path) [0x00120] in Assets/Editor/D2P_TempExporter/"
        "DiveToPalworldExporter.cs:1020"
    )
    lines.append("executeMethod DiveToPalworldExporter.ExportBatch threw exception.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# mask_full_log_for_attachment: 単体
# ---------------------------------------------------------------------------


def test_mask_full_log_removes_raw_paths_and_username():
    full_log = _build_synthetic_full_log()
    masked, dropped = inquiry.mask_full_log_for_attachment(full_log)

    assert dropped == 0
    assert _FAKE_PROJECT_PATH not in masked
    assert _FAKE_ASSET_PATH not in masked
    assert _FAKE_UNC_PATH not in masked
    assert "SampleProjectName" not in masked
    assert "SampleTaro" not in masked
    assert "SampleHanako" not in masked

    user = _fake_username()
    if len(user) > 3:
        assert user not in masked

    # 診断に効く構造情報(拡張子・行の骨格)は残ること(issue #921「性質だけ送る」の確認)
    assert "ext=.prefab" in masked
    assert "unc=true" in masked
    # 例外・スタックトレース行そのもの(パスを含まない部分)は透過すること
    assert "NullReferenceException: Object reference not set to an instance of an object" in masked
    assert "executeMethod DiveToPalworldExporter.ExportBatch threw exception." in masked


def test_mask_full_log_empty_and_none_passthrough():
    assert inquiry.mask_full_log_for_attachment("") == ("", 0)
    assert inquiry.mask_full_log_for_attachment(None) == ("", 0)


def test_mask_full_log_drops_line_on_masking_exception(monkeypatch):
    """dev#921「失敗しても壊さない」: 1行の伏字化で想定外の例外が起きたら、
    その行は内容を一切出さずに丸ごと落とし、dropped_line_countへ計上すること。"""
    boom_line = "this line triggers a masking failure: " + _FAKE_PROJECT_PATH
    text = "safe line 1\n" + boom_line + "\nsafe line 2"

    real_sanitize = inquiry.sanitize_for_clipboard

    def flaky_sanitize(s):
        if s is not None and "triggers a masking failure" in s:
            raise RuntimeError("synthetic masking failure (test double)")
        return real_sanitize(s)

    monkeypatch.setattr(inquiry, "sanitize_for_clipboard", flaky_sanitize)
    masked, dropped = inquiry.mask_full_log_for_attachment(text)

    assert dropped == 1
    assert _FAKE_PROJECT_PATH not in masked
    assert "triggers a masking failure" not in masked
    assert "safe line 1" in masked
    assert "safe line 2" in masked


# ---------------------------------------------------------------------------
# 負の対照(受入ゲート最重要): このテスト集合自体が「マスキングが壊れている/
# 素通ししている」ケースを実際に検出できることの証明。
# ---------------------------------------------------------------------------


def test_negative_control_broken_masking_is_detected(monkeypatch):
    """マスキングを無効化(恒等関数へ差し替え)した状態でも同じアサーションを
    走らせ、確実にFAILする(=検出できる)ことを確認する。マスキング自体を
    壊すのではなく、このテストファイルの検査観点が「常にPASSする無意味な
    検査」ではないことの裏付け。"""
    full_log = _build_synthetic_full_log()

    def identity_sanitize(s):
        return s

    monkeypatch.setattr(inquiry, "sanitize_for_clipboard", identity_sanitize)
    masked, _dropped = inquiry.mask_full_log_for_attachment(full_log)

    # マスキングを外すと生のパスがそのまま残る(=このテストの検出力の証明)
    assert _FAKE_PROJECT_PATH in masked, (
        "負の対照が成立しない: sanitize_for_clipboardを無効化しても生パスが"
        "masked出力に現れなかった(テストフィクスチャの前提が崩れている)"
    )


# ---------------------------------------------------------------------------
# build_layer2_attachment_block
# ---------------------------------------------------------------------------


def test_build_layer2_attachment_block_has_markers_and_masked_content():
    full_log = _build_synthetic_full_log()
    block, dropped = inquiry.build_layer2_attachment_block(full_log)

    assert dropped == 0
    assert block.startswith(inquiry._ATTACHMENT_BEGIN_MARKER)
    assert block.rstrip().endswith(inquiry._ATTACHMENT_END_MARKER)
    assert _FAKE_PROJECT_PATH not in block
    assert _FAKE_ASSET_PATH not in block
    assert "NullReferenceException" in block


def test_build_layer2_attachment_block_empty_input_yields_empty_block():
    assert inquiry.build_layer2_attachment_block("") == ("", 0)
    assert inquiry.build_layer2_attachment_block(None) == ("", 0)


# ---------------------------------------------------------------------------
# build_report_payload_json との統合: 第2層が既存のlog_gzip_b64経路に
# 乗ること・第1層(本文)と混ざらないこと。
# ---------------------------------------------------------------------------


def test_payload_without_attachment_is_unchanged_from_layer1_only():
    """既存呼び出し(attachment_log_text省略)は完全に無変更であること
    (dev#921導入前の全既存テスト・呼び出し元との後方互換)。"""
    payload_json, masked_log = inquiry.build_report_payload_json(
        version="v2.3.7",
        lang="ja",
        os_description="Windows 11",
        avatar_name="avatar.vrm",
        status_text="idle",
        channel="dev",
        log_text="--- log ---\nhello\n",
    )
    import json as _json

    data = _json.loads(payload_json)
    decoded = gzip.decompress(base64.b64decode(data["log_gzip_b64"])).decode("utf-8")
    assert decoded == masked_log == "--- log ---\nhello\n"
    assert inquiry._ATTACHMENT_BEGIN_MARKER not in decoded


def test_payload_with_attachment_carries_full_masked_log_via_existing_gzip_field():
    """dev#921第2層の中核受入条件: attachment_log_textを渡すと、既存の
    log_gzip_b64フィールド(新しい送信経路を作らない)へ、伏字化済みの全文が
    マーカー付きで載ること。"""
    full_log = _build_synthetic_full_log()
    payload_json, masked_log = inquiry.build_report_payload_json(
        version="v2.3.7",
        lang="ja",
        os_description="Windows 11",
        avatar_name="avatar.vrm",
        status_text="Unity export failed",
        channel="dev",
        log_text="--- excerpt ---\nNullReferenceException at tail\n",
        attachment_log_text=full_log,
    )
    import json as _json

    data = _json.loads(payload_json)
    # トップレベルスキーマは変わらない(新フィールドを追加していないこと)
    assert set(data.keys()) == {"version", "lang", "meta", "log_gzip_b64"}

    decoded = gzip.decompress(base64.b64decode(data["log_gzip_b64"])).decode("utf-8")

    # 第1層(本文)はそのまま先頭に残る
    assert decoded.startswith(masked_log)
    # 第2層(添付)がマーカー付きで続く
    assert inquiry._ATTACHMENT_BEGIN_MARKER in decoded
    assert inquiry._ATTACHMENT_END_MARKER in decoded
    # 第2層内の生パス・個人名は一切残らない(最重要の負の対照そのもの)
    assert _FAKE_PROJECT_PATH not in decoded
    assert _FAKE_ASSET_PATH not in decoded
    assert _FAKE_UNC_PATH not in decoded
    assert "SampleProjectName" not in decoded
    assert "SampleTaro" not in decoded
    assert "SampleHanako" not in decoded
    # ただし戻り値のmasked_log(変化検出用ベース)は第1層のみで、添付を含まない
    assert inquiry._ATTACHMENT_BEGIN_MARKER not in masked_log


def test_payload_return_value_masked_log_excludes_attachment_even_when_given():
    """呼び出し元(将来のGUI結線)が変化検出のベースとして使うmasked_logは、
    添付の有無に関係なく第1層のみを表すこと(既存support_dialog.pyの
    last_sent_base_log運用契約を壊さないため)。"""
    payload_json, masked_log = inquiry.build_report_payload_json(
        version="v2.3.7",
        lang="ja",
        os_description="Windows 11",
        avatar_name="avatar.vrm",
        status_text="idle",
        channel="dev",
        log_text="base log only",
        attachment_log_text="attachment with " + _FAKE_PROJECT_PATH,
    )
    assert masked_log == "base log only"
