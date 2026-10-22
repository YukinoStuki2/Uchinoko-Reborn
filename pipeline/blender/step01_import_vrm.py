# -*- coding: utf-8 -*-
"""Step01: VRMを読み込み、移植用に正規化する。

実行: blender --background --factory-startup --python-exit-code 1 --python step01_import_vrm.py -- <job.json>
出力: <job>/converted/step01_clean.blend
      <job>/textures/*.png(ベースカラーテクスチャ)
      <job>/converted/avatar_meta.json(Humanoidマップ・スロット表・警告・
        非スキンメッシュの元の親ボーン名)

やること:
  1. VRMアドオンでインポート(0.x / 1.0 両対応)
  2. アーマチュア変換Apply、シェイプキー全削除(表情非対応)
  3. ボーンコンストレイント全削除(SpringBone/Node Constraintの剛体化)
  4. Humanoid定義から {パルボーン: 実ボーン名} を確定
  5. マテリアルをASCII安全名(m00..)に改名し、ベースカラーテクスチャをPNG抽出
"""

import contextlib
import json
import os
import re
import shutil
import struct
import sys
import zlib

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "py"))
import vp_bl
import vp_dup_armature as vp_dup  # dev#1174: 重複armature検出、bpy非依存
import vp_flatten_pin  # dev#1246: 平坦化FBXのroot_matピン留め判定、bpy非依存
import vp_mesh_drop  # dev#1168前半: ラボ機能「メッシュ削除」の照合、bpy非依存
import vp_modnorm
import vp_reattach_armature  # dev#1318: 破棄Armature束縛メッシュの付け替え、bpy非依存
import vp_springbone_extract  # dev#1508 W1b: VRM SpringBone→springbones.jsonスキーマ変換、bpy非依存
import vp_tex
from vp_bl import core
import sway_allocator  # dev#1508 受入ゲート(sway_source_snapshot): 判定ロジックの正本
import sway_source_bones  # dev#1508 受入ゲート: 対象骨集合の独立導出
import sway_chain_defaults  # dev#1592: job["sway_chain_overrides"]のenabled解決(step02と共有)

TAG = "step01"


def _matte_rgb():
    """U50診断用: D2P_MATTE_COLOR環境変数('R,G,B'各0-255)をタプルで返す。
    未設定・空・不正値ならNone(呼び出し側はNoneなら完全no-op)。ハードコード
    禁止(現場で色を選び直せるようにするための要件)。"""
    raw = os.environ.get("D2P_MATTE_COLOR")
    if not raw:
        return None
    parts = raw.split(",")
    if len(parts) != 3:
        print(f"[{TAG}][WARN] invalid D2P_MATTE_COLOR (specify as R,G,B): {raw!r} — ignoring")
        return None
    try:
        r, g, b = (max(0, min(255, int(p.strip()))) for p in parts)
    except ValueError:
        print(f"[{TAG}][WARN] invalid D2P_MATTE_COLOR (not integers): {raw!r} — ignoring")
        return None
    return (r, g, b)


def _png_size(path):
    """PNGファイルのIHDRチャンクからwidth/heightを読む(PNG仕様上IHDRは常に
    signature直後の最初のチャンクなので固定オフセットで安全に読める)。
    PNGでない/壊れている場合はNone。"""
    with open(path, "rb") as f:
        head = f.read(33)
    if len(head) < 33 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def apply_matte_if_enabled(path):
    """U50診断用: D2P_MATTE_COLOR設定時のみ、既にtex_dirへ書き出し済みの
    PNGテクスチャ(path)を、同じ解像度・RGBA・アルファ255固定の単色で上書き
    する。実機SSで「この色が写っている画素=キャラ領域」と直接判定するための
    マット注入(推定ではなく色注入でシルエットを得る)。

    未設定(既定)なら os.environ.get が None を返した時点で即returnし、
    ファイルI/Oを一切行わない完全no-op。対象はPNGのみ(拡張子が.png以外の
    コピーは対象外・警告のみで元ファイルは無改変のまま残す)。"""
    color = _matte_rgb()
    if color is None:
        return
    if not path.lower().endswith(".png"):
        print(f"[{TAG}][WARN] matte only supports PNG, skipping: {path}")
        return
    size = _png_size(path)
    if size is None:
        print(f"[{TAG}][WARN] failed to parse PNG header, skipping matte: {path}")
        return
    w, h = size
    r, g, b = color
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # bitdepth8, colortype6=RGBA
    row = bytes([0]) + bytes((r, g, b, 255)) * w  # フィルタ0(None) + 画素データ
    raw = row * h
    idat = zlib.compress(raw, 6)
    png = sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    print(f"[{TAG}] D2P_MATTE_COLOR applied: overwrote {path} with solid RGBA({r},{g},{b},255) "
          f"({w}x{h})")


def import_vrm(job, warnings):
    # VRMのライセンス確認ダイアログはヘッドレスで出せない。ツール側(GUI/CLI)で
    # 「アバターの規約を確認した」チェックを必須にした上で、アドオン公式の
    # 自動確認モードで通す(規約確認の責任はユーザーにある旨をUI/READMEに明記)
    os.environ["BLENDER_VRM_AUTOMATIC_LICENSE_CONFIRMATION"] = "true"
    before = set(bpy.data.objects)
    bpy.ops.import_scene.vrm(filepath=job["vrm_path"])
    new_objs = set(bpy.data.objects) - before
    arms = [o for o in new_objs if o.type == "ARMATURE"]
    if not arms:
        core.die(TAG, "VRM import produced no Armature")
    if len(arms) == 1:
        return arms[0]
    # dev#1174: VRM importが複数Armatureオブジェクトを生む変則ケース(通常の
    # VRM/glTFは単一skinのため稀だが、import_fbx_avatar()側で既に確立済みの
    # 基準(ボーン数最大を主骨格とみなす)に合わせ、無警告での先頭採用
    # (旧: next(...))をやめて明示的に選び、ユーザーへ案内する
    arm = max(arms, key=lambda a: len(a.data.bones))
    warnings.append(
        f"detected multiple Armatures. Using {arm.name} (others discarded). "
        f"{vp_dup.GUIDANCE_TEXT}")
    # dev#1318(実報告35TX8ERY): 破棄されるArmatureに親子付け/Armature
    # モディファイアで束縛されたメッシュ(=衣装等が別リグを持つ場合の実体)
    # は、この直後に呼ばれるcleanup_objects()の「obj.parent is arm または
    # 対象armへのArmatureモディファイアを持つ」判定から漏れ、無警告のまま
    # 削除されていた。VRMアドオンの大量の「Duplicated VRM0 bone」警告
    # (=2本のArmatureが同名ボーンを持つ複製骨格)が示す通り、頂点グループ名
    # (ボーン名)は選ばれたarmでもそのまま通用するため、親子付けと
    # Armatureモディファイアの対象を選ばれたarmへ付け替えて保護する。
    others = [a for a in arms if a is not arm]
    vrm_meshes = [o for o in new_objs if o.type == "MESH"]
    reattached = vp_reattach_armature.reattach_meshes_from_discarded_armatures(
        vrm_meshes, arm, others, tag=TAG)
    if reattached:
        warnings.append(
            "reattached mesh(es) that were bound to a discarded duplicate "
            f"Armature onto the main skeleton (bone names matched): {reattached}")
    return arm


def _safe_exists(path):
    """os.path.existsの完全非例外版。Windowsではパス長超過・不正な文字などで
    OSError/ValueErrorが飛びうるため、判定不能は一律「無い」とみなす
    (存在判定でクラッシュしてはならない)。"""
    try:
        return os.path.exists(path)
    except (OSError, ValueError):
        return False


def _is_within(path, base):
    """pathがbaseの内側(base自身は含まない)かどうか。両者とも正規化済み前提。"""
    p = os.path.normcase(path)
    b = os.path.normcase(base)
    return p.startswith(b + os.sep)


def _immediate_subdirs(base):
    """base直下のサブディレクトリ(ソート順)。列挙不能なら空リスト。"""
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    out = []
    for n in names:
        p = os.path.join(base, n)
        try:
            if os.path.isdir(p):
                out.append(p)
        except OSError:
            continue
    return out


def fbx_texture_candidates(recorded_path, base_dir):
    """FBXに記録されたテクスチャ参照を解決するための候補パスを、
    **明示的に与えたルート(base_dir)基準だけ**で、正規化済みで組み立てる。

    dev#369の構造的原因: BlenderのFBXインポータ(io_scene_fbx.import_fbx.
    blen_read_texture_image)は、FBXが持つ `RelativeFilename` を
    `os.path.join(basedir, filepath)` で**今そのFBXが置かれているフォルダ**
    に対して連結する。ところがその相対パスは、FBXを書き出した側(Unityの
    FBX Exporter)が**別の基準ディレクトリ**(ユーザーのUnityプロジェクト、
    例: %LOCALAPPDATA%\\VRChatProjects\\...)で記録したものである。
    D2Pは輸出したFBXを `work\\<名前>_export\\` へ置くため、基準が食い違い、
    `work\\X_export\\..\\..\\..\\..\\..\\..\\..\\..\\AppData\\Local\\...` という
    「基準の違う相対パスを別の基準へ連結した」だけの無意味なパスが生まれる。

    そのパスは正規化されないままBlenderの `bpy.path.resolve_ncase()` に渡り、
    `_ncase_path_found()` の `os.listdir(dirpath)` が `PermissionError` しか
    捕捉していないため、それ以外のOSError(実報告では `..` 8段ぶんの冗長な
    24文字がWin32のパス長上限を越えて出た `FileNotFoundError [WinError 3]`)が
    そのまま外へ抜け、**変換全体が停止**していた。

    したがって修正は「`..` の段数を数え直す」ことではない。
      * 候補は必ず **正規化してから** OSへ渡す(冗長な `..` を一切通さない)
      * 連結の基準は **明示的に渡されたルートのみ**とする
      * base_dirの外へ逃げる記録パスは「別の基準で書かれたもの」とみなして
        後回しにし、まずはbase_dir配下(D2P輸出物の実体がある場所)を見る

    返り値: 候補パスのリスト(重複除去済み・すべて正規化済み・優先度順)。
    """
    base = os.path.normpath(os.path.abspath(base_dir))
    raw = (recorded_path or "")
    raw = raw.replace("/", os.sep).replace("\\", os.sep)
    if not raw:
        return []
    if os.path.isabs(raw):
        norm = os.path.normpath(raw)
    else:
        norm = os.path.normpath(os.path.join(base, raw))
    name = os.path.basename(norm)
    inside = _is_within(norm, base)

    cands = []

    def add(p):
        p = os.path.normpath(p)
        if p not in cands:
            cands.append(p)

    # 1) base_dirの内側に収まる参照は、記録されたパスをそのまま採用する
    #    (D2P輸出物がサブフォルダを持つ通常ケース。従来の挙動を保つ)
    if inside:
        add(norm)
    # 2) base_dir直下のファイル名一致(Unity輸出はテクスチャをFBXと同じ
    #    フォルダへ書き出すため、実運用ではここで当たる)
    if name:
        add(os.path.join(base, name))
        # 3) base_dir直下のサブフォルダのファイル名一致
        for sub in _immediate_subdirs(base):
            add(os.path.join(sub, name))
    # 4) base_dirの外を指す記録パス(=別の基準で書かれたもの)は最後の手段。
    #    正規化済みなので冗長な `..` はOSへ渡らない
    if not inside:
        add(norm)
    return cands


def resolve_fbx_texture(recorded_path, base_dir):
    """fbx_texture_candidates()の候補を順に見て、最初に実在したものを返す。

    返り値: (解決したパス or None, 試した候補の全リスト)。
    解決できなかった場合に候補リストを必ず返すのは、失敗時に
    「どの基準で・どこを探したか」をログへ残せるようにするため
    (自動探索は必ず探索先と判定をログに残す、というプロジェクト規約)。
    """
    cands = fbx_texture_candidates(recorded_path, base_dir)
    for c in cands:
        if _safe_exists(c):
            return c, cands
    return None, cands


