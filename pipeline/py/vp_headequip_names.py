# -*- coding: utf-8 -*-
"""dev#277第1弾④(頭装備切り替え、2026-08-08)ラボ機能の表示名解決CLI。

PROPOSAL(work\\rd_1198_wpb\\PROPOSAL.md §8.2)の不確実点5「表示名の解決経路は
未確認」への回答: `vp_equipment_names.resolve_display_names()`は入力を
装備コードのリストとして受け取るだけの汎用関数であり、装備限定
(Player/Outfit)固有のロジックを一切含まない——**そのままHeadEquipコード
にも使い回せる**。新しいlocresパーサ・DataTableパーサを本モジュールでは
実装しない(vp_equipment_names.pyの既存実装を再利用するだけ)。

**装備限定との違い(コード一覧の取得元)**: vp_equipment_names.py の
`list_equipment_codes_from_pak()`はユーザーのPalworld pakから実行時に
コード一覧を読む(衣装SKはユーザー環境依存)。頭装備は
`vp_headequip_filter.py`が`noue_template_manifest.json`(このアプリ自身が
持つ固定カタログ)から静的にコード一覧を導出できるため、pak読み取りは
**表示名解決(DataTable探索)のためだけ**に必要で、コード一覧そのものには
不要——`palworld_pak`が未解決/存在しなくても常にcodesは返す(内部コード
フォールバックの土台)。

**DataTable解決の拡張(2026-08-08、dev#165/#277第1弾④、本WP)**: 本モジュール
初版(上記段落)の時点ではvp_equipment_names.pyのDataTable直接解決
(`resolve_equipment_item_ids()`)が体防具(Player/Outfit)専用の行フィルタ
(`_is_body_armor_preset_row`)を持っていたため、HeadEquipコードは常に0件
(locres経路も空、装備限定と同じ制約)で内部コード表示にフォールバック
していた。本WPで`vp_equipment_names.py`へ`resolve_headequip_item_ids()`
(頭装備プリセット行専用の対応表構築。1コードに複数の色/バリアント行が
対応するのが通常であることを踏まえ、末尾"_<数字>"の有無で基準行を選ぶ)
と`resolve_display_names()`の`domain`引数("equipment"|"headequip")を追加し、
本モジュールは`domain="headequip"`で呼び出すよう変更した(下記
`list_headequip_codes()`より下のmain()参照)。

実pak実測(2026-08-08、`Pal-Windows.pak`): 64頭装備コード中62件で一意な
対応が取れ、日英中韓5言語いずれでも正しい表示名(例:
HeadEquip016→ja"金属ヘルム"/en"Metal Helm")を取得できることを確認済み。
残り2件は安全側で対応なし(既存の内部コード表示フォールバックのまま)——
詳細は`vp_equipment_names.resolve_headequip_item_ids()`のdocstring参照
(HeadEquip040=頭防具/体防具2系統から基準行が見つかる曖昧ケース、
HeadEquip014=DataTable自体にプリセット行が存在しない実データの欠落)。

CLIとしても呼べる(app_pyはpipeline\\pyをimportしない設計のため、app_py側は
本モジュールをsubprocessで起動しJSONを標準出力から受け取る想定):

    python vp_headequip_names.py <manifest_path> <palworld_pak|(空文字)> <lang> <cache_dir>

標準出力へ1行のJSON `{"ok": bool, "source": str, "detail": str,
"codes": [...], "names": {code: text, ...}}` を書く。プロセスの終了コードは
常に0(vp_equipment_names.pyのmain()と同じ理由)。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import vp_equipment_names  # noqa: E402 (resolve_display_names()を再利用)
import vp_headequip_filter  # noqa: E402

TAG = "vp_headequip_names"


def list_headequip_codes(manifest_path):
    """manifest_path(noue_template_manifest.jsonの絶対パス)から頭装備コード
    集合を返す。読み取り失敗時は空集合(呼び出し側がok=Falseとして扱う)。"""
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()
    rels = vp_headequip_filter.headequip_rels_from_manifest(manifest)
    return vp_headequip_filter.known_headequip_codes(rels)


def main():
    if len(sys.argv) != 5:
        print(f"Usage: python {os.path.basename(__file__)} "
              "<manifest_path> <palworld_pak|(empty)> <lang> <cache_dir>")
        sys.exit(2)
    manifest_path, pak_path, lang, cache_dir = sys.argv[1:5]

    codes = sorted(list_headequip_codes(manifest_path))
    if not codes:
        print(json.dumps({
            "ok": False, "source": "none",
            "detail": f"could not derive headequip codes from manifest: {manifest_path}",
            "locres_path": None, "names": {}, "codes": [],
        }, ensure_ascii=False))
        return

    if not pak_path or not os.path.exists(pak_path):
        # コードはmanifest由来で常に取れる(パイプライン内蔵カタログ)ため、
        # pak未解決でもcodesは返す(装備限定と異なりここは失敗理由にしない)。
        print(json.dumps({
            "ok": True, "source": "none",
            "detail": f"codes resolved from manifest (palworld_pak not resolved: {pak_path!r}, "
                       "display name lookup skipped)",
            "locres_path": None, "names": {}, "codes": codes,
        }, ensure_ascii=False))
        return

    names, status = vp_equipment_names.resolve_display_names(
        pak_path, lang, codes, cache_dir, domain="headequip")
    print(json.dumps({**status, "names": names, "codes": codes}, ensure_ascii=False))


if __name__ == "__main__":
    main()
