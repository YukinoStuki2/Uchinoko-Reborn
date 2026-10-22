# multi_avatar_pak_store.py -- dev#1170 WP-3(マルチアバターPAK作成)ラボ機能の
# 「装備コード -> ライブラリエントリID」対応表の永続化ロジック(tkinter非依存)。
#
# equipment_filter_store.py/mesh_delete_store.py と同じ設計: 状態の読み書きだけを
# tkinter非依存モジュールに切り出す(pipeline_runner.pyがヘッドレス経路から読める
# ようにするため、というのが他機能の理由だが、本機能は下記のとおりpipeline_runner.py
# からは一切読まれない設計。それでも「UI層はstore層のみを直接読み書きする」という
# 既存の分離方針は踏襲しておく——将来この機能をjob.json経由へ配線し直す判断が
# 入っても、ここだけ差し替えれば済む)。
#
# **オーナー確定仕様(2026-08-09対話、issue #1170)との対応関係**:
# この対応表はメインパネルの通常変換(job.json/pipeline_runner.write_job())には
# 一切接続しない。マルチアバターPAK作成は専用UIの「作成」ボタンからのみ発火する
# 別経路(合成ジョブJSON、multi_avatar_pak_compose.py参照)であり、ラボ憲章④
# 「デフォルト値のときは未実装状態と完全に同一」は「pipeline_runner.pyが本
# モジュールを一切importしない」という構造そのもので自動的に満たされる
# (equipment_filter等のように「空なら既定と同じキー無し」という値レベルの
# 配慮が不要——job.json組み立て経路に触れてすらいないため)。
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional

_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402

LAB_FEATURE_ID = "multi_avatar_pak"
_STATE_FILENAME = "settings_lab_multi_avatar_pak.json"


def _state_path(app_root: str) -> str:
    return os.path.join(app_root, _STATE_FILENAME)


def load_assignments(app_root: str) -> Dict[str, str]:
    """保存済みの対応表(装備コード -> ライブラリエントリID)。ファイル不在/
    壊れている/形式が違う場合は空dict(=既定=未設定、安全側)。"""
    path = _state_path(app_root)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assignments = data.get("assignments")
        if isinstance(assignments, dict):
            return {
                str(code): str(entry_id)
                for code, entry_id in assignments.items()
                if isinstance(code, str) and code and isinstance(entry_id, str) and entry_id
            }
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        pass
    return {}


def save_assignments(app_root: str, assignments: Dict[str, str]) -> None:
    """対応表を保存する。空dictを渡すと「未設定」を意味する内容になる
    (equipment_filter_store.save_selected_codes()と同じ方針: ファイル自体は
    残すが中身は空、次回load_assignments()は空dictを返すのでファイル不在と
    等価)。書き込み失敗は握りつぶす(設定保存の失敗で画面を止めない)。"""
    path = _state_path(app_root)
    try:
        clean = {
            str(code): str(entry_id)
            for code, entry_id in assignments.items()
            if code and entry_id
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"assignments": clean}, f, ensure_ascii=False, indent=1, sort_keys=True)
    except OSError:
        pass


def reset(app_root: str) -> None:
    """dev#1186レジストリ記述子の「既定値リセット関数」。既定値=未設定(空)。"""
    save_assignments(app_root, {})


def is_active(app_root: str) -> bool:
    """1件以上割当済みか。"""
    return bool(load_assignments(app_root))


def state_summary(app_root: str, lang: Optional[str] = None) -> Optional[str]:
    """dev#1186レジストリ記述子の「状態サマリ関数」。この機能は意図的に
    lab_window.pyのラボ共通警告(any_feature_active())からは除外される
    (オーナー確定仕様: 「ラボ共通警告への合流はこの機能では不要。メインパネル
    の変換出力に影響しないため」)。ラボ窓の行に表示するための状態文言のみを
    返す用途。無効(未設定)ならNone。

    2026-08-09 バグ修正(dev#1170、オーナー実機確認「Lab Statusで
    Enabled: 30bones(s) は表示がおかしいのでは?」): 旧実装は他機能
    (drop_bonesのボーン除外件数)のフォーマットキー
    LabStatusDropBonesCountFormat({0}本/{0} bone(s))を誤って流用しており、
    「装備を30件割り当てた」状態が「30本のボーン」という無関係な文言で
    出ていた。本機能専用のLabMultiAvatarPakSummaryFormatを新設し、
    割当済み装備数を表す文言(例: 「{0}件割当」)に差し替える
    (equipment_filter_store.state_summary()等、他store同様に
    i18n.S(key, lang).format(n)でlang引数を尊重する形に揃える)。"""
    n = len(load_assignments(app_root))
    if n == 0:
        return None
    return i18n.S("LabMultiAvatarPakSummaryFormat", lang).format(n)


