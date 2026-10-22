# -*- coding: utf-8 -*-
"""dev#1230: vp_preflight_result.py の単体テスト
(ユーザーサイドpreflight非ブロック化、結果JSON生成部分)。

実行: python -m pytest pipeline\\py\\test_vp_preflight_result.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_preflight_result as m  # noqa: E402


def test_parse_preflight_failed_gate_lines_extracts_fail_only():
    stdout_text = (
        "[preflight] job=work\\avatar\\job.json\n"
        "  [PASS] G1 something is fine\n"
        "  [FAIL] G4 hardcoded stub count mismatch — expected 153, got 150\n"
        "  [PASS] G5 slot role OK\n"
        "  [FAIL] G13 DT serial size mismatch\n"
        "\n"
        "=== preflight result: 2 FAIL — do not use this MOD ===\n"
    )
    got = m.parse_preflight_failed_gate_lines(stdout_text)
    assert got == [
        "G4 hardcoded stub count mismatch — expected 153, got 150",
        "G13 DT serial size mismatch",
    ]


def test_parse_preflight_failed_gate_lines_all_pass_returns_empty():
    stdout_text = "  [PASS] G1 ok\n  [PASS] G2 ok\n"
    assert m.parse_preflight_failed_gate_lines(stdout_text) == []


def test_parse_preflight_failed_gate_lines_empty_input():
    assert m.parse_preflight_failed_gate_lines("") == []
    assert m.parse_preflight_failed_gate_lines(None) == []


def test_result_json_path_is_sibling_of_out_pak():
    out_pak = os.path.join("work", "avatar", "build", "avatar_PlayerSwap_P.pak")
    path = m.result_json_path(out_pak)
    assert os.path.basename(path) == "preflight_result.json"
    assert os.path.dirname(path) == os.path.abspath(os.path.dirname(out_pak))


def test_write_preflight_result_json_writes_expected_fields(tmp_path):
    out_pak = str(tmp_path / "build" / "avatar_PlayerSwap_P.pak")
    written = m.write_preflight_result_json(
        out_pak, "FAIL", 1, ["G4 stub mismatch", "G13 DT mismatch"]
    )
    assert os.path.isfile(written)
    with open(written, encoding="utf-8") as f:
        doc = json.load(f)
    assert doc == {
        "status": "FAIL",
        "returncode": 1,
        "failed_gates": ["G4 stub mismatch", "G13 DT mismatch"],
    }


def test_write_preflight_result_json_overwrites_stale_result(tmp_path):
    # 負の対照: 前回FAILの残骸が、今回PASSの結果で正しく上書きされること
    # (古いFAILがGUIへ残り続ける事故の防止)。
    out_pak = str(tmp_path / "build" / "avatar_PlayerSwap_P.pak")
    m.write_preflight_result_json(out_pak, "FAIL", 1, ["G4 stub mismatch"])
    path = m.write_preflight_result_json(out_pak, "PASS", 0, [])
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["status"] == "PASS"
    assert doc["failed_gates"] == []
    # tmpファイルが残っていないこと(os.replace()でアトミックに置換された)
    assert not os.path.isfile(path + ".tmp")
