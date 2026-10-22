# -*- coding: utf-8 -*-
r"""dev#702 WP-1受入試験: app_py\lu_export.py の単体テスト
(第3弾WP-2/WP-3でdevtools\から移設、importパスのみ追随更新)。

正本: C:\P\Work\DiveToPalworld\work\rd_702\PROPOSAL.md 「WP-1」節の受入条件1-4。
実Unity・実pwshは一切呼ばない——export_from_unity.ps1呼び出し部分(subprocess.run)
をfakeのrun_fnへ差し替えてシミュレートする(tests\shipcheck\test_av_scan_gate.py
等の既存のrun_fn差し替え流儀を踏襲、PROPOSAL WP-1受入条件4)。

CLAUDE.md「受入試験はリリースゲートに任せる」原則により、実変換・実Unity輸出を
伴う試験は課さない(本WPはlu_export.py単体のロジック試験のみ)。
devtools\lu_export.py(移設後の後方互換shim)自体の疎通は
devtools\tests\test_lu_export_shim.py が別途担当する。

実行: python -m pytest app_py\tests\test_lu_export.py -v
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import pytest

HERE_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_PY_DIR = os.path.dirname(HERE_DIR)
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import lu_export as lue  # noqa: E402
import pipeline_runner as pr  # noqa: E402


class FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _make_fake_export_run_fn(
    calls,
    write_fbx=True,
    write_humanoid=True,
    write_material_map=True,
    write_physbones=False,
    fail=False,
    fail_stderr="boom",
):
    """export_from_unity.ps1呼び出しをシミュレートするfake run_fn。実Unity・
    実pwshには一切触れない。cmdの"-Out"引数の値を使って出力ファイルを書き出す
    (実際のexport_from_unity.ps1/unity\\DiveToPalworldExporter.csの出力契約:
    outDir直下に<name>.fbx・humanoid.json・material_map.jsonを書く、を模す)。
    write_physbones(dev#1356): unity\\DiveToPalworldExporter.cs
    ExtractPhysBoneChains()が書くphysbones.jsonの有無をシミュレートする
    (既定False=旧バージョンのUnityエクスポータ/本WPより前のキャッシュを模す)。"""

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if fail:
            return FakeCompletedProcess(returncode=1, stderr=fail_stderr)
        out_dir = cmd[cmd.index("-Out") + 1]
        os.makedirs(out_dir, exist_ok=True)
        if write_fbx:
            with open(os.path.join(out_dir, "avatar.fbx"), "wb") as f:
                f.write(b"fake-fbx-bytes")
        if write_humanoid:
            with open(os.path.join(out_dir, "humanoid.json"), "w", encoding="utf-8") as f:
                f.write("{}")
        if write_material_map:
            with open(os.path.join(out_dir, "material_map.json"), "w", encoding="utf-8") as f:
                f.write("{}")
        if write_physbones:
            with open(os.path.join(out_dir, "physbones.json"), "w", encoding="utf-8") as f:
                f.write('{"format": "divetopalworld-physbones-1", "physbones": []}')
        return FakeCompletedProcess(returncode=0)

    return fake_run


def _write_prefab(path, content=b"prefab-v1"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


# =====================================================================
# hash_file_sha256
# =====================================================================

def test_hash_file_sha256_matches_hashlib(tmp_path):
    p = tmp_path / "sample.bin"
    p.write_bytes(b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert lue.hash_file_sha256(str(p)) == expected


def test_hash_file_sha256_differs_when_content_differs(tmp_path):
    """負の対照: 中身が変われば別のハッシュになる。"""
    p1 = tmp_path / "a.bin"
    p2 = tmp_path / "b.bin"
    p1.write_bytes(b"content-A")
    p2.write_bytes(b"content-B")
    assert lue.hash_file_sha256(str(p1)) != lue.hash_file_sha256(str(p2))


# =====================================================================
# resolve_unity_export_out_dir / find_exported_fbx: 既存実装の再利用確認
# =====================================================================

def test_resolve_unity_export_out_dir_delegates_to_pipeline_runner():
    """PROPOSAL WP-1仕様: app_py/pipeline_runner.py:270と同じ式を再利用する
    (式を複製しない)。既存関数への単純委譲であることを確認する。"""
    work_root = r"C:\work\jobx"
    prefab_path = r"C:\UnityP\apron\Assets\flatapron.prefab"
    assert lue.resolve_unity_export_out_dir(work_root, prefab_path) == (
        pr.resolve_unity_export_out_dir(work_root, prefab_path)
    )


def test_find_exported_fbx_returns_none_when_dir_missing(tmp_path):
    assert lue.find_exported_fbx(str(tmp_path / "missing")) is None


def test_find_exported_fbx_returns_first_fbx(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "avatar.fbx").write_bytes(b"x")
    assert lue.find_exported_fbx(str(out_dir)) == str(out_dir / "avatar.fbx")


# =====================================================================
# prefab_export_sig_path / save_export_sig / is_export_cache_fresh
# =====================================================================

def test_prefab_export_sig_path_is_fixed_filename(tmp_path):
    assert lue.prefab_export_sig_path(str(tmp_path)) == os.path.join(
        str(tmp_path), "source_prefab.sha256"
    )


def test_save_export_sig_writes_current_hash_atomically(tmp_path):
    out_dir = tmp_path / "out"
    prefab = tmp_path / "avatar.prefab"
    prefab.write_bytes(b"prefab-content")
    lue.save_export_sig(str(out_dir), str(prefab))
    sig_path = lue.prefab_export_sig_path(str(out_dir))
    assert os.path.isfile(sig_path)
    with open(sig_path, encoding="utf-8") as f:
        saved = f.read().strip()
    assert saved == lue.hash_file_sha256(str(prefab))
    # tmpファイルが残っていない(アトミック書き込みの後始末確認)
    assert not os.path.isfile(sig_path + ".tmp")


def test_is_export_cache_fresh_false_when_out_dir_missing(tmp_path):
    prefab = tmp_path / "avatar.prefab"
    prefab.write_bytes(b"v1")
    assert lue.is_export_cache_fresh(str(tmp_path / "missing"), str(prefab)) is False


def test_is_export_cache_fresh_false_when_fbx_missing(tmp_path):
    """負の対照: sigはあるがfbx実体が無い→鮮度NG。"""
    out_dir = tmp_path / "out"
    prefab = tmp_path / "avatar.prefab"
    prefab.write_bytes(b"v1")
    lue.save_export_sig(str(out_dir), str(prefab))
    assert lue.is_export_cache_fresh(str(out_dir), str(prefab)) is False


def test_is_export_cache_fresh_false_when_sig_missing(tmp_path):
    """負の対照: fbxはあるがsigが無い→鮮度NG。"""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "avatar.fbx").write_bytes(b"x")
    prefab = tmp_path / "avatar.prefab"
    prefab.write_bytes(b"v1")
    assert lue.is_export_cache_fresh(str(out_dir), str(prefab)) is False


def test_is_export_cache_fresh_true_when_sig_matches(tmp_path):
    out_dir = tmp_path / "out"
    prefab = tmp_path / "avatar.prefab"
    prefab.write_bytes(b"v1")
    out_dir.mkdir()
    (out_dir / "avatar.fbx").write_bytes(b"x")
    lue.save_export_sig(str(out_dir), str(prefab))
    lue.save_exporter_schema_sig(str(out_dir))  # dev#1551 laneG5修理: 新条件も満たす
    assert lue.is_export_cache_fresh(str(out_dir), str(prefab)) is True


def test_is_export_cache_fresh_false_when_prefab_content_changed(tmp_path):
    """負の対照(受入条件2の核心): prefab内容が変わればsig不一致で鮮度NG。"""
    out_dir = tmp_path / "out"
    prefab = tmp_path / "avatar.prefab"
    prefab.write_bytes(b"v1")
    out_dir.mkdir()
    (out_dir / "avatar.fbx").write_bytes(b"x")
    lue.save_export_sig(str(out_dir), str(prefab))
    lue.save_exporter_schema_sig(str(out_dir))  # dev#1551 laneG5修理: 新条件も満たす
    assert lue.is_export_cache_fresh(str(out_dir), str(prefab)) is True
    prefab.write_bytes(b"v2-changed")
    assert lue.is_export_cache_fresh(str(out_dir), str(prefab)) is False


# ---------------------------------------------------------------------------
# dev#1104残課題: material_map.jsonが参照する非nullテクスチャの実在確認
# (C:\P\Work\DiveToPalworld\work\lane_1104_texaudit\PROGRESS_dev1104_texaudit.md参照)
# ---------------------------------------------------------------------------

_MATERIAL_MAP_WITH_TEXTURES = (
    '{"format": "divetopalworld-materials-1", "meshes": {'
    '"Body": [{"material_name": "body", "texture": "tex_00.png", "color": [1,1,1,1]}]'
    '}}'
)


def test_is_export_cache_fresh_true_when_material_map_textures_all_present(tmp_path):
    """正の対照: material_map.jsonが参照するテクスチャが実在すれば従来どおりTrue。"""
    out_dir = tmp_path / "out"
    prefab = tmp_path / "avatar.prefab"
    prefab.write_bytes(b"v1")
    out_dir.mkdir()
    (out_dir / "avatar.fbx").write_bytes(b"x")
    (out_dir / "material_map.json").write_text(_MATERIAL_MAP_WITH_TEXTURES, encoding="utf-8")
    (out_dir / "tex_00.png").write_bytes(b"fake-png-bytes")
    lue.save_export_sig(str(out_dir), str(prefab))
    lue.save_exporter_schema_sig(str(out_dir))  # dev#1551 laneG5修理: 新条件も満たす
    assert lue.is_export_cache_fresh(str(out_dir), str(prefab)) is True


def test_is_export_cache_fresh_false_when_material_map_texture_file_missing(tmp_path):
    """負の対照(dev#1104残課題の核心): material_map.jsonがtexture=tex_00.pngを
    参照しているのに、そのファイルがout_dir内に存在しない場合は鮮度NG
    (=キャッシュを信用せず再輸出させる。「texture欄は非nullなのに実PNGが無い」
    ディレクトリをそのまま次の変換で使い回さない)。"""
    out_dir = tmp_path / "out"
    prefab = tmp_path / "avatar.prefab"
    prefab.write_bytes(b"v1")
    out_dir.mkdir()
    (out_dir / "avatar.fbx").write_bytes(b"x")
    (out_dir / "material_map.json").write_text(_MATERIAL_MAP_WITH_TEXTURES, encoding="utf-8")
    # tex_00.png を意図的に書かない(dev#1104報告と同型の壊れた状態を再現)
    lue.save_export_sig(str(out_dir), str(prefab))
    assert lue.is_export_cache_fresh(str(out_dir), str(prefab)) is False


def test_is_export_cache_fresh_true_when_material_map_absent(tmp_path):
    """material_map.json自体が無い場合は対象外(既存のFBX+sigのみの判定のまま、
    後方互換を壊さない)。"""
    out_dir = tmp_path / "out"
    prefab = tmp_path / "avatar.prefab"
    prefab.write_bytes(b"v1")
    out_dir.mkdir()
    (out_dir / "avatar.fbx").write_bytes(b"x")
    lue.save_export_sig(str(out_dir), str(prefab))
    lue.save_exporter_schema_sig(str(out_dir))  # dev#1551 laneG5修理: 新条件も満たす
    assert lue.is_export_cache_fresh(str(out_dir), str(prefab)) is True


def test_is_export_cache_fresh_false_when_material_map_json_corrupt(tmp_path):
    """安全側: material_map.jsonが壊れたJSONなら鮮度NG(再輸出させる)。"""
    out_dir = tmp_path / "out"
    prefab = tmp_path / "avatar.prefab"
    prefab.write_bytes(b"v1")
    out_dir.mkdir()
    (out_dir / "avatar.fbx").write_bytes(b"x")
    (out_dir / "material_map.json").write_text("{not valid json", encoding="utf-8")
    lue.save_export_sig(str(out_dir), str(prefab))
    assert lue.is_export_cache_fresh(str(out_dir), str(prefab)) is False


def test_is_export_cache_fresh_true_when_material_map_texture_is_null(tmp_path):
    """texture欄がnull(単色マテリアル)の場合はファイル実在チェックの対象外。"""
    out_dir = tmp_path / "out"
    prefab = tmp_path / "avatar.prefab"
    prefab.write_bytes(b"v1")
    out_dir.mkdir()
    (out_dir / "avatar.fbx").write_bytes(b"x")
    mm = '{"meshes": {"Body": [{"material_name": "body", "texture": null, "color": [1,1,1,1]}]}}'
    (out_dir / "material_map.json").write_text(mm, encoding="utf-8")
    lue.save_export_sig(str(out_dir), str(prefab))
    lue.save_exporter_schema_sig(str(out_dir))
    assert lue.is_export_cache_fresh(str(out_dir), str(prefab)) is True


# =====================================================================
# dev#1551 laneG5修理(work\run_1551\gui_verify\RESULT.md 0章の確定根因への
# 対処): エクスポータ自身のソースが変わった/署名が無い旧キャッシュは
# 鮮度NGにする。prefab自体は変わらなくても、エクスポータのスキーマ進化を
# 追跡できることを検証する。
# =====================================================================

def _make_fake_exporter_sources(tmp_path, content=b"exporter-v1"):
    """_EXPORTER_SOURCE_FILESの代わりに使うfakeソースファイル2本を作る。"""
    cs = tmp_path / "FakeExporter.cs"
    ps1 = tmp_path / "fake_export.ps1"
    cs.write_bytes(content)
    ps1.write_bytes(content)
    return (str(cs), str(ps1))


def test_exporter_schema_fingerprint_changes_when_source_changes(tmp_path, monkeypatch):
    """正の対照: エクスポータのソース内容が変われば指紋も変わる。"""
    paths = _make_fake_exporter_sources(tmp_path, b"exporter-v1")
    monkeypatch.setattr(lue, "_EXPORTER_SOURCE_FILES", paths)
    fp1 = lue.exporter_schema_fingerprint()
    with open(paths[0], "wb") as f:
        f.write(b"exporter-v2-changed")
    fp2 = lue.exporter_schema_fingerprint()
    assert fp1 != fp2


def test_exporter_schema_fingerprint_stable_when_source_unchanged(tmp_path, monkeypatch):
    """負の対照: ソースが変わらなければ指紋も変わらない(誤検知しない)。"""
    paths = _make_fake_exporter_sources(tmp_path, b"exporter-stable")
    monkeypatch.setattr(lue, "_EXPORTER_SOURCE_FILES", paths)
    assert lue.exporter_schema_fingerprint() == lue.exporter_schema_fingerprint()


def test_exporter_schema_fingerprint_unknown_when_source_missing(tmp_path, monkeypatch):
    """安全側: ソースファイルが見つからない場合は"unknown"(鮮度判定側は常に
    不一致=再輸出させる安全側に倒れる)。"""
    monkeypatch.setattr(
        lue, "_EXPORTER_SOURCE_FILES",
        (str(tmp_path / "missing1.cs"), str(tmp_path / "missing2.ps1")),
    )
    assert lue.exporter_schema_fingerprint() == "unknown"


def test_exporter_schema_sig_path_is_fixed_filename(tmp_path):
    assert lue.exporter_schema_sig_path(str(tmp_path)) == os.path.join(
        str(tmp_path), "export_schema.sha256"
    )


def test_save_exporter_schema_sig_writes_current_fingerprint_atomically(tmp_path, monkeypatch):
    paths = _make_fake_exporter_sources(tmp_path, b"exporter-v1")
    monkeypatch.setattr(lue, "_EXPORTER_SOURCE_FILES", paths)
    out_dir = tmp_path / "out"
    lue.save_exporter_schema_sig(str(out_dir))
    sig_path = lue.exporter_schema_sig_path(str(out_dir))
    assert os.path.isfile(sig_path)
    with open(sig_path, encoding="utf-8") as f:
        saved = f.read().strip()
    assert saved == lue.exporter_schema_fingerprint()
    assert not os.path.isfile(sig_path + ".tmp")


def test_is_export_cache_fresh_false_when_exporter_schema_sig_missing(tmp_path, monkeypatch):
    """負の対照(本修理の核心、work\\flatHaori_export\\の実例そのもの): fbx・
    prefab sigはともに新鮮(一致)だが、export_schema.sha256自体が無い
    (=本修理より前に書かれた既存キャッシュ)場合は鮮度NG——エクスポータの
    スキーマが変わったかどうか判定できない以上、安全側で再輸出させる。"""
    paths = _make_fake_exporter_sources(tmp_path, b"exporter-v1")
    monkeypatch.setattr(lue, "_EXPORTER_SOURCE_FILES", paths)
    out_dir = tmp_path / "out"
    prefab = tmp_path / "avatar.prefab"
    prefab.write_bytes(b"v1")
    out_dir.mkdir()
    (out_dir / "avatar.fbx").write_bytes(b"x")
    lue.save_export_sig(str(out_dir), str(prefab))
    # export_schema.sha256 を意図的に書かない(旧キャッシュを模す)。
    assert lue.is_export_cache_fresh(str(out_dir), str(prefab)) is False


def test_is_export_cache_fresh_false_when_exporter_schema_changed(tmp_path, monkeypatch):
    """負の対照: エクスポータのソースが輸出後に変わった(=キャッシュ作成時と
    現在で指紋が違う)場合も鮮度NG。"""
    paths = _make_fake_exporter_sources(tmp_path, b"exporter-v1")
    monkeypatch.setattr(lue, "_EXPORTER_SOURCE_FILES", paths)
    out_dir = tmp_path / "out"
    prefab = tmp_path / "avatar.prefab"
    prefab.write_bytes(b"v1")
    out_dir.mkdir()
    (out_dir / "avatar.fbx").write_bytes(b"x")
    lue.save_export_sig(str(out_dir), str(prefab))
    lue.save_exporter_schema_sig(str(out_dir))
    assert lue.is_export_cache_fresh(str(out_dir), str(prefab)) is True
    # エクスポータのソースをdev#1508相当の改修とみなして書き換える。
    with open(paths[0], "wb") as f:
        f.write(b"exporter-v2-added-params-field")
    assert lue.is_export_cache_fresh(str(out_dir), str(prefab)) is False


def test_is_export_cache_fresh_true_when_exporter_schema_matches(tmp_path, monkeypatch):
    """正の対照: 全条件(fbx・prefab sig・schema sig)が揃って一致すれば従来
    どおりTrue(本修理が既存の正常系を壊していないことの確認)。"""
    paths = _make_fake_exporter_sources(tmp_path, b"exporter-v1")
    monkeypatch.setattr(lue, "_EXPORTER_SOURCE_FILES", paths)
    out_dir = tmp_path / "out"
    prefab = tmp_path / "avatar.prefab"
    prefab.write_bytes(b"v1")
    out_dir.mkdir()
    (out_dir / "avatar.fbx").write_bytes(b"x")
    lue.save_export_sig(str(out_dir), str(prefab))
    lue.save_exporter_schema_sig(str(out_dir))
    assert lue.is_export_cache_fresh(str(out_dir), str(prefab)) is True


def test_resolve_prefab_to_fbx_writes_exporter_schema_sig_on_export(tmp_path, monkeypatch):
    """輸出成功時、prefab sigと対でexport_schema.sha256も必ず書かれる。"""
    paths = _make_fake_exporter_sources(tmp_path, b"exporter-v1")
    monkeypatch.setattr(lue, "_EXPORTER_SOURCE_FILES", paths)
    prefab = tmp_path / "avatar.prefab"
    _write_prefab(str(prefab))
    out_dir = tmp_path / "out"
    export_ps1 = str(tmp_path / "export_from_unity.ps1")
    calls = []
    fake_run = _make_fake_export_run_fn(calls)

    result = lue.resolve_prefab_to_fbx(str(prefab), str(out_dir), export_ps1, run_fn=fake_run)
    assert result["ok"] is True
    assert result["exported"] is True
    schema_sig = lue.exporter_schema_sig_path(os.path.abspath(str(out_dir)))
    assert os.path.isfile(schema_sig)
    with open(schema_sig, encoding="utf-8") as f:
        assert f.read().strip() == lue.exporter_schema_fingerprint()


def test_resolve_prefab_to_fbx_reexports_when_only_exporter_schema_is_stale(
    tmp_path, monkeypatch
):
    """受入条件(コーディネータ指示の再現テストそのもの): prefab内容は一切
    変わっていないのに、旧スキーマのキャッシュ(export_schema.sha256が
    無い、work\\flatHaori_export\\と同型)から出発すると自動的に1回だけ
    再輸出される。負の対照として、その後の3回目呼び出しは(新スキーマの
    署名が書かれた後なので)fresh=Trueのまま再輸出されないことも確認する。"""
    paths = _make_fake_exporter_sources(tmp_path, b"exporter-v1")
    monkeypatch.setattr(lue, "_EXPORTER_SOURCE_FILES", paths)
    prefab = tmp_path / "avatar.prefab"
    _write_prefab(str(prefab), b"flathaori-prefab-content")
    out_dir = tmp_path / "out"
    export_ps1 = str(tmp_path / "export_from_unity.ps1")
    calls = []
    fake_run = _make_fake_export_run_fn(calls, write_physbones=True)

    # 旧世代キャッシュを手で再現(prefab sigのみ、schema sigは無し)。
    out_dir_abs = os.path.abspath(str(out_dir))
    os.makedirs(out_dir_abs, exist_ok=True)
    with open(os.path.join(out_dir_abs, "avatar.fbx"), "wb") as f:
        f.write(b"legacy-fbx-bytes")
    with open(os.path.join(out_dir_abs, "physbones.json"), "w", encoding="utf-8") as f:
        f.write('{"format": "divetopalworld-physbones-1", "physbones": '
                '[{"anchor": "Head_L.001", "chains": [["Head_L.002"]]}]}')  # 旧スキーマ=params無し
    lue.save_export_sig(out_dir_abs, str(prefab))
    assert not os.path.isfile(lue.exporter_schema_sig_path(out_dir_abs))

    # 1回目: 旧キャッシュのまま呼ぶと、prefabハッシュは一致しているのに
    # schema sig欠落のため再輸出が起きる。
    r1 = lue.resolve_prefab_to_fbx(str(prefab), str(out_dir), export_ps1, run_fn=fake_run)
    assert r1["ok"] is True
    assert r1["exported"] is True  # 自動再輸出された
    assert len(calls) == 1
    # fake exporterはparams付きのphysbones.jsonは書かない前提のシミュレータ
    # なので、ここでは「再輸出が起きたこと」自体を検証すれば足りる
    # (実物のUnityエクスポータが新スキーマを書くことはunity側の責務であり
    # 本テストのfakeの役割ではない)。

    # 負の対照: 2回目は新しく書かれたschema sigのおかげでfresh、再輸出なし。
    r2 = lue.resolve_prefab_to_fbx(str(prefab), str(out_dir), export_ps1, run_fn=fake_run)
    assert r2["ok"] is True
    assert r2["fresh"] is True
    assert r2["exported"] is False
    assert len(calls) == 1  # 増えていない


# =====================================================================
# resolve_prefab_to_fbx: 受入条件1-4
# =====================================================================

def test_resolve_prefab_to_fbx_first_call_exports_second_call_is_fresh(tmp_path):
    """受入条件1: 同一prefabで resolve_prefab_to_fbx() を2回呼ぶ→1回目
    exported=True、2回目fresh=True・exported=False(Unity再起動なし=fake
    run_fnの呼び出し回数が1のまま増えないことで確認)。"""
    prefab = tmp_path / "avatar.prefab"
    _write_prefab(str(prefab))
    out_dir = tmp_path / "out"
    export_ps1 = str(tmp_path / "export_from_unity.ps1")  # fake経由なので実在不要
    calls = []
    fake_run = _make_fake_export_run_fn(calls)

    r1 = lue.resolve_prefab_to_fbx(str(prefab), str(out_dir), export_ps1, run_fn=fake_run)
    assert r1["ok"] is True
    assert r1["exported"] is True
    assert r1["fresh"] is False
    assert r1["fbx"] and os.path.isfile(r1["fbx"])
    assert r1["humanoid_json"] and os.path.isfile(r1["humanoid_json"])
    assert r1["material_map_json"] and os.path.isfile(r1["material_map_json"])
    assert len(calls) == 1

    r2 = lue.resolve_prefab_to_fbx(str(prefab), str(out_dir), export_ps1, run_fn=fake_run)
    assert r2["ok"] is True
    assert r2["fresh"] is True
    assert r2["exported"] is False
    assert r2["fbx"] == r1["fbx"]
    assert len(calls) == 1  # fake Unity輸出は再度呼ばれていない


def test_resolve_prefab_to_fbx_reexports_when_prefab_changes(tmp_path):
    """受入条件2: prefabの中身を変更→sigが不一致になりexported=Trueが再度
    成立する(実Unityが使えないためexport_from_unity.ps1をfakeスタブに
    差し替えて検証)。"""
    prefab = tmp_path / "avatar.prefab"
    _write_prefab(str(prefab), b"prefab-v1")
    out_dir = tmp_path / "out"
    export_ps1 = str(tmp_path / "export_from_unity.ps1")
    calls = []
    fake_run = _make_fake_export_run_fn(calls)

    r1 = lue.resolve_prefab_to_fbx(str(prefab), str(out_dir), export_ps1, run_fn=fake_run)
    assert r1["exported"] is True
    assert len(calls) == 1

    r2 = lue.resolve_prefab_to_fbx(str(prefab), str(out_dir), export_ps1, run_fn=fake_run)
    assert r2["fresh"] is True
    assert len(calls) == 1

    # prefabの中身を変更(受入条件文言は「別ファイルにリネームしてまた戻す」
    # だが、鮮度判定は常に「現在のprefabのSHA256」なので単純な上書きでも
    # 同じ効果になる)
    _write_prefab(str(prefab), b"prefab-v2-changed")

    r3 = lue.resolve_prefab_to_fbx(str(prefab), str(out_dir), export_ps1, run_fn=fake_run)
    assert r3["ok"] is True
    assert r3["exported"] is True
    assert r3["fresh"] is False
    assert len(calls) == 2  # 再輸出でfake run_fnが再度呼ばれた


def test_resolve_prefab_to_fbx_fails_closed_when_export_script_fails(tmp_path):
    """受入条件3(負の対照): export_from_unity.ps1が失敗(non-zero exit)する
    場合、ok=Falseかつreasonに診断情報が入る。"""
    prefab = tmp_path / "avatar.prefab"
    _write_prefab(str(prefab))
    out_dir = tmp_path / "out"
    export_ps1 = str(tmp_path / "export_from_unity.ps1")
    calls = []
    fake_run = _make_fake_export_run_fn(
        calls, fail=True, fail_stderr="Unity editor was not found"
    )

    result = lue.resolve_prefab_to_fbx(str(prefab), str(out_dir), export_ps1, run_fn=fake_run)
    assert result["ok"] is False
    assert result["reason"]
    assert "Unity editor was not found" in result["reason"]
    assert result["fbx"] is None
    assert result["exported"] is False


def test_resolve_prefab_to_fbx_fails_closed_when_fbx_not_produced(tmp_path):
    """負の対照: exit=0で成功終了したのに.fbxが出力されていない異常ケースでも
    ok=Falseに倒す(「輸出は成功したことになっているが実体が無い」を見逃さない)。
    このときsigも保存しない(次回も必ず再挑戦させ、偽の鮮度キャッシュを
    作らないため)。"""
    prefab = tmp_path / "avatar.prefab"
    _write_prefab(str(prefab))
    out_dir = tmp_path / "out"
    export_ps1 = str(tmp_path / "export_from_unity.ps1")
    calls = []
    fake_run = _make_fake_export_run_fn(calls, write_fbx=False)

    result = lue.resolve_prefab_to_fbx(str(prefab), str(out_dir), export_ps1, run_fn=fake_run)
    assert result["ok"] is False
    assert ".fbx" in result["reason"]
    assert not os.path.isfile(lue.prefab_export_sig_path(os.path.abspath(str(out_dir))))


def test_resolve_prefab_to_fbx_fails_closed_when_run_fn_raises(tmp_path):
    """負の対照: run_fn自体が例外を投げる(pwsh実行ファイルが存在しない等)
    場合もok=Falseで、例外を外へ漏らさない。"""
    prefab = tmp_path / "avatar.prefab"
    _write_prefab(str(prefab))
    out_dir = tmp_path / "out"
    export_ps1 = str(tmp_path / "export_from_unity.ps1")

    def raising_run(cmd, **kwargs):
        raise OSError("pwsh not found")

    result = lue.resolve_prefab_to_fbx(
        str(prefab), str(out_dir), export_ps1, run_fn=raising_run
    )
    assert result["ok"] is False
    assert "pwsh not found" in result["reason"]


def test_resolve_prefab_to_fbx_passes_out_dir_as_abspath(tmp_path, monkeypatch):
    """work\\wp_702_progress.md記載の前任実測罠(相対パスだとUnityプロジェクト
    ディレクトリ起点で解決されて誤爆する)の再発防止確認: run_fnに渡るcmdの
    "-Out"引数が常に絶対パスであること(受入条件のPROPOSAL仕様コメント
    「out_dirは必ずabspathで渡す」)。"""
    prefab = tmp_path / "avatar.prefab"
    _write_prefab(str(prefab))
    monkeypatch.chdir(tmp_path)
    out_dir_rel = "relative_out"
    export_ps1 = str(tmp_path / "export_from_unity.ps1")
    calls = []
    fake_run = _make_fake_export_run_fn(calls)

    lue.resolve_prefab_to_fbx(str(prefab), out_dir_rel, export_ps1, run_fn=fake_run)
    assert len(calls) == 1
    cmd = calls[0]
    out_arg = cmd[cmd.index("-Out") + 1]
    assert os.path.isabs(out_arg)


def test_resolve_prefab_to_fbx_ok_when_humanoid_and_material_map_absent(tmp_path):
    """曖昧点の解釈確認(完了報告に明記): 仕様docstring「humanoid_json(あれば)」
    のとおり、fbxさえ生成されればhumanoid.json/material_map.jsonが無くても
    ok=Trueとし、該当キーはNoneにする(fbx自体が必須、他は任意)。"""
    prefab = tmp_path / "avatar.prefab"
    _write_prefab(str(prefab))
    out_dir = tmp_path / "out"
    export_ps1 = str(tmp_path / "export_from_unity.ps1")
    calls = []
    fake_run = _make_fake_export_run_fn(
        calls, write_humanoid=False, write_material_map=False
    )

    result = lue.resolve_prefab_to_fbx(str(prefab), str(out_dir), export_ps1, run_fn=fake_run)
    assert result["ok"] is True
    assert result["humanoid_json"] is None
    assert result["material_map_json"] is None


# =====================================================================
# physbones_json(dev#1356、揺れもの/dev#19サイドカー搬送): 正=載る/
# 負の対照=旧バージョンのUnityエクスポータ(サイドカー無し)でも従来どおり
# 動く(pak出力への影響ゼロを裏付ける単体レベルの確認)。
# =====================================================================

def test_resolve_prefab_to_fbx_carries_physbones_json_when_present(tmp_path):
    """正: Unityエクスポータがphysbones.jsonを書けば、job文脈(戻り値)に
    そのパスが載る(exported=True、fresh=Trueの両方で確認)。"""
    prefab = tmp_path / "avatar.prefab"
    _write_prefab(str(prefab))
    out_dir = tmp_path / "out"
    export_ps1 = str(tmp_path / "export_from_unity.ps1")
    calls = []
    fake_run = _make_fake_export_run_fn(calls, write_physbones=True)

    r1 = lue.resolve_prefab_to_fbx(str(prefab), str(out_dir), export_ps1, run_fn=fake_run)
    assert r1["ok"] is True
    assert r1["exported"] is True
    assert r1["physbones_json"] and os.path.isfile(r1["physbones_json"])
    assert os.path.basename(r1["physbones_json"]) == "physbones.json"

    r2 = lue.resolve_prefab_to_fbx(str(prefab), str(out_dir), export_ps1, run_fn=fake_run)
    assert r2["ok"] is True
    assert r2["fresh"] is True
    assert r2["physbones_json"] == r1["physbones_json"]


def test_resolve_prefab_to_fbx_physbones_json_none_when_absent(tmp_path):
    """負の対照(受入条件3の根拠): physbones.jsonを書かない旧バージョンの
    Unityエクスポータ(または本WPより前のキャッシュ)を模しても、他のキーは
    従来どおりで、physbones_jsonだけがNoneになる——搬送のみの追加であり、
    既存の鮮度判定・fbx/humanoid_json/material_map_jsonの挙動には一切
    影響しないことを確認する(pak出力バイト不変の単体レベルの裏付け)。"""
    prefab = tmp_path / "avatar.prefab"
    _write_prefab(str(prefab))
    out_dir = tmp_path / "out"
    export_ps1 = str(tmp_path / "export_from_unity.ps1")
    calls = []
    fake_run = _make_fake_export_run_fn(calls, write_physbones=False)

    result = lue.resolve_prefab_to_fbx(str(prefab), str(out_dir), export_ps1, run_fn=fake_run)
    assert result["ok"] is True
    assert result["exported"] is True
    assert result["physbones_json"] is None
    # 他のキーは物理ファイルが書かれた通常どおりの挙動のまま
    assert result["fbx"] and os.path.isfile(result["fbx"])
    assert result["humanoid_json"] and os.path.isfile(result["humanoid_json"])
    assert result["material_map_json"] and os.path.isfile(result["material_map_json"])


def test_resolve_prefab_to_fbx_physbones_json_does_not_affect_freshness(tmp_path):
    """負の対照: physbones.jsonの有無は鮮度判定(is_export_cache_fresh)の対象外。
    physbones.jsonが後から消えても(何らかの理由でサイドカーだけ失われても)、
    fbx+sigが健在なら引き続きfresh=Trueのまま(既存の鮮度契約を壊さない)。"""
    prefab = tmp_path / "avatar.prefab"
    _write_prefab(str(prefab))
    out_dir = tmp_path / "out"
    export_ps1 = str(tmp_path / "export_from_unity.ps1")
    calls = []
    fake_run = _make_fake_export_run_fn(calls, write_physbones=True)

    r1 = lue.resolve_prefab_to_fbx(str(prefab), str(out_dir), export_ps1, run_fn=fake_run)
    assert r1["ok"] is True
    physbones_path = r1["physbones_json"]
    assert physbones_path
    os.remove(physbones_path)

    r2 = lue.resolve_prefab_to_fbx(str(prefab), str(out_dir), export_ps1, run_fn=fake_run)
    assert r2["ok"] is True
    assert r2["fresh"] is True  # physbones.json消失は鮮度判定に影響しない
    assert r2["physbones_json"] is None  # ただしjob文脈には正直にNoneが載る
    assert len(calls) == 1  # 再輸出はされていない


# =====================================================================
# CLIエントリポイント(main/_cli_resolve、第3弾WP-2): pipeline\cli\convert.ps1
# Phase -1が呼び出す。実pwshは呼ばない——resolve_prefab_to_fbx自体をfakeへ
# 差し替える(モジュール属性の差し替えは_cli_resolve内のグローバル名参照解決
# 経由で効く。関数のデフォルト引数run_fnとは別の差し替え経路であることに注意)。
# =====================================================================


def test_cli_resolve_writes_result_json_not_stdout(tmp_path, monkeypatch):
    """convert.ps1側のstdoutパース汚染回避(PROPOSAL根拠H)の核心: 解決結果は
    --result-json先のファイルに書かれ、rcはresult["ok"]と一致する。"""
    calls = []

    def fake_resolve(prefab_path, out_dir, export_script, pwsh_exe="pwsh"):
        calls.append((prefab_path, out_dir, export_script, pwsh_exe))
        return {
            "ok": True, "reason": None, "fresh": True, "exported": False,
            "fbx": "C:\\fake\\a.fbx", "humanoid_json": None, "material_map_json": None,
        }

    monkeypatch.setattr(lue, "resolve_prefab_to_fbx", fake_resolve)
    prefab = tmp_path / "avatar.prefab"
    _write_prefab(str(prefab))
    result_json = tmp_path / "result.json"

    rc = lue.main([
        "resolve", "--prefab", str(prefab), "--work-root", str(tmp_path / "work"),
        "--export-script", str(tmp_path / "export.ps1"), "--result-json", str(result_json),
    ])

    assert rc == 0
    assert len(calls) == 1
    data = json.loads(result_json.read_text(encoding="utf-8"))
    assert data["ok"] is True
    assert data["fbx"] == "C:\\fake\\a.fbx"


def test_cli_resolve_exit_1_and_reason_in_result_json_on_failure(tmp_path, monkeypatch):
    """負の対照: 解決失敗時、exitコードは1でresult.jsonにもok=False+reasonが残る
    (convert.ps1側がfail-closedするために必要な契約)。"""

    def fake_resolve(*_a, **_k):
        return {
            "ok": False, "reason": "boom-forced-failure", "fresh": False,
            "exported": False, "fbx": None, "humanoid_json": None, "material_map_json": None,
        }

    monkeypatch.setattr(lue, "resolve_prefab_to_fbx", fake_resolve)
    prefab = tmp_path / "avatar.prefab"
    _write_prefab(str(prefab))
    result_json = tmp_path / "result.json"

    rc = lue.main([
        "resolve", "--prefab", str(prefab), "--work-root", str(tmp_path / "work"),
        "--export-script", str(tmp_path / "export.ps1"), "--result-json", str(result_json),
    ])

    assert rc == 1
    data = json.loads(result_json.read_text(encoding="utf-8"))
    assert data["ok"] is False
    assert data["reason"] == "boom-forced-failure"


def test_cli_main_rejects_unknown_subcommand():
    """負の対照: 未知のサブコマンドは2で拒否する(resolve以外を静かに受理しない)。"""
    assert lue.main(["bogus"]) == 2
    assert lue.main([]) == 2


def test_cli_resolve_derives_out_dir_via_shared_function_not_duplicated_formula(
    tmp_path, monkeypatch
):
    """負の対照(式の複製禁止、PROPOSAL WP-1仕様): CLIはout_dirを自前計算せず、
    resolve_unity_export_out_dir()(pipeline_runner.py委譲)へ渡した結果をそのまま
    resolve_prefab_to_fbx()へ渡す。convert.ps1側もこの式をps1内で複製しない
    設計(--work-rootのみ受け取り、--outは受け付けない)。"""
    captured = {}

    def fake_resolve(prefab_path, out_dir, export_script, pwsh_exe="pwsh"):
        captured["out_dir"] = out_dir
        return {
            "ok": True, "reason": None, "fresh": True, "exported": False,
            "fbx": "x", "humanoid_json": None, "material_map_json": None,
        }

    monkeypatch.setattr(lue, "resolve_prefab_to_fbx", fake_resolve)
    prefab = tmp_path / "avatar.prefab"
    _write_prefab(str(prefab))
    work_root = str(tmp_path / "work")

    lue.main([
        "resolve", "--prefab", str(prefab), "--work-root", work_root,
        "--export-script", "dummy.ps1", "--result-json", str(tmp_path / "r.json"),
    ])

    assert captured["out_dir"] == pr.resolve_unity_export_out_dir(work_root, str(prefab))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
