# -*- coding: utf-8 -*-
"""dev#1170: 装備別上書き注入の共通プリミティブ集。

**2026-08-09 WP-2(合成エンジン)での役割変更**: 本モジュールはWP-A初版
(job.jsonの`equipment_avatar_map`キー+`ensure_avatar_build()`によるconvert.ps1
再帰サブビルド)のドライバ実装だった。オーナー確定仕様(issue #1170、
2026-08-09対話)により「合成」は**中間物ライブラリ(vp_avatar_library.py、
WP-1)からのSK注入+テクスチャ+MI差し替えだけで1 pakを作る」設計に一本化され、
job.jsonの`equipment_avatar_map`キー・その場での再変換(ensure_avatar_build)
という概念自体が廃止された(消費側=convert_noue.pyの配線も削除済み)。

本モジュールはそのドライバ(`build_equip_avatar_overrides()`、
`normalize_equipment_avatar_map()`等)を落とし、**装備コード単位のMI発見・
共有MI衝突検出・排他MI再構築・共有ボディMIクローンといった、上書き注入の
低レベル部品だけを残す**。これらは`pipeline\\py\\vp_avatar_compose.py`
(dev#1170 WP-2、合成エンジン本体)が「割当アバターの完成pak」の代わりに
「ライブラリエントリの保存済みSK+アトラス」を入力として直接呼び出す。

方式の正本: work\\rd_1170_mesh\\FINDINGS.md(実証実験、実機Phase B成功済み)。
新規名アセットは使わず「バニラに実在するパス」への上書きだけで組む
(work\\rd_1170_tex\\FINDINGS.md Phase B診断: 新規名テクスチャアセットは
静的に完璧でも実機でロードされない、が確定した後の方式転換)。

共有MI制約(オーナー裁定2026-08-09): 同一MIパスを参照する複数の装備コードが
異なる割当先(旧: アバターファイル、新: ライブラリエントリ)へ割り当てられた
場合はビルドエラーで停止する(回避設計はしない)。`detect_shared_mi_conflicts()`
は割当先を不透明な値として扱う(パス/エントリIDのどちらでも動く)。
"""
import hashlib
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import live_template  # noqa: E402
import pak_live_extract  # noqa: E402
import vp_core as core  # noqa: E402
import vp_equipment_filter  # noqa: E402
import vp_pakwrite  # noqa: E402
import vp_tex  # noqa: E402
import vp_texinject  # noqa: E402

TAG = "vp_equipment_avatar"

# 共有ボディMIのクローン先サブフォルダ接頭辞。dev#165のF3a(AvatarSelect)とは
# 別名にして名前空間を分離する(equipment_filter/合成エンジンが同一ビルドで
# 併用されても衝突しない)。WP-2合成エンジンも同じ接頭辞をそのまま使う
# (preflight_pak.pyのG2/G3ホワイトリスト正規表現はこの接頭辞を前提にして
# おり、変更不要)。
_BODY_MI_CLONE_SUBFOLDER_PREFIX = "EquipAvatarMap_"

# detect_shared_mi_conflicts()が「未割当」を表すのに使う内部センチネル。
DEFAULT_AVATAR_KEY = "__default__"


class EquipmentAvatarError(RuntimeError):
    """装備別上書き注入処理中の想定内エラー(ビルド停止・明確な案内)。"""


def _avatar_key(avatar_path):
    """アバターパスから安定した短いhex識別子を作る(クローン先パッケージ
    パスの名前空間分離、ログ表示用)。"""
    return hashlib.sha1(os.path.abspath(avatar_path).encode("utf-8")).hexdigest()[:10]


