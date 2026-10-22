# sway_pb_catalog.py -- ラボ「揺れもの詳細」パネルのPB/SB単位(1コンポーネント=
# 1行)表示ヘルパ(dev#1508、列車計画W2c、.devonly\docs\sway\sway_pbunit_design\DESIGN.md §4-5)。
#
# 背景: `app_py\ui\sway_chain_dialog.py`(書き込み禁止)の`_flatten_physbone_entries()`
# は「1房=1行」に展開する旧粒度で、多房PB(スカート等)が房数ぶんバラけて表示される
# 問題があった(SPEC.md §2「1PB=1行」裁定、2026-08-16実試遊)。本モジュールは
# 「1PB/SBコンポーネント=1行」の新粒度への変換ロジックを、書き込み禁止対象の
# sway_chain_dialog.pyへ触れずに新設する(DESIGN.md §5段1の指定どおり)。
#
# **physbone_catalog.pyを経由しない理由**: `app_py\physbone_catalog.py`は搬送のみ
# (dev#1356の設計、docstring明記)であり、`_parse_entry()`は意図的に
# `{"anchor","chains"}`以外のキー(pb_object_name/pb_object_path/params等)を
# 落とす。この設計は`app_py\tests\test_physbone_export_pbunit_dev1508.py::
# test_existing_catalog_reader_still_ignores_new_fields_unchanged`が無退行として
# 明示的にロック済みであり、本WPはphysbone_catalog.pyを書き込み禁止として扱う。
# しかし本モジュールの表示名(pb_object_name)機能、および後続の「特殊ボーンを
# 強制セットアップ」機能(PB実値pull/spring/limit_type/limit_rotation/max_angle_x
# が必要)のどちらも、落とされたフィールドに依存する。そのため本モジュールは
# prefab側もphysbones.jsonサイドカーを独自に(最小限の検証つきで)直接読む
# ——`app_py\vrm_spring_catalog.py`が同じ理由でGLBコンテナ読み取りを独自実装
# している「複製流儀」(同ファイルdocstring「既存の複製流儀にならう」)に揃える。
# physbone_catalog.py自体は無改修(引き続きanchor/chainsのみを運ぶ既存契約を保つ)。
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)
_ROOT_DIR = os.path.dirname(_APP_PY_DIR)
_PIPELINE_PY_DIR = os.path.join(_ROOT_DIR, "pipeline", "py")
if _PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_PY_DIR)

import pipeline_runner  # noqa: E402  (resolve_unity_export_out_dir()の再利用のみ)
import vrm_spring_catalog  # noqa: E402  (VRM側: 既に pb_object_name/type/params
# 込みの上位互換スキーマで返す、dev#1508 W1b)
from ui import sway_chain_dialog as _legacy_chain_dialog  # noqa: E402  (読み取り
# 専用の再利用: SAMPLE_CHAINSのみ。sway_chain_dialog.py自体は書き込み禁止だが、
# importして定数を読むことは許容される[DESIGN.md §5段1の記載どおり]。)

import sway_allocator  # noqa: E402  (pipeline/py: 無偏向判定の唯一の真実の源。
# 2026-08-16オーナー口述指定「判定は sway_allocator.py の無偏向判定と同一規則を
# 使う[重複実装せず可能なら関数を利用]」に基づき、_judge_pb_bias()をそのまま
# 呼ぶ[test_sway_allocator.pyが同じ private関数を`# noqa: SLF001`付きで直接
# 呼ぶ既存慣例に揃える])。
import sway_quantize  # noqa: E402  (pipeline/py: quantize_pb())
import sway_styles_store  # noqa: E402  (BUILTIN_STYLE_PARAMS/PARAM_RANGES/
# STYLE_PARAM_KEYSの再利用。書き込みはしない、読み取りのみ)

FORMAT_ID = "divetopalworld-physbones-1"

# ---------------------------------------------------------------------------
# $GUID尾の表示用削り(DESIGN.md §6-2、新設。既存devtools\replay\bone_names.py
# は大文字小文字正規化専用で削り機能を持たないため、混同を避けて新設する)。
# ---------------------------------------------------------------------------

