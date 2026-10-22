# sway_styles_store.py -- ラボ「ゆれかた」統合パネル(dev#19/#1423研究完了後の
# 最終仕様、.devonly\docs\sway\sway_wrapup\SPEC.md §2、2026-08-16 WP wp_sway_panel)の設定値
# 永続化ロジック(tkinter非依存)。
#
# 旧2機能を統合する:
#   - app_py\sway_chain_override_store.py (「揺れもの詳細設定」、鎖単位の
#     ON/OFF+4段かたさ)
#   - app_py\lab_raw_sway_params_store.py (「生パラメータ調整」、family
#     (tail/ear)単位の5パラメータ生値)
# 両ストア・両ダイアログは本WPでは一切変更しない(書き込み禁止、SPEC.md §2冒頭
# 「旧2ストアからマイグレーション」「旧ストアファイルは残す(消さない)」)。
#
# **データモデル**:
#   - 「ゆれかた」= 名前つきパラメータセット(SPEC.md §2)。
#     組み込み3種(soft/normal/hard、下記BUILTIN_STYLE_PARAMS)は固定値の
#     読み取り専用プリセットで、ディスクへは保存しない(定数のみ)。
#     カスタムは個数上限なし(2026-08-16オーナー裁定でSPEC.md §2原文の
#     「最大9個」制限を撤廃。同時に効かせられるのは9スロットまでという
#     制約はそのまま残るが、それは割当[assignments]側の制約であり、
#     「定義できる個数」自体は制限しない)、ユーザーが自由に作成・編集する
#     (custom_styles: name -> 10キー params dict、アバターに依存しないグローバル
#     データ)。
#   - 「割当」= 鎖(bones配列)ごとに、どの「ゆれかた」を使うか
#     (assignments: [{"bones":[...], "style": name}, ...]、name は
#     BUILTIN_STYLE_NAMES ∪ custom_styles のキーのいずれか。"none"/未割当の
#     鎖はここに現れない――絶対に保存しない、下記「意味論」参照)。
#     鎖のボーン名は入力アバターのスケルトンに依存するため、sway_chain_
#     override_store.py と同じ「直前に編集したavatar_pathとの組」方式で
#     アバター単位に保存する(avatar_path不一致時は残留として無視、
#     mesh_delete_store.pyコメント踏襲)。
#
# **意味論(ラボ憲章④の核)**:
#   - 「ゆれかた」の割当は完全な明示的上書きである。ある鎖がassignmentsに
#     現れない(=未割当)ならば、本パネルはその鎖について一切意見を持たない
#     ――将来のパイプライン結線(SPEC.md §5「工事項目」)は、その鎖を標準機能
#     「ゆらす」(SPEC.md §1、自動対象決定)にそのまま委ねる想定。
#   - style="none"(なし、ドロップダウンの既定表示)は「未割当」と同じ意味
#     であり、保存時は常に間引かれる(assignmentsには絶対に現れない)。
#     したがって「新規に開いて何も変更せずOK」は必ず既定状態(ファイル不在
#     または空)のまま――ラボ憲章④(既定値のときは未実装状態と完全に同一)
#     が、鎖の個数や候補判定ロジック(まだ実装されていない自動アロケータ、
#     SPEC.md §1.3量子化しきい値等)に一切依存せず機械的に保証される
#     (本モジュールは意図して"native donor rule"の既定ON/OFF判定
#     [pipeline\py\sway_identify.py]を複製しない――複製すると、そのロジックが
#     将来変わるたびに本ストアの「既定」の意味も変わってしまう。唯一の
#     「既定」は「assignments/custom_stylesが空」であり、それ以外ではない)。
#   - job設定への出力キーは "lab_sway_styles"(SPEC.md §2「job設定への出力」)。
#     get_job_override()は、現在のアバターについてassignmentsが1件以上ある
#     ときだけ辞書を返す(空ならNone、job.jsonにキー自体が現れない)。
#     custom_stylesを定義しただけで、どの鎖にも割り当てていない場合は
#     job出力に一切現れない(定義だけのカスタムは将来の消費側にとって
#     無意味な情報であり、④の「既定値のとき出力ゼロ」を鎖割当の有無だけで
#     判定できるようにするための意図的な設計、work\wp_sway_panel\BRIEF.md
#     受入ゲート1の解釈)。
#
# **job出力スキーマ**(SPEC.md §2の内容を全て運べる形、docstring明記
# ――パイプライン側の消費結線は本WPのスコープ外、後続工事):
#   job["lab_sway_styles"] = {
#     "styles": {
#         name: {  # 実際に割り当てられているゆれかたのみ(組み込み含む)
#             "stiffness": float(0-1), "damping": float(0-1),
#             "wdl": float(0-1), "wdr": float(0-1),
#             "gravity_z": float(-980-980), "limit_angle": float(0-180),
#             "fake_pitch": float(deg), "fake_roll": float(deg), "fake_yaw": float(deg),
#             # radiusは含めない(2026-08-16指揮者追送: コライダー調査完了、
#             # コライダーコピーは放棄確定、現状ゼロ効果が実測確定したため。
#             # 将来必要になれば別途追加する)。
#         }, ...
#     },
#     "assignments": [{"bones": [anchor, node1, ...], "style": name}, ...],
#   }
#
# **マイグレーション**(SPEC.md §2「旧2ストアからマイグレーション」、初回
# ロード時のみ・一方向): `load_state_with_migration()`を参照。
from __future__ import annotations

