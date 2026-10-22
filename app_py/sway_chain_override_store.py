# sway_chain_override_store.py -- 揺れものUI プロトタイプ(dev#19、実物GUI
# 埋め込み版WP)。ラボ機能「揺れもの詳細設定」の選択状態永続化ロジック
# (tkinter非依存)。
#
# mesh_delete_store.py/shapekey_filter_store.pyと同じ理由・同じ設計:
#   - pipeline_runner.py(ヘッドレス経路からもimportされる)が直接読める
#     よう、tkinterをimportするui\sway_chain_dialog.pyとは分離する。
#   - チェーンの構造(骨名)は入力アバター自身に依存するため、保存スコープは
#     mesh_delete_store.py/shapekey_filter_store.pyと同じ「直前に編集した
#     avatar_pathとの組」方式(アバター単位)。別アバターへ切り替えた場合は
#     残留データを既定値として扱う(誤爆防止、mesh_delete_store.pyの
#     コメント参照)。
#
# **意味論**: 1チェーンの既定状態は hardness="follow"(標準の「揺れの度合い」
# に従う)・manual=False、かつenabledはチェーン自身の同定結果に従う
# (dev#19 native-donor-rule、pipeline\\py\\sway_identify.default_sway_enabled():
# 尻尾・耳=既定ON、その他(スカート・髪・エプロン・スカーフ等)=既定OFF)。
# この既定状態と完全に一致するエントリは保存しない(ラボ憲章④=既定値の
# ときは未実装状態と完全に同一、を状態ファイルの中身でも常に満たす)。
# 手動追加チェーン(manual=True)は存在すること自体が既定からの逸脱なので、
# hardness="follow"のままでも保存対象になる。
#
# dev#1438(2026-08-15 致命バグ修正): 旧実装はenabledの既定を常にTrue固定と
# 誤って仮定していた(dev#19 native-donor-rule導入以前の名残)。その結果、
# 既定OFFのチェーン(スカート等)をユーザーが明示的にONへ変えても
# 「enabled=True・hardness=follow・manual=False」という表面上の形が既定
# エントリと一致してしまい、保存対象から誤って除外されていた——ダイアログ
# 再オープン時にユーザーの変更が消えて見える不具合(#1438)の根本原因。
# 逆に、既定OFFのチェーンを一切触らなかった場合(enabled=Falseのまま)は
# 逆に「既定と不一致」と誤判定され、無意味なエントリが大量に保存されて
# いた(state_summary件数がチェックボックスの実表示と乖離する症状の一因)。
# 本修正で、既定判定をsway_identify.default_sway_enabled()に基づく
# チェーンごとの値と比較する形へ直す。
#
# dev#1551(安全域WP、issue #1551「安全域」欄、2026-08-18オーナー最終裁定):
# 各エントリへ"safety_margin"(int、既定1)を追加した。定義=このチェーンで
# ドナーボーンをいくつ削るか(先端からのマージ縮約、
# pipeline\\py\\sway_hub.target_len_with_safety_margin()が実際の計算式)。
# 製品既定値は**1**(GUI未設定でも常に適用される、
# pipeline\\blender\\step02_retarget.py:SWAY_DEFAULT_SAFETY_MARGIN)——
# enabled/hardnessの「既定=標準機能に従う」とは意味論が違う(safety_marginに
# "follow"相当のセンチネルは無く、常に具体的な整数)。既定(=1)と完全一致する
# エントリは(他フィールドも既定なら)引き続き保存対象外(ラボ憲章④)。
#
# dev#1595(2026-08-20、issue #1595「GUI揺れ詳細設定のenabled上書きが変換時に
# 脱落する(耳OFFが効かない)」修正): load_config()は既定との再間引きを
# **行わない**よう改めた。理由: 間引き(ラボ憲章④)は保存時(save_config())
# の責務であり、ファイルに存在するエントリは保存時点で正しいdefault_enabled_
# map(偏向判定ベース)により「非既定」と確定済みのはず。読込側が(呼び出し元
# によっては別のmap、あるいはmap無し=名前ベースフォールバックという)
# 保存時と食い違う既定判定で再度間引くと、正しく保存されたはずのユーザー
# 上書きが読込時に誤って消える(実測: pipeline_runner.write_job()がmap無しで
# load_config()を呼んでいたため、GUI保存済みのOFF上書きが偏向判定と名前
# ベース判定の不一致分だけ変換ジョブから脱落し、耳などのOFF指定が効かなく
# なっていた)。load_config()はもはや`default_enabled_map`引数を使わない
# (ファイルの中身をそのまま返すだけ)——引数自体は既存呼び出し元
# (app_py\\ui\\sway_style_dialog.py・テスト)との互換のため残すが、無視される。
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)
_ROOT_DIR = os.path.dirname(_APP_PY_DIR)
_PIPELINE_PY_DIR = os.path.join(_ROOT_DIR, "pipeline", "py")
if _PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_PY_DIR)

