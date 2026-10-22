# sway_style_dialog.py -- ラボ「ゆれかた」統合パネル(SPEC.md §2、
# .devonly\docs\sway\sway_wrapup\SPEC.md、WP wp_sway_panel、2026-08-16。レイアウト・操作性
# 改修: WP wp_sway_panel_layout、2026-08-16 オーナーHumanTest実試遊)。
#
# 旧2ダイアログ(sway_chain_dialog.py「揺れもの詳細設定」+
# lab_raw_sway_params_dialog.py「生パラメータ調整」)を1つに統合する。
# データ永続化は sway_styles_store.py(tkinter非依存、本改修でもスキーマ・
# 保存ロジックは一切変更していない)。
#
# 画面構成:
#   1. 「ゆれかた一覧」: 組み込み3種(やわらかめ/ふつう/かため、読み取り
#      専用)+「なし」+カスタム(個数上限なし、2026-08-16オーナー裁定で
#      撤廃)。クリックで選ぶと同時に「筆」として持つ(下記スポイト&
#      ペースト方式)。新規作成/改名/複製/削除、10パラメータのスライダー
#      編集(カスタム選択時のみ編集可)。
#   2. 「揺れもの一覧」: 既存sway_chain_dialogの鎖テーブルを母体に、行を
#      クリックすると、上段で持っている「筆」のゆれかたがその行に塗られる
#      (2026-08-16 オーナーUI変更指示: 行ごとのドロップダウンは廃止し、
#      app_py\\ui\\multi_avatar_pak_dialog.py の「ペンキ方式」[右ペインで
#      選択→左ペインをクリックで塗る]と同じ操作感に統一。本ダイアログは
#      左右ペインではなく上下セクションだが、「クリックで選択=筆を持つ」
#      「クリックで対象に適用=塗る」「選択中は relief=sunken で強調」
#      「対象の表示は "元の名前 -> 塗った値" 形式」という核となる操作感・
#      ウィジェット構成・文言の型はそのまま踏襲する――実装者解釈、
#      REPORT.md記載)。「全てに塗る」ボタン+消費表示「スロット: n/9」
#      (同時に効かせられる親骨×ゆれかたの組数上限、9のまま不変)。
#
# **レイアウト規約**(2026-08-16オーナーHumanTest実試遊フィードバック、
# WP wp_sway_panel_layout): 既定ウィンドウサイズでも下部ボタン列(手動追加・
# 既定値リセット・キャンセル・OK)や「ゆれかた一覧」の名前入力欄が隠れて
# 操作不能になる不具合があった(原因: tkinterのpackジオメトリマネージャは
# 「先にpack()した子がcavityの優先権を持つ」ため、fill=both,expand=Trueな
# 一覧セクションを他の固定要素より先にpackすると、一覧側が余白を先取りして
# しまい、ウィンドウの自然高さが実コンテンツの高さに満たない場合に後から
# packした固定要素[ボタン列・名前入力欄]が押し出されて見えなくなる)。
#
# 修正した構造(ダイアログ全体・各セクション内の両方に同じ原則を適用):
#   - 「常に見えていてほしい固定要素」は、伸縮する一覧領域より**先**に
#     pack(側="bottom"または単に先にpackする)する。
#   - ダイアログ全体: `bottom`(下部ボタン)を他の何よりも先にpack。
#   - 「ゆれかた一覧」セクション内: 名前入力欄・作成/改名/複製/削除ボタン・
#     エラー表示(`crud_area`)を、スクロールする一覧領域(`styles_body`)より
#     **先**にside="bottom"でpack。
#   - 「揺れもの一覧」セクション内: スロット表示・「全てに塗る」・手動追加
#     (`footer_area`)を、スクロールする行一覧(`rows_pane`)より**先**に
#     side="bottom"でpack。
#   - 両セクションとも、伸縮する一覧領域自体は独立したCanvas+Scrollbarの
#     スクロール領域を持つ(`_make_scroll_region()`)。
#   - `dlg.minsize()` で全要素の最低限の操作が成立する寸法を設定。
#
# カタログ取得(query_sway_catalog)・sample_modeは
# ui.sway_chain_dialog(既存、書き込み禁止)の関数をそのまま読み取り専用で
# 再利用する(重複実装によるロジック分岐を避けるため)。
#
# **2026-08-16 WP wp_w2c_pbunit(dev#1508 列車計画W2c、SPEC.md §2「一覧の行
# 単位=PB/SBコンポーネント単位」裁定)で改修**: 「揺れもの一覧」の行を、
# 旧「1房=1行」から「1PB/SBコンポーネント=1行」へ変更する。表示・割当は
# ui.sway_pb_catalog(新規、上記import参照)のPB単位カタログ
# (query_sway_pb_units()/sample_pb_units())を使う。**ストアのスキーマは
# 変更しない**(sway_styles_store.py・sway_styles_store.load_state_with_
# migration()は書き込み禁止のまま、鎖単位[bones配列]のスキーマを継続前提
# とする)——OK押下時は行(=PB)の選択を配下の全房へfan-out書き込みする
# (.devonly\\docs\\sway\\sway_pbunit_design\\DESIGN.md §5段1)。同じ理由で、マイグレーション
# 専用の`catalog_chains`(鎖単位フラットリスト)は引き続き
# `_legacy_chain_dialog.query_sway_catalog()`で取得し、表示用の
# `catalog_units`(PB単位)とは別に保持する二本立てとなる。
#
# 追加した「特殊ボーンを強制セットアップ」ボタン(2026-08-16オーナー口述
# 指定): 偏向判定で既定除外されるPB行それぞれに、そのPB実値から自動生成
# したカスタム「ゆれかた」を割り当てる。偏向判定は
# pipeline\\py\\sway_allocator.py の判定規則をそのまま再利用する
# (ui.sway_pb_catalog.is_unit_biased()経由、重複実装しない)。
#
# **2026-08-18 WP wp/1551-gui-safety-margin(dev#1551安全域WP、issue #1551
# 「安全域」欄、2026-08-18オーナー最終裁定)で追加**: 「揺れもの一覧」の各行
# へ「安全域」(ドナーボーンを先端から何本削るか、既定1、0-9)のスピンボックス
# を追加した。PR #1570で搬送路自体(sway_chain_override_store.py の
# safety_marginフィールド→pipeline_runner.py→
# pipeline\\blender\\step02_retarget.py)は実装済みだったが、GUI側の配線先が
# 旧ダイアログ(ui.sway_chain_dialog、dev#1508で本パネルに置き換わり現GUIから
# 到達不能)のままだった不具合を修理する。**ストアは鎖単位のsway_chain_
# override_store.pyのまま変更しない**(本パネルが管理するsway_styles_store
# とは別ストア。両ストアともbones配列[anchor,node1,...]をキーにしており、
# ui.sway_pb_catalog.unit_bones_keys()で同じ規約に変換できるため、行(=PB
# 単位)からのfan-out書き込みは既存のfanout_unit_assignments()と同型で書ける)。
# hardnessフィールドは本パネルの管理対象外のまま(現行GUIにその概念は無く、
# 「style」に統合済み)——読込時の値をそのまま引き継ぐだけに留める
# (_on_ok()参照)。
#
# **2026-08-19 WP wp/1572-chain-settings-wiring(dev#1572第3便、issue #1572
# 追記「チェインの揺れ設定問題1・2」)で改訂**: 上記「enabledフィールドは
# 本パネルの管理対象外」は本WPで終了する。「揺れもの一覧」の各行へ実際の
# ON/OFFチェックボックスを追加し(旧行ボタンの「筆で塗る」動作とは別軸、
# `_on_paint_row()`のコメント「第3便で実際のenabled切り替えとして配線
# される想定」参照)、sway_chain_override_store.pyのenabledフィールドを
# 本パネルが直接読み書きする。既定enabled(偏向判定込み)は
# `pipeline\\py\\sway_chain_defaults.is_default_enabled()`(パイプライン
# `pipeline\\blender\\step02_retarget.py::_lab_assignments_from_job()`と
# 同一の共有関数)で計算する——旧`sway_identify.default_sway_enabled()`
# (名前ベース)はもう使わない。
from __future__ import annotations

