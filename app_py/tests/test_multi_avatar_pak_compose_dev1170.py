# test_multi_avatar_pak_compose_dev1170.py -- dev#1170 WP-3(マルチアバターPAK
# 作成)の合成ジョブJSON組み立て+WP-5(本WP)の合成エンジン実接続の単体試験。
#
# WP-5(2026-08-09)で run_compose() のスタブ実装(常にComposeNotReadyError)を
# 実接続(pipeline\py\vp_avatar_compose.compose()を直接import・呼び出し)へ
# 差し替えた。下の「run_compose」節はスタブ時代の試験
# (test_run_compose_raises_compose_not_ready_error等)を実接続の挙動に
# 合わせて更新したもの——実合成(実Palworld pak・実SK注入)はWP-2のON
# スモークで既に実証済み(CLAUDE.md「受入試験はリリースゲートに任せる」)のため、
# ここでは「vp_avatar_compose.compose()が正しい引数で呼ばれるか」
# 「その戻り値/例外がそのまま呼び出し元へ伝わるか」というユニットレベルの
# 配線だけを検証する(sys.modulesへフェイクモジュールを差し込み、実pipeline
# コードは一切実行しない)。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pytest  # noqa: E402

import multi_avatar_pak_compose as compose  # noqa: E402
import multi_avatar_pak_store as store  # noqa: E402


# ---------------------------------------------------------------------------
# build_compose_job (合成ジョブJSON組み立て、指示書の入力仕様どおり)
# ---------------------------------------------------------------------------


def test_build_compose_job_shape():
    job = compose.build_compose_job("MyMod", {"Bronze001": "Alicia", "Cloth002": "Bob"})
    assert job["output_name"] == "MyMod"
    assert job["assignments"] == {"Bronze001": "Alicia", "Cloth002": "Bob"}
    assert job["format_version"] == compose.COMPOSE_JOB_FORMAT_VERSION


def test_build_compose_job_strips_empty_keys_and_values():
    job = compose.build_compose_job("MyMod", {"": "Alicia", "Cloth002": "", "Ok": "Bob"})
    assert job["assignments"] == {"Ok": "Bob"}


def test_build_compose_job_tolerates_none_assignments():
    job = compose.build_compose_job("MyMod", None)
    assert job["assignments"] == {}


def test_build_compose_job_tolerates_empty_output_name():
    job = compose.build_compose_job("", {"A": "B"})
    assert job["output_name"] == ""
    assert job["assignments"] == {"A": "B"}


def test_build_compose_job_does_not_mutate_input_dict():
    original = {"A": "B"}
    compose.build_compose_job("Name", original)
    assert original == {"A": "B"}


# ---------------------------------------------------------------------------
# run_compose (WP-5実接続: pipeline\py\vp_avatar_compose.compose()への配線)
#
# 実pipelineコードを動かさないため、sys.modules["vp_avatar_compose"]へ
# フェイクを差し込む(monkeypatch.setitemでテスト後は自動復元される)。
# ---------------------------------------------------------------------------


class _FakeVpAvatarCompose:
    """pipeline\\py\\vp_avatar_compose モジュールの最小フェイク。compose()の
    呼び出し引数を記録し、事前に設定した戻り値/例外を返す/送出する。"""

    def __init__(self):
        self.calls = []
        self.result = {"pak_path": "dummy.pak", "job_dir": "dummy_dir"}
        self.raises = None

    def compose(self, work_root, job, log=print):
        self.calls.append({"work_root": work_root, "job": job, "log": log})
        if self.raises is not None:
            raise self.raises
        return self.result


@pytest.fixture()
def fake_engine(monkeypatch):
    fake = _FakeVpAvatarCompose()
    monkeypatch.setitem(sys.modules, "vp_avatar_compose", fake)
    return fake


def test_run_compose_forwards_work_root_job_and_log_to_engine(tmp_path, fake_engine):
    job = compose.build_compose_job("MyMod", {"A": "B"})
    logs = []

    result = compose.run_compose(str(tmp_path), job, log=logs.append)

    assert result == fake_engine.result
    assert len(fake_engine.calls) == 1
    call = fake_engine.calls[0]
    assert call["work_root"] == str(tmp_path)
    assert call["job"] == job
    assert call["log"] == logs.append  # bound-method同士は`is`ではなく`==`で比較する


def test_run_compose_default_log_is_forwarded_as_print(tmp_path, fake_engine):
    job = compose.build_compose_job("MyMod", {"A": "B"})

    compose.run_compose(str(tmp_path), job)

    assert fake_engine.calls[0]["log"] is print


