# sway_chain_dialog.py -- 揺れものUI プロトタイプ(dev#19、実物GUI埋め込み版
# WP、work\rd_19_flight\briefs\uimock2_embedded.md)。ラボ機能「揺れもの詳細
# 設定」のダイアログ本体。
#
# mesh_delete_dialog.py(カタログ取得+チェックリストUI)とlab_window.py内の
# LabDialog試作(work\rd_19_uimock\mock_sway_ui.py、前作モック)を土台にした、
# 実物GUI埋め込み版。
#
# 意味論:
#   - チェーン一覧の行はON/OFF(揺れるか)+かたさ(標準に従う/固め/ふつう/
#     やわらかめ)+安全域(dev#1551、下記)を持つ。既定=ON・標準に従う・
#     安全域1。
#   - 既定から変わっている行だけが sway_chain_override_store.py へ保存される
#     (ラボ憲章④)。
#   - dev#1551(安全域WP、issue #1551「安全域」欄、2026-08-18オーナー最終
#     裁定): 各鎖の「安全域」はドナーボーンを先端から何本削るかを指定する
#     (`pipeline\py\sway_hub.target_len_with_safety_margin()`が実際の
#     計算式「反映骨数=min(donor容量,アバター鎖長)−安全域」)。先端の動きが
#     おかしい揺れものは安全域を増やすとよい——製品既定値は1(GUI未設定でも
#     常に1本分マージされる、`pipeline\blender\step02_retarget.py`
#     `SWAY_DEFAULT_SAFETY_MARGIN`)。
#   - チェーンのデータ源は入力アバター自身(VRM: vrm_spring_catalog.py の
#     GLB直読み / prefab: physbone_catalog.py のUnity輸出済みサイドカー)。
#     いずれも未解決(未読込・輸出未実行等)の場合は空状態の正規表示を出す
#     (本WP指示書の要求どおり)。
#   - 開発確認用の`--sample`フラグ(main.py起動時、work\rd_19_uimock2\
#     RESULT.mdに明記のとおり製品には残さない前提)で、実データの代わりに
#     組み込みサンプルチェーンを注入できる(空状態/サンプル入り状態の両方を
#     UI評価できるようにするため)。
from __future__ import annotations

import json
import os
import struct
import sys
import tkinter as tk
from collections import Counter
from tkinter import ttk
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)
_ROOT_DIR = os.path.dirname(_APP_PY_DIR)
_PIPELINE_PY_DIR = os.path.join(_ROOT_DIR, "pipeline", "py")
if _PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_PY_DIR)

import i18n  # noqa: E402
import physbone_catalog  # noqa: E402  (dev#1356: prefab側サイドカーのスキーマ検証)
import pipeline_runner  # noqa: E402  (resolve_unity_export_out_dir()の再利用のみ)
import vrm_spring_catalog  # noqa: E402  (dev#1370: VRM側spring boneのGLB直読み)
from ui import window_pos  # noqa: E402

# dev#19 native-donor-rule WP(issue #19、2026-08-14夜オーナー最終裁定):
# 尻尾/耳の同定はpipeline\py\sway_identify.py(bpy非依存の純粋関数)を、
# app_py\pak_manager.pyが確立した「sys.path.insert(0, <root>/pipeline/py)して
# から通常import」パターンで直接importする(app_py\multi_avatar_pak_compose.py
# と同型)。判定ロジックの複製はしない——真実の源は同定関数1つ。
import sway_identify  # noqa: E402

import sway_chain_override_store as _store  # noqa: E402

LAB_FEATURE_ID = _store.LAB_FEATURE_ID
HARDNESS_CHOICES = _store.HARDNESS_CHOICES  # ("follow", "hard", "normal", "soft")
# dev#1551(安全域WP): 製品既定値/上限。store.py側の値を唯一の真実の源と
# する(ここでは再定義しない)。
DEFAULT_SAFETY_MARGIN = _store.DEFAULT_SAFETY_MARGIN
MAX_SAFETY_MARGIN = _store.MAX_SAFETY_MARGIN
load_config = _store.load_config
save_config = _store.save_config
clear_avatar = _store.clear_avatar
reset = _store.reset
is_active = _store.is_active
state_summary = _store.state_summary

_HARDNESS_KEYS = {
    "follow": "LabSwayChainHardnessFollow",
    "hard": "SwayIntensityHard",
    "normal": "SwayIntensityNormal",
    "soft": "SwayIntensitySoft",
}

