# equipment_select_dialog.py -- dev#165(2026-08-08 装備限定)ラボ機能。
#
# 変換時に注入対象の装備を絞り込む複数選択ダイアログ+ラボUI基盤(dev#1186)
# 向けの機能レジストリ記述子。
#
# **既知欠陥は解消済み(2026-08-08 第2期、指揮者裁定・オーナーGO)**:
# 初版(第1期)はメッシュにしか効かずマテリアル(共有テクスチャアトラス)が
# 未選択装備でも残る欠陥(G12と同型)を抱えていたが、live_template.py/
# build_pak_from_avatar.py側の設計変更(除外集合を明示引数として渡し、
# テンプレートのフィンガープリントにequipment_filterを含める)で解消した。
# 詳細はpipeline\py\vp_equipment_filter.pyモジュールdocstring参照。
#
# **本WPはlab_window.py/main_window.pyへの結線を行わない**(並行WP dev#1186と
# の衝突回避、指示書の書き込み許可範囲)。結線に必要なのは以下の1行のみ:
#   lab_window.py 側:
#     LAB_FEATURES = [..., equipment_select_dialog.LAB_REGISTRY_DESCRIPTOR]
#   pipeline_runner.py(job.json組み立て箇所)側:
#     codes = equipment_select_dialog.load_selected_codes(app_root)
#     if codes:
#         job["equipment_filter"] = codes
#
# app_pyはpipeline\pyをimportしない設計(pak_manager.py冒頭コメント踏襲)。
# 装備コード一覧・表示名の解決は pipeline\py\vp_equipment_names.py を
# subprocessで起動してJSONを受け取る(pipeline_runner.pyがconvert.ps1を
# 起動するのと同じ「越境しない」流儀)。
#
# 権利裁定(2026-08-08、dev#165コメント6項): 装備固有名詞の実行時抽出・表示は
# 採用可。名称データそのものはこのファイルにもハードコードしない(常に
# ユーザー自身のpakから毎回読む)。抽出に失敗した場合は内部コード表示へ
# フォールバックし、機能自体(選択・保存)は維持する
# (CLAUDE.md「外部依存パスの原則」の三点セット)。
#
# 第4弾(2026-08-08、オーナー裁定「最初から正しい装備名で出せ」): 表示名解決の
# 実体はpipeline\py\vp_equipment_names.pyがDT_ItemNameText_Common(装備の
# 正式名DataTable)+DT_CharacterCreationMeshPresetTable_Equipments(装備コード
# →ItemIDの対応表)を直接パースして行う(locres単独では装備名が引けないことが
# 実測判明、詳細は同モジュールdocstring)。このファイル側の変更は、ダイアログを
# 開いたままメイン窓の言語が切り替わった場合にチェックボックス文言も追従させる
# 言語切替observer登録のみ(第3弾で導入済みのi18n.register()ダミー登録パターン
# を流用)。
from __future__ import annotations

import json
import os
import subprocess
import sys
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import messagebox
from typing import Callable, Dict, List, Optional, Set

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import window_pos  # noqa: E402  (2026-08-08: 親窓に重ねる位置決め)

# 2026-08-08 緊急修正(オーナー実測、lu_export.py即死): 選択状態の保存・
# 読み出しロジックは tkinter非依存の equipment_filter_store.py へ移動した。
# pipeline_runner.py はヘッドレス経路(tkinter未導入python)からも読み込まれる
# ため、tkinterをimportする本モジュールを直接importしてはならない
# (UI層 → store層の一方向依存。本モジュールはstoreの関数をそのまま
# 再エクスポートし、既存呼び出し元・テストの `esd.load_selected_codes` 等の
# 参照はそのまま動く)。
import equipment_filter_store as _store  # noqa: E402

LAB_FEATURE_ID = _store.LAB_FEATURE_ID
_STATE_FILENAME = _store._STATE_FILENAME
_state_path = _store._state_path
load_selected_codes = _store.load_selected_codes
save_selected_codes = _store.save_selected_codes
reset = _store.reset
is_active = _store.is_active
state_summary = _store.state_summary


