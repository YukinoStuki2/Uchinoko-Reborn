# test_inquiry_dev1011_generic_pii.py -- dev#1011: 汎用PII(氏名相当の
# メールアドレス・電話番号・IPアドレス・クレジットカード・APIキー等)を
# 業界標準ライブラリ(logprivacy)へ任せる併用レイヤーの検証。
#
# オーナー裁定(issue #1011, 2026-08-03): 「うちのログプライバシーは業界標準の
# ○○をつかっています、で説明おわるじゃん」。方針(B)併用——汎用PIIは
# ライブラリ、ファイルパスは既存の自作実装(dev#7/dev#372/dev#873/dev#1012)。
#
# このテストファイルは logprivacy が pip インストールされている開発環境での
# 実行を前提とする(未導入なら pip install logprivacy==0.6.0)。CI/他の開発機で
# 未導入でも全体のテストスイートを壊さないよう、当該部分は
# pytest.importorskip で明示的にスキップする(隠れた失敗にしない)。
#
# 実在の個人情報は一切含まない。
from __future__ import annotations

import os
import sys

import pytest

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import inquiry  # noqa: E402

logprivacy = pytest.importorskip(
    "logprivacy",
    reason="dev#1011の汎用PII層は開発時のみ有効(pip install logprivacy==0.6.0で有効化)。"
    "配布物には未配線(app_py\\build.py側の追加配線が別WPで必要、issue #1011コメント参照)。",
)


def test_library_actually_loaded_in_this_test_environment():
    """このテスト環境では実際にlogprivacyが有効化されていること
    (importorskipだけだと「未導入なので全部skip」に気づかず緑を誤認しうる
    ため、フォールバックでなく本物の経路を通っていることを明示的に確認する)。"""
    assert inquiry._LOGPRIVACY_AVAILABLE is True
    assert inquiry._GENERIC_PII_CLEANER is not None


# ---------------------------------------------------------------------------
# 正方向: 実際のログに混ざった汎用PIIが除去されること
# ---------------------------------------------------------------------------


def test_email_address_is_redacted():
    text = "問い合わせ: taro.yamada@example.com までご連絡ください"
    result = inquiry.sanitize_for_clipboard(text)
    assert "taro.yamada@example.com" not in result
    assert "ご連絡ください" in result


def test_bearer_token_is_redacted():
    text = "Authorization: Bearer abcdEFGH12345678ijklMNOP failed with 401"
    result = inquiry.sanitize_for_clipboard(text)
    assert "abcdEFGH12345678ijklMNOP" not in result
    assert "failed with 401" in result


def test_password_field_is_redacted():
    text = "config dump: password=hunter2Secret! host=localhost"
    result = inquiry.sanitize_for_clipboard(text)
    assert "hunter2Secret!" not in result
    assert "host=localhost" in result


def test_stripe_style_secret_key_is_redacted():
    # Synthetic, unusable test data; no captured or live service credential.
    fake_key = "sk_test_" + ("0" * 32)
    text = f"billing error using key {fake_key} today"
    result = inquiry.sanitize_for_clipboard(text)
    assert fake_key not in result
    assert "billing error" in result


# ---------------------------------------------------------------------------
# 負の対照(核): 診断に必要な情報が誤検知で潰れないこと。dev#873で「伏字化が
# 診断を殺す」実害が出たばかりであり、この確認を省略しないこと(WP指示書の
# 明示要求)。
# ---------------------------------------------------------------------------


def test_sha256_hash_survives():
    text = "gitcommit=575ff21c3a9b6e4d8f0a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e4f5a6"
    result = inquiry.sanitize_for_clipboard(text)
    assert result == text


def test_guid_survives():
    text = "session_id=3F2504E0-4F89-11D3-9A0C-0305E82C3301"
    result = inquiry.sanitize_for_clipboard(text)
    assert result == text