# 開発確認用サンプル(--sampleフラグ専用、製品には残さない。RESULT.md参照)。
SAMPLE_CHAINS: List[Dict[str, Any]] = [
    {"anchor": "J_Bip_C_Hips", "bones": ["J_Bip_C_Hips", "Tail_01", "Tail_02", "Tail_03"],
     "node_count": 3},
    {"anchor": "J_Bip_C_Head", "bones": ["J_Bip_C_Head", "EarL_01", "EarL_02"],
     "node_count": 2},
    {"anchor": "J_Bip_C_Head", "bones": ["J_Bip_C_Head", "EarR_01", "EarR_02"],
     "node_count": 2},
    {"anchor": "J_Bip_C_Spine2", "bones": ["J_Bip_C_Spine2", "HairBack_01", "HairBack_02",
                                            "HairBack_03", "HairBack_04"], "node_count": 4},
    {"anchor": "J_Bip_C_Hips", "bones": ["J_Bip_C_Hips", "Skirt_F_01", "Skirt_F_02"],
     "node_count": 2},
    {"anchor": "J_Bip_C_Hips", "bones": ["J_Bip_C_Hips", "Skirt_B_01", "Skirt_B_02"],
     "node_count": 2},
]


# ---------------------------------------------------------------------------
# カタログ取得(mesh_delete_dialog.pyのVRM/prefab二本立てと同型)。
# ---------------------------------------------------------------------------

def _read_glb_json_chunk(vrm_path: str) -> dict:
    with open(vrm_path, "rb") as f:
        header = f.read(12)
        if len(header) < 12:
            raise ValueError("file too small to be a GLB/VRM container")
        magic, _version, _length = struct.unpack("<4sII", header)
        if magic != b"glTF":
            raise ValueError(f"not a glTF/VRM binary container (magic={magic!r})")
        chunk_header = f.read(8)
        if len(chunk_header) < 8:
            raise ValueError("missing JSON chunk header")
        chunk_len, chunk_type = struct.unpack("<I4s", chunk_header)
        if chunk_type != b"JSON":
            raise ValueError(f"first chunk is not JSON (type={chunk_type!r})")
        chunk = f.read(chunk_len)
        if len(chunk) < chunk_len:
            raise ValueError("truncated JSON chunk")
    return json.loads(chunk)


def _flatten_physbone_entries(entries: List[dict]) -> List[Dict[str, Any]]:
    """physbone_catalog/vrm_spring_catalog共通の{"anchor","chains":[[...]]}
    形式を、本ダイアログが扱う「1チェーン=1行」のフラットリストへ整形する。
    "bones"はanchorを先頭に含めた列(sway_manual job設定キーの想定形
    {"bones":[anchor,node1,...]}に合わせた、将来の実キー命名を意識した形。
    work\\rd_19_uimock2\\RESULT.md参照)。"""
    out = []
    for entry in entries:
        anchor = entry.get("anchor")
        if not anchor:
            continue
        for chain in entry.get("chains") or []:
            if not chain:
                continue
            out.append({
                "anchor": anchor,
                "bones": [anchor] + list(chain),
                "node_count": len(chain),
            })
    return out


def query_sway_catalog(app_root: str, work_root: str, avatar_path: str) -> dict:
    """入力アバターの揺れチェーン一覧を取得する。戻り値は常に
    {"ok": bool, "source": str, "detail": str, "chains": [...]}
    の形(例外を投げない、既存catalog群と同じ三点セット方針)。"""
    if not avatar_path or not os.path.exists(avatar_path):
        return {"ok": False, "source": "none",
                "detail": f"avatar not selected or not found: {avatar_path!r}", "chains": []}

    ext = os.path.splitext(avatar_path)[1].lower()

    if ext == ".vrm":
        result = vrm_spring_catalog.catalog_from_vrm(avatar_path)
        chains = _flatten_physbone_entries(result.get("physbones") or [])
        return {"ok": bool(result.get("ok")) and bool(chains), "source": "vrm",
                "detail": result.get("detail", ""), "chains": chains}

    if ext == ".prefab":
        out_dir = pipeline_runner.resolve_unity_export_out_dir(work_root, avatar_path)
        sidecar = os.path.join(out_dir, "physbones.json")
        result = physbone_catalog.catalog_from_sidecar(sidecar)
        chains = _flatten_physbone_entries(result.get("physbones") or [])
        return {"ok": bool(result.get("ok")) and bool(chains), "source": "prefab",
                "detail": result.get("detail", ""), "chains": chains}

    return {"ok": False, "source": "none",
            "detail": f"unsupported avatar extension for sway chain enumeration: {ext!r}",
            "chains": []}


