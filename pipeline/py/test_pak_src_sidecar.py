# -*- coding: utf-8 -*-
"""pak⇒blend原則(2026-08-15深夜オーナー裁定)の単体テスト+負の対照。

pak_src_sidecar.py(pipeline\\py\\、bpy非依存)の write_sidecar/read_sidecar/
resolve_step02 を、実ファイルを使わず一時ディレクトリだけで検証する。

実行: python -m pytest pipeline\\py\\test_pak_src_sidecar.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pak_src_sidecar as sidecar  # noqa: E402


# ---------------------------------------------------------------------------
# sidecar_path()
# ---------------------------------------------------------------------------

def test_sidecar_path_appends_suffix(tmp_path):
    pak = tmp_path / "foo_P.pak"
    assert sidecar.sidecar_path(str(pak)) == str(pak) + ".src.json"


def test_sidecar_path_is_absolute_even_for_relative_input(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = sidecar.sidecar_path("relative_name_P.pak")
    assert os.path.isabs(p)


# ---------------------------------------------------------------------------
# write_sidecar() / read_sidecar(): 正常系ラウンドトリップ
# ---------------------------------------------------------------------------

def test_write_then_read_roundtrip(tmp_path):
    pak = tmp_path / "job1" / "out_P.pak"
    pak.parent.mkdir(parents=True)
    pak.write_bytes(b"dummy pak bytes")
    step02_female = tmp_path / "job1" / "converted" / "step02_female.blend"
    step02_female.parent.mkdir(parents=True)
    step02_female.write_bytes(b"dummy blend")
    job_json = tmp_path / "job1" / "job.json"
    job_json.write_text("{}", encoding="utf-8")

    out_path = sidecar.write_sidecar(
        str(pak), {"Female": str(step02_female), "Male": None},
        job_json=str(job_json))

    assert out_path == sidecar.sidecar_path(str(pak))
    assert os.path.exists(out_path)

    data = sidecar.read_sidecar(str(pak))
    assert data is not None
    assert data["pak"] == os.path.abspath(str(pak))
    assert data["step02_female"] == os.path.abspath(str(step02_female))
    assert data["step02_male"] is None
    assert data["job_dir"] == os.path.abspath(str(tmp_path / "job1"))
    assert "generated_at" in data and data["generated_at"]
    assert data["generator"] == "build_pak_from_avatar.py"


def test_write_sidecar_custom_generator(tmp_path):
    pak = tmp_path / "custom_P.pak"
    out_path = sidecar.write_sidecar(
        str(pak), {"Female": None, "Male": None}, generator="my_custom_tool.py")
    data = json.loads((tmp_path / "custom_P.pak.src.json").read_text(encoding="utf-8"))
    assert data["generator"] == "my_custom_tool.py"
    assert out_path == str(tmp_path / "custom_P.pak.src.json")


# ---------------------------------------------------------------------------
# read_sidecar(): 負の対照(存在しない/壊れている)
# ---------------------------------------------------------------------------

def test_read_sidecar_missing_returns_none_negative_control(tmp_path):
    """負の対照: サイドカー自体が無ければNone(例外を投げない)。"""
    pak = tmp_path / "nosidecar_P.pak"
    assert sidecar.read_sidecar(str(pak)) is None


def test_read_sidecar_corrupt_json_returns_none_negative_control(tmp_path):
    """負の対照: サイドカーが壊れたJSONならNone(例外を投げない)。"""
    pak = tmp_path / "corrupt_P.pak"
    with open(sidecar.sidecar_path(str(pak)), "w", encoding="utf-8") as f:
        f.write("{not valid json!!")
    assert sidecar.read_sidecar(str(pak)) is None


def test_read_sidecar_non_dict_json_returns_none_negative_control(tmp_path):
    """負の対照: JSONとしては妥当だがdictでない(例: 配列)場合もNone。"""
    pak = tmp_path / "arrayjson_P.pak"
    with open(sidecar.sidecar_path(str(pak)), "w", encoding="utf-8") as f:
        json.dump([1, 2, 3], f)
    assert sidecar.read_sidecar(str(pak)) is None


# ---------------------------------------------------------------------------
# resolve_step02(): 解決順・理由コードの網羅
# ---------------------------------------------------------------------------

def test_resolve_step02_success(tmp_path):
    pak = tmp_path / "ok_P.pak"
    step02 = tmp_path / "step02_female.blend"
    step02.write_bytes(b"x")
    sidecar.write_sidecar(str(pak), {"Female": str(step02), "Male": None})

    path, reason = sidecar.resolve_step02(str(pak), gender="Female")
    assert path == os.path.abspath(str(step02))
    assert reason == "sidecar"


def test_resolve_step02_no_pak_path_given_negative_control():
    path, reason = sidecar.resolve_step02(None)
    assert path is None
    assert reason == "no-pak-path-given"


def test_resolve_step02_sidecar_missing_negative_control(tmp_path):
    pak = tmp_path / "missing_P.pak"
    path, reason = sidecar.resolve_step02(str(pak))
    assert path is None
    assert reason == "sidecar-missing"


def test_resolve_step02_sidecar_invalid_negative_control(tmp_path):
    pak = tmp_path / "badjson_P.pak"
    with open(sidecar.sidecar_path(str(pak)), "w", encoding="utf-8") as f:
        f.write("not json")
    path, reason = sidecar.resolve_step02(str(pak))
    assert path is None
    assert reason == "sidecar-invalid"


def test_resolve_step02_no_gender_entry_negative_control(tmp_path):
    """負の対照: 要求genderのstep02がサイドカーに記録されていない(None)場合。"""
    pak = tmp_path / "malegap_P.pak"
    sidecar.write_sidecar(str(pak), {"Female": None, "Male": None})
    path, reason = sidecar.resolve_step02(str(pak), gender="Female")
    assert path is None
    assert reason == "sidecar-no-female-entry"


def test_resolve_step02_step02_missing_on_disk_negative_control(tmp_path):
    """負の対照: サイドカーは記録されているが、step02の実ファイルが
    (work\\の使い捨て慣行等で)既に消えている場合。"""
    pak = tmp_path / "stale_P.pak"
    nonexistent_step02 = tmp_path / "already_deleted_step02_female.blend"
    sidecar.write_sidecar(str(pak), {"Female": str(nonexistent_step02), "Male": None})
    path, reason = sidecar.resolve_step02(str(pak), gender="Female")
    assert path is None
    assert reason == "sidecar-step02-missing-on-disk"


def test_resolve_step02_male_gender(tmp_path):
    pak = tmp_path / "maleok_P.pak"
    step02_male = tmp_path / "step02_male.blend"
    step02_male.write_bytes(b"x")
    sidecar.write_sidecar(str(pak), {"Female": None, "Male": str(step02_male)})
    path, reason = sidecar.resolve_step02(str(pak), gender="Male")
    assert path == os.path.abspath(str(step02_male))
    assert reason == "sidecar"
