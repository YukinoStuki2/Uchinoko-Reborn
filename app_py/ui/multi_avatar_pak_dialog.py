# multi_avatar_pak_dialog.py -- dev#1170 WP-3(2026-08-09 オーナー確定仕様)
# 「マルチアバターPAK作成」ラボ機能の専用ダイアログ。
#
# 正本: issue #1170 の2026-08-09「確定仕様」コメント(オーナー対話)。
#   1. ラボ窓に1行追加。開くと専用ダイアログ
#   2. 初回は「設定開始」ボタン→ライブラリからアバターを1つ選択→その中間物が
#      全装備スロットへデフォルト充填される(割り当てなし=バニラ残しを
#      構造的に否定)
#   3. 左ペイン=Palworldの装備一覧(装備限定と同じカタログ・表示名)/
#      右ペイン=ライブラリ一覧(作成済みMOD一覧と1:1の中間物)
#   4. ペンキ方式: 右ペインでアバター名をクリック(選択状態)→左ペインの装備を
#      ぽちぽち押すと(連続複数可)最後に選択したアバターがその装備に割当。
#      アバターごとに自動色分けして見やすく
#   5. 中間物なしの旧エントリはグレーアウト+案内。マルチ品フラグの
#      エントリは右ペインに出さない
#   6. 専用「作成」ボタン→名前入力ダイアログ→合成エンジン(WP-2)を呼んで実行
#   7. 作成済みMOD一覧でマルチ品が単体と区別できる表示(→本WPでは
#      main_window.pyを触らないため、判定APIのみpak_manager.py側に用意
#      済み。配線は将来WPで1行差すだけ、詳細はpak_manager.entry_is_multi_
#      avatar()のdocstring参照)
#   8. 説明文言(ダイアログ内、5言語、i18n_data.json
#      LabMultiAvatarPakDialogHint)。{VER}はTOOL_VERSION定数から動的に
#      埋める(ハードコードしない、下記_tool_version()参照)
#   9. ラボ共通警告(any_feature_active())への合流は不要(メインパネルの
#      変換出力に影響しないため)。lab_window.py側のLabFeature.
#      affects_conversion=Falseで表現する
#
# 合成エンジン(WP-2、並行WP)との接続: multi_avatar_pak_compose.run_compose()
# がスタブ実装(dev#1170 WP-2確定後に中身だけ差し替える設計、同モジュールの
# docstring参照)。本ファイルはそのシグネチャにのみ依存する。
#
# ラボ憲章④: この機能はメインパネルの変換(job.json/pipeline_runner.
# write_job())に一切接続しない設計そのものが根拠(multi_avatar_pak_store.py
# モジュールdocstring参照)。ダイアログを開かない/対応表が空のときの出力
# 不変は「そもそも読まれる経路が無い」ことで自動的に満たされる。
from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import messagebox, simpledialog
from typing import Callable, Dict, List, Optional

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import multi_avatar_pak_compose  # noqa: E402
import multi_avatar_pak_store as _store  # noqa: E402
import pak_manager  # noqa: E402
from ui import equipment_select_dialog  # noqa: E402  (dev#165の装備カタログ取得を再利用)
from ui import window_pos  # noqa: E402  (2026-08-08: 親窓に重ねる位置決め)

LAB_FEATURE_ID = _store.LAB_FEATURE_ID
load_assignments = _store.load_assignments
save_assignments = _store.save_assignments
reset = _store.reset
is_active = _store.is_active
state_summary = _store.state_summary


def _tool_version() -> str:
    """app_py\\ui\\main_window.py の TOOL_VERSION 定数を動的に読む。

    main_window.pyはモジュール冒頭で `from ui import lab_window` しており、
    lab_window.pyはこのモジュールをimportするため、モジュール読み込み時に
    `from ui.main_window import TOOL_VERSION` を行うと循環importで失敗する
    (main_window.pyがTOOL_VERSIONを定義する行より前でlab_window.pyを
    importしているため)。ダイアログを実際に開く呼び出し時(この関数が
    呼ばれる時点)ではmain_window.pyの読み込みは既に完了しているため、
    関数本体内での遅延importなら安全に解決できる(循環importを断つ定石)。
    取得できなければ空文字列(バージョン非表示のフォールバック、三点セットの
    「わからないときは黙って壊さない」と同じ方針)。
    """
    try:
        from ui import main_window as _mw  # noqa: PLC0415 (意図的な遅延import)
        return str(getattr(_mw, "TOOL_VERSION", "") or "")
    except Exception:  # noqa: BLE001 -- バージョン文言が出せないだけで機能は止めない
        return ""