@contextlib.contextmanager
def rooted_fbx_texture_resolution(base_dir):
    """FBXインポートの間だけ、Blenderの外部テクスチャ解決を
    「明示ルート基準・正規化済み・非致命」へ差し替えるコンテキストマネージャ。

    io_scene_fbx は `from bpy_extras import image_utils` してから
    `image_utils.load_image(...)` を呼ぶ(=呼び出し時にモジュール属性を引く)
    ので、ここで属性を差し替えれば確実に経路を押さえられる。差し替えるのは
    引数の組み立てだけで、実際の画像ロード・プレースホルダ生成はBlender本体の
    load_image()にそのまま任せる(挙動の再実装をしない)。
    """
    try:
        from bpy_extras import image_utils
    except ImportError:  # Blender外(単体テスト等)では何もしない
        yield
        return
    original = image_utils.load_image

    def rooted_load_image(imagepath, dirname="", **kwargs):
        root = dirname or base_dir
        recorded = str(imagepath or "")
        resolved, cands = resolve_fbx_texture(recorded, root)
        if resolved is not None:
            return original(resolved, dirname=root, **kwargs)
        # 解決できなかった: どの基準で何を試したかを必ず残す。
        # ここで停止はしない(FBX入力のテクスチャはUnity輸出の
        # material_map.jsonが正本であり、Blender側の解決は補助にすぎない)。
        print(f"[{TAG}][WARN] FBX texture reference could not be resolved: {recorded}")
        print(f"[{TAG}]   base used: {root}")
        for c in cands:
            print(f"[{TAG}]   tried: {c}")
        # ファイル名だけをBlenderへ渡す(place_holder=Trueなので
        # プレースホルダ画像が返る。二度と冗長な `..` を渡さない)
        fallback = os.path.basename(recorded.replace("/", os.sep).replace("\\", os.sep))
        return original(fallback or recorded, dirname=root, **kwargs)

    image_utils.load_image = rooted_load_image
    try:
        yield
    finally:
        image_utils.load_image = original


# dev#39: 同梱Blenderの `io_scene_fbx.import_fbx` は、デフォーマ連鎖
# (bone→cluster→skin→mesh)を辿る際に `fbx_connection_map.get(x)` を
# デフォルト引数無しで呼ぶ箇所が2つある(cluster_uuid / mesh_uuid)。FBX内で
# 該当ノードの接続が1本でも欠けていると `.get()` が None を返し、
# `for ... in None` が `TypeError: 'NoneType' object is not iterable` に
# なって変換全体が停止する(Blender 4.3.2/5.0とも本家未修正)。
# 同ファイル内の他の同種呼び出し(3462/3572/3611/3704/3728/3765/3783行等、
# 8箇所以上)は既に `.get(x, ())` というデフォルト空タプルの慣習になっており、
# この2箇所だけが抜けている「欠落パターンのクラスバグ」。周辺コードの慣習に
# 揃えるだけの、意味的に正しい修正(値を寄せて合わせる場当たり修正ではない)。
#
# 実報告: 裏オプションFBX直入力(TF99Y95F)に加え、**公式prefab経路**
# (VB8DV9PN, v2.2.8, Unity輸出FBX)でも同一例外が発生しており、公式サポート
# 経路が変換不能になる不具合として扱う(issue #39)。
#
# 同梱BlenderはGit管理外(pipeline\cli\ensure_blender.ps1が都度ダウンロード
# する共有資源、全worktree/全並行レーンで共有)なので、ファイルを恒久的に
# 書き換えて同梱する方式は取れない。起動のたびに冪等パッチを当てる
# (差分が無ければ何もしない。本家側で先に直った場合も自動的に無害化する)。
_FBX_IMPORTER_DEFORMER_NONE_GUARD_FIXES = (
    ("for skin_uuid, skin_link in fbx_connection_map.get(cluster_uuid):",
     "for skin_uuid, skin_link in fbx_connection_map.get(cluster_uuid, ()):"),
    ("for object_uuid, object_link in fbx_connection_map.get(mesh_uuid):",
     "for object_uuid, object_link in fbx_connection_map.get(mesh_uuid, ()):"),
)


def _fbx_importer_deformer_none_guard_fixes(src):
    """テキストレベルの純粋パッチ(I/O無し、bpy不要)。冪等——既にパッチ済み
    (または本家側で修正済み)のソースを渡しても何も変えない。
    戻り値: (patched_src, changed: bool)"""
    changed = False
    for old, new in _FBX_IMPORTER_DEFORMER_NONE_GUARD_FIXES:
        if old in src:
            src = src.replace(old, new)
            changed = True
    return src, changed


def patch_bundled_fbx_importer_deformer_none_guard():
    """dev#39: 同梱Blenderの io_scene_fbx.import_fbx モジュールのソース
    ファイルを検査し、上記の欠落パターンを検出したら書き換える。

    `io_scene_fbx/__init__.py` の `ImportFBX.execute()` は
    `from . import import_fbx` を execute() 呼び出しのたびに行う遅延import
    のため、Blenderプロセス起動〜`bpy.ops.import_scene.fbx()` 呼び出し前の
    間はこのサブモジュールがまだ一度もimportされていない
    (sys.modulesに乗っていない)。よって呼び出し前にファイルをディスク上で
    パッチしておけば、reload等の複雑な仕掛け無しに最初のimport自体が
    パッチ済みソースを読む。念のため、既に他経路でimport済み
    (sys.modules登録済み)の場合だけ importlib.reload() で保険を掛ける。
    """
    import importlib
    import importlib.util

    spec = importlib.util.find_spec("io_scene_fbx.import_fbx")
    if spec is None or not spec.origin:
        # 同梱アドオンが見つからない(想定外の配置)。無理に何かするより、
        # この後の通常importに任せて自然に失敗させる方が安全。
        return False
    path = spec.origin
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
    except OSError as e:
        print(f"[{TAG}][WARN] dev#39 patch: could not read {path}: {e}")
        return False

    patched_src, changed = _fbx_importer_deformer_none_guard_fixes(src)
    if not changed:
        return False  # 既にパッチ済み、または本家側で修正済み

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(patched_src)
    except OSError as e:
        print(f"[{TAG}][WARN] dev#39 patch: could not write {path}: {e}")
        return False

    print(f"[{TAG}] dev#39: patched bundled FBX importer's missing "
          f"connection_map default guard ({path})")

    mod = sys.modules.get("io_scene_fbx.import_fbx")
    if mod is not None:
        importlib.reload(mod)
    return True


# dev#1073(実報告MJV7B3K2 v2.3.8, ZJNWBRCJ v2.3.12): 同梱Blenderの
# `io_scene_fbx.import_fbx` は `blen_read_shapes()` 内で
# `objects = list({node.bl_obj for node in objects})` の直後に
# `assert(objects)` を無条件実行する。この`objects`は、呼び出し元
# (3610-3618行、`fbx_connection_map.get(m_uuid, ())`)が「BlendShapeデフォーマ
# 連鎖の先にあるMesh GeometryノードへModel(オブジェクト)接続が1本でも
# あるか」を調べた結果であり、0本ならこの`assert`がAssertionErrorで
# 変換全体を落とす(Blender 4.3.2/5.0とも本家未修正)。
#
# 実Unity輸出FBXから接続グラフを直接検証した結果(work\wp_1073\
# unity_repro\)、この状態(BlendShapeデフォーマ連鎖を持つがどのModelからも
# 参照されないMesh Geometryノード)はFBXの構造として実在し得ることを、
# 実Unity FBX Exporter(com.unity.formats.fbx)の出力を1接続だけ除去した
# 最小差分で確認済み(このFBXは同一箇所・同一AssertionErrorで再現する)。
# 一方、ConvertStaticMeshesToSkinned/FlattenSkinnedMeshes(unity\
# DiveToPalworldExporter.cs)側で試した「未使用(全重み0)ブレンドシェイプの
# 複製メッシュ」「同一メッシュを共有する2レンダラーの片方を輸出前に破棄」の
# 2仮説は、いずれも実Unity輸出でModel接続が生きたまま(=孤立しない)FBXに
# しかならず、再現しなかった(dev#1073コメント参照)。孤立の発生源を
# Unity側のどの処理が生むかは未特定のまま(FBX Exporterパッケージ内部の
# 挙動である可能性が高い)だが、「どのModelからも参照されないGeometryの
# shape data」は定義上、変換結果のどの可視メッシュにも一切影響しない
# (参照するオブジェクトが存在しない=画面に出ない)ため、ここで安全に
# 無害化しても実在するシェイプキーを静かに失う心配がない。dev#39と同じ
# 「入口で正規化する」防御的パッチとして、assertを「孤立分だけ空扱いで
# スキップし、警告を出して変換は継続する」形に置き換える。
_FBX_IMPORTER_ORPHAN_SHAPE_GUARD_FIXES = (
    ("    objects = list({node.bl_obj for node in objects})\n"
     "    assert(objects)\n",
     "    objects = list({node.bl_obj for node in objects})\n"
     "    if not objects:\n"
     "        # dev#1073: shape key geometry with no connected Model/Object\n"
     "        # (orphaned in the FBX connection graph) cannot affect any\n"
     "        # visible mesh; skip it instead of aborting the whole import.\n"
     "        print(\"[D2P][WARN] dev#1073: skipping orphaned shape key \"\n"
     "              \"geometry with no connected Model/Object (mesh: %r)\"\n"
     "              % getattr(me, 'name', me))\n"
     "        return {}\n"),
)


def _fbx_importer_orphan_shape_guard_fixes(src):
    """テキストレベルの純粋パッチ(I/O無し、bpy不要)。冪等——既にパッチ済み
    (または本家側で修正済み)のソースを渡しても何も変えない。
    戻り値: (patched_src, changed: bool)"""
    changed = False
    for old, new in _FBX_IMPORTER_ORPHAN_SHAPE_GUARD_FIXES:
        if old in src:
            src = src.replace(old, new)
            changed = True
    return src, changed


def patch_bundled_fbx_importer_orphan_shape_guard():
    """dev#1073: 同梱Blenderの io_scene_fbx.import_fbx モジュールを検査し、
    `blen_read_shapes()`の無条件assert(objects)を検出したら、孤立シェイプ
    ジオメトリ(接続Modelが0件)をスキップする形へ書き換える。
    実装はpatch_bundled_fbx_importer_deformer_none_guard(dev#39)と同じ
    「起動のたびに冪等パッチを当てる」方式(同梱BlenderはGit管理外の
    共有資源のため恒久同梱不可)。
    """
    import importlib
    import importlib.util

    spec = importlib.util.find_spec("io_scene_fbx.import_fbx")
    if spec is None or not spec.origin:
        return False
    path = spec.origin
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
    except OSError as e:
        print(f"[{TAG}][WARN] dev#1073 patch: could not read {path}: {e}")
        return False

    patched_src, changed = _fbx_importer_orphan_shape_guard_fixes(src)
    if not changed:
        return False  # 既にパッチ済み、または本家側で修正済み

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(patched_src)
    except OSError as e:
        print(f"[{TAG}][WARN] dev#1073 patch: could not write {path}: {e}")
        return False

    print(f"[{TAG}] dev#1073: patched bundled FBX importer's orphaned shape "
          f"key geometry guard ({path})")

    mod = sys.modules.get("io_scene_fbx.import_fbx")
    if mod is not None:
        importlib.reload(mod)
    return True


