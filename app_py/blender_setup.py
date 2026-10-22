# blender_setup.py -- Blender準備契約(DESIGN.md §2.2)のPython移植。
#
# dev#532 方針A WP-A3: DESIGN.md(C:\P\Work\DiveToPalworld\work\wp532A\DESIGN.md)
# §2.2「Blender準備契約」の移植先。任務の契約範囲は
#   DoEnsureBlenderReady・ensure_blender.ps1呼び出し・進捗中継・失敗時リトライ
# の4点(指示書より)。
#
# 移植元: app\DiveToPalworld.cs
#   - AssetSubDir()                    L.1752-1757
#   - FindBlender()                    L.1836-1860 (MAX_PATH短縮ジャンクション
#                                        TryGetShortBlenderPathは対象外、後述)
#   - BlenderSetupAction enum          L.2012-2017
#   - DecideBlenderSetupAction()       L.2019-2030 (純関数。CheckBlenderSetupDecisionLogic
#                                        L.5055-5083 のケース表がそのまま受入試験)
#   - DoEnsureBlenderReady()           L.2037-2098
#   - RunEnsureBlenderSetupProcess()   L.2107-2169
#   - RunEnsureBlenderCheckOnly()      L.2177-2205
#   - FindPwsh()                       L.2721-2739
#
# 合理的解釈(スコープの線引き、完了報告にも記載):
#   - FindPwsh()は本来pipeline_runner.py(WP-A2、DESIGN.md §4.1)の担当だが、
#     A2は本WP時点で未着手・未マージのため、blender_setup.py内に最小限の
#     private実装(_find_pwsh)を置く。WP-A2完了後の重複解消は別WPの課題とする。
#     (dev#1242申し送りWPで解消済み: find_pwsh()として公開関数化し、
#     pipeline_runner.find_pwsh()はこの関数への委譲に置き換えた。旧名
#     _find_pwshは同一関数へのエイリアスとして残置。)
#   - TryGetShortBlenderPath(dev#149、MAX_PATH超過対策のNTFSジャンクション)は
#     「Blender準備契約」の中核4点に含まれない付随最適化のため、本WPでは移植
#     しない(find_blenderは常に実体パスを返す。動作は変わらないが深い
#     インストール先でのdev#149相当の問題は本WPでは未対策のまま)。
#   - WarmSharedCacheOnStartup/WarmBlenderProcessOnStartup(DoEnsureBlenderReady
#     成功後に続けて呼ばれる別機能。convert_noue.py起動・pak解決(A4領域)に
#     依存し、契約4点にも含まれない)は本WPのスコープ外。

from __future__ import annotations

import enum
import os
import re
import subprocess
from typing import Callable, List, Optional, Tuple

# AppendLog()のProgressMark定数(L.2829-2836)と同じ正規表現。
PROGRESS_MARK = re.compile(r"##PROGRESS##\s*(\d+)\s*(.*)")

# RunEnsureBlenderSetupProcess()が失敗時の案内文を切り出す境界マーカー。
FAIL_MARKER = "[D2P_BLENDER_SETUP_FAIL]"

# dev#1242: PowerShell実行ファイル自体の起動に失敗した場合(WinError2等)の
# ヘッダ行。ensure_blender.ps1のShow-D2PFailureGuidanceが出す既存の
# "[D2P_BLENDER_SETUP_FAIL] Blender setup failed." と同じFAIL_MARKER接頭辞を
# 持たせることで、main_window.pyの既存翻訳機構(_BLENDER_SETUP_FAIL_LINE_MAP/
# translate_blender_setup_fail_message、dev#939)にそのまま乗る。続く
# "Reason: {0}" 行は既存テンプレート(_BLENDER_SETUP_FAIL_LINE_TEMPLATES)が
# 既に5言語対応済みのため、OS由来の生例外文字列(ユーザーOS言語)は
# ラベル部分だけがUI言語へ翻訳された「詳細」として分離表示される
# (issue dev#1242コメント: 「表示はUI言語で統一し、OS由来の生文字列は
# エラーコード/詳細欄として分離して添える」の実装)。
LAUNCH_FAIL_HEADER = f"{FAIL_MARKER} Failed to launch ensure_blender.ps1."