import copy
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)
_ROOT_DIR = os.path.dirname(_APP_PY_DIR)
_PIPELINE_PY_DIR = os.path.join(_ROOT_DIR, "pipeline", "py")
if _PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_PY_DIR)

import i18n  # noqa: E402
import sway_identify  # noqa: E402  (マイグレーション専用: 尻尾/耳同定の唯一の
# 真実の源。tkinter非依存の純粋関数モジュールなので、sway_chain_override_store.py
# と同じ理由でapp_py側から直接importしてよい)。

# マイグレーション元の2ストア(読み取り専用でimportするだけ――このモジュールが
# それらのファイルへ書き込むことは無い。両モジュールともtkinterに依存しない
# ため、本ストアをpipeline_runner.py等のヘッドレス経路からimportしても
# tkinterの依存が混ざらない、既存2ストアと同じ設計を維持する)。
import lab_raw_sway_params_store  # noqa: E402
import sway_chain_override_store  # noqa: E402

LAB_FEATURE_ID = "sway_styles"
_STATE_FILENAME = "settings_lab_sway_styles.json"

# ---------------------------------------------------------------------------
# パラメータスキーマ(SPEC.md §2「ゆれかた」定義)。
# ---------------------------------------------------------------------------

STYLE_PARAM_KEYS: Tuple[str, ...] = (
    "stiffness", "damping", "wdl", "wdr", "gravity_z", "limit_angle",
    "fake_pitch", "fake_roll", "fake_yaw",
)
# 2026-08-16 指揮者追送(仕様確定の禁止事項追加、work\sway_collider_survey\の
# コライダー調査完了を受けて): コライダーコピーは放棄確定・radiusは現状
# ゼロ効果が実測確定したため、ゆれかた編集UI・本ストアのスキーマいずれにも
# radiusを含めない(SPEC.md §2原文はradius項目を含んでいたが、この追送で
# 上書きされた)。将来必要になれば改めて追加する。

PARAM_RANGES: Dict[str, Tuple[float, float]] = {
    "stiffness": (0.0, 1.0),
    "damping": (0.0, 1.0),
    "wdl": (0.0, 1.0),
    "wdr": (0.0, 1.0),
    "gravity_z": (-980.0, 980.0),
    "limit_angle": (0.0, 180.0),
    # FakePitch擬似3値(SPEC.md §2): 度数。既定0=恒等=完全no-op。範囲はSPEC.mdに
    # 明記が無いため、3D回転オフセットとして意味を持つ全周を許容する
    # (実装者解釈、完了報告に記載)。
    "fake_pitch": (-180.0, 180.0),
    "fake_roll": (-180.0, 180.0),
    "fake_yaw": (-180.0, 180.0),
}

