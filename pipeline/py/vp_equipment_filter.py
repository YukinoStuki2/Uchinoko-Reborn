# -*- coding: utf-8 -*-
"""dev#165(2026-08-08 オーナー裁定「装備限定」): 変換時に注入対象の衣装SKを、
ユーザーが選択した装備だけへ絞り込むラボ機能の中核ロジック。

**第2期(2026-08-08、指揮者裁定・オーナーGO): 旧設計の欠陥を解消済み。**
第1期(初版)は `vp_exclusions.EXCLUDED_SK_NAMES` というグローバルdictを
`convert_noue.py`が`build_pak_from_avatar.main()`直前だけ一時書き換えする
コンテキストマネージャ方式だった。これはメッシュ(Phase2)にしか間に合わず、
マテリアル(`live_template._unify_slot_materials`が全ジョブ共有・キャッシュ
される**テンプレート組み立て時**に1回だけ確定させる)には効かなかった
(G12と同型の見た目破綻が起きる欠陥。旧版の記録は git log 参照)。

**新設計**: グローバル書き換えを廃止し、「有効除外集合 = 固定denylist
(`vp_exclusions.EXCLUDED_SK_NAMES`) ∪ 未選択装備」を**明示引数**として
テンプレート組み立て(`live_template.py`、`_unify_slot_materials`含む)と
Phase2注入(`build_pak_from_avatar.py`)の両方へ**同じ計算式**で渡す。
テンプレートの組み立ては`job`辞書全体を最初から受け取っているため、
`job.get("equipment_filter")` を読むだけで済み、新しいグローバル状態は
一切増えない。テンプレートのフィンガープリント(`live_template.
_live_template_fingerprint()`)にも`equipment_filter`を含めることで、
絞り込みパターンごとに正しく別キャッシュへ分離される
(既定=空リストは従来と同じキーの並びを保ちつつ値が加わるだけなので、
1度だけキャッシュが作り直されるがそれ以降は安定。最終出力は
バイト完全一致——生成ロジック自体は「除外集合が空なら何も変わらない」
という性質を保ったまま)。

共有MI(1つのMIパスを複数の異なる衣装SKが参照するケース、Plastic001の
M01が実例)の巻き添え問題は、`live_template.collect_unified_mi_targets()`/
`_inject_outfit_body_parka_textures()`が元々「**除外されていないSKたちが
参照するMIパスの和集合**」という構造で対象を決めているため、除外判定さえ
正しく渡せば**追加のコードなしに**解決する: 除外されたSKがMIを持ち込まなく
なるだけで、他の非除外SKが同じMIパスを持ち込めば、そのMIは引き続き対象
セットに残る(=「選択側が必要とするなら残る」)。

対象は Player/Outfit 配下の `SK_Player_{Male,Female}_Outfit_*` のみ(頭装備・
髪・体そのもののSKはこの機能の対象外)。build_pak_from_avatar.py の
_run_sk_injection() が実際に注入対象として集める集合
(`collect_targets(template/Player/Outfit)`)と完全に一致する。

装備コード(equipment_code): SKベース名から性別プレフィックスを取り除いた
残り(例 "SK_Player_Female_Outfit_Bronze001" -> "Bronze001")。GUIの装備選択
ダイアログはこのコードを選択単位として使い、job.jsonの`equipment_filter`
キーにもこのコードのリストを書く。表示名は別モジュール
(vp_equipment_names.py)が実行時にlocresから解決し、失敗時はこのコードを
そのまま表示にフォールバックする。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

TAG = "vp_equipment_filter"

# build_pak_from_avatar.py _run_sk_injection() の SK_Player_{gender}_Outfit_*
# 判定(gender_of()相当)と対になるプレフィックス。順序は無関係(startswithで
# 判定するだけ)。
_OUTFIT_PREFIXES = ("SK_Player_Male_Outfit_", "SK_Player_Female_Outfit_")


def _basename_noext(s):
    """vp_exclusions._basename_noext と同一ロジック(独立モジュールなので
    複製。1関数のみで乖離のリスクは小さい)。"""
    s = (s or "").replace("\\", "/")
    s = s.rsplit("/", 1)[-1]
    for ext in (".uasset", ".uexp", ".ubulk"):
        if s.endswith(ext):
            s = s[:-len(ext)]
    return s


def equipment_code(name):
    """SK名(パス・拡張子は問わない)から性別非依存の装備コードを返す。
    Player/Outfit配下の SK_Player_{Male,Female}_Outfit_* 以外(頭装備・髪・
    体そのもののSK等)は対象外として None を返す。"""
    s = _basename_noext(name)
    for prefix in _OUTFIT_PREFIXES:
        if s.startswith(prefix):
            code = s[len(prefix):]
            return code or None
    return None


def normalize_equipment_filter(equipment_filter):
    """job.get("equipment_filter")の生値(None/空リスト/コードのリスト)を
    正規化する。戻り値は「絞り込み集合」または**None**(=絞り込み無し、
    既定)。空/None入力は必ずNoneを返す(既定値の唯一の表現、④無退行の
    根拠——「空集合」と「None」を区別しない=呼び出し側で分岐が増えない)。"""
    if not equipment_filter:
        return None
    codes = {c for c in equipment_filter if c}
    return codes or None


def list_outfit_sk_names(template_dir):
    """template配下 Player/Outfit 以下を再帰走査し、.uexpの拡張子なしSK名
    (ソート済み、重複無し)を返す。equipment_code()がNoneを返すもの
    (対象外のSK)は含めない。template_dirにPlayer/Outfitが存在しなければ
    空リスト(呼び出し側が「テンプレート未解決」等でハンドルする)。

    組み立て済みのテンプレートディレクトリが要るため、GUIの装備選択
    ダイアログ(テンプレート未解決)向けではなく、変換時の実際の注入対象
    列挙(build_pak_from_avatar.py側)向け。テンプレート組み立て**前**に
    必要な場合は outfit_sk_names_from_manifest() を使う。"""
    outfit_root = os.path.join(template_dir, "Player", "Outfit")
    names = set()
    if not os.path.isdir(outfit_root):
        return []
    for _dirpath, _dirs, filenames in os.walk(outfit_root):
        for fn in filenames:
            if not fn.lower().endswith(".uexp"):
                continue
            base = fn[:-len(".uexp")]
            if equipment_code(base) is not None:
                names.add(base)
    return sorted(names)


def outfit_sk_names_from_manifest(manifest):
    """`noue_template_manifest.json`(live_template._load_manifest()の戻り値、
    "vanilla"キーにPlayer/Outfit配下を含む相対パスの一覧を持つ)から、装備SK
    ベース名(拡張子なし)集合を返す。

    テンプレートを一切組み立てずに(=700MBのpak抽出をせずに)呼べるのが
    list_outfit_sk_names()との違い。マテリアル統一(live_template.
    _unify_slot_materials等)は**テンプレート組み立ての最中**に除外集合を
    知る必要があるため、組み立て済みディレクトリに依存できない
    (組み立てられる前に判定が要る、という順序の制約)。"""
    names = set()
    for rel in manifest.get("vanilla", []):
        rel_norm = rel.replace("\\", "/")
        if not rel_norm.startswith("Player/Outfit/"):
            continue
        if not rel_norm.endswith(".uasset"):
            continue
        base = os.path.basename(rel_norm)[:-len(".uasset")]
        if equipment_code(base) is not None:
            names.add(base)
    return names


def known_equipment_codes(all_outfit_sk_names):
    """SKベース名の集合/リスト(list_outfit_sk_names()または
    outfit_sk_names_from_manifest()の戻り値)から、装備コード集合
    (男女で1コードにまとまる)を返す。装備選択ダイアログの選択肢一覧は
    この集合を使う。"""
    codes = set()
    for name in all_outfit_sk_names:
        code = equipment_code(name)
        if code is not None:
            codes.add(code)
    return codes


def unselected_sk_names(all_outfit_sk_names, equipment_filter):
    """all_outfit_sk_names(list_outfit_sk_names()/outfit_sk_names_from_
    manifest()の戻り値)のうち、equipment_filter(job.get("equipment_filter")
    の生値)で選択されなかった装備SKベース名の集合を返す(**副作用なし**、
    グローバル状態は一切変更しない)。

    equipment_filterがNone/空なら**必ず空集合**(=絞り込み無し、既定。
    ④無退行の根拠)。呼び出し側はこの戻り値を「他の除外理由(コラボ
    denylist等)とORして最終的な除外判定にする」ために使う
    (vp_exclusions.is_excluded(name, extra_excluded=this)のように)。"""
    requested = normalize_equipment_filter(equipment_filter)
    if requested is None:
        return set()
    return {name for name in all_outfit_sk_names
            if equipment_code(name) is not None and equipment_code(name) not in requested}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python {os.path.basename(__file__)} <template_dir>")
        sys.exit(1)
    codes = sorted(known_equipment_codes(list_outfit_sk_names(sys.argv[1])))
    print(f"[{TAG}] {len(codes)} equipment code(s):")
    for c in codes:
        print(f"  {c}")
