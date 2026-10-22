# -*- coding: utf-8 -*-
"""U16受入ゲート: vp_atlas.py(マテリアルアトラス化コア)の自動テスト。

G1(アトラス組み立て): 3マテリアル以上の合成/実データで、アトラス組み立て後の
画像サイズ・UV変換後の座標が期待通りであることを検証する。
G2(タイリング検出): 意図的にタイリングUV(0〜4の範囲)を持つ合成マテリアルで、
正しく検出されることを検証する。
G4(無退行の前提条件): distinctテクスチャが1枚以下のラベルはアトラス化を
スキップする(=texture_transformが空)ことを検証する(convert_noue.py側で
このシグナルにより既存の単一テクスチャ注入へフォールバックする)。

実行: python test_vp_atlas.py
"""
import json
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_atlas  # noqa: E402
import vp_tex    # noqa: E402

REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALICIA_META = os.path.join(REPO_DIR, "work", "alicia", "converted", "avatar_meta.json")
ALICIA_TEX_DIR = os.path.join(REPO_DIR, "work", "alicia", "textures")

failures = []


def check(label, cond, detail=""):
    """dev#739: 従来はここでfailuresへ記録するだけでassertしておらず、
    pytest経由では常に緑になっていた(main()を直接実行したときしか
    有効でなかった)。呼び出し側(50件超)は無改変のまま、ここでassertする
    ことでpytest収集時にも実際に効くようにする。"""
    if cond:
        print(f"[PASS] {label}")
    else:
        print(f"[FAIL] {label} {detail}")
        failures.append(label)
    assert cond, f"{label} {detail}".rstrip()


# ---------------------------------------------------------------- classify_material

def test_classify_material_single():
    """U50-single(2026-07-25、責任者裁定「入力アバターが何マテリアルでも
    1枚のアトラス・1マテリアルに畳む」): classify_material() は**常に0**を返す。

    旧テスト(body/parka のキーワード判定 3件)は仕様ごと廃止した。
    キーワード判定は SK 側のスロット役(t00/t01)と一致して初めて正しく、
    実測で注入対象60SK中16SKが不一致だった
    (work\\u50_equip\\out\\FINDINGS2.txt 5節)。単一化でこの不整合は
    構造的に起こりえなくなる。

    `research\\ue_exit\\dump_avatar_mesh.py` の classify_material() も
    同時に単一化してあり、**両者が同じ値を返すこと**が同期要件
    (モジュールdocstring参照)。あちらは bpy 依存で直接importできないため、
    ここでは vp_atlas 側の単一化のみを固定する。"""
    check("SINGLE_MATERIAL is True", vp_atlas.SINGLE_MATERIAL is True)
    for name in ("body", "Parka", "Alicia_body_wear", "Alicia_hair_wear",
                 "Shata_overalls", "Heon_mohu", "0mofu", "", None):
        check(f"classify_material({name!r}) -> 0 (single material)",
              vp_atlas.classify_material(name) == 0,
              f"got {vp_atlas.classify_material(name)}")


def test_to_blender_transform():
    """U50-single 実機NG(2026-07-25)の回帰テスト。

    `cell_transform()` はアトラス画像の座標系(v下向き=UEのUV)で作られるが、
    UV焼き込みは Blender の UV 座標系(v上向き)で行われ、
    `vp_meshrestore.encode_uv0()` が V_ue = 1 - V_blender と反転して書き出す。
    この差を吸収しないと**行(v)方向だけ違うセル**を引き、実機で顔が
    無地グレーになる(実測: 相関 NCC 0.7182)。

    rows=1 のとき恒等写像になる(=これまで露見しなかった理由)ことと、
    rows>1 で正しいセルに落ちることの両方を固定する。"""
    # rows=1: 恒等(従来の全アバターがこれ。無退行の根拠)
    for i in range(2):
        xf = vp_atlas.cell_transform(i, 1, 2)
        check(f"to_blender_transform: rows=1 cell{i} is identity",
              vp_atlas.to_blender_transform(xf) == xf, str(xf))
    # rows=2: Blender空間で適用した結果を UE空間へ戻すと期待セルに入る
    for i in range(4):
        xf = vp_atlas.cell_transform(i, 2, 2)
        su, sv, ou, ov = xf
        bxf = vp_atlas.to_blender_transform(xf)
        ends = []
        for v_b_src in (0.0, 1.0):
            _u, v_b = vp_atlas.apply_transform(0.0, v_b_src, bxf)
            ends.append(1.0 - v_b)          # encode_uv0 と同じ変換
        lo, hi = min(ends), max(ends)
        check(f"to_blender_transform: rows=2 cell{i} lands in expected cell v[{ov},{ov + sv}]",
              abs(lo - ov) < 1e-9 and abs(hi - (ov + sv)) < 1e-9,
              f"got v[{lo},{hi}]")


