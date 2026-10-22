# -*- coding: utf-8 -*-
"""build_pak_from_avatar._run_sway_hub_reparent_patch() の結線テスト
(dev#1508 W2a-2、汎用ハブ配線のpak結線)。

`_run_dt_patch()`と同じ「ユーザーのPalworld実pakからライブ抽出する」設計
のため、実Palworld環境が無くても`core.read_pak_entries`/
`pak_live_extract.extract_files`をmonkeypatchして結線ロジック自体
(json読み込み・ReparentStep変換・apply_reparent_chain呼び出し・
rel_path計算)を検証する(`test_wp_dev19_sway_abp_pipeline_wiring.py`と
同型の設計方針)。
"""
from __future__ import annotations

import json
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_pak_from_avatar as bpfa  # noqa: E402
import sway_shared_skeleton as sss  # noqa: E402
import vp_pakwrite  # noqa: E402


def _write_job(tmp_path, converted_dir=None, palworld_pak=None, **extra):
    job_dir = tmp_path / "job"
    job_dir.mkdir(exist_ok=True)
    job = {"vrm_path": "dummy.vrm", "avatar_name": "dummy", "job_dir": str(job_dir)}
    if palworld_pak is not None:
        job.setdefault("paths", {})["palworld_pak"] = palworld_pak
    job.update(extra)
    job_json = job_dir / "job.json"
    with open(job_json, "w", encoding="utf-8") as f:
        json.dump(job, f)
    if converted_dir is None:
        converted_dir = job_dir / "converted"
    os.makedirs(converted_dir, exist_ok=True)
    return str(job_json), str(converted_dir)


# =====================================================================
# 合成の最小共有Skeleton uasset/uexp(test_sway_shared_skeleton.pyと同型)
# =====================================================================

def _build_uasset_bytes(names):
    out = bytearray()
    out += struct.pack("<I", 0x9E2A83C1)
    out += struct.pack("<i", -7)
    out += struct.pack("<i", 0)
    out += struct.pack("<i", 0)
    out += struct.pack("<i", 0)
    out += struct.pack("<i", 0)
    out += struct.pack("<i", 0)
    out += struct.pack("<i", 0)
    out += struct.pack("<i", 0)
    out += struct.pack("<i", len(names))
    name_offset_pos = len(out)
    name_offset = name_offset_pos + 4
    out += struct.pack("<i", name_offset)
    assert len(out) == name_offset
    for nm in names:
        raw = nm.encode("ascii") + b"\x00"
        out += struct.pack("<i", len(raw))
        out += raw
        out += struct.pack("<i", 0)
    return bytes(out)


def _build_refskeleton_uexp_bytes(bone_defs, pad_before=37, pad_after=53):
    count = len(bone_defs)
    body = bytearray()
    body += struct.pack("<i", count)
    for name_idx, parent_idx, _q, _p, _s in bone_defs:
        body += struct.pack("<iii", name_idx, 0, parent_idx)
    body += struct.pack("<i", count)
    for _name_idx, _parent_idx, q, p, s in bone_defs:
        vals = list(q) + list(p) + list(s)
        body += struct.pack("<10d", *vals)
    body += struct.pack("<i", count)
    for i, (name_idx, _parent_idx, _q, _p, _s) in enumerate(bone_defs):
        body += struct.pack("<iii", name_idx, 0, i)
    return (b"\x00" * pad_before) + bytes(body) + (b"\x00" * pad_after)


IDENTITY_Q = (0.0, 0.0, 0.0, 1.0)