# dev#876(6度目の再発、実報告X54TKURK v2.3.12): 同梱Blenderの
# `io_scene_fbx.import_fbx` は `FbxImportHelperNode.link_hierarchy()` の
# `(mmat, amat) = mesh.armature_setup[self]` (2975行)で `KeyError` を送出し、
# 変換全体を止めることがある(Blender 4.3.2/5.0とも本家未修正)。
#
# 発生機序: `find_armature_bones(armature)` は「直接の子がis_boneなら
# `.armature`をタグ付けしてさらに再帰する」実装(2467-2471行)で、is_bone
# ではない祖先を挟んだ先のボーンには絶対に到達しない(非ボーンの子孫へは
# 再帰しない設計)。一方 `collect_skeleton_meshes()`(2578-2583行)は
# `is_bone`を一切問わずツリーを素通しして、その挟まれたボーンのクラスタ
# (=メッシュ)を親armatureの`meshes`集合へちゃんと拾い上げてしまう
# (import_fbx.py内 "See T70244" コメントの既知の集計漏れ)。結果、
# `mesh.armature_setup`には`.armature`が最後まで`None`のままだった
# キー(=`None`)でデータが記録され、正しいarmatureヘルパーノード
# (`self`)をキーに`[self]`で引くと存在せずKeyErrorになる。
#
# dev#455(Merge Armatureアンカー)→dev#876(残置Animatorコンテナ)→
# dev#925/PR#1050(rootBoneのみ参照・Humanoid未参照ボーンの一般化)と、
# Unity側(`unity\DiveToPalworldExporter.cs`)で「何が"非ボーン"祖先として
# 生き残るか」を突き止めて塞ぐ対症を3周行ったが、X54TKURK
# (輸出直前の不変条件チェックが `bone数=307` で違反0件と記録した直後の
# 同一実行)で6度目の再発を確認した。Unity FBX Exporter
# (com.unity.formats.fbx)がFBXノードをLimbNode/Null/Rootのどれとして
# 書き出すかはブラックボックスであり、Unity側のC#から「どのTransformが
# ボーンか」をUnityの意味論(SkinnedMeshRenderer.bones[]/rootBone/
# Humanoidマップ)だけで完全に予測するのは構造的に頭打ち(この3回の
# 対症がいずれも"個別に判明したトリガー"止まりだったのがその証拠)。
#
# そのため方針転換: Unity側で先回りに防ぐ努力は維持しつつ、消費側
# (Blenderインポータ)そのものを「このKeyErrorでは絶対に落ちない」ように
# 防御的パッチする。`None`キーに記録されたデータは、まさにこのバグ機序で
# 本来`self`に記録されるはずだったのと同一のクラスタ由来なので、
# 空扱い・場当たり近似ではなく、実際に記録済みの正しいbind-pose行列を
# 取り違えたキーから回収する構造的なフォールバックになる(万一`None`にも
# 無ければ、次善として辞書内の他のどれかのエントリを使い、それも無ければ
# 単位行列。いずれの分岐でも警告ログを出し、正常系(`self`が最初から
# 見つかる既存の大多数のケース)の挙動はバイト単位で不変)。dev#39/dev#1073
# と同じ「起動のたびに冪等パッチを当てる」方式(同梱BlenderはGit管理外の
# 共有資源のため恒久同梱不可)。
_FBX_IMPORTER_ARMATURE_SETUP_GUARD_FIXES = (
    ("                for mesh in self.meshes:\n"
     "                    (mmat, amat) = mesh.armature_setup[self]\n",
     "                for mesh in self.meshes:\n"
     "                    # D2P dev#876: mesh.armature_setup may lack an\n"
     "                    # entry for this armature helper node (a deeper\n"
     "                    # bone's `.armature` tag can be left None when a\n"
     "                    # still-present non-bone ancestor breaks\n"
     "                    # find_armature_bones()'s is_bone-only recursion).\n"
     "                    # Recover the real bind-pose data instead of\n"
     "                    # crashing with a bare KeyError.\n"
     "                    setup = mesh.armature_setup.get(self)\n"
     "                    if setup is None:\n"
     "                        setup = mesh.armature_setup.get(None)\n"
     "                    if setup is None and mesh.armature_setup:\n"
     "                        setup = next(iter(mesh.armature_setup.values()))\n"
     "                    if setup is None:\n"
     "                        print(\"[D2P][WARN] dev#876: mesh %r has no \"\n"
     "                              \"recorded bind-pose data for armature \"\n"
     "                              \"%r; using an identity fallback (this \"\n"
     "                              \"mesh's skinning may look slightly off)\"\n"
     "                              % (getattr(mesh.bl_obj, 'name', mesh),\n"
     "                                 self.fbx_name))\n"
     "                        setup = (Matrix(), None)\n"
     "                    (mmat, amat) = setup\n"),
)


def _fbx_importer_armature_setup_guard_fixes(src):
    """テキストレベルの純粋パッチ(I/O無し、bpy不要)。冪等——既にパッチ済み
    (または本家側で修正済み)のソースを渡しても何も変えない。
    戻り値: (patched_src, changed: bool)"""
    changed = False
    for old, new in _FBX_IMPORTER_ARMATURE_SETUP_GUARD_FIXES:
        if old in src:
            src = src.replace(old, new)
            changed = True
    return src, changed


def patch_bundled_fbx_importer_armature_setup_guard():
    """dev#876: 同梱Blenderの io_scene_fbx.import_fbx モジュールを検査し、
    `link_hierarchy()`内の無条件`mesh.armature_setup[self]`を検出したら、
    正しいキーが無い場合に`None`キー→他のエントリ→単位行列の順で
    フォールバックする形へ書き換える。実装はdev#39/dev#1073と同じ
    「起動のたびに冪等パッチを当てる」方式(同梱BlenderはGit管理外の
    共有資源のため恒久同梱不可)。
    """
    import importlib
    import importlib.util

    spec = importlib.util.find_spec("io_scene_fbx.import_fbx")
    if spec is None or not spec.origin:
        return False
    path = spec.origin
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
    except OSError as e:
        print(f"[{TAG}][WARN] dev#876 patch: could not read {path}: {e}")
        return False

    patched_src, changed = _fbx_importer_armature_setup_guard_fixes(src)
    if not changed:
        return False  # 既にパッチ済み、または本家側で修正済み

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(patched_src)
    except OSError as e:
        print(f"[{TAG}][WARN] dev#876 patch: could not write {path}: {e}")
        return False

    print(f"[{TAG}] dev#876: patched bundled FBX importer's "
          f"armature_setup KeyError guard ({path})")

    mod = sys.modules.get("io_scene_fbx.import_fbx")
    if mod is not None:
        importlib.reload(mod)
    return True


# dev#1175(実報告EMNREP4K v2.3.12): 同梱Blenderの `io_scene_fbx.fbx_utils`
# の `similar_values_iter()` (277-284行) は、比較対象の2ベクトルの成分ごとに
# `abs(v1 - v2) / max(abs(v1), abs(v2))` を計算して閾値と比べる。この分母は
# 数学的には「両成分とも真の0.0」の場合しかゼロにならないはずだが、その
# 条件下では直前の `v1 != v2` が必ずFalseになり除算そのものへ到達しない
# ため、通常入力では発生しない。しかし一方の成分がNaNの場合、
# `v1 != v2` はNaN比較の性質上常にTrueになる一方、Pythonの`max()`は
# NaN非対応(`b > a`がNaN絡みでは常にFalseになるため、渡した順序次第で
# 有限側の値をそのまま返す)ため、`max(abs(v1), abs(v2))`が実際には
# 0.0を返しうる。結果 `<NaN絡みの分子> / 0.0` でZeroDivisionErrorになり、
# 変換全体が落ちる(Blender 4.3.2、本家未修正)。
#
# 呼び出し元(`import_fbx.py`の`child_connect()`、2608/2645行)は
# ボーンのtail/headが同一座標かどうかを見て親子ボーンを自動接続するための
# ものであり、EMNREP4Kのトレースバックはまさにこの経路(zero-length bone
# ジオメトリに由来するNaN成分を含むFBXデータ)で発生している
# (`work\wp_1175\PROGRESS.md`参照、実Blenderでの再現・特定を実施済み)。
# dev#39/dev#1073/dev#876と同じ「入口で正規化する」防御的パッチとして、
# 分母が0(またはNaN)に退化する場合は例外を出さず「一致しない」扱いに
# フォールバックし、変換を継続する(=そのボーンは自動接続されず独立ボーンの
# ままになるだけで、他の正常なボーンの接続判定はバイト単位で不変)。
_FBX_UTILS_SIMILAR_VALUES_ZERODIV_GUARD_FIXES = (
    ("        if (v1 != v2) and ((abs(v1 - v2) / max(abs(v1), abs(v2))) > e):\n"
     "            return False\n",
     "        if v1 != v2:\n"
     "            denom = max(abs(v1), abs(v2))\n"
     "            if denom == 0.0 or denom != denom:\n"
     "                # D2P dev#1175: a zero-length bone (coincident\n"
     "                # head/tail) can leave a NaN component in one of\n"
     "                # the compared vectors. Python's max() is\n"
     "                # NaN-unaware and can silently return 0.0 here\n"
     "                # instead of the true magnitude, which then\n"
     "                # divides by zero below and aborts the whole\n"
     "                # import. Treat a degenerate denominator as\n"
     "                # \"not similar\" instead of crashing.\n"
     "                print(\"[D2P][WARN] dev#1175: skipping degenerate \"\n"
     "                      \"bone tail/head comparison (likely a \"\n"
     "                      \"zero-length bone) that would otherwise \"\n"
     "                      \"divide by zero\")\n"
     "                return False\n"
     "            if (abs(v1 - v2) / denom) > e:\n"
     "                return False\n"),
)


def _fbx_utils_similar_values_zerodiv_guard_fixes(src):
    """テキストレベルの純粋パッチ(I/O無し、bpy不要)。冪等——既にパッチ済み
    (または本家側で修正済み)のソースを渡しても何も変えない。
    戻り値: (patched_src, changed: bool)"""
    changed = False
    for old, new in _FBX_UTILS_SIMILAR_VALUES_ZERODIV_GUARD_FIXES:
        if old in src:
            src = src.replace(old, new)
            changed = True
    return src, changed


def patch_bundled_fbx_importer_similar_values_zerodiv_guard():
    """dev#1175: 同梱Blenderの io_scene_fbx.fbx_utils モジュールを検査し、
    `similar_values_iter()`の無条件除算を検出したら、分母が0(またはNaN)に
    退化する場合に例外を出さず「一致しない」へフォールバックする形へ
    書き換える。実装はdev#39/dev#1073/dev#876と同じ「起動のたびに冪等
    パッチを当てる」方式(同梱BlenderはGit管理外の共有資源のため恒久
    同梱不可)。パッチ対象は`io_scene_fbx.import_fbx`ではなく
    `io_scene_fbx.fbx_utils`である点に注意(`similar_values_iter`の定義元)。
    """
    import importlib
    import importlib.util

    spec = importlib.util.find_spec("io_scene_fbx.fbx_utils")
    if spec is None or not spec.origin:
        return False
    path = spec.origin
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
    except OSError as e:
        print(f"[{TAG}][WARN] dev#1175 patch: could not read {path}: {e}")
        return False

    patched_src, changed = _fbx_utils_similar_values_zerodiv_guard_fixes(src)
    if not changed:
        return False  # 既にパッチ済み、または本家側で修正済み

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(patched_src)
    except OSError as e:
        print(f"[{TAG}][WARN] dev#1175 patch: could not write {path}: {e}")
        return False

    print(f"[{TAG}] dev#1175: patched bundled FBX importer's "
          f"similar_values_iter zero-division guard ({path})")

    # `io_scene_fbx.import_fbx` は起動時に
    # `from .fbx_utils import (..., similar_values_iter, ...)` で名前を
    # コピーして束縛するため、fbx_utilsだけをreloadしても既にimport済みの
    # import_fbxからは古い関数のままになる。両方を(存在すれば)reloadする。
    fbx_utils_mod = sys.modules.get("io_scene_fbx.fbx_utils")
    if fbx_utils_mod is not None:
        importlib.reload(fbx_utils_mod)
    import_fbx_mod = sys.modules.get("io_scene_fbx.import_fbx")
    if import_fbx_mod is not None:
        importlib.reload(import_fbx_mod)
    return True


# dev#669: BlenderのFBXインポータはバイナリFBXしか読めず、ASCII(テキスト)
# 形式のFBXを渡すと `bpy.ops.import_scene.fbx()` の中で生の
# `RuntimeError: Error: ASCII FBX files are not supported '<path>'` を
# 送出して変換全体を止める(実報告 R3MD5NES、FBX直入力・humanoid.json併用の
# 両裏オプション経路とも同一箇所で発生)。バイナリFBXは`Kaydara FBX Binary`
# マジックで必ず始まる(公式仕様)ため、Blenderへ渡す前に先頭バイトだけを
# 見て判定し、非対応形式なら分かりやすい専用エラーに差し替える(入口で
# 正規化。bpy非依存の純粋関数なので実Blender無しに単体試験できる)。
_FBX_BINARY_MAGIC = b"Kaydara FBX Binary"


def _is_binary_fbx(path):
    """先頭バイトが`Kaydara FBX Binary`マジックで始まるかを見る。
    ファイルが読めない場合はここでは判定せず True を返し、後続の通常の
    インポート処理(既存のファイル未存在チェック等)に委ねる。"""
    try:
        with open(path, "rb") as f:
            head = f.read(len(_FBX_BINARY_MAGIC))
    except OSError:
        return True
    return head == _FBX_BINARY_MAGIC


def require_binary_fbx(path):
    """ASCII FBX等、Blenderの`import_scene.fbx`が読めない非対応形式なら、
    Blenderへ渡す前に明確な専用エラーで停止する。バイナリFBXは素通しする。"""
    if _is_binary_fbx(path):
        return
    core.die(TAG, "ASCII FBX files are not supported: '" + path + "'.\n"
              "This FBX was exported in ASCII (text) format, which Blender's "
              "FBX importer cannot read. Re-export it in Binary FBX format "
              "from the original tool (most exporters default to Binary; "
              "look for an 'ASCII'/'Type: ASCII' export option and turn it "
              "off) and try the conversion again.")


