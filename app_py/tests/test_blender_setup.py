# test_blender_setup.py -- WP-A3受入条件: DecideBlenderSetupAction相当の3分岐を
# pytestで網羅する(旧 --check-blender-setup-decision / CheckBlenderSetupDecisionLogic
# L.5055-5083 相当のPython版試験。DESIGN.md §5.2 WP-A3行)。
#
# ケース表は app\DiveToPalworld.cs の CheckBlenderSetupDecisionLogic() が持つ
# 8通り(ensurePs1Exists x blenderExeExists x checkOnlyValid の全組み合わせ)を
# そのまま移植したもの(L.5059-5070)。実Blender・実プロセス起動は行わない
# (CLAUDE.md「受入試験はリリースゲートに任せる」: 変換を伴わない、ロジック単体+
# 負の対照のみで止める)。

from __future__ import annotations

import os
import subprocess
import sys

import pytest

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import blender_setup  # noqa: E402
from blender_setup import BlenderSetupAction, decide_blender_setup_action  # noqa: E402

# (ensure_ps1_exists, blender_exe_exists, check_only_valid, expected)
# DiveToPalworld.cs L.5059-5070 の8ケースと1:1(順序・値とも同一)。
CASES = [
    (False, False, False, BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT),
    (False, False, True, BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT),
    (False, True, False, BlenderSetupAction.READY_NO_ACTION),
    (False, True, True, BlenderSetupAction.READY_NO_ACTION),
    (True, False, False, BlenderSetupAction.NEED_FULL_SETUP),
    (True, False, True, BlenderSetupAction.NEED_FULL_SETUP),
    # dev#230の核心: exeはあるがマーカー無効 -> 即readyにせず必ずフル実行
    (True, True, False, BlenderSetupAction.NEED_FULL_SETUP),
    (True, True, True, BlenderSetupAction.READY_NO_ACTION),
]


@pytest.mark.parametrize(
    "ensure_ps1_exists,blender_exe_exists,check_only_valid,expected", CASES
)
def test_decide_blender_setup_action_case_table(
    ensure_ps1_exists, blender_exe_exists, check_only_valid, expected
):
    actual = decide_blender_setup_action(
        ensure_ps1_exists, blender_exe_exists, check_only_valid
    )
    assert actual == expected, (
        f"ensure_ps1_exists={ensure_ps1_exists} blender_exe_exists={blender_exe_exists} "
        f"check_only_valid={check_only_valid}: expected={expected} actual={actual}"
    )


def test_case_table_covers_all_eight_combinations():
    # 網羅性そのものの負の対照: 3引数の全2^3=8通りが表にあることを確認する
    # (表の一部を消しても他のケースだけでは気づけない、という空洞化を防ぐ)。
    seen = {(c[0], c[1], c[2]) for c in CASES}
    assert len(seen) == 8


def test_dev_not_found_ignores_check_only_valid():
    # ensurePs1が無ければcheckOnlyValidの値に関わらずexeの有無だけで決まる
    # (コメントL.5049-5051の主張そのものを明示的に検査する負の対照)。
    a = decide_blender_setup_action(False, False, False)
    b = decide_blender_setup_action(False, False, True)
    assert a == b == BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT


def test_stale_marker_forces_full_setup_not_ready():
    # dev#230の核心そのものへの負の対照: 「exeがあるだけ」でreadyにしてしまう
    # 退行が起きたら必ず落ちる(exe実在=True, checkOnlyValid=False は
    # NEED_FULL_SETUPでなければならない)。
    assert (
        decide_blender_setup_action(True, True, False)
        == BlenderSetupAction.NEED_FULL_SETUP
    )


# ---------------------------------------------------------------------------
# 補助関数の単体試験(実プロセス起動を伴わない範囲)
# ---------------------------------------------------------------------------