# dev#14(2026-08-02): 旧FindBlender() L.1840の開発機決め打ちフォールバック。
# WP-A3移植時点では「既存債務としてそのまま移植」していたが、
# tests\test_blender_setup.py がこの値を明示的にmonkeypatchしないと
# テストの再現性が指揮者機(このパスが実在するPC)に依存してしまうと
# 自己申告している(=このパスは配布物には存在せず、開発機のみに影響する
# フォールバック)。CLAUDE.md「外部依存パスの原則」に反するため、
# find_blender()の探索候補からは外した。シンボル自体は既存テストの
# monkeypatch対象として後方互換のため残す(値そのものは以後どこからも
# 参照されない)。
_DEV_FALLBACK_BLENDER_DIR = r"C:\P\Work\PalMod\tools\blender-4.3.2-windows-x64"

# dev#23b(dev#23監査PR#754の申し送りに基づく修理): find_blender()に欠けていた
# ②手動指定・③探索ログの三点セット是正。命名はdep_resolver.pyのENV_UNITY_EDITORと
# 同じ"D2P_"接頭辞規則(コードベース内の既存env varは全てこの接頭辞。ブランド名
# "Uchinoko"は表示用の改称であり内部識別子の接頭辞ではないため踏襲する)。
ENV_BLENDER_EXE = "D2P_BLENDER_EXE"
# settings.py(DESIGN.md §2.8で書き込み許可が明示された4ファイル専用)には
# 寄せず、本ファイル内で自己完結させる(dev#23bの書き込み許可がblender_setup.py
# のみのため)。ファイル名の流儀(appRoot直下フラットtxt)はsettings_paksdir.txt等
# と揃えた。
BLENDER_SETTINGS_BASENAME = "settings_blenderexe.txt"

# dev#1242: ensure_blender.ps1起動そのものがWinError2で即死する不具合(issue本文の
# 実ユーザーログ「ensure_blender.ps1の起動に失敗しました: [WinError 2] 系统找不到
# 指定的文件。」)の是正。_find_pwsh()(旧FindPwsh() L.2721-2739の移植)は
# PATH検索とProgramFiles固定パスしか見ておらず、①手動指定フォールバック・
# ③探索ログの両方が欠けていた(find_blender()/dev#23bとの非対称)。ENV_BLENDER_EXE
# と同じ命名規則(D2P_接頭辞)・同じ二段構え(環境変数→設定ファイル)を踏襲する。
ENV_PWSH_EXE = "D2P_PWSH_EXE"
PWSH_SETTINGS_BASENAME = "settings_pwshexe.txt"

LogFn = Callable[[str], None]


def _noop_log(_line: str) -> None:
    """find_blender()のlog引数省略時の既定(pak_manager.pyの_noop_logパターン)。"""


class PwshManualPathError(RuntimeError):
    """dev#1242: 環境変数/設定ファイルで手動指定されたPowerShell実行ファイルの
    パスが実在しない場合に_find_pwsh()が送出する。BlenderManualPathError
    (dev#23b)と同型(指定を無視して自動発見へ黙って落ちない)。"""

    def __init__(self, source: str, value: str, app_root: str) -> None:
        self.source = source
        self.value = value
        settings_display = (
            os.path.join(app_root, PWSH_SETTINGS_BASENAME)
            if app_root
            else PWSH_SETTINGS_BASENAME
        )
        guidance = (
            "How to specify manually:\n"
            f"  - set environment variable {ENV_PWSH_EXE} to the full path of a "
            "PowerShell executable (pwsh.exe or powershell.exe), or a folder "
            "containing one\n"
            f"  - write the full path of a PowerShell executable (or a folder "
            f"containing one) as a single line in {settings_display}\n"
            "Removing the invalid override falls back to auto-discovery."
        )
        message = (
            f"[blender_setup] the PowerShell specified via {source} was not found: {value}\n"
            f"{guidance}"
        )
        super().__init__(message)


class BlenderManualPathError(RuntimeError):
    """dev#23b: 環境変数/設定ファイルで手動指定されたBlenderパスが実在しない場合に
    find_blender()が送出する。CLAUDE.md「外部依存パスの原則」――
    「手動指定された値が実在しないときは、指定されたが見つからないと明示して
    落ちる(黙って自動発見へ落ちない。指定を無視するのが最悪)」を実装したもの。

    dep_resolver.pyのUnity解決ロジック(resolve_unity_editor())は手動指定が
    無効でも自動発見へフォールバックする設計だが、本WPの指示書はBlenderについて
    明示的にこれと異なる動作(即失敗)を要求しているため、意図的に異なる設計を
    採っている(work\\night_20260802\\23b_progress.md参照)。"""

    def __init__(self, source: str, value: str, app_root: str) -> None:
        self.source = source
        self.value = value
        guidance = (
            "How to specify manually:\n"
            f"  - set environment variable {ENV_BLENDER_EXE} to the full path of "
            "blender.exe (or a folder containing it)\n"
            f"  - write the full path of blender.exe (or a folder containing it) "
            f"as a single line in {os.path.join(app_root, BLENDER_SETTINGS_BASENAME)}\n"
            "Removing the invalid override falls back to auto-discovery (under assets\\tools)."
        )
        message = (
            f"[blender_setup] the Blender specified via {source} was not found: {value}\n"
            f"{guidance}"
        )
        super().__init__(message)


