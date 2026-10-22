# -*- coding: utf-8 -*-
"""rd_120(2026-07-29 机上調査 work\\rd_120\\PROPOSAL.md): 変換パイプライン
並列化の共有ヘルパー(pak不変設計)。

対象3点(build_pak_from_avatar.py / convert_noue.py)がそれぞれ独自に
ThreadPoolExecutor/ProcessPoolExecutorを組み立てると、"入力順を保つ"
"片方失敗でももう片方の完了を待つ" という2つの不変条件をあちこちに
重複実装することになる。ここへ1本化し、pytest(tests\\parallel\\)で
その2つの不変条件だけを実プロセス/実Blenderなしに検証する。

なぜpak不変と言えるか(rd_120 PROPOSAL 3節の実装への落とし込み):
  - run_pool_ordered()はexecutor.map()を使う。map()は「完了した順」ではなく
    「入力に渡した順」で結果を返すことがconcurrent.futures仕様として保証されて
    いるため、並列度・実行順が変わっても呼び出し元が受け取る結果列は
    逐次実行時と同じ順序になる(=ログ順・集計順を変えない)。
  - run_pair_parallel()はThreadPoolExecutor(max_workers=len(items))で全item
    (通常2件、female/male)を即座にsubmitしてから、submit順に.result()を
    呼ぶ。片方が例外(die()のSystemExitを含む——concurrent.futures.thread.
    _WorkItem.run()はBaseExceptionを捕捉してfutureへ格納するため、SystemExitも
    通常の例外と同様にfuture.result()で再送出される)を投げても、
    `with ThreadPoolExecutor() as ex:` のcontext managerがshutdown(wait=True)を
    __exit__で呼ぶため、例外が呼び出し元へ伝播しきる前に**もう片方の処理も
    最後まで走り切る**(=両方の診断ログ・副作用ファイルが残る。
    rd_120 PROPOSAL 8節論点2で許容範囲と評価済みの trade-off)。
"""
import concurrent.futures
import os


def run_pair_parallel(fn, items):
    """items(通常2要素)の各要素を独立にfn(item)へ渡し、ThreadPoolExecutorで
    並列実行して**入力順**の結果リストを返す。

    fnがsubprocess.run()などブロッキングI/O待ちの処理を含む場合に向く
    (GILは関係ない。プロセスを増やす必要はない)。

    片方が例外を投げても、context managerのshutdown(wait=True)がもう片方の
    完了を待ってから例外を伝播する(モジュールdocstring参照)。"""
    items = list(items)
    if not items:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(items)) as ex:
        futures = [ex.submit(fn, item) for item in items]
        return [fut.result() for fut in futures]


def run_pool_ordered(worker_fn, tasks, n_workers, initializer=None, initargs=(),
                      executor_factory=concurrent.futures.ProcessPoolExecutor):
    """tasksをworker_fnへ並列分配し、**入力順を保った**結果リストを返す。

    executor_factoryは既定でProcessPoolExecutor(CPUバウンドなPython処理向け、
    rd_120 5.1のPhase2 SK注入ループを想定)。テスト時はThreadPoolExecutor等を
    注入することで、実プロセス起動コストを払わずに「入力順=出力順」
    「1件の失敗が他タスクの実行・収集を止めない」という不変条件だけを検証できる
    (worker_fn自体は例外を投げず(ok=False, ...)形の結果を返す設計を前提とする
    ——build_pak_from_avatar._injection_worker参照)。"""
    with executor_factory(max_workers=n_workers, initializer=initializer,
                           initargs=initargs) as ex:
        return list(ex.map(worker_fn, tasks))


def _parse_positive_int_env(env_var):
    """env_varが正の整数として解釈できればその値、できなければNoneを返す
    (default_worker_count()/adaptive_worker_count()で共有する解析ロジック。
    分岐がずれると「明示上書き時はメモリクランプを無視する」判定が
    default_worker_count()自身の判定基準とズレる恐れがあるため1本化した)。"""
    override = os.environ.get(env_var)
    if not override:
        return None
    try:
        n = int(override)
    except ValueError:
        return None
    return n if n >= 1 else None


