# -*- coding: utf-8 -*-
r"""work\_shared_cache\<kind>\<fp12>\ の可視化+旧世代掃除(dev#45)。

dev#45b(WP wp_45b_followup、2026-08-02)での移設: 本モジュールの実体は
元々 devtools\disk_guard.py の一部(§5)だったが、devtools\ は配布zipに
同梱されない(app_py\build.py の _copy_app_sources()/_copy_pipeline_and_unity()
実測。コピー対象は app_py\/pipeline\/unity\/assets\/res\licenses のみで
devtools\は含まれない)。旧実装は「app_py\warm_startup.pyがwarm_cache()
完了直後に app_root\devtools\disk_guard.py を動的importして呼ぶ」配線に
なっており、devtoolsが存在しないエンドユーザーの配布版では常にスキップ
されていた(dev#45 item③=work\_shared_cache旧世代(約700MB)の死蔵掃除が
実質未達、WP wp_45b_followup 指示書「穴2」参照)。

本移設で、GCの本体ロジックを配布物に実際に含まれる app_py\ 配下へ移す。
app_py\warm_startup.py は本モジュールを(app_root経由の動的パス解決ではなく)
通常のPythonモジュールとして直接importする——本モジュール自身がwarm_startup.py
と同じapp_py\ディレクトリに同居する通常の兄弟ファイルであるため、devの
リポジトリ直下実行でもビルド後の配布物(res\app\配下、app_py\build.py::
_copy_app_sources()がapp_py\の全ファイルをそのままres\app\へコピーする)
でも常に解決できる。

devtools\disk_guard.py 側は本モジュールを呼ぶ薄いCLIラッパーとして残す
(`python devtools\disk_guard.py shared-cache-list` / `shared-cache-gc`の
既存CLIインタフェースを保つため。release.py/relgate.pyからのimportも
devtools側に残したまま動く)。

保持ポリシー(kindごとにmtime降順で上位keep_n件(既定2)/構築中ロックあり/
grace期間(既定1時間)以内 を保持)は移設前と一切変えていない(移設であって
再設計ではない、WP指示書の明示制約)。ログメッセージの文言・プレフィックス
(「[disk_guard]」)も移設前のまま変更していない(release.py/relgate.py/
tests\shipcheck\test_disk_guard.py が期待するテキストを壊さないため)。

移設元: devtools\disk_guard.py(PR #927までの版、§5 shared_cache 可視化+
旧世代掃除セクション一式)。
"""
import json
import os
import re
import stat
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
# dev実行: このファイルはリポジトリ直下\app_py\にあるため dirname(_HERE)=
# リポジトリルート。配布実行: res\app\にあるため dirname(_HERE)=res\
# (pipeline\/unity\の兄弟)。いずれの場合も pipeline\py\ は _ROOT の直下に
# 実在する(app_py\build.py::_copy_pipeline_and_unity()が res\pipeline\ を
# 作る)。
_ROOT = os.path.dirname(_HERE)

_PIPELINE_PY_DIR = os.path.join(_ROOT, "pipeline", "py")
if _PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_PY_DIR)
import vp_core as core  # noqa: E402  (dev#642: rmtree_robust、read-only施錠済みshared_cache対策)

# dev#45: work\_shared_cache\<kind>\<fp12>\ の保持ポリシー(disk_guard.pyから
# 移設、値・意味とも不変)。コード/pak/manifestが変わるたびに新fp12(=新世代)が
# 生まれる設計なので、変更のたびに世代が積み上がる。keep_n=2は「現行世代+
# 安全マージン1世代」。grace_secondsは、直前に始まった長時間変換がまさに
# その世代を読み込んでいる最中である可能性への時間的レース対策(本GCは
# ファイル読み取り中かどうかを直接検知できないため)。
SHARED_CACHE_KEEP_N = 2
SHARED_CACHE_GRACE_SECONDS = 60 * 60

# vp_core.fingerprint_hash()の出力(sha1先頭12桁hex、vp_core.shared_cache_dir参照)
_FP12_DIR_RE = re.compile(r"^[0-9a-f]{12}$")


def _dir_size_bytes(path):
    """path配下の全ファイルサイズ合計(読めないファイルはスキップ、安全側)。"""
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def _remove_file_robust(path):
    """rmtree_robust(dev#642)のファイル版。shared_cache配下のマーカー
    (<fp12>.fingerprint.json)はlock_cache_dir_readonly()の対象外(dst_dirの
    外にある兄弟ファイルのため、pipeline\\py\\vp_core.py:lock_cache_dir_readonly
    参照)で通常は書き込み可能だが、念のためread-onlyでも1回だけ解除して
    再試行する。"""
    if not os.path.exists(path):
        return
    try:
        os.remove(path)
    except OSError:
        try:
            os.chmod(path, stat.S_IWRITE)
        except OSError:
            pass
        os.remove(path)


