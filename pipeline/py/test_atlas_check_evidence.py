# -*- coding: utf-8 -*-
"""dev#1468(証拠保存WP)の単体テスト: アトラス視覚チェックの比較画像・差分画像を
恒久保存し、grep可能な `[ATLAS_CHECK]` タグでログへ出す機能を検証する。

対象: pipeline\\py\\convert_noue.py の
  - `_atlas_check_diff_image(a, b, amplify)`(差分可視化PNG生成、判定に無関係)
  - `_log_atlas_check_evidence(...)`(証拠ログの1行出力)
  - `_render_atlas_visual_check(...)`(上記2つを実際に配線した本体。Blender
    subprocessは`subprocess.run`をmonkeypatchして代替する——本テストは
    Blenderを起動しない)

方針: PASS/FAIL判定ロジック自体はこのWPのスコープ外であり変更していないため、
このファイルは「証拠(画像・ログ行)が実際に残るか」だけを検証する
(判定の閾値・分岐は test_ncc_impl_parity.py 等の既存テストの管轄)。

実行: python -m pytest pipeline/py/test_atlas_check_evidence.py -q
"""
import os
import sys

import numpy as np
import pytest

HERE_DIR = os.path.dirname(os.path.abspath(__file__))
if HERE_DIR not in sys.path:
    sys.path.insert(0, HERE_DIR)

import convert_noue as cn  # noqa: E402
import vp_tex  # noqa: E402


# ==================================================================
# 1. _atlas_check_diff_image: 差分可視化PNGの中身
# ==================================================================

def _rgba(rgb_u8):
    h, w = rgb_u8.shape[:2]
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[..., :3] = rgb_u8
    out[..., 3] = 255
    return out


def test_diff_image_identical_inputs_are_all_zero_but_opaque():
    a = _rgba(np.full((8, 8, 3), 100, dtype=np.uint8))
    b = a.copy()
    diff = cn._atlas_check_diff_image(a, b)
    assert diff.shape == (8, 8, 4)
    assert diff.dtype == np.uint8
    assert (diff[..., :3] == 0).all(), "同一画像同士のdiffは全チャンネル0であるべき"
    assert (diff[..., 3] == 255).all(), "diff画像は常に不透明であるべき(alphaで見えなくなると診断に使えない)"


def test_diff_image_amplifies_and_clips():
    a = _rgba(np.full((4, 4, 3), 10, dtype=np.uint8))
    b = _rgba(np.full((4, 4, 3), 50, dtype=np.uint8))  # 差=40
    diff = cn._atlas_check_diff_image(a, b, amplify=4)
    # 40*4=160 (クリップ無し)
    assert (diff[..., :3] == 160).all()

    b2 = _rgba(np.full((4, 4, 3), 200, dtype=np.uint8))  # 差=190
    diff2 = cn._atlas_check_diff_image(a, b2, amplify=4)
    # 190*4=760 -> 255にクリップされるはず
    assert (diff2[..., :3] == 255).all(), "大きな差は255へクリップされるべき(オーバーフローしない)"


def test_diff_image_roundtrips_through_png(tmp_path):
    """encode_png/decode_pngを実際に往復させ、保存先ファイルが正しく読める
    ことを確認する(_render_atlas_visual_check内の実際の使い方の縮図)。"""
    a = _rgba(np.zeros((6, 6, 3), dtype=np.uint8))
    b = _rgba(np.full((6, 6, 3), 3, dtype=np.uint8))  # 差=3
    diff = cn._atlas_check_diff_image(a, b, amplify=4)
    out_path = str(tmp_path / "diff.png")
    vp_tex.encode_png(out_path, diff)
    assert os.path.exists(out_path)
    _w, _h, decoded = vp_tex.decode_png(out_path)
    assert decoded.shape == (6, 6, 4)
    assert (decoded[..., :3] == 12).all()  # 3*4=12


# ==================================================================
# 2. _log_atlas_check_evidence: [ATLAS_CHECK]タグの中身
# ==================================================================

