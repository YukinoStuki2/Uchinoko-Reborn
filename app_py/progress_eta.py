# progress_eta.py -- 変換の残り時間推定(ETA)。dev#137。
#
# 背景: dev#5(PR #307でclose済み)は「55%->96%間で##PROGRESS##が一切来ない
# 見かけ上の停滞」を、convert_noue.pyの工程境界行を中継して中間マーカーを
# 増やすことで解決した。本モジュールが扱うのはその先——マーカー自体は
# 来ていても、区間ごとの実所要時間は検体・マシンごとに大きく違い、静的な
# %表示だけでは「あとどれくらいか」が伝わらない、という体感面の問題
# (出典: work/rd_125/PROPOSAL.md 第19案)。
#
# 既存ログ調査の結論(着手前にPR本文へも転記する):
#   - res\logs\launch.log は毎起動 "w"(上書き)で開かれる(app_py\main.py
#     _setup_launch_log)。##PROGRESS##行自体はここに残るが、行ごとの
#     タイムスタンプが無く、かつ次回起動で消える。
#   - pipeline\cli\convert.ps1 のPROGRESSマーカー(Write-Host経由)にも
#     PowerShell側は時刻を付けていない。$JobDir\build\logs\配下の各種.logも
#     同様に「区間到達"時刻"」を記録していない。
#   - 既存ログのどこにも「この検体のこの区間は何秒かかったか」を復元できる
#     情報が無いため、既存ログの集計だけではETAを作れない。
# 対応: 変換の実処理・ログ出力は一切変えず、GUI側(main_window.py)が
# ##PROGRESS##到着時点で(到達%, 経過秒)を記録し、実行成功時にだけ
# この履歴ファイルへ追記する、という最小限の記録だけをここに追加する。
#
# 恒常領域: app_root直下(settings.py の settings_*.txt と同じ置き場。
# work\ 配下には恒常データを置かない、というプロジェクト全体の方針
# 〈feedback-no-persistent-data-in-work〉に従う。GUIにとっての唯一の
# 恒常書き込み領域はapp_root直下であり、devtools側の.devonly\state\は
# 配布物(zip)には含まれないため使えない)。
#
# 設計原則(このモジュール全体を貫く唯一のルール): **推定できないときは
# Noneを返す。でっち上げた数字を絶対に出さない**(道具は分からないときに
# 黙る、が本プロジェクトの原則)。呼び出し側(main_window.py)はNoneのとき
# 現行の%表示のままにする(フォールバック)。
from __future__ import annotations

import json
import os
from typing import Optional

HISTORY_FILENAME = "progress_history.json"

# 直近何件を保持するか(無限成長防止。1検体あたり数十バイト〜数百バイト
# 程度なので実害は無いが、上限を設けないこと自体が「際限なく成長する
# ファイル」という別の負債になるため明示的に切る)。
MAX_RUNS_PER_MODE = 20

# 有効runがこれ未満なら「推定不能」とみなす(1件だけの履歴を「典型的な
# 所要時間」として提示するのは、外れ値1件がそのまま数字化されるという
# 意味で「でっち上げ」に近いため、最低2件を要求する)。
MIN_HISTORY_RUNS = 2

# 変換モードごとに進捗の形(marker配置)がまったく異なる(materials-only
# は8/40/80/100、preview-onlyは3〜80止まり、full conversionは2〜96+終了)ため、
# 履歴はモードごとに完全に分離して蓄積する(異なる形状を混ぜると比較自体が
# 無意味になる)。
MODE_FULL = "full"
MODE_PREVIEW_ONLY = "preview_only"
MODE_MATERIALS_ONLY = "materials_only"


def resolve_mode(preview_only: bool, materials_only: bool) -> str:
    """_start_pipeline()の引数から履歴バケットのキーを決める。"""
    if materials_only:
        return MODE_MATERIALS_ONLY
    if preview_only:
        return MODE_PREVIEW_ONLY
    return MODE_FULL


# ---------------------------------------------------------------------------
# 恒常履歴ファイルの読み書き
# ---------------------------------------------------------------------------


def history_file_path(app_root: str) -> str:
    return os.path.join(app_root, HISTORY_FILENAME)


def load_history(app_root: str) -> dict:
    """壊れている/存在しない場合は空辞書(settings.pyと同じ「握りつぶして
    既定値」方針。履歴が読めないだけでGUIを止めてはならない)。"""
    path = history_file_path(app_root)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_history(app_root: str, history: dict) -> None:
    """書き込み失敗は握りつぶす(履歴が1件残らなくても変換本体には
    影響させない、settings._write_textと同じ方針)。"""
    path = history_file_path(app_root)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False)
    except OSError:
        pass


def _normalize_checkpoints(
    checkpoints: list[tuple[float, float]],
) -> list[list[float]]:
    """(pct, 経過秒)の並びを、pctについて単調増加になるよう正規化する
    (同一pctの重複・逆行〈想定外の順序で来た場合の防御〉は後着を捨てる)。"""
    cleaned: list[list[float]] = []
    last_pct = -1.0
    for pct, elapsed in checkpoints:
        if pct is None or elapsed is None:
            continue
        if pct <= last_pct:
            continue
        if elapsed < 0:
            continue
        cleaned.append([float(pct), float(elapsed)])
        last_pct = pct
    return cleaned