def test_find_blender_falls_back_to_bare_name_when_nothing_found(tmp_path, monkeypatch):
    # 候補(assets\tools配下、開発機決め打ちパス)がいずれも存在しない環境では
    # C#版同様 "blender.exe"(PATH解決に委ねる文字列)を返す。
    # _DEV_FALLBACK_BLENDER_DIRはこのリポジトリの指揮者機(ぱんのPC)には実在
    # しうる(dev#149の開発機フォールバックそのもの)ため、テストの再現性を
    # 環境に依存させないよう明示的に存在しないパスへ差し替える。
    monkeypatch.setattr(
        blender_setup, "_DEV_FALLBACK_BLENDER_DIR", str(tmp_path / "no_such_blender_dir")
    )
    empty_root = str(tmp_path)
    result = blender_setup.find_blender(empty_root)
    assert result == "blender.exe"


def test_find_blender_prefers_assets_tools_over_dev_fallback(tmp_path):
    tools_dir = tmp_path / "assets" / "tools" / "blender-4.3.2-windows-x64"
    tools_dir.mkdir(parents=True)
    exe = tools_dir / "blender.exe"
    exe.write_text("stub")
    result = blender_setup.find_blender(str(tmp_path))
    assert result == str(exe)


def test_asset_sub_dir_prefers_assets_subdir_when_present(tmp_path):
    dist_dir = tmp_path / "assets" / "tools"
    dist_dir.mkdir(parents=True)
    assert blender_setup.asset_sub_dir(str(tmp_path), "tools") == str(dist_dir)


def test_asset_sub_dir_falls_back_to_direct_subdir(tmp_path):
    # assets\tools が存在しない開発ツリーでは直下\tools を返す(L.1752-1757)。
    expected = os.path.join(str(tmp_path), "tools")
    assert blender_setup.asset_sub_dir(str(tmp_path), "tools") == expected


def test_ensure_blender_ps1_path_joins_pipeline_cli(tmp_path):
    expected = os.path.join(str(tmp_path), "pipeline", "cli", "ensure_blender.ps1")
    assert blender_setup.ensure_blender_ps1_path(str(tmp_path)) == expected


def test_run_ensure_blender_check_only_returns_false_when_script_missing(tmp_path):
    # ensure_ps1自体が存在しない(≒ファイル起動が失敗する)場合でも例外を投げず
    # False(安全側のフルセットアップへのフォールバック)を返すこと。
    missing_ps1 = str(tmp_path / "no_such_ensure_blender.ps1")
    result = blender_setup.run_ensure_blender_check_only(
        missing_ps1, str(tmp_path), timeout_sec=5.0
    )
    assert result is False


def test_run_ensure_blender_setup_process_relays_progress_and_extracts_fail_message(
    monkeypatch, tmp_path
):
    # 実ensure_blender.ps1もpwshも使わず、subprocess.Popenをダミープロセスへ
    # 差し替えて「##PROGRESS##中継」と「[D2P_BLENDER_SETUP_FAIL]以降の抽出」の
    # 2点だけを検査する(実Blenderダウンロードは受入に含めない、指示書どおり)。
    class _FakeProc:
        def __init__(self, lines, returncode):
            self.stdout = iter(lines)
            self.returncode = returncode

        def wait(self):
            return self.returncode

    fake_lines = [
        "##PROGRESS## 10 Downloading\n",
        "##PROGRESS## 55 Patching\n",
        "[D2P_BLENDER_SETUP_FAIL] something went wrong\nsee log for details\n",
    ]

    def _fake_popen(*args, **kwargs):
        return _FakeProc(fake_lines, returncode=1)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    progress_calls = []
    ok, fail_message = blender_setup.run_ensure_blender_setup_process(
        "dummy_ensure_blender.ps1",
        str(tmp_path),
        on_progress=lambda pct, phase: progress_calls.append((pct, phase)),
    )

    assert ok is False
    assert progress_calls == [(10, "Downloading"), (55, "Patching")]
    assert fail_message is not None
    assert fail_message.startswith("[D2P_BLENDER_SETUP_FAIL]")
    assert "something went wrong" in fail_message


