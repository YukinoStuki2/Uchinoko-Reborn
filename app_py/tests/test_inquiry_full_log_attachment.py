# test_inquiry_full_log_attachment.py -- 全ログ添付版(dev#921第2層の一般化、
# 2026-08-03オーナー裁定)の受入条件。
#
# オーナー原文:
#   「僕のローカルと同じレベルのログ(サニタイズはショウガいないけど)が
#   とれるようにして」「全部サニタイズしておくればいいだけでしょ。表も何も
#   いるか?」
#
# 対象: app_py\inquiry.py に追加した
#   - collect_log_like_files()            -- ディレクトリ群を再帰的に歩き、
#     バイナリ/非ログ成果物を除いた全ファイルパスを集める
#   - read_attachment_file_text()          -- 1ファイルをテキストとして読む
#   - build_work_dir_attachment_text()     -- 複数ディレクトリ/個別ファイルを
#     1つのテキストへ束ねる(マーカー付き)
#
# マスキング自体(sanitize_for_clipboard/mask_full_log_for_attachment/
# build_layer2_attachment_block)は新規に書き起こさない(既存実装の再利用)。
# 本ファイルは「収集」の受入条件と、既存マスキングとの結合(負の対照込み)を見る。
from __future__ import annotations

import base64
import gzip as gzip_module
import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import inquiry  # noqa: E402


# ---------------------------------------------------------------------------
# collect_log_like_files: バイナリ/非ログ成果物の除外
# ---------------------------------------------------------------------------