_ZERO_PARAMS: Dict[str, float] = {k: 0.0 for k in STYLE_PARAM_KEYS}

# 組み込み3種(SPEC.md §1「プリセット値」damping/stiffness/wdの順で明記された
# ものを、STYLE_PARAM_KEYS順のdictへ変換。wd値はwdl・wdr共通(旧lab_raw_sway_
# params_store/旧sway_abp_build.pyと同じ「wdl・wdrへ同じ値を書く」踏襲)。
# fake_pitch/roll/yawはSPEC.mdに規定が無いため0(=no-op)。
BUILTIN_STYLE_NAMES: Tuple[str, ...] = ("soft", "normal", "hard")

BUILTIN_STYLE_PARAMS: Dict[str, Dict[str, float]] = {
    "soft": {**_ZERO_PARAMS, "damping": 0.25, "stiffness": 0.05, "wdl": 0.0, "wdr": 0.0},
    "normal": {**_ZERO_PARAMS, "damping": 0.08, "stiffness": 0.20, "wdl": 0.0, "wdr": 0.0},
    "hard": {**_ZERO_PARAMS, "damping": 0.30, "stiffness": 0.30, "wdl": 0.3, "wdr": 0.3},
}

# "none"は「なし」(未割当と同義)のセンチネル。BUILTIN_STYLE_PARAMSには含めない
# (paramsを持たない、選べるが保存されない値であるため)。
NONE_STYLE = "none"

RESERVED_STYLE_NAMES = frozenset({NONE_STYLE, *BUILTIN_STYLE_NAMES})

# マイグレーション専用: 旧「揺れの度合い」グローバル設定(app_py\ui\main_window.py
# SWAY_INTENSITY_VALUES/_SWAY_INTENSITY_DEFAULT_INDEX)の既定値。main_window.py
# は書き込み禁止対象かつ巨大なtkinter GUIモジュールのため、値そのものを本ストア
# へ複製する(main_window.pyをimportしない――層分離を壊さないため)。
# 2026-08-16時点の値: _SWAY_INTENSITY_DEFAULT_INDEX = SWAY_INTENSITY_VALUES
# .index("normal") = 2 (main_window.py L.183/187)。ライブのユーザー設定値は
# 永続化されたファイルから読めない(tk.Scaleウィジェットの初期値でしかない)
# ため、「現グローバル強度相当」(SPEC.md §2冒頭)はこの既定値で近似する
# (実装者解釈、完了報告に記載)。
_LEGACY_GLOBAL_INTENSITY_DEFAULT = "normal"


def _state_path(app_root: str) -> str:
    return os.path.join(app_root, _STATE_FILENAME)


def _norm_avatar_path(avatar_path: str) -> str:
    if not avatar_path:
        return ""
    try:
        return os.path.normcase(os.path.abspath(avatar_path))
    except (OSError, ValueError):
        return os.path.normcase(avatar_path)


def _clamp(key: str, value: float) -> float:
    lo, hi = PARAM_RANGES[key]
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _sanitize_params(raw: Any) -> Optional[Dict[str, float]]:
    """壊れた/部分的なparams dictを、STYLE_PARAM_KEYS全キー・クランプ済みの
    完全なdictへ直す。個別キー欠落/非数値はそのキーだけ0.0へフォールバック
    (lab_raw_sway_params_store._sanitize系と同じ多重防御方針)。raw自体が
    dictでなければNone。"""
    if not isinstance(raw, dict):
        return None
    out = dict(_ZERO_PARAMS)
    for key in STYLE_PARAM_KEYS:
        if key not in raw:
            continue
        v = raw[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        out[key] = _clamp(key, float(v))
    return out


def _is_valid_custom_name(name: Any) -> bool:
    return isinstance(name, str) and bool(name) and name not in RESERVED_STYLE_NAMES


def _sanitize_custom_styles(raw: Any) -> Dict[str, Dict[str, float]]:
    """カスタム「ゆれかた」定義の個数に上限は無い(2026-08-16オーナー裁定で
    SPEC.md §2原文の「最大9個」を撤廃)。同時に効かせられるスロット数
    (親骨×ゆれかたで9組まで)は割当[assignments]側の制約であり、ここでは
    関知しない。"""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, float]] = {}
    for name, params in raw.items():
        if not _is_valid_custom_name(name):
            continue
        parsed = _sanitize_params(params)
        if parsed is None:
            continue
        out[name] = parsed
    return out


