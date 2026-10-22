# test_progress_eta.py -- dev#137: 進捗ETA化(静的%から残り時間推定へ)。
#
# progress_eta.py の純関数(estimate_remaining_seconds等)とファイルIO
# (load_history/save_history/record_run)の単体テスト。GUI/tkinterには
# 一切依存しない(main_window.pyへの配線検証はtest_progress_eta_wiring.py
# の担当)。
#
# 設計の核心(このテストファイル全体が守る不変条件): **推定できないとき
# (履歴が無い/少ない/1件だけ)は必ずNoneを返す。でっち上げた数字を出さない**。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import progress_eta as eta  # noqa: E402


# ---------------------------------------------------------------------------
# resolve_mode
# ---------------------------------------------------------------------------


def test_resolve_mode_full_conversion():
    assert eta.resolve_mode(preview_only=False, materials_only=False) == eta.MODE_FULL


def test_resolve_mode_preview_only():
    assert (
        eta.resolve_mode(preview_only=True, materials_only=False)
        == eta.MODE_PREVIEW_ONLY
    )


def test_resolve_mode_materials_only_takes_priority():
    """呼び出し元(_start_pipeline)はpreview_only/materials_onlyを同時に
    Trueにしないが、念のためmaterials_onlyを優先する(fast_repack.py経路が
    実際に動くのはmaterials_onlyの方であるため)。"""
    assert (
        eta.resolve_mode(preview_only=True, materials_only=True)
        == eta.MODE_MATERIALS_ONLY
    )


# ---------------------------------------------------------------------------
# load_history / save_history / record_run (ファイルIO)
# ---------------------------------------------------------------------------


def test_load_history_missing_file_returns_empty_dict(tmp_path):
    assert eta.load_history(str(tmp_path)) == {}


def test_load_history_corrupt_file_returns_empty_dict(tmp_path):
    """壊れたJSONでもGUIを止めない(握りつぶして既定値、settings.pyと同じ方針)。"""
    path = eta.history_file_path(str(tmp_path))
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not valid json")
    assert eta.load_history(str(tmp_path)) == {}


def test_record_run_and_load_history_roundtrip(tmp_path):
    app_root = str(tmp_path)
    eta.record_run(app_root, eta.MODE_FULL, [(2, 1.0), (55, 30.0), (96, 58.0)], 60.0)
    history = eta.load_history(app_root)
    assert eta.MODE_FULL in history
    runs = history[eta.MODE_FULL]
    assert len(runs) == 1
    # full conversionは最後のcheckpointが100%未満(96%)なので、実測した
    # total_duration_sec(60.0)が100%到達点として補われる。
    assert runs[0][-1] == [100.0, 60.0]
    assert runs[0][0] == [2.0, 1.0]


def test_record_run_does_not_duplicate_100_when_already_present(tmp_path):
    """materials-onlyのように既に100%markerが来ているrunでは、total_durationで
    二重に100%pointを追加しない(最後の実測値をそのまま使う)。"""
    app_root = str(tmp_path)
    eta.record_run(
        app_root, eta.MODE_MATERIALS_ONLY, [(8, 1.0), (40, 20.0), (80, 40.0), (100, 45.0)], 45.2
    )
    history = eta.load_history(app_root)
    runs = history[eta.MODE_MATERIALS_ONLY]
    assert len(runs) == 1
    assert runs[0][-1] == [100.0, 45.0]  # 45.2ではなく実測checkpointの45.0のまま


def test_record_run_separates_modes(tmp_path):
    """フル変換とmaterials-onlyの履歴は別バケットに保存される(進捗の形が
    まったく別物のため混ぜてはいけない)。"""
    app_root = str(tmp_path)
    eta.record_run(app_root, eta.MODE_FULL, [(0, 0.0), (96, 90.0)], 94.0)
    eta.record_run(app_root, eta.MODE_MATERIALS_ONLY, [(8, 1.0), (100, 45.0)], 45.0)
    history = eta.load_history(app_root)
    assert eta.MODE_FULL in history
    assert eta.MODE_MATERIALS_ONLY in history
    assert history[eta.MODE_FULL] != history[eta.MODE_MATERIALS_ONLY]


