# -*- coding: utf-8 -*-
"""工程0: ユーザー自身のPalworldインストールからバニラ情報を実行時抽出する。

配布物にゲームデータを一切含めないための要。ここで作るもの(全てジョブ内):
  vanilla/refskel_male.json / refskel_female.json  … 各性別のバインドポーズ数値
  vanilla/refskel_{family}_{male,female}.json      … dev#19 sway donor拡張家系
                                                     (EXTRA_SWAY_FAMILY_SK_REL
                                                     登録済み全家系、常に抽出。
                                                     extract-all-families WP)
  vanilla/common_bones.json                        … 両性別に共通するボーン集合
  vanilla/dup_outfit_{male,female}.csv             … 全ティア複製リスト
  vanilla/dup_head_{male,female}.csv / dup_hair.csv / dup_headequip.csv
  vanilla/sk_inventory.json                        … バニラpakのSK完全在庫
                                                     (場所依存列挙、preflight G10用)
  vanilla/pak_entries.txt.gz                       … バニラpak全エントリ(preflight用)

使い方: python extract_vanilla.py <job.json> [--stage blender|full]

U54(2026-07-26)でキャッシュ判定と2段化を入れた。詳細は下の STAGE_* 節を参照。
"""

import csv
import gzip
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_live_extract
import sway_shared_skeleton  # dev#1508 W2a-2c(汎用ハブ配線): 共有Skeleton
                              # (SK_PalHuman_Skeleton)の全骨rest transform
                              # カタログ抽出(extract_shared_skeleton_catalog()参照)
import vp_core as core

TAG = "extract_vanilla"
# 抽出物の版数。出力の追加・形式変更時に上げる(convert.ps1が照合し、古ければ再抽出)
VANILLA_VERSION = "7"  # 1=初版 2=headequip追加 3=hair refskel追加 4=場所依存列挙(U50)
                        # 5=sway donor合成リーフボーン追加(dev#19 swayfix)
                        # 6=donor家系refskelを既定で全家系抽出(dev#19
                        #   extract-all-families WP、sway_extra_family依存を撤去)
                        # 7=共有Skeleton(SK_PalHuman_Skeleton)全骨カタログ
                        #   sk_palhuman_full.json追加(dev#1508 W2a-2c、汎用ハブ配線)

# dev#1508 W2a-2c(汎用ハブ配線): 共有Skeleton(SK_PalHuman_Skeleton)の
# バニラ正パス。`build_pak_from_avatar.py`の`SWAY_HUB_SK_PACKAGE_NAME`/
# `SWAY_HUB_SK_VANILLA_REL`と意図的に重複させている(値を変えるときは両方
# 直すこと——本ファイル冒頭の「意図的な重複」運用と同型、bpy非依存の
# 2つの独立プロセス境界を跨ぐ定数はこのリポジトリでは重複を許容する)。
SWAY_HUB_SK_PACKAGE_NAME = "SK_PalHuman_Skeleton"
SWAY_HUB_SK_VANILLA_REL = (
    f"Pal/Content/Pal/Model/Character/Skeleton/Human/{SWAY_HUB_SK_PACKAGE_NAME}")

# ============================================================================
# U54(2026-07-26): 抽出のキャッシュ判定と2段化
# ----------------------------------------------------------------------------
# これまで main() には早期リターンが無く、**プレビュー1枚のためにも毎回**
# pakインデックス(18万エントリ)の走査を含むフル抽出が走っていた
# (実測: 初回74秒 / OSキャッシュが温まっていても6秒。しかもフル変換1回で
#  convert.ps1のPhase 0とconvert_noue.pyのmain()から計2回)。
#
# 出力は「誰が読むか」で2段に分かれる:
#   blender段 … refskel_{male,female,hair}.json / common_bones.json
#                Blender工程(step02_retarget.py / validate_armature.py)が
#                直接読む。**プレビュー生成に要るのはここまで**
#   full段    … dup_*.csv / sk_inventory.json / pak_entries.txt.gz
#                pak組み立て(build_pak_from_avatar.py)とpreflight_pak.pyだけが
#                読む。pakインデックス全走査が要る重い側
#
# version.txt の意味は従来どおり「**full段まで**完了した抽出物の版数」。
# UEモードのconvert.ps1(Phase 0)とrestore_full.pyが昔からこの意味で読むので、
# blender段だけで止めたときは**書かない**。中途半端な抽出物を「完了」と
# 誤認させないため。
STAGE_BLENDER = "blender"
STAGE_FULL = "full"
STAGES = (STAGE_BLENDER, STAGE_FULL)

# 段ごとの必須出力(スタンプを信じ切らず実在も確かめる)。refskel_hair.jsonは
# バニラ髪SKが取れないときに作られない(WARNを出して続行する)ので必須にしない
BLENDER_OUTPUTS = ("refskel_male.json", "refskel_female.json",
                   "common_bones.json", "sk_palhuman_full.json")
FULL_OUTPUTS = ("dup_outfit_male.csv", "dup_outfit_female.csv",
                "dup_head_male.csv", "dup_head_female.csv",
                "dup_hair.csv", "dup_headequip.csv",
                "sk_inventory.json", "pak_entries.txt.gz")
STAMP_NAME = "extract_stamp.json"

# ============================================================================
# dev#91(2026-07-29): 抽出物マニフェスト(層理論の互換プローブ)
# ----------------------------------------------------------------------------
# 「変換パイプラインが消費するバニラ抽出物セットのハッシュが前版と不変なら
# ツール互換は確定」という十分条件(dev#91、ぱん裁定でクライアント側自己判定を
# 主機構に採用)を実装する材料。GUI(app\DiveToPalworld.cs)が起動時のバージョン
# チェックで「版番号は不一致だが抽出物は既知良好と一致」を検出し、擬陽性警告を
# 自己抑止するのに使う。
#
# 37.7GBのpak本体は一切ハッシュしない。ハッシュ対象はfull段完了時点で既に
# ディスク上にある小さな出力ファイルだけ(実測合計は概ね1MB未満、
# pak_entries.txt.gzが支配的)。full段は「バニラ抽出はツール起動後どのみち
# 自動で走る」(U54 WP-Bのwarm-cache、GUI起動直後にバックグラウンドで実行)ため、
# 通常運用でこの計算が追加の起動遅延にはならない。
#
# ハッシュ対象からは意図的に extract_stamp.json / version.txt を除外する:
#   - extract_stamp.json … 絶対パス・mtime等の機体固有値を含み、
#     「抽出物の中身が同じか」という問いに無関係なノイズ
#   - version.txt        … 抽出器自身のスキーマ版数(VANILLA_VERSION)であって
#     パルワールド本体のバージョンではない(モジュール冒頭コメント参照)。
#     schema版が同じである前提はcompute_manifest()の外側(呼び出し側が
#     VANILLA_VERSION一致を別途確認する)で担保する
MANIFEST_NAME = "vanilla_manifest.json"
# refskel_hair.jsonは必須出力でない(バニラ髪SKが取れない環境では作られない)ため
# BLENDER_OUTPUTS/FULL_OUTPUTSには含めないが、存在すれば材料の一部として拾う
MANIFEST_OPTIONAL_FILES = ("refskel_hair.json",)
MANIFEST_FILES = BLENDER_OUTPUTS + FULL_OUTPUTS + MANIFEST_OPTIONAL_FILES


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_manifest(vanilla_dir):
    """抽出物セットのsha256マニフェストを作る。戻り値:
    {"algo": "sha256", "files": {relname: hash, ...}, "combined_hash": hash}

    combined_hash は "relname:filehash\\n" をファイル名昇順に連結した文字列の
    sha256。ファイル集合が1つでも増減/変化すればcombined_hashも必ず変わる。
    存在しない任意ファイル(refskel_hair.json等)は静かにmanifestから除外する
    (欠落自体が既知良好リストとの不一致という形で自然に効く)。
    """
    files = {}
    for name in MANIFEST_FILES:
        path = os.path.join(vanilla_dir, name)
        if os.path.exists(path):
            files[name] = _sha256_file(path)
    combined = hashlib.sha256()
    for name in sorted(files):
        combined.update(f"{name}:{files[name]}\n".encode("utf-8"))
    return {"algo": "sha256", "files": files, "combined_hash": combined.hexdigest()}


