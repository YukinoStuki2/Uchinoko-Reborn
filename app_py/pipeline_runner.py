# pipeline_runner.py -- 変換パイプラインの起動契約
# (旧 app\DiveToPalworld.cs の WriteJob/BuildConvertScriptPath/BuildConvertArgs/
#  FindPwsh/RunPipeline/RunUnityExport 相当)。
#
# 正本: C:\P\Work\DiveToPalworld\work\wp532A\DESIGN.md §2.1(convert.ps1起動契約と
# job.jsonスキーマ)/ §4.3(非同期処理方式)。移植元行番号(app\DiveToPalworld.cs):
#   - SanitizeName()                 L.1734-1742
#   - AssetSubDir()                  L.1752-1757
#   - FindFirst()                    L.1862-1867
#   - FindBlender()                  L.1836-1861 (dev#23c(2026-08-02)で
#     blender_setup.find_blender()への委譲に置き換え済み。詳細は下記
#     find_blender()のdocstring参照)
#   - WriteJob()                     L.1771-1817
#   - BuildConvertScriptPath()       L.1824-1827
#   - BuildConvertArgs()             L.1829-1834
#   - FindPwsh()                     L.2721-2739
#   - RunPipeline()                  L.2547-2607
#   - RunUnityExport()               L.2612-2682
#   - AppendLog()の##PROGRESS##/##AVATAR_WARNING##解析とANSI除去 L.2829-2883
#   - Strings.ProgressLabelTemplates (可変部を含む進捗ラベル)  L.352-362
#
# 書き込み許可(DESIGN.md §5.2 WP-A2行): このファイル +
# app_py\ui\main_window.py の該当ハンドラ部分のみ。
#
# 指揮者裁定(dev#532 A2発進指示): job.jsonへ`engine_mode: "noue"`を明示的に書く
# (DESIGN.md §6-1で指摘された既存ドリフトの解消。gui_wiring_check.pyの必須キー
# には含まれないが、pipeline\cli\convert.ps1は`$cfg.engine_mode`を読み、
# `$Step01IgnoredKeys`にも既に列挙済みの正規のトップレベルキーであるため、
# 追加しても既存契約と衝突しない)。
#
# 依存モジュールの解決: main_window.py と同じ流儀(app_pyディレクトリを
# sys.pathへ入れてから絶対importする)。
from __future__ import annotations

import glob
import json
import os
import queue
import re
import shutil
import string
import subprocess
import sys
import threading
from typing import Callable, Optional

_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import blender_setup  # noqa: E402
import equipment_filter_store  # noqa: E402  (dev#165: 装備限定ラボ機能の選択状態読み出し。
# 2026-08-08緊急修正: 以前は ui.equipment_select_dialog を直接importしていたが、
# そのモジュールは冒頭で `import tkinter as tk` するため、tkinter未導入の
# ヘッドレスpython環境(lu_export.py等)からpipeline_runner.pyが読み込まれると
# ModuleNotFoundErrorで即死していた([D2P_LU_NO_RESULT])。選択状態の
# 保存・読み出しロジックはtkinter非依存のequipment_filter_store.pyへ切り出し
# 済みなので、そちらのみをimportする(UI層→store層の一方向依存)。
import headequip_filter_store  # noqa: E402  (dev#277第1弾④: 頭装備切り替えラボ機能。
# equipment_filter_storeと同じ理由でtkinter非依存モジュールのみをimportする。)
import dt_flag_head_hide_store  # noqa: E402  (dev#1258 WP-E: 「差替え中装備のみ頭OFF」
# ラボ機能。equipment_filter_store/headequip_filter_storeと同じ理由でtkinter非依存
# モジュールのみをimportする。)
import shapekey_filter_store  # noqa: E402  (dev#1168: シェイプキーラボ機能の
# 設定読み出し。equipment_filter_store/headequip_filter_storeと同じ理由で
# tkinter非依存モジュールのみをimportする。)
import i18n  # noqa: E402
import mesh_delete_store  # noqa: E402  (dev#1168前半: メッシュ削除ラボ機能。
# equipment_filter_store/headequip_filter_storeと同じ理由でtkinter非依存
# モジュールのみをimportする。)
import lab_raw_sway_params_store  # noqa: E402  (dev#1418ラボ機能「生パラメータ
# 全解放パネル」、work\wp_1418_rawparam\BRIEF.md: equipment_filter_store等と
# 同じ理由でtkinter非依存モジュールのみをimportする。)
import settings  # noqa: E402
import sway_chain_override_store  # noqa: E402  (dev#19揺れものUIプロトタイプ、
# work\rd_19_flight\briefs\uimock2_embedded.md: ラボ「揺れもの詳細設定」の
# 選択状態読み出し。equipment_filter_store等と同じ理由でtkinter非依存
# モジュールのみをimportする。)
import vrm_spring_catalog  # noqa: E402  (dev#19/dev#1370: VRM揺れもの正規化。
# tkinter非依存、既存importと同じ理由でモジュールのみをimportする。)

# ---------------------------------------------------------------------------
# job.jsonスキーマ定数(DESIGN.md §2.1)
# ---------------------------------------------------------------------------

PAL_WINDOWS_PAK_NAME = "Pal-Windows.pak"  # DiveToPalworld.cs L.2985 PalWindowsPakName
# 本体pakのファイル名候補(dev#229続報)。pak_manager.PAK_FILENAME_CANDIDATESと
# 同一の値・同一の理由でここにも独自に持つ(app_pyはpipeline\pyをimportしない
# 設計のため、PAL_WINDOWS_PAK_NAME同様に複製する)。job.jsonのpaths.palworld_pak
# 生成(write_job)がPAL_WINDOWS_PAK_NAME単一決め打ちのままだと、GUIでPaksフォルダの
# 手動選択(pak_manager.py側)を候補リスト化しても、job.json側で存在しないSteam名の
# パスを書いてしまい、Xbox App版利用者は結局「バニラpakが見つからない」で
# 止まり続けていた(dev#229)。
PAK_FILENAME_CANDIDATES = (
    PAL_WINDOWS_PAK_NAME,  # Steam版(既定・最優先。既存挙動そのまま)
    "Pal-WinGDK.pak",      # Xbox App / Microsoft Store版(Game Pass)
)

# 指揮者裁定によりconvert.ps1の既定と明示的に一致させる(§0. モジュールdocstring参照)。
ENGINE_MODE = "noue"


# ---------------------------------------------------------------------------
# パス解決ヘルパー(SanitizeName/AssetSubDir/FindFirst/FindBlender/PaksDirQuiet相当)
# ---------------------------------------------------------------------------

_SANITIZE_ALLOWED = set(string.ascii_letters + string.digits)


def sanitize_name(name: str) -> str:
    """SanitizeName() L.1734-1742相当。ASCII英数字以外を捨て、空ならAvatarへ。"""
    kept = "".join(c for c in name if c in _SANITIZE_ALLOWED)
    return kept if kept else "Avatar"


def asset_sub_dir(app_root: str, name: str) -> str:
    """AssetSubDir() L.1752-1757相当。配布zip(assets\\配下)/開発チェックアウト
    (リポジトリ直下)のどちらでも動くフォールバック。"""
    dist = os.path.join(app_root, "assets", name)
    if os.path.isdir(dist):
        return dist
    return os.path.join(app_root, name)


def find_first(directory: str, pattern: str) -> Optional[str]:
    """FindFirst() L.1862-1867相当。ディレクトリが無ければNone、一致が無ければNone。
    C#のDirectory.GetFileSystemEntriesはOS依存順序で先頭を返すが、Python版は
    再現性のためソート順の先頭を返す(値の存在有無という契約自体は変えない、
    複数一致時の決定性を上げる合理的な差分)。"""
    if not os.path.isdir(directory):
        return None
    hits = sorted(glob.glob(os.path.join(directory, pattern)))
    return hits[0] if hits else None


def find_blender(app_root: str, log: Optional[Callable[[str], None]] = None) -> str:
    """FindBlender() L.1836-1861相当。

    dev#23c(2026-08-02、dev#23監査PR#754の申し送りの残件解消): このモジュール
    独自の探索実装(自動発見のみ、②手動指定・③探索ログ無し)を廃止し、
    blender_setup.find_blender()(dev#23bで②③を実装済み)へ委譲する形に
    寄せた。CLAUDE.md「入口で正規化、特別扱いを積むな」原則どおり、Blender実行体の
    解決ロジックを1箇所に統一する(2重実装の解消)。

    優先順位・挙動はblender_setup.find_blender()と完全に同一(env var
    D2P_BLENDER_EXE → settings_blenderexe.txt → assets\\tools自動発見 →
    最終フォールバック"blender.exe")。手動指定(環境変数/設定ファイル)が
    設定されているのに実在しない場合は blender_setup.BlenderManualPathError を
    送出し、黙って自動発見へは進まない(CLAUDE.md「指定を無視するのが最悪」)。
    手動指定が一切無い既定経路(開発機・配布物とも通常はこちら)の挙動は、
    dev#14で開発機決め打ちフォールバックを除去した後のblender_setup版と
    1:1で不変(自動発見が成功する限りpipeline_runner側の見え方は変わらない)。

    log: 探索した場所を1行ずつ通知する任意コールバック(blender_setup.find_blender()の
    LogFnをそのまま転送する)。省略時は何も出力しない(write_job()等、既存
    呼び出し元は無改修で動く)。"""
    return blender_setup.find_blender(app_root, log=log)


def _resolve_pak_filename(paks_dir: Optional[str]) -> Optional[str]:
    """paks_dir配下にPAK_FILENAME_CANDIDATESのいずれかが実在すれば、その
    実ファイル名を返す(先頭=Steam版から順に確認)。pak_manager.
    resolve_pak_filename()と同一ロジック(dev#229続報)。"""
    if not paks_dir or not os.path.isdir(paks_dir):
        return None
    for filename in PAK_FILENAME_CANDIDATES:
        if os.path.isfile(os.path.join(paks_dir, filename)):
            return filename
    return None


def _paks_dir_has_pak(paks_dir: Optional[str]) -> bool:
    return _resolve_pak_filename(paks_dir) is not None


