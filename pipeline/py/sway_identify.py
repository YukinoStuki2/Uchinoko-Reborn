# -*- coding: utf-8 -*-
"""sway_identify.py -- 揺れ鎖の「尻尾/耳」同定(dev#19 native-donor-rule WP、
issue #19、2026-08-14オーナー裁定、照合範囲修正2026-08-14夜第2版)。

## 背景・設計(オーナー裁定の最終形、2026-08-14夜)

当初案(名前フィルタで揺れ対象そのものを絞る/sway_chain_override_storeとの
優先順位規則)はいずれもオーナー裁定で破棄された。**最終仕様は極めてシンプル**:

1. アバター読込時にPB/SB鎖を列挙する(既存カタログ、physbone_catalog.py /
   vrm_spring_catalog.py)。
2. 本モジュールの同定関数で、各鎖が「尻尾」か「耳」かを判定する。
3. **同定の役割は既定チェック状態を決めることのみ**(尻尾・耳=既定ON、
   その他=既定OFF)。隠れフィルタ・優先順位規則は作らない。
4. 揺れ対象=**「チェックされた鎖」ただそれだけ**——ラボ「揺れもの詳細設定」
   (app_py\\ui\\sway_chain_dialog.py)のチェック状態がそのまま最終決定であり、
   本モジュールはその「初期値」を計算するだけの1箇所の真実の源。

したがって本モジュールが提供するのは同定そのもの(`identify_sway_kind()`)と、
それをそのまま既定チェック状態へ変換する薄いラッパー(`default_sway_enabled()`)
の2関数のみ。bpy非依存の純粋関数(pytest単体で検証可能。Blender起動不要)。

## 判定規則(2026-08-14夜、照合範囲修正)

初版は「アンカー名がhips/pelvis系」「アンカー名がhead系」をそれぞれ尻尾/耳の
**必須条件**にしていたが、実データ(flatapronの実PhysBone、
work\\rd_19_smokefinal\\flatapron_export\\physbones.json)で
`anchor="Tail Root"`(hips/pelvis/hipのいずれも含まない)・鎖骨名
`Tail.001`〜`Tail.005` という構成が実在し、初版ロジックでは尻尾が同定できず
既定OFFに落ちる欠陥が判明した(work\\rd_19_smokefinal\\FINAL_REPORT.md)。
オーナー裁定「雑な名前推定でいい」を受け、**アンカー名のカテゴリ条件を撤廃**
し、判定はトークン照合のみに統一した:

- **尻尾**: アンカー名+鎖の全ボーン名のうち、いずれか1つでも尻尾系パターン
  (`TAIL_NAME_PATTERNS`、tail/shippo/尻尾/しっぽ)に部分一致(大小無視)すれば
  尻尾候補。
- **耳**: アンカー名+鎖の全ボーン名のうち、いずれか1つでも耳系パターン
  (`EAR_NAME_PATTERNS`、ear/mimi/耳/kemonomimi)に部分一致すれば耳候補。
- どちらのトークンも一切現れなければ`None`(スカート・髪・エプロン・スカーフ
  等はここに落ちる——誤って既定ONにすると「揺らすとメッシュが破壊される」
  実害があるため、名前だけでは判定できない鎖は既定OFFにする保守設計、
  2026-08-14オーナー実体験に基づく裁定)。

**非対称の原則は維持**: headアンカーだけを根拠にした自動ON(耳トークンが
どこにも無いのに耳判定する)は追加しない。耳判定は依然として耳トークンの
一致が必須条件であり、今回撤廃したのは「アンカー名のカテゴリ」という
追加の絞り込み条件のみ(髪等の誤爆を防ぐ効果は、耳トークン自体が無ければ
そもそも一致しないという一致条件そのものが担う)。

anchor(SourceChainのanchor相当)は「鎖自身の直接の親」を指す想定
(pipeline\\py\\sway_assign.SourceChain.anchor、app_py\\ui\\sway_chain_dialog.py
の`entry["bones"][0]`と同じ意味論)。祖先探索(pipeline\\py\\sway_assign.py
classify_source_region()相当)は本モジュールでは行わない——鎖自身の直接の親を
見るだけで十分という設計判断(sway_chain_dialog.SAMPLE_CHAINS/実データの
両方でこの前提が成立することを確認済み)。
"""

from __future__ import annotations

from typing import Optional, Sequence

# 尻尾/耳のボーン名パターン(アンカー名+鎖中のいずれか1本が一致すればよい)。
# 部分一致・大小無視。"kemonomimi"は"mimi"の部分文字列を含むため技術的には
# 冗長だが、パターンリストの可読性(オーナー指定語彙をそのまま残す)を優先し
# 明示的に残す。
TAIL_NAME_PATTERNS = ("tail", "shippo", "尻尾", "しっぽ")
EAR_NAME_PATTERNS = ("ear", "mimi", "耳", "kemonomimi")


def _matches_any(name: str, patterns: Sequence[str]) -> bool:
    if not name:
        return False
    low = name.lower()
    return any(p.lower() in low for p in patterns)


def identify_sway_kind(anchor: Optional[str], chain_bones: Sequence[str]) -> Optional[str]:
    """揺れ鎖(anchor+chain_bones、chain_bonesはanchor自身を含まない揺れる
    ボーン列)が「尻尾」「耳」のどちらかに同定できれば"tail"/"ear"を、
    できなければNoneを返す(pure関数、副作用無し)。

    照合範囲はanchor自身+chain_bones全体(2026-08-14夜修正、アンカー名の
    カテゴリ条件は撤廃済み——名前トークンがどこか1箇所にあれば足りる)。

    anchor: 鎖の直接の親ボーン名(pipeline\\py\\sway_assign.SourceChain.anchor
      相当)。Noneまたは空文字列は単に照合対象から除外される(トークンが
      chain_bones側にあれば引き続き同定される)。
    chain_bones: 鎖自身のボーン名列(anchor自身は含まない)。
    """
    anchor = anchor or ""
    names = list(chain_bones or [])
    candidates = [anchor] + names
    if any(_matches_any(n, TAIL_NAME_PATTERNS) for n in candidates):
        return "tail"
    if any(_matches_any(n, EAR_NAME_PATTERNS) for n in candidates):
        return "ear"
    return None


def default_sway_enabled(anchor: Optional[str], chain_bones: Sequence[str]) -> bool:
    """揺れ鎖の既定チェック状態(dev#19最終裁定: 尻尾・耳=既定ON、その他=
    既定OFF)。identify_sway_kind()の結果をそのままbool化するだけの薄い
    ラッパー——「真実の源は同定関数1つ」の原則どおり、判定ロジック自体は
    ここに複製しない。"""
    return identify_sway_kind(anchor, chain_bones) is not None