@dataclass
class MultiAvatarPakContext:
    app_root: str
    work_root: str
    palworld_pak: Optional[str]
    lang: str
    cache_dir: Optional[str] = None
    python_exe: Optional[str] = None
    append_log: Callable[[str], None] = field(default=lambda msg: None)
    # dev#1328: 合成成功後の自動適用コア。main_window.py._apply_pak_path_silent
    # (既存の「Palworldに適用」ボタンと同じpak_manager系機構をmessagebox無しで
    # 再利用したもの)を呼び出し元(lab_window.py)が注入する。Noneのまま(未配線・
    # テスト等)なら自動適用は行わず、_apply_after_compose()が「未配線」として
    # ログへ記録したうえで適用失敗と同じ扱いにする(「適用していないのに適用した
    # と言う」ことを防ぐ安全側)。シグネチャ: (pak_path, avatar_name) -> bool。
    apply_pak_path: Optional[Callable[[str, str], bool]] = None
    # dev#1352: 合成成功直後にメインGUIの作成済みMOD一覧(pakList)を更新する
    # ためのコア。main_window.py._on_refresh_pak_list(通常変換完了時に既に
    # 使われている一覧更新の仕組み、dev#601)を呼び出し元(lab_window.py)が
    # そのまま注入する——新規の更新機構は作らない。Noneのまま(未配線・テスト等)
    # なら一覧更新は行わない(ログにのみ記録、apply_pak_pathと同じ安全側)。
    # シグネチャ: () -> None。
    refresh_pak_list: Optional[Callable[[], None]] = None


def _apply_after_compose(
    ctx: MultiAvatarPakContext, pak_path: Optional[str], avatar_name: str
) -> bool:
    """dev#1328: 合成成功直後の自動適用を判定する純粋関数(tkinter非依存、
    単体試験しやすくするため_on_create()から抽出)。ctx.apply_pak_pathが
    Noneなら「未配線」として適用を試みず、pak_path欠落・例外もすべて失敗
    (False)扱いにする——「作成しました」だけを見せて実は適用していない、
    という状態を作らない安全側の判断(CLAUDE.md「値を寄せて合わせる修正は
    却下」と同じ、成功を偽装しない)。呼び出し元(worker()のon_ok())が
    戻り値に応じて統合済みの成功/失敗メッセージを1個だけ出す。"""
    if not pak_path:
        ctx.append_log("[lab][multi_avatar_pak] apply skipped: no pak_path in compose result")
        return False
    if ctx.apply_pak_path is None:
        ctx.append_log("[lab][multi_avatar_pak] apply skipped: no apply mechanism wired")
        return False
    try:
        applied = bool(ctx.apply_pak_path(pak_path, avatar_name))
    except Exception as ex:  # noqa: BLE001 -- 適用時の想定外例外もログのみ、通知は続行
        ctx.append_log(f"[lab][multi_avatar_pak] apply raised: {ex}")
        return False
    ctx.append_log(f"[lab][multi_avatar_pak] apply {'succeeded' if applied else 'failed'}: {avatar_name}")
    return applied


def _refresh_pak_list_after_compose(ctx: MultiAvatarPakContext) -> bool:
    """dev#1352: 合成成功直後にメインGUIの作成済みMOD一覧(pakList)を更新する
    (tkinter非依存の純粋関数、単体試験しやすくするため_on_create()から抽出)。
    通常変換完了時に既に使われている一覧更新の仕組み(main_window.py.
    _on_refresh_pak_list、dev#601)をそのまま呼ぶだけで、新規の更新機構は
    作らない。ctx.refresh_pak_listがNoneなら(未配線・テスト等)何もしない
    (「呼べないものを呼んだふりをしない」、_apply_after_compose()と同じ
    安全側の考え方)。呼び出し元の失敗時(ComposeNotReadyError/例外)からは
    呼ばれない——旧一覧のままでよい(負の対照: 変換失敗時は一覧を更新しない)。
    """
    if ctx.refresh_pak_list is None:
        ctx.append_log("[lab][multi_avatar_pak] pak list refresh skipped: no refresh mechanism wired")
        return False
    try:
        ctx.refresh_pak_list()
    except Exception as ex:  # noqa: BLE001 -- 一覧更新の失敗で成功通知自体は止めない
        ctx.append_log(f"[lab][multi_avatar_pak] pak list refresh raised: {ex}")
        return False
    ctx.append_log("[lab][multi_avatar_pak] pak list refreshed")
    return True


def _apply_failure_message_key(ctx: MultiAvatarPakContext) -> str:
    """dev#1353: 合成後の自動適用が失敗したときに表示するi18nキーを選ぶ
    (tkinter非依存の純粋関数)。Palworldが起動中であることが原因の失敗は、
    汎用の「適用に失敗しました」ではなく専用メッセージ
    (LabMultiAvatarPakCreateApplyFailureGameRunning)を選ぶ。プロセス検出は
    既存のpak_manager.is_game_running()(tasklist CSV出力でIMAGENAME列の
    25文字切り詰めを回避済み、main_window.py._apply_pak_path等で既に使われて
    いるものと同一)をそのまま再利用する——新規の検出ロジックは作らない。
    検出自体が例外を投げた場合は安全側(汎用メッセージ)に倒す。"""
    try:
        game_running = pak_manager.is_game_running()
    except Exception as ex:  # noqa: BLE001 -- 検出失敗は汎用メッセージへフォールバック
        ctx.append_log(f"[lab][multi_avatar_pak] game-running check raised: {ex}")
        return "LabMultiAvatarPakCreateApplyFailure"
    if game_running:
        return "LabMultiAvatarPakCreateApplyFailureGameRunning"
    return "LabMultiAvatarPakCreateApplyFailure"


