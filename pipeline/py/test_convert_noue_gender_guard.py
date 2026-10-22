# -*- coding: utf-8 -*-
"""dev#1572回帰テスト: convert_noue.py: check_dual_gender_required()の単体試験。

背景(2026-08-19朝オーナー裁定): job.jsonの `genders` は本来デバッグ用
(dev#336の性別限定はラボ機能で現在はラボからも撤去済み。gender_filter_store.py
冒頭・app_py\\ui\\lab_window.py:541付近・app_py\\pipeline_runner.py:475付近の
コメント参照)で、製品GUIに性別限定機能は存在しない。試験レーンが片性別
(Female-only)jobで揺れもの検証をしてしまい「製品版と違うパイプラインで
試験するメリットは0」と裁定された。本ファイルはconvert_noue.py本体の
main()を丸ごと走らせず(bpy等の重い依存を避ける)、
check_dual_gender_required()だけを直接呼び、job.jsonのgendersキーで
片性別ビルドを要求すると即die()(sys.exit(1))することを検証する。

G1: genders=["Female"](片性別) -> SystemExitで異常終了し、標準出力の
    メッセージに「両性別」を含む
G2: genders=["Male"](片性別、別ケース) -> 同様にSystemExit
G3(負の対照・正常系): genders=["Male","Female"](順不同含む)/ genders
    キー無し -> 例外を出さず通過する(既定の両性別ビルドを妨げない)
G4(負の対照・構造): 「入口チェックそのものが無ければ片性別が素通りする」
    ことを示す最小モデルで、新チェック関数が無いと通ってしまうことを確認
    (=このテストが新実装(check_dual_gender_required呼び出し)に依存して
    いる証拠。旧実装(subsetチェックのみ)は単一性別を許可していた)

実行: python test_convert_noue_gender_guard.py または pytest経由
"""
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert_noue  # noqa: E402

failures = []


def check(label, cond, detail=""):
    if cond:
        print(f"[PASS] {label}")
    else:
        print(f"[FAIL] {label} {detail}")
        failures.append(label)
    assert cond, f"{label} {detail}".rstrip()


def _run_guard(job):
    """check_dual_gender_required(job)を呼び、(raised: bool, stdout: str)を返す。"""
    buf = io.StringIO()
    raised = False
    with contextlib.redirect_stdout(buf):
        try:
            convert_noue.check_dual_gender_required(job)
        except SystemExit:
            raised = True
    return raised, buf.getvalue()


def test_single_female_is_rejected():
    """G1: genders=["Female"]は即die()(SystemExit)し、メッセージに
    「両性別」を含む。"""
    raised, out = _run_guard({"genders": ["Female"]})
    check("check_dual_gender_required(Female-only): raises SystemExit", raised, out)
    check("check_dual_gender_required(Female-only): message mentions 両性別",
          "両性別" in out, out)


def test_single_male_is_rejected():
    """G2: genders=["Male"]も同様に即die()する(片方だけの別ケース)。"""
    raised, out = _run_guard({"genders": ["Male"]})
    check("check_dual_gender_required(Male-only): raises SystemExit", raised, out)
    check("check_dual_gender_required(Male-only): message mentions 両性別",
          "両性別" in out, out)


def test_empty_genders_list_is_rejected():
    """G1派生: genders=[](空リスト)も片性別と同様に拒否される
    (0性別は両性別と一致しないため)。"""
    raised, out = _run_guard({"genders": []})
    check("check_dual_gender_required(empty list): raises SystemExit", raised, out)


def test_both_genders_pass_control():
    """G3(負の対照): genders=["Male","Female"]は通過する(既定の両性別
    ビルドを妨げない)。"""
    raised, out = _run_guard({"genders": ["Male", "Female"]})
    check("check_dual_gender_required(Male+Female): does not raise",
          not raised, out)


def test_reversed_order_both_genders_pass_control():
    """G3(負の対照・順不同): genders=["Female","Male"](逆順)も通過する
    (集合比較であって順序に依存しないことの確認)。"""
    raised, out = _run_guard({"genders": ["Female", "Male"]})
    check("check_dual_gender_required(Female+Male, reversed): does not raise",
          not raised, out)


def test_missing_genders_key_pass_control():
    """G3(負の対照): gendersキー自体が無いjob(通常の製品job.json)は
    従来どおり通過する。"""
    raised, out = _run_guard({})
    check("check_dual_gender_required(no genders key): does not raise",
          not raised, out)


def test_structural_negative_control_old_behavior_would_pass():
    """G4(負の対照・構造): 新チェック関数(check_dual_gender_required)を
    呼ばない旧実装相当(job.get("genders")をそのまま使うだけ)では、
    片性別jobが素通りしてしまうことを示す。これは
    check_dual_gender_required自体が新設された防波堤であることの証明。
    """
    job = {"genders": ["Female"]}
    # 旧実装相当: 単純にgenders値を読むだけで、拒否ロジックが無い
    old_style_requested = set(job.get("genders") or ["Male", "Female"])
    check("old-style code would silently accept single-gender job "
          "(demonstrates the guard is the thing preventing it)",
          old_style_requested == {"Female"},
          old_style_requested)
    # 新実装は同じjobを確実に拒否する(上と対比)
    raised, _ = _run_guard(job)
    check("new check_dual_gender_required rejects the same job",
          raised)


def main():
    test_single_female_is_rejected()
    test_single_male_is_rejected()
    test_empty_genders_list_is_rejected()
    test_both_genders_pass_control()
    test_reversed_order_both_genders_pass_control()
    test_missing_genders_key_pass_control()
    test_structural_negative_control_old_behavior_would_pass()
    print()
    if failures:
        print(f"=== FAIL: {len(failures)} ===")
        for f in failures:
            print(f" - {f}")
        sys.exit(1)
    print("=== ALL PASS ===")


if __name__ == "__main__":
    main()