def _sanitize_assignment(entry: Any, valid_style_names: Sequence[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    bones = entry.get("bones")
    if not isinstance(bones, list) or not bones or not all(
        isinstance(b, str) and b for b in bones
    ):
        return None
    style = entry.get("style")
    if style not in valid_style_names:
        return None
    return {"bones": list(bones), "style": style}


def _sanitize_assignments(
    raw: Any, custom_style_names: Sequence[str]
) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    valid_names = list(BUILTIN_STYLE_NAMES) + list(custom_style_names)
    out = []
    seen_bones: set = set()
    for item in raw:
        parsed = _sanitize_assignment(item, valid_names)
        if parsed is None:
            continue
        key = tuple(parsed["bones"])
        if key in seen_bones:
            continue  # 重複bones配列は最初の1件を採用(壊れたファイルへの多重防御)
        seen_bones.add(key)
        out.append(parsed)
    return out


def _load_raw(app_root: str) -> Dict[str, Any]:
    path = _state_path(app_root)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def load_custom_styles(app_root: str) -> Dict[str, Dict[str, float]]:
    """カスタム「ゆれかた」定義(アバターに依存しないグローバルデータ)。
    ファイル不在/壊れている場合は空dict(ラボ憲章④の安全側既定)。"""
    return _sanitize_custom_styles(_load_raw(app_root).get("custom_styles"))


def load_assignments(app_root: str, avatar_path: str) -> List[Dict[str, Any]]:
    """現在のavatar_pathに対する保存済み割当一覧。保存時のavatar_pathと
    一致しない(別アバター編集時の残留)場合は空リスト(sway_chain_override_
    store.load_config()と同じ方針)。割当先のstyle名がcustom_stylesに
    実在しない(削除済み等)場合は自動的に除外する(id参照整合性の多重防御)。"""
    data = _load_raw(app_root)
    if _norm_avatar_path(data.get("avatar_path", "")) != _norm_avatar_path(avatar_path):
        return []
    custom_names = list(load_custom_styles(app_root).keys())
    return _sanitize_assignments(data.get("assignments"), custom_names)


def save_state(
    app_root: str,
    avatar_path: str,
    custom_styles: Dict[str, Dict[str, float]],
    assignments: List[Dict[str, Any]],
) -> None:
    """呼び出し側(ダイアログ)は現在の作業中セット全件(style="none"の行を
    含めてよい)を渡してよい――ここでcustom_stylesの形式検証+assignments中の
    style="none"/無効な割当の間引きを行ってから保存する(ラボ憲章④、
    sway_chain_override_store.save_config()と同じ「間引きはストア側の責務」
    方針)。書き込み失敗は握りつぶす(既存storeと同じ方針)。

    dev#1551 laneG5修理(work\\run_1551\\gui_verify\\RESULT.md追送、
    コーディネータ確定裁定2026-08-17、症状③「既定値に戻す→TailRootまで
    消える」の根本原因): 間引き後にcustom_styles・assignmentsの両方が
    空になる場合(=保存すべき内容が実質何も無い)は、空のJSONを書くのでは
    なく状態ファイル自体を削除する。空JSONを書いてしまうと
    `load_state_with_migration()`の「一度でも保存されたか」判定
    (`os.path.exists(_state_path(app_root))`のみを見る)が誤って真になり、
    native-donor-rule既定の一回限りの自動移行が(このアバターに限らず
    将来のどのアバターに対しても)恒久的にブロックされてしまう
    ――「既定値に戻す」という操作が、逆に二度と既定へ戻れない状態を
    作り出してしまう構造的バグだった。ファイルを削除すれば
    `os.path.exists()`が偽に戻り、次回のダイアログオープン時に移行が
    正しく再実行される(=既定[native-donor-ruleの尻尾/耳]が復元される)。"""
    cleaned_styles = _sanitize_custom_styles(custom_styles)
    custom_names = list(cleaned_styles.keys())
    valid_names = list(BUILTIN_STYLE_NAMES) + custom_names
    cleaned_assignments = []
    seen_bones: set = set()
    for raw in (assignments or []):
        if not isinstance(raw, dict):
            continue
        if raw.get("style") == NONE_STYLE:
            continue  # 「なし」=未割当は保存しない(意味論の核)
        parsed = _sanitize_assignment(raw, valid_names)
        if parsed is None:
            continue
        key = tuple(parsed["bones"])
        if key in seen_bones:
            continue
        seen_bones.add(key)
        cleaned_assignments.append(parsed)

    path = _state_path(app_root)
    if not cleaned_styles and not cleaned_assignments:
        try:
            os.remove(path)
        except OSError:
            pass  # 元々存在しない(既に「未保存」状態)ケースを含め、無視でよい
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "custom_styles": cleaned_styles,
                    "avatar_path": _norm_avatar_path(avatar_path) if cleaned_assignments else "",
                    "assignments": cleaned_assignments,
                },
                f, ensure_ascii=False, indent=1,
            )
    except OSError:
        pass