# 実データ(work\flatHaori_export\physbones.json)で確認した形式:
#   "Lower Arm.L.001$8aba0be2-2624-4628-8e98-ee7c23bd55fc"
# Modular Avatarが内部処理(Bone Proxy/Merge Armature等)で付与するとみられる
# 標準UUID形式(8-4-4-4-12桁の16進)の尾のみを対象にする、保守的な正規表現
# (DESIGN.md §6-2「発生源未確認のため広く$以降を削らない」)。表示専用――
# 内部キー・保存データ(working_rows/assignments)は生の名前のまま扱うこと。
_GUID_TAIL_RE = re.compile(
    r"\$[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)


def strip_guid_tail(name: Optional[str]) -> str:
    """骨名末尾の"$<GUID>"尾を表示用にのみ削る。一致しなければ元の文字列を
    そのまま返す(負の対照: 非GUID形の$接尾辞・$の無い名前は変化しない)。"""
    if not name:
        return name or ""
    return _GUID_TAIL_RE.sub("", name)


# ---------------------------------------------------------------------------
# PB単位フラット化(DESIGN.md §4.2、1コンポーネント=1行)。
# ---------------------------------------------------------------------------

def flatten_physbone_units(entries: List[dict]) -> List[Dict[str, Any]]:
    """physbone_catalog/vrm_spring_catalog系の{"anchor","chains":[[...]],...}
    形式(1コンポーネント=1エントリ、複数chains可)を、UIが扱う「1PB/SB=1行」
    のユニットリストへ変換する(旧sway_chain_dialog._flatten_physbone_entries()
    の「1房=1行」展開はしない――ここが本モジュールの核)。

    各ユニット: {
      "type": "physbone" | "springbone",
      "anchor": str,
      "display_name": str,   # pb_object_name(あれば、GUID尾を削って表示用に
                              # 正規化)、無ければanchor(同じくGUID尾を削る)
      "chains": [[str,...], ...],
      "chain_count": int,
      "bone_count": int,
      "params": dict | None,
    }
    不正なエントリ(anchor欠落・chains空)はスキップする(physbone_catalog.py
    の_parse_entry()と同じ安全側方針)。"""
    units: List[Dict[str, Any]] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        anchor = entry.get("anchor")
        if not isinstance(anchor, str) or not anchor:
            continue
        raw_chains = entry.get("chains")
        if not isinstance(raw_chains, list):
            continue
        chains: List[List[str]] = []
        for chain in raw_chains:
            if not isinstance(chain, list) or not chain:
                continue
            if not all(isinstance(b, str) and b for b in chain):
                continue
            chains.append(list(chain))
        if not chains:
            continue
        pb_object_name = entry.get("pb_object_name")
        base = pb_object_name if isinstance(pb_object_name, str) and pb_object_name else anchor
        units.append({
            "type": entry.get("type") or "physbone",
            "anchor": anchor,
            "display_name": strip_guid_tail(base),
            "chains": chains,
            "chain_count": len(chains),
            "bone_count": sum(len(c) for c in chains),
            "params": entry.get("params") if isinstance(entry.get("params"), dict) else None,
        })
    return units


# ---------------------------------------------------------------------------
# カタログ取得(prefab: 独自サイドカー読み取り / VRM: vrm_spring_catalog直結)。
# ---------------------------------------------------------------------------

def _read_prefab_sidecar_raw(sidecar_path: str) -> dict:
    """physbones.jsonサイドカーを直接読む(モジュールdocstring上部「
    physbone_catalog.pyを経由しない理由」参照)。{"ok","detail","physbones"}
    の三点セット形式で返す(例外を投げない)。"""
    if not sidecar_path or not os.path.isfile(sidecar_path):
        return {"ok": False, "detail": f"sidecar not found: {sidecar_path}", "physbones": []}
    try:
        with open(sidecar_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}", "physbones": []}
    if not isinstance(data, dict):
        return {"ok": False, "detail": "sidecar is not a JSON object", "physbones": []}
    raw_entries = data.get("physbones")
    if not isinstance(raw_entries, list):
        return {"ok": False, "detail": "sidecar has no 'physbones' list", "physbones": []}
    return {"ok": True, "detail": f"read {sidecar_path}", "physbones": raw_entries}


def query_sway_pb_units(app_root: str, work_root: str, avatar_path: str) -> dict:
    """入力アバターのPB/SBユニット一覧を取得する。戻り値は常に
    {"ok": bool, "source": str, "detail": str, "units": [...]}
    (sway_chain_dialog.query_sway_catalog()と同じ三点セット方針、例外を
    投げない)。"""
    if not avatar_path or not os.path.exists(avatar_path):
        return {"ok": False, "source": "none",
                "detail": f"avatar not selected or not found: {avatar_path!r}", "units": []}

    ext = os.path.splitext(avatar_path)[1].lower()

    if ext == ".vrm":
        result = vrm_spring_catalog.catalog_from_vrm(avatar_path)
        units = flatten_physbone_units(result.get("physbones") or [])
        return {"ok": bool(result.get("ok")) and bool(units), "source": "vrm",
                "detail": result.get("detail", ""), "units": units}

    if ext == ".prefab":
        out_dir = pipeline_runner.resolve_unity_export_out_dir(work_root, avatar_path)
        sidecar = os.path.join(out_dir, "physbones.json")
        result = _read_prefab_sidecar_raw(sidecar)
        units = flatten_physbone_units(result.get("physbones") or [])
        return {"ok": bool(result.get("ok")) and bool(units), "source": "prefab",
                "detail": result.get("detail", ""), "units": units}

    return {"ok": False, "source": "none",
            "detail": f"unsupported avatar extension for sway pb enumeration: {ext!r}",
            "units": []}


def sample_pb_units() -> List[Dict[str, Any]]:
    """開発確認用(--sampleフラグ)。sway_chain_dialog.SAMPLE_CHAINS(1チェーン=
    1行の旧フラット形式)を、各行=単房のPBエントリへ機械変換してから
    flatten_physbone_units()へ通す(1:1対応を保つことで、既存ダイアログ
    テストの行数・表示名の期待値を変えない――多房PBの実際の挙動[複数房が
    1行に束ねられること]は本モジュールの単体テストで別途検証する)。"""
    entries = []
    for c in _legacy_chain_dialog.SAMPLE_CHAINS:
        bones = c["bones"]
        entries.append({"anchor": bones[0], "chains": [list(bones[1:])]})
    return flatten_physbone_units(entries)


# ---------------------------------------------------------------------------
# 表示ラベル(曖昧解消、i18n非依存の基本部分のみ)。
# ---------------------------------------------------------------------------

def unit_base_label(unit: Dict[str, Any], name_counts: Dict[str, int]) -> str:
    """基本ラベル(pb_object_name優先/GUID尾除去済みのanchorフォールバック
    +曖昧解消)。「(房n本)」「(手動)」「-> ゆれかた名」等のi18n文言は
    呼び出し側(sway_style_dialog.py)が付加する。

    同じdisplay_nameを共有する複数ユニットが存在する場合(pb_object_nameが
    無くanchorへフォールバックしたユニット同士が同じanchorを共有する縮退
    ケース)、旧sway_chain_dialog._display_name()と同じ要領で最初の房の
    先頭ボーン名を括弧書きで添えて区別する。"""
    base = unit["display_name"]
    if name_counts.get(base, 1) > 1 and unit["chains"] and unit["chains"][0]:
        return f"{base} ({unit['chains'][0][0]})"
    return base


# ---------------------------------------------------------------------------
# 鎖単位ストア(sway_styles_store.py、スキーマ不変)との往復(段1の核)。
# ---------------------------------------------------------------------------

def unit_bones_keys(anchor: Optional[str], chains: List[List[str]]) -> List[Tuple[str, ...]]:
    return [tuple(([anchor] if anchor else []) + list(c)) for c in chains]


def resolve_unit_style(
    anchor: Optional[str], chains: List[List[str]],
    saved_by_bones: Dict[Tuple[str, ...], str], none_style: str,
) -> Tuple[str, bool]:
    """1PBユニットの複数房ぶんの保存済み鎖単位assignmentsから、行(PB単位)の
    style1つを決める。DESIGN.md §4.3のマイグレーション規則(先頭優先+
    差異ログ)を、保存時fan-out・読込時reconcileの往復で恒常的に使う(段1は
    ストアのスキーマを変えないため、鎖単位ストアとPB単位UIの往復にこの
    reconcileが毎回必要)。戻り値: (style, had_conflict)。"""
    styles = []
    for key in unit_bones_keys(anchor, chains):
        s = saved_by_bones.get(key)
        if s is not None:
            styles.append(s)
    if not styles:
        return none_style, False
    first = styles[0]
    conflict = any(s != first for s in styles)
    return first, conflict


def fanout_unit_assignments(
    anchor: Optional[str], chains: List[List[str]], style: str
) -> List[Dict[str, Any]]:
    """1行(PB単位)への割当を、鎖単位の旧スキーマ({"bones":[...],"style":...})
    へ展開する(段1の「行塗り=配下の全房へfan-out書き込み」、DESIGN.md §5
    段1)。anchorが無い(手動行)場合はchains[0]自体がbones配列そのもの
    (旧sway_style_dialog._on_manual_add()と同じ、prefixを付けない)。"""
    out: List[Dict[str, Any]] = []
    for key in unit_bones_keys(anchor, chains):
        out.append({"bones": list(key), "style": style})
    return out


# ---------------------------------------------------------------------------
# 偏向判定(sway_allocator.py の判定規則を再利用、重複実装しない)。
# ---------------------------------------------------------------------------

def is_unit_biased(unit: Dict[str, Any]) -> Tuple[bool, str]:
    """このPB/SBユニットが偏向(既定で揺れ対象から除外される側)かどうか。
    判定規則は pipeline\\py\\sway_allocator.py の _judge_pb_bias()/
    _judge_sb_bias() と完全に同一のものを再利用する(2026-08-16オーナー
    口述指定「判定は sway_allocator.py の無偏向判定と同一規則を使う[重複
    実装せず可能なら関数を利用]」)。戻り値: (is_biased, reason)。"""
    params = unit.get("params") or {}
    if unit.get("type") == "springbone":
        return sway_allocator._judge_sb_bias(params)  # noqa: SLF001 (既存
        # test_sway_allocator.pyと同じ、private関数の直接再利用慣例)
    return sway_allocator._judge_pb_bias(params)  # noqa: SLF001


# ---------------------------------------------------------------------------
# 「特殊ボーンを強制セットアップ」(2026-08-16オーナー口述指定)。
# ---------------------------------------------------------------------------

# sway_quantize.STYLES ("yawa"/"futsuu"/"kata") -> sway_styles_store.
# BUILTIN_STYLE_NAMES ("soft"/"normal"/"hard") への写像。
_QUANT_TO_BUILTIN: Dict[str, str] = {"yawa": "soft", "futsuu": "normal", "kata": "hard"}


def compute_forced_style_params(params: Dict[str, Any]) -> Dict[str, float]:
    """偏向PBの実値から「ゆれかた」10キーパラメータを自動生成する
    (2026-08-16オーナー口述指定「特殊ボーンを強制セットアップ」)。

    - ベース値: `sway_quantize.quantize_pb(pull, spring)` が返す3段プリセット
      名("yawa"/"futsuu"/"kata")を`sway_styles_store.BUILTIN_STYLE_NAMES`側
      ("soft"/"normal"/"hard")へ写像し、`BUILTIN_STYLE_PARAMS`から複製する。
    - limit_angle: 元の`max_angle_x`(PBのMax Angle)をそのまま写す(偏向鎖
      にも同じ読み方を使う――コーンの開き自体は偏向可否と無関係な量のため、
      `sway_allocator._pb_limit_angle`の無偏向側と同じフィールドを見る)。
    - fake_pitch/fake_roll/fake_yaw: 元の`limit_rotation`(3要素)をそのまま
      写す(実装者解釈: 書き出し順=[Pitch,Roll,Yaw]をそのまま対応する3値へ
      割り当てる。他に手掛かりが無いため素直な順序を採用、REPORT.md記載)。

    値は`PARAM_RANGES`でクランプする(壊れた入力への防御)。"""
    pull = params.get("pull")
    spring = params.get("spring")
    pull = float(pull) if isinstance(pull, (int, float)) and not isinstance(pull, bool) else 0.0
    spring = float(spring) if isinstance(spring, (int, float)) and not isinstance(spring, bool) else 0.0
    quant = sway_quantize.quantize_pb(pull, spring)
    builtin_name = _QUANT_TO_BUILTIN.get(quant, "normal")
    out: Dict[str, float] = dict(sway_styles_store.BUILTIN_STYLE_PARAMS[builtin_name])

    def _clamp(key: str, value: float) -> float:
        lo, hi = sway_styles_store.PARAM_RANGES[key]
        return max(lo, min(hi, value))

    max_angle = params.get("max_angle_x")
    if isinstance(max_angle, (int, float)) and not isinstance(max_angle, bool):
        out["limit_angle"] = _clamp("limit_angle", float(max_angle))

    rot = params.get("limit_rotation")
    if isinstance(rot, list) and len(rot) == 3:
        for key, v in zip(("fake_pitch", "fake_roll", "fake_yaw"), rot):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[key] = _clamp(key, float(v))
    return out
