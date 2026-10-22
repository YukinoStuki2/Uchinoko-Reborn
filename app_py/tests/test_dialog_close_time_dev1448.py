# test_dialog_close_time_dev1448.py -- dev#1448: 全サブウィンドウの閉時間
# 閾値検査を恒常自動テストとして固定する。
#
# 背景: dev#1437(オーナー実機報告「OK/×どちらでも閉じるまで非常に長い」)の
# 真因は tkinter の生 destroy() 呼び出しそのもの(1ウィジェット=1回の
# Tclラウンドトリップ)がウィジェット数に比例して積み上がることだった
# (work\wp_labdlg_fix\NOTES.md、修正=PR #1445の行あたりウィジェット削減)。
# 発進メモ(BRIEF.md)によれば「フィクスチャの効く次元=行数×行あたり
# ウィジェット数」であり、この効き方は sway_chain_dialog.py 以外の
# チェックリスト系ダイアログにも共通する構造(equipment_select_dialog.py等
# 多数がcanvas+innerフレーム+チェックボックス/ボタンの同型パターン)。
# 本ファイルは「回帰したら機械的に検出する」ための恒常テストであり、
# dev#1437修正のあった個別ダイアログだけでなく、同型のリスクを持つ
# サブウィンドウ全体を対象にする。
#
# 計測方法: 各ダイアログを代表規模のデータで開き、WM_DELETE_WINDOW
# ハンドラ(×ボタン相当。dlg.protocol("WM_DELETE_WINDOW")で取得できる
# 実際のTclコマンド名をdlg.tk.call()で叩く——ユーザーが×を押すのと
# 同じ経路)を起動してからdestroy完了までの実時間を計測する。
# 環境ブレ対策として毎回「開いて閉じる」を2回実行し、速い方の値を採用する
# (BRIEF.md「閾値を緩める方向で解決しない」の指示どおり、遅い方の1回に
# 引きずられての誤検出だけを避ける狙いで、判定自体は厳しいほうを残す
# 設計にはしていない=単純にmin()を取るだけ)。
#
# 対象ダイアログの棚卸し(2026-08-15、本WP着手時にapp_py\ui\を実地調査):
#   sway_chain_dialog / equipment_select_dialog / headequip_select_dialog /
#   mesh_delete_dialog / drop_bones_dialog / shapekey_select_dialog /
#   dt_flag_head_hide_dialog / gender_select_dialog / preflight_warning_dialog /
#   support_dialog / lab_window(ラボ窓本体、open_lab_window)
#   計11ウィンドウ。output_folder_dialog(PR #1454)は本ブランチのbase
#   (master)時点で app_py\ui\ に実体が存在しない(未マージ)ため対象から
#   除外した——詳細はC:\P\Work\DiveToPalworld\work\wp_1448_closetime\NOTES.md。
#   multi_avatar_pak_dialogも一覧に含める(BRIEF「ほか」の対象、装備コード数
#   ぶんのボタンをcanvas上に並べる同型のスケールリスクを持つため)。
#
# 代表規模の設計(ダイアログごとの実データ次元に合わせた「行数」相当):
#   sway_chain_dialog: 600チェーン(BRIEF.md本文が明示する「600行級」)。
#   mesh_delete_dialog/drop_bones_dialog: 400件(複雑な衣装持ちアバターの
#     メッシュ数・ボーン数の実測上限帯を想定)。
#   equipment_select_dialog/headequip_select_dialog/multi_avatar_pak_dialog:
#     400件(Palworld側装備カタログの現実的な規模帯)。
#   shapekey_select_dialog: 1メッシュに400シェイプキー(検索UIが必須なほど
#     数千個持つ場合があるとモジュールdocstringに明記されている、初期表示は
#     最初に自動選択される1メッシュぶんのみ描画されるため、そのメッシュに
#     まとめて乗せることで「初期描画コスト」を代表させる)。
#   support_dialog/preflight_warning_dialog/gender_select_dialog/
#     dt_flag_head_hide_dialog/lab_window: 固定レイアウト(行数に比例する
#     動的ウィジェット生成を持たない)ため、通常起動のまま計測する。
#
# 実tk.Tk()は作らない(conftest.pyの共有hidden_root、既存慣例踏襲)。
from __future__ import annotations

import os
import sys
import tempfile
import time
import tkinter as tk
from unittest import mock

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)
_ROOT_DIR = os.path.dirname(_APP_PY_DIR)
_PIPELINE_PY_DIR = os.path.join(_ROOT_DIR, "pipeline", "py")
if _PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_PY_DIR)