def clear_avatar_assignments(app_root: str, avatar_path: str) -> None:
    """このアバターの鎖割当だけを空にする(ダイアログの「このアバターの設定を
    既定値に戻す」ボタン用)。custom_styles(グローバル、他アバターでも使う
    再利用可能な定義)は保持する――sway_chain_override_store.clear_avatar()
    と同じ「アバター固有データだけ消す」方針だが、本ストアはさらに
    グローバルなカスタム定義を持つ点が異なるため、reset()(全消去)とは
    別の関数として用意する。"""
    custom_styles = load_custom_styles(app_root)
    save_state(app_root, avatar_path, custom_styles, [])


def reset(app_root: str) -> None:
    """dev#1186レジストリ記述子の「既定値リセット関数」。カスタム定義・
    現在アバターの割当いずれも全消去する(mesh_delete_store.reset()と同じ
    流儀、avatar_path問わず全消去)。

    dev#1551 laneG5修理(save_state()のdocstring参照、症状③の根本原因):
    空JSONを書くのではなく状態ファイル自体を削除する――理由はsave_state()の
    「実質空なら削除」分岐と同一(os.path.exists()ベースの一回限り移行判定を
    誤らせない)。"""
    path = _state_path(app_root)
    try:
        os.remove(path)
    except OSError:
        pass  # 元々存在しない場合を含め無視でよい(mesh_delete_store.reset()と同じ方針)


def is_active(app_root: str, avatar_path: str) -> bool:
    """本ラボ機能が現在のアバターに対して機能的な効果を持つか
    (=1件以上の鎖割当が現在のアバターに保存されているか)。カスタム定義
    だけが存在し、どの鎖にも割り当てられていない状態は「アバターへの
    効果ゼロ」であり非アクティブ扱いとする(BRIEF受入ゲート1の解釈、
    get_job_override()と同じ判定基準に揃える)。"""
    return bool(load_assignments(app_root, avatar_path))


def state_summary(app_root: str, avatar_path: str, lang: Optional[str] = None) -> Optional[str]:
    """dev#1186レジストリ記述子の「状態サマリ関数」。無効ならNone、有効なら
    短い概要(現在アバターの割当件数)。"""
    n = len(load_assignments(app_root, avatar_path))
    if n == 0:
        return None
    return i18n.S("LabSwayStyleSummaryFormat", lang).format(n)


