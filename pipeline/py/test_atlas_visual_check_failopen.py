# -*- coding: utf-8 -*-
"""dev#1468受入テスト: アトラス視覚チェックFAILを、変換を止めるdie()から
「##AVATAR_WARNING##で警告した上で変換を継続する」へ降格したことの検証。

背景(オーナー裁定2026-08-15、issue #1468): 「こっちの勝手な正義感で
『本来使えるかもしれない物』を『失敗』と断定して『ユーザーに渡さない』と
いうことをするのをやめてください。preflight同様『内部チェックで問題が
あったから問題があるかもしれないけど適用しました』があるべき姿です」。

本ファイルは `pipeline\\py\\convert_noue.py::_render_atlas_visual_check` を、
Blenderサブプロセス(cn.subprocess.run)をmonkeypatchしてエンドツーエンドに
駆動する(_render_atlas_visual_check自身はbpy非依存で、比較対象PNGを
実際に読んでNCCを計算する)。

実行: python -m pytest pipeline/py/test_atlas_visual_check_failopen.py -q
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert_noue as cn  # noqa: E402
import vp_tex  # noqa: E402


def _rng_image(rng, h, w, base):
    """base周辺の小さな独立ノイズを持つ画像(健全なre-bake相当の微小差)。"""
    noise = rng.integers(-3, 4, size=(h, w, 3))
    arr = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[..., :3] = arr
    out[..., 3] = 255
    return out


def _make_ref_image(h, w):
    rng = np.random.default_rng(1468)
    base = rng.integers(0, 255, size=(h, w, 3)).astype(np.uint8)
    return _rng_image(rng, h, w, base), base


def _make_matching_sample(base, h, w):
    """refとほぼ同一(微小ノイズのみ)= PASSさせるための比較画像。"""
    rng = np.random.default_rng(2026)
    return _rng_image(rng, h, w, base)


def _make_broken_sample(base, h, w):
    """一部タイル(左上64x64相当)だけ全く別の絵に差し替えた比較画像
    (dev#76の局所破損想定=タイル最小NCCでFAILさせる)。"""
    rng = np.random.default_rng(2026)
    out = _rng_image(rng, h, w, base)
    # 左上のパッチを別内容(反転パターン)に差し替え、タイルNCCを崩す
    out[0:64, 0:64, 0] = 255 - out[0:64, 0:64, 0]
    out[0:64, 0:64, 1] = (out[0:64, 0:64, 1].astype(int) * 37 % 256).astype(np.uint8)
    out[0:64, 0:64, 2] = 0
    return out


def _setup_job(tmp_path, gender="female"):
    job_dir = tmp_path / "job"
    converted_dir = job_dir / "converted"
    converted_dir.mkdir(parents=True)
    atlas_dir = tmp_path / "atlas"
    atlas_dir.mkdir(parents=True)
    job = {"job_dir": str(job_dir)}
    ref_path = str(converted_dir / f"preview_{gender}_stand.png")
    atlas_png_path = str(atlas_dir / "atlas_body.png")
    return job, str(atlas_dir), ref_path, atlas_png_path


def _install_fake_blender(monkeypatch, out_png_path, sample_rgba):
    """cn.subprocess.runを、実Blenderを起動する代わりにout_pngを書き出す
    フェイクへ差し替える(exit=0を返す=経路②レンダリング失敗は通らない)。"""
    def _fake_run(cmd, stdout=None, stderr=None, text=None):
        vp_tex.encode_png(out_png_path, sample_rgba)

        class _R:
            returncode = 0
        return _R()
    monkeypatch.setattr(cn.subprocess, "run", _fake_run)


@pytest.fixture(autouse=True)
def _small_patch(monkeypatch):
    # 128x128のテスト画像でも十分な粒度になるよう、実運用の64のままでOK
    # (このfixtureは将来サイズを変える場合の差し込み点として残す)
    yield


def test_atlas_visual_check_fail_warns_and_continues(tmp_path, monkeypatch, capsys):
    """受入条件1(前半): 視覚チェックFAIL条件で変換が完走し、
    ##AVATAR_WARNING##が出る(die()は呼ばれずSystemExitが飛ばない)。"""
    monkeypatch.delenv("D2P_STRICT_VISUAL_CHECK", raising=False)
    h = w = 128
    job, atlas_dir, ref_path, atlas_png_path = _setup_job(tmp_path)
    ref_rgba, base = _make_ref_image(h, w)
    vp_tex.encode_png(ref_path, ref_rgba)
    vp_tex.encode_png(atlas_png_path, ref_rgba)  # 存在確認のみに使われるダミー

    broken_sample = _make_broken_sample(base, h, w)
    out_png_path = os.path.join(atlas_dir, "atlascheck_female.png")
    _install_fake_blender(monkeypatch, out_png_path, broken_sample)

    # die()を直接呼び出したかどうかも独立して監視する(WARN経路ではNGな呼び出し)
    died = {"called": False}

    def _spy_die(msg):
        died["called"] = True
        raise SystemExit(1)
    monkeypatch.setattr(cn, "die", _spy_die)

    cn._render_atlas_visual_check(job, "female", "dummy.blend", "dummy_blender.exe", atlas_dir)

    out = capsys.readouterr().out
    assert not died["called"], (
        "エンドユーザー経路でdie()が呼ばれた(FAILがまだ変換を止めている)")
    assert "##AVATAR_WARNING##" in out, f"AVATAR_WARNINGが出力されていない: {out!r}"
    assert "post-atlas visual check detected a possible mismatch" in out
    assert "##ATLAS_VISUAL_CHECK## RAN" in out and "result=FAIL" in out, (
        "検出結果マーカー(result=FAIL)が維持されていない")


def test_atlas_visual_check_pass_no_warning(tmp_path, monkeypatch, capsys):
    """負の対照: チェックPASS時は##AVATAR_WARNING##が出ない。"""
    monkeypatch.delenv("D2P_STRICT_VISUAL_CHECK", raising=False)
    h = w = 128
    job, atlas_dir, ref_path, atlas_png_path = _setup_job(tmp_path)
    ref_rgba, base = _make_ref_image(h, w)
    vp_tex.encode_png(ref_path, ref_rgba)
    vp_tex.encode_png(atlas_png_path, ref_rgba)

    matching_sample = _make_matching_sample(base, h, w)
    out_png_path = os.path.join(atlas_dir, "atlascheck_female.png")
    _install_fake_blender(monkeypatch, out_png_path, matching_sample)

    died = {"called": False}

    def _spy_die(msg):
        died["called"] = True
        raise SystemExit(1)
    monkeypatch.setattr(cn, "die", _spy_die)

    cn._render_atlas_visual_check(job, "female", "dummy.blend", "dummy_blender.exe", atlas_dir)

    out = capsys.readouterr().out
    assert not died["called"]
    assert "##AVATAR_WARNING##" not in out, f"PASS時にAVATAR_WARNINGが出た: {out!r}"
    assert "##ATLAS_VISUAL_CHECK## RAN" in out and "result=PASS" in out


def test_atlas_visual_check_fail_dies_under_strict_release_gate(tmp_path, monkeypatch, capsys):
    """受入条件2相当の裏側: D2P_STRICT_VISUAL_CHECK=1(devtools\\relgate.py=
    リリース関所)のときは従来どおりdie()する(既知良品検体でのFAILは
    真の退行として引き続きfail-closedで検出する)。"""
    monkeypatch.setenv("D2P_STRICT_VISUAL_CHECK", "1")
    h = w = 128
    job, atlas_dir, ref_path, atlas_png_path = _setup_job(tmp_path)
    ref_rgba, base = _make_ref_image(h, w)
    vp_tex.encode_png(ref_path, ref_rgba)
    vp_tex.encode_png(atlas_png_path, ref_rgba)

    broken_sample = _make_broken_sample(base, h, w)
    out_png_path = os.path.join(atlas_dir, "atlascheck_female.png")
    _install_fake_blender(monkeypatch, out_png_path, broken_sample)

    with pytest.raises(SystemExit):
        cn._render_atlas_visual_check(job, "female", "dummy.blend", "dummy_blender.exe", atlas_dir)

    out = capsys.readouterr().out
    assert "##AVATAR_WARNING##" in out, (
        "strictモードでもWARN自体は先に出力される想定(die()はその後)")