def extract_avatar_atlas_png(pak_path, out_png_path):
    """完成pakのt00.uexp(注入済みアトラス)をDXTデコードしPNGとして保存する
    (実証済み手法、work\\rd_1170_mesh\\FINDINGS.md 3節: 「正しい注入元は
    アバター自身の完成pak自身のt00.uexp」)。既に存在すればスキップする。

    pak_pathは**このパイプラインが作った完成MODパク**(build_pak_from_avatar.py、
    COMMON_MOUNT配線)であり、バニラPalworld本体パクとはpakエントリの座標系が
    異なる(dev#1198 WP-B5a: DEFAULT_MOUNT(バニラ相当、live_template.PAK_PREFIX
    が前提)== COMMON_MOUNT + vp_pakwrite.BODY_PREFIX。MODパクのエントリは
    BODY_PREFIXだけを前置した座標系で格納されている)。live_template.PAK_PREFIX
    (バニラパク抽出専用)を誤用しないこと。"""
    if os.path.exists(out_png_path):
        return out_png_path
    rel = "Player/ModelMaterials/MainShader/t00"
    key_ue = vp_pakwrite.BODY_PREFIX + rel + ".uexp"
    got = pak_live_extract.extract_files(pak_path, [key_ue])
    if key_ue not in got:
        raise EquipmentAvatarError(
            f"t00 texture not found in {pak_path}")
    layout = core.parse_texture2d(got[key_ue])
    mip0 = layout["mips"][0]
    blob = got[key_ue][mip0["offset"]:mip0["offset"] + mip0["size"]]
    rgba = vp_tex.decode_dxt(blob, layout["size_x"], layout["size_y"], layout["pixel_format"])
    os.makedirs(os.path.dirname(out_png_path) or ".", exist_ok=True)
    vp_tex.encode_png(out_png_path, rgba)
    return out_png_path


# ------------------------------------------------------------- MI discovery


def _all_outfit_mi_references(pak, manifest):
    """全Outfit SK(バニラ状態、パクから直接抽出。テンプレート/共有キャッシュに
    一切依存しない読み取り専用スキャン)から、{mi_full_path: {装備コード,...}}
    を構築する。live_template.collect_unified_mi_targets()と同じ発見ロジック
    (find_outfit_material_paths_all)を装備コード単位で記帳するだけの
    読み取り専用の再利用。"""
    outfit_uassets = sorted(
        rel for rel in manifest["vanilla"]
        if rel.startswith("Player/Outfit/") and rel.endswith(".uasset"))
    result = {}
    tmp_dir = tempfile.mkdtemp(prefix="d2p_equip_avatar_scan_")
    try:
        for rel in outfit_uassets:
            base = os.path.basename(rel)[:-len(".uasset")]
            code = vp_equipment_filter.equipment_code(base)
            if code is None:
                continue
            keys = [live_template.PAK_PREFIX + rel,
                    live_template.PAK_PREFIX + rel[:-len(".uasset")] + ".uexp"]
            got = pak_live_extract.extract_files(pak, keys)
            if keys[0] not in got or keys[1] not in got:
                continue
            ua_path = os.path.join(tmp_dir, "scan.uasset")
            ue_path = os.path.join(tmp_dir, "scan.uexp")
            with open(ua_path, "wb") as f:
                f.write(got[keys[0]])
            with open(ue_path, "wb") as f:
                f.write(got[keys[1]])
            try:
                paths = live_template.find_outfit_material_paths_all(ua_path, ue_path, limit=2)
            except live_template._OutfitMaterialPatchError:
                continue
            for p in paths:
                result.setdefault(p, set()).add(code)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return result


def detect_shared_mi_conflicts(mi_refs, code_assignment):
    """共有MI制約(オーナー裁定2026-08-09): 同一MIパスを参照する装備コード群が
    異なる「実効割当先」(code_assignmentの値、または未割当=DEFAULT_AVATAR_KEY)
    へ分かれている場合、そのMIパスを衝突として返す。共有ボディMI
    (live_template._BODY_MI_SUFFIXES)はクローン+retarget機構で個別に解決
    するため、この衝突判定の対象外(スキップ)。

    code_assignmentは{装備コード: 割当先}の辞書で、値は不透明な識別子として
    扱う(WP-A初版時代のアバターファイルパス、WP-2合成エンジンのライブラリ
    エントリIDのどちらでも動く——比較は等価性のみで、パス正規化等は一切
    行わない。呼び出し側が値の意味を決める)。
    戻り値: [(mi_path, [装備コード,...], [実効割当先,...]), ...]"""
    conflicts = []
    for mi_path, codes in sorted(mi_refs.items()):
        if any(mi_path.endswith(suf) for suf in live_template._BODY_MI_SUFFIXES):
            continue
        effective = {code_assignment.get(c, DEFAULT_AVATAR_KEY) for c in codes}
        if len(effective) > 1:
            conflicts.append((mi_path, sorted(codes), sorted(effective)))
    return conflicts


