# -*- coding: utf-8 -*-
"""dev#1170 WP-1: マルチアバターPAK合成の基盤となる「中間物ライブラリ」。

オーナー確定仕様(2026-08-09対話、issue #1170):
  「変換」= VRM/prefab -> 中間物(pak組み立て直前の素材一式、そのときの
  変換設定が焼き込まれた状態)。通常変換のたびに中間物が自動保存される。
  ライブラリの実体 = メイン画面「作成済みMOD一覧」。一覧エントリと中間物は
  1:1の運命共同体(エントリ削除→中間物も削除/一覧にある限りGC等で勝手に
  消さない)。中間物保存より前の旧エントリは中間物なし(専用UIがグレー
  アウト表示する。本モジュールは「中間物の有無」を判別できるAPIを持つ)。

保存内容(現物確認: pipeline/py/vp_equipment_avatar.py の
ensure_avatar_build()+抽出部が「割当アバター」1体ぶんを組み立てる際に
完成build_dirから実際に取り出していたもの、過不足なく踏襲。同ファイルの
モジュールdocstring2〜3節・ensure_avatar_build()/variant_sk_paths()/
extract_avatar_atlas_png()参照):
  1. 装備SK群 — <job_dir>/build/noue_work/variant/Player/Outfit/
     SK_Player_{gender}_Outfit_{code}/ 配下の全ファイル(uasset/uexpに加え、
     同フォルダ内に実在する派生variant、例 _v02/_v03も含めフォルダごと)を
     そのままコピーする(vp_equipment_avatar.variant_sk_paths()が読む形と
     同じ配置で保存し直す)。
  2. アトラス — 完成pak(<avatar>_PlayerSwap_P.pak)のt00(注入済みアトラス)
     をデコードしPNG化したもの。vp_equipment_avatar.extract_avatar_atlas_png()
     をそのまま再利用する(パク座標系の扱いを重複実装しない)。
  3. manifest.json — 内訳・変換設定サマリ・作成日時・元アバター名・
     フォーマットversionを記録する(オーナー確定仕様どおり)。

一覧エントリ(app_py\\pak_manager.list_built_paks()が列挙する
<work_root>\\<entry_id>\\build\\*_PlayerSwap_P.pak)との対応: エントリID=
job_dirのフォルダ名(app_py\\pipeline_runner.write_job()のsanitize_name()が
決める名前と同じ語彙)。library/はjob_dir直下に置くため、
app_py\\pak_manager.delete_avatar_artifacts()のshutil.rmtree(job_dir)で
自動的に道連れ削除される(エントリ削除→中間物削除の連動、追加配線不要。
tests\\dev1170_avatar_library\\で負の対照込みに実証)。

④無退行の根拠: save_library()は失敗しても例外を外へ伝播させない(呼び出し
側convert_noue.pyは戻り値を見るだけで変換自体を継続する)。保存対象は
job_dir/library/という新規サブフォルダのみで、既存のbuild_pak_from_avatar.
main()が書くpak本体・job.json・job_snapshot.json等には一切触れない
(呼び出しはpakが完成した後に行う)。

app_py側とpipeline側のどちらからも使える置き場について: 本モジュールは
pipeline/py/に置くが、app_py\\shared_cache_gc.pyが既に確立した「app_py側は
sys.path.insert(0, <root>/pipeline/py)してから通常importする」パターン
(dev#45b移設)をapp_py\\pak_manager.pyでも踏襲する。ロジックの実体は
本モジュール1箇所のみで、GUI層はそれを再エクスポートするだけに留める。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import live_template  # noqa: E402 (dev#1358: AvatarSelect参照の正規化に使う)
import vp_core as core  # noqa: E402
import vp_equipment_avatar  # noqa: E402
import vp_equipment_filter  # noqa: E402

TAG = "vp_avatar_library"

# manifest.jsonのフォーマットversion。内容(キー構成)を破壊的に変える場合は
# 上げる(専用UI側は未知のversionを「読めない=中間物無し扱い」にフォール
# バックできるよう、versionを必ず読む契約)。
FORMAT_VERSION = 1

LIBRARY_DIRNAME = "library"
MANIFEST_FILENAME = "manifest.json"
ATLAS_FILENAME = "atlas_t00.png"
# job_dir/library/ の下でSKツリーを再現するサブパス。
# vp_equipment_avatar.variant_sk_paths()が読む
# "noue_work/variant/Player/Outfit/<base>/<base>.{uasset,uexp}" と同じ
# "Player/Outfit/<base>/..." 構造をそのまま踏襲する(呼び出し側が2つの
# 別ロジックを持たずに済むよう、意図的に相似形にしてある)。
SK_SUBPATH = os.path.join("sk", "Player", "Outfit")


class AvatarLibraryError(RuntimeError):
    """中間物ライブラリ処理中の想定内エラー。"""


# --------------------------------------------------------------- path解決


def library_dir(job_dir: str) -> str:
    """job_dir配下の中間物ライブラリのディレクトリパス(存在確認はしない)。"""
    return os.path.join(job_dir, LIBRARY_DIRNAME)


def manifest_path(job_dir: str) -> str:
    return os.path.join(library_dir(job_dir), MANIFEST_FILENAME)


def has_library(job_dir: str) -> bool:
    """job_dir(=一覧の1エントリ)に中間物が保存済みか。manifest.jsonの存在
    だけで判定する(中間物保存より前の旧エントリはFalse — オーナー確定仕様)。
    """
    return os.path.isfile(manifest_path(job_dir))


def read_manifest(job_dir: str):
    """manifest.jsonをdictとして返す。無ければ/壊れていればNone(呼び出し側
    の専用UIが例外に落ちずグレーアウト表示へフォールバックできるようにする)。
    """
    p = manifest_path(job_dir)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def resolve_sk_path(job_dir: str, gender: str, code: str):
    """保存済みSKの(uasset, uexp)絶対パスを返す。無ければNone。

    dev#1170 WP-2(合成エンジン)の実pak検証で判明した落とし穴の是正:
    バニラのOutfit SKは、同一の"基準"フォルダ(例
    SK_Player_Female_Outfit_Ancient001/)の中に複数の異なる装備コード
    (基準そのものAncient001、および"バリアント"Ancient001_v02/_v03/_v04等)
    がファイルとして同居する実物パターンが多数ある(noue_work/variant側も
    テンプレート側と同じフォルダ構造を保つため、save_library()の
    shutil.copytree()はこれらを丸ごと正しくコピー済み——欠けていたのは
    「コードからファイルへの経路解決」の側だけ)。フォルダ名がcodeと一致
    する保証は無いため、"SK_Player_{gender}_Outfit_{code}.uasset/.uexp"
    という**ファイル名**をSK_SUBPATH配下の全フォルダから探す(フォルダ名は
    問わない)。"""
    base = f"SK_Player_{gender}_Outfit_{code}"
    root = os.path.join(library_dir(job_dir), SK_SUBPATH)
    if not os.path.isdir(root):
        return None
    for entry in sorted(os.listdir(root)):
        d = os.path.join(root, entry)
        if not os.path.isdir(d):
            continue
        ua = os.path.join(d, base + ".uasset")
        ue = os.path.join(d, base + ".uexp")
        if os.path.exists(ua) and os.path.exists(ue):
            return ua, ue
    return None


def resolve_atlas_path(job_dir: str):
    """保存済みアトラスPNGの絶対パスを返す。無ければNone。"""
    p = os.path.join(library_dir(job_dir), ATLAS_FILENAME)
    return p if os.path.isfile(p) else None


def resolve_job_dir(work_root: str, entry_id: str):
    """エントリID(=work_root直下のフォルダ名)からjob_dirの絶対パスを解決
    する。誤ったIDでの誤爆(パストラバーサル等)を避けるため、区切り文字を
    含むIDや、実在しないディレクトリはNoneを返す。"""
    if not entry_id or os.sep in entry_id or (os.altsep and os.altsep in entry_id):
        return None
    if entry_id in (os.curdir, os.pardir):
        return None
    job_dir = os.path.join(work_root, entry_id)
    return job_dir if os.path.isdir(job_dir) else None


def resolve_library_dir(work_root: str, entry_id: str):
    """エントリIDから中間物ライブラリのディレクトリパスを解決する。
    job_dir自体が存在しなければNone(中間物の有無は別途has_library()で
    判定する——本関数はentry_idの妥当性チェックのみを担う)。"""
    job_dir = resolve_job_dir(work_root, entry_id)
    return library_dir(job_dir) if job_dir is not None else None


# --------------------------------------------------------------- 保存


def _dir_size_bytes(root: str) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return total


def _scan_outfit_codes(variant_outfit_dir: str):
    """<job_dir>/build/noue_work/variant/Player/Outfit配下から
    (gender, code, フォルダの絶対パス)の一覧を作る。

    dev#1170 WP-2の実pak検証で判明: 同一フォルダ内に複数の異なる装備コード
    (バリアント、例SK_Player_Female_Outfit_Ancient001/配下に基準
    Ancient001本体+_v02/_v03/_v04がファイルとして同居)が存在するため、
    **フォルダ名ではなくフォルダ内の各.uassetファイル**からコードを判定
    する(vp_equipment_filter.equipment_code()と同じ語彙判定、dev#165と
    同一の装備コード体系、二重実装を避ける)。戻り値には同一フォルダに
    属する複数コードが含まれうる(呼び出し側=_save_library_impl()が
    フォルダ単位の重複コピーを避ける)。"""
    out = []
    if not os.path.isdir(variant_outfit_dir):
        return out
    for entry in sorted(os.listdir(variant_outfit_dir)):
        d = os.path.join(variant_outfit_dir, entry)
        if not os.path.isdir(d):
            continue
        seen_codes = set()
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".uasset"):
                continue
            base = fn[:-len(".uasset")]
            code = vp_equipment_filter.equipment_code(base)
            if code is None or code in seen_codes:
                continue
            seen_codes.add(code)
            gender = "Male" if base.startswith("SK_Player_Male_Outfit_") else "Female"
            out.append((gender, code, d))
    return out


def _settings_summary(job: dict) -> dict:
    """変換設定サマリ(manifest.json用)。job.jsonの生値をそのまま持ち回すと
    パス等の環境依存値・機微値(paths等)が混入するため、後続WP(専用UI・
    合成エンジン)が使う想定の設定項目だけを明示的に抜粋する。"""
    return {
        "genders": sorted(job.get("genders") or ["Male", "Female"]),
        "merge_fingers": bool(job.get("merge_fingers", False)),
        "unlit": bool(job.get("unlit", False)),
        "force_two_sided": bool(job.get("force_two_sided", True)),
        "shadow_lift": job.get("shadow_lift", 0.7),
        "shoulder_offset_deg": job.get("shoulder_offset_deg", 0.0),
        "uniform_scale": job.get("uniform_scale", 1.0),
        "engine_mode": job.get("engine_mode", "noue"),
        "equipment_filter": sorted(job.get("equipment_filter") or []),
    }


# --------------------------------------------------------- dev#1358 正規化


def _normalize_avatar_select_body_mi_refs(uasset_bytes):
    """dev#1358(診断: work\\rd_19_r2a2\\diag\\DIAG.md): equipment_filter有効
    ビルドが焼き込む共有素体MIの複製先参照(live_template.
    _f3a_avatar_select_body_mi()、`.../Body/{Gender}/AvatarSelect/
    MI_Player_{Gender}_Body`)を、保存前にバニラの素のパス
    (`.../Body/{Gender}/MI_Player_{Gender}_Body`)へ書き戻す。

    中間物ライブラリは「どのビルド文脈でも再利用できるポータブルな状態」で
    保存されるべきという設計原則(compose機能の前提そのもの、
    vp_avatar_compose.retarget_sk_body_mi_imports呼び出しはバニラパスの
    完全一致でしか対象を見つけられない)に合わせる。

    対象参照が無い(素体MIを参照しない/既にバニラパス)場合、または入力が
    実uasset構造としてパース不能(壊れている、あるいはこのプロジェクトの
    単体テストが使う合成ダミーバイト列)な場合は、**無改変のまま**
    `(uasset_bytes, 0)` を返す——保存経路全体を壊さないための最善努力処理
    (この関数はあくまで正規化の"根治"側であり、実際の安全網は合成側の
    ガード、vp_avatar_compose._guard_and_rescue_body_mi_retarget()が担う)。

    戻り値: (new_uasset_bytes, n_normalized)。"""
    try:
        found = live_template.find_sk_body_mi_package_imports(uasset_bytes)
    except Exception:
        return uasset_bytes, 0
    marker_folder = f"/{live_template._AVATAR_BODY_MI_SUBFOLDER}/"
    path_map = {}
    for full_path in found:
        leaf = full_path.rsplit("/", 1)[-1]
        select_suffix = marker_folder + leaf
        if not full_path.endswith(select_suffix):
            continue  # 既にバニラパス(正規化不要)
        vanilla = full_path[:-len(select_suffix)] + "/" + leaf
        path_map[full_path] = vanilla
    if not path_map:
        return uasset_bytes, 0
    try:
        new_bytes, n_hits, _retargeted = live_template.retarget_sk_body_mi_imports(
            uasset_bytes, path_map)
    except Exception:
        return uasset_bytes, 0
    return new_bytes, n_hits


def _normalize_dir_avatar_select_refs(dst_dir, log):
    """dst_dir配下(1つの装備コードフォルダ、バリアント含む)の全.uassetを
    走査し、_normalize_avatar_select_body_mi_refs()を適用して必要なら
    上書きする。戻り値: 正規化した参照の総数。"""
    n = 0
    for fn in sorted(os.listdir(dst_dir)):
        if not fn.endswith(".uasset"):
            continue
        p = os.path.join(dst_dir, fn)
        with open(p, "rb") as f:
            data = f.read()
        new_data, n_hits = _normalize_avatar_select_body_mi_refs(data)
        if n_hits:
            with open(p, "wb") as f:
                f.write(new_data)
            n += n_hits
            log(f"[{TAG}] normalized {n_hits} AvatarSelect body-MI "
                f"reference(s) in {fn} before saving to library (dev#1358)")
    return n


def save_library(job: dict, job_dir: str, out_pak: str, work_dir: str, log=print):
    """通常のnoue変換完了時に呼ぶ(convert_noue.py、build_pak_from_avatar.
    main()完了=pak完成の直後)。job_dir/library/ へ中間物一式を保存する。

    失敗しても例外を投げない(④無退行の根拠: 保存失敗は警告に留め変換自体は
    成功させる)。戻り値: 成功時はmanifest dict、失敗時はNone。
    """
    try:
        return _save_library_impl(job, job_dir, out_pak, work_dir, log=log)
    except Exception as e:  # noqa: BLE001 (④の唯一の根拠: 変換の成功を妨げない)
        log(f"[{TAG}][WARN] failed to save intermediate library (the build itself "
            f"is unaffected): {e}")
        return None


def _save_library_impl(job: dict, job_dir: str, out_pak: str, work_dir: str, log):
    variant_outfit_dir = os.path.join(work_dir, "variant", "Player", "Outfit")
    codes = _scan_outfit_codes(variant_outfit_dir)

    lib_dir = library_dir(job_dir)
    tmp_dir = lib_dir.rstrip("\\/") + "_tmp"
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir, exist_ok=True)

    sk_root = os.path.join(tmp_dir, SK_SUBPATH)
    os.makedirs(sk_root, exist_ok=True)
    n_files = 0
    n_normalized = 0
    included = []
    copied_dirs = set()
    for gender, code, src_dir in codes:
        # dev#1170 WP-2是正: 同一フォルダが複数コード(バリアント)を持つ
        # ことがあるため、コピーはフォルダ単位で1回だけ行う(2回目以降の
        # shutil.copytree()は宛先が既に存在してFileExistsErrorになる)。
        # includedへの記帳は全コード分そのまま行う(manifest.jsonの
        # contents.skが実際に保存されている全コードを正しく反映するため)。
        if src_dir not in copied_dirs:
            dst_dir = os.path.join(sk_root, os.path.basename(src_dir))
            shutil.copytree(src_dir, dst_dir)
            n_files += len(os.listdir(dst_dir))
            copied_dirs.add(src_dir)
            # dev#1358: equipment_filterビルド由来のAvatarSelect参照を
            # バニラパスへ正規化してから保存する(コピー直後、まだ他の
            # コードから再利用されるより前)。
            n_normalized += _normalize_dir_avatar_select_refs(dst_dir, log)
        included.append({"gender": gender, "code": code})

    atlas_tmp = os.path.join(tmp_dir, ATLAS_FILENAME)
    vp_equipment_avatar.extract_avatar_atlas_png(out_pak, atlas_tmp)

    avatar_path = job.get("vrm_path") or ""
    source_sha256 = None
    if avatar_path and os.path.isfile(avatar_path):
        try:
            source_sha256 = core.sha256_file(avatar_path)
        except OSError:
            source_sha256 = None

    manifest = {
        "format_version": FORMAT_VERSION,
        "entry_id": os.path.basename(job_dir.rstrip("\\/")),
        "avatar_name": job.get("avatar_name", "Avatar"),
        "source_avatar_path": avatar_path or None,
        "source_avatar_sha256": source_sha256,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "settings": _settings_summary(job),
        "contents": {
            "atlas": ATLAS_FILENAME,
            "sk": included,
        },
    }
    with open(os.path.join(tmp_dir, MANIFEST_FILENAME), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)

    if os.path.isdir(lib_dir):
        shutil.rmtree(lib_dir)
    os.replace(tmp_dir, lib_dir)

    size_bytes = _dir_size_bytes(lib_dir)
    log(f"[{TAG}] intermediate library saved: {lib_dir} "
        f"(sk_codes={len(included)} sk_files={n_files} size={size_bytes} bytes "
        f"avatarselect_normalized={n_normalized})")
    return manifest


# --------------------------------------------------------------- 列挙


def list_entries(work_root: str):
    """work_root配下の全エントリ(=メイン画面「作成済みMOD一覧」の1行)を
    列挙する。app_py\\pak_manager.list_built_paks()と同じ発見基準
    (<work_root>/<entry_id>/build/*_PlayerSwap_P.pak)に、中間物の有無・
    設定サマリ・作成日時を足したもの。後続WP(専用UI・合成エンジン)は
    本関数だけを使えばよい——app_py/pipeline両方から
    pipeline/py/vp_avatar_library.pyを直接importできる(このモジュール自体は
    tkinter/i18nに依存しない)。

    戻り値: [{"entry_id", "avatar_name", "pak_path", "job_dir",
              "has_library", "created_at", "settings"}, ...]、entry_id昇順。
    """
    result = []
    if not os.path.isdir(work_root):
        return result
    for entry in sorted(os.listdir(work_root)):
        job_dir = os.path.join(work_root, entry)
        build_dir = os.path.join(job_dir, "build")
        if not os.path.isdir(build_dir):
            continue
        pak_path = None
        for f in sorted(os.listdir(build_dir)):
            if f.endswith("_PlayerSwap_P.pak"):
                pak_path = os.path.join(build_dir, f)
                break
        if pak_path is None:
            continue
        manifest = read_manifest(job_dir)
        result.append({
            "entry_id": entry,
            "avatar_name": (manifest or {}).get("avatar_name", entry),
            "pak_path": pak_path,
            "job_dir": job_dir,
            "has_library": manifest is not None,
            "created_at": (manifest or {}).get("created_at"),
            "settings": (manifest or {}).get("settings"),
        })
    return result
