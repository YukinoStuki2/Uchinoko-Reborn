# -*- coding: utf-8 -*-
"""dev#1417回帰テスト: convert_noue.py: resolve_textures() のfail-loud化。

背景(issue本文): tex_dir(job_dir/textures)ごと欠落した状態でビルドすると、
vp_tex.is_real_png()がOSErrorでFalseを返す(fail-open設計、意図的に無改変)
ため、全スロットが<not-actually-png:>として静かに除外され、
テンプレート同梱の既定柄がそのまま出荷されていた。この不具合の実害は
「ログにも警告にも出ない」ことなので、本ファイルはresolve_textures()を
実際に呼び出し、標準出力に[TEX_FALLBACK]診断ログと##AVATAR_WARNING##が
確かに現れることを検証する(test_convert_noue_tint.pyと同じ、bpy非依存の
エンドツーエンド統合試験パターン)。

G1: tex_dirが丸ごと欠落 -> 全スロット<not-actually-png:>経由でfail-loud
    ([TEX_FALLBACK]ログ+##AVATAR_WARNING##が出る)
G2(負の対照): 正常な入力(textures\\が揃っている)では[TEX_FALLBACK]も
    ##AVATAR_WARNING##も一切出ない
G3: 拡張子が.pngでない参照(FBX入力等)でもfail-loudになる
G4: フォールバック挙動そのものは無改変 -- G1のケースでも変換(resolve_textures
    自体)は例外を出さずに完走し、bodyラベルはresultに含まれない
    (=テンプレート既定柄を使う、という既存の判断は変えていないことの確認)

実行: python test_convert_noue_texfallback.py または pytest経由
"""
import contextlib
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert_noue  # noqa: E402
import vp_tex         # noqa: E402

failures = []


def check(label, cond, detail=""):
    if cond:
        print(f"[PASS] {label}")
    else:
        print(f"[FAIL] {label} {detail}")
        failures.append(label)
    assert cond, f"{label} {detail}".rstrip()


def make_job(job_dir):
    return {"job_dir": job_dir}


def write_white_png(path, size=16):
    import numpy as np
    img = np.full((size, size, 4), 255, dtype="uint8")
    vp_tex.encode_png(path, img)


def test_resolve_textures_missing_tex_dir_is_fail_loud():
    """issue本文の核: textures\\ ディレクトリごと欠落した状態でも変換自体は
    完走するが([TEX_FALLBACK]ログ+##AVATAR_WARNING##が必ず出る)。"""
    with tempfile.TemporaryDirectory() as job_dir:
        # tex_dir(job_dir/textures)を意図的に作らない。
        meta = {"slots": {
            "m00": {"orig_name": "body", "texture": "t00.png",
                    "base_color": [1.0, 1.0, 1.0, 1.0]},
        }}
        job = make_job(job_dir)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tex, slot_xf, alpha_mask = convert_noue.resolve_textures(job, meta)
        out = buf.getvalue()
        check("resolve_textures(missing tex_dir): completes without raising "
              "(fallback behavior itself unchanged, conversion still runs to completion)",
              True)
        check("resolve_textures(missing tex_dir): body label is NOT produced "
              "(template default stays -- same as before this WP)",
              "body" not in tex, str(tex))
        check("resolve_textures(missing tex_dir): stdout contains [TEX_FALLBACK] tag",
              "[TEX_FALLBACK]" in out, out)
        check("resolve_textures(missing tex_dir): stdout contains ##AVATAR_WARNING##",
              "##AVATAR_WARNING##" in out, out)
        check("resolve_textures(missing tex_dir): stdout mentions the skipped texture",
              "t00.png" in out, out)
        check("resolve_textures(missing tex_dir): diagnostic line is grep-able "
              "with reason=not_actually_png",
              "reason=not_actually_png" in out, out)


def test_resolve_textures_normal_input_has_no_fallback_noise():
    """負の対照(G2): 正常な入力(実PNGが揃っている)では[TEX_FALLBACK]も
    ##AVATAR_WARNING##も一切出ない(誤検知が無いことの確認)。"""
    with tempfile.TemporaryDirectory() as job_dir:
        tex_dir = os.path.join(job_dir, "textures")
        os.makedirs(tex_dir, exist_ok=True)
        write_white_png(os.path.join(tex_dir, "t00.png"))
        meta = {"slots": {
            "m00": {"orig_name": "body", "texture": "t00.png",
                    "base_color": [1.0, 1.0, 1.0, 1.0]},
        }}
        job = make_job(job_dir)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tex, slot_xf, alpha_mask = convert_noue.resolve_textures(job, meta)
        out = buf.getvalue()
        check("resolve_textures(normal input): body label IS produced",
              "body" in tex, str(tex))
        check("resolve_textures(normal input, negative control): "
              "no [TEX_FALLBACK] in stdout", "[TEX_FALLBACK]" not in out, out)
        check("resolve_textures(normal input, negative control): "
              "no ##AVATAR_WARNING## in stdout", "##AVATAR_WARNING##" not in out, out)


def test_resolve_textures_non_png_extension_is_fail_loud():
    """G3: 拡張子自体が.pngでない参照(FBX入力でjpg/tga等を参照した旧形式meta
    相当)でもfail-loudになる。"""
    with tempfile.TemporaryDirectory() as job_dir:
        tex_dir = os.path.join(job_dir, "textures")
        os.makedirs(tex_dir, exist_ok=True)
        meta = {"slots": {
            "m00": {"orig_name": "body", "texture": "t00.jpg"},
        }}
        job = make_job(job_dir)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tex, slot_xf, alpha_mask = convert_noue.resolve_textures(job, meta)
        out = buf.getvalue()
        check("resolve_textures(non-png extension): body label is NOT produced",
              "body" not in tex, str(tex))
        check("resolve_textures(non-png extension): stdout contains [TEX_FALLBACK] tag",
              "[TEX_FALLBACK]" in out, out)
        check("resolve_textures(non-png extension): stdout contains ##AVATAR_WARNING##",
              "##AVATAR_WARNING##" in out, out)
        check("resolve_textures(non-png extension): diagnostic line uses reason=not_png",
              "reason=not_png" in out, out)


def main():
    test_resolve_textures_missing_tex_dir_is_fail_loud()
    test_resolve_textures_normal_input_has_no_fallback_noise()
    test_resolve_textures_non_png_extension_is_fail_loud()
    print()
    if failures:
        print(f"=== FAIL: {len(failures)} ===")
        for f in failures:
            print(f" - {f}")
        sys.exit(1)
    print("=== ALL PASS ===")


if __name__ == "__main__":
    main()