def _resolve_manual_blender_path(raw: str) -> Optional[str]:
    """手動指定の値からblender.exeの実パスを求める。dep_resolver.pyの
    _resolve_manual_path()と同じ「blender.exeへの直接パス、またはそれを
    含むフォルダ」の両方を受け付ける方式を踏襲する。"""
    raw = (raw or "").strip().strip('"')
    if not raw:
        return None
    if os.path.isfile(raw) and raw.lower().endswith(".exe"):
        return raw
    cand = os.path.join(raw, "blender.exe")
    if os.path.isfile(cand):
        return cand
    return None


def _resolve_manual_pwsh_path(raw: str) -> Optional[str]:
    """手動指定の値からPowerShell実行ファイルの実パスを求める。
    _resolve_manual_blender_path()と同じ「直接パス、またはそれを含むフォルダ」の
    両方を受け付ける方式だが、拡張子固定のblender.exeと違い候補が2種類
    (pwsh.exe/powershell.exe)あるため両方を試す。"""
    raw = (raw or "").strip().strip('"')
    if not raw:
        return None
    if os.path.isfile(raw) and raw.lower().endswith(".exe"):
        return raw
    for name in ("pwsh.exe", "powershell.exe"):
        cand = os.path.join(raw, name)
        if os.path.isfile(cand):
            return cand
    return None


def _read_pwsh_settings_file(app_root: str) -> Optional[str]:
    """settings_pwshexe.txt を読む。_read_blender_settings_file()と同じ流儀。"""
    path = os.path.join(app_root, PWSH_SETTINGS_BASENAME)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = f.read().strip()
    except OSError:
        return None
    return raw or None


def _read_blender_settings_file(app_root: str) -> Optional[str]:
    """settings_blenderexe.txt を読む。settings.py の _read_text() と同じ流儀
    (UTF-8、1行目trim、無ければNone、読み込み失敗も握りつぶしてNone)だが、
    settings.py 自体(DESIGN.md §2.8の対象4ファイル専用)へは寄せず、
    本ファイル内で完結させる。"""
    path = os.path.join(app_root, BLENDER_SETTINGS_BASENAME)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = f.read().strip()
    except OSError:
        return None
    return raw or None


class BlenderSetupAction(enum.Enum):
    """DecideBlenderSetupAction()の戻り値(C# enum L.2012-2017の1:1移植)。"""

    READY_NO_ACTION = "ReadyNoAction"          # 既にBlenderが使える。何もしなくてよい
    NEED_FULL_SETUP = "NeedFullSetup"          # ensure_blender.ps1のフル実行が必要
    DEV_NOT_FOUND_NO_SCRIPT = "DevNotFoundNoScript"  # 開発チェックアウト等でスクリプトもexeも無い
    # dev#23b追加: C# 1:1移植の3値には無い、本WPで新設したケース。手動指定
    # (環境変数/設定ファイル)されたBlenderパスが実在しない場合(find_blender()が
    # BlenderManualPathErrorを送出した)。decide_blender_setup_action()自体は
    # 純関数のまま無改修で、この値はdo_ensure_blender_ready()側でのみ使う。
    MANUAL_PATH_INVALID = "ManualPathInvalid"


