# -*- coding: utf-8 -*-
"""dev#1170 WP-2: マルチアバターPAK合成エンジン(パイプライン側)。

オーナー確定仕様(2026-08-09対話、issue #1170「確定仕様」コメントが正本):

  「合成」= 対応表(装備スロット→中間物ライブラリのエントリ)からSK注入+
  テクスチャ+MI差し替えだけで1 pakを作る。**再変換は一切しない**(VRM/
  prefabへは触らず、convert.ps1・Blenderも呼ばない。中間物ライブラリ
  (`vp_avatar_library.py`、WP-1)が既に保存済みのSK/アトラスを流用するだけ)。

  メインアバターという概念は存在しない。合成器は対応表だけを正とする
  (全スロット充填済みの対応表を受け取る前提。未充填スロットはUI側で
  存在させない設計だが、防御としてここでもエラーにする)。

  頭は「無」を強制注入する: v2.8.0の頭部スタブ機構(Head/Hair空スタブ、
  dev#1258)を常時適用し、ラボの他の頭関連設定(dt_flag_head_hide等)は
  一切参照しない。実装上は極めて単純: 本モジュールが組み立てる内部job辞書
  (`_build_template_job()`)には`equipment_filter`/`headequip_show`/
  `genders`/`dt_flag_head_hide`のいずれのキーも一切書かない。これらは
  `live_template.py`/`preflight_pak.py`の双方で`job.get(key, <既定>)`読み
  なので、キー不在=既定値が常に採用される。dev#1258時点の既定
  (`dt_flag_head_hide=False`)は「Head/HairをHeadEquipと同じ常時空スタブ
  方式にする」であり、これがまさに求める「頭は無」そのもの
  (`live_template._is_head_or_hair_stub_rel()`のdocstring参照)。

  素体(素肌)=OldCloth系スロットも通常の割当対象(他の装備コードと同列に
  扱う。特別扱いしない)。

## 合成ジョブJSON形式(WP-3 UI向けインターフェース契約)

    {
      "output_name": "<ユーザー命名、job_dir名の元になる>",
      "assignments": {"<装備コード>": "<ライブラリエントリID>", ...},
      "paths": {"palworld_pak": "<任意、省略時は自動発見>"}
    }

- `output_name`: 必須。空文字列/空白のみはエラー。`sanitize_name()`
  (ASCII英数字以外を捨て、空ならAvatarへ——app_py\\pipeline_runner.py の
  同名関数と同じ規則の最小複製、pipeline側はapp_py\\に依存できないため)を
  通してjob_dir名になる。既存job_dirと同名なら**上書き**(通常変換の
  `write_job()`と同じ挙動、WP-3側での重複名警告はUIの責務)。
- `assignments`: 必須。{装備コード(`vp_equipment_filter.equipment_code()`と
  同じ語彙、例"Cloth001"): ライブラリエントリID(`vp_avatar_library.
  list_entries()`が返す`entry_id`、= work_root相対のjob_dirフォルダ名)}。
  **コラボ系(vp_exclusions)以外の全装備コードを含むこと**(未充填はエラー、
  下記受入参照)。同じエントリIDを複数の装備コードへ割り当ててよい
  (=そのエントリのアバターを丸ごと使う)。
- `paths.palworld_pak`: 任意。省略時は`palworld_locate.find_palworld_pak()`
  で自動発見する(外部依存パスの原則、CLAUDE.md参照)。

## CLI仕様(WP-3向け)

    python pipeline\\py\\vp_avatar_compose.py --job <compose_job.json> \\
        --work-root <work_root> [--palworld-pak <path>] \\
        [--preflight-nonblocking] [--skip-preflight]

`--work-root`が「エントリの解決元」と「出力先」の両方を兼ねる(WP-3 GUIの
work\\ディレクトリと同じもの)。本モジュールはpipeline\\py\\配下の他の
フラットスクリプト(build_pak_from_avatar.py等)と同じ実行規約に従う
(`python <このファイル>.py ...`。pipeline\\py\\自体をカレントディレクトリ
にするか`PYTHONPATH`へ加えれば`python -m vp_avatar_compose ...`としても
同じエントリポイントが動く——このリポジトリにパッケージ化
(`__init__.py`)は無く、既存の全pipeline\\py\\スクリプトが同じ規約)。
関数API(`compose_avatar()`)もそのままimportして使える。

## 出力

完成pakを`<work_root>/<sanitize_name(output_name)>/build/*_PlayerSwap_P.pak`
(pipeline_runner.write_job()と同じjob_dir構造、pak_manager.list_built_paks()
が拾える形)へ書く。

**マルチ品フラグの書き場所(2026-08-09時点でWP-3側が既に確定・マージ済みの
契約、`app_py\\pak_manager.entry_is_multi_avatar()`のdocstring/実装が正本)**:
`multi_avatar: true`は`job_dir/library/manifest.json`——すなわち
`vp_avatar_library.manifest_path(job_dir)`が指すのと**同じファイル**へ書く
(job_dir直下の別ファイルではない)。`pak_manager.entry_is_multi_avatar()`は
`vp_avatar_library.read_manifest(job_dir)`(=このパスをそのまま読む)経由で
判定するため、ここに書かなければWP-3の「右ペインから除外」「作成済みMOD
一覧でマルチ品を判別」が機能しない。ただし**`vp_avatar_library.
save_library()`自体は呼ばない**(SK群+アトラスの重いコピーをせず、
`library/`ディレクトリと`manifest.json`だけを直接書く——`has_library()`は
manifest.jsonの存在だけを見るため、この最小限の書き込みで両方の契約
(「マルチ品と判定される」+「合成品の中間物は保存しない」)を同時に満たす)。

## 実装の骨子

各装備コードについて:
  1. 割当エントリの中間物(`vp_avatar_library.resolve_sk_path()`が返す
     Outfit SK、`resolve_atlas_path()`が返すアトラスPNG)から装備SKを
     バニラ実在パスへ配置。
  2. その装備の非共有(排他)MIをバニラMIバイト+平坦化opsで再構築し
     (`vp_equipment_avatar._rebuild_exclusive_mi()`)、そのバニラ"_B"
     テクスチャ枠へ割当エントリのアトラスをubulk対応で焼き込む。
  3. 共有ボディMI(MI_Player_{gender}_Body)は、そのgender+割当エントリ
     専用の複製パスへクローンし(`live_template._clone_mvp_mic_as()`)、
     装備SK側のimportだけをretargetする。
  4. 共有MI衝突検出(`vp_equipment_avatar.detect_shared_mi_conflicts()`)
     ——同一共有MIが異なるエントリへ割られたらエラー。

これらの低レベル部品は`pipeline\\py\\vp_equipment_avatar.py`
(WP-A初版のドライバを落として部品だけを残したもの)をそのまま呼ぶ
(二重実装を避ける)。SK/テクスチャ/MIの上書きツリーが揃ったら、
`build_pak_from_avatar.py`のPhase 3(pak化)・Phase 3.5(DT flagパッチ、
`_run_dt_patch()`)・Phase 4(preflight、`run_preflight_phase()`)を
**関数として直接呼ぶ**(サブプロセスのCLI経由ではない——Phase 1/2
(Blender dump/SK注入)は要らないため、`build_pak_from_avatar.main()`
自体は呼ばない)。上書きツリーのfinal_filesへのマージも同ファイルの
`apply_equip_avatar_extra_dir()`(WP-A初版が導入した汎用ユーティリティ、
「テンプレートに無いrelも追加できる」という性質がそのまま必要)を再利用する。

テンプレート(`live_template.build_live_template()`)・バニラ参照データ
(`extract_vanilla.run()`)はいずれも**アバター非依存**(Palworldのpakと
抽出器だけで決まる)ため、通常の単一アバター変換と同じマシン共有キャッシュ
(`work_root/_shared_cache/...`)を再利用する——初回以降はほぼ瞬時。

## avatar_meta.json(preflight G4向けの合法な最小値)

preflight_pak.pyのG4ゲートは`<job_dir>/converted/avatar_meta.json`の
`slots`辞書からマテリアル/テクスチャ数を数える。合成品は特定の1アバターの
Blender変換結果を持たないため、本モジュールは`{"slots": {"composed":
{"texture": None}}}`という最小合法値を自分で書く。noueテンプレートは
材質が1件以上あれば常に固定2件のマテリアル資産(M_VP_m00/m01)と固定2件の
テクスチャ資産(t00/t01)を同梱する(`preflight_pak.g4_mat_tex_expect()`の
docstring参照、dev#958)ため、この値はどの合成品に対しても正しい期待値を
導く(実Blender出力を偽装しているのではなく、G4が実際に検査したい不変量
——「材質注入が最低1件起きたか」——を最小の形で表明しているだけ)。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import string
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import build_pak_from_avatar  # noqa: E402 (Phase3/3.5/4のヘルパーを直接再利用)
import extract_vanilla  # noqa: E402 (バニラ参照データ、Blender不要のpure Python抽出)
import live_template  # noqa: E402
import palworld_locate  # noqa: E402
import vp_avatar_library  # noqa: E402 (WP-1: 中間物ライブラリ)
import vp_equipment_avatar  # noqa: E402 (MI発見/再構築/共有MI検出/bodyクローンの部品)
import vp_equipment_filter  # noqa: E402
import vp_exclusions  # noqa: E402
import vp_pakwrite  # noqa: E402
import vp_texinject  # noqa: E402

TAG = "vp_avatar_compose"

# 合成品マニフェスト(job_dir/library/manifest.json)のformat_version。
# vp_avatar_library.FORMAT_VERSIONとは独立のカウンタ(内容(キー構成)が
# 別物のため——合成品はsk/atlas等の中間物ペイロードを持たない)。
FORMAT_VERSION = 1

_SANITIZE_ALLOWED = set(string.ascii_letters + string.digits)


class ComposeError(RuntimeError):
    """合成ジョブ処理中の想定内エラー(ビルド停止・明確な案内)。ユーザーを
    咎めない文言で書く(CLAUDE.md「ユーザーのアバターを咎めない」)。"""


# --------------------------------------------------------------- path解決


def sanitize_name(name):
    """app_py\\pipeline_runner.sanitize_name()と同じ規則の最小複製
    (ASCII英数字以外を捨て、空ならAvatarへ)。pipeline\\py\\はapp_py\\へ
    依存できない(本WPの書き込み許可外)ため、この1関数だけ複製する。"""
    kept = "".join(c for c in (name or "") if c in _SANITIZE_ALLOWED)
    return kept if kept else "Avatar"


def job_dir_for(work_root, output_name):
    """出力先job_dir(=work_root直下のsanitize_name(output_name)フォルダ)。
    既存の通常変換job_dirと同じ命名規則(pipeline_runner.write_job())。"""
    return os.path.join(os.path.abspath(work_root), sanitize_name(output_name))


def _entry_key(entry_id):
    """ライブラリエントリIDから安定した短いhex識別子を作る(共有ボディMI
    クローン先パッケージパスの名前空間分離用、ログ表示用)。
    vp_equipment_avatar._avatar_key()はファイルパスのos.path.abspath()を
    前提にしており、エントリID(work_root相対の不透明な文字列トークン)には
    使えないため、こちらは素の文字列をハッシュするだけの独自実装。"""
    return hashlib.sha1(str(entry_id).encode("utf-8")).hexdigest()[:10]


# --------------------------------------------------------------- 検証


def normalize_assignments(compose_job):
    """合成ジョブJSONの"assignments"を正規化する。空/未設定はエラー
    (対応表が空では合成できない——通常のjob.get既定no-opパターンとは違い、
    本関数自体が呼ばれる時点で「合成しようとしている」ことが確定している)。
    キー・値とも文字列化し、空文字列のキー/値は無視する。"""
    raw = (compose_job or {}).get("assignments")
    if not raw:
        raise ComposeError(
            "assignments is empty; please assign every equipment slot and "
            "try composing again")
    out = {}
    for code, entry_id in raw.items():
        if not code or not entry_id:
            continue
        out[str(code)] = str(entry_id)
    if not out:
        raise ComposeError(
            "assignments is empty; please assign every equipment slot and "
            "try composing again")
    return out


def _codes_for_names(all_names, code):
    return [n for n in all_names if vp_equipment_filter.equipment_code(n) == code]


def outfit_sk_folder_map(manifest):
    """manifest["vanilla"]から、(gender, code) -> "Player/Outfit/<フォルダ名>"
    の対応表を作る。

    dev#1170 WP-2の実pak検証で判明した落とし穴の是正: バニラのOutfit SKは、
    同一の"基準"フォルダ(例 Player/Outfit/SK_Player_Female_Outfit_Ancient001/)
    の中に複数の異なる装備コード(基準そのものAncient001、および
    "バリアント"Ancient001_v02/_v03/_v04等)がファイルとして同居する実物
    パターンが多数ある——フォルダ名がcode(接尾辞込み)と一致するとは
    限らない。ファイル名から接尾辞を取り除いてフォルダ名を推測する
    (脆く、"Iron001_v02_2"のような2段接尾辞では一般化しない)のではなく、
    実際にmanifestへ記録されているフォルダ構造をそのまま読む
    (vp_avatar_library.resolve_sk_path()の同種の是正と対になる)。"""
    out = {}
    for rel in manifest["vanilla"]:
        if not (rel.startswith("Player/Outfit/") and rel.endswith(".uasset")):
            continue
        parts = rel.split("/")
        if len(parts) != 4:
            continue
        folder, base = parts[2], parts[3][:-len(".uasset")]
        code = vp_equipment_filter.equipment_code(base)
        if code is None:
            continue
        gender = "Male" if base.startswith("SK_Player_Male_Outfit_") else "Female"
        out[(gender, code)] = f"Player/Outfit/{folder}"
    return out


def required_equipment_codes(manifest):
    """合成の対象として割当が必須な装備コード集合。全裝備コードのうち、
    コラボ系(vp_exclusions、責任者裁定「コラボ系アイテムは非対応」)で
    **両性別とも**完全に除外されているコードは対象外にする(中間物
    ライブラリは通常変換でも注入されなかったコードのSKを一切保存しない
    ため、割当を要求しても常にエラーになるだけで意味がない)。"""
    all_names = vp_equipment_filter.outfit_sk_names_from_manifest(manifest)
    codes = vp_equipment_filter.known_equipment_codes(all_names)
    required = set()
    for code in codes:
        names_for_code = _codes_for_names(all_names, code)
        if names_for_code and all(vp_exclusions.is_excluded(n) for n in names_for_code):
            continue
        required.add(code)
    return required


def validate_assignments(assignments, manifest):
    """assignmentsの構造的妥当性を検証する(実在パク/ライブラリエントリの
    実在確認はここでは行わない、呼び出し側の別の検証ステップの責務)。
    - 未知の装備コード(バニラに一致するOutfit SKが無い)→ ComposeError
    - 割当必須コードの未充填 → ComposeError
    """
    all_names = vp_equipment_filter.outfit_sk_names_from_manifest(manifest)
    known_codes = vp_equipment_filter.known_equipment_codes(all_names)
    unknown = sorted(c for c in assignments if c not in known_codes)
    if unknown:
        raise ComposeError(
            "unknown equipment code(s) in assignments (please convert again "
            f"to refresh the equipment list and try composing again): {unknown}")
    required = required_equipment_codes(manifest)
    missing = sorted(required - set(assignments))
    if missing:
        raise ComposeError(
            "some equipment slots are not assigned; please assign every "
            f"equipment slot and try composing again: {missing}")


def resolve_palworld_pak(compose_job, explicit=None):
    """パルワールド本体pakのパスを解決する。①明示引数 ②合成ジョブJSONの
    paths.palworld_pak ③自動発見(palworld_locate)、の順(外部依存パスの
    原則、CLAUDE.md参照)。見つからなければComposeError。"""
    if explicit:
        return os.path.abspath(explicit)
    p = ((compose_job or {}).get("paths") or {}).get("palworld_pak")
    if p:
        return os.path.abspath(p)
    try:
        return palworld_locate.find_palworld_pak()
    except palworld_locate.PalworldNotFoundError as e:
        raise ComposeError(f"Palworld installation not found: {e}") from e


def _entry_mi_ops(entry_job_dir):
    """dev#1170 WP-2フォローアップ第2弾(2026-08-10): このライブラリ
    エントリの保存済み変換設定(vp_avatar_library._settings_summary()が
    manifest.json["settings"]へ記録したshadow_lift/unlit)から、統一MI
    クローンへ適用するops列を作る。

    live_template.unify_base_ops()(Specular=0、常時)+
    live_template.unify_shadow_ops(shadow_lift, unlit)(shadow_lift>0または
    unlit=Trueのときだけ非空。single-avatar通常品のbuild_shadow_mi_overrides()
    と同じ式)。設定が読めない(manifest破損・旧形式)場合は安全側
    (shadow_lift=0.0, unlit=False = 追加opsなし、Emissive関連パラメータは
    一切出現しない)にフォールバックする。"""
    manifest = vp_avatar_library.read_manifest(entry_job_dir) or {}
    settings = manifest.get("settings") or {}
    shadow_lift = settings.get("shadow_lift", 0.0)
    unlit = bool(settings.get("unlit", False))
    k_ops, _k = live_template.unify_shadow_ops(shadow_lift, unlit=unlit)
    return live_template.unify_base_ops() + k_ops


def resolve_entry_job_dir(work_root, entry_id):
    """ライブラリエントリID(WP-1、= work_root相対のjob_dirフォルダ名)から
    実在するjob_dirを解決する。存在しない/中間物が未保存ならComposeError
    (ユーザーを咎めない文言、CLAUDE.md参照)。"""
    job_dir = vp_avatar_library.resolve_job_dir(work_root, entry_id)
    if job_dir is None:
        raise ComposeError(
            f"library entry not found: {entry_id!r}; please convert again "
            "to refresh the list and try composing again")
    if not vp_avatar_library.has_library(job_dir):
        raise ComposeError(
            f"library entry {entry_id!r} has no saved intermediate data; "
            "please convert this avatar again and try composing again")
    return job_dir


# --------------------------------------------------------------- ファイル書き出し


def _write_bytes(base_dir, rel, data):
    p = os.path.join(base_dir, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    return p


def _clone_body_mi_for_entry(pak, body_full, gender, entry_id, rep_tex, unify_src_paths,
                              ops, tmp_dir, overrides_dir, processed_mi_paths, log):
    """1つの(body_full, entry_id)ペアについて、共有ボディMI
    (MI_Player_{gender}_Body)のクローン+Base Texture差し替えを行う。

    dev#1170 WP-2差し戻し是正(Masterライターレビュー、2026-08-09)で
    compose_avatar()本体のループから切り出した——共有ボディMIを参照する
    装備群が複数の異なるライブラリエントリへ分割割当された場合、
    エントリごとに**独立して**呼び出せるようにするため(旧実装は
    「複数エントリなら一律ComposeError」だった。実測work\\rd_1170_mesh\\
    FINDINGS.md 1節: Female側は全58装備SKがこの共有ボディMIを参照する
    ため、本機能の核心用途=装備ごとに別エントリを割る、がほぼ確実に
    このガードに触れて失敗していた)。

    dev#1170 WP-2フォローアップ第2弾(2026-08-10、実機報告のEmissive残留
    修正): 旧実装は「バニラの素体MI自身」のバイトをそのままクローンして
    Base Textureだけ向け替えていた。実測(work\\rd_1170_emission\\
    FINDINGS.md)ではMI_Player_{Male,Female}_Body自体はEmissive Texture
    パラメータを持たない(実害はこの経路では未確認)が、通常品(single-avatar
    変換)は素体スロットも例外なく統一MI(live_template.UNIFY_SRC_GAME_PATH
    由来)へ置き換えている——実際に既存job出力で素体MIと衣装MIのuexpが
    バイト完全一致することを確認済み(compose以外の全アバターがこの前提で
    出荷されている)。本関数もその前提に合わせ、統一MI源(unify_src_paths、
    呼び出し側compose_avatar()が1回だけ抽出)から素体クローンを作る形へ
    揃えた——将来Emissiveパラメータを持つバニラ資産に差し替わっても
    構造的に安全であり、shadow_lift(opsに含まれうる)もこれで初めて
    合成品の素体スロットへ届くようになる。

    クローン先パッケージパス(`_body_mi_clone_path()`)はavatar_key=
    `_entry_key(entry_id)`で分岐するため、エントリごとに異なるパッケージ
    パスになり衝突しない。

    戻り値: (new_full, created)。createdはこの呼び出しで実際にクローン
    作業を行ったか(True)、既に処理済み=処理済み集合にヒットしただけか
    (False、呼び出し元のn_body_cloneカウント用)。"""
    akey = _entry_key(entry_id)
    new_full = vp_equipment_avatar._body_mi_clone_path(body_full, akey)
    if new_full in processed_mi_paths:
        return new_full, False

    rel_vanilla = vp_equipment_avatar._game_path_to_rel(body_full)
    safe = rel_vanilla.replace("/", "_") + "_" + akey
    tex_short = rep_tex.rsplit("/", 1)[-1]
    src_ua_path, src_ue_path = unify_src_paths
    va, ve, _oplog = live_template.build_unified_mi_variant_for_target(
        src_ua_path, src_ue_path, rep_tex, tex_short, ops, tmp_dir, tag="body_" + safe)

    clone_ua, clone_ue = live_template._clone_mvp_mic_as(va, ve, new_full)
    new_rel = vp_equipment_avatar._game_path_to_rel(new_full)
    _write_bytes(overrides_dir, new_rel + ".uasset", clone_ua)
    _write_bytes(overrides_dir, new_rel + ".uexp", clone_ue)
    processed_mi_paths.add(new_full)
    log(f"[{TAG}] body slot ({gender}/{entry_id!r}): cloned {body_full} "
        f"-> {new_full} (Base Texture -> {tex_short})")
    return new_full, True


def _guard_and_rescue_body_mi_retarget(sk_ua_bytes, body_full, new_full, sk_rel):
    """dev#1358(診断: work\\rd_19_r2a2\\diag\\DIAG.md): live_template.
    retarget_sk_body_mi_imports(sk_ua_bytes, {body_full: new_full})が
    n_hits=0で通過したSKについて、「このSKは共有ボディMIを一切参照して
    いない」(正常)と「参照してはいるが想定外パス(equipment_filterビルド
    由来のAvatarSelect複製先、`.../Body/{Gender}/AvatarSelect/
    MI_Player_{Gender}_Body`)で無視された」(想定外・無音no-opの禁止対象)
    を区別する。

    vp_avatar_library.save_library()のdev#1358是正で新規保存されるライブ
    ラリエントリのSKは、保存時点で既にバニラパスへ正規化されているため
    このガードには到達しない(呼び出し元の一次retargetでn_hits>0になる)。
    本関数は**是正前に保存済みの既存ライブラリエントリ**への互換のために
    フォールバック救済も兼ねる: 対象性別の共有ボディMIスロットを参照する
    importが(パス接頭辞を問わず接尾辞ベースで)見つかれば、new_fullへ
    直接retargetして救済する。

    実uasset構造としてパース不能な入力(壊れている、あるいはこのプロジェ
    クトの単体テストが使う合成ダミーバイト列)は判定不能として現状維持
    (=無改変、n_hits=0のまま)する——実パイプラインが扱うSKは常に実
    uasset構造なので、このフォールバックは実運用の安全性を弱めない。

    戻り値: (n_hits, new_or_same_uasset_bytes)。想定外の構造不一致
    (対象importが見つかったのに実際のretargetが1件も書き換えられない)は
    ComposeErrorを送出する(無音no-opにしない)。"""
    gender_suffix = ("/MI_Player_Male_Body" if body_full.endswith("/MI_Player_Male_Body")
                      else "/MI_Player_Female_Body")
    try:
        found = live_template.find_sk_body_mi_package_imports(sk_ua_bytes)
    except Exception:
        return 0, sk_ua_bytes
    matching = sorted(p for p in found if p.endswith(gender_suffix) and p != new_full)
    if not matching:
        return 0, sk_ua_bytes  # このSKは本当にこの性別の共有ボディMIを参照していない(正常)
    path_map = {p: new_full for p in matching}
    try:
        new_bytes, n_hits, _retargeted = live_template.retarget_sk_body_mi_imports(
            sk_ua_bytes, path_map)
    except Exception as e:
        raise ComposeError(
            f"compose: body MI retarget failed for {sk_rel} while rescuing "
            f"dangling reference(s) {sorted(path_map)}: {e} (dev#1358)") from e
    if n_hits != len(path_map):
        raise ComposeError(
            f"compose: body MI retarget mismatch for {sk_rel}: found "
            f"reference(s) {sorted(path_map)} but only {n_hits} import(s) "
            "were patched (dangling shared-body-material reference guard, "
            "dev#1358)")
    return n_hits, new_bytes


# ------------------------------------------------------------------ compose


def compose_avatar(compose_job, work_root, *, palworld_pak=None,
                    preflight_nonblocking=False, skip_preflight=False, log=print):
    """合成ジョブを実行し、完成pakをwork_root配下のjob_dir構造へ書き出す。

    convert.ps1・Blenderは呼ばない(中間物ライブラリの保存済みSK+アトラス
    からのSK注入以降のみ)。戻り値:
    {"job_dir", "out_pak", "n_sk", "n_mi", "n_tex", "n_body_clone",
     "n_body_retarget", "preflight_status"}
    (preflight_statusは"skipped"/"blocking_pass"/"nonblocking:<PASS|FAIL>")

    想定内の入力エラー(未充填スロット・存在しないエントリID・共有MI衝突等)
    はComposeErrorを送出する。予期しない構造的破損(バニラpakの想定外構造
    等)はvp_core.die()系のSystemExitで停止する(パイプライン共通の作法、
    ComposeErrorとは意図的に区別する——後者は「入力が悪い」、前者は
    「環境/実装側の前提が崩れた」)。
    """
    work_root = os.path.abspath(work_root)
    output_name = (compose_job or {}).get("output_name")
    if not output_name or not str(output_name).strip():
        raise ComposeError("output_name is required")
    output_name = str(output_name).strip()

    assignments = normalize_assignments(compose_job)
    pak = resolve_palworld_pak(compose_job, palworld_pak)
    if not os.path.exists(pak):
        raise ComposeError(f"Palworld's pak was not found: {pak}")

    manifest = live_template._load_manifest()
    validate_assignments(assignments, manifest)

    # ライブラリエントリの実在確認(重複エントリIDは1回だけ解決)。
    entry_job_dirs = {}
    for entry_id in sorted(set(assignments.values())):
        entry_job_dirs[entry_id] = resolve_entry_job_dir(work_root, entry_id)

    log(f"[{TAG}] compose job: output_name={output_name!r} "
        f"assignments={len(assignments)} code(s), "
        f"{len(entry_job_dirs)} distinct library entrie(s)")

    mi_refs = vp_equipment_avatar._all_outfit_mi_references(pak, manifest)
    conflicts = vp_equipment_avatar.detect_shared_mi_conflicts(mi_refs, assignments)
    if conflicts:
        lines = [f"  - {mi_path}: equipment={codes} assigned_entries={entries}"
                 for mi_path, codes, entries in conflicts]
        raise ComposeError(
            "the following material(s) are shared by equipment items assigned "
            "to different library entries, which is not supported; assign the "
            "same library entry to every equipment item in each group and try "
            "composing again:\n" + "\n".join(lines))

    job_dir = job_dir_for(work_root, output_name)
    build_dir = os.path.join(job_dir, "build")
    work_dir = os.path.join(build_dir, "compose_work")
    if os.path.isdir(work_dir):
        shutil.rmtree(work_dir)
    os.makedirs(work_dir, exist_ok=True)
    overrides_dir = os.path.join(work_dir, "overrides")
    tmp_dir = os.path.join(work_dir, "tmp")
    os.makedirs(overrides_dir, exist_ok=True)
    os.makedirs(tmp_dir, exist_ok=True)

    # dev#1170 WP-2フォローアップ第2弾(Emissive残留修正): 統一MI源
    # (live_template.UNIFY_SRC_GAME_PATH)のバイトを1回だけ抽出しておく。
    # 以降の全MI(装備排他MI+共有ボディMI)クローンがこれを共通の土台として
    # 使う——「バニラ衣装が個別に持つEmissive Texture/Intensityの残留」を
    # 構造的に排除する(_rebuild_exclusive_mi/_clone_body_mi_for_entry
    # docstring参照)。
    unify_src_paths = live_template.unify_src_paths(pak, tmp_dir)
    # 同じ理由でNormal/ORM/Subsurfaceのflatten対象も統一MI源から1回だけ
    # 収集する(dev#165第2期のunify_src_normal_orm_flatten_targets()と
    # 同じ設計——全スロットが同一のUNIFY_SRC_GAME_PATH由来になったため、
    # flatten対象も全スロット共通)。
    flatten_targets_all = dict(live_template.unify_src_normal_orm_flatten_targets(pak, tmp_dir))
    # entry_id -> ops列(unify_base_ops + shadow_lift/unlitに応じたops)。
    # ライブラリエントリ数ぶんだけ計算すれば足りるため事前キャッシュする。
    entry_ops = {entry_id: _entry_mi_ops(entry_job_dirs[entry_id])
                 for entry_id in entry_job_dirs}

    n_sk = 0
    n_mi = 0
    n_tex = 0
    n_body_clone = 0
    processed_mi_paths = set()
    # (gender, entry_id) -> representative "_B" texture full path
    body_representative_tex = {}
    targets_rel = []
    # (gender, code) -> "Player/Outfit/<フォルダ名>"(folderはcode自体と
    # 一致するとは限らない、outfit_sk_folder_map()のdocstring参照)。
    sk_folder_map = outfit_sk_folder_map(manifest)

    for code, entry_id in sorted(assignments.items()):
        entry_job_dir = entry_job_dirs[entry_id]
        atlas_png = vp_avatar_library.resolve_atlas_path(entry_job_dir)
        if not atlas_png:
            raise ComposeError(
                f"library entry {entry_id!r} has no saved atlas; please "
                "convert this avatar again and try composing again")
        for gender in ("Female", "Male"):
            folder_rel = sk_folder_map.get((gender, code))
            if folder_rel is None:
                continue  # この性別にはこの装備コードが存在しない
            sk_base = f"SK_Player_{gender}_Outfit_{code}"
            sk_rel = f"{folder_rel}/{sk_base}"

            sk_paths = vp_avatar_library.resolve_sk_path(entry_job_dir, gender, code)
            if sk_paths is None:
                raise ComposeError(
                    f"library entry {entry_id!r} does not have a saved mesh "
                    f"for {gender}/{code}; please convert this avatar again "
                    "and try composing again")
            sk_ua_path, sk_ue_path = sk_paths
            with open(sk_ua_path, "rb") as f:
                sk_ua_bytes = f.read()
            with open(sk_ue_path, "rb") as f:
                sk_ue_bytes = f.read()

            # このSKが参照する非共有MIパス(このcodeのみが参照するもの)
            exclusive_mi_paths = sorted(
                p for p, codes in mi_refs.items()
                if code in codes
                and not any(p.endswith(suf) for suf in live_template._BODY_MI_SUFFIXES))
            first_tex_full = None
            for mi_path in exclusive_mi_paths:
                if mi_path not in processed_mi_paths:
                    new_ua, new_ue, tex_full, _flat = vp_equipment_avatar._rebuild_exclusive_mi(
                        pak, mi_path, tmp_dir, unify_src_paths, entry_ops[entry_id])
                    mi_rel = vp_equipment_avatar._game_path_to_rel(mi_path)
                    _write_bytes(overrides_dir, mi_rel + ".uasset", new_ua)
                    _write_bytes(overrides_dir, mi_rel + ".uexp", new_ue)
                    n_mi += 1
                    if tex_full:
                        tex_rel = vp_equipment_avatar._game_path_to_rel(tex_full)
                        tex_ua, tex_ue, tex_ubulk = vp_equipment_avatar._extract_vanilla(
                            pak, tex_rel, (".uasset", ".uexp", ".ubulk"))
                        if tex_ua is None or tex_ue is None:
                            raise ComposeError(
                                f"base texture not found in vanilla pak: {tex_full}")
                        ubulk_path = None
                        if tex_ubulk is not None:
                            ubulk_path = os.path.join(
                                tmp_dir, "src_" + tex_rel.replace("/", "_") + ".ubulk")
                            with open(ubulk_path, "wb") as f:
                                f.write(tex_ubulk)
                        template_uexp_path = os.path.join(
                            tmp_dir, "src_" + tex_rel.replace("/", "_") + ".uexp")
                        with open(template_uexp_path, "wb") as f:
                            f.write(tex_ue)
                        out_uexp_tmp = os.path.join(
                            tmp_dir, "out_" + tex_rel.replace("/", "_") + ".uexp")
                        out_ubulk_tmp = (os.path.join(
                            tmp_dir, "out_" + tex_rel.replace("/", "_") + ".ubulk")
                            if ubulk_path else None)
                        info = vp_texinject.inject_texture_file_vanilla_slot(
                            template_uexp_path, ubulk_path, atlas_png,
                            out_uexp_tmp, out_ubulk_tmp)
                        with open(out_uexp_tmp, "rb") as f:
                            new_tex_ue = f.read()
                        _write_bytes(overrides_dir, tex_rel + ".uasset", tex_ua)
                        _write_bytes(overrides_dir, tex_rel + ".uexp", new_tex_ue)
                        if info["used_ubulk"]:
                            with open(out_ubulk_tmp, "rb") as f:
                                new_tex_ubulk = f.read()
                            _write_bytes(overrides_dir, tex_rel + ".ubulk", new_tex_ubulk)
                        n_tex += 1
                        log(f"[{TAG}] {code}/{gender}: baked library entry "
                            f"{entry_id!r} atlas into {tex_rel} "
                            f"({info['pixel_format']} {info['size_x']}x"
                            f"{info['size_y']} psnr={info['psnr']:.1f}dB)")
                    processed_mi_paths.add(mi_path)
                if first_tex_full is None:
                    src_ua_only, = vp_equipment_avatar._extract_vanilla(
                        pak, vp_equipment_avatar._game_path_to_rel(mi_path), (".uasset",))
                    _tf = (vp_equipment_avatar.find_mi_base_texture_full_path(src_ua_only)
                           if src_ua_only else None)
                    if _tf:
                        first_tex_full = _tf

            # body-slot(共有MI)の代表テクスチャを記帳(このgender/entryで
            # まだ確定していなければ、最初に見つかった排他テクスチャを採用)
            body_key = (gender, entry_id)
            if first_tex_full and body_key not in body_representative_tex:
                body_representative_tex[body_key] = first_tex_full

            _write_bytes(overrides_dir, sk_rel + ".uasset", sk_ua_bytes)
            _write_bytes(overrides_dir, sk_rel + ".uexp", sk_ue_bytes)
            n_sk += 1
            targets_rel.append(sk_rel + ".uexp")

    # --- 共有ボディMI: クローン+SK importのretarget ---
    body_mi_paths = sorted(
        p for p in mi_refs
        if any(p.endswith(suf) for suf in live_template._BODY_MI_SUFFIXES))
    # (body_full, entry_id) -> new clone full path
    body_clone_path = {}
    for body_full in body_mi_paths:
        gender = "Male" if body_full.endswith("/MI_Player_Male_Body") else "Female"
        codes_here = mi_refs[body_full]
        mapped_here = {c: assignments[c] for c in codes_here if c in assignments}
        if not mapped_here:
            continue  # このボディMIを参照する装備はどれも対応表の対象外
        # dev#1170 WP-2差し戻し是正(Masterライターレビュー、2026-08-09):
        # 共有ボディMI(実測work\rd_1170_mesh\FINDINGS.md 1節: Female側は
        # 全58装備SKがMI_Player_Female_Bodyを参照)は本機能の核心用途
        # そのものが「装備ごとに別エントリを割る」なので、複数エントリへの
        # 分割割当を一律エラーにするのは誤り(旧実装はraiseしていた)。
        # 実効エントリごとに_clone_body_mi_for_entry()で**別々のクローン**を
        # 作る(_body_mi_clone_path()の出力先はavatar_key=_entry_key(entry_id)
        # で分岐するため、エントリごとに異なるパッケージパスになり衝突しない)。
        entries_here = sorted(set(mapped_here.values()))
        for entry_id in entries_here:
            body_key = (gender, entry_id)
            rep_tex = body_representative_tex.get(body_key)
            if not rep_tex:
                log(f"[{TAG}][WARN] no representative texture found for "
                    f"{gender}/{entry_id!r}; leaving the shared body slot "
                    f"({body_full}) untouched for this group (cosmetic-only limitation)")
                continue

            new_full, created = _clone_body_mi_for_entry(
                pak, body_full, gender, entry_id, rep_tex, unify_src_paths,
                entry_ops[entry_id], tmp_dir, overrides_dir, processed_mi_paths, log)
            body_clone_path[(body_full, entry_id)] = new_full
            if created:
                n_body_clone += 1

    # SKのimportをボディクローンへretarget(SKを既に書き出した後、byte列を
    # 直接読み直してパッチする)
    n_body_retarget = 0
    for (body_full, entry_id), new_full in body_clone_path.items():
        codes_for_entry = sorted(c for c, e in assignments.items() if e == entry_id)
        for code in codes_for_entry:
            if code not in mi_refs.get(body_full, set()):
                continue
            for gender in ("Female", "Male"):
                folder_rel = sk_folder_map.get((gender, code))
                if folder_rel is None:
                    continue
                sk_base = f"SK_Player_{gender}_Outfit_{code}"
                sk_rel = f"{folder_rel}/{sk_base}"
                sk_ua_path = os.path.join(overrides_dir, *sk_rel.split("/")) + ".uasset"
                if not os.path.exists(sk_ua_path):
                    continue
                with open(sk_ua_path, "rb") as f:
                    sk_ua_bytes = f.read()
                new_sk_bytes, n_hits, _retargeted = live_template.retarget_sk_body_mi_imports(
                    sk_ua_bytes, {body_full: new_full})
                if n_hits == 0:
                    # dev#1358(診断: work\rd_19_r2a2\diag\DIAG.md): 「このSKは
                    # 素体共有MIを参照していない」(正常)と「参照しては
                    # いるが想定外パス(例: equipment_filterビルド由来の
                    # AvatarSelect複製先)で無視された」(想定外)を区別する。
                    # 無音no-opにせず、可能ならその場で救済する。
                    n_hits, new_sk_bytes = _guard_and_rescue_body_mi_retarget(
                        sk_ua_bytes, body_full, new_full, sk_rel)
                if n_hits:
                    with open(sk_ua_path, "wb") as f:
                        f.write(new_sk_bytes)
                    n_body_retarget += n_hits

    if flatten_targets_all:
        live_template._flatten_normal_orm_textures(overrides_dir, pak, flatten_targets_all)

    log(f"[{TAG}] overrides built: sk={n_sk} mi={n_mi} tex={n_tex} "
        f"body_clone={n_body_clone} body_retarget={n_body_retarget} -> {overrides_dir}")

    # --- 頭は「無」を強制注入: dt_flag_head_hide等のラボの頭関連設定を
    # 一切参照しないため、equipment_filter/headequip_show/genders/
    # dt_flag_head_hideのいずれのキーも書かない最小jobを組む(モジュール
    # docstring参照。dev#1258時点の既定=常時空スタブが常に採用される)。
    template_job = {"job_dir": job_dir, "paths": {"palworld_pak": pak}}
    os.makedirs(job_dir, exist_ok=True)
    log(f"[{TAG}] building live template (shared cache, avatar-independent) ...")
    template_dir = live_template.build_live_template(template_job)

    # --- バニラ参照データ(preflightが読む。pure Pythonのpak解析のみ、
    # Blender実行は無い——extract_vanilla.extract_blender_stage()はpakから
    # SKバイトを直接抽出し数値化するだけで、Blender.exeは一切起動しない)
    log(f"[{TAG}] extracting vanilla reference data (shared cache) ...")
    extract_vanilla.run(template_job, extract_vanilla.STAGE_FULL)

    # --- Phase 3: pak化(build_pak_from_avatar.pyの部品を直接再利用) ---
    all_files = vp_pakwrite.collect_files(template_dir)
    final_files, _extra, n_overridden, n_added = (
        build_pak_from_avatar.apply_equip_avatar_extra_dir(all_files, overrides_dir))
    log(f"[{TAG}] overrides merged into template: {n_overridden} existing "
        f"entrie(s) overridden, {n_added} new entrie(s) added")
    common_mount_files = vp_pakwrite.to_common_mount_body_files(final_files)

    job_json_path = os.path.join(job_dir, "job.json")
    with open(job_json_path, "w", encoding="utf-8") as f:
        json.dump({
            "avatar_name": output_name,
            "paths": {"palworld_pak": pak},
            "preflight_nonblocking": bool(preflight_nonblocking),
        }, f, ensure_ascii=False, indent=2, sort_keys=True)

    # --- Phase 3.5: DT flagパッチ(頭部問題根治の既定動作、全ビルド常時適用) ---
    dt_files = build_pak_from_avatar._run_dt_patch(job_json_path, targets_rel, work_dir)
    common_mount_files = common_mount_files + dt_files

    os.makedirs(build_dir, exist_ok=True)
    out_pak = os.path.join(build_dir, f"{os.path.basename(job_dir)}_PlayerSwap_P.pak")
    pak_info = vp_pakwrite.build_pak(common_mount_files, out_pak,
                                      mount_point=vp_pakwrite.COMMON_MOUNT)
    log(f"[{TAG}] pak generated: {out_pak} "
        f"(entries={pak_info['n_entries']} size={pak_info['size']})")

    # --- 合成品専用のavatar_meta.json(実Blender出力ではない最小合法値、
    # モジュールdocstring参照) ---
    converted_dir = os.path.join(job_dir, "converted")
    os.makedirs(converted_dir, exist_ok=True)
    with open(os.path.join(converted_dir, "avatar_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"spec_version": "compose", "slots": {"composed": {"texture": None}}},
                   f, ensure_ascii=False, indent=2)

    # --- Phase 4: preflight ---
    preflight_status = "skipped"
    if not skip_preflight:
        cook_log = build_pak_from_avatar.DEFAULT_COOK_LOG
        log(f"[{TAG}] running preflight ...")
        result_path = build_pak_from_avatar.run_preflight_phase(
            job_json_path, out_pak, template_dir, cook_log, preflight_nonblocking)
        # blocking(既定): FAILならrun_preflight_phase自体がdie()で停止する
        # ため、ここへ到達する時点で常にPASS。nonblocking: 戻り値の
        # preflight_result.jsonを読んでステータスを転記する。
        if result_path is None:
            preflight_status = "blocking_pass"
        else:
            with open(result_path, encoding="utf-8") as f:
                preflight_status = "nonblocking:" + json.load(f).get("status", "UNKNOWN")

    # --- マニフェスト(multi_avatarフラグ)---
    # 書き場所は job_dir/library/manifest.json(= vp_avatar_library.
    # manifest_path(job_dir))そのもの——app_py\pak_manager.
    # entry_is_multi_avatar()がvp_avatar_library.read_manifest(job_dir)
    # 経由でこのファイルを読む契約(WP-3で既に確定・マージ済み、モジュール
    # docstring参照)。vp_avatar_library.save_library()自体は呼ばない
    # (SK群+アトラスの重いコピーをしない=合成品の中間物は保存しない=
    # 合成品を再度合成の入力にはできない、意図的な設計)。
    lib_dir = vp_avatar_library.library_dir(job_dir)
    os.makedirs(lib_dir, exist_ok=True)
    manifest_out = {
        "format_version": FORMAT_VERSION,
        "multi_avatar": True,
        "avatar_name": output_name,
        "output_name": output_name,
        "assignments": dict(sorted(assignments.items())),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
    }
    with open(vp_avatar_library.manifest_path(job_dir), "w", encoding="utf-8") as f:
        json.dump(manifest_out, f, ensure_ascii=False, indent=2, sort_keys=True)

    shutil.rmtree(tmp_dir, ignore_errors=True)

    result = {
        "job_dir": job_dir, "out_pak": out_pak, "pak_path": out_pak,
        "n_sk": n_sk, "n_mi": n_mi, "n_tex": n_tex, "n_body_clone": n_body_clone,
        "n_body_retarget": n_body_retarget, "preflight_status": preflight_status,
    }
    log(f"[{TAG}] compose complete: sk={n_sk} mi={n_mi} tex={n_tex} "
        f"body_clone={n_body_clone} body_retarget={n_body_retarget} "
        f"preflight={preflight_status} -> {out_pak}")
    return result


def compose(work_root, job, log=print):
    """WP-3(`app_py\\multi_avatar_pak_compose.py`)の`run_compose()`スタブが
    差し替え候補として明示的に挙げている呼び出し形
    (`vp_multi_avatar_compose.compose(work_root, job, log=...)`相当)に
    合わせた薄いラッパー。引数順序が`compose_avatar()`(compose_job,
    work_root)と逆(work_root, job)であること以外は同じ。
    将来のWP-3⇔WP-2結線WPがこの関数(またはCLIサブプロセス経由)のどちらを
    使ってもよいように両方を用意してある(CLI経由が`python_exe`引数の存在
    から見て有力——モジュールdocstring「CLI仕様」参照)。"""
    return compose_avatar(job, work_root, log=log)


# ------------------------------------------------------------------ CLI


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="dev#1170 WP-2: マルチアバターPAK合成エンジン。中間物"
                     "ライブラリ(vp_avatar_library.py)のエントリを対応表に"
                     "従って1つのpakへ組み立てる(convert.ps1・Blenderは"
                     "呼ばない、SK注入以降のみ)。")
    ap.add_argument("--job", required=True,
                     help='合成ジョブJSONのパス({"output_name": ..., '
                          '"assignments": {装備コード: ライブラリエントリID}})')
    ap.add_argument("--work-root", required=True,
                     help="ライブラリエントリの解決元・出力先"
                          "(GUIのwork\\ディレクトリと同じもの)")
    ap.add_argument("--palworld-pak", default=None,
                     help="省略時はpalworld_locate.find_palworld_pak()で自動発見")
    ap.add_argument("--preflight-nonblocking", action="store_true",
                     help="preflight FAILでも停止せず、pakを成果物として"
                          "完成させたまま結果を記録して継続する(dev#1230と同じ思想)")
    ap.add_argument("--skip-preflight", action="store_true",
                     help="preflightを実行しない(開発/テスト用途)")
    args = ap.parse_args(argv)

    with open(args.job, encoding="utf-8-sig") as f:
        compose_job = json.load(f)

    try:
        result = compose_avatar(
            compose_job, args.work_root, palworld_pak=args.palworld_pak,
            preflight_nonblocking=args.preflight_nonblocking,
            skip_preflight=args.skip_preflight)
    except ComposeError as e:
        print(f"[{TAG}][FATAL] {e}")
        sys.exit(1)

    print(f"[{TAG}] done: {result['out_pak']}")


if __name__ == "__main__":
    main()