def record_run(
    app_root: str,
    mode: str,
    checkpoints: list[tuple[float, float]],
    total_duration_sec: float,
) -> None:
    """1回の完了済み変換の区間到達記録を恒常履歴へ追記する。

    呼び出し側(main_window._on_pipeline_exit)は成功時(code==0)にのみ
    呼ぶこと。失敗/キャンセルされたrunをETAの母集団に混ぜると、
    「失敗するまでの時間」が「完了までの時間」に化けて推定を歪める
    (この関数自身は成否を判定しない=呼び出し側の責務)。

    full conversionはconvert.ps1が最後に明示的な"Progress 100"を出さない
    (96%表示のまま終了コード0でプロセスが終わる、pipeline\\cli\\convert.ps1
    参照)。そのため最後のcheckpointが100%未満なら、実測した
    total_duration_sec(プロセス終了までの実経過秒)を100%到達点として
    補って記録する。"""
    cleaned = _normalize_checkpoints(checkpoints)
    if total_duration_sec is not None and total_duration_sec > 0:
        if not cleaned or cleaned[-1][0] < 100:
            cleaned.append([100.0, float(total_duration_sec)])
    if not cleaned:
        return
    history = load_history(app_root)
    runs = history.get(mode)
    if not isinstance(runs, list):
        runs = []
    runs.append(cleaned)
    if len(runs) > MAX_RUNS_PER_MODE:
        runs = runs[-MAX_RUNS_PER_MODE:]
    history[mode] = runs
    save_history(app_root, history)


# ---------------------------------------------------------------------------
# 推定本体(純関数。GUI/ファイルIOに一切依存しない)
# ---------------------------------------------------------------------------


def _interpolate_time_at_pct(
    checkpoints: list[list[float]], pct: float
) -> Optional[float]:
    """1回分の履歴run(pctについて昇順のcheckpoints)から、指定pctに
    到達した時点の経過秒を線形補間で求める。空リストはNone。"""
    if not checkpoints:
        return None
    first_pct, first_t = checkpoints[0]
    if pct <= first_pct:
        # 最初のcheckpointより手前を問われた場合、原点(0秒地点)からの
        # 比例で近似する(0%地点そのものの記録は無いため)。
        if first_pct <= 0:
            return first_t
        return first_t * (pct / first_pct)
    for (p0, t0), (p1, t1) in zip(checkpoints, checkpoints[1:]):
        if p0 <= pct <= p1:
            if p1 == p0:
                return t0
            ratio = (pct - p0) / (p1 - p0)
            return t0 + ratio * (t1 - t0)
    # pctが記録済みの最終checkpointを超えている(=そのrunでは既に
    # 完了しているはずの地点)
    return checkpoints[-1][1]


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def estimate_remaining_seconds(
    history_runs: list[list[list[float]]],
    current_pct: int,
    current_elapsed_sec: float,
) -> Optional[float]:
    """現在の到達%+経過秒から、残り時間(秒)を推定する。

    引数:
      history_runs: 同一モード内の完了済みrunのcheckpoints列
                    (各要素は [[pct, elapsed_sec], ...] のリスト。
                    record_run()が返す形をそのまま渡す想定)。
      current_pct: 今回の到達%。
      current_elapsed_sec: 今回runの開始からの経過秒。

    戻り値: 推定残り秒数、または推定不能を示すNone。

    アルゴリズム:
      1. 100%まで到達し、かつ2点以上のcheckpointsを持つrunだけを
         「有効run」とする。有効runがMIN_HISTORY_RUNS未満ならNone
         (1件だけの履歴を「典型的な所要時間」として提示するのは
         でっち上げに近い)。
      2. 各有効runについて、current_pctへ到達した時刻(補間)と
         100%到達時刻の差分(=「ここから完了までにかかったはずの時間」)
         を求める。
      3. その差分群の中央値を「典型的な残り時間」とする(外れ値1件が
         紛れ込んでも中央値なら支配されない、負の対照テストの対象)。
      4. 中央値算出に使ったrunの「current_pctまでの到達時間」に対する
         現在の実経過時間の比(ペース比)の中央値を掛け、このマシン/
         この検体の実際のペースへ補正する。極端な補正(履歴序盤のごく
         僅かなズレが後半で増幅する)を避けるため0.3〜3.0倍にクランプする。
    """
    valid_runs = [r for r in history_runs if len(r) >= 2 and r[-1][0] >= 100]
    if len(valid_runs) < MIN_HISTORY_RUNS:
        return None
    if current_pct >= 100:
        return 0.0

    remaining_samples: list[float] = []
    pace_ratios: list[float] = []
    for run in valid_runs:
        t_at_pct = _interpolate_time_at_pct(run, current_pct)
        t_at_100 = run[-1][1]
        if t_at_pct is None or t_at_100 <= t_at_pct:
            continue
        remaining_samples.append(t_at_100 - t_at_pct)
        if t_at_pct > 0:
            pace_ratios.append(current_elapsed_sec / t_at_pct)

    if len(remaining_samples) < MIN_HISTORY_RUNS:
        return None

    median_remaining = _median(remaining_samples)
    if pace_ratios:
        pace = _median(pace_ratios)
        pace = max(0.3, min(3.0, pace))
        median_remaining *= pace

    return max(0.0, median_remaining)