class BlenderSetupProcessHandle:
    """dev#640: run_ensure_blender_setup_process()が起動したBlenderセットアップ
    子プロセス(ensure_blender.ps1)への参照を保持し、GUI終了時に黙ってkillできる
    ようにする。C#版の blenderSetupProc フィールド(L.465)+
    KillBlenderSetupProcess()(L.1339-1353)の1:1移植。

    呼び出し元(main_window.py)がインスタンスを1つ生成して
    do_ensure_blender_ready()/run_ensure_blender_setup_process()へ
    process_handle= として渡すと、プロセス起動中だけ self.proc に
    subprocess.Popen が入る(完了/失敗後は必ずNoneへ戻る)。
    kill()はメインスレッド(tkinterのWM_DELETE_WINDOWハンドラ)から
    ワーカースレッド実行中のプロセスを安全に止めるために使う。"""

    def __init__(self) -> None:
        self.proc: Optional[subprocess.Popen] = None

    def kill(self) -> None:
        """KillBlenderSetupProcess() L.1339-1353の移植。プロセスツリーごと
        taskkillで黙って停止する(確認なし、例外は握りつぶす——ユーザーが
        明示的に始めた作業ではない裏方処理のため、C#コメントと同じ判断。
        次回起動時のマーカー検証で自己修復される設計、PR #637本文にも
        同じ理由付けの記載あり)。プロセスが無ければ何もしない。"""
        proc = self.proc
        if proc is None:
            return
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                capture_output=True,
                timeout=5,
            )
        except Exception:  # noqa: BLE001 -- C#版と同じく確認なし・例外握り潰し
            pass


def asset_sub_dir(app_root: str, name: str) -> str:
    """AssetSubDir() L.1752-1757相当。配布物では assets\\<name>、開発ツリーでは
    直下\\<name> に置かれる二重構成を吸収する。"""
    dist = os.path.join(app_root, "assets", name)
    if os.path.isdir(dist):
        return dist
    return os.path.join(app_root, name)


def find_blender(app_root: str, log: Optional[LogFn] = None) -> str:
    """FindBlender() L.1836-1860の移植(MAX_PATH短縮ジャンクションを除く、
    上記の合理的解釈を参照)+ dev#23b(監査PR#754申し送り)で②手動指定・
    ③探索ログを追加。

    優先順位(WP指示書どおり): 環境変数 D2P_BLENDER_EXE → 設定ファイル
    settings_blenderexe.txt → 自動発見(assets\\tools走査)。

    dev#14(2026-08-02、PR #749): 自動発見の最終手段だった開発機決め打ち
    フォールバック(_DEV_FALLBACK_BLENDER_DIR)は探索候補から除去済み。
    配布物には存在しえないパスであり、実在するのはその値が実際に指す
    1台の開発機だけだった(「配布物では絶対に踏まない経路が開発機でだけ
    動く」不具合そのもの)。自動発見が失敗した場合は素直に"blender.exe"
    (PATH解決に委ねる文字列)を返す。dev#23bが追加した手動指定(環境変数/
    設定ファイル)は、この決め打ちフォールバックが担っていた「配布物にも
    ない場合の逃げ道」を、ユーザーが明示的に設定する形で正しく代替する。

    手動指定(環境変数/設定ファイルのいずれか)が**設定されているのに**実在
    しない場合は BlenderManualPathError を送出し、自動発見へは進まない
    (CLAUDE.md「指定を無視するのが最悪」)。手動指定が一切無い場合は従来どおり
    自動発見のみが働き、候補が1つも実在しなければC#版と同じく"blender.exe"
    (PATH解決に委ねる文字列)を返す(この最終フォールバックの挙動は変更して
    いない)。

    log: 探索した場所を1行ずつ通知する任意コールバック(pak_manager.pyの
    LogFnパターンを踏襲)。省略時は何も出力しない(main_window.py等、既存
    呼び出し元は無改修で動く)。"""
    emit = log if log is not None else _noop_log

    # --- 手動指定1: 環境変数(最優先) ---
    env_val = (os.environ.get(ENV_BLENDER_EXE) or "").strip()
    if env_val:
        exe = _resolve_manual_blender_path(env_val)
        if exe:
            emit(f"[blender_setup] manual-env {ENV_BLENDER_EXE}={env_val} -> found, selected: {exe}")
            return exe
        emit(f"[blender_setup] manual-env {ENV_BLENDER_EXE}={env_val} -> NOT FOUND")
        raise BlenderManualPathError(f"environment variable {ENV_BLENDER_EXE}", env_val, app_root)
    emit(f"[blender_setup] manual-env {ENV_BLENDER_EXE} -> not set")

    # --- 手動指定2: 設定ファイル(環境変数が未設定/空のときのみ) ---
    settings_path = os.path.join(app_root, BLENDER_SETTINGS_BASENAME)
    settings_val = _read_blender_settings_file(app_root)
    if settings_val:
        exe = _resolve_manual_blender_path(settings_val)
        if exe:
            emit(f"[blender_setup] manual-settings {settings_path}={settings_val} -> found, selected: {exe}")
            return exe
        emit(f"[blender_setup] manual-settings {settings_path}={settings_val} -> NOT FOUND")
        raise BlenderManualPathError(f"settings file {settings_path}", settings_val, app_root)
    exists_but_empty = os.path.isfile(settings_path)
    emit(
        f"[blender_setup] manual-settings {settings_path} -> "
        + ("exists but empty" if exists_but_empty else "not present (optional)")
    )

    # --- 自動発見: assets\tools 走査(開発機決め打ちフォールバックはdev#14で除去済み) ---
    tools_dir = asset_sub_dir(app_root, "tools")
    candidates: List[str] = []
    if os.path.isdir(tools_dir):
        try:
            entries = sorted(os.listdir(tools_dir))
        except OSError as ex:
            emit(f"[blender_setup] auto {tools_dir} -> permission/IO error ({ex})")
            entries = []
        for entry in entries:
            if entry.startswith("blender-") and entry.endswith("-windows-x64"):
                candidates.append(os.path.join(tools_dir, entry))
    else:
        emit(f"[blender_setup] auto {tools_dir} -> directory not present")

    for c in candidates:
        exe = os.path.join(c, "blender.exe")
        if os.path.isfile(exe):
            emit(f"[blender_setup] auto candidate {exe} -> found, selected")
            return exe
        emit(f"[blender_setup] auto candidate {exe} -> not found")

    emit("[blender_setup] nothing found, falling back to bare 'blender.exe' (PATH resolution)")
    return "blender.exe"


