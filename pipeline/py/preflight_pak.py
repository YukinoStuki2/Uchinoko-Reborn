# -*- coding: utf-8 -*-
"""MOD pakのオフライン全数検品(ゲーム非起動)。1つでも落ちたら使用禁止。

PalModでゲーム内テストによって発覚した全敗因クラスを機械検証する:
  平坦化パス / SM6欠落 / バインドポーズずれ / スケルトン同梱 / 使用フラグ欠落 /
  ストリーミングミップ / 参照切れ

U50(2026-07-25)で構造ゲートを2つ追加した(**既定は警告、FAILにはしない**):
  G10 ライブpakに実在する全SKがこのpakに収録されているか(場所依存・名前単位)
  G11 全衣装SKの**全描画スロット**が注入アトラス t00 を指しているか
件数を締めていく運用は環境変数で行う:
  D2P_PREFLIGHT_COVERAGE / D2P_PREFLIGHT_SLOTROLE = fail | max:<件数> | warn(既定)

U50(2026-07-25 夕)で2点を仕様追随させた:
  * **非対応(コラボ系)装備の除外**(`vp_exclusions.py` が唯一の正本)。
    除外されたSKは注入もMI差し替えもされず**バニラのまま**出る(意図どおり)ので、
    G5/G5b/G10/G11 の検査対象から外す。**除外していないSKへの検査は一切
    緩めていない**(除外集合は vp_exclusions のみが決める)。
  * **マテリアル単一化**(live_template._unify_slot_materials、既定ON)により
    t01 は使われなくなり、全描画スロットのMIが t00 を参照する。G11の判定基準を
    旧「slot0->t00 / slot1->t01」から「**全描画スロットが t00**」へ更新した。

使い方: python preflight_pak.py <job.json> <mod.pak> <pak_extractルート> <cook_log>

cook_log引数(第4引数)について(2026-07-26 cooklog_fix):
  UEモード(pipeline\\cli\\convert.ps1のUE分岐)では実際にBuildCookRunで生成された
  本物のcookログ(生テキスト)が渡される。
  noueモード(既定)では実際にcookする工程が無いため、代わりに
  `pipeline\\py\\noue_master\\shader_platform_facts.json`(SM5/SM6双方でcook済みという
  固定の事実だけを持つJSON、live_template.COOK_LOG経由)が渡される。
  G7はこの2形式のどちらが来ても判定できるよう、JSON解析を先に試み、
  失敗したら生ログへの文字列検索へフォールバックする(下記G7実装参照)。
"""

import concurrent.futures
import glob
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_core as core
# dev#1198 WP-B5a: G1のマウント期待値をvp_pakwrite.COMMON_MOUNT(唯一の正本)
# から取得する。文字列のハードコード重複を避け、build_pak_from_avatar.py/
# fast_repack.pyの実配線と常に同期させるため。
import vp_pakwrite  # noqa: E402
# dev#19 tailmatch3_fix: G14(sway ABP同梱の回帰防止ゲート)用。
# hardness_key_for_intensity()はjob.sway_intensityから「揺れ有効か」を
# 判定する唯一の正本ロジック(build_pak_from_avatar.pyのsway ABPパッチ実行
# 判定と同一)なので、preflight側でも同じ関数を再利用して判定基準の重複を
# 避ける。
import sway_abp_build  # noqa: E402
# dev#1508 graceful-degrade(night_20260817 laneI): 揺れ鎖の明示的縮退の
# 判定ヘルパー(sway_exclusions_{gender}.jsonの"fully_disabled"フラグから
# 「意図的な全OFF縮退」を正当なPASSとして通す例外の判定に使う)。
import sway_degrade  # noqa: E402
# U50: 「非対応(コラボ系)」装備の除外リスト(唯一の正本)。除外されたSKは
# 注入もMI差し替えもされずバニラのままpakへ入る/入らないので、検品側も
# 同じ正本を見て検査対象から外す必要がある(pakの欠陥ではない)。
import vp_exclusions  # noqa: E402
# U18: G5/G5b用(pakに実際に同梱されたRenderSectionsのBoneMapを読むため)。
# U51(research\ue_exit→pipeline\py移設): parse_sk_structure.pyは元research\ue_exit\
# から無改変のままpipeline\py\へコピーされた(research\ue_exit\側は開発参照用に
# 残置、実行時には見ない)。同じディレクトリ(HERE、上でsys.pathへ追加済み)から
# そのままimportできる
import parse_sk_structure as sk_struct  # noqa: E402
# dev#165(2026-07-30): 性別限定ビルド(job.jsonのgenders)で要求されていない
# 性別の衣装SKは、build_pak_from_avatar.pyのPhase2で実際に注入をスキップし、
# vp_exclusions(コラボdenylist)と同じPhase3バニラコピー経路に乗る。
# preflightは別プロセスなので、同じ「注入されていない」判定をここでも
# 独立に再現する必要がある(gender_of()はSK名から性別を読む、既存の
# build_pak_from_avatar.py/build_avatar_variant_all.pyと同一関数を再利用)。
from build_avatar_variant_all import gender_of  # noqa: E402
# dev#165第2期(2026-08-08、装備限定): job.jsonのequipment_filterで選択
# されていない装備SKは、build_pak_from_avatar.pyのPhase2でメッシュ注入を
# スキップし、live_template.pyでマテリアル統一もスキップされる(=バニラの
# まま)。preflightは別プロセスなので、同じ「除外されている」判定を
# ここでも独立に再現する(_is_gender_excludedと同じパターン)。
import vp_equipment_filter  # noqa: E402
# dev#277第1弾④(2026-08-08、頭装備切り替え): job.jsonのheadequip_showで
# 選択(チェックON=表示)された頭装備は、live_template.pyがスタブ生成も
# コピーも行わず出力pakから完全に除外する(=Head/Hairと同じ「manifestに
# 無い扱い」)。preflightはmanifestの静的宣言をG4の期待値に使うため、
# 同じ除外判定をここでも再現する必要がある(_manifest_sk_counts参照)。
import vp_headequip_filter  # noqa: E402
# dev#1198 WP-B5b-fix: G13(DTの.uasset SerialSize整合検査)用。DT_PACKAGE_NAMEは
# build_pak_from_avatar.pyが唯一の正本(文字列のハードコード重複を避ける、
# WP-B5aのDT_PREFIX/COMMON_MOUNT同様の方針)。
import dt_flag_patcher  # noqa: E402
from build_pak_from_avatar import DT_PACKAGE_NAME  # noqa: E402
# dev#1508 W2a-2d(G3ゲート昇格): 共有Skeleton(SK_PalHuman_Skeleton)の
# パス定数・manifestファイル名はbuild_pak_from_avatar.pyが唯一の正本
# (DT_PACKAGE_NAMEと同じ方針、文字列のハードコード重複を避ける)。
from build_pak_from_avatar import (  # noqa: E402
    SWAY_HUB_SK_PACKAGE_NAME, SWAY_HUB_PATCH_MANIFEST_FILENAME)
import sway_shared_skeleton  # noqa: E402


def strip_body_prefix(rel):
    """dev#1198 WP-B5a: COMMON_MOUNT配線でpak entryが得るようになった
    vp_pakwrite.BODY_PREFIX("Model/Character/")を、存在すれば剥がす。
    無ければそのまま返す(将来DT系エントリ(WP-B5b、DT_PREFIX)が同居しても
    誤って書き換えない、純粋関数のため単体テスト可能)。"""
    if rel.startswith(vp_pakwrite.BODY_PREFIX):
        return rel[len(vp_pakwrite.BODY_PREFIX):]
    return rel


# ============================================================================
# G2/G3 ホワイトリスト定数(F3a、dev#1198系WP-B6の後継配線で main() 内の
# ローカル変数からモジュールレベルへ昇格)。job/vanilla_dir等の実行時データに
# 依存しない純粋なリテラル/正規表現であり、main()を完走させずに直接単体
# テストできる(tests\equipment_filter_dev165\test_preflight_g2_g3_avatar_
# select_whitelist.py 参照)。値・判定ロジックは昇格前と完全に同一
# (挙動への影響なし、可読性のためのリファクタのみ)。
# ============================================================================

# G2: 新規アセット(ModelMaterials)は既存のバニラパスに一致しなくても許可。
G2_NEW_ASSET_OK = re.compile(r".*/ModelMaterials/MainShader/[^/]+$")
# G2: アンカーファイル。新称(_divetopalworld_anchor.txt)/旧称
# (_vrm2palworld_anchor.txt、改名前に生成された既存pak向け)の両方を許容する
# (2026-07-22昼発覚。過去に生成済みのpakの検品を壊さないため。生成側は
# 改名コミット02f1f24で既に新称に統一済み)。
G2_ANCHOR_OK = re.compile(r".*_(?:divetopalworld|vrm2palworld)_anchor\.txt$")
# G2: F3a(dev#1198系WP-B6の後継配線): AvatarSelect複製素体MI(G3の
# G3_BODY_MI_WHITELIST追加4パスと同一集合、live_template.
# avatar_body_mi_package_path()が生成)もバニラに存在しない新規パスの
# ため、G3同様の狭い完全一致相当パターンで例外許可する(ModelMaterialsの
# ような広いディレクトリ単位ではなく、ファイル名までピン留めした正規表現。
# 既定(equipment_filter未使用)ビルドではこのパス自体が生成されないため
# G2の判定に影響しない=④無退行の根拠)。
# dev#994(自己レビューで発見): (?:Male|Female)を2箇所独立に書くと
# "Body/Male/AvatarSelect/MI_Player_Female_Body"のような性別取り違えの
# パスまで誤って許可してしまう(負の対照テストで実際に検出、
# test_preflight_g2_g3_avatar_select_whitelist.py参照)。名前付きグループ+
# バックリファレンスで両者を同一性別に固定する。
G2_AVATAR_SELECT_OK = re.compile(
    r".*/Body/(?P<gender>Male|Female)/AvatarSelect/MI_Player_(?P=gender)_Body\.(?:uasset|uexp)$")
# G2: dev#1170 WP-A(装備別アバター): vp_equipment_avatar._body_mi_clone_path()
# が生成する、割当アバターごとの共有ボディMIクローン先(F3a/AvatarSelectと
# 同じ発想だが名前空間を分離した別サブフォルダ、EquipAvatarMap_<10桁hex>)。
# equipment_avatar_map未設定の既定ビルドではこのパス自体が生成されないため
# G2の判定に影響しない(④無退行の根拠)。
G2_EQUIP_AVATAR_MAP_BODY_MI_OK = re.compile(
    r".*/Body/(?P<gender>Male|Female)/EquipAvatarMap_[0-9a-f]{10}/"
    r"MI_Player_(?P=gender)_Body\.(?:uasset|uexp)$")

# G3: 禁止物(共有スケルトン・素体・ストリーミングミップ・装備専用Skeleton/Physics)。
# このゲート自体はT3設計(U40)より前から存在する既存の安全境界であり、
# 「共有スケルトン・素体スケルタルメッシュ本体・Physics・ストリーミング
# ミップは改変対象外」という原則は今回も維持する(全面禁止のまま)。
#
# U42(2026-07-25、指揮者裁定): 素体共有MI(MI_Player_Male_Body/
# MI_Player_Female_Body、MaterialInstanceConstant資産。スケルタルメッシュ
# 本体でもSkeletonでもPhysicsでもubulkでもない)のみ、完全一致の
# ホワイトリストで狭く例外許可する。背景: T3(pipeline\py\live_template.py
# _inject_outfit_body_parka_textures)がこの2ファイルを「Materials[]配列内の
# 物理スロット位置がSKによって異なる競合」として安全側除外していたため、
# 多数の衣装が参照する素体のBase Textureが実機で常にバニラのまま
# (=アバターの肌色が一切乗らない)という実測不具合(docs\
# REPORT_U42_2026-07-25.md G1節)があった。ホワイトリストは意図的に
# パターンではなく4パス(2ファイル×.uasset/.uexp)の完全一致列挙とし、
# 将来他のBody配下ファイルが意図せず紛れ込んでも機械的に弾かれるよう
# 構造的に防ぐ。
# U46(2026-07-25): 体の色ズレ(茶色い体・顔の金属質模様・服のしわ)修正の
# 一環で、素体共有MIが参照するNormal/MetallicRoughnessOcclusionSpecular
# テクスチャ資産(/Body/配下、同一パス・ペイロード置換で平坦中立値に
# 差し替え。ubulk化はせず全ミップinlineへ再構成済み — G3の.ubulk全面
# 禁止には抵触しない)を追加。U42と同じ原理(完全一致の列挙、パターン
# マッチ不使用、将来の意図しない拡大を機械的に防ぐ)。live_template.py
# _flatten_normal_orm_textures参照。
# U47(2026-07-25): 素体スロット(ShadingModel=6 TwoSidedFoliage)の
# 「Subsurface Texture」がアバター自身のBase Textureへ再配線されていた
# ことが「肌の色被り」の実測原因だったため(docs\REPORT_U47_2026-07-25.md
# G1節)、この再配線を廃止し、代わりに元々の参照先テクスチャ資産自体を
# 黒へ平坦化する方式(U46のNormal/ORMと同じ技法)へ切り替えた。実測
# (work\u47_diag\probe_sss_tex.py): 該当資産は
# /Player/Body/Female/T_Player_Female_Body_SSS の1件のみで、男性素体MIも
# このFemale資産を共有参照する(Male_Body_SSSという別ファイルは存在
# しない)。U42/U46と同じ原理(完全一致の列挙、パターンマッチ不使用)で
# 2パス(1ファイル×.uasset/.uexp)を追加する。
# F3a(dev#1198系WP-B6の後継配線、work\rd_1198_wpb\PROPOSAL.md §6.3):
# equipment_filter有効ビルドで選択装備だけへ焼くAvatarSelect複製素体MI
# (live_template.avatar_body_mi_package_path()、leaf名は元と同一、直前に
# AvatarSelectサブフォルダを1つ挟むだけ)。U42/U46/U47と同じ原理
# (完全一致列挙、パターンマッチ不使用)で2ファイル×.uasset/.uexpの
# 4パスを追加する。既定(equipment_filter未使用)ビルドではこのパスは
# 一切生成されないため、この追加自体はG3の判定に影響しない
# (④無退行の根拠)。
G3_BODY_MI_WHITELIST = frozenset({
    "Player/Body/Male/MI_Player_Male_Body.uasset",
    "Player/Body/Male/MI_Player_Male_Body.uexp",
    "Player/Body/Female/MI_Player_Female_Body.uasset",
    "Player/Body/Female/MI_Player_Female_Body.uexp",
    "Player/Body/Female/T_Player_Female_Body_SSS.uasset",
    "Player/Body/Female/T_Player_Female_Body_SSS.uexp",
    "Player/Body/Male/AvatarSelect/MI_Player_Male_Body.uasset",
    "Player/Body/Male/AvatarSelect/MI_Player_Male_Body.uexp",
    "Player/Body/Female/AvatarSelect/MI_Player_Female_Body.uasset",
    "Player/Body/Female/AvatarSelect/MI_Player_Female_Body.uexp",
} | {
    f"Player/Body/{gender}/T_Player_{gender}_Body_{suffix}.{ext}"
    for gender in ("Male", "Female")
    for suffix in ("N", "max_N", "min_N", "M")
    for ext in ("uasset", "uexp")
})

# G3: dev#1170 WP-A(装備別アバター): vp_equipment_avatar._body_mi_clone_path()
# が生成する共有ボディMIクローン(G2_EQUIP_AVATAR_MAP_BODY_MI_OK正本コメント
# 参照)。G3は既存G3_BODY_MI_WHITELIST(完全一致列挙)に加えて、この1件だけ
# パターン方式(G2_NEW_ASSET_OK/G3_EQUIP_AVATAR_MAP_TEX_UBULK_OKと同じ発想)
# を採用する——割当アバターごとに異なるハッシュを持つ可変パスのため完全一致
# 列挙では列挙しきれない。既定(equipment_avatar_map未使用)ビルドではこの
# パス自体が生成されないため、G3の判定に影響しない(④無退行の根拠)。
G3_EQUIP_AVATAR_MAP_BODY_MI_OK = re.compile(
    r"^Player/Body/(?P<gender>Male|Female)/EquipAvatarMap_[0-9a-f]{10}/"
    r"MI_Player_(?P=gender)_Body\.(?:uasset|uexp)$")

