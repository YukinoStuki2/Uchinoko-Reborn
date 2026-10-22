# -*- coding: utf-8 -*-
r"""高速リパック: 中間成果を再利用して pak だけ作り直す(開発ループ専用)。

出典: work\u50_unify\fast_repack.py(2026-07-25 の影スイープで実際に使われた試作)を
devtools へ昇格し、作業域をハードコードせず任意の job から使えるようにしたもの。
2026-07-26: 本ツールは GUI「影のみ更新(高速)」の実行時に呼ばれる出荷物側の
コンポーネントであり、開発専用ではなくなった(devtools\ は非公開のため、
開発専用ツール以外は置けない)。そのため devtools\ から pipeline\py\ へ移設した。
pipeline\ 配下のソースは一切変更しない(import して使うだけ)という制約自体は
変わっていない — 本ファイル自身が pipeline\py\ の一員になっただけ。

■ 何をするか
フル変換(pipeline\cli\convert.ps1)のうち、pak 書き出し(Phase 3)だけを再実行する。
Blender 工程(Phase 1)と衣装SK 60体への実アバター注入(Phase 2)は結果が
    <job_dir>\build\noue_work\variant\
に残っており、マテリアル(MI)のパラメータだけを振るスイープでは一切変わらない。
実測の内訳(work\u50_fastloop\REPORT.md): Phase2 が 109 秒で最大、Phase3 の pak 書き出しは
約 3 秒。pak 735MB の 98.5% は毎回まったく同じバイトを書き直しているだけだった。
    1反復 3分45秒 → 約55秒(約4.1倍)の見積り。

■ 使い方
    python pipeline\py\fast_repack.py --job work\<name>\job.json --out work\<name>\build\try1_P.pak
    python pipeline\py\fast_repack.py --job ... --out ... --tex-gain 1.8556   # テクスチャも作り直す
    python pipeline\py\fast_repack.py --job ... --out k07_P.pak --shadow-lift 0.7  # 影の濃さを振る
    python pipeline\py\fast_repack.py --job ... --out ... --preflight              # 検品まで通す(+約17秒)

■ 呼び出し元(U51、2026-07-25)
GUI「影のみ更新(高速)」→ `pipeline\cli\convert.ps1 -MaterialsOnly`(noue) → 本ツール `--preflight`。
したがって本ツールは**開発専用ではなくなった**。CLI引数と `##REPACK_ERROR##` マーカーは
convert.ps1 の materials-only(noue)分岐と対になっている。片方だけ変えないこと。

■ 影の濃さ(shadow_lift)について — 本ツールの主目的
影の濃さはエンドユーザーがほぼ唯一いじる項目なので、パイプライン中もっとも重い
テンプレート再構築に載せない設計になっている(U50-fast)。
    live_template  … k 非依存(統一MIは BaseColor/Emissive を焼いていない)
    統一MI 79件    … k 依存。`live_template.build_shadow_mi_overrides()` が
                     build\noue_mi_override\ へ数KB書き出す(1秒未満)
本ツールは **毎回この 79件を job.json の shadow_lift(または --shadow-lift)から
作り直してから** pak を書く。したがって shadow_lift を変えても停止せず、
そのまま正しく反映される(k=0 なら1件も作らない = テンプレートのMIがそのまま出る)。
job.json の差分が shadow_lift / unlit **だけ**なら鮮度ゲートも通す
(判定材料は build\job_snapshot.json = 最後のフル変換時点の job.json)。

■ DT(dev#1198)・sway ABP(dev#19)の持ち越し(dev#1494、2026-08-16修正)
影の濃さ以外は変えない設計のため、フル変換が生成した DT テーブル同梱
(dev#1198、頭部/髪の修正)と sway ABP(dev#19、揺れもの)も毎回そのまま
持ち越す。DT は直前フル変換が work\dt_patch\ へ書いた patched バイト列を
再利用(Palworld本体pakは読み直さない)。sway ABP はアバター非依存の純
関数なので sway_abp_build.sway_abp_pak_entries() を毎回もう一度呼ぶ
(job.json は shadow_lift/unlit 以外フル変換時点と同一なので結果は
バイト完全一致=実質的な持ち越し)。修正前はこの2資産が欠落し、
preflight G13/G14 が検出するもののfail-open裁定(dev#1230)により壊れた
pak がそのまま出荷されていた(実報告C8B8RH4W)。

■ sway hub 共有骨格パッチ(dev#1508)の持ち越し(dev#1652、2026-08-22修正)
上記2資産と同じ理由で、共有骨格 SK_PalHuman_Skeleton の reparent パッチ
(dev#1508 W2a-2、揺れ有効アバターの共有骨格差し替え)も dev#1494 修正の
時点では対象外のまま残っていた。揺れ有効アバターの「影のみ更新」で
G3b/G15(揺れ源fail-closedゲート)がFAILし、揺れが実際に壊れたpakが
出荷されていた(dev#1652)。直前フル変換が work\sway_hub_reparent\ へ
書いたパッチ済みバイト列を _reuse_sway_hub_reparent() でDTと同じ方式で
持ち越す(揺れ無効/ハブ割当0件アバターではファイル自体が存在せず、
その場合は従来どおり空リスト=挙動不変)。

■ ★★ 使う前に必ず読むこと(危険性) ★★
1. **キャッシュの鮮度がすべて。**再利用する live_template / noue_work\variant / atlas は
   アバターとテクスチャに依存する。VRM/FBX・アトラス・--tex-gain を変えたのに使い回すと
   **古い成果で判断してしまう**。2026-07-25 にこの取り違え事故が実際に2件起きている。
   → 本ツールは毎回「何を再利用したか」を必ずログへ出す。加えて job.json や
     アバターファイルがキャッシュより新しい場合は **既定で停止する**(--allow-stale で続行可)。
     ログの再利用一覧に目を通さずに結果を判断しないこと。
2. **既定では preflight(約17秒)を飛ばす。**禁止物混入(Skeleton/Body/ubulk)や壊れた pak を
   そのまま実機へ送ることになる。クラッシュすれば気づくが、**通ってしまうと気づかない**。
   → 反復中に使うのはよい。ただし**責任者に見せる前・DEV_NOTES へ記録する前には
     必ずフル変換 + `pipeline\py\preflight_pak.py` を通し直すこと。**
     本ツールの出力だけを根拠に合否を報告してはならない。
   → **`--preflight` を付ければこのツール自身が検品まで通す**(U51)。
     GUIの「影のみ更新」は convert.ps1 経由で必ずこれを付けて呼ぶ。
     エンドユーザーに壊れた pak を渡さないため、この経路で外してはならない。
3. **同一アバターの反復にしか効かない。**アバターを変えたらフル変換からやり直す。
4. 実験ごとに作業域を分けること(devtools\new_experiment.ps1)。build\ を共有すると壊れる。

pipeline\ 配下のソースは一切変更しない(import して使うだけ)。
"""
import argparse
import datetime
import io
import json
import os
import subprocess
import sys

