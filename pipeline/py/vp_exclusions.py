# -*- coding: utf-8 -*-
"""U50: 「非対応」にする装備アセットの除外リスト(**唯一の正本**)。

責任者裁定(2026-07-25): 「**コラボ系アイテムは非対応です**」。

除外された装備は:
  - メッシュ注入をしない(アバターの体が入らない)
  - MI差し替えもしない(マテリアルもバニラのまま)
  - 頭装備のダミー化(非表示化)もしない
結果として **バニラの装備がそのまま出る**。責任者の方針
「**失敗するにしても優雅に失敗する**」に従い、壊れた見た目を出すより
「その装備だけ元のパルワールドの装備が出る」で止める。

------------------------------------------------------------------------
### 追加のしかた(次の人へ)

`EXCLUDED_SK_NAMES` に SK のアセット名(拡張子なし、パスなし)を足すだけ。
コメントに「どのコラボか」「日本語名」を併記すること。
新しいコラボが判明したら、ここに追記すれば全経路へ一斉に効く。

パス単位で除外したい特殊ケースのために `EXCLUDED_PATH_SUBSTRINGS`
(パスに含まれれば除外)も用意してある。フォルダ名でまとめて落としたい
ときはこちらが楽(例: "Yakushima")。

外部ファイル `work\\u50_terraria\\exclusion_asset_paths.txt` は調査担当
エージェントの**調査結果**であり、本モジュールが正本。調査結果が更新
されたら人がここへ反映する(実行時に work\\ を読みに行くことはしない。
配布物に work\\ は含まれないため)。

------------------------------------------------------------------------
### preflight 側での読み方(配線は指揮者が調整)

`pipeline\\py\\preflight_pak.py` は別エージェントが編集中のため触っていない。
G10(カバレッジ)/ G11(スロット役)が除外分を NG に数えないようにするには、
preflight 側で次のように読んでほしい:

    import vp_exclusions
    ...
    for rel in all_sk_paths:
        if vp_exclusions.is_excluded(rel):
            continue          # 非対応=意図的に未収録/未注入なのでNGではない

`is_excluded()` は「pak内相対パス」「/Game/... のフルパッケージパス」
「SK名そのもの」のいずれを渡しても判定できる。
除外件数をログに出したい場合は `excluded_reason(rel)` が日本語の理由
(コラボ名+日本語アイテム名)を返す。
"""
import os

# ---------------------------------------------------------------------------
# コラボ系(責任者裁定「コラボ系アイテムは非対応」)
# ---------------------------------------------------------------------------

# テラリアコラボ (Tides of Terraria, v0.6.0 2025-06-25)。内部コードネーム "Yakushima"。
# 根拠: work\u50_terraria\exclusion_asset_paths.txt(バニラpak全SK棚卸しで裏付け済み)
_TERRARIA = {
    "SK_Player_Female_Outfit_Yakushima001": "Terraria: Holy Plate (female)",
    "SK_Player_Male_Outfit_Yakushima001": "Terraria: Holy Plate (male)",
    "SK_YakushimaHeadEquip001": "Terraria: Holy Mask",
    "SK_YakushimaHeadEquip002": "Terraria: Holy Headgear",
    "SK_YakushimaHeadEquip003": "Terraria: Holy Helmet",
    "SK_YakushimaHeadEquip004": "Terraria: Holy Hood",
    "SK_YakushimaHeadEquip005": "Terraria: Moon Lord's Mask",
    "SK_YakushimaHeadEquip006": "Terraria: Cthulhu's Eye Mask",
}

# ULTRAKILLコラボ。内部コードネーム "Octavia"。V1/V2アーマー。
# 男性用SKしかバニラに存在しない(work\u50_equip\out\FINDINGS2.txt 5節)。
# 除外により、注入時に腕が75°ねじれる問題(preflight G5 で検出)も併せて解消する。
_ULTRAKILL = {
    "SK_Player_Male_Outfit_Octavia001": "ULTRAKILL: V1/V2 Armor (male)",
    "SK_Player_Female_Outfit_Octavia001": "ULTRAKILL: V1/V2 Armor (female, may not exist in vanilla)",
    "SK_Player_Male_Outfit_Octavia001_v01": "ULTRAKILL: V1 Armor",
    "SK_Player_Male_Outfit_Octavia001_v02": "ULTRAKILL: V2 Armor",
    "SK_Player_Female_Outfit_Octavia001_v01": "ULTRAKILL: V1 Armor (female)",
    "SK_Player_Female_Outfit_Octavia001_v02": "ULTRAKILL: V2 Armor (female)",
}