def test_run_ensure_blender_setup_process_success_has_no_fail_message(monkeypatch, tmp_path):
    class _FakeProc:
        def __init__(self, lines, returncode):
            self.stdout = iter(lines)
            self.returncode = returncode

        def wait(self):
            return self.returncode

    def _fake_popen(*args, **kwargs):
        return _FakeProc(["##PROGRESS## 100 Done\n"], returncode=0)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    ok, fail_message = blender_setup.run_ensure_blender_setup_process(
        "dummy_ensure_blender.ps1", str(tmp_path)
    )
    assert ok is True
    assert fail_message is None


def test_do_ensure_blender_ready_ready_no_action_when_no_ensure_script(monkeypatch, tmp_path):
    # ensure_ps1が無く、find_blenderがexeを見つけられる場合(モック)は
    # READY_NO_ACTIONで即成功。ensure_blender.ps1もpwshも一切起動しない。
    fake_blender = tmp_path / "blender.exe"
    fake_blender.write_text("stub")
    monkeypatch.setattr(
        blender_setup, "find_blender", lambda app_root, log=None: str(fake_blender)
    )

    ok, fail_message, action = blender_setup.do_ensure_blender_ready(str(tmp_path))
    assert ok is True
    assert fail_message is None
    assert action == BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT or action == BlenderSetupAction.READY_NO_ACTION
    # ensure_ps1(pipeline\cli\ensure_blender.ps1)は本物がリポジトリに存在するため
    # tmp_pathを渡した場合はensure_ps1_exists=Falseとなり、exeが実在するので
    # DecideBlenderSetupAction(False, True, *)=READY_NO_ACTIONになるはず
    assert action == BlenderSetupAction.READY_NO_ACTION


def test_do_ensure_blender_ready_dev_not_found_when_nothing_exists(tmp_path, monkeypatch):
    # 同様に開発機決め打ちパスの実在に依存しないよう差し替える(上記コメント参照)。
    monkeypatch.setattr(
        blender_setup, "_DEV_FALLBACK_BLENDER_DIR", str(tmp_path / "no_such_blender_dir")
    )
    ok, fail_message, action = blender_setup.do_ensure_blender_ready(str(tmp_path))
    assert ok is False
    assert action == BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT
    assert fail_message is not None


# ---------------------------------------------------------------------------
# dev#23b: find_blender() 手動指定(環境変数/設定ファイル)+探索ログ
# (dev#23監査PR#754の申し送り。CLAUDE.md「外部依存パスの原則」の②③是正)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_blender_env(monkeypatch):
    # このモジュールの全テストで、開発機の実環境変数に左右されないようにする
    # (dev#23bで新設したD2P_BLENDER_EXEが万一実行環境に設定されていても、
    # 各テストは明示的にmonkeypatch.setenvしたときだけ有効にする)。
    # dev#1242: 同様にD2P_PWSH_EXEも各テストで明示指定したときだけ有効にする。
    monkeypatch.delenv(blender_setup.ENV_BLENDER_EXE, raising=False)
    monkeypatch.delenv(blender_setup.ENV_PWSH_EXE, raising=False)


def _no_auto_discovery_env(tmp_path, monkeypatch):
    """自動発見が何もヒットしない状態を作る共通ヘルパー(環境変数干渉を排除済み)。"""
    monkeypatch.setattr(
        blender_setup, "_DEV_FALLBACK_BLENDER_DIR", str(tmp_path / "no_such_blender_dir")
    )
    return str(tmp_path)


# --- 正の対照 ---------------------------------------------------------------


def test_find_blender_manual_env_var_is_selected(tmp_path, monkeypatch):
    app_root = _no_auto_discovery_env(tmp_path, monkeypatch)
    manual_exe = tmp_path / "manual_blender" / "blender.exe"
    manual_exe.parent.mkdir(parents=True)
    manual_exe.write_text("stub")
    monkeypatch.setenv(blender_setup.ENV_BLENDER_EXE, str(manual_exe))

    result = blender_setup.find_blender(app_root)
    assert result == str(manual_exe)