def test_record_run_caps_history_at_max_runs_per_mode(tmp_path):
    app_root = str(tmp_path)
    for i in range(eta.MAX_RUNS_PER_MODE + 5):
        eta.record_run(app_root, eta.MODE_FULL, [(0, 0.0), (100, float(100 + i))], 100.0 + i)
    history = eta.load_history(app_root)
    runs = history[eta.MODE_FULL]
    assert len(runs) == eta.MAX_RUNS_PER_MODE
    # 直近分だけが残ること(最も新しいrunのtotal durationが末尾に来る)
    assert runs[-1][-1][1] == 100.0 + (eta.MAX_RUNS_PER_MODE + 5 - 1)


def test_record_run_ignores_non_monotonic_and_duplicate_checkpoints(tmp_path):
    """想定外の順序(逆行/重複pct)で来たcheckpointsも、正規化されて保存される
    (単調非減少を保証、dev#5のRelay-NoueSubphaseProgressと同じ考え方)。"""
    app_root = str(tmp_path)
    eta.record_run(
        app_root,
        eta.MODE_FULL,
        [(10, 5.0), (10, 5.5), (5, 3.0), (50, 40.0)],  # 重複10%、逆行5%を含む
        90.0,
    )
    history = eta.load_history(app_root)
    runs = history[eta.MODE_FULL]
    pcts = [p for p, _ in runs[0]]
    assert pcts == sorted(pcts)
    assert pcts.count(10.0) == 1


def test_record_run_with_no_checkpoints_and_zero_duration_is_noop(tmp_path):
    """checkpointsが空でtotal_durationも0以下なら何も記録しない(でっち上げの
    元になる空のrunをそもそも履歴に残さない)。"""
    app_root = str(tmp_path)
    eta.record_run(app_root, eta.MODE_FULL, [], 0.0)
    assert eta.load_history(app_root) == {}


# ---------------------------------------------------------------------------
# estimate_remaining_seconds -- 推定できないときはNone
# ---------------------------------------------------------------------------


def test_estimate_with_no_history_returns_none():
    assert eta.estimate_remaining_seconds([], 55, 30.0) is None


def test_estimate_with_single_history_run_is_insufficient():
    """境界: 履歴runがちょうど1件だけの場合、それを「典型的な所要時間」として
    提示するのはでっち上げに近いため、MIN_HISTORY_RUNS(2)未満はNoneとする。"""
    single_run_history = [[[0.0, 0.0], [50.0, 50.0], [100.0, 100.0]]]
    assert eta.estimate_remaining_seconds(single_run_history, 50, 50.0) is None


def test_estimate_excludes_incomplete_runs_from_validity_count():
    """100%まで到達していないrun(失敗/キャンセル等、正規化後も100%未満で
    終わっている)は有効runとしてカウントされない。2件あっても片方が
    未完了なら実質1件しか無いのと同じでNone。"""
    history = [
        [[0.0, 0.0], [50.0, 50.0], [100.0, 100.0]],  # 完了
        [[0.0, 0.0], [50.0, 48.0], [70.0, 68.0]],  # 未完了(100%到達なし)
    ]
    assert eta.estimate_remaining_seconds(history, 50, 50.0) is None


def test_estimate_current_pct_at_100_returns_zero_without_needing_history_shape():
    history = [
        [[0.0, 0.0], [100.0, 100.0]],
        [[0.0, 0.0], [100.0, 110.0]],
    ]
    assert eta.estimate_remaining_seconds(history, 100, 999.0) == 0.0


def test_estimate_with_consistent_history_returns_expected_remaining():
    """履歴あり: 2件の一致したrun(50%地点で50秒、100%地点で100秒)があり、
    今回も50%地点でちょうど50秒経過している(=履歴と同じペース)場合、
    残り時間は履歴どおり約50秒と推定されること。"""
    history = [
        [[0.0, 0.0], [50.0, 50.0], [100.0, 100.0]],
        [[0.0, 0.0], [50.0, 50.0], [100.0, 100.0]],
    ]
    remaining = eta.estimate_remaining_seconds(history, 50, 50.0)
    assert remaining is not None
    assert abs(remaining - 50.0) < 0.01