def ensure_blender_ps1_path(app_root: str) -> str:
    """DoEnsureBlenderReady() L.2040相当のパス組み立てのみを切り出したもの。"""
    return os.path.join(app_root, "pipeline", "cli", "ensure_blender.ps1")


def find_pwsh(app_root: str = "", log: Optional[LogFn] = None) -> str:
    """FindPwsh() L.2721-2739の移植 + dev#1242で外部依存パスの原則
    (①自動発見→②手動指定フォールバック→③探索ログ)へ適合させたもの。
    find_blender()/dev#23bと同型の3点セット。

    dev#1242申し送りの共通化(本WP): 旧pipeline_runner.find_pwsh()は本関数と
    同型の重複実装(PATH+ProgramFilesのみ、System32絶対パス無し、手動指定・
    探索ログ無し)を独自に持っていた。pipeline_runner.py側は本関数への薄い
    委譲(delegation)に置き換え、実装はここに一本化した。呼び出し元が2つ
    (blender_setup.py自身のrun_ensure_blender_check_only/
    run_ensure_blender_setup_process、pipeline_runner.find_pwsh())になった
    ため、名前から先頭アンダースコアを外して公開関数にした。旧名 _find_pwsh
    は既存テスト/呼び出し元との後方互換のためモジュール末尾でエイリアスして
    いる(同一関数オブジェクト)。

    優先順位: 環境変数 D2P_PWSH_EXE → 設定ファイル settings_pwshexe.txt →
    PATH上のpwsh.exe(PowerShell 7)→ <ProgramFiles>\\PowerShell\\7\\pwsh.exe →
    <SystemRoot>\\System32\\WindowsPowerShell\\v1.0\\powershell.exe(Windows標準
    PowerShell 5.1への絶対パス。dev#1242新設、これがdev#1242の実際の根治)→
    最終手段としてbare "powershell.exe"(PATH解決に委ねる、従来と同じ)。

    dev#1242の実ユーザー報告(WinError 2)は、この関数が最終的にbare名
    "powershell.exe" を返し、CreateProcessのPATH検索(壊れた/欠落した環境変数
    PATHに依存)だけを頼りにしていたことが原因。System32\\WindowsPowerShell\\
    v1.0はWindows標準のインストール先であり、PATH経由ではなく絶対パスで直接
    確認すればPATHの状態に関わらず見つかる。

    手動指定(環境変数/設定ファイル)が設定されているのに実在しない場合は
    PwshManualPathErrorを送出し、自動発見へは進まない(find_blenderと同じ
    「指定を無視するのが最悪」判断)。手動指定が一切無い場合は従来どおり
    自動発見のみが働く。"""
    emit = log if log is not None else _noop_log

    # --- 手動指定1: 環境変数(最優先) ---
    env_val = (os.environ.get(ENV_PWSH_EXE) or "").strip()
    if env_val:
        exe = _resolve_manual_pwsh_path(env_val)
        if exe:
            emit(f"[blender_setup] manual-env {ENV_PWSH_EXE}={env_val} -> found, selected: {exe}")
            return exe
        emit(f"[blender_setup] manual-env {ENV_PWSH_EXE}={env_val} -> NOT FOUND")
        raise PwshManualPathError(f"environment variable {ENV_PWSH_EXE}", env_val, app_root)
    emit(f"[blender_setup] manual-env {ENV_PWSH_EXE} -> not set")

    # --- 手動指定2: 設定ファイル(環境変数が未設定/空のときのみ) ---
    settings_path = os.path.join(app_root, PWSH_SETTINGS_BASENAME) if app_root else PWSH_SETTINGS_BASENAME
    settings_val = _read_pwsh_settings_file(app_root) if app_root else None
    if settings_val:
        exe = _resolve_manual_pwsh_path(settings_val)
        if exe:
            emit(f"[blender_setup] manual-settings {settings_path}={settings_val} -> found, selected: {exe}")
            return exe
        emit(f"[blender_setup] manual-settings {settings_path}={settings_val} -> NOT FOUND")
        raise PwshManualPathError(f"settings file {settings_path}", settings_val, app_root)
    if app_root:
        exists_but_empty = os.path.isfile(settings_path)
        emit(
            f"[blender_setup] manual-settings {settings_path} -> "
            + ("exists but empty" if exists_but_empty else "not present (optional)")
        )

    # --- 自動発見1: PATH上のpwsh.exe(PowerShell 7) ---
    path_env = os.environ.get("PATH", "")
    for d in path_env.split(os.pathsep):
        try:
            cand = os.path.join(d.strip(), "pwsh.exe")
        except OSError:
            continue
        if os.path.isfile(cand):
            emit(f"[blender_setup] auto PATH pwsh.exe -> found, selected: {cand}")
            return cand
    emit("[blender_setup] auto PATH pwsh.exe -> not found in any PATH directory")

    # --- 自動発見2: <ProgramFiles>\PowerShell\7\pwsh.exe ---
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    pwsh7 = os.path.join(program_files, "PowerShell", "7", "pwsh.exe")
    if os.path.isfile(pwsh7):
        emit(f"[blender_setup] auto {pwsh7} -> found, selected")
        return pwsh7
    emit(f"[blender_setup] auto {pwsh7} -> not found")

    # --- 自動発見3(dev#1242新設): Windows標準PowerShell 5.1への絶対パス。
    # PATH解決に一切依存しないため、壊れた/欠落したPATH環境でも見つかる。 ---
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    winps = os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    if os.path.isfile(winps):
        emit(f"[blender_setup] auto {winps} -> found, selected")
        return winps
    emit(f"[blender_setup] auto {winps} -> not found")

    emit("[blender_setup] nothing found, falling back to bare 'powershell.exe' (PATH resolution)")
    return "powershell.exe"