import os
import sys
import tkinter as tk
from collections import Counter
from tkinter import messagebox, ttk
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)
_ROOT_DIR = os.path.dirname(_APP_PY_DIR)
_PIPELINE_PY_DIR = os.path.join(_ROOT_DIR, "pipeline", "py")
if _PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_PY_DIR)

import i18n  # noqa: E402
import sway_chain_defaults  # noqa: E402  (dev#1572第3便、issue #1572追記
# 「チェインの揺れ設定問題1・2」: 既定enabled判定の唯一の共有関数。
# pipeline\\blender\\step02_retarget.py::_lab_assignments_from_job()と
# 同一関数を呼ぶ――旧sway_identify.default_sway_enabled()[名前ベース、
# 偏向を見ない]は本パネルの既定enabled判定にはもう使わない。本パネルは
# 「enabled」フィールドを実際に管理する側になった[下記_on_ok()/
# _resolve_unit_enabled()参照、旧コメント「enabled/hardnessフィールドは
# 本パネルの管理対象外」は本WPで終了]。
from ui import window_pos  # noqa: E402
from ui import sway_chain_dialog as _legacy_chain_dialog  # noqa: E402  (読み取り
# 専用の再利用: query_sway_catalog()(sway_styles_store.load_state_with_migration()
# が要求する鎖単位[bones配列]のcatalog_chainsを組み立てるためだけに使う――
# 同ストアは書き込み禁止対象のためスキーマを変更できない)。
# ui\\sway_chain_dialog.py は書き込み禁止だが、importして関数を呼ぶことは
# 許容される――WP指示書「既存2ダイアログ...は書き込み禁止」は編集の禁止で
# あり、読み取り専用の再利用まで禁じるものではない[BRIEF/lab-devスキルは
# むしろ「既存sway_chain_dialogの鎖テーブルを母体に」と明記している])。
from ui import sway_pb_catalog  # noqa: E402  (dev#1508 列車計画W2c、新規表示
# ヘルパ: 1PB/SB=1行のPB単位カタログ・GUID尾削り・fan-out書き込み・
# 「特殊ボーンを強制セットアップ」の値生成。.devonly\\docs\\sway\\sway_pbunit_design\\DESIGN.md
# §4-5参照)

import sway_styles_store as _store  # noqa: E402
import sway_chain_override_store as _chain_store  # noqa: E402  (dev#1551安全域WP:
# 鎖単位の安全域ストア。上記モジュールdocstring「2026-08-18 WP
# wp/1551-gui-safety-margin」参照。sway_styles_storeとは独立したストアで、
# スキーマは変更しない)

LAB_FEATURE_ID = _store.LAB_FEATURE_ID
STYLE_PARAM_KEYS = _store.STYLE_PARAM_KEYS
PARAM_RANGES = _store.PARAM_RANGES
BUILTIN_STYLE_NAMES = _store.BUILTIN_STYLE_NAMES
BUILTIN_STYLE_PARAMS = _store.BUILTIN_STYLE_PARAMS
NONE_STYLE = _store.NONE_STYLE
RESERVED_STYLE_NAMES = _store.RESERVED_STYLE_NAMES
DEFAULT_SAFETY_MARGIN = _chain_store.DEFAULT_SAFETY_MARGIN
MAX_SAFETY_MARGIN = _chain_store.MAX_SAFETY_MARGIN
MAX_SLOTS = 9  # 同時に効かせられるスロット数(親骨×ゆれかた)の上限。カスタム
# 「ゆれかた」定義自体の個数上限は無い(2026-08-16オーナー裁定で撤廃)。

# dev#1572(2026-08-19、第2便PR#1584の過修正の是正、本WP): 「ゆれかた」
# 編集UI(ゆれかた一覧ピッカー・CRUD・生パラメータスライダー・「筆」機構・
# 鎖ごとのスタイル表示・スロット数)を画面から隠すフラグ。コード・ロジック
# 自体は削除しない(ラボ憲章②「雑な実装でよい」の範囲で、将来の再設計
# [dev#1572ロードマップ第3便「チェインの揺れ設定問題」]に備えて温存する)。
# モジュールレベル定数にしてあるのは、既存の回帰テスト
# (test_sway_style_dialog_wp_sway_panel.py・test_sway_style_dialog_pbunit_
# wp_w2c.py)がこのロジック自体の正しさを引き続き検証できるよう、テスト側
# から`dlg_mod._SWAY_STYLE_PICKER_VISIBLE = True`で一時的に上書きできる
# ようにするため(show_sway_style_dialog()内でこの名前へ代入はしないので、
# 関数内の`if _SWAY_STYLE_PICKER_VISIBLE:`はPythonの通常の名前解決で
# このモジュール変数を読みに行く)。製品として実際にGUIへ出るときの値は
# 常にFalse(このモジュール変数の既定値)。
_SWAY_STYLE_PICKER_VISIBLE = False

reset = _store.reset
is_active = _store.is_active
state_summary = _store.state_summary

_ZERO_PARAMS: Dict[str, float] = {k: 0.0 for k in STYLE_PARAM_KEYS}

_PARAM_LABEL_KEYS: Dict[str, str] = {
    "stiffness": "LabRawSwayParamsParamStiffness",
    "damping": "LabRawSwayParamsParamDamping",
    "wdl": "LabSwayStyleParamWdl",
    "wdr": "LabSwayStyleParamWdr",
    "gravity_z": "LabRawSwayParamsParamGravityZ",
    "limit_angle": "LabRawSwayParamsParamLimitAngle",
    "fake_pitch": "LabSwayStyleParamPitch",
    "fake_roll": "LabSwayStyleParamRoll",
    "fake_yaw": "LabSwayStyleParamYaw",
}

_BUILTIN_DISPLAY_KEYS: Dict[str, str] = {
    "soft": "SwayIntensitySoft", "normal": "SwayIntensityNormal", "hard": "SwayIntensityHard",
}

# ペンキ方式の配色(app_py\\multi_avatar_pak_store.py AVATAR_COLOR_PALETTEと
# 同じ値――「筆」の色分けという同種のUIパターンなので、視覚的な一貫性の
# ためパレット自体を踏襲する。本ストアは無関係な機能[マルチアバターPAK]の
# モジュールなので値だけを複製し、import はしない[層分離を保つため])。
_STYLE_COLOR_PALETTE: List[str] = [
    "#ffd699", "#a3d9a5", "#a3c9f7", "#f7a3c9", "#d9a3f7",
    "#f7e2a3", "#a3f7e2", "#f7a3a3", "#c9a3f7", "#c9f7a3",
]
_NONE_STYLE_COLOR = "#f0f0f0"


def _style_display_label(name: Optional[str]) -> str:
    if name is None or name == NONE_STYLE:
        return i18n.S("SwayIntensityNone")
    key = _BUILTIN_DISPLAY_KEYS.get(name)
    if key:
        return i18n.S(key)
    return name


def _style_color_map(names: List[str]) -> Dict[str, str]:
    """multi_avatar_pak_store.avatar_color_map()と同型の純粋関数(名前の列→
    色の対応、同名は先着優先)。"none"は常に_NONE_STYLE_COLOR固定
    (パレット消費しない)。"""
    colors: Dict[str, str] = {}
    palette_idx = 0
    for name in names:
        if name in colors:
            continue
        if name == NONE_STYLE:
            colors[name] = _NONE_STYLE_COLOR
            continue
        colors[name] = _STYLE_COLOR_PALETTE[palette_idx % len(_STYLE_COLOR_PALETTE)]
        palette_idx += 1
    return colors