def _make_scroll_area(parent: tk.Misc):
    """dev#165 equipment_select_dialog.pyと同じcanvas+scrollbar+innerframeの
    組み立て(マウスホイール対応込み)。2箇所(装備ペイン・ライブラリペイン)
    で使うのでヘルパー化した。戻り値: (canvas, inner, on_mousewheel)。
    inner配下に生成する個々のボタン/ラベルにも on_mousewheel を直接bindする
    こと(canvas単体へのbindだけでは、重なった子ウィジェット上でホイールが
    効かない——equipment_select_dialog.pyのコメントと同じ理由)。"""
    list_frame = tk.Frame(parent)
    list_frame.pack(fill="both", expand=True)
    canvas = tk.Canvas(list_frame, highlightthickness=0)
    scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas)
    inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    def _on_mousewheel(event: "tk.Event") -> str:
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    canvas.bind("<MouseWheel>", _on_mousewheel)
    inner.bind("<MouseWheel>", _on_mousewheel)
    return canvas, inner, _on_mousewheel


def show_multi_avatar_pak_dialog(parent: tk.Misc, ctx: MultiAvatarPakContext) -> tk.Toplevel:
    """マルチアバターPAK作成ダイアログ本体。呼び出しごとにToplevelを1個作る
    (equipment_select_dialog.show_equipment_select_dialog()と同じ流儀)。"""
    dlg = tk.Toplevel(parent)
    dlg.title(i18n.S("LabFeatureMultiAvatarPak"))
    dlg.geometry("640x520")
    dlg.transient(parent)
    i18n.register(dlg, "LabFeatureMultiAvatarPak", lambda w, t: w.title(t))
    window_pos.apply_offset_position(dlg, parent)

    # 装備カタログ・ライブラリ一覧はダイアログを開いた時点で1回だけ取得する
    # (ペンキ操作のたびにsubprocessでカタログを再取得すると重くなるため。
    # ダイアログを開いている間に別窓で変換が完了して一覧が増えても、次に
    # ダイアログを開き直すまで反映されない——ラボ憲章②の範囲内の割り切り)。
    catalog = equipment_select_dialog.query_equipment_catalog(
        ctx.app_root, ctx.palworld_pak, ctx.lang,
        cache_dir=ctx.cache_dir, python_exe=ctx.python_exe)
    ctx.append_log(f"[lab][multi_avatar_pak] catalog query: ok={catalog.get('ok')} "
                    f"source={catalog.get('source')} detail={catalog.get('detail')}")
    codes: List[str] = list(catalog.get("codes") or [])
    names: Dict[str, str] = dict(catalog.get("names") or {})
    display = {c: names.get(c, c) for c in codes}

    entries = pak_manager.list_library_entries(ctx.work_root)
    multi_flags = {
        e["job_dir"]: pak_manager.entry_is_multi_avatar(e["job_dir"]) for e in entries
    }
    selectable, grayed = pak_manager.partition_library_entries_for_multi_avatar_pak(
        entries, multi_flags)
    entry_name_by_id = {e["entry_id"]: e["avatar_name"] for e in (selectable + grayed)}

    # dev#1337 修正(2026-08-10 オーナー実機報告「左ペインをクリックするたびに
    # ライブラリの色が変わる+プチフリーズする」): 色割当は selectable
    # (ダイアログを開いた時点で固定済みの全ライブラリ一覧、上のブロックで
    # 既に1回だけ取得済み)から、ダイアログの生存期間全体で1回だけ計算する。
    # 旧実装は _render_main() 内で avatar_color_map(used_entry_ids(assignments))
    # を「再描画のたびに」呼んでいた。used_entry_ids() は
    # sorted(assignments.keys()) の先頭に出てくる装備コード順でentry_idを
    # 並べるため、どの装備をどのアバターへ塗るかで出現順が変わり、
    # 塗るたびに色の割当順(=見た目の色)がシフトしていた
    # (オーナー報告「色が毎回変わる」の機序、詳細はwork\wp_1337\NOTES.md)。
    # ライブラリ集合(selectable)自体は塗り操作で変化しないため、これを
    # 唯一の入力にすれば assignments の中身に関係なく色は不変になる。
    # 開き直せば selectable が新規に計算され、色も再計算される
    # (オーナー承認済みの「開時固定」の仮定どおり)。
    colors: Dict[str, str] = _store.avatar_color_map([e["entry_id"] for e in selectable])

    container = tk.Frame(dlg)
    container.pack(fill="both", expand=True)

    hint = tk.Label(
        dlg, text=i18n.F("LabMultiAvatarPakDialogHint", _tool_version()),
        wraplength=616, justify="left", anchor="w",
    )
    hint.pack(fill="x", padx=8, pady=(8, 4), before=container)

    def _refresh_hint(_w: tk.Misc, _t: str) -> None:
        hint.config(text=i18n.F("LabMultiAvatarPakDialogHint", _tool_version()))

    i18n.register(hint, "LabMultiAvatarPakDialogHint", _refresh_hint)

    # 2026-08-09 バグ修正(dev#1170、オーナー実機確認「1回やるごとにクリア
    # されちゃう」): 右ペインのアバター選択状態はrender()を呼ぶたびに
    # _render_main()が新しいdictへ作り直していたため、装備を1個塗る
    # (=on_change()経由でrender()を呼ぶ)たびに選択が消えていた
    # (オーナー確定仕様④「ペンキ方式: ...連続して複数可能」に反する)。
    # この選択状態をshow_multi_avatar_pak_dialog()側(ダイアログの生存期間
    # 全体で1個だけ)へ引き上げ、_render_main()には毎回同じdictを渡すことで
    # 再描画をまたいで保持されるようにする。選択の変更は明示操作
    # (別アバターのクリック)のみで起きる——装備を塗る操作自体は選択を
    # クリアしない(_render_main内のon_click_equipment()を参照)。
    selected_state: Dict[str, Optional[str]] = {"entry_id": None}

    # dev#1337 修正: assignments も selected_state と同じ流儀で、ダイアログの
    # 生存期間全体で1個のin-memory状態として保持する。旧実装は render() が
    # 呼ばれるたび(=左ペインで装備を1件塗るたび)に _store.load_assignments()
    # でディスクを読み直していた。装備を塗る操作自体は
    # on_click_equipment() -> _store.assign_many() が既に対応表を読み込み・
    # 保存済みで、その戻り値(保存直後の対応表そのもの)を素通りさせて
    # 捨てていたため、1クリックあたりファイル読み込みが2回発生していた
    # (assign_many内の読み+render内の読み直し)。この冗長I/Oと、その直後の
    # 全ウィジェット再構築が「毎回プチフリーズする」の実体と判断した
    # (詳細はwork\wp_1337\NOTES.md)。_apply_assignments_update() が
    # default_fill()/assign_many() の戻り値でassignments_stateを直接更新し、
    # render() 側の再読み込みを撤廃する。
    assignments_state: Dict[str, Dict[str, str]] = {
        "data": _store.load_assignments(ctx.app_root)
    }

    # dev#1341(オーナー裁定「クリックは1msだってかからない本来メモリ操作
    # だけの処理。他に必要な処理があるなら、それをUIと同期でやっているのが
    # おかしい」): assignments_stateへの更新は、装備を塗るクリック1回ごとに
    # ディスクへ同期書き込みしない。dirty_stateはメモリ上の対応表が
    # ディスク未反映(=保存が必要)かどうかのフラグで、実際の書き込みは
    # ダイアログを閉じる瞬間(_flush_if_dirty()、WM_DELETE_WINDOW/Closeボタン
    # 共通)にまとめて1回だけ行う("遅延書き込み"、issue本文の対応方針②)。
    # クローズ前にプロセスが異常終了した場合、直前の未フラッシュな編集
    # (装備の塗り直し・リセット)はディスクへ反映されないまま失われる
    # ——このダイアログはラボ機能の補助的な下書き編集であり(ラボ憲章④:
    # メインパネルの変換出力には一切接続しない)、失われても「PAK作成」を
    # やり直せば復旧できる範囲なので許容している。
    dirty_state: Dict[str, bool] = {"dirty": False}

    def _mark_dirty() -> None:
        dirty_state["dirty"] = True

    def _flush_if_dirty() -> None:
        if dirty_state["dirty"]:
            _store.save_assignments(ctx.app_root, assignments_state["data"])
            dirty_state["dirty"] = False
            ctx.append_log("[lab][multi_avatar_pak] flushed assignments to disk on close")

    def _on_close() -> None:
        _flush_if_dirty()
        dlg.destroy()

    def _apply_assignments_update(new_assignments: Dict[str, str]) -> None:
        assignments_state["data"] = new_assignments
        _mark_dirty()
        render()

    def _on_reset() -> None:
        # dev#1342: 「リセット」ボタン。既定(=未設定/空、multi_avatar_pak_
        # store.reset()と同じ定義)へ戻す。dev#1341の原則どおり、ここでも
        # ディスクへの同期書き込みは行わない(_apply_assignments_update経由
        # でdirty化し、クローズ時にまとめて反映)。空へ戻ると次のrender()は
        # 自動的に_render_setup()(「設定開始」画面)を表示する——値の意味は
        # 「割当なし」で他の未設定状態と区別が無いため、これは正しい遷移。
        ctx.append_log("[lab][multi_avatar_pak] reset requested (memory only, pending flush)")
        _apply_assignments_update({})

    def render() -> None:
        # dev#1341: render()(=container配下の全ウィジェット破棄+再構築)は
        # 「設定開始」→アバター選択の初回遷移、リセット、言語切替のような
        # 画面構造そのものが変わる操作でのみ呼ばれる。装備を塗る通常クリック
        # (on_click_equipment、_render_main内)はrender()を一切経由せず、
        # 影響する装備ボタン1個だけをconfig()で更新する(差分描画)。
        for w in container.winfo_children():
            w.destroy()
        assignments = assignments_state["data"]
        if not assignments:
            _render_setup(container, ctx, codes, selectable, _apply_assignments_update)
        else:
            _render_main(dlg, container, ctx, codes, display, selectable, grayed,
                         entry_name_by_id, assignments, colors, selected_state,
                         _mark_dirty, _on_reset, _on_close)

    # 2026-08-09 バグ修正(dev#1170、オーナー実機確認「Multi-Avatar PAKの
    # 装備名がLanguage Englishにしても日本語のまま」): displayはダイアログを
    # 開いた瞬間のctx.langで一度だけ組み立てられ、以後言語切替が起きても
    # 再取得されずに固定表示になっていた(equipment_select_dialog.py
    # ._refresh_names_on_language_change()には既に同種の追従があったが、
    # 本ダイアログには同等の仕掛けが無かった)。equipment_select_dialog.pyと
    # 同じ観測パターン(i18n.register()へのダミー登録、textそのものは使わず
    # カタログを新言語で再取得するコールバック)を追加し、displayを書き換えて
    # から再描画する。i18n.register()は登録直後に現在言語で1回setterを呼ぶ
    # ため、この登録はrender()定義より後(NameError回避)かつ最初のrender()
    # 呼び出しより前に置く必要がある。
    def _refresh_catalog_on_language_change(_widget: "tk.Misc", _text: str) -> None:
        ctx.lang = i18n.current_lang
        catalog2 = equipment_select_dialog.query_equipment_catalog(
            ctx.app_root, ctx.palworld_pak, ctx.lang,
            cache_dir=ctx.cache_dir, python_exe=ctx.python_exe)
        names2: Dict[str, str] = dict(catalog2.get("names") or {})
        for c in codes:
            display[c] = names2.get(c, c)
        render()

    i18n.register(dlg, "LabFeatureMultiAvatarPak", _refresh_catalog_on_language_change)

    render()
    # dev#1341: ウィンドウの「X」もClose(BtnClose)ボタンも、必ず同じ
    # _on_close()(=クローズ時の遅延書き込み+destroy)を通す。
    dlg.protocol("WM_DELETE_WINDOW", _on_close)
    return dlg