def import_fbx_avatar(job, warnings, humanoid_json=None):
    """FBX入力(VRChatter向け)。Humanoid対応表はhumanoid.json(Unity輸出)から。"""
    import json
    import mathutils
    require_binary_fbx(job["vrm_path"])
    patch_bundled_fbx_importer_deformer_none_guard()
    patch_bundled_fbx_importer_orphan_shape_guard()
    patch_bundled_fbx_importer_armature_setup_guard()
    patch_bundled_fbx_importer_similar_values_zerodiv_guard()
    before = set(bpy.data.objects)
    # dev#369: FBXに記録されたテクスチャ相対パスは、書き出した側(Unity
    # プロジェクト)の基準で書かれている。それをFBXの現在位置へ連結する
    # Blender既定の解決は、基準が違うため無意味なパスを生み、しかも
    # 失敗が致命的(FileNotFoundErrorで変換全体が停止)だった。
    # 明示ルート(FBXのあるフォルダ)基準の解決へ差し替える。
    with rooted_fbx_texture_resolution(os.path.dirname(
            os.path.abspath(job["vrm_path"]))):
        bpy.ops.import_scene.fbx(filepath=job["vrm_path"])
    new_objs = set(bpy.data.objects) - before
    arms = [o for o in new_objs if o.type == "ARMATURE"]
    if not arms:
        core.die(TAG, "FBX import produced no Armature")
    # 複数アーマチュアがある変則FBXは、ボーン数最大のものを本体とみなす
    arm = max(arms, key=lambda a: len(a.data.bones))
    if len(arms) > 1:
        warnings.append(f"detected multiple Armatures. Using {arm.name} (others discarded)")
    # ミラー由来の負スケールは法線が裏返る恐れがある(焼き込みはするが警告)
    for o in new_objs:
        if o.type == "MESH" and min(o.scale) < 0:
            warnings.append(f"mesh with negative scale: {o.name} (faces may be flipped)")

    # 座標系の平坦化(Unity FBX Exporter産FBX対策、2026-07-22 toto実測):
    # 親Empty(Armatureノード)がスケールを持ち「アーマチュア空間 != ワールド」に
    # なる(ボーンだけ2.18倍など。ワールドでは整合するのでBlender上は正常に見える)。
    # step02リターゲットはアーマチュア空間で読むため、親子を切ってワールド変換を
    # 実体へ焼き込み、空間を一致させる。あわせて単位もmへ正規化する
    meshes = [o for o in new_objs if o.type == "MESH"]
    # 非スキンメッシュ(頂点グループ0)の元の親ボーン名を、直後のparent_clear()で
    # 親子関係が切れる前に記録しておく。ボーン直付け(parent_type=BONE)だけで
    # なく、ボーン末端のEmpty子ノード経由(PhysBoneCollider等と同型)で間接的に
    # ぶら下がっているケースも、Empty側の親を遡って最初のBONE親を採用する。
    # D2P平坦化FBXではこの後メッシュのparent_type/parent_boneをOBJECT/""へ
    # 強制するため(下のコメント参照)、元の親ボーン情報はここでしか取れない。
    # step02のzero-weight rescueが「元の親ボーンに対応するパルボーンへ束縛」
    # するために使う(帽子・リボン等が腰[pelvis固定]でなく頭に付くようにする)。
    source_parent_bone = {}
    for o in meshes:
        if len(o.vertex_groups) > 0:
            continue  # スキン済みは対象外(ここでの推定は使わない)
        cur = o
        seen = set()
        bone_name = None
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            if cur.parent_type == "BONE" and cur.parent_bone:
                bone_name = cur.parent_bone
                break
            cur = cur.parent
        source_parent_bone[o.name] = bone_name
    keep = [arm] + meshes
    # FBXシーンルート(toto等)の行列 = 「Unityワールド→Blenderワールド」変換。
    # D2P平坦化FBXの頂点データはUnityワールド座標なので、メッシュにはこれを使う
    # (アーマチュア行列はeRoot=Hipsノードの平行移動を含むため使えない)
    root_obj = arm
    while root_obj.parent is not None:
        root_obj = root_obj.parent
    root_mat = root_obj.matrix_world.copy()
    bpy.ops.object.select_all(action="DESELECT")
    for o in keep:
        o.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    for o in list(new_objs):
        if o.type == "EMPTY":
            bpy.data.objects.remove(o, do_unlink=True)
    # D2P平坦化済みFBX(DiveToPalworldExporter産)は「メッシュ頂点データと
    # ボーンデータが同一空間」なので、メッシュのオブジェクト行列を
    # アーマチュアと同一にすれば厳密に整合する(BlenderのFBXインポータが
    # スキンメッシュを誤配置する問題の決定的な回避。2026-07-22)
    flattened = False
    if humanoid_json:
        try:
            with open(humanoid_json, encoding="utf-8") as f:
                flattened = bool(json.load(f).get("d2p_flattened"))
        except Exception:
            pass
    # D2P平坦化FBXの前提「メッシュ頂点データとボーンデータが同一空間」は、
    # Unity側 DiveToPalworldExporter.FlattenSkinnedMeshes() が
    # **SkinnedMeshRenderer のみ**を対象に頂点をバインド時ワールドへ焼き込み、
    # ルート直下・ローカル原点へ再配置しているために成り立つ(unity側は
    # 読み取り専用で確認済み。書き込みは対象外ファイルのため不可)。
    # 素のMeshRenderer(帽子・リボン等、スキニングされずボーンやその末端の
    # Empty子ノードへTransformで直付けされたアクセサリ)はUnity側で一切
    # 平坦化されず、元のノード位置のまま輸出される。この種のメッシュは
    # 直前のparent_clear(CLEAR_KEEP_TRANSFORM)で既に正しいワールド位置が
    # matrix_worldへ解決されている。
    #
    # 判定は「頂点グループ(スキンウェイト)を1つでも持つか」で行う。
    # BlenderのFBXインポータはDeformer(スキン)クラスタ情報がFBX側にあれば
    # 頂点グループを作る(元FBXでの親ノード種別・Armatureモディファイアの
    # 有無に関わらない)。頂点グループが1つも無いメッシュだけが真に
    # 「スキンされていない=位置は親ノードのTransformのみで決まる」もの。
    #
    # 判定基準を「Armatureモディファイアの有無」にしてはいけない
    # (2026-07-26 agyo検体で実測・却下): 単一ボーン100%ウェイトのスキン
    # メッシュをUnity FBX Exporterが「ボーン直接子」として最適化書き出しする
    # ケース(このファイル下部、OBJECT強制コメント参照)では、頂点グループ
    # 自体は複数個・実データ入りで存在するのにArmatureモディファイアが
    # 付かない(agyoのBody/karada/mohuで確認: n_vgroups=13/50/8だが
    # has_armature_modifier=False)。ここでmodifier有無を判定に使うと、
    # これら本来flatten対象のスキン済みメッシュを「非スキン」と誤判定し、
    # root_mat上書きをスキップしてしまい、平坦化FBX対応の本来の目的
    # (BlenderのFBXインポータがスキンメッシュを誤配置する問題の回避、
    # 2026-07-22)を壊す。
    #
    # 一方、頂点グループの有無なら両ケースを正しく区別できる:
    # 2026-07-26実測(flatver101_sunaoのFootLPBC/FootRPBC、PhysBoneCollider
    # 用の空リーフ)は頂点グループ0(真に非スキン)。一律上書きすると左右の
    # コライダーが別々の位置を失い同一座標(root_mat)へ収束することを確認
    # 済み(左右のmatrix_world.translationが完全一致した)。
    #
    # dev#1246追記(2026-08-08、座標系ずれ実報告TFVNM33Vの根治): 「頂点グループの
    # 有無」だけでは不十分な反例が見つかった。入れ子(名前衝突)Armatureを持つ
    # アバターでは、装飾小物(例: AccessoryCube)が本体armとは別の、後段
    # cleanup_objects()で破棄される副次Armatureへスキンされている場合がある。
    # このメッシュも頂点グループを1つ以上持つため上のロジックでは「スキン済み」
    # と誤判定され、root_matへ強制ピン留めされていた。しかしそのウェイトは
    # 本体armのどのボーンにも対応せず(破棄される副次Armatureのボーン名)、
    # Unity側のFlattenSkinnedMeshes()もこのメッシュを本体armとの整合を前提に
    # ベイクしていない——「root_matへ揃える」という平坦化の前提自体が成立しない。
    # 結果、そのメッシュは骨格原点から2000cm超も離れた無意味な座標へ固定され、
    # 後段のsnap_to_ground()の最小Z算出まで巻き込んで全体の接地位置を狂わせ、
    # プレビューが画角外(空白)になる実害を実測した(work\rd_1246_verify\PROGRESS.md)。
    # 「本体armのボーンへのウェイトを1つでも持つか」で判定し直す: 頂点グループ
    # "名"が実際にarm.data.bonesに存在するかを見れば、agyo型(Armature
    # モディファイア無しでも本体armへ実ウェイトを持つ)は従来通りskinned判定
    # されたまま、入れ子armへのウェイトしか持たないメッシュだけを正しく
    # unskinned(root_mat上書きしない=位置保持)側へ倒せる。
    if flattened:
        arm_bone_names = {b.name for b in arm.data.bones}
        skinned_names, unskinned_names = vp_flatten_pin.classify_flatten_pin_targets(
            meshes, arm_bone_names)
        unskinned = [o for o in meshes if o.name in unskinned_names]
        for o in meshes:
            if o.name not in skinned_names:
                continue
            o.matrix_world = root_mat.copy()
        warnings.append("D2P flattened FBX: pinned mesh matrices to the FBX root")
        if unskinned:
            warnings.append(
                "D2P flattened FBX: preserved position for non-skinned meshes "
                "(attached directly to a bone/leaf node, or skinned only to a "
                f"different/discarded Armature): {[o.name for o in unskinned]}")
    height = 0.0
    for o in meshes:
        for c in o.bound_box:
            height = max(height, (o.matrix_world @ mathutils.Vector(c)).z)
    if height > 10.0:  # 高さ10m超の人型はいない=cm単位と判断(Unity FBX Exporterはcm)
        s = mathutils.Matrix.Scale(0.01, 4)
        for o in keep:
            o.matrix_world = s @ o.matrix_world
        warnings.append(f"normalized units cm->m (pre-normalization height {height:.0f})")
    # 複数オブジェクトが同一Meshデータを共有(multi-user)していると、直後の
    # transform_applyがRuntimeErrorで即abortする(2026-07-26実測: PhysBone
    # Collider用にボーン末端の子として置かれた空リーフが、コンポーネント除去後
    # Unity FBX Exporterによって共有プレースホルダーMeshとして書き出される
    # ケースで発生。FootLPBC/FootRPBC等)。個別オブジェクトのtransformを
    # 安全に焼き込めるよう、共有Meshデータを複製して単一ユーザー化してから進む
    single_usered = []
    for o in meshes:
        if o.data is not None and o.data.users > 1:
            o.data = o.data.copy()
            single_usered.append(o.name)
    if single_usered:
        warnings.append(f"made multi-user mesh single-user: {single_usered}")
        print(f"[{TAG}] multi-user mesh made single-user: {single_usered}")
    bpy.ops.object.select_all(action="DESELECT")
    for o in keep:
        o.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # メッシュはアーマチュアの子に戻す(ワールド維持)。step02の
    # global_scale_and_placeはchildren_recursiveへまとめてtransform_applyする
    # 前提のため、親子が切れているとメッシュだけ置き去りになり大破する
    # (2026-07-22実測: 糸状Vプレビューの真因)
    #
    # 単一ボーン100%ウェイトのスキンメッシュをUnity FBX Exporterが
    # 「ボーン直接子(parent_type=BONE, parent_bone=<bone>)」として最適化
    # 書き出しすることがある(2026-07-26実測: 特定検体の素体メッシュで発生)。
    # 上のparent_clear(CLEAR_KEEP_TRANSFORM)はparent=Noneにするがparent_bone
    # 属性の値は消さずに残す。その状態でo.parent=armだけを代入すると
    # Blenderがparent_boneの残留値を見てparent_typeを暗黙にBONEへ戻してしまい、
    # 以降のArmatureモディファイア評価がボーンローカル空間(Y軸基準)で解釈され
    # 90度分の姿勢ずれが生じる(2026-07-26 diag_M_ptcheckで実測確認済み)。
    # ここでは全メッシュに対しparent_type/parent_boneを明示的にOBJECTへ強制
    # することで、由来に関わらず「Armatureモディファイアで駆動する通常の
    # オブジェクト子」という意図した構造を保証する(名前のハードコードではなく
    # parent_type構造そのものへの一般的な対処)。
    for o in meshes:
        o.parent = arm
        o.parent_type = "OBJECT"
        o.parent_bone = ""
        o.matrix_parent_inverse = arm.matrix_world.inverted()
    return arm, source_parent_bone


