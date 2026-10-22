# -*- coding: utf-8 -*-
"""U6-T2: step02.blend → pak 一気通貫CLI(UE非依存パイプラインの本統合)。

1コマンドで以下を実行する(UnrealPak.exe不使用。同梱Blender+numpyのみ):
  1) 同梱Blender headlessで --step02-female/--step02-male を実アバターメッシュへ
     ダンプ(`research\\ue_exit\\dump_avatar_mesh.py`、無改変・そのまま呼び出し)
  2) 衣装SK 60体へ性別別に実アバターを注入
     (`research\\ue_exit\\build_avatar_variant_all.py`の
     `collect_targets`/`gender_of`/`build_and_validate`をimport再利用、無改変)
  3) 残り375件(スタブ153+マテリアル+テクスチャ+アンカー等)は
     --template からそのままコピー
  4) `vp_pakwrite.py`(U6-T1、本ファイルと同じpipeline\\py配下、新規)でpak化
     (UnrealPak不使用)
  5) `preflight_pak.py`を自動実行して結果を表示

既存ファイル(vp_core.py/vp_meshrestore.py/preflight_pak.py/
research\\ue_exit\\build_avatar_variant*.py/dump_avatar_mesh.py)は一切変更しない。
本ファイルはそれらをimport/subprocessで呼び出すだけの新規オーケストレータ
(pipeline\\py\\restore_full.pyと同じ設計方針)。

実行例:
  python build_pak_from_avatar.py \\
      --step02-female work\\<job>\\converted\\step02_female.blend \\
      --step02-male   work\\<job>\\converted\\step02_male.blend \\
      --template work\\<job>\\build\\pak_extract \\
      --out out\\avatar.pak \\
      --blender <blender.exeへの絶対パス> --job-json work\\<job>\\job.json
  (dev#14: --blender/--job-jsonは開発機ローカルパスの既定値を撤去し必須引数化
   した。convert_noue.py経由の通常実行では常に明示的に渡されるため挙動は
   不変。--cook-logの既定値はpipeline\\py\\noue_master\\shader_platform_facts.json
   (noueモード共通の固定事実ファイル、2026-07-26 cooklog_fix)。UEモードの実cookログを
   使いたい場合のみ明示指定する)
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time  # dev#1650(計測WP): フェーズ別所要時間の一時計時に使う。ログのみで
             # 診断できる原則に合わせ、恒久的に残す(出力pakには一切影響しない)

HERE = os.path.dirname(os.path.abspath(__file__))       # pipeline\py
PIPELINE_DIR = os.path.dirname(HERE)                     # pipeline\
REPO_DIR = os.path.dirname(PIPELINE_DIR)                 # リポジトリルート

sys.path.insert(0, HERE)
import dt_flag_patcher  # noqa: E402 (dev#1198 WP-B5b: DTフラグパッチ本体)
import pak_live_extract  # noqa: E402 (dev#1198 WP-B5b: バニラDTの実行時抽出)
import vp_core as core  # noqa: E402 (dev#1198 WP-B5b: job.json読み込み+pakインデックス)
import vp_dt_row_select  # noqa: E402 (dev#1198 WP-B5b: DT行選定)
import pak_src_sidecar  # noqa: E402 (pak⇒blend原則: pak隣へstep02パスのサイドカーを書く)
import vp_exclusions  # noqa: E402
import vp_equipment_filter  # noqa: E402 (dev#165第2期: 装備限定のPhase2絞り込み)
import vp_pakwrite  # noqa: E402
import vp_preflight_result  # noqa: E402 (dev#1230: preflight非ブロック化の結果JSON)
import vp_refskel_extend  # noqa: E402 (dev#19 R3統合: sway extra donor骨のRefSkeleton事前拡張)
import sway_assign  # noqa: E402 (dev#19 swayfix: リーフボーン名解決にSWAY_DONOR_FAMILIESを再利用)
import sway_abp_build  # noqa: E402 (dev#19 揺れものpak生成の製品パイプライン結線)
import sway_allocator_wire  # noqa: E402 (dev#1508 W2a: sway_node_overrides.jsonファイル名の共有定数)
import sway_shared_skeleton  # noqa: E402 (dev#1508 W2a-2: 汎用ハブ配線、共有Skeleton reparentパッチ)
import vp_texinject  # noqa: E402
import vp_parallel  # noqa: E402 (rd_120: Phase1/Phase2並列化の共有ヘルパー)
# U51(research\ue_exit→pipeline\py移設): build_avatar_variant*.py/dump_avatar_mesh.py
# は元research\ue_exit\から無改変のままpipeline\py\へコピーされ、以降はHEREから
# 直接import/参照する(research\ue_exit\側は開発参照用に残置、実行時には見ない)
from build_avatar_variant import load_dump  # noqa: E402
from build_avatar_variant_all import (  # noqa: E402
    build_and_validate, collect_targets, gender_of,
)

TAG = "build_pak_from_avatar"

DEFAULT_DUMP_SCRIPT = os.path.join(HERE, "dump_avatar_mesh.py")
DEFAULT_PREFLIGHT = os.path.join(HERE, "preflight_pak.py")
# dev#14(2026-08-02): --blender/--job-jsonにはかつて開発機ローカルの絶対パス
# (DEFAULT_BLENDER_EXE=C:\P\Work\PalMod\...、DEFAULT_JOB_JSON=work\toto\job.json)
# が既定値として設定されていた。これらは開発機以外には実在せず、省略時に
# 「開発機のパスが無い」という真因と無関係な内部エラーで停止する設計ミスだった
# (同じ構造の不具合が convert_noue.py 側の参照バニラデータ解決で実際に報告され、
# resolve_vanilla_source() で解消済み——WP16。本ファイルの--cook-logは2026-07-26
# cooklog_fixで既に同種の修正を受けている)。convert_noue.py経由の通常実行では
# --blender/--job-jsonは常に明示的に渡されるため(job["paths"]["blender_exe"]、
# job_json引数)、既定値を持たせる意味がそもそも無い。フォールバック先を持たせず
# argparse側でrequired=Trueにし、省略時は明確な使用法エラーで即停止させる。
# 個人アバター名"toto"を含んでいた。noueモードでpreflightが本来参照すべきは
# pipeline\py\noue_master\shader_platform_facts.json(SM5/SM6双方でcook済みという
# 固定の事実、live_template.COOK_LOGと同じ実体)であり、これはリポジトリにも配布物にも
# 常に存在するため、スタンドアロン実行時の既定値として妥当(convert_noue.py経由の
# 通常実行では--cook-logが明示的に上書きされるため、この既定値は直接呼び出し時のみ使う)。
DEFAULT_COOK_LOG = os.path.join(HERE, "noue_master", "shader_platform_facts.json")

# U6-T3(ストレッチ): avatar_meta.json実測(m00=body/t00.png, m01=parka/t01.png、
# docs\REPORT_U5_2026-07-23.md T1b節参照)固定のテクスチャスロット対応
TEX_SLOT_REL = {
    "body": "Player/ModelMaterials/MainShader/t00.uexp",
    "parka": "Player/ModelMaterials/MainShader/t01.uexp",
}

# dev#1198 WP-B5b: DT同梱の本配線(頭部問題根治の最終ピース)。
# 設計正本: work\rd_1198_wpb\PROPOSAL.md §2・§3・§5.1・§11、
# 実証済みプロトタイプ: work\rd_1198_dtreach\build_dtreach_pak.py。
DT_PACKAGE_NAME = "DT_CharacterCreationMeshPresetTable_Equipments"
# pak内のバニラ正パス(Pal/Content/... 座標系、core.read_pak_entries()/
# pak_live_extract.extract_files()が使う座標系と同じ)。
DT_VANILLA_REL = f"Pal/Content/Pal/DataTable/CharacteCreation/{DT_PACKAGE_NAME}"

# dev#1508 W2a-2(汎用ハブ配線): 共有Skeleton(SK_PalHuman_Skeleton)の
# バニラ正パス。work\rd_19_r1_vanilla\extracted\...の実測構造・
# sway_shared_skeleton.pyのモジュールdocstringが指す実体と同一。
SWAY_HUB_SK_PACKAGE_NAME = "SK_PalHuman_Skeleton"
SWAY_HUB_SK_VANILLA_REL = (
    f"Pal/Content/Pal/Model/Character/Skeleton/Human/{SWAY_HUB_SK_PACKAGE_NAME}")
# job_dir/converted/配下、sway_hub_placement.plan_reparent_steps()の出力を
# ReparentStep相当のjsonへシリアライズしたもの(将来のstep02_retarget.py
# 結線が書き出す想定、本WPでは未結線——モジュールdocstring/_run_sway_hub_
# reparent_patch()参照)。
SWAY_HUB_REPARENT_FILENAME = "sway_hub_reparent.json"
# dev#1508 W2a-2d(G3ゲート昇格): _run_sway_hub_reparent_patch()が実際に
# 共有Skeletonへ適用した内容(骨名・親・座標)を記録するサイドカー。
# preflight_pak.py G3はこのファイルと「バニラとの実差分」を突き合わせ、
# manifestに載っている差分だけを許可する(載っていない差分が1つでも
# あればFAIL、manifestが無いのに差分があってもFAIL=fail-closed)。
# job_dir/converted/配下(job固有、job_dir/vanilla/のような複数ジョブ
# 共有キャッシュではない——PROGRESS.md「per-jobのconverted/配下」の方針を
# 踏襲)。
SWAY_HUB_PATCH_MANIFEST_FILENAME = "sway_hub_patch_manifest.json"


def die(msg):
    print(f"[{TAG}][FATAL] {msg}")
    sys.exit(1)


def run_preflight_phase(job_json, out_pak, template, cook_log, nonblocking):
    """Phase 4(preflight_pak.py実行)本体。dev#1230: nonblocking=False(既定)
    のときは従来と一字一句同じ挙動(die()で停止、byte-for-byte不変。
    relgate.py/release.py等の開発側関所はnonblockingを一切渡さないため、
    このモジュールを含めたこのWP全体の変更後もこの分岐は無変更)。

    nonblocking=True(ユーザーサイド変換フロー専用、convert_noue.pyが
    job.jsonのpreflight_nonblockingキーから伝える)のときは、preflight_pak.py
    の標準出力を捕捉してからそのまま自分の標準出力へ再出力する(convert.ps1の
    `2>&1 | Tee-Object $noueLog`が拾う既存のログ経路をそのまま維持する)。
    FAILしてもdie()せず、vp_preflight_result.write_preflight_result_json()で
    結果(status/returncode/failed_gates)をout_pakと同じディレクトリの
    preflight_result.jsonへ書いて継続する(GUI側 app_py\\pipeline_runner.py
    の read_preflight_result() が読む)。

    戻り値: nonblocking時は書き込んだpreflight_result.jsonの絶対パス、
    それ以外(blocking時、または到達しない=常にdie()で終わる)はNone
    (呼び出し元はテスト以外でこの戻り値を使わない)。"""
    if not nonblocking:
        r = subprocess.run([sys.executable, DEFAULT_PREFLIGHT, job_json,
                            out_pak, template, cook_log])
        if r.returncode != 0:
            die(f"preflight_pak.py exited with {r.returncode} (see output above)")
        return None

    r = subprocess.run([sys.executable, DEFAULT_PREFLIGHT, job_json,
                        out_pak, template, cook_log],
                        capture_output=True, text=True)
    for text in (r.stdout, r.stderr):
        if text:
            sys.stdout.write(text if text.endswith("\n") else text + "\n")
    failed_gates = vp_preflight_result.parse_preflight_failed_gate_lines(r.stdout)
    status = "PASS" if r.returncode == 0 else "FAIL"
    result_path = vp_preflight_result.write_preflight_result_json(
        out_pak, status, r.returncode, failed_gates)
    if r.returncode != 0:
        print(f"[{TAG}] preflight FAILED but --preflight-nonblocking is set: "
              f"keeping pak as-is and continuing (n_fail_gates={len(failed_gates)}, "
              f"result recorded to {result_path})")
    else:
        print(f"[{TAG}] preflight PASSED")
    return result_path


def run(cmd, log_path):
    """subprocessを実行し、ログをファイルへ保存する。失敗したら末尾を出して停止する。
    (restore_full.py の run() と同じ流儀)"""
    print(f"[{TAG}] $ {' '.join(cmd)}")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        tail = ""
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                tail = f.read()[-3000:]
        except OSError:
            pass
        die(f"command failed exit={r.returncode} (log: {log_path})\n"
            f"--- log tail ---\n{tail}")
    print(f"[{TAG}]   -> OK (log: {log_path})")


# === rd_120 5.3: Female/Maleダンプの並列化 ==================================
# vp_parallel.run_pair_parallel()(ThreadPoolExecutor、subprocess.run()待ちが
# 大半でCPUを食わないI/Oバウンド処理なのでスレッドで十分)へ委譲する。
# ダンプ本体はrun()をそのまま呼ぶ(die()を含む既存の失敗時挙動を変えない)。
# die()がワーカースレッド内で呼ばれても、run_pair_parallel()のcontext manager
# がもう片方のダンプの完了を待ってから例外を伝播する(vp_parallel.pyの
# モジュールdocstring参照)ので、Female/Male両方の診断ログが必ず残る。
def _dump_gender(args):
    gender, blend, blender_exe, dump_blender_args, out_json, log_path, max_influences = args
    print(f"[{TAG}] === Phase 1: {gender} dump ===")
    run([blender_exe, "--background", "--factory-startup", *dump_blender_args,
         "--python-exit-code", "1", "--python",
         DEFAULT_DUMP_SCRIPT, "--", blend, gender, out_json, str(max_influences)],
        log_path)
    if not os.path.exists(out_json):
        die(f"{gender} dump produced no output: {out_json}")
    return gender, out_json


# === rd_120 5.1: Phase2 SK注入ループのプロセス並列化 =========================
# `dump`辞書(gender別、数百KB)をタスク引数として58回渡すと再pickleコストが
# 乗るため、initializer(_init_worker)でワーカープロセスごとに1回だけ
# モジュールグローバルへ積む(PROPOSAL 5.1節)。タスク引数は軽量タプルのみ。
_WORKER_DUMPS = None


def _init_worker(dumps):
    global _WORKER_DUMPS
    _WORKER_DUMPS = dumps


def _injection_worker(task):
    """1件のSK注入をワーカープロセスで実行する。現行の
    `try: build_and_validate(...) except Exception as e: ...`をそのまま踏襲し、
    **例外を外へ投げず** (rel_uexp, gender, ok, errs, info) を返す
    (=1件の失敗が他タスクの実行・結果収集を止めない。tests\\parallel\\
    test_pak_parallel.pyの負の対照テスト参照)。"""
    uexp_path, uasset_path, gender, out_uexp, out_uasset, rel_uexp = task
    dump = _WORKER_DUMPS[gender]
    try:
        ok, errs, info = build_and_validate(uexp_path, uasset_path, dump, out_uexp, out_uasset)
    except Exception as e:
        ok, errs, info = False, [str(e)], {}
    return rel_uexp, gender, ok, errs, info


def _default_injection_workers():
    """既定ワーカー数=max(1, cpu_count-2)。D2P_INJECT_WORKERS環境変数で上書き可
    (rd_120 PROPOSAL 8節論点1)。dev#1176: 通常メモリ環境ではこの値から
    下げないが、利用可能メモリが少ない環境では
    vp_parallel.adaptive_worker_count()が下限側にクランプする
    (実報告WEARE5UK、ProcessPoolExecutorワーカー起動時のMemoryError対策)。"""
    return vp_parallel.adaptive_worker_count("D2P_INJECT_WORKERS", floor=2)


def _run_injection_pool(tasks, n_workers, dumps):
    """rd_120 5.1のProcessPoolExecutor実行をMemoryError変換込みで包む
    (dev#1176: 実報告WEARE5UK)。トレースバック確定済みの発生箇所は
    ProcessPoolExecutorのワーカー起動時(multiprocessing.reduction.dump、
    spawn方式でのpickle転送)。ここでMemoryErrorが起きると、このtry/exceptが
    無ければ生のPythonトレースバック(技術的で対処法が書かれていない)が
    そのままユーザーのログに残ってしまう。die()の分かりやすい英語案内
    (このスクリプトの他のdie()呼び出しと同じ言語慣習、CLAUDE.md「言語方針」
    ——パイプライン出力は英語)へ変換する。

    このtry/exceptを外せばvp_parallel.run_pool_ordered()自体はMemoryErrorを
    素通しで外へ伝播する(=このラッパーだけが変換を担う)ことを
    tests\\parallel\\test_adaptive_worker_count_dev1176.py の負の対照で実測している。"""
    try:
        return vp_parallel.run_pool_ordered(
            _injection_worker, tasks, n_workers, initializer=_init_worker, initargs=(dumps,))
    except MemoryError:
        die(f"worker process pool ran out of memory while starting "
            f"{n_workers} worker process(es) for SK injection "
            "(MemoryError during ProcessPoolExecutor startup). "
            "Close other applications to free up memory, or lower the "
            "parallel worker count via the D2P_INJECT_WORKERS environment "
            "variable (e.g. D2P_INJECT_WORKERS=2), then try again.")


# === dev#19 R3統合(rd_19_refskel PROPOSAL手順4): sway donorが要求する骨の
# うち対象SK自身のRefSkeletonに元々無いものを、共有骨格の実測bindpose
# (refskel_{family}_{gender}.json、extract_vanilla.py "sway_extra_family"の
# 出力。donorexp WP(2026-08-11、issue#19)で家系ごとの一意名へ変更、下の
# _refskel_extra_for()参照)から静的に事前登録した拡張コピーへ差し替える。
#
# 設計判断(rd_19_refskel_wt/PROPOSAL.mdのjobキー案からの変更、本流化時の
# 解釈): job.jsonのsway_cloth_donor_family/sway_chainsを読んで「どの
# ファミリーが有効か」を間接的に解決するのではなく、**その回の実際の
# dump(Blender step02+dump_avatar_mesh.pyが書き出した頂点ウェイト)が
# 実際に参照するボーン名集合**を直接の入力にする。理由: (1)
# SWAY_DONOR_FAMILIES はBlender専用モジュール(pipeline\blender\
# step02_retarget.py、bpy依存)にありpipeline\py側から素直にimportできない
# (dev#19既存WPが sway_assign._load_step02_symbols() のソース静的実行で
# 回避している通り)。(2) dumpの参照ボーン名はsway機構がどんな将来の
# donorファミリー・複数チェーン(sway_chains)を使っても共通の最終出力
# であり、family名を経由する間接解決より頑丈。(3) sway未使用ジョブでは
# dumpが標準ボーン以外を一切参照しないため、このアプローチでも
# ④(既定値=未実装状態と完全同一)は自動的に成立する。
def _dump_used_bone_names(dump):
    """dump(build_avatar_variant.load_dump()形式)のvertices[].weightsから、
    weight>0で実際に参照されているボーン名集合を返す。
    build_avatar_variant.build_uexp_variant()のused_names計算と同じ考え方
    (weight>0の頂点グループのみを「実際に使うボーン」として数える)を、
    RefSkeleton拡張要否の判定のために注入前に独立して行う。"""
    names = set()
    for v in dump.get("vertices", ()) or ():
        for name, w in v.get("weights", ()) or ():
            if w > 0:
                names.add(name)
    return names


def _refskel_extend_overrides(pairs, template, variant_dir, dumps):
    """dev#19 R3統合(rd_19_refskel PROPOSAL手順4)の唯一の未実装ピース:
    kept確定直後・注入タスク組み立て前に呼ばれ、sway donorが要求する
    骨が対象SK自身のRefSkeletonに無い場合、共有骨格の実測bindposeから
    拡張したコピーを作って差し替える。

    戻り値: {rel_uexp(templateからの相対パス, "/"区切り): (uexp_path,
    uasset_path)}(拡張が実際に必要だったSKのみのエントリ。テンプレート
    本体・variant_dir本来の出力構造には一切書き込まない — 拡張コピーは
    variant_dirの兄弟ディレクトリrefskel_ext_srcへ置く)。

    ④既定値不変の根拠: 通常のアバターは常に標準ヒューマノイド骨へ
    ウェイトを持つため、used_bone_namesが空になることは(壊れたdumpを
    除き)無い——しかし標準骨は定義上どの装備SKのRefSkeletonにも
    元から存在する(でなければベースの実アバター注入自体が全SKで
    機能しない)ため、sway未使用ジョブでは per-SK の missing が必ず
    空になり、1件も上書きされずに空dictを返す(SKごとのRefSkeleton
    読み取り自体は行うが、書き込み・ファイル生成は一切発生しない)。
    dumps自体が空/未指定(dumps={} 等、既存呼び出し元
    tests\\equipment_filter_dev165の直接呼び出しテスト)の場合は
    その読み取りすら行わず即座に空dictを返す。
    負の対照は test_build_pak_from_avatar_refskel_wiring_dev19.py 参照。"""
    used_names_by_gender = {
        gender: _dump_used_bone_names(dump or {})
        for gender, dump in (dumps or {}).items()
    }
    if not any(used_names_by_gender.values()):
        return {}

    refskel_extra_cache = {}
    leaf_needed_cache = {}

    def _refskel_extra_for(gender):
        """donorexp WP(2026-08-11、issue#19、要件1/2): 複数家系を同時抽出
        できるようになったため、固定1ファイル(旧`refskel_extra_{gender}.json`)
        を直接読むのではなく、vanilla/配下の`refskel_*_{gender}.json`
        (base自身の`refskel_{gender}.json`)へマッチする**全ファイル**を
        ソート順にマージする(家系名をハードコードしない
        ——preflight_pak.load_vanilla_ref_for_g5()と同じ方針)。
        マッチが1件も無ければ従来どおりNone(=拡張材料なし)。

        swayfix WP(dev#19、issue#19)で、base自身の`refskel_{gender}.json`も
        マージ対象へ追加した(以前は`refskel_*_{gender}.json`の`*`部分が
        必須で除外されていた)。OldCloth001は"extra family"扱いではなく
        base自身のrefskelにchain/合成リーフボーンが載るため、base抜きでは
        OldCloth001のリーフボーン(SYNTHETIC_LEAF_BONES、
        extract_vanilla.py側)がここで解決できなかった。base側は元々
        「衣装固有クロスボーン込みの人体骨格全体」なので、他家系の
        missing解決に紛れ込んでも実害は無い(名前が衝突しない限り無害な
        追加材料が増えるだけ)。"""
        if gender not in refskel_extra_cache:
            dump = (dumps or {}).get(gender) or {}
            job_converted_dir = dump.get("_job_converted_dir")
            data = None
            if job_converted_dir:
                vanilla_dir = os.path.join(
                    os.path.dirname(job_converted_dir), "vanilla")
                pattern = os.path.join(
                    vanilla_dir, f"refskel_*_{gender.lower()}.json")
                base_path = os.path.join(
                    vanilla_dir, f"refskel_{gender.lower()}.json")
                candidates = sorted(glob.glob(pattern))
                if os.path.isfile(base_path) and base_path not in candidates:
                    candidates = [base_path] + candidates
                # dev#1508 W2a-2c(汎用ハブ配線): ハブroot+自由donorプールの
                # 骨は共有Skeleton(SK_PalHuman_Skeleton、実測4079骨)全体から
                # per-jobで動的に選ばれるため、vanilla_dir(全ジョブで共有
                # されうるキャッシュ、ロック対象——U54キャッシュ判定節参照)
                # ではなく、このjob固有のconverted/配下(`step02_retarget.py`
                # `wire_sway_hub_auto()`が書き出す
                # `sway_hub_refskel_{gender}.json`、job_dirを跨いだ受け渡し
                # の既存流儀=sway_node_overrides.jsonと同型)へ配置される。
                # 末尾に追加する(家系refskelとの名前衝突は構造的に起きない
                # ——選ばれるdonor骨は`sway_hub.reserved_descendants_of()`が
                # 全KPノードroot骨の子孫を除外するため、家系登録済みチェーン
                # (それ自体がKPノードrootまたはその子孫)とは重ならない)。
                hub_path = os.path.join(
                    job_converted_dir, f"sway_hub_refskel_{gender.lower()}.json")
                if os.path.isfile(hub_path) and hub_path not in candidates:
                    candidates.append(hub_path)
                merged = {}
                for cand in candidates:
                    with open(cand, encoding="utf-8") as f:
                        merged.update(json.load(f))
                if merged:
                    data = merged
            refskel_extra_cache[gender] = data
        return refskel_extra_cache[gender]

    def _leaf_bones_for(used_names, gender):
        """swayfix WP(dev#19、issue#19): used_names(重み>0で実際に参照される
        ボーン名集合)がある家系のcloth_chainと交差するなら、その家系の
        リーフボーン名(resolve_sway_leaf())の集合を返す(used_names自体は
        含まない、追加分のみ)。

        リーフボーン自体は無重みのため_dump_used_bone_names()には現れないが
        (ここがこの関数を新設した理由)、PROPOSAL §7.2-7.4のとおり
        DummyBoneLength=0化後は実子として存在しないとKawaiiPhysicsの外挿が
        壊れる——「そのavatarがこの家系のsway_cloth donorを実際に使っている」
        ことをused_namesとcloth_chainの交差で判定し、使っているときだけ
        リーフを追加要求する(sway未使用ジョブでは交差が常に空になり
        既定不変、④の根拠と同型)。

        earleaf WP(dev#19、issue#19、work\\rd_19_leafcheck\\RESULT.md欠陥A):
        fam["chain"]だけでなくfam.get("siblings")(L/R対称家系ではR側の
        実チェーン)も交差判定に含める。resolve_leaf(fam, gender, chain=...)へ
        siblings側のchainを渡すことで、siblings末尾が"_l"/"_r"を持つ家系
        (HeadEquip062_ear等)ではR側専用のleaf名を導出できる(旧実装は
        fam["chain"](常にL側/無側)しか見ておらず、R側donorだけがウェイトを
        受けたケースでR側リーフが要求されずに欠落しうる構造的な穴だった)。
        siblingsが左右接尾辞を持たない家系(Ancient001のwaistClothB/C等)では
        resolve_leaf()が無変更のbase leafを返すため、by_bone上で重複キー
        (同一leaf)になるだけで無害・無退行。"""
        if gender not in leaf_needed_cache:
            try:
                syms = sway_assign._load_step02_symbols()
                families = syms["SWAY_DONOR_FAMILIES"]
                resolve_leaf = syms["resolve_sway_leaf"]
            except Exception as e:
                print(f"[{TAG}][WARN] refskel extend: could not load "
                      f"SWAY_DONOR_FAMILIES for leaf-bone detection ({e}); "
                      "leaf bones will not be auto-registered")
                leaf_needed_cache[gender] = (set(), {})
            else:
                by_bone = {}
                for fam in families.values():
                    gendered = fam.get("gendered", True)
                    prefix = ("M_" if gender == "Male" else "F_") if gendered else ""
                    chain = [f"{prefix}{b}" for b in fam["chain"]]
                    leaf = resolve_leaf(fam, gender, chain=chain)
                    # dev#19 leaf2refskel WP(2026-08-14、issue#19、
                    # work\rd_19_fixedbuild\build_f1.log 243行の実測が正本):
                    # weight-direct-assign WPが旧leaf(spec["leaf"])を可動donor
                    # へ転用する「spillover」を起こす家系(leaf2持ち)では、
                    # 転用後の旧leafは無重みのプレースホルダではなく実ウェイト
                    # 持ちの通常donorボーンになる——Blender側
                    # resolve_sway_chain_entries()の判定
                    # (len(sway_bones)==len(cloth_chain)+1)をここでbpy非依存に
                    # 再実装する代わりに、その判定の**帰結**を直接
                    # used_names(実測dumpの重み付きボーン集合)から読み取る:
                    # spilloverが起きていれば旧leaf名は必ずused_namesに現れる
                    # (実ウェイトが乗るため)。この経路のleaf_wantedを新しい
                    # 無重みの実リーフ(leaf2、例:tail_07)へ差し替える
                    # ——差し替えないと旧leaf(例:tail_06)が要求され続け、
                    # 旧leafは既に必須(重み付き)経路で登録済みのため
                    # already_have判定でleaf_missingが空になり、leaf2が
                    # 一度もRefSkeletonへ登録されない(実害: 揺れの回転
                    # 凍結点がウェイト持ちのtail_06になりW字が悪化)。
                    leaf2_raw = fam.get("leaf2")
                    leaf2 = None
                    if leaf2_raw and leaf and leaf in used_names:
                        expanded_chain = chain + [leaf]
                        leaf2 = resolve_leaf(fam, gender, chain=expanded_chain,
                                              key="leaf2")
                    if leaf2:
                        by_bone.setdefault(leaf2, set()).update(expanded_chain)
                    elif leaf:
                        by_bone.setdefault(leaf, set()).update(chain)
                    siblings = fam.get("siblings") or []
                    if siblings:
                        sib_chain = [f"{prefix}{b}" for b in siblings]
                        sib_leaf = resolve_leaf(fam, gender, chain=sib_chain)
                        if sib_leaf:
                            by_bone.setdefault(sib_leaf, set()).update(sib_chain)
                leaf_needed_cache[gender] = (set(by_bone), by_bone)
        _all_leaves, by_bone = leaf_needed_cache[gender]
        return {leaf for leaf, chain in by_bone.items() if chain & used_names}

    ext_src_dir = os.path.join(os.path.dirname(variant_dir), "refskel_ext_src")
    overrides = {}
    for uexp_path, uasset_path in pairs:
        gender = gender_of(os.path.basename(uexp_path))
        used_names = used_names_by_gender.get(gender) or set()
        if not used_names:
            continue
        try:
            refskel_full = core.load_refskel(uasset_path)
            bone_names = set(refskel_full)
        except Exception as e:
            print(f"[{TAG}][WARN] refskel extend: could not read RefSkeleton "
                  f"of {os.path.basename(uasset_path)} to check for sway "
                  f"donor bones ({e}); leaving it as-is")
            continue

        missing = sorted(used_names - bone_names)
        refskel_extra = _refskel_extra_for(gender)
        new_bones = []
        resolved_names = set()
        if missing:
            if refskel_extra is None:
                # 拡張材料が無い(該当ファミリーがsway_extra_familyとして
                # 抽出されていない等)。新しい失敗モードを作らず、後段の
                # build_and_validate()が従来どおり
                # 「bone name(s) not present in RefSkeleton」で失敗するに任せる。
                continue
            try:
                chain = vp_refskel_extend.resolve_missing_bone_chain(
                    refskel_extra, missing, bone_names)
                new_bones = vp_refskel_extend.family_bones_from_refskel(refskel_extra, chain)
                resolved_names = set(chain)
            except vp_refskel_extend.RefskelExtendError as e:
                print(f"[{TAG}][WARN] refskel extend: cannot resolve sway donor "
                      f"bones {missing} for {os.path.basename(uasset_path)}: {e}")
                continue

        # swayfix WP(dev#19、issue#19): リーフボーン(無重み)はbest-effort。
        # 上の必須(重み付き)解決とは独立に試み、失敗してもnew_bones(必須分)
        # は活かす——旧来のテスト・運用(リーフ材料が無いvanilla_dir)を壊さない。
        if refskel_extra is not None:
            already_have = bone_names | resolved_names | {b["name"] for b in new_bones}
            leaf_wanted = _leaf_bones_for(used_names, gender)
            leaf_missing = sorted(n for n in leaf_wanted if n not in already_have)
            if leaf_missing:
                try:
                    leaf_chain = vp_refskel_extend.resolve_missing_bone_chain(
                        refskel_extra, leaf_missing, already_have)
                    new_bones += vp_refskel_extend.family_bones_from_refskel(
                        refskel_extra, leaf_chain)
                except vp_refskel_extend.RefskelExtendError as e:
                    print(f"[{TAG}][WARN] refskel extend: cannot resolve sway "
                          f"donor leaf bone(s) {leaf_missing} for "
                          f"{os.path.basename(uasset_path)}: {e} (non-fatal, "
                          "leaf placement skipped for this SK)")

        # dev#1508 hubwire final(未解決1修正、work\wp_rootbone_fix_notes\
        # PROGRESS.md「未解決1」): missingとして検出されない(=対象SK自身の
        # RefSkeletonに元々存在する)骨でも、ハブ配線計画(refskel_extra、
        # `sway_hub.refskel_dict_for_wiring()`の出力)に載っている骨は、
        # 親をハブ配線計画どおりに上書きする。旧実装は「対象SKに無い場合
        # のみ」新規登録し、既存donor骨(donor骨として選ばれた骨がたまたま
        # 注入先SK自身の元のRefSkeletonに既に実在するケース——同じ家系由来の
        # 装備SKへ、その家系自身の骨がdonorとして注入される場合等)は一切
        # 上書きされず旧親(観測: root)のまま残っていた。実位置(FTransform.
        # pos)・回転はここでは変更しない——build_avatar_variant.
        # compute_patched_local_positions/rotations()がchibi_bone_world_head/
        # quat機構で、パッチ後のこの新しい親を読んでworld目標位置から
        # ローカル値を再計算する(親が先に正しくなっていることが前提)。
        reparent_needed = []
        if refskel_extra is not None:
            for name in sorted(bone_names & set(refskel_extra)):
                want_parent = refskel_extra[name]["parent"]
                cur_parent = refskel_full.get(name, {}).get("parent")
                if want_parent is not None and want_parent != cur_parent:
                    reparent_needed.append((name, want_parent))

        if not new_bones and not reparent_needed:
            continue

        rel_uexp = os.path.relpath(uexp_path, template).replace("\\", "/")
        rel_uasset = rel_uexp[:-5] + ".uasset"
        out_uexp = os.path.join(ext_src_dir, rel_uexp)
        out_uasset = os.path.join(ext_src_dir, rel_uasset)

        cur_uexp_path, cur_uasset_path = uexp_path, uasset_path
        if new_bones:
            info = vp_refskel_extend.extend_sk_refskeleton(
                uasset_path, uexp_path, new_bones, out_uasset, out_uexp)
            # swayfix WP(dev#19): 必須(重み付き)分とリーフ(best-effort)分を
            # 1回のextend_sk_refskeleton()呼び出しへ合流させたため、ログは
            # 個別のresolve_missing_bone_chain()結果(旧`chain`変数)ではなく、
            # 実際にnew_bonesへ入った全ボーン名を出す(どちらの経路由来かは
            # 上のresolved_names/leaf_missingログで別途わかる)。
            print(f"[{TAG}] refskel extend: {os.path.basename(uasset_path)} "
                  f"+{len(new_bones)} bone(s) ({info['n_bones_before']} -> "
                  f"{info['n_bones_after']}) bones={[b['name'] for b in new_bones]}")
            cur_uexp_path, cur_uasset_path = out_uexp, out_uasset

        n_reparented = 0
        if reparent_needed:
            with open(cur_uexp_path, "rb") as f:
                cur_uexp_bytes = f.read()
            reparented_names = []
            for name, want_parent in reparent_needed:
                try:
                    cur_uexp_bytes, _rinfo = vp_refskel_extend.reparent_existing_bone(
                        cur_uexp_bytes, cur_uasset_path, name, want_parent)
                    reparented_names.append((name, want_parent))
                    n_reparented += 1
                except vp_refskel_extend.RefskelExtendError as e:
                    # トポロジ制約(親は常に子より前の配列インデックス)は
                    # content-only patchでは原理的に越えられない場合がある
                    # (例: 新規追加ボーンを親にしたい既存の早い配列位置の骨)。
                    # 検出→出荷+警告(このプロジェクトの既定方針)——ブロックせず、
                    # この骨だけ旧親のまま残す(旧実装と同じ状態、退行ではない)。
                    print(f"[{TAG}][WARN] refskel extend: cannot reparent existing "
                          f"donor bone {name!r} -> {want_parent!r} for "
                          f"{os.path.basename(uasset_path)} (topology constraint): "
                          f"{e} (non-fatal, bone kept at its original parent)")
            if n_reparented:
                os.makedirs(os.path.dirname(out_uexp) or ".", exist_ok=True)
                with open(out_uexp, "wb") as f:
                    f.write(cur_uexp_bytes)
                if cur_uasset_path != out_uasset:
                    # new_bonesが空でreparentのみのケース: uassetはreparentで
                    # 変化しない(NameMap追加なし)ので、元のuassetをそのまま
                    # out_uasset側へコピーする(overridesはout_uexp/out_uasset
                    # の対になったペアを期待するため)。
                    os.makedirs(os.path.dirname(out_uasset) or ".", exist_ok=True)
                    shutil.copyfile(cur_uasset_path, out_uasset)
                print(f"[{TAG}] refskel extend: {os.path.basename(uasset_path)} "
                      f"reparented {n_reparented} existing donor bone(s): "
                      f"{reparented_names}")

        if not new_bones and not n_reparented:
            continue
        overrides[rel_uexp] = (out_uexp, out_uasset)
    if overrides:
        print(f"[{TAG}] refskel extend: {len(overrides)} SK(s) extended for sway donor bones")
    return overrides


# === dev#288(L2/L2b重畳): Phase 2(sk_injection)とPhase 2b/2c/2d(overrides) ===
# NOTES.md(work\speed_mission\l2l2b\NOTES.md)の入出力独立性の列挙どおり、
# 書き込み先(sk_injection: variant_dir配下 Player/Outfit/... / overrides:
# tex_dir配下 Player/ModelMaterials/MainShader/... とメモリ上のdict)は互いに
# 素で、共有可変状態も無い。ロジック自体は無変更、元main()の該当ブロックを
# そのまま関数へ切り出しただけ(die()呼び出し・print文・変数名も同一)。
def _run_sk_injection(template, requested_genders, variant_dir, dumps, requested_equipment=None):
    """Phase 2: 衣装SK 60体へ性別別に実アバターを注入する。戻り値: targets_rel
    (注入に成功したSKのtemplate相対パス列、Phase 3のreplace_map構築に使う)。

    dev#165第2期(2026-08-08): requested_equipment(vp_equipment_filter.
    normalize_equipment_filter()済みの集合、既定None=絞り込み無し)を渡すと、
    選択されなかった装備コードのSKもgender_excludedと同じPhase3バニラ
    コピー経路に乗せる(メッシュを注入しない)。requested_equipment=None
    (省略時)は既存のkept/excluded列と一字一句同じになる(④無退行の根拠)。
    マテリアル側(t00/t01統一)の絞り込みはlive_template.py側(テンプレート
    組み立て時)で別途完結しており、ここでは関知しない。"""
    print(f"[{TAG}] === Phase 2: injecting real avatar into outfit SKs ===")
    outfit_root = os.path.join(template, "Player", "Outfit")
    pairs = collect_targets(outfit_root)
    # U40(T3設計転換): live_template.pyがPlayer/Outfit/配下にMI_*(バニラMI
    # 差し替え、SkeletalMeshではない)を追加で置くようになったため、
    # collect_targets(拡張子のみでの機械的な.uexp/.uassetペア収集、
    # research\ue_exit\build_avatar_variant_all.py、無改変維持)がそれも
    # 「衣装SK」として拾ってしまう。MI_*はメッシュではなくindex bufferを
    # 持たないため実アバター注入は必ず失敗する(意図通り、対象外)。
    # ファイル名がSK_で始まるものだけを注入対象とし、MI_*はここで除外して
    # Phase 3の「残りはテンプレートのままコピー」経路に委ねる
    # (=T3パッチ済みのバイト列がそのまま最終pakへ入る)。
    before_filter = len(pairs)
    pairs = [(u, a) for u, a in pairs if os.path.basename(u).startswith("SK_")]
    n_excluded_mi = before_filter - len(pairs)
    if n_excluded_mi:
        print(f"[{TAG}] T3: excluding {n_excluded_mi} MI_* (vanilla MI replacement, "
              f"non-mesh) from real-avatar injection targets (included in the pak as-is from the template)")
    # U50(2026-07-25、責任者裁定「コラボ系アイテムは非対応です」):
    # 除外対象のSKには実アバターを注入しない。注入しなければ Phase 3 の
    # 「残りはテンプレートのままコピー」経路に乗り、**バニラの装備がそのまま
    # 出る**(方針「失敗するにしても優雅に失敗する」)。
    # 正本は pipeline\py\vp_exclusions.py(そこへ足せば全経路に効く)。
    kept = []
    excluded = []
    # dev#165(2026-07-30): 「--gendersで要求されていない性別のSK」を、
    # 既存のdenylist除外(コラボ衣装)と全く同じPhase3バニラコピー経路に
    # 乗せる。新しいフォールバック機構を作らず、preflight_pak.py G3/G4/G5が
    # 既に許容している「注入されずバニラのままpakに入る」経路を再利用する
    # ことで最小の変更にとどめる。既定(genders未指定=Male,Female両方要求)
    # ではgender_of(...)の結果は必ずrequested_gendersに含まれるため、この
    # 分岐には一切入らず、既存のkept/excluded列と一字一句同じになる。
    gender_excluded = []
    # dev#165第2期(2026-08-08): 「--equipment-filterで選択されなかった装備の
    # SK」も同じPhase3バニラコピー経路に乗せる。requested_equipmentがNone
    # (既定)ならこの分岐には一切入らず、既存のkept/excluded/gender_excluded
    # 列と一字一句同じになる。
    equipment_excluded = []
    for u, a in pairs:
        if vp_exclusions.is_excluded(u):
            excluded.append(u)
        elif gender_of(os.path.basename(u)) not in requested_genders:
            gender_excluded.append(u)
        elif (requested_equipment is not None
              and vp_equipment_filter.equipment_code(os.path.basename(u)) not in requested_equipment):
            equipment_excluded.append(u)
        else:
            kept.append((u, a))
    pairs = kept
    # dev#19 R3統合(rd_19_refskel PROPOSAL手順4): kept確定直後・注入タスク
    # 組み立て前に、sway donorが要求する骨のRefSkeleton事前拡張を解決する
    # (詳細は_refskel_extend_overrides()のdocstring参照)。
    _t_refskel_ext = time.time()
    refskel_ext_overrides = _refskel_extend_overrides(pairs, template, variant_dir, dumps)
    print(f"[{TAG}] refskel extend: overrides computed in "
          f"{time.time() - _t_refskel_ext:.1f}s ({len(refskel_ext_overrides)} SK(s))")
    if excluded:
        print(f"[{TAG}] {len(excluded)} SK(s) not injected (unsupported/collab items) "
              f"= vanilla equipment will appear as-is:")
        for u in excluded:
            print(f"[{TAG}]   - {os.path.basename(u)} "
                  f"({vp_exclusions.excluded_reason(u)})")
    if gender_excluded:
        print(f"[{TAG}] {len(gender_excluded)} SK(s) not injected "
              f"(gender not in --genders={sorted(requested_genders)}) "
              f"= vanilla equipment will appear as-is:")
        for u in gender_excluded:
            print(f"[{TAG}]   - {os.path.basename(u)}")
    if equipment_excluded:
        print(f"[{TAG}] {len(equipment_excluded)} SK(s) not injected "
              f"(equipment code not in --equipment-filter="
              f"{sorted(requested_equipment) if requested_equipment else []}) "
              f"= vanilla equipment will appear as-is:")
        for u in equipment_excluded:
            print(f"[{TAG}]   - {os.path.basename(u)}")
    print(f"[{TAG}] target SK: {len(pairs)}")
    # rd_120 5.1: ProcessPoolExecutorでpairsを並列注入する。
    # 順序非依存の根拠(PROPOSAL 3節、build_and_validate()自体は無改変):
    #   各SKの入力(uexp_path/uasset_path/dump)は互いに独立、出力(out_uexp/
    #   out_uasset)も他SKのファイルに一切触れないSK専用パス。並列化後の
    #   出力を束ねるPhase 3(下記)は`targets_rel`の"集合"だけを見て
    #   replace_mapを作り、実ファイル列挙順はテンプレート側のディレクトリ順
    #   (vp_pakwrite.collect_files)であって注入ループの実行順ではないため、
    #   Phase2をどんな順序・並行度で実行しても最終pakはバイト完全一致する。
    #   vp_parallel.run_pool_ordered()はexecutor.map()を使い、結果を**入力順
    #   (=pairsの列挙順)**で返すため、下のprint順・n_fail集計・targets_rel
    #   構築順は逐次実行時と1文字も変わらない。
    tasks = []
    for uexp_path, uasset_path in pairs:
        rel_uexp = os.path.relpath(uexp_path, template).replace("\\", "/")
        gender = gender_of(os.path.basename(uexp_path))
        out_uexp = os.path.join(variant_dir, rel_uexp)
        out_uasset = out_uexp[:-5] + ".uasset"
        # dev#19 R3統合: rel_uexp(=最終pak内パス、out_uexp/out_uasset算出の
        # 基準)は常に元のtemplate上のパスから求める。RefSkeleton拡張が
        # 必要だったSKだけ、注入の「読み込み元」(src_uexp/src_uasset)を
        # refskel_ext_srcの拡張済みコピーへ差し替える(出力先パスは不変)。
        src_uexp, src_uasset = refskel_ext_overrides.get(rel_uexp, (uexp_path, uasset_path))
        tasks.append((src_uexp, src_uasset, gender, out_uexp, out_uasset, rel_uexp))

    n_workers = _default_injection_workers()
    print(f"[{TAG}] injecting {len(tasks)} SK(s) with {n_workers} worker process(es) "
          f"(override via D2P_INJECT_WORKERS)")
    _t_inject_pool = time.time()
    injection_results = _run_injection_pool(tasks, n_workers, dumps)
    print(f"[{TAG}] dev#1650 timing: injection pool (parallel) "
          f"{time.time() - _t_inject_pool:.1f}s")

    targets_rel = []
    n_fail = 0
    gender_counts = {"Male": 0, "Female": 0}
    for rel_uexp, gender, ok, errs, info in injection_results:
        gender_counts[gender] += 1
        status = "OK" if ok else "FAIL"
        # dev#1072: 容量膨張の問い合わせ(実例K4XRB4DK)をログだけで診断できる
        # ようにするため、DVB(FDuplicatedVerticesBuffer)最大クラスタサイズを
        # 併記する(build_avatar_variant.build_duplicated_vertices()のdocstring
        # 参照: サイズkのクラスタはO(k^2)でDupVertDataを膨張させる)。
        print(f"[{TAG}] [{status}] {rel_uexp} gender={gender} "
              f"numv={info.get('num_vertices')} tri={info.get('num_triangles')} "
              f"dvb_max_cluster={info.get('section_dvb_max_cluster_size')}" +
              (f" errs={errs}" if errs else ""))
        if not ok:
            n_fail += 1
        else:
            targets_rel.append(rel_uexp)
    if n_fail:
        die(f"outfit SK injection failed for {n_fail} (see log above for details)")
    print(f"[{TAG}] outfit SK injection: {len(targets_rel)}/{len(pairs)} succeeded "
          f"(gender_counts={gender_counts})")
    print(f"[{TAG}] === Phase2Subphase: sk_injection done ===")
    return targets_rel


def _run_overrides(args, template, work):
    """Phase 2b/2c/2d: テクスチャ/マテリアル/シャドウリフトMIの差し替えを
    準備する。戻り値: (tex_replace, mat_override, mi_override)(いずれも
    {pak内相対パス: 差し替え元ファイルパス} のdict、Phase 3のreplace_map
    構築に使う)。"""
    print(f"[{TAG}] === Phase2Subphase: overrides start ===")
    # === Phase 2b(U6-T3ストレッチ): テクスチャ注入 ===
    tex_dir = os.path.join(work, "tex")
    tex_args = {"body": args.tex_body, "parka": args.tex_parka}
    tex_alpha_coverage = {"body": args.tex_body_alpha_coverage,
                           "parka": args.tex_parka_alpha_coverage}
    tex_replace = {}
    for slot, png_path in tex_args.items():
        if not png_path:
            continue
        png_path = os.path.abspath(png_path)
        if not os.path.exists(png_path):
            die(f"--tex-{slot} does not exist: {png_path}")
        rel = TEX_SLOT_REL[slot]
        template_uexp = os.path.join(template, *rel.split("/"))
        out_uexp = os.path.join(tex_dir, rel)
        print(f"[{TAG}] === Phase 2b: texture injection ({slot}: {png_path}) ===")
        info = vp_texinject.inject_texture_file(
            template_uexp, png_path, out_uexp,
            alpha_coverage=tex_alpha_coverage[slot], gain=args.tex_gain)
        print(f"[{TAG}]   {rel}: {info['pixel_format']} {info['size_x']}x{info['size_y']} "
              f"PSNR={info['psnr']:.2f}dB gain={info['gain']:.4f}"
              f"(version={info['gain_version']})")
        tex_replace[rel] = out_uexp

    # === Phase 2c(U13): マテリアル差し替え(バリアント選択+shadow_liftパッチ済み) ===
    mat_override = {}
    if args.mat_override_dir:
        mo_dir = os.path.abspath(args.mat_override_dir)
        for fn in sorted(os.listdir(mo_dir)):
            rel = f"Player/ModelMaterials/MainShader/{fn}"
            mat_override[rel] = os.path.join(mo_dir, fn)
        print(f"[{TAG}] material replacement: {len(mat_override)} ({mo_dir})")

    # === Phase 2d(U50-fast): 影の濃さ(shadow_lift)を焼き込んだ統一MIの差し替え ===
    # Phase 2c と同じ「後段でMIファイルを差し替える」形。違いは木構造で置かれて
    # いる点だけ(相対パスがそのままpak内パスになる)。これにより shadow_lift は
    # ライブテンプレート(879ファイル/約700MB)の再構築を必要としない。
    mi_override = {}
    if args.mi_override_dir:
        mi_dir = os.path.abspath(args.mi_override_dir)
        for dirpath, _d, filenames in os.walk(mi_dir):
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                rel = os.path.relpath(p, mi_dir).replace("\\", "/")
                mi_override[rel] = p
        print(f"[{TAG}] shadow-lift MI replacement: {len(mi_override)} ({mi_dir})")
    print(f"[{TAG}] === Phase2Subphase: overrides done ===")
    return tex_replace, mat_override, mi_override


def _run_phase2_overlap(template, requested_genders, variant_dir, dumps, args, work,
                         requested_equipment=None):
    """dev#288(L2/L2b重畳): Phase 2(sk_injection)とPhase 2b/2c/2d(overrides)を
    `vp_parallel.run_pair_parallel()`で並列実行する。戻り値:
    (targets_rel, (tex_replace, mat_override, mi_override))。

    独立性の根拠はNOTES.md(work\\speed_mission\\l2l2b\\NOTES.md)参照:
    書き込み先(variant_dir配下 Player/Outfit/... と tex_dir配下
    Player/ModelMaterials/MainShader/...)が互いに素で、共有可変状態も無い。

    run_pair_parallel()はThreadPoolExecutorのcontext managerがshutdown(wait=True)
    するため、片方が例外(die()のSystemExit含む)を投げてももう片方の処理は
    最後まで走り切ってから例外が呼び出し元(このtry無しの呼び出しならmain())へ
    伝播する(rd_120と同じ既存trade-off)。例外メッセージは元のdie()呼び出しを
    そのまま使うため、失敗内容が他方のものと誤認されることはない。

    dev#165第2期: requested_equipment(既定None)はそのまま_run_sk_injection
    へ渡すだけ(キーワード引数、既定Noneなら_run_sk_injectionも従来どおり)。"""
    sk_fn = lambda: _run_sk_injection(  # noqa: E731
        template, requested_genders, variant_dir, dumps, requested_equipment)
    ov_fn = lambda: _run_overrides(args, template, work)  # noqa: E731
    targets_rel, overrides_result = vp_parallel.run_pair_parallel(
        lambda f: f(), [sk_fn, ov_fn])
    return targets_rel, overrides_result


def _run_dt_patch(job_json, targets_rel, work):
    """dev#1198 WP-B5b: 頭部問題根治の最終ピース(DT同梱の本配線)。

    ユーザーのPalworld pakからバニラDT
    (DT_CharacterCreationMeshPresetTable_Equipments .uasset/.uexp)を実行時
    抽出し、実際に注入が成功したSK集合(targets_rel)からTrue化すべき行を
    機械選定(vp_dt_row_select)してパッチ(dt_flag_patcher)する。

    これはオプトインではなく既定動作(全ビルドに常時適用)。抽出・パース・
    パッチのいずれかが失敗したら**変換全体を停止する**(黙ってDT同梱を
    スキップして変換を続けることはしない — 頭部問題の無警告再発を防ぐため、
    PROPOSAL §2.3)。

    戻り値: [(abs_path, rel_path_in_common_mount), ...] の2要素リスト
    (uasset/uexp)。呼び出し元がこれをcommon_mount_files(final_filesを
    to_common_mount_body_files()で変換した後のリスト)へ直接連結する
    (DT_PREFIXはBODY_PREFIXと異なる系統のため、to_common_mount_body_files()
    は通さない — PROPOSAL §5.1 / WP-B5aの申し送りどおり)。
    """
    print(f"[{TAG}] === Phase 3.5: DT flag patch (dev#1198 head/hair fix) ===")
    if not os.path.exists(job_json):
        die(f"cannot extract vanilla {DT_PACKAGE_NAME} for the dev#1198 head/hair "
            f"fix: job.json not found: {job_json}")
    job = core.load_job(job_json)
    pak = job["paths"].get("palworld_pak")
    if not pak or not os.path.exists(pak):
        detail = job.get("_palworld_pak_search_error") or (
            f"Palworld's pak was not found: {pak}\n"
            "Please set paths.palworld_pak in job.json")
        die(f"cannot extract vanilla {DT_PACKAGE_NAME} for the dev#1198 head/hair "
            f"fix: {detail}")

    want = [DT_VANILLA_REL + ext for ext in (".uasset", ".uexp")]
    try:
        mount, entries = core.read_pak_entries(pak)
    except Exception as e:
        die(f"failed to read Palworld's pak index while extracting vanilla "
            f"{DT_PACKAGE_NAME}: {e}")
    missing = [p for p in want if p not in entries]
    if missing:
        die(f"vanilla {DT_PACKAGE_NAME} not found in Palworld's pak "
            f"(missing: {missing}). This can happen after a Palworld update "
            "moved/renamed this DataTable -- refusing to guess, stopping the "
            "conversion rather than silently shipping without the dev#1198 "
            "head/hair fix (PROPOSAL section 2.3).")
    try:
        extracted = pak_live_extract.extract_files(pak, want)
    except Exception as e:
        die(f"failed to extract vanilla {DT_PACKAGE_NAME} from Palworld's pak: {e}")

    dt_dir = os.path.join(work, "dt_patch")
    os.makedirs(dt_dir, exist_ok=True)
    uasset_path = os.path.join(dt_dir, DT_PACKAGE_NAME + ".uasset")
    uexp_path = os.path.join(dt_dir, DT_PACKAGE_NAME + ".uexp")
    vanilla_uasset_bytes = extracted[DT_VANILLA_REL + ".uasset"]
    with open(uasset_path, "wb") as f:
        f.write(vanilla_uasset_bytes)
    uexp_bytes = extracted[DT_VANILLA_REL + ".uexp"]

    try:
        names = core.read_names(uasset_path)
        dt_rows = vp_dt_row_select.load_dt_rows_from_uexp(uexp_bytes, names)
    except dt_flag_patcher.DtStructureError as e:
        die(f"vanilla {DT_PACKAGE_NAME} has an unexpected byte structure "
            "(possible Palworld update) -- refusing to guess, stopping the "
            f"conversion rather than silently shipping without the dev#1198 "
            f"head/hair fix: {e}")

    selected = vp_dt_row_select.select_full_body_equipment_rows(dt_rows, targets_rel)
    preview = selected[:10]
    print(f"[{TAG}] DT row selection (dev#1198): {len(selected)} row(s) -> "
          f"bIsFullBodyEquipment=True ({preview}"
          f"{', ...' if len(selected) > len(preview) else ''})")
    if not selected:
        print(f"[{TAG}][WARN] no DT row matched the injected SK set -- the "
              "dev#1198 head/hair fix will not flip any row in this build "
              "(expected if no outfit SK was injected)")

    if selected:
        edits = {name: True for name in selected}
        try:
            patched_uexp = dt_flag_patcher.patch_full_body_equipment_flags(
                uexp_bytes, names, edits)
        except (dt_flag_patcher.DtStructureError, ValueError) as e:
            die(f"failed to patch vanilla {DT_PACKAGE_NAME} (dev#1198): {e}")
        # dev#1198 WP-B5b-fix: .uexpの可変長編集(False->True 1行につき+1バイト
        # 挿入)で生じたサイズ差分を、.uasset側のSerialSize/BulkDataStartOffset
        # へ機械的に反映する。ここを怠ると、UEのロード時サイズ照合で
        # 「LowLevelFatalError ... Serial size mismatch」となり起動直後に
        # 即死する(根治対象のクラッシュ、work/lab1_crash_triage/
        # parse_export_table.pyで数値実証済み)。
        uexp_size_delta = len(patched_uexp) - len(uexp_bytes)
        try:
            patched_uasset_bytes = dt_flag_patcher.patch_uasset_serial_size(
                vanilla_uasset_bytes, uexp_size_delta)
        except dt_flag_patcher.DtStructureError as e:
            die(f"failed to patch vanilla {DT_PACKAGE_NAME}'s .uasset SerialSize "
                f"(dev#1198 WP-B5b-fix): {e}")
        with open(uasset_path, "wb") as f:
            f.write(patched_uasset_bytes)
        with open(uexp_path, "wb") as f:
            f.write(patched_uexp)
    else:
        # 選定行が無くてもDT2件は常に同梱する(バニラのまま=無変更)。
        # .uassetは上のwith open(uasset_path...)で既にバニラのまま書き出し済み。
        with open(uexp_path, "wb") as f:
            f.write(uexp_bytes)

    dt_rel_uasset = vp_pakwrite.normalize_rel(
        DT_PACKAGE_NAME + ".uasset", vp_pakwrite.DT_PREFIX)
    dt_rel_uexp = vp_pakwrite.normalize_rel(
        DT_PACKAGE_NAME + ".uexp", vp_pakwrite.DT_PREFIX)

    # リグレッション不可能性: COMMON_MOUNT+DT_PREFIXの実効パスがバニラ正パスと
    # 一致することを構築前に機械アサートする(PROPOSAL section 5.1、
    # work\rd_1198_dtreach で実証済みの手法をそのまま踏襲)。
    expected_uasset = "../../../" + DT_VANILLA_REL + ".uasset"
    expected_uexp = "../../../" + DT_VANILLA_REL + ".uexp"
    eff_uasset = vp_pakwrite.effective_path(vp_pakwrite.COMMON_MOUNT, dt_rel_uasset)
    eff_uexp = vp_pakwrite.effective_path(vp_pakwrite.COMMON_MOUNT, dt_rel_uexp)
    if eff_uasset != expected_uasset or eff_uexp != expected_uexp:
        die("internal error: DT effective path does not match the vanilla "
            f"physical path (dev#1198): {eff_uasset!r} != {expected_uasset!r} "
            f"or {eff_uexp!r} != {expected_uexp!r}")

    print(f"[{TAG}] === Phase 3.5: DT flag patch done "
          f"({len(selected)} row(s) patched) ===")
    return [(uasset_path, dt_rel_uasset), (uexp_path, dt_rel_uexp)]


def _run_sway_abp_patch(job_json, work):
    """dev#19(揺れものpak生成の製品パイプライン結線): job["sway_intensity"]
    ("hard"/"normal"/"soft")に応じて、`pipeline\\py\\sway_abp_templates\\`の
    著作済みABPテンプレへ硬さプリセットをUE非依存でバイトパッチし、
    common_mount_files へ合流させるための (abs_path, rel) リストを返す。

    _run_dt_patch() と同じ「常時呼ぶが内部で条件判定してno-opになる」設計
    (job["sway_intensity"]キー欠落・"none"・未知値、またはテンプレ未同梱
    (pipeline\\py\\sway_abp_templates\\specs\\が空/無い)の場合は
    sway_abp_build.sway_abp_pak_entries()が空リストを返し、本関数もそのまま
    空リストを返す=pak出力は本WP適用前と完全に一致する)。

    テンプレの構造(ノード数・root_bone列・ファイル名)はここでは一切
    ハードコードしない——`sway_abp_build.py`がspecs/*.jsonを動的に読む設計
    (sway_abp_templates/README.md参照)。想定外のテンプレ構造・パッチ失敗は
    sway_abp_build.SwayAbpBuildError / sway_abp_patcher.AbpStructureError を
    ここで捕捉し、DT flag patchと同じ「黙ってスキップせず変換全体を止める」
    方針でdie()する。
    """
    if not os.path.exists(job_json):
        die(f"cannot resolve sway ABP settings: job.json not found: {job_json}")
    job = core.load_job(job_json)
    intensity = job.get("sway_intensity")
    if sway_abp_build.hardness_key_for_intensity(intensity) is None:
        print(f"[{TAG}] sway_intensity={intensity!r}: sway ABP patch skipped "
              "(disabled/unknown, pak output unaffected)")
        return []

    # dev#1508 W2a(2026-08-16): step02_retarget.py(Blenderプロセス、骨配線)が
    # job_dir/converted/配下に書き出したノード単位override(グループごとの
    # 量子化プリセット値+limit_angle写し)を読む。ファイルが無い場合
    # (sway_enable無効だった/古いキャッシュ等)は空dict=旧来の全ノード一律
    # 挙動のまま(完全no-opフォールバック、sway_abp_build.build_spec_nodes()
    # のnode_overrides=None相当)。
    node_overrides = {}
    overrides_path = os.path.join(
        job["job_dir"], "converted", sway_allocator_wire.NODE_OVERRIDES_FILENAME)
    if os.path.isfile(overrides_path):
        try:
            with open(overrides_path, encoding="utf-8") as f:
                node_overrides = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[{TAG}][WARN] failed to read sway node overrides "
                  f"({overrides_path}): {e} -- falling back to uniform hardness")
            node_overrides = {}

    print(f"[{TAG}] === Phase 3.6: sway ABP patch (dev#19/dev#1508, sway_intensity="
          f"{intensity!r}, {len(node_overrides)} node override(s)) ===")
    out_dir = os.path.join(work, "sway_abp")
    try:
        entries = sway_abp_build.sway_abp_pak_entries(
            job, out_dir, node_overrides=node_overrides)
    except sway_abp_build.SwayAbpBuildError as e:
        die(f"failed to build sway ABP pak entries (dev#19): {e}")
    if not entries:
        print(f"[{TAG}][WARN] sway_intensity={intensity!r} but no sway ABP "
              "template was found under pipeline\\py\\sway_abp_templates\\ "
              "-- sway ABP patch skipped, pak output unaffected")
        return []
    n_templates = len(entries) // 2
    print(f"[{TAG}] sway ABP patch done: {n_templates} template(s), "
          f"{len(entries)} file(s) (hardness={sway_abp_build.hardness_key_for_intensity(intensity)!r})")
    return entries


def _run_sway_hub_reparent_patch(job_json, work):
    """dev#1508 W2a-2(汎用ハブ配線、指揮者指示書「本体」項目2「pak結線」):
    `job_dir/converted/sway_hub_reparent.json`(`sway_hub_placement.
    plan_reparent_steps()`の出力を`sway_shared_skeleton.ReparentStep`相当の
    json配列へシリアライズしたもの、将来の`step02_retarget.py`結線が書き
    出す想定——本WPではまだ書き出されないため、常にファイル無し=no-op)が
    存在すれば、ユーザー自身のPalworldインストールから共有Skeleton
    (`SK_PalHuman_Skeleton.uasset/uexp`)をその場ライブ抽出し
    (`pak_live_extract`、`_run_dt_patch()`と同じ「著作物を配布物に含めない」
    既存原則を踏襲)、`sway_shared_skeleton.apply_reparent_chain()`で
    「内容だけ」reparentパッチしてcommon_mount_filesへ合流させるための
    (abs_path, rel)リストを返す。

    共有Skeletonは通常の426件vanillaテンプレ(`noue_template_manifest.json`)
    にも既存のreplace_map系(tex_replace/mat_override/targets_rel)にも
    含まれない資産——`_run_sway_abp_patch()`/`_run_dt_patch()`と同じ
    「常時呼ぶが内部で条件判定してno-opになる」設計の**追加**entryとして
    common_mount_filesへ合流させる(既存のreplace_map/all_filesとの
    rel_path重複は発生しない、build_pak()はrel_path重複を検出しないため
    重複させると壊れる——重複させない設計であることが安全性の前提)。

    ファイルが無い(=このWP時点でstep02がまだ書き出さない/揺れ無効/ハブ
    割当0件)場合は空リスト(pak出力は本WP適用前と完全に一致)。抽出・
    パッチのいずれかが失敗したら**変換全体を停止する**(`_run_dt_patch()`と
    同じ方針、黙ってスキップしない)。
    """
    if not os.path.exists(job_json):
        die("cannot resolve sway hub reparent settings (dev#1508 W2a-2): "
            f"job.json not found: {job_json}")
    job = core.load_job(job_json)
    reparent_path = os.path.join(
        job["job_dir"], "converted", SWAY_HUB_REPARENT_FILENAME)
    if not os.path.isfile(reparent_path):
        return []
    try:
        with open(reparent_path, encoding="utf-8") as f:
            steps_raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        die(f"failed to read sway hub reparent steps ({reparent_path}) "
            f"(dev#1508 W2a-2): {e}")
    if not steps_raw:
        return []

    print(f"[{TAG}] === Phase 3.7: sway hub shared-skeleton reparent patch "
          f"(dev#1508 W2a-2, {len(steps_raw)} step(s)) ===")

    pak = job["paths"].get("palworld_pak")
    if not pak or not os.path.exists(pak):
        detail = job.get("_palworld_pak_search_error") or (
            f"Palworld's pak was not found: {pak}\n"
            "Please set paths.palworld_pak in job.json")
        die(f"cannot extract vanilla {SWAY_HUB_SK_PACKAGE_NAME} for the "
            f"dev#1508 W2a-2 sway hub reparent patch: {detail}")

    want = [SWAY_HUB_SK_VANILLA_REL + ext for ext in (".uasset", ".uexp")]
    try:
        mount, entries = core.read_pak_entries(pak)
    except Exception as e:
        die(f"failed to read Palworld's pak index while extracting vanilla "
            f"{SWAY_HUB_SK_PACKAGE_NAME} (dev#1508 W2a-2): {e}")
    missing = [p for p in want if p not in entries]
    if missing:
        die(f"vanilla {SWAY_HUB_SK_PACKAGE_NAME} not found in Palworld's pak "
            f"(missing: {missing}) -- refusing to guess, stopping the "
            "conversion rather than silently shipping without the sway hub "
            "reparent patch (dev#1508 W2a-2).")
    try:
        extracted = pak_live_extract.extract_files(pak, want)
    except Exception as e:
        die(f"failed to extract vanilla {SWAY_HUB_SK_PACKAGE_NAME} from "
            f"Palworld's pak (dev#1508 W2a-2): {e}")

    stage_dir = os.path.join(work, "sway_hub_reparent")
    os.makedirs(stage_dir, exist_ok=True)
    uasset_path = os.path.join(stage_dir, SWAY_HUB_SK_PACKAGE_NAME + ".uasset")
    uexp_path = os.path.join(stage_dir, SWAY_HUB_SK_PACKAGE_NAME + ".uexp")
    with open(uasset_path, "wb") as f:
        f.write(extracted[SWAY_HUB_SK_VANILLA_REL + ".uasset"])
    with open(uexp_path, "wb") as f:
        f.write(extracted[SWAY_HUB_SK_VANILLA_REL + ".uexp"])

    def _step_from_json(s):
        nlt = s.get("new_local_transform")
        transform = None
        if nlt is not None:
            transform = (tuple(nlt[0]), tuple(nlt[1]), tuple(nlt[2]))
        return sway_shared_skeleton.ReparentStep(
            target=s["target"], new_parent=s["new_parent"],
            new_local_transform=transform, tag=s.get("tag", ""))

    try:
        steps = [_step_from_json(s) for s in steps_raw]
    except (KeyError, TypeError, IndexError) as e:
        die(f"malformed {SWAY_HUB_REPARENT_FILENAME} (dev#1508 W2a-2): {e}")

    try:
        out_uasset, out_uexp, infos = sway_shared_skeleton.apply_reparent_chain(
            uasset_path, uexp_path, steps)
    except sway_shared_skeleton.SharedSkeletonError as e:
        die(f"failed to apply sway hub reparent patch to {SWAY_HUB_SK_PACKAGE_NAME} "
            f"(dev#1508 W2a-2): {e}")

    with open(uasset_path, "wb") as f:
        f.write(out_uasset)
    with open(uexp_path, "wb") as f:
        f.write(out_uexp)

    for info in infos:
        print(f"[{TAG}] sway hub reparent: [{info.get('tag', '')}] "
              f"{info.get('target_name')} -> {info.get('new_parent_name')} "
              f"({info.get('n_bytes_diff')} byte(s) changed)")

    rel_uasset = vp_pakwrite.normalize_rel(
        "Skeleton/Human/" + SWAY_HUB_SK_PACKAGE_NAME + ".uasset", vp_pakwrite.BODY_PREFIX)
    rel_uexp = vp_pakwrite.normalize_rel(
        "Skeleton/Human/" + SWAY_HUB_SK_PACKAGE_NAME + ".uexp", vp_pakwrite.BODY_PREFIX)

    # リグレッション不可能性チェック(_run_dt_patch()と同じ手法): COMMON_MOUNT+
    # BODY_PREFIXの実効パスが共有Skeletonのバニラ正パスと一致することを構築前に
    # 機械アサートする。
    expected = "../../../" + SWAY_HUB_SK_VANILLA_REL
    eff_uasset = vp_pakwrite.effective_path(vp_pakwrite.COMMON_MOUNT, rel_uasset)
    eff_uexp = vp_pakwrite.effective_path(vp_pakwrite.COMMON_MOUNT, rel_uexp)
    if eff_uasset != expected + ".uasset" or eff_uexp != expected + ".uexp":
        die("internal error: sway hub shared-skeleton effective path does not "
            f"match the vanilla physical path (dev#1508 W2a-2): "
            f"{eff_uasset!r} != {expected + '.uasset'!r} or "
            f"{eff_uexp!r} != {expected + '.uexp'!r}")

    # dev#1508 W2a-2d(G3ゲート昇格): 実際に適用した差分(骨名・親・座標)を
    # サイドカーへ記録する。infosは既にtarget/old_parent/new_parent/
    # transform_changedを持つが、座標値そのもの(quat/pos/scale)は含まない
    # ため、パッチ済みのuasset_path/uexp_path(この時点で既にout_uasset/
    # out_uexpが書き込み済み)を再スキャンしてground truthを取得する
    # (manifest記載値=「実際にpakへ収まったバイトから読み取れる値」である
    # ことを保証する。infosの入力値をそのまま転記すると、書き込みと
    # manifestの間で値がずれても検出できない)。
    try:
        patched_catalog = sway_shared_skeleton.full_skeleton_catalog(uasset_path, uexp_path)
    except sway_shared_skeleton.SharedSkeletonError as e:
        die(f"failed to build the G3 patch manifest (dev#1508 W2a-2d): could not "
            f"re-scan the patched {SWAY_HUB_SK_PACKAGE_NAME}: {e}")
    patched_by_name = {b["name"]: b for b in patched_catalog["bones"]}
    manifest_steps = []
    for info in infos:
        name = info["target_name"]
        pb = patched_by_name.get(name)
        if pb is None:
            die(f"internal error: patched shared-skeleton catalog is missing target "
                f"bone {name!r} while building the G3 patch manifest (dev#1508 W2a-2d)")
        manifest_steps.append({
            "target_name": name, "tag": info.get("tag", ""),
            "old_parent_idx": info["old_parent_idx"], "old_parent_name": info["old_parent_name"],
            "new_parent_idx": info["new_parent_idx"], "new_parent_name": info["new_parent_name"],
            "transform_changed": info["transform_changed"],
            "quat": pb["quat"], "pos": pb["pos"], "scale": pb["scale"],
        })
    manifest = {"package": SWAY_HUB_SK_PACKAGE_NAME, "steps": manifest_steps}
    manifest_path = os.path.join(job["job_dir"], "converted", SWAY_HUB_PATCH_MANIFEST_FILENAME)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    print(f"[{TAG}] sway hub patch manifest written ({len(manifest_steps)} step(s)) "
          f"-- dev#1508 W2a-2d G3 upgrade sidecar: {manifest_path}")

    print(f"[{TAG}] sway hub reparent patch done: {len(steps)} step(s)")
    return [(uasset_path, rel_uasset), (uexp_path, rel_uexp)]


def apply_equip_avatar_extra_dir(final_files, equip_avatar_extra_dir):
    """dev#1170 WP-A由来の汎用ユーティリティ: equip_avatar_extra_dirツリーを
    final_files((abs_path, rel), ...のリスト)へ合流させる。rel_uexp/
    rel_uassetが既にfinal_filesに存在すれば**上書き**、存在しなければ
    **追加**する(--mi-override-dir等の既存replace_map経路が「置換のみ・
    追加不可」(n_replaced != len(replace_map)ならdie())なのと対照的——
    U50-single統一により通常のテンプレートから除外されている装備専用
    テクスチャ枠を新設アセットを使わず追加できるようにするため)。

    **2026-08-09 WP-2(合成エンジン)時点の呼び出し元**: convert_noue.pyの
    job.json `equipment_avatar_map`キー配線(WP-A初版)はオーナー確定仕様
    (issue #1170)により廃止済み(単一アバター変換フローはこの関数を
    もう呼ばない=--equip-avatar-extra-dir自体が渡らず常時④無退行)。
    現在の唯一の呼び出し元は`pipeline\\py\\vp_avatar_compose.py`
    (合成エンジン本体)で、build_pak_from_avatar.main()のCLI/argparse経路
    (Phase 1/2=Blender dump/SK注入)を経由せず、この関数を**直接呼ぶ**
    (合成エンジンは中間物ライブラリの保存済みSKを使うためBlenderが不要)。

    equip_avatar_extra_dirがNone/空文字列なら**必ず**
    (final_files, {}, 0, 0)を返す(=入力を一切変更しない)。

    戻り値: (new_final_files, equip_avatar_extra dict{rel: src},
             n_overridden, n_added)。new_final_filesは元のfinal_filesとは
    別のリストオブジェクト(呼び出し元の入力を破壊しない)。"""
    if not equip_avatar_extra_dir:
        return final_files, {}, 0, 0

    ed = os.path.abspath(equip_avatar_extra_dir)
    equip_avatar_extra = {}
    for dirpath, _d, filenames in os.walk(ed):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, ed).replace("\\", "/")
            equip_avatar_extra[rel] = p

    new_final_files = list(final_files)
    final_files_by_rel = {rel: i for i, (_s, rel) in enumerate(new_final_files)}
    n_overridden = 0
    n_added = 0
    for rel, src in equip_avatar_extra.items():
        if rel in final_files_by_rel:
            new_final_files[final_files_by_rel[rel]] = (src, rel)
            n_overridden += 1
        else:
            new_final_files.append((src, rel))
            n_added += 1
    return new_final_files, equip_avatar_extra, n_overridden, n_added


def main():
    ap = argparse.ArgumentParser(
        description="step02_{gender}.blend + テンプレpak_extract から "
                     "ゲームに入れられるpakを1コマンドで生成する(UnrealPak不使用)")
    ap.add_argument("--step02-female", default=None,
                    help="--genders にFemaleが含まれる場合は必須")
    ap.add_argument("--step02-male", default=None,
                    help="--genders にMaleが含まれる場合は必須")
    ap.add_argument("--genders", default="Male,Female",
                    help="dev#165(2026-07-30): カンマ区切りでMale/Femaleの"
                         "部分集合を指定。既定はMale,Female(=従来どおり両方に"
                         "実アバターを注入)。指定から漏れた性別の衣装SKは"
                         "注入せずテンプレート(バニラ)のままpakへ入れる"
                         "(vp_exclusions denylist除外と同じPhase3経路)")
    ap.add_argument("--equipment-filter", default="",
                    help="dev#165第2期(2026-08-08): カンマ区切りの装備コード"
                         "(vp_equipment_filter.equipment_code、性別非依存、例"
                         "Bronze001)。指定時はこのコードの装備のみメッシュ"
                         "注入対象にする(マテリアル側の絞り込みはテンプレート"
                         "組み立て時=live_template.py側で別途完結済み)。既定は"
                         "空文字列=絞り込み無し(従来どおり全装備に実アバターを"
                         "注入)")
    ap.add_argument("--template", required=True,
                    help="pak_extractディレクトリ(435ファイル、性別衣装SK込み)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--blender", required=True,
                    help="Blender本体exe(dev#14: 開発機既定値は撤去、必須引数化)")
    ap.add_argument("--work", default=None,
                    help="作業ディレクトリ(ダンプ/中間生成物の置き場所)。"
                         "省略時は一時ディレクトリを新規作成する")
    ap.add_argument("--max-influences", type=int, default=8)
    ap.add_argument("--job-json", required=True,
                    help="preflight_pak.py用job.json"
                         "(dev#14: 開発機既定値は撤去、必須引数化)")
    ap.add_argument("--cook-log", default=DEFAULT_COOK_LOG,
                    help="preflight_pak.py用cook_log(UEモード:実cookログ / "
                         "noueモード:noue_master\\shader_platform_facts.json)")
    ap.add_argument("--skip-preflight", action="store_true")
    ap.add_argument("--preflight-nonblocking", action="store_true",
                    help="dev#1230(2026-08-08オーナー裁定): preflight FAILでも"
                         "die()せず、pakを成果物として完成させたまま結果を"
                         "preflight_result.json(out_pakと同じディレクトリ)へ"
                         "記録して継続する。ユーザーサイド変換フロー"
                         "(convert_noue.py経由、job.jsonのpreflight_nonblocking"
                         "キー)専用。既定False=従来どおりdie()で停止"
                         "(relgate.py/release.py等の開発側関所はこのフラグを"
                         "渡さないため無変更)")
    ap.add_argument("--tex-body", default=None,
                    help="U6-T3(ストレッチ): body(t00)スロットへ注入するPNG。"
                         "テンプレートと異なる解像度は自動リサイズ(ニアレストネイバー)")
    ap.add_argument("--tex-parka", default=None,
                    help="U6-T3(ストレッチ): parka(t01)スロットへ注入するPNG")
    ap.add_argument("--tex-body-alpha-coverage", action="store_true",
                    help="FIX2(2026-07-24): bodyテクスチャのミップ生成で"
                         "アルファカバレッジを保存する(avatar_meta.jsonの"
                         "alpha_mode==MASKスロット向け)")
    ap.add_argument("--tex-parka-alpha-coverage", action="store_true",
                    help="FIX2(2026-07-24): parkaテクスチャのミップ生成で"
                         "アルファカバレッジを保存する")
    ap.add_argument("--tex-gain", type=float, default=1.0,
                    help="U49(2026-07-25): 注入テクスチャ(body/parka共通)へ"
                         "掛ける明度ゲイン(shadow_lift接続、"
                         "vp_texinject.shadow_lift_gain()参照)。既定1.0=無補正"
                         "(従来どおりのピクセル列、convert_noue.pyがjob.jsonの"
                         "shadow_liftから計算して渡す)")
    ap.add_argument("--mat-override-dir", default=None,
                    help="U13: スロット別マテリアル(M_VP_{slot}.uasset/uexp)の"
                         "差し替え元ディレクトリ。convert_noue.pyがバリアント選択+"
                         "shadow_liftバイトパッチ済みのファイルを置く")
    ap.add_argument("--uniform-scale", type=float, default=1.0,
                    help="dev#157 / WP-I157(2026-07-30): サイズ可変。全ボーンの"
                         "ローカルTranslationをk倍(root不動点、"
                         "build_avatar_variant.apply_uniform_scale参照)。"
                         "既定1.0は完全no-op(pakバイト不変)。隠し設定"
                         "(GUI未露出、job.json手書き/本引数の直接指定専用)")
    ap.add_argument("--mi-override-dir", default=None,
                    help="U50-fast(2026-07-26): 影の濃さ(shadow_lift)を焼き込んだ"
                         "統一MIの差し替え元ディレクトリ。--mat-override-dirと違い"
                         "**pak内相対パスと同じ木構造**で置かれている"
                         "(Player/Outfit/.../MI_*.uasset 等)。"
                         "live_template.build_shadow_mi_overrides()が生成し、"
                         "convert_noue.pyが渡す。k=0(影の濃さ0)のときは1件も"
                         "生成されず、この引数自体が渡らない")
    ap.add_argument("--equip-avatar-extra-dir", default=None,
                    help="差し替え/追加ファイルツリー(pak内相対パスと同じ木構造。"
                         "--mi-override-dirと違い、テンプレートに存在しない新規"
                         "パス(バニラ実在の装備専用テクスチャ枠、"
                         "_unify_slot_materials()により通常のテンプレートからは"
                         "除外されている)も追加できる)。convert_noue.py経由の"
                         "通常CLI実行では渡らない(dev#1170オーナー確定仕様で"
                         "job.json equipment_avatar_mapキー配線は廃止済み)。"
                         "唯一の呼び出し元はpipeline\\py\\vp_avatar_compose.py"
                         "(合成エンジン)で、この関数(main()のargparse経路では"
                         "なくapply_equip_avatar_extra_dir()を直接)を呼ぶ")
    args = ap.parse_args()

    # dev#165(2026-07-30): --genders で要求された性別だけがstep02パスを
    # 必須とする。既定"Male,Female"では従来どおり両方必須(挙動不変)。
    _valid_genders = {"Male", "Female"}
    requested_genders = {g.strip() for g in args.genders.split(",") if g.strip()}
    if not requested_genders or not requested_genders <= _valid_genders:
        die(f"--genders must be a non-empty comma-separated subset of "
            f"{sorted(_valid_genders)}: {args.genders!r}")

    # dev#165第2期(2026-08-08): --equipment-filterで要求された装備コード。
    # 空文字列(既定)ならrequested_equipment=None(=絞り込み無し)。
    requested_equipment = vp_equipment_filter.normalize_equipment_filter(
        [c.strip() for c in args.equipment_filter.split(",") if c.strip()])

    step02_female = os.path.abspath(args.step02_female) if args.step02_female else None
    step02_male = os.path.abspath(args.step02_male) if args.step02_male else None
    step02_by_gender = {"Female": step02_female, "Male": step02_male}
    for g in sorted(requested_genders):
        if not step02_by_gender[g]:
            die(f"--genders includes {g} but --step02-{g.lower()} was not given")
    template = os.path.abspath(args.template)
    out_pak = os.path.abspath(args.out)
    blender_exe = os.path.abspath(args.blender)

    for p, label in ((step02_female, "--step02-female"), (step02_male, "--step02-male"),
                     (template, "--template"), (blender_exe, "--blender")):
        if p is not None and not os.path.exists(p):
            die(f"{label} does not exist: {p}")

    work = os.path.abspath(args.work) if args.work else tempfile.mkdtemp(
        prefix="d2p_build_pak_from_avatar_")
    os.makedirs(work, exist_ok=True)
    log_dir = os.path.join(work, "logs")
    dump_dir = os.path.join(work, "dump")
    variant_dir = os.path.join(work, "variant")
    os.makedirs(dump_dir, exist_ok=True)
    print(f"[{TAG}] work directory: {work}")

    # === Phase 1: Blender headlessで両性別をダンプ ===
    # WP-B3(2026-07-28): dump_avatar_mesh.py内のmesh.calc_tangents()
    # (Blender内蔵mikktspace)がBlenderのタスクスケジューラ(BLI_task)の
    # マルチスレッド評価に起因して実行のたびに1e-6オーダーで結果がブレる
    # ことを実測で確認した(同一.blend・同一スクリプトを単独プロセスで
    # 逐次2回実行しても、特定頂点のtangent成分だけが最終桁で相違。
    # pos/normal/uv/weightsは常に完全一致)。この揺れがbuild_avatar_variant.py
    # のencode_tangent_pair()での8bit量子化の境界をたまたま跨ぐと、
    # Outfit衣装SKのuexpが1バイトだけ変化し、pakのSHA256が実行ごとに
    # non-deterministicになる(release.py v1.1.4試行 run_20260728_054403で
    # 実際に発生、prefab_flatapronのOutfit系uexp 29件が変更ありでFAIL)。
    # `-t 1`(Blender CLIオプション、BLI_taskのスレッド数を1に固定)を
    # 付けた場合のみ、同一検証手順で3回連続バイト完全一致を確認済み。
    # calc_tangents()を呼ぶBlender起動はこのdump_avatar_mesh.py呼び出し
    # 1箇所だけ(pipeline全体をgrep済み、他のBlender工程は呼んでいない)
    # なので、ここにだけ限定して付与する(全Blender工程に付けると遅くなる)。
    dump_blender_args = ["-t", "1"]
    dumps = {}
    # rd_120 5.3: Female/Maleダンプ(Blenderヘッドレス2本)を並列実行する。
    # 唯一の制約(適用手順どおり厳守): dump_blender_args=["-t", "1"](上記の
    # WP-B3コメント参照)はプロセスごとの引数なので、2プロセスを並列に起動
    # しても各プロセス内部は引き続き-t 1のまま——この引数は変更しない。
    # この並列化はBlenderプロセスの起動本数を増やすだけで、各プロセス内部の
    # 決定性には一切触れない(=pakのSHA256決定性は不変、PROPOSAL 1節7項)。
    # dev#165(2026-07-30): --gendersで要求されていない性別はダンプしない
    # (該当step02パスがそもそも渡されていないためNoneであり得る)。
    # 既定"Male,Female"ではrequested_gendersが両方を含むため、この
    # フィルタは従来のタプルと一字一句同じ列を作り、既存挙動と不変。
    dump_tasks = [
        (gender, blend, blender_exe, dump_blender_args,
         os.path.join(dump_dir, f"avatar_{gender.lower()}.json"),
         os.path.join(log_dir, f"dump_{gender}.log"), args.max_influences)
        for gender, blend in (("Female", step02_female), ("Male", step02_male))
        if gender in requested_genders
    ]
    # dev#220追加計装(2026-07-30): 旧"variant_inject_sec"ラベルがPhase1(この
    # ダンプ)とPhase2(SK注入、下)を1つに束ねていたため、どちらが実際に
    # 支配的かを区別できなかった。開始/終了printだけの軽量観測(計算・出力に
    # 一切影響しない)。
    print(f"[{TAG}] === Phase1Subphase: avatar_dump start ===")
    _t_dump = time.time()
    dump_results = vp_parallel.run_pair_parallel(_dump_gender, dump_tasks)
    print(f"[{TAG}] dev#1650 timing: avatar_dump (blender, parallel) "
          f"{time.time() - _t_dump:.1f}s")
    for gender, out_json in dump_results:
        dumps[gender] = load_dump(out_json)
        # U21: RefSkeletonバインドポーズ位置パッチ(build_avatar_variant.py
        # load_chibi_bone_world_head参照)向けに、真のjob_dir/convertedの
        # 場所を明示的に渡す。dump['source_blend']はUVアトラス焼き込み後の
        # blend(work/<job>/build/atlas/step02_{gender}_atlas.blend)を指して
        # おり、pipeline/blender/step02_retarget.pyがchibi_bone_world_head_
        # {gender}.jsonを書き出す本来のconvertedディレクトリ
        # (work/<job>/converted/)とは別の場所になる(U21初回実装で発覚した
        # バグ: source_blendのdirnameから逆算すると見つからず、パッチが
        # 常にサイレントno-opになっていた)。job.jsonの場所から直接
        # job_dir/convertedを解決する方が確実なので、こちらを明示的に渡す。
        dumps[gender]['_job_converted_dir'] = os.path.join(
            os.path.dirname(os.path.abspath(args.job_json)), "converted")
        # dev#157 / WP-I157: サイズ可変。build_avatar_variant.build_uexp_variant()が
        # dump.get('uniform_scale', 1.0)を読む(apply_uniform_scale参照)。
        dumps[gender]['uniform_scale'] = args.uniform_scale
    print(f"[{TAG}] === Phase1Subphase: avatar_dump done ===")

    # === Phase 2(sk_injection, L2) と Phase 2b/2c/2d(overrides, L2b)を重畳 ===
    # dev#288: 独立性の根拠はNOTES.md(work\speed_mission\l2l2b\NOTES.md)参照。
    _t_phase2 = time.time()
    targets_rel, (tex_replace, mat_override, mi_override) = _run_phase2_overlap(
        template, requested_genders, variant_dir, dumps, args, work,
        requested_equipment=requested_equipment)
    print(f"[{TAG}] dev#1650 timing: Phase2 overlap (sk_injection+overrides) "
          f"{time.time() - _t_phase2:.1f}s")

    # === Phase 3: pak化(残り375件はテンプレートのまま、vp_pakwriteでpak化) ===
    # dev#1198 WP-B5a: 実際に書き出すmountはCOMMON_MOUNT(下のbuild_pak()呼び出し
    # 参照)。ここでの表示はcollect_files(template)がDEFAULT_MOUNT体系相対の
    # rel_pathを返す入力側の前提を示すログのため、DEFAULT_MOUNTのまま残す。
    print(f"[{TAG}] === Phase 3: building pak (input mount convention="
          f"{vp_pakwrite.DEFAULT_MOUNT}, output mount={vp_pakwrite.COMMON_MOUNT}) ===")
    all_files = vp_pakwrite.collect_files(template)
    replace_map = dict(tex_replace)
    replace_map.update(mat_override)
    replace_map.update(mi_override)
    for rel_uexp in targets_rel:
        rel_uasset = rel_uexp[:-5] + ".uasset"
        replace_map[rel_uexp] = os.path.join(variant_dir, rel_uexp)
        replace_map[rel_uasset] = os.path.join(variant_dir, rel_uasset)

    final_files = []
    n_replaced = 0
    for src, rel in all_files:
        if rel in replace_map:
            final_files.append((replace_map[rel], rel))
            n_replaced += 1
        else:
            final_files.append((src, rel))
    if n_replaced != len(replace_map):
        die(f"only {n_replaced}/{len(replace_map)} replacement target(s) matched")

    # dev#1170 WP-A(装備別アバター、Phase 2e): --equip-avatar-extra-dir。
    # 上のreplace_map経路と違い、テンプレートに存在しないrel(vanilla実在
    # パスだがU50-single統一により通常のテンプレートからは除外されている
    # 装備専用テクスチャ枠)も**追加**できる(既存の
    # `if n_replaced != len(replace_map): die()` 不変条件には触れず、独立
    # した後続パスとして扱う)。--equip-avatar-extra-dir省略時(既定)は
    # apply_equip_avatar_extra_dir()が即座に(final_files, {}, 0, 0)を返し
    # final_filesは上のreplace_map経路の結果のままになる(④無退行の根拠)。
    final_files, equip_avatar_extra, n_overridden, n_added = apply_equip_avatar_extra_dir(
        final_files, args.equip_avatar_extra_dir)
    if equip_avatar_extra:
        print(f"[{TAG}] dev#1170 equipment_avatar_map: {n_overridden} existing "
              f"template entrie(s) overridden, {n_added} new entrie(s) added "
              f"({os.path.abspath(args.equip_avatar_extra_dir)})")

    # dev#1198 WP-B5a: COMMON_MOUNT実配線。final_filesはこれまでDEFAULT_MOUNT
    # 前提のボディ資産相対rel_pathで組み立てられている。normalize_relで
    # BODY_PREFIXを付与しCOMMON_MOUNTへ切り替えても、effective_pathは
    # DEFAULT_MOUNT時と完全一致する(vp_pakwrite.to_common_mount_body_files
    # のdocstring・test_vp_pakwrite_wpb5a_wiring.py参照)。
    common_mount_files = vp_pakwrite.to_common_mount_body_files(final_files)

    # dev#1198 WP-B5b: DT同梱の本配線(頭部問題根治の最終ピース)。
    # to_common_mount_body_files()はボディ専用(BODY_PREFIX固定)のため、
    # DT資産(DT_PREFIX)は別途normalize_rel済みの(abs_path, rel)ペアとして
    # common_mount_filesへ合流させる(WP-B5a申し送りどおり)。
    _t_dt_patch = time.time()
    dt_files = _run_dt_patch(os.path.abspath(args.job_json), targets_rel, work)
    print(f"[{TAG}] dev#1650 timing: DT flag patch {time.time() - _t_dt_patch:.1f}s")
    common_mount_files = common_mount_files + dt_files

    # dev#19(揺れものpak生成の製品パイプライン結線): job["sway_intensity"]
    # ("hard"/"normal"/"soft")が指定されていれば、著作済みABPテンプレへ
    # 硬さプリセットをパッチしてcommon_mount_filesへ合流させる。DT同梱
    # (上)と同じ「常時呼ぶがno-opになりうる」パターン——無効/未指定なら
    # 空リストが返りpak出力は不変。
    _t_sway_abp = time.time()
    sway_abp_files = _run_sway_abp_patch(os.path.abspath(args.job_json), work)
    print(f"[{TAG}] dev#1650 timing: sway ABP patch {time.time() - _t_sway_abp:.1f}s")
    common_mount_files = common_mount_files + sway_abp_files

    # dev#1508 W2a-2(汎用ハブ配線、指揮者指示書「本体」項目2「pak結線」):
    # job_dir/converted/sway_hub_reparent.jsonがあれば共有Skeletonへ
    # reparentパッチを適用してcommon_mount_filesへ合流させる。本WP時点では
    # step02_retarget.py側がまだこのファイルを書き出さないため、常に
    # ファイル無し=空リスト(pak出力は本WP適用前と完全に一致、
    # sway_abp_files/dt_filesと同じ「常時呼ぶがno-opになりうる」パターン)。
    _t_sway_hub_reparent = time.time()
    sway_hub_reparent_files = _run_sway_hub_reparent_patch(
        os.path.abspath(args.job_json), work)
    print(f"[{TAG}] dev#1650 timing: sway hub reparent patch "
          f"{time.time() - _t_sway_hub_reparent:.1f}s")
    common_mount_files = common_mount_files + sway_hub_reparent_files

    _t_build_pak = time.time()
    os.makedirs(os.path.dirname(out_pak) or ".", exist_ok=True)
    info = vp_pakwrite.build_pak(common_mount_files, out_pak,
                                  mount_point=vp_pakwrite.COMMON_MOUNT)
    print(f"[{TAG}] dev#1650 timing: build_pak {time.time() - _t_build_pak:.1f}s")
    print(f"[{TAG}] pak generated: {out_pak} "
          f"(total entries {info['n_entries']}, replaced {n_replaced}, size={info['size']})")

    # pak⇒blend原則(2026-08-15深夜オーナー裁定「pakがあってblendがないことは
    # ありえない」、dev#pak⇒blend原則の実装): pak隣へサイドカー(<pak名>.src.json)
    # を書き出す。sway_run.py/devtools\replay側がstep02 blend(このpakの土台)を
    # 検体辞書に頼らず自動解決できるようにする。step02_by_genderは既に上で
    # 構築済みのローカル変数をそのまま渡すだけ(新しい探索・推測は行わない)。
    sidecar_path = pak_src_sidecar.write_sidecar(
        out_pak, step02_by_gender, job_json=args.job_json)
    print(f"[{TAG}] pak src sidecar written: {sidecar_path}")

    # === Phase 4: preflight_pak.py 自動実行 ===
    if args.skip_preflight:
        print(f"[{TAG}] --skip-preflight specified, skipping preflight")
    else:
        job_json = os.path.abspath(args.job_json)
        cook_log = os.path.abspath(args.cook_log)
        if not (os.path.exists(job_json) and os.path.exists(cook_log)):
            print(f"[{TAG}] job.json/cook.log not found, skipping preflight "
                  f"(job_json={job_json} cook_log={cook_log}. "
                  "Specify explicitly with --job-json/--cook-log)")
        else:
            print(f"[{TAG}] === Phase 4: preflight_pak.py ===")
            _t_preflight = time.time()
            run_preflight_phase(job_json, out_pak, template, cook_log,
                                 args.preflight_nonblocking)
            print(f"[{TAG}] dev#1650 timing: preflight_pak "
                  f"{time.time() - _t_preflight:.1f}s")

    print(f"[{TAG}] done: {out_pak}")
    print(f"[{TAG}] work directory (dump/intermediates/logs): {work}")


if __name__ == "__main__":
    main()