def _make_scroll_region(parent: tk.Misc) -> Tuple[tk.Frame, tk.Canvas, tk.Frame, Callable]:
    """`parent`いっぱいに広がるCanvas+Scrollbarを作り、その中に配置する
    実際のコンテナ(戻り値3つ目、以後の子ウィジェットの親として使う)を
    返す。戻り値: (outer_frame, canvas, inner_body, on_mousewheel)。
    outer_frameを`pack(fill="both", expand=True)`で配置してから使う想定
    (mesh_delete_dialog.py/multi_avatar_pak_dialog.py._make_scroll_area()
    と同型のcanvas+scrollbarパターン、本ダイアログでは2箇所[ゆれかた
    ピッカー・揺れもの行一覧]で使うため関数化した。on_mousewheelは
    呼び出し側が個々の子ウィジェットへも個別bindするためのもの
    ――dev#1435の「個別bind、bind_allは使わない」方針を踏襲)。"""
    outer_frame = tk.Frame(parent)
    canvas = tk.Canvas(outer_frame, highlightthickness=0)
    scrollbar = tk.Scrollbar(outer_frame, orient="vertical", command=canvas.yview)
    inner_body = tk.Frame(canvas)
    inner_body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner_body, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    def _on_mousewheel(event: "tk.Event") -> str:
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    canvas.bind("<MouseWheel>", _on_mousewheel)
    inner_body.bind("<MouseWheel>", _on_mousewheel)
    return outer_frame, canvas, inner_body, _on_mousewheel


@dataclass
class SwayStyleContext:
    app_root: str
    work_root: str
    avatar_path: str
    sample_mode: bool = False
    append_log: Callable[[str], None] = field(default=lambda msg: None)


