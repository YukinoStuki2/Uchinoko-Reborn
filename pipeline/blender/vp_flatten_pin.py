# -*- coding: utf-8 -*-
r"""D2P平坦化FBXのroot_matピン留め対象の仕分け(dev#1246、2026-08-08)。

背景(実報告TFVNM33V、座標系ずれ→パル騎乗中の浮遊+プレビュー空白):
step01_import_vrm.py の import_fbx_avatar() は、D2P平坦化FBX(Unity
DiveToPalworldExporter.FlattenSkinnedMeshes()産)のスキン済みメッシュを
FBXシーンルートの行列(root_mat)へ強制ピン留めする(SkinnedMeshRendererの
頂点をバインド時ワールドへ焼き込み、ルート直下・ローカル原点へ再配置する
Unity側の前提と対にする処理)。

旧判定基準「頂点グループを1つでも持つか」には反例があった: 入れ子
(名前衝突)Armatureを持つアバターでは、装飾小物(例: AccessoryCube)が
本体armとは別の、後段cleanup_objects()で破棄される副次Armatureへ
スキンされている場合がある。このメッシュも頂点グループを持つため
「スキン済み」と誤判定されroot_matへピン留めされていたが、そのウェイトは
本体armのどのボーンにも対応せず(破棄される副次Armatureのボーン名)、
「root_matへ揃える」という平坦化の前提自体が成立しない。結果、そのメッシュは
骨格原点から2000cm超も離れた無意味な座標へ固定され、後段のsnap_to_ground()の
最小Z算出まで巻き込んで全体の接地位置を狂わせ、プレビューが画角外(空白)に
なる実害を実測した(work\rd_1246_verify\PROGRESS.md)。

「本体armのボーンへのウェイトを1つでも持つか」(頂点グループ"名"が実際に
本体armのボーン名と一致するか)で判定し直す。2026-07-26 agyo検体の教訓
(Unity FBX Exporterが単一ボーン100%ウェイトのスキンメッシュをArmature
モディファイア無しで最適化書き出しするケース)はこの判定でも壊さない
——頂点グループ名は本体armの実ボーン名のままなので、name照合なら正しく
skinned判定される。「Armatureモディファイアの有無」を判定基準にしては
いけない、という2026-07-26の既存の教訓(このファイルの主docstring参照)は
維持される。

このモジュールはbpy非依存(ダックタイピング、vp_modnorm.py/vp_dup_armature.pyと
同じ設計方針)で、Blender外のtests/coverage/selftestから直接検証できる。
"""


def classify_flatten_pin_targets(meshes, arm_bone_names):
    """D2P平坦化FBXのroot_matピン留め対象を仕分ける。

    meshes: `.name` と `.vertex_groups`(各要素が `.name` を持つ)を備えた
        オブジェクトの列。bpyのObjectでそのまま動くが、bpyには依存しない。
    arm_bone_names: 本体アーマチュア(`arm`)のボーン名の集合
        (set等、`in`演算子が使えればよい)。

    返り値: (skinned_names, unskinned_names) の2つの集合(set)。
    skinned_names = root_matへピン留めすべきメッシュ名の集合
        (頂点グループが1つでも本体armのボーン名と一致するメッシュ)。
    unskinned_names = 元のTransform位置を保持すべきメッシュ名の集合
        (頂点グループが無い、または全て本体arm以外のボーン名を指すメッシュ)。
    """
    skinned_names = {
        o.name for o in meshes
        if any(vg.name in arm_bone_names for vg in o.vertex_groups)
    }
    unskinned_names = {o.name for o in meshes} - skinned_names
    return skinned_names, unskinned_names
