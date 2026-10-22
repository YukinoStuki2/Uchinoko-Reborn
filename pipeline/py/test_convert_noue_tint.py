# -*- coding: utf-8 -*-
"""dev#505回帰テスト: convert_noue.py: resolve_textures() の統合試験。

実報告CFLSKDWM(瞳/虹彩が白飛びする)の直接回帰。vp_atlas.py側の単体試験
(test_vp_atlas.py)は plan_avatar/build_atlas_from_paths を個別に検証するが、
本ファイルは実際にpakへ注入されるPNGを組み立てる convert_noue.resolve_textures()
自体(dev#505で新設した2分岐: 単一tintedテクスチャの直接ベイク/
アトラス経路でのtinted_texture_key解決)を、bpy無しで(convert_noue.pyは
bpy非依存)エンドツーエンドに検証する。

実行: python test_convert_noue_tint.py または pytest経由
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert_noue  # noqa: E402
import vp_atlas       # noqa: E402
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


def test_resolve_textures_single_tinted_texture_is_baked():
    """CFLSKDWMの核: このラベルの唯一のマテリアルが「白マスク+非白tint」
    (例: 瞳)のとき、resolve_texturesが実際にタイント済みPNGを作ること。"""
    with tempfile.TemporaryDirectory() as job_dir:
        tex_dir = os.path.join(job_dir, "textures")
        os.makedirs(tex_dir, exist_ok=True)
        write_white_png(os.path.join(tex_dir, "t02.png"))
        meta = {"slots": {
            "m03": {"orig_name": "RadDollV3_Eye", "texture": "t02.png",
                    "base_color": [1.0, 0.5, 0.0, 1.0]},
        }}
        job = make_job(job_dir)
        tex, slot_xf, alpha_mask = convert_noue.resolve_textures(job, meta)
        check("resolve_textures(single tinted): body label produced",
              "body" in tex, str(tex))
        out_png = tex["body"]
        check("resolve_textures(single tinted): output file exists",
              os.path.exists(out_png), out_png)
        _, _, pixels = vp_tex.decode_png(out_png)
        px = pixels[0, 0]
        check("resolve_textures(single tinted): output is NOT white "
              "(the CFLSKDWM bug would leave R=G=B=255)",
              not (px[0] == 255 and px[1] == 255 and px[2] == 255), str(px))
        check("resolve_textures(single tinted): red channel stays ~white (tint R=1.0)",
              int(px[0]) == 255, str(px))
        check("resolve_textures(single tinted): blue channel is driven to 0 (tint B=0.0)",
              int(px[2]) == 0, str(px))
        check("resolve_textures(single tinted): slot_xf is empty (no atlas needed for 1 texture)",
              slot_xf == {}, str(slot_xf))


def test_resolve_textures_multi_texture_atlas_applies_tint():
    """複数distinctテクスチャ(アトラス経路)でも、tinted_texture_keyが
    tex_dir解決を経てbuild_atlas_from_pathsまで正しく橋渡しされること。"""
    with tempfile.TemporaryDirectory() as job_dir:
        tex_dir = os.path.join(job_dir, "textures")
        os.makedirs(tex_dir, exist_ok=True)
        write_white_png(os.path.join(tex_dir, "t00.png"))  # body: 白のまま(tint無し)
        write_white_png(os.path.join(tex_dir, "t02.png"))  # eye: 白 x オレンジtint
        meta = {"slots": {
            "m00": {"orig_name": "RadDollV3_Body", "texture": "t00.png",
                    "base_color": [1.0, 1.0, 1.0, 1.0]},
            "m03": {"orig_name": "RadDollV3_Eye", "texture": "t02.png",
                    "base_color": [1.0, 0.5, 0.0, 1.0]},
        }}
        job = make_job(job_dir)
        tex, slot_xf, alpha_mask = convert_noue.resolve_textures(job, meta)
        check("resolve_textures(multi): body label produced", "body" in tex, str(tex))
        check("resolve_textures(multi): atlas needed (2 distinct entries)",
              set(slot_xf) == {"m00", "m03"}, str(slot_xf))
        _, _, canvas = vp_tex.decode_png(tex["body"])
        xf_m00 = slot_xf["m00"]
        xf_m03 = slot_xf["m03"]
        check("resolve_textures(multi): m00/m03 land in different cells",
              xf_m00 != xf_m03, f"{xf_m00} vs {xf_m03}")

        def sample_cell(xf):
            su, sv, ou, ov = xf
            h, w = canvas.shape[:2]
            x = int((ou + su / 2) * w)
            y = int((ov + sv / 2) * h)
            return canvas[min(y, h - 1), min(x, w - 1)]

        px_body = sample_cell(xf_m00)
        px_eye = sample_cell(xf_m03)
        check("resolve_textures(multi): untinted body cell stays white",
              px_body[0] == 255 and px_body[1] == 255 and px_body[2] == 255, str(px_body))
        check("resolve_textures(multi): tinted eye cell is NOT white",
              not (px_eye[0] == 255 and px_eye[1] == 255 and px_eye[2] == 255), str(px_eye))
        check("resolve_textures(multi): tinted eye cell blue channel driven to 0",
              int(px_eye[2]) == 0, str(px_eye))


def test_resolve_textures_white_tint_regression_control():
    """負の対照(G4無退行): 全スロットがtint=白(実質全既存アバター)なら、
    resolve_texturesの出力はtint機能を追加する前と同じ経路(プレーンな
    ファイル名でのアトラス化)を通り、ピクセルはソースそのまま。"""
    with tempfile.TemporaryDirectory() as job_dir:
        import numpy as np
        tex_dir = os.path.join(job_dir, "textures")
        os.makedirs(tex_dir, exist_ok=True)
        red = np.zeros((16, 16, 4), dtype="uint8")
        red[:, :, 0] = 255
        red[:, :, 3] = 255
        vp_tex.encode_png(os.path.join(tex_dir, "t00.png"), red)
        blue = np.zeros((16, 16, 4), dtype="uint8")
        blue[:, :, 2] = 255
        blue[:, :, 3] = 255
        vp_tex.encode_png(os.path.join(tex_dir, "t01.png"), blue)
        meta = {"slots": {
            "m00": {"orig_name": "body", "texture": "t00.png",
                    "base_color": [1.0, 1.0, 1.0, 1.0]},
            "m01": {"orig_name": "parka", "texture": "t01.png"},  # base_color無し(旧形式)も混在
        }}
        job = make_job(job_dir)
        tex, slot_xf, alpha_mask = convert_noue.resolve_textures(job, meta)
        _, _, canvas = vp_tex.decode_png(tex["body"])

        def sample_cell(xf):
            su, sv, ou, ov = xf
            h, w = canvas.shape[:2]
            x = int((ou + su / 2) * w)
            y = int((ov + sv / 2) * h)
            return canvas[min(y, h - 1), min(x, w - 1)]

        px0 = sample_cell(slot_xf["m00"])
        px1 = sample_cell(slot_xf["m01"])
        check("resolve_textures(white tint control): m00 stays pure red",
              (int(px0[0]), int(px0[1]), int(px0[2])) == (255, 0, 0), str(px0))
        check("resolve_textures(white tint control): m01 stays pure blue",
              (int(px1[0]), int(px1[1]), int(px1[2])) == (0, 0, 255), str(px1))


def main():
    test_resolve_textures_single_tinted_texture_is_baked()
    test_resolve_textures_multi_texture_atlas_applies_tint()
    test_resolve_textures_white_tint_regression_control()
    print()
    if failures:
        print(f"=== FAIL: {len(failures)} ===")
        for f in failures:
            print(f" - {f}")
        sys.exit(1)
    print("=== ALL PASS ===")


if __name__ == "__main__":
    main()