from ui import dt_flag_head_hide_dialog as dfh  # noqa: E402
from ui import drop_bones_dialog as dbd  # noqa: E402
from ui import equipment_select_dialog as esd  # noqa: E402
from ui import gender_select_dialog as gsd  # noqa: E402
from ui import headequip_select_dialog as hed  # noqa: E402
from ui import lab_window  # noqa: E402
from ui import mesh_delete_dialog as mdd  # noqa: E402
from ui import multi_avatar_pak_dialog as mapd  # noqa: E402
from ui import preflight_warning_dialog as pwd  # noqa: E402
from ui import shapekey_select_dialog as skd  # noqa: E402
from ui import support_dialog as spd  # noqa: E402
from ui import sway_chain_dialog as scd  # noqa: E402

import multi_avatar_pak_store as maps_store  # noqa: E402
import vp_avatar_library as val  # noqa: E402  (multi_avatar_pak_dialog試験の下ごしらえ用)
import vp_equipment_avatar as vea  # noqa: E402  (同上)

# ---------------------------------------------------------------------------
# 計測ハーネス
# ---------------------------------------------------------------------------

_CLOSE_THRESHOLD_SECONDS = 2.0
_CATALOG_ROW_COUNT = 400
_SWAY_ROW_COUNT = 600


def _invoke_close_and_measure(dlg: tk.Toplevel) -> float:
    """dlgのWM_DELETE_WINDOWハンドラ(×ボタンを押した場合と同じTclコマンド)
    を実際に起動し、destroy完了までの実経過時間(秒)を返す。呼び出し後、
    dlgは破棄済みなので以後参照しないこと。"""
    cmd = dlg.protocol("WM_DELETE_WINDOW")
    assert cmd, "WM_DELETE_WINDOWハンドラが登録されていない(×ボタンで閉じられない状態)"
    t0 = time.perf_counter()
    dlg.tk.call(cmd)
    return time.perf_counter() - t0


def _best_of_two_close_seconds(build_dlg) -> float:
    """build_dlg()(引数無し、呼ぶたびに新しいtk.Toplevelを1個返す)で
    「開いて閉じる」を2回計測し、速い方(環境ブレの影響が少ない側)を返す。
    BRIEF.md「閾値を緩める方向で解決しない」の指示どおり、この関数自体は
    判定を甘くしない——単に2回中の最良値を代表値として採用するだけで、
    採用後の閾値比較(_CLOSE_THRESHOLD_SECONDS)は変更しない。"""
    times = [_invoke_close_and_measure(build_dlg()) for _ in range(2)]
    return min(times)


def _assert_within_threshold(dialog_name: str, elapsed: float) -> None:
    assert elapsed < _CLOSE_THRESHOLD_SECONDS, (
        f"{dialog_name}: 閉じるのに {elapsed:.3f}s かかった"
        f"(閾値 {_CLOSE_THRESHOLD_SECONDS:.1f}s 超過、dev#1448)"
    )


# ---------------------------------------------------------------------------
# 1. sway_chain_dialog(揺れもの詳細設定) -- 600チェーン
# ---------------------------------------------------------------------------


def test_sway_chain_dialog_close_time_dev1448(hidden_root, tmp_path, monkeypatch):
    big_chains = [
        {
            "anchor": "J_Bip_C_Hips",
            "bones": ["J_Bip_C_Hips", f"Sway_{i:04d}_01", f"Sway_{i:04d}_02"],
            "node_count": 2,
        }
        for i in range(_SWAY_ROW_COUNT)
    ]
    monkeypatch.setattr(scd, "SAMPLE_CHAINS", big_chains)

    def build() -> tk.Toplevel:
        ctx = scd.SwayChainContext(
            app_root=str(tmp_path), work_root=str(tmp_path),
            avatar_path="C:\\fake_dev1448.vrm", sample_mode=True,
        )
        return scd.show_sway_chain_dialog(hidden_root, ctx)

    elapsed = _best_of_two_close_seconds(build)
    _assert_within_threshold("sway_chain_dialog", elapsed)


# ---------------------------------------------------------------------------
# 2. mesh_delete_dialog(メッシュ削除) -- 400メッシュ名
# ---------------------------------------------------------------------------