import i18n  # noqa: E402
import sway_identify  # noqa: E402  (dev#1438: 既定enabled判定の唯一の真実の源。
# bpy非依存の純粋関数モジュールなのでapp_py側から直接importしてよい
# (sway_chain_dialog.pyが同じ理由で既にimportしているパターンを踏襲)。)

LAB_FEATURE_ID = "sway_chains"
_STATE_FILENAME = "settings_lab_sway_chains.json"

HARDNESS_CHOICES = ("follow", "hard", "normal", "soft")

# dev#1551(安全域WP): 製品既定値そのもの。
# pipeline\blender\step02_retarget.pyのSWAY_DEFAULT_SAFETY_MARGINと
# 値を一致させること(GUI側の「既定」表示と実際の変換既定挙動を揃える
# ための唯一の真実の源はissue #1551オーナー裁定であり、両モジュールが
# それぞれこの定数を持つ——app_py側はpipeline側をimportしない設計方針
# (sway_chain_override_store.pyモジュールdocstring「tkinter非依存」参照)
# のため、意図的な重複)。
DEFAULT_SAFETY_MARGIN = 1
MAX_SAFETY_MARGIN = 9  # GUIスピンボックスの上限(常識的な範囲、暴走防止)


def _state_path(app_root: str) -> str:
    return os.path.join(app_root, _STATE_FILENAME)


def _norm_avatar_path(avatar_path: str) -> str:
    if not avatar_path:
        return ""
    try:
        return os.path.normcase(os.path.abspath(avatar_path))
    except (OSError, ValueError):
        return os.path.normcase(avatar_path)


def _default_enabled_for_bones(bones: List[str]) -> bool:
    """非manualエントリの旧既定enabled値(dev#1438、名前ベース)。bonesは
    [anchor, node1, node2, ...]の形(sway_chain_dialog._flatten_physbone_
    entries()/entry["bones"]と同じ意味論、bones[0]がanchor)。

    dev#1572第3便(issue #1572追記「チェインの揺れ設定問題1・2」)以降、
    真の既定enabled(実際にパイプラインが揺らすかどうか)は`pipeline\\py\\
    sway_chain_defaults.is_default_enabled()`(偏向判定ベース)へ移行済み
    ——**本関数は、呼び出し側がPB/SBパラメータへアクセスできず
    `default_enabled_map`を渡せない場面専用の後方互換フォールバックとして
    のみ残す**(下記`_is_default_entry()`のdefault_enabled_map未指定時、
    および既存の凍結UI`ui\\sway_chain_dialog.py`からの呼び出し)。新規の
    呼び出し元は必ず`default_enabled_map`(bonesタプル->bool、算出元は
    `sway_chain_defaults.is_default_enabled()`)を渡すこと——このモジュール
    自身はPB/SBパラメータを持たないため、偏向判定そのものをここで行う
    ことはできない(構造的な理由、二重実装ではなく情報が無いだけ)。"""
    if not bones:
        return False
    return sway_identify.default_sway_enabled(bones[0], bones[1:])


def _is_default_entry(
    entry: Dict[str, Any],
    default_enabled_map: Optional[Dict[Any, bool]] = None,
) -> bool:
    """`default_enabled_map`(dev#1572第3便、任意): `{tuple(bones): bool}`
    形式で、`sway_chain_defaults.is_default_enabled()`(偏向判定ベース、
    唯一の真実の源)から算出した既定enabledを渡せる。エントリのbonesが
    このmapに載っていればそちらを使い、載っていない/mapそのものが
    Noneなら旧来の名前ベースフォールバック(`_default_enabled_for_bones()`、
    後方互換)を使う。"""
    if entry.get("manual", False):
        # 手動追加チェーンは存在すること自体が既定からの逸脱(冒頭コメント
        # 参照)なので、他条件を見るまでもなく常に非既定。
        return False
    bones = entry.get("bones") or []
    default_enabled = None
    if default_enabled_map is not None:
        default_enabled = default_enabled_map.get(tuple(bones))
    if default_enabled is None:
        default_enabled = _default_enabled_for_bones(bones)
    return (
        bool(entry.get("enabled", True)) == default_enabled
        and entry.get("hardness", "follow") == "follow"
        and int(entry.get("safety_margin", DEFAULT_SAFETY_MARGIN)) == DEFAULT_SAFETY_MARGIN
    )


def _sanitize_safety_margin(value: Any) -> int:
    """dev#1551: 壊れた値(非数値・範囲外)は既定値へ丸める(安全側、
    equipment_filter_store.py等の既存catalogが例外を投げない三点セット
    方針と同じ)。"""
    try:
        margin = int(value)
    except (TypeError, ValueError):
        return DEFAULT_SAFETY_MARGIN
    return max(0, min(MAX_SAFETY_MARGIN, margin))