def test_find_blender_manual_settings_file_is_selected_when_env_unset(tmp_path, monkeypatch):
    app_root = _no_auto_discovery_env(tmp_path, monkeypatch)
    manual_exe = tmp_path / "manual_blender2" / "blender.exe"
    manual_exe.parent.mkdir(parents=True)
    manual_exe.write_text("stub")
    settings_file = tmp_path / blender_setup.BLENDER_SETTINGS_BASENAME
    settings_file.write_text(str(manual_exe), encoding="utf-8")

    result = blender_setup.find_blender(app_root)
    assert result == str(manual_exe)


def test_find_blender_env_var_takes_priority_over_settings_file(tmp_path, monkeypatch):
    app_root = _no_auto_discovery_env(tmp_path, monkeypatch)
    env_exe = tmp_path / "from_env" / "blender.exe"
    env_exe.parent.mkdir(parents=True)
    env_exe.write_text("stub")
    settings_exe = tmp_path / "from_settings" / "blender.exe"
    settings_exe.parent.mkdir(parents=True)
    settings_exe.write_text("stub")
    settings_file = tmp_path / blender_setup.BLENDER_SETTINGS_BASENAME
    settings_file.write_text(str(settings_exe), encoding="utf-8")
    monkeypatch.setenv(blender_setup.ENV_BLENDER_EXE, str(env_exe))

    result = blender_setup.find_blender(app_root)
    assert result == str(env_exe)


def test_find_blender_manual_dir_form_is_accepted(tmp_path, monkeypatch):
    # dep_resolver.pyのUnityと同じく、exeへの直接パスだけでなく
    # 「blender.exeを含むフォルダ」の指定も受け付ける。
    app_root = _no_auto_discovery_env(tmp_path, monkeypatch)
    manual_dir = tmp_path / "manual_blender_dir"
    manual_dir.mkdir()
    (manual_dir / "blender.exe").write_text("stub")
    monkeypatch.setenv(blender_setup.ENV_BLENDER_EXE, str(manual_dir))

    result = blender_setup.find_blender(app_root)
    assert result == str(manual_dir / "blender.exe")


def test_find_blender_no_manual_specification_falls_back_to_auto_discovery(tmp_path, monkeypatch):
    # 手動指定が一切無い場合は従来どおり自動発見のみが働く
    # (既存挙動を壊していないことの証明。負の対照 #2)。
    app_root = str(tmp_path)
    tools_dir = tmp_path / "assets" / "tools" / "blender-4.3.2-windows-x64"
    tools_dir.mkdir(parents=True)
    exe = tools_dir / "blender.exe"
    exe.write_text("stub")

    result = blender_setup.find_blender(app_root)
    assert result == str(exe)


# --- 負の対照(必須2本) -----------------------------------------------------


def test_find_blender_manual_env_var_invalid_does_not_fall_back_to_auto_discovery(
    tmp_path, monkeypatch
):
    # 負の対照#1: 環境変数が実在しないパスを指す場合、黙って自動発見に落ちず、
    # BlenderManualPathErrorで失敗する。自動発見側に「正解」を用意しておいても
    # (=もし黙ってフォールバックしていたら見つかってしまう状況を作っても)
    # 使われないことまで確認する(「指定を無視するのが最悪」の直接検査)。
    app_root = str(tmp_path)
    tools_dir = tmp_path / "assets" / "tools" / "blender-4.3.2-windows-x64"
    tools_dir.mkdir(parents=True)
    (tools_dir / "blender.exe").write_text("stub")  # 自動発見なら見つかる正解
    monkeypatch.setenv(
        blender_setup.ENV_BLENDER_EXE, str(tmp_path / "no_such_blender.exe")
    )

    with pytest.raises(blender_setup.BlenderManualPathError) as excinfo:
        blender_setup.find_blender(app_root)
    msg = str(excinfo.value)
    assert blender_setup.ENV_BLENDER_EXE in msg
    assert "no_such_blender.exe" in msg
    # 手動指定の直し方(ガイダンス)がメッセージに含まれること
    assert "settings_blenderexe.txt" in msg