def paks_dir_quiet(app_root: str) -> Optional[str]:
    """PaksDirQuiet() L.3328-3342相当の簡略版。settings_paksdir.txt に保存済みの
    キャッシュのみを見て、ダイアログはもちろんSteamライブラリの生自動探索
    (SteamRootCandidates/SteamLibraryRoots、レジストリ読取を伴う)も行わない。
    その自動発見の完全実装は pak_manager.py(WP-A4、DESIGN.md §2.3/§5.2)の
    責務であり、本WPの書き込み許可ファイルには含まれない
    〈WP-A2の合理的解釈〉。未解決ならNoneを返し、呼び出し側(write_job)は
    §2.1のとおりpaths.palworld_pakキーを省略する(「省略可」と明記されている)。

    dev#229続報: _paks_dir_has_pak()がPAK_FILENAME_CANDIDATES(Steam/Xbox App
    両対応)の判定に拡張済みのため、ここも自動的に両対応になる。
    """
    cached = settings.load_paksdir(app_root)
    if _paks_dir_has_pak(cached):
        return cached
    return None


# ---------------------------------------------------------------------------
# RestoreSettings() L.1621-1628 前段(job.json読み込み)相当
# ---------------------------------------------------------------------------


def read_job(job_json_path: str) -> Optional[dict]:
    """RestoreSettings(string jobJson, bool setVrmPath) L.1621-1628のうち、
    ファイル読み込み+パース部分だけを切り出した純粋関数(dev#605/#616/#623)。
    存在しない/読めない/壊れたJSONはNoneを返す(RestoreSettingsの
    `if (!File.Exists(jobJson)) return;` および続く `try { json = ... }
    catch (Exception) { return; }` と同じ「読めなければ静かに復元しない」方針)。
    py側job.jsonは自前生成のUTF-8正規JSON(pipeline_runner.write_job()参照)
    なのでC#側の自前regex読み取り(JsonStr/JsonNum/JsonBool/JsonStrArray)では
    なくjson.loadで足りる(pak_manager.resolve_delete_targets()が既に同じ
    流儀でjob.jsonを読んでいる、DESIGN.md §2.5と同じ理由)。"""
    if not os.path.isfile(job_json_path):
        return None
    try:
        with open(job_json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# WriteJob() 相当
# ---------------------------------------------------------------------------


def write_job(
    app_root: str,
    work_root: str,
    vrm_path: str,
    *,
    shoulder_offset_deg: int = 0,
    merge_fingers: bool = False,
    unlit: bool = False,
    force_two_sided: bool = True,
    shadow_bar_value: int = 30,
    drop_bones_text: str = "",
    license_confirmed: bool = False,
    uniform_scale: float = 1.0,
    sway_intensity: str = "normal",
) -> str:
    """WriteJob() L.1771-1817相当。job.jsonを書き出し、そのファイルパスを返す。

    shoulder_offset_deg/merge_fingers/unlit/force_two_sidedの既定値は
    DiveToPalworld.cs L.1042-1046のコメント「内部互換性のためにフィールドを
    初期化(UIには表示しない)」に書かれた初期値そのもの(shoulderBar.Value=0,
    mergeFingersCheck.Checked=false, unlitCheck.Checked=false,
    twoSidedCheck.Checked=true)。これらはWP-A1の骨格(main_window.py)にも
    対応する可視ウィジェットが無い隠しフィールドであり、呼び出し側が
    以前のjob.jsonから復元した値を渡せるようキーワード引数にしてある
    (復元ロジック自体=SetVrmのjob.json読込はWP-A2のスコープ外)。

    uniform_scale(dev#560 第③段、2026-08-08): 身長(全体スケール)スライダー
    (main_window.py heightScaleBar)の値。job.jsonの`uniform_scale`(第①段
    PR #1126がpipeline\\blender\\step02_retarget.pyで読む内部パラメータ)へ
    そのまま書く。dev#158裁定のレンジ(0.5〜2.0)へここでもクランプする
    (UI側のtk.Scaleが50〜200%しか生成しないため通常は不要だが、将来の
    呼び出し元・手書きjob.json由来の値に対する多重防御)。既定1.0は
    apply_output_scale()側が早期returnする完全no-opのため、このキーワード
    引数を省略する既存呼び出し元(未変更のまま)には一切影響が無い。

    sway_intensity(dev#1572、2026-08-18裁定「かたさが配線されていない問題」
    案C、v2.11方式の復元): 標準機能「揺れの度合い」(main_window.py
    swayIntensityBar)の4択、値は"none"/"soft"/"normal"/"hard"。dev#1508
    W2b(2026-08-16)がこれを一時的にON/OFFトグルへ置換していたが、本WPで
    4択へ復元した(個別鎖の「ゆれかた」調整UIは画面から隠蔽、標準機能の
    この4択のみが揺れの強さを選ぶ手段になる)。

    job["sway_intensity"]は"soft"/"normal"/"hard"のいずれかのときだけ
    書く("none"のときはキー自体を省略する——dev#19プロトタイプ時代からの
    元々の設計そのもの、ラボ憲章④「既定値のときは未実装状態と完全に同一」
    と同型)。この値はpipeline\\py\\sway_abp_build.py
    hardness_key_for_intensity()が読み、既存の一括刻印経路(全KPノードへ
    同一のdamping/stiffness/wd、テンプレのnode_overridesが無いノードすべて
    に適用)へそのまま効く。

    job["sway_enable"](bool、dev#19揺れものUIプロトタイプ由来、"enabled"と
    紛らわしいが別キー)はsway_intensity!="none"のときのみTrueを書く。
    こちらはW1c/W2a-1の自動アロケータ(pipeline\\blender\\step02_retarget.py
    auto_assign_sway_chains()・pipeline\\py\\preflight_pak.py等)が「揺れもの
    処理そのものを行うか」のゲートとして直接読んでおり、どのdonor鎖を採用
    するか(候補判定・無偏向判定・量子化)を決める別軸のロジックのため、
    4択のうちどれを選んでも(soft/normal/hardいずれでも)Trueを書く
    ——4択は「選ばれた鎖にどの硬さを刻印するか」だけを制御し、「どの鎖を
    選ぶか」には関与しない(この2軸の分離はW1c/W2a-1導入時からの既存設計、
    本WPはそこへ触れていない)。

    旧`sway_enabled`(bool、dev#1508 W2b由来のGUI内部専用キー)は本WPで
    廃止した——job.jsonへは二度と書かない。ただしmain_window.py
    _apply_restored_settings()は、このキーを持つ古いjob.json(W2b期に保存
    されたもの)を読んだ場合の移行規則を持つ(True→"normal"、False→
    "none")。
    """
    name = sanitize_name(os.path.splitext(os.path.basename(vrm_path))[0])
    job_dir = os.path.join(work_root, name)
    os.makedirs(job_dir, exist_ok=True)

    blender = find_blender(app_root)
    addon_zip = find_first(
        asset_sub_dir(app_root, "third_party"), "VRM_Addon_for_Blender-Extension*.zip"
    )
    # C#のJ(addonZip)はnullだと素朴に.Replace()を呼びNullReferenceExceptionで
    # 落ちる(gui_wiring_check.pyがフィクスチャを必ず用意しているのはこのため、
    # 既存の許容されたスキ)。Python版はここをnull安全にし、見つからなければ
    # 空文字列を書く(実運用ではthird_party配下に同梱されており通常到達しない
    # パスだが、クラッシュより「空のパスで後段が明確に失敗する」方を選ぶ、
    # CLAUDE.mdの「実装したと効いているは別」「値を寄せて合わせない」の精神に
    # 沿った意図的な改善。DESIGN.md §2.1のスキーマ契約〈キーは常に存在する〉は
    # 崩さない)。
    if addon_zip is None:
        addon_zip = ""

    drop_bones = [b.strip() for b in drop_bones_text.split(",") if b.strip()]
    shadow_lift = round((100 - shadow_bar_value) / 100.0, 3)
    # dev#560裁定(dev#158)のレンジへクランプ(§ docstring参照)。
    try:
        uniform_scale_clamped = max(0.5, min(2.0, float(uniform_scale)))
    except (TypeError, ValueError):
        uniform_scale_clamped = 1.0

    job: dict = {
        "vrm_path": vrm_path,
        "avatar_name": name,
        "shoulder_offset_deg": shoulder_offset_deg,
        "merge_fingers": bool(merge_fingers),
        "unlit": bool(unlit),
        "force_two_sided": bool(force_two_sided),
        "shadow_lift": shadow_lift,
        "drop_bones": drop_bones,
        "license_confirmed": bool(license_confirmed),
        "engine_mode": ENGINE_MODE,
        "uniform_scale": uniform_scale_clamped,
        # dev#1230(2026-08-08オーナー裁定): ユーザーサイド(このGUI経由)の
        # 変換フローは常にpreflight非ブロック(FAIL時もpakを完成させ、
        # GUIが警告ダイアログを出す)。devtools\relgate.py/release.pyが
        # 組み立てるjob.jsonはこのキーを持たない(job.get既定False)ため、
        # 開発側の関所(preflight FAILで停止)は無変更のまま。
        "preflight_nonblocking": True,
        "paths": {
            "blender_exe": blender,
            "vrm_addon_zip": addon_zip,
        },
    }
    paks_dir = paks_dir_quiet(app_root)
    if paks_dir is not None:
        # dev#229続報: paks_dir_quiet()が解決に使ったのと同じ判定
        # (PAK_FILENAME_CANDIDATES)で実ファイル名を再解決する。paks_dirが
        # Noneでない時点でどれか1件は必ず実在する(paks_dir_quietの契約)ため
        # Noneは来ない想定だが、念のためフォールバックにPAL_WINDOWS_PAK_NAME
        # (従来の既定値)を残す。
        pak_filename = _resolve_pak_filename(paks_dir) or PAL_WINDOWS_PAK_NAME
        job["paths"]["palworld_pak"] = os.path.join(paks_dir, pak_filename)

    # dev#165(装備限定、2026-08-08結線): ラボ窓で選択済みの装備コードが
    # 1件以上あればjob["equipment_filter"]へ書く。未選択(空リスト/
    # 状態ファイル不在)ならキー自体を省略する——ラボ憲章④(既定値のときは
    # 未実装状態と完全に同一)をjob.jsonの時点で満たすため。convert_noue.py
    # 側もjob.get("equipment_filter")のキー不在を「絞り込み無し」として
    # 扱う設計(PR #1192本文の受入結果表「既定でmasterと完全一致」参照)。
    codes = equipment_filter_store.load_selected_codes(app_root)
    if codes:
        job["equipment_filter"] = codes

    # dev#277第1弾④(頭装備切り替え、2026-08-08結線): ラボ窓で選択済みの
    # 「表示する」頭装備コードが1件以上あればjob["headequip_show"]へ書く。
    # 未選択(空リスト/状態ファイル不在)ならキー自体を省略する——
    # ラボ憲章④(既定値のときは未実装状態と完全に同一=全頭装備が従来どおり
    # 非表示)をjob.jsonの時点で満たすため。live_template.py側も
    # job.get("headequip_show")のキー不在を「表示切り替え無し」として扱う
    # 設計(vp_headequip_filter.normalize_headequip_selection参照)。
    headequip_show = headequip_filter_store.load_selected_codes(app_root)
    if headequip_show:
        job["headequip_show"] = headequip_show

    # dev#1168前半(メッシュ削除、2026-08-09結線、保存スコープをアバター単位へ
    # 変更=dev#1281残論点、指揮者裁定): ラボ窓で保存済みの削除指定のうち、
    # 現在のvrm_path(このjobが対象とするアバター)と一致するものだけを
    # job["drop_meshes"]へ書く。不一致(別アバター編集時の残留)/未指定
    # (空リスト/状態ファイル不在)ならキー自体を省略する——ラボ憲章④
    # (既定値のときは未実装状態と完全に同一)をjob.jsonの時点で満たすため。
    # step01_import_vrm.py側もjob.get("drop_meshes")のキー不在を「削除無し」
    # として扱う設計(drop_named_meshes()、vp_mesh_drop.classify_mesh_drop_targets()参照)。
    deleted_meshes = mesh_delete_store.load_deleted_names(app_root, vrm_path)
    if deleted_meshes:
        job["drop_meshes"] = deleted_meshes

    # dev#1258(WP-E、2026-08-09オーナー裁定、ラボ機能「差替え中装備のみ
    # 頭OFF」結線): ラボ窓でONにされていればjob["dt_flag_head_hide"]へ
    # Trueを書く。OFF(既定)ならキー自体を省略する——ラボ憲章④(既定値の
    # ときは未実装状態と完全に同一)をjob.jsonの時点で満たすため。この
    # WPを境に「未実装状態」の基準はv2.6.0のDTフラグ方式からHead/Hair
    # 常時空スタブ方式へ入れ替わる(PROPOSAL §4.3)。live_template.py/
    # preflight_pak.py側もjob.get("dt_flag_head_hide", False)のキー不在を
    # 「新既定=スタブ方式」として扱う設計。
    if dt_flag_head_hide_store.load_enabled(app_root):
        job["dt_flag_head_hide"] = True

    # dev#1168(シェイプキー、2026-08-09結線): ラボ窓で保存済みの{メッシュ:
    # {キー: 値}}のうち、現在のvrm_path(このjobが対象とするアバター)と
    # 一致するものだけをjob["shape_keys"]へ書く。不一致(別アバター編集時の
    # 残留)/未設定ならキー自体を省略する——ラボ憲章④(既定値のときは
    # 未実装状態と完全に同一)をjob.jsonの時点で満たすため。
    # pipeline\blender\step01_import_vrm.py側もjob.get("shape_keys")の
    # キー不在を「値の適用無し、従来どおり全シェイプキーdrop」として扱う設計。
    shape_keys = shapekey_filter_store.load_config(app_root, vrm_path)
    if shape_keys:
        job["shape_keys"] = shape_keys

    # dev#19/dev#1370(揺れもの、L1): vrm_pathが.vrm(VRM0/VRM1)の場合のみ、
    # VRMコンテナ内のspringBoneデータをapp_py\vrm_spring_catalog.pyで
    # glTF直読み・正規化し、非空ならjob["springbones"]へ書く(prefab側の
    # physbones.jsonサイドカー搬送、dev#1356と同じ「搬送のみ」パターン)。
    # prefab入力(vrm_pathが.prefab)はこの時点でまだprefabパスのままであり
    # (Unity輸出=Phase -1はconvert.ps1側で後から行われる)、GLBコンテナでは
    # ないため対象外——prefab側の揺れものはphysbones.json(Unity輸出時に
    # 書かれるサイドカー)が別途カバーする。空(springBone無し/読み飛ばし)なら
    # キー自体を省略する——ラボ憲章④(既定値のときは未実装状態と完全に同一)
    # をjob.jsonの時点で満たすため。消費(sway写像への実結線)は別WPの
    # 自動割当エンジンが担う(本関数はここまで=搬送のみ)。
    if vrm_path.lower().endswith(".vrm"):
        spring_catalog = vrm_spring_catalog.catalog_from_vrm(vrm_path)
        # dev#1508 W1b: fail-open+ログ必須(タスク要件)。抽出失敗(壊れた
        # GLBコンテナ等)は変換自体を止めない——springboneデータが単に無い
        # だけの正常系(ok=True・空リスト)と区別し、真の失敗(ok=False)の
        # ときだけ警告を出す。
        if not spring_catalog.get("ok"):
            print(f"[write_job] WARNING: VRM SpringBone extraction failed "
                  f"(fail-open, conversion continues without springbone data): "
                  f"{spring_catalog.get('detail')}")
        springbones = spring_catalog.get("physbones") or []
        if springbones:
            job["springbones"] = springbones

    # dev#1572(2026-08-18裁定、案C: v2.11方式の復元、docstring参照):
    # 標準機能「揺れの度合い」4択(なし/やわらかめ/ふつう/かため)を
    # job["sway_intensity"]("soft"/"normal"/"hard")+job["sway_enable"]
    # (bool、アロケータのゲート)へ書く。"none"のときはどちらのキーも
    # 書かない——ラボ憲章④(既定値のときは未実装状態と完全に同一)を
    # ここでも踏襲する(dev#19プロトタイプ時代の元の設計そのもの)。
    # 旧`sway_enabled`(bool、dev#1508 W2b由来のGUI内部専用キー)はもう
    # 書かない(job.jsonへ出力するのは本WPで廃止、docstring参照)。
    if sway_intensity in ("soft", "normal", "hard"):
        job["sway_intensity"] = sway_intensity
        job["sway_enable"] = True

    # dev#19揺れものUIプロトタイプ(仕様2-3): ラボ「揺れもの詳細設定」で
    # 保存済みのチェーン単位の上書き(ON/OFF・かたさ・手動追加・安全域)の
    # うち、現在のvrm_path(このjobが対象とするアバター)と一致するものだけを
    # job["sway_chain_overrides"]へ書く。既定から変わっていない(空リスト)
    # ならキー自体を省略する——ラボ憲章④をここでも満たす。スキーマ:
    # [{"bones": [anchor, node1, ...], "enabled": bool,
    #   "hardness": "follow"|"hard"|"normal"|"soft", "manual": bool,
    #   "safety_margin": int}, ...]
    # (sway_manual job設定キー(sway_assign.py既存、GUI未結線)の想定形
    # {"bones":[anchor,node1,...], "id":...}に寄せた命名。enabled/hardness/
    # manualをsway_manualへどう写像するかは未決——本プロトタイプは搬送形
    # だけを示す(パイプライン側は本WPでは未結線)。**"safety_margin"のみ
    # 例外**: dev#1551(安全域WP、issue #1551「安全域」欄)で
    # `pipeline\blender\step02_retarget.py::_safety_margin_overrides_from_job()`
    # 経由で実際に配線(`sway_hub.plan_hub_wiring()`の先端マージ縮約)へ
    # 消費される。
    sway_chain_overrides = sway_chain_override_store.load_config(app_root, vrm_path)
    if sway_chain_overrides:
        job["sway_chain_overrides"] = sway_chain_overrides

    # dev#1418ラボ機能「生パラメータ全解放パネル」(work\wp_1418_rawparam\BRIEF.md、
    # 2026-08-15結線): ラボ窓で保存済みのfamily別生パラメータ
    # (stiffness/damping/wd/gravity_z/limit_angle)が既定(F1既定値、
    # lab_raw_sway_params_store.DEFAULT_PARAMS)と完全一致しなければ
    # job["lab_raw_sway_params"]へ書く。既定のままなら state.get_job_override()
    # がNoneを返しキー自体を省略する——ラボ憲章④(既定値のときは未実装状態と
    # 完全に同一)をjob.jsonの時点で満たすため。pipeline\py\sway_abp_build.py側も
    # job.get("lab_raw_sway_params")のキー不在を「上書き無し」として扱う設計
    # (raw_sway_params_from_job()参照)。
    lab_raw_sway_params_override = lab_raw_sway_params_store.get_job_override(app_root)
    if lab_raw_sway_params_override:
        job["lab_raw_sway_params"] = lab_raw_sway_params_override

    # dev#336(性別限定)はラボ第1弾に非搭載(2026-08-08オーナー裁定、構造
    # 制約: DT行フラグが性別共通で除外性別の首なしが必然)。job["genders"]
    # 配線はここでは行わない——ラボ窓UIの除去と対にして無効化することで、
    # 過去にgender_filter_store側へ保存済みの選択が残っていても変換結果に
    # 一切効かない(「UIが無く設定も効かない」状態)にする。
    # gender_filter_store.py・ui/gender_select_dialog.py・
    # convert_noue.py側のgenders絞り込みロジック自体は将来のA2再設計に
    # 備えて残置(このファイルからは呼ばない)。

    job_json_path = os.path.join(job_dir, "job.json")
    # File.WriteAllText(jobJson, sb.ToString(), new UTF8Encoding(false)) 相当
    # (BOM無しUTF-8)。ensure_ascii=Falseで非ASCII文字(日本語ファイル名等)を
    # \uXXXXへエスケープせず、C#のJ()(バックスラッシュ/引用符のみエスケープ)
    # と同じ見た目のJSONにする。
    with open(job_json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return job_json_path


# ---------------------------------------------------------------------------
# BuildConvertScriptPath/BuildConvertArgs/FindPwsh 相当
# ---------------------------------------------------------------------------


def build_convert_script_path(app_root: str) -> str:
    """BuildConvertScriptPath() L.1824-1827相当。"""
    return os.path.join(app_root, "pipeline", "cli", "convert.ps1")


def build_convert_args(
    script: str, job_json: str, preview_only: bool = False, materials_only: bool = False
) -> str:
    """BuildConvertArgs() L.1829-1834相当。文字列フォーマットも1:1で踏襲する。"""
    args = '-NoProfile -ExecutionPolicy Bypass -File "{}" -Job "{}"'.format(script, job_json)
    if preview_only:
        args += " -PreviewOnly"
    if materials_only:
        args += " -MaterialsOnly"
    return args


def build_unity_export_script_path(app_root: str) -> str:
    """RunUnityExport() L.2624相当。"""
    return os.path.join(app_root, "pipeline", "cli", "export_from_unity.ps1")


def resolve_unity_export_out_dir(work_root: str, prefab_path: str) -> str:
    """RunUnityExport() L.2630-2631相当(dev#298: workRoot基準のoutDirを明示的に渡す)。"""
    base = os.path.splitext(os.path.basename(prefab_path))[0]
    return os.path.join(work_root, base + "_export")


def build_unity_export_args(script: str, prefab_path: str, out_dir: str) -> str:
    """RunUnityExport() L.2639-2641相当。"""
    return '-NoProfile -ExecutionPolicy Bypass -File "{}" -Prefab "{}" -Out "{}"'.format(
        script, prefab_path, out_dir
    )


def find_pwsh(app_root: str = "", log: Optional[Callable[[str], None]] = None) -> str:
    """FindPwsh() L.2721-2739相当。

    dev#1242申し送りの共通化(本WP): このモジュール独自の探索実装(PATH+
    ProgramFilesのみ、②手動指定・③探索ログ・System32絶対パス根治のいずれも
    無し)を廃止し、blender_setup.find_pwsh()(dev#1242で三点セット化済み)へ
    委譲する形に寄せた。find_blender()(dev#23c、上のdocstring参照)と同型の
    2重実装解消。

    優先順位・挙動はblender_setup.find_pwsh()と完全に同一(env var
    D2P_PWSH_EXE → settings_pwshexe.txt → PATH上のpwsh.exe →
    <ProgramFiles>\\PowerShell\\7\\pwsh.exe →
    <SystemRoot>\\System32\\WindowsPowerShell\\v1.0\\powershell.exe(絶対パス、
    壊れたPATHでも見つかる)→ 最終フォールバック"powershell.exe")。手動指定
    (環境変数/設定ファイル)が設定されているのに実在しない場合は
    blender_setup.PwshManualPathError を送出し、黙って自動発見へは進まない
    (find_blenderと同じ「指定を無視するのが最悪」)。

    app_root: 設定ファイルsettings_pwshexe.txtの探索基準ディレクトリ。省略
    (既定"")した場合は設定ファイル探索を飛ばす(blender_setup.find_pwsh()の
    app_root=""既定動作と同じ)。既存呼び出し元(run_pipeline/run_unity_export
    はいずれもapp_rootを保持しているため、通常はそちらから渡される。

    log: 探索した場所を1行ずつ通知する任意コールバック(blender_setup.
    find_pwsh()のLogFnをそのまま転送する)。省略時は何も出力しない(既存
    呼び出し元は無改修で動く)。"""
    return blender_setup.find_pwsh(app_root, log=log)


# ---------------------------------------------------------------------------
# 標準出力の解析(AppendLog() L.2829-2883相当)
# ---------------------------------------------------------------------------

_ANSI_ESCAPE_RE = re.compile("\x1b\\[[0-9;]*[A-Za-z]")
_PROGRESS_MARK_RE = re.compile(r"##PROGRESS## (\d+) (.*)")
_AVATAR_WARN_RE = re.compile(r"##AVATAR_WARNING## (.*)")
_AVATAR_FATAL_RE = re.compile(r"##AVATAR_FATAL## (.*)")


def strip_ansi(line: str) -> str:
    """AnsiEscape正規表現によるANSIカラーコード除去(L.2829, L.2841相当)。"""
    return _ANSI_ESCAPE_RE.sub("", line)


def parse_progress_marker(line: str) -> Optional[tuple[int, str]]:
    """ProgressMark正規表現(L.2830)相当。戻り値: (0-100にクランプ済みpct, 生ラベル)
    またはマッチしなければNone。"""
    m = _PROGRESS_MARK_RE.search(strip_ansi(line))
    if not m:
        return None
    try:
        pct = int(m.group(1))
    except ValueError:
        return None
    return max(0, min(100, pct)), m.group(2).strip()


def parse_avatar_warning(line: str) -> Optional[str]:
    """AvatarWarnMark正規表現(L.2836)相当。"""
    m = _AVATAR_WARN_RE.search(strip_ansi(line))
    return m.group(1).strip() if m else None


# dev#1261(実報告DLK66VBE、20KB破損VRM疑い): ##AVATAR_WARNING##と同型だが、
# 変換を継続不能にするFATAL専用のマーカー。pipeline\blender\
# step01_import_vrm.py::cleanup_objects()がメッシュ0個を検出したとき
# `##AVATAR_FATAL## no_mesh` を出す(内部die()の英語診断文言自体は
# 問い合わせデバッグの作法(CLAUDE.md)どおり変更しない)。
# コード→i18nキーの対応表。可変部を持たない固定文言のため、AVATAR_WARNING系
# のような正規表現テンプレート表ではなく、i18n_data.jsonの通常キーへ単純に
# 対応させる(i18n.Sで5言語追従)。
#
# dev#1260(実報告CN23H3S5/R5PEK47D再検証、オーナー裁定2026-08-09):
# 必須Humanoidボーンが解決できないFATALを、pipeline\blender\vp_bl.py::
# humanoid_map_from_json()がclassify_missing_bone_reason()で2分類し、
# `##AVATAR_FATAL## humanoid_bone_unassigned` / `##AVATAR_FATAL##
# humanoid_bone_collision` のいずれかを出す。詳細な理由(命名違い・候補名)は
# 内部診断文言(die()の第2引数、英語のまま)側に残り、ここではGUI状態表示用の
# 固定文言のみを翻訳する。
_AVATAR_FATAL_I18N_KEYS: dict[str, str] = {
    "no_mesh": "MsgNoMeshFatal",
    "humanoid_bone_unassigned": "MsgHumanoidBoneUnassignedFatal",
    "humanoid_bone_collision": "MsgHumanoidBoneCollisionFatal",
    # dev#1394(実報告ATXSKRLB/ZJSU5FWD/7TXW783Q): 下記parse_palworld_not_found_fatal()
    # が返すコード。##AVATAR_FATAL##マーカー由来ではないが、GUI側の翻訳/状態表示は
    # no_mesh等と共通の仕組み(_pipeline_fatal_cause/translate_avatar_fatal)を
    # そのまま再利用する(二重の仕組みを増やさない)。
    "palworld_not_found": "MsgPalworldNotFoundFatal",
}


def parse_avatar_fatal(line: str) -> Optional[str]:
    """AVATAR_FATALマーカー行からコード(例: "no_mesh")を取り出す。"""
    m = _AVATAR_FATAL_RE.search(strip_ansi(line))
    return m.group(1).strip() if m else None


# dev#1394: Phase 0(pipeline\py\convert_noue.py::resolve_vanilla_source()、
# 他にextract_vanilla.py/build_pak_from_avatar.py/live_template.py/
# vp_avatar_compose.pyでも共通利用)のdie()が出す「Palworld本体/pakが見つから
# ない」FATALには##AVATAR_FATAL##マーカーが無い(die()呼び出し元はpipeline\py側
# で、本WPの書き込み許可範囲外のため新規マーカーを追加しない設計判断
# 〈work\wp_1394_fallback\NOTES.md §1.4参照〉)。代わりに、既に複数ファイルで
# 共通利用されている既存の安定した固定診断文言(2種、内部診断文言自体は
# CLAUDE.md方針どおり変更しない)を先頭一致で検出し、##AVATAR_FATAL##系と
# 同じ_pipeline_fatal_cause経由でGUI側へ伝える。
#   1. "Palworld was not found. Locations searched:"
#      (pipeline\py\palworld_locate.py::PalworldNotFoundError由来。Phase 0内部
#      自動発見〈vp_core.load_job()〉が完全失敗した場合)
#   2. "Palworld's pak was not found:"
#      (job.jsonに明示パス〈settings_paksdir.txtのキャッシュ由来〉があったが
#      実在しない場合のフォールバック文言)
_PALWORLD_NOT_FOUND_FATAL_MARKERS = (
    "Palworld was not found. Locations searched:",
    "Palworld's pak was not found:",
)

PALWORLD_NOT_FOUND_FATAL_CODE = "palworld_not_found"


def parse_palworld_not_found_fatal(line: str) -> Optional[str]:
    """[FATAL]行が「Palworld本体/pakが見つからない」種別かどうかを判定し、
    該当すれば##AVATAR_FATAL##系と共通のコード文字列を返す(未一致はNone)。
    die()は`[<TAG>][FATAL] {msg}`の形で出力するため(TAGはconvert_noue/
    extract_vanilla/build_pak_from_avatar等、呼び出し元により異なる)、
    タグ名には依存せず"[FATAL]"の有無と固定文言の部分一致だけを見る。"""
    stripped = strip_ansi(line)
    if "[FATAL]" not in stripped:
        return None
    if any(marker in stripped for marker in _PALWORLD_NOT_FOUND_FATAL_MARKERS):
        return PALWORLD_NOT_FOUND_FATAL_CODE
    return None


def translate_avatar_fatal(code: str, lang: Optional[str] = None) -> str:
    """AVATAR_FATALコードを現在のUI言語のユーザー向け文言へ翻訳する。
    未知のコードは原文(コード文字列)のまま返す(AVATAR_WARNING系と同じ
    「未知でも情報を落とさない」方針)。"""
    key = _AVATAR_FATAL_I18N_KEYS.get(code)
    if key is None:
        return code
    return i18n.S(key, lang)


# dev#939 ②: convert_noue.py が出す##AVATAR_WARNING##(固定英語テンプレート3種+
# 可変部)を、GUI完了ダイアログ(messagebox.showwarning)へ表示する前に翻訳する
# 対応表。translate_blender_phase/translate_progress_label_dynamic(dev#933)と
# 同じ「regexテンプレートに一致すれば翻訳、しなければ原文のまま」の方針
# (未知の警告文でも無言の空欄・??key??にせず、原文の情報を残す)。
_AVATAR_WARNING_TEMPLATES: list[tuple[re.Pattern, dict[str, str]]] = [
    (
        re.compile(
            r"^Color information for some materials could not be retrieved, "
            r"so they may not display correctly \(material=(.+)\)$"
        ),
        {
            "ja": "一部のマテリアルの色情報を取得できなかったため、"
            "正しく表示されない可能性があります(material={0})",
            "en": "Color information for some materials could not be retrieved, "
            "so they may not display correctly (material={0})",
            "ko": "일부 머티리얼의 색상 정보를 가져올 수 없어 올바르게 표시되지 "
            "않을 수 있습니다(material={0})",
            "zhTW": "部分材質的顏色資訊無法取得,可能無法正確顯示(material={0})",
            "zhCN": "部分材质的颜色信息无法获取,可能无法正确显示(material={0})",
        },
    ),
    (
        re.compile(
            r"^This avatar has an unusual UV structure and may not display "
            r"correctly \(affected material: (.+)\)$"
        ),
        {
            "ja": "このアバターは特殊なUV構造を持っているため、"
            "正しく表示されない可能性があります(影響を受けるマテリアル: {0})",
            "en": "This avatar has an unusual UV structure and may not display "
            "correctly (affected material: {0})",
            "ko": "이 아바타는 특수한 UV 구조를 가지고 있어 올바르게 표시되지 "
            "않을 수 있습니다(영향을 받는 머티리얼: {0})",
            "zhTW": "此角色具有特殊的 UV 結構,可能無法正確顯示(受影響的材質: {0})",
            "zhCN": "此角色具有特殊的 UV 结构,可能无法正确显示(受影响的材质: {0})",
        },
    ),
    (
        re.compile(
            r"^The post-atlas visual check could not be run \((.+)\)\. "
            r"Conversion continues, but broken visuals will not be automatically "
            r"detected$"
        ),
        {
            "ja": "アトラス化後の見た目チェックを実行できませんでした({0})。"
            "変換は続行しますが、見た目の破損は自動検出されません",
            "en": "The post-atlas visual check could not be run ({0}). "
            "Conversion continues, but broken visuals will not be automatically "
            "detected",
            "ko": "아틀라스 처리 후 외관 검사를 실행할 수 없었습니다({0}). "
            "변환은 계속되지만 외관 손상은 자동으로 감지되지 않습니다",
            "zhTW": "無法執行圖集化後的外觀檢查({0})。"
            "轉換將繼續進行,但外觀損壞不會被自動偵測到",
            "zhCN": "无法执行图集化后的外观检查({0})。"
            "转换将继续进行,但外观损坏不会被自动检测到",
        },
    ),
    # dev#1417: テクスチャ既定柄フォールバックのfail-loud化(pipeline\py\
    # vp_tex.py::tex_fallback_diagnostics()が出す2種の新規##AVATAR_WARNING##)。
    (
        re.compile(
            r"^Texture file '(.+)' has a \.png extension but is not a valid PNG, "
            r"so the template's default texture is used instead$"
        ),
        {
            "ja": "テクスチャファイル『{0}』は拡張子が.pngですが実際のPNGでは"
            "ないため、テンプレートの既定テクスチャを使用します",
            "en": "Texture file '{0}' has a .png extension but is not a valid "
            "PNG, so the template's default texture is used instead",
            "ko": "텍스처 파일 '{0}'은(는) 확장자가 .png이지만 실제 PNG가 아니므로 "
            "템플릿의 기본 텍스처를 사용합니다",
            "zhTW": "材質檔案『{0}』雖然副檔名為 .png,但實際上不是有效的 PNG "
            "檔案,因此將使用範本的預設材質",
            "zhCN": "材质文件『{0}』虽然扩展名为 .png,但实际上不是有效的 PNG "
            "文件,因此将使用模板的默认材质",
        },
    ),
    (
        re.compile(
            r"^Texture file '(.+)' is not a PNG file, so the template's default "
            r"texture is used instead$"
        ),
        {
            "ja": "テクスチャファイル『{0}』はPNGファイルではないため、"
            "テンプレートの既定テクスチャを使用します",
            "en": "Texture file '{0}' is not a PNG file, so the template's "
            "default texture is used instead",
            "ko": "텍스처 파일 '{0}'은(는) PNG 파일이 아니므로 템플릿의 기본 "
            "텍스처를 사용합니다",
            "zhTW": "材質檔案『{0}』不是 PNG 檔案,因此將使用範本的預設材質",
            "zhCN": "材质文件『{0}』不是 PNG 文件,因此将使用模板的默认材质",
        },
    ),
    (
        # dev#1468(オーナー裁定2026-08-15): アトラス視覚チェックがFAILしても
        # die()せず変換を継続する経路(pipeline\py\convert_noue.py::
        # _render_atlas_visual_check、"AVATAR_WARNING##" 直下のコメント参照)
        # のGUI向け翻訳。_AVATAR_WARN_REは1行=改行なし前提のため、
        # convert_noue.py側もこの警告文言は単一行で出力する。
        re.compile(
            r"^The post-atlas visual check detected a possible mismatch \((.+)\)\. "
            r"Conversion continues, but please check the appearance of the converted "
            r"avatar$"
        ),
        {
            "ja": "アトラス化後の見た目チェックで差異を検出しました({0})。"
            "変換は続行しますが、変換結果の見た目をご確認ください",
            "en": "The post-atlas visual check detected a possible mismatch ({0}). "
            "Conversion continues, but please check the appearance of the converted "
            "avatar",
            "ko": "아틀라스 처리 후 외관 검사에서 차이를 감지했습니다({0}). "
            "변환은 계속되지만 변환 결과의 외관을 확인해 주세요",
            "zhTW": "圖集化後的外觀檢查偵測到差異({0})。"
            "轉換將繼續進行,但請確認轉換結果的外觀",
            "zhCN": "图集化后的外观检查检测到差异({0})。"
            "转换将继续进行,但请确认转换结果的外观",
        },
    ),
    # dev#1625(2026-08-21 オーナー裁定): 姿勢不一致(donor骨が明後日の方向を
    # 向いたまま配線される、実機で頭部・胸部が破綻)の最小切除
    # (pipeline\blender\step02_retarget.py、SWAY_POSTURE_MISMATCH_CULL_TAG)。
    # {0}にはgenderと切除ハブ数が入る(例: "Female: 4 chain(s)")。
    (
        re.compile(
            r"^Some sway \(jiggle\) physics chains were disabled because the "
            r"source bone's posture did not match its donor closely enough "
            r"\((.+)\)$"
        ),
        {
            "ja": "アバターとの姿勢の差が大きすぎたため、一部の揺れ物理が"
            "無効化されました({0})",
            "en": "Some sway (jiggle) physics chains were disabled because the "
            "source bone's posture did not match its donor closely enough "
            "({0})",
            "ko": "아바타와의 자세 차이가 너무 커서 일부 흔들림 물리가 "
            "비활성화되었습니다({0})",
            "zhTW": "由於角色姿勢差異過大,部分搖晃物理已被停用({0})",
            "zhCN": "由于角色姿势差异过大,部分摇摆物理已被停用({0})",
        },
    ),
    # dev#1649(2026-08-22 オーナー裁定「エラーを検知して揺れなしに自動
    # フォールバックする」): 揺れ有効での変換が失敗し、揺れ無効での自動
    # 全体リトライが成功したときに_SwayFallbackHandle._on_retry_exit()が
    # 出す固定文言(可変部なし——元の失敗理由は既にログ欄に流れている
    # 生ログ行〈primary攻撃時のFATAL等〉で確認できるため、ここでは
    # 「揺れ無しでやり直した」事実だけを固定文で伝える)。
    (
        re.compile(
            r"^Sway \(jiggle\) physics processing caused an error, so the "
            r"avatar was automatically converted again with sway disabled "
            r"\(see the log above for the original error\)$"
        ),
        {
            "ja": "揺れ(ジグル)物理の処理でエラーが発生したため、"
            "揺れを無効にして自動的に変換をやり直しました"
            "(元のエラーは上のログをご確認ください)",
            "en": "Sway (jiggle) physics processing caused an error, so the "
            "avatar was automatically converted again with sway disabled "
            "(see the log above for the original error)",
            "ko": "흔들림(지글) 물리 처리에서 오류가 발생하여, 흔들림을 "
            "비활성화한 상태로 자동으로 다시 변환했습니다"
            "(원래 오류는 위 로그를 확인해 주세요)",
            "zhTW": "搖晃(jiggle)物理處理發生錯誤,因此已自動停用搖晃並"
            "重新轉換(原始錯誤請參閱上方記錄)",
            "zhCN": "摇摆(jiggle)物理处理发生错误,因此已自动停用摇摆并"
            "重新转换(原始错误请参阅上方日志)",
        },
    ),
]


def translate_avatar_warning(raw: str, lang: Optional[str] = None) -> str:
    """dev#939 ②: parse_avatar_warning()が抜き出した##AVATAR_WARNING##の中身
    (常に英語)を、現在のUI言語へ翻訳する。translate_progress_label_dynamic
    と同じフォールバック方針(_AVATAR_WARNING_TEMPLATESのどれにも一致しなければ
    原文をそのまま返す -- convert_noue.py側に新しい警告文が増えてもこの表を
    更新するまでは英語のまま表示され続けるだけで、空欄や例外にはならない)。"""
    if not raw:
        return raw
    use_lang = lang or i18n.current_lang
    for pattern, fmt_table in _AVATAR_WARNING_TEMPLATES:
        m = pattern.match(raw)
        if not m:
            continue
        fmt = fmt_table.get(use_lang) or fmt_table.get("ja")
        if not fmt:
            return raw
        try:
            return fmt.format(*m.groups())
        except (IndexError, KeyError):
            return raw
    return raw


# dev#1262: Unityエクスポート失敗ログから「UniVRMの二重導入」
# (UPMパッケージ版 com.vrmc.univrm と、Assets/VRM/ 配下への手動導入版の共存)を
# 検出する。実報告4YYV28PZの実例(GUID衝突が連続発生してExport failedに
# 至る)は次の形をとる:
#   'Packages/com.vrmc.univrm/Runtime/Format/VRMException.cs' conflicts with:
#   'Assets/VRM/Runtime/Format/VRMException.cs' (current owner)
#   ...assign a new GUID because the asset is in an immutable folder. The
#   asset will be ignored.
# 4条件すべて(UPM版への言及/手動導入版フォルダへの言及/衝突の言及/
# immutable folderの言及)が同一テキスト中に揃った場合のみ発火させる
# (単発の"conflicts with"や無関係な失敗ログでの誤検出を避けるため。
# UniVRM名指しの文字列パターンだが、NDMFプラグイン一般の除去処理
# (VRCFury dev#17裁定)とは無関係のログ解析)。
_UNIVRM_DUP_UPM_MARKER = "com.vrmc.univrm"
_UNIVRM_DUP_MANUAL_MARKERS = ("Assets/VRM", "Assets\\VRM")
_UNIVRM_DUP_CONFLICT_MARKER = "conflicts with"
_UNIVRM_DUP_IMMUTABLE_MARKER = "immutable folder"


def detect_univrm_duplicate_install(text: str) -> bool:
    """Unityエクスポートの失敗ログ(またはその抜粋)テキストから、UniVRMの
    二重導入(UPMパッケージ版+手動導入版の共存によるGUID衝突)を検出する。
    text is None/空文字列なら常にFalse。"""
    if not text:
        return False
    has_upm = _UNIVRM_DUP_UPM_MARKER in text
    has_manual = any(marker in text for marker in _UNIVRM_DUP_MANUAL_MARKERS)
    has_conflict = _UNIVRM_DUP_CONFLICT_MARKER in text
    has_immutable = _UNIVRM_DUP_IMMUTABLE_MARKER in text
    return has_upm and has_manual and has_conflict and has_immutable


# ---------------------------------------------------------------------------
# Strings.ProgressLabelTemplates 相当(可変部を含む進捗ラベルの動的翻訳)
#
# 指揮者裁定: i18n.py(WP-A1)は固定文字列辞書(ProgressLabels)のみを移植し、
# 可変部を含むテンプレート判定は進捗リレー機構と一体のこちら(WP-A2)が担当する
# (DESIGN.md §5.2 A2行「進捗ラベルの動的翻訳(ProgressLabelTemplates)は本WPの
# 担当(A1が委ねた分)」)。
# ---------------------------------------------------------------------------

_PROGRESS_LABEL_TEMPLATES: list[tuple[re.Pattern, dict[str, str]]] = [
    (
        re.compile(r"^Retargeting skeleton \+ preview \(parallel: (.+)\)$"),
        {
            "ja": "スケルトン+プレビューをリターゲット中(並列: {0})",
            "en": "Retargeting skeleton + preview (parallel: {0})",
            "ko": "스켈레톤+미리보기 리타겟 중(병렬: {0})",
            "zhTW": "正在重新定位骨架+預覽(平行: {0})",
            "zhCN": "正在重新定位骨架+预览(并行: {0})",
        },
    ),
    (
        re.compile(r"^Retargeting skeleton \((.+)\)$"),
        {
            "ja": "スケルトンをリターゲット中({0})",
            "en": "Retargeting skeleton ({0})",
            "ko": "스켈레톤 리타겟 중({0})",
            "zhTW": "正在重新定位骨架({0})",
            "zhCN": "正在重新定位骨架({0})",
        },
    ),
    (
        re.compile(r"^Generating preview image \((.+)\)$"),
        {
            "ja": "プレビュー画像を生成中({0})",
            "en": "Generating preview image ({0})",
            "ko": "미리보기 이미지 생성 중({0})",
            "zhTW": "正在產生預覽圖({0})",
            "zhCN": "正在生成预览图({0})",
        },
    ),
]


def translate_progress_label_dynamic(raw: str, lang: Optional[str] = None) -> str:
    """TranslateProgressLabelFrom() L.381-404相当の完全版(固定辞書+テンプレート)。
    固定辞書(i18n.PROGRESS_LABELS)を優先し、無ければ可変部テンプレートを試し、
    どちらにも一致しなければ原文をそのまま返す(未知ラベル=無表示を作らない
    ブラックリスト方式、L.309のコメントどおり踏襲)。"""
    if not raw:
        return raw
    if raw in i18n.PROGRESS_LABELS:
        return i18n.translate_progress_label(raw, lang)
    lang = lang or i18n.current_lang
    for pattern, fmt_table in _PROGRESS_LABEL_TEMPLATES:
        m = pattern.match(raw)
        if not m:
            continue
        fmt = fmt_table.get(lang) or fmt_table.get("ja")
        if not fmt:
            return raw
        try:
            return fmt.format(m.group(1))
        except (IndexError, KeyError):
            return raw
    return raw


# ---------------------------------------------------------------------------
# 非同期プロセス実行(RunPipeline/RunUnityExport の非同期部分、DESIGN.md §4.3)
#
# tkinterはメインスレッド以外からのウィジェット操作を許さないため、
# threading.Thread(子プロセスの出力読み取り) + queue.Queue(受け渡し) +
# root.after()によるポーリング、という定番パターンを採る。このモジュール自体は
# tkinterに依存しない(pytestからheadlessにテストできるようにするため)。
# ---------------------------------------------------------------------------


class ProcessHandle:
    """RunPipeline()/RunUnityExport()が起動する子プロセスの非同期ハンドル。

    使い方: start()で起動し、呼び出し側(main_window.py)はtkinterの
    root.after(ms, handle.poll)で定期的にpoll()を呼ぶ。poll()はUIスレッド
    (=poll()を呼んでいるスレッド)上でon_line/on_exitコールバックを実行する。
    """

    def __init__(
        self,
        shell: str,
        args: str,
        on_line: Callable[[str], None],
        on_exit: Callable[[int], None],
    ):
        self.shell = shell
        self.args = args
        self._on_line = on_line
        self._on_exit = on_exit
        self._proc: Optional[subprocess.Popen] = None
        self._queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self.exit_code: Optional[int] = None
        self.job_dir: Optional[str] = None  # RunPipeline: currentPipelineJobDir相当
        self.out_dir: Optional[str] = None  # RunUnityExport: outDir相当

    def start(self) -> None:
        # ProcessStartInfo(shell, args){UseShellExecute=false,
        # RedirectStandardOutput/Error=true, CreateNoWindow=true,
        # StandardOutputEncoding=StandardErrorEncoding=UTF8} 相当。
        # 環境変数は一切明示操作しない(env=Noneで親プロセスの環境をそのまま
        # 継承、DESIGN.md §2.1のA8ゲートcheck_env_contract相当の性質を維持)。
        # C#はOutputDataReceived/ErrorDataReceivedを別々に購読するが、どちらも
        # 同じAppendLog()へ渡す設計(L.2580-2587)なので、Python版はstderrを
        # stdoutへ合流させて単一ストリームとして読む(実効的な挙動は同じ、
        # 行の混ざり順序だけがOS/バッファリング依存になりうる合理的な簡略化)。
        cmdline = '"{}" {}'.format(self.shell, self.args)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(
            cmdline,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=None,
            creationflags=creationflags,
        )
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        proc = self._proc
        assert proc is not None
        try:
            if proc.stdout is not None:
                for raw_line in proc.stdout:
                    self._queue.put(("line", raw_line.rstrip("\r\n")))
        finally:
            code = proc.wait()
            self.exit_code = code
            self._queue.put(("exit", code))

    def poll(self) -> None:
        """tkinterのroot.after()から定期呼び出しする(§4.3のqueue.Queue+afterパターン)。
        呼び出し中のスレッド上でon_line/on_exitを実行する。dev#592層3(本丸):
        1行分のon_line呼び出しを行単位try/exceptで包む。ログ表示の失敗
        (例: UnicodeEncodeError)が1行で起きても、残りの行とexitイベント
        (完了処理: プレビュー反映・完了通知)を止めてはならない。"""
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "line":
                    try:
                        self._on_line(payload)  # type: ignore[arg-type]
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    self._on_exit(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def kill(self) -> None:
        """CancelConversion/KillConversion相当。プロセスツリーごと終了する
        (DESIGN.md §1.1 #6備考: taskkill /T /Fで足りるとされている方式を採用)。"""
        if self._proc is None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(self._proc.pid), "/T", "/F"],
                    capture_output=True,
                )
            else:
                self._proc.terminate()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# dev#1649(2026-08-22 オーナー裁定「エラーを検知して揺れなしに自動フォール
# バックする」): 揺れ処理起因のエラーで変換全体が失敗したとき、自動的に
# 揺れ無しで変換をやり直して完走させ、GUIで警告する。
#
# 発動条件は「揺れ有効(sway_intensityがsoft/normal/hardのいずれか)で、
# フル変換(preview_only/materials_onlyいずれもFalse)が失敗(exit code!=0)」
# という素朴な形にした(dev#1649指示書どおり「判断の少なさを優先」)。
# 段階の分類(Blender step02のsway割当なのか、Python側sway_abp_buildなのか、
# それとも揺れと無関係な失敗なのか)を確実に見分ける仕組みは、既存のログ
# 規約(マーカー文字列)だけでは作れず、誤判定すると「揺れと無関係な失敗
# まで握りつぶして再試行する」危険がある。素朴な全体リトライは1回だけ
# (フォールバック先job.jsonのsway_intensityは"none"=フォールバック対象外
# 条件になるため、構造的に再帰しない)。
#
# preview_only/materials_onlyを対象外にする理由: どちらも「フル変換が
# 既に一度成功している」ことを前提にした軽量パス(プレビュー再生成/
# fast_repack)であり、そこでの失敗を「揺れ起因」とみなして丸ごとフル変換
# (Blenderのstep01/02含む)を割り込ませるのは、ユーザーが要求していない
# 重い動作を勝手に始めることになるため。
#
# GUI(app_py\ui\main_window.py)側は無改修——run_pipeline()の戻り値
# (poll/is_running/kill/job_dir/out_dir/exit_code)の型がProcessHandleと
# _SwayFallbackHandleのどちらでも同じ形に見えるようにしてある
# (受入基準「揺れ有効時のこれまでの成功経路の挙動は一切変えない」を
# アーキテクチャで保証する:非対象時はProcessHandleを従来どおりそのまま
# 返す一方、対象時のみ_SwayFallbackHandleでラップする)。
# ---------------------------------------------------------------------------

_SWAY_FALLBACK_RETRY_ENABLED_INTENSITIES = frozenset({"soft", "normal", "hard"})


def _sway_fallback_eligible(sway_intensity: str, preview_only: bool, materials_only: bool) -> bool:
    """dev#1649: 自動フォールバック(揺れ無し全体リトライ)を行ってよい条件。
    揺れ無効ユーザー(sway_intensity=="none")には一切影響しない
    (=既存の正常系挙動を完全に保つ、受入基準「揺れ無効ユーザーにも影響
    ゼロ」)。"""
    return (
        sway_intensity in _SWAY_FALLBACK_RETRY_ENABLED_INTENSITIES
        and not preview_only
        and not materials_only
    )


def _clean_job_dir_for_retry(job_dir: Optional[str]) -> None:
    """dev#1649: フォールバック再実行の前に、失敗した1回目の中間状態
    (converted/build/textures/vanillaのローカル複製/logs等)を残さないよう
    job_dir配下を丸ごと削除する(直後にwrite_job()が再作成する)。

    共有キャッシュ(pipeline\\py\\live_template.pyのNOUE_MASTER_DIR、
    extract_vanilla.pyの共有バニラキャッシュ等)はjob_dir外にあるため
    影響を受けない——削除してもテンプレート一式(数百MB級)の再構築が
    毎回必要になるような重い再実行にはならない。

    削除に失敗しても(権限・ロック中ファイル等)例外を投げない(fail-open。
    write_job()がos.makedirs(exist_ok=True)するため、削除が一部失敗しても
    既存job_dirへ上書きする形でそのまま再実行を試みられる)。"""
    if job_dir and os.path.isdir(job_dir):
        shutil.rmtree(job_dir, ignore_errors=True)


def _sway_fallback_noop_line(_line: str) -> None:
    """dev#1649: フォールバック再実行(2回目)の生stdout行はGUIのon_lineへ
    中継しない(呼び出し元)。中継すると2回目実行自身の##PROGRESS##/
    ##AVATAR_FATAL##等がmain_window._pipeline_fatal_causeを上書きし、
    受入基準「リトライも失敗→**元の**エラーで報告」が壊れるため
    (main_window.py側の状態は1回目の生ログ行だけで確定させる)。
    2回目実行の完全な生ログは従来どおりconvert.ps1自身がjob_dir\\logs\\配下
    へ書く(「ログのみで診断可能」原則はディスク上のログで満たす)。"""
    return None


class _SwayFallbackHandle:
    """dev#1649: 揺れ有効での変換失敗を検知したら、揺れ無効で1回だけ全体を
    自動リトライするラッパー。main_window.pyからはProcessHandleと同じ形
    (poll()/is_running()/kill()/job_dir/out_dir/exit_code)に見える——
    呼び出し側(main_window.py)を一切変更せずに済むことがこのクラスの
    唯一の存在理由(ProcessHandle自体は無改変、既存テストへの影響ゼロ)。
    """

    def __init__(
        self,
        *,
        app_root: str,
        work_root: str,
        vrm_path: str,
        script: str,
        shell: str,
        preview_only: bool,
        materials_only: bool,
        write_job_kwargs: dict,
        on_line: Callable[[str], None],
        on_exit: Callable[[int], None],
    ):
        self._app_root = app_root
        self._work_root = work_root
        self._vrm_path = vrm_path
        self._script = script
        self._shell = shell
        self._preview_only = preview_only
        self._materials_only = materials_only
        self._write_job_kwargs = write_job_kwargs
        self._on_line = on_line
        self._on_exit = on_exit
        self._inner: Optional[ProcessHandle] = None
        self._primary_code: Optional[int] = None
        # dev#1649: ユーザー自身のCancel/ウィンドウを閉じるによる中止は
        # 「失敗」ではないため、フォールバックを発動しない
        # (main_window.py側は無改修のままkill()を呼ぶだけでこの区別が付く)。
        self._killed = False
        self.job_dir: Optional[str] = None
        self.out_dir: Optional[str] = None
        self.exit_code: Optional[int] = None

    def poll(self) -> None:
        if self._inner is not None:
            self._inner.poll()
            self.exit_code = self._inner.exit_code

    def is_running(self) -> bool:
        return self._inner is not None and self._inner.is_running()

    def kill(self) -> None:
        self._killed = True
        if self._inner is not None:
            self._inner.kill()

    def _on_primary_exit(self, code: int) -> None:
        if code == 0 or self._killed:
            self._on_exit(code)
            return
        self._primary_code = code
        self._on_line(
            f"[dev#1649] Sway (jiggle) physics may have caused this failure "
            f"(exit={code}); automatically retrying the conversion once with "
            "sway disabled (auto-fallback). Cleaning the job's work area first."
        )
        try:
            _clean_job_dir_for_retry(self.job_dir)
            fallback_job_json = write_job(
                self._app_root,
                self._work_root,
                self._vrm_path,
                sway_intensity="none",
                **self._write_job_kwargs,
            )
            fallback_args = build_convert_args(
                self._script, fallback_job_json, self._preview_only, self._materials_only)
        except OSError as ex:
            self._on_line(
                f"[dev#1649] Sway fallback setup failed ({ex}); reporting the "
                "original error instead")
            self._on_exit(code)
            return
        retry = ProcessHandle(
            self._shell, fallback_args, _sway_fallback_noop_line, self._on_retry_exit)
        retry.job_dir = os.path.dirname(fallback_job_json)
        self._inner = retry
        self.job_dir = retry.job_dir
        retry.start()

    def _on_retry_exit(self, code: int) -> None:
        if code == 0:
            self._on_line(
                "##AVATAR_WARNING## Sway (jiggle) physics processing caused "
                "an error, so the avatar was automatically converted again "
                "with sway disabled (see the log above for the original error)")
            self._on_exit(0)
        elif self._killed:
            self._on_exit(code)
        else:
            self._on_line(
                f"[dev#1649] Retry without sway also failed (exit={code}); "
                "reporting the original error above")
            self._on_exit(self._primary_code)


def run_pipeline(
    app_root: str,
    work_root: str,
    vrm_path: str,
    *,
    preview_only: bool = False,
    materials_only: bool = False,
    on_line: Callable[[str], None],
    on_exit: Callable[[int], None],
    shoulder_offset_deg: int = 0,
    merge_fingers: bool = False,
    unlit: bool = False,
    force_two_sided: bool = True,
    shadow_bar_value: int = 30,
    drop_bones_text: str = "",
    license_confirmed: bool = False,
    uniform_scale: float = 1.0,
    sway_intensity: str = "normal",
    log: Optional[Callable[[str], None]] = None,
):
    """RunPipeline() L.2547-2607相当。job.json書き出し→convert.ps1起動までを
    1呼び出しで行い、非同期ハンドルを返す。UIの状態遷移(busyBar/statusLabel/
    cancelButton等)はmain_window.py側がハンドルとon_line/on_exitコールバックを
    使って組み立てる(このモジュールはtkinterに依存しない)。

    uniform_scale: dev#560 第③段。write_job()へそのまま転送する(docstring
    参照)。

    sway_intensity(dev#1572): 標準機能「揺れの度合い」4択
    ("none"/"soft"/"normal"/"hard")。write_job()へそのまま転送する
    (write_job()のdocstring参照)。

    log(dev#1242申し送り②): find_pwsh()の探索ログを受け取る任意コールバック。
    このモジュール自体はtkinterに依存しないため、実際のログ欄への描画は
    呼び出し元(main_window.py、通常はself._log)が担う。省略時は何も出力
    しない(既存呼び出し元は無改修で動く)。

    戻り値: 通常はProcessHandle(従来どおり)。dev#1649: 揺れ有効かつ
    preview_only/materials_onlyいずれもFalseの組み合わせ(=フル変換)の
    ときだけ_SwayFallbackHandle(ProcessHandleと同じ形の薄いラッパー)を
    返す。呼び出し側の型注釈上の互換性のため戻り値の型ヒントはあえて
    ProcessHandleへ固定していない(duck typing、コメント参照)。"""
    job_json = write_job(
        app_root,
        work_root,
        vrm_path,
        shoulder_offset_deg=shoulder_offset_deg,
        merge_fingers=merge_fingers,
        unlit=unlit,
        force_two_sided=force_two_sided,
        shadow_bar_value=shadow_bar_value,
        drop_bones_text=drop_bones_text,
        license_confirmed=license_confirmed,
        uniform_scale=uniform_scale,
        sway_intensity=sway_intensity,
    )
    script = build_convert_script_path(app_root)
    args = build_convert_args(script, job_json, preview_only, materials_only)
    shell = find_pwsh(app_root, log=log)

    if not _sway_fallback_eligible(sway_intensity, preview_only, materials_only):
        handle = ProcessHandle(shell, args, on_line, on_exit)
        handle.job_dir = os.path.dirname(job_json)
        handle.start()
        return handle

    wrapper = _SwayFallbackHandle(
        app_root=app_root,
        work_root=work_root,
        vrm_path=vrm_path,
        script=script,
        shell=shell,
        preview_only=preview_only,
        materials_only=materials_only,
        write_job_kwargs=dict(
            shoulder_offset_deg=shoulder_offset_deg,
            merge_fingers=merge_fingers,
            unlit=unlit,
            force_two_sided=force_two_sided,
            shadow_bar_value=shadow_bar_value,
            drop_bones_text=drop_bones_text,
            license_confirmed=license_confirmed,
            uniform_scale=uniform_scale,
        ),
        on_line=on_line,
        on_exit=on_exit,
    )
    primary = ProcessHandle(shell, args, on_line, wrapper._on_primary_exit)
    primary.job_dir = os.path.dirname(job_json)
    wrapper._inner = primary
    wrapper.job_dir = primary.job_dir
    primary.start()
    return wrapper


def run_unity_export(
    app_root: str,
    work_root: str,
    prefab_path: str,
    *,
    on_line: Callable[[str], None],
    on_exit: Callable[[int], None],
    log: Optional[Callable[[str], None]] = None,
) -> ProcessHandle:
    """RunUnityExport() L.2612-2682相当(実プロセス起動部分)。

    log(dev#1242申し送り②): run_pipeline()と同じ、find_pwsh()の探索ログを
    受け取る任意コールバック。"""
    script = build_unity_export_script_path(app_root)
    out_dir = resolve_unity_export_out_dir(work_root, prefab_path)
    args = build_unity_export_args(script, prefab_path, out_dir)
    shell = find_pwsh(app_root, log=log)
    handle = ProcessHandle(shell, args, on_line, on_exit)
    handle.out_dir = out_dir
    handle.start()
    return handle


# ---------------------------------------------------------------------------
# busyBarのモード切替(dev#602: prefab変換で進捗マーカーが来ない長区間、busyBar
# が静止して見える問題)。
#
# C#版の実挙動(自由設計しない。以下がすべて):
#   - RunPipeline() L.2602-2603: busyBar.Style = Continuous; Value = 0
#     (フル変換=convert_noue.pyが開始直後から##PROGRESS##を出し続ける工程。
#     終始Continuousで、値はAppendLog() L.2849の`busyBar.Value = pct`のみで動く)
#   - RunUnityExport() L.2677-2679: 「実進捗マーカーが無い工程(Unity起動〜
#     インポート〜ベイク〜輸出)なのでマーキー表示にする」
#     busyBar.Style = Marquee; MarqueeAnimationSpeed = 30
#     (この工程は構造的に##PROGRESS##が一切来ない。C#はタイムアウト監視等は
#     持たず、工程の頭からMarquee固定)
#   - OnUnityExportDone() L.2686: busyBar.Style = Continuous
#     (成否に関わらず無条件でContinuousへ戻す)
#
# つまり「マーカーが長時間途絶えたらMarqueeへ」という汎用タイマーはC#に
# 存在しない。実際の切替単位は「工程(phase)」であり、フル変換は終始
# determinate、Unity輸出は終始indeterminateである。
# ---------------------------------------------------------------------------

BUSY_BAR_MODE_DETERMINATE = "determinate"
BUSY_BAR_MODE_INDETERMINATE = "indeterminate"

PHASE_PIPELINE = "pipeline"
PHASE_UNITY_EXPORT = "unity_export"


def initial_busy_bar_mode(phase: str) -> str:
    """RunPipeline() L.2602(Continuous)とRunUnityExport() L.2678(Marquee)の
    分岐を純関数化したもの。phase=PHASE_UNITY_EXPORTのみindeterminate
    (ttk Progressbarのmarquee相当)、それ以外(PHASE_PIPELINE、および未知の
    phase文字列に対する安全側フォールバック)はdeterminate。"""
    if phase == PHASE_UNITY_EXPORT:
        return BUSY_BAR_MODE_INDETERMINATE
    return BUSY_BAR_MODE_DETERMINATE


def busy_bar_mode_on_marker() -> str:
    """AppendLog()で##PROGRESS##行を受け取った時点のbusyBarモード。C#版は
    busyBar.Value = pctを代入するだけだが、それが意味を持つのはStyleが
    Continuousのときだけ(Marquee中はValueを見た目に反映しないWinForms仕様)。
    py版のttk.Progressbarはindeterminate中に["value"]を設定しても表示に
    反映されないため、マーカー到着時は明示的にdeterminateへ戻してから値を
    入れる(構造的にはUnity輸出工程では発生しない防御的な扱いだが、
    「マーカーが来た=実進捗が分かっている」を安全側で保証する)。"""
    return BUSY_BAR_MODE_DETERMINATE


# ---------------------------------------------------------------------------
# Unity輸出フェーズの無音解消(dev#602追補、問い合わせ Z5S945NP「더이상 진행
# 안 됨」= これ以上進まない、で離脱した実例への対応)。
#
# 根因(コードで確認済み。pipeline\cli\export_from_unity.ps1 L.301-302):
#   `& $editor -batchmode ... -logFile $log | Out-Null` はUnity終了までブロック
#   し、Unity自身の出力は -logFile 指定のファイルにのみ書かれ stdout には一切
#   出ない。PowerShell側もこの直前のWrite-Host以降、Unity終了まで何も
#   Write-Hostしないため、この工程は構造的に長時間(数十秒〜、初回パッケージ
#   導入時は数分)無出力になる(busyBarのmarquee化=dev#602本体、PR #633で
#   「動いて見える」ことは解決済みだが、それとは別に「何が起きているか」
#   「どれだけ経ったか」という情報が一切無いままだった)。
#
# 対応方針: export_from_unity.ps1 は変更しない(動いているps1の大改造回避、
# CLAUDE.md言語方針)。GUI側(このモジュール+main_window.py)だけで、実プロセス
# からの出力が一定時間(既定15秒、受入条件「30秒以内」に安全マージンを
# 取った値)途絶えたら、経過時間つきの合成メッセージをstatusLabel/ログ欄へ
# 追加する「ハートビート」を実装する。
#
# 負の対照の設計: ハートビートは「実行中である」以上のことを一切主張しない
# (成功を示す文言を含まない)。成否判定は従来どおりon_exit(実プロセスの
# 終了コード)のみに基づく(main_window._on_unity_export_exit)ため、実際に
# 輸出が失敗した場合はハートビートの有無に関わらず失敗表示になる。
# ---------------------------------------------------------------------------

UNITY_EXPORT_HEARTBEAT_INTERVAL_SEC = 15.0


def should_emit_unity_export_heartbeat(
    elapsed_since_last_output_sec: float,
    interval_sec: float = UNITY_EXPORT_HEARTBEAT_INTERVAL_SEC,
) -> bool:
    """最後に何か(実プロセスの出力行、または前回のハートビート)があってから
    interval_sec秒以上経過していれば True。呼び出し側(main_window.py)は
    tkinterのroot.after()による既存の80msポーリングループ(_poll_active_handle）
    から毎回この関数を呼び、Trueが返った回だけ実際にメッセージを出す
    (=ポーリング間隔よりずっと粗い実際の発火頻度になる)。"""
    return elapsed_since_last_output_sec >= interval_sec


def format_elapsed_mmss(elapsed_sec: float) -> str:
    """経過時間を mm:ss 形式の文字列にする純関数。負値・NaN等の異常値は
    00:00に丸める(防御的、経過時間表示のためだけの補助的機能が変換本体を
    巻き込んで死んではならない)。"""
    try:
        total = int(elapsed_sec)
    except (TypeError, ValueError):
        total = 0
    if total < 0:
        total = 0
    minutes, seconds = divmod(total, 60)
    return f"{minutes:02d}:{seconds:02d}"


# ---------------------------------------------------------------------------
# 早期プレビュー反映(dev#288 WP-UXIMPL提案2、DiveToPalworld.cs L.2854-2870/
# L.2957-2963相当。dev#532方針A WP-A11/dev#549で移植)。
#
# Phase1完了(39%到達)時点でプレビュー画像は既に生成済み(gender並列ブロックの
# render_preview.py実行が担当)。OnPipelineDone(全工程完了後)を待たず1回だけ
# 再読込することで、フル変換パスでの新プレビュー反映が30〜59秒早まる。
#
# 実際の画像デコード・PictureBox/Label反映(Pillow/ImageTk同梱)はB1完了後の
# WPが担う(main_window.py・DESIGN.md §1.1 #15備考のとおり、previewFront/
# previewSideは現状プレースホルダのTk Label)。ここでは「呼ぶべきタイミングか」
# の判定(should_load_early_preview、AppendLog L.2860の if 条件を純関数化)と
# 「どのファイルを読むか」の解決(load_previews、LoadPreviews L.2957-2963の
# ファイル存在確認部分)のみを、GUIフレームワーク非依存の形でここに置く
# (既存のDetectLangFromCulture/DecideBlenderSetupAction等と同じ「判定ロジック
# だけを純関数化してテスト容易にする」設計idiomを踏襲)。
# ---------------------------------------------------------------------------

EARLY_PREVIEW_THRESHOLD = 39


def should_load_early_preview(pct: int, already_loaded: bool) -> bool:
    """AppendLog() L.2860の判定
    `pct >= 39 && !earlyPreviewLoadedThisRun` を純関数化したもの。"""
    return pct >= EARLY_PREVIEW_THRESHOLD and not already_loaded


def load_previews(job_dir: str) -> dict[str, Optional[str]]:
    """LoadPreviews() L.2957-2963相当のうち、ファイル解決部分(純粋・読み取り
    のみ、書き込みなし)。存在しないファイルはNoneを返す(呼び出し側は
    Noneのキーを「画像なし」として扱う。C#のif (File.Exists(...))と同じ
    「無ければ何もしない」方針)。

    dev#1103: 従来はMale固定パスしか探さなかった(genders未指定のGUI標準
    フローでは両方生成されるため通常は隠れるが、job.jsonが`genders:
    ["Female"]`のようにFemale専用で生成された場合——convert_noue.pyの
    requested_genders絞り込み参照——Male側ファイルが最初から存在せず
    「静かに何も表示しない」症状を引き起こす構造的弱点だった)。
    GUIに性別選択ウィジェットは無い(2026-08-07時点で確認済み)ため、
    「選択」ではなく「存在する方」を解決する: Male優先(既存挙動を保つ、
    負の対照)→無ければFemaleへフォールバック→どちらも無ければ
    従来どおりfront/side共にNone。frontとsideが異なる性別から混在して
    選ばれることは無い(1性別分のペアで解決する)。"""
    conv = os.path.join(job_dir, "converted")

    def _paths(gender: str) -> tuple[str, str]:
        return (
            os.path.join(conv, f"preview_{gender}_stand.png"),
            os.path.join(conv, f"preview_{gender}_stand_side.png"),
        )

    for gender in ("male", "female"):
        front, side = _paths(gender)
        if os.path.isfile(front) or os.path.isfile(side):
            return {
                "front": front if os.path.isfile(front) else None,
                "side": side if os.path.isfile(side) else None,
            }
    return {"front": None, "side": None}


# ---------------------------------------------------------------------------
# dev#1230(2026-08-08オーナー裁定): ユーザーサイドpreflightの非ブロック化。
#
# pipeline\py\build_pak_from_avatar.py(フル変換)/pipeline\py\fast_repack.py
# (「影のみ更新(高速)」)はどちらも、job.jsonの"preflight_nonblocking"
# (このファイルのwrite_job()が常にTrueで書く)が立っているとき、preflight
# FAILでも停止せず、結果を <job_dir>\build\preflight_result.json へ記録して
# 継続する(pipeline\py\vp_preflight_result.py が書き込み側)。
# app_pyはpipeline\pyをimportしない設計方針(このファイル冒頭のコメント群、
# PAL_WINDOWS_PAK_NAME等の既存の複製パターンを参照)のため、ファイル名
# "preflight_result.json"はここでも独立した文字列リテラルとして持つ
# (vp_preflight_result.RESULT_FILENAMEと一致させること、変更時は両方直す)。
# ---------------------------------------------------------------------------

PREFLIGHT_RESULT_FILENAME = "preflight_result.json"


def resolve_preflight_result_path(job_dir: str) -> str:
    """<job_dir>\\build\\preflight_result.json のパスを返す(存在確認はしない、
    純粋なパス組み立てのみ)。"""
    return os.path.join(job_dir, "build", PREFLIGHT_RESULT_FILENAME)


def read_preflight_result(job_dir: str) -> Optional[dict]:
    """preflight_result.jsonを読む。無い(--skip-preflight/preflight
    非対応の古いジョブ/preflight_nonblocking未使用のジョブ)/壊れている場合は
    Noneを返す(呼び出し元は「preflight FAILの記録なし」として扱ってよい
    ——load_previews()と同じ「無ければ何もしない」方針)。"""
    path = resolve_preflight_result_path(job_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    return doc


def is_preflight_fail_result(result: Optional[dict]) -> bool:
    """_on_pipeline_exit()の判定を純関数化したもの(main_window.py側は
    tkinter依存のダイアログ表示だけを持てばよいようにする)。"""
    return bool(result) and result.get("status") == "FAIL"


def find_exported_fbx(out_dir: str) -> Optional[str]:
    """OnUnityExportDone() L.2701-2707相当。輸出フォルダから最初の*.fbxを返す。"""
    if not os.path.isdir(out_dir):
        return None
    hits = sorted(glob.glob(os.path.join(out_dir, "*.fbx")))
    return hits[0] if hits else None
