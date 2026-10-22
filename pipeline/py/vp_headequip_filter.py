# -*- coding: utf-8 -*-
"""dev#277第1弾④(2026-08-08 オーナー裁定「頭装備切り替え」)ラボ機能の
中核ロジック。

オーナー原文(dev#277、§0.1、`work\\rd_1198_wpb\\PROPOSAL.md` §8):
  ・ＵＩは装備限定とおなじである
  ・チェックを外した頭装備は、表示しないこと
  ・デフォルトは全てＯＦＦ

**装備限定(dev#165、vp_equipment_filter.py)との構造上の違い**:
装備限定はユーザーの手元のPalworld pakから実行時に衣装SKの一覧を読む
(`list_outfit_sk_names()`)。頭装備切り替えの対象(HeadEquip、帽子)は
このアプリ自身が用意する固定カタログ(`noue_template_manifest.json`の
"project"区分、dev#26案Bでランタイム生成されるスタブ資産)であり、
ユーザーのpakを読む必要が無い——カタログはビルド時に静的に確定する。

**「表示する」の実装意味**: WP-B3(dev#1198)がHead/Hairを
`noue_template_manifest.json`の"project"から丸ごと削除した設計と同じ
考え方を、HeadEquipにはコード単位で選択的に適用する。「チェックを外した
頭装備は表示しない」= 既定どおりスタブ生成(空スタブでバニラの帽子を
覆い隠す)。「チェックを入れた頭装備は表示する」= そのHeadEquipのrelを
出力pakから一切省く(スタブ生成もコピーもしない。Head/Hairと同じ
「manifestに無い扱い」にすることで、Palworld本体のバニラpakフォールバック
により実際の帽子ジオメトリが描画される)。

既定(job.get("headequip_show")が空/未設定)は`shown_headequip_rels()`が
必ず空集合を返すため、`live_template._project_stub_sk_rels()`の判定は
WP-B3までの挙動と完全に一致する(ラボ憲章④)。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

TAG = "vp_headequip_filter"

# noue_template_manifest.jsonの実測値(work\rd_1198_wpb\PROPOSAL.md §8.2):
# ファイル名は "SK_HeadEquip<3桁連番>" に、色/バージョン差分の任意の
# "_<英数字>" サフィックスが付く形(例: SK_HeadEquip001, SK_HeadEquip001_purple,
# SK_HeadEquip019_v01)。性別プレフィックスは無い(装備限定のOutfitと異なり
# 頭装備は性別非依存)。
_HEADEQUIP_CODE_RE = re.compile(r"^HeadEquip\d+(_\w+)?$")


def _basename_noext(s):
    """vp_equipment_filter._basename_noext と同一ロジック(独立モジュール
    なので複製。1関数のみで乖離のリスクは小さい)。"""
    s = (s or "").replace("\\", "/")
    s = s.rsplit("/", 1)[-1]
    for ext in (".uasset", ".uexp", ".ubulk"):
        if s.endswith(ext):
            s = s[:-len(ext)]
    return s


def headequip_code(name):
    """SK名(パス・拡張子は問わない)から頭装備コードを返す。
    "SK_HeadEquip<連番>(_バリアント)?" 以外(他カテゴリのSK・非SK資産)は
    対象外として None を返す。"""
    s = _basename_noext(name)
    if not s.startswith("SK_"):
        return None
    code = s[len("SK_"):]
    if _HEADEQUIP_CODE_RE.match(code):
        return code
    return None


def headequip_rels_from_manifest(manifest):
    """`noue_template_manifest.json`(live_template._load_manifest()の戻り値)
    の"project"区分から、Player/HeadEquip配下のheadequip_code()が解決できる
    rel(拡張子付きのまま、uasset/uexp両方を含む)の一覧を返す。

    テンプレートを組み立てずに(=pak抽出をせずに)呼べる——このアプリ自身が
    用意する固定カタログのため、装備限定のoutfit_sk_names_from_manifest()と
    同じ理由でmanifest読み取りだけで完結する。"""
    rels = []
    for rel in manifest.get("project", []):
        norm = rel.replace("\\", "/")
        if not norm.startswith("Player/HeadEquip/"):
            continue
        if headequip_code(norm) is not None:
            rels.append(rel)
    return rels


def known_headequip_codes(headequip_rels):
    """headequip_rels(headequip_rels_from_manifest()の戻り値等)から、
    頭装備コード集合(uasset/uexpペアで1コードにまとまる)を返す。
    頭装備選択ダイアログの選択肢一覧はこの集合を使う。"""
    codes = set()
    for rel in headequip_rels:
        code = headequip_code(rel)
        if code is not None:
            codes.add(code)
    return codes


def normalize_headequip_selection(headequip_show):
    """job.get("headequip_show")の生値(None/空リスト/コードのリスト)を
    正規化する。戻り値は「表示する頭装備コードの集合」または**None**
    (=表示切り替え無し、既定=全て非表示=現状どおり)。空/None入力は
    必ずNoneを返す(既定値の唯一の表現、④無退行の根拠)。"""
    if not headequip_show:
        return None
    codes = {c for c in headequip_show if c}
    return codes or None


def shown_headequip_rels(all_headequip_rels, headequip_show):
    """all_headequip_rels(headequip_rels_from_manifest()の戻り値)のうち、
    headequip_show(job.get("headequip_show")の生値)で選択(チェックON=
    表示する)されたコードに一致するrelの集合を返す(**副作用なし**)。

    headequip_showがNone/空なら**必ず空集合**(=絞り込み無し、既定。
    ④無退行の根拠)。呼び出し側(live_template._project_stub_sk_rels)は
    この戻り値に含まれるrelをスタブ生成対象・コピー対象の両方から除外する
    (Head/Hairと同じ「manifestに無い扱い」)。"""
    requested = normalize_headequip_selection(headequip_show)
    if requested is None:
        return set()
    return {rel for rel in all_headequip_rels
            if headequip_code(rel) in requested}


if __name__ == "__main__":
    import json
    if len(sys.argv) != 2:
        print(f"Usage: python {os.path.basename(__file__)} <noue_template_manifest.json>")
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        manifest = json.load(f)
    rels = headequip_rels_from_manifest(manifest)
    codes = sorted(known_headequip_codes(rels))
    print(f"[{TAG}] {len(codes)} headequip code(s) ({len(rels)} rel(s)):")
    for c in codes:
        print(f"  {c}")