# 2026-07-26: devtools\ から pipeline\py\ へ移設(このファイル自身が既に
# pipeline\py\ にいるので、REPO_DIR はここから2段上)。同居する vp_pakwrite 等は
# 「python <このファイル>」実行時にPythonが自動でスクリプトの場所をsys.path[0]へ
# 入れるため追加のsys.path操作なしでimportできるが、明示しておく(頑健性のため)。
HERE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(HERE_DIR))
sys.path.insert(0, HERE_DIR)
_ue_exit = os.path.join(REPO_DIR, "research", "ue_exit")
if os.path.isdir(_ue_exit):
    sys.path.insert(0, _ue_exit)

import vp_pakwrite  # noqa: E402
import vp_preflight_result  # noqa: E402 (dev#1230: preflight非ブロック化の結果JSON)
import vp_texinject  # noqa: E402
import vp_core  # noqa: E402
import live_template  # noqa: E402 (U50-fast: 影の濃さMIの生成)
import convert_noue  # noqa: E402 (U50-fast: M_VPバリアント選択をフル変換と共有する)
# dev#1494: DT(dev#1198)・sway ABP(dev#19)の持ち越し欠落修正。フル変換
# (build_pak_from_avatar.py Phase3.5/3.6)と同じ定数・同じ公開関数を使う
# ためのimport(pipeline\ 配下のソースは一切変更しない、importして使うだけ)。
import build_pak_from_avatar  # noqa: E402 (dev#1494: DT_PACKAGE_NAME定数の共有)
import sway_abp_build  # noqa: E402 (dev#1494: sway_abp_pak_entries()の再利用)
# dev#7: 生フルパス伏字化の共通実装。元は本ファイルにあった _path_facts/_display_path を
# pipeline\py\path_privacy.py へ一般化して切り出した(convert.ps1/export_from_unity.ps1
# からも使う。work\issue_zero\i7\NOTES.md参照)。エイリアス名(_で始まる)は
# 既存呼び出し箇所(_path_facts(p) 等)を書き換えずに済ませるため
from path_privacy import path_facts as _path_facts, display_path as _display_path  # noqa: E402

# U50-fast: 影の濃さはテンプレートから切り離されたので、この2キーだけは
# job.json が変わっていても中間成果(Blender成果/衣装SK注入/アトラス)を
# 再利用してよい。ここを増やすときは「その設定がテンプレートや variant を
# 変えないこと」をコードで確認してからにすること。
SHADOW_ONLY_KEYS = ("shadow_lift", "unlit")

# live_template 内でのテクスチャの位置(live_template.MVP_PACKAGE_PREFIX と対応)。
# slot0=素体(t00) / slot1=衣装(t01)。
TEX_SLOT_REL = {"body": "Player/ModelMaterials/MainShader/t00.uexp",
                "parka": "Player/ModelMaterials/MainShader/t01.uexp"}
ATLAS_PNG = {"body": "atlas_body.png", "parka": "atlas_parka.png"}

# U51: GUI(app\DiveToPalworld.cs の「影のみ更新」)から convert.ps1 -MaterialsOnly
# 経由で呼ばれるようになったので、失敗の**種類**を機械可読にする。
# convert.ps1 はこのマーカーを見てエンドユーザー向けの一文を出す。
# ここを増やす/改名するときは pipeline\cli\convert.ps1 の materials-only(noue)
# 分岐にある同名の文字列も必ず一緒に直すこと。
ERR_NO_FULL_BUILD = "##REPACK_ERROR## NO_FULL_BUILD"   # 一度もフル変換していない/中間成果が壊れている
ERR_STALE = "##REPACK_ERROR## STALE"                   # 影の濃さ以外の設定が変わっている
ERR_PREFLIGHT = "##REPACK_ERROR## PREFLIGHT_FAIL"      # 出来たpakが検品に落ちた