# dev#1012レビュー時にMasterライターが独立検証で発見した実際の破損検体
# (2026-08-03、指揮者裁定によりPhoneRule/IPAddressRuleを除外)。
# 「たまたま通る検体」だけを使ったtest_guid_survives単体では、この穴を
# 検出できなかった——検体の偏りそのものが問題だったため、実際に壊れていた
# 文字列をそのまま固定する。PhoneRuleは末尾の数字列を電話番号と誤認識し、
# ダッシュ区切りGUID(RFC4122形式、相関ID・セッションIDとして頻出)を
# 部分破壊していた。
@pytest.mark.parametrize(
    "text",
    [
        "{A1B2C3D4-E5F6-4789-9ABC-DEF012345678}",
        "guid: 550e8400-e29b-41d4-a716-446655440000",
        "{12345678-1234-1234-1234-123456789012}",
        "session id b2c3d4e5-f6a7-4890-b123-456789012345",
        "8f14e45fceea167a5a36dedd4bea2543",
    ],
)
def test_guid_variants_survive_previously_broken_by_phonerule(text):
    """負の対照(dev#1012レビュー起因): これらのGUIDはPhoneRule導入時に
    実際に部分破壊されていた(例: 末尾が"[PHONE]"へ置換される)。
    PhoneRule除外後は無変更で生存すること。"""
    result = inquiry.sanitize_for_clipboard(text)
    assert result == text, (
        "GUIDが部分破壊された(PhoneRuleの再導入、または同種の誤検知が"
        "再発した可能性): result=" + repr(result)
    )
    assert "[PHONE]" not in result


def test_windows_version_string_survives():
    text = "OS: Windows 11 Pro 10.0.26200"
    result = inquiry.sanitize_for_clipboard(text)
    assert result == text


def test_version_and_build_strings_survive():
    text = "Blender 4.3.2 / Unity 2022.3.22f1 / tool v2.3.7"
    result = inquiry.sanitize_for_clipboard(text)
    assert result == text


# dev#1012レビュー時にMasterライターが独立検証で発見した実際の破損検体。
# IPAddressRuleが4分割の数字バージョン文字列(.NET/Windowsアセンブリ
# バージョンの標準形式)をIPv4アドレスと誤認識し、"[IP_ADDRESS]"へ丸ごと
# 置換していた。
@pytest.mark.parametrize(
    "text",
    [
        "assembly version: 1.0.0.0",
        "version 4.3.2.1 released",
    ],
)
def test_dotted_version_numbers_survive_previously_broken_by_ipaddressrule(text):
    """負の対照(dev#1012レビュー起因): これらの4分割バージョン文字列は
    IPAddressRule導入時に実際に"[IP_ADDRESS]"へ丸ごと置換されていた。
    IPAddressRule除外後は無変更で生存すること。"""
    result = inquiry.sanitize_for_clipboard(text)
    assert result == text, (
        "バージョン文字列がIPアドレスと誤認識された(IPAddressRuleの"
        "再導入、または同種の誤検知が再発した可能性): result=" + repr(result)
    )
    assert "[IP_ADDRESS]" not in result


def test_path_facts_output_survives():
    """dev#372の最小事実集合(name=/exists=/drive_type=/length=/segments=/
    root=/ext= 等)がPII層に誤検知されないこと。"""
    text = (
        "path masked; name=editors-v2.json exists=False drive_type=fixed "
        "length=56 non_ascii_chars=False has_space=False UNC=False "
        "under_OneDrive=False segments=7 root=drive quote=False "
        "invalid_chars=False unexpanded_env_var=False trailing_whitespace=False "
        "trailing_dot=False ext=.json"
    )
    result = inquiry.sanitize_for_clipboard(text)
    assert result == text


def test_exception_message_and_line_number_survive():
    text = "unity_export.log:6653:Exception: Humanoid setup avatar not found"
    result = inquiry.sanitize_for_clipboard(text)
    assert "Exception: Humanoid setup avatar not found" in result
    assert ":6653:" in result


def test_japanese_diagnostic_text_survives_unmangled():
    """日本語ログが壊れないこと(WP指示書の明示要求)。"""
    text = "D2P: NDMFベイク完了、警告12件。アバター名: サンプルアバター"
    result = inquiry.sanitize_for_clipboard(text)
    assert result == text


def test_japanese_error_message_survives_unmangled():
    text = "エラー: Blenderのダウンロードに失敗しました (SHA256不一致)"
    result = inquiry.sanitize_for_clipboard(text)
    assert result == text


def test_mesh_and_material_diagnostic_names_survive():
    text = "remap: geo_00 -> 0 pal groups, material_map.jsonに無いメッシュ: Beret"
    result = inquiry.sanitize_for_clipboard(text)
    assert result == text


