# multi_avatar_pak_compose.py -- dev#1170 WP-3(マルチアバターPAK作成)の
# 「作成」ボタンが呼ぶ合成ジョブ組み立て+実行呼び出し(tkinter非依存)。
#
# 合成エンジン本体(WP-2、`pipeline\\py\\vp_avatar_compose.py`)への接続点。
# WP-3時点ではWP-2のCLI/関数APIが未確定だったため、呼び出し部を本モジュールの
# run_compose() 1関数へ集約するスタブ実装だった(呼び出しシグネチャ
# (work_root, job, log, python_exe) は変えない設計。呼び出し元の
# ui\\multi_avatar_pak_dialog.pyはこのシグネチャにしか依存しない)。
#
# dev#1170 WP-5(本WP、2026-08-09)で実接続済み: WP-2確定のCLI/関数API
# (`vp_avatar_compose.compose(work_root, job, log=...)`)を直接importして
# 呼ぶ。呼び出し方は `app_py\\pak_manager.py` が dev#1170 WP-1 で確立した
# 「app_py側は sys.path.insert(0, <root>/pipeline/py) してから通常import
# する」パターンをそのまま踏襲する(equipment_select_dialog.py系のsubprocess
# 越境パターンは、本モジュールがヘッドレス経路から呼ばれないため不要
# ——pak_manager.pyの同パターンの説明コメント参照)。
#
# 入力=合成ジョブJSON(指示書より): {"output_name": str, "assignments":
# {装備コード: エントリID, ...}}。pipeline\\配下(WP-2の担当領域)は本WPでは
# 一切変更しない——本モジュールは pipeline\\py の実装ファイルを一切編集せず、
# importして呼ぶだけ。
from __future__ import annotations

import os
import sys
from typing import Callable, Dict, Optional

_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_APP_PY_DIR)
_PIPELINE_PY_DIR = os.path.join(_ROOT_DIR, "pipeline", "py")

# 合成ジョブJSONのフォーマットversion。WP-2側のCLI/関数APIが読む契約を破壊的に
# 変える場合はここを上げる(manifest.jsonのFORMAT_VERSIONと同じ発想)。
COMPOSE_JOB_FORMAT_VERSION = 1


class ComposeNotReadyError(RuntimeError):
    """合成エンジン(WP-2)を呼び出せない場合に送出する。WP-5(本WP)実接続後は
    「未接続」ではなく「pipeline\\py\\vp_avatar_compose.pyをimportできない」
    (環境破損等の想定外事態)場合の防御的フォールバックとして残す——
    「動くふりをして壊れた結果を返す」より安全側(CLAUDE.md「値を寄せて合わせる
    修正は却下」と同じ精神)。呼び出し元(ui\\multi_avatar_pak_dialog.py)は
    この例外を捕まえ、i18nキー LabMultiAvatarPakComposeUnavailable の
    メッセージへ翻訳してユーザーへ見せる(スタックトレースを直接見せない)。"""


def build_compose_job(output_name: str, assignments: Dict[str, str]) -> dict:
    """合成ジョブJSONを組み立てる純粋関数。output_name/assignmentsの妥当性
    (空でないか等)はダイアログ側(ui\\multi_avatar_pak_dialog.py)が「作成」
    ボタンの押下前に確認する想定——本関数自体は正規化(空文字列キー/値の
    除去)だけを行い、例外を投げない。"""
    clean_assignments = {
        str(code): str(entry_id)
        for code, entry_id in (assignments or {}).items()
        if code and entry_id
    }
    return {
        "format_version": COMPOSE_JOB_FORMAT_VERSION,
        "output_name": output_name or "",
        "assignments": clean_assignments,
    }


def run_compose(
    work_root: str,
    job: dict,
    log: Callable[[str], None] = print,
    python_exe: Optional[str] = None,
) -> dict:
    """合成エンジン(WP-2、`pipeline\\py\\vp_avatar_compose.py`)への接続点。

    実体は `vp_avatar_compose.compose(work_root, job, log=log)`(=
    `compose_avatar(job, work_root, log=log)` の薄いラッパー、引数順序が
    work_root/jobで逆であること以外は同じ)を直接呼ぶだけ。importは遅延
    (関数呼び出し時)で行う——モジュール読み込み時点でpipeline\\pyの重い
    依存(vp_equipment_avatar/live_template等)を巻き込まないため、かつ
    importに失敗した場合だけを診断できるようにするため。

    python_exe引数は呼び出し元(ui\\multi_avatar_pak_dialog.py)の既存
    シグネチャ互換のために残すが、直接import経路では使わない(未使用。
    pak_manager.pyの直接importパターンに倣った結果、サブプロセス起動が
    不要になったため)。

    想定内の入力エラー(未充填スロット・存在しないエントリID等)は
    `vp_avatar_compose.ComposeError` がそのまま呼び出し元へ伝播する(既に
    ユーザーを咎めない文言で書かれている——ui\\multi_avatar_pak_dialog.pyの
    汎用except節がLabMultiAvatarPakCreateFailureBodyへ整形して表示する)。
    importできない(環境破損等の想定外事態)場合のみComposeNotReadyErrorを
    送出する(クラスdocstring参照)。
    """
    if _PIPELINE_PY_DIR not in sys.path:
        sys.path.insert(0, _PIPELINE_PY_DIR)
    try:
        import vp_avatar_compose  # noqa: E402 (sys.path挿入後の遅延import)
    except ImportError as e:
        log(f"[multi_avatar_pak_compose] compose engine could not be loaded: {e}")
        raise ComposeNotReadyError(
            f"multi-avatar PAK compose engine could not be loaded: {e}") from e

    return vp_avatar_compose.compose(work_root, job, log=log)