# dev#67: GUI(app_py\noue_full_build.py の has_noue_full_build())が「影のみ更新」
# ボタンを有効化する条件と、本ツールが実際に要求する前提を機械照合できるよう、
# この3ディレクトリの組み立てをここへ切り出す(main()内に埋め込んだ元のリテラル
# タプルを関数化しただけで、判定内容・呼び出し順は変えていない)。
# noue_full_build.py の _NEED_SUBDIRS と一致させること(増減時は両方一緒に直す)。
# live_templateを対象外とする理由はmain()側の同名コメント(dev#42 item7)を参照。
def required_full_build_paths(build_dir):
    """<build_dir> 配下で「フル変換が完走したか」の判定に使う (label, path) の組。
    build_dir は job_dir/build(GUIの build_dir_path(work_root, vrm_path) と同じ
    組み立て)。"""
    work = os.path.join(build_dir, "noue_work")
    return (
        ("noue_work/variant", os.path.join(work, "variant")),
        ("atlas", os.path.join(build_dir, "atlas")),
        ("noue_mat_override", os.path.join(build_dir, "noue_mat_override")),
    )


def missing_full_build_labels(build_dir):
    """required_full_build_paths()のうち実在しないものの label 一覧。
    空リストなら中間成果が全て揃っている(dev#67 契約テスト用)。"""
    return [label for label, p in required_full_build_paths(build_dir) if not os.path.exists(p)]

# 鮮度ゲートに引っかかったとき「何が変わったのか」をエンドユーザーの言葉で出す。
# GUI の表記に合わせる(app\DiveToPalworld.cs のラベル/ツールチップが正)。
JP_KEY_LABEL = {
    "shadow_lift": "shadow depth", "unlit": "no shadow", "force_two_sided": "two-sided display",
    "shoulder_offset_deg": "shoulder spread", "merge_fingers": "fixed fingers",
    "drop_bones": "removed bones", "vrm_path": "avatar file",
    "avatar_name": "avatar name", "genders": "gender", "engine_mode": "conversion mode",
    "hair_sway": "hair sway", "hair_bones": "hair-sway bones",
    "sway_cloth_bones": "cloth-sway bones", "merge_eyes": "eye merging",
    "humanoid_json": "bone mapping", "paths": "tool locations",
    "license_confirmed": "terms confirmation",
}


def _jp_keys(keys):
    return ", ".join(JP_KEY_LABEL.get(k, k) for k in keys)


def _fmt_mtime(path):
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return "??"


# dev#7: 診断ログへ入力アバター/job.json等の生フルパスを無加工出力していた穴の修正。
# _path_facts/_display_path は pipeline\py\path_privacy.py へ一般化して切り出し済み
# (上のimport節でエイリアスとして束縛している)。


def _stat_tree(path):
    """(ファイル数, 合計バイト, 最も新しいmtime)。パスが無ければ (0, 0, None)。"""
    if os.path.isfile(path):
        st = os.stat(path)
        return 1, st.st_size, st.st_mtime
    n = size = 0
    newest = None
    for dirpath, _d, filenames in os.walk(path):
        for fn in filenames:
            st = os.stat(os.path.join(dirpath, fn))
            n += 1
            size += st.st_size
            newest = st.st_mtime if newest is None else max(newest, st.st_mtime)
    return n, size, newest


def _log_reuse(label, path, bases=()):
    """再利用するキャッシュの素性をログへ出す(危険性1への対策。省略禁止)。
    dev#7: 生フルパスではなく bases 相対(work配下ならそれ)で表示する。"""
    n, size, newest = _stat_tree(path)
    disp = _display_path(path, bases)
    if n == 0:
        print(f"[repack] reuse {label:16s}: **does not exist** {disp}")
        return None
    stamp = datetime.datetime.fromtimestamp(newest).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[repack] reuse {label:16s}: {n} file(s) / {size:,}B / last modified {stamp}  {disp}")
    return newest


# dev#1494: DTテーブル(dev#1198)・sway ABP(dev#19)の持ち越し。
#
# 症状(実報告C8B8RH4W): fast_repack.pyは live_template/variant/atlas/
# mat_override だけを再利用資産として扱っており、後から追加された
# dev#1198(頭部/髪の修正、DT_CharacterCreationMeshPresetTable_Equipments
# の同梱)とdev#19(揺れものpak生成、sway ABP同梱)の2資産が持ち越されて
# いなかった。preflight G13/G14はこれを正しくFAILとして検出するが、
# fail-open裁定(dev#1230、job.json.preflight_nonblocking)により
# エンドユーザーへ壊れたpakがそのまま渡っていた。
#
# 修正方針: 直前フル変換(build_pak_from_avatar.py)の結果を「完全に
# 持ち越す」。


def _reuse_dt_patch(dt_dir, bases):
    """直前フル変換が `build_pak_from_avatar._run_dt_patch()` で
    `work\\dt_patch\\` へ書いたDT(dev#1198)パッチ済み.uasset/.uexpを、
    そのまま持ち越す。

    DTパッチは**全フル変換で常時生成される**(dev#1198、オプトインでは
    ない。preflight_pak.py G13コメント「the dev#1198 head/hair fix DT
    copy is expected in every build」と同じ前提)。無ければキャッシュが
    不完全(フル変換がdev#1198より前、または壊れている)とみなし
    フェイルクローズで停止する(黙って欠落したまま出荷しない)。

    Palworld本体pakは一切読み直さない(rel_pathは定数のみから組み立てる)
    ため、Palworldインストールの大きさに関わらずコストは一定
    (fast_repackの「速さ」を損なわない)。

    戻り値: [(abs_path, rel_path_in_common_mount), ...] の2要素リスト
    (uasset/uexp)。_run_dt_patch()の戻り値と同じ形。"""
    dt_package_name = build_pak_from_avatar.DT_PACKAGE_NAME
    uasset_src = os.path.join(dt_dir, dt_package_name + ".uasset")
    uexp_src = os.path.join(dt_dir, dt_package_name + ".uexp")
    if not (os.path.exists(uasset_src) and os.path.exists(uexp_src)):
        raise SystemExit(
            f"{ERR_NO_FULL_BUILD}\n"
            f"no DT patch (dev#1198) to reuse: {_display_path(dt_dir, bases)}\n"
            "Run a full conversion first (pipeline\\cli\\convert.ps1). "
            "Every full conversion produces this DT copy (dev#1198 head/hair "
            "fix) unconditionally -- its absence means the cached build is "
            "incomplete or predates dev#1198 (dev#1494).")
    dt_rel_uasset = vp_pakwrite.normalize_rel(
        dt_package_name + ".uasset", vp_pakwrite.DT_PREFIX)
    dt_rel_uexp = vp_pakwrite.normalize_rel(
        dt_package_name + ".uexp", vp_pakwrite.DT_PREFIX)
    return [(uasset_src, dt_rel_uasset), (uexp_src, dt_rel_uexp)]