def resolve_style_params(app_root: str, style_name: str) -> Optional[Dict[str, float]]:
    """style_name(組み込み or カスタム)の実パラメータを解決する。"none"や
    未知の名前はNone。"""
    if style_name in BUILTIN_STYLE_PARAMS:
        return dict(BUILTIN_STYLE_PARAMS[style_name])
    custom = load_custom_styles(app_root)
    if style_name in custom:
        return dict(custom[style_name])
    return None


def get_job_override(app_root: str, avatar_path: str) -> Optional[Dict[str, Any]]:
    """pipeline_runner.write_job()向け(本WPでは未結線、後続工事): 既定
    (現在アバターへの割当が0件)ならNone(job.jsonへキー自体を書かせない)、
    非既定なら {"styles": {...実際に使われているゆれかたのみ...},
    "assignments": [...]} の完全なdict。"""
    assignments = load_assignments(app_root, avatar_path)
    if not assignments:
        return None
    custom_styles = load_custom_styles(app_root)
    used_names = {a["style"] for a in assignments}
    styles_out: Dict[str, Dict[str, float]] = {}
    for name in used_names:
        if name in BUILTIN_STYLE_PARAMS:
            styles_out[name] = dict(BUILTIN_STYLE_PARAMS[name])
        elif name in custom_styles:
            styles_out[name] = dict(custom_styles[name])
    return {"styles": styles_out, "assignments": [dict(a) for a in assignments]}


# ---------------------------------------------------------------------------
# マイグレーション(SPEC.md §2「旧2ストアからマイグレーション」、一方向・
# 初回ロード時のみ)。
# ---------------------------------------------------------------------------

def _migrated_family_style_name(family: str) -> str:
    family_key = {
        "tail": "LabRawSwayParamsFamilyTail", "ear": "LabRawSwayParamsFamilyEar",
    }.get(family, family)
    family_label = i18n.S(family_key)
    return i18n.S("LabSwayStyleMigratedNameFormat").format(family_label)


def _family_params_to_style_params(fam_params: Dict[str, float]) -> Dict[str, float]:
    """lab_raw_sway_params_store の5キー(stiffness/damping/wd/gravity_z/
    limit_angle、wdはwdl・wdr共通値)を、新10キースキーマへ写像する
    (fake_*は未使用のため0)。"""
    out = dict(_ZERO_PARAMS)
    out["stiffness"] = _clamp("stiffness", fam_params.get("stiffness", 0.0))
    out["damping"] = _clamp("damping", fam_params.get("damping", 0.0))
    wd = _clamp("wdl", fam_params.get("wd", 0.0))
    out["wdl"] = wd
    out["wdr"] = wd
    out["gravity_z"] = _clamp("gravity_z", fam_params.get("gravity_z", 0.0))
    out["limit_angle"] = _clamp("limit_angle", fam_params.get("limit_angle", 0.0))
    return out


def _style_from_hardness(hardness: str) -> str:
    return hardness if hardness in BUILTIN_STYLE_NAMES else _LEGACY_GLOBAL_INTENSITY_DEFAULT


