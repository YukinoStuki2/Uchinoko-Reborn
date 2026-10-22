# test_pipeline_runner_sway_chain_overrides_dev1595.py -- dev#1595
# (issue #1595「GUI揺れ詳細設定のenabled上書きが変換時に脱落する
# (耳OFFが効かない)」)の回帰テスト。実tk.Tk()は使わない(pipeline_runner.py・
# sway_chain_override_store.pyはいずれもtkinter非依存)。
#
# 原因(issue #1595本文、実測はcomodo検体):
#   - 保存側(app_py\ui\sway_style_dialog.py)は偏向判定ベースのdefault_
#     enabled_map(算出元: pipeline\py\sway_chain_defaults.is_default_
#     enabled())で「既定と一致するエントリ」を間引いてから保存する
#     (ラボ憲章④)。
#   - 変換側(app_py\pipeline_runner.py、本テストが直接叩く経路)は
#     sway_chain_override_store.load_config(app_root, vrm_path)をmap無しで
#     呼んでいた。map無し時の`_is_default_entry()`は旧・名前ベース
#     フォールバック(pipeline\py\sway_identify.default_sway_enabled())を
#     使うため、保存時(偏向判定ベース)と読込時(名前ベース)で「既定」の
#     定義が食い違う鎖では、正しく保存されたはずのユーザー上書きが読込時に
#     誤って「既定と同じ」と再判定され、job["sway_chain_overrides"]から
#     脱落していた。
#
# 実測(comodo検体、res\settings_lab_sway_chains.json由来、
# res\work\comodo\build\job_snapshot.jsonでOFF3件の脱落を確認済み):
# Head_L/Head_R/Hips.002は名前に耳/尻尾トークンを含まないため名前ベース
# 既定はOFFだが、非偏向PhysBoneのため偏向判定ベース既定はON。ユーザーが
# これら3件を明示的にOFFへ変更した保存済みエントリが、読込時の名前ベース
# 再判定(OFF==OFFで「既定と同じ」と誤認)により脱落していた。Tail(両定義
# とも既定ON、ユーザーOFF)は両定義で一致して非既定と判定されるため、
# 修正前から正しく読み込めていた——「Tailだけ効いた」の実測と符合する。
#
# 本テストは、修正前(load_config()がdefault_enabled_map省略時に旧
# _is_default_entry()で再間引きする実装)ではHead_L/Head_R/Hips.002の3件が
# 欠落して赤くなり、修正後(load_config()が読込時の再間引きを行わず、
# ファイルの中身をそのまま返す)では8件全てが読み込めることを固定する。
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pipeline_runner  # noqa: E402
import sway_chain_override_store as chain_store  # noqa: E402

AVATAR = "C:\\fake_comodo.vrm"

# comodo実測相当の8鎖(モジュールdocstring参照)。
# ---- OFF 4件(うちHead_L/Head_R/Hips.002の3件が、保存時(偏向判定ベース、
#      真の既定=ON)と読込時フォールバック(名前ベース、既定=OFF)の食い違いで
#      脱落していた核心3件。Tailは両定義が一致[既定ON]するため修正前から
#      正しく読み込めていた対照)。
_OFF_ENTRIES = [
    {"bones": ["Head", "Head_L_01", "Head_L_02"], "enabled": False,
     "hardness": "follow", "manual": False, "safety_margin": 1},
    {"bones": ["Head", "Head_R_01", "Head_R_02"], "enabled": False,
     "hardness": "follow", "manual": False, "safety_margin": 1},
    {"bones": ["Hips", "Hips_002_01", "Hips_002_02"], "enabled": False,
     "hardness": "follow", "manual": False, "safety_margin": 1},
    {"bones": ["Hips", "Tail_01", "Tail_02"], "enabled": False,
     "hardness": "follow", "manual": False, "safety_margin": 1},
]
# ---- ON 4件(既定OFFの鎖をユーザーが明示的にON。名前ベース・偏向判定ベース
#      いずれの既定判定でも一致してOFFのため、修正前から正しく読み込めていた
#      対照。Hips.002_L/R系の実測になぞらえた命名)。
_ON_ENTRIES = [
    {"bones": ["Hips", "Hips_002_L_01"], "enabled": True,
     "hardness": "follow", "manual": False, "safety_margin": 1},
    {"bones": ["Hips", "Hips_002_L_02"], "enabled": True,
     "hardness": "follow", "manual": False, "safety_margin": 1},
    {"bones": ["Hips", "Hips_002_R_01"], "enabled": True,
     "hardness": "follow", "manual": False, "safety_margin": 1},
    {"bones": ["Hips", "Hips_002_R_02"], "enabled": True,
     "hardness": "follow", "manual": False, "safety_margin": 1},
]