def test_to_blender_transform_rows3_plus():
    """2026-07-25の回帰テスト: **rows>=3 でも変換が正しい**ことを固定する。

    alicia の FATAL(セル包含チェックで停止)を調べたとき、当初「rows=2 まで
    しか検証していないので3行以上に別の破綻があるのでは」という見立てが
    立てられた。**その見立ては誤りである**ことを機械で固定しておく。

    代数(rows によらず成立する):
      bxf = (su, sv, ou, 1-sv-ov)
      Blender空間で焼く:  v_b' = v_b*sv + (1-sv-ov)
      encode_uv0 が反転: v_ue' = 1 - v_b' = sv*(1-v_b) + ov = sv*v_ue + ov   ∎
    sv, ov に一切の条件が付いていないので rows は何行でもよい。
    (真因は行数ではなく、UVアイランドが隣のタイルへ置かれていたこと。
     `test_face_wrap_shift` を参照)

    ここでは rows=1..5 / cols=1..5 の**全セル**について、
    「Blender空間で焼いた結果をUE空間へ戻すと、ちょうどそのセルになる」
    ことを確認する。
    """
    bad = []
    for rows in range(1, 6):
        for cols in range(1, 6):
            for i in range(rows * cols):
                xf = vp_atlas.cell_transform(i, rows, cols)
                su, sv, ou, ov = xf
                bxf = vp_atlas.to_blender_transform(xf)
                # u軸は反転しないのでそのまま
                u_lo, _ = vp_atlas.apply_transform(0.0, 0.0, bxf)
                u_hi, _ = vp_atlas.apply_transform(1.0, 0.0, bxf)
                ends = []
                for v_b_src in (0.0, 1.0):
                    _u, v_b = vp_atlas.apply_transform(0.0, v_b_src, bxf)
                    ends.append(1.0 - v_b)     # encode_uv0 と同じ変換
                v_lo, v_hi = min(ends), max(ends)
                ok = (abs(u_lo - ou) < 1e-9 and abs(u_hi - (ou + su)) < 1e-9
                      and abs(v_lo - ov) < 1e-9 and abs(v_hi - (ov + sv)) < 1e-9)
                if not ok:
                    bad.append(f"rows={rows} cols={cols} i={i} "
                               f"got u[{u_lo},{u_hi}] v[{v_lo},{v_hi}] "
                               f"want u[{ou},{ou + su}] v[{ov},{ov + sv}]")
    check("to_blender_transform: all rows/cols=1..5 cells match the expected cell in UE space",
          not bad, f"{len(bad)} NG: {bad[:5]}")

    # 3行以上のグリッドが実際に使われる枚数であることも固定する
    for n, want in ((7, (3, 3)), (8, (3, 3)), (9, (3, 3)),
                    (10, (3, 4)), (13, (4, 4)), (17, (4, 5))):
        check(f"compute_grid({n}) == {want} (rows>=3 actually occurs)",
              vp_atlas.compute_grid(n) == want, str(vp_atlas.compute_grid(n)))

    # rows=3 のグリッドで全セルがUE空間を隙間なく・重なり無く覆う
    cells = []
    for i in range(9):
        su, sv, ou, ov = vp_atlas.cell_transform(i, 3, 3)
        cells.append((ou, ov, ou + su, ov + sv))
    area = sum((c[2] - c[0]) * (c[3] - c[1]) for c in cells)
    check("cell_transform(rows=3): total area of 9 cells is 1.0", abs(area - 1.0) < 1e-9,
          str(area))

    def overlap(a, b):
        return not (a[2] <= b[0] + 1e-12 or b[2] <= a[0] + 1e-12
                    or a[3] <= b[1] + 1e-12 or b[3] <= a[1] + 1e-12)
    check("cell_transform(rows=3): no overlap between any cells",
          not any(overlap(cells[i], cells[j])
                  for i in range(9) for j in range(i + 1, 9)))


def test_face_wrap_shift():
    """2026-07-25 alicia FATAL の**真因**の回帰テスト。

    真因は行数ではなく、**UVアイランドが隣のタイル(v∈[-1,0])へ置かれた
    メッシュ**だった。単体テクスチャならWRAPアドレッシングで正しく描けるが、
    アトラスへ詰めると隣のセル(別テクスチャ)を舐めてしまう。
    実測: m00 Alicia_body は 2808面中わずか **4面**、
          m03 Alicia_eye は 1タイルではなく -0.004824 の縁のはみ出し。
    """
    # 既に [0,1] に収まっている面は**絶対に**動かさない(既存アバター無退行)
    for lo, hi in ((0.0, 1.0), (0.2, 0.8), (0.0, 0.0), (1.0, 1.0),
                   (-1e-5, 1.0 + 1e-5)):
        check(f"face_wrap_shift({lo},{hi}) == 0 (unchanged when in range)",
              vp_atlas.face_wrap_shift(lo, hi) == 0,
              str(vp_atlas.face_wrap_shift(lo, hi)))

    # 隣のタイルへ置かれた面 -> 整数シフトで [0,1] へ戻る
    cases = [(-0.9, -0.1, 1), (-1.9, -1.1, 2), (1.2, 1.8, -1), (2.1, 2.9, -2)]
    for lo, hi, want in cases:
        got = vp_atlas.face_wrap_shift(lo, hi)
        check(f"face_wrap_shift({lo},{hi}) == {want}", got == want, str(got))
        check(f"face_wrap_shift({lo},{hi}): fits in [0,1] after shift",
              -1e-9 <= lo + got and hi + got <= 1.0 + 1e-9,
              f"[{lo + got},{hi + got}]")

    # シフト量は必ず整数(WRAP等価であるための必要条件)
    for lo, hi in ((-0.443, 0.02), (-3.7, -3.2), (5.1, 5.4)):
        k = vp_atlas.face_wrap_shift(lo, hi)
        check(f"face_wrap_shift({lo},{hi}) is an integer", isinstance(k, int) and k == int(k),
              repr(k))

    # 面自体が1タイルより広い(本物のタイリング)はシフトでは救えない
    # -> シフト後もはみ出したままで、detect_tiling が従来どおり除外する
    lo, hi = 0.0, 4.0
    k = vp_atlas.face_wrap_shift(lo, hi)
    check("face_wrap_shift: a 4.0-wide face does not fit in [0,1] even after shifting",
          not (-1e-9 <= lo + k and hi + k <= 1.0 + 1e-9), f"k={k}")
    check("detect_tiling: genuine tiling is still detected even with the shifted bbox",
          vp_atlas.detect_tiling(lo + k, hi + k, 0.0, 1.0) is True)


