# -*- coding: utf-8 -*-
"""build_pak_from_avatar._run_sway_abp_patch() の結線テスト(dev#19、揺れもの
pak生成の製品パイプライン結線)。

_run_dt_patch()と違い、本関数はPalworldの実pak(ユーザーのゲームインストール)
を必要としない(揺れABPテンプレは自前生成済みでリポジトリに同梱されている
ため、job.jsonだけで完結する)。したがって実Palworld環境無しでこの結線
そのものを直接検証できる。
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_pak_from_avatar as bpfa  # noqa: E402


def _write_job(tmp_path, **extra):
    job = {"vrm_path": "dummy.vrm", "avatar_name": "dummy"}
    job.update(extra)
    job_json = tmp_path / "job.json"
    with open(job_json, "w", encoding="utf-8") as f:
        json.dump(job, f)
    return str(job_json)


def test_run_sway_abp_patch_disabled_returns_empty(tmp_path):
    """負の対照: sway_intensity無しのjob.jsonは完全no-op(作業ディレクトリ
    にsway_abpサブディレクトリすら作られない)。"""
    job_json = _write_job(tmp_path)
    work = str(tmp_path / "work")
    os.makedirs(work)
    entries = bpfa._run_sway_abp_patch(job_json, work)
    assert entries == []
    assert not os.path.isdir(os.path.join(work, "sway_abp"))


def test_run_sway_abp_patch_enabled_returns_all_templates(tmp_path):
    job_json = _write_job(tmp_path, sway_intensity="normal")
    work = str(tmp_path / "work")
    os.makedirs(work)
    entries = bpfa._run_sway_abp_patch(job_json, work)

    n_templates = len(bpfa.sway_abp_build.load_template_manifest())
    assert len(entries) == 2 * n_templates
    for abs_path, rel in entries:
        assert os.path.isfile(abs_path)
        assert rel.startswith("Blueprint/Character/Player/Imp_Cloth/ABP_")
        assert ".." not in rel.split("/")
        assert rel.endswith(".uasset") or rel.endswith(".uexp")


def test_run_sway_abp_patch_missing_job_json_dies(tmp_path):
    """負の対照: job.jsonが存在しないパスを渡すとdie()(sys.exit(1))で
    停止する(黙って空リストへ倒れない)。"""
    work = str(tmp_path / "work")
    os.makedirs(work)
    with pytest.raises(SystemExit):
        bpfa._run_sway_abp_patch(str(tmp_path / "no_such_job.json"), work)
