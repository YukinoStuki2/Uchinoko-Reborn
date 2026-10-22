# -*- coding: utf-8 -*-
r"""LU層(Blender入力取得層、prefab→FBX一式)の解決ロジック一元化(dev#702 WP-1、
第3弾WP-2/WP-3で本体をdevtools\からapp_py\へ移設)。

正本: C:\P\Work\DiveToPalworld\work\rd_702\PROPOSAL.md 「WP-1: devtools/lu_export.py」節。

移設の経緯(2026-08-02、PR #776本文の構造矛盾裁定): devtools\ は配布物に含まれない
(devtools\deploy.py の EXCLUDE_TOP)ため、出荷される convert.ps1・GUIが
devtools\lu_export.py へ依存してはならない。実体を出荷される app_py\lu_export.py へ
移設し、devtools\lu_export.py は後方互換の薄いshim(relgate.py 等の既存importを
壊さないためだけの再export)にした。

目的: prefabからFBX一式(FBX本体 + humanoid.json + material_map.json + テクスチャ)を
得る「解決」ロジック(キャッシュ鮮度判定 + 必要なら export_from_unity.ps1 呼び出し)を、
CLI(pipeline\cli\convert.ps1、Phase -1)・GUI(app_py\ui\main_window.py)・
relgate(devtools\relgate.py、shim経由)の3箇所が同じ実装を共有する形で1本化する。

キャッシュ鍵はプレファブ自体のSHA256のみ(オーナー明示要件、依存アセットの変更までは
追わない、PROPOSAL根拠G)。鮮度の判定に使う署名ファイルは出力フォルダ直下の
"source_prefab.sha256"(prefab_export_sig_path())で、値は現在のprefabのSHA256の
16進文字列(改行付き)。書き込みはアトミック(.tmp書き出し→os.replace、
tests\relgate\intermediate_hash.py::save_record() と同じ流儀)。

resolve_unity_export_out_dir() / find_exported_fbx() は同じapp_py\pipeline_runner.py の
既存実装をそのままimportして再利用する(挙動を割らないため、式を複製しない。
PROPOSAL根拠F・WP-1仕様コメント)。

CLIエントリポイント(第3弾WP-2で追加): `python lu_export.py resolve --prefab <path>
--work-root <dir> --export-script <export_from_unity.ps1> --result-json <path>
[--pwsh <exe>]`。convert.ps1 Phase -1 が呼び出す(pipeline\cli\convert.ps1参照)。
結果はstdoutではなく --result-json 先のファイルへJSONで書く(PowerShell関数内で
`&`呼び出しの標準出力を戻り値ストリームに混入させてしまう前任実測バグの再発防止、
PROPOSAL根拠H)。stdout/stderrには人間可読な短い状態行のみを出す(パース対象外)。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from typing import Callable, Optional

HERE_DIR = os.path.dirname(os.path.abspath(__file__))  # app_py自身のディレクトリ
if HERE_DIR not in sys.path:
    sys.path.insert(0, HERE_DIR)

import pipeline_runner as _pipeline_runner  # noqa: E402


# ---------------------------------------------------------------------------
# ハッシュ
# ---------------------------------------------------------------------------

def hash_file_sha256(path: str) -> str:
    """ファイル内容のSHA256を16進文字列で返す。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# app_py/pipeline_runner.py の既存実装の再利用(式を複製しない)
# ---------------------------------------------------------------------------

def resolve_unity_export_out_dir(work_root: str, prefab_path: str) -> str:
    """app_py\\pipeline_runner.py:270 (RunUnityExport() L.2630-2631相当)と
    同じ式をそのまま再利用する(新規に式を複製しない、PROPOSAL WP-1仕様)。"""
    return _pipeline_runner.resolve_unity_export_out_dir(work_root, prefab_path)