_ALL_ENTRIES = _OFF_ENTRIES + _ON_ENTRIES  # 8鎖


def _write_state_file(app_root: str, avatar_path: str, chains) -> None:
    """sway_chain_override_store.save_config()相当の最終形(=保存時に
    正しい偏向判定ベースmapで既に間引き済み)を直接書く。本テストの狙いは
    「読込側の再間引き」だけを検査することなので、保存経路そのもの
    (GUI+save_config)は経由しない——ファイルの中身は、GUIが正しく保存した
    後の状態を模している(comodoの実測settings_lab_sway_chains.jsonと同型)。"""
    path = os.path.join(app_root, chain_store._STATE_FILENAME)  # noqa: SLF001
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"avatar_path": os.path.normcase(os.path.abspath(avatar_path)),
                   "chains": chains}, f, ensure_ascii=False, indent=1)


def _job_sway_chain_overrides(app_root: str, avatar_path: str):
    """app_py\\pipeline_runner.py write_job()が実際に使う経路そのもの
    (457行付近: sway_chain_override_store.load_config(app_root, vrm_path)、
    map無し)を直接再現する。"""
    overrides = pipeline_runner.sway_chain_override_store.load_config(app_root, avatar_path)
    job = {}
    if overrides:
        job["sway_chain_overrides"] = overrides
    return job


def test_all_eight_chains_reach_job_sway_chain_overrides(tmp_path):
    """受入ゲート1: comodo実測相当の8鎖(うちOFF4件、少なくとも
    Head_L/Head_R/Hips.002の3件がバグの核心)全てがjob["sway_chain_overrides"]
    へ載ること。"""
    app_root = str(tmp_path)
    _write_state_file(app_root, AVATAR, _ALL_ENTRIES)

    job = _job_sway_chain_overrides(app_root, AVATAR)

    assert "sway_chain_overrides" in job
    by_last_bone = {tuple(e["bones"])[-1]: e for e in job["sway_chain_overrides"]}
    assert len(by_last_bone) == 8, (
        f"8鎖全件が載っていない(欠落分がdev#1595の再間引きバグ): {sorted(by_last_bone)}"
    )
    # バグの核心3件(名前ベース既定=OFF・偏向判定ベース既定=ON、ユーザーOFF)。
    for last_bone in ("Head_L_02", "Head_R_02", "Hips_002_02"):
        assert last_bone in by_last_bone, f"{last_bone} が脱落している(dev#1595の再現)"
        assert by_last_bone[last_bone]["enabled"] is False
    # 対照: 両定義が一致するTail(修正前から正しく読み込めていた)。
    assert by_last_bone["Tail_02"]["enabled"] is False
    # 対照: ON側4件も全て残ること。
    for last_bone in ("Hips_002_L_01", "Hips_002_L_02", "Hips_002_R_01", "Hips_002_R_02"):
        assert by_last_bone[last_bone]["enabled"] is True


def test_negative_control_no_state_file_means_no_overrides_key(tmp_path):
    """負の対照(受入ゲート2): 設定ファイル自体が存在しない(=このアバターの
    ラボ設定を一度も保存していない)ときは、job["sway_chain_overrides"]自体が
    現れない(既定挙動不変、ラボ憲章④)。"""
    app_root = str(tmp_path)
    job = _job_sway_chain_overrides(app_root, AVATAR)
    assert "sway_chain_overrides" not in job


def test_negative_control_different_avatar_residue_means_no_overrides_key(tmp_path):
    """負の対照(受入ゲート2続き): 別アバターの残留データがあっても、
    現在のvrm_pathと一致しなければjob["sway_chain_overrides"]は現れない
    (別アバター編集時の残留を誤爆させない既存方針の継続確認)。"""
    app_root = str(tmp_path)
    _write_state_file(app_root, "C:\\other_avatar.vrm", _ALL_ENTRIES)
    job = _job_sway_chain_overrides(app_root, AVATAR)
    assert "sway_chain_overrides" not in job