def test_mesh_delete_dialog_close_time_dev1448(hidden_root, tmp_path, monkeypatch):
    names = [f"mesh_{i:04d}" for i in range(_CATALOG_ROW_COUNT)]
    monkeypatch.setattr(
        mdd, "query_mesh_catalog",
        lambda *_a, **_k: {"ok": True, "source": "test",
                            "detail": "dev#1448 representative scale", "names": names},
    )

    def build() -> tk.Toplevel:
        ctx = mdd.MeshDeleteContext(
            app_root=str(tmp_path), work_root=str(tmp_path),
            avatar_path="C:\\fake_dev1448.vrm",
        )
        return mdd.show_mesh_delete_dialog(hidden_root, ctx)

    elapsed = _best_of_two_close_seconds(build)
    _assert_within_threshold("mesh_delete_dialog", elapsed)


# ---------------------------------------------------------------------------
# 3. drop_bones_dialog(ボーンでメッシュ削除) -- 400ボーン名
# ---------------------------------------------------------------------------


def test_drop_bones_dialog_close_time_dev1448(hidden_root, tmp_path, monkeypatch):
    names = [f"bone_{i:04d}" for i in range(_CATALOG_ROW_COUNT)]
    monkeypatch.setattr(
        dbd, "query_bone_catalog",
        lambda *_a, **_k: {"ok": True, "source": "test",
                            "detail": "dev#1448 representative scale", "bones": names},
    )

    def build() -> tk.Toplevel:
        ctx = dbd.DropBonesContext(
            app_root=str(tmp_path), work_root=str(tmp_path),
            avatar_path="C:\\fake_dev1448.vrm",
        )
        return dbd.show_drop_bones_dialog(hidden_root, ctx)

    elapsed = _best_of_two_close_seconds(build)
    _assert_within_threshold("drop_bones_dialog", elapsed)


# ---------------------------------------------------------------------------
# 4. equipment_select_dialog(装備限定) -- 400コード
# ---------------------------------------------------------------------------


def test_equipment_select_dialog_close_time_dev1448(hidden_root, tmp_path, monkeypatch):
    codes = [f"Code{i:04d}" for i in range(_CATALOG_ROW_COUNT)]
    monkeypatch.setattr(
        esd, "query_equipment_catalog",
        lambda *_a, **_k: {"ok": True, "source": "test", "detail": "",
                            "codes": codes, "names": {}},
    )

    def build() -> tk.Toplevel:
        ctx = esd.EquipmentSelectContext(
            app_root=str(tmp_path), palworld_pak="C:\\fake_dev1448.pak", lang="ja",
        )
        return esd.show_equipment_select_dialog(hidden_root, ctx)

    elapsed = _best_of_two_close_seconds(build)
    _assert_within_threshold("equipment_select_dialog", elapsed)


# ---------------------------------------------------------------------------
# 5. headequip_select_dialog(頭装備切り替え) -- 400コード
# ---------------------------------------------------------------------------


def test_headequip_select_dialog_close_time_dev1448(hidden_root, tmp_path, monkeypatch):
    codes = [f"Head{i:04d}" for i in range(_CATALOG_ROW_COUNT)]
    monkeypatch.setattr(
        hed, "query_headequip_catalog",
        lambda *_a, **_k: {"ok": True, "source": "test", "detail": "",
                            "codes": codes, "names": {}},
    )

    def build() -> tk.Toplevel:
        ctx = hed.HeadEquipSelectContext(
            app_root=str(tmp_path), palworld_pak="C:\\fake_dev1448.pak", lang="ja",
        )
        return hed.show_headequip_select_dialog(hidden_root, ctx)

    elapsed = _best_of_two_close_seconds(build)
    _assert_within_threshold("headequip_select_dialog", elapsed)


# ---------------------------------------------------------------------------
# 6. shapekey_select_dialog(シェイプキー) -- 1メッシュに400キー
#    (メッシュ一覧の先頭=自動選択されるメッシュへまとめて乗せ、初期描画の
#    代表コストにする。アルファベット順で先頭に来るよう命名する)
# ---------------------------------------------------------------------------


def test_shapekey_select_dialog_close_time_dev1448(hidden_root, tmp_path, monkeypatch):
    big_keys = [f"key_{i:04d}" for i in range(_CATALOG_ROW_COUNT)]
    fake_meshes = {"AAA_Face": big_keys, "Body": ["Fat", "Thin"], "Zzz_Extra": ["X"]}
    monkeypatch.setattr(
        skd, "resolve_catalog",
        lambda *_a, **_k: {"ok": True, "detail": "dev#1448 representative scale",
                            "meshes": fake_meshes},
    )

    def build() -> tk.Toplevel:
        ctx = skd.ShapeKeySelectContext(
            app_root=str(tmp_path), work_root=str(tmp_path),
            avatar_path="C:\\fake_dev1448.vrm",
        )
        return skd.show_shapekey_select_dialog(hidden_root, ctx)

    elapsed = _best_of_two_close_seconds(build)
    _assert_within_threshold("shapekey_select_dialog", elapsed)


