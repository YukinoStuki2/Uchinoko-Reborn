# -*- coding: utf-8 -*-
"""vp_preflight_result.py -- dev#1230: ユーザーサイドpreflight非ブロック化の
共有ヘルパー。

背景(dev#1230、2026-08-08オーナー裁定): ユーザーサイド(変換の最後)の
preflightは、FAILでも変換をブロックしない。pak成果物を渡し、GUIが警告
ダイアログでユーザーに選ばせる。preflight検査自体(pipeline\\py\\
preflight_pak.py、全ゲート)は無改変で実行し続け、結果(PASS/FAIL・FAILした
ゲートの詳細)だけを、GUI(app_py\\pipeline_runner.py)が読める構造化JSONへ
落とす。

このモジュールが持つのは「preflight_pak.pyの標準出力から結果を抽出し、
JSONへ書く」部分だけ。preflightサブプロセスの起動そのもの・PASS/FAIL時に
die()するかどうかの分岐は、呼び出し元
(pipeline\\py\\build_pak_from_avatar.py Phase4 / pipeline\\py\\
fast_repack.py --preflight)ごとに既存のまま残す(挙動不変の原則:
relgate.py/release.pyはこのモジュールの新しい書き込み経路を一切呼ばない
ため、開発側の関所は無変更)。

RESULT_FILENAME: 出力先はpakと同じディレクトリ
(os.path.dirname(out_pak)、通常 <job_dir>\\build\\)に固定。
app_py\\pipeline_runner.pyの resolve_preflight_result_path() と
ファイル名を一致させること(app_pyがpipeline\\pyをimportしない設計方針の
ため、DEFAULT_MOUNT等と同じ既存の複製パターンを踏襲、2箇所の定数を
意図的に分離している)。
"""
from __future__ import annotations

import json
import os
import re

RESULT_FILENAME = "preflight_result.json"

# preflight_pak.pyのgate()/finish()が出す `  [FAIL] <name> — <detail>` 行
# (先頭の空白は任意、gate()自体は2スペースインデントで出す)。
_GATE_FAIL_RE = re.compile(r"^\s*\[FAIL\]\s+(.+)$")


def parse_preflight_failed_gate_lines(stdout_text):
    """preflight_pak.pyの標準出力からFAILしたゲート行だけを抽出する。
    stdout_textがNone/空文字列なら空リストを返す(呼び出し失敗等の防御)。"""
    if not stdout_text:
        return []
    out = []
    for line in stdout_text.splitlines():
        m = _GATE_FAIL_RE.match(line)
        if m:
            out.append(m.group(1).strip())
    return out


def result_json_path(out_pak):
    """out_pak(生成されたpakの絶対/相対パス)と同じディレクトリの
    preflight_result.jsonパスを返す。"""
    return os.path.join(os.path.dirname(os.path.abspath(out_pak)), RESULT_FILENAME)


def write_preflight_result_json(out_pak, status, returncode, failed_gates):
    """preflight結果を out_pak と同じディレクトリへ書く。

    status: "PASS" または "FAIL"。
    既存ファイルは無条件で上書きする(同じjob_dir\\buildを再利用する
    再実行のたびに最新状態へ更新するため——古いFAILの残骸の上に新しい
    PASSが埋もれる/その逆の事故を避ける)。書き込みは一時ファイル+
    os.replace()でアトミックにする(read_preflight_result側が書きかけの
    JSONを読む競合を避ける)。

    戻り値: 書き込んだファイルの絶対パス。"""
    path = result_json_path(out_pak)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    doc = {
        "status": status,
        "returncode": returncode,
        "failed_gates": list(failed_gates),
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path