# ---------------------------------------------------------------------------
# 設定開始フロー(オーナー確定仕様②)
# ---------------------------------------------------------------------------


def _render_setup(
    container: tk.Misc,
    ctx: MultiAvatarPakContext,
    all_codes: List[str],
    selectable: list,
    on_done: Callable[[Dict[str, str]], None],
) -> None:
    state_frame = tk.Frame(container)
    state_frame.pack(fill="both", expand=True)

    def show_button() -> None:
        for w in state_frame.winfo_children():
            w.destroy()
        hint2 = tk.Label(
            state_frame, text=i18n.S("LabMultiAvatarPakSetupHint"),
            wraplength=600, justify="left", anchor="w",
        )
        hint2.pack(fill="x", padx=8, pady=(4, 8))
        i18n.register(hint2, "LabMultiAvatarPakSetupHint")

        if not selectable:
            empty = tk.Label(
                state_frame, text=i18n.S("LabMultiAvatarPakSetupNoEntries"),
                fg="#a06000", wraplength=600, justify="left",
            )
            empty.pack(fill="x", padx=8, pady=8)
            i18n.register(empty, "LabMultiAvatarPakSetupNoEntries")
            return

        btn = tk.Button(state_frame, text=i18n.S("LabMultiAvatarPakBtnSetup"),
                         command=show_picker)
        btn.pack(padx=8, pady=8)
        i18n.register(btn, "LabMultiAvatarPakBtnSetup")

    def show_picker() -> None:
        for w in state_frame.winfo_children():
            w.destroy()
        list_frame = tk.Frame(state_frame)
        list_frame.pack(fill="both", expand=True, padx=8, pady=8)
        for entry in selectable:
            tk.Button(
                list_frame, text=entry["avatar_name"], anchor="w",
                command=lambda eid=entry["entry_id"]: _pick(eid),
            ).pack(fill="x", pady=2)

    def _pick(entry_id: str) -> None:
        # dev#1341: _store.default_fill()(ディスクへ同期書き込み)ではなく
        # compute_default_fill()(純粋関数、I/O無し)を使う。ディスクへの
        # 反映はダイアログクローズ時の遅延書き込みに任せる(呼び出し元
        # show_multi_avatar_pak_dialog()の_apply_assignments_update()参照)。
        filled = _store.compute_default_fill(entry_id, all_codes)
        ctx.append_log(
            f"[lab][multi_avatar_pak] setup: default-filled {len(filled)} "
            f"slot(s) with entry_id={entry_id} (memory; pending flush)")
        on_done(filled)

    show_button()