def default_worker_count(env_var, floor=2):
    """既定ワーカー数 = max(1, cpu_count - floor)。env_var環境変数が正の整数で
    設定されていればそれを最優先する(rd_120 PROPOSAL 8節論点1: WSB等の低スペック
    機やユーザー環境向けの手動上書き口。GUI設定には出さず環境変数のみ
    ——「設定項目は少ないほうがいい」方針、feedback-fewer-user-settings.md)。"""
    override = _parse_positive_int_env(env_var)
    if override is not None:
        return override
    cpu = os.cpu_count() or 4
    return max(1, cpu - floor)


def _windows_available_memory_bytes():
    """Windowsの利用可能物理メモリ(バイト)。ctypes経由でkernel32の
    GlobalMemoryStatusExを呼ぶだけで、新規依存(psutil等)を一切追加しない
    (dev#1176 WP指示書: 新規依存の追加は聖域)。Windows以外・API呼び出し失敗時は
    None を返す(「道具は分からないときに黙る」——推測値でクランプしない。
    呼び出し側はNoneをフォールバック指示として扱う)。"""
    if os.name != "nt":
        return None
    try:
        import ctypes

        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
        if not ok:
            return None
        return int(stat.ullAvailPhys)
    except Exception:
        # dev#1176: 取得手段が使えない環境(将来の非Windows対応やAPI変更)でも
        # ここで確実に失敗を吸収し、呼び出し側を常にフォールバックさせる。
        return None


def adaptive_worker_count(env_var, floor=2, mem_probe=None,
                           min_mb_per_worker=512, reserve_mb=1024):
    """default_worker_count()の結果を、利用可能メモリの少なさでのみ**下限側に
    クランプする**(dev#1176: 実報告WEARE5UK、ProcessPoolExecutorのワーカー
    起動時=multiprocessing.reduction.dumpでのpickle転送でMemoryErrorが実際に
    発生したことへの対策)。

    設計方針(WP指示書どおり):
      - 通常メモリ環境ではCPUベースの既定値から**下げない**(速度退行として
        扱う)。あくまで低メモリ環境でのみ効く下限クランプ。
      - env_varで明示的にワーカー数を上書きしている場合はユーザーの意思を
        優先し、メモリクランプは適用しない(default_worker_count()自身が
        既に無条件で上書き値を返す挙動と一致させる)。
      - メモリを取得できない場合(mem_probeがNone/例外/0以下を返す)は
        クランプせずdefault_worker_count()の値をそのまま返す(推測値で
        クランプしない)。

    mem_probe: 利用可能メモリ(バイト)を返す0引数callable。省略時は
    _windows_available_memory_bytes(Windows専用、ctypes経由、新規依存なし)。
    単体テストではここへ固定値を返すフェイクを注入して、実OSのメモリ状態に
    依存せず低メモリ/通常メモリ/取得失敗の3条件を決定的に検証する
    (tests\\parallel\\test_adaptive_worker_count_dev1176.py)。

    min_mb_per_worker/reserve_mb: ワーカー1プロセスあたりに見込む最低メモリ量
    (spawn直後のインタプリタ起動+pickle転送分の保守的な下限)と、OS/他アプリの
    ために常に空けておく予約分。値を実測に寄せて調整する類のパラメータでは
    なく、「ワーカー起動そのものが安全に行える最低ライン」という構造的な
    見積りなので、恒常3検体のrelgateで通常メモリ環境が退行しないこと
    (PROGRESS.md参照)で妥当性を裏取りしている。"""
    base = default_worker_count(env_var, floor=floor)
    if _parse_positive_int_env(env_var) is not None:
        return base
    probe = mem_probe or _windows_available_memory_bytes
    try:
        available = probe()
    except Exception:
        available = None
    if not available or available <= 0:
        return base
    usable = max(0, available - reserve_mb * 1024 * 1024)
    mem_cap = max(1, usable // (min_mb_per_worker * 1024 * 1024))
    return min(base, int(mem_cap))