def find_mi_base_texture_full_path(uasset_bytes):
    """MIのBase Texture importが指す完全パッケージパスを読み取り専用で返す
    (live_template._patch_mi_base_texture()と同じ探索基準: ObjectNameが
    "_B"で終わるTexture2D importのうち最小オフセットのもの)。
    見つからなければNone。"""
    h = live_template._parse_header_with_offsets(uasset_bytes)
    names, names_end = live_template._read_name_table(uasset_bytes, h.name_offset, h.name_count)
    if names_end != h.import_offset:
        return None
    off = h.import_offset
    imports = []
    for _ in range(h.import_count):
        imp, off = live_template._parse_import(uasset_bytes, off)
        imports.append(imp)
    base_tex_i = None
    for i, imp in enumerate(imports):
        cn = names[imp["class_name_idx"]] if 0 <= imp["class_name_idx"] < len(names) else None
        on = names[imp["object_name_idx"]] if 0 <= imp["object_name_idx"] < len(names) else None
        if cn == "Texture2D" and on is not None and on.endswith("_B"):
            base_tex_i = i
            break
    if base_tex_i is None:
        return None
    outer_fpi = imports[base_tex_i]["outer_index"]
    if outer_fpi >= 0:
        return None
    oi = -outer_fpi - 1
    if not (0 <= oi < len(imports)):
        return None
    pkg_imp = imports[oi]
    if names[pkg_imp["class_name_idx"]] != "Package":
        return None
    return names[pkg_imp["object_name_idx"]]


def _game_path_to_rel(full_path):
    prefix = "/Game/Pal/Model/Character/"
    if not full_path.startswith(prefix):
        raise EquipmentAvatarError(f"unexpected package path (prefix mismatch): {full_path}")
    return full_path[len(prefix):]


def _extract_vanilla(pak, rel_base, exts):
    keys = [live_template.PAK_PREFIX + rel_base + e for e in exts]
    got = pak_live_extract.extract_files(pak, keys)
    return [got.get(k) for k in keys]


# -------------------------------------------------------------- MI rebuild