def test_bbox_overshoot_and_clamp():
    """整数シフトで吸収しきれない縁のはみ出し(実測 alicia m03 = 0.004824)の
    扱い。**切り詰めてよい上限は `UV_CELL_CLAMP_TOL`**で、それを超えるものは
    切り詰めず vp_atlas_uvbake.py の Pass 3 でビルドを止める(ゲートは緩めない)。"""
    check("bbox_overshoot: fully in range -> 0.0",
          vp_atlas.bbox_overshoot([0.0, 1.0, 0.0, 1.0]) == 0.0)
    over = vp_atlas.bbox_overshoot([0.164348, 0.973056, -0.004824, 0.942763])
    check("bbox_overshoot: alicia m03 measured value -> 0.004824",
          abs(over - 0.004824) < 1e-9, str(over))
    check("bbox_overshoot: alicia m03 is within the clamp threshold",
          vp_atlas.UV_IN_RANGE_TOL < over <= vp_atlas.UV_CELL_CLAMP_TOL)
    check("bbox_overshoot: a full-tile offset exceeds the clamp threshold (= gate stops the build)",
          vp_atlas.bbox_overshoot([0.0, 1.0, -0.442973, 0.990797])
          > vp_atlas.UV_CELL_CLAMP_TOL)
    check("UV_CELL_CLAMP_TOL is far smaller than one tile",
          vp_atlas.UV_CELL_CLAMP_TOL < 0.1)
    check("clamp01: unchanged when in range (bit-identical)", vp_atlas.clamp01(0.3) == 0.3)
    check("clamp01(-0.004824) == 0.0", vp_atlas.clamp01(-0.004824) == 0.0)
    check("clamp01(1.004824) == 1.0", vp_atlas.clamp01(1.004824) == 1.0)


def test_wrap_shift_is_visually_equivalent():
    """整数シフトが WRAP アドレッシングと厳密に等価であること
    (=見た目が変わらないことの根拠)を固定する。

    WRAP では u と u+k(kは整数)は同じテクセルを指す。面を丸ごと整数だけ
    平行移動しても、面内の各頂点が指すテクセルは1つも変わらない。"""
    def frac(x):
        return x - math.floor(x)
    face_v = [-0.42, -0.31, -0.05]          # alicia m00 の該当面に近い値
    k = vp_atlas.face_wrap_shift(min(face_v), max(face_v))
    same = all(abs(frac(v) - frac(v + k)) < 1e-12 for v in face_v)
    check("integer face shift is equivalent to WRAP (fractional part of every vertex unchanged)", same,
          str([(frac(v), frac(v + k)) for v in face_v]))
    check("face fits in [0,1] after the integer shift",
          all(0.0 <= v + k <= 1.0 for v in face_v), str([v + k for v in face_v]))


def test_compute_grid():
    check("compute_grid(1) == (1,1)", vp_atlas.compute_grid(1) == (1, 1))
    check("compute_grid(3) == (2,2)", vp_atlas.compute_grid(3) == (2, 2),
          str(vp_atlas.compute_grid(3)))
    check("compute_grid(4) == (2,2)", vp_atlas.compute_grid(4) == (2, 2))
    check("compute_grid(5) == (2,3)", vp_atlas.compute_grid(5) == (2, 3),
          str(vp_atlas.compute_grid(5)))
    check("compute_grid(9) == (3,3)", vp_atlas.compute_grid(9) == (3, 3))
    for n in (1, 2, 3, 5, 7, 8, 12):
        rows, cols = vp_atlas.compute_grid(n)
        check(f"compute_grid({n}): rows*cols >= n", rows * cols >= n,
              f"rows={rows} cols={cols}")


# ---------------------------------------------------------------- cell_transform / apply_transform

def test_cell_transform():
    rows, cols = 2, 3
    su, sv, ou, ov = vp_atlas.cell_transform(4, rows, cols)  # r=1,c=1
    check("cell_transform(4,2,3): su==1/3", abs(su - 1 / 3) < 1e-9)
    check("cell_transform(4,2,3): sv==1/2", abs(sv - 1 / 2) < 1e-9)
    check("cell_transform(4,2,3): ou==1/3", abs(ou - 1 / 3) < 1e-9)
    check("cell_transform(4,2,3): ov==1/2", abs(ov - 1 / 2) < 1e-9)

    # index=4のセルは u in [1/3,2/3], v in [1/2,1] のはず。
    # マテリアル内uv(0.5,0.5)(中央)を変換すると、そのセルの中央に来る
    u2, v2 = vp_atlas.apply_transform(0.5, 0.5, (su, sv, ou, ov))
    check("apply_transform: within cell bounds (u)", 1 / 3 <= u2 <= 2 / 3, f"u2={u2}")
    check("apply_transform: within cell bounds (v)", 1 / 2 <= v2 <= 1.0, f"v2={v2}")
    check("apply_transform: u,v=(0,0) -> cell top-left corner",
          vp_atlas.apply_transform(0.0, 0.0, (su, sv, ou, ov)) == (ou, ov))
    check("apply_transform: u,v=(1,1) -> cell bottom-right corner",
          vp_atlas.apply_transform(1.0, 1.0, (su, sv, ou, ov)) == (ou + su, ov + sv))

    # 全セルが重なり無くタイル張りされていることを確認(index 0..5)
    covered = []
    for i in range(rows * cols):
        s = vp_atlas.cell_transform(i, rows, cols)
        covered.append((s[2], s[3], s[2] + s[0], s[3] + s[1]))  # (u0,v0,u1,v1)
    def overlap(a, b):
        return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
    any_overlap = any(overlap(covered[i], covered[j])
                       for i in range(len(covered)) for j in range(i + 1, len(covered)))
    check("cell_transform: no overlap between any cells", not any_overlap)