def write_manifest(vanilla_dir):
    """compute_manifest()の結果をvanilla_dir直下へ書く。呼び出し側が
    read-only施錠(共有キャッシュ)の解除/再施錠を担当すること。"""
    manifest = compute_manifest(vanilla_dir)
    with open(os.path.join(vanilla_dir, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    print(f"[{TAG}] vanilla manifest: combined_hash={manifest['combined_hash']} "
          f"({len(manifest['files'])} file(s))")
    return manifest


def ensure_manifest(vanilla_dir, shared):
    """vanilla_manifest.jsonが無ければ作る(既存の共有キャッシュ/job_dirを
    本機能導入前に作ったユーザーのための後方互換パス)。full段の出力が
    揃っていない場合は何もしない(まだ計算材料が無い)。"""
    if os.path.exists(os.path.join(vanilla_dir, MANIFEST_NAME)):
        return
    if not _have_all(vanilla_dir, FULL_OUTPUTS):
        return
    if shared:
        core.unlock_cache_dir_for_write(vanilla_dir)
    try:
        write_manifest(vanilla_dir)
    finally:
        if shared:
            core.lock_cache_dir_readonly(vanilla_dir)

SK_REL = ("Pal/Content/Pal/Model/Character/Player/Outfit/"
          "SK_Player_{g}_Outfit_OldCloth001/SK_Player_{g}_Outfit_OldCloth001")
HAIR_REL = ("Pal/Content/Pal/Model/Character/Player/Hair/Hair001/"
            "SK_Player_Hair001")

# dev#19 R2b-3(2026-08-11、試着室pak実験、rd_19_r2b3限定の追加)〜donorexp WP
# (issue#19、2026-08-11本流化)〜extract-all-families WP(2026-08-14、下記
# extract_sk_files()docstring参照、本流化第2段): OldCloth001以外のdonor
# ファミリーは、ここに列挙した全キーが**常に**追加抽出され、家系ごとに一意な
# refskel_{family_lower}_{gender}.json へbindpose数値を書き出す
# (OldCloth001の基底refskel_{gender}.jsonは従来どおり不変、追加分のみ増える)。
# job.json "sway_extra_family" は抽出対象そのものはもう左右しない
# (後方互換の未知家系名検証にのみ残る、extract_sk_files()参照)。
#
# donorexp WP(2026-08-11、issue#19、notes_master_1385.md白黒判定の解消):
# "sway_extra_family" は文字列(単一家系、旧仕様)またはリスト(複数家系、
# 新仕様)のどちらも受け付ける(_normalize_extra_families()参照)。旧仕様の
# 単一文字列指定は、本WP以前と全く同じ意味論を保つ(唯一の変更は出力ファイル名
# ——固定共有名"refskel_extra_{gender}.json"から家系ごとの一意名へ。旧共有名は
# 複数家系が同時抽出されると上書き衝突する構造的バグ(notes_master_1385.md
# §「供給段」)を持っていたため、単一家系指定でも家系名を含む一意名へ揃えて
# 衝突可能性そのものを除去する)。キー不在(既定)は分岐に一切入らない
# (=完全no-op、既定出力不変)。
EXTRA_SWAY_FAMILY_SK_REL = {
    "Ancient001": ("Pal/Content/Pal/Model/Character/Player/Outfit/"
                    "SK_Player_{g}_Outfit_Ancient001/SK_Player_{g}_Outfit_Ancient001"),
    # dev#19 rd_19_refskel(2026-08-11): 尻尾8節donor(pelvis直下、チビ安全)。
    # refskel_kigurumi001_{gender}.json はRefSkeleton追加登録
    # (vp_refskel_extend.py)のバインド値ソースとG5b基準マージ(dev#1363)の
    # 両方に使われる
    "Kigurumi001": ("Pal/Content/Pal/Model/Character/Player/Outfit/"
                     "SK_Player_{g}_Outfit_Kigurumi001/SK_Player_{g}_Outfit_Kigurumi001"),
    # dev#19 R3統合(issue#1384、2026-08-11): 耳donor(head直下4節×左右、
    # work\rd_19_haori\sk_palhuman_bones.jsonで実在確認済み。donor詳細は
    # work\rd_19_ears\PROPOSAL.md §4)。SK_HeadEquip062はPlayer/Outfit系と
    # 異なりMale/Female分岐の無い共有アセット(1ファイルのみ)なので、
    # パステンプレートに"{g}"を含めない——下のextract_sk_files()で
    # `extra_rel.format(g=g)`を男女とも呼ぶが、str.format()は未使用の
    # キーワード引数を無視するため、両呼び出しとも同じパスを返し安全に
    # 同じ1ファイルを指す(結果、Extra_HeadEquip062_ear_Male/Femaleは
    # 同一内容になる)。
    "HeadEquip062_ear": ("Pal/Content/Pal/Model/Character/Player/HeadEquip/"
                          "HeadEquip062/SK_HeadEquip062"),
    # donorexp WP(2026-08-11、issue#19、要件3): 骨盤系スカート用donor拡充。
    # work\rd_19_haori\sk_palhuman_bones.json(骨在庫4079骨)実測でpelvis直下
    # 家系を比較した結果、Hunter001が最も枝分かれの多い候補(pelvis直下に
    # 独立4チェーン: 01(2節)/03(1節)/04(2節)/06(4節)、他候補は最大でも
    # OldCloth001の2チェーンまで)。Aliciaのスカート10チェーンを単一家系だけで
    # 賄いきる在庫はバニラに存在しないため、Hunter001(4チェーン)+
    # OldCloth001(2チェーン、既存)+相乗りフォールバック(要件4)の組み合わせで
    # 「対応できない揺れものを作らない」(dev#19裁定§5-3の③)を満たす設計。
    # 選定根拠の候補比較はwork\rd_19_flight\notes_donorexp.md参照。
    "Hunter001": ("Pal/Content/Pal/Model/Character/Player/Outfit/"
                  "SK_Player_{g}_Outfit_Hunter001/SK_Player_{g}_Outfit_Hunter001"),
    # tailmatch WP(dev#19、issue#19、2026-08-12、work\rd_19_flight\briefs\
    # tailmatch_probe.mdが正本): 節数完全一致donor(裁定原理5)の実証。
    # SK_PalHuman_Skeleton(共有骨格、4079骨)自体はvp_core.find_refskeleton()
    # のフィンガープリント上限(count<=400)を超えて直接抽出できないため、
    # このNPC由来チェーンを実際にウェイト付きで含む個別メッシュSK
    # (SK_NPC_GrassBoss001_Skin001、181骨、Male/Female分岐の無い共有アセット。
    # HeadEquip062_earと同様{g}を含まないパス)を指す。パス実在・181骨での
    # 抽出成功・NPC_GrassBoss001_Skin001_tail_{01..05,10}全6骨の座標が
    # work\rd_19_donorcatalog\sk_palhuman_full.jsonの値と一致することを
    # work\rd_19_flight\notes_tailmatch.mdで実測確認済み。
    "NPC_GrassBoss001_Skin001_tail": (
        "Pal/Content/Pal/Model/Character/NPC/Boss/GrassBoss/"
        "SK_NPC_GrassBoss001_Skin001/SK_NPC_GrassBoss001_Skin001"),
}


# swayfix WP(dev#19、issue#19、2026-08-11、work\rd_19_anglelimit\PROPOSAL.md
# §7.2-7.4が正本): 各donor家系のcloth_chain末尾へ追加する合成リーフボーン
# (ウェイト無し、vanilla非在の座標プレースホルダ)の定義。
# pipeline\blender\step02_retarget.py SWAY_DONOR_FAMILIESの"chain"/"leaf"/
# "gendered"/"siblings"と**意図的に重複**させている(step02_retarget.pyはbpy
# 依存モジュールであり、bpy非依存のこのファイルから素直にimportできない
# ——既存のROTATE_CHAINS 3箇所重複(step02_retarget.py冒頭コメント参照)と
# 同じ運用。2箇所を変更するときは値の一致を保つこと)。
#
# earleaf WP(dev#19、issue#19、2026-08-11、work\rd_19_leafcheck\RESULT.md
# 欠陥Bが正本): "siblings"(省略可)は、chainと左右(_l/_r)対をなす別チェーン
# (HeadEquip062_earのみ現状該当、chain=..._l系、siblings=..._r系)。
# siblings末尾が"_l"/"_r"で終わる場合のみ、_add_synthetic_leaf_bone()が
# leafの接尾辞をsiblings側へ書き換えたR側専用の合成リーフボーンも追加登録
# する(下記_add_synthetic_leaf_bone()docstring参照)。旧実装はL側決め打ちの
# "HeadEquip062_ear_05_l"1本しか定義しておらず、R側リーフのRefSkeleton構造
# 登録先自体が存在しなかった(欠陥B)。siblings末尾が左右接尾辞を持たない
# 家系(Ancient001のwaistClothB/C等)ではこの追加登録は発火しない
# (_swap_lr_suffix()がNoneを返し無変更のまま、無退行)。
# siblingsの値はpipeline\blender\step02_retarget.py SWAY_DONOR_FAMILIESの
# 対応する家系のsiblingsと完全一致させる(左右接尾辞を持たない家系でも、
# test_synthetic_leaf_bones_matches_step02_families()の完全性チェックが
# 1:1対応を機械的に保証できるよう、値そのものは省略せず転記する。挙動は
# _side_suffix_of()がNoneを返すため無変更=無退行)。
SYNTHETIC_LEAF_BONES = {
    "OldCloth001": {"chain": [f"OldCloth001_{i:02d}" for i in (4, 5, 6, 7)],
                     "leaf": "OldCloth001_08", "gendered": True,
                     "siblings": [f"OldCloth001_{i:02d}" for i in (1, 2, 3)]},
    "Ancient001": {"chain": [f"Ancient001_waistClothA_{i:02d}" for i in (1, 2, 3, 4)],
                   "leaf": "Ancient001_waistClothA_05", "gendered": True,
                   "siblings": ([f"Ancient001_waistClothB_{i:02d}" for i in (1, 2, 3, 4)]
                                + [f"Ancient001_waistClothC_{i:02d}" for i in (1, 2, 3, 4)])},
    "Kigurumi001": {"chain": [f"Kigurumi001_tail_{i:02d}" for i in range(1, 9)],
                    "leaf": "Kigurumi001_tail_09", "gendered": True,
                    "siblings": []},
    "HeadEquip062_ear": {"chain": [f"HeadEquip062_ear_0{i}_l" for i in (1, 2, 3, 4)],
                          "leaf": "HeadEquip062_ear_05_l", "gendered": False,
                          "siblings": [f"HeadEquip062_ear_0{i}_r" for i in (1, 2, 3, 4)]},
    "Hunter001": {"chain": [f"Hunter001_{i:02d}" for i in (6, 7, 8, 9)],
                  "leaf": "Hunter001_10", "gendered": True,
                  "siblings": [f"Hunter001_{i:02d}" for i in (1, 2, 3, 4, 5)]},
    # tailmatch WP(dev#19、issue#19、2026-08-12): pipeline\blender\
    # step02_retarget.py SWAY_DONOR_FAMILIES の同名エントリと値を一致させる
    # (上のSYNTHETIC_LEAF_BONES docstring「意図的な重複」の運用どおり)。
    # tailexclude WP(dev#19、issue#19、2026-08-13、
    # work\rd_19_pbmap\TAIL_ROOT_FALLBACK_ROOTCAUSE_20260813.md・
    # TAIL_VISUAL_VERDICT_20260813.mdが正本): tail_10/tail_11を除外(chain末尾
    # =tail_05、leaf=tail_06)。step02_retarget.py側の同名エントリのコメントに
    # 詳細な理由を記載——この2箇所は値を必ず一致させること(上記docstring)。
    "NPC_GrassBoss001_Skin001_tail": {
        "chain": [f"NPC_GrassBoss001_Skin001_tail_{i:02d}" for i in (1, 2, 3, 4, 5)],
        "leaf": "NPC_GrassBoss001_Skin001_tail_06", "gendered": False,
        "siblings": [],
        # dev#19 weight-direct-assign WP(2026-08-14、オーナー裁定「元々
        # ウェイトが乗っているボーンがn本なら、donorはn+1本以上でなければ
        # ならない」): しっぽの実転写元は6帯(Tail Root+Tail.001-005)で
        # chainは5節しかないため、旧leaf("..._06")を可動donorへ転用しないと
        # 全帯が収まらない。転用後は"..._06"に実ウェイトが乗るため、揺れの
        # 末端を表す新しいウェイト無しの実リーフボーンがさらに先に要る。
        # "leaf2"はそのための第2合成リーフ(先頭ゼロ2桁"_07"、UE FName分割
        # 地雷"_10"/"_11"問題(tailexclude WP参照)を踏まない命名)。
        # pipeline\blender\step02_retarget.py SWAY_DONOR_FAMILIESの同名
        # エントリと値を一致させること(このファイル冒頭の「意図的な重複」
        # 運用どおり)。
        "leaf2": "NPC_GrassBoss001_Skin001_tail_07"},
}


def _side_suffix_of(name):
    """nameが"_l"または"_r"で終わっていればその接尾辞("_l"/"_r")を返す。
    どちらでもなければNone(左右の概念を持たない家系、例: OldCloth001)。

    earleaf WP(dev#19、issue#19): L/R対称家系のリーフ名派生に使う共通規約。
    pipeline\\blender\\step02_retarget.py 側の_sway_side_suffix_of()と同一の
    規約(末尾"_l"/"_r")で意図的に重複定義(bpy非依存モジュールへ素直に
    importできないため、既存の重複運用と同じ)。"""
    if name.endswith("_l") or name.endswith("_r"):
        return name[-2:]
    return None


def _swap_lr_suffix(name, target_suffix):
    """name末尾の"_l"/"_r"を target_suffix("_l"または"_r")へ置換する
    (name/target_suffixのいずれかが対象外なら無変更のnameをそのまま返す)。
    pipeline\\blender\\step02_retarget.py 側の_sway_with_side_suffix()と同一
    規約(意図的な重複、上記_side_suffix_of()docstring参照)。"""
    if target_suffix is None:
        return name
    if name.endswith("_l") or name.endswith("_r"):
        return name[:-2] + target_suffix
    return name


def _add_one_leaf_bone(ref, chain, leaf_name):
    """chain(接頭辞込みの完全ボーン名列)の末尾へ、leaf_name(接頭辞込み)の
    合成リーフボーン1件をin-placeで追記する共通処理(_add_synthetic_leaf_bone()
    のchain/leaf側・siblings/sibling-leaf側の両方から呼ばれる、earleaf WP
    で関数分割)。位置決めの考え方は_add_synthetic_leaf_bone()docstring参照。

    leaf_nameが既にref内にある、またはchainが空/chain末尾がrefに未抽出の
    場合は静かにno-op(die()しない、安全側)。"""
    if leaf_name in ref:
        return  # 既に存在(想定外の衝突) — 上書きしない、安全側
    if not chain or chain[-1] not in ref:
        return
    tail_bone = ref[chain[-1]]
    delta = list(tail_bone["pos"])
    if all(abs(v) < 1e-9 for v in delta):
        delta = [0.0, 0.0, 1.0]  # tail自身のposがゼロ(想定外): 適当な非ゼロ値
    ref[leaf_name] = {
        "parent": chain[-1],
        "quat": [0.0, 0.0, 0.0, 1.0],
        "pos": delta,
        "scale": [1.0, 1.0, 1.0],
    }


def _add_synthetic_leaf_bone(ref, family, gender):
    """SYNTHETIC_LEAF_BONES[family]の定義に従い、ref(1性別分のRefSkeleton
    dict、core.load_refskel()形式)へ合成リーフボーン(chain側1件+、
    siblings側が左右接尾辞対応なら追加でsiblings側1件)をin-placeで追記する。

    位置は「chain末尾骨自身の親相対pos(=1つ前の骨からの局所オフセット)を
    そのまま1節分再利用したプレースホルダ」(親→子の局所オフセットは概ね
    そのチェーンの"1節分の長さ・向き"を表すため、同じ値を使い回すことは
    「同じ調子でもう1節続ける」という合理的な仮定になる)。
    実際のper-avatar位置はBlender側(step02_retarget.py
    reposition_sway_donor_chain_and_leaf())が変換のたびに再計算し、既存の
    U21 chibi_bone_world_head機構でcooked SKへ反映される——ここでの値は
    「RefSkeletonへ構造登録するための仮の非ゼロ値」で足り、この値そのものが
    実機出力に残ることは無い(vp_refskel_extend.pyが読むのはこのJSONの値だが、
    それは全装備SKへの**構造的な骨追加**のためであり、位置の正しさは
    per-avatarパッチが担保する)。

    earleaf WP(dev#19、issue#19、work\\rd_19_leafcheck\\RESULT.md欠陥B):
    spec.get("siblings")があり、その末尾ボーンが"_l"/"_r"で終わる場合、
    spec["leaf"]の接尾辞をsiblings側の左右へ書き換えたR側(またはL側)
    専用の合成リーフボーンも追加登録する(siblings末尾から親の"chain末尾
    骨相対pos"を再利用する点はchain側と同じ)。siblingsが左右接尾辞を
    持たない家系(Ancient001のwaistClothB/C等)ではこの追加登録は発火しない
    (_swap_lr_suffix()が無変更を返し、既にchain側で追加済みの名前と
    衝突して何もしない=無退行)。

    family未登録・チェーン末尾がrefへ未抽出等の異常時は静かにno-op
    (die()しない——片方のfamilyの欠落だけで抽出全体を止めない。
    実際の欠落は後続のresolve_sway_chain_entries()側のvanilla_dirチェック/
    build_pal_armature側で別途検出される)。
    """
    spec = SYNTHETIC_LEAF_BONES.get(family)
    if spec is None:
        return
    prefix = ("M_" if gender == "Male" else "F_") if spec["gendered"] else ""
    chain = [f"{prefix}{b}" for b in spec["chain"]]
    leaf_name = f"{prefix}{spec['leaf']}"
    _add_one_leaf_bone(ref, chain, leaf_name)

    # dev#19 weight-direct-assign WP(2026-08-14、オーナー裁定): spec["leaf2"]
    # (省略可)があれば、旧leafをさらに1節延長した第2合成リーフを追加登録
    # する。既存のleaf生成と同じ手口(_add_one_leaf_bone()、親の1つ前からの
    # 相対オフセットを再利用する外挿)をchain+[leaf_name]に対してもう1段
    # 適用するだけ(leaf_nameは直前の呼び出しで既にrefへ登録済みのため、
    # chain末尾として参照できる)。旧leafを可動donorへ転用する家系
    # (resolve_sway_chain_entries()のspillover分岐、現状tailのみ)専用。
    leaf2 = spec.get("leaf2")
    if leaf2:
        leaf2_name = f"{prefix}{leaf2}"
        _add_one_leaf_bone(ref, chain + [leaf_name], leaf2_name)

    siblings = spec.get("siblings")
    if not siblings:
        return
    sib_chain = [f"{prefix}{b}" for b in siblings]
    sib_leaf_name = _swap_lr_suffix(leaf_name, _side_suffix_of(sib_chain[-1]))
    if sib_leaf_name == leaf_name:
        return  # siblingsが左右接尾辞を持たない家系 — 追加登録なし(無退行)
    _add_one_leaf_bone(ref, sib_chain, sib_leaf_name)


def _family_gender_of_sk_key(sk_key):
    """extract_sk_files()の結果dictキー("Male"/"Female"/"Hair"/
    "Extra_{family}_{gender}")から(family, gender)を返す。
    "Male"/"Female" -> ("OldCloth001", sk_key)(基底chainはOldCloth001)。
    "Hair" -> (None, None)(sway対象外)。"Extra_..." -> _refskel_output_name()
    と同じrsplit規則でfamily/genderを分離する。"""
    if sk_key in ("Male", "Female"):
        return "OldCloth001", sk_key
    if sk_key == "Hair":
        return None, None
    prefix = "Extra_"
    if not sk_key.startswith(prefix):
        return None, None
    family, _sep, gender = sk_key[len(prefix):].rpartition("_")
    if not family or gender not in ("Male", "Female"):
        return None, None
    return family, gender


def _normalize_extra_families(raw):
    """job["sway_extra_family"]の生値を、家系名のlist(順序維持・空なら[])へ
    正規化する(donorexp WP、要件1)。

    - 未指定/偽値(None, "", [], 0等) -> []  (=完全no-op、既定出力不変)
    - 文字列(旧仕様、単一家系)        -> [その文字列]
    - リスト/タプル(新仕様、複数家系)  -> list(...)(そのまま、重複除去はしない
      ——呼び出し元job.jsonの記載ミスをここで隠さない)
    """
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    return list(raw)


def _find_fallback_base_outfit_family(entries):
    """OldCloth001自体がpakに存在しない場合の代役家系探索(xboxgraceful WP2、
    dev#1606残課題、2026-08-22オーナー裁定「揺れもの無しに設定したら変換が
    通る」)。

    Player/Outfit配下に実在する、OldCloth001と同型(バージョン管理サブ
    フォルダを持たない単一階層、`SK_Player_{g}_Outfit_{family}/
    SK_Player_{g}_Outfit_{family}`)の家系のうち、Male/Female・uasset/uexpの
    4ファイルすべてが揃っているものを、家系名の辞書順で決定論的に1つ選んで
    返す(entries自体の列挙順は実行のたびに変わりうる、dev#91参照)。1件も
    無ければNoneを返す。

    前提: Palworldの全Player衣装SkeletalMeshは共有Skeletonアセット
    (SK_PalHuman_Skeleton)にリグされており、body共通ボーン
    (common_bones.jsonが計算する交差集合)のbind pose数値は衣装非依存
    ——という設計(EXTRA_SWAY_FAMILY_SK_REL各家系のdonor骨格ソースとして
    既に採用されている前提と同じ)に基づく。OldCloth001固有のsway donor
    チェーン(SYNTHETIC_LEAF_BONES["OldCloth001"]、"OldCloth001_04"..等の
    ボーン名)は代役家系には存在しないため、_add_synthetic_leaf_bone()が
    静かにno-opするだけで実害はない(OldCloth001自身のsway donorが
    使えなくなるだけ、他家系donorやbody共通ボーンには影響しない)。

    enumerate_vanilla_sk()(場所依存列挙、SK_CATEGORY_ROOTS["outfit"])を
    再利用する——このファイル内で定義順としては後だが、呼び出し時点で
    モジュールは全読み込み済みのため問題ない。
    """
    inventory = enumerate_vanilla_sk(entries)
    prefix_by_gender = {
        "Male": "SK_Player_Male_Outfit_",
        "Female": "SK_Player_Female_Outfit_",
    }
    found = {}  # family -> {"Male", "Female"}(uassetが揃っている性別の集合、
                # 下でuexpも確認する前段のふるい)
    for r in inventory.get("outfit", []):
        name = r["name"]
        folder_tail = r["folder"].rsplit("/", 1)[-1]
        if folder_tail != name:
            continue  # バージョン管理サブフォルダ等(Octavia001/v01等)は対象外
        for gender, prefix in prefix_by_gender.items():
            if name.startswith(prefix):
                found.setdefault(name[len(prefix):], set()).add(gender)
                break
    uasset_complete = sorted(fam for fam, genders in found.items()
                              if genders == {"Male", "Female"})
    # enumerate_vanilla_sk()は".uasset"エントリしか見ないため、対になる
    # ".uexp"の実在はここで別途確認する(片方だけ揃っていても抽出できない)。
    for fam in uasset_complete:
        rels = [f"Pal/Content/Pal/Model/Character/Player/Outfit/"
                f"SK_Player_{g}_Outfit_{fam}/SK_Player_{g}_Outfit_{fam}"
                for g in ("Male", "Female")]
        if all(rel + ext in entries for rel in rels for ext in (".uasset", ".uexp")):
            return fam
    return None


def extract_sk_files(job, out_dir):
    """OldCloth001のSK+バニラ髪SK(uasset/uexp)を抽出する。UE/UnrealPak.exeは
    使わず、pak_live_extract(U17)でPalworld本体のpakからその場解凍する。
    EXTRA_SWAY_FAMILY_SK_REL登録済みの全donorファミリーのSKも常に併せて
    抽出する(下記「dev#19 extract-all-families WP」参照)。

    dev#19 extract-all-families WP(2026-08-14、issue#19、
    work\\rd_19_smokefinal3\\MANIFEST.md実測欠陥の修正): 旧実装は
    job.json "sway_extra_family"(dev#19 R2b-3追加)に明示指定された家系
    だけを抽出していた。既定GUIジョブはこのキーを一切設定しないため、
    Kigurumi001等の追加donor家系のrefskelがそもそも抽出されず、自動割当
    エンジンのdiscovery(step02_retarget.build_donor_bone_pairs_from_vanilla()、
    このjobが実際に抽出したrefskel_*.jsonの実在だけを見る設計)の候補
    プールに一度も現れない構造的欠陥があった(n+1規則自体
    ——sway_native_rule.py——は正しく実装済みだが、候補が来ないので発動
    しようがない。実測: flatapron 6帯尻尾がKigurumi001(native8、n+1規則の
    正解)ではなく縮退のOldCloth001(native4)へ落ちていた)。

    修正: job["sway_extra_family"]の値に関わらず、EXTRA_SWAY_FAMILY_SK_REL
    に登録済みの全家系を常に抽出する。job["sway_extra_family"]は後方互換の
    ため未知家系名の検証にのみ残す(指定してもしなくても抽出結果そのもの
    は変わらない——既に全家系が無条件で含まれるため)。

    donorexp WP(2026-08-11、issue#19、要件1)由来の "Extra_{family}_{gender}"
    (家系名を含む一意なキー)という戻り値dictの形は不変。

    xboxgraceful WP(dev#1606、issue#1606、2026-08-21): 各extra-family(Hairを
    含む)は「pak内に無ければその家系だけWARN+スキップして続行」する
    (=結果dictにそのキーが現れないだけで、他家系や変換全体には影響しない)。
    OldCloth001(SK_REL、Male/Female)は人体/服骨格の基本SK(refskel_male/
    female.jsonの源、common_bones.json算出にも必須、揺れの有無に関わらず
    リターゲット自体に必須)であり、揺れ有効時(job["sway_enable"]が真)は
    従来どおりFATAL(緩和しない)。Xbox App(Microsoft Store/Game Pass)版
    PalworldのPal-WinGDK.pakがextra-family各家系のSKを1つも含まないケースの
    実測が動機(work\\inq_triage_20260821\\DRBNPKMX.md)。

    xboxgraceful WP2(dev#1606残課題、issue#1606、2026-08-22オーナー裁定
    「揺れもの無しに設定したら変換が通る」): OldCloth001自体もpakに1つも
    無い場合(同実測、DRBNPKMX.mdのFATALログにOldCloth001自体も含まれて
    いた)、かつ揺れ無効設定(job["sway_enable"]が偽)のときに限り、
    Player/Outfit配下に実在する別家系(_find_fallback_base_outfit_family()
    参照)を代役として使い、リターゲット自体は完走させる。揺れ有効時は
    代役を使わず従来どおりFATAL(見た目品質より安全側、「無理筋の実装で
    見た目品質を壊さない」というオーナー裁定に対応)。ゲーム由来データの
    同梱は権利方針上禁止のため、代役はこのjobのpakからその場で探すだけで
    配布物へは一切焼き込まない。

    既知の限界(fingerprintは意図的にpak内容のみに依存し job 設定を含まない
    ——dev#19 extract-all-families WPの設計、本ファイル上部
    build_fingerprint()docstring参照): 同一pak・同一ユーザーが
    sway_enableをOFF→ONへ切り替えて再実行した場合、共有キャッシュが
    新鮮と判定されればこの関数自体が再実行されず、OFF時に代役で作った
    refskel_male/female.jsonがそのまま再利用される(=ON時に本来出るはずの
    FATALが出ない)。これはOldCloth001自体が欠けたpak(Xbox版の一部)でしか
    起こらない上、最悪の帰結も「代役骨格のままsway機能が縮退する」だけで
    誤った見た目にはならない(OldCloth001固有のsway donorだけが使えない)。
    より厳密な修正(job依存の再評価をpakキャッシュの外側——例:
    convert_noue.py側——へ切り出す)は本WPのスコープ外として送る。"""
    pak = job["paths"].get("palworld_pak")
    if not pak or not os.path.exists(pak):
        # WP16(公開issue #8): job.jsonに明示指定が無く自動探索も失敗した場合、
        # vp_core.load_job()がjob["_palworld_pak_search_error"]に「探した場所」
        # つきの詳細メッセージを残している。あればそちらを使い、無ければ
        # (=job.jsonの明示指定が単に無効だった場合)従来どおりの簡潔な文言にする。
        detail = job.get("_palworld_pak_search_error") or (
            f"Palworld's pak was not found: {pak}\n"
            "Please set paths.palworld_pak in job.json")
        core.die(TAG, detail)

    # 後方互換の検証のみ(抽出対象そのものはもう左右しない、上のdocstring参照)。
    explicit_extra = _normalize_extra_families(job.get("sway_extra_family"))
    unknown_families = [f for f in explicit_extra if f not in EXTRA_SWAY_FAMILY_SK_REL]
    if unknown_families:
        core.die(TAG, f"sway_extra_family: unknown family(ies) {unknown_families!r} "
                       f"(known: {sorted(EXTRA_SWAY_FAMILY_SK_REL)})")
    # dev#19 extract-all-families WP: 常に登録済み全家系を抽出する
    # (list(EXTRA_SWAY_FAMILY_SK_REL)は宣言順、決定論的)。未登録家系が
    # ここに紛れ込むことは構造的に無い(このdict自体が抽出対象の唯一の
    # 出所のため——受入条件③の負の対照)。
    extra_families = list(EXTRA_SWAY_FAMILY_SK_REL)

    mount, entries = core.read_pak_entries(pak)

    # xboxgraceful WP2: OldCloth001の代役決定(base_rel_template構築より前に
    # entriesが要るため、read_pak_entries()をここへ引き上げた)。
    base_rel_template = SK_REL
    base_family_label = "OldCloth001"
    old_cloth_paths = [SK_REL.format(g=g) + ext
                        for g in ("Male", "Female") for ext in (".uasset", ".uexp")]
    old_cloth_available = all(p in entries for p in old_cloth_paths)
    if not old_cloth_available and not job.get("sway_enable"):
        fallback_family = _find_fallback_base_outfit_family(entries)
        if fallback_family:
            base_rel_template = (
                "Pal/Content/Pal/Model/Character/Player/Outfit/"
                f"SK_Player_{{g}}_Outfit_{fallback_family}/"
                f"SK_Player_{{g}}_Outfit_{fallback_family}")
            base_family_label = fallback_family
            print(f"[{TAG}][WARN] OldCloth001 SK not found in pak; sway is disabled "
                  f"(job['sway_enable'] is falsy) so using '{fallback_family}' as the "
                  "base body/outfit skeleton source instead (dev#1606)")

    want = {}  # pak内相対パス -> (out_dirへの書き出し先絶対パス)
    for g in ("Male", "Female"):
        base_rel = base_rel_template.format(g=g)
        for ext in (".uasset", ".uexp"):
            want[base_rel + ext] = os.path.join(out_dir, *(base_rel + ext).split("/"))
    for ext in (".uasset", ".uexp"):
        want[HAIR_REL + ext] = os.path.join(out_dir, *(HAIR_REL + ext).split("/"))
    for family in extra_families:
        extra_rel = EXTRA_SWAY_FAMILY_SK_REL[family]
        for g in ("Male", "Female"):
            base_rel = extra_rel.format(g=g)
            for ext in (".uasset", ".uexp"):
                want[base_rel + ext] = os.path.join(out_dir, *(base_rel + ext).split("/"))

    hair_available = (HAIR_REL + ".uasset") in entries and (HAIR_REL + ".uexp") in entries

    # xboxgraceful WP(dev#1606、issue#1606、2026-08-21): Hairと同じ
    # 「家系ごと欠けたらその家系だけWARN+スキップ、変換自体は続行」を
    # EXTRA_SWAY_FAMILY_SK_REL登録済みの全extra-family(donor骨格ソース)へ
    # 拡張する。Xbox App(Microsoft Store/Game Pass)版Palworldのpak
    # (Pal-WinGDK.pak)がこれら家系のSKを1つも含まないケースが実測された
    # (work\inq_triage_20260821\DRBNPKMX.md)。OldCloth001(SK_REL、
    # Male/Female)だけは人体/服骨格の基本SK(refskel_male.json/
    # refskel_female.jsonの源、下流extract_blender_stage()のcommon_bones
    # 算出にも必須)のため、従来どおりFATAL(緩和しない)。
    family_available = {}
    for family in extra_families:
        extra_rel = EXTRA_SWAY_FAMILY_SK_REL[family]
        family_paths = [extra_rel.format(g=g) + ext
                         for g in ("Male", "Female") for ext in (".uasset", ".uexp")]
        family_available[family] = all(p in entries for p in family_paths)

    # Hairおよび欠落中のextra-family分は、旧来のHair専用フィルタ
    # (`not p.startswith(HAIR_REL)`)と同じ手口で「必須チェック対象から
    # 除外」する。OldCloth001(SK_REL)のパスはこの除外集合に一切含まれない
    # ため、欠落時は従来どおりmissing_skへ載りFATALのまま。
    optional_paths = {HAIR_REL + ext for ext in (".uasset", ".uexp")}
    for family, available in family_available.items():
        if available:
            continue
        extra_rel = EXTRA_SWAY_FAMILY_SK_REL[family]
        optional_paths.update(extra_rel.format(g=g) + ext
                               for g in ("Male", "Female") for ext in (".uasset", ".uexp"))

    want_paths = [p for p in want if p in entries or p not in optional_paths]
    missing_sk = [p for p in want_paths if p not in entries]
    if missing_sk:
        core.die(TAG, f"{base_family_label} SK not found in pak (required): {missing_sk}")

    files = pak_live_extract.extract_files(pak, want_paths)
    for p, data in files.items():
        out_path = want[p]
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)

    result = {}
    for g in ("Male", "Female"):
        ua = want[base_rel_template.format(g=g) + ".uasset"]
        result[g] = ua
    if hair_available:
        result["Hair"] = want[HAIR_REL + ".uasset"]
    else:
        print(f"[{TAG}][WARN] failed to extract vanilla hair SK — hair-sway feature unavailable")
    for family in extra_families:
        if not family_available[family]:
            print(f"[{TAG}][WARN] failed to extract vanilla '{family}' SK "
                  f"— this donor family's sway is unavailable, continuing")
            continue
        extra_rel = EXTRA_SWAY_FAMILY_SK_REL[family]
        for g in ("Male", "Female"):
            ua = want[extra_rel.format(g=g) + ".uasset"]
            result[f"Extra_{family}_{g}"] = ua
    return result


# ============================================================================
# U50(2026-07-25): 対象一覧を「命名の形」依存から「場所」依存へ
# ----------------------------------------------------------------------------
# 旧実装は「SKは家族フォルダの直下にある」「頭装備のフォルダ名は HeadEquip\d+」
# のように**階層の深さと命名の型を決め打ちした正規表現**で列挙していた。
# その結果、命名がパターンから外れたバニラアセットが**静かに漏れて**いた
# (実測、work\u50_equip\out\FINDINGS.txt):
#   ・Outfit    : SK_Player_Male_Outfit_Octavia001/v01/SK_..._v01 が1階層深く漏れ
#                 (V1/V2アーマーにメッシュ注入が起きない)
#   ・HeadEquip : YakushimaHeadEquip001..006 / SK_YakushimaHeadEquip00N が
#                 フォルダ名・SK名の両方でパターンに当たらず漏れ
#                 (ホーリー系/ムーンロードのおめん/クトゥルフのめだまマスクが
#                  非表示化されずバニラのまま描画される)
# 対策として、「Player/Outfit 配下の SkeletalMesh はすべて衣装」
# 「Player/HeadEquip 配下はすべて頭装備」と**再帰・非決め打ちで**列挙する。
# 判定に使うのは「どのルート配下にあるか」「SK_ で始まるか」「Skeleton/Physics
# 付随アセットでないか」の3点のみで、深さも家族名も一切前提にしない。
# ============================================================================

# pak内エントリの座標系: "Pal/Content/" から始まる
PAK_CONTENT_PREFIX = "Pal/Content/"
# mod pak / noue_template_manifest.json 側の座標系(この接頭辞を除いた相対パス)
CHARACTER_PREFIX = "Pal/Content/Pal/Model/Character/"

# カテゴリ -> そのカテゴリのSkeletalMeshが置かれるルート(Pal/Content/ からの相対)
SK_CATEGORY_ROOTS = {
    "outfit": "Pal/Model/Character/Player/Outfit",
    "head": "Pal/Model/Character/Player/Head",
    "hair": "Pal/Model/Character/Player/Hair",
    "headequip": "Pal/Model/Character/Player/HeadEquip",
}

# 複製元(自作メッシュを直接置く場所)は複製先リストから外す
DUP_SOURCE_NAMES = frozenset({
    "SK_Player_Male_Outfit_OldCloth001",
    "SK_Player_Female_Outfit_OldCloth001",
    "SK_Player_Male_Head001", "SK_Player_Female_Head001",
    "SK_Player_Hair001", "SK_HeadEquip001",
})


def is_mesh_sk_name(name):
    """アセット名がSkeletalMesh本体のものか(付随のSkeleton/PhysicsAssetでないか)。

    命名の"型"は一切前提にしない。SK_ 接頭辞は Palworld の全カテゴリで
    例外なく守られている実測事実(Outfit 62 / Head 52 / Hair 37 /
    HeadEquip 70、いずれも100%)に基づく唯一の名前依存で、
    「どの家族か」「何階層目か」には依存しない。
    """
    return (name.startswith("SK_")
            and "Skeleton" not in name and "Physics" not in name)


def enumerate_vanilla_sk(entries):
    """バニラpakのエントリ一覧から、カテゴリ別のSkeletalMesh SKを場所依存で列挙する。

    引数 entries: core.read_pak_index/read_pak_entries が返す "Pal/Content/..."
                  形式のパス一覧。
    返り値: {category: [ {folder, name, rel} ... ]}(name昇順)
      folder … UE側のパッケージフォルダ(/Game/Pal/Model/Character/...)
      name   … アセット名(SK_...)
      rel    … CHARACTER_PREFIX を除いた相対パス(mod pak / manifest と同じ座標系。
               例: "Player/Outfit/SK_Player_Male_Outfit_Octavia001/v01/
                    SK_Player_Male_Outfit_Octavia001_v01.uasset")
    """
    out = {cat: [] for cat in SK_CATEGORY_ROOTS}
    for e in entries:
        if not e.endswith(".uasset"):
            continue
        for cat, root in SK_CATEGORY_ROOTS.items():
            prefix = PAK_CONTENT_PREFIX + root + "/"
            if not e.startswith(prefix):
                continue
            pkg = e[len(PAK_CONTENT_PREFIX):-len(".uasset")]  # Pal/Model/.../SK_x
            folder, _, name = pkg.rpartition("/")
            if not is_mesh_sk_name(name):
                break
            out[cat].append({"folder": f"/Game/{folder}", "name": name,
                             "rel": e[len(CHARACTER_PREFIX):]})
            break
    for cat in out:
        out[cat].sort(key=lambda r: (r["folder"], r["name"]))
    return out


def _gender_of(name):
    if "_Male_" in name:
        return "male"
    if "_Female_" in name:
        return "female"
    return None


def gen_duplication_lists(entries, vanilla_dir):
    """pakインデックスから全ティアの複製リストCSVを性別別に生成する(場所依存)。"""
    inventory = enumerate_vanilla_sk(entries)
    # カテゴリ -> {出力CSV名: 行リスト}。outfit/head のみ性別で分ける
    buckets = {
        "dup_outfit_male.csv": [], "dup_outfit_female.csv": [],
        "dup_head_male.csv": [], "dup_head_female.csv": [],
        "dup_hair.csv": [], "dup_headequip.csv": [],
    }
    ungendered = []
    for cat, rows in inventory.items():
        for r in rows:
            if r["name"] in DUP_SOURCE_NAMES:
                continue
            if cat in ("outfit", "head"):
                g = _gender_of(r["name"])
                if g is None:
                    # 性別が判定できないものを黙って落とすと、まさに今回直した
                    # 「静かな漏れ」の再発になる。落とすが**必ず声を上げる**
                    # (preflightのカバレッジゲートが名指しで検出する)
                    ungendered.append(r["rel"])
                    continue
                buckets[f"dup_{cat}_{g}.csv"].append(r)
            else:
                buckets[f"dup_{cat}.csv"].append(r)
    if ungendered:
        print(f"[{TAG}][WARN] excluded {len(ungendered)} Outfit/Head SK whose gender "
              f"could not be determined from the duplication list "
              f"(the preflight coverage gate will detect this): "
              f"{ungendered[:5]}")

    counts = {}
    for fname, rows in buckets.items():
        path = os.path.join(vanilla_dir, fname)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Folder", "Name"])
            w.writerows(sorted({(r["folder"], r["name"]) for r in rows}))
        counts[fname] = len(rows)
        print(f"[{TAG}] {fname}: {len(rows)} rows")
    print(f"[{TAG}] location-based enumeration (U50): "
          + ", ".join(f"{c}={len(inventory[c])}" for c in sorted(inventory)))
    if min(counts.values()) == 0:
        core.die(TAG, f"one or more duplication lists are empty: {counts} — pak structure "
                 "differs from expectations (possible Palworld major update)")

    # カバレッジゲート(preflight)の基準になる完全在庫。CSVは複製元を除いた
    # 「複製先」の一覧なので、漏れの検出にはこちらの生の全数を使う
    inv_path = os.path.join(vanilla_dir, "sk_inventory.json")
    with open(inv_path, "w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=1)
    print(f"[{TAG}] sk_inventory.json: "
          + " ".join(f"{c}={len(inventory[c])}" for c in sorted(inventory)))
    return counts


# --------------------------------------------------------------- キャッシュ判定

def build_fingerprint(job):
    """キャッシュの鍵。**パルワールド本体が更新されたら必ず変わること**が要件。

    鍵に何を使うか(U54、③はdev#226で mtime→内容ハッシュへ改訂):
      ① Pal-Windows.pak の絶対パス+サイズ+更新時刻
         … 抽出物の中身はすべてこのpakだけから決まる。本体が更新されれば
           サイズか更新時刻のどちらかは必ず動く。既に `live_template.
           build_live_template()` が同じ鍵(pak mtime+size)を使っており、
           GUI側の対応バージョン確認(app\\DiveToPalworld.cs)もpakサイズを
           判定材料にしている。プロジェクト全体で同じ流儀に揃える
      ② VANILLA_VERSION … 出力の形式が変わったら作り直す(UEモードの
         convert.ps1 Phase 0 が昔から見ている版数と同じもの)
      ③ この抽出器自身(extract_vanilla.py)の内容sha256(dev#226以前は
         サイズ+更新時刻だった)
         … VANILLA_VERSION の上げ忘れや、アプリ更新でロジックだけ変わった
           場合に「作り直す方」へ倒すため。誤検知の代償は再抽出1回だけで、
           倒れる向きが安全(古い抽出物を使い続ける事故が起きない)。
           dev#226(WSBキャッシュ持ち込みゲート)の実装中、配布zipを毎回
           まっさらなWindows Sandboxへ展開すると展開先ファイルのmtimeは
           「展開した瞬間の時刻」になり(Python zipfile.extractall()の
           挙動、2026-07-30実測)、mtimeベースの識別子は同一内容でも
           Sandbox起動のたびに変わってしまうことが判明した。クリーン
           都度環境でも安定した鮮度判定ができるよう、内容sha256(展開
           位置・タイミングに依存しない)へ切り替える。

    pak自体はハッシュ(sha1等)を採らない。40GBを毎回読むのは本末転倒であり、
    ①だけでもゲーム更新は検知できる(Steamの更新はファイルを置き換える)。
    """
    pak = job["paths"]["palworld_pak"]
    pst = os.stat(pak)
    fp = {
        "vanilla_version": VANILLA_VERSION,
        "pak_path": os.path.abspath(pak),
        "pak_size": pst.st_size,
        "pak_mtime": pst.st_mtime,
        "extractor_hash": core.sha256_file(os.path.abspath(__file__)),
    }
    # dev#19 extract-all-families WP(2026-08-14): 旧実装はここで
    # job["sway_extra_family"]をfingerprintへ含め、指定の有無でキャッシュを
    # 分けていた。extract_sk_files()が登録済み全家系を常に抽出するように
    # なった今、抽出物の中身はもうsway_extra_familyの値に依存しない
    # (=同じpakなら常に同じ出力)ため、この条件付きキーを削除した。
    # VANILLA_VERSIONの版上げ(下記コメント参照)+この関数自身を含む
    # extract_vanilla.py本体のextractor_hash変化により、この変更を跨ぐ
    # 既存キャッシュは自動的に無効化される(古い抽出物を使い回す事故は
    # 起きない、上のdocstring③と同じ安全側の理屈)。
    return fp


def _stamp_path(vanilla_dir):
    return os.path.join(vanilla_dir, STAMP_NAME)


def _read_stamp(vanilla_dir):
    path = _stamp_path(vanilla_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None  # 壊れていたら「無い」扱い=作り直す(安全側)


def _write_stamp(vanilla_dir, job, stage):
    with open(_stamp_path(vanilla_dir), "w", encoding="utf-8") as f:
        json.dump({"stage": stage, "fingerprint": build_fingerprint(job)},
                  f, indent=1)


def _clear_stamp(vanilla_dir):
    """これから出力を上書きする前に消す。途中で落ちても、次回に「完了済み」と
    誤認されないようにするため(古い抽出物を使い回す事故の予防)。"""
    try:
        os.remove(_stamp_path(vanilla_dir))
    except OSError:
        pass


def _have_all(vanilla_dir, names):
    return all(os.path.exists(os.path.join(vanilla_dir, n)) for n in names)


def _version_txt_ok(vanilla_dir):
    """version.txt が「full段まで今の版数で完了した」と言っているか。"""
    try:
        with open(os.path.join(vanilla_dir, "version.txt"), encoding="utf-8") as f:
            return f.read().strip() == VANILLA_VERSION
    except OSError:
        return False


# ============================================================================
# U54 WP-B(2026-07-27): マシン共有キャッシュ化
# ----------------------------------------------------------------------------
# 抽出物は完全にアバター非依存(pakと抽出器だけで決まる)なのに、従来は
# job_dir(work\<AvatarName>\vanilla\)へ書いていたためアバターごとに
# 再抽出していた。ここではPalworldのpakが解決できる通常経路(ライブ抽出)に
# 限り、マシン共有キャッシュ(vp_core.shared_cache_dir)へ本体を置く。
#
# ただし step02_retarget.py(Blender)とpreflight_pak.pyは job["job_dir"]/
# vanilla を直接読んでおり(本WPの書き込み許可ファイル一覧に含まれない
# ため、読み手側のパス解決を付け替えられない)、4.2の原則(per-jobコピー
# 禁止、読み手を共有キャッシュへ向け直す)を完全には満たせない。
# 「どうしても困難な場合のみ最小のper-jobコピーを許す」の規定に従い、
# 共有キャッシュ本体(重い計算=pak全走査等はここで1回だけ)とは別に、
# job_dir配下へも軽量な複製(実測<1MB、pak_entries.txt.gzが支配的でも
# 約800KB)を残す(_sync_job_local_copy)。節約したいのは**計算**であって
# 数百KBのコピーではないため、実害は無い。
#
# D2P_NOUE_TEMPLATE_ROOT(開発/検証用override)またはpakが解決できない
# (開発機フォールバック)場合は、従来どおりjob_dir/vanilla直接書き込みの
# ままにする(resolve_vanilla_source()のkind判定と同じ条件)。
# ============================================================================

def _job_local_vanilla_dir(job):
    return os.path.join(job["job_dir"], "vanilla")


def resolve_vanilla_dir(job):
    """読み手・書き手が共通して使うべきバニラ参照データの実際の場所を1箇所で
    決める。convert_noue.resolve_vanilla_source()のkind判定(override>live>dev)
    と同じ条件(pakの有無、override環境変数)だけを見る軽量な再実装
    (extract_vanilla.py は convert_noue.py から import される側なので、
    循環importを避けるためconvert_noue.pyへは依存しない)。"""
    if os.environ.get("D2P_NOUE_TEMPLATE_ROOT"):
        return _job_local_vanilla_dir(job)  # override: 従来どおりjob_dir直下
    pak = job["paths"].get("palworld_pak")
    if pak and os.path.exists(pak):
        work_root = core.job_work_root(job)
        return core.shared_cache_dir(work_root, "vanilla", build_fingerprint(job))
    return _job_local_vanilla_dir(job)  # 開発機フォールバック: 従来どおり


def cached_stage(job, vanilla_dir=None):
    """既存の抽出物が**今のpak・今の抽出器**に対して有効なら、どこまで
    済んでいるか(STAGE_FULL / STAGE_BLENDER)を返す。無効ならNone。

    スタンプの記載を信じ切らず、その段の出力が実在するかも必ず確かめる
    (作業域をコピーして一部だけ欠けている、手で消した等を拾う)。
    """
    if vanilla_dir is None:
        vanilla_dir = resolve_vanilla_dir(job)
    stamp = _read_stamp(vanilla_dir)
    if not stamp:
        return None
    try:
        if stamp.get("fingerprint") != build_fingerprint(job):
            return None  # pakが更新された/抽出器が変わった → 作り直す
    except OSError:
        # pakが読めない(パス違い等)。ここで判定はできないので「無効」を返し、
        # 抽出本体に理由付きで落としてもらう
        return None
    if not _have_all(vanilla_dir, BLENDER_OUTPUTS):
        return None
    if (stamp.get("stage") == STAGE_FULL
            and _have_all(vanilla_dir, FULL_OUTPUTS)
            and _version_txt_ok(vanilla_dir)):
        return STAGE_FULL
    return STAGE_BLENDER


def is_cache_fresh(job, want_stage):
    """want_stageが既存の抽出物で満たされているか(convert_noue.pyから使う)。"""
    have = cached_stage(job)
    if have == STAGE_FULL:
        return True
    return have == STAGE_BLENDER and want_stage == STAGE_BLENDER


# ------------------------------------------------------------------ 抽出の本体

def _refskel_output_name(sk_key):
    """extract_sk_files()の結果dictキー("Male"/"Female"/"Hair"/
    "Extra_{family}_{gender}")から、書き出すrefskel JSONのファイル名を導出
    する(donorexp WP、要件2: 固定共有名"refskel_extra_{gender}.json"を廃し、
    家系ごとに一意なファイル名へ)。

    - "Male"/"Female" -> "refskel_male.json"/"refskel_female.json"(不変)
    - "Hair"           -> "refskel_hair.json"(不変)
    - "Extra_{family}_{gender}" -> "refskel_{family.lower()}_{gender.lower()}.json"
      (familyそのものに"_"を含む場合(例: "HeadEquip062_ear")でも、末尾の
      "_Male"/"_Female"だけをrsplit("_", 1)で切り離せば正しく family を
      取り出せる——genderは常に"Male"/"Female"のいずれかで固定のため)
    """
    if sk_key in ("Male", "Female"):
        return f"refskel_{sk_key.lower()}.json"
    if sk_key == "Hair":
        return "refskel_hair.json"
    prefix = "Extra_"
    if not sk_key.startswith(prefix):
        raise ValueError(f"unrecognized extract_sk_files() result key: {sk_key!r}")
    family, _sep, gender = sk_key[len(prefix):].rpartition("_")
    if not family or gender not in ("Male", "Female"):
        raise ValueError(f"unrecognized extract_sk_files() result key: {sk_key!r}")
    return f"refskel_{family.lower()}_{gender.lower()}.json"


def extract_shared_skeleton_catalog(job, vanilla_dir):
    """dev#1508 W2a-2c(汎用ハブ配線): 共有Skeleton(SK_PalHuman_Skeleton、
    実測4079骨)の全骨rest transformを`vanilla/sk_palhuman_full.json`へ
    抽出する。`pipeline\\blender\\step02_retarget.py`(sway_hub_wire.py経由)が
    ハブroot+自由donorプールの骨在庫として読む。

    通常のfind_refskeleton()(count<=400の安全域)では抽出できない大規模
    RefSkeletonのため、専用スキャナ(`sway_shared_skeleton.
    scan_full_refskeleton()`、min_bones/max_bones=1000〜6000)を使う
    (`SK_PalHuman_Skeleton(共有骨格、4079骨)自体はvp_core.find_refskeleton()の
    フィンガープリント上限を超えて直接抽出できない`、本ファイル上部の
    EXTRA_SWAY_FAMILY_SK_REL節コメント参照)。"""
    pak = job["paths"].get("palworld_pak")
    if not pak or not os.path.exists(pak):
        detail = job.get("_palworld_pak_search_error") or (
            f"Palworld's pak was not found: {pak}\n"
            "Please set paths.palworld_pak in job.json")
        core.die(TAG, detail)
    want = [SWAY_HUB_SK_VANILLA_REL + ext for ext in (".uasset", ".uexp")]
    mount, entries = core.read_pak_entries(pak)
    missing = [p for p in want if p not in entries]
    if missing:
        core.die(TAG, f"shared skeleton ({SWAY_HUB_SK_PACKAGE_NAME}) not found in "
                       f"Palworld's pak (missing: {missing}) -- dev#1508 hub donor "
                       "catalog extraction cannot proceed")
    files = pak_live_extract.extract_files(pak, want)

    tmp = tempfile.mkdtemp(prefix="d2p_ext_sk_")
    try:
        uasset_path = os.path.join(tmp, SWAY_HUB_SK_PACKAGE_NAME + ".uasset")
        uexp_path = os.path.join(tmp, SWAY_HUB_SK_PACKAGE_NAME + ".uexp")
        with open(uasset_path, "wb") as f:
            f.write(files[SWAY_HUB_SK_VANILLA_REL + ".uasset"])
        with open(uexp_path, "wb") as f:
            f.write(files[SWAY_HUB_SK_VANILLA_REL + ".uexp"])
        try:
            catalog = sway_shared_skeleton.full_skeleton_catalog(uasset_path, uexp_path)
        except sway_shared_skeleton.SharedSkeletonError as e:
            core.die(TAG, f"failed to scan shared skeleton "
                           f"({SWAY_HUB_SK_PACKAGE_NAME}) for hub donor catalog "
                           f"(dev#1508 W2a-2c): {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # source_uasset/source_uexpはこのプロセスのtempディレクトリ(既に削除済み)を
    # 指す絶対パスのため、キャッシュへは残さない(可搬性・ノイズ排除)。
    catalog = dict(catalog)
    catalog.pop("source_uasset", None)
    catalog.pop("source_uexp", None)
    out = os.path.join(vanilla_dir, "sk_palhuman_full.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(catalog, f)
    print(f"[{TAG}] sk_palhuman_full.json: {catalog['bone_count']} bones")


def extract_blender_stage(job, vanilla_dir):
    """Blender工程が読む分(refskel_*.json / common_bones.json)を作る。"""
    # 1) SK抽出 → RefSkeleton数値化(ゲームバイナリは即削除、数値のみ保持)
    tmp = tempfile.mkdtemp(prefix="d2p_ext_")
    try:
        sk = extract_sk_files(job, tmp)
        ref = {}
        for g, ua in sk.items():
            # 髪SKは小骨格(root〜head+hair_01..09の十数本)なので下限を下げる
            ref[g] = core.load_refskel(ua, min_bones=5 if g == "Hair" else 40)
            # swayfix WP(dev#19): このSKのdonor familyが登録済みなら、
            # cloth_chain末尾へ合成リーフボーン1件を追記する(ref[g]を
            # in-place更新、JSON出力にも反映される)。
            _leaf_family, _leaf_gender = _family_gender_of_sk_key(g)
            if _leaf_family is not None:
                _add_synthetic_leaf_bone(ref[g], _leaf_family, _leaf_gender)
            out_name = _refskel_output_name(g)
            out = os.path.join(vanilla_dir, out_name)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(ref[g], f, indent=1)
            print(f"[{TAG}] {out_name}: {len(ref[g])} bones")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 2) 共通ボーン集合(衣装固有のクロスボーン M_/F_OldCloth001_* を除いた交差)。
    #    Blender工程はこの集合だけでアーマチュアを構築する → 両性別で同一階層になり
    #    UE側で1つのSkeletonアセットを共有できる
    common = sorted(set(ref["Male"]) & set(ref["Female"]),
                    key=list(ref["Male"]).index)
    dropped = sorted((set(ref["Male"]) | set(ref["Female"])) - set(common))
    with open(os.path.join(vanilla_dir, "common_bones.json"), "w",
              encoding="utf-8") as f:
        json.dump({"common": common, "dropped": dropped}, f, indent=1)
    print(f"[{TAG}] common bones: {len(common)} (dropped: {dropped})")

    # 3) 共有Skeleton(SK_PalHuman_Skeleton)全骨カタログ(dev#1508 W2a-2c、
    #    汎用ハブ配線のdonor骨在庫)。
    extract_shared_skeleton_catalog(job, vanilla_dir)


def extract_full_stage(job, vanilla_dir):
    """pak組み立て/preflightが読む分(複製リスト+pak全エントリ)を作る。
    pakインデックスの全走査が要る重い側。"""
    # 3) 複製リスト+pak全エントリ(preflightの照合基準)
    mount, entries = core.read_pak_index(job["paths"]["palworld_pak"])
    gen_duplication_lists(entries, vanilla_dir)
    # dev#91(2026-07-29実測で発覚): core.read_pak_index()が返すentriesの並び順は
    # 同一pakでも実行のたびに変わる(pak内部インデックスの走査順が安定していない。
    # v1.0.1/v1.0.2の同一37万行の集合で818行の並び差を実測)。
    # 消費側(preflight_pak.py)はset()化してから使うため並び順に意味は無いが、
    # ここをソートせずに書くと、内容が完全に同一でもファイルのバイト列(ひいては
    # 抽出物マニフェストのcombined_hash、dev#91)が実行ごとに揺れてしまい、
    # 「材料が変わっていないことをハッシュで自己判定する」という目的そのものが
    # 壊れる。ソートして書けば、同じpakからは常に同じバイト列になる。
    # あわせてgzipヘッダのmtimeも固定する(既定はwtの度に現在時刻が入り、
    # 中身が同一でも圧縮後バイト列だけが変わってしまうため)。
    data = "\n".join(sorted(entries)).encode("utf-8")
    with gzip.GzipFile(os.path.join(vanilla_dir, "pak_entries.txt.gz"),
                        mode="wb", mtime=0) as f:
        f.write(data)
    print(f"[{TAG}] pak_entries: {len(entries)} entries (mount={mount})")


def _sync_job_local_copy(job, cache_dir, fingerprint):
    """共有キャッシュの中身をjob_dir配下の従来位置(vanilla\\)へも軽量複製する。
    理由はモジュール冒頭のU54 WP-Bコメント参照(step02_retarget.py/
    preflight_pak.pyがjob_dir/vanillaを直接読むため)。

    複製元(共有キャッシュ)はread-only施錠済みだが、複製先(job_dir側)は
    従来どおり書き込み可能なファイルとして置く(そちらを直接書き換える
    工程は無い読み取り専用の消費者だけなので実害はない)。

    **鮮度判定はfingerprint一致ではなくファイル単位の実在+サイズ一致で行う**
    (引数fingerprintは呼び出し元の互換のため残すが判定には使わない)。
    理由: fingerprintはstage(blender/full)に依存せず同一のため、
    「blender段だけ複製済み」の状態で後からfull段が共有キャッシュへ
    追加されても、fingerprint一致だけを見ていると複製が更新されない
    (実測で発覚: dup_*.csv/sk_inventory.json/pak_entries.txt.gz/version.txtが
    job_dir側に反映されないバグになっていた)。"""
    job_local = _job_local_vanilla_dir(job)
    cache_files = [fn for fn in os.listdir(cache_dir)
                   if fn != STAMP_NAME and os.path.isfile(os.path.join(cache_dir, fn))]
    need_copy = not os.path.isdir(job_local)
    if not need_copy:
        for fn in cache_files:
            dst = os.path.join(job_local, fn)
            src = os.path.join(cache_dir, fn)
            if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src):
                need_copy = True
                break
    if not need_copy:
        return
    os.makedirs(job_local, exist_ok=True)
    for fn in cache_files:
        src = os.path.join(cache_dir, fn)
        dst = os.path.join(job_local, fn)
        # 複製元(共有キャッシュ)はread-only施錠済み。shutil.copy2はメタデータ
        # (パーミッションビット込み)も複製するため、そのまま使うとjob_dir側の
        # 複製先までread-only化されてしまい、次回以降の上書きコピーが
        # PermissionErrorで失敗する(実測で発覚)。copyfile(中身のみ)を使い、
        # 複製先は明示的に書き込み可能にする。
        if os.path.exists(dst):
            try:
                os.chmod(dst, stat.S_IREAD | stat.S_IWRITE)
            except OSError:
                pass
        shutil.copyfile(src, dst)
        try:
            os.chmod(dst, stat.S_IREAD | stat.S_IWRITE)
        except OSError:
            pass
    print(f"[{TAG}] also copying shared cache into job_dir (for step02/preflight): "
          f"{cache_dir} -> {job_local} ({len(cache_files)} file(s))")


def ensure_job_local_copy(job):
    """共有キャッシュ(ライブ抽出モードのみ)の中身をjob_dir配下へも複製する。

    convert_noue.ensure_vanilla()の is_cache_fresh ショートサーキット
    (共有キャッシュが既に新鮮なため extract_vanilla.py のサブプロセス自体を
    一切起動しない経路)専用の公開エントリ。サブプロセス経由でmain()が
    実際に走る経路は、main()内部で必ず_sync_job_local_copyまで完了させる
    ため、ここを呼ぶ必要はない(呼んでも冪等なので害はない)。
    override/開発機フォールバックのときは何もしない(元からjob_dir直下)。"""
    vanilla_dir = resolve_vanilla_dir(job)
    if vanilla_dir == _job_local_vanilla_dir(job):
        return
    _sync_job_local_copy(job, vanilla_dir, build_fingerprint(job))


def parse_args(argv):
    """<job.json> [--stage blender|full]。--stage省略時はfull(従来と同じ)。"""
    stage = STAGE_FULL
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == "--stage":
            if i + 1 >= len(argv):
                core.die(TAG, "--stage requires a value (blender|full)")
            stage = argv[i + 1]
            i += 2
            continue
        rest.append(argv[i])
        i += 1
    if len(rest) != 1 or stage not in STAGES:
        core.die(TAG, "usage: python extract_vanilla.py <job.json> "
                      "[--stage blender|full]")
    return rest[0], stage


def _extract_body(job, vanilla_dir, stage, have):
    """実際の抽出処理(共有/job_dir直下どちらのvanilla_dirでも同じ)。
    呼び出し側(main)が共有キャッシュの場合はロック保持+read-only解除/再施錠
    を担当し、ここは中身の生成だけに専念する。"""
    if have == STAGE_BLENDER:
        # refskel/common_bonesは同じpakから作られた既存物。重い側だけ作り直す
        print(f"[{TAG}] reusing existing refskel/common_bones (pak unchanged). "
              f"building only the pak index side")
    else:
        _clear_stamp(vanilla_dir)  # 上書き前に無効化(中断時に誤認させない)
        extract_blender_stage(job, vanilla_dir)
        if stage == STAGE_BLENDER:
            _write_stamp(vanilla_dir, job, STAGE_BLENDER)
            print(f"[{TAG}] done (stage=blender, pak index side not run)")
            return

    # full段。version.txtは「full完了」の宣言なので、作り直す前に必ず消す
    # (途中で落ちたときに古い版数が残って「完了済み」に見えるのを防ぐ)。
    # スタンプはblender段として書き直しておく: ここまでの出力は今のpakから
    # 作られた正しいものなので、途中で落ちても次回はfull段からやり直せばよい
    try:
        os.remove(os.path.join(vanilla_dir, "version.txt"))
    except OSError:
        pass
    _write_stamp(vanilla_dir, job, STAGE_BLENDER)
    extract_full_stage(job, vanilla_dir)
    with open(os.path.join(vanilla_dir, "version.txt"), "w") as f:
        f.write(VANILLA_VERSION)
    # dev#91: full段が実際に揃った直後(まだ呼び出し側がロックを再施錠する前)に
    # マニフェストを書く。ここで書けば共有キャッシュ経路でも通常のunlock/relockの
    # 外側に追加処理を作らずに済む
    write_manifest(vanilla_dir)
    _write_stamp(vanilla_dir, job, STAGE_FULL)
    print(f"[{TAG}] done (version {VANILLA_VERSION})")


def run(job, stage):
    """job dict(core.load_job済み、または--warm-cache用の最小dict)とstageから
    実際の抽出/共有キャッシュ処理を行う。main()(サブプロセスCLI)と
    convert_noue.py --warm-cache(同一プロセス内の直接呼び出し)の共通経路。"""
    vanilla_dir = resolve_vanilla_dir(job)
    shared = (vanilla_dir != _job_local_vanilla_dir(job))

    have = cached_stage(job, vanilla_dir)
    if have == STAGE_FULL or have == stage:
        print(f"[{TAG}] reusing existing extraction (neither Palworld's pak nor the "
              f"extractor changed): stage={have} -> {vanilla_dir}")
        # dev#91: 本機能導入前に作られたキャッシュ/job_dirにはmanifestが無いので、
        # full段の出力が揃っているなら再抽出せず後追いで作る(後方互換)
        if have == STAGE_FULL:
            ensure_manifest(vanilla_dir, shared)
        if shared:
            _sync_job_local_copy(job, vanilla_dir, build_fingerprint(job))
        return

    if not shared:
        # 従来どおり(override/開発機フォールバック): job_dir直下、ロック不要
        os.makedirs(vanilla_dir, exist_ok=True)
        _extract_body(job, vanilla_dir, stage, have)
        return

    # 共有キャッシュ: クロスプロセスロックを取ってから構築する
    # (GUIのwarmと変換の同時実行、relgate並列複数検体の同時実行への対処)
    lock = core.acquire_cache_lock(vanilla_dir)
    try:
        have = cached_stage(job, vanilla_dir)  # ロック待ち中に他プロセスが完成させた可能性
        if have == STAGE_FULL or have == stage:
            print(f"[{TAG}] reusing existing extraction (another process finished it "
                  f"while waiting for the lock): stage={have} -> {vanilla_dir}")
            if have == STAGE_FULL:
                ensure_manifest(vanilla_dir, shared)
        else:
            os.makedirs(vanilla_dir, exist_ok=True)
            core.unlock_cache_dir_for_write(vanilla_dir)  # 既存分があれば書込可能に戻す
            _extract_body(job, vanilla_dir, stage, have)
            core.lock_cache_dir_readonly(vanilla_dir)  # 完成 -> 施錠
        _sync_job_local_copy(job, vanilla_dir, build_fingerprint(job))
    finally:
        core.release_cache_lock(lock)


def main():
    job_json, stage = parse_args(sys.argv[1:])
    job = core.load_job(job_json)
    run(job, stage)


if __name__ == "__main__":
    main()