# 後方互換エイリアス(旧名 _find_pwsh)。既存テスト(test_blender_setup.py)や
# 将来のmonkeypatch対象がこの名前を参照しても壊れないよう、同一関数オブジェクト
# を束ねておく(挙動は完全に同一、find_pwshの別名にすぎない)。
_find_pwsh = find_pwsh


def decide_blender_setup_action(
    ensure_ps1_exists: bool, blender_exe_exists: bool, check_only_valid: bool
) -> BlenderSetupAction:
    """DecideBlenderSetupAction() L.2019-2030の1:1移植。ファイルI/O・プロセス
    起動を一切含まない純関数(3つのboolだけで判定)。

    根拠(CheckBlenderSetupDecisionLogic L.5048-5054のコメントより):
      - ensurePs1が無い(開発チェックアウト等)場合、checkOnlyValidの値に関わらず
        exeの有無だけで決まる(マーカー検証はensurePs1側の責務なので、その
        スクリプト自体が無ければ検証しようがない)。
      - ensurePs1がある場合、exeがあってcheckOnlyValid(Test-D2PMarkerValid相当)が
        Trueの時だけREADY_NO_ACTION。それ以外(exe無し、またはマーカー無効)は
        NEED_FULL_SETUP(dev#230対策: 「exeがあるだけ」でreadyにしない、が核心)。
    """
    if not ensure_ps1_exists:
        return (
            BlenderSetupAction.READY_NO_ACTION
            if blender_exe_exists
            else BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT
        )
    if blender_exe_exists and check_only_valid:
        return BlenderSetupAction.READY_NO_ACTION
    return BlenderSetupAction.NEED_FULL_SETUP