# ここへ新しいコラボを足す(dict を1つ作って _ALL へ入れるだけ)
_ALL = {}
_ALL.update(_TERRARIA)
_ALL.update(_ULTRAKILL)

EXCLUDED_SK_NAMES = dict(_ALL)

# フォルダ名/パスの一部で丸ごと落としたいとき用(SK名の増減に強い)。
# バリアント(_v01/_v02/_v03…)が後から増えても取りこぼさない。
EXCLUDED_PATH_SUBSTRINGS = (
    "Yakushima",   # テラリアコラボ
    "Octavia",     # ULTRAKILLコラボ
)

# 【ンダコアラ(Kigurumi001)はコラボではない】
# 調査の結果、パルワールド独自のハロウィン限定ミッション報酬と判明したため
# 本リストには**入れない**(責任者確認済み)。単一マテリアル化で解決する見込み。


def _basename_noext(s):
    s = (s or "").replace("\\", "/")
    s = s.rsplit("/", 1)[-1]
    for ext in (".uasset", ".uexp", ".ubulk"):
        if s.endswith(ext):
            s = s[:-len(ext)]
    return s


def is_excluded(path_or_name, extra_excluded=None):
    """pak内相対パス / /Game/... フルパッケージパス / SK名 のいずれでも判定する。

    dev#165第2期(2026-08-08、装備限定): `extra_excluded`は呼び出し側が
    計算した追加の除外SK名集合(拡張子なしベース名、大小文字区別、例
    "SK_Player_Male_Outfit_Bronze001")を渡すための**任意引数**。
    省略/None/空なら**固定denylist(EXCLUDED_SK_NAMES)のみ**で判定し、
    既存の全呼び出し元(引数1個のみで呼んでいる箇所)は挙動が一切変わらない
    (=既存の「コラボ固定denylist」の挙動は不変)。

    典型的な使い方(live_template.py/build_pak_from_avatar.py):
    その場のjob.jsonのequipment_filterから計算した「未選択装備SK名集合」を
    extra_excludedとして渡し、「固定denylist ∪ 未選択装備」という有効除外
    集合をこの1関数で一括判定する(グローバル状態は一切変更しない)。"""
    if not path_or_name:
        return False
    s = str(path_or_name).replace("\\", "/")
    for sub in EXCLUDED_PATH_SUBSTRINGS:
        if sub in s:
            return True
    name = _basename_noext(s)
    if name in EXCLUDED_SK_NAMES:
        return True
    if extra_excluded and name in extra_excluded:
        return True
    return False


def excluded_reason(path_or_name, extra_excluded=None):
    """除外理由(英語)を返す。除外対象でなければ None。
    extra_excludedの意味はis_excluded()と同じ(任意引数、省略時は挙動不変)。"""
    if not is_excluded(path_or_name, extra_excluded=extra_excluded):
        return None
    name = _basename_noext(path_or_name)
    if name in EXCLUDED_SK_NAMES:
        return EXCLUDED_SK_NAMES[name]
    s = str(path_or_name).replace("\\", "/")
    for sub in EXCLUDED_PATH_SUBSTRINGS:
        if sub in s:
            return f"unsupported (collab item: {sub})"
    if extra_excluded and name in extra_excluded:
        return "lab: equipment filter, not selected"
    return "unsupported"


def filter_paths(paths, extra_excluded=None):
    """(残すパス, 除外したパス) に分ける。extra_excludedの意味は
    is_excluded()と同じ(任意引数、省略時は挙動不変)。"""
    keep, drop = [], []
    for p in paths:
        (drop if is_excluded(p, extra_excluded=extra_excluded) else keep).append(p)
    return keep, drop


def summary():
    return (f"unsupported (collab) SK: {len(EXCLUDED_SK_NAMES)} / "
            f"path match: {list(EXCLUDED_PATH_SUBSTRINGS)}")


if __name__ == "__main__":
    print(summary())
    for k, v in sorted(EXCLUDED_SK_NAMES.items()):
        print(f"  {k:45s} {v}")