# ---------------------------------------------------------------- detect_tiling (G2)

def test_detect_tiling():
    check("detect_tiling: normal UV[0,1] -> False",
          vp_atlas.detect_tiling(0.0, 1.0, 0.0, 1.0) is False)
    check("detect_tiling: slight overshoot (-0.02,1.02) -> False",
          vp_atlas.detect_tiling(-0.02, 1.02, -0.01, 1.01) is False)
    check("detect_tiling: u tiling over 0..4 -> True",
          vp_atlas.detect_tiling(0.0, 4.0, 0.0, 1.0) is True)
    check("detect_tiling: both u,v tiling over 0..3 -> True",
          vp_atlas.detect_tiling(0.0, 3.0, 0.0, 3.0) is True)
    check("detect_tiling: small range but large offset (-0.6,0.5) -> True",
          vp_atlas.detect_tiling(-0.6, 0.5, 0.0, 1.0) is True)


# ---------------------------------------------------------------- build_atlas_image (G1)

def test_build_atlas_image():
    import numpy as np
    red = np.zeros((64, 64, 4), np.uint8)
    red[:, :, 0] = 255
    red[:, :, 3] = 255
    green = np.zeros((32, 32, 4), np.uint8)
    green[:, :, 1] = 255
    green[:, :, 3] = 255
    blue = np.zeros((100, 100, 4), np.uint8)
    blue[:, :, 2] = 255
    blue[:, :, 3] = 255

    canvas, rows, cols, cs = vp_atlas.build_atlas_image([red, green, blue], cell_size=32)
    check("build_atlas_image(3 images): grid==(2,2)", (rows, cols) == (2, 2))
    check("build_atlas_image(3 images): cell_size==32", cs == 32)
    check("build_atlas_image(3 images): canvas.shape==(64,64,4)",
          canvas.shape == (64, 64, 4), str(canvas.shape))

    def cell(r, c):
        return canvas[r * cs:(r + 1) * cs, c * cs:(c + 1) * cs]

    check("build_atlas_image: cell(0,0) is red", (cell(0, 0)[:, :, 0] == 255).all()
          and (cell(0, 0)[:, :, 1] == 0).all())
    check("build_atlas_image: cell(0,1) is green", (cell(0, 1)[:, :, 1] == 255).all()
          and (cell(0, 1)[:, :, 0] == 0).all())
    check("build_atlas_image: cell(1,0) is blue", (cell(1, 0)[:, :, 2] == 255).all()
          and (cell(1, 0)[:, :, 0] == 0).all())
    check("build_atlas_image: cell(1,1) is unused (black)", (cell(1, 1)[:, :, :3] == 0).all())

    # max_canvas制約: セルサイズが自動縮小されること
    imgs9 = [red] * 9
    canvas9, rows9, cols9, cs9 = vp_atlas.build_atlas_image(imgs9, cell_size=2048, max_canvas=1024)
    check("build_atlas_image(9 images, max_canvas=1024): cell_size is auto-shrunk",
          cs9 * max(rows9, cols9) <= 1024, f"cs9={cs9} rows9={rows9} cols9={cols9}")


# ---------------------------------------------------------------- plan_label / plan_avatar

def test_plan_label_no_atlas_when_single_texture():
    transforms, rows, cols = vp_atlas.plan_label(["t00.png"])
    check("plan_label(1 texture): transforms is empty (no atlas needed)", transforms == {})
    check("plan_label(1 texture): rows,cols==(1,1)", (rows, cols) == (1, 1))


def make_synthetic_meta(pairs):
    """pairs: [(slot_id, orig_name, texture_filename), ...] または
    [(slot_id, orig_name, texture_filename, base_color), ...] からavatar_meta.json風dictを作る
    (dev#505: base_colorはオプションの4要素目、既存呼び出し=3要素は無改修で動く)。"""
    slots = {}
    for pair in pairs:
        slot_id, orig_name, tex = pair[0], pair[1], pair[2]
        entry = {"orig_name": orig_name, "texture": tex}
        if len(pair) >= 4:
            entry["base_color"] = pair[3]
        slots[slot_id] = entry
    return {"slots": slots}


def test_plan_avatar_two_material_single_atlas():
    """U50-single: toto相当(m00=body/t00.png, m01=parka/t01.png)は、
    単一マテリアル化により**1枚のアトラス(2セル)**に畳まれる。
    旧仕様では2ラベルへ分かれ、各1枚なのでアトラス化されなかった。"""
    meta = make_synthetic_meta([
        ("m00", "body", "t00.png"),
        ("m01", "parka", "t01.png"),
    ])
    plan, skipped = vp_atlas.plan_avatar(meta)
    check("plan_avatar(toto-equivalent): all slots go to the body label",
          plan["body"]["texture_order"] == ["t00.png", "t01.png"],
          str(plan["body"]["texture_order"]))
    check("plan_avatar(toto-equivalent): parka label is empty", plan["parka"]["texture_order"] == [])
    check("plan_avatar(toto-equivalent): atlassed since there are 2 images",
          set(plan["body"]["texture_transform"]) == {"t00.png", "t01.png"})
    check("plan_avatar(toto-equivalent): slot_transforms covers 2 slots",
          set(vp_atlas.slot_transforms(plan)) == {"m00", "m01"})
    check("plan_avatar(toto-equivalent): skipped is empty", skipped == [])