# ---------------------------------------------------------------------------
# 装備カタログ+表示名の解決(pipeline\py\vp_equipment_names.py をsubprocess
# で起動する。app_pyはpipeline\pyをimportしない設計のため)。
# ---------------------------------------------------------------------------

def _pipeline_script_path(app_root: str, name: str) -> str:
    return os.path.join(app_root, "pipeline", "py", name)


def query_equipment_catalog(
    app_root: str,
    palworld_pak: Optional[str],
    lang: str,
    cache_dir: Optional[str] = None,
    python_exe: Optional[str] = None,
    timeout: float = 60.0,
) -> dict:
    """装備コード一覧+可能な限りの表示名を取得する。戻り値は常に
    {"ok": bool, "source": str, "detail": str, "codes": [...], "names": {...}}
    の形(例外を投げない)。palworld_pakが未解決(None/不在)、subprocess起動
    失敗、パース失敗、pak内解析失敗——いずれの経路でも ok=False + 空の
    codes/names を返すので、呼び出し側(ダイアログ)は「内部コード0件=検索
    UIだけ出して手入力を促す」既存動作へフォールバックできる
    (三点セットの③=detailに探索結果を残す)。"""
    if not palworld_pak or not os.path.exists(palworld_pak):
        return {"ok": False, "source": "none",
                "detail": f"palworld_pak not resolved: {palworld_pak!r}",
                "codes": [], "names": {}}

    script = _pipeline_script_path(app_root, "vp_equipment_names.py")
    if not os.path.exists(script):
        return {"ok": False, "source": "none",
                "detail": f"vp_equipment_names.py not found: {script}",
                "codes": [], "names": {}}

    cache_dir = cache_dir or os.path.join(app_root, "work", "_shared_cache", "equipment_names")
    py = python_exe or sys.executable
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(
            [py, script, palworld_pak, lang, cache_dir, ""],
            capture_output=True, text=True, timeout=timeout,
            creationflags=creationflags)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "source": "none",
                "detail": f"vp_equipment_names.py could not be run: "
                          f"{type(e).__name__}: {e}",
                "codes": [], "names": {}}

    if r.returncode != 0 or not (r.stdout or "").strip():
        stderr_tail = (r.stderr or "")[-500:]
        return {"ok": False, "source": "none",
                "detail": f"vp_equipment_names.py exited with {r.returncode} "
                          f"(stderr tail: {stderr_tail})",
                "codes": [], "names": {}}

    try:
        last_line = r.stdout.strip().splitlines()[-1]
        result = json.loads(last_line)
    except (json.JSONDecodeError, IndexError) as e:
        return {"ok": False, "source": "none",
                "detail": f"vp_equipment_names.py produced unparsable output: {e}",
                "codes": [], "names": {}}

    result.setdefault("codes", [])
    result.setdefault("names", {})
    return result


# ---------------------------------------------------------------------------
# ダイアログ本体(検索ボックス+スクロール付き複数選択チェックリスト)。
# ---------------------------------------------------------------------------

@dataclass
class EquipmentSelectContext:
    app_root: str
    palworld_pak: Optional[str]
    lang: str
    cache_dir: Optional[str] = None
    python_exe: Optional[str] = None
    append_log: Callable[[str], None] = field(default=lambda msg: None)