def find_humanoid_json(job):
    """humanoid.jsonの場所: job指定 → <fbx名>.humanoid.json → 同フォルダのhumanoid.json"""
    if job.get("humanoid_json") and os.path.exists(job["humanoid_json"]):
        return job["humanoid_json"]
    fbx = job["vrm_path"]
    stem = os.path.splitext(fbx)[0]
    for cand in (stem + ".humanoid.json",
                 os.path.join(os.path.dirname(fbx), "humanoid.json")):
        if os.path.exists(cand):
            return cand
    core.die(TAG, "humanoid.json not found. FBX input requires a bone mapping table.\n"
             "Open the avatar in Unity, export it via the bundled unity\\HumanoidMapExporter.cs "
             "(place it under Assets/Editor) using the menu Tools > DiveToPalworld > "
             "Export Humanoid Map, and place the result in the same folder as the FBX")


def find_leaf_marker_bones_json(job):
    """dev#1551 laneC2: leaf_marker_bones.jsonの場所。find_humanoid_json()と
    同じ規約(job明示指定 → FBXと同フォルダ)だが、無くてもdie()しない
    (旧Unity輸出物・VRM入力には存在しない、安全側フォールバックのサイドカー)。"""
    if job.get("leaf_marker_bones_json") and os.path.exists(job["leaf_marker_bones_json"]):
        return job["leaf_marker_bones_json"]
    fbx = job.get("vrm_path", "")
    cand = os.path.join(os.path.dirname(fbx), "leaf_marker_bones.json")
    if os.path.exists(cand):
        return cand
    return None


# dev#1551緊急修理: この長さ未満の(親head→マーカーhead)ベクトルは
# 「ゼロ長化」とみなしてtail上書きを適用しない防御しきい値(単位=Blender armature
# のローカル座標、通常メートル相当)。0.1mm(1e-4)は通常の人型ボーン長
# (数cm〜数十cm)に対して十分小さく、意図的な短いマーカーとの取り違えは
# ほぼ起こらない一方、浮動小数ノイズ(RESULT.mdで実測した1e-9オーダー)は
# 確実に検出できる。
_LEAF_MARKER_MIN_TAIL_LEN = 1e-4


def fix_leaf_marker_bone_tails(arm, leaf_marker_json_path, warnings):
    """dev#1551 laneC2(条件2/3の既知の赤②の根治): Unity側AttachLeafMarkerBones
    (unity\\DiveToPalworldExporter.cs)が登録した重み無し末端マーカー骨(例:
    Humanoidの"_end"チップ骨)は、Blenderの葉ボーンtail推定ヒューリスティック
    (子を持たないボーンは親と同じ長さ・方向へ延長する、オラクル実測で確認済みの
    既定挙動)へ委ねられる。このヒューリスティックは親ボーンが複数の子(マーカー+
    MergeArmatureが付けた無関係な服の$guid骨等)を持つ場合に不安定化し、どの子を
    基準に長さを決めるかが一意に定まらないため、親自身の長さがオラクルと食い違う
    実例が見つかった(work\\run_1551\\laneC2\\NOTES.md、comodoのHips.001:
    オラクル9.1cmに対し兄弟の$guid服骨に引きずられ約半分の4.6cmへ短縮)。

    サイドカー(マーカー名→親ボーン名、Unity輸出直後の最終エクスポート名で
    書かれている)を読み、親のtailをマーカーの現在head位置(head位置はbindpose
    由来で常に正しい。tailだけがBlenderのヒューリスティックで不安定になる)へ
    明示的に上書きし、マーカー自身のtailも「親と同じベクトルで延長する」という
    オラクルで確認済みの規約をそのまま複製して復元する。これにより、親の子の
    数(兄弟の有無)に一切左右されない決定的な結果になる。

    サイドカーが無い(旧Unity輸出物・VRM入力)場合は何もしない(安全側no-op、
    従来どおりBlenderのヒューリスティックに委ねる)。
    """
    if not leaf_marker_json_path:
        return
    with open(leaf_marker_json_path, encoding="utf-8") as f:
        data = json.load(f)
    markers = data.get("markers", {})
    if not markers:
        return
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    fixed = 0
    missing = []
    degenerate = []
    try:
        for marker_name, parent_name in markers.items():
            mb = eb.get(marker_name)
            pb = eb.get(parent_name)
            if mb is None or pb is None:
                missing.append(marker_name)
                continue
            new_tail = mb.head.copy()
            # dev#1551緊急修理(work\run_1551\pgf_diag\RESULT.md): マーカーの
            # 現在head位置が親自身のhead位置とほぼ一致してしまうケースがある
            # (実例: PGF.prefabでVRCPhysBoneColliderアンカーが誤ってマーカーと
            # 混同され、そのheadが親骨自身のhead付近に来ていた)。この場合
            # pb.tail = mb.head をそのまま適用すると親骨がゼロ長(head==tail)
            # になる。Blenderには「head==tailかつ非ルートのボーンは、EDIT→
            # OBJECTモード復帰時に黙って破棄する」既知の挙動があり(実測で確認
            # 済み)、放置すると実在する骨(comodo実例ではSpine)が跡形もなく
            # 消え、後段のhumanoid_map_from_json()が「必須Humanoidボーンが
            # 見つからない」という誤誘導FATALで死ぬ。上流(Unity側マーカー検出)
            # の誤りがあっても、ここで「骨を消す方向の変形」を構造的に不可能に
            # しておくことで、実骨消滅という致命傷まで連鎖させない。
            if (new_tail - pb.head).length < _LEAF_MARKER_MIN_TAIL_LEN:
                degenerate.append(marker_name)
                continue
            pb.tail = new_tail
            vec = pb.tail - pb.head
            mb.tail = mb.head + vec
            fixed += 1
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    if fixed:
        warnings.append(
            f"fixed tail length for {fixed} leaf marker bone(s) and their parent bone "
            f"(dev#1551: resolved an ambiguous multi-child FBX import tail heuristic)")
    if missing:
        warnings.append(
            f"leaf_marker_bones.json referenced bone(s) not found in the imported "
            f"armature (skipped): {missing}")
    if degenerate:
        warnings.append(
            f"skipped {len(degenerate)} leaf marker bone(s) whose head position "
            f"nearly coincides with their parent bone's head (applying the fix would "
            f"have collapsed the parent bone to zero length, and Blender silently "
            f"drops zero-length non-root bones on EDIT->OBJECT mode exit; left the "
            f"parent bone's tail untouched instead -- dev#1551 regression guard): "
            f"{degenerate}")


def cleanup_objects(arm, warnings):
    """アーマチュアと、その配下のメッシュ以外を消す。非表示メッシュも落とす。"""
    keep_meshes = []
    for obj in list(bpy.data.objects):
        if obj is arm:
            continue
        if obj.type == "MESH" and (obj.parent is arm or any(
                m.type == "ARMATURE" and m.object is arm
                for m in obj.modifiers)):
            if obj.hide_viewport or obj.hide_render:
                warnings.append(f"excluded hidden mesh: {obj.name}")
                bpy.data.objects.remove(obj, do_unlink=True)
            else:
                keep_meshes.append(obj)
        else:
            bpy.data.objects.remove(obj, do_unlink=True)
    if not keep_meshes:
        # dev#1261(実報告DLK66VBE、20KB破損VRM疑い): 内部診断文言(英語、
        # 上記die()の第2引数)は問い合わせデバッグの作法(CLAUDE.md「問い合わせ
        # からのデバッグ」)どおり変更しない——ログだけで原因に到達できる
        # 情報を保つのが目的で、これはこれで開発者向けに必要。
        # ここではGUI向けの言語追従表示のため、既存の##AVATAR_WARNING##と
        # 同型のマーカー行を追加で出す(app_py\pipeline_runner.py の
        # parse_avatar_fatal/translate_avatar_fatalが拾い、main_window.pyが
        # オーナー指定文言(i18n key MsgNoMeshFatal)へ翻訳して表示する)。
        # pipeline\pyとapp_pyは相互import禁止の一方向設計のため、翻訳は
        # ここでなくapp_py側で行う(##AVATAR_WARNING##と同じ分業)。
        print("##AVATAR_FATAL## no_mesh")
        core.die(TAG, "avatar has no meshes at all")
    # メッシュ名を無害な連番へ強制リネーム。VRMのメッシュ名がパルのボーン名と
    # 衝突すると(例: Seed-sanの「head」メッシュ)、FBX往復でUEがボーン側を
    # 「head1」にリネームし、頭がアニメ非追従になる実害を確認済み
    orig_names = {}
    for i, obj in enumerate(keep_meshes):
        orig = obj.name
        obj.name = f"geo_{i:02d}"
        if obj.data:
            obj.data.name = obj.name
        orig_names[obj.name] = orig
        if orig != obj.name:
            print(f"[{TAG}] mesh renamed: '{orig}' -> {obj.name}")
    return keep_meshes, orig_names


def apply_transforms(arm):
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    for child in arm.children_recursive:
        child.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def drop_shape_keys(job=None, warnings=None, orig_names=None):
    """dev#1168(2026-08-09、ラボ機能「シェイプキー」): job["shape_keys"]
    (={orig_mesh_name: {key_name: value(0..1)}})が与えられていれば、対象
    メッシュのシェイプキーを指定値で現在のミックスとして基底ジオメトリへ
    焼き込んでから、全シェイプキーをdropする。job未指定/キー不在/該当メッシュ
    無し/該当キー名が1件も一致しない場合は、焼き込み処理を一切行わず
    (=挙動は変更前と完全に同一)、従来どおり全シェイプキーをdropするだけ。

    メッシュ名の対応: この関数が呼ばれる時点でメッシュは既にcleanup_objects()
    により"geo_00"等へ強制リネーム済みのため、job["shape_keys"]のキー
    (元の名前、GUIがVRM/prefabから読み取った名前)を照合するには
    orig_names(cleanup_objects()の戻り値、現在名->元の名前の対応)経由で
    元の名前へ逆引きする必要がある。orig_names未指定時は照合できないため、
    焼き込みは行わない(安全側、従来動作のまま)。

    焼き込み方式: Object.shape_key_add(name=..., from_mix=True)で現在の
    value設定に基づくミックス結果を新規キーとして生成させ(Blender標準の
    相対シェイプキー合成をそのまま使う、自前で合成式を再実装しない)、その
    座標を**mesh.vertices(基底ジオメトリそのもの)へ直接上書きする**。
    多フレームのシェイプキーは最終フレームのみを対象とする(WP指示書の
    明示許容: 「多フレームBSは現行コード同様の最終フレームのみで可」
    ——2026-07-22時点のバインドポーズ焼き込みコードと同じ簡略化)。
    法線は本関数では再計算しない(基底頂点位置さえ正しければ、Blender/
    エクスポータ側が面法線から自動的に導出する。ラボ憲章②「あんまり試験
    しない雑な実装でよい」の範囲)。

    2026-08-09死因修正(dev#1285、オーナー報告「シェイプキー変更しても
    プレビューが変わらない」): 旧実装はミックス結果を
    `key_blocks[0].data[i].co`(Basisシェイプキーのデータ)へ上書きして
    いたが、Blender実測(work\\wp_sk_preview_fix\\repro_shapekey_clear*.py)
    で確認した通り、Basisシェイプキーの`data`はメッシュの実体
    (`mesh.vertices`)とは別バッファであり、Basisへの書き込みは
    `mesh.vertices`へ一切反映されない。直後の`obj.shape_key_clear()`で
    全シェイプキー(Basis含む)を削除すると、`mesh.vertices`は最初から
    触っていない元の頂点座標のまま残る——つまり焼き込みは常に無効化されて
    いた(ログには"shape keys applied"と出るのに、実際のジオメトリは
    一切変わらない)。この不具合はVRM/prefabどちらの入力経路にも共通
    (mesh_cfgの照合キーが正しく一致していたprefab経路でも同様に無効化
    されていたはずで、シェイプキーラボ機能はdev#1168導入時点から一度も
    機能していなかった)。修正: ミックス結果を`obj.data.vertices[i].co`
    へ直接書き込む(シェイプキーがまだ残っている間に書けば、その後の
    `shape_key_clear()`後も値は保持される、上記repro script中の
    `repro_shapekey_clear2.py`で確認済み)。"""
    cfg = job.get("shape_keys") if isinstance(job, dict) else None
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.data.shape_keys:
            continue
        key_blocks = obj.data.shape_keys.key_blocks
        n = len(key_blocks)
        applied = 0
        if cfg and orig_names is not None:
            orig = orig_names.get(obj.name, obj.name)
            mesh_cfg = cfg.get(orig) if isinstance(cfg, dict) else None
            if mesh_cfg:
                for kb in key_blocks:
                    if kb == key_blocks[0]:  # Basis自身は対象外
                        continue
                    v = mesh_cfg.get(kb.name)
                    if v is None:
                        continue
                    try:
                        fv = max(0.0, min(1.0, float(v)))
                    except (TypeError, ValueError):
                        continue
                    if fv:
                        kb.value = fv
                        applied += 1
                if applied:
                    new_key = obj.shape_key_add(name="d2p_shapekey_mix", from_mix=True)
                    # mesh.verticesへ直接書く(key_blocks[0].data経由では
                    # shape_key_clear()後にmesh.verticesへ反映されない、
                    # 上のdocstring「2026-08-09死因修正」参照)。
                    mesh_data = obj.data
                    for i in range(len(mesh_data.vertices)):
                        mesh_data.vertices[i].co = new_key.data[i].co
                    msg = (f"[{TAG}] shape keys applied: {obj.name} "
                           f"(orig='{orig}', {applied} key(s))")
                    print(msg)
                    if warnings is not None:
                        warnings.append(
                            f"shape keys applied then dropped: {obj.name} "
                            f"({applied} key(s) baked)")
        obj.shape_key_clear()
        print(f"[{TAG}] shape keys dropped: {obj.name} ({n})")


