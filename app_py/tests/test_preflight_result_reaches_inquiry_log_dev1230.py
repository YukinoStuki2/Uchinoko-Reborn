# test_preflight_result_reaches_inquiry_log_dev1230.py -- dev#1230受入条件②:
# 「preflightは全ゲート実行を維持し、FAIL詳細を診断ログへ必ず記録
# (問合せログに載ることをテストで確認)」の直接検証。
#
# pipeline\py\vp_preflight_result.write_preflight_result_json() が
# <job_dir>\build\preflight_result.json へ書くFAIL詳細(failed_gates)が、
# app_py\inquiry.build_work_dir_attachment_text()(main_window.py
# _read_full_log_attachment_text() が実際に呼ぶのと同じ経路、
# labeled_dirs=[("work", job_dir)])の出力に実際に現れることを、
# 2つのモジュールを実際に組み合わせて検証する(「実装した」と「効いている」は
# 別、CLAUDE.md)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_DIR = os.path.dirname(_APP_PY_DIR)
_PIPELINE_PY_DIR = os.path.join(_REPO_DIR, "pipeline", "py")
for _dir in (_APP_PY_DIR, _PIPELINE_PY_DIR):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

import inquiry  # noqa: E402
import vp_preflight_result  # noqa: E402


def test_preflight_fail_detail_appears_in_work_dir_attachment_text(tmp_path):
    job_dir = str(tmp_path / "MyAvatar")
    out_pak = os.path.join(job_dir, "build", "MyAvatar_PlayerSwap_P.pak")
    vp_preflight_result.write_preflight_result_json(
        out_pak, "FAIL", 1,
        ["G13 DT serial size mismatch — Got 100, Expected 101"],
    )
    # 変換フローがpakと同じディレクトリへ他の診断ファイルも残す想定を模倣
    # (実際の構造: job_dir\build\logs\convert_noue.log等)。preflight_result.json
    # 単体の到達を見たいので、他ファイルは最小限にする。

    text = inquiry.build_work_dir_attachment_text(
        labeled_dirs=[("work", job_dir)], labeled_files=[]
    )

    assert "preflight_result.json" in text
    assert '"status": "FAIL"' in text
    assert "G13 DT serial size mismatch" in text


def test_preflight_pass_result_also_reaches_attachment_but_without_fail_marker(tmp_path):
    # 負の対照: PASS結果はFAIL文言を含まず、statusがPASSのまま届くこと
    # (誤ってFAILしたかのような文言が混入していないことの確認)。
    job_dir = str(tmp_path / "MyAvatar")
    out_pak = os.path.join(job_dir, "build", "MyAvatar_PlayerSwap_P.pak")
    vp_preflight_result.write_preflight_result_json(out_pak, "PASS", 0, [])

    text = inquiry.build_work_dir_attachment_text(
        labeled_dirs=[("work", job_dir)], labeled_files=[]
    )

    assert '"status": "PASS"' in text
    assert '"status": "FAIL"' not in text


def test_no_preflight_result_file_means_no_crash_and_empty_attachment(tmp_path):
    # 負の対照: preflight_result.json自体が無い(旧ジョブ/--skip-preflight)
    # 場合でも、収集処理自体は例外を投げず空文字列を返すこと(dev#921の
    # 「ログが無いことを理由に送信自体を失敗させない」方針を壊していない)。
    job_dir = str(tmp_path / "MyAvatar")
    os.makedirs(job_dir, exist_ok=True)

    text = inquiry.build_work_dir_attachment_text(
        labeled_dirs=[("work", job_dir)], labeled_files=[]
    )

    assert text == ""