def show_equipment_select_dialog(parent: tk.Misc, ctx: EquipmentSelectContext) -> tk.Toplevel:
    """dev#165の装備選択ダイアログ本体。呼び出しごとにToplevelを1個作る
    (support_dialog.show_support_dialog()と同じ流儀)。OKで選択を保存、
    Cancelは破棄のみ(未保存で閉じる)。"""
    dlg = tk.Toplevel(parent)
    dlg.title(i18n.S("LabEquipmentFilterDialogTitle"))
    dlg.geometry("380x460")
    dlg.transient(parent)
    i18n.register(dlg, "LabEquipmentFilterDialogTitle", lambda w, t: w.title(t))
    # 2026-08-08: オーナー指摘「ラボサブウィンドウが左上に出るのが使いにくい。
    # メインに重なるように」対応。サイズ指定("380x460")は保ったまま位置だけ足す。
    window_pos.apply_offset_position(dlg, parent)

    result = query_equipment_catalog(
        ctx.app_root, ctx.palworld_pak, ctx.lang,
        cache_dir=ctx.cache_dir, python_exe=ctx.python_exe)
    ctx.append_log(f"[lab][equipment_filter] catalog query: ok={result.get('ok')} "
                    f"source={result.get('source')} detail={result.get('detail')}")

    codes: List[str] = list(result.get("codes") or [])
    names: Dict[str, str] = dict(result.get("names") or {})
    display = {c: names.get(c, c) for c in codes}

    # 2026-08-08 追加(オーナー指示、headequip_select_dialogの説明表示と
    # 同じ流儀: dlg直下にwraplength付きLabelをpackし、i18n.register()で
    # 言語切替に追従させる)。
    hint = tk.Label(dlg, text=i18n.S("LabEquipmentFilterHint"),
                     wraplength=356, justify="left", anchor="w")
    hint.pack(fill="x", padx=8, pady=(8, 0))
    i18n.register(hint, "LabEquipmentFilterHint")

    # dev#1170(WP-4、2026-08-09): 装備限定機能そのものの用途説明(誰向けか・
    # 変換はメインパネルから行う旨・複数アバター用途は別機能へ誘導)。
    # 既存hintと同じ流儀(dlg直下にwraplength付きLabelをpack、i18n.register()
    # で言語切替に追従)。オーナー確定文面(2026-08-09対話)をそのまま使う。
    purpose_hint = tk.Label(dlg, text=i18n.S("LabEquipmentFilterPurposeHint"),
                             wraplength=356, justify="left", anchor="w")
    purpose_hint.pack(fill="x", padx=8, pady=(4, 0))
    i18n.register(purpose_hint, "LabEquipmentFilterPurposeHint")

    if not codes:
        # 2026-08-08 バグ修正(PR #1202本文「既知の既存挙動」): カタログ取得が
        # 完全失敗(codes=[])した状態でOKを押すと、以前保存済みの選択が空
        # リストで黙って上書きされていた。ここでは失敗を目に見える形で伝え、
        # on_ok()側の保存スキップと対にする(「わからないときは黙って壊さない」)。
        notice = tk.Label(dlg, text=i18n.S("LabEquipmentFilterCatalogUnavailableNotice"),
                           fg="#a06000", wraplength=356, justify="left")
        notice.pack(fill="x", padx=8, pady=(8, 0))
        i18n.register(notice, "LabEquipmentFilterCatalogUnavailableNotice")
    elif not result.get("ok") and not names:
        notice = tk.Label(dlg, text=i18n.S("LabEquipmentFilterFallbackNotice"),
                           fg="#a06000", wraplength=356, justify="left")
        notice.pack(fill="x", padx=8, pady=(8, 0))
        i18n.register(notice, "LabEquipmentFilterFallbackNotice")

    # 2026-08-08 第3弾(チェック意味論変更): 保存済みの選択(=絞り込み対象の
    # ホワイトリスト)が空(=未カスタマイズ=既定)なら、UI上は「全装備が有効」
    # を表す全チェックON状態で見せる(store/job設定側の意味論——空=絞り込み
    # 無し=キー不在——は一切変えない。load_selected_codes()の戻り値をそのまま
    # 「表示上の選択集合」として使うか、空なら全カタログで代替するだけ)。
    # 既存の一部選択(非空)を読み込んだ場合は、その集合だけが従来どおり
    # チェックONになる(ホワイトリスト意味論は不変)。
    full_codes: Set[str] = set(codes)
    stored_selected: Set[str] = set(load_selected_codes(ctx.app_root))
    selected: Set[str] = stored_selected if stored_selected else full_codes

    search_frame = tk.Frame(dlg)
    search_frame.pack(fill="x", padx=8, pady=8)
    search_label = tk.Label(search_frame, text=i18n.S("LabEquipmentFilterSearchLabel"))
    search_label.pack(side="left")
    i18n.register(search_label, "LabEquipmentFilterSearchLabel")
    search_var = tk.StringVar()
    search_entry = tk.Entry(search_frame, textvariable=search_var)
    search_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))

    list_frame = tk.Frame(dlg)
    list_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
    canvas = tk.Canvas(list_frame, highlightthickness=0)
    scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas)
    inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # dev#165第2弾補修(2026-08-08): スクロールバーの直接ドラッグ操作しか
    # 効かなかったため、マウスホイールでもスクロールできるようにする
    # (Windows前提。event.deltaは120単位、正=上方向スクロール)。
    # bind_all()は使わない(他の窓・ダイアログへ副作用が漏れるため)——
    # canvas本体と、チェックリストが乗る中身フレーム・各チェックボタンへ
    # 個別にbindすることで、「リスト上にカーソルがあれば効く」を実現する
    # (チェックボタンはcanvas上に重なる別ウィジェットなので、canvas単体への
    # bindだけではチェックボタンの上でホイールが効かない)。
    def _on_mousewheel(event: "tk.Event") -> str:
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    canvas.bind("<MouseWheel>", _on_mousewheel)
    inner.bind("<MouseWheel>", _on_mousewheel)

    check_vars: Dict[str, tk.BooleanVar] = {}
    check_widgets: Dict[str, tk.Checkbutton] = {}
    for code in sorted(codes, key=lambda c: display[c].lower()):
        var = tk.BooleanVar(value=(code in selected))
        check_vars[code] = var
        cb = tk.Checkbutton(inner, text=display[code], variable=var, anchor="w")
        cb.bind("<MouseWheel>", _on_mousewheel)
        check_widgets[code] = cb

    def apply_search(*_args) -> None:
        q = search_var.get().strip().lower()
        for cb in check_widgets.values():
            cb.pack_forget()
        for code in sorted(codes, key=lambda c: display[c].lower()):
            if q and q not in display[code].lower() and q not in code.lower():
                continue
            check_widgets[code].pack(anchor="w", fill="x")

    search_var.trace_add("write", apply_search)
    apply_search()

    # 2026-08-08(dev#165第4弾、装備名DataTable直接解決): 装備の表示名は
    # ctx.lang依存(DT_ItemNameText_Commonの言語別バリアント)なので、この
    # ダイアログが開いたままメイン窓側で言語が切り替わった場合(このダイアログ
    # は`grab_set()`していないためメイン窓は開いている間も操作できる)、表示中の
    # チェックボックス文言も追従させる。既存の「言語切替のobserver化」(第3弾、
    # lab_window.py._status_refresh_on_language_changeと同じ流儀)にならい、
    # i18n.register()へダミー登録(text自体は使わずカタログを新言語で再取得する
    # コールバック)を1件加えるだけの最小の仕掛け(main_window.py側は無改変)。
    def _refresh_names_on_language_change(_widget: "tk.Misc", _text: str) -> None:
        ctx.lang = i18n.current_lang
        result2 = query_equipment_catalog(
            ctx.app_root, ctx.palworld_pak, ctx.lang,
            cache_dir=ctx.cache_dir, python_exe=ctx.python_exe)
        names2: Dict[str, str] = dict(result2.get("names") or {})
        for code in codes:
            display[code] = names2.get(code, code)
            check_widgets[code].config(text=display[code])
        apply_search()

    i18n.register(dlg, "LabEquipmentFilterDialogTitle", _refresh_names_on_language_change)

    btn_frame1 = tk.Frame(dlg)
    btn_frame1.pack(fill="x", padx=8)
    select_all_btn = tk.Button(
        btn_frame1, text=i18n.S("LabEquipmentFilterSelectAll"),
        command=lambda: [v.set(True) for v in check_vars.values()])
    select_all_btn.pack(side="left")
    i18n.register(select_all_btn, "LabEquipmentFilterSelectAll")
    clear_all_btn = tk.Button(
        btn_frame1, text=i18n.S("LabEquipmentFilterClearAll"),
        command=lambda: [v.set(False) for v in check_vars.values()])
    clear_all_btn.pack(side="left", padx=(4, 0))
    i18n.register(clear_all_btn, "LabEquipmentFilterClearAll")

    btn_frame2 = tk.Frame(dlg)
    btn_frame2.pack(fill="x", padx=8, pady=8)

    def on_ok() -> None:
        if not full_codes:
            # 2026-08-08 バグ修正(PR #1202本文「既知の既存挙動」): カタログ
            # 取得が完全失敗(codes=[])した状態では、full_codes==set()==chosen
            # (どちらも空集合)が常に成立してしまい、下の「全ON=既定」判定に
            # 誤ってヒットして保存済みの選択を空リストで上書きしていた。
            # カタログが取れていない=何を選んだか判断できない状態なので、
            # 保存は一切行わずダイアログを閉じるだけにする(既存の保存値は
            # 触らない。「わからないときは黙って壊さない」)。
            ctx.append_log(
                "[lab][equipment_filter] catalog unavailable (codes empty); "
                "OK closed without saving, existing selection preserved")
            dlg.destroy()
            return
        chosen = {code for code, var in check_vars.items() if var.get()}
        # 2026-08-08 第3弾: 全OFF(絞り込みの結果、注入対象の装備が1つも無く
        # なる状態)は禁止する(ラボ憲章②の枠内で簡便な実装=警告して保存を
        # 弾くだけ、チェックボタン自体の操作は制限しない)。カタログ自体が
        # 空(codes==[])のときは常に「全て一致」になり誤検知しないよう
        # full_codesが空でない場合だけ判定する。
        if full_codes and not chosen:
            messagebox.showwarning(
                i18n.S("LabEquipmentFilterDialogTitle"),
                i18n.S("LabEquipmentFilterAllOffWarning"))
            return
        if chosen == full_codes:
            # 全ON=既定(絞り込み無し)。空リストとして保存することで、
            # job設定にequipment_filterキーが一切出ない状態(ラボ憲章④:
            # 未実装状態と完全に同一)を維持する。
            save_selected_codes(ctx.app_root, [])
        else:
            save_selected_codes(ctx.app_root, sorted(chosen))
        ctx.append_log(
            f"[lab][equipment_filter] selection saved: "
            f"{len(chosen)} of {len(full_codes)} code(s) checked")
        dlg.destroy()

    ok_btn = tk.Button(btn_frame2, text=i18n.S("BtnOk"), command=on_ok)
    ok_btn.pack(side="right")
    i18n.register(ok_btn, "BtnOk")
    cancel_btn = tk.Button(btn_frame2, text=i18n.S("BtnCancel"), command=dlg.destroy)
    cancel_btn.pack(side="right", padx=(0, 4))
    i18n.register(cancel_btn, "BtnCancel")

    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    return dlg


# ---------------------------------------------------------------------------
# dev#1186 ラボ機能レジストリ記述子(lab_window.py側が結線する1行のためだけの
# もの。本WPではlab_window.pyを変更しない)。
# id / i18n名称キー / 状態サマリ関数 / ダイアログを開く関数 / リセット関数。
# ---------------------------------------------------------------------------

LAB_REGISTRY_DESCRIPTOR = {
    "id": LAB_FEATURE_ID,
    "name_key": "LabFeatureEquipmentFilter",
    "state_summary": state_summary,
    "open_dialog": show_equipment_select_dialog,
    "reset": reset,
}