def default_fill(app_root: str, entry_id: str, equipment_codes: List[str]) -> Dict[str, str]:
    """「設定開始」フロー: 選んだ1件のライブラリエントリを、渡された全装備
    コードへ一括割当する(オーナー確定仕様②「その中間物が全装備スロットへ
    デフォルト充填される」=割当なしのバニラ残しを構造的に否定)。保存まで
    行い、確定した対応表を返す。

    dev#1341: UIの「設定開始」→アバター選択クリック経路からは呼ばれなく
    なった(下のcompute_default_fill()を使う、assign_many()と同じ理由)。
    本関数自体はテスト容易性のため残す。"""
    assignments = {code: entry_id for code in equipment_codes if code}
    save_assignments(app_root, assignments)
    return assignments


def compute_default_fill(entry_id: str, equipment_codes: List[str]) -> Dict[str, str]:
    """dev#1341: default_fill()のディスクI/Oを伴わない純粋版。呼び出し側
    (ui\\multi_avatar_pak_dialog.py)がメモリ上の対応表を更新するために使う。"""
    return {code: entry_id for code in equipment_codes if code}


def assign_many(app_root: str, entry_id: str, equipment_codes: List[str]) -> Dict[str, str]:
    """「ペンキ」割当: 現在の対応表を読み込み、渡された装備コード群を
    entry_idへ上書きしてから保存する(他の装備の割当はそのまま残る)。
    保存後の対応表全体を返す。

    dev#1341: この関数自体はディスクI/Oを伴う(load_assignments+
    save_assignments)ため、UIのクリック経路(ui\\multi_avatar_pak_dialog.py
    の左ペイン装備クリック)からは呼ばれなくなった——クリックのたびに
    ディスクへ同期書き込みしていたことが体感プチフリーズの支配項だったため
    (work\\wp_1341_1342\\NOTES.md参照)。クリック経路は下のcompute_paint()
    (純粋関数、I/O無し)でメモリ上のみ更新し、永続化はダイアログクローズ時へ
    遅延する。本関数自体はテスト容易性・他の呼び出し元(あれば)のために
    そのまま残す。"""
    assignments = load_assignments(app_root)
    for code in equipment_codes:
        if code:
            assignments[code] = entry_id
    save_assignments(app_root, assignments)
    return assignments


def compute_paint(
    assignments: Dict[str, str], entry_id: str, equipment_codes: List[str]
) -> Dict[str, str]:
    """dev#1341: assign_many()のディスクI/Oを伴わない純粋版。渡された
    assignmentsのコピーへ、equipment_codesをentry_idへ上書きしたものを返す
    (引数のdictそのものは書き換えない)。UIのクリックハンドラ
    (ui\\multi_avatar_pak_dialog.py on_click_equipment())が、ディスクへ
    一切触れずにメモリ上の対応表を更新するために使う——オーナー裁定
    「クリックには本当は◯◯の処理が必要、という反論は却下される。UIスレッド
    と同期で実行していること自体が欠陥」(dev#1341)への直接対応。"""
    updated = dict(assignments)
    for code in equipment_codes:
        if code:
            updated[code] = entry_id
    return updated


def unassign(app_root: str, equipment_code: str) -> Dict[str, str]:
    """指定した装備コードの割当を解除する(補助操作。UIからの直接呼び出しは
    第1版では未使用だが、テスト容易性のため公開関数として用意しておく)。"""
    assignments = load_assignments(app_root)
    assignments.pop(equipment_code, None)
    save_assignments(app_root, assignments)
    return assignments


def used_entry_ids(assignments: Dict[str, str]) -> List[str]:
    """対応表に登場するエントリIDを初出順・重複無しで返す(色分けの割当順に
    使う純粋関数)。"""
    seen: List[str] = []
    seen_set = set()
    for code in sorted(assignments.keys()):
        entry_id = assignments[code]
        if entry_id not in seen_set:
            seen_set.add(entry_id)
            seen.append(entry_id)
    return seen


# 自動色分け用の固定パレット(オーナー確定仕様④「アバターごとに自動色分け
# して見やすく」)。tkinterのbackground色として使えるHEX文字列。件数が
# パレットを超えたら循環させる(色の重複は許容——多数アバターの同時運用は
# ラボ憲章②の範囲外なので凝った割当アルゴリズムは持たない)。
AVATAR_COLOR_PALETTE: List[str] = [
    "#ffd699", "#a3d9a5", "#a3c9f7", "#f7a3c9", "#d9a3f7",
    "#f7e2a3", "#a3f7e2", "#f7a3a3", "#c9a3f7", "#c9f7a3",
]


def avatar_color_map(entry_ids: List[str]) -> Dict[str, str]:
    """entry_idの列(順序が色の割当順)から、{entry_id: color} の対応を作る
    純粋関数(GUI非依存、単体テスト容易)。"""
    colors: Dict[str, str] = {}
    for i, entry_id in enumerate(entry_ids):
        if entry_id in colors:
            continue
        colors[entry_id] = AVATAR_COLOR_PALETTE[i % len(AVATAR_COLOR_PALETTE)]
    return colors