# ---------------------------------------------------------------------------
# メイン画面(ペンキ方式割当、オーナー確定仕様③④)
# ---------------------------------------------------------------------------


def _render_main(
    dlg: tk.Toplevel,
    container: tk.Misc,
    ctx: MultiAvatarPakContext,
    codes: List[str],
    display: Dict[str, str],
    selectable: list,
    grayed: list,
    entry_name_by_id: Dict[str, str],
    assignments: Dict[str, str],
    colors: Dict[str, str],
    selected_state: Dict[str, Optional[str]],
    mark_dirty: Callable[[], None],
    on_reset: Callable[[], None],
    on_close: Callable[[], None],
) -> None:
    # dev#1337 修正: colorsはshow_multi_avatar_pak_dialog()側でダイアログ
    # 開時に1回だけ計算されたものを、パラメータとしてそのまま受け取る
    # (以前ここで assignments から毎回再計算していたのが色シャッフルの
    # 原因だった、詳細は呼び出し元・work\wp_1337\NOTES.md参照)。
    #
    # dev#1341: assignmentsは呼び出し元(show_multi_avatar_pak_dialog()の
    # assignments_state["data"])と同一のdictオブジェクト(コピーではない)。
    # on_click_equipment()はこのdictをその場で直接書き換える(assignments
    # [code] = eid)ため、呼び出し元のassignments_stateにも即座に反映される
    # ——render()を呼ばずに済む差分描画の前提。on_change(旧引数)は「画面
    # 構造ごと作り直す」場合(設定開始・リセット・言語切替)専用に限定し、
    # 名前をmark_dirty/on_reset/on_closeへ分離した(このコメント直下の
    # on_click_equipment()参照)。

    paint_hint = tk.Label(
        container, text=i18n.S("LabMultiAvatarPakPaintHint"),
        wraplength=616, justify="left", anchor="w",
    )
    paint_hint.pack(fill="x", padx=8, pady=(0, 4))
    i18n.register(paint_hint, "LabMultiAvatarPakPaintHint")

    panes = tk.Frame(container)
    panes.pack(fill="both", expand=True, padx=8, pady=4)

    left = tk.Frame(panes)
    left.pack(side="left", fill="both", expand=True, padx=(0, 4))
    right = tk.Frame(panes)
    right.pack(side="left", fill="both", expand=True, padx=(4, 0))

    left_header = tk.Label(left, text=i18n.S("LabMultiAvatarPakColEquipment"))
    left_header.pack(anchor="w")
    i18n.register(left_header, "LabMultiAvatarPakColEquipment")
    right_header = tk.Label(right, text=i18n.S("LabMultiAvatarPakColLibrary"))
    right_header.pack(anchor="w")
    i18n.register(right_header, "LabMultiAvatarPakColLibrary")

    _left_canvas, left_inner, left_mousewheel = _make_scroll_area(left)
    _right_canvas, right_inner, right_mousewheel = _make_scroll_area(right)

    # 2026-08-09バグ修正(dev#1170、詳細はshow_multi_avatar_pak_dialog()側の
    # コメント参照): selected_stateは呼び出し元(ダイアログの生存期間全体で
    # 1個)から渡された共有dict。ここではローカルで新規に作り直さない
    # (作り直すと再描画のたびに選択が失われる、ペンキ方式の連続塗りが
    # 壊れる原因そのものだった)。
    avatar_buttons: Dict[str, tk.Button] = {}

    def refresh_selection_visuals() -> None:
        for eid, btn in avatar_buttons.items():
            btn.config(relief=("sunken" if eid == selected_state["entry_id"] else "raised"))

    def on_pick_avatar(entry_id: str) -> None:
        selected_state["entry_id"] = entry_id
        refresh_selection_visuals()

    for e in selectable:
        color = colors.get(e["entry_id"], "#dddddd")
        btn = tk.Button(
            right_inner, text=e["avatar_name"], bg=color, anchor="w",
            command=lambda eid=e["entry_id"]: on_pick_avatar(eid),
        )
        btn.bind("<MouseWheel>", right_mousewheel)
        btn.pack(fill="x", pady=2)
        avatar_buttons[e["entry_id"]] = btn

    # 再描画(リセット・言語切替等でrender()が呼ばれ直した場合)をまたいでも、
    # 持ち越されたselected_stateの選択が右ペインの見た目(sunken表示)に
    # 反映されるよう、ボタンを作り終えた直後に一度同期する(dev#1341以降、
    # 装備を塗る操作自体はもうrender()を呼ばないため、この同期はここでの
    # 初回描画1回分のみで足りる)。
    refresh_selection_visuals()

    for e in grayed:
        lbl = tk.Label(right_inner, text=e["avatar_name"], fg="#999999", anchor="w")
        lbl.bind("<MouseWheel>", right_mousewheel)
        lbl.pack(fill="x", pady=2)

    if grayed:
        gray_hint = tk.Label(
            right, text=i18n.S("LabMultiAvatarPakGrayoutHint"),
            fg="#a06000", wraplength=280, justify="left",
        )
        gray_hint.pack(fill="x", pady=(4, 0))
        i18n.register(gray_hint, "LabMultiAvatarPakGrayoutHint")

    def _equipment_label_and_color(code: str, assigned_to: Optional[str]) -> tuple:
        color = colors.get(assigned_to, "#f0f0f0") if assigned_to else "#f0f0f0"
        label_text = display[code]
        if assigned_to:
            avatar_label = entry_name_by_id.get(assigned_to, assigned_to)
            label_text = f"{display[code]} -> {avatar_label}"
        return label_text, color

    # dev#1341: 装備ボタンをcode -> tk.Buttonで引けるようにしておき、
    # クリック時は該当ボタン1個だけをconfig()更新する(差分描画)。
    eq_buttons: Dict[str, tk.Button] = {}

    def on_click_equipment(code: str) -> None:
        eid = selected_state["entry_id"]
        if not eid:
            return
        # dev#1341(オーナー裁定「クリックは装備とアバターのIDを配列で関連
        # 付けするだけの処理、本来1msもかからない」): ここではディスクI/O
        # (assign_many()の読み込み・書き込み)も、ウィジェットの全再構築
        # (render())も一切発生しない。assignmentsは呼び出し元
        # (show_multi_avatar_pak_dialog())のassignments_state["data"]と
        # 同一のdictオブジェクトなので、この場での代入がそのまま「メモリ上の
        # 関連付け」そのものになる。永続化はダイアログクローズ時へ遅延する
        # (mark_dirty()でフラグを立てるだけ、ここではI/Oしない)。
        assignments[code] = eid
        mark_dirty()
        label_text, color = _equipment_label_and_color(code, eid)
        btn = eq_buttons.get(code)
        if btn is not None:
            btn.config(text=label_text, bg=color)
        ctx.append_log(f"[lab][multi_avatar_pak] assigned {code} -> {eid} (memory; pending flush)")

    for code in sorted(codes, key=lambda c: display[c].lower()):
        label_text, color = _equipment_label_and_color(code, assignments.get(code))
        eq_btn = tk.Button(
            left_inner, text=label_text, bg=color, anchor="w",
            command=lambda c=code: on_click_equipment(c),
        )
        eq_btn.bind("<MouseWheel>", left_mousewheel)
        eq_btn.pack(fill="x", pady=1)
        eq_buttons[code] = eq_btn

    bottom = tk.Frame(container)
    bottom.pack(fill="x", padx=8, pady=8)

    status_var = tk.StringVar(value="")
    status_label = tk.Label(bottom, textvariable=status_var, fg="#666666")
    status_label.pack(side="left")

    def _on_create() -> None:
        name = simpledialog.askstring(
            i18n.S("LabMultiAvatarPakNamePromptTitle"),
            i18n.S("LabMultiAvatarPakNamePromptBody"),
            parent=dlg,
        )
        if not name or not name.strip():
            return
        output_name = name.strip()
        # dev#1341: ディスクから読み直さない(まだフラッシュされていない
        # 塗り直しがある場合、ディスクは古い状態のままになりうる)。
        # assignmentsはassignments_state["data"]と同一オブジェクトの
        # 生きた最新状態そのものなので、そのままのコピーを渡せば十分。
        current_assignments = dict(assignments)
        job = multi_avatar_pak_compose.build_compose_job(output_name, current_assignments)

        create_btn.config(state="disabled")
        status_var.set(i18n.S("LabMultiAvatarPakCreateRunning"))

        def _safe_reset_controls() -> None:
            """dev#1320: 合成の実行中に言語切替が起きると、
            show_multi_avatar_pak_dialog()側のi18n登録コールバック
            (_refresh_catalog_on_language_change)がrender()を呼び、
            container配下のウィジェット(status_var/create_btn含む)を
            全部destroy()して作り直す。このworker()はrender()呼び出し
            時点のstatus_var/create_btnをクロージャで直接キャプチャして
            いるため、その後にdlg.after()経由で呼ばれるon_ok/on_fail/
            on_unavailableがそれらへtouchすると、destroy済みウィジェット
            へのconfig()/set()がTclErrorを投げる。tkinterのafter
            コールバック内で未捕捉の例外が起きると、その行より後の処理
              (=ユーザーに結果を伝えるmessagebox.showinfo/showerror)まで
            到達せず、静かに通知が消える(dev#1320実測: 合成完了msgbox・
            適用済み表示の両方が消えた)。
            通知(messagebox)は「再構築で死ぬウィジェット参照」に依存
            させず、常に生存するdlg(Toplevel自体はrender()で破棄されない)
            だけを頼りに届ける設計へ直す。このヘルパーはあくまで補助的な
            UI状態復帰(ボタン再有効化等)であり、失敗しても通知は止めない
            (各操作を個別にtry/exceptで保護し、呼び出し元は必ず続行する)。
            """
            try:
                status_var.set("")
            except tk.TclError:
                pass
            try:
                create_btn.config(state="normal")
            except tk.TclError:
                pass

        def worker() -> None:
            try:
                compose_result = multi_avatar_pak_compose.run_compose(
                    ctx.work_root, job, log=ctx.append_log, python_exe=ctx.python_exe)
            except multi_avatar_pak_compose.ComposeNotReadyError as ex:
                # 例外変数exはexceptブロックを抜けると暗黙にdelされるため、
                # dlg.after()で非同期に呼ばれるon_unavailable()の中で直接
                # 参照するとNameErrorになる(2026-08-09実装時に一度踏んだ罠)。
                # ブロック内で文字列化して別名へ退避してから閉じ込める。
                error_text = str(ex)

                def on_unavailable() -> None:
                    _safe_reset_controls()
                    messagebox.showinfo(
                        i18n.S("LabFeatureMultiAvatarPak"),
                        i18n.S("LabMultiAvatarPakComposeUnavailable"))
                    ctx.append_log(f"[lab][multi_avatar_pak] compose not ready: {error_text}")

                dlg.after(0, on_unavailable)
                return
            except Exception as ex:  # noqa: BLE001 -- ユーザーには整形済みの文言だけ見せる
                error_text = str(ex)  # 上のComposeNotReadyErrorと同じ理由でexを退避

                def on_fail() -> None:
                    _safe_reset_controls()
                    # dev#1514: 従来はerror_text(生例外文)をダイアログへ直接
                    # 埋め込んでいた。ダイアログはi18n定型文のみとし、生例外は
                    # append_log(下)だけに残す(診断能力を落とさない)。
                    messagebox.showerror(
                        i18n.S("LabFeatureMultiAvatarPak"),
                        i18n.S("LabMultiAvatarPakCreateFailureBody"))
                    ctx.append_log(f"[lab][multi_avatar_pak] compose failed: {error_text}")

                dlg.after(0, on_fail)
                return

            def on_ok() -> None:
                # dev#1320+dev#1328統合: 通知(messagebox)は状態復帰UIの成否に
                # 依存させない(_safe_reset_controls、言語切替でのTclError対策)。
                # 続けて自動適用(dev#1328)を試み、結果に応じた統合済みメッセージを
                # 1個だけ出す。
                _safe_reset_controls()
                # dev#1352: 合成はここまでで既に成功している(ライブラリに
                # 新エントリが保存済み)ため、適用の成否に関わらずメインGUIの
                # 作成済みMOD一覧を更新する(通常変換完了時と同じ仕組みの再利用)。
                _refresh_pak_list_after_compose(ctx)
                pak_path = (compose_result or {}).get("pak_path") or (compose_result or {}).get("out_pak")
                applied = _apply_after_compose(ctx, pak_path, output_name)
                if applied:
                    messagebox.showinfo(
                        i18n.S("LabFeatureMultiAvatarPak"),
                        i18n.S("LabMultiAvatarPakCreateAndApplySuccess"))
                else:
                    # dev#1353: Palworld起動中が原因の適用失敗は専用メッセージを
                    # 選ぶ(汎用の「適用に失敗しました」で原因と対処が伝わらない
                    # というオーナー実機報告への対応)。
                    messagebox.showwarning(
                        i18n.S("LabFeatureMultiAvatarPak"),
                        i18n.S(_apply_failure_message_key(ctx)))

            dlg.after(0, on_ok)

        threading.Thread(target=worker, daemon=True).start()

    create_btn = tk.Button(bottom, text=i18n.S("LabMultiAvatarPakBtnCreate"), command=_on_create)
    create_btn.pack(side="right")
    i18n.register(create_btn, "LabMultiAvatarPakBtnCreate")

    # dev#1341: ウィンドウの「X」と同じ_on_close()(=クローズ時の遅延書き込み
    # +destroy)を通す。dlg.destroy()を直接呼ぶと、未フラッシュな編集が
    # 保存されないまま失われてしまう。
    close_btn = tk.Button(bottom, text=i18n.S("BtnClose"), command=on_close)
    close_btn.pack(side="right", padx=(0, 4))
    i18n.register(close_btn, "BtnClose")

    # dev#1342: 「リセット」ボタン。押すと即座に既定(=未設定/空)へ戻る
    # (確認ダイアログ無し、issue本文「確認ダイアログなしの即時実行(KISS)」)。
    reset_btn = tk.Button(bottom, text=i18n.S("LabMultiAvatarPakBtnReset"), command=on_reset)
    reset_btn.pack(side="right", padx=(0, 4))
    i18n.register(reset_btn, "LabMultiAvatarPakBtnReset")