def test_log_atlas_check_evidence_emits_grepable_tag(capsys):
    cn._log_atlas_check_evidence(
        gender="male", result="PASS", ncc=0.9981, tile_min_ncc=0.6957,
        worst_tile=(320, 128), ref_png=r"C:\job\converted\preview_male_stand.png",
        out_png=r"C:\job\build\atlas\atlascheck_male.png",
        diff_png=r"C:\job\build\atlas\atlascheck_diff_male.png")
    out = capsys.readouterr().out
    assert "[ATLAS_CHECK]" in out
    line = next(ln for ln in out.splitlines() if "[ATLAS_CHECK]" in ln)
    assert "gender=male" in line
    assert "result=PASS" in line
    assert "ncc=0.9981" in line
    assert "tile_min_ncc=0.6957" in line
    assert "worst_tile=(320, 128)" in line
    assert r"pre=C:\job\converted\preview_male_stand.png" in line
    assert r"post=C:\job\build\atlas\atlascheck_male.png" in line
    assert r"diff=C:\job\build\atlas\atlascheck_diff_male.png" in line


def test_log_atlas_check_evidence_handles_fail_and_no_tiles():
    """FAIL時・tile_min_ncc=None(タイル無し)の両方でも例外なく出力できること。"""
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cn._log_atlas_check_evidence(
            gender="female", result="FAIL", ncc=0.5, tile_min_ncc=None,
            worst_tile=None, ref_png="ref.png", out_png="out.png", diff_png=None)
    out = buf.getvalue()
    assert "[ATLAS_CHECK]" in out
    assert "result=FAIL" in out
    assert "tile_min_ncc=NA" in out
    assert "diff=None" in out


# ==================================================================
# 3. _render_atlas_visual_check: 実際の配線(Blender subprocessをmonkeypatch)
# ==================================================================

class _FakeCompletedProcess:
    def __init__(self, returncode):
        self.returncode = returncode


def _write_check_fixture(job_dir, gender, w=16, h=16, seed=1, mismatch=False):
    """ref(converted/preview_{gender}_stand.png)とatlas_dir/atlas_body.pngを
    実ファイルとして用意する(_render_atlas_visual_check の前提チェックを
    満たすため)。mismatch=Trueならref/atlas_checkの内容を大きくずらしFAILへ
    倒す。"""
    rng = np.random.default_rng(seed)
    converted = os.path.join(job_dir, "converted")
    os.makedirs(converted, exist_ok=True)
    atlas_dir = os.path.join(job_dir, "build", "atlas")
    os.makedirs(atlas_dir, exist_ok=True)

    ref_rgba = _rgba(rng.integers(0, 255, size=(h, w, 3)).astype(np.uint8))
    ref_path = os.path.join(converted, f"preview_{gender}_stand.png")
    vp_tex.encode_png(ref_path, ref_rgba)

    atlas_png = os.path.join(atlas_dir, "atlas_body.png")
    vp_tex.encode_png(atlas_png, ref_rgba)  # 中身はrender_atlas_check.pyの入力なので何でもよい

    if mismatch:
        sample_rgba = _rgba(rng.integers(0, 255, size=(h, w, 3)).astype(np.uint8))
    else:
        sample_rgba = ref_rgba.copy()
    return ref_path, atlas_dir, atlas_png, sample_rgba


def test_render_atlas_visual_check_pass_saves_evidence(tmp_path, monkeypatch, capsys):
    job_dir = str(tmp_path / "job")
    ref_path, atlas_dir, atlas_png, sample_rgba = _write_check_fixture(
        job_dir, "male", mismatch=False)
    out_png = os.path.join(atlas_dir, "atlascheck_male.png")

    def fake_run(cmd, stdout=None, stderr=None, text=None):
        vp_tex.encode_png(out_png, sample_rgba)  # 「Blenderがレンダリングした」ことを模す
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(cn.subprocess, "run", fake_run)

    job = {"job_dir": job_dir}
    cn._render_atlas_visual_check(job, "male", "dummy.blend", "blender.exe", atlas_dir)

    out = capsys.readouterr().out
    assert "##ATLAS_VISUAL_CHECK## RAN gender=male" in out
    assert "result=PASS" in out
    assert "[ATLAS_CHECK] gender=male result=PASS" in out

    diff_path = os.path.join(atlas_dir, "atlascheck_diff_male.png")
    assert os.path.exists(out_png), "アトラス化後の比較画像(post)が保存されていない"
    assert os.path.exists(ref_path), "アトラス化前の比較画像(pre)が保存されていない"
    assert os.path.exists(diff_path), "差分可視化画像が保存されていない"
    assert f"diff={diff_path}" in out