def _reuse_sway_hub_reparent(work, bases):
    """dev#1652: sway hub 共有骨格reparentパッチ(dev#1508 W2a-2、
    SK_PalHuman_Skeleton)の持ち越し。

    症状(dev#1652、実報告): fast_repack.pyはdev#1494でDT(dev#1198)・
    sway ABP(dev#19)の持ち越しには対応したが、後から追加された
    sway_hub_reparent(dev#1508、揺れ有効アバターの共有骨格パッチ)は
    対象外のままだった。揺れ有効アバターで「影のみ更新」を使うと、
    揺れABP(G14はPASS)は同梱されるのに共有骨格パッチだけpakへ
    0件のまま出荷され(G3b/G15がFAIL)、揺れが実際に壊れる。

    直前フル変換(build_pak_from_avatar._run_sway_hub_reparent_patch())が
    <work>\\sway_hub_reparent\\ へ書いたパッチ済み.uasset/.uexpを、
    _reuse_dt_patch()と同じ「そのまま持ち越す」方針で使う。この資産は
    job_dir/converted/sway_hub_reparent.json(パッチ計画、reparent steps)
    と job_dir/converted/sway_hub_patch_manifest.json(G3bが比較する
    計画manifest)だけから決まり、どちらもrepack実行では一切書き換え
    られない(shadow_lift/unlitはもちろん、Palworld本体pakの再読込も
    不要)ため、DTと同様に再計算せず安全に持ち越せる。

    DTと異なり、この資産は**オプション**(揺れ無効/ハブ割当0件の
    アバターでは、フル変換自身もこのフェーズをno-opにしてファイルを
    書かない、_run_sway_hub_reparent_patch()のdocstring参照)。したがって
    両ファイルとも存在しなければ「揺れ無効(またはハブ割当0件)」として
    空リストを返す(=揺れ無効アバターの「影のみ更新」の挙動は不変、
    dev#1652が要求する負の対照条件そのもの)。片方だけ存在する場合は
    壊れたキャッシュとみなしフェイルクローズする(DTと同じ姿勢:
    黙って欠落したまま出荷しない)。

    戻り値: [(abs_path, rel_path_in_common_mount), ...] の2要素リスト
    (uasset/uexp)、または揺れ無効時は空リスト。"""
    name = build_pak_from_avatar.SWAY_HUB_SK_PACKAGE_NAME
    stage_dir = os.path.join(work, "sway_hub_reparent")
    uasset_src = os.path.join(stage_dir, name + ".uasset")
    uexp_src = os.path.join(stage_dir, name + ".uexp")
    have_uasset = os.path.exists(uasset_src)
    have_uexp = os.path.exists(uexp_src)
    if not have_uasset and not have_uexp:
        return []
    if not (have_uasset and have_uexp):
        raise SystemExit(
            f"{ERR_NO_FULL_BUILD}\n"
            "incomplete sway hub shared-skeleton patch (dev#1508/dev#1652) "
            f"to reuse: {_display_path(stage_dir, bases)} "
            f"(uasset={have_uasset}, uexp={have_uexp})\n"
            "Run a full conversion first (pipeline\\cli\\convert.ps1).")
    rel_uasset = vp_pakwrite.normalize_rel(
        "Skeleton/Human/" + name + ".uasset", vp_pakwrite.BODY_PREFIX)
    rel_uexp = vp_pakwrite.normalize_rel(
        "Skeleton/Human/" + name + ".uexp", vp_pakwrite.BODY_PREFIX)
    return [(uasset_src, rel_uasset), (uexp_src, rel_uexp)]


def _rebuild_sway_abp(job, work):
    """sway ABP(dev#19)を持ち越す。

    sway ABPはアバター非依存の純関数(job["sway_intensity"]/
    job["lab_raw_sway_params"]と静的テンプレ
    `pipeline\\py\\sway_abp_templates\\` だけで決まり、Palworld本体pakも
    Blender成果も読まない、sway_abp_build.sway_abp_pak_entries()の
    docstring参照)なので、フル変換(_run_sway_abp_patch())と**同じ公開
    関数をそのままもう一度呼ぶ**。job.jsonはshadow_lift/unlit以外フル
    変換時点と同一であることが鮮度ゲート(main()のjob_diff_keys比較)で
    既に保証されているため、結果はフル変換時とバイト完全一致する
    (=実質的に「持ち越し」と同義。Palworld本体pakを読まないため
    再計算のコストも無視できる)。

    job(--job-dir単独指定時はNone)が無ければ、フル変換側もこのフェーズを
    実行できていない(_run_sway_abp_patch()もjob.json必須でdie()する)ため、
    同じく何も付加しない(空リスト)。

    戻り値: [(abs_path, rel_path_in_common_mount), ...]。sway無効/未指定
    ならsway_abp_pak_entries()自身が空リストを返す(既存のno-op設計)。"""
    if job is None:
        return []
    out_dir = os.path.join(work, "sway_abp")
    try:
        return sway_abp_build.sway_abp_pak_entries(job, out_dir)
    except sway_abp_build.SwayAbpBuildError as e:
        raise SystemExit(
            f"failed to rebuild sway ABP pak entries (dev#19, dev#1494): {e}")