def run_ensure_blender_check_only(
    ensure_ps1: str, app_root: str, timeout_sec: float = 10.0, log: Optional[LogFn] = None
) -> bool:
    """RunEnsureBlenderCheckOnly() L.2177-2205の移植。
    `ensure_blender.ps1 -CheckOnly` を同期・非表示で実行し、
    Test-D2PMarkerValid(exe実在+マーカー実在+version/sha256/patched一致)の
    結果を終了コードで受け取る。終了コード0=有効、それ以外/タイムアウト/例外は
    False(フル実行へフォールバック、安全側)。

    dev#1242: PowerShell実行ファイルの手動指定が無効(PwshManualPathError)な
    場合もFalse(安全側、フル実行へフォールバック)。この関数はbool以外の
    チャンネルを持たないため、詳細な失敗理由の伝達はrun_ensure_blender_setup_
    process()側(フル実行時に同じ手動指定を再度読み、失敗理由をfail_messageで
    返す)に委ねる。"""
    log_fn = log if log is not None else _noop_log
    try:
        pwsh = find_pwsh(app_root, log=log_fn)
    except PwshManualPathError as ex:
        log_fn(str(ex))
        return False
    try:
        args = [
            pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", ensure_ps1, "-AppRoot", app_root, "-CheckOnly",
        ]
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return False

    try:
        proc.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.communicate()
        except OSError:
            pass
        return False
    return proc.returncode == 0


def run_ensure_blender_setup_process(
    ensure_ps1: str,
    app_root: str,
    on_progress: Optional[Callable[[int, str], None]] = None,
    process_handle: Optional["BlenderSetupProcessHandle"] = None,
    log: Optional[LogFn] = None,
) -> Tuple[bool, Optional[str]]:
    """RunEnsureBlenderSetupProcess() L.2107-2169の移植。
    ensure_blender.ps1をフル実行(取得/再パッチ)し、標準出力/エラーの
    ##PROGRESS##行を on_progress(pct, phase) へ中継する(進捗中継)。
    失敗時は[D2P_BLENDER_SETUP_FAIL]以降の案内文をfail_messageとして返す
    (見つからなければ全出力、それも空ならNone)。
    呼び出し元が再度この関数を呼べば失敗時リトライになる(C#版のリトライボタンと
    同じ設計: このモジュール自体は再試行ループを持たず、UI側の明示操作に委ねる)。

    process_handle(dev#640、任意): 渡された場合、起動直後にPopenを
    process_handle.procへ登録し、終了時(成功/失敗いずれも)に必ずNoneへ戻す
    (C#版 blenderSetupProc = proc; ... blenderSetupProc = null; L.2147/2152/2165
    相当)。GUI終了時にメインスレッドから kill() できるようにするための配線。

    dev#1242: 実ユーザー報告(WinError 2, issue本文)を受け、①PowerShell実行
    ファイルの探索に手動指定フォールバック+探索ログを追加(_find_pwsh参照)、
    ②起動失敗メッセージを[D2P_BLENDER_SETUP_FAIL]構造(LAUNCH_FAIL_HEADER+
    "Reason: {ex}")へ変更し、main_window.pyの既存翻訳機構(dev#939)に
    そのまま乗るようにした(従来はハードコードされた日本語文言にOS生例外
    文字列がそのまま連結され、UI言語に関わらず常に日本語+OS言語混在だった)。"""
    log_fn = log if log is not None else _noop_log
    try:
        pwsh = find_pwsh(app_root, log=log_fn)
    except PwshManualPathError as ex:
        return False, str(ex)

    try:
        args = [
            pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", ensure_ps1, "-AppRoot", app_root,
        ]
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as ex:
        return False, f"{LAUNCH_FAIL_HEADER}\nReason: {ex}"

    if process_handle is not None:
        process_handle.proc = proc

    lines: List[str] = []
    try:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\r\n")
            lines.append(line)
            m = PROGRESS_MARK.match(line)
            if m and on_progress is not None:
                try:
                    pct = max(0, min(100, int(m.group(1))))
                except ValueError:
                    continue
                phase = m.group(2).strip()
                on_progress(pct, phase)
    finally:
        proc.wait()
        if process_handle is not None:
            process_handle.proc = None

    if proc.returncode == 0:
        return True, None

    full_output = "\n".join(lines)
    idx = full_output.find(FAIL_MARKER)
    fail_message = full_output[idx:].strip() if idx >= 0 else full_output.strip()
    return False, (fail_message or None)