def test_screen_resolution_string_survives():
    """Masterライターの独立検証で確認したカテゴリ: 解像度表記
    (幅x高さ@リフレッシュレート)が誤検知されないこと。"""
    text = "screen resolution: 2560x1440 @ 144Hz"
    result = inquiry.sanitize_for_clipboard(text)
    assert result == text


def test_build_number_with_commit_hash_survives():
    """Masterライターの独立検証で確認したカテゴリ: ビルド番号+コミット
    ハッシュの併記が誤検知されないこと。"""
    text = "build 20260803.1 (commit 575ff21)"
    result = inquiry.sanitize_for_clipboard(text)
    assert result == text


# ---------------------------------------------------------------------------
# 自ツールのインフラURLは診断情報として温存する(UrlRuleを意図的に除外した
# 設計判断の検証)。
# ---------------------------------------------------------------------------


def test_own_report_endpoint_url_survives():
    text = "posting to https://report.osakishokai.com/report failed with timeout"
    result = inquiry.sanitize_for_clipboard(text)
    assert "https://report.osakishokai.com/report" in result
    assert "failed with timeout" in result


def test_blender_download_url_survives():
    text = "downloading https://download.blender.org/release/Blender4.3/blender-4.3.2-windows-x64.zip"
    result = inquiry.sanitize_for_clipboard(text)
    assert "https://download.blender.org/release/Blender4.3/blender-4.3.2-windows-x64.zip" in result


# ---------------------------------------------------------------------------
# パス伏字化(既存の自作実装)が従来どおり効いていること(退行なし)。
# ---------------------------------------------------------------------------


def test_path_masking_still_works_alongside_pii_layer():
    text = r"failed to load C:\Users\SampleTaro_Zzyzx9912\Downloads\avatar.vrm"
    result = inquiry.sanitize_for_clipboard(text)
    assert "SampleTaro_Zzyzx9912" not in result
    assert r"C:\Users\SampleTaro_Zzyzx9912\Downloads\avatar.vrm" not in result


def test_email_inside_otherwise_normal_log_line_is_redacted_and_path_untouched_elsewhere():
    """パス伏字化とPII層が同一行内で共存できること(順序確認)。"""
    text = (
        r"contact taro@example.com about C:\Users\SampleTaro_Zzyzx9912\avatar.vrm"
    )
    result = inquiry.sanitize_for_clipboard(text)
    assert "taro@example.com" not in result
    assert "SampleTaro_Zzyzx9912" not in result
    assert "contact" in result


# ---------------------------------------------------------------------------
# 縮退動作: ライブラリが無い環境ではエラーにならず、元のテキストをそのまま
# 通す(本プロジェクトの「自動発見は必ず手動指定フォールバックを持つこと」
# 原則を依存の有無に適用したもの)。
# ---------------------------------------------------------------------------


def test_sanitize_generic_pii_degrades_gracefully_when_cleaner_unavailable(monkeypatch):
    monkeypatch.setattr(inquiry, "_GENERIC_PII_CLEANER", None)
    text = "contact taro@example.com now"
    assert inquiry.sanitize_generic_pii(text) == text


def test_sanitize_for_clipboard_still_masks_paths_when_pii_layer_unavailable(monkeypatch):
    """PII層が無効化されても、既存のパス伏字化(dev#7/dev#373/dev#1012)は
    引き続き機能すること(併用レイヤーが片方欠けても他方が壊れない)。"""
    monkeypatch.setattr(inquiry, "_GENERIC_PII_CLEANER", None)
    text = r"failed to load C:\Users\SampleTaro_Zzyzx9912\avatar.vrm"
    result = inquiry.sanitize_for_clipboard(text)
    assert "SampleTaro_Zzyzx9912" not in result


def test_sanitize_generic_pii_survives_internal_exception(monkeypatch):
    """dev#921と同じ「失敗しても壊さない」方針: PII層が例外を投げても
    元のテキストをそのまま返す(全体を巻き込んで落とさない)。"""

    class _BoomCleaner:
        def clean_text(self, text):
            raise RuntimeError("boom")

    monkeypatch.setattr(inquiry, "_GENERIC_PII_CLEANER", _BoomCleaner())
    text = "contact taro@example.com now"
    assert inquiry.sanitize_generic_pii(text) == text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