def main():
    ap = argparse.ArgumentParser(
        description="中間成果を再利用してpakだけ作り直す。"
                    "既定ではpreflightを飛ばすので、責任者に見せる前・記録前には必ず"
                    "フル変換+preflight_pak.pyを通すこと(--preflightを付ければ本ツールが検品まで通す)。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("--job", help="job.json。作業域(build\\ の親)を決める。--job-dir と排他")
    ap.add_argument("--job-dir", help="作業域を直接指定する(job.json が無い実験用)")
    ap.add_argument("--out", required=True, help="出力する pak のパス")
    ap.add_argument("--tex-gain", type=float, default=None,
                    help="指定するとテクスチャを作り直す(既定: noue_work\\tex の既存物を流用)")
    ap.add_argument("--tex-dir", default=None,
                    help="テクスチャ出力先(既定 build\\noue_work\\tex)。gain違いを併存させたいとき用")
    ap.add_argument("--allow-stale", action="store_true",
                    help="job.json/アバターがキャッシュより新しくても続行する(既定は停止)")
    ap.add_argument("--shadow-lift", type=float, default=None,
                    help="影の濃さ k(0.0-1.0)。省略時は job.json の値を使う。"
                         "job.json を書き換えずに k だけ振りたいとき用")
    ap.add_argument("--unlit", dest="unlit", action="store_true", default=None,
                    help="unlit として扱う(=k を 0 扱いにする既存の意味論)")
    ap.add_argument("--preflight", action="store_true",
                    help="pak生成後に pipeline\\py\\preflight_pak.py を通す(約17秒)。"
                         "エンドユーザー向け(GUIの「影のみ更新」)は必ずこれを付ける。"
                         "開発の反復では既定(付けない)のままでよい")
    a = ap.parse_args()

    if bool(a.job) == bool(a.job_dir):
        raise SystemExit("specify exactly one of --job or --job-dir")
    if a.job:
        job_path = os.path.abspath(a.job)
        job_dir = os.path.dirname(job_path)
    else:
        job_path, job_dir = None, os.path.abspath(a.job_dir)

    build = os.path.join(job_dir, "build")
    work = os.path.join(build, "noue_work")
    atlas = os.path.join(build, "atlas")
    mat_override = os.path.join(build, "noue_mat_override")
    # dev#1494: build_pak_from_avatar.py の _run_dt_patch() が書く先と同じ
    # パス(work = args.work = <job_dir>\build\noue_work、convert_noue.py
    # の --work 配線と一致)。
    dt_dir = os.path.join(work, "dt_patch")

    _bases = (job_dir, REPO_DIR)  # dev#7: 診断ログの表示専用。実パスはそのまま各変数で使う
    print(f"[repack] work area: {_display_path(job_dir, (REPO_DIR,))}")
    # dev#42 item7(2026-07-29): live_template はU54 WP-Bでアバター非依存の共有キャッシュ
    # (work\_shared_cache\live_template\<fp12>\)へ移った。このアバター固有のbuild\配下に
    # あるとは限らない(初回はここに無く、この後 live_template.build_live_template() が
    # 組み立てる)ので、「フル変換が完走したか」の必須リストからは外す。このアバター固有の
    # 3ディレクトリだけを見る(app_py\noue_full_build.py の has_noue_full_build() と
    # 厳密に一致させること。dev#67で required_full_build_paths() へ切り出し済み)。
    for label, p in required_full_build_paths(build):
        if not os.path.exists(p):
            raise SystemExit(
                f"{ERR_NO_FULL_BUILD}\n"
                f"no intermediate result to reuse: {_display_path(p, _bases)}\n"
                "Run a full conversion first (pipeline\\cli\\convert.ps1).")

    # --- live_templateの解決: 自前でパスを組まず build_live_template() に委ねる ---
    # --job(job.json)がある通常経路では、共有キャッシュのフィンガープリント判定に
    # 従って既存を再利用するか(既に温めてあれば一瞬)、無ければこの場で組み立てる。
    # --job-dir単独(job.jsonが無い実験用途)では共有キャッシュを解決する材料
    # (job["paths"]["palworld_pak"])が無いため、従来どおり作業域直下を前提にする。
    job = None
    if job_path and os.path.exists(job_path):
        try:
            job = vp_core.load_job(job_path)
        except Exception as e:
            print(f"[repack] failed to read job.json via vp_core.load_job() "
                  f"(cannot resolve live_template; falling back to --job-dir-style path): {e}")

    if job is not None:
        template = live_template.build_live_template(job)
    else:
        template = os.path.join(build, "live_template")
        if not os.path.exists(template):
            raise SystemExit(
                f"{ERR_NO_FULL_BUILD}\n"
                f"no intermediate result to reuse: {_display_path(template, _bases)}\n"
                "Run a full conversion first (pipeline\\cli\\convert.ps1).")

    # --- 危険性1: キャッシュの鮮度を必ず表示し、明らかに古ければ止める ---
    print("[repack] --- caches being reused (always check before judging the result) ---")
    newest = {}
    for label, p in (("live_template", template), ("variant", os.path.join(work, "variant")),
                     ("atlas", atlas), ("mat_override", mat_override),
                     ("dt_patch", dt_dir),  # dev#1494: DT(dev#1198)持ち越しの鮮度も表示
                     ("sway_hub_reparent", os.path.join(work, "sway_hub_reparent"))):
                     # dev#1652: 共有骨格パッチ(dev#1508)持ち越しの鮮度も表示。
                     # 揺れ無効/ハブ割当0件アバターでは実在しない(=n=0表示)のが正常。
        newest[label] = _log_reuse(label, p, _bases)
    fp = template.rstrip("\\/") + ".fingerprint.json"
    if os.path.exists(fp):
        with io.open(fp, encoding="utf-8") as f:
            print(f"[repack] live_template.fingerprint = {json.dumps(json.load(f), ensure_ascii=False)}")

    # 「最後にフル変換が完走したのはいつか」を基準にする。
    # live_template は fingerprint で世代管理される長寿命キャッシュなので、
    # 単純に全キャッシュの最古を基準にすると毎回誤検出する(実測)。
    # convert_noue.py が最後に書く build_provenance.json が完走の印になる。
    prov = os.path.join(build, "build_provenance.json")
    if os.path.exists(prov):
        cache_floor = os.path.getmtime(prov)
        print(f"[repack] baseline  last full conversion completed: {_fmt_mtime(prov)}  {_display_path(prov, _bases)}")
    else:
        # 完走の印が無い場合は、毎回作り直される variant を代用する
        cache_floor = newest.get("variant") or min(v for v in newest.values() if v is not None)
        print("[repack] baseline  build_provenance.json is missing, using variant's mtime instead")
    stale = []
    inputs = []
    if job_path and os.path.exists(job_path):
        inputs.append(("job.json", job_path))
        try:
            with io.open(job_path, encoding="utf-8-sig") as f:
                cfg = json.load(f)
            if cfg.get("vrm_path") and os.path.exists(cfg["vrm_path"]):
                inputs.append(("avatar", cfg["vrm_path"]))
        except Exception as e:  # job.json が壊れていても鮮度表示だけは出す
            print(f"[repack] could not read job.json (freshness check uses job.json only): {e}")
    # U50-fast: 「job.json が新しい」だけで止めると、影の濃さを1文字変えた
    # だけでも停止してしまう(影の濃さは中間成果を一切変えないのに)。
    # 最後のフル変換時点の控え(job_snapshot.json)と中身を比較し、
    # 差分が SHADOW_ONLY_KEYS だけなら鮮度judgeの対象から外す。
    snap_path = os.path.join(build, "job_snapshot.json")
    job_diff_keys = None
    if job is not None and os.path.exists(snap_path):
        try:
            with io.open(snap_path, encoding="utf-8-sig") as f:
                snap = json.load(f)
            # 既にtemplate解決時にvp_core.load_job()済みのjobをそのまま使う
            # (二重ロード回避。palworld_locateのレジストリ/Steam探索を2回走らせない)
            cur = {k: v for k, v in job.items() if k != "job_dir"}
            job_diff_keys = sorted(set(snap) ^ set(cur)) or []
            job_diff_keys += sorted(k for k in set(snap) & set(cur) if snap[k] != cur[k])
            job_diff_keys = sorted(set(job_diff_keys))
            if not job_diff_keys:
                print("[repack] job.json content is **identical** to the last full conversion "
                      f"(snapshot: {_display_path(snap_path, _bases)})")
            else:
                print(f"[repack] job.json changes: {job_diff_keys}  "
                      f"(snapshot: {_display_path(snap_path, _bases)})")
        except Exception as e:
            job_diff_keys = None
            print(f"[repack] could not compare against job_snapshot.json ({e}). Falling back to mtime")

    for label, p in inputs:
        mt = os.path.getmtime(p)
        mark = ""
        # dev#7: job.json/アバターの生フルパスは利用者名を含みうる個人情報のため、
        # ログには出さず _path_facts() の事実(ファイル名/存在有無/ドライブ種別等)だけ出す。
        if (label == "job.json" and job_diff_keys is not None
                and set(job_diff_keys) <= set(SHADOW_ONLY_KEYS)):
            # 影の濃さ(と unlit)はテンプレート/variant/アトラスに一切影響しない。
            print(f"[repack] input    {label:16s}: modified {_fmt_mtime(p)}  {_path_facts(p)}"
                  f"  <- diff is shadow-lift only ({job_diff_keys}). Intermediate results still valid")
            continue
        if mt > cache_floor:
            stale.append(label)
            mark = "  <- *newer than cache"
        print(f"[repack] input    {label:16s}: modified {_fmt_mtime(p)}  {_path_facts(p)}{mark}")
    if stale:
        msg = ("[repack] input(s) newer than intermediate results: " + ", ".join(stale) +
               "\n  Proceeding as-is means **judging with stale results**"
               "(2 real mix-up incidents occurred on 2026-07-25).\n"
               "  Redo the full conversion, or pass --allow-stale if this is intentional.")
        # U51: エンドユーザー(GUIの「影のみ更新」)にも何が起きたか伝わる一文を足す。
        # 「黙って古い成果を出す」も「開発者向けの語彙だけで落ちる」も等しく失格。
        if job_diff_keys:
            msg += ("\n  [Settings other than shadow depth have changed] Changed: "
                    + _jp_keys(job_diff_keys) + "\n"
                    "  These cannot be applied via \"Update shadow only\". "
                    "Please run \"Full conversion\".")
        elif "avatar" in stale:
            msg += ("\n  [The avatar file has been updated] "
                    "Please run \"Full conversion\".")
        elif job_diff_keys is None:
            # 前回のフル変換が U50-fast より前(job_snapshot.json が無い)。
            # 何が変わったか判定できないので、安全側=フル変換を案内する
            msg += ("\n  [No record of the previous full conversion, so it cannot be "
                    "determined whether settings changed] Please run \"Full conversion\".")
        if not a.allow_stale:
            raise SystemExit(ERR_STALE + "\n" + msg)
        print(msg + "\n  --allow-stale was specified, continuing.")
    print("[repack] " + "-" * 60)

    # --- テクスチャ ---
    tex_dir = os.path.abspath(a.tex_dir) if a.tex_dir else os.path.join(work, "tex")
    tex_replace = {}
    # U50-single 以降、注入されるアトラスは t00 の1枚だけになった(両スロットの
    # 統一MIが同じ Base Texture=t00 を指すため、convert_noue は t01 を作らない)。
    # したがって「スロットが揃っていること」ではなく「**フル変換が実際に作った
    # ぶんと同じものを差し替えていること**」を基準にする。
    #   - --tex-gain 指定時: アトラスPNGがあるスロットだけ作り直す
    #   - 未指定時       : noue_work\tex に実在するスロットだけ流用する
    # 1枚も解決できなければ止める(黙って素のテンプレートを出荷しない)。
    for slot, rel in TEX_SLOT_REL.items():
        out_uexp = os.path.join(tex_dir, *rel.split("/"))
        png = os.path.join(atlas, ATLAS_PNG[slot])
        if a.tex_gain is not None:
            if not os.path.exists(png):
                print(f"[repack] tex {slot}: excluded, no atlas PNG "
                      f"(full conversion did not inject this slot either): {_display_path(png, _bases)}")
                continue
            template_uexp = os.path.join(template, *rel.split("/"))
            info = vp_texinject.inject_texture_file(
                template_uexp, png, out_uexp, alpha_coverage=True, gain=a.tex_gain)
            print(f"[repack] tex {slot}: gain={info['gain']:.4f} PSNR={info['psnr']:.2f}dB "
                  f"-> {_display_path(out_uexp, _bases)}")
        if not os.path.exists(out_uexp):
            print(f"[repack] tex {slot}: excluded, no injected texture "
                  f"(full conversion did not inject this slot either): {_display_path(out_uexp, _bases)}")
            continue
        tex_replace[rel] = out_uexp
        if a.tex_gain is None:
            print(f"[repack] tex {slot}: reusing existing (not rebuilt) "
                  f"last modified {_fmt_mtime(out_uexp)}  {_display_path(out_uexp, _bases)}")
    if not tex_replace:
        raise SystemExit(
            f"{ERR_NO_FULL_BUILD}\n"
            f"no injected texture found: {_display_path(tex_dir, _bases)}\n"
            "Run a full conversion first (pipeline\\cli\\convert.ps1) "
            "(proceeding as-is would produce a pak without the avatar's texture).")

    # --- 影の濃さ(shadow_lift)のMI: 毎回ここで作り直す(1秒未満) ---
    # テンプレートは k 非依存なので、pak を書く直前に統一MI 79件だけ差し替える。
    # これがフル変換(convert_noue.py → build_pak_from_avatar --mi-override-dir)と
    # **同じ関数・同じ出力先**であることが、両者の一致を構造的に保証している。
    mi_override_dir = os.path.join(build, "noue_mi_override")
    mi_replace = {}
    if job is not None:
        # template解決時に読み込み済みのjobをそのまま使う(二重ロード回避)。
        # ここで shadow_lift/unlit を書き換えるが、それより前(job_diff_keys比較)は
        # 既に済んでいるので、この場での変更が過去の判定に影響することはない
        if a.shadow_lift is not None:
            print(f"[repack] overriding job.json's value ({job.get('shadow_lift')}) "
                  f"with --shadow-lift {a.shadow_lift}")
            job["shadow_lift"] = a.shadow_lift
        if a.unlit:
            print("[repack] --unlit specified (treated as equivalent to k=1.0)")
            job["unlit"] = True
        out, n_mi, mi_info = live_template.build_shadow_mi_overrides(
            job, template, mi_override_dir)
        print(f"[repack] shadow depth: k={mi_info['k']:.4f} / MI {n_mi} / "
              f"uexp sha1={mi_info['uexp_sha1']}")
        # 旧経路(M_VP_{slot})も shadow_lift を焼いている。実機の描画には届いて
        # いない(参照ゼロ。DEV_NOTES 2026-07-25(27) §3)が、**焼き直さないと
        # 本ツールの出力がフル変換の出力とバイト一致しなくなる**ので、フル変換と
        # 同じ関数(convert_noue.prepare_material_overrides)をそのまま呼ぶ。
        meta_path = os.path.join(job_dir, "converted", "avatar_meta.json")
        if os.path.exists(meta_path):
            with io.open(meta_path, encoding="utf-8") as f:
                _meta = json.load(f)
            convert_noue.prepare_material_overrides(
                job, _meta, live_template.VARIANTS_DIR)
        else:
            print(f"[repack][WARN] avatar_meta.json not found, M_VP left unchanged: "
                  f"{_display_path(meta_path, _bases)} (this path does not reach rendering "
                  f"so the visuals are unaffected, but it will not byte-match the full "
                  f"conversion's output)")
    else:
        if a.shadow_lift is not None or a.unlit:
            raise SystemExit("--shadow-lift / --unlit requires --job (job.json)")
        n_mi = 0
        if os.path.isdir(mi_override_dir):
            print(f"[repack] shadow depth: --job-dir specified, reusing existing "
                  f"{_display_path(mi_override_dir, _bases)} as-is (not rebuilt)")
    for dirpath, _d, filenames in os.walk(mi_override_dir):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            mi_replace[os.path.relpath(p, mi_override_dir).replace("\\", "/")] = p

    # --- 差し替え表の組み立て ---
    replace_map = dict(tex_replace)
    replace_map.update(mi_replace)
    n_mat = 0
    for fn in sorted(os.listdir(mat_override)):
        replace_map[f"Player/ModelMaterials/MainShader/{fn}"] = os.path.join(mat_override, fn)
        n_mat += 1

    variant_dir = os.path.join(work, "variant")
    n_var = 0
    for dirpath, _d, filenames in os.walk(variant_dir):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            replace_map[os.path.relpath(p, variant_dir).replace("\\", "/")] = p
            n_var += 1
    print(f"[repack] replacing: tex {len(tex_replace)} / shadow-lift MI {len(mi_replace)} / "
          f"mat_override {n_mat} / variant {n_var} = total {len(replace_map)}")

    all_files = vp_pakwrite.collect_files(template)
    final_files = []
    n_replaced = 0
    for src, rel in all_files:
        if rel in replace_map:
            final_files.append((replace_map[rel], rel))
            n_replaced += 1
        else:
            final_files.append((src, rel))
    if n_replaced != len(replace_map):
        raise SystemExit(f"{ERR_NO_FULL_BUILD}\n"
                         f"only {n_replaced}/{len(replace_map)} replacement target(s) matched "
                         "(live_template and the cache version may be out of sync)")

    # dev#1198 WP-B5a: COMMON_MOUNT実配線。build_pak_from_avatar.py Phase3と
    # 同じ配線(vp_pakwrite.to_common_mount_body_files参照)。
    common_mount_files = vp_pakwrite.to_common_mount_body_files(final_files)

    # dev#1494: DT(dev#1198)/sway ABP(dev#19)の持ち越し(実報告C8B8RH4W)。
    # build_pak_from_avatar.py Phase3.5/3.6 と同じ、to_common_mount_body_files()
    # を通さない別系統(DT_PREFIX)としてcommon_mount_filesへ直接合流させる
    # (WP-B5b/dev#19申し送りどおり)。この2ステップを省略すると、preflight
    # G13/G14が正しくFAILを検出する(fail-open裁定dev#1230のため壊れたpak
    # がそのまま出荷される)。
    dt_files = _reuse_dt_patch(dt_dir, _bases)
    sway_abp_files = _rebuild_sway_abp(job, work)
    # dev#1652: sway hub 共有骨格パッチ(dev#1508)の持ち越し。DT/sway ABPと
    # 同じcommon_mount_files合流の第3の資産(build_pak_from_avatar.pyの
    # Phase3.7と対になる。総点検の結果、common_mount_filesへ特別合流する
    # 資産はこの3つで全てだった -- 詳細はPR本文の表を参照)。
    sway_hub_files = _reuse_sway_hub_reparent(work, _bases)
    print(f"[repack] carried over from last full build: DT (dev#1198) {len(dt_files)} file(s), "
          f"sway ABP (dev#19) {len(sway_abp_files)} file(s), "
          f"sway hub shared-skeleton patch (dev#1508, dev#1652) {len(sway_hub_files)} file(s)")
    common_mount_files = common_mount_files + dt_files + sway_abp_files + sway_hub_files

    out_pak = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out_pak) or ".", exist_ok=True)
    info = vp_pakwrite.build_pak(common_mount_files, out_pak,
                                  mount_point=vp_pakwrite.COMMON_MOUNT)
    print(f"[repack] pak generated: {_display_path(out_pak, _bases)} (total entries {info['n_entries']}, "
          f"replaced {n_replaced}, size={info['size']:,})")

    # --- 検品(U51: エンドユーザー経路では必ず通す) ---
    if a.preflight:
        if not (job_path and os.path.exists(job_path)):
            raise SystemExit("--preflight requires --job (job.json)")
        preflight_py = os.path.join(REPO_DIR, "pipeline", "py", "preflight_pak.py")
        print("[repack] === preflight_pak.py (final check / ~17s) ===")
        # dev#1230(2026-08-08オーナー裁定): GUIの「影のみ更新(高速)」も
        # ユーザーサイド変換フローの一部(convert.ps1 -MaterialsOnly経由)。
        # job.jsonのpreflight_nonblockingキー(app_py\pipeline_runner.pyの
        # write_job()が常にTrueで書く)が立っていればブロックしない。
        # jobがNone(load_job失敗、上のtry/except参照)のときは安全側
        # (従来どおりブロック)に倒す。
        preflight_nonblocking = bool(job.get("preflight_nonblocking", False)) if job else False
        if not preflight_nonblocking:
            r = subprocess.run([sys.executable, preflight_py, job_path, out_pak,
                                template, live_template.COOK_LOG])
            if r.returncode != 0:
                raise SystemExit(
                    f"{ERR_PREFLIGHT}\n"
                    f"final check failed (preflight_pak.py exit={r.returncode}). "
                    "Do not use this MOD.")
            print("[repack] preflight PASS")
        else:
            r = subprocess.run([sys.executable, preflight_py, job_path, out_pak,
                                template, live_template.COOK_LOG],
                                capture_output=True, text=True)
            for text in (r.stdout, r.stderr):
                if text:
                    sys.stdout.write(text if text.endswith("\n") else text + "\n")
            failed_gates = vp_preflight_result.parse_preflight_failed_gate_lines(r.stdout)
            status = "PASS" if r.returncode == 0 else "FAIL"
            result_path = vp_preflight_result.write_preflight_result_json(
                out_pak, status, r.returncode, failed_gates)
            if r.returncode != 0:
                print(f"[repack] preflight FAILED but job.json preflight_nonblocking "
                      f"is set: keeping pak as-is and continuing "
                      f"(n_fail_gates={len(failed_gates)}, result recorded to {result_path})")
            else:
                print("[repack] preflight PASS")
    else:
        print("[repack] Note: preflight was not run. Before showing this to the "
              "responsible person or recording it, always run "
              "full conversion + pipeline\\py\\preflight_pak.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