def _write(path, content=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def test_collect_log_like_files_includes_text_excludes_binary(tmp_path):
    root = str(tmp_path / "work" / "SampleAvatar")
    _write(os.path.join(root, "job.json"), '{"avatar_name": "SampleAvatar"}')
    _write(os.path.join(root, "build", "logs", "convert_noue.log"), "line1\nline2\n")
    _write(os.path.join(root, "vanilla", "sk_inventory.json"), "{}")
    _write(os.path.join(root, "vanilla", "dup_hair.csv"), "a,b,c\n")
    # バイナリ成果物(除外対象)
    _write(os.path.join(root, "converted", "step01_clean.blend"), "not really blend bytes")
    _write(os.path.join(root, "build", "atlas", "atlas_body.png"), "not really png bytes")
    _write(os.path.join(root, "build", "M_VP_m00.uasset"), "not really uasset bytes")
    _write(os.path.join(root, "build", "relgateAvatar_PlayerSwap_P.pak"), "not really pak bytes")

    files = inquiry.collect_log_like_files([root])
    rels = sorted(os.path.relpath(p, root) for p in files)

    assert rels == sorted([
        "job.json",
        os.path.join("build", "logs", "convert_noue.log"),
        os.path.join("vanilla", "sk_inventory.json"),
        os.path.join("vanilla", "dup_hair.csv"),
    ])


def test_collect_log_like_files_excludes_noue_work_dump_but_keeps_logs(tmp_path):
    """実測(本WP): work\\<name>\\build\\noue_work\\dump\\avatar_{male,female}.json
    は1ファイル約10MBの生メッシュダンプ(ログではない)。同じlogsディレクトリの
    dump_{Male,Female}.log(テキストの実行ログ)は対象のまま残ること。"""
    root = str(tmp_path / "work" / "SampleAvatar")
    _write(os.path.join(root, "build", "noue_work", "dump", "avatar_male.json"), "{huge mesh dump}")
    _write(os.path.join(root, "build", "noue_work", "dump", "avatar_female.json"), "{huge mesh dump}")
    _write(os.path.join(root, "build", "noue_work", "logs", "dump_Male.log"), "dump log male\n")
    _write(os.path.join(root, "build", "noue_work", "logs", "dump_Female.log"), "dump log female\n")

    files = inquiry.collect_log_like_files([root])
    rels = sorted(os.path.relpath(p, root) for p in files)

    assert rels == sorted([
        os.path.join("build", "noue_work", "logs", "dump_Male.log"),
        os.path.join("build", "noue_work", "logs", "dump_Female.log"),
    ])


def test_collect_log_like_files_excludes_gz():
    """2026-08-03オーナー追加裁定(送付ログはUI表示必須)対応の実測結果:
    vanilla\\pak_entries.txt.gz は展開すると約14.7MB(実測、本WP)になり、
    UI表示・行単位マスキング双方の応答性を損なう。.gzは「既に圧縮済みの
    不透明バイナリ」として除外する(拡張子ベースの機械的な除外基準)。"""
    assert ".gz" in inquiry._ATTACHMENT_BINARY_EXTS


def test_collect_log_like_files_skips_missing_directory(tmp_path):
    missing = str(tmp_path / "does_not_exist")
    assert inquiry.collect_log_like_files([missing]) == []
    assert inquiry.collect_log_like_files([None, "", missing]) == []


# ---------------------------------------------------------------------------
# read_attachment_file_text
# ---------------------------------------------------------------------------


def test_read_attachment_file_text_returns_none_for_missing_file(tmp_path):
    missing = str(tmp_path / "nope.log")
    assert inquiry.read_attachment_file_text(missing) is None


def test_read_attachment_file_text_reads_utf8(tmp_path):
    p = str(tmp_path / "a.log")
    _write(p, "hello world\nsecond line\n")
    assert inquiry.read_attachment_file_text(p) == "hello world\nsecond line\n"


# ---------------------------------------------------------------------------
# build_work_dir_attachment_text: 複数ディレクトリ・個別ファイルの結合
# ---------------------------------------------------------------------------


def test_build_work_dir_attachment_text_combines_dirs_and_files_with_markers(tmp_path):
    job_dir = str(tmp_path / "work" / "SampleAvatar")
    export_dir = str(tmp_path / "work" / "SampleAvatar_export")
    launch_log = str(tmp_path / "logs" / "launch.log")

    _write(os.path.join(job_dir, "job.json"), '{"avatar_name": "SampleAvatar"}')
    _write(os.path.join(export_dir, "unity_export.log"), "unity export log content\n")
    _write(launch_log, "gui launch log content\n")

    text = inquiry.build_work_dir_attachment_text(
        labeled_dirs=[("work", job_dir), ("unity_export", export_dir)],
        labeled_files=[("launch_log", launch_log)],
    )

    assert "job.json" in text
    assert '"avatar_name": "SampleAvatar"' in text
    assert "unity export log content" in text
    assert "gui launch log content" in text
    # マーカーで区切られていること(どのファイルの内容かが読み取れる)
    assert "----- file: work" in text
    assert "----- file: unity_export" in text
    assert "----- file: launch_log -----" in text


def test_build_work_dir_attachment_text_empty_when_nothing_present(tmp_path):
    """負の対照(受入ゲート③の土台): work_root配下にログが1件も無くても
    例外を投げず、空文字列を返す(呼び出し元がNone扱いして添付無し送信に
    倒せる)。"""
    missing_dir = str(tmp_path / "no_such_avatar")
    missing_file = str(tmp_path / "no_such_launch.log")
    text = inquiry.build_work_dir_attachment_text(
        labeled_dirs=[("work", missing_dir)],
        labeled_files=[("launch_log", missing_file)],
    )
    assert text == ""


def test_build_work_dir_attachment_text_no_args_returns_empty():
    assert inquiry.build_work_dir_attachment_text() == ""


# ---------------------------------------------------------------------------
# 既存マスキングとの結合(build_layer2_attachment_block経由)+負の対照
# ---------------------------------------------------------------------------

_FAKE_PROJECT_PATH = r"C:\UnityP\SampleProjectName\Assets\Avatar\SampleAvatar.prefab"


def test_full_pipeline_masks_paths_from_multiple_collected_files(tmp_path):
    job_dir = str(tmp_path / "work" / "SampleAvatar")
    export_dir = str(tmp_path / "work" / "SampleAvatar_export")
    _write(
        os.path.join(job_dir, "build", "logs", "convert_noue.log"),
        "processing asset at " + _FAKE_PROJECT_PATH + "\ndone\n",
    )
    _write(
        os.path.join(export_dir, "unity_export.log"),
        "export failed for " + _FAKE_PROJECT_PATH + "\n",
    )

    attachment_text = inquiry.build_work_dir_attachment_text(
        labeled_dirs=[("work", job_dir), ("unity_export", export_dir)],
    )
    block, dropped = inquiry.build_layer2_attachment_block(attachment_text)

    assert dropped == 0
    assert _FAKE_PROJECT_PATH not in block
    assert "SampleProjectName" not in block
    assert "ext=.prefab" in block  # 構造情報は残る(dev#921既存契約)
    assert "done" in block
    assert "export failed for" in block


def test_negative_control_full_pipeline_leaks_without_masking(monkeypatch, tmp_path):
    """負の対照: sanitize_for_clipboardを恒等関数に差し替えると、複数ファイル
    束ねた添付でも生パスがそのまま漏れることを確認する(検出力の実測、
    test_inquiry_layer2_dev921.pyの既存パターンを多ファイル収集の下流にも
    適用)。"""
    job_dir = str(tmp_path / "work" / "SampleAvatar")
    _write(
        os.path.join(job_dir, "build", "logs", "convert_noue.log"),
        "processing asset at " + _FAKE_PROJECT_PATH + "\n",
    )
    attachment_text = inquiry.build_work_dir_attachment_text(labeled_dirs=[("work", job_dir)])

    monkeypatch.setattr(inquiry, "sanitize_for_clipboard", lambda s: s)
    block, _dropped = inquiry.build_layer2_attachment_block(attachment_text)

    assert _FAKE_PROJECT_PATH in block, (
        "負の対照が成立しない: sanitize_for_clipboardを無効化しても生パスが"
        "block出力に現れなかった(テストフィクスチャの前提が崩れている)"
    )


# ---------------------------------------------------------------------------
# 受入ゲート③: ログファイルが1つも無い場合でも問い合わせ送信自体は成功する
# (build_report_payload_jsonレベルでの確認。UIレベルはtest_support_dialog_
# full_log_attachment.pyで確認する)
# ---------------------------------------------------------------------------


def test_payload_build_succeeds_with_zero_collected_log_files(tmp_path):
    missing_dir = str(tmp_path / "no_such_avatar")
    attachment_text = inquiry.build_work_dir_attachment_text(labeled_dirs=[("work", missing_dir)])
    assert attachment_text == ""

    payload_json, masked_log = inquiry.build_report_payload_json(
        version="v2.3.7",
        lang="ja",
        os_description="Windows 11",
        avatar_name="a.vrm",
        status_text="idle",
        channel="dev",
        log_text="diagnostics only, no attachment",
        attachment_log_text=attachment_text or None,
    )
    data = json.loads(payload_json)
    decoded = gzip_module.decompress(base64.b64decode(data["log_gzip_b64"])).decode("utf-8")
    assert decoded == "diagnostics only, no attachment"
    assert inquiry._ATTACHMENT_BEGIN_MARKER not in decoded