def test_render_atlas_visual_check_fail_still_saves_evidence(tmp_path, monkeypatch, capsys):
    """FAIL時、既定(非strict)では##AVATAR_WARNING##で警告した上で変換を継続
    (dev#1468 PR #1475のfail-open降格、SystemExitはしない)するが、それより
    前に証拠(画像+ログ)が残ることを確認する(「FAILしたが何が原因か」を
    後から目視できる型)。"""
    job_dir = str(tmp_path / "job")
    ref_path, atlas_dir, atlas_png, sample_rgba = _write_check_fixture(
        job_dir, "female", mismatch=True)
    out_png = os.path.join(atlas_dir, "atlascheck_female.png")

    def fake_run(cmd, stdout=None, stderr=None, text=None):
        vp_tex.encode_png(out_png, sample_rgba)
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(cn.subprocess, "run", fake_run)
    monkeypatch.delenv("D2P_STRICT_VISUAL_CHECK", raising=False)

    job = {"job_dir": job_dir}
    # 非strictでは変換を止めない(SystemExitしない)。
    cn._render_atlas_visual_check(job, "female", "dummy.blend", "blender.exe", atlas_dir)

    out = capsys.readouterr().out
    assert "result=FAIL" in out
    assert "[ATLAS_CHECK] gender=female result=FAIL" in out
    assert "##AVATAR_WARNING##" in out
    diff_path = os.path.join(atlas_dir, "atlascheck_diff_female.png")
    assert os.path.exists(diff_path), "FAIL時も差分可視化画像が保存されているべき"
    assert os.path.exists(out_png)
    assert os.path.exists(ref_path)


def test_render_atlas_visual_check_fail_strict_still_dies_with_evidence(
        tmp_path, monkeypatch, capsys):
    """D2P_STRICT_VISUAL_CHECK=1(リリース関所)ではFAIL時に従来どおりdie()
    (SystemExit)するが、そのdie()より前に証拠(画像+ログ)は残ることを確認する。"""
    job_dir = str(tmp_path / "job")
    ref_path, atlas_dir, atlas_png, sample_rgba = _write_check_fixture(
        job_dir, "female", mismatch=True)
    out_png = os.path.join(atlas_dir, "atlascheck_female.png")

    def fake_run(cmd, stdout=None, stderr=None, text=None):
        vp_tex.encode_png(out_png, sample_rgba)
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(cn.subprocess, "run", fake_run)
    monkeypatch.setenv("D2P_STRICT_VISUAL_CHECK", "1")

    job = {"job_dir": job_dir}
    with pytest.raises(SystemExit):
        cn._render_atlas_visual_check(job, "female", "dummy.blend", "blender.exe", atlas_dir)

    out = capsys.readouterr().out
    assert "result=FAIL" in out
    assert "[ATLAS_CHECK] gender=female result=FAIL" in out
    diff_path = os.path.join(atlas_dir, "atlascheck_diff_female.png")
    assert os.path.exists(diff_path), "FAIL時も差分可視化画像が保存されているべき"
    assert os.path.exists(out_png)
    assert os.path.exists(ref_path)


# ==================================================================
# 4. 負の対照: チェックが走らない経路(SKIPPED)では[ATLAS_CHECK]が出ない
# ==================================================================

def test_negative_control_skipped_path_emits_no_atlas_check_tag(tmp_path, capsys):
    """_visual_check_not_run()経由(refが無い=missing_inputs経路)では
    `[ATLAS_CHECK]`タグが一切出ないことを確認する(=証拠ログは「検査が実際に
    走った回」だけに紐づく、というこのWPの中核主張の反証可能性を示す)。"""
    job_dir = str(tmp_path / "job_skip")
    os.makedirs(job_dir, exist_ok=True)
    atlas_dir = os.path.join(job_dir, "build", "atlas")
    os.makedirs(atlas_dir, exist_ok=True)
    # ref(converted/preview_male_stand.png)もatlas_pngも用意しない
    # -> missing_inputs経路でreturnするはず

    job = {"job_dir": job_dir}
    cn._render_atlas_visual_check(job, "male", "dummy.blend", "blender.exe", atlas_dir)

    out = capsys.readouterr().out
    assert "##ATLAS_VISUAL_CHECK## SKIPPED gender=male reason=missing_inputs" in out
    assert "[ATLAS_CHECK]" not in out, (
        "検査が走っていない(SKIPPED)のに証拠タグが出た——"
        "_log_atlas_check_evidenceが誤って呼ばれている")
    diff_path = os.path.join(atlas_dir, "atlascheck_diff_male.png")
    assert not os.path.exists(diff_path), "検査が走っていないのに差分画像が生成された"