def show_sway_style_dialog(parent: tk.Misc, ctx: SwayStyleContext) -> tk.Toplevel:
    dlg = tk.Toplevel(parent)
    dlg.title(i18n.S("LabSwayStyleDialogTitle"))
    dlg.geometry("760x760")
    # レイアウト規約(上記モジュールdocstring参照): 全要素の最低限の操作が
    # 成立する寸法を下限とする(実測に基づく概算値)。
    dlg.minsize(680, 480)
    dlg.transient(parent)
    i18n.register(dlg, "LabSwayStyleDialogTitle", lambda w, t: w.title(t))
    window_pos.apply_offset_position(dlg, parent)

    # ---- 下部ボタン行(常時可視) ----
    # 他の何よりも先にpack(side="bottom")する(レイアウト規約、モジュール
    # docstring参照)。実ボタンはこの関数の末尾、working_rows/working_styles
    # 等のロジックが揃ってから追加する(packの優先順位は「いつpack()を
    # 呼んだか」で決まり「いつ子ウィジェットを追加したか」には依らない)。
    bottom = tk.Frame(dlg)
    bottom.pack(fill="x", padx=8, pady=8, side="bottom")

    hint = tk.Label(dlg, text=i18n.S("LabSwayStyleHint"), wraplength=736,
                     justify="left", anchor="w")
    hint.pack(fill="x", padx=8, pady=(8, 4))
    i18n.register(hint, "LabSwayStyleHint")

    # -- カタログ取得: 2本立て(モジュールdocstring上部「2026-08-16 WP
    #    wp_w2c_pbunit」参照)。--
    #    ①catalog_chains(鎖単位フラット、旧来どおり): マイグレーション専用
    #      入力(sway_styles_store.load_state_with_migration()、書き込み
    #      禁止対象のためスキーマを変えられない)。
    #    ②catalog_units(PB単位、新規): working_rows/表示用。
    if ctx.sample_mode:
        catalog_chains: List[Dict[str, Any]] = [
            dict(c) for c in _legacy_chain_dialog.SAMPLE_CHAINS
        ]
        catalog_units: List[Dict[str, Any]] = sway_pb_catalog.sample_pb_units()
        catalog_ok, catalog_detail = True, "sample data (--sample)"
    else:
        result = _legacy_chain_dialog.query_sway_catalog(
            ctx.app_root, ctx.work_root, ctx.avatar_path)
        catalog_chains = result.get("chains") or []
        catalog_ok, catalog_detail = bool(result.get("ok")), result.get("detail", "")
        units_result = sway_pb_catalog.query_sway_pb_units(
            ctx.app_root, ctx.work_root, ctx.avatar_path)
        catalog_units = units_result.get("units") or []
    ctx.append_log(
        f"[lab][sway_styles] catalog query: ok={catalog_ok} sample={ctx.sample_mode} "
        f"detail={catalog_detail} chains={len(catalog_chains)} units={len(catalog_units)}"
    )

    # dev#1572第3便(issue #1572追記「チェインの揺れ設定問題1・2」): 各PB/SB
    # ユニットの既定enabled(偏向判定込み)を、パイプライン側
    # (pipeline\\blender\\step02_retarget.py::_lab_assignments_from_job())と
    # 同一の共有関数`sway_chain_defaults.is_default_enabled()`で先に算出し、
    # bonesタプル(unit_bones_keys、房ごと)->boolの対応表を作る。ストアの
    # `_is_default_entry()`(ラボ憲章④の間引き判定)へこの表を渡すことで、
    # 名前ベースの旧既定(sway_identify.default_sway_enabled())との食い違い
    # (問題1の実体、モジュールdocstring参照)を保存/読込の両方で解消する。
    default_enabled_by_bones: Dict[Tuple[str, ...], bool] = {}
    for unit in catalog_units:
        unit_default = sway_chain_defaults.is_default_enabled(
            unit.get("type"), unit.get("params"))
        for key in sway_pb_catalog.unit_bones_keys(unit["anchor"], unit["chains"]):
            default_enabled_by_bones[key] = unit_default

    custom_styles_loaded, assignments_loaded = _store.load_state_with_migration(
        ctx.app_root, ctx.avatar_path, catalog_chains)

    # dev#1551(安全域WP): 鎖単位の安全域上書き(sway_chain_override_store、
    # style用ストアとは別)を読み込み、bonesタプル->safety_margin/元エントリ
    # の対応表を作る。読込専用(このダイアログはOKを押すまでディスクに一切
    # 書き込まない、既存の設計原則をそのまま踏襲)。
    # dev#1572第3便: default_enabled_by_bones(上記)を渡し、偏向判定ベースの
    # 真の既定でラボ憲章④の間引きを判定させる。
    chain_overrides_loaded = _chain_store.load_config(
        ctx.app_root, ctx.avatar_path, default_enabled_map=default_enabled_by_bones)
    safety_margin_by_bones: Dict[Tuple[str, ...], int] = {
        tuple(e["bones"]): e.get("safety_margin", DEFAULT_SAFETY_MARGIN)
        for e in chain_overrides_loaded
    }
    chain_override_by_bones: Dict[Tuple[str, ...], Dict[str, Any]] = {
        tuple(e["bones"]): e for e in chain_overrides_loaded
    }

    def _resolve_unit_safety_margin(
        anchor: Optional[str], chains: List[List[str]]
    ) -> Tuple[int, bool]:
        """1PBユニットの複数房ぶんの保存済み安全域から、行(PB単位)の値を
        1つ決める(sway_pb_catalog.resolve_unit_style()と同型: 先頭優先+
        差異ログ)。"""
        values = [
            safety_margin_by_bones[key]
            for key in sway_pb_catalog.unit_bones_keys(anchor, chains)
            if key in safety_margin_by_bones
        ]
        if not values:
            return DEFAULT_SAFETY_MARGIN, False
        first = values[0]
        return first, any(v != first for v in values)

    def _resolve_unit_enabled(
        anchor: Optional[str], chains: List[List[str]]
    ) -> Tuple[bool, bool]:
        """1PBユニットの複数房ぶんの保存済みenabledから、行(PB単位)の値を
        1つ決める(`_resolve_unit_safety_margin()`と同型: 先頭優先+
        差異ログ)。保存済みが無い房は、`default_enabled_by_bones`
        (偏向判定ベースの既定、上記)で埋める(dev#1572第3便)。"""
        keys = sway_pb_catalog.unit_bones_keys(anchor, chains)
        values = [
            bool(chain_override_by_bones[key]["enabled"])
            if key in chain_override_by_bones
            else default_enabled_by_bones.get(key, True)
            for key in keys
        ]
        if not values:
            return True, False
        first = values[0]
        return first, any(v != first for v in values)

    # working_styles: name(custom) -> 10キーparams dict(編集用の作業コピー)。
    working_styles: Dict[str, Dict[str, float]] = {
        name: dict(params) for name, params in custom_styles_loaded.items()
    }

    def _merge_working_rows() -> List[Dict[str, Any]]:
        """working_rows(PB単位、行=1PB/SB)を組み立てる。各行のstyleは、
        鎖単位で保存済みのassignments_loadedから
        ui.sway_pb_catalog.resolve_unit_style()で復元する(段1の核、
        モジュールdocstring上部参照)。safety_marginも同じ要領で
        chain_overrides_loadedから復元する(dev#1551)。enabledも同じ要領で
        復元する(dev#1572第3便、`_resolve_unit_enabled()`参照)。"""
        saved_by_bones = {tuple(a["bones"]): a["style"] for a in assignments_loaded}
        catalog_keys = set()
        rows: List[Dict[str, Any]] = []
        for unit in catalog_units:
            for key in sway_pb_catalog.unit_bones_keys(unit["anchor"], unit["chains"]):
                catalog_keys.add(key)
            style, conflict = sway_pb_catalog.resolve_unit_style(
                unit["anchor"], unit["chains"], saved_by_bones, NONE_STYLE)
            if conflict:
                ctx.append_log(
                    f"[lab][sway_styles] chain-level style conflict reconciled "
                    f"(first-wins): unit={unit['display_name']!r} anchor={unit['anchor']!r}"
                )
            margin, margin_conflict = _resolve_unit_safety_margin(
                unit["anchor"], unit["chains"])
            if margin_conflict:
                ctx.append_log(
                    f"[lab][sway_styles] chain-level safety_margin conflict reconciled "
                    f"(first-wins): unit={unit['display_name']!r} anchor={unit['anchor']!r}"
                )
            enabled, enabled_conflict = _resolve_unit_enabled(unit["anchor"], unit["chains"])
            if enabled_conflict:
                ctx.append_log(
                    f"[lab][sway_styles] chain-level enabled conflict reconciled "
                    f"(first-wins): unit={unit['display_name']!r} anchor={unit['anchor']!r}"
                )
            rows.append({
                "anchor": unit["anchor"], "chains": [list(c) for c in unit["chains"]],
                "display_name": unit["display_name"], "type": unit.get("type", "physbone"),
                "params": unit.get("params"), "style": style, "manual": False,
                "safety_margin": margin, "enabled": enabled,
            })
        # 手動行(旧鎖単位assignmentsのうち、カタログに存在しないもの)。
        for a in assignments_loaded:
            key = tuple(a["bones"])
            if key in catalog_keys:
                continue
            prior = chain_override_by_bones.get(key)
            rows.append({
                "anchor": None, "chains": [list(a["bones"])], "display_name": a["bones"][0],
                "type": "manual", "params": None, "style": a["style"], "manual": True,
                "safety_margin": safety_margin_by_bones.get(key, DEFAULT_SAFETY_MARGIN),
                "enabled": bool(prior["enabled"]) if prior is not None else True,
            })
        return rows

    working_rows: List[Dict[str, Any]] = _merge_working_rows()

    if not catalog_units and not ctx.sample_mode:
        empty_notice = tk.Label(dlg, text=i18n.S("LabSwayChainEmptyStateNotice"),
                                 fg="#555555", wraplength=736, justify="left")
        empty_notice.pack(fill="x", padx=8, pady=(0, 4))
        i18n.register(empty_notice, "LabSwayChainEmptyStateNotice")

    # `_selected` はクロージャ内可変状態(現在「筆」として持っているゆれかた
    # の実名。None=何も持っていない、"none"=「なし」を持っている[消しゴム
    # として使う]、それ以外=BUILTIN_STYLE_NAMESまたはカスタム名)。
    _selected: Dict[str, Optional[str]] = {"name": None}

    # dev#1572(2026-08-18ロードマップ「かたさが配線されていない問題」
    # 追記4「鎖ごとの『ゆれかた』列・カスタムスタイル・生パラメータUIは
    # 今版では画面から消す」、第2便PR#1584は誤ってこの隠蔽をラボ機能
    # 登録そのものの削除として実装してしまい安全域スピンボックスへの
    # 入口ごと失われた——本WP(第2便の過修正の是正)は、ラボ機能登録は
    # 復旧しつつ、ダイアログ内の「ゆれかた」関連ウィジェット(ゆれかた
    # 一覧ピッカー・CRUD・生パラメータスライダー・「筆」機構・鎖ごとの
    # スタイル表示・スロット数)だけを非生成にして隠す
    # (_SWAY_STYLE_PICKER_VISIBLE、モジュール冒頭で定義)。
    #
    # scale_widgets/value_labels/_format_value/_commit_slider_edits_to は
    # 下の`if _SWAY_STYLE_PICKER_VISIBLE:`ブロックの外側(=常に定義)に
    # 置く: _on_ok()が_commit_slider_edits_to(_selected["name"])を無条件に
    # 呼ぶため(_selected["name"]は本フラグがFalseの間ずっとNoneのまま
    # なので、_commit_slider_edits_toの中身は早期returnして安全に
    # 何もしない)。その他のゆれかた編集系関数(_rebuild_style_buttons等)は
    # 同ブロック内で定義し、ブロックがFalseの間は一切定義も呼び出しも
    # されない(=呼び出し元のボタン自体が存在しないため到達不能)。

    scale_widgets: Dict[str, tk.Scale] = {}
    value_labels: Dict[str, tk.Label] = {}

    def _format_value(key: str, value: float) -> str:
        if key in ("gravity_z", "limit_angle", "fake_pitch", "fake_roll", "fake_yaw"):
            return f"{value:.1f}"
        return f"{value:.2f}"

    def _commit_slider_edits_to(name: Optional[str]) -> None:
        """現在スライダーに表示されている値を name(カスタムのときのみ)へ
        書き戻す。予約名(組み込み/"none")・None のときは何もしない
        (読み取り専用)。_SWAY_STYLE_PICKER_VISIBLE=Falseの間は_selected
        ["name"]が常にNoneのため、この関数は_on_ok()から無条件に呼ばれても
        必ずここで早期returnする(scale_widgetsが空dictでも安全)。"""
        if name is None or name in RESERVED_STYLE_NAMES:
            return
        working_styles[name] = {
            key: float(scale_widgets[key].get()) for key in STYLE_PARAM_KEYS
        }

    if _SWAY_STYLE_PICKER_VISIBLE:
        # =====================================================================
        # 1. 「ゆれかた一覧」セクション(dev#1572により画面から隠蔽、
        #    _SWAY_STYLE_PICKER_VISIBLE=Falseの間はこのブロック全体が
        #    実行されない=一切のウィジェットを生成しない)。
        # =====================================================================
        styles_frame = tk.LabelFrame(dlg, text=i18n.S("LabSwayStyleStylesSectionLabel"),
                                      padx=6, pady=6)
        styles_frame.pack(fill="both", expand=True, padx=8, pady=(4, 4))
        i18n.register(
            styles_frame, "LabSwayStyleStylesSectionLabel", lambda w, t: w.config(text=t))

        styles_hint = tk.Label(styles_frame, text=i18n.S("LabSwayStyleStylesHint"),
                                wraplength=720, justify="left", anchor="w")
        styles_hint.pack(fill="x")
        i18n.register(styles_hint, "LabSwayStyleStylesHint")

        # ---- CRUD操作域(名前入力・作成/改名/複製/削除・エラー表示・現在の筆)。
        # レイアウト規約どおり、伸縮する一覧領域(styles_body)より**先**に
        # side="bottom"でpackし、常時可視を保証する(2026-08-16オーナー
        # HumanTest実試遊「名前欄にカーソルが当たらない」バグの修正――旧実装は
        # この域を一覧領域より後にpackしており、一覧が伸びると押し出されて
        # 実質到達不能になっていた)。
        crud_area = tk.Frame(styles_frame)
        crud_area.pack(fill="x", side="bottom", pady=(4, 0))

        error_label = tk.Label(crud_area, text="", fg="#b00000", anchor="w")
        error_label.pack(fill="x")

        current_paint_label = tk.Label(crud_area, text="", anchor="w", fg="#333333")
        current_paint_label.pack(fill="x")

        name_row = tk.Frame(crud_area)
        name_row.pack(fill="x", pady=(4, 0))
        name_label_w = tk.Label(name_row, text=i18n.S("LabSwayStyleNewNameLabel"))
        name_label_w.pack(side="left")
        i18n.register(name_label_w, "LabSwayStyleNewNameLabel")
        name_var = tk.StringVar()
        name_entry = tk.Entry(name_row, textvariable=name_var, width=24)
        name_entry.pack(side="left", padx=(4, 8))

        btn_row = tk.Frame(crud_area)
        btn_row.pack(fill="x", pady=(4, 0))

        # ---- 一覧領域(独立スクロール領域、crud_areaより後にpackするので
        #      余った空間だけを使う)。----
        styles_body = tk.Frame(styles_frame)
        styles_body.pack(fill="both", expand=True, pady=(4, 0))

        picker_pane = tk.Frame(styles_body)
        picker_pane.pack(side="left", fill="both")
        _picker_outer, _picker_canvas, picker_inner, picker_mousewheel = _make_scroll_region(
            picker_pane)
        _picker_outer.pack(fill="both", expand=True)
        picker_pane.configure(width=200)
        picker_pane.pack_propagate(False)

        params_area = tk.Frame(styles_body)
        params_area.pack(side="left", fill="both", expand=True, padx=(8, 0))

        for row_idx, key in enumerate(STYLE_PARAM_KEYS):
            lo, hi = PARAM_RANGES[key]
            resolution = 0.01 if key in ("stiffness", "damping", "wdl", "wdr") else 0.1
            name_label = tk.Label(params_area, text=i18n.S(_PARAM_LABEL_KEYS[key]), anchor="w",
                                   width=20)
            name_label.grid(row=row_idx, column=0, sticky="w")
            i18n.register(name_label, _PARAM_LABEL_KEYS[key])

            value_label = tk.Label(params_area, anchor="e", width=7)
            value_label.grid(row=row_idx, column=2, sticky="e")
            value_labels[key] = value_label

            def _on_move(raw: str, key=key) -> None:
                value_labels[key].config(text=_format_value(key, float(raw)))

            scale = tk.Scale(params_area, from_=lo, to=hi, resolution=resolution,
                              orient="horizontal", showvalue=False, command=_on_move, length=300)
            scale.grid(row=row_idx, column=1, sticky="we", padx=4, pady=1)
            scale_widgets[key] = scale

        def _load_params_into_sliders(params: Dict[str, float], editable: bool) -> None:
            for key in STYLE_PARAM_KEYS:
                scale_widgets[key].config(state="normal")
                scale_widgets[key].set(params[key])
                value_labels[key].config(text=_format_value(key, params[key]))
                scale_widgets[key].config(state="normal" if editable else "disabled")

        def _resolve_params_for_display(name: Optional[str]) -> Dict[str, float]:
            if name in BUILTIN_STYLE_PARAMS:
                return BUILTIN_STYLE_PARAMS[name]
            return working_styles.get(name, dict(_ZERO_PARAMS))

        def _refresh_current_paint_label() -> None:
            name = _selected["name"]
            current_paint_label.config(
                text=i18n.S("LabSwayStyleCurrentPaintFormat").format(_style_display_label(name)))

        style_buttons: Dict[str, tk.Button] = {}

        def _refresh_style_button_visuals() -> None:
            for n, btn in style_buttons.items():
                btn.config(relief=("sunken" if n == _selected["name"] else "raised"))

        def _rebuild_style_buttons(select: Optional[str] = None) -> None:
            """「ゆれかた一覧」ピッカーの再構築(multi_avatar_pak_dialog.py
            _render_main()の右ペイン[ライブラリボタン列]と同型: 実名ごとに
            tk.Buttonを1個生成し、クリックで_on_pick_style()を呼ぶ。選択中は
            relief="sunken"で強調する)。"なし"を先頭に、続けて組み込み3種、
            カスタムは名前順。"""
            for w in picker_inner.winfo_children():
                w.destroy()
            style_buttons.clear()
            names_in_order = [NONE_STYLE, *BUILTIN_STYLE_NAMES, *sorted(working_styles.keys())]
            colors = _style_color_map(names_in_order)
            for name in names_in_order:
                btn = tk.Button(
                    picker_inner, text=_style_display_label(name), bg=colors.get(name),
                    anchor="w", command=lambda n=name: _on_pick_style(n),
                )
                btn.bind("<MouseWheel>", picker_mousewheel)
                btn.pack(fill="x", pady=1)
                style_buttons[name] = btn

            target = select if select is not None else _selected["name"]
            if target is not None and target in style_buttons:
                _selected["name"] = target
                _load_params_into_sliders(
                    _resolve_params_for_display(target), target not in RESERVED_STYLE_NAMES)
            else:
                _selected["name"] = None
                _load_params_into_sliders(dict(_ZERO_PARAMS), False)
            _refresh_style_button_visuals()
            _refresh_current_paint_label()

        def _on_pick_style(name: str) -> None:
            """スポイト: ゆれかたをクリックして選ぶと同時に「筆」として持つ
            (multi_avatar_pak_dialog.py on_pick_avatar()と同じ操作感)。"""
            prev = _selected["name"]
            if name != prev:
                _commit_slider_edits_to(prev)
            _selected["name"] = name
            _load_params_into_sliders(
                _resolve_params_for_display(name), name not in RESERVED_STYLE_NAMES)
            _refresh_style_button_visuals()
            _refresh_current_paint_label()

        def _validate_new_name(name: str, allow_existing: Optional[str] = None) -> Optional[str]:
            if not name:
                return i18n.S("LabSwayStyleNameEmptyError")
            if name in RESERVED_STYLE_NAMES:
                return i18n.S("LabSwayStyleNameReservedError")
            if name in working_styles and name != allow_existing:
                return i18n.S("LabSwayStyleNameDuplicateError")
            return None

        def _on_create() -> None:
            _commit_slider_edits_to(_selected["name"])
            name = name_var.get().strip()
            err = _validate_new_name(name)
            if err:
                error_label.config(text=err)
                return
            error_label.config(text="")
            working_styles[name] = dict(_ZERO_PARAMS)
            name_var.set("")
            _rebuild_style_buttons(select=name)
            _rebuild_rows()

        def _on_rename() -> None:
            old = _selected["name"]
            if old is None or old in RESERVED_STYLE_NAMES:
                return
            _commit_slider_edits_to(old)
            new = name_var.get().strip()
            err = _validate_new_name(new, allow_existing=old)
            if err:
                error_label.config(text=err)
                return
            error_label.config(text="")
            working_styles[new] = working_styles.pop(old)
            for row in working_rows:
                if row["style"] == old:
                    row["style"] = new
            name_var.set("")
            _rebuild_style_buttons(select=new)
            _rebuild_rows()

        def _on_duplicate() -> None:
            src = _selected["name"]
            if src is None:
                return
            _commit_slider_edits_to(src)
            typed = name_var.get().strip()
            new_name = typed or f"{src}_copy"
            # 自動生成名が衝突する場合は連番を振る(ユーザー入力名の衝突は
            # 通常どおりエラー表示)。
            if not typed:
                suffix = 2
                while new_name in working_styles or new_name in RESERVED_STYLE_NAMES:
                    new_name = f"{src}_copy{suffix}"
                    suffix += 1
            err = _validate_new_name(new_name)
            if err:
                error_label.config(text=err)
                return
            error_label.config(text="")
            working_styles[new_name] = dict(_resolve_params_for_display(src))
            name_var.set("")
            _rebuild_style_buttons(select=new_name)
            _rebuild_rows()

        def _on_delete() -> None:
            name = _selected["name"]
            if name is None or name in RESERVED_STYLE_NAMES:
                return
            del working_styles[name]
            for row in working_rows:
                if row["style"] == name:
                    row["style"] = NONE_STYLE
            error_label.config(text="")
            _rebuild_style_buttons(select=None)
            _rebuild_rows()

        create_btn = tk.Button(btn_row, text=i18n.S("BtnLabSwayStyleCreate"), command=_on_create)
        create_btn.pack(side="left")
        i18n.register(create_btn, "BtnLabSwayStyleCreate")
        rename_btn = tk.Button(btn_row, text=i18n.S("BtnLabSwayStyleRename"), command=_on_rename)
        rename_btn.pack(side="left", padx=(4, 0))
        i18n.register(rename_btn, "BtnLabSwayStyleRename")
        duplicate_btn = tk.Button(btn_row, text=i18n.S("BtnLabSwayStyleDuplicate"),
                                   command=_on_duplicate)
        duplicate_btn.pack(side="left", padx=(4, 0))
        i18n.register(duplicate_btn, "BtnLabSwayStyleDuplicate")
        delete_btn = tk.Button(btn_row, text=i18n.S("BtnRemoveManualChain"), command=_on_delete)
        delete_btn.pack(side="left", padx=(4, 0))
        i18n.register(delete_btn, "BtnRemoveManualChain")

    # =========================================================================
    # 2. 「揺れもの一覧」セクション。
    # =========================================================================
    chains_frame = tk.LabelFrame(dlg, text=i18n.S("LabSwayStyleChainsSectionLabel"),
                                  padx=6, pady=6)
    chains_frame.pack(fill="both", expand=True, padx=8, pady=(4, 4))
    i18n.register(chains_frame, "LabSwayStyleChainsSectionLabel", lambda w, t: w.config(text=t))

    # dev#1572(第2便の過修正の是正、本WP): LabSwayStyleChainsHintは「筆」
    # (ゆれかたピッカー)の使い方を説明する文言で、_SWAY_STYLE_PICKER_VISIBLE
    # =Falseの間は意味を持たない(むしろ存在しないUIを指すため誤解を招く)。
    # ウィジェット自体を生成しないことで隠す(i18nキー・文言は温存)。
    if _SWAY_STYLE_PICKER_VISIBLE:
        chains_hint = tk.Label(chains_frame, text=i18n.S("LabSwayStyleChainsHint"),
                                wraplength=720, justify="left", anchor="w")
        chains_hint.pack(fill="x")
        i18n.register(chains_hint, "LabSwayStyleChainsHint")

    # dev#1551(安全域WP、issue #1551「安全域」欄、2026-08-18オーナー最終
    # 裁定「GUIに案内文」): 「先端の動きがおかしい揺れものは、安全域を
    # 増やしてください」の案内(旧ui.sway_chain_dialog.pyと同じi18nキーを
    # 再利用)。
    safety_margin_hint = tk.Label(
        chains_frame, text=i18n.S("LabSwayChainSafetyMarginHint"),
        wraplength=720, justify="left", anchor="w", fg="#555555")
    safety_margin_hint.pack(fill="x")
    i18n.register(safety_margin_hint, "LabSwayChainSafetyMarginHint")

    if ctx.sample_mode:
        sample_notice = tk.Label(chains_frame, text=i18n.S("LabSwayChainSampleModeNotice"),
                                  fg="#a06000", wraplength=720, justify="left")
        sample_notice.pack(fill="x")
        i18n.register(sample_notice, "LabSwayChainSampleModeNotice")

    # ---- フッター域(スロット表示・全てに塗る・手動追加)。レイアウト規約
    # どおり、伸縮する行一覧(rows_pane)より**先**にside="bottom"でpackし
    # 常時可視を保証する。----
    footer_area = tk.Frame(chains_frame)
    footer_area.pack(fill="x", side="bottom", pady=(4, 0))

    # dev#1572(第2便の過修正の是正、本WP): スロット表示(親骨×ゆれかたの
    # 組数)は「ゆれかた」割当の残容量を示すものなので、割当UI自体を隠す
    # 本WPではウィジェットを生成しない(_refresh_slot_label()は引き続き
    # slot_label.config(...)を呼ぶが、slot_labelはtk.Labelとして生成済み
    # なので未packでも安全にconfigできる――「非表示」戦略、下記参照)。
    slot_label = tk.Label(footer_area, text="", anchor="w")
    if _SWAY_STYLE_PICKER_VISIBLE:
        slot_label.pack(fill="x")
        slot_hint = tk.Label(footer_area, text=i18n.S("LabSwayStyleSlotHint"),
                              wraplength=720, justify="left", anchor="w", fg="#555555")
        slot_hint.pack(fill="x")
        i18n.register(slot_hint, "LabSwayStyleSlotHint")

    def _row_slot_key(row: Dict[str, Any]) -> Tuple[int, str]:
        """dev#1551(hub廃止・1chain=1KP、2026-08-17オーナー裁定): 各行
        (=1 PB/SBコンポーネント)はもう他の行と統合されず、常に独立して
        1スロットを消費する(`pipeline\\py\\sway_allocator.build_groups()`の
        dev#1551対応と同じ規約——同じ親骨(anchor)を共有する複数の行でも
        別々のKPノードへ配線される)。旧実装は`(_row_group_key_base(row),
        row["style"])`(=anchorベース)でdedupしていたが、dev#1551でdedup
        自体が誤りになったため、行のidentity(id(row))をキー基底にして
        1行=1キーを保証する。"""
        return (id(row), row["style"])

    def _compute_group_order() -> List[Tuple[int, str]]:
        order: List[Tuple[int, str]] = []
        for row in working_rows:
            if row["style"] == NONE_STYLE:
                continue
            order.append(_row_slot_key(row))
        return order

    def _refresh_slot_label() -> None:
        n = len(_compute_group_order())
        slot_label.config(text=i18n.S("LabSwayStyleSlotFormat").format(n))
        slot_label.config(fg="#b00000" if n > MAX_SLOTS else "#000000")

    def _on_bulk_apply() -> None:
        """全ての行に、現在持っている「筆」を塗る(multi_avatar_pak_dialog
        には直接対応する機能が無いため、BRIEF指示どおり「全てに塗る」相当
        として残した、実装者解釈)。何も筆を持っていなければ何もしない。"""
        brush = _selected["name"]
        if brush is None:
            return
        for row in working_rows:
            row["style"] = brush
        _rebuild_rows()
        ctx.append_log(f"[lab][sway_styles] bulk apply: {brush} -> {len(working_rows)} row(s)")

    # dev#1572(第2便の過修正の是正、本WP): 「全てに塗る」は「筆」を前提と
    # する操作のため、ピッカー隠蔽時はボタン自体を生成しない
    # (_on_bulk_applyの定義は温存、コード削除しない)。
    if _SWAY_STYLE_PICKER_VISIBLE:
        bulk_apply_btn = tk.Button(footer_area, text=i18n.S("BtnLabSwayStyleBulkApply"),
                                    command=_on_bulk_apply)
        bulk_apply_btn.pack(anchor="w", pady=(2, 0))
        i18n.register(bulk_apply_btn, "BtnLabSwayStyleBulkApply")

    def _unique_forced_style_name(base_display_name: str) -> str:
        """「（自動）<pb_object_name>」形式の一意な名前を作る(2026-08-16
        オーナー口述指定)。既存名(working_styles/予約名)と衝突する場合は
        `_on_duplicate()`と同じ「連番を振る」方式で回避する。"""
        base = i18n.S("LabSwayStyleForceSetupNameFormat").format(base_display_name)
        if base not in working_styles and base not in RESERVED_STYLE_NAMES:
            return base
        suffix = 2
        candidate = f"{base}_{suffix}"
        while candidate in working_styles or candidate in RESERVED_STYLE_NAMES:
            suffix += 1
            candidate = f"{base}_{suffix}"
        return candidate

    def _on_force_setup_special_bones() -> None:
        """「特殊ボーンを強制セットアップ」(2026-08-16オーナー口述指定):
        偏向として既定除外されるPB行それぞれに、そのPB実値から自動生成した
        カスタム「ゆれかた」を割り当てる。偏向判定は
        ui.sway_pb_catalog.is_unit_biased()(pipeline\\py\\sway_allocator.py
        の判定規則をそのまま再利用、重複実装しない)を使う。SpringBone行・
        手動行(paramsが無い)は対象外。スロット数(n/9)はこの操作では検査
        しない(オーナー指定「カウントも一応無視」——実際の容量処理は
        パイプライン側の仕事)。"""
        applied = 0
        # dev#1551 laneG5修理(work\run_1551\gui_verify\RESULT.md 0.4節が確定
        # した根因): row["params"]が欠落している(=PBカタログの供給元
        # physbones.jsonが旧スキーマ/陳腐化キャッシュ由来)行は、偏向判定
        # (is_unit_biased)へ到達する前に無条件でスキップされる。これまでは
        # このスキップが完全に無言だったため、「押しても何も起きない」原因が
        # ログからも追えなかった(コーディネータ指示: ダイアログ文言には
        # 踏み込まず、ログでの可視化のみ最小限で行う)。
        skipped_no_params = 0
        skipped_unbiased = 0
        for row in working_rows:
            if row["manual"]:
                continue
            if not row.get("params"):
                skipped_no_params += 1
                continue
            is_biased, _reason = sway_pb_catalog.is_unit_biased(row)
            if not is_biased:
                skipped_unbiased += 1
                continue
            style_params = sway_pb_catalog.compute_forced_style_params(row["params"])
            name = _unique_forced_style_name(row["display_name"])
            working_styles[name] = style_params
            row["style"] = name
            applied += 1
        _rebuild_style_buttons()
        _rebuild_rows()
        ctx.append_log(
            f"[lab][sway_styles] force setup special bones: {applied} row(s) applied, "
            f"{skipped_unbiased} row(s) skipped (already unbiased), "
            f"{skipped_no_params} row(s) skipped (no PB params in catalog -- "
            f"the Unity export cache for this avatar may be stale; re-selecting "
            f"the prefab to trigger a fresh export can resolve this)")
        # 実行後は常にメッセージダイアログを表示する(2026-08-16オーナー
        # 口述指定「実行後にメッセージダイアログを表示」、適用件数に依らず
        # 無条件――偏向行が1つも無かった場合[applied==0]も操作自体は行った
        # ことを示すため表示する)。
        messagebox.showwarning(
            i18n.S("LabSwayStyleForceSetupTitle"),
            i18n.S("LabSwayStyleForceSetupWarning"),
            parent=dlg,
        )

    # dev#1572(第2便の過修正の是正、本WP): 「特殊ボーンを強制セットアップ」
    # はカスタム「ゆれかた」(生パラメータ)を自動生成する操作のため、
    # ピッカー隠蔽時はボタン自体を生成しない(_on_force_setup_special_bones
    # の定義は温存、コード削除しない)。
    if _SWAY_STYLE_PICKER_VISIBLE:
        force_setup_btn = tk.Button(
            footer_area, text=i18n.S("BtnLabSwayStyleForceSetup"),
            command=_on_force_setup_special_bones)
        force_setup_btn.pack(anchor="w", pady=(2, 0))
        i18n.register(force_setup_btn, "BtnLabSwayStyleForceSetup")

    # ---- 手動追加(スタイルの選び方は「現在の筆」に統一、専用ドロップ
    # ダウンは廃止)。----
    manual = tk.LabelFrame(footer_area, text=i18n.S("LabSwayChainManualLabel"), padx=6, pady=6)
    manual.pack(fill="x", pady=(6, 0))
    i18n.register(manual, "LabSwayChainManualLabel", lambda w, t: w.config(text=t))

    manual_name_label = tk.Label(manual, text=i18n.S("LabSwayChainManualNameLabel"))
    manual_name_label.grid(row=0, column=0, sticky="w")
    i18n.register(manual_name_label, "LabSwayChainManualNameLabel")
    manual_name_var = tk.StringVar()
    tk.Entry(manual, textvariable=manual_name_var, width=20).grid(
        row=0, column=1, sticky="w", padx=4)

    def _on_manual_add() -> None:
        name = manual_name_var.get().strip()
        if not name:
            return
        style = _selected["name"] if _selected["name"] is not None else NONE_STYLE
        working_rows.append({
            "anchor": None, "chains": [[name]], "display_name": name,
            "type": "manual", "params": None, "style": style, "manual": True,
            "safety_margin": DEFAULT_SAFETY_MARGIN, "enabled": True,
        })
        manual_name_var.set("")
        _rebuild_rows()

    add_btn = tk.Button(manual, text=i18n.S("BtnSwayChainManualAdd"), command=_on_manual_add)
    add_btn.grid(row=0, column=2, padx=4)
    i18n.register(add_btn, "BtnSwayChainManualAdd")

    # ---- 行一覧の列見出し(dev#1551安全域WP。旧ui.sway_chain_dialog.pyの
    # col_safety_marginラベルと同じi18nキーを再利用。行ボタン自体は名前が
    # 可変長のためヘッダーの整列はチェックボックス列・スピンボックス列の
    # みで揃える)。dev#1572第3便: 「ON」列(旧ui.sway_chain_dialog.pyの
    # LabSwayChainColOnキーを再利用)を追加。----
    chain_rows_header = tk.Frame(chains_frame)
    chain_rows_header.pack(fill="x", pady=(2, 0))
    col_on = tk.Label(chain_rows_header, text=i18n.S("LabSwayChainColOn"), width=4)
    col_on.pack(side="left")
    i18n.register(col_on, "LabSwayChainColOn")
    tk.Label(chain_rows_header, text="").pack(side="left", fill="x", expand=True)
    col_safety_margin = tk.Label(
        chain_rows_header, text=i18n.S("LabSwayChainColSafetyMargin"), width=8)
    col_safety_margin.pack(side="right")
    i18n.register(col_safety_margin, "LabSwayChainColSafetyMargin")

    # ---- 行一覧(独立スクロール領域、footer_areaより後にpackするので
    #      余った空間だけを使う)。----
    rows_pane = tk.Frame(chains_frame)
    rows_pane.pack(fill="both", expand=True, pady=(2, 0))
    _rows_outer, _rows_canvas, rows_inner, rows_mousewheel = _make_scroll_region(rows_pane)
    _rows_outer.pack(fill="both", expand=True)

    def _row_label_and_color(
        row: Dict[str, Any], name_counts: Dict[str, int], colors: Dict[str, str]
    ) -> Tuple[str, str]:
        """multi_avatar_pak_dialog._equipment_label_and_color()と同型:
        未割当は元の名前だけ、割当済みは"元の名前 -> ゆれかた名"。

        2026-08-16 WP wp_w2c_pbunit(dev#1508列車計画W2c): 基本名は
        ui.sway_pb_catalog.unit_base_label()(pb_object_name優先/GUID尾
        除去済みanchorフォールバック+曖昧解消)。多房PB(chains>1)は
        「(房n本)」を補足表示する(SPEC.md §2)。"""
        base = sway_pb_catalog.unit_base_label(row, name_counts)
        if len(row["chains"]) > 1:
            base = f"{base} ({i18n.S('LabSwayStyleChainCountFormat').format(len(row['chains']))})"
        if row["manual"]:
            base = f"{base} ({i18n.S('LabSwayChainManualTag')})"
        # dev#1572(第2便の過修正の是正、本WP): 「元の名前 -> ゆれかた名」の
        # スタイルsuffix・色分けは、鎖ごとの「ゆれかた」列そのものなので
        # ピッカー隠蔽時は表示しない(タスク指示#2)。旧ロジックは
        # _SWAY_STYLE_PICKER_VISIBLE=Trueのパスとして温存する(削除しない)。
        if not _SWAY_STYLE_PICKER_VISIBLE:
            return base, _NONE_STYLE_COLOR
        style = row["style"]
        if style == NONE_STYLE:
            return base, _NONE_STYLE_COLOR
        return f"{base} -> {_style_display_label(style)}", colors.get(style, _NONE_STYLE_COLOR)

    row_buttons: Dict[int, tk.Button] = {}

    def _on_paint_row(idx: int) -> None:
        """ペースト: 現在持っている「筆」を、クリックした行に塗る
        (multi_avatar_pak_dialog.on_click_equipment()と同じ操作感)。
        何も筆を持っていなければ何もしない(無言、装備側と同じ安全側)。

        dev#1572(第2便の過修正の是正、本WP): ピッカー(「ゆれかた一覧」)を
        隠蔽したことで_selected["name"]は常にNoneのままになるため、この
        ハンドラは事実上常に早期returnする——行ボタン自体は「残す:鎖一覧、
        ON/OFFチェック」の指示に沿って残すが、指示どおり**結線しない**
        (「現在どおり未結線の見た目でよい」)。第3便(dev#1572ロードマップ
        「チェインの揺れ設定問題1/2」)で実際のenabled切り替えとして配線
        される想定。"""
        brush = _selected["name"]
        if brush is None:
            return
        working_rows[idx]["style"] = brush
        ctx.append_log(f"[lab][sway_styles] painted row {idx}: {brush}")
        # スロット超過状態の変化は行全体の色/文字色にも影響するため
        # 全体を再構築する(multi_avatar_pak_dialog dev#1341のような差分
        # 更新の最適化はしない――行数がその想定[装備スロット数十]ほど
        # 多くならないラボ機能のため、雑な全再構築で十分、ラボ憲章②)。
        _rebuild_rows()

    def _on_delete_row(idx: int) -> None:
        del working_rows[idx]
        _rebuild_rows()

    def _rebuild_rows() -> None:
        for child in rows_inner.winfo_children():
            child.destroy()
        row_buttons.clear()
        _refresh_slot_label()
        group_order = _compute_group_order()
        overflow_keys = set(group_order[MAX_SLOTS:]) if len(group_order) > MAX_SLOTS else set()

        # 曖昧解消用の表示名カウント(sway_pb_catalog.unit_base_label()参照)。
        # 手動行は旧実装同様、カウント対象から除外する(常に一意なため)。
        name_counts = Counter(
            row["display_name"] for row in working_rows if not row["manual"]
        )
        names_in_order = [NONE_STYLE, *BUILTIN_STYLE_NAMES, *sorted(working_styles.keys())]
        colors = _style_color_map(names_in_order)

        rows_inner.grid_columnconfigure(1, weight=1)
        for idx, row in enumerate(working_rows):
            overflow = _row_slot_key(row) in overflow_keys
            label_text, color = _row_label_and_color(row, name_counts, colors)

            # dev#1572第3便(issue #1572追記「チェインの揺れ設定問題1・2」):
            # 揺れる/揺れないの実際のON/OFFチェックボックス(旧行ボタンの
            # 「筆で塗る」動作(`_on_paint_row()`、styleの選択)とは完全に
            # 独立の軸——ピッカー隠蔽中でも常に生成・結線する)。
            enabled_var = tk.BooleanVar(value=bool(row.get("enabled", True)))

            def _on_toggle_enabled(i=idx, var=enabled_var) -> None:
                working_rows[i]["enabled"] = var.get()

            enabled_cb = tk.Checkbutton(
                rows_inner, variable=enabled_var, command=_on_toggle_enabled,
            )
            enabled_cb.grid(row=idx, column=0, pady=1)
            enabled_cb.bind("<MouseWheel>", rows_mousewheel)

            row_btn = tk.Button(
                rows_inner, text=label_text, bg=color, anchor="w",
                fg="#b00000" if overflow else "#000000",
                command=lambda i=idx: _on_paint_row(i),
            )
            row_btn.grid(row=idx, column=1, sticky="we", pady=1)
            row_btn.bind("<MouseWheel>", rows_mousewheel)
            row_buttons[idx] = row_btn

            # dev#1551(安全域WP): 各行の安全域スピンボックス(0..
            # MAX_SAFETY_MARGIN、既定1)。複数房のPB(chains>1)は行全体へ
            # 同じ値を適用する(styleと同じfan-out規約、_on_ok()参照)。
            # ttk.Spinboxはtextvariable+コマンド無しでも矢印/直接入力の
            # 両方が使える(旧ui.sway_chain_dialog.pyの同型実装を踏襲)。
            margin_var = tk.IntVar(value=row.get("safety_margin", DEFAULT_SAFETY_MARGIN))
            margin_sb = ttk.Spinbox(
                rows_inner, from_=0, to=MAX_SAFETY_MARGIN, width=3,
                textvariable=margin_var, justify="center",
            )
            margin_sb.grid(row=idx, column=2, padx=4, pady=1)
            margin_sb.bind("<MouseWheel>", rows_mousewheel)

            def _on_margin_change(*_a, i=idx, var=margin_var) -> None:
                try:
                    value = int(var.get())
                except (tk.TclError, ValueError):
                    return  # 入力途中の空文字/不正値は無視(旧実装と同じ、
                    # ttk.Spinboxのfrom_/toが範囲を機械的に制約するため)
                working_rows[i]["safety_margin"] = max(0, min(MAX_SAFETY_MARGIN, value))

            margin_var.trace_add("write", _on_margin_change)

            if row["manual"]:
                del_btn = tk.Button(rows_inner, text=i18n.S("BtnRemoveManualChain"),
                                     command=lambda i=idx: _on_delete_row(i), width=6)
                del_btn.grid(row=idx, column=3, padx=4, pady=1)
                del_btn.bind("<MouseWheel>", rows_mousewheel)

    _rebuild_rows()
    if _SWAY_STYLE_PICKER_VISIBLE:
        _rebuild_style_buttons()

    # ---- 下部ボタン(実ウィジェット。入れ物`bottom`は関数冒頭で確保済み) ----
    def _on_reset() -> None:
        _store.clear_avatar_assignments(ctx.app_root, ctx.avatar_path)
        assignments_loaded.clear()
        # dev#1551(安全域WP): ボタン文言「このアバターの設定を既定値に戻す」
        # はsafety_marginも含む(別ストアだが同じ「このアバターの設定」の
        # 一部)。sway_chain_override_store.clear_avatar()もここで呼ぶ。
        _chain_store.clear_avatar(ctx.app_root, ctx.avatar_path)
        chain_overrides_loaded.clear()
        safety_margin_by_bones.clear()
        chain_override_by_bones.clear()
        working_rows[:] = _merge_working_rows()
        _rebuild_rows()
        ctx.append_log("[lab][sway_styles] reset chain assignments to defaults for current avatar")

    reset_btn = tk.Button(bottom, text=i18n.S("BtnLabSwayChainReset"), command=_on_reset)
    reset_btn.pack(side="left")
    i18n.register(reset_btn, "BtnLabSwayChainReset")

    def _on_ok() -> None:
        _commit_slider_edits_to(_selected["name"])
        # 段1(表示のみPB単位化): ストアのスキーマは変えない。行(=PB)の
        # style選択を配下の全房へfan-out書き込みする(DESIGN.md §5段1)。
        assignments: List[Dict[str, Any]] = []
        # dev#1551(安全域WP): 行のsafety_marginも同じfan-out規約で鎖単位
        # ストア(sway_chain_override_store、styleとは別ストア)へ書く。
        # dev#1572第3便: enabledも同じfan-out規約で書く(本パネルが実際に
        # 管理する側になった、モジュールdocstring参照)——working_rows[i]
        # ["enabled"]はロード時に`_resolve_unit_enabled()`で初期化され、
        # チェックボックス操作で直接更新される現在値そのものなので、
        # ここでは読み直すだけでよい(旧prior/manual/名前ベースの
        # 3分岐フォールバックは不要になった)。hardnessは引き続き本パネルの
        # 管理対象外(読込時の値をそのまま引き継ぐ、無ければ既定"follow")。
        chain_overrides: List[Dict[str, Any]] = []
        for row in working_rows:
            assignments.extend(sway_pb_catalog.fanout_unit_assignments(
                row["anchor"], row["chains"], row["style"]))
            enabled = bool(row.get("enabled", True))
            for key in sway_pb_catalog.unit_bones_keys(row["anchor"], row["chains"]):
                prior = chain_override_by_bones.get(key)
                hardness = prior.get("hardness", "follow") if prior is not None else "follow"
                chain_overrides.append({
                    "bones": list(key),
                    "enabled": enabled,
                    "hardness": hardness,
                    "manual": row["manual"],
                    "safety_margin": row["safety_margin"],
                })
        _store.save_state(ctx.app_root, ctx.avatar_path, working_styles, assignments)
        _chain_store.save_config(
            ctx.app_root, ctx.avatar_path, chain_overrides,
            default_enabled_map=default_enabled_by_bones)
        ctx.append_log(
            f"[lab][sway_styles] saved: {len(working_styles)} custom style(s), "
            f"{len(working_rows)} row(s) in working set, "
            f"{len(chain_overrides)} chain-level safety-margin candidate(s)"
        )
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
# dev#1186 ラボ機能レジストリ記述子(lab_window.py側が結線する、マージ時に
# 1行で繋ぐ想定。旧2機能[sway_chains/lab_raw_sway_params]の記述子撤去は
# 本WPのスコープ外――結線と同時にマージ時作業として行う、REPORT.md参照)。
# ---------------------------------------------------------------------------

LAB_REGISTRY_DESCRIPTOR = {
    "id": LAB_FEATURE_ID,
    "name_key": "LabFeatureSwayStyles",
    "state_summary": state_summary,
    "open_dialog": show_sway_style_dialog,
    "reset": reset,
}