def list_shared_cache_generations(shared_cache_root):
    """work\\_shared_cache 配下の世代を列挙する(読むだけ、副作用なし)。

    世代の実体は `<kind>/<fp12>/` ディレクトリと、その兄弟マーカー
    `<kind>/<fp12>.fingerprint.json`(vp_core.shared_cache_dir/
    build_live_template参照。マーカーはdst_dirの外に置かれる設計、
    pak化時に梱包対象として拾われないようにするため)。マーカーが無い
    `<fp12>` ディレクトリは「構築進行中/構築失敗の残骸」とみなし一覧・
    削除対象いずれからも除外する(判定できないものには触らない安全側)。

    戻り値: {kind: [entry, ...]}(entryはmtime降順)。entry = {
      "fp12": str, "dir": str, "marker": str,
      "mtime": float,   # マーカーの更新時刻。マーカーは構築完了時に1回だけ
                         # 書かれ、キャッシュヒット時の再利用では更新されない
                         # (live_template.py:_reuse_if_fresh参照)。したがって
                         # 「最終アクセス時刻」ではなく「最終構築(=この内容に
                         # なった)時刻」の代理指標——NTFSの最終アクセス時刻は
                         # 既定で更新が無効化されており信頼できないため、現状
                         # 取得できる中で最も安定した時刻をここでは採用する。
      "size_bytes": int,  # dir配下の実ファイル合計サイズ
      "locked": bool,     # 構築中クロスプロセスロック(vp_core.acquire_cache_lock
                           # が作る <fp12>.lock)の有無。ある間は必ず保持する
      "fingerprint": dict または None,  # マーカーのJSON内容(読めなければNone)
    }
    """
    result = {}
    if not os.path.isdir(shared_cache_root):
        return result
    for kind in sorted(os.listdir(shared_cache_root)):
        kind_dir = os.path.join(shared_cache_root, kind)
        if not os.path.isdir(kind_dir):
            continue
        entries = []
        for name in sorted(os.listdir(kind_dir)):
            if not _FP12_DIR_RE.match(name):
                continue
            gen_dir = os.path.join(kind_dir, name)
            if not os.path.isdir(gen_dir):
                continue
            marker = gen_dir.rstrip("\\/") + ".fingerprint.json"
            if not os.path.isfile(marker):
                continue  # マーカー無し=構築未完了/残骸の可能性、対象外(安全側)
            lock_path = gen_dir.rstrip("\\/") + ".lock"
            fingerprint = None
            try:
                with open(marker, encoding="utf-8") as f:
                    fingerprint = json.load(f)
            except (OSError, ValueError):
                fingerprint = None
            try:
                mtime = os.path.getmtime(marker)
            except OSError:
                mtime = 0.0
            entries.append({
                "fp12": name,
                "dir": gen_dir,
                "marker": marker,
                "mtime": mtime,
                "size_bytes": _dir_size_bytes(gen_dir),
                "locked": os.path.exists(lock_path),
                "fingerprint": fingerprint,
            })
        entries.sort(key=lambda e: e["mtime"], reverse=True)
        result[kind] = entries
    return result


def plan_shared_cache_gc(shared_cache_root, keep_n=SHARED_CACHE_KEEP_N,
                          grace_seconds=SHARED_CACHE_GRACE_SECONDS, now=None):
    """削除計画を作るだけの純関数(副作用なし。ディスクは読むが書かない)。

    保持ポリシー(dev#45): kindごとにlist_shared_cache_generations()の
    mtime降順(=構築完了が新しい順)に並べ、以下いずれかを満たす世代を保持する:
      1. 上位keep_n件(既定2: 現行世代+安全マージン1世代)
      2. 構築中ロック(`<fp12>.lock`)が存在する
      3. grace_seconds(既定1時間)以内に構築された
         (直前に始まった長時間変換がこの世代を参照中である可能性への
         レース対策——本GCは「読み取り中かどうか」を直接検知できないため、
         時間的な余裕で守る。確信が持てないものは消さない)
    それ以外を削除対象とする。

    戻り値: {kind: {"keep": [entry,...], "remove": [entry,...]}}"""
    now = time.time() if now is None else now
    generations = list_shared_cache_generations(shared_cache_root)
    plan = {}
    for kind, entries in generations.items():
        keep, remove = [], []
        for idx, entry in enumerate(entries):
            if idx < keep_n or entry["locked"] or (now - entry["mtime"]) < grace_seconds:
                keep.append(entry)
            else:
                remove.append(entry)
        plan[kind] = {"keep": keep, "remove": remove}
    return plan