def test_plan_avatar_multi_material_single():
    """U50-single: 4マテリアルは全部1枚のアトラス(2x2)へ畳まれる。"""
    meta = make_synthetic_meta([
        ("m00", "body", "t00.png"),
        ("m01", "eye", "t01.png"),
        ("m02", "face", "t02.png"),
        ("m03", "wear", "t03.png"),   # 旧仕様ではparka、今は同じアトラスへ
    ])
    plan, skipped = vp_atlas.plan_avatar(meta)
    check("plan_avatar(4 materials): skipped is empty", skipped == [])
    check("plan_avatar(4 materials): texture_order==[t00..t03]",
          plan["body"]["texture_order"] == ["t00.png", "t01.png", "t02.png", "t03.png"],
          str(plan["body"]["texture_order"]))
    check("plan_avatar(4 materials): grid==(2,2) (n=4)",
          (plan["body"]["rows"], plan["body"]["cols"]) == (2, 2))

    sx = vp_atlas.slot_transforms(plan)
    check("slot_transforms: covers all 4 slots", set(sx) == {"m00", "m01", "m02", "m03"}, str(sx.keys()))
    check("slot_transforms: m00 == cell(0,0) equivalent", sx["m00"] == (0.5, 0.5, 0.0, 0.0), str(sx["m00"]))
    check("slot_transforms: m01 == cell(0,1) equivalent", sx["m01"] == (0.5, 0.5, 0.5, 0.0), str(sx["m01"]))
    check("slot_transforms: m02 == cell(1,0) equivalent", sx["m02"] == (0.5, 0.5, 0.0, 0.5), str(sx["m02"]))
    check("slot_transforms: m03 == cell(1,1) equivalent", sx["m03"] == (0.5, 0.5, 0.5, 0.5), str(sx["m03"]))


def test_plan_avatar_skips_non_png():
    meta = make_synthetic_meta([
        ("m00", "body", "t00.png"),
        ("m01", "eye", "t01.jpg"),   # PNG以外 -> 除外
        ("m02", "face", "t02.png"),
    ])
    plan, skipped = vp_atlas.plan_avatar(meta)
    check("plan_avatar: non-PNG slot is recorded in skipped", skipped == [("m01", "t01.jpg")])
    check("plan_avatar: non-PNG slot is not included in texture_order",
          "t01.jpg" not in plan["body"]["texture_order"]
          and "t01.jpg" not in plan["parka"]["texture_order"])


def test_plan_avatar_without_tex_dir_ignores_content():
    """負の対照(既存呼び出しの無改修確認、dev#990): tex_dirを渡さない
    plan_avatar(meta)単体呼び出しは、拡張子が.pngなら中身を一切見ない
    (従来どおり)。実体が非PNGでもエラーにならず、通常どおり計画に含まれる。"""
    with tempfile.TemporaryDirectory() as tmp:
        fake_png = os.path.join(tmp, "t00.png")
        with open(fake_png, "wb") as f:
            f.write(b"not a real png at all")
        meta = make_synthetic_meta([("m00", "body", "t00.png")])
        plan, skipped = vp_atlas.plan_avatar(meta)
        check("plan_avatar(no tex_dir): fake-content .png is not skipped "
              "(content is not checked without tex_dir)", skipped == [])
        check("plan_avatar(no tex_dir): fake-content .png stays in texture_order",
              "t00.png" in plan["body"]["texture_order"])