def _merge_working_set(
    catalog_chains: List[Dict[str, Any]], saved_overrides: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """カタログ由来の行(既定値+保存済み上書きがあれば適用)と、手動追加行
    (保存済みのmanual=Trueエントリ)を1つの作業用リストへ合成する。

    既定チェック状態(dev#19 native-donor-rule WP、issue #19、2026-08-14夜
    オーナー最終裁定): 保存済み上書きが無い行の既定enabledは、これまでの
    「常にTrue(全鎖ON)」から、sway_identify.default_sway_enabled()による
    同定結果(尻尾・耳=ON、その他(スカート・髪・エプロン・スカーフ等)=OFF)
    へ変更する。同定の役割はこの既定値を決めることのみ——保存済み上書きが
    あればそちらが常に優先される(揺れ対象=「チェックされた鎖」ただそれだけ、
    隠れフィルタは無い)。"""
    saved_by_bones = {
        tuple(e["bones"]): e for e in saved_overrides if not e.get("manual")
    }
    working: List[Dict[str, Any]] = []
    for c in catalog_chains:
        key = tuple(c["bones"])
        override = saved_by_bones.get(key)
        default_enabled = sway_identify.default_sway_enabled(c["anchor"], c["bones"][1:])
        working.append({
            "anchor": c["anchor"], "bones": c["bones"], "node_count": c["node_count"],
            "enabled": bool(override["enabled"]) if override else default_enabled,
            "hardness": override["hardness"] if override else "follow",
            "manual": False,
            # dev#1551(安全域WP): 保存済み上書きがあればそれを、無ければ
            # 製品既定値(1)を使う。
            "safety_margin": (
                override.get("safety_margin", DEFAULT_SAFETY_MARGIN) if override
                else DEFAULT_SAFETY_MARGIN),
        })
    for e in saved_overrides:
        if e.get("manual"):
            working.append({
                "anchor": None, "bones": e["bones"],
                "node_count": max(0, len(e["bones"]) - 1),
                "enabled": bool(e.get("enabled", True)),
                "hardness": e.get("hardness", "follow"),
                "manual": True,
                "safety_margin": e.get("safety_margin", DEFAULT_SAFETY_MARGIN),
            })
    return working


def _display_name(
    entry: Dict[str, Any], anchor_counts: Optional[Dict[str, int]] = None
) -> str:
    """チェーンの表示名(dev#1470、オーナー要望2026-08-15「ボーン名が
    『揺れの末端』になっていて気持ち悪い。始点側の名前であるべき」)。

    旧仕様は entry["bones"][-1](末端/先端ボーン名)を表示していたが、
    表示のみを entry["bones"][0](始点/根本=anchorボーン、手動行では
    唯一のボーン名)へ変更する。ストアの保存キー(bones全体のtuple)・
    同定ロジック・job出力は一切変えない——本関数の戻り値はUI表示にのみ
    使われる(表示のみの変更、BRIEF C:\\P\\Work\\DiveToPalworld\\work\\
    wp_chainname\\BRIEF.md参照)。

    同じ始点ボーンを共有する複数チェーンが存在する場合(例: スカート前後
    が両方Hips始点、耳L/Rが両方Head始点)、始点名だけでは行を区別できず
    誤操作の原因になる。anchor_countsで始点名の出現回数を渡された場合、
    重複する行だけ直後の最初のノードボーン名(bones[1]、例: "Skirt_F_01")
    を括弧書きで添えて一意にする。"""
    base = entry["bones"][0]
    if anchor_counts and anchor_counts.get(base, 1) > 1 and len(entry["bones"]) > 1:
        return f"{base} ({entry['bones'][1]})"
    return base


# ---------------------------------------------------------------------------
# ダイアログ本体。
# ---------------------------------------------------------------------------

@dataclass
class SwayChainContext:
    app_root: str
    work_root: str
    avatar_path: str
    sample_mode: bool = False
    append_log: Callable[[str], None] = field(default=lambda msg: None)


def show_sway_chain_dialog(parent: tk.Misc, ctx: SwayChainContext) -> tk.Toplevel:
    dlg = tk.Toplevel(parent)
    dlg.title(i18n.S("LabSwayChainDialogTitle"))
    dlg.geometry("560x560")
    dlg.transient(parent)
    i18n.register(dlg, "LabSwayChainDialogTitle", lambda w, t: w.title(t))
    window_pos.apply_offset_position(dlg, parent)

    hint = tk.Label(dlg, text=i18n.S("LabSwayChainHint"), wraplength=536,
                     justify="left", anchor="w")
    hint.pack(fill="x", padx=8, pady=(8, 0))
    i18n.register(hint, "LabSwayChainHint")

    # dev#1551(安全域WP、issue #1551「安全域」欄、2026-08-18オーナー最終
    # 裁定「GUIに案内文」): 「先端の動きがおかしい揺れものは、安全域を
    # 増やしてください」の案内。
    safety_margin_hint = tk.Label(
        dlg, text=i18n.S("LabSwayChainSafetyMarginHint"), wraplength=536,
        justify="left", anchor="w", fg="#555555")
    safety_margin_hint.pack(fill="x", padx=8, pady=(2, 0))
    i18n.register(safety_margin_hint, "LabSwayChainSafetyMarginHint")

    if ctx.sample_mode:
        sample_notice = tk.Label(dlg, text=i18n.S("LabSwayChainSampleModeNotice"),
                                  fg="#a06000", wraplength=536, justify="left")
        sample_notice.pack(fill="x", padx=8, pady=(4, 0))
        i18n.register(sample_notice, "LabSwayChainSampleModeNotice")

    if ctx.sample_mode:
        catalog_chains = [dict(c) for c in SAMPLE_CHAINS]
        catalog_ok, catalog_detail = True, "sample data (--sample)"
    else:
        result = query_sway_catalog(ctx.app_root, ctx.work_root, ctx.avatar_path)
        catalog_chains = result.get("chains") or []
        catalog_ok, catalog_detail = bool(result.get("ok")), result.get("detail", "")
    ctx.append_log(
        f"[lab][sway_chains] catalog query: ok={catalog_ok} "
        f"sample={ctx.sample_mode} detail={catalog_detail} chains={len(catalog_chains)}"
    )

    saved_overrides = load_config(ctx.app_root, ctx.avatar_path)
    working: List[Dict[str, Any]] = _merge_working_set(catalog_chains, saved_overrides)

    if not catalog_chains and not ctx.sample_mode:
        empty_notice = tk.Label(dlg, text=i18n.S("LabSwayChainEmptyStateNotice"),
                                 fg="#555555", wraplength=536, justify="left")
        empty_notice.pack(fill="x", padx=8, pady=(4, 0))
        i18n.register(empty_notice, "LabSwayChainEmptyStateNotice")

    # 修正イテレーション2(オーナーUX評価#6「節数」列削除、#5「チェーン名」→
    # 「ボーン名」): 列は on/名前/かたさ/(削除ボタン用の空列)の4本になった。
    # node_countは内部データとしては引き続き保持する(working辞書のキーは
    # そのまま、表示列だけを削る。ヘッダーの列インデックスがcol2以降1つずつ
    # 詰まる点に注意)。
    #
    # 修正イテレーション2(オーナーUX評価#4、言語切替追従漏れ): このヘッダー
    # 行の3ラベル(on/名前/かたさ)は前バージョンでi18n.register()し忘れており、
    # ダイアログを開いたまま言語切替しても文言が更新されなかった(オーナー
    # 実機評価で発見)。他画面(mesh_delete_dialog.py等)と同じ「作った直後に
    # i18n.register()する」流儀へ揃える。
    header = tk.Frame(dlg)
    header.pack(fill="x", padx=8, pady=(8, 0))
    col_on = tk.Label(header, text=i18n.S("LabSwayChainColOn"), width=4)
    col_on.grid(row=0, column=0)
    i18n.register(col_on, "LabSwayChainColOn")
    col_name = tk.Label(header, text=i18n.S("LabSwayChainColName"), width=20, anchor="w")
    col_name.grid(row=0, column=1, sticky="w")
    i18n.register(col_name, "LabSwayChainColName")
    col_hardness = tk.Label(header, text=i18n.S("LabSwayChainColHardness"), width=14)
    col_hardness.grid(row=0, column=2)
    i18n.register(col_hardness, "LabSwayChainColHardness")
    # dev#1551(安全域WP): 新列「安全域」(col3)。削除ボタン用の空プレース
    # ホルダーはcol4へ1つ後ろへずれる。
    col_safety_margin = tk.Label(
        header, text=i18n.S("LabSwayChainColSafetyMargin"), width=8)
    col_safety_margin.grid(row=0, column=3)
    i18n.register(col_safety_margin, "LabSwayChainColSafetyMargin")
    tk.Label(header, text="", width=6).grid(row=0, column=4)

    list_frame = tk.Frame(dlg)
    list_frame.pack(fill="both", expand=True, padx=8, pady=(4, 0))
    canvas = tk.Canvas(list_frame, highlightthickness=0, height=220)
    scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
    rows_frame = tk.Frame(canvas)
    rows_frame.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=rows_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    def _on_mousewheel(event: "tk.Event") -> str:
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    # dev#1435(致命寄り改善、オーナー実機報告「ボーン名・チェックボックス等
    # の項目にマウスオン中、ホイールスクロールが効かない」): tkinterの
    # <MouseWheel>はイベント発生時にポインタ直下のウィジェットへ配送される
    # だけで、親(row/canvas)には自動で伝播しない。旧実装はcanvas/rows_frame
    # (背景の隙間)にしかbindしておらず、行の中身(チェックボックス・名前・
    # かたさコンボボックス自体)の上にポインタがあるとイベントがそこで
    # 止まっていた。
    # 対処は「ダイアログ存在中のbind_all」ではなく、各行の実ウィジェットへ
    # 個別にbindする方式を選んだ(BRIEF記載の2案のうち後者)。理由:
    # bind_allはプロセス全体(他の開いているダイアログ含む)に影響し、
    # 破棄時の解除漏れリスクがある。個別bindなら影響範囲がこのダイアログの
    # ウィジェットに閉じる。
    # 副次効果の確認: ttk.Comboboxはbindtagsが(インスタンス, 'TCombobox'
    # クラス, トップレベル, 'all')の順で、'TCombobox'クラス側に既定の
    # <MouseWheel>ハンドラ(選択値をホイールで送り出す動作)が登録されている
    # (実測確認済み)。インスタンスレベルのbindはクラスレベルより先に評価
    # されるため、_on_mousewheelが"break"を返すことで、このダイアログの
    # コンボボックス上でホイールを回しても値が意図せず変わる副作用も同時に
    # 防げる(test_sway_chain_dialog_wheel_scroll_dev1435.py参照)。
    canvas.bind("<MouseWheel>", _on_mousewheel)
    rows_frame.bind("<MouseWheel>", _on_mousewheel)

    # 修正イテレーション2(オーナーUX評価#4、言語切替追従漏れ): 前バージョンは
    # hardness_displayをダイアログ構築時に1回だけ計算しており、開いたまま
    # 言語切替すると①行の見出しは新言語なのにコンボボックスの選択肢だけ旧言語の
    # まま、②選択中テキストも旧言語のまま、という不整合が起きた(オーナー実機
    # 評価で発見)。`_current_hardness_display()`で毎回引き直す関数へ変える。
    def _current_hardness_display() -> List[str]:
        return [i18n.S(_HARDNESS_KEYS[h]) for h in HARDNESS_CHOICES]

    def _hardness_index(value: str) -> int:
        return HARDNESS_CHOICES.index(value) if value in HARDNESS_CHOICES else 0

    # dev#1437(致命、オーナー実機報告「OK/×どちらでも閉じるまで非常に長い」):
    # 実測(work\wp_labdlg_fix\NOTES.md参照)で原因はsave_config自体(数ms)
    # ではなく、tkinterの生destroy呼び出しそのもの(1ウィジェット=1回の
    # Tclラウンドトリップ)がチェーン数に比例して積み上がることだと判明した
    # (cProfileで1回のdlg.destroy()中のTcl呼び出し回数が支配的コストだと
    # 確認済み)。行あたりの実ウィジェット数を旧実装の5個(行用Frame+
    # チェックボックス+名前Label+かたさCombobox+削除ボタン or 空Label)
    # から2〜3個(チェックボックス自体にnameを持たせて名前Labelを統合、
    # 行用Frameを廃止してrows_frameへ直接grid、削除ボタンは手動行にのみ
    # 生成し非手動行では何も置かない)へ削減し、行数に比例するTcl呼び出し
    # 総数を約4〜6割削減する。チェックボックスへ名前を持たせる形は
    # mesh_delete_dialog.pyの既存パターンと同じ(cb = tk.Checkbutton(...,
    # text=name, ...))。
    def _rebuild_rows() -> None:
        hardness_display = _current_hardness_display()
        for child in rows_frame.winfo_children():
            child.destroy()
        # dev#1470: 始点ボーン名の重複検出(手動行は始点=末端が常に単独
        # 要素で他行と衝突しないため対象外)。カタログ由来行のみで数える。
        anchor_counts = Counter(
            e["bones"][0] for e in working if not e["manual"]
        )
        for idx, entry in enumerate(working):
            enabled_var = tk.BooleanVar(value=entry["enabled"])

            def _on_toggle(i=idx, var=enabled_var) -> None:
                working[i]["enabled"] = var.get()

            name = _display_name(entry, anchor_counts) + (
                f" ({i18n.S('LabSwayChainManualTag')})" if entry["manual"] else "")
            # on列+名前列を1個のCheckbutton(text=name)に統合(dev#1437、
            # 上の設計コメント参照)。見出しは「on」「名前」2本のままなので
            # columnspan=2でその下に収める。
            cb = tk.Checkbutton(
                rows_frame, text=name, variable=enabled_var, command=_on_toggle,
                anchor="w", width=26,
            )
            cb.grid(row=idx, column=0, columnspan=2, sticky="w", pady=1)
            cb.bind("<MouseWheel>", _on_mousewheel)  # dev#1435
            # 修正イテレーション2(オーナーUX評価#6): 「節数」列をテーブルから
            # 削除(entry["node_count"]自体は内部データとして引き続き保持し、
            # working辞書には残す。表示しないだけ)。

            hardness_var = tk.StringVar(value=hardness_display[_hardness_index(entry["hardness"])])
            # 修正イテレーション1(オーナーUX評価#2、work\rd_19_flight\briefs\
            # uimock2_fixes.md): tk.OptionMenuは未テーマの旧Tk外観(平らな
            # ボタン+三角ではない謎の棒状インジケータ)で描画され、他の
            # ttk部品と見た目が揃わず「表示がおかしい」に見えることを実機
            # 起動確認(WSB内スクリーンショット、ttk.Comboboxとの並置比較)で
            # 特定した。ttk.Comboboxへ置き換える(readonly、textvariableは
            # 既存のhardness_varをそのまま使い回せるため、下のtrace_add側は
            # 無改修で動く)。
            hb = ttk.Combobox(
                rows_frame, state="readonly", textvariable=hardness_var,
                values=hardness_display, width=10,
            )
            hb.grid(row=idx, column=2, padx=4, pady=1)
            hb.bind("<MouseWheel>", _on_mousewheel)  # dev#1435("break"で
            # ttk既定のホイール選択送りも同時に抑止する、上の設計コメント参照)

            def _on_hardness_change(*_a, i=idx, var=hardness_var, disp=hardness_display) -> None:
                try:
                    pos = disp.index(var.get())
                except ValueError:
                    pos = 0
                working[i]["hardness"] = HARDNESS_CHOICES[pos]

            hardness_var.trace_add("write", _on_hardness_change)

            # dev#1551(安全域WP、issue #1551「安全域」欄): ドナーボーンを
            # 先端から何本削るか(0..MAX_SAFETY_MARGIN、既定1)。
            # ttk.Spinboxはtextvariable+コマンド無しでも矢印/直接入力の
            # 両方が使える(mesh_delete_dialog.py等に前例が無い新規部品
            # だが、hardnessと同じttk系に揃えている)。
            safety_margin_var = tk.IntVar(value=entry.get("safety_margin", DEFAULT_SAFETY_MARGIN))
            sb = ttk.Spinbox(
                rows_frame, from_=0, to=MAX_SAFETY_MARGIN, width=3,
                textvariable=safety_margin_var, justify="center",
            )
            sb.grid(row=idx, column=3, padx=4, pady=1)
            sb.bind("<MouseWheel>", _on_mousewheel)  # dev#1435と同じ理由

            def _on_safety_margin_change(*_a, i=idx, var=safety_margin_var) -> None:
                try:
                    value = int(var.get())
                except (tk.TclError, ValueError):
                    return  # 入力途中の空文字/不正値は無視(OK時にconfirmする設計は
                    # 採らない——ttk.Spinboxのfrom_/toが範囲を機械的に制約するため)
                working[i]["safety_margin"] = max(0, min(MAX_SAFETY_MARGIN, value))

            safety_margin_var.trace_add("write", _on_safety_margin_change)

            if entry["manual"]:
                def _on_delete(i=idx) -> None:
                    del working[i]
                    _rebuild_rows()

                del_btn = tk.Button(
                    rows_frame, text=i18n.S("BtnRemoveManualChain"), command=_on_delete,
                    width=6,
                )
                del_btn.grid(row=idx, column=4, padx=4, pady=1)
                del_btn.bind("<MouseWheel>", _on_mousewheel)  # dev#1435
            # 非手動行はdev#1437の削減対象そのもの: 旧実装は空のtk.Label
            # (幅6文字分のプレースホルダ)をここに置いていたが、削除ボタンが
            # 無い行ではセル自体を空にしても列幅はcolumn 4内の他行の
            # ボタン幅で決まるため見た目は変わらない(ウィジェット1個/行を
            # 丸ごと省略できる)。

    _rebuild_rows()

    # ---- 手動追加 ----
    manual = tk.LabelFrame(dlg, text=i18n.S("LabSwayChainManualLabel"), padx=6, pady=6)
    manual.pack(fill="x", padx=8, pady=(8, 0))
    i18n.register(manual, "LabSwayChainManualLabel", lambda w, t: w.config(text=t))

    manual_name_label = tk.Label(manual, text=i18n.S("LabSwayChainManualNameLabel"))
    manual_name_label.grid(row=0, column=0, sticky="w")
    i18n.register(manual_name_label, "LabSwayChainManualNameLabel")
    manual_name_var = tk.StringVar()
    tk.Entry(manual, textvariable=manual_name_var, width=20).grid(
        row=0, column=1, sticky="w", padx=4)

    manual_hardness_label = tk.Label(manual, text=i18n.S("LabSwayChainManualHardnessLabel"))
    manual_hardness_label.grid(row=0, column=2, sticky="w")
    i18n.register(manual_hardness_label, "LabSwayChainManualHardnessLabel")
    manual_hardness_var = tk.StringVar(value=_current_hardness_display()[0])
    # 修正イテレーション1(オーナーUX評価#2): 上のリスト行と同じ理由で
    # tk.OptionMenu→ttk.Comboboxへ統一。
    manual_hardness_combo = ttk.Combobox(
        manual, state="readonly", textvariable=manual_hardness_var,
        values=_current_hardness_display(), width=10,
    )
    manual_hardness_combo.grid(row=0, column=3, sticky="w", padx=4)

    # 修正イテレーション2(オーナーUX評価#4): 手動追加行のコンボボックスは
    # rows_frame配下ではなく`manual`直下に固定で1つだけ存在し、_rebuild_rows()
    # では再生成されないため、単独で言語切替に追従させる専用の再描画関数を
    # 持たせる(選択中位置=かたさの種類は保ったまま、表示文言だけ新言語へ
    # 差し替える)。
    def _refresh_manual_hardness_choices(_widget: tk.Misc, _text: str) -> None:
        old_display = list(manual_hardness_combo.cget("values"))
        try:
            pos = old_display.index(manual_hardness_var.get())
        except ValueError:
            pos = 0
        new_display = _current_hardness_display()
        manual_hardness_combo.config(values=new_display)
        manual_hardness_var.set(new_display[pos] if 0 <= pos < len(new_display) else new_display[0])

    # キー自体は何でもよい(setterが引数を使わず独自ロジックで動くダミー登録、
    # main_window.pyのswayIntensityValueLabelと同じ相乗りパターン)。
    # ヘッダーの「かたさ」列と同じ意味の文言に揃える。
    i18n.register(
        manual_hardness_combo, "LabSwayChainColHardness", _refresh_manual_hardness_choices
    )

    # 修正イテレーション2(オーナーUX評価#4): 一覧テーブルの各行(ボーン名の
    # 「(手動)」タグ・かたさコンボボックスの選択肢と選択中テキスト)は
    # _rebuild_rows()を呼び直すだけで新言語に揃う(rebuild内でi18n.S()を
    # 都度引き直す設計のため)。ダイアログを開いたまま言語切替されたとき、
    # この再描画そのものを起動するトリガーが無かったのが実機評価#4の実体
    # ("dev_sample_sway"入りWSB確認で確認: ヘッダー/コンボボックス選択肢/
    # 手動追加欄が言語切替後も旧言語のまま残っていた)。同じダミー登録
    # パターンでrows_frameを紐付け、apply_language()のたび再描画させる。
    i18n.register(rows_frame, "LabSwayChainColName", lambda _w, _t: _rebuild_rows())

    def _on_manual_add() -> None:
        name = manual_name_var.get().strip()
        if not name:
            return
        try:
            pos = list(manual_hardness_combo.cget("values")).index(manual_hardness_var.get())
        except ValueError:
            pos = 0
        working.append({
            "anchor": None, "bones": [name], "node_count": 1,
            "enabled": True, "hardness": HARDNESS_CHOICES[pos], "manual": True,
            # dev#1551(安全域WP): 手動追加行はボーン1本(anchorのみ、子が
            # 無いchain)なので安全域は構造的に無効(target_len_with_safety_
            # margin()のn_ext<=1分岐、常に1のまま)——UIには専用の入力を
            # 設けず、一覧行のスピンボックス(既定値のまま、無害)に任せる。
            "safety_margin": DEFAULT_SAFETY_MARGIN,
        })
        manual_name_var.set("")
        _rebuild_rows()

    add_btn = tk.Button(manual, text=i18n.S("BtnSwayChainManualAdd"), command=_on_manual_add)
    add_btn.grid(row=0, column=4, padx=4)
    i18n.register(add_btn, "BtnSwayChainManualAdd")

    # ---- 下部ボタン ----
    bottom = tk.Frame(dlg)
    bottom.pack(fill="x", padx=8, pady=8, side="bottom")

    # dev#1436(改善要望、オーナー実機評価): 「全てON」「全てOFF」ボタン。
    # working全件のenabledを一括で書き換えて_rebuild_rows()し直すだけ
    # (_on_reset/_on_manual_addと同じ「workingを直接編集→再描画」の
    # 既存パターンを踏襲。ストアへの保存はOKボタンを押すまで発生しない
    # ——他のボタンと同じ挙動)。
    def _on_select_all(enabled: bool) -> None:
        for entry in working:
            entry["enabled"] = enabled
        _rebuild_rows()
        ctx.append_log(
            f"[lab][sway_chains] {'select all' if enabled else 'deselect all'}: "
            f"{len(working)} row(s)")

    select_all_btn = tk.Button(
        bottom, text=i18n.S("BtnLabSwayChainSelectAll"),
        command=lambda: _on_select_all(True))
    select_all_btn.pack(side="left")
    i18n.register(select_all_btn, "BtnLabSwayChainSelectAll")

    select_none_btn = tk.Button(
        bottom, text=i18n.S("BtnLabSwayChainSelectNone"),
        command=lambda: _on_select_all(False))
    select_none_btn.pack(side="left", padx=(4, 0))
    i18n.register(select_none_btn, "BtnLabSwayChainSelectNone")

    def _on_reset() -> None:
        clear_avatar(ctx.app_root, ctx.avatar_path)
        working[:] = _merge_working_set(catalog_chains, [])
        _rebuild_rows()
        ctx.append_log("[lab][sway_chains] reset to defaults for current avatar")

    reset_btn = tk.Button(bottom, text=i18n.S("BtnLabSwayChainReset"), command=_on_reset)
    reset_btn.pack(side="left", padx=(12, 0))
    i18n.register(reset_btn, "BtnLabSwayChainReset")

    def _on_ok() -> None:
        save_config(ctx.app_root, ctx.avatar_path, working)
        ctx.append_log(
            f"[lab][sway_chains] selection saved: {len(working)} row(s) in working set")
        dlg.destroy()

    ok_btn = tk.Button(bottom, text=i18n.S("BtnOk"), command=_on_ok)
    ok_btn.pack(side="right")
    i18n.register(ok_btn, "BtnOk")
    cancel_btn = tk.Button(bottom, text=i18n.S("BtnCancel"), command=dlg.destroy)
    cancel_btn.pack(side="right", padx=(0, 4))
    i18n.register(cancel_btn, "BtnCancel")

    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    return dlg


# ---------------------------------------------------------------------------
# dev#1186 ラボ機能レジストリ記述子(lab_window.py側が結線する)。
# ---------------------------------------------------------------------------

LAB_REGISTRY_DESCRIPTOR = {
    "id": LAB_FEATURE_ID,
    "name_key": "LabFeatureSwayChains",
    "state_summary": state_summary,
    "open_dialog": show_sway_chain_dialog,
    "reset": reset,
}