def gc_shared_cache(report, shared_cache_root=None, work_root=None,
                     keep_n=SHARED_CACHE_KEEP_N, grace_seconds=SHARED_CACHE_GRACE_SECONDS,
                     execute=False):
    """work\\_shared_cache の旧世代掃除(dev#45)。

    **既定はdry-run**(execute=False): plan_shared_cache_gc()の削除対象を
    reportへ列挙するだけで、1バイトも消さない。execute=Trueを明示したときだけ
    core.rmtree_robust(dev#642、read-only施錠解除つき)で実削除する。

    shared_cache_rootを省略した場合は vp_core.shared_cache_root(work_root)
    (env D2P_SHARED_CACHEでの上書きに対応)を使う。work_rootも省略時は
    _ROOT\\work(devではリポジトリルート\\work、配布ではres\\work)。

    戻り値: {kind: {"kept": [fp12,...], "removed": [fp12,...]}}"""
    if shared_cache_root is None:
        work_root = work_root or os.path.join(_ROOT, "work")
        shared_cache_root = core.shared_cache_root(work_root)

    if not os.path.isdir(shared_cache_root):
        report.log(f"[disk_guard] shared_cache pruning: directory missing, skipping: {shared_cache_root}")
        return {}

    plan = plan_shared_cache_gc(shared_cache_root, keep_n=keep_n, grace_seconds=grace_seconds)
    mode = "execute" if execute else "dry-run (no deletion)"
    result = {}
    for kind, sub in plan.items():
        kept_names = [e["fp12"] for e in sub["keep"]]
        remove_entries = sub["remove"]
        removed_names = []
        for entry in remove_entries:
            if execute:
                try:
                    core.rmtree_robust(entry["dir"])
                    _remove_file_robust(entry["marker"])
                    removed_names.append(entry["fp12"])
                except OSError as e:
                    report.log(f"[disk_guard][WARN] shared_cache generation removal failed (skipping, continuing): "
                               f"{entry['dir']}: {e}")
            else:
                removed_names.append(entry["fp12"])
        size_mb = sum(e["size_bytes"] for e in remove_entries) / (1024 ** 2)
        size_note = f"(total {'removed' if execute else 'to be removed'}={size_mb:.1f}MB)" if remove_entries else ""
        report.log(f"[disk_guard] shared_cache pruning[{mode}] kind={kind}: "
                   f"kept={kept_names} {'removed' if execute else 'to remove'}={removed_names} {size_note}"
                   f"(keep limit={keep_n} generation(s)+locked+within last {grace_seconds}s kept, dev#45)")
        result[kind] = {"kept": kept_names, "removed": removed_names}
    return result


def gc_shared_cache_after_warm(report, work_root, *, keep_n=SHARED_CACHE_KEEP_N,
                                grace_seconds=SHARED_CACHE_GRACE_SECONDS, execute=True):
    """dev#45 ①: app_py\\warm_startup.pyがGUI起動時のwarm_cache()完了直後に
    呼ぶための薄いI/F。gc_shared_cache()をそのまま委譲するだけで、保持
    ポリシー(keep_n/grace_seconds/構築中ロック)自体は一切変更しない
    (この関数もplan_shared_cache_gc()を直接は呼ばず、必ずgc_shared_cache()
    経由にすることで保持ポリシーの実装が1箇所に保たれる)。

    既定execute=Trueが、gc_shared_cache()自身の既定(dry-run)と唯一異なる
    点: warm_cache完了直後という「今まさに新しい世代を構築し終えた」
    タイミングは、保持ポリシー(現行世代+安全マージン1世代+ロック中+
    直近grace秒)が最も安全に働く場面であり、ここをdry-runのままにすると
    「実装したと効いているは別」(CLAUDE.md)の再発になるため
    (CLI(shared-cache-gc)側の既定dry-runはそのまま、人間が明示的に
    --executeしない限り何も消さない安全側を維持する)。

    dev#45b(2026-08-02): 本関数はdevtools\\disk_guard.pyから移設されたが、
    呼び出しI/F(引数・戻り値・既定値)は一切変えていない。app_py\\
    warm_startup.py::_run_shared_cache_gc_after_warm()から直接呼ばれる。"""
    return gc_shared_cache(report, work_root=work_root, keep_n=keep_n,
                            grace_seconds=grace_seconds, execute=execute)