def _sanitize_entry(entry: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    bones = entry.get("bones")
    if not isinstance(bones, list) or not bones or not all(
        isinstance(b, str) and b for b in bones
    ):
        return None
    hardness = entry.get("hardness", "follow")
    if hardness not in HARDNESS_CHOICES:
        hardness = "follow"
    return {
        "bones": list(bones),
        "enabled": bool(entry.get("enabled", True)),
        "hardness": hardness,
        "manual": bool(entry.get("manual", False)),
        "safety_margin": _sanitize_safety_margin(
            entry.get("safety_margin", DEFAULT_SAFETY_MARGIN)),
    }


def load_config(
    app_root: str, avatar_path: str,
    default_enabled_map: Optional[Dict[Any, bool]] = None,
) -> List[Dict[str, Any]]:
    """保存済みの「既定から変わっているチェーン」一覧。ファイル不在/壊れて
    いる/形式が違う場合、および保存時のavatar_pathが現在のavatar_pathと
    一致しない(別アバター編集時の残留)場合はいずれも空リスト(=ラボ憲章④
    の既定値、安全側)。

    dev#1595(issue #1595)以降、ここでは既定との再間引きを**行わない**。
    ファイルに載っているエントリは、保存時(save_config())の時点で既に
    「非既定」と確定済みのもの(ラボ憲章④の間引きは保存側の責務、モジュール
    docstring「dev#1595」節参照)。読込側で再度`_is_default_entry()`を
    かけると、保存時と異なる既定判定(呼び出し元ごとに渡すdefault_enabled_map
    が違う、あるいは省略時は名前ベースフォールバック)によって、正しく
    保存されたはずのユーザー上書きが誤って消える恐れがある——実際に
    `pipeline_runner.write_job()`がmap無しでこの関数を呼んでいたため、GUI側
    (偏向判定ベースのmapで正しく保存済み)のOFF上書きが変換ジョブから脱落
    する不具合が起きていた(issue #1595)。

    `default_enabled_map`引数は既存呼び出し元
    (`app_py\\ui\\sway_style_dialog.py`・関連テスト)との互換のため残すが、
    もう使われない(渡しても渡さなくても結果は同じ)。"""
    path = _state_path(app_root)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    if _norm_avatar_path(data.get("avatar_path", "")) != _norm_avatar_path(avatar_path):
        return []
    raw_chains = data.get("chains")
    if not isinstance(raw_chains, list):
        return []
    out = []
    for raw in raw_chains:
        parsed = _sanitize_entry(raw)
        if parsed is not None:
            out.append(parsed)
    return out


def save_config(
    app_root: str, avatar_path: str, chains: List[Dict[str, Any]],
    default_enabled_map: Optional[Dict[Any, bool]] = None,
) -> None:
    """呼び出し側(ダイアログ)は現在の作業中セット全件(既定のままの行も
    含めてよい)を渡してよい――ここで既定と完全一致するエントリを間引いて
    から保存する(ラボ憲章④)。書き込み失敗は握りつぶす
    (equipment_filter_store.pyと同じ方針)。

    `default_enabled_map`: `load_config()`と同じ(dev#1572第3便、任意、
    省略時は名前ベースフォールバック)。"""
    cleaned = []
    for raw in chains:
        parsed = _sanitize_entry(raw)
        if parsed is not None and not _is_default_entry(parsed, default_enabled_map):
            cleaned.append(parsed)
    path = _state_path(app_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "avatar_path": _norm_avatar_path(avatar_path) if cleaned else "",
                    "chains": cleaned,
                },
                f, ensure_ascii=False, indent=1,
            )
    except OSError:
        pass


def clear_avatar(app_root: str, avatar_path: str) -> None:
    """このアバターの保存済み設定だけを既定へ戻す(ダイアログの「既定値に
    戻す」ボタン用。他アバターの保存は触らない)。"""
    save_config(app_root, avatar_path, [])


def reset(app_root: str) -> None:
    """dev#1186レジストリ記述子の「既定値リセット関数」。ラボ窓の
    『全てのラボ機能を無効化』ボタンから呼ばれる想定。avatar_path問わず
    全消去する(mesh_delete_store.reset()と同じ流儀)。"""
    path = _state_path(app_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"avatar_path": "", "chains": []}, f, ensure_ascii=False)
    except OSError:
        pass


def is_active(app_root: str, avatar_path: str) -> bool:
    """ラボ機能が既定から変更されているか(=現在のアバターに対して1件以上
    カスタマイズ済みか)。"""
    return bool(load_config(app_root, avatar_path))


def state_summary(app_root: str, avatar_path: str, lang: Optional[str] = None) -> Optional[str]:
    """dev#1186レジストリ記述子の「状態サマリ関数」。無効(未指定/別アバター
    の残留)ならNone、有効なら短い概要(lab_window.py側が『有効: <この文字列>』
    へ整形する想定)。"""
    n = len(load_config(app_root, avatar_path))
    if n == 0:
        return None
    return i18n.S("LabSwayChainSummaryFormat", lang).format(n)