# ---------------------------------------------------------------------------
# 7. multi_avatar_pak_dialog(マルチアバターPAK作成) -- 装備400コード
# ---------------------------------------------------------------------------


def _fake_extract_atlas(pak_path, out_png_path):
    os.makedirs(os.path.dirname(out_png_path), exist_ok=True)
    with open(out_png_path, "wb") as f:
        f.write(b"FAKE_ATLAS")
    return out_png_path


def _make_library_entry(work_root: str, entry_id: str = "Dev1448Avatar") -> str:
    """test_multi_avatar_pak_dialog_ui_dev1170.py._make_saved_entry()と同型
    (最小限のライブラリ保存物を1件作るだけの下ごしらえ、複製ではなく
    新規テストファイル内での自己完結のため書き直したもの)。"""
    job_dir = os.path.join(work_root, entry_id)
    build_dir = os.path.join(job_dir, "build")
    outfit_dir = os.path.join(build_dir, "noue_work", "variant", "Player", "Outfit")
    base = "SK_Player_Female_Outfit_Cloth001"
    d = os.path.join(outfit_dir, base)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, base + ".uasset"), "wb") as f:
        f.write(b"UA")
    with open(os.path.join(d, base + ".uexp"), "wb") as f:
        f.write(b"UE")
    os.makedirs(build_dir, exist_ok=True)
    out_pak = os.path.join(build_dir, f"{entry_id}_PlayerSwap_P.pak")
    with open(out_pak, "wb") as f:
        f.write(b"PAK")
    job = {"vrm_path": "", "avatar_name": entry_id, "genders": ["Female", "Male"]}
    with mock.patch.object(vea, "extract_avatar_atlas_png", side_effect=_fake_extract_atlas):
        val.save_library(job, job_dir, out_pak, os.path.join(build_dir, "noue_work"))
    return job_dir


def test_multi_avatar_pak_dialog_close_time_dev1448(hidden_root, tmp_path, monkeypatch):
    codes = [f"Code{i:04d}" for i in range(_CATALOG_ROW_COUNT)]
    monkeypatch.setattr(
        mapd.equipment_select_dialog, "query_equipment_catalog",
        lambda *_a, **_k: {"ok": True, "source": "test", "detail": "",
                            "codes": codes, "names": {}},
    )

    app_root = str(tmp_path / "app_root")
    work_root = str(tmp_path / "work_root")
    os.makedirs(app_root, exist_ok=True)
    os.makedirs(work_root, exist_ok=True)
    _make_library_entry(work_root, "Dev1448Avatar")
    # assignmentsを非空にして「設定開始」画面ではなく本編(左=装備codesぶんの
    # ボタン一覧、右=ライブラリ一覧)を初期描画させる(_render_main参照)。
    maps_store.save_assignments(app_root, {codes[0]: "Dev1448Avatar"})

    def build() -> tk.Toplevel:
        ctx = mapd.MultiAvatarPakContext(
            app_root=app_root, work_root=work_root,
            palworld_pak="C:\\fake_dev1448.pak", lang="ja",
        )
        return mapd.show_multi_avatar_pak_dialog(hidden_root, ctx)

    elapsed = _best_of_two_close_seconds(build)
    _assert_within_threshold("multi_avatar_pak_dialog", elapsed)


# ---------------------------------------------------------------------------
# 8. support_dialog(問合せ) -- 固定レイアウト
# ---------------------------------------------------------------------------


def test_support_dialog_close_time_dev1448(hidden_root):
    def build() -> tk.Toplevel:
        ctx = spd.SupportContext(
            tool_version="dev1448-test", lang="ja", channel="dev",
            get_os_description=lambda: "Windows 11",
            get_avatar_name=lambda: "SampleAvatar",
            get_status_text=lambda: "idle",
            build_diagnostics_text=lambda: "diag text (dev#1448)",
        )
        return spd.show_support_dialog(hidden_root, spd.SupportDialogState(), ctx)

    elapsed = _best_of_two_close_seconds(build)
    _assert_within_threshold("support_dialog", elapsed)


# ---------------------------------------------------------------------------
# 9. preflight_warning_dialog -- 固定レイアウト
# ---------------------------------------------------------------------------