def find_exported_fbx(out_dir: str) -> Optional[str]:
    """app_py\\pipeline_runner.py:720 (OnUnityExportDone() L.2701-2707相当)を
    そのまま再利用する。輸出フォルダ内で最初に見つかった*.fbxを返す(無ければNone)。
    ※本WPの仕様では明示されていないが、「out_dir内にfbx実体があるか」の判定
    (is_export_cache_fresh)・成功時の戻り値組み立て(resolve_prefab_to_fbx)の
    双方で同じロジックが必要になるため、既存関数を再利用する形にした
    (新規に別実装を複製しない、という仕様コメントの精神をそのまま延長した解釈。
    完了報告に明記)。"""
    return _pipeline_runner.find_exported_fbx(out_dir)


# ---------------------------------------------------------------------------
# キャッシュ鮮度(署名ファイル)
# ---------------------------------------------------------------------------

def prefab_export_sig_path(out_dir: str) -> str:
    return os.path.join(out_dir, "source_prefab.sha256")


def _material_map_textures_all_present(out_dir: str) -> bool:
    """dev#1104残課題(C:\\P\\Work\\DiveToPalworld\\work\\lane_1104_texaudit\\
    PROGRESS_dev1104_texaudit.md参照): material_map.jsonの"texture"フィールド
    (非null)が実際にout_dir内のファイルとして存在するかを確認する。

    実ユーザー報告(V9QTNUMH)は「material_map.jsonのtextureは非nullなのに実PNGが
    無い」状態だった。Unity輸出側の実機監査ではSaveTexture()自体に「成功を返し
    つつファイルが無い」内部経路は見つからなかった(常に検証済みで書けるか、
    例外で分かりやすく落ちるかのいずれか、本WPで修正済み)ため、根因はUnityの
    書き込みそのものより、**輸出成功後・Blender読み込み前にout_dirの中身が
    変質する外部要因**(このis_export_cache_fresh()自身が古い/不完全な出力
    ディレクトリを「新鮮」と誤認して再輸出をスキップしてしまう、という理論上の
    死角を含む)にある可能性が高いと判断した。

    material_map.json自体が存在しない場合はこの関数の対象外としてTrueを返す
    (既存のFBX+sigのみの判定に委ねる。呼び出し元の既存挙動を変えない)。
    JSONが壊れている場合は安全側(False=鮮度NG、再輸出させる)に倒す。
    """
    mm_path = os.path.join(out_dir, "material_map.json")
    if not os.path.isfile(mm_path):
        return True
    try:
        with open(mm_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    meshes = data.get("meshes", {})
    if not isinstance(meshes, dict):
        return False
    for entries in meshes.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            tex = entry.get("texture")
            if tex and not os.path.isfile(os.path.join(out_dir, tex)):
                return False
    return True


def is_export_cache_fresh(out_dir: str, prefab_path: str) -> bool:
    """out_dir内にfbx実体+sigファイルがあり、sigの値が現在のprefabのSHA256と
    一致すればTrue(キャッシュ鮮度判定の主鍵はプレファブ自体のSHA256。issue本文の
    明示要件どおり、prefab以外の依存アセット[アバター側の変更]までは追わない)。

    dev#1104残課題(_material_map_textures_all_present()のdocstring参照)により、
    material_map.jsonが存在する場合はそこが参照する非nullテクスチャが全て
    out_dir内に実在することも鮮度の条件に加える(FBX+prefabハッシュだけでは
    「テクスチャ欠落済みの出力ディレクトリ」を新鮮と誤認しうるため)。

    dev#1551 laneG5修理(2026-08-17、work\\run_1551\\gui_verify\\RESULT.md 0章):
    さらに「エクスポータ自身のソースが前回輸出時から変わっていないか」
    (exporter_schema_fingerprint()、モジュール上部の解説参照)も鮮度条件に
    加える。この署名ファイル(export_schema.sha256)が無い/現在の指紋と
    不一致なら鮮度NG——本修理より前に書かれた既存キャッシュは署名ファイル
    自体が存在しないため、次回参照時に自動的に陳腐判定され、無条件で
    1回だけ再輸出される(手動でのキャッシュ削除を要求しない)。"""
    if not os.path.isdir(out_dir):
        return False
    if not find_exported_fbx(out_dir):
        return False
    sig_path = prefab_export_sig_path(out_dir)
    if not os.path.isfile(sig_path):
        return False
    if not os.path.isfile(prefab_path):
        return False
    try:
        with open(sig_path, "r", encoding="utf-8") as f:
            saved = f.read().strip()
    except OSError:
        return False
    if not saved:
        return False
    try:
        current = hash_file_sha256(prefab_path)
    except OSError:
        return False
    if saved != current:
        return False
    schema_sig_path = exporter_schema_sig_path(out_dir)
    if not os.path.isfile(schema_sig_path):
        return False
    try:
        with open(schema_sig_path, "r", encoding="utf-8") as f:
            saved_schema = f.read().strip()
    except OSError:
        return False
    if not saved_schema or saved_schema != exporter_schema_fingerprint():
        return False
    return _material_map_textures_all_present(out_dir)


def save_export_sig(out_dir: str, prefab_path: str) -> None:
    """アトミック書き込み(.tmp→os.replace、intermediate_hash.save_recordと同じ流儀)。"""
    os.makedirs(out_dir, exist_ok=True)
    sig_path = prefab_export_sig_path(out_dir)
    tmp = sig_path + ".tmp"
    digest = hash_file_sha256(prefab_path)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(digest)
        f.write("\n")
    os.replace(tmp, sig_path)


# ---------------------------------------------------------------------------
# エクスポータのスキーマ/コード版数(dev#1551 laneG5修理、2026-08-17、
# work\run_1551\gui_verify\RESULT.md 0章が確定した根因への対処)。
#
# 背景: 鮮度判定はこれまでprefab自体のSHA256のみを見ており(モジュール
# docstring冒頭「オーナー明示要件、依存アセットの変更までは追わない」)、
# エクスポータ側(unity\DiveToPalworldExporter.cs / pipeline\cli\
# export_from_unity.ps1)の出力スキーマが進化しても一切追跡していなかった。
# dev#1508でphysbones.jsonへparams/pb_object_name/anchor_explicit_rootが
# 追加された際、prefab自体が変わらない限り既存キャッシュが無警告で「新鮮」
# のまま握り続け(実例: work\flatHaori_export\、2026-08-11作成のまま
# 6日以上放置)、GUI「揺れもの詳細」パネルの「特殊ボーンを強制セットアップ」
# が全行でparams欠落によりno-opになる実害が出た(RESULT.md 0.4節)。
#
# 対処: 「prefab自体のSHA256のみ」という鮮度鍵の要件そのものは変えない
# (依然としてprefabの中身が同じなら再輸出は起きない)——追加するのは
# 「エクスポータ自身が変わっていないか」という**別の**鮮度条件。エクスポータの
# ソースファイル自体をハッシュするため、将来のスキーマ変更のたびに手動で
# バージョン番号を上げる運用(取りこぼしの温床)には頼らない——ソース1行でも
# 変われば自動的に指紋が変わり、キャッシュが自動的に陳腐化する。
# ---------------------------------------------------------------------------

_EXPORTER_SOURCE_FILES = (
    os.path.join(os.path.dirname(HERE_DIR), "unity", "DiveToPalworldExporter.cs"),
    os.path.join(os.path.dirname(HERE_DIR), "pipeline", "cli", "export_from_unity.ps1"),
)


def exporter_schema_fingerprint() -> str:
    """現在のエクスポータ(Unity C#本体+呼び出しps1)のソース内容から合成した
    指紋(SHA256の16進文字列)。いずれかのソースファイルが見つからない
    (開発機の配置崩れ等、通常は起きない)場合は"unknown"を返す——鮮度判定側は
    "unknown"を保存済み値と比較しても常に不一致になるよう扱う(この指紋自体が
    信頼できない環境では、安全側に倒して常に再輸出させる)。"""
    h = hashlib.sha256()
    for path in _EXPORTER_SOURCE_FILES:
        if not os.path.isfile(path):
            return "unknown"
        with open(path, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def exporter_schema_sig_path(out_dir: str) -> str:
    return os.path.join(out_dir, "export_schema.sha256")


def save_exporter_schema_sig(out_dir: str) -> None:
    """アトミック書き込み(save_export_sig()と同じ流儀)。resolve_prefab_to_fbx()の
    実輸出成功時、save_export_sig()と対で呼ぶ想定。"""
    os.makedirs(out_dir, exist_ok=True)
    sig_path = exporter_schema_sig_path(out_dir)
    tmp = sig_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(exporter_schema_fingerprint())
        f.write("\n")
    os.replace(tmp, sig_path)


# ---------------------------------------------------------------------------
# 1コール解決(鮮度判定→(必要なら)Unity輸出→sig保存)
# ---------------------------------------------------------------------------

def _existing_or_none(path: str) -> Optional[str]:
    return path if os.path.isfile(path) else None


def resolve_prefab_to_fbx(
    prefab_path: str,
    out_dir: str,
    export_from_unity_ps1: str,
    pwsh_exe: str = "pwsh",
    run_fn: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
) -> dict:
    """1コールで「鮮度判定→(必要なら)Unity輸出→sig保存」まで行う。

    戻り値: {"fbx": <path>, "humanoid_json": <path or None>,
             "material_map_json": <path or None>,
             "physbones_json": <path or None>, "fresh": bool,
             "exported": bool, "ok": bool, "reason": str|None}

    physbones_json(dev#1356、揺れもの/dev#19): unity\\DiveToPalworldExporter.cs
    ExtractPhysBoneChains()が書くサイドカー(あれば)のパス。他のサイドカー
    (humanoid_json/material_map_json)と同じ「搬送のみ」パターン——本関数は
    存在すればパスをjob文脈へ載せるだけで、中身の解析・写像への結線は行わない
    (消費はapp_py\\physbone_catalog.pyのスキーマ検証+別WPの担当)。

    Unity輸出失敗時は ok=False, reason に export_from_unity.ps1 の失敗詳細
    (exit code + stderr/stdout)を入れる。

    呼び出しは subprocess.run([pwsh_exe, "-File", export_from_unity_ps1,
    "-Prefab", prefab_path, "-Out", os.path.abspath(out_dir)], ...)
    (out_dirは必ずabspathで渡す——「相対パスだとUnityプロジェクトディレクトリ
    起点で解決されて誤爆する」罠の再発防止、work\\wp_702_progress.md
    「実装中に踏んだ罠」1点目参照)。

    run_fn: subprocess.run互換の呼び出し可能オブジェクト(既定はsubprocess.run
    そのもの)。単体テストでは実Unity・実pwshを使わず、この引数をfakeへ
    差し替えて検証する(tests\\shipcheck\\test_av_scan_gate.py等の既存の
    run_fn差し替え流儀を踏襲。仕様コメントのシグネチャに無い追加キーワード
    引数だが、受入条件4「単体テストは実Unity不要」を満たすために必要な
    最小の拡張と判断した——完了報告に明記)。
    """
    result = {
        "fbx": None,
        "humanoid_json": None,
        "material_map_json": None,
        "physbones_json": None,
        "fresh": False,
        "exported": False,
        "ok": False,
        "reason": None,
    }

    out_dir_abs = os.path.abspath(out_dir)

    if is_export_cache_fresh(out_dir_abs, prefab_path):
        fbx = find_exported_fbx(out_dir_abs)
        result.update(
            {
                "fbx": fbx,
                "humanoid_json": _existing_or_none(os.path.join(out_dir_abs, "humanoid.json")),
                "material_map_json": _existing_or_none(
                    os.path.join(out_dir_abs, "material_map.json")
                ),
                "physbones_json": _existing_or_none(
                    os.path.join(out_dir_abs, "physbones.json")
                ),
                "fresh": True,
                "exported": False,
                "ok": True,
            }
        )
        return result

    cmd = [
        pwsh_exe,
        "-File",
        export_from_unity_ps1,
        "-Prefab",
        prefab_path,
        "-Out",
        out_dir_abs,
    ]
    try:
        proc = run_fn(cmd, capture_output=True, text=True)
    except OSError as exc:
        result["reason"] = "export_from_unity.ps1の起動に失敗しました: {}".format(exc)
        return result

    returncode = getattr(proc, "returncode", 1)
    if returncode != 0:
        detail = (getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "").strip()
        result["reason"] = "export_from_unity.ps1が失敗しました(exit={}): {}".format(
            returncode, detail
        )
        return result

    fbx = find_exported_fbx(out_dir_abs)
    if not fbx:
        result["reason"] = (
            "export_from_unity.ps1は成功終了(exit=0)しましたが、"
            "{}に.fbxが見つかりません".format(out_dir_abs)
        )
        return result

    save_export_sig(out_dir_abs, prefab_path)
    save_exporter_schema_sig(out_dir_abs)  # dev#1551 laneG5修理: is_export_cache_fresh()
    # が新たに要求するエクスポータ指紋を、prefab sigと対で必ず書く。
    result.update(
        {
            "fbx": fbx,
            "humanoid_json": _existing_or_none(os.path.join(out_dir_abs, "humanoid.json")),
            "material_map_json": _existing_or_none(
                os.path.join(out_dir_abs, "material_map.json")
            ),
            "physbones_json": _existing_or_none(
                os.path.join(out_dir_abs, "physbones.json")
            ),
            "fresh": False,
            "exported": True,
            "ok": True,
        }
    )
    return result


# ---------------------------------------------------------------------------
# CLIエントリポイント(第3弾WP-2: pipeline\cli\convert.ps1 Phase -1が呼び出す)
# ---------------------------------------------------------------------------

def _cli_resolve(argv: list) -> int:
    """`lu_export.py resolve ...` サブコマンド本体。

    結果はstdoutへ出さず --result-json 先のファイルへJSONで書く(モジュール
    docstring参照、convert.ps1側のstdoutパース汚染回避のため)。stdoutには
    人間可読な短い状態行だけを出す(ログ表示専用、convert.ps1はパースしない)。
    """
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="lu_export.py resolve")
    parser.add_argument("--prefab", required=True)
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--export-script", required=True)
    parser.add_argument(
        "--result-json", required=True,
        help="解決結果(JSON)の書き出し先。stdoutではなくここへ書く。",
    )
    parser.add_argument("--pwsh", default="pwsh")
    ns = parser.parse_args(argv)

    out_dir = resolve_unity_export_out_dir(ns.work_root, ns.prefab)
    result = resolve_prefab_to_fbx(ns.prefab, out_dir, ns.export_script, pwsh_exe=ns.pwsh)

    tmp_path = ns.result_json + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        _json.dump(result, f, ensure_ascii=False)
    os.replace(tmp_path, ns.result_json)

    print(
        "[lu_export] ok={} fresh={} exported={} fbx={}".format(
            result["ok"], result["fresh"], result["exported"], result["fbx"]
        )
    )
    if not result["ok"]:
        print("[lu_export] reason: {}".format(result["reason"]))
    return 0 if result["ok"] else 1


def main(argv: Optional[list] = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    if not argv or argv[0] != "resolve":
        print(
            "usage: lu_export.py resolve --prefab <path> --work-root <dir> "
            "--export-script <export_from_unity.ps1> --result-json <path> [--pwsh <exe>]",
            file=sys.stderr,
        )
        return 2
    return _cli_resolve(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
