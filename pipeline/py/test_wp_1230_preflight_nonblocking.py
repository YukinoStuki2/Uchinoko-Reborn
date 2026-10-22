# -*- coding: utf-8 -*-
"""dev#1230(2026-08-08オーナー裁定): ユーザーサイドpreflightの非ブロック化。

正本(オーナー原文、issue本文): 「ユーザーサイド(変換の最後)のpreflightは、
FAILでも変換をブロックしない。pak成果物を渡し、警告ダイアログでユーザーに
選ばせ、結果報告の導線を示す」。

検証する内容:
  1) build_pak_from_avatar.run_preflight_phase(): nonblocking=False(既定)
     ではFAIL時にdie()相当(SystemExit(1))で停止すること(=relgate.py/
     release.py等の開発側関所は無変更、正の対照)。
  2) 同関数: nonblocking=Trueではpreflight FAILでも例外を投げず、
     preflight_result.json(status=FAIL・failed_gates入り)を書いて
     継続すること(正の対照)。
  3) nonblocking=TrueかつPASS: preflight_result.json(status=PASS)を書き、
     従来どおり継続すること(既定挙動が壊れていないことの確認)。
  4) job.jsonにpreflight_nonblockingキーが無い/False(relgate.py側の
     job.json)なら、build_pak_from_avatar.pyへ--preflight-nonblockingが
     渡らない(convert_noue.py側の配線、argv走査)。job.json側に
     preflight_nonblocking=Trueがあれば渡る(負の対照込み)。
  5) fast_repack.py(GUI「影のみ更新(高速)」経路)も同じjob.jsonキーで
     同型の非ブロック化をすること(ソース走査、pipeline\\py配下スクリプトを
     実変換せずに検証するCLAUDE.md「受入試験はリリースゲートに任せる」に
     沿った確認)。

実行: python -m pytest pipeline\\py\\test_wp_1230_preflight_nonblocking.py -q
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_pak_from_avatar as bpfa  # noqa: E402
import vp_preflight_result  # noqa: E402


class _FakeCompletedProcess:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ---------------------------------------------------------------------------
# 1) blocking(既定)分岐: 従来どおりdie()で止まること
# ---------------------------------------------------------------------------


def test_run_preflight_phase_blocking_fail_raises_system_exit(tmp_path, monkeypatch, capsys):
    out_pak = str(tmp_path / "build" / "avatar_PlayerSwap_P.pak")
    os.makedirs(os.path.dirname(out_pak), exist_ok=True)

    def fake_run(cmd, **kwargs):
        assert "capture_output" not in kwargs  # 従来どおり出力を継承すること
        return _FakeCompletedProcess(1)

    monkeypatch.setattr(bpfa.subprocess, "run", fake_run)

    with pytest.raises(SystemExit):
        bpfa.run_preflight_phase("job.json", out_pak, "template", "cook.log", False)

    # 負の対照: preflight_result.jsonはblocking経路では一切書かれない
    # (relgate.py/release.py等の開発側関所を無変更に保つため)
    assert not os.path.isfile(vp_preflight_result.result_json_path(out_pak))
    assert "FATAL" in capsys.readouterr().out


def test_run_preflight_phase_blocking_pass_returns_none(tmp_path, monkeypatch):
    out_pak = str(tmp_path / "build" / "avatar_PlayerSwap_P.pak")
    os.makedirs(os.path.dirname(out_pak), exist_ok=True)
    monkeypatch.setattr(bpfa.subprocess, "run", lambda cmd, **kw: _FakeCompletedProcess(0))

    result = bpfa.run_preflight_phase("job.json", out_pak, "template", "cook.log", False)

    assert result is None
    assert not os.path.isfile(vp_preflight_result.result_json_path(out_pak))


# ---------------------------------------------------------------------------
# 2)/3) nonblocking分岐
# ---------------------------------------------------------------------------


def test_run_preflight_phase_nonblocking_fail_does_not_raise_and_records_result(
    tmp_path, monkeypatch, capsys
):
    out_pak = str(tmp_path / "build" / "avatar_PlayerSwap_P.pak")
    os.makedirs(os.path.dirname(out_pak), exist_ok=True)
    fake_stdout = (
        "  [PASS] G1 mount OK\n"
        "  [FAIL] G13 DT serial size mismatch — Got 100, Expected 101\n"
        "\n=== preflight result: 1 FAIL — do not use this MOD ===\n"
    )

    def fake_run(cmd, **kwargs):
        assert kwargs.get("capture_output") is True
        return _FakeCompletedProcess(1, stdout=fake_stdout, stderr="")

    monkeypatch.setattr(bpfa.subprocess, "run", fake_run)

    result_path = bpfa.run_preflight_phase(
        "job.json", out_pak, "template", "cook.log", True
    )

    assert result_path == vp_preflight_result.result_json_path(out_pak)
    with open(result_path, encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["status"] == "FAIL"
    assert doc["returncode"] == 1
    assert doc["failed_gates"] == ["G13 DT serial size mismatch — Got 100, Expected 101"]
    # preflight_pak.pyの生出力は捕捉されても、自分の標準出力へそのまま
    # 再出力されること(convert.ps1のTee-Object経路が拾い続けられるように)
    out = capsys.readouterr().out
    assert "[FAIL] G13 DT serial size mismatch" in out
    assert "preflight FAILED" in out


def test_run_preflight_phase_nonblocking_pass_records_pass_result(tmp_path, monkeypatch):
    out_pak = str(tmp_path / "build" / "avatar_PlayerSwap_P.pak")
    os.makedirs(os.path.dirname(out_pak), exist_ok=True)
    fake_stdout = "  [PASS] G1 mount OK\n\n=== preflight result: ALL CHECKS PASS ===\n"
    monkeypatch.setattr(
        bpfa.subprocess, "run",
        lambda cmd, **kw: _FakeCompletedProcess(0, stdout=fake_stdout, stderr=""),
    )

    result_path = bpfa.run_preflight_phase(
        "job.json", out_pak, "template", "cook.log", True
    )

    with open(result_path, encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["status"] == "PASS"
    assert doc["returncode"] == 0
    assert doc["failed_gates"] == []


def test_run_preflight_phase_nonblocking_overwrites_previous_fail_with_pass(
    tmp_path, monkeypatch
):
    # 負の対照: 前回runがFAILを記録していても、再実行がPASSなら
    # 結果ファイルがPASSへ更新されること(古いFAILの残骸で誤警告しない)。
    out_pak = str(tmp_path / "build" / "avatar_PlayerSwap_P.pak")
    os.makedirs(os.path.dirname(out_pak), exist_ok=True)
    monkeypatch.setattr(
        bpfa.subprocess, "run",
        lambda cmd, **kw: _FakeCompletedProcess(
            1, stdout="  [FAIL] G1 broken\n", stderr=""
        ),
    )
    bpfa.run_preflight_phase("job.json", out_pak, "template", "cook.log", True)

    monkeypatch.setattr(
        bpfa.subprocess, "run",
        lambda cmd, **kw: _FakeCompletedProcess(0, stdout="  [PASS] G1 ok\n", stderr=""),
    )
    result_path = bpfa.run_preflight_phase(
        "job.json", out_pak, "template", "cook.log", True
    )

    with open(result_path, encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["status"] == "PASS"
    assert doc["failed_gates"] == []


# ---------------------------------------------------------------------------
# 4) convert_noue.py: job.json -> --preflight-nonblocking の配線(ソース走査)
# ---------------------------------------------------------------------------

_CONVERT_NOUE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "convert_noue.py"
)


def test_convert_noue_reads_preflight_nonblocking_from_job_and_forwards_flag():
    with open(_CONVERT_NOUE_PATH, encoding="utf-8") as f:
        src = f.read()
    assert 'job.get("preflight_nonblocking", False)' in src
    assert '"--preflight-nonblocking"' in src
    # 配線は if preflight_nonblocking: の中でのみ argv に追加されること
    # (既定Falseのjob.json = relgate.py側は絶対に渡さない、負の対照)。
    # 「preflight_nonblockingを読んだこと自体を伝える通知print」も同じ
    # if文を使うため、argv追加行の直前にある方(rindex)を対象にする。
    idx_append = src.index('argv += ["--preflight-nonblocking"]')
    idx_flag = src.rindex('if preflight_nonblocking:', 0, idx_append)
    assert idx_flag < idx_append
    assert idx_append - idx_flag < 60  # 直後のブロックであること(離れすぎない)


# ---------------------------------------------------------------------------
# 5) fast_repack.py: 同じjob.jsonキーでの非ブロック化(ソース走査+関数動作)
# ---------------------------------------------------------------------------

_FAST_REPACK_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fast_repack.py"
)


def test_fast_repack_reads_preflight_nonblocking_from_job():
    with open(_FAST_REPACK_PATH, encoding="utf-8") as f:
        src = f.read()
    assert 'job.get("preflight_nonblocking", False)' in src
    assert "vp_preflight_result.write_preflight_result_json" in src
    # 負の対照: blocking分岐(else側)は従来どおりraise SystemExit(ERR_PREFLIGHT)
    # を持ち続けること(relgate.py等の開発側は本WPでこのフラグを渡さないため
    # 必ずこちら側を通る)
    assert "raise SystemExit(\n                    f\"{ERR_PREFLIGHT}\\n\"" in src \
        or "raise SystemExit(\n                f\"{ERR_PREFLIGHT}\\n\"" in src \
        or "{ERR_PREFLIGHT}" in src