def drop_bone_meshes(arm, meshes, drop_bones, warnings):
    """指定ボーン(とその子孫)にウェイトが乗った頂点を削除する(上級者向け)。
    Humanoid外アクセサリ(例: Seed-sanのロボアーム)を消したい時に使う。
    合計ウェイト>0.5の頂点を削除し、空になったメッシュはオブジェクトごと消す。"""
    if not drop_bones:
        return meshes
    targets = set()
    for name in drop_bones:
        bone = arm.data.bones.get(name)
        if bone is None:
            warnings.append(f"drop_bones: bone not found: {name}")
            continue
        targets.add(bone.name)
        for child in bone.children_recursive:
            targets.add(child.name)
    if not targets:
        return meshes
    print(f"[{TAG}] drop_bones: {sorted(drop_bones)} -> {len(targets)} bone(s) targeted (incl. descendants)")

    survivors = []
    for obj in meshes:
        idx = {vg.index for vg in obj.vertex_groups if vg.name in targets}
        if not idx:
            survivors.append(obj)
            continue
        sel = [v.index for v in obj.data.vertices
               if sum(g.weight for g in v.groups if g.group in idx) > 0.5]
        if not sel:
            survivors.append(obj)
            continue
        if len(sel) == len(obj.data.vertices):
            name = obj.name
            bpy.data.objects.remove(obj, do_unlink=True)
            print(f"[{TAG}] drop_bones: removed entire mesh: {name}")
            continue
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        for i in sel:
            obj.data.vertices[i].select = True
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="VERT")
        bpy.ops.mesh.delete(type="VERT")
        bpy.ops.object.mode_set(mode="OBJECT")
        print(f"[{TAG}] drop_bones: {obj.name}: deleted {len(sel)} vertex(es)")
        if len(obj.data.vertices) == 0:
            bpy.data.objects.remove(obj, do_unlink=True)
        else:
            survivors.append(obj)
    if not survivors:
        core.die(TAG, "drop_bones removed every mesh (the spec is too broad)")
    return survivors


def drop_named_meshes(meshes, orig_names, drop_mesh_names, warnings):
    """dev#1168前半(ラボ機能「メッシュ削除」)。指定したメッシュをオブジェクト
    ごと削除する(部分削除は行わない、既存drop_bone_meshes()とは異なり常に
    全削除)。drop_mesh_namesはGUIチェックリストが「元の名前」(cleanup_objects()
    リネーム前、orig_namesの値)で構成した削除対象集合。

    照合ロジック本体はvp_mesh_drop.classify_mesh_drop_targets()(bpy非依存、
    tests\\coverage\\selftestで単体検証済み)へ委譲し、ここではbpy.data.objects
    の実削除とログ/warnings出力だけを行う(入口正規化の原則、drop_bone_meshesと
    同じ構造)。ラボ憲章④: drop_mesh_namesが空なら早期returnで完全no-op。"""
    if not drop_mesh_names:
        return meshes
    to_remove, missing = vp_mesh_drop.classify_mesh_drop_targets(
        [o.name for o in meshes], orig_names, drop_mesh_names)
    for name in sorted(missing):
        warnings.append(f"drop_meshes: mesh not found: {name}")
    if not to_remove:
        return meshes
    survivors = []
    for obj in meshes:
        if obj.name in to_remove:
            # dev#1168/実報告2026-08-09(comodo「Body」・comodo_apron「Hat」の
            # 双方で確実に再現): 削除前に名前をローカル変数へ退避すること。
            # bpy.data.objects.remove()の直後にobj.nameへアクセスすると、
            # 内部StructRNAが既に解放済みのため
            # `ReferenceError: StructRNA of type Object has been removed` で
            # step01自体がクラッシュする(f-stringはprint実行時に全項目を
            # 評価するため、remove()より前の行での代入では防げない——
            # このf-string内のobj.name参照そのものが原因)。直上のdrop_bones()
            # (L.1110-1112)と同じ「削除前に名前を確保する」パターンに揃える。
            orig = orig_names.get(obj.name, obj.name)
            renamed = obj.name
            bpy.data.objects.remove(obj, do_unlink=True)
            print(f"[{TAG}] drop_meshes: removed mesh: {orig} ({renamed})")
        else:
            survivors.append(obj)
    if not survivors:
        core.die(TAG, "drop_meshes removed every mesh (the spec is too broad)")
    return survivors


def extract_spring_roots(arm):
    """VRMのSpringBone定義から揺れ物チェーンのルートボーン名を抽出する。
    (VRM1: spring_bone1.springs の各先頭joint / VRM0: secondaryAnimationのbones)
    step02がこのうち「頭の子孫」だけを揺れ髪として採用する。"""
    ext = arm.data.vrm_addon_extension
    roots = []
    try:
        for spring in ext.spring_bone1.springs:
            joints = [j.node.bone_name for j in spring.joints
                      if j.node.bone_name]
            if joints:
                roots.append(joints[0])
    except AttributeError:
        pass
    try:
        for bg in ext.vrm0.secondary_animation.bone_groups:
            for b in bg.bones:
                if b.bone_name:
                    roots.append(b.bone_name)
    except AttributeError:
        pass
    roots = sorted({r for r in roots if r in arm.data.bones})
    if roots:
        print(f"[{TAG}] spring bone roots: {roots}")
    return roots


def extract_springbone_components(arm):
    """dev#1508 W1b(work\\night_20260817\\laneE\\SMOKE.md確定の欠落を埋める):
    VRMのSpringBone定義を、`sway_allocator.parse_springbones()`が期待する
    フルスキーマ(anchor/chains/params)へ変換する。extract_spring_roots()
    はroot骨名だけを返す軽量版(揺れ髪機構の頭子孫フィルタ専用、既存不変)
    ——本関数はアロケータへ渡す完全な鎖+量子化入力(stiffness/gravity_power/
    drag_force)まで含む。

    bpy依存の抽出(`arm.data.vrm_addon_extension`/`arm.data.bones`から素の
    Python辞書への変換)だけをここで行い、変換ロジック本体は
    `vp_springbone_extract.build_springbone_components()`(bpy非依存、
    `tests\\coverage\\selftest\\test_springbone_extract_dev1508_w1b.py`で
    単体検証済み)へ委譲する(vp_mesh_drop.py等と同じ設計方針)。

    戻り値: job["springbones"]にそのまま代入できるフラットlist
    (`[{"anchor": str, "chains": [[str,...],...], "params": {...}}, ...]`)。
    SpringBone定義が無い/骨がインポートされなかった場合は空リスト。"""
    ext = arm.data.vrm_addon_extension
    bones = arm.data.bones
    bone_names = {b.name for b in bones}
    parent_of = {b.name: (b.parent.name if b.parent else None) for b in bones}
    children_of = {}
    for b in bones:
        if b.parent is not None:
            children_of.setdefault(b.parent.name, []).append(b.name)

    vrm1_springs = []
    try:
        for spring in ext.spring_bone1.springs:
            joints = [{
                "bone_name": j.node.bone_name,
                "stiffness": j.stiffness,
                "gravity_power": j.gravity_power,
                "drag_force": j.drag_force,
            } for j in spring.joints]
            vrm1_springs.append({"joints": joints})
    except AttributeError:
        pass

    vrm0_bone_groups = []
    try:
        for bg in ext.vrm0.secondary_animation.bone_groups:
            vrm0_bone_groups.append({
                # dev#1508: VRM Addon for BlenderのVRM0プロパティ名は
                # "stiffiness"(原文ママtypo)。ここで正しい綴り"stiffness"
                # (sway_allocator/sway_quantizeが期待するキー名)へ変換する
                # ——アドオン側の綴り誤りを本モジュールより先へ運ばない。
                "stiffness": bg.stiffiness,
                "gravity_power": bg.gravity_power,
                "drag_force": bg.drag_force,
                "bones": [b.bone_name for b in bg.bones],
            })
    except AttributeError:
        pass

    components = vp_springbone_extract.build_springbone_components(
        vrm1_springs, vrm0_bone_groups, parent_of, children_of, bone_names)
    if components:
        print(f"[{TAG}] springbone components extracted: {len(components)} "
              f"(VRM1 springs={len(vrm1_springs)}, "
              f"VRM0 bone_groups={len(vrm0_bone_groups)})")
    return components


def clear_bone_constraints(arm):
    """SpringBone/NodeConstraint類の剛体化: ポーズボーンのコンストレイントを全削除。"""
    n = 0
    for pb in arm.pose.bones:
        for c in list(pb.constraints):
            pb.constraints.remove(c)
            n += 1
    if n:
        print(f"[{TAG}] bone constraints cleared: {n}")


# ------------------------------------------------------------- マテリアル抽出

def get_base_color(mat):
    """(image|None, rgba, alpha_mode, double_sided) を返す。
    MToon(VRMアドオン拡張)→ Principled → 任意のTEX_IMAGE の順で探す。"""
    image, rgba = None, (1.0, 1.0, 1.0, 1.0)
    alpha_mode, double_sided = "OPAQUE", False
    # 1) VRMアドオンのMToon拡張
    try:
        m1 = mat.vrm_addon_extension.mtoon1
        if m1.enabled:
            src = m1.pbr_metallic_roughness.base_color_texture.index.source
            image = src if src is not None else None
            rgba = tuple(m1.pbr_metallic_roughness.base_color_factor)
            alpha_mode = str(m1.alpha_mode)
            double_sided = bool(m1.double_sided)
            return image, rgba, alpha_mode, double_sided
    except AttributeError:
        pass
    # 2) ノードから
    if mat.use_nodes:
        principled = next((n for n in mat.node_tree.nodes
                           if n.type == "BSDF_PRINCIPLED"), None)
        if principled is not None:
            inp = principled.inputs.get("Base Color")
            if inp is not None:
                rgba = tuple(inp.default_value)
                for link in mat.node_tree.links:
                    if link.to_node is principled and link.to_socket is inp \
                            and link.from_node.type == "TEX_IMAGE":
                        image = link.from_node.image
        if image is None:
            tex = next((n for n in mat.node_tree.nodes
                        if n.type == "TEX_IMAGE" and n.image is not None), None)
            if tex is not None:
                image = tex.image
    if getattr(mat, "blend_method", "OPAQUE") in ("CLIP", "HASHED"):
        alpha_mode = "MASK"
    elif getattr(mat, "blend_method", "OPAQUE") == "BLEND":
        alpha_mode = "BLEND"
    double_sided = not mat.use_backface_culling
    return image, rgba, alpha_mode, double_sided


def _resolve_image_file(image, search_dirs):
    """画像の実ファイルを探す。FBXは外部参照が切れていることが多いので、
    Blenderの解決パス → アバター周辺フォルダのファイル名一致 の順で捜索する。"""
    try:
        p = bpy.path.abspath(image.filepath) if image.filepath else ""
    except Exception:
        p = ""
    if p and os.path.exists(p):
        return p
    base = os.path.basename(p) or image.name
    base = re.sub(r"\.\d{3}$", "", base)  # 'body.png.002' → 'body.png'
    if "." not in base:
        base += ".png"
    for d in search_dirs:
        cand = os.path.join(d, base)
        if os.path.exists(cand):
            return cand
    return None