# G3: dev#1170 WP-A: 装備専用のバニラ"_B"(BaseColor)テクスチャは通常
# _unify_slot_materials()によりテンプレートから除外されているが、
# equipment_avatar_map使用時はvp_equipment_avatar.py がバニラ実在パスへ
# 割当アバターのアトラスを焼き込んで**追加**する(新規名アセットではない
# ——work\rd_1170_mesh\FINDINGS.mdの実機実証済み方式)。バニラの装備専用
# テクスチャはubulk形式(ストリーミングミップ分離)が実測上多いため、G3の
# ".ubulk"全面禁止に触れる。対象を"Player/Outfit/SK_Player_{gender}_
# Outfit_<code>/"配下のTexture2Dアセット(拡張子問わず)に厳密に絞った
# パターンで例外許可する(Body/Skeleton配下には一切触れない、G2の
# MainShaderホワイトリストと同じ「ディレクトリ単位で広げるがカテゴリは
# 狭く絞る」設計)。既定ビルドではequipment_avatar_map未使用のためこの
# パス自体が(内容が変わるだけで)既にvanilla_setに存在する通常のG2判定を
# 通過するのみで、この定数自体の追加はG3判定に一切影響しない(④無退行)。
G3_EQUIP_AVATAR_MAP_TEX_UBULK_OK = re.compile(
    r"^Player/Outfit/SK_Player_(?P<gender>Male|Female)_Outfit_[^/]+/"
    r"(?:[^/]+/)?T_Player_(?P=gender)_Outfit_[^/]+\.ubulk$")

# G3: dev#1508 W2a-2d(G3ゲート昇格): 共有Skeleton(SK_PalHuman_Skeleton)は
# 「共有スケルトン不可侵」というG3本来の禁止対象そのものだが、汎用ハブ
# 配線(Phase 3.7)は内容だけのreparentパッチ(配列長・NameMap不変)を
# 意図的に同梱する設計(dev#1508)。この2パスに限り、盲目的なパス一致
# ホワイトリスト(U42等と同型)ではなく、`check_sway_hub_shared_skeleton_
# patch()`による独立したバイトレベル検証(バニラとの実差分が
# `sway_hub_patch_manifest.json`の予定パッチと厳密一致すること)を
# 通った場合だけ許可する——本frozensetはforbidden判定から2パスを
# 除外するだけで、実際の可否はmain()内の専用ゲート(下記)が別途決める。
G3_SWAY_HUB_SK_WHITELIST = frozenset({
    f"Skeleton/Human/{SWAY_HUB_SK_PACKAGE_NAME}.uasset",
    f"Skeleton/Human/{SWAY_HUB_SK_PACKAGE_NAME}.uexp",
})


def _is_gender_excluded(rel_or_name, requested_genders):
    """dev#165: このSKが「job.jsonのgendersで要求されていない性別」のため
    注入をスキップされた(=バニラのまま)ものかどうかを判定する。
    既定(両性別要求)では常にFalse(=既存の挙動に対する新しい分岐に一切
    入らない)。Head/Hair/HeadEquipやMI_*等、_Male_/_Female_を名前に
    含まないファイルはgender_of()が例外を送出するため、判定不能=除外しない
    (性別非依存の資産には一切影響しない)。"""
    if requested_genders >= {"Male", "Female"}:
        return False
    try:
        g = gender_of(os.path.basename(str(rel_or_name)))
    except Exception:
        return False
    return g not in requested_genders


def _g12_is_scoped_asset(rel):
    """dev#336(2026-08-08)G12実体検査化: WP文言「outfit SK/素体/MI」のうち、
    「①pak内に存在するならバニラと同一であること」を**不在必須**として
    厳格に検査する対象資産かどうかを判定する。

    対象: 衣装MI(ファイル名がMI_で始まる)と素体(Player/Body/Male|Female/
    配下の全ファイル、MI・テクスチャとも)。work\\f2_build_verify\\
    PROGRESS.mdの実測(F2ビルド、genders=["Female"]):
    REFに対しF2で消えた194エントリは全てこのスコープに一致する
    (素体MI/テクスチャ10件 + 各衣装SKのMI/テクスチャ群)。

    対象外: 衣装SKメッシュ本体(SK_*.uasset/.uexp)——**除外性別のSKメッシュは
    バニラ形状のまま残るのが正しい設計**(同PROGRESS.mdでバイトレベル実証:
    メッシュは真の game 本体pakと完全一致=注入なし)。これは
    check_g12_gender_isolation() 側の②(_g12_sk_atlas_violations、アトラス
    参照検査)の対象になる。衣装アイテムの個別テクスチャ(T_Player_*_Outfit_*)
    も対象外——gendersと無関係にビルド間で出入りしうることをPROGRESS.mdで
    確認済みで、対象に含めると誤検知する。"""
    base = os.path.basename(rel)
    if base.startswith("MI_"):
        return True
    return "/Body/Male/" in rel or "/Body/Female/" in rel


def _is_equipment_excluded(rel_or_name, requested_equipment):
    """dev#165第2期: このSKが「job.jsonのequipment_filterで選択されていない
    装備」のため注入・マテリアル統一をスキップされた(=バニラのまま)もの
    かどうかを判定する。requested_equipment=None(既定・絞り込み無し)では
    常にFalse(=既存の挙動に対する新しい分岐に一切入らない)。Head/Hair/
    HeadEquipやMI_*等、SK_Player_{Male,Female}_Outfit_*以外の資産は
    equipment_code()がNoneを返すため、判定不能=除外しない(対象外の資産には
    影響しない)。"""
    if not requested_equipment:
        return False
    code = vp_equipment_filter.equipment_code(os.path.basename(str(rel_or_name)))
    if code is None:
        return False
    return code not in requested_equipment


def _g5_expected_count(n_total, n_excluded_sk, n_gender_excluded_sk,
                        n_equipment_excluded_sk):
    """G5/G5bカバレッジゲートの期待検査数を返す(dev#165第2期・2026-08-08
    修正で抽出)。

    検査対象(sk_uassets、main()参照)は
    denylist除外∪gender除外∪equipment除外のいずれにも当たらないSKだけに
    絞り込まれるため、期待数もその3種の除外を**すべて**差し引かなければ
    ならない。equipment除外分を引き忘れると、job.jsonのequipment_filterで
    絞り込んだビルドでは検査対象(sk_uassets)が大きく減るのに期待数だけが
    元のまま(pak収録数から denylist/gender除外のみを引いた値)になり、
    構造的に一致しなくなって誤FAILする(オーナー実測: pak has 62,
    equipment_filterで60枚除外、実際に検査できたのは2枚なのに旧式は
    期待値62のままだった)。

    引数はすべて非負整数の件数(既定=絞り込み無しではequipment/genderの
    除外数は0なので、この関数はn_total - n_excluded_skと一致し既存挙動を
    完全に保つ)。
    """
    return n_total - n_excluded_sk - n_gender_excluded_sk - n_equipment_excluded_sk


results = []
soft_results = []