def test_find_blender_manual_settings_file_invalid_does_not_fall_back_to_auto_discovery(
    tmp_path, monkeypatch
):
    # 負の対照#1の設定ファイル版。
    app_root = str(tmp_path)
    tools_dir = tmp_path / "assets" / "tools" / "blender-4.3.2-windows-x64"
    tools_dir.mkdir(parents=True)
    (tools_dir / "blender.exe").write_text("stub")  # 自動発見なら見つかる正解
    settings_file = tmp_path / blender_setup.BLENDER_SETTINGS_BASENAME
    settings_file.write_text(str(tmp_path / "no_such_blender2.exe"), encoding="utf-8")

    with pytest.raises(blender_setup.BlenderManualPathError) as excinfo:
        blender_setup.find_blender(app_root)
    msg = str(excinfo.value)
    assert "no_such_blender2.exe" in msg


def test_do_ensure_blender_ready_handles_invalid_manual_path_without_crashing(
    tmp_path, monkeypatch
):
    # 負の対照: do_ensure_blender_ready()がBlenderManualPathErrorを外へ
    # 伝播させず(=ワーカースレッドをクラッシュさせず)、通常の失敗経路
    # (ok=False, fail_message, MANUAL_PATH_INVALID)を返すこと。
    monkeypatch.setenv(
        blender_setup.ENV_BLENDER_EXE, str(tmp_path / "no_such_blender3.exe")
    )
    ok, fail_message, action = blender_setup.do_ensure_blender_ready(str(tmp_path))
    assert ok is False
    assert action == BlenderSetupAction.MANUAL_PATH_INVALID
    assert fail_message is not None
    assert blender_setup.ENV_BLENDER_EXE in fail_message


# --- 探索ログ ----------------------------------------------------------------


def test_find_blender_log_records_every_searched_location(tmp_path, monkeypatch):
    # 探索ログに「探した場所が全部」現れることを検査する。
    app_root = _no_auto_discovery_env(tmp_path, monkeypatch)
    tools_dir = tmp_path / "assets" / "tools"
    hit_dir = tools_dir / "blender-4.3.2-windows-x64"
    miss_dir = tools_dir / "blender-3.6.0-windows-x64"
    hit_dir.mkdir(parents=True)
    miss_dir.mkdir(parents=True)
    (hit_dir / "blender.exe").write_text("stub")
    # miss_dir には blender.exe を置かない(not found候補として記録されるはず)

    lines: list[str] = []
    result = blender_setup.find_blender(app_root, log=lines.append)

    assert result == str(hit_dir / "blender.exe")
    joined = "\n".join(lines)
    # 環境変数・設定ファイルの不在も記録される
    assert blender_setup.ENV_BLENDER_EXE in joined
    assert blender_setup.BLENDER_SETTINGS_BASENAME in joined
    # 自動発見側: ヒットした候補・見つからなかった候補の両方が記録される
    assert str(hit_dir / "blender.exe") in joined
    assert str(miss_dir / "blender.exe") in joined


def test_find_blender_log_records_manual_env_failure_before_raising(tmp_path, monkeypatch):
    app_root = str(tmp_path)
    monkeypatch.setenv(
        blender_setup.ENV_BLENDER_EXE, str(tmp_path / "no_such_blender4.exe")
    )
    lines: list[str] = []
    with pytest.raises(blender_setup.BlenderManualPathError):
        blender_setup.find_blender(app_root, log=lines.append)
    joined = "\n".join(lines)
    assert "NOT FOUND" in joined
    assert str(tmp_path / "no_such_blender4.exe") in joined


# ---------------------------------------------------------------------------
# dev#1242: 実ユーザー報告(WinError 2, issue本文)
# 「ensure_blender.ps1の起動に失敗しました: [WinError 2] 系统找不到指定的文件。」
# ①_find_pwsh()に欠けていた②手動指定・③探索ログの是正(find_blender/dev#23b
# と同型)、②起動失敗メッセージの[D2P_BLENDER_SETUP_FAIL]構造化(言語混在解消)。
# ---------------------------------------------------------------------------