def test_plan_avatar_with_tex_dir_rejects_renamed_non_png():
    """正の対照(dev#990、実報告3JMQWCNS): 拡張子だけ.pngにリネームされた
    非PNG(例: JPEGの中身)は、tex_dirを渡すとマジックナンバー検証で弾かれ、
    `<not-actually-png:...>`としてskippedへ記録され、計画から除外される。"""
    with tempfile.TemporaryDirectory() as tmp:
        fake_png = os.path.join(tmp, "t00.png")
        with open(fake_png, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0JFIF-fake-jpeg-bytes")  # JPEGマジック風、PNGではない
        real_png = os.path.join(tmp, "t01.png")
        vp_tex.encode_png(real_png, __import__("numpy").zeros((2, 2, 4), dtype="uint8"))
        meta = make_synthetic_meta([
            ("m00", "body", "t00.png"),
            ("m01", "face", "t01.png"),
        ])
        plan, skipped = vp_atlas.plan_avatar(meta, tex_dir=tmp)
        check("plan_avatar(tex_dir): fake-content .png is recorded in skipped "
              "with the not-actually-png marker",
              skipped == [("m00", "<not-actually-png:t00.png>")], str(skipped))
        check("plan_avatar(tex_dir): fake-content .png is excluded from texture_order",
              "t00.png" not in plan["body"]["texture_order"])
        check("plan_avatar(tex_dir): the genuine PNG slot is kept",
              "t01.png" in plan["body"]["texture_order"])


def test_plan_avatar_with_tex_dir_accepts_real_png():
    """負の対照(dev#990): tex_dir指定時でも、本物のPNGは従来どおり
    計画に含まれる(誤検知しない)。"""
    with tempfile.TemporaryDirectory() as tmp:
        real_png = os.path.join(tmp, "t00.png")
        vp_tex.encode_png(real_png, __import__("numpy").zeros((2, 2, 4), dtype="uint8"))
        meta = make_synthetic_meta([("m00", "body", "t00.png")])
        plan, skipped = vp_atlas.plan_avatar(meta, tex_dir=tmp)
        check("plan_avatar(tex_dir): a genuine PNG is not skipped", skipped == [])
        check("plan_avatar(tex_dir): a genuine PNG stays in texture_order",
              "t00.png" in plan["body"]["texture_order"])


# ---------------------------------------------------------------- 実データ(alicia)での検証

def test_plan_avatar_alicia_real_data():
    if not os.path.exists(ALICIA_META):
        print(f"[SKIP] test_plan_avatar_alicia_real_data: {ALICIA_META} not found")
        return
    with open(ALICIA_META, encoding="utf-8") as f:
        meta = json.load(f)
    plan, skipped = vp_atlas.plan_avatar(meta)
    check("alicia real data: skipped is empty (all 12 slots are PNG)", skipped == [])
    check("alicia real data: all 12 slots go into one atlas (6 distinct images)",
          plan["body"]["texture_order"] == ["t00.png", "t01.png", "t02.png",
                                            "t03.png", "t04.png", "t05.png"],
          str(plan["body"]["texture_order"]))
    check("alicia real data: parka label is empty", plan["parka"]["texture_order"] == [])
    check("alicia real data: slot count is 12", len(plan["body"]["slots"]) == 12,
          str(plan["body"]["slots"]))
    check("alicia real data: grid==(2,3) (n=6)",
          (plan["body"]["rows"], plan["body"]["cols"]) == (2, 3))
    sx = vp_atlas.slot_transforms(plan)
    check("alicia real data: slot_transforms covers all 12 slots (both labels atlassed)",
          len(sx) == 12, str(len(sx)))

    if os.path.isdir(ALICIA_TEX_DIR):
        paths = [os.path.join(ALICIA_TEX_DIR, fn) for fn in plan["body"]["texture_order"]]
        if all(os.path.exists(p) for p in paths):
            canvas, rows, cols, cs = vp_atlas.build_atlas_from_paths(paths)
            check("alicia real data: build_atlas_from_paths(body) has dimensions matching grid(2,3)",
                  canvas.shape == (rows * cs, cols * cs, 4), str(canvas.shape))
            check("alicia real data: build_atlas_from_paths(body) rows,cols==(2,3)",
                  (rows, cols) == (2, 3))
        else:
            print("[SKIP] some alicia real textures are missing (build_atlas_from_paths real-data check)")


# --------------------------------------------------- dev#505: 非白tintの乗算
#
# 実報告CFLSKDWM(韓国語ユーザー): アバターの瞳(虹彩)がプレビュー・変換
# 結果ともオレンジ色のはずが白目のみになる。原因: トゥーンシェーダーの
# 「白/グレーのマスクテクスチャ」×「_Colorタイント」という一般的な構造に
# 対し、本パイプラインはテクスチャが有るスロットのbase_color(Unityの
# `_Color`)を常に無視していた(texture=nullの単色マテリアルにしか使って
# いなかった)。眼球専用の特別扱いではなく、テクスチャの有無に関わらず
# base_colorを一貫して乗算する構造修正。

def test_is_white_tint():
    check("is_white_tint((1,1,1,1)) is True", vp_atlas.is_white_tint((1.0, 1.0, 1.0, 1.0)) is True)
    check("is_white_tint((1,1,1,0.3)) is True (alpha ignored)",
          vp_atlas.is_white_tint((1.0, 1.0, 1.0, 0.3)) is True)
    check("is_white_tint(just under 1/255) is True",
          vp_atlas.is_white_tint((1.0 - 0.99 / 255, 1.0, 1.0, 1.0)) is True)
    check("is_white_tint(orange) is False", vp_atlas.is_white_tint((1.0, 0.5, 0.0, 1.0)) is False)
    check("is_white_tint(black) is False", vp_atlas.is_white_tint((0.0, 0.0, 0.0, 1.0)) is False)


def test_tinted_texture_key_roundtrip():
    key = vp_atlas.tinted_texture_key("t02.png", (1.0, 0.5, 0.0, 1.0))
    check("tinted_texture_key: is_tinted_texture_key -> True",
          vp_atlas.is_tinted_texture_key(key) is True)
    check("tinted_texture_key: is_solid_color_key -> False (別種のキー)",
          vp_atlas.is_solid_color_key(key) is False)
    path, rgba = vp_atlas.parse_tinted_texture_key(key)
    check("tinted_texture_key: path round-trips", path == "t02.png", path)
    check("tinted_texture_key: rgba round-trips", rgba == (1.0, 0.5, 0.0, 1.0), str(rgba))
    # Windowsの絶対パス(コロン・バックスラッシュを含む)でも壊れないこと
    key2 = vp_atlas.tinted_texture_key(r"C:\work\wp_505\textures\t02.png", (0.2, 0.2, 0.2, 1.0))
    path2, rgba2 = vp_atlas.parse_tinted_texture_key(key2)
    check("tinted_texture_key: absolute Windows path round-trips",
          path2 == r"C:\work\wp_505\textures\t02.png", path2)
    check("is_solid_color_key/is_tinted_texture_key: plain filename is neither",
          vp_atlas.is_solid_color_key("t02.png") is False
          and vp_atlas.is_tinted_texture_key("t02.png") is False)


def test_apply_tint_white_is_noop():
    """負の対照の逆: tint=白は既存アバターの大多数(G4無退行)。
    ピクセルが一切変わらないことを固定する。"""
    import numpy as np
    rng_img = np.zeros((4, 4, 4), np.uint8)
    rng_img[:, :, 0] = [10, 80, 160, 255]
    rng_img[:, :, 1] = [255, 160, 80, 10]
    rng_img[:, :, 2] = 128
    rng_img[:, :, 3] = 200
    out = vp_atlas.apply_tint(rng_img, (1.0, 1.0, 1.0, 1.0))
    check("apply_tint(white tint): output is bit-identical to input",
          (out == rng_img).all(), f"max diff={np.abs(out.astype(int) - rng_img.astype(int)).max()}")


def test_apply_tint_matches_linear_to_srgb_reference():
    """apply_tint(ベクトル化)が、既存の信頼済みスカラー実装linear_to_srgbと
    同じ数式で動いていることをクロス検証する(魔法の数値の埋め込みを避ける)。"""
    import numpy as np
    white = np.full((2, 2, 4), 255, np.uint8)
    tint = (1.0, 0.5, 0.0, 1.0)
    out = vp_atlas.apply_tint(white, tint)
    # 白(sRGB 1.0)をtintで乗算 == tintそのものをlinear_to_srgbで符号化した値
    expect_r = round(vp_atlas.linear_to_srgb(1.0) * 255)
    expect_g = round(vp_atlas.linear_to_srgb(0.5) * 255)
    expect_b = round(vp_atlas.linear_to_srgb(0.0) * 255)
    got = out[0, 0]
    check("apply_tint(white x orange tint): R matches linear_to_srgb reference",
          int(got[0]) == expect_r, f"got={got[0]} want={expect_r}")
    check("apply_tint(white x orange tint): G matches linear_to_srgb reference",
          abs(int(got[1]) - expect_g) <= 1, f"got={got[1]} want={expect_g}")
    check("apply_tint(white x orange tint): B matches linear_to_srgb reference",
          int(got[2]) == expect_b, f"got={got[2]} want={expect_b}")
    check("apply_tint: this is genuinely not white/grey (the CFLSKDWM bug would leave it white)",
          not (got[0] == got[1] == got[2]), str(got))


def test_apply_tint_alpha_is_linear_multiply():
    import numpy as np
    img = np.zeros((1, 1, 4), np.uint8)
    img[0, 0] = (255, 255, 255, 200)
    out = vp_atlas.apply_tint(img, (1.0, 1.0, 1.0, 0.5))
    check("apply_tint: alpha is a direct linear multiply (200*0.5=100)",
          abs(int(out[0, 0, 3]) - 100) <= 1, str(out[0, 0]))


def test_plan_avatar_white_tint_unchanged():
    """G4無退行: base_colorが実質白なら、従来どおりプレーンなファイル名の
    ままtexture_orderへ入る(tinted_texture_keyへ包まれない)。"""
    meta = make_synthetic_meta([
        ("m00", "eye", "t00.png", [1.0, 1.0, 1.0, 1.0]),
    ])
    plan, skipped = vp_atlas.plan_avatar(meta)
    check("plan_avatar(white tint): texture_order stays a plain filename",
          plan["body"]["texture_order"] == ["t00.png"], str(plan["body"]["texture_order"]))
    check("plan_avatar(white tint): skipped is empty", skipped == [])


def test_plan_avatar_no_base_color_unchanged():
    """負の対照: base_colorフィールド自体が無い(旧形式meta)場合も従来どおり
    プレーンなファイル名のまま(クラッシュしない)。"""
    meta = make_synthetic_meta([("m00", "eye", "t00.png")])
    plan, skipped = vp_atlas.plan_avatar(meta)
    check("plan_avatar(no base_color): texture_order stays a plain filename",
          plan["body"]["texture_order"] == ["t00.png"], str(plan["body"]["texture_order"]))


def test_plan_avatar_non_white_tint_wraps_key():
    """本題(CFLSKDWM再現の核): テクスチャが有るスロットでも非白tintは
    tinted_texture_keyへ包まれ、プランに正規に組み込まれる。"""
    meta = make_synthetic_meta([
        ("m03", "RadDollV3_Eye", "t02.png", [1.0, 0.5, 0.0, 1.0]),
    ])
    plan, skipped = vp_atlas.plan_avatar(meta)
    check("plan_avatar(orange tint): skipped is empty", skipped == [])
    check("plan_avatar(orange tint): texture_order has exactly 1 entry",
          len(plan["body"]["texture_order"]) == 1, str(plan["body"]["texture_order"]))
    only = plan["body"]["texture_order"][0]
    check("plan_avatar(orange tint): entry is a tinted_texture_key",
          vp_atlas.is_tinted_texture_key(only) is True, only)
    path, rgba = vp_atlas.parse_tinted_texture_key(only)
    check("plan_avatar(orange tint): embedded path is the original filename",
          path == "t02.png", path)
    check("plan_avatar(orange tint): embedded tint matches base_color",
          rgba == (1.0, 0.5, 0.0, 1.0), str(rgba))
    check("plan_avatar(orange tint): slot_texture[m03] is the same key",
          plan["body"]["slot_texture"]["m03"] == only)


def test_plan_avatar_same_texture_different_tint_not_deduped():
    """第2の退行に対する回帰テスト: 同じ白マスクテクスチャを異なる色へ
    タイントした2マテリアルが、ファイル名だけの同一視で1セルへ丸め込まれ
    片方の色が消える、という事態を防ぐ。"""
    meta = make_synthetic_meta([
        ("m00", "eye_l", "mask.png", [1.0, 0.0, 0.0, 1.0]),   # 赤
        ("m01", "eye_r", "mask.png", [0.0, 0.0, 1.0, 1.0]),   # 青
    ])
    plan, skipped = vp_atlas.plan_avatar(meta)
    order = plan["body"]["texture_order"]
    check("plan_avatar(same file, different tint): 2 distinct entries (not deduped)",
          len(order) == 2, str(order))
    check("plan_avatar(same file, different tint): both entries are tinted keys",
          all(vp_atlas.is_tinted_texture_key(o) for o in order), str(order))
    check("plan_avatar(same file, different tint): m00 != m01 slot_texture",
          plan["body"]["slot_texture"]["m00"] != plan["body"]["slot_texture"]["m01"])


def test_plan_avatar_same_texture_same_tint_deduped():
    """同一ファイル+同一tintは、従来どおり1セルへ共有される(無駄なく詰める、
    solid_color_keyの既存挙動と対称)。"""
    meta = make_synthetic_meta([
        ("m00", "eye_l", "mask.png", [1.0, 0.5, 0.0, 1.0]),
        ("m01", "eye_r", "mask.png", [1.0, 0.5, 0.0, 1.0]),
    ])
    plan, skipped = vp_atlas.plan_avatar(meta)
    order = plan["body"]["texture_order"]
    check("plan_avatar(same file, same tint): deduped to 1 entry", len(order) == 1, str(order))
    check("plan_avatar(same file, same tint): m00 == m01 slot_texture",
          plan["body"]["slot_texture"]["m00"] == plan["body"]["slot_texture"]["m01"])


def test_plan_avatar_malformed_base_color_falls_back_gracefully():
    """負の対照: base_colorが壊れた形(数値でない・要素不足)でも、
    タイント適用をあきらめてプレーンなファイル名へ寛容にフォールバックする
    (AvatarMetaErrorは送出しない。base_colorはtexture有りスロットでは
    必須情報ではないため)。"""
    for bad in ([1.0, 1.0], ["red", "green", "blue", 1.0],
                {"r": 1, "g": 2, "b": 3, "a": 4}, None):
        meta = make_synthetic_meta([("m00", "eye", "t00.png", bad)]) if bad is not None \
            else make_synthetic_meta([("m00", "eye", "t00.png")])
        plan, skipped = vp_atlas.plan_avatar(meta)
        check(f"plan_avatar(malformed base_color={bad!r}): no crash, plain filename kept",
              plan["body"]["texture_order"] == ["t00.png"], str(plan["body"]["texture_order"]))


def test_build_atlas_from_paths_applies_tint():
    """統合試験: tinted_texture_key を含む paths から build_atlas_from_paths が
    実際にタイント済みピクセルを合成すること(=眼球が白ではなくオレンジに
    なることをコード全体の経路で確認する、CFLSKDWMの直接回帰テスト)。"""
    import numpy as np
    with tempfile.TemporaryDirectory() as tmp:
        white_path = os.path.join(tmp, "mask.png")
        white_img = np.full((16, 16, 4), 255, np.uint8)
        vp_tex.encode_png(white_path, white_img)

        red_path = os.path.join(tmp, "solid_red.png")
        red_img = np.zeros((16, 16, 4), np.uint8)
        red_img[:, :, 0] = 255
        red_img[:, :, 3] = 255
        vp_tex.encode_png(red_path, red_img)

        paths = [
            red_path,
            vp_atlas.tinted_texture_key(white_path, (1.0, 0.5, 0.0, 1.0)),
        ]
        canvas, rows, cols, cs = vp_atlas.build_atlas_from_paths(paths, cell_size=16)
        check("build_atlas_from_paths(tinted): grid==(1,2)", (rows, cols) == (1, 2))

        def cell(r, c):
            return canvas[r * cs:(r + 1) * cs, c * cs:(c + 1) * cs]

        c0, c1 = cell(0, 0), cell(0, 1)
        check("build_atlas_from_paths(tinted): cell0 is the untouched red texture",
              (c0[:, :, 0] == 255).all() and (c0[:, :, 1] == 0).all())
        check("build_atlas_from_paths(tinted): cell1 is NOT white (tint was applied)",
              not (c1[:, :, 0] == 255).all() or not (c1[:, :, 1] == 255).all()
              or not (c1[:, :, 2] == 255).all())
        check("build_atlas_from_paths(tinted): cell1 red channel stays ~white (tint R=1.0)",
              int(c1[0, 0, 0]) == 255, str(c1[0, 0]))
        check("build_atlas_from_paths(tinted): cell1 blue channel is driven to 0 (tint B=0.0)",
              int(c1[0, 0, 2]) == 0, str(c1[0, 0]))
        check("build_atlas_from_paths(tinted): cell1 green channel is between (tint G=0.5, not clipped)",
              0 < int(c1[0, 0, 1]) < 255, str(c1[0, 0]))


def main():
    test_classify_material_single()
    test_to_blender_transform()
    test_to_blender_transform_rows3_plus()
    test_face_wrap_shift()
    test_bbox_overshoot_and_clamp()
    test_wrap_shift_is_visually_equivalent()
    test_compute_grid()
    test_cell_transform()
    test_detect_tiling()
    test_build_atlas_image()
    test_plan_label_no_atlas_when_single_texture()
    test_plan_avatar_two_material_single_atlas()
    test_plan_avatar_multi_material_single()
    test_plan_avatar_skips_non_png()
    test_plan_avatar_without_tex_dir_ignores_content()
    test_plan_avatar_with_tex_dir_rejects_renamed_non_png()
    test_plan_avatar_with_tex_dir_accepts_real_png()
    test_plan_avatar_alicia_real_data()
    test_is_white_tint()
    test_tinted_texture_key_roundtrip()
    test_apply_tint_white_is_noop()
    test_apply_tint_matches_linear_to_srgb_reference()
    test_apply_tint_alpha_is_linear_multiply()
    test_plan_avatar_white_tint_unchanged()
    test_plan_avatar_no_base_color_unchanged()
    test_plan_avatar_non_white_tint_wraps_key()
    test_plan_avatar_same_texture_different_tint_not_deduped()
    test_plan_avatar_same_texture_same_tint_deduped()
    test_plan_avatar_malformed_base_color_falls_back_gracefully()
    test_build_atlas_from_paths_applies_tint()

    print()
    if failures:
        print(f"=== FAIL: {len(failures)} ===")
        for f in failures:
            print(f" - {f}")
        sys.exit(1)
    print("=== ALL PASS ===")


if __name__ == "__main__":
    main()