def _migrate_explicit_chain_overrides(
    app_root: str, avatar_path: str, catalog_chains: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """sway_chain_override_store由来のマイグレーション、**優先度1(最優先)**:
    ユーザーが実際に「揺れもの詳細設定」で触った鎖のみ(sway_chain_override_
    store.load_config()が返すエントリ――同ストアの仕様上、既定[native-donor
    ルールの既定ON/OFF・hardness="follow"]と完全一致するものは最初から
    保存されないため、ここに現れるエントリは全てユーザーの明示的操作の
    痕跡である)。SPEC.md §2「旧ONの鎖→現グローバル強度相当の組み込み
    ゆれかた」のうち、"旧ONの鎖"が明示操作によるものだけをここで扱う
    (何も触っていないのに既定でONな鎖は_migrate_implicit_native_donor_
    defaults()の役割――family単位の生パラメータ移行[優先度2]より先に
    「未操作の既定ON」で埋めてしまうと、後から来る生パラメータ移行が
    対象を奪われてしまうため、優先度を分離する)。"""
    overrides = sway_chain_override_store.load_config(app_root, avatar_path)
    catalog_by_bones = {tuple(c["bones"]): c for c in catalog_chains if c.get("bones")}
    out: List[Dict[str, Any]] = []
    for e in overrides:
        key = tuple(e.get("bones") or [])
        if not key:
            continue
        if not e.get("manual") and key not in catalog_by_bones:
            continue  # カタログから消えた古い保存データ(アバター差し替え等)
        if not bool(e.get("enabled", True)):
            continue  # SPEC.md §2は「旧ONの鎖」のみを移行対象とする
        style = _style_from_hardness(e.get("hardness", "follow"))
        out.append({"bones": list(key), "style": style})
    return out


def _migrate_implicit_native_donor_defaults(
    catalog_chains: Sequence[Dict[str, Any]], already_assigned: set,
) -> List[Dict[str, Any]]:
    """**優先度3(最後)**: ユーザーが一度も触っていない鎖のうち、
    sway_identify.default_sway_enabled()による既定(尻尾/耳)がONのものを
    "現グローバル強度相当"の組み込みゆれかたへ移行する。優先度1
    (明示的上書き)・優先度2(family別生パラメータ、_migrate_raw_params)の
    いずれにも拾われなかった鎖だけを対象にする(already_assignedで除外)。"""
    out: List[Dict[str, Any]] = []
    for c in catalog_chains:
        bones = c.get("bones")
        if not bones:
            continue
        key = tuple(bones)
        if key in already_assigned:
            continue
        anchor = c.get("anchor")
        if sway_identify.default_sway_enabled(anchor, list(bones[1:])):
            out.append({"bones": list(bones), "style": _LEGACY_GLOBAL_INTENSITY_DEFAULT})
    return out


def _migrate_raw_params(
    app_root: str, catalog_chains: Sequence[Dict[str, Any]], already_assigned: set,
) -> Tuple[Dict[str, Dict[str, float]], List[Dict[str, Any]]]:
    """lab_raw_sway_params_store由来のマイグレーション(SPEC.md §2「旧family
    別生パラメータ→カスタムゆれかた化」)。family(tail/ear)ごとに既定値と
    異なる場合のみカスタムスタイルを1件作成し、sway_identify.identify_
    sway_kind()でそのfamilyに同定されるカタログ鎖のうち、まだ
    _migrate_chain_overrides()で割当済みでないものへ割り当てる(鎖単位の
    明示的上書き[旧「揺れもの詳細設定」]の方が優先される、という旧2機能間
    の実際の優先関係[SPEC.md docstring "標準機能の「揺れの度合い」より
    優先されます"の踏襲=より具体的な設定が勝つ]をそのまま引き継ぐ)。"""
    raw_params = lab_raw_sway_params_store.load_params(app_root)
    custom_styles: Dict[str, Dict[str, float]] = {}
    assignments: List[Dict[str, Any]] = []
    for family in lab_raw_sway_params_store.FAMILIES:
        fam_params = raw_params.get(family)
        default_fam = lab_raw_sway_params_store.DEFAULT_PARAMS[family]
        if not fam_params or fam_params == default_fam:
            continue
        name = _migrated_family_style_name(family)
        custom_styles[name] = _family_params_to_style_params(fam_params)
        for c in catalog_chains:
            bones = c.get("bones")
            if not bones:
                continue
            key = tuple(bones)
            if key in already_assigned:
                continue
            anchor = c.get("anchor")
            if sway_identify.identify_sway_kind(anchor, list(bones[1:])) == family:
                assignments.append({"bones": list(bones), "style": name})
                already_assigned.add(key)
    return custom_styles, assignments


def migrate_from_legacy(
    app_root: str, avatar_path: str, catalog_chains: Sequence[Dict[str, Any]]
) -> Tuple[Dict[str, Dict[str, float]], List[Dict[str, Any]]]:
    """旧2ストアの現在値から、新スキーマの (custom_styles, assignments) を
    構築する純粋関数(ディスクへは一切書き込まない――呼び出し側
    [load_state_with_migration()/ダイアログのOK処理]が必要に応じて保存する)。
    catalog_chains は
    ui.sway_chain_dialog.query_sway_catalog() 等が返す
    [{"anchor":str,"bones":[anchor,node1,...],...}, ...] 形式(呼び出し側が
    用意する。本モジュールはtkinter/カタログ取得ロジックへ依存しない設計を
    維持するため、カタログの取得自体は呼び出し側[ダイアログ]の責務とする)。

    優先度(数字が小さいほど優先): ①鎖単位の明示的上書き(旧「揺れもの
    詳細設定」で実際に触った鎖) > ②family単位の生パラメータカスタム化
    (旧「生パラメータ調整」、その鎖がsway_identifyでそのfamilyに同定される
    場合) > ③何も触っていない鎖のnative-donor既定ON(尻尾/耳)。実装者解釈
    (完了報告に記載): SPEC.mdはこの3者の優先順位を明記していないが、
    「より具体的・より意図的な設定が勝つ」という自然な原則(既存2ダイアログ
    のヒント文言"標準機能の「揺れの度合い」より優先されます"が示す
    「個別設定 > 包括設定」の踏襲)に基づく。"""
    explicit_assignments = _migrate_explicit_chain_overrides(app_root, avatar_path, catalog_chains)
    already = {tuple(a["bones"]) for a in explicit_assignments}
    raw_styles, raw_assignments = _migrate_raw_params(app_root, catalog_chains, already)
    already |= {tuple(a["bones"]) for a in raw_assignments}
    implicit_assignments = _migrate_implicit_native_donor_defaults(catalog_chains, already)
    return raw_styles, explicit_assignments + raw_assignments + implicit_assignments


def load_state_with_migration(
    app_root: str, avatar_path: str, catalog_chains: Sequence[Dict[str, Any]]
) -> Tuple[Dict[str, Dict[str, float]], List[Dict[str, Any]]]:
    """ダイアログのオープン時に呼ぶ想定のエントリポイント(ダイアログの
    「作業中セット(working_styles/working_rows)」の初期値を計算するだけの
    **読み取り専用**関数――本関数自体はディスクへ一切書き込まない。

    新ストアの状態ファイルが**まだ一度も保存されていない**(=このダイアログ
    でOKが一度も押されていない)場合に限り、旧2ストアから初回マイグレー
    ションを行った結果を返す(SPEC.md §2「初回ロード時」)。ユーザーが
    その画面をそのままOKすれば、呼び出し側(ダイアログ)の通常のOK処理
    (save_state呼び出し)がこの結果をディスクへ確定させる――逆に×/
    キャンセルで閉じれば何も書き込まれない(既存の「OKで確定、キャンセル/
    ×で破棄」流儀[sway_chain_dialog.py等]をマイグレーション後の初期値にも
    そのまま適用するための設計。**ダイアログを開いただけ・見ただけで
    ディスクの状態が変わることは無い**――もし本関数がここで即座に保存
    していると、「気になって開いてすぐ閉じただけ」でも意図せず既定状態から
    逸脱してしまう[本WP実装中に単体テストで発見、完了報告に解釈として記載])。

    状態ファイルが既に存在する(=過去に一度でもOKされている)場合は、
    通常のload_custom_styles/load_assignmentsだけを返す(再マイグレーション
    はしない――ユーザーがその後に行った編集を上書きしないため)。"""
    if not os.path.exists(_state_path(app_root)):
        return migrate_from_legacy(app_root, avatar_path, catalog_chains)
    return load_custom_styles(app_root), load_assignments(app_root, avatar_path)


def style_choice_names(app_root: str) -> List[str]:
    """ダイアログのドロップダウン向け: [なし, soft, normal, hard, カスタム名...]
    の順(SPEC.md §2のドロップダウン列挙順どおり)。"""
    return [NONE_STYLE, *BUILTIN_STYLE_NAMES, *sorted(load_custom_styles(app_root).keys())]