def _no_auto_discovery_pwsh_env(tmp_path, monkeypatch):
    """_find_pwsh()の自動発見が何もヒットしない状態を作る(このリポジトリの
    開発機/CI機に実在する本物のPowerShellパスに依存させないための隔離)。"""
    monkeypatch.setenv("PATH", str(tmp_path / "no_such_path_dir"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "no_such_program_files"))
    monkeypatch.setenv("SystemRoot", str(tmp_path / "no_such_system_root"))
    return str(tmp_path)


# --- WinError2相当: 起動失敗メッセージの構造化(赤→緑の中核) -----------------


def test_run_ensure_blender_setup_process_launch_failure_uses_structured_marker(
    monkeypatch, tmp_path
):
    # dev#1242の実ユーザーログを模す: subprocess.PopenがWinError2(実行ファイル
    # 不在)相当のOSErrorを送出するケース。旧実装はハードコードされた日本語文言
    # ("ensure_blender.ps1の起動に失敗しました: ...")にOS生例外文字列(ユーザー
    # OS言語)をそのまま連結していた(issueで指摘された言語混在の直接原因)。
    # 新実装は既存の[D2P_BLENDER_SETUP_FAIL]構造(main_window.pyの行単位翻訳
    # 機構、dev#939)に乗るヘッダ行+"Reason: {ex}"へ変える。
    winerror2 = OSError(2, "系统找不到指定的文件")  # ユーザー実機ログの再現

    def _fake_popen(*args, **kwargs):
        raise winerror2

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    ok, fail_message = blender_setup.run_ensure_blender_setup_process(
        "dummy_ensure_blender.ps1", str(tmp_path)
    )

    assert ok is False
    assert fail_message is not None
    # 新ヘッダは[D2P_BLENDER_SETUP_FAIL]接頭辞を持ち、main_window.pyの既存
    # 翻訳機構にそのまま乗る(旧来のハードコード日本語文言は消えていること)。
    assert fail_message.startswith(blender_setup.FAIL_MARKER)
    assert "ensure_blender.ps1の起動に失敗しました" not in fail_message
    # OS生例外文字列は"Reason: "行として分離される(消えてはいない=診断情報は保持)。
    assert "Reason: " in fail_message
    assert "系统找不到指定的文件" in fail_message


def test_run_ensure_blender_setup_process_pwsh_manual_path_invalid_returns_guidance(
    monkeypatch, tmp_path
):
    # 負の対照: PowerShell実行ファイルの手動指定(環境変数)が無効な場合、
    # subprocess.Popenへ一切到達せず(=何かのexeを勝手に起動しない)、
    # 手動指定の直し方を含む案内文がfail_messageとして返る(即死・無言死しない)。
    def _fake_popen(*args, **kwargs):
        raise AssertionError("Popen must not be called when manual pwsh path is invalid")

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    monkeypatch.setenv(
        blender_setup.ENV_PWSH_EXE, str(tmp_path / "no_such_pwsh.exe")
    )

    ok, fail_message = blender_setup.run_ensure_blender_setup_process(
        "dummy_ensure_blender.ps1", str(tmp_path)
    )

    assert ok is False
    assert fail_message is not None
    assert blender_setup.ENV_PWSH_EXE in fail_message
    assert blender_setup.PWSH_SETTINGS_BASENAME in fail_message


# --- _find_pwsh(): 三点セット(①自動発見②手動指定③探索ログ) ------------------


def test_find_pwsh_manual_env_var_is_selected(tmp_path, monkeypatch):
    app_root = _no_auto_discovery_pwsh_env(tmp_path, monkeypatch)
    manual_exe = tmp_path / "manual_pwsh" / "pwsh.exe"
    manual_exe.parent.mkdir(parents=True)
    manual_exe.write_text("stub")
    monkeypatch.setenv(blender_setup.ENV_PWSH_EXE, str(manual_exe))

    result = blender_setup._find_pwsh(app_root)
    assert result == str(manual_exe)