def test_run_compose_python_exe_argument_is_accepted_but_unused_by_direct_import(
    tmp_path, fake_engine
):
    # dev#1170 WP-5: pak_manager.pyの直接importパターンを踏襲したため
    # subprocess起動が不要になった。python_exeは呼び出し元シグネチャ互換の
    # ためだけに残るので、存在しないパスを渡しても何も起動されず正常に完了する
    # こと(=フェイクエンジンが1回だけ呼ばれること)を確認する。
    job = compose.build_compose_job("MyMod", {"A": "B"})

    compose.run_compose(
        str(tmp_path), job, python_exe=r"C:\this\path\does\not\exist\python.exe")

    assert len(fake_engine.calls) == 1


def test_run_compose_propagates_engine_errors_unwrapped(tmp_path, fake_engine):
    # 想定内の入力エラー(vp_avatar_compose.ComposeError等)はそのまま
    # 呼び出し元(ui\multi_avatar_pak_dialog.py)へ伝播する契約
    # (呼び出し元の汎用except節がLabMultiAvatarPakCreateFailureBodyへ
    # 整形して表示する、モジュールdocstring参照)。
    fake_engine.raises = RuntimeError(
        "some equipment slots are not assigned; please assign every "
        "equipment slot and try composing again: ['Cloth002']")
    job = compose.build_compose_job("MyMod", {"A": "B"})

    with pytest.raises(RuntimeError, match="Cloth002"):
        compose.run_compose(str(tmp_path), job)


def test_run_compose_raises_compose_not_ready_error_when_engine_cannot_be_imported(
    tmp_path, monkeypatch
):
    # sys.modules[name] = None は「importステートメントに強制的にImportErrorを
    # 投げさせる」標準的な手筋(CPython importシステムの仕様どおり)。
    # pipeline\py\vp_avatar_compose.pyが実在しない/壊れているという想定外
    # 事態を再現する。
    monkeypatch.setitem(sys.modules, "vp_avatar_compose", None)
    job = compose.build_compose_job("MyMod", {"A": "B"})
    logs = []

    with pytest.raises(compose.ComposeNotReadyError):
        compose.run_compose(str(tmp_path), job, log=logs.append)

    assert any("could not be loaded" in line for line in logs)


def test_run_compose_error_is_a_runtime_error_subclass():
    assert issubclass(compose.ComposeNotReadyError, RuntimeError)


# ---------------------------------------------------------------------------
# 一気通貫試験: UI層(store→合成ジョブJSON)→run_compose()→
# vp_avatar_composeの入口までがユニットレベルで繋がること
# ---------------------------------------------------------------------------


def test_end_to_end_store_to_build_compose_job_to_run_compose_to_engine_entry(
    tmp_path, fake_engine
):
    """multi_avatar_pak_store(UI層の永続化)に保存した対応表が、
    build_compose_job()を経て run_compose()経由でvp_avatar_compose.compose()の
    入口まで、値を変えずに届くこと。実変換・実合成(pipeline\\配下の実処理)は
    一切実行しない(fake_engineがsys.modules差し込みで実importを遮る)。"""
    app_root = str(tmp_path / "app_root")
    work_root = str(tmp_path / "work_root")
    os.makedirs(app_root, exist_ok=True)
    os.makedirs(work_root, exist_ok=True)

    # UI層相当の操作: ペンキ割当を2回行う(multi_avatar_pak_dialog.py の
    # on_click_equipment() が呼ぶ store.assign_many() と同じ呼び出し形)。
    store.assign_many(app_root, "AliciaEntry", ["Bronze001"])
    store.assign_many(app_root, "BobEntry", ["Cloth002"])

    # 「作成」ボタン押下相当: 保存済み対応表を読み出してjobを組み立てる
    # (multi_avatar_pak_dialog.py._on_create()と同じ呼び出し形)。
    current_assignments = store.load_assignments(app_root)
    job = compose.build_compose_job("MyOutfitSet", current_assignments)

    logs = []
    result = compose.run_compose(work_root, job, log=logs.append)

    assert result == fake_engine.result
    assert len(fake_engine.calls) == 1
    call = fake_engine.calls[0]
    assert call["work_root"] == work_root
    assert call["job"]["output_name"] == "MyOutfitSet"
    assert call["job"]["assignments"] == {
        "Bronze001": "AliciaEntry", "Cloth002": "BobEntry",
    }
    # store層の永続状態が壊れていないこと(念のための負の対照:
    # run_compose呼び出しがstore側のファイルへ副作用を持たないこと)
    assert store.load_assignments(app_root) == {
        "Bronze001": "AliciaEntry", "Cloth002": "BobEntry",
    }
