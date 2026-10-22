# -*- coding: utf-8 -*-
"""dev#1625(2026-08-21 オーナー裁定)回帰テスト: convert_noue.py::
warn_posture_mismatch_cull()。

背景: `pipeline\\blender\\step02_retarget.py`が姿勢不一致ハブを切除すると
`sway_exclusions_{gender}.json`へ"posture mismatch (dev#1625)"タグ付き
エントリを書く。GUIの完了ダイアログへの##AVATAR_WARNING##告知は、
step02_retarget.py自身(Blender工程、Phase 1)ではなくここ
(convert_noue.py、Phase 2-6)で出す——convert.ps1のPhase 1リレーは表示用に
Select-Stringで行を間引いており、##AVATAR_WARNING##はこの条件に一致しない
ため、Phase 1側で直接printしても呼び出し元(app_py)まで届かない
(convert.ps1はこのWPの書き込み許可範囲外、実機検証で発覚)。

G1: 切除ありのsway_exclusions_{gender}.json(dev#1625タグ付き)がある ->
    診断ログ[convert_noue] dev#1625行 + ##AVATAR_WARNING##が出る
G2(負の対照): 切除0件(excludedが空リスト)では##AVATAR_WARNING##が出ない
G3(負の対照): 切除はあるが別理由(容量超過等、dev#1625タグ無し)だけの
    場合も##AVATAR_WARNING##が出ない(本WP以前からの既存挙動を変えない)
G4: sway_exclusions_{gender}.json自体が存在しない(sway_enable=false等)
    場合も静かに何もしない(例外を出さない)
G5: 複数性別(male+female)ぶんを合算した件数がメッセージに出る

実行: python test_convert_noue_posture_mismatch_warning_dev1625.py または
pytest経由
"""
import contextlib
import io
import json
import os
import sys
import tempfile

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


def _write_exclusions(conv, gender, excluded):
    path = os.path.join(conv, f"sway_exclusions_{gender.lower()}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "format": "divetopalworld-sway-exclusions-1",
            "gender": gender.lower(),
            "total_units": len(excluded) + 1,
            "fully_disabled": False,
            "excluded": excluded,
        }, f)


def test_posture_mismatch_entry_triggers_avatar_warning():
    with tempfile.TemporaryDirectory() as conv:
        _write_exclusions(conv, "Female", [
            {"unit_key": "sb:J_Bip_C_Head#5", "source": "sb", "anchor": "J_Bip_C_Head",
             "stage": "gate_transform",
             "reason": "J_Bip_C_Head: posture mismatch (dev#1625): donor "
                       "'NPC_GrassBoss001_Skin001_hat_cone_01' direction differs "
                       "by 45.86 deg (exceeds cull threshold 16.5 deg)"},
        ])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            convert_noue.warn_posture_mismatch_cull(conv, {"Female"})
        out = buf.getvalue()
        check("posture mismatch entry: ##AVATAR_WARNING## appears",
              "##AVATAR_WARNING##" in out, out)
        check("posture mismatch entry: dev#1625 diagnostic tag appears",
              "dev#1625" in out, out)
        check("posture mismatch entry: chain count (1) appears in warning",
              "1 chain(s)" in out, out)


def test_negative_control_zero_exclusions_no_warning():
    """負の対照(G2): excludedが空リストなら何も出ない。"""
    with tempfile.TemporaryDirectory() as conv:
        _write_exclusions(conv, "Female", [])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            convert_noue.warn_posture_mismatch_cull(conv, {"Female"})
        out = buf.getvalue()
        check("zero exclusions: no ##AVATAR_WARNING##",
              "##AVATAR_WARNING##" not in out, out)
        check("zero exclusions: no output at all", out == "", out)


def test_negative_control_other_exclusion_reasons_do_not_trigger():
    """負の対照(G3): dev#1625タグの付かない既存の切除理由(容量超過等)
    だけでは告知しない(本WPが追加した経路だけに反応する)。"""
    with tempfile.TemporaryDirectory() as conv:
        _write_exclusions(conv, "Male", [
            {"unit_key": "sb:J_Sec_L_HoodString1#2", "source": "sb",
             "anchor": "J_Sec_L_HoodString1", "stage": "capacity_overflow",
             "reason": "capacity exceeded, not adopted: J_Sec_L_HoodString1"},
        ])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            convert_noue.warn_posture_mismatch_cull(conv, {"Male"})
        out = buf.getvalue()
        check("non-dev1625 exclusion only: no ##AVATAR_WARNING##",
              "##AVATAR_WARNING##" not in out, out)


def test_missing_exclusions_file_is_a_silent_noop():
    """G4: sway_exclusions_{gender}.json自体が無い(sway_enable=false等)
    場合も例外を出さず何もしない。"""
    with tempfile.TemporaryDirectory() as conv:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            convert_noue.warn_posture_mismatch_cull(conv, {"Female", "Male"})
        out = buf.getvalue()
        check("missing sway_exclusions file: no crash, no warning",
              out == "", out)


def test_both_genders_counts_are_summed():
    """G5: male/female両方にdev#1625切除があれば合算件数が出る。"""
    with tempfile.TemporaryDirectory() as conv:
        entry = {"unit_key": "sb:J_Bip_C_UpperChest#0", "source": "sb",
                  "anchor": "J_Bip_C_UpperChest", "stage": "gate_transform",
                  "reason": "J_Bip_C_UpperChest: posture mismatch (dev#1625): "
                            "donor 'NPC_SnowBoss_belt_01_r' direction differs "
                            "by 120.98 deg (exceeds cull threshold 16.5 deg)"}
        _write_exclusions(conv, "Female", [entry, entry])  # 2件
        _write_exclusions(conv, "Male", [entry])  # 1件
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            convert_noue.warn_posture_mismatch_cull(conv, {"Female", "Male"})
        out = buf.getvalue()
        check("both genders summed: total is 3 chain(s)",
              "3 chain(s)" in out, out)
        # 1行だけ出る(genderごとに複数回出したりしない)
        check("exactly one ##AVATAR_WARNING## line",
              out.count("##AVATAR_WARNING##") == 1, out)


def main():
    test_posture_mismatch_entry_triggers_avatar_warning()
    test_negative_control_zero_exclusions_no_warning()
    test_negative_control_other_exclusion_reasons_do_not_trigger()
    test_missing_exclusions_file_is_a_silent_noop()
    test_both_genders_counts_are_summed()
    print()
    if failures:
        print(f"=== FAIL: {len(failures)} ===")
        for f in failures:
            print(f" - {f}")
        sys.exit(1)
    print("=== ALL PASS ===")


if __name__ == "__main__":
    main()