def test_find_pwsh_manual_settings_file_is_selected_when_env_unset(tmp_path, monkeypatch):
    app_root = _no_auto_discovery_pwsh_env(tmp_path, monkeypatch)
    manual_exe = tmp_path / "manual_pwsh2" / "powershell.exe"
    manual_exe.parent.mkdir(parents=True)
    manual_exe.write_text("stub")
    settings_file = tmp_path / blender_setup.PWSH_SETTINGS_BASENAME
    settings_file.write_text(str(manual_exe), encoding="utf-8")

    result = blender_setup._find_pwsh(app_root)
    assert result == str(manual_exe)


def test_find_pwsh_env_var_takes_priority_over_settings_file(tmp_path, monkeypatch):
    app_root = _no_auto_discovery_pwsh_env(tmp_path, monkeypatch)
    env_exe = tmp_path / "from_env" / "pwsh.exe"
    env_exe.parent.mkdir(parents=True)
    env_exe.write_text("stub")
    settings_exe = tmp_path / "from_settings" / "pwsh.exe"
    settings_exe.parent.mkdir(parents=True)
    settings_exe.write_text("stub")
    settings_file = tmp_path / blender_setup.PWSH_SETTINGS_BASENAME
    settings_file.write_text(str(settings_exe), encoding="utf-8")
    monkeypatch.setenv(blender_setup.ENV_PWSH_EXE, str(env_exe))

    result = blender_setup._find_pwsh(app_root)
    assert result == str(env_exe)


def test_find_pwsh_manual_env_var_invalid_raises_and_does_not_fall_back(tmp_path, monkeypatch):
    # 負の対照#1: 環境変数が実在しないパスを指す場合、黙って自動発見に落ちない
    # (自動発見側にはこのテスト環境の本物のPowerShellが実在しうるので、もし
    # 黙ってフォールバックしていたら見つかってしまう状況で確認する)。
    app_root = str(tmp_path)
    monkeypatch.setenv(
        blender_setup.ENV_PWSH_EXE, str(tmp_path / "no_such_pwsh2.exe")
    )

    with pytest.raises(blender_setup.PwshManualPathError) as excinfo:
        blender_setup._find_pwsh(app_root)
    msg = str(excinfo.value)
    assert blender_setup.ENV_PWSH_EXE in msg
    assert "no_such_pwsh2.exe" in msg
    assert blender_setup.PWSH_SETTINGS_BASENAME in msg


def test_find_pwsh_manual_settings_file_invalid_raises_and_does_not_fall_back(
    tmp_path, monkeypatch
):
    app_root = str(tmp_path)
    settings_file = tmp_path / blender_setup.PWSH_SETTINGS_BASENAME
    settings_file.write_text(str(tmp_path / "no_such_pwsh3.exe"), encoding="utf-8")

    with pytest.raises(blender_setup.PwshManualPathError) as excinfo:
        blender_setup._find_pwsh(app_root)
    msg = str(excinfo.value)
    assert "no_such_pwsh3.exe" in msg


def test_find_pwsh_no_manual_specification_falls_back_to_auto_discovery(tmp_path, monkeypatch):
    # 手動指定が一切無い場合は従来どおり自動発見のみが働く(既存挙動を壊して
    # いないことの証明)。PATH上にpwsh.exeを置いた最小ケース。
    app_root = _no_auto_discovery_pwsh_env(tmp_path, monkeypatch)
    path_dir = tmp_path / "on_path"
    path_dir.mkdir()
    pwsh_exe = path_dir / "pwsh.exe"
    pwsh_exe.write_text("stub")
    monkeypatch.setenv("PATH", str(path_dir))

    result = blender_setup._find_pwsh(app_root)
    assert result == str(pwsh_exe)


def test_find_pwsh_log_records_every_searched_location(tmp_path, monkeypatch):
    app_root = _no_auto_discovery_pwsh_env(tmp_path, monkeypatch)
    lines: list[str] = []
    result = blender_setup._find_pwsh(app_root, log=lines.append)

    # 何もヒットしない環境なので最終的にbare名へフォールバックする
    # (従来挙動どのおりの安全側デグレード)。
    assert result == "powershell.exe"
    joined = "\n".join(lines)
    assert blender_setup.ENV_PWSH_EXE in joined
    assert blender_setup.PWSH_SETTINGS_BASENAME in joined
    assert "PATH pwsh.exe" in joined
    assert "PowerShell" in joined and "7" in joined  # ProgramFiles候補
    assert "WindowsPowerShell" in joined  # System32絶対パス候補
    assert "falling back to bare" in joined