def test_preflight_warning_dialog_close_time_dev1448(hidden_root):
    def build() -> tk.Toplevel:
        ctx = pwd.PreflightWarningContext(
            on_remove_mod=lambda: None, on_open_inquiry=lambda: None,
        )
        return pwd.show_preflight_warning_dialog(hidden_root, ctx)

    elapsed = _best_of_two_close_seconds(build)
    _assert_within_threshold("preflight_warning_dialog", elapsed)


# ---------------------------------------------------------------------------
# 10. gender_select_dialog(性別限定) -- 固定レイアウト
# ---------------------------------------------------------------------------


def test_gender_select_dialog_close_time_dev1448(hidden_root, tmp_path):
    def build() -> tk.Toplevel:
        ctx = gsd.GenderSelectContext(app_root=str(tmp_path))
        return gsd.show_gender_select_dialog(hidden_root, ctx)

    elapsed = _best_of_two_close_seconds(build)
    _assert_within_threshold("gender_select_dialog", elapsed)


# ---------------------------------------------------------------------------
# 11. dt_flag_head_hide_dialog(差替え中装備のみ頭OFF) -- 固定レイアウト
# ---------------------------------------------------------------------------


def test_dt_flag_head_hide_dialog_close_time_dev1448(hidden_root, tmp_path):
    def build() -> tk.Toplevel:
        ctx = dfh.DtFlagHeadHideContext(app_root=str(tmp_path))
        return dfh.show_dt_flag_head_hide_dialog(hidden_root, ctx)

    elapsed = _best_of_two_close_seconds(build)
    _assert_within_threshold("dt_flag_head_hide_dialog", elapsed)


# ---------------------------------------------------------------------------
# 12. lab_window(ラボ窓本体、open_lab_window) -- 固定8行
# ---------------------------------------------------------------------------


class _FakeLabSelf:
    """lab_window.open_lab_window()が要求する最小のself。
    test_lab_window_ui.py._FakeSelfと同型(main_window.pyの実メソッドは
    あえて持たせず、getattrガードで安全に呼ばれないことも兼ねて確認する)。"""

    def __init__(self, root: tk.Misc, app_root: str, work_root: str) -> None:
        self.widgets = {"dropBonesBox": tk.Entry(root)}
        self.app_root = app_root
        self.work_root = work_root


def test_lab_window_close_time_dev1448(hidden_root, tmp_path):
    def build() -> tk.Toplevel:
        fake_self = _FakeLabSelf(hidden_root, str(tmp_path), str(tmp_path))
        return lab_window.open_lab_window(fake_self, hidden_root)

    elapsed = _best_of_two_close_seconds(build)
    _assert_within_threshold("lab_window", elapsed)


# ---------------------------------------------------------------------------
# 負の対照: 閉経路に人為的な2秒超の遅延を注入したケースを、本ファイルの
# 計測ロジックが実際に検出できることの確認(CLAUDE.md「負の対照を取る」)。
# 実際にこのテスト自体をFAILさせるのではなく、「計測値が閾値を超えることを
# 正しく表明できる」構造そのものを検証する(全ダイアログ試験がFAILすべき
# ときに実際にFAILする、という前提の裏取り)。
# ---------------------------------------------------------------------------


def test_negative_control_close_time_detects_artificial_delay_dev1448(
    hidden_root, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        mdd, "query_mesh_catalog",
        lambda *_a, **_k: {"ok": True, "source": "test", "detail": "",
                            "names": [f"mesh_{i}" for i in range(20)]},
    )
    ctx = mdd.MeshDeleteContext(
        app_root=str(tmp_path), work_root=str(tmp_path), avatar_path="C:\\fake_dev1448.vrm",
    )
    dlg = mdd.show_mesh_delete_dialog(hidden_root, ctx)

    # ソース(ui\mesh_delete_dialog.py)自体は変更しない。テスト側だけで
    # WM_DELETE_WINDOWハンドラを人為的に遅いものへ差し替える
    # (dlg.protocol()の再登録はtkinter標準のAPIで、モジュール側コードには
    # 一切触れない)。
    real_destroy = dlg.destroy
    injected_delay = _CLOSE_THRESHOLD_SECONDS + 0.3

    def _artificially_slow_close() -> None:
        time.sleep(injected_delay)
        real_destroy()

    dlg.protocol("WM_DELETE_WINDOW", _artificially_slow_close)

    elapsed = _invoke_close_and_measure(dlg)
    assert elapsed >= _CLOSE_THRESHOLD_SECONDS, (
        f"人為的に注入した{injected_delay:.1f}s遅延が elapsed={elapsed:.3f}s として"
        "検出されなかった(計測ロジックが機能していない=検出力の証明に失敗)"
    )