def do_ensure_blender_ready(
    app_root: str,
    on_progress: Optional[Callable[[int, str], None]] = None,
    process_handle: Optional["BlenderSetupProcessHandle"] = None,
    log: Optional[LogFn] = None,
) -> Tuple[bool, Optional[str], BlenderSetupAction]:
    """DoEnsureBlenderReady() L.2037-2098の移植。ワーカースレッドで呼ぶ想定で
    あり、ここではUIに一切触れない(呼び出し元がスレッド分離とPostToUi相当の
    中継を担う、DESIGN.md §4.3)。

    戻り値: (ok, fail_message, action)。

    process_handle(dev#640、任意): run_ensure_blender_setup_process()へ
    そのまま転送する。NEED_FULL_SETUP以外の分岐(READY_NO_ACTION/
    DEV_NOT_FOUND_NO_SCRIPT)は子プロセスを起動しないため関与しない。

    WarmSharedCacheOnStartup/WarmBlenderProcessOnStartup相当の後続処理
    (成功後にバニラ準備等をバックグラウンドで撃つ最適化)は本WPのスコープ外
    (ファイル冒頭コメント参照)。

    dev#23b: find_blender()は手動指定(環境変数/設定ファイル)が無効な場合に
    BlenderManualPathErrorを送出するようになった。呼び出し元
    _blender_setup_worker()(main_window.py、書き込み許可外)は本関数を
    無防備に呼んでおり、ここで例外を伝播させるとワーカースレッドが無言で
    落ち、GUIが「確認中...」表示のまま永久にハングする。そのためここで
    捕捉し、通常の失敗経路(ok=False, fail_message, action)へ変換する。

    dev#1242: PowerShell実行ファイルの手動指定(D2P_PWSH_EXE/
    settings_pwshexe.txt)も同じ仕組みが必要になったが、_find_pwsh()を呼ぶ
    run_ensure_blender_check_only()/run_ensure_blender_setup_process()は
    いずれもPwshManualPathErrorを自分自身の関数内で捕捉し、既存の戻り値
    契約(bool / Tuple[bool, Optional[str]])のまま返す設計にした(ここまで
    例外を伝播させない)ため、本関数側で追加のtry/exceptは不要。"""
    log_fn = log if log is not None else _noop_log
    try:
        blender = find_blender(app_root, log=log_fn)
    except BlenderManualPathError as ex:
        return False, str(ex), BlenderSetupAction.MANUAL_PATH_INVALID
    ensure_ps1 = ensure_blender_ps1_path(app_root)
    ensure_ps1_exists = os.path.isfile(ensure_ps1)
    blender_exe_exists = os.path.isfile(blender)
    # -CheckOnlyはensurePs1が無ければ意味を持たない(遅延評価、L.2043-2046と同じ)
    check_only_valid = (
        ensure_ps1_exists
        and blender_exe_exists
        and run_ensure_blender_check_only(ensure_ps1, app_root, log=log_fn)
    )

    action = decide_blender_setup_action(ensure_ps1_exists, blender_exe_exists, check_only_valid)

    if action is BlenderSetupAction.READY_NO_ACTION:
        return True, None, action
    if action is BlenderSetupAction.DEV_NOT_FOUND_NO_SCRIPT:
        # dev#19 uimock2_fixes評価#6の副産物で発見: このモジュールはUIに
        # 触れない設計(関数docstring参照)であり、fail_messageはmain_window.py
        # 側のtranslate_blender_setup_fail_message()が行単位で翻訳する
        # (dev#1242の"[D2P_BLENDER_SETUP_FAIL] ..."ヘッダ行と同じ仕組み)。
        # したがってここでは生の日本語ではなく英語ASCIIを返す(ensure_blender.ps1
        # 由来の他の行と同じ規約)。旧版は生の日本語をここで直接返しており、
        # 英語UIモードでもこの1行だけ日本語が漏れる不具合だった(i18n_data.json
        # のキー完全性検査はこの経路をそもそも通らないため無力だった――
        # 検査の穴の詳細はRESULT.md参照)。
        return False, f"Blender not found (dev environment): {blender}", action
    # NEED_FULL_SETUP
    ok, fail_message = run_ensure_blender_setup_process(
        ensure_ps1, app_root, on_progress=on_progress, process_handle=process_handle,
        log=log_fn,
    )
    return ok, fail_message, action