def test_find_pwsh_log_records_manual_env_failure_before_raising(tmp_path, monkeypatch):
    app_root = str(tmp_path)
    monkeypatch.setenv(
        blender_setup.ENV_PWSH_EXE, str(tmp_path / "no_such_pwsh4.exe")
    )
    lines: list[str] = []
    with pytest.raises(blender_setup.PwshManualPathError):
        blender_setup._find_pwsh(app_root, log=lines.append)
    joined = "\n".join(lines)
    assert "NOT FOUND" in joined
    assert str(tmp_path / "no_such_pwsh4.exe") in joined


# --- 根治そのものの検査: 壊れたPATHでもWindows標準の絶対パスで見つかる -------


def test_find_pwsh_finds_system_powershell_by_absolute_path_even_with_broken_path_env(
    monkeypatch, tmp_path
):
    # dev#1242の核心そのものへの検査: 実ユーザー環境のようにPATHが壊れて
    # pwsh.exe/powershell.exeを一切解決できない状況でも、Windows標準の絶対パス
    # (<SystemRoot>\System32\WindowsPowerShell\v1.0\powershell.exe)を直接
    # 確認するため見つかる。このテストは実行環境の本物のSystemRootに依存する
    # (Windows上のCI/開発機であれば常に実在する、C#版FindPwsh()の代替に
    # なっていたbare名頼みの脆さそのものを検査する)。
    monkeypatch.setenv("PATH", str(tmp_path / "no_such_path_dir"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "no_such_program_files"))
    # SystemRootは意図的に変更しない(本物の環境変数のまま)。

    result = blender_setup._find_pwsh(str(tmp_path))
    assert result != "powershell.exe", (
        "PATHが壊れていてもbare名フォールバックへ落ちてはならない"
        "(絶対パス候補が実在するはず)"
    )
    assert os.path.isfile(result)
    assert "WindowsPowerShell" in result


# --- do_ensure_blender_ready(): pwsh手動指定エラーが無言死せず案内文で届く ----


def test_do_ensure_blender_ready_pwsh_manual_path_invalid_surfaces_guidance_not_silent(
    tmp_path, monkeypatch
):
    # 負の対照(受入条件の核心): 本当にPowerShellが起動できない環境
    # (手動指定が誤設定されている状況を模す)では、do_ensure_blender_ready()が
    # 無言で落ちたりハングしたりせず、手動指定UIへの導線(環境変数名/設定
    # ファイル名を含むガイダンス)と探索ログの両方が出る。
    ensure_ps1 = tmp_path / "pipeline" / "cli" / "ensure_blender.ps1"
    ensure_ps1.parent.mkdir(parents=True)
    ensure_ps1.write_text("# dummy")
    fake_blender = tmp_path / "blender.exe"
    fake_blender.write_text("stub")
    monkeypatch.setattr(blender_setup, "find_blender", lambda app_root, log=None: str(fake_blender))
    monkeypatch.setenv(
        blender_setup.ENV_PWSH_EXE, str(tmp_path / "no_such_pwsh5.exe")
    )

    log_lines: list[str] = []
    ok, fail_message, action = blender_setup.do_ensure_blender_ready(
        str(tmp_path), log=log_lines.append
    )

    assert ok is False
    assert fail_message is not None
    # 手動指定UIへの導線(どこを直せばよいか)が案内文に含まれる
    assert blender_setup.ENV_PWSH_EXE in fail_message
    assert blender_setup.PWSH_SETTINGS_BASENAME in fail_message
    # 探索ログにも同じ失敗が記録されている(即死・無言死しないことの直接証拠)
    joined = "\n".join(log_lines)
    assert "NOT FOUND" in joined
    assert str(tmp_path / "no_such_pwsh5.exe") in joined
