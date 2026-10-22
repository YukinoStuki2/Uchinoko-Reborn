# -*- coding: utf-8 -*-
"""dev#336(2026-08-08 オーナー裁定「性別限定」、work\\rd_1198_wpb\\PROPOSAL.md
§7再設計): 変換時に注入対象の衣装SK・素体共有MIを、ユーザーが選択した性別
だけへ絞り込むラボ機能の中核ロジック。

**設計方針(PROPOSAL.md §7.2「性別限定は装備限定(F3)の縮退形として設計
できる」)**: 性別限定は新しい除外機構を作らず、dev#165(装備限定)が
確立した「有効除外集合 = 固定denylist ∪ 未選択装備 ∪ 未選択性別」という
同じ計算式に、もう1つの入力を足すだけで実現する。本モジュールはその
「未選択性別のSK名集合」を計算する純粋関数のみを提供する
(vp_equipment_filter.pyと対になる設計、副作用なし)。

**job.jsonの`genders`キー自体は新設ではない**(dev#165、2026-07-30、
`build_pak_from_avatar.py`の`--genders`/`convert_noue.py`の
`requested_genders`/`preflight_pak.py`の`_is_gender_excluded`が既に
Phase2のSK注入・preflightゲートの期待値計算で参照している、既存の
CLI/job.json機構)。当時はGUIから書き込む手段が無かった(2026-08-07時点で
「GUIに性別選択ウィジェットは無い」、app_py/pipeline_runner.py L883-888
コメント参照)。本モジュール+ラボUI(app_py/ui/gender_select_dialog.py)は
既存のjob["genders"]機構へ**書き込み側**を追加するだけで、Phase2/preflight
側のロジックは無改修のまま流用する。

**本モジュールが埋める残りの穴(PROPOSAL.md §7.2「旧ブロッカー」)**:
Phase2(SK注入)・preflightは既にgendersを考慮していたが、
`live_template.py`のマテリアル統一(`_effective_extra_excluded_sk_names`
経由の`collect_unified_mi_targets`/`_inject_outfit_body_parka_textures`)は
job["genders"]を一切参照していなかった。これは装備限定(dev#165第1期)が
抱えていたのと同型の欠陥(メッシュは絞り込まれるがマテリアル/テクスチャは
共有パスのまま巻き添えになる)——性別限定でMale側だけを選んでも、
Female側の共有素体MI(MI_Player_Female_Body)がテンプレート組み立て時に
無条件でBase Textureをアバターのt00へ向け直されてしまい、注入されていない
はずのFemale側の肌色だけアバター色になる、という不整合が起きる。
`live_template._effective_extra_excluded_sk_names()`へ本モジュールの
`unselected_sk_names_by_gender()`を合成することでこれを解消する
(vp_gender_filter.py自身はlive_template.pyを一切importしない、
一方向依存)。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

TAG = "vp_gender_filter"

_VALID_GENDERS = frozenset({"Male", "Female"})


def _basename_noext(s):
    """vp_equipment_filter._basename_noext と同一ロジック(独立モジュール
    なので複製。1関数のみで乖離のリスクは小さい)。"""
    s = (s or "").replace("\\", "/")
    s = s.rsplit("/", 1)[-1]
    for ext in (".uasset", ".uexp", ".ubulk"):
        if s.endswith(ext):
            s = s[:-len(ext)]
    return s


def gender_of(name):
    """SK名(パス・拡張子は問わない)から性別を判定する。
    `research\\ue_exit\\build_avatar_variant_all.py`の`gender_of()`
    (Phase2の既存判定、`_Male_`/`_Female_`という部分文字列一致)と同じ
    判定基準を独立モジュールとして複製するが、**例外を投げない**点が異なる:
    本モジュールはPlayer/Outfit配下以外の資産(頭装備・素体MI名等)にも
    安全に呼べる必要があるため、判定不能(どちらの部分文字列も含まない)なら
    Noneを返す(=性別非依存の資産には一切影響しない、安全側)。"""
    s = _basename_noext(name)
    if "_Male_" in s:
        return "Male"
    if "_Female_" in s:
        return "Female"
    return None


def normalize_gender_selection(genders):
    """job.get("genders")の生値を正規化する。戻り値:
      - None: 絞り込み無し(既定)。入力がNone/空/両性別を含む(=
        {"Male","Female"}のスーパーセット)場合は常にNone。
      - frozenset({"Male"}) または frozenset({"Female"}): 片性別限定。

    ④無退行の根拠: 既定(キー不在/["Male","Female"]/["Female","Male"])は
    すべて同じNoneへ正規化されるため、呼び出し側の分岐が増えない。
    不正値(未知の文字列を含む等)は無視して残りから判定する
    (vp_equipment_filter.normalize_equipment_filterのfalsy除去と同じ
    安全側の方針)。"""
    if not genders:
        return None
    g = {x for x in genders if x in _VALID_GENDERS}
    if not g or g >= _VALID_GENDERS:
        return None
    return frozenset(g)


def unselected_sk_names_by_gender(all_outfit_sk_names, genders):
    """all_outfit_sk_names(vp_equipment_filter.outfit_sk_names_from_
    manifest()/list_outfit_sk_names()の戻り値と同じ形、拡張子なしSK名の
    集合/リスト)のうち、genders(job.get("genders")の生値)で選択されな
    かった性別のSK名集合を返す(**副作用なし**)。

    genders正規化がNone(絞り込み無し、既定)なら**必ず空集合**
    (④無退行の直接根拠)。gender_of()がNoneを返す名前(性別が名前から
    判定できないもの)は対象外(除外しない、安全側)——本関数の入力は
    Player/Outfit配下のSK名のみを想定しているため通常は起きないが、
    Head/Hair等が誤って混入しても実害が無いようにする。"""
    requested = normalize_gender_selection(genders)
    if requested is None:
        return set()
    excluded_genders = _VALID_GENDERS - requested
    return {name for name in all_outfit_sk_names
            if gender_of(name) in excluded_genders}


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("Male", "Female", "Both"):
        print(f"Usage: python {os.path.basename(__file__)} <Male|Female|Both>")
        sys.exit(1)
    genders = None if sys.argv[1] == "Both" else [sys.argv[1]]
    requested = normalize_gender_selection(genders)
    print(f"[{TAG}] genders={sys.argv[1]!r} -> normalized={sorted(requested) if requested else None}")