def extract_materials_from_unity_map(meshes, orig_names, tex_dir, fbx_dir,
                                     map_path, warnings):
    """Unityエクスポータのmaterial_map.jsonからスロット表を作る(FBX入力の本命)。
    Unity側で実際に着ているマテリアル(lilToon差し替え済み)の実テクスチャが
    レンダラー名×スロット番号で来るので、FBX内の材質名のズレに影響されない。"""
    os.makedirs(tex_dir, exist_ok=True)
    with open(map_path, encoding="utf-8") as f:
        data = json.load(f)
    mesh_map = data.get("meshes", {})
    slots = {}
    sig_to_mat = {}
    tex_cache = {}

    def copy_tex(unity_file):
        if unity_file in tex_cache:
            return tex_cache[unity_file]
        src = os.path.join(fbx_dir, unity_file)
        if not os.path.exists(src):
            # dev#1104(実報告V9QTNUMH): material_map.jsonの"texture"フィールドは
            # 非nullなのに、実際のPNGファイルがFBXの隣に無いケース(理由は
            # Unity側の書き出し失敗・パス問題等、ここからは特定不能)。
            # 従来はここで無警告のままNoneへ静かに縮退し、呼び出し元は
            # base_color(多くのlilToonアバターで白 [1,1,1,1])のみのマテリアルを
            # 作る。プレビューのガンマ/露出補正(render_preview.py:
            # PREVIEW_GAMMA=1.3, PREVIEW_EXPOSURE=1.0)と組み合わさると、この
            # 白ベースカラーが完全な白飛びとして見える
            # (「成功したのに結果が変」——他マテリアルは正常なため見た目からは
            # 原因不明。ログに1行残すことで次回以降は診断可能にする)。
            warnings.append(
                f"texture not found: {unity_file} (referenced by "
                "material_map.json but missing next to the exported FBX) — "
                "will use a solid color")
            tex_cache[unity_file] = None
            return None
        ext = os.path.splitext(unity_file)[1].lower()
        if ext == ".png" and not vp_tex.is_real_png(src):
            # dev#990(実報告3JMQWCNS): 拡張子だけ.pngにリネームされた非PNG。
            # prefab/Unity-FBX経由(material_map.json)もextract_materials()と
            # 同じマジックナンバー検証を通す。
            warnings.append(
                f"<not-actually-png:{unity_file}> texture has a .png extension "
                "but is not actually a PNG file — will use a solid color")
            return None
        out_name = f"t{len(tex_cache):02d}" + ext
        out_path = os.path.join(tex_dir, out_name)
        shutil.copy(src, out_path)
        apply_matte_if_enabled(out_path)
        tex_cache[unity_file] = out_name
        return out_name

    for obj in meshes:
        orig = orig_names.get(obj.name, obj.name)
        entries = mesh_map.get(orig)
        if entries is None:
            warnings.append(f"mesh not in material_map.json: {orig} (will use a solid color)")
            entries = []
        n_slots = max(len(obj.material_slots), 1)
        if obj.data.materials is None or len(obj.data.materials) == 0:
            obj.data.materials.append(None)
        for i in range(len(obj.material_slots)):
            info = entries[i] if i < len(entries) else None
            tex_file = copy_tex(info["texture"]) if info and info.get("texture") else None
            color = tuple(info.get("color", [1, 1, 1, 1])) if info else (0.5, 0.5, 0.5, 1.0)
            ds = bool(info.get("double_sided")) if info else False
            mat_name = info.get("material_name", "") if info else ""
            # dev#30残タスク: Unityエクスポータ(unity\DiveToPalworldExporter.cs
            # ExportMaterials、D2P_SECONDALBEDO_PURE_BEGIN/END)が検出した
            # 「2枚目/3枚目アルベドテクスチャ(lilToonのMain2nd/Main3rd等)が
            # 有効」フラグ。焼き込みはしない(検出のみ)。旧形式の
            # material_map.json(このフィールドが無い)では常にFalse扱い
            second_albedo = bool(info.get("second_albedo_detected")) if info else False
            sig = (tex_file, color, ds)
            if sig not in sig_to_mat:
                slot = f"m{len(sig_to_mat):02d}"
                m = bpy.data.materials.new(slot)
                m.use_nodes = True
                m.diffuse_color = color
                sig_to_mat[sig] = m
                slots[slot] = {
                    "orig_name": mat_name, "texture": tex_file,
                    "base_color": [round(c, 5) for c in color],
                    "alpha_mode": "MASK", "double_sided": ds,
                    "second_albedo_detected": second_albedo,
                }
                print(f"[{TAG}] slot {slot}: '{mat_name}' tex={tex_file} (unity map)")
                if second_albedo:
                    warnings.append(
                        f"second-layer albedo texture detected on material "
                        f"'{mat_name}' (slot {slot}) — only the main texture is "
                        f"carried over, this layer (e.g. a cheek-blush decal) "
                        f"will not appear on the converted model")
            elif second_albedo and not slots[sig_to_mat[sig].name]["second_albedo_detected"]:
                # 同一シグネチャ(tex/color/両面)を共有する別マテリアルが後から
                # フラグ有りで来た場合はORで拾う(先勝ちで見逃さない)
                slots[sig_to_mat[sig].name]["second_albedo_detected"] = True
                warnings.append(
                    f"second-layer albedo texture detected on material "
                    f"'{mat_name}' (slot {sig_to_mat[sig].name}) — only the "
                    f"main texture is carried over, this layer (e.g. a "
                    f"cheek-blush decal) will not appear on the converted model")
            obj.material_slots[i].material = sig_to_mat[sig]
        if len(obj.material_slots) < len(entries):
            warnings.append(f"slot count mismatch: {orig} "
                            f"(blender={len(obj.material_slots)} unity={len(entries)})")
    return slots


def extract_materials(meshes, tex_dir, warnings, search_dirs):
    """マテリアルをm00..に改名し、テクスチャとスロット表を作る。"""
    os.makedirs(tex_dir, exist_ok=True)
    mats = []
    for obj in meshes:
        if not obj.data.materials:
            fallback = bpy.data.materials.new("vrm2pal_fallback")
            fallback.diffuse_color = (0.5, 0.5, 0.5, 1.0)
            obj.data.materials.append(fallback)
            warnings.append(f"assigned gray to mesh with no material: {obj.name}")
        for m in obj.data.materials:
            if m is not None and m not in mats:
                mats.append(m)
    slots = {}
    saved_images = {}
    for i, mat in enumerate(mats):
        orig = mat.name
        slot = f"m{i:02d}"
        image, rgba, alpha_mode, double_sided = get_base_color(mat)
        tex_file = None
        if image is not None:
            if image.name in saved_images:
                tex_file = saved_images[image.name]
            else:
                src = _resolve_image_file(image, search_dirs)
                ext = (os.path.splitext(src)[1].lower() or ".png") if src is not None else None
                if src is not None and ext == ".png" and not vp_tex.is_real_png(src):
                    # dev#990(実報告3JMQWCNS): 拡張子だけ.pngにリネームされた
                    # 非PNG(JPEG/BMP等)。マジックナンバーで弾き、以前は後段
                    # (atlas_bake)まで運ばれて落ちていたのを入口で止める。
                    warnings.append(
                        f"<not-actually-png:{os.path.basename(src)}> texture for "
                        f"{orig} has a .png extension but is not actually a PNG "
                        "file — will use a solid color")
                elif src is not None:
                    # 実ファイルがあればそのままコピー(再圧縮なし。png/jpg/tga可)
                    tex_file = f"t{len(saved_images):02d}{ext}"
                    out = os.path.join(tex_dir, tex_file)
                    shutil.copy(src, out)
                    apply_matte_if_enabled(out)
                    saved_images[image.name] = tex_file
                elif image.has_data:
                    # 埋め込み画像(VRM等)はBlender経由でPNG化
                    tex_file = f"t{len(saved_images):02d}.png"
                    out = os.path.join(tex_dir, tex_file)
                    img_copy = image.copy()  # 元imageのfilepathを汚さない
                    img_copy.filepath_raw = out
                    img_copy.file_format = "PNG"
                    img_copy.save()
                    bpy.data.images.remove(img_copy)
                    apply_matte_if_enabled(out)
                    saved_images[image.name] = tex_file
                else:
                    warnings.append(f"texture not found: {orig} "
                                    f"({image.name}) — will use a solid color. "
                                    "Place the image file in the same folder as the FBX and re-run")
        mat.name = slot
        slots[slot] = {
            "orig_name": orig, "texture": tex_file,
            "base_color": [round(c, 5) for c in rgba],
            "alpha_mode": alpha_mode, "double_sided": double_sided,
        }
        print(f"[{TAG}] slot {slot}: '{orig}' tex={tex_file} alpha={alpha_mode}")
    return slots


# =====================================================================
# dev#1508 受入ゲート正本化: step01スナップショット
# =====================================================================