def _rebuild_exclusive_mi(pak, mi_full_path, tmp_dir, unify_src_paths, ops):
    """非共有(排他)MIを再構築する。

    dev#1170 WP-2フォローアップ(2026-08-10、実機報告: albedoは正しいが
    装備によって異なる模様が追加で描かれる=Emissive疑い): 旧実装は
    「このMI自身のバニラバイト」+ unify_base_ops(Specular=0のみ)だけを
    適用していたため、バニラ衣装が個別に持つ"Emissive Texture"(装飾・
    紋様のデカール、例T_Player_Female_Outfit_Bronze001_v01_M01_EM)と
    "Emissive Texture Intensity"(実測4.0〜10.0、非ゼロが大半)がそのまま
    残留し、アバターのBase Textureの上にバニラの模様が加算描画されていた
    (work\\rd_1170_emission\\FINDINGS.md参照、実データ77件中62件で残留を
    確認)。single-avatar通常品はこの問題を「統一MI」機構
    (live_template.UNIFY_SRC_GAME_PATH由来の**1種類のバニラMI**だけを
    全スロットへ複製する、_unify_slot_materials()/build_shadow_mi_overrides()
    参照)で構造的に回避している——本関数もそれと同じ土台(unify_src_paths、
    呼び出し側が1回だけ抽出してtmp_dirへ書き出したUNIFY_SRC_GAME_PATHの
    バイト)を使うことで同じ回避を得る。UNIFY_SRC_GAME_PATH自身は
    Emissive Texture/Intensityを持たない(実測確認済み)ため、
    opsが空(shadow_lift=0/unlit=False)なら合成品のMIにEmissiveパラメータは
    一切出現しない(通常品のshadow_lift=0ケースと同じ構造的保証)。

    Base Textureの向き先(target)は、このMI自身のバニラバイトから読み取った
    元々の"_B"パスをそのまま使う(このMI固有のBase Textureファイルへ
    アトラスを焼き込む、呼び出し側compose_avatar()の既存の注入経路は不変)。
    ops(unify_base_ops()常時 + shadow_lift/unlitに応じたunify_shadow_ops())
    は呼び出し側が該当ライブラリエントリの保存設定から計算して渡す。

    dev#1321(2026-08-10、実機報告: 装備によってはマテリアルエラー):
    build_unified_mi_variant_for_target()が返すバイトは、SRC
    (live_template.UNIFY_SRC_GAME_PATH = バニラ衣装OldCloth001)の
    FPackageFileSummary.PackageName/export[0].ObjectName(=このMI自身の
    「自己申告の所属パッケージパス」)をそのまま引き継いでいる——Base
    Texture importの向け先(何を参照するか)だけを付け替える処理であり、
    アセット自身の自己同一性は変更しない。ところがcompose_avatar()は
    この戻り値をmi_full_path(このMI**自身**の本来のバニラパス、例えば
    ".../Iron001/v01/MI_Player_Female_Outfit_Iron001_v01_M01")の位置へ
    書き込む——つまり全77件の排他MIクローンが、実際のマウント先とは
    無関係に「自分はOldCloth001_v01_M02である」と自己申告したまま
    pakに収録されていた(実測work\\rd_1321\\check_selfid.py、負の対照:
    同じ問題を修正済みの共有素体MIクローン
    _clone_body_mi_for_entry()と比較し、そちらは_clone_mvp_mic_as()で
    自己同一性をtarget側へ改名しているため一致することを確認済み)。
    77件が同一の(PackageName, ObjectName)を自己申告して衝突するため、
    エンジンのオブジェクト解決に依存する形でマテリアルエラーが起きうる
    (装備の見た目・Emissive有無とは無関係の構造的欠陥)。

    live_template._clone_mvp_mic_as()(単体アバター通常品の
    write_unified_mis()、および本ファイルの_clone_body_mi_for_entry()が
    既に使っている、実績のある機構)で、このMI自身の本来のパス
    (mi_full_path)へ自己同一性を改名してから返す。

    戻り値: (new_uasset, new_uexp, base_texture_full_path, flatten_targets)。
    flatten_targetsは常に{}(全スロットが同一のUNIFY_SRC_GAME_PATH由来と
    なったため、Normal/ORM/Subsurfaceのflatten対象も全スロット共通—
    呼び出し側がlive_template.unify_src_normal_orm_flatten_targets()を
    compose_avatar()内で1回だけ呼んで扱う。dev#165第2期の通常品と同じ
    設計)。"""
    rel = _game_path_to_rel(mi_full_path)
    (ua,) = _extract_vanilla(pak, rel, (".uasset",))
    if ua is None:
        raise EquipmentAvatarError(f"MI not found in vanilla pak: {mi_full_path}")

    base_tex = find_mi_base_texture_full_path(ua)
    if base_tex is None:
        raise EquipmentAvatarError(
            f"Base Texture import not found in vanilla MI: {mi_full_path}")
    tex_short = base_tex.rsplit("/", 1)[-1]

    src_ua_path, src_ue_path = unify_src_paths
    safe = rel.replace("/", "_")
    new_ua, new_ue, _oplog = live_template.build_unified_mi_variant_for_target(
        src_ua_path, src_ue_path, base_tex, tex_short, ops, tmp_dir, tag=safe)
    # dev#1321: SRC由来の自己同一性(PackageName/export[0].ObjectName)を
    # このMI自身の本来のパスへ改名する(_clone_body_mi_for_entry()と同じ
    # 機構、上のdocstring参照)。
    new_ua, new_ue = live_template._clone_mvp_mic_as(new_ua, new_ue, mi_full_path)

    return new_ua, new_ue, base_tex, {}


def _body_mi_clone_path(old_full_path, avatar_key):
    if not any(old_full_path.endswith(suf) for suf in live_template._BODY_MI_SUFFIXES):
        raise EquipmentAvatarError(f"not a body MI path: {old_full_path}")
    parent, leaf = old_full_path.rsplit("/", 1)
    return f"{parent}/{_BODY_MI_CLONE_SUBFOLDER_PREFIX}{avatar_key}/{leaf}"