def _synthetic_sk_bytes(n_total=sss.DEFAULT_MIN_BONES):
    """root -> a -> b + フィラー骨(root直下)を、
    `sway_shared_skeleton.apply_reparent_chain()`の既定スキャン範囲
    (DEFAULT_MIN_BONES〜DEFAULT_MAX_BONES、実SK4079骨向けの安全域)に
    収まる規模まで水増しした合成共有Skeleton(reparent対象確認用)。
    本関数はmin_bones/max_bonesを本番コードから一切上書きしない
    (実機の安全マージンをテスト側で緩めない、という方針の裏返し)。"""
    names = ["root", "a", "b"] + [f"filler{i:04d}" for i in range(n_total - 3)]
    bone_defs = [
        (0, -1, IDENTITY_Q, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        (1, 0, IDENTITY_Q, (1.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        (2, 1, IDENTITY_Q, (2.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
    ] + [(i, 0, IDENTITY_Q, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)) for i in range(3, n_total)]
    return _build_uasset_bytes(names), _build_refskeleton_uexp_bytes(bone_defs)


def _patch_monkeys(monkeypatch, uasset_bytes, uexp_bytes, pak_path):
    """core.read_pak_entries/pak_live_extract.extract_files を、合成SKバイト
    列を返すダブルへ差し替える(実Palworld pak不要)。"""
    want = [bpfa.SWAY_HUB_SK_VANILLA_REL + ext for ext in (".uasset", ".uexp")]

    def _fake_read_pak_entries(path):
        assert path == pak_path
        return "fake_mount", {p: {} for p in want}

    def _fake_extract_files(path, rel_paths):
        assert path == pak_path
        assert set(rel_paths) == set(want)
        return {
            want[0]: uasset_bytes,
            want[1]: uexp_bytes,
        }

    monkeypatch.setattr(bpfa.core, "read_pak_entries", _fake_read_pak_entries)
    monkeypatch.setattr(bpfa.pak_live_extract, "extract_files", _fake_extract_files)


# =====================================================================
# no-op経路
# =====================================================================

def test_no_reparent_json_returns_empty_and_no_pak_access(tmp_path, monkeypatch):
    """負の対照: sway_hub_reparent.jsonが存在しない(本WP時点の既定状態、
    step02未結線)場合は完全no-op——Palworld pak読み取りにすら触れない。"""
    def _boom(*a, **kw):
        raise AssertionError("must not touch the Palworld pak when the json is absent")
    monkeypatch.setattr(bpfa.core, "read_pak_entries", _boom)
    monkeypatch.setattr(bpfa.pak_live_extract, "extract_files", _boom)

    job_json, _conv = _write_job(tmp_path)
    work = str(tmp_path / "work")
    os.makedirs(work)
    entries = bpfa._run_sway_hub_reparent_patch(job_json, work)
    assert entries == []
    assert not os.path.isdir(os.path.join(work, "sway_hub_reparent"))


def test_empty_reparent_json_list_returns_empty(tmp_path, monkeypatch):
    job_json, conv = _write_job(tmp_path)
    with open(os.path.join(conv, bpfa.SWAY_HUB_REPARENT_FILENAME), "w", encoding="utf-8") as f:
        json.dump([], f)
    work = str(tmp_path / "work")
    os.makedirs(work)
    entries = bpfa._run_sway_hub_reparent_patch(job_json, work)
    assert entries == []


# =====================================================================
# 実配線経路
# =====================================================================

def test_reparent_json_present_patches_and_returns_correct_rel_paths(tmp_path, monkeypatch):
    uasset_bytes, uexp_bytes = _synthetic_sk_bytes()
    pak_path = str(tmp_path / "fake.pak")
    with open(pak_path, "wb") as f:
        f.write(b"dummy")  # os.path.exists()判定用、中身は読まれない(monkeypatch済み)
    _patch_monkeys(monkeypatch, uasset_bytes, uexp_bytes, pak_path)

    job_json, conv = _write_job(tmp_path, palworld_pak=pak_path)
    steps_json = [{"target": "b", "new_parent": "root",
                   "new_local_transform": [[0.0, 0.0, 0.0, 1.0], [9.0, 8.0, 7.0], [1.0, 1.0, 1.0]],
                   "tag": "test-step"}]
    with open(os.path.join(conv, bpfa.SWAY_HUB_REPARENT_FILENAME), "w", encoding="utf-8") as f:
        json.dump(steps_json, f)

    work = str(tmp_path / "work")
    os.makedirs(work)
    entries = bpfa._run_sway_hub_reparent_patch(job_json, work)

    assert len(entries) == 2
    rels = sorted(rel for _abs, rel in entries)
    assert rels == sorted([
        "Model/Character/Skeleton/Human/SK_PalHuman_Skeleton.uasset",
        "Model/Character/Skeleton/Human/SK_PalHuman_Skeleton.uexp",
    ])
    for abs_path, rel in entries:
        assert os.path.isfile(abs_path)
        assert ".." not in rel.split("/")
        # effective_path(COMMON_MOUNT, rel)がバニラ正パスと一致すること
        eff = vp_pakwrite.effective_path(vp_pakwrite.COMMON_MOUNT, rel)
        assert eff == "../../../" + bpfa.SWAY_HUB_SK_VANILLA_REL + os.path.splitext(rel)[1]

    # 実際にreparentが適用されたことを、パッチ後のuexpを再スキャンして確認
    uexp_abs = next(a for a, r in entries if r.endswith(".uexp"))
    with open(uexp_abs, "rb") as f:
        patched_uexp = f.read()
    names = ["root", "a", "b"] + [f"filler{i:04d}" for i in range(sss.DEFAULT_MIN_BONES - 3)]
    loc = sss.scan_full_refskeleton(patched_uexp, names)
    d = dict(loc.bones)
    assert d["b"] == 0  # "root"(idx0)へreparentされた


def test_reparent_json_writes_g3_patch_manifest_matching_applied_state(tmp_path, monkeypatch):
    """dev#1508 W2a-2d(G3ゲート昇格): job_dir/converted/配下へ
    sway_hub_patch_manifest.jsonが書かれ、その内容が実際にパッチ済みの
    uexpから読み取れる状態(親・座標)と一致することを確認する。"""
    uasset_bytes, uexp_bytes = _synthetic_sk_bytes()
    pak_path = str(tmp_path / "fake.pak")
    with open(pak_path, "wb") as f:
        f.write(b"dummy")
    _patch_monkeys(monkeypatch, uasset_bytes, uexp_bytes, pak_path)

    job_json, conv = _write_job(tmp_path, palworld_pak=pak_path)
    steps_json = [{"target": "b", "new_parent": "root",
                   "new_local_transform": [[0.0, 0.0, 0.0, 1.0], [9.0, 8.0, 7.0], [1.0, 1.0, 1.0]],
                   "tag": "test-step"}]
    with open(os.path.join(conv, bpfa.SWAY_HUB_REPARENT_FILENAME), "w", encoding="utf-8") as f:
        json.dump(steps_json, f)

    work = str(tmp_path / "work")
    os.makedirs(work)
    bpfa._run_sway_hub_reparent_patch(job_json, work)

    manifest_path = os.path.join(conv, bpfa.SWAY_HUB_PATCH_MANIFEST_FILENAME)
    assert os.path.isfile(manifest_path)
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["package"] == bpfa.SWAY_HUB_SK_PACKAGE_NAME
    assert len(manifest["steps"]) == 1
    step = manifest["steps"][0]
    assert step["target_name"] == "b"
    assert step["tag"] == "test-step"
    assert step["old_parent_name"] == "a"
    assert step["new_parent_name"] == "root"
    assert step["new_parent_idx"] == 0
    assert step["transform_changed"] is True
    assert step["pos"] == [9.0, 8.0, 7.0]
    assert step["quat"] == [0.0, 0.0, 0.0, 1.0]
    assert step["scale"] == [1.0, 1.0, 1.0]


def test_empty_reparent_json_list_writes_no_manifest(tmp_path, monkeypatch):
    """負の対照: 揺れハブ無効(steps空)ではmanifestも書かれない(=差分ゼロで
    preflight G3側はentries不在の既定経路になり、manifestが無くてもPASS
    する設計と整合する)。"""
    job_json, conv = _write_job(tmp_path)
    with open(os.path.join(conv, bpfa.SWAY_HUB_REPARENT_FILENAME), "w", encoding="utf-8") as f:
        json.dump([], f)
    work = str(tmp_path / "work")
    os.makedirs(work)
    bpfa._run_sway_hub_reparent_patch(job_json, work)
    manifest_path = os.path.join(conv, bpfa.SWAY_HUB_PATCH_MANIFEST_FILENAME)
    assert not os.path.isfile(manifest_path)


def test_reparent_json_missing_target_bone_dies(tmp_path, monkeypatch):
    """負の対照: 存在しない骨名をtargetにした場合、apply_reparent_chain()の
    SharedSkeletonErrorをdie()(sys.exit(1))へ変換して変換全体を止める。"""
    uasset_bytes, uexp_bytes = _synthetic_sk_bytes()
    pak_path = str(tmp_path / "fake.pak")
    with open(pak_path, "wb") as f:
        f.write(b"dummy")
    _patch_monkeys(monkeypatch, uasset_bytes, uexp_bytes, pak_path)

    job_json, conv = _write_job(tmp_path, palworld_pak=pak_path)
    steps_json = [{"target": "no_such_bone", "new_parent": "root", "tag": "bad-step"}]
    with open(os.path.join(conv, bpfa.SWAY_HUB_REPARENT_FILENAME), "w", encoding="utf-8") as f:
        json.dump(steps_json, f)

    work = str(tmp_path / "work")
    os.makedirs(work)
    with pytest.raises(SystemExit):
        bpfa._run_sway_hub_reparent_patch(job_json, work)


def test_reparent_json_malformed_entry_dies(tmp_path, monkeypatch):
    """負の対照: 必須キー("new_parent")が欠けたJSONは、pakを読む前に
    die()する(malformed入力を黙って部分処理しない)。"""
    def _boom(*a, **kw):
        raise AssertionError("must not touch the Palworld pak for malformed json")
    monkeypatch.setattr(bpfa.core, "read_pak_entries", _boom)
    monkeypatch.setattr(bpfa.pak_live_extract, "extract_files", _boom)

    pak_path = str(tmp_path / "fake.pak")
    with open(pak_path, "wb") as f:
        f.write(b"dummy")
    job_json, conv = _write_job(tmp_path, palworld_pak=pak_path)
    with open(os.path.join(conv, bpfa.SWAY_HUB_REPARENT_FILENAME), "w", encoding="utf-8") as f:
        json.dump([{"target": "b"}], f)  # new_parent missing

    work = str(tmp_path / "work")
    os.makedirs(work)
    with pytest.raises(SystemExit):
        bpfa._run_sway_hub_reparent_patch(job_json, work)


def test_missing_job_json_dies(tmp_path):
    work = str(tmp_path / "work")
    os.makedirs(work)
    with pytest.raises(SystemExit):
        bpfa._run_sway_hub_reparent_patch(str(tmp_path / "no_such_job.json"), work)


def test_missing_palworld_pak_dies(tmp_path):
    job_json, conv = _write_job(tmp_path, palworld_pak=str(tmp_path / "does_not_exist.pak"))
    with open(os.path.join(conv, bpfa.SWAY_HUB_REPARENT_FILENAME), "w", encoding="utf-8") as f:
        json.dump([{"target": "b", "new_parent": "root"}], f)
    work = str(tmp_path / "work")
    os.makedirs(work)
    with pytest.raises(SystemExit):
        bpfa._run_sway_hub_reparent_patch(job_json, work)