def _load_json_or_none(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def compute_sway_source_bone_names(job):
    """job["physbones_json"](ファイルパス)/job["springbones"](フラット
    list)から、`sway_allocator.allocate()`(判定ロジックの正本、無改変)を
    実行し、`sway_source_bones.all_accepted_source_bone_names()`
    (配線実装(sway_hub/sway_hub_wire)から独立)で「揺れると判定された
    全ボーン(anchor含む)」の名前集合を返す。

    step02側(`wire_and_diagnose_hub()`)と全く同じ入力
    (physbones_json/springbones_json、capacity省略=既定9)で
    `sway_allocator.allocate()`を呼ぶため、決定論的な純関数として同一の
    判定結果になる(step02が別途実行するアロケータ判定との重複だが、
    ここでの目的はstep01時点のground truthスナップショット対象を確定
    させることであり、判定ロジック自体は変更しない——2回実行しても結果は
    同じ、副作用も無い)。

    dev#1592(#1590取りこぼし修理、2026-08-19): `lab_assignments`は
    `sway_chain_defaults.lab_assignments_from_job()`(step02の
    `_lab_assignments_from_job()`と同じ共有関数)でjob["sway_chain_
    overrides"]のenabled上書きを反映してから渡す——省略(None)のままだと
    偏向判定のみで決まるため、GUIでenabled:trueへ上書きした既定OFF鎖の
    頂点ウェイトがこのスナップショットに記録されず、step02側(#1590で
    正しく配線済み)の対象骨集合と食い違って`sway_source_gate`が誤FAIL
    する(issue #1592、オーナー実測)。`weighted_bone_names`は省略
    (None、`lab_assignments_from_job()`docstring参照)——本関数の
    `physbone_entries`/`springbone_entries`はstep02のように事前に
    weighted-onlyへフィルタされていない生catalogのままであり、override
    側の生bones([anchor, node1, ...])とそのまま突き合わせて一致する。

    physbones_json/springbonesが両方無い/空なら空集合(=非swayジョブ、
    完全no-op)。"""
    physbones_raw = _load_json_or_none(job.get("physbones_json"))
    springbones_raw = {"springbones": list(job.get("springbones") or [])}
    if physbones_raw is None and not job.get("springbones"):
        return frozenset()
    physbone_entries = list((physbones_raw or {}).get("physbones", []) or [])
    springbone_entries = list(job.get("springbones") or [])
    lab_assignments = sway_chain_defaults.lab_assignments_from_job(
        job, physbone_entries, springbone_entries)
    plan = sway_allocator.allocate(
        physbones_json=physbones_raw, springbones_json=springbones_raw,
        lab_assignments=lab_assignments)
    return sway_source_bones.all_accepted_source_bone_names(plan)


def _bone_local_transform(bone):
    """dev#1508 受入ゲート正本化(2026-08-16実データ検証で訂正): 回転は
    donor側がlook-at再構成のため生クォータニオンでは比較できない
    (`sway_source_gate.py`モジュールdocstring「回転の比較方法」節)。
    ここではpos(head)/tail/scaleのみを記録し、向きの比較はtail-head
    方向ベクトルで行う(呼び出し側=`sway_source_gate.check_bone_transform()`)。"""
    m = bone.matrix_local
    scale = m.to_scale()
    return {
        "pos": [bone.head_local.x, bone.head_local.y, bone.head_local.z],
        "tail": [bone.tail_local.x, bone.tail_local.y, bone.tail_local.z],
        "scale": [scale.x, scale.y, scale.z],
    }


def _bone_vertex_weights(bone_name, meshes):
    """全meshesを走査し、`bone_name`という名前の頂点グループを持つメッシュ
    それぞれについて、{mesh名: {頂点index(str): weight}}(weight>0の頂点
    のみ)を返す。1頂点グループも見つからなければ空dict。"""
    out = {}
    for obj in meshes:
        vg = obj.vertex_groups.get(bone_name)
        if vg is None:
            continue
        idx = vg.index
        per_vertex = {}
        for v in obj.data.vertices:
            for g in v.groups:
                if g.group == idx and g.weight > 0.0:
                    per_vertex[str(v.index)] = g.weight
                    break
        if per_vertex:
            out[obj.name] = per_vertex
    return out


def build_sway_source_snapshot(job, arm, meshes, warnings):
    """dev#1508 受入ゲート正本化: 「揺れると判定された全ボーン」
    (`compute_sway_source_bone_names()`)について、step01時点(=このまま
    step01_clean.blendへ保存される直前)のtransform(位置・回転・スケール、
    armature空間のlocal matrix)+全meshにおける頂点ウェイトテーブルを
    dictで返す(`{bone名: {"pos":...,"rot":...,"scale":...,"weights":
    {mesh名: {vidx: w}}}}`)。

    step02受入ゲート(`pipeline\\blender\\step02_retarget.py`
    `_sway_gate_run()`)の右辺比較のうち、**頂点ウェイトの左辺**として
    そのまま使う(mesh名・頂点indexがstep01→step02で不変なため、直接
    比較が意味を持つ——`sway_source_gate.py`モジュールdocstring参照)。
    位置/回転/スケールはアバター全体のグローバルスケール・retargetを
    経るため、本スナップショットの値は記録・事後診断用途(このJSONを
    見ればstep01時点の実座標が分かる)であり、ゲート本体の位置比較には
    使わない(step02側がavatar_arm実測値を独立に再取得する、
    `sway_source_gate.py`モジュールdocstring参照)。

    対象骨がarmatureに実在しない(名前解決できない、$GUID付き骨がFBX
    インポートで変質した等)場合はそのボーンをスキップしログへ警告する
    (die()しない、既存の安全側フォールバック方針を踏襲)。"""
    bone_names = compute_sway_source_bone_names(job)
    if not bone_names:
        return {}
    snapshot = {}
    missing = []
    for name in sorted(bone_names):
        bone = arm.data.bones.get(name)
        if bone is None:
            missing.append(name)
            continue
        entry = _bone_local_transform(bone)
        entry["weights"] = _bone_vertex_weights(name, meshes)
        snapshot[name] = entry
    if missing:
        msg = (f"sway_source_snapshot: {len(missing)} judged-swaying bone(s) "
               f"not found in armature (will not be checkable by the accept "
               f"gate): {missing}")
        warnings.append(msg)
        print(f"[{TAG}][WARN] {msg}")
    return snapshot


def main():
    job, _ = vp_bl.load_job_from_argv()
    if not os.path.exists(job["vrm_path"]):
        core.die(TAG, f"VRM not found: {job['vrm_path']}")
    out_dir = core.job_subdir(job, "converted")
    tex_dir = core.job_subdir(job, "textures")
    warnings = []

    is_fbx = job["vrm_path"].lower().endswith(".fbx")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if is_fbx:
        humanoid_json = find_humanoid_json(job)
        arm, source_parent_bone = import_fbx_avatar(
            job, warnings, humanoid_json=humanoid_json)
        # dev#1551 laneC2: "_end"等の重み無し末端マーカー骨のtail長を、
        # Unity側サイドカー(leaf_marker_bones.json、有れば)で決定的に復元する。
        # VRM入力・サイドカー無しの旧Unity輸出物ではno-op。
        leaf_marker_json = find_leaf_marker_bones_json(job)
        fix_leaf_marker_bone_tails(arm, leaf_marker_json, warnings)
    else:
        vp_bl.ensure_vrm_addon(job)
        arm = import_vrm(job, warnings)
        source_parent_bone = {}
    meshes, orig_names = cleanup_objects(arm, warnings)
    # 入口での正規化(公開issue #18・dev#299): 制作者が編集時に表示を切ったまま
    # 保存したArmatureモディファイア(show_viewport/show_render=False)を強制
    # ONにする。また、上のcleanup_objectsで破棄された重複Armatureを指していた
    # ままの、ターゲット参照切れ(object=None)のArmatureモディファイアを除去
    # する(dev#299: 表示フラグがTrueでもBlenderはこれを「無効」と判定し、
    # 放置するとstep02のmodifier_applyが「モディファイアーはOFFです」相当の
    # RuntimeErrorで停止する)。いずれもエラーにせずログを残して進む。
    for mesh_name, _mod, reasons in vp_modnorm.normalize_armature_modifiers(
            meshes, tag=TAG):
        if reasons == vp_modnorm.ORPHAN_TARGET_REASON:
            warnings.append(
                f"armature modifier on '{mesh_name}' had no target armature "
                f"(orphaned reference, likely a discarded duplicate "
                f"Armature) and was removed")
        else:
            warnings.append(
                f"disabled armature modifier on '{mesh_name}' was forced ON "
                f"({', '.join(reasons)})")
    apply_transforms(arm)
    drop_shape_keys(job, warnings, orig_names)
    # FBXにSpringBone情報は無い(PhysBone等はUnityコンポーネント側のため)
    spring_roots = [] if is_fbx else extract_spring_roots(arm)
    # dev#1508 W1b: sway_allocatorが読める完全スキーマ(anchor/chains/params)
    # へ変換し、同一プロセス内のcompute_sway_source_bone_names()/
    # build_sway_source_snapshot()がすぐ使えるようjob["springbones"]へ
    # 差し込む(prefab経路のjob["physbones_json"]と対称な役割)。step02は
    # 別プロセスのためjob dictの直接共有ができない——下のconverted\
    # springbones.jsonサイドカー書き出しが正式な受け渡し経路
    # (step02_retarget.py main()の入口正規化参照)。
    springbone_components = [] if is_fbx else extract_springbone_components(arm)
    job["springbones"] = springbone_components
    clear_bone_constraints(arm)
    meshes = drop_bone_meshes(arm, meshes, job.get("drop_bones", []), warnings)
    # dev#1168前半(ラボ機能「メッシュ削除」): job["drop_meshes"]は空リストが
    # 既定(ラボ憲章④=未実装状態と完全同一)。drop_bone_meshes()の直後に置く
    # ことで、ボーン削除で既に消えたメッシュへの重複警告を避け、orig_names
    # (cleanup_objects()の戻り値、まだ生存メッシュぶんのみ有効)をそのまま
    # 使い回せる。
    meshes = drop_named_meshes(meshes, orig_names, job.get("drop_meshes", []), warnings)
    # 非スキンメッシュ(帽子・リボン等)の元の親ボーン名を、リネーム後の最終
    # メッシュ名(geo_XX)へ付け替えてmetaへ渡す。drop_bones等で消えたメッシュは
    # 自然に脱落する。値がNone(遡っても見つからない)のものは記録しない
    # (step02側はunskinned_source_boneに無ければ従来通りpelvis救済へ回る)。
    survivor_names = {o.name for o in meshes}
    unskinned_source_bone = {}
    for new_name, orig in orig_names.items():
        if new_name not in survivor_names:
            continue
        bone_name = source_parent_bone.get(orig)
        if bone_name:
            unskinned_source_bone[new_name] = bone_name
    if unskinned_source_bone:
        print(f"[{TAG}] unskinned source bone: {unskinned_source_bone}")

    if is_fbx:
        pal_map = vp_bl.humanoid_map_from_json(arm, humanoid_json, warnings)
        spec = "fbx+humanoid.json"
    else:
        pal_map, spec = vp_bl.humanoid_to_pal_map(arm)
        # dev#1260: FBX経路はvp_bl.humanoid_map_from_json内で必須ボーン充足の
        # 判定(die()の可能性がある)より前に重複armature診断
        # (vp_bl.log_duplicate_bone_warning、dev#1174のfind_mapped_bone_duplicates)
        # を実行済み(die()経路でもログへ届くようにするため)。VRM経路には
        # 同等の事前診断が無かったので、ここで同じ順序に揃える。骨格全体の
        # 無差別走査ではなく、実際にマッピングされたボーンの周辺だけを見る
        # (vp_dup_armature.pyのスコープ判断どおり、尻尾チェーン等の正常構造を
        # 誤検知しないため)。
        bone_names_all = [b.name for b in arm.data.bones]
        vp_bl.log_duplicate_bone_warning(TAG, pal_map, bone_names_all, warnings)
    print(f"[{TAG}] VRM {spec}, humanoid mapped: {len(pal_map)} pal bones")
    for req in vp_bl.REQUIRED_PAL_BONES:
        if req not in pal_map:
            # dev#233: 内部pal_bone名(例: foot_l)はユーザーに意味が通じないため、
            # Unity側のConfigure Avatar上の表示名(例: Left Foot)+対処手順に変換して出す
            core.die(TAG, vp_bl.missing_humanoid_bone_message(req))
    if "clavicle_l" not in pal_map:
        warnings.append("no shoulder (clavicle) bone — the shoulder slider applies to the upper arm instead")

    # マテリアル/テクスチャの取得。優先順:
    #   1) Unityエクスポータのmaterial_map.json(FBX入力の本命。実際に着ている
    #      マテリアルの実テクスチャがレンダラー名×スロット番号で確定する)
    #   2) FBX/VRM内のマテリアルから推定(テクスチャはアバター周辺フォルダも捜索)
    avatar_dir = os.path.dirname(job["vrm_path"])
    map_path = os.path.join(avatar_dir, "material_map.json")
    if is_fbx and os.path.exists(map_path):
        slots = extract_materials_from_unity_map(
            meshes, orig_names, tex_dir, avatar_dir, map_path, warnings)
    else:
        search_dirs = [avatar_dir] + [os.path.join(avatar_dir, d)
                                      for d in sorted(os.listdir(avatar_dir))
                                      if os.path.isdir(os.path.join(avatar_dir, d))]
        slots = extract_materials(meshes, tex_dir, warnings, search_dirs)

    meta = {
        "spec_version": spec,
        "armature": arm.name,
        "meshes": [o.name for o in meshes],
        "pal_map": pal_map,
        "slots": slots,
        # 全ボーン一覧(drop_bones指定の参考用。上級者向け)
        "bones": [b.name for b in arm.data.bones],
        # VRM定義のSpringBoneルート(揺れ髪の自動対象。頭の子孫のみstep02が採用)
        "spring_roots": spring_roots,
        # 非スキンメッシュ(頂点グループ0。帽子・リボン等)の元の親ボーン名
        # {geo_XX: 実ボーン名}。step02のzero-weight rescueが、pal_mapの逆引き
        # (build_group_targets、祖先walk込み)でパルボーンへ解決して束縛する。
        # 見つからなかった/スキン済みのメッシュはキー自体が無い
        "unskinned_source_bone": unskinned_source_bone,
        "warnings": warnings,
    }
    with open(os.path.join(out_dir, "avatar_meta.json"), "w",
              encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    # dev#1508 W1b: job["springbones"](上でVRM SpringBoneから確定済み)を
    # converted\springbones.json サイドカーへ常に書き出す(空リストでも
    # 書く——step01_sway_snapshot.jsonと同じ「ファイル存在自体を契約に
    # する」設計。prefab側job["physbones_json"]はconvert.ps1がjob.resolved.
    # jsonへ焼き込む=step01/step02双方が同じ$Jobファイルから読めるが、
    # VRMのSpringBoneはBlender内(このプロセス)でしか解析できず、
    # step01/step02は別プロセスで同じ$Jobを個別に再読込するため、
    # job.json自体を書き換える代わりにこのサイドカー経由で渡す
    # ——step02_retarget.py main()の入口正規化がこれを読み戻す)。
    with open(os.path.join(out_dir, "springbones.json"), "w",
              encoding="utf-8") as f:
        json.dump({"format": sway_allocator.SPRINGBONES_FORMAT,
                   "springbones": springbone_components}, f, ensure_ascii=False)

    # dev#1508 受入ゲート正本化(オーナー追加指示2026-08-16): 「揺れると
    # 判定された全ボーン」のstep01時点スナップショット(transform+頂点
    # ウェイト)をbuild配下(予測可能なパス、run束ね化レーンが収集する
    # atlas\)へ保存する。step02受入ゲートの左辺(頂点ウェイト側)として
    # 使う。非swayジョブ(physbones/springbonesが両方空)なら
    # snapshot=={}となり、ファイル自体は書くが中身は空({}) --
    # 完全no-opではなくファイル存在自体を契約にする(step02側の
    # 「ファイルが無い=検証不能」という曖昧さを避ける)。
    atlas_dir = core.job_subdir(job, "build", "atlas")
    sway_snapshot = build_sway_source_snapshot(job, arm, meshes, warnings)
    snapshot_path = os.path.join(atlas_dir, "step01_sway_snapshot.json")
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump({"format": "d2p-sway-source-snapshot-1",
                   "bones": sway_snapshot}, f, ensure_ascii=False)
    print(f"[{TAG}] sway_source_snapshot: {len(sway_snapshot)} bone(s) -> {snapshot_path}")

    out = os.path.join(out_dir, "step01_clean.blend")
    vp_bl.save_mainfile_or_die(TAG, out)
    print(f"[{TAG}] saved: {out}")

    # 同上(オーナー追加指示): オーナーがstep01/step02のblendをBlenderで
    # 並べて目視できるよう、step01のblendもbuild配下(atlas\)へ複製する
    # (実測~10MB、容量許容範囲——オーナー追加指示は容量が問題になる場合
    # のみJSONのみ必須・blend省略可としており、今回は問題無い規模)。
    atlas_blend = os.path.join(atlas_dir, "step01.blend")
    shutil.copyfile(out, atlas_blend)
    print(f"[{TAG}] step01 blend copied for side-by-side review: {atlas_blend}")

    for w in warnings:
        print(f"[{TAG}][WARN] {w}")


main()