def test_estimate_scales_with_current_pace_when_running_faster_than_history():
    """今回runが履歴よりずっと速いペースで50%まで到達している(25秒 vs
    履歴50秒)場合、残り時間も履歴の半分程度に補正されること
    (ペース補正=このマシン/検体の実際の速度を反映する)。"""
    history = [
        [[0.0, 0.0], [50.0, 50.0], [100.0, 100.0]],
        [[0.0, 0.0], [50.0, 50.0], [100.0, 100.0]],
    ]
    remaining = eta.estimate_remaining_seconds(history, 50, 25.0)
    assert remaining is not None
    # pace = 25/50 = 0.5, median_remaining(50) * 0.5 = 25
    assert abs(remaining - 25.0) < 0.01


def test_estimate_interpolates_between_checkpoints_not_only_at_exact_marker_pct():
    """今回の到達%が履歴のcheckpoint間(補間が必要な値)でも推定できること。"""
    history = [
        [[0.0, 0.0], [40.0, 40.0], [100.0, 100.0]],
        [[0.0, 0.0], [40.0, 40.0], [100.0, 100.0]],
    ]
    # pct=55は40と100の間 -> 補間: 40 + (55-40)/(100-40)*(100-40) = 55
    remaining = eta.estimate_remaining_seconds(history, 55, 55.0)
    assert remaining is not None
    assert abs(remaining - 45.0) < 0.01  # 100 - 55 = 45


# ---------------------------------------------------------------------------
# 負の対照(必須): 外れ値1件が結果を支配しないこと(中央値の頑健性)
# ---------------------------------------------------------------------------


def test_estimate_is_robust_to_a_single_outlier_run():
    """境界: 外れ値が混ざる場合の挙動。3件のうち2件は「50%地点で50秒
    かかり、残り50秒で完了」という一致した履歴だが、1件だけ極端に遅い
    (50%地点で50秒、そこから500秒もかけて完了=何らかの理由で刺さった
    run)。中央値を使うことで、この外れ値1件に結果が引きずられないこと
    (単純平均だと (50+50+500)/3 ≈ 200 となり大きく歪む)。"""
    history = [
        [[0.0, 0.0], [50.0, 50.0], [100.0, 100.0]],  # 残り50秒
        [[0.0, 0.0], [50.0, 50.0], [100.0, 100.0]],  # 残り50秒
        [[0.0, 0.0], [50.0, 50.0], [100.0, 550.0]],  # 外れ値: 残り500秒
    ]
    remaining = eta.estimate_remaining_seconds(history, 50, 50.0)
    assert remaining is not None
    # 単純平均(≈200)には近くならず、中央値である50に近いこと
    assert remaining < 100.0, (
        f"外れ値1件に結果が引きずられている(remaining={remaining}、"
        "中央値ではなく平均に近い値になっている疑い)"
    )
    assert abs(remaining - 50.0) < 0.5


def test_estimate_pace_ratio_is_clamped_to_avoid_extreme_swings():
    """ペース補正の暴走防止: 今回の経過時間が履歴よりも極端に短い/長い場合、
    補正倍率は0.3〜3.0にクランプされる(でっち上げに近い極端な数字を
    出さないための安全弁)。"""
    history = [
        [[0.0, 0.0], [50.0, 50.0], [100.0, 100.0]],
        [[0.0, 0.0], [50.0, 50.0], [100.0, 100.0]],
    ]
    # pace = 5000/50 = 100倍だが3.0倍にクランプされるはず -> remaining = 50*3.0 = 150
    remaining = eta.estimate_remaining_seconds(history, 50, 5000.0)
    assert remaining is not None
    assert abs(remaining - 150.0) < 0.01