def gate(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


G13_NAME = "G13 DT .uasset SerialSize matches its paired .uexp size"
G14_NAME = "G14 sway ABP entries present when job.sway_intensity requests wobble (dev#19)"


def check_sway_abp_presence(job, pak_entries_full):
    """dev#19 tailmatch3_fix: `work\\rd_19_swaydiag\\DIAG.md` が機械診断した
    「job.jsonにsway_intensityキーが無い(または"none"/未知値)せいで
    sway ABPパッチが完全スキップされ、揺れが全滅したpakでもG1-G13が
    無関係にALL PASSしてしまう」事故の回帰防止ゲート。

    job["sway_intensity"] が有効値(hard/normal/soft、
    sway_abp_build.hardness_key_for_intensity()が正本判定)なら、pak内に
    揺れABP(`Imp_Cloth`配下の`ABP_*.uasset`/`.uexp`、
    sway_abp_build.sway_abp_pak_entries()が同梱する形式)が1件以上
    存在しなければFAILする。sway_intensity が未指定/"none"/未知値の場合は
    ABPパッチ自体が意図的にno-opする設計(sway_abp_build.py冒頭コメント)
    のため、この場合はABPエントリ0件が正しい挙動であり検査対象外
    (常にPASS、既存挙動を変えない)。

    Args:
        job: core.load_job()が返すjob dict。
        pak_entries_full: core.read_pak_entries()の戻り値の第2要素
            ({rel: {...}})——G13と同じ、pak内相対パスをキーとする辞書。

    Returns:
        (ok, detail) のタプル。
    """
    hardness_key = sway_abp_build.hardness_key_for_intensity(job.get("sway_intensity"))
    if hardness_key is None:
        return True, (
            f"sway_intensity={job.get('sway_intensity')!r} (disabled/unknown) "
            "-- sway ABP patch is a no-op by design, gate skipped")
    n_abp = sum(1 for p in pak_entries_full
                if "Imp_Cloth" in p and "ABP_" in p
                and (p.endswith(".uasset") or p.endswith(".uexp")))
    ok = n_abp > 0
    detail = (f"sway_intensity={job.get('sway_intensity')!r} (hardness={hardness_key}), "
               f"sway ABP entries in pak={n_abp} (want >0)")
    return ok, detail


def check_dt_serial_size(mod_pak, pak_entries_full, dt_uasset_rel, dt_uexp_rel):
    """dev#1198 WP-B5b-fix: G13の判定ロジック本体を、main()から独立して単体
    テストできる純粋寄りの関数として切り出したもの(pak_entries_fullの読み
    取り以外に副作用は無い)。gate()を直接呼ばず (ok: bool, detail: str) を
    返すので、テストは実物のpakファイルを構築せずとも、任意のバイト列を
    仕込んだ一時ファイル+手組みのpak_entries_full辞書で正負両対照を検証
    できる。

    Args:
        mod_pak: 検品対象pakのパス(dt_uasset_rel/dt_uexp_relのバイトを
            data_offset/sizeで読み出すために開く)。
        pak_entries_full: core.read_pak_entries()の戻り値の第2要素
            ({rel: {"compression","data_offset","size",...}})。
        dt_uasset_rel / dt_uexp_rel: DTの.uasset/.uexpのpak内相対パス
            (vp_pakwrite.normalize_rel(..., vp_pakwrite.DT_PREFIX)の戻り値)。

    Returns:
        (ok, detail) のタプル。
    """
    if dt_uasset_rel not in pak_entries_full or dt_uexp_rel not in pak_entries_full:
        return False, (
            f"DT entries not found in pak (expected {dt_uasset_rel!r} and "
            f"{dt_uexp_rel!r} -- the dev#1198 head/hair fix DT copy is expected "
            "in every build)")
    dt_uasset_entry = pak_entries_full[dt_uasset_rel]
    dt_uexp_entry = pak_entries_full[dt_uexp_rel]
    if dt_uasset_entry["compression"] != 0 or dt_uexp_entry["compression"] != 0:
        return False, (
            "compressed DT entry detected (this pipeline should always produce "
            "uncompressed entries)")
    with open(mod_pak, "rb") as pf:
        pf.seek(dt_uasset_entry["data_offset"])
        dt_uasset_bytes = pf.read(dt_uasset_entry["size"])
        pf.seek(dt_uexp_entry["data_offset"])
        dt_uexp_bytes = pf.read(dt_uexp_entry["size"])
    try:
        declared_size = dt_flag_patcher.read_export_serial_size(dt_uasset_bytes)
    except dt_flag_patcher.DtStructureError as e:
        return False, str(e)
    # .uexpの末尾4バイトはパッケージタグのフッタで、exportのSerialSizeには
    # 含まれない(work/lab1_crash_triage/parse_export_table.pyの実測:
    # バニラ/パッチ後いずれも actual - serial_size == 4 で一致)。
    actual_payload_size = len(dt_uexp_bytes) - 4
    ok = declared_size == actual_payload_size
    detail = (f"declared(.uasset SerialSize)={declared_size} "
              f"actual(.uexp size - 4B tag)={actual_payload_size} "
              f"(.uexp on-disk size={len(dt_uexp_bytes)})")
    return ok, detail


def diff_shared_skeleton_catalog(vanilla_catalog, mod_catalog):
    """dev#1508 W2a-2d(G3ゲート昇格): バニラ(vanilla_catalog)とmod
    (mod_catalog)の共有Skeletonカタログ(`sway_shared_skeleton.
    full_skeleton_catalog()`と同形式、`{"bone_count","bones":[{"name",
    "parent_idx","quat","pos","scale"},...]}`)を比較し、実際に変化した
    骨だけを`{name: {"old_parent_idx","new_parent_idx","transform_changed",
    "quat","pos","scale"}}`で返す。

    content-onlyパッチ(`sway_shared_skeleton.py`、配列長・NameMap不変が
    前提)を検査する関数のため、骨名集合が食い違う場合はその前提が崩れて
    いる異常として`ValueError`を送出する(値を寄せて合わせず、構造の
    異常として検出する)。"""
    v_by_name = {b["name"]: b for b in vanilla_catalog["bones"]}
    m_by_name = {b["name"]: b for b in mod_catalog["bones"]}
    if set(v_by_name) != set(m_by_name):
        only_v = sorted(set(v_by_name) - set(m_by_name))[:3]
        only_m = sorted(set(m_by_name) - set(v_by_name))[:3]
        raise ValueError(
            "shared skeleton bone name set changed between vanilla and mod "
            f"(not a content-only patch): only-in-vanilla={only_v} "
            f"only-in-mod={only_m}")
    diffs = {}
    for name, vb in v_by_name.items():
        mb = m_by_name[name]
        parent_changed = vb["parent_idx"] != mb["parent_idx"]
        transform_changed = (list(vb["quat"]) != list(mb["quat"])
                              or list(vb["pos"]) != list(mb["pos"])
                              or list(vb["scale"]) != list(mb["scale"]))
        if parent_changed or transform_changed:
            diffs[name] = {
                "old_parent_idx": vb["parent_idx"], "new_parent_idx": mb["parent_idx"],
                "transform_changed": transform_changed,
                "quat": mb["quat"], "pos": mb["pos"], "scale": mb["scale"],
            }
    return diffs


def _had_sway_source_input(job):
    """dev#1508 W1b ゲートfail-closed化(work\\night_20260817\\briefs\\
    laneG_vrm_w1b.md「3. ゲートのfail-closed化」): sway_enable=trueかつ
    入力にPB/SB揺れ源が最低1件でも存在したか——`sway_allocator.allocate()`
    の判定結果(0件になりうる)を経由せず、入力サイドカーの生データを
    直接見て判定する。

    G3b/G15の「skip」判定を「揺れ源が最初から皆無なら正当なskip・揺れ源が
    存在するのに結果が0鎖ならfail-closed」へ振り分けるための入口。

    prefab: job["physbones_json"](Unity輸出サイドカー、convert.ps1が
    job.resolved.jsonへ焼き込む)の"physbones"リストが非空か。
    VRM: job_dir/converted/springbones.json(dev#1508 W1b、step01が常に
    書き出すサイドカー)の"springbones"リストが非空か。

    job["sway_enable"]が偽(またはキー自体が無い)なら常にFalse
    (sway自体が無効なジョブでのgate skipは従来どおり正当)。"""
    if not job.get("sway_enable"):
        return False
    physbones_path = job.get("physbones_json")
    if physbones_path and os.path.isfile(physbones_path):
        try:
            with open(physbones_path, encoding="utf-8") as f:
                if json.load(f).get("physbones"):
                    return True
        except (OSError, json.JSONDecodeError):
            pass
    job_dir = job.get("job_dir")
    if job_dir:
        springbones_path = os.path.join(job_dir, "converted", "springbones.json")
        if os.path.isfile(springbones_path):
            try:
                with open(springbones_path, encoding="utf-8") as f:
                    if json.load(f).get("springbones"):
                        return True
            except (OSError, json.JSONDecodeError):
                pass
    return False


def _sway_degrade_explains_zero_chains(job):
    """dev#1508 graceful-degrade(揺れ鎖の明示的縮退、night_20260817
    laneI): `_had_sway_source_input(job)`がTrue(=揺れ源は入力にある)
    なのにpakへ揺れ鎖が1本も乗らなかった場合、`check_sway_hub_shared_
    skeleton_patch()`(G3b)/`check_sway_source_gate_against_pak()`(G15)
    は本来これをFAIL(#1546のfail-closed化、「配線結果が0鎖」という
    無言の欠落=dev#1508バグそのもの)として扱う。

    本関数は、その特定のケースが**laneIの縮退ループが実際に「これ以上
    リトライしても直らない」と判定してsway全体を意図的にOFFへ倒した**
    結果であることを、`step02_retarget.py`が書く`converted\\
    sway_exclusions_{gender}.json`(性別ごとに単独プロセスが書く、
    並列競合の無いファイル——`sway_exclusions.json`(両性別マージの
    ユーザー向けビュー)は書き込みがロック付きread-modify-writeで
    best-effortのため、fail-closed判定の正本には使わない)から機械
    判定する。

    判定規則(G3b/G15はpak全体を見るだけで性別を区別しないため、AND規則
    で安全側に倒す): 揺れ源ユニットが実在した(`total_units > 0`)全ての
    性別ファイルについて`fully_disabled=true`であること。**1つでも
    `total_units > 0`かつ`fully_disabled`でない性別があればFalse**
    (=その性別はまだ鎖が残っているはず、または縮退が実際には走らずに
    0鎖になった=本当のバグの可能性、fail-closedを維持)。
    `total_units > 0`の性別が1件も見つからなければ(ファイル欠落・
    全性別0件)False(=縮退ループが実際に走った証拠が無い、fail-closedを
    維持)。壊れた(パース不能な)ファイルもFalse(安全側)。"""
    job_dir = job.get("job_dir")
    if not job_dir:
        return False
    found_disabled_gender = False
    for gender in ("male", "female"):
        path = os.path.join(job_dir, "converted", f"sway_exclusions_{gender}.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                report = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False
        if int(report.get("total_units", 0) or 0) <= 0:
            continue  # この性別はそもそも揺れ源ユニットが無かった(sway無効等)、判定対象外
        if not sway_degrade.explains_zero_chains(report):
            return False
        found_disabled_gender = True
    return found_disabled_gender


def check_sway_hub_shared_skeleton_patch(job, vanilla_dir, mod_pak, pak_entries_full):
    """dev#1508 W2a-2d(G3ゲート昇格、指揮者指示書「1. G3ゲートの昇格」):
    共有Skeleton(SK_PalHuman_Skeleton)がpakに含まれる場合、バニラとの
    実差分を独立に計算し、`job_dir/converted/sway_hub_patch_manifest.json`
    (`build_pak_from_avatar._run_sway_hub_reparent_patch()`がPhase 3.7で
    書き出す「予定パッチ」)と厳密一致することを検査する。

    旧G3は「Skeleton/」を含むパスを問答無用でFORBIDDENと判定していた
    ため、共有Skeletonがpakに含まれる限り常にFAILしていた(PR #1533実測、
    work\\master_writer_progress.md 462-473行)。本関数は、その2エントリ
    (.uasset/.uexp)「だけ」に限定した例外条件——manifestを盲目的に信用
    するのではなく、実際にpakへ収まったバイトを自分でスキャンして
    manifestと突き合わせる——を提供する(manifestを書き換えるだけでは
    通らない設計。「共有スケルトン不可侵」という保護の意図自体は不変)。

    比較は双方向(厳密一致): manifestに無い実差分(unexpected)・
    manifestにあるのに実差分に現れない項目(missing、パッチが適用されず
    に終わった可能性)・実差分とmanifestの内容が食い違う項目
    (mismatched、新親や座標が計画と異なる)のいずれもFAILとする。

    Returns:
        (ok: bool, detail: str) のタプル。
        エントリがpakに存在しなければ(sway hub無効時の既定経路)常に
        (True, ...)を返す——「差分ゼロ=従来どおりPASS」(タスク仕様)。
    """
    rel_uasset = vp_pakwrite.normalize_rel(
        "Skeleton/Human/" + SWAY_HUB_SK_PACKAGE_NAME + ".uasset", vp_pakwrite.BODY_PREFIX)
    rel_uexp = vp_pakwrite.normalize_rel(
        "Skeleton/Human/" + SWAY_HUB_SK_PACKAGE_NAME + ".uexp", vp_pakwrite.BODY_PREFIX)
    present_uasset = rel_uasset in pak_entries_full
    present_uexp = rel_uexp in pak_entries_full
    if not present_uasset and not present_uexp:
        # dev#1508 W1b fail-closed化: sway_enable+PB/SB揺れ源が入力に
        # 存在するのに共有Skeletonパッチが一切pakに乗っていないのは、
        # 「揺れ源はあったのに配線結果が0鎖だった」ことの直接証拠
        # (laneG_vrm_w1b.md「3. ゲートのfail-closed化」)。従来の
        # 「差分ゼロ=常にPASS」は、揺れ源が最初から無い(=sway無効/
        # PB・SB非搭載アバター)場合にのみ正当なので、そちらだけ引き続き
        # PASSにする。
        #
        # dev#1508 graceful-degrade(揺れ鎖の明示的縮退、night_20260817
        # laneI)追加例外: `_sway_degrade_explains_zero_chains()`が
        # Trueを返す場合(=縮退ループが実際に「これ以上リトライしても
        # 直らない」と判定してsway全体を意図的にOFFへ倒し、その事実が
        # sway_exclusions_{gender}.jsonへ記録されている)は、0鎖を
        # dev#1508バグではなく正当な縮退として通す。
        if _had_sway_source_input(job) and not _sway_degrade_explains_zero_chains(job):
            return False, (f"sway_enable + PB/SB source input present but no "
                            f"{SWAY_HUB_SK_PACKAGE_NAME} entries in pak "
                            "(fail-closed: sway wiring produced 0 chains, "
                            "dev#1508 W1b)")
        return True, (f"no {SWAY_HUB_SK_PACKAGE_NAME} entries in pak "
                       "(sway hub patch not shipped, gate skipped, or gracefully "
                       "degraded to fully-disabled -- dev#1508 laneI)")
    if present_uasset != present_uexp:
        return False, (f"only one of .uasset/.uexp present for "
                        f"{SWAY_HUB_SK_PACKAGE_NAME} (uasset={present_uasset}, "
                        f"uexp={present_uexp}) -- partial shared-skeleton entry, refusing")

    manifest_path = os.path.join(job["job_dir"], "converted", SWAY_HUB_PATCH_MANIFEST_FILENAME)
    if not os.path.isfile(manifest_path):
        return False, (f"{SWAY_HUB_SK_PACKAGE_NAME} entries present in pak but "
                        f"{SWAY_HUB_PATCH_MANIFEST_FILENAME} sidecar is missing "
                        "(fail-closed: cannot verify the shared-skeleton patch was "
                        "applied only as planned)")
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return False, f"failed to read {SWAY_HUB_PATCH_MANIFEST_FILENAME}: {e}"

    vanilla_catalog_path = os.path.join(vanilla_dir, "sk_palhuman_full.json")
    if not os.path.isfile(vanilla_catalog_path):
        return False, (f"vanilla shared-skeleton catalog not found: "
                        f"{vanilla_catalog_path} -- cannot compute the actual diff "
                        "(fail-closed)")
    try:
        with open(vanilla_catalog_path, encoding="utf-8") as f:
            vanilla_catalog = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return False, f"failed to read vanilla shared-skeleton catalog: {e}"

    uasset_e = pak_entries_full[rel_uasset]
    uexp_e = pak_entries_full[rel_uexp]
    if uasset_e["compression"] != 0 or uexp_e["compression"] != 0:
        return False, (f"compressed {SWAY_HUB_SK_PACKAGE_NAME} entry detected "
                        "(this pipeline should always produce uncompressed entries)")
    with open(mod_pak, "rb") as pf:
        pf.seek(uasset_e["data_offset"])
        uasset_bytes = pf.read(uasset_e["size"])
        pf.seek(uexp_e["data_offset"])
        uexp_bytes = pf.read(uexp_e["size"])

    tmp_dir = os.path.join(job["job_dir"], "build", "preflight_g3_sway_hub_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_uasset = os.path.join(tmp_dir, SWAY_HUB_SK_PACKAGE_NAME + ".uasset")
    tmp_uexp = os.path.join(tmp_dir, SWAY_HUB_SK_PACKAGE_NAME + ".uexp")
    with open(tmp_uasset, "wb") as f:
        f.write(uasset_bytes)
    with open(tmp_uexp, "wb") as f:
        f.write(uexp_bytes)
    try:
        mod_catalog = sway_shared_skeleton.full_skeleton_catalog(tmp_uasset, tmp_uexp)
    except sway_shared_skeleton.SharedSkeletonError as e:
        return False, f"failed to scan {SWAY_HUB_SK_PACKAGE_NAME} in the mod pak: {e}"

    try:
        actual_diffs = diff_shared_skeleton_catalog(vanilla_catalog, mod_catalog)
    except ValueError as e:
        return False, str(e)

    planned = {}
    for step in manifest.get("steps", []):
        name = step.get("target_name")
        if name:
            planned[name] = step

    unexpected = sorted(set(actual_diffs) - set(planned))
    missing = sorted(set(planned) - set(actual_diffs))
    mismatched = []
    for name in sorted(set(actual_diffs) & set(planned)):
        a = actual_diffs[name]
        p = planned[name]
        if (a["new_parent_idx"] != p.get("new_parent_idx")
                or a["transform_changed"] != p.get("transform_changed")
                or (a["transform_changed"] and (
                    list(a["quat"]) != list(p.get("quat", []))
                    or list(a["pos"]) != list(p.get("pos", []))
                    or list(a["scale"]) != list(p.get("scale", []))))):
            mismatched.append(name)

    ok = not unexpected and not missing and not mismatched
    detail_parts = [f"{len(actual_diffs)} bone(s) differ from vanilla, "
                     f"{len(planned)} planned in manifest"]
    if unexpected:
        detail_parts.append(f"unplanned diff(s) not in manifest: {unexpected[:5]}")
    if missing:
        detail_parts.append(f"planned in manifest but not actually applied: {missing[:5]}")
    if mismatched:
        detail_parts.append(f"applied differently than planned: {mismatched[:5]}")
    return ok, "; ".join(detail_parts)


def _load_mod_shared_skeleton_catalog(job, mod_pak, pak_entries_full):
    """`check_sway_hub_shared_skeleton_patch()`と同じ手順(pak内
    SK_PalHuman_Skeletonの.uasset/.uexpバイトを切り出し、
    `sway_shared_skeleton.full_skeleton_catalog()`でカタログ化)を、G15
    (`check_sway_source_gate_against_pak()`)からも独立に呼べるよう関数化
    したもの(dev#1508 追加防衛線、オーナー裁定2026-08-16)。

    戻り値: (mod_catalog または None, detail文字列)。エントリがpakに存在
    しない/破損している場合は(None, 理由)を返す(呼び出し側がgate自体を
    スキップするか判断する)。"""
    rel_uasset = vp_pakwrite.normalize_rel(
        "Skeleton/Human/" + SWAY_HUB_SK_PACKAGE_NAME + ".uasset", vp_pakwrite.BODY_PREFIX)
    rel_uexp = vp_pakwrite.normalize_rel(
        "Skeleton/Human/" + SWAY_HUB_SK_PACKAGE_NAME + ".uexp", vp_pakwrite.BODY_PREFIX)
    present_uasset = rel_uasset in pak_entries_full
    present_uexp = rel_uexp in pak_entries_full
    if not present_uasset or not present_uexp:
        return None, (f"{SWAY_HUB_SK_PACKAGE_NAME} .uasset/.uexp not both present in pak "
                       f"(uasset={present_uasset}, uexp={present_uexp})")

    uasset_e = pak_entries_full[rel_uasset]
    uexp_e = pak_entries_full[rel_uexp]
    if uasset_e["compression"] != 0 or uexp_e["compression"] != 0:
        return None, (f"compressed {SWAY_HUB_SK_PACKAGE_NAME} entry detected "
                       "(this pipeline should always produce uncompressed entries)")
    with open(mod_pak, "rb") as pf:
        pf.seek(uasset_e["data_offset"])
        uasset_bytes = pf.read(uasset_e["size"])
        pf.seek(uexp_e["data_offset"])
        uexp_bytes = pf.read(uexp_e["size"])

    tmp_dir = os.path.join(job["job_dir"], "build", "preflight_g15_sway_source_gate_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_uasset = os.path.join(tmp_dir, SWAY_HUB_SK_PACKAGE_NAME + ".uasset")
    tmp_uexp = os.path.join(tmp_dir, SWAY_HUB_SK_PACKAGE_NAME + ".uexp")
    with open(tmp_uasset, "wb") as f:
        f.write(uasset_bytes)
    with open(tmp_uexp, "wb") as f:
        f.write(uexp_bytes)
    try:
        return sway_shared_skeleton.full_skeleton_catalog(tmp_uasset, tmp_uexp), ""
    except sway_shared_skeleton.SharedSkeletonError as e:
        return None, f"failed to scan {SWAY_HUB_SK_PACKAGE_NAME} in the mod pak: {e}"


G15_NAME = "G15 sway source gate final line of defense (step01 snapshot donor map vs pak RefSkeleton, dev#1508)"


def check_sway_source_gate_against_pak(job, vanilla_dir, mod_pak, pak_entries_full):
    """dev#1508 追加防衛線(オーナー裁定2026-08-16): 「ソース基準ゲートを
    preflightにも最終防衛線として追加する」。主防壁はstep02の早期
    fail-closed(`run_sway_source_gate()`)だが、本ゲートはさらに
    **step02〜pak組み立ての間の破壊**(パッチの取りこぼし・上書き消失等)
    を塞ぐ多層防御として、`job_dir/converted/sway_source_donor_map_
    {gender}.json`(step02が書き出す、そのgenderで実際にゲートを通過した
    「ソース骨 -> donor骨」対応表)を読み、各donor骨がpakの共有Skeleton
    (SK_PalHuman_Skeleton)側でバニラから実際に変化していることを検査する。

    **検査の性質(スコープの限定、正直な設計判断)**: 生座標での「step01の
    値とpak内座標の完全一致」は、avatar_arm全体がstep01からstep02にかけて
    グローバルスケール・retargetを経るため原理的に無意味
    (`sway_source_gate.py`モジュールdocstring「Transform完全一致」節と
    同じ理由)。加えてpakのRefSkeleton座標系はBlender側(cm/m・軸変換)とも
    異なるため、両者を直接数値比較することもできない。そのため本ゲートは
    「donor骨がバニラの初期値のまま(=パッチが当たらなかった/消失した)で
    ないこと」——`diff_shared_skeleton_catalog()`(G3bと共通のロジック、
    vanilla_catalogとmod_catalogの実差分を計算する)の差分集合に、
    donor_mapの全donor骨が含まれることを検査する。sway_hub_patch_
    manifest.json(計画基準)ではなく、step02が実際に検査を通した
    ソース骨集合(`sway_source_donor_map_{gender}.json`)を基準にする点が
    G3bとの違い(G3bは計画とpakの突き合わせ、G15はゲート通過実績とpakの
    突き合わせ)。

    sway無効/donor_mapファイルが存在しない(=そのgenderでsway_enable=偽
    だった、または旧バージョンのstep02で変換された)場合は従来動作として
    スキップ(True, ...)を返す。"""
    conv = os.path.join(job["job_dir"], "converted")
    donor_map_paths = [
        os.path.join(conv, f"sway_source_donor_map_{g}.json") for g in ("male", "female")]
    donor_map_paths = [p for p in donor_map_paths if os.path.isfile(p)]
    if not donor_map_paths:
        # dev#1508 W1b fail-closed化(laneG_vrm_w1b.md「3. ゲートの
        # fail-closed化」): sway_enable+PB/SB揺れ源が入力に存在するのに
        # donor_mapファイル自体が1つも書かれていないのは、「揺れ源はあった
        # のに配線結果が0鎖だった」ことの証拠(step02が0鎖なら
        # sway_source_donor_map_{gender}.jsonを書かない設計のため)。
        # 揺れ源が最初から無い場合(=sway無効/PB・SB非搭載)のみ引き続き
        # 正当なskipとしてPASSする。
        #
        # dev#1508 graceful-degrade(揺れ鎖の明示的縮退、night_20260817
        # laneI)追加例外: sway全体を意図的にOFFへ倒した場合
        # (`run_sway_source_gate()`が対象骨0件でno-op returnし、
        # donor_mapファイル自体を書かない)も、この分岐に到達する。
        # `_sway_degrade_explains_zero_chains()`がそれを正当な縮退と
        # 確認できればPASSにする(G3bと同じ例外条件)。
        if _had_sway_source_input(job) and not _sway_degrade_explains_zero_chains(job):
            return False, ("sway_enable + PB/SB source input present but no "
                            "sway_source_donor_map_{gender}.json found "
                            "(fail-closed: sway wiring produced 0 chains, "
                            "dev#1508 W1b)")
        return True, ("no sway_source_donor_map_{gender}.json found (sway disabled, "
                       "gracefully degraded to fully-disabled (dev#1508 laneI), "
                       "or converted with a pre-dev#1508 pipeline) -- gate skipped")

    all_donors = {}
    for p in donor_map_paths:
        try:
            with open(p, encoding="utf-8") as f:
                all_donors.update(json.load(f))
        except (OSError, json.JSONDecodeError) as e:
            return False, f"failed to read {p}: {e}"
    if not all_donors:
        # 同上: donor_mapファイル自体は書かれたが中身が空(=配線結果0鎖)の
        # ケースも、揺れ源が存在した以上fail-closed対象にする。
        # dev#1508 graceful-degrade追加例外(上記と同一条件)。
        if _had_sway_source_input(job) and not _sway_degrade_explains_zero_chains(job):
            return False, ("sway_enable + PB/SB source input present but "
                            "sway_source_donor_map_{gender}.json is empty "
                            "(fail-closed: sway wiring produced 0 chains, "
                            "dev#1508 W1b)")
        return True, "donor map(s) present but empty (no judged-swaying bones) -- gate skipped"

    vanilla_catalog_path = os.path.join(vanilla_dir, "sk_palhuman_full.json")
    if not os.path.isfile(vanilla_catalog_path):
        return False, (f"vanilla shared-skeleton catalog not found: "
                        f"{vanilla_catalog_path} -- cannot compute the actual diff "
                        "(fail-closed)")
    try:
        with open(vanilla_catalog_path, encoding="utf-8") as f:
            vanilla_catalog = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return False, f"failed to read vanilla shared-skeleton catalog: {e}"

    mod_catalog, detail = _load_mod_shared_skeleton_catalog(job, mod_pak, pak_entries_full)
    if mod_catalog is None:
        return False, (f"donor map(s) declare {len(set(all_donors.values()))} donor bone(s) "
                        f"but the pak's shared-skeleton could not be read: {detail}")

    try:
        actual_diffs = diff_shared_skeleton_catalog(vanilla_catalog, mod_catalog)
    except ValueError as e:
        return False, str(e)

    unpatched = sorted({d for d in set(all_donors.values()) if d not in actual_diffs})
    ok = not unpatched
    n_donors = len(set(all_donors.values()))
    detail = f"{n_donors} unique donor bone(s) checked against pak RefSkeleton"
    if unpatched:
        detail += (f"; {len(unpatched)} donor bone(s) unchanged from vanilla in the pak "
                   f"(patch lost between step02 and pak build): {unpatched[:5]}")
    return ok, detail


def soft_gate(name, ok, detail, env_flag, n_bad=0):
    """U50: 既定では警告(WARN)で、環境変数でFAILへ昇格できるゲート。

    背景(work\\u50_equip\\out\\FINDINGS.txt): 既存の件数照合ゲート(G4)は
    「CSV生成側」と「pak収録側」が同じ正規表現の盲点を共有しているため、
    両方が同じだけ漏れていると件数が一致してしまい検出できなかった。
    G10/G11はその盲点を持たない構造ゲートだが、導入時点で既知のNGが
    残っている(G11=16/60SK。別途「マテリアル完全単一化」で対応中)。
    ここでFAILにすると既存のビルドが全部落ちるため、**当面は警告**とし、
    件数が減っていくのを追えるようにNG件数と内訳を必ず出力する。

    将来の昇格は環境変数で行う(既定=warn):
      <env_flag>=fail     … NGが1件でもあればFAIL
      <env_flag>=max:<N>  … NGがN件を超えたらFAIL(件数を締めていく運用向け)
      <env_flag>=warn/未設定 … 常に警告(検品の合否には影響しない)
    """
    mode = (os.environ.get(env_flag) or "warn").strip().lower()
    promote = False
    if not ok:
        if mode == "fail":
            promote = True
        elif mode.startswith("max:"):
            try:
                promote = n_bad > int(mode[len("max:"):])
            except ValueError:
                promote = True   # 指定が壊れているなら安全側(FAIL)へ
    if promote:
        gate(name, False, f"{detail} [promoted to FAIL by {env_flag}={mode}]")
        return
    soft_results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'WARN'}] {name}" + (f" — {detail}" if detail else ""))


def count_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return sum(1 for _ in f) - 1  # ヘッダ除く


def g4_mat_tex_expect(n_mat):
    """G4のcounts[4]/counts[5](m00/m01・t00/t01)の期待値を返す。

    dev#958(2026-08-03): 両者はavatar_meta.jsonのマテリアルスロット数
    (n_mat)にのみ従属する——noueテンプレートは材質が1件以上あれば固定
    2件のマテリアル資産(M_VP_m00/m01)と固定2件のテクスチャ資産
    (t00/t01)を常に同梱するため。convert_noue.prepare_material_overrides
    (L338-352)は、そのラベルの唯一のマテリアルがtexture=null(単色)で
    あってもis_solid_color_keyの判定経路で単色PNGをその場で焼いて注入する
    ので、全マテリアル単色(実画像テクスチャ0件)のアバターでもt00/t01は
    2件収録される。材質が0件なら注入自体が起きないので両方0。
    戻り値: (n_mat_expect, n_tex_expect) のタプル(常に同値)。
    """
    expect = 2 if n_mat >= 1 else 0
    return expect, expect


def _manifest_sk_counts(headequip_show=None, dt_flag_head_hide=False):
    """noue_template_manifest.jsonが宣言している(=noueが実際に用意する)
    カテゴリ別SK数を返す。読めなければNone。

    U50: dup_*.csv は「バニラpakに実在する全SK」の**場所依存の完全列挙**へ
    直したので、noueテンプレがまだカバーしていないSK(2026-07-25時点で
    HeadEquipのYakushima 6件。ダミーSK資産の新規生成が要るため未対応)が
    あると、CSV由来の期待値とpak実測がずれる。noueにとっての「宣言された
    収録集合」はmanifestなので、G4はCSV由来かmanifest由来のどちらかに
    一致すればPASSとする。**漏れの検出はG10(名前単位)が担当する**ので、
    ここを緩めても盲点にはならない。

    dev#277第1弾④(2026-08-08、頭装備切り替え): headequip_show(job.get(
    "headequip_show")の生値)で選択(チェックON=表示)された頭装備は、
    live_template._project_skip_rels()がスタブ生成もコピーも行わず出力pak
    から完全に除外する(Head/Hairと同じ「manifestに無い扱い」)ため、G4の
    manifest由来HeadEquip期待値(静的宣言=常に64論理アセット/128ファイル)
    からも選択数ぶんを差し引く必要がある。既定(None/空)なら差し引き
    ゼロ=従来と完全一致(④無退行)。

    dev#1258(WP-E、2026-08-09): noue_template_manifest.jsonのproject区分は
    Head/Hair 178件を常時含む(既定=常時空スタブ生成、live_template.py
    _is_head_or_hair_stub_rel参照)。dt_flag_head_hide=True(ラボ機能ON)の
    ときだけ、live_template._assemble_live_template()がHead/Hairを出力pak
    から完全に除外する(v2.6.0までの既定と同じ)ため、G4の期待値からも
    Head/Hairを0扱いへ落とす必要がある。既定Falseなら差し引きなし
    (manifest宣言どおりの値をそのまま返す=本WPの新既定に対する④無退行)。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "noue_template_manifest.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            man = json.load(f)
    except Exception:
        return None
    rels = list(man.get("vanilla", [])) + list(man.get("project", []))
    out = {}
    for cat in ("Outfit", "Head", "Hair", "HeadEquip"):
        pfx = f"Player/{cat}/"
        out[cat] = len([r for r in rels
                        if r.startswith(pfx) and r.endswith(".uasset")
                        and os.path.basename(r).startswith("SK_")])
    shown = vp_headequip_filter.normalize_headequip_selection(headequip_show)
    if shown:
        headequip_rels = vp_headequip_filter.headequip_rels_from_manifest(man)
        shown_rels = vp_headequip_filter.shown_headequip_rels(headequip_rels, headequip_show)
        out["HeadEquip"] -= len([r for r in shown_rels if r.endswith(".uasset")])
    if dt_flag_head_hide:
        out["Head"] = 0
        out["Hair"] = 0
    return (out["Outfit"], out["Head"], out["Hair"], out["HeadEquip"])


def _load_sk_inventory(vanilla_dir, vanilla_entries):
    """バニラpakのSK完全在庫(場所依存列挙)を得る。

    extract_vanilla.pyが書き出したsk_inventory.jsonを使い、無ければ
    pak_entries.txt.gzから同じ関数でその場で作り直す(古いjobディレクトリ
    でもゲートが効くように)。返り値: {category: [rel, ...]} or None。
    """
    path = os.path.join(vanilla_dir, "sk_inventory.json")
    inv = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                inv = json.load(f)
        except Exception:
            inv = None
    if inv is None:
        try:
            import extract_vanilla
            inv = extract_vanilla.enumerate_vanilla_sk(vanilla_entries)
        except Exception as e:
            print(f"  [WARN] failed to reconstruct SK inventory (skipping G10): {e}")
            return None
    return {cat: [r["rel"] for r in rows] for cat, rows in inv.items()}


# WP-B3(dev#1198、2026-08-08、当時の既定): Head/Hair系スタブの生成を
# 無条件廃止し、可視性を注入装備行のbIsFullBodyEquipmentフラグに担わせて
# いた時代は、出力pakがHead/Hairを意図的に一切収録しなかった。
# dev#1258(WP-E、2026-08-09)で既定が反転(Head/Hair常時空スタブへ復帰)
# したため、このカテゴリ集合は「dt_flag_head_hide=True(ラボ機能ON、
# v2.6.0までの既定)のときだけ」使う(PROPOSAL §4.4-4)。
_G10_COVERAGE_EXCLUDED_CATEGORIES = frozenset({"head", "hair"})


def _filter_inv_for_g10_coverage(inv, dt_flag_head_hide=False):
    """G10のカバレッジ検査対象からHead/Hairカテゴリを取り除くかどうかを
    判定する(dev#1258 WP-E、旧dev#1198 WP-B3の判定を反転)。

    `inv`は`_load_sk_inventory`の戻り値と同じ形({category: [rel, ...]})。

    dt_flag_head_hide=False(既定): Head/HairはHeadEquipと同じく常時
    スタブ生成され出力pakに存在するため、**除外しない**(HeadEquipと
    同じ扱いへ戻す、PROPOSAL §4.4-4)。
    dt_flag_head_hide=True(ラボ機能ON): live_template.pyがHead/Hairを
    出力pakから完全に除外する(v2.6.0までの既定と同じ)ため、従来どおり
    G10のカバレッジ検査対象から外す。
    HeadEquipを含む他カテゴリはdt_flag_head_hideの値に関わらず無改変で
    返す(純粋関数、pak/IO不要につき単体テスト可能)。"""
    if not dt_flag_head_hide:
        return dict(inv)
    return {cat: rows for cat, rows in inv.items()
            if cat not in _G10_COVERAGE_EXCLUDED_CATEGORIES}


_GAME_PKG_PREFIX = "/Game/Pal/Model/Character/"


def _slot_role_check(template_dir, requested_equipment=None):
    """全衣装SKについて、**全描画スロット**が注入アトラス t00 を指しているかを
    テンプレート上の実バイトから機械判定する。

    dev#165第2期: requested_equipment(既定None)を渡すと、job.jsonの
    equipment_filterで選択されなかった装備SKも検査対象から外す
    (live_template.pyがそのSKのMIを意図的に統一しないため、バニラ=
    "VANILLA"判定になるのは仕様どおりでNGではない)。既定Noneでは
    既存の挙動と一字一句同じ。

    ### 判定基準の変更(2026-07-25、マテリアル単一化に伴う)

    旧基準は「slot0->t00 / slot1->t01」で、live_template側の
    「同じMIが別SKで別スロット役 → 競合ガードで差し替え対象外」という挙動を
    **シミュレート**して数えていた(work\\u50_equip\\slot_role_check.py 由来)。

    現在の live_template._unify_slot_materials(既定ON)は、注入対象衣装SKの
    描画スロットが参照するMIを**全件**、たった1種類の統一MI(Base Texture=t00)
    で置き換える。スロット役という概念自体が無くなり t01 は使われない。
    よって基準は「**全描画スロットが t00**」になる。
    旧基準のままだと slot1 が必ず t00 になるため全件NGとなり誤検知する
    (この基準変更前のNG 16件はすべて旧基準由来で、実体は正常だった)。

    ### シミュレーションではなく実バイトを見る

    旧実装はSKのMaterials[]の参照関係だけから結果を推定していたが、本実装は
    参照先のMIアセットを**テンプレート上で実際に開き**、name tableに
    `<MainShaderパッケージ>/t00` が入っているか(=Base Textureが我々の
    注入アトラスへ向いているか)を読む。統一MIの書き出しが漏れたMIは
    バニラのままなので name table に一致が無く、"VANILLA" として確実にNGになる。
    テンプレートに当該MIファイル自体が無い場合も "MISSING" でNGにする。

    非対応(コラボ系、vp_exclusions)のSKは、MI差し替え自体を意図的に
    行わない(=バニラの装備がそのまま出る)ため検査対象から外す。

    返り値: (NG件数, 検査件数, NG明細のリスト, エラー文字列 or None)
    """
    try:
        import live_template as lt
    except Exception as e:
        return 0, 0, [], f"failed to import live_template: {e}"
    # live_template._unify_slot_materials / collect_unified_mi_targets が
    # 使うのと同じ「スロット役を割り当てない出現順の全マテリアルパス」取得。
    finder = getattr(lt, "find_outfit_material_paths_all", None)
    err_cls = getattr(lt, "_OutfitMaterialPatchError", Exception)
    mvp_prefix = getattr(lt, "MVP_PACKAGE_PREFIX", None)
    if finder is None or mvp_prefix is None:
        return 0, 0, [], ("live_template.find_outfit_material_paths_all / "
                          "MVP_PACKAGE_PREFIX not found "
                          "(the implementation may have changed; this gate needs updating)")
    outfit_root = os.path.join(template_dir, "Player", "Outfit")
    if not os.path.isdir(outfit_root):
        return 0, 0, [], f"template has no Player/Outfit: {outfit_root}"

    atlas_cache = {}

    def atlas_of(mi_full_path):
        """MIアセットが実際に参照している注入アトラス名を返す。
        t00 / t01 / "t00+t01" / "VANILLA"(注入アトラス参照なし) / "MISSING"。"""
        if mi_full_path in atlas_cache:
            return atlas_cache[mi_full_path]
        v = "MISSING"
        if mi_full_path.startswith(_GAME_PKG_PREFIX):
            rel = mi_full_path[len(_GAME_PKG_PREFIX):]
            ua = os.path.join(template_dir, *rel.split("/")) + ".uasset"
            if os.path.exists(ua):
                try:
                    names = core.read_names(ua)
                except Exception as e:
                    v = f"PARSE_ERROR({e})"
                else:
                    hit = sorted({n.rsplit("/", 1)[-1] for n in names
                                  if n.startswith(mvp_prefix + "/t")})
                    v = "+".join(hit) if hit else "VANILLA"
        atlas_cache[mi_full_path] = v
        return v

    ng = []
    n_checked = 0
    n_excluded = 0
    for dirpath, _d, fns in os.walk(outfit_root):
        for fn in sorted(fns):
            if not fn.startswith("SK_") or not fn.endswith(".uasset"):
                continue
            ua = os.path.join(dirpath, fn)
            ue = ua[:-len(".uasset")] + ".uexp"
            rel = os.path.relpath(ua, outfit_root).replace("\\", "/")
            if vp_exclusions.is_excluded(rel) or _is_equipment_excluded(rel, requested_equipment):
                n_excluded += 1
                continue
            n_checked += 1
            try:
                paths = finder(ua, ue)
            except err_cls as e:
                ng.append(f"{rel}: could not determine draw-slot MI path(s) ({e})")
                continue
            if not paths:
                ng.append(f"{rel}: 0 material references for draw slots")
                continue
            bad = [f"slot{i}={atlas_of(p)}({p.rsplit('/', 1)[-1]})"
                   for i, p in enumerate(paths) if atlas_of(p) != "t00"]
            if bad:
                ng.append(f"{rel}: " + " / ".join(bad) + " (expected all slots = t00)")
    if n_excluded:
        print(f"  [INFO] G11 excluded (unsupported/collab items, or equipment filter): {n_excluded}")
    return len(ng), n_checked, ng, None


# ============================================================================
# G12実体検査化(dev#336、2026-08-08、致命ゲート)
# ----------------------------------------------------------------------------
# 旧G12(2026-07-30新設、dev#165)は「requested_genders>={"Male","Female"}」の
# 集合比較だけで判定していた。両性別未満(=genders限定ビルド)なら中身を一切
# 見ずに無条件FAILする設計で、当時は「衣装テクスチャの経路はメッシュとは
# 独立に、性別を問わず全衣装SK共通の1枚のアトラス(t00/t01)へ常時上書き
# される」という前提に基づく安全側の暫定ブロックだった。
#
# dev#336(2026-08-08、本WPと同日)のlive_template._effective_extra_excluded_
# sk_names()が、job.get("genders")の除外性別SK名集合をcollect_unified_mi_
# targets()の除外リストへOR合成するようになった結果、この前提は既に崩れて
# いる: 除外性別のMI/素体は統一(t00/t01化)対象から外れるだけでなく、
# build_pak_from_avatar.pyのfinal_files選定自体でpakへ一切収録されなく
# なった(work\f2_build_verify\PROGRESS.md/g12_verification.logでバイト
# レベル実証済み)。旧G12は検査対象の実装に追随していない「古いゲート」に
# なっていた。
#
# 新G12は実体を2点検査する:
#   ①(_g12_is_scoped_asset対象=衣装MI・素体MI/テクスチャ)
#     除外性別のこれらの資産はpakに**存在してはならない**(存在=漏れ=異常。
#     不在ならUEが自動的にベースゲームpakのバニラ資産へフォールバックする
#     ため、「存在するならバニラと同一」を不在という形で厳格に保証する)。
#   ②(_g12_sk_atlas_violations対象=衣装SKメッシュ本体)
#     除外性別のSKメッシュは①と異なりバニラ形状のまま**残るのが正しい
#     設計**(バイト実証済み、真のgame本体pakと完全一致)。②はこの残存
#     メッシュが参照するMIが、注入済みアバターアトラス(t00/t01)を指して
#     いないかを検査する。指していれば「バニラ形状+アバターテクスチャ」
#     というUV不整合の見た目破綻が実際に起きている証拠であり、これが
#     旧G12が本来懸念していた具体的なリスクそのもの。
#
# 「要求性別に共有されるMI」の例外(実測で発見、dev#336のスコープではなく
# ベースゲーム自体のアセット設計に起因): Palworldのバニラアセットは
# 一部の衣装アイテム(例: Ancient001)で**Female側SKメッシュに専用MIが
# 存在せず、Male名のMIをそのまま共有参照する**構造になっている(実測:
# 真のPal-Windows.pakにMI_Player_Female_Outfit_Ancient001系は一切存在せず、
# MI_Player_Male_Outfit_Ancient001_*のみが実在し、Female/Male両方のSKから
# 参照される)。このため、genders=["Female"]のビルドでもFemaleのAncient001
# メッシュを正しく描画するには"Male"と名の付くMIをアバターアトラスへ
# 統一・収録する必要があり、Male側の(除外されたはずの)バニラ形状メッシュも
# 同じMIファイルを参照しているため、必然的に同じアバターテクスチャを
# 拾ってしまう。これは実装のバグではなく、共有MIという1つの物理ファイルに
# 「除外性別はバニラのまま・要求性別はアバター化」という二律背反な要求を
# 同時に満たすことができないという構造的な限界であり、G12もこの限界を
# 検出力の対象外として扱う(=このMIを要求性別側の必須依存として実際に
# 参照しているSKが存在するかどうかを _g12_sk_referenced_mi_bases() で
# 判定し、該当すれば①②いずれの判定からも除外する)。除外していないその他の
# 真の漏れ(要求性別のどのSKからも参照されない、純粋に除外性別専用のMI)への
# 検出力は一切緩めていない。
#
# ①②いずれもFALSEならFAIL(検査意図は弱めていない。旧ゲートより緩い
# 「genders指定を素通し」ではなく、実体を見て初めて安全と判定する)。
# ============================================================================

def _g12_strip_game_prefix(full_path):
    """'/Game/Pal/Model/Character/...'(拡張子なしパッケージパス)を、
    entries/strip_body_prefixと同じ座標系('Model/Character/...'、拡張子
    なし)へ変換する。一致しなければ入力をそのまま返す(安全側、フィルタが
    無効化されるだけで検出力が上がる方向にしか作用しない)。"""
    prefix = "/Game/Pal/"
    if full_path.startswith(prefix):
        return full_path[len(prefix):]
    return full_path


def _g12_sk_referenced_mi_bases(template_dir, sk_rels, find_material_paths=None):
    """sk_rels(body-relative なSK .uassetパスのリスト)が参照するMIの
    「pak相対パス・拡張子なし」集合を返す(_g12_strip_game_prefix適用済み)。

    要求性別側のSK(=include対象)に対して呼べば「本当に必要なMI」の集合が
    得られる——ファイル名にたまたま逆性別の文字列を含むMI(Ancient001の
    共有MI等)でも、実際に要求性別のSKから参照されていれば含まれる。
    ①②いずれもこの集合に載っているMI/SKは「漏れ」ではなく「必要な依存」
    として除外扱いしない(G12実体検査化ヘッダコメントの「共有されるMIの
    例外」参照)。"""
    if find_material_paths is None:
        import live_template as lt
        find_material_paths = lt.find_outfit_material_paths_all
    needed = set()
    for rel in sk_rels:
        ua = os.path.join(template_dir, *rel.split("/"))
        ue = ua[:-len(".uasset")] + ".uexp"
        if not (os.path.exists(ua) and os.path.exists(ue)):
            continue
        try:
            paths = find_material_paths(ua, ue)
        except Exception:
            continue
        needed.update(_g12_strip_game_prefix(p) for p in paths)
    return needed


def _g12_sk_atlas_violations(template_dir, excluded_sk_rels,
                              needed_mi_bases=frozenset(),
                              find_material_paths=None, atlas_of=None):
    """dev#336 G12実体検査②: excluded_sk_rels(body-relative、例
    'Player/Outfit/SK_Player_Male_Outfit_Bronze001/SK_Player_Male_Outfit_
    Bronze001.uasset')の各SKが参照するMIが、注入済みアバターアトラス
    (t00/t01)を指していないかを検査する。needed_mi_basesに載っている
    MI(要求性別側のSKが実際に参照している=共有MIの例外、ヘッダコメント
    参照)への参照は違反として数えない。

    template_dir配下の実ファイルを読む根拠: build_pak_from_avatar.pyの
    final_files構築(Phase3)は、replace_map(targets_rel/tex_replace/
    mat_override/mi_override)に載らないrelについてsrc=templateの現物
    ファイルをそのままpakへコピーする。除外性別のSKはこれらいずれの
    置換対象にもならないため、template上のバイトが実際にpakへ入る現物
    そのもの(=preflightがmod_pak自体を再抽出しなくても正しく検査できる)。

    find_material_paths(ua_path, ue_path)->list[str] / atlas_of(mi_full_path)
    ->str('t00'/'t01'/'t00+t01'/'VANILLA'/'MISSING'/...)は依存性注入
    (既定はlive_template.find_outfit_material_paths_all / _slot_role_check
    と同じname table走査)。テストで差し替え可能にすることで、実cooked
    バイトを合成せずに正負両対照を検証できる
    (tests/gender_filter_dev336/test_preflight_g12_gender_isolation.py)。

    戻り値: アトラス参照ありと判定されたSKの明細文字列のリスト。
    """
    if find_material_paths is None or atlas_of is None:
        import live_template as lt
        mvp_prefix = lt.MVP_PACKAGE_PREFIX
        atlas_cache = {}

        def _default_atlas_of(mi_full_path):
            if mi_full_path in atlas_cache:
                return atlas_cache[mi_full_path]
            v = "MISSING"
            if mi_full_path.startswith(_GAME_PKG_PREFIX):
                rel = mi_full_path[len(_GAME_PKG_PREFIX):]
                ua = os.path.join(template_dir, *rel.split("/")) + ".uasset"
                if os.path.exists(ua):
                    try:
                        names = core.read_names(ua)
                    except Exception as e:
                        v = f"PARSE_ERROR({e})"
                    else:
                        hit = sorted({n.rsplit("/", 1)[-1] for n in names
                                      if n.startswith(mvp_prefix + "/t")})
                        v = "+".join(hit) if hit else "VANILLA"
            atlas_cache[mi_full_path] = v
            return v

        if find_material_paths is None:
            find_material_paths = lt.find_outfit_material_paths_all
        if atlas_of is None:
            atlas_of = _default_atlas_of

    violations = []
    for rel in excluded_sk_rels:
        ua = os.path.join(template_dir, *rel.split("/"))
        ue = ua[:-len(".uasset")] + ".uexp"
        if not (os.path.exists(ua) and os.path.exists(ue)):
            continue
        try:
            paths = find_material_paths(ua, ue)
        except Exception:
            continue
        hits = [p for p in paths if atlas_of(p) in ("t00", "t01", "t00+t01")
                and _g12_strip_game_prefix(p) not in needed_mi_bases]
        if hits:
            violations.append(f"{rel}: references injected atlas via {hits}")
    return violations


def check_g12_gender_isolation(template_dir, entries, requested_genders,
                                requested_equipment=None,
                                find_material_paths=None, atlas_of=None):
    """dev#336(2026-08-08)G12実体検査化本体。gate()を直接呼ばず
    (ok, detail, leaked, atlas_violations)を返す純寄りの関数として切り出す
    (check_dt_serial_size/G13と同じ設計方針、main()を完走させずに単体
    テストできる)。

    既定(両性別要求、requested_genders>={"Male","Female"})では常にOK
    (④無退行の根拠: 既存のgenders未指定ビルドは一切この分岐に入らない)。

    genders限定時は上の「G12実体検査化」節ヘッダコメントの①②を検査する。

    スコープ外1(vp_exclusions非対応コラボ/equipment_filter非選択): G5/G10/
    G11が既にそうしているのと同じ理由・同じ判定(vp_exclusions.is_excluded/
    _is_equipment_excluded)で対象から除外する。これらの項目は「unification
    (T3統一)対象から常に除外」されており、genders設定と無関係にMIが元の
    ままpakへ入る(=もともとgenders機構の管理外)。「非対応(collab)」は他の
    全ゲートで既に検査対象外という明示済みの制約であり、ここで初めて弱め
    ているのではなく、既存のスコープ境界に合わせているだけ。

    スコープ外2(要求性別側のSKが実際に参照する共有MI): _g12_sk_referenced_
    mi_bases()参照。ベースゲーム自体のアセット設計に起因する例外で、
    dev#336のgenders機構では原理的に解決できない(work\\f2_build_verify\\
    pak_F2実pakでのAncient001実測: Female側SKメッシュに専用MIが存在せず
    Male名のMIを共有参照するため、要求性別Femaleを正しく描画するには
    その"Male"名MIをアバターアトラスへ収録する必要があり、結果として
    除外されたはずのMale側バニラメッシュも同じMIを介して同じテクスチャを
    拾ってしまう)。①②とも、要求性別側のSKが実際に依存しているMIへの
    参照は「漏れ/違反」として数えない。要求性別のどのSKからも参照されない
    純粋な除外性別専有のMI/素体資産への検出力は一切緩めていない。
    """
    requested = set(requested_genders)
    if requested >= {"Male", "Female"}:
        return True, "OK (both genders requested, default)", [], []
    excluded_genders = {"Male", "Female"} - requested

    def _in_scope(p):
        return not (vp_exclusions.is_excluded(p)
                    or _is_equipment_excluded(p, requested_equipment))

    # 要求性別側(除外されていない)のSKが実際に参照するMIの集合。共有MIの
    # 例外(ヘッダコメント参照)を①②の判定から差し引くために先に求める。
    included_sk_rels = sorted(
        strip_body_prefix(p) for p in entries
        if _in_scope(p) and os.path.basename(p).startswith("SK_")
        and p.endswith(".uasset") and not _is_gender_excluded(p, requested))
    needed_mi_bases = frozenset()
    if included_sk_rels:
        try:
            needed_mi_bases = _g12_sk_referenced_mi_bases(
                template_dir, included_sk_rels,
                find_material_paths=find_material_paths)
        except Exception as e:
            print(f"  [WARN] G12 could not compute the required-gender MI "
                  f"dependency set (shared-MI exemption skipped, detection "
                  f"stays strict): {e}")

    def _rel_base(p):
        for ext in (".uasset", ".uexp", ".ubulk"):
            if p.endswith(ext):
                return p[:-len(ext)]
        return p

    # ①: 衣装MI・素体(MI/テクスチャ)はpakに存在してはならない
    #    (要求性別側が実際に依存しているMIは例外)。
    leaked = sorted(p for p in entries
                     if _in_scope(p) and _g12_is_scoped_asset(p)
                     and _is_gender_excluded(p, requested)
                     and _rel_base(p) not in needed_mi_bases)

    # ②: 除外性別の衣装SKメッシュ(残存が正しい設計)が注入アトラスを
    #    参照していないか(要求性別側が実際に依存しているMIへの参照は例外)。
    excluded_sk_rels = sorted(
        strip_body_prefix(p) for p in entries
        if _in_scope(p) and os.path.basename(p).startswith("SK_")
        and p.endswith(".uasset") and _is_gender_excluded(p, requested))
    atlas_violations = []
    if excluded_sk_rels:
        try:
            atlas_violations = _g12_sk_atlas_violations(
                template_dir, excluded_sk_rels, needed_mi_bases=needed_mi_bases,
                find_material_paths=find_material_paths, atlas_of=atlas_of)
        except Exception as e:
            print(f"  [WARN] G12 could not run the SK->atlas reference check: {e}")

    ok = not leaked and not atlas_violations
    if ok:
        detail = (
            f"genders={sorted(requested)}: 0 MI/body-asset leaks and "
            f"0/{len(excluded_sk_rels)} excluded-gender outfit SK reference the "
            f"injected avatar atlas (excluded gender's mesh/material/texture "
            f"all fall back to the base game pak for a vanilla appearance, "
            f"dev#336)")
    else:
        parts = []
        if leaked:
            parts.append(
                f"{len(leaked)} MI/body-asset entries for excluded gender(s) "
                f"{sorted(excluded_genders)} leaked into the pak (expected: "
                f"absent -- these should fall back to the base game pak), "
                f"e.g. {leaked[:5]}")
        if atlas_violations:
            parts.append(
                f"{len(atlas_violations)} excluded-gender outfit SK reference "
                f"the injected avatar atlas (t00/t01) -- vanilla-shaped mesh + "
                f"this avatar's texture, the broken-appearance risk dev#165 "
                f"G12 was created for, e.g. {atlas_violations[:3]}")
        detail = f"genders={sorted(requested)}: " + "; ".join(parts)
    return ok, detail, leaked, atlas_violations


# ============================================================================
# G5並列化(rdp_preflight, 2026-07-29研究dev#120フォローアップ)
# ----------------------------------------------------------------------------
# G5/G5bループ(58SK分)はrd_120実測でPhase4(preflight全体)の支配的コストと
# 特定された。当初「単一ファイルハンドル(mod_pakを開くpf)を複数プロセスで
# 共有できない」設計制約が指摘されていたが、実際に重いのはpf経由の抽出
# (I/Oのみ、高速)ではなく、抽出後にtmp_uasset/tmp_uexp(SKごとに独立した
# 一時ファイル)だけを読むcore.find_refskeleton()(uexp全域の総当たり
# オフセット走査)とparse_sk_structure.py(同様の前方/後方総当たり走査)という
# pure Python CPUバウンドループである。これらはmod_pak自身のpfには一切
# 触れないので、「抽出はpfで直列のまま(不変)・解析はSKごとに独立なので
# プロセス並列」という2段構成にすれば、pf共有制約に一切触れずに済む
# (=「ワーカーごとに開き直す」でも「先読み」でもなく、そもそも並列区間に
# pfを持ち込まない設計)。
# ============================================================================

def _g5_analyze_one(args):
    """G5/G5b: 1SK分の解析(read_names/find_refskeleton/parse_sk_structure/
    bind回転差)。抽出済みの一時uasset/uexpパスだけを読み、mod_pak自体の
    ファイルハンドルには一切触れない。ProcessPoolExecutorのワーカーから
    pickle経由で呼ばれるためモジュールトップレベル関数にする(Windows
    spawnの制約)。

    例外は握りつぶさずそのまま送出する(直列版と同じく、解析不能なSKが
    あれば即座に致命エラーで停止する既存挙動を変えない。ProcessPoolExecutor
    はワーカー例外を呼び出し元の.result()/イテレーション時に再送出するため、
    mainプロセス側で見える挙動は直列時と同じ「即クラッシュ」になる)。

    戻り値: (worst_local(dr, "base:bone"), unknown_bones_local(set))
    """
    tmp_uasset, tmp_uexp, ref = args
    base = os.path.basename(tmp_uasset)
    names = core.read_names(tmp_uasset)
    bones, transforms, _ = core.find_refskeleton(tmp_uexp, names)
    struct_info = sk_struct.parse_sk_structure(tmp_uexp, tmp_uasset)
    used_idx = set()
    for sec in struct_info["sections"]:
        used_idx.update(sec["bone_map"])
    worst_local = (0.0, "")
    unknown_local = set()
    for i, ((bname, _p), t) in enumerate(zip(bones, transforms)):
        if i not in used_idx:
            continue  # 実際のRenderSectionsが参照しない(=描画に無関係な)ボーン
        vb = ref.get(bname)
        if vb is None:
            # メッシュ名とボーン名の衝突でUEがボーンをリネームすると
            # (例: head→head1)実行時スケルトンに対応が無くなり非追従になる。
            # 実際に使用中のボーンはバニラの部分集合でなければならない
            unknown_local.add(f"{base}:{bname}")
            continue
        dr = core.quat_angle_deg(t[0:4], vb["quat"])
        if dr > worst_local[0]:
            worst_local = (dr, f"{base}:{bname}")
    return worst_local, unknown_local


def _g5_worker_count(n_tasks):
    """並列度の既定値。D2P_PREFLIGHT_G5_WORKERS=1 を指定すると強制直列化
    される(デバッグ・低スペック環境・再現性を要するテスト用)。既定は
    cpu_countと8の小さい方、かつタスク数を超えない(空振りプロセス起動の
    無駄を避ける)。"""
    env = (os.environ.get("D2P_PREFLIGHT_G5_WORKERS") or "").strip()
    if env:
        try:
            n = int(env)
            if n >= 1:
                return min(n, n_tasks) if n_tasks else 1
        except ValueError:
            pass
    return max(1, min(os.cpu_count() or 4, 8, n_tasks or 1))


def _run_g5_analysis(extraction_tasks, analyze_fn=_g5_analyze_one):
    """G5/G5b解析の並列実行本体。抽出済みタスク(mod_pakのpfから独立、SKごと
    に完全に独立な入力)をProcessPoolExecutorへ配る。concurrent.futures.
    Executor.map()は投入順で結果を返す(公式挙動)ので、集約結果
    (worst=単純max、unknown_bones=単純union)は並列度・実行順に関係なく
    直列実行時と完全に同一になる(SKごとの計算に共有可変状態が無いため)。
    タスクが0〜1件、または並列度1のときはプロセス起動コストを避けて
    直列実行する(同じanalyze_fn()を呼ぶだけなので結果は完全に同値)。

    analyze_fn: 既定は_g5_analyze_one(本番動作はこれで固定)。テスト時のみ、
    真のProcessPoolExecutorディスパッチ(spawn・pickle・順序保証)を軽量な
    モックSK解析関数で検証できるよう差し替え可能にしてある
    (work\\rdp_preflight\\tests\\test_g5_parallel_dispatch.py参照。
    analyze_fnはpickle対象になるためモジュールトップレベル関数である必要がある)。
    """
    n = len(extraction_tasks)
    if n == 0:
        return []
    workers = _g5_worker_count(n)
    if workers <= 1:
        return [analyze_fn(t) for t in extraction_tasks]
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(analyze_fn, extraction_tasks))


def _aggregate_g5_results(per_task_results):
    """_run_g5_analysis()の戻り値([(worst_local, unknown_local), ...])を
    G5/G5bゲートが使う最終形(worst, unknown_bones, n_checked)へ集約する。

    集約は単純なmax(回転差)とunion(不明ボーン集合)+件数カウントのみで、
    どの順序で結果が来ても(=並列度に関係なく)最終値は同一になる
    (可換・結合的な演算のみで構成されているため)。テスト
    (work\\rdp_preflight\\tests\\)から直列/並列の集約結果が一致することを
    直接検証できるよう、main()の本体から関数として切り出した。
    """
    worst = (0.0, "")
    n_checked = 0
    unknown_bones = set()
    for worst_local, unknown_local in per_task_results:
        if worst_local[0] > worst[0]:
            worst = worst_local
        unknown_bones |= unknown_local
        n_checked += 1
    return worst, unknown_bones, n_checked


def load_vanilla_ref_for_g5(vanilla_dir, converted_dir=None):
    """G5/G5b(バインド回転差・ボーン集合⊆バニラ)が使う「既知のバニラ
    ボーン」基準集合(性別別、ボーン名->bindpose数値)を組み立てる。

    dev#19 R2b-3(2026-08-11、試着室pak実験)→dev#1363(本流化)の拡張:
    extract_vanilla.py "sway_extra_family" で追加donorファミリー
    (例: Ancient001)を抽出したジョブは、`vanilla_dir` に家系ごとの
    `refskel_{family}_{gender}.json` が追加で置かれる。存在すればそのファミリー
    のボーン(例: F_Ancient001_waistClothA_01..04)も正規に既知のバニラボーン
    としてG5b比較対象へマージする。

    donorexp WP(2026-08-11、issue#19、要件1/2): 複数家系を同時抽出できる
    ようになったため、固定1ファイル(旧`refskel_extra_{gender}.json`)を直接
    読むのではなく、`refskel_*_{gender}.json`(base自身の`refskel_{gender}.json`
    にはマッチしない——ワイルドカードの前に必ず`_`区切りの家系名セグメントが
    要るため)へマッチする**全ファイル**をソート順にマージする。家系名を
    ハードコードしないため、将来家系が増えても本関数の変更は不要。
    **sway_extra_family未指定のジョブでは追加ファイルが1つも無いため、
    既存挙動は完全に不変**(マッチ0件=何もしない=本拡張導入前のロジックと
    一字一句同じ結果)。

    dev#1508 W2a-2d(実データ実測で発見・本関数で解消): 汎用ハブ配線が
    アバターの実データからdonor骨として選ぶボーン(例: F_Cloth001_
    waistCloth_03_r)は、`build_pak_from_avatar._refskel_extend_overrides()`
    が`job_dir/converted/sway_hub_refskel_{gender}.json`
    (`sway_hub.refskel_dict_for_wiring()`が書く、job固有・vanilla_dir外の
    ファイル、W2a-2c PROGRESS.md「per-jobのconverted/配下」参照)を拡張材料
    として使い、**全ての衣装SK**(Phase 2はavatarを60体超の全衣装SKへ注入
    するため、ハブ配線が選んだdonor骨を持たない衣装SKも正当に拡張される)
    へ正しく反映する。G5bのvanilla_refがこのファイルを知らないと、
    正当に拡張された衣装SK(例: 完全に無関係なAncient001)まで「バニラに
    無いボーンを参照している」と誤検出する(実測: comodo実変換、G5b FAIL
    3件、いずれもsway hub donor骨。sway_enable=falseの同一jobでは発生せず、
    本現象がsway hub由来であることを確認済み)。converted_dirを渡すと、
    存在すればこのファイルも同じ理由でマージする(存在しなければ従来どおり
    無視、④無退行の根拠——sway hub未使用ジョブ・converted_dir省略呼び出し
    (既存テスト含む)ではファイルが無いか引数自体が省略されるため一切
    影響しない)。

    main()から抽出した理由: このIO+マージのみのロジックは実pak/実変換を
    伴わずに単体テスト可能(tmp_pathへ小さいJSONを2つ置くだけで検証できる)
    ため、main()の巨大な本体から独立させた
    (tests\\coverage\\test_preflight_g5b_sway_extra_family_dev1363.py参照)。
    """
    vanilla_ref = {}
    for g in ("male", "female"):
        with open(os.path.join(vanilla_dir, f"refskel_{g}.json"),
                  encoding="utf-8") as f:
            vanilla_ref[g] = json.load(f)
        pattern = os.path.join(vanilla_dir, f"refskel_*_{g}.json")
        for extra_path in sorted(glob.glob(pattern)):
            with open(extra_path, encoding="utf-8") as f:
                vanilla_ref[g].update(json.load(f))
        if converted_dir:
            hub_path = os.path.join(converted_dir, f"sway_hub_refskel_{g}.json")
            if os.path.isfile(hub_path):
                with open(hub_path, encoding="utf-8") as f:
                    vanilla_ref[g].update(json.load(f))
    return vanilla_ref


def main():
    job = core.load_job(sys.argv[1])
    mod_pak, extract, cook_log = sys.argv[2], sys.argv[3], sys.argv[4]
    vanilla_dir = os.path.join(job["job_dir"], "vanilla")
    conv = os.path.join(job["job_dir"], "converted")
    # dev#165: build_pak_from_avatar.pyのgender exclusion(Phase2)と同じ
    # 判定基準をここでも再現するための入力(_is_gender_excluded参照)
    requested_genders = set(job.get("genders") or ["Male", "Female"])
    # dev#165第2期: 同様に、equipment_filterで選択されなかった装備の判定
    # 基準をここでも再現するための入力(_is_equipment_excluded参照)。
    requested_equipment = vp_equipment_filter.normalize_equipment_filter(
        job.get("equipment_filter"))

    print("=== preflight: offline MOD pak inspection ===")
    if not os.path.exists(mod_pak):
        gate("pak exists", False, mod_pak)
        return finish()

    mount, entries = core.read_pak_index(mod_pak)
    # dev#1198 WP-B5a: COMMON_MOUNT配線により entries は今後
    # vp_pakwrite.BODY_PREFIX("Model/Character/")付きの座標系になる。
    # G3のホワイトリスト完全一致・G10のSK在庫名前照合は、いずれもBODY_PREFIX
    # 無しのボディ資産相対パス(旧DEFAULT_MOUNT時代の座標系、
    # noue_template_manifest.json/dup_*.csv/vp_exclusionsもこの座標系)を
    # 前提にした既存比較のため、prefixを剥がした正規化済みリストを別名で
    # 保持し、そちらを使う(剥がさずraw entriesのまま比較すると、G3は
    # ホワイトリスト対象の素体共有MIまで誤ってFORBIDDEN判定してしまい、
    # G10は在庫の全件が「収録漏れ」に見えてしまう——検査意図を弱める方向
    # ではなく、正本の座標系に合わせて検出力を維持する修正)。
    # G1(mount自体の比較)・G2(mount+entry連結で実効パスを再構成)は
    # raw entriesのまま無改修(元から座標系に依存しない設計のため)。
    entries_body_rel = [strip_body_prefix(e) for e in entries]
    with gzip.open(os.path.join(vanilla_dir, "pak_entries.txt.gz"), "rt",
                   encoding="utf-8") as f:
        vanilla_entries = f.read().splitlines()
    vanilla_set = set(vanilla_entries)

    # G1: マウントポイント
    # dev#1198 WP-B5a: build_pak_from_avatar.py Phase3/fast_repack.pyが
    # COMMON_MOUNT(共通祖先"../../../Pal/Content/Pal/")へ切り替わったため、
    # 期待値も追随させる。旧DEFAULT_MOUNT(".../Model/Character/"、ボディ資産
    # 専用の狭いmount)のpakは意図的にFAILする(負の対照: 古い実装で生成された
    # pakを新G1が検出できることの機械保証。test_preflight_g1_common_mount_
    # wpb5a.py参照)。緩めているのではなく、正本の値を追随させているだけ
    # (旧値との一致は許容しない=厳格な等価比較のまま)。
    gate("G1 mount point",
         mount == vp_pakwrite.COMMON_MOUNT, mount)

    # G2: パス整合(平坦化検知)。新規アセット(ModelMaterials)とアンカー・
    # AvatarSelect複製素体MI(F3a)以外は、バニラに同一パスが存在しなければ
    # ならない(=正しく上書きされる証拠)。判定パターン自体はモジュール
    # レベル定数G2_NEW_ASSET_OK/G2_ANCHOR_OK/G2_AVATAR_SELECT_OKの正本
    # コメント参照。
    full = [mount.replace("../../../", "") + e for e in entries]
    bad = [p for p in full
           if not (p in vanilla_set or G2_NEW_ASSET_OK.match(p) or G2_ANCHOR_OK.match(p)
                   or G2_AVATAR_SELECT_OK.match(p) or G2_EQUIP_AVATAR_MAP_BODY_MI_OK.match(p))]
    gate("G2 all entry paths match vanilla (no flattening)", not bad,
         f"{len(bad)} mismatch(es), e.g.:{bad[:3]}" if bad else f"{len(full)} OK")

    # G3: 禁止物(共有スケルトン・素体・ストリーミングミップ・装備専用Skeleton/
    # Physics)。「共有スケルトン・素体スケルタルメッシュ本体・Physics・
    # ストリーミングミップは改変対象外」という原則を維持しつつ、素体共有MI・
    # 平坦化済みNormal/ORM/SSSテクスチャ・AvatarSelect複製素体MI(F3a)のみ
    # 完全一致のホワイトリスト(モジュールレベル定数G3_BODY_MI_WHITELIST、
    # 正本コメント参照)で例外許可する。
    # dev#1198 WP-B5a: entries_body_rel(BODY_PREFIX剥がし済み)で比較する。
    # 剥がさずraw entriesのまま比較すると、G3_BODY_MI_WHITELISTの各資産
    # (BODY_PREFIX無しの座標系で列挙済み)が完全一致せず誤ってFORBIDDEN扱い
    # されてしまう(素体共有MIが誤検出=許可されるべきものが弾かれる誤FAIL)。
    # dev#1508 W2a-2d(G3ゲート昇格): 共有Skeleton(SK_PalHuman_Skeleton)の
    # 2パスは、盲目的なパス一致(G3_SWAY_HUB_SK_WHITELIST)だけでは許可
    # しない——このforbidden判定からは除外するが、その代わりに直後の
    # G3b(check_sway_hub_shared_skeleton_patch)がバイトレベルで独立検証
    # する。G3bがFAILすれば全体としてはFAILのまま(保護の意図は不変)。
    forbidden = [p for p in entries_body_rel
                 if (("Skeleton/" in p or "/Body/" in p or p.endswith(".ubulk")
                      or "_Skeleton." in p or "Physics" in p)
                     and p not in G3_BODY_MI_WHITELIST
                     and not G3_EQUIP_AVATAR_MAP_BODY_MI_OK.match(p)
                     and not G3_EQUIP_AVATAR_MAP_TEX_UBULK_OK.match(p)
                     and p not in G3_SWAY_HUB_SK_WHITELIST)]
    gate("G3 zero forbidden items (Skeleton/Body/Physics/ubulk, only the 4 base-body MI paths "
         "+ verified sway-hub shared-skeleton patch exempt)", not forbidden,
         str(forbidden[:3]) if forbidden else "")

    # G3b: dev#1508 W2a-2d(G3ゲート昇格の本体): 共有Skeletonがpakに含まれる
    # 場合、バニラとの実差分がsway_hub_patch_manifest.json(予定パッチ)と
    # 厳密一致することを独立検証する(check_sway_hub_shared_skeleton_patch()
    # 正本コメント参照)。
    _, pak_entries_full_g3 = core.read_pak_entries(mod_pak)
    g3b_ok, g3b_detail = check_sway_hub_shared_skeleton_patch(
        job, vanilla_dir, mod_pak, pak_entries_full_g3)
    gate("G3b sway-hub shared-skeleton patch matches its planned manifest "
         "(dev#1508 W2a-2d)", g3b_ok, g3b_detail)

    # G15: dev#1508 追加防衛線(オーナー裁定2026-08-16)。step02の早期
    # fail-closedゲート(run_sway_source_gate())が既に通したソース骨->donor
    # 対応(sway_source_donor_map_{gender}.json)を使い、pak組み立て段階で
    # そのパッチが失われていないかを検査する(check_sway_source_gate_
    # against_pak()正本コメント参照)。
    g15_ok, g15_detail = check_sway_source_gate_against_pak(
        job, vanilla_dir, mod_pak, pak_entries_full_g3)
    gate(G15_NAME, g15_ok, g15_detail)

    # G4: 収録数(複製リスト+複製元。マテリアル・テクスチャはスロット表から導出)
    with open(os.path.join(conv, "avatar_meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    n_out_m = count_csv(os.path.join(vanilla_dir, "dup_outfit_male.csv")) + 1
    n_out_f = count_csv(os.path.join(vanilla_dir, "dup_outfit_female.csv")) + 1
    n_head = (count_csv(os.path.join(vanilla_dir, "dup_head_male.csv")) + 1
              + count_csv(os.path.join(vanilla_dir, "dup_head_female.csv")) + 1)
    n_hair = count_csv(os.path.join(vanilla_dir, "dup_hair.csv")) + 1
    n_he = count_csv(os.path.join(vanilla_dir, "dup_headequip.csv")) + 1
    n_mat = len(meta["slots"])
    n_tex = len({s["texture"] for s in meta["slots"].values() if s["texture"]})
    # U19(2026-07-23、U54(2026-07-26)で式を訂正):
    # counts[4]/counts[5]が数えているのは、avatar_meta.json由来のスロット数
    # (n_mat/n_tex)から導いた「何バケツに丸められるか」ではなく、
    # **noueテンプレートが常に持つ固定2パッケージ名そのもの**である:
    #   counts[4] = canonical_mat(MainShader/M_VP_[A-Za-z0-9]+.uasset)
    #             = M_VP_m00.uasset / M_VP_m01.uasset の実在数(常に2)
    #   counts[5] = MainShader/配下でM_VP_*でない.uasset
    #             = t00.uasset / t01.uasset の実在数(常に2)
    # このm00/m01・t00/t01はavatar_meta.jsonのスロット数に関係なく、
    # Palworldプレイヤーメッシュテンプレート自身が常に同梱する固定資産
    # 名である(live_template.MVP_PACKAGE_PREFIX配下、
    # convert_noue.prepare_material_overridesが上書きしない残りはテンプレ
    # 既定のまま同梱される)。U50-single(2026-07-25)でvp_atlas.classify_material
    # が常に0(body)を返すよう単一化されて以降、「3枚以上は2バケツへ丸める」
    # という旧説明は成立しなくなっている(全スロットがbodyへ畳まれる)が、
    # テンプレート資産自体の固定2枚という実体は単一化の前後で変わっていない。
    # 実測(2026-07-26): alicia(12マテリアル)/seed/vrm1でも実測counts[4:]は
    # 常に(2,2)——n_mat依存ではなくテンプレート構造依存であることが独立に
    # 確認できる。min(n_mat,2)はn_mat>=2の間はたまたま2に一致していたため
    # 誤りが露見しなかったが、n_mat=1(vrm_kate/vrm_robothead)では期待値が
    # 1に丸まってしまい、実測の2と食い違って誤FAILしていた
    # (docs的経緯はdiag_A_vrm.md参照)。
    # 正しい期待値は「材質が1件以上あれば常に2、0件なら0
    # (=注入すら起きていない=過小収録の検知は維持)」。
    # dev#958(2026-08-03訂正): counts[5](t00/t01)の注入トリガーは
    # 「実画像テクスチャを持つスロットの有無」(n_tex)ではなく「マテリアルが
    # 1件以上あるか」(n_mat)である。convert_noue.prepare_material_overrides
    # (L338-352)は、そのラベルの唯一のマテリアルがtexture=null(単色)で
    # あってもis_solid_color_keyの判定経路で単色PNGをその場で焼いて注入する
    # (全マテリアル単色=n_tex==0のアバターでもorder自体は非空のまま)。
    # したがってt00/t01の実在はn_matにのみ従属し、n_tex(実画像テクスチャを
    # 持つスロット数)は代理変数として誤り。n_tex==0でもn_mat>=1なら実測
    # counts[5]は2になり、旧式(n_tex>=1で判定)は誤って0を期待してG4を
    # 誤FAILさせていた(実報告99WAWMG2、全マテリアル単色のアバター)。
    n_mat_expect, n_tex_expect = g4_mat_tex_expect(n_mat)
    expect = (n_out_m + n_out_f, n_head, n_hair, n_he, n_mat_expect, n_tex_expect)
    # U13: noueのマスター+MIC構成では正規スロット名(M_VP_m00等、アンダースコアなし)
    # の他に恒久マスター(M_VP_m00_LitMaster1S等)がMainShader配下に同梱される。
    # マテリアル数の勘定は正規スロット名のみを対象にする(マスターは別枠の恒久資産)
    canonical_mat = re.compile(r"MainShader/M_VP_[A-Za-z0-9]+\.uasset$")
    # U40(T3設計転換): live_template.pyがPlayer/Outfit/配下にMI_*
    # (バニラMI差し替え、SkeletalMeshではない)を追加で収録するようになった
    # ため、「/Outfit/配下の.uasset」を無条件でSK衣装として数えると
    # 実測値が水増しされる(60衣装 + 差し替えたMI数、のように)。
    # ファイル名がSK_で始まるものだけを衣装SKとして数える
    # (docs\REPORT_U40_2026-07-25.md T3節)。
    counts = (
        len([p for p in entries if "/Outfit/" in p and p.endswith(".uasset")
             and os.path.basename(p).startswith("SK_")]),
        len([p for p in entries if "/Head/" in p and p.endswith(".uasset")]),
        len([p for p in entries if "/Hair/" in p and p.endswith(".uasset")]),
        len([p for p in entries if "/HeadEquip/" in p and p.endswith(".uasset")]),
        len([p for p in entries if canonical_mat.search(p)]),
        len([p for p in entries if "MainShader/" in p and "/M_VP_" not in p
             and p.endswith(".uasset")]),
    )
    # U15-T2: D2P_NOUE_TEMPLATE_ROOTでテンプレを別アバター(例: Shapell)に
    # 差し替えたクロステンプレート検証時は、テンプレ側の元アバターが持つ
    # 未使用マテリアル/テクスチャスロット(注入対象外、テンプレは読み取り専用で
    # 使用スロットのみ上書きする設計)がそのまま残るため実測>期待になりうる。
    # これはテンプレート由来の資産であり不具合ではない(過小=不具合/過多=許容)。
    # 通常経路(override未設定)は従来どおり厳密一致のまま
    #
    # U50(2026-07-25): dup_*.csvが「バニラpakに実在する全SKの場所依存の完全
    # 列挙」になった(extract_vanilla.py参照)。noueテンプレがまだカバー
    # できていないSK(現時点でHeadEquipのYakushima 6件。ダミーSK資産の
    # 新規生成が必要で未対応)があると、CSV由来の期待値とは必ずずれる。
    # そこでnoueの「宣言された収録集合」であるmanifest由来の期待値も許容し、
    # **どちらか一方に一致すればPASS**とする。緩めた分の検出責任はG10
    # (名前単位のカバレッジ照合、盲点なし)が引き受ける。
    # WP-B3(dev#1198、2026-08-08、当時の既定): 「manifest由来を許容」という
    # フォールバックが、Head/Hairスタブ廃止(常に0件)もそのまま吸収して
    # いた。dev#1258(WP-E、2026-08-09)で既定が反転(Head/Hair常時空スタブ
    # 復帰)したため、既定(dt_flag_head_hide=False)ではmanifest由来の
    # m_expect4もHead/Hairを非ゼロで含むようになる(HeadEquipと同じ扱い)。
    # dt_flag_head_hide=True(ラボ機能ON)のときだけ、m_expect4のHead/Hairが
    # 0へ落ちる(v2.6.0までの既定と同じ挙動の再現)。
    # dev#277第1弾④(2026-08-08、頭装備切り替え): job.jsonのheadequip_show
    # を渡すことで、選択された頭装備ぶんだけHeadEquip期待値を減算する
    # (既定=None/空なら減算ゼロ、従来と完全一致)。これが無いと、頭装備を
    # 1件でもONにした変換がG4(ハードゲート)で必ずFAILしてしまう
    # ——live_template.pyが実際にそのぶんファイルをpakから除いているため。
    m_expect4 = _manifest_sk_counts(job.get("headequip_show"),
                                     job.get("dt_flag_head_hide", False))
    expect4_candidates = [expect[:4]]
    if m_expect4 is not None and m_expect4 != expect[:4]:
        expect4_candidates.append(m_expect4)
    if os.environ.get("D2P_NOUE_TEMPLATE_ROOT"):
        g4_ok = (counts[:4] in expect4_candidates
                 and counts[4] >= expect[4] and counts[5] >= expect[5])
    else:
        g4_ok = counts[:4] in expect4_candidates and counts[4:] == expect[4:]
    gate("G4 entry counts (outfit/head/hair/head-equip/material/texture)", g4_ok,
         f"actual={counts} expected={expect}"
         + (f" or manifest-derived {m_expect4 + expect[4:]}"
            if len(expect4_candidates) > 1 else ""))

    # G5/G5b: バインド回転=バニラ・ボーン集合⊆バニラ(全衣装SK、性別別)
    #
    # U18実測(docs\REPORT_U18_2026-07-23.md参照): 真のバニラ衣装SKは、
    # 武器アタッチメントソケット(weapon_r等、テンプレート自身の元メッシュでも
    # スキニングに使われない純粋な骨のみのボーン)や、per-outfitの装飾用追加
    # ボーン(例: Ancient001のF_Ancient001_elbowArmor_01_l、腕装甲パーツ専用)を
    # RefSkeleton配列に持つ。これらはvanilla_ref(refskel_male/female.json、
    # 男女共通65ボーン基準)には存在しないか、存在してもテンプレート自身の
    # 意匠として意図的に異なる向きを持つことがある(60/60実測で複数個体を確認)。
    # 一方、本パイプラインはRenderSectionsを常にアバター側の実ウェイトから
    # 再構築するため(build_avatar_variant.py参照)、テンプレートの元の
    # BoneMapは一切引き継がれない — 出力(=pakに実際に同梱されるバイト)の
    # BoneMapは常にvanilla_ref由来の共通ボーン名の部分集合になる
    # (build_avatar_variant.pyの「RefSkeletonに存在しないボーン名」検証済み)。
    # そのため、テンプレートのRefSkeleton全件ではなく、**pakに実際に同梱された
    # (=注入済みの)RenderSectionsが実際に参照するボーンだけ**を検査対象にする
    # (旧実装はextract=テンプレート引数のディレクトリを直接globし、未使用の
    # 装飾ボーンまで含めて誤検知していた)。
    vanilla_ref = load_vanilla_ref_for_g5(vanilla_dir, converted_dir=conv)
    _, pak_entries_full = core.read_pak_entries(mod_pak)
    # U40(T3設計転換): 上のG4と同じ理由で、MI_*(バニラMI差し替え、SkeletalMesh
    # ではない)をG5/G5bのRefSkeleton/ボーン検査対象から除外する
    # (MI_*にはRefSkeletonが存在せずcore.find_refskeletonが例外送出する)。
    # U50(2026-07-25): 非対応(コラボ系)のSKは注入されず**バニラのまま**pakに
    # 入るため、バニラ固有の装甲ボーン等をそのまま持つ。これはpakの欠陥では
    # ないので、G5(カバレッジ)/G5b(ボーン集合⊆バニラ)の検査対象から外す。
    # 除外集合はvp_exclusionsのみが決めるので、除外していないSKに対する
    # 検出力は一切変わらない。
    outfit_sk_entries = [p for p in entries
                         if "/Outfit/" in p and p.endswith(".uasset")
                         and os.path.basename(p).startswith("SK_")]
    n_excluded_sk = len([p for p in outfit_sk_entries
                         if vp_exclusions.is_excluded(p)])
    # dev#165: job.jsonのgendersで要求されていない性別のSKも、denylist除外と
    # 同じ理由(注入されずバニラのまま=装飾ボーン等がvanilla_ref共通集合に
    # 無いことがある)でG5/G5bの検査対象から外す。既定(両性別要求)では
    # _is_gender_excludedは常にFalseを返すため、この行は既存のフィルタと
    # 一字一句同じ結果になる。
    n_gender_excluded_sk = len([p for p in outfit_sk_entries
                                if not vp_exclusions.is_excluded(p)
                                and _is_gender_excluded(p, requested_genders)])
    # dev#165第2期: job.jsonのequipment_filterで選択されなかった装備のSKも、
    # 同じ理由(注入・マテリアル統一されずバニラのまま)でG5/G5bの検査対象
    # から外す。requested_equipment=None(既定)では_is_equipment_excludedは
    # 常にFalseを返すため、この行は既存のフィルタと一字一句同じ結果になる。
    n_equipment_excluded_sk = len([p for p in outfit_sk_entries
                                   if not vp_exclusions.is_excluded(p)
                                   and not _is_gender_excluded(p, requested_genders)
                                   and _is_equipment_excluded(p, requested_equipment)])
    sk_uassets = sorted(p for p in outfit_sk_entries
                        if "Player/Outfit/" in p
                        and not vp_exclusions.is_excluded(p)
                        and not _is_gender_excluded(p, requested_genders)
                        and not _is_equipment_excluded(p, requested_equipment))
    if n_excluded_sk:
        print(f"  [INFO] G5/G5b excluded (unsupported/collab items): {n_excluded_sk} "
              + str(sorted(os.path.basename(p)[:-len('.uasset')]
                           for p in outfit_sk_entries
                           if vp_exclusions.is_excluded(p))))
    if n_gender_excluded_sk:
        print(f"  [INFO] G5/G5b excluded (gender not in job.genders="
              f"{sorted(requested_genders)}): {n_gender_excluded_sk} "
              + str(sorted(os.path.basename(p)[:-len('.uasset')]
                           for p in outfit_sk_entries
                           if not vp_exclusions.is_excluded(p)
                           and _is_gender_excluded(p, requested_genders))))
    if n_equipment_excluded_sk:
        print(f"  [INFO] G5/G5b excluded (equipment code not in job.equipment_filter="
              f"{sorted(requested_equipment) if requested_equipment else []}): "
              f"{n_equipment_excluded_sk} "
              + str(sorted(os.path.basename(p)[:-len('.uasset')]
                           for p in outfit_sk_entries
                           if not vp_exclusions.is_excluded(p)
                           and not _is_gender_excluded(p, requested_genders)
                           and _is_equipment_excluded(p, requested_equipment))))
    tmp_dir = os.path.join(job["job_dir"], "build", "preflight_g5_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    # rdp_preflight並列化: 抽出フェーズ(pf使用、直列・不変)と解析フェーズ
    # (プロセス並列)を分離する。理由・決定論性の根拠は_run_g5_analysis()の
    # docstring参照。
    extraction_tasks = []  # [(tmp_uasset, tmp_uexp, ref), ...] 抽出順=sk_uassets順
    with open(mod_pak, "rb") as pf:
        def extract_bytes(rel_path):
            e = pak_entries_full[rel_path]
            if e["compression"] != 0:
                gate("G5 precondition: pak is uncompressed", False,
                     f"compressed entry detected (this pipeline should always produce uncompressed): {rel_path}")
                return b""
            pf.seek(e["data_offset"])
            return pf.read(e["size"])

        for p in sk_uassets:
            uexp_rel = p[:-7] + ".uexp"
            if uexp_rel not in pak_entries_full:
                continue
            base = os.path.basename(p)
            tmp_uasset = os.path.join(tmp_dir, base)
            tmp_uexp = tmp_uasset[:-7] + ".uexp"
            with open(tmp_uasset, "wb") as f:
                f.write(extract_bytes(p))
            with open(tmp_uexp, "wb") as f:
                f.write(extract_bytes(uexp_rel))
            ref = vanilla_ref["male"] if "_Male_" in base else vanilla_ref["female"]
            extraction_tasks.append((tmp_uasset, tmp_uexp, ref))

    worst, unknown_bones, n_checked = _aggregate_g5_results(
        _run_g5_analysis(extraction_tasks))
    # U18実測(docs\REPORT_U18_2026-07-23.md参照): 真のバニラ衣装SKは、
    # 実際にスキニングへ使われている通常ボーン(例: clavicle_l、鎖骨)でも
    # 個別outfitの原作アセット自体がvanilla_ref(共通65ボーン基準)と最大10度
    # 程度の bind回転差を持つことがあると判明(SK_Player_Male_Outfit_Hunter001の
    # clavicle_lで実測)。この値はテンプレート(注入前)とビルド後出力とで
    # バイト完全一致することを確認済み(=本パイプラインは一切変更していない、
    # 100% verbatimコピー)。つまりこれはPalworld自身が出荷している本物の
    # バニラデータそのものであり、そのまま多くのプレイヤーが日常的に装備している
    # 実データである以上、実機で見た目が壊れているとは考えにくい
    # (UEのスキニングはメッシュごとに自己完結したbind poseで計算されるため、
    # 「1つの共通参照骨格と完全一致しなければならない」という前提自体が
    # 本チェックの誤り)。よって回転量の一致は致命ゲートにはせず、
    # 診断情報としてのみ表示する(n_checkedの一致=全60体を実際に検査できた
    # ことの構造的健全性チェックのみ致命ゲートとして残す)。
    # U50: 期待値をCSV由来のexpect[0]から「pakに実際に入っている衣装SK数」
    # (counts[0])へ変更。収録数そのものの妥当性はG4が見ており、ここは
    # 「入っている全SKを実際に検査できたか(uasset/uexpが揃い、解析できたか)」
    # という構造健全性を見るのが本来の役目。CSVがカバレッジの穴の分だけ
    # 大きくなりうる(G10参照)ため、CSVに縛ると本来の意味を失う
    # U50: 期待値から「非対応(コラボ系)で意図的に検査対象外にしたSK」を引く。
    # 引かないとn_checkedが構造的に一致しなくなり誤FAILする(pakは正常)。
    # dev#165: 同じ理由でgender除外分も引く(既定は0なので既存挙動と不変)。
    # dev#165第2期(2026-08-08修正): sk_uassets(実検査対象、697行目)は
    # n_equipment_excluded_sk分も既に除いているのに、期待数側がその分を
    # 引いていなかったため、equipment_filter使用時に構造的に一致しなくなり
    # 誤FAILしていた(オーナー実測: 62枚中equipment_filterで60枚除外、
    # 検査できたのは2枚なのに期待数はexcluded/gender-excludedのみ差し引いた
    # 62のままだった)。既定(requested_equipment=None)では
    # n_equipment_excluded_sk は常に0なので、この式は既存挙動と不変
    # (_g5_expected_countの単体テスト参照)。
    n_g5_expect = _g5_expected_count(
        counts[0], n_excluded_sk, n_gender_excluded_sk, n_equipment_excluded_sk)
    gate("G5 bind-rotation-diff check coverage (structural soundness)",
         n_checked == n_g5_expect,
         f"{n_checked}/{n_g5_expect} checked"
         f"(pak has {counts[0]}, excluded {n_excluded_sk}, "
         f"gender-excluded {n_gender_excluded_sk}, "
         f"equipment-excluded {n_equipment_excluded_sk}. "
         f"CSV-derived expected total is {expect[0]})")
    print(f"  [INFO] G5 diagnostic: max rotation diff (used bones only, includes the "
          f"template's own per-instance variance, not a defect) {worst[0]:.3f}deg ({worst[1]})")
    gate("G5b mesh bone set is a subset of vanilla (bone-rename detection, used bones only)",
         not unknown_bones,
         str(sorted(unknown_bones)[:3]) if unknown_bones else "all bones match")

    # G6: 参照の閉包性(参照する/Game/パスが自pak∪バニラに実在)
    own_pkgs = {p.rsplit(".", 1)[0] for p in full}
    vanilla_pkgs = {p.rsplit(".", 1)[0] for p in vanilla_entries
                    if p.endswith(".uasset")}
    all_pkgs = own_pkgs | vanilla_pkgs

    def pkg_exists(pkg):
        if pkg in all_pkgs:
            return True
        # FName番号の罠: 「SK_..._v02_2」のようなアセットは基底文字列「..._v02」+
        # 番号で直列化されるため、バイト走査では番号無しの文字列が見える。
        # 「pkg + _数字」が実在するなら偽陽性として容認する
        # (バニラのFemale_Outfit_Iron001_v02_2で実害確認)
        prefix = pkg + "_"
        return any(p.startswith(prefix) and p[len(prefix):].isdigit()
                   for p in all_pkgs)

    dangling = set()
    for ua in glob.glob(os.path.join(extract, "**", "*.uasset"), recursive=True):
        with open(ua, "rb") as f:
            s = f.read().decode("latin-1")
        for m in re.finditer(r"/Game/[A-Za-z0-9_/.]+", s):
            pkg = "Pal/Content/" + m.group(0)[len("/Game/"):]
            if not pkg_exists(pkg):
                dangling.add(m.group(0))
    gate("G6 reference closure (no dangling references)", not dangling,
         str(sorted(dangling)[:3]) if dangling else "")

    # G7: シェーダー(SM5+SM6両対応でcookされたか)
    # 2026-07-26 cooklog_fix: cook_logはUEモードでは生のBuildCookRunログ(テキスト)、
    # noueモードではnoue_master\shader_platform_facts.json(固定の事実だけを持つJSON、
    # 生ログの開発機パス・個人アバター名を含む問題を解消するため導入)のどちらかが渡される。
    # まずJSONとして解析し、期待する構造(platforms_cooked配列)を持てばそれで判定する。
    # 解析できなければ(=UEモードの生ログ)従来どおり文字列検索へフォールバックする
    # (UEモード側の挙動・判定基準は一切変えていない)。
    ok_log = False
    if os.path.exists(cook_log):
        with open(cook_log, encoding="utf-8", errors="replace") as f:
            log = f.read()
        fact = None
        try:
            fact = json.loads(log)
        except (ValueError, TypeError):
            fact = None
        if isinstance(fact, dict) and isinstance(fact.get("platforms_cooked"), list):
            platforms = set(fact["platforms_cooked"])
            ok_log = {"PCD3D_SM5", "PCD3D_SM6"}.issubset(platforms)
        else:
            ok_log = "PCD3D_SM6" in log and "PCD3D_SM5" in log
    mat_sizes = [os.path.getsize(p) for p in glob.glob(
        os.path.join(extract, "Player", "ModelMaterials", "MainShader",
                     "M_VP_*.uexp"))]
    # U13: noueのマスター+MIC構成では正規スロット(M_VP_{slot}.uexp)がMICの場合
    # 数百byte程度まで縮む(shadow_lift等のオーバーライド値のみ保持、実シェーダーは
    # 恒久マスター側にある)。シェーダー実体の有無は「最大サイズ」で判定する
    # (min→maxへ変更。旧来のUEモード全出力(MIC無し)ではmin/maxが一致するため
    # 挙動は変わらない)
    ok_size = mat_sizes and max(mat_sizes) > 60_000
    gate("G7 shader SM5+SM6", bool(ok_log and ok_size),
         f"log={ok_log} max={max(mat_sizes) // 1024 if mat_sizes else 0}KB")

    # G8: テクスチャのミップ焼き込み(uexpに実体)
    tex_sizes = {os.path.basename(p): os.path.getsize(p) for p in glob.glob(
        os.path.join(extract, "Player", "ModelMaterials", "MainShader", "*.uexp"))
        if "M_VP_" not in os.path.basename(p)}
    ok_tex = (not n_tex) or (tex_sizes and min(tex_sizes.values()) > 100_000)
    gate("G8 texture data present (NeverStream baked in)", bool(ok_tex),
         f"min={min(tex_sizes.values()) // 1024 if tex_sizes else 0}KB / {len(tex_sizes)} file(s)")

    # G9: マテリアルにGPUSkinシェーダー(used_with_skeletal_meshの物証)
    # U13: MIC(数百byte、shadow_lift等のオーバーライド値のみ)は自身にシェーダーを
    # 持たず親の恒久マスター経由でGPUSkinが効く(MIC自体は検査対象外とする。
    # 100KB未満はMIC相当とみなす — 旧来の全出力Materialは350KB超のため無関係)
    no_skin = []
    for p in glob.glob(os.path.join(extract, "Player", "ModelMaterials",
                                    "MainShader", "M_VP_*.uexp")):
        if os.path.getsize(p) < 100_000:
            continue
        with open(p, "rb") as f:
            if b"GPUSkin" not in f.read():
                no_skin.append(os.path.basename(p))
    gate("G9 material has GPUSkin shader", not no_skin,
         str(no_skin) if no_skin else "all materials OK")

    # ========================================================================
    # G10(U50、既定WARN): 対象一覧のカバレッジ
    # ------------------------------------------------------------------------
    # 「ライブpakに実在する全SKが、このMOD pakに入っているか」を**名前単位**で
    # 照合する。在庫側は命名の形に依存しない場所依存の全数列挙
    # (extract_vanilla.enumerate_vanilla_sk)なので、G4の件数照合が持っていた
    # 「CSV生成側と収録側が同じ正規表現の盲点を共有する」構造がここには無い。
    # 漏れたアセットは「メッシュ注入されない(衣装)」「非表示化されない(頭装備)」
    # という形で実機の見た目が壊れる。
    # ========================================================================
    inv = _load_sk_inventory(vanilla_dir, vanilla_entries)
    if inv is not None:
        # dev#1258(WP-E、2026-08-09、旧dev#1198 WP-B3の判定を反転): 既定
        # (dt_flag_head_hide=False)ではHead/HairもHeadEquipと同じく常時
        # スタブ生成されて出力pakに存在するため、G10のカバレッジ判定から
        # 除外しない。dt_flag_head_hide=True(ラボ機能ON)のときだけ、
        # Head/Hairは"欠落"ではなく"そもそも検査対象外"として除外する
        # (_filter_inv_for_g10_coverage参照。HeadEquipは対象外にしない)。
        inv = _filter_inv_for_g10_coverage(inv, job.get("dt_flag_head_hide", False))
        # U50(2026-07-25): 非対応(コラボ系)のSKは検査対象から外す。
        # 実測(2026-07-25)では、除外SKは**両方の状態を取りうる**:
        #   * Outfit の Yakushima001(男女)/ Octavia001(v01/v02)は
        #     noue_template_manifest.json に載っているのでテンプレ経由で
        #     **バニラのままpakに収録される**(=未収録にはならない)
        #   * HeadEquip の Yakushima001〜006 は manifest に無く、
        #     **pakに収録されない**(ダミーSK資産の新規生成が未対応)
        # どちらであってもユーザーには「バニラの装備がそのまま出る」だけで
        # 実害が無い(=NGではない)ので、収録の有無で場合分けせず
        # 「除外SKはカバレッジ判定から外す」で統一する。件数はINFOに出す。
        # dev#1198 WP-B5a: inv[cat]のrelはBODY_PREFIX無しの座標系
        # (extract_vanilla.CHARACTER_PREFIXで既に"Model/Character/"相当を
        # 剥がし済み)のため、比較側もentries_body_relを使う。raw entriesの
        # ままだと全件不一致になり、G10が「収録漏れ」を全数誤検出する
        # (=検査が事実上無意味化する)。
        pak_set = set(entries_body_rel)
        missing = {}
        excluded_absent = []
        for cat in sorted(inv):
            miss = []
            for r in inv[cat]:
                if r in pak_set:
                    continue
                if vp_exclusions.is_excluded(r):
                    excluded_absent.append(f"{cat}: {r}")
                else:
                    miss.append(r)
            if miss:
                missing[cat] = miss
        n_missing = sum(len(v) for v in missing.values())
        n_inv = sum(len(v) for v in inv.values())
        n_inv_excluded = sum(1 for rows in inv.values() for r in rows
                             if vp_exclusions.is_excluded(r))
        suffix = (f"(plus {n_inv_excluded} excluded as unsupported/collab items)"
                  if n_inv_excluded else "")
        if missing:
            detail = (f"missing {n_missing}/{n_inv} vanilla SK — "
                      + " / ".join(f"{c}:{len(v)}" for c, v in missing.items())
                      + suffix)
        else:
            detail = f"all {n_inv} vanilla SK present{suffix}"
        soft_gate("G10 all SK in the live pak are covered by the target list (location-based, naming-independent match)",
                  not missing, detail, "D2P_PREFLIGHT_COVERAGE", n_missing)
        for c, v in sorted(missing.items()):
            for rel in sorted(v):
                print(f"    [G10 missing] {c}: {rel}")
        for row in sorted(excluded_absent):
            print(f"    [G10 excluded as unsupported, not present] {row}")

    # ========================================================================
    # G11(U50、既定WARN): 全描画スロットが注入アトラス t00 を指しているか
    # ------------------------------------------------------------------------
    # 旧基準は「slot0->t00 / slot1->t01」だったが、マテリアル単一化
    # (live_template._unify_slot_materials、既定ON)で t01 は使われなくなり、
    # 全描画スロットのMIが t00 を指すのが正しい状態になった(旧基準のNG 16件は
    # すべて基準側が古かっただけで実体は正常)。判定は参照先MIの実バイト
    # (name table)を読む方式へ変更してある(_slot_role_check の docstring 参照)。
    # ========================================================================
    n_ng, n_sk, ng_rows, err = _slot_role_check(extract, requested_equipment)
    if err:
        print(f"  [WARN] G11 could not determine slot roles: {err}")
    else:
        soft_gate("G11 all draw slots of all outfit SK point to the injected atlas t00",
                  n_ng == 0, f"NG {n_ng}/{n_sk} SK",
                  "D2P_PREFLIGHT_SLOTROLE", n_ng)
        for row in ng_rows:
            print(f"    [G11 NG] {row}")

    # ========================================================================
    # G12(dev#336、2026-08-08、実体検査化。致命ゲート): 性別限定ビルドの
    # 実体検査。ゲート仕様の変更点は check_g12_gender_isolation() 直前の
    # ヘッダコメント参照。
    # ------------------------------------------------------------------------
    # 【旧仕様(2026-07-30 dev#165新設、廃止)】requested_genders>=
    #   {"Male","Female"}の集合比較のみ。両方揃っていなければ中身を一切
    #   検査せず無条件FAIL(genders指定=即FAILの致命ゲート)。
    # 【新仕様(2026-08-08 dev#336)】除外性別の①衣装MI・素体(MI/テクスチャ)
    #   がpakに存在しないこと(存在=漏れでFAIL)、②残存する除外性別の衣装SK
    #   メッシュが注入済みアバターアトラス(t00/t01)を参照していないこと
    #   (参照=見た目破綻の実害でFAIL)を実バイトから検査する。①②いずれも
    #   満たせばPASS——「genders指定を素通し」にはしない(検査意図は不変、
    #   古いゲートを実装に追随させただけ)。根拠: work\f2_build_verify\
    #   PROGRESS.md/g12_verification.log(dev#336実装が既に①②を満たす形へ
    #   除外機構を変えていたことのバイトレベル実証)。
    # ========================================================================
    g12_ok, g12_detail, g12_leaked, g12_atlas = check_g12_gender_isolation(
        extract, entries, requested_genders, requested_equipment)
    gate("G12 gender-limited build (job.json genders): excluded gender's "
         "outfit MI/body assets must be absent from the pak, and any "
         "excluded-gender SK mesh that remains must not reference the "
         "injected avatar texture atlas (dev#336 real-content check)",
         g12_ok, g12_detail)
    for p in g12_leaked[:20]:
        print(f"    [G12 leaked MI/body asset] {p}")
    for p in g12_atlas[:20]:
        print(f"    [G12 atlas reference] {p}")

    # ========================================================================
    # G13(dev#1198 WP-B5b-fix、致命ゲート): 頭部問題根治の最終ピース(DT同梱)が
    # 実際にpakへ書き出した .uasset/.uexp の整合を、生成ロジックとは独立に
    # 現物から検査する。
    # ------------------------------------------------------------------------
    # dt_flag_patcher.patch_full_body_equipment_flags() は .uexp を可変長編集
    # する(False->True 1行につき+1バイト挿入)。この差分を .uasset 側の
    # エクスポートテーブルSerialSizeへ反映し損ねると、UEはロード時に
    # SerialSizeと.uexp実サイズを照合して不一致を検出し、
    #   LowLevelFatalError ... Serial size mismatch: Got <X>, Expected <Y>
    # で**起動直後に即死**する(根治対象のクラッシュ、
    # work/lab1_crash_triage/parse_export_table.pyで数値実証済み)。
    # dt_flag_patcher.patch_uasset_serial_size() 自体の単体テストは合成
    # フィクスチャに対する検証であり、「実装した」と「効いている」は別
    # (CLAUDE.md)——本ゲートはbuild_pak_from_avatar.pyが実際に書き出して
    # pakへ収めた現物のバイトを読み、独立に整合を確認する。
    # ========================================================================
    dt_uasset_rel = vp_pakwrite.normalize_rel(
        DT_PACKAGE_NAME + ".uasset", vp_pakwrite.DT_PREFIX)
    dt_uexp_rel = vp_pakwrite.normalize_rel(
        DT_PACKAGE_NAME + ".uexp", vp_pakwrite.DT_PREFIX)
    dt_ok, dt_detail = check_dt_serial_size(
        mod_pak, pak_entries_full, dt_uasset_rel, dt_uexp_rel)
    gate(G13_NAME, dt_ok, dt_detail)

    # ========================================================================
    # G14(dev#19 tailmatch3_fix、致命ゲート): job.sway_intensityが揺れ有効値
    # なのにpakへ揺れABPが1件も同梱されなかった事故(rd_19_swaydiag/DIAG.md)の
    # 回帰防止。check_sway_abp_presence()のdocstring参照。
    # ========================================================================
    sway_ok, sway_detail = check_sway_abp_presence(job, pak_entries_full)
    gate(G14_NAME, sway_ok, sway_detail)

    return finish()


def finish():
    n_fail = sum(1 for _, ok, _ in results if not ok)
    n_warn = sum(1 for _, ok, _ in soft_results if not ok)
    if n_warn:
        print(f"\n--- Warnings (do not affect pass/fail; may be promoted to FAIL in the future): {n_warn} ---")
        for name, ok, detail in soft_results:
            if not ok:
                print(f"  [WARN] {name} — {detail}")
        print("  To promote: set D2P_PREFLIGHT_COVERAGE / D2P_PREFLIGHT_SLOTROLE to "
              "fail or max:<count>")
    print(f"\n=== preflight result: "
          f"{'ALL CHECKS PASS' if n_fail == 0 else f'{n_fail} FAIL — do not use this MOD'}"
          f"{f'({n_warn} warning(s))' if n_warn else ''} ===")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
