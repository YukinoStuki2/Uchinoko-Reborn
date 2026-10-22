# test_pipeline_runner_find_blender_dev23c.py -- dev#23c受入条件:
#
# dev#23(横断監査PR#754)の申し送りに残っていた唯一の未修理欠落
# 「pipeline_runner.find_blender()には②手動指定・③探索ログが無い」の解消を
# 検査する。dev#23bでblender_setup.find_blender()に実装済みの②③を
# pipeline_runner.find_blender()が委譲によってそのまま継承していることを
# 確認する(2重実装の解消。test_blender_setup.pyのdev#23bテストと対になる
# pipeline_runner側の受入試験)。
#
# 受入ゲート(WP指示書より):
#   ①自動発見成功 ②D2P_BLENDER_EXEによる手動指定が効く
#   ③設定ファイルによる手動指定が効く ④探索trailがログに出る
#   負の対照: (a) 手動指定に存在しないパスを与えると黙って自動発見へ落ちず
#             明示的に失敗すること
from __future__ import annotations

import os
import sys

import pytest

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import blender_setup  # noqa: E402
import pipeline_runner as pr  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_blender_env(monkeypatch):
    # test_blender_setup.pyの_clean_blender_envと同じ理由: 開発機の実環境変数に
    # 左右されないようにする(D2P_BLENDER_EXEが万一実行環境に設定されていても、
    # 各テストは明示的にmonkeypatch.setenvしたときだけ有効にする)。
    monkeypatch.delenv(blender_setup.ENV_BLENDER_EXE, raising=False)


# ---------------------------------------------------------------------------
# ① 自動発見成功(既定経路。手動指定は一切設定しない)
# ---------------------------------------------------------------------------


def test_pipeline_runner_find_blender_auto_discovery_succeeds(tmp_path):
    app_root = tmp_path
    tools_dir = app_root / "assets" / "tools" / "blender-4.3.2-windows-x64"
    tools_dir.mkdir(parents=True)
    exe = tools_dir / "blender.exe"
    exe.write_text("stub")

    result = pr.find_blender(str(app_root))
    assert result == str(exe)


# ---------------------------------------------------------------------------
# ② D2P_BLENDER_EXE による手動指定が効く
# ---------------------------------------------------------------------------


def test_pipeline_runner_find_blender_manual_env_var_is_selected(tmp_path, monkeypatch):
    app_root = tmp_path
    manual_exe = tmp_path / "manual_blender" / "blender.exe"
    manual_exe.parent.mkdir(parents=True)
    manual_exe.write_text("stub")
    monkeypatch.setenv(blender_setup.ENV_BLENDER_EXE, str(manual_exe))

    result = pr.find_blender(str(app_root))
    assert result == str(manual_exe)


# ---------------------------------------------------------------------------
# ③ 設定ファイル(settings_blenderexe.txt)による手動指定が効く
# ---------------------------------------------------------------------------


def test_pipeline_runner_find_blender_manual_settings_file_is_selected(tmp_path):
    app_root = tmp_path
    manual_exe = tmp_path / "manual_blender2" / "blender.exe"
    manual_exe.parent.mkdir(parents=True)
    manual_exe.write_text("stub")
    settings_file = tmp_path / blender_setup.BLENDER_SETTINGS_BASENAME
    settings_file.write_text(str(manual_exe), encoding="utf-8")

    result = pr.find_blender(str(app_root))
    assert result == str(manual_exe)


# ---------------------------------------------------------------------------
# ④ 探索trailがログに出る
# ---------------------------------------------------------------------------


def test_pipeline_runner_find_blender_log_records_every_searched_location(tmp_path):
    app_root = tmp_path
    tools_dir = tmp_path / "assets" / "tools"
    hit_dir = tools_dir / "blender-4.3.2-windows-x64"
    miss_dir = tools_dir / "blender-3.6.0-windows-x64"
    hit_dir.mkdir(parents=True)
    miss_dir.mkdir(parents=True)
    (hit_dir / "blender.exe").write_text("stub")
    # miss_dir には blender.exe を置かない(not found候補として記録されるはず)

    lines: list[str] = []
    result = pr.find_blender(str(app_root), log=lines.append)

    assert result == str(hit_dir / "blender.exe")
    joined = "\n".join(lines)
    assert blender_setup.ENV_BLENDER_EXE in joined
    assert blender_setup.BLENDER_SETTINGS_BASENAME in joined
    assert str(hit_dir / "blender.exe") in joined
    assert str(miss_dir / "blender.exe") in joined


# ---------------------------------------------------------------------------
# 負の対照(a): 手動指定に存在しないパスを与えると黙って自動発見へ落ちず、
# 明示的に失敗する
# ---------------------------------------------------------------------------


def test_pipeline_runner_find_blender_manual_env_invalid_does_not_silently_fall_back(
    tmp_path, monkeypatch
):
    app_root = tmp_path
    # 自動発見なら見つかってしまう「正解」をわざと用意しておく。
    # それでも手動指定が誤っている限り使われないことまで確認する。
    tools_dir = tmp_path / "assets" / "tools" / "blender-4.3.2-windows-x64"
    tools_dir.mkdir(parents=True)
    (tools_dir / "blender.exe").write_text("stub")
    monkeypatch.setenv(
        blender_setup.ENV_BLENDER_EXE, str(tmp_path / "no_such_blender.exe")
    )

    with pytest.raises(blender_setup.BlenderManualPathError) as excinfo:
        pr.find_blender(str(app_root))
    msg = str(excinfo.value)
    assert blender_setup.ENV_BLENDER_EXE in msg
    assert "no_such_blender.exe" in msg


def test_pipeline_runner_find_blender_manual_settings_invalid_does_not_silently_fall_back(
    tmp_path,
):
    app_root = tmp_path
    tools_dir = tmp_path / "assets" / "tools" / "blender-4.3.2-windows-x64"
    tools_dir.mkdir(parents=True)
    (tools_dir / "blender.exe").write_text("stub")
    settings_file = tmp_path / blender_setup.BLENDER_SETTINGS_BASENAME
    settings_file.write_text(str(tmp_path / "no_such_blender2.exe"), encoding="utf-8")

    with pytest.raises(blender_setup.BlenderManualPathError) as excinfo:
        pr.find_blender(str(app_root))
    assert "no_such_blender2.exe" in str(excinfo.value)
