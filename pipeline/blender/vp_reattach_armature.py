# -*- coding: utf-8 -*-
"""複数Armature検出時、破棄されるArmatureに束縛されたメッシュを選ばれた
Armatureへ付け替える(dev#1318、実報告35TX8ERY)。

背景: import_vrm()は複数のArmatureオブジェクトが読み込まれた場合、ボーン数
最大の1つを選び、残りを破棄する(dev#1174)。このとき、選ばれなかった
Armatureに親子付け(`.parent`)またはArmatureモディファイア(`.modifiers`の
`object`)で束縛されたメッシュ(=衣装・アクセサリ等が別リグを持つ場合の
その本体)は、直後のcleanup_objects()の
「`obj.parent is arm` または対象armへのArmatureモディファイアを持つ」
判定に一致せず、**無警告のまま削除**されていた。

実報告35TX8ERYの診断ログでは、成功した変換(v2.9.1)のstep01出力に
'Body'/'BodyCat'メッシュしか現れず、同アバターの別ログ(v2.3.13時点)に
写っていた'Hoodie'(衣装)メッシュへの言及が完全に消えていた——警告0件の
まま衣装が消えていたことがこの構造欠陥の直接証拠になる。
vp_dup_armature.pyのdocstring(dev#1174)にも35TX8ERYは重複Armature検出の
実例として記録済みで、VRMアドオンが出す大量の
`[VRM Add-on:WARNING] Duplicated VRM0 bone: ...` は「2本のArmatureが同名の
ボーンを持つ複製骨格である」ことを示している。同名なら頂点グループ名
(=ボーン名)は選ばれたArmatureでもそのまま通用するため、親子付けと
Armatureモディファイアの対象だけ選ばれたArmatureへ付け替えれば、削除する
ことなく正しく再構成できる(ボーン名が一致しない場合でも、束縛が消えた
静止メッシュとして残る方が、無警告で消滅するより常に良い)。

vp_modnorm.py/vp_flatten_pin.pyと同じ設計方針: bpy非依存(ダックタイピング)
で、Blender外のテストから直接検証できる。
"""


def reattach_meshes_from_discarded_armatures(meshes, chosen_arm, discarded_arms,
                                              tag="vp_reattach", log=print):
    """discarded_armsに束縛されたメッシュをchosen_armへ付け替える。

    meshes: `.name` `.parent`(書込可) `.modifiers`(各要素が`.type`
        `.object`(書込可)を持つ)を備えたオブジェクトの列。親子付けを
        変更する対象は追加で `.matrix_world`(コピー可・書込可、ワールド
        変換の維持用)`.parent_type` `.parent_bone`(いずれも書込可)を
        使う。
    chosen_arm: 選ばれたArmatureオブジェクト。
    discarded_arms: 破棄されるArmatureオブジェクトの列(空でもよい)。
    tag: ログ行の先頭タグ。
    log: ログ出力関数(既定print。テストでは記録用に差し替え可)。

    返り値: 付け替えたメッシュ名のリスト(何も無ければ空リスト)。
    """
    discarded_ids = {id(a) for a in discarded_arms}
    if not discarded_ids:
        return []
    reattached = []
    for o in meshes:
        parent = getattr(o, "parent", None)
        parent_is_discarded = parent is not None and id(parent) in discarded_ids
        mods_to_fix = [
            m for m in getattr(o, "modifiers", ())
            if getattr(m, "type", None) == "ARMATURE"
            and getattr(m, "object", None) is not None
            and id(m.object) in discarded_ids
        ]
        if not parent_is_discarded and not mods_to_fix:
            continue
        if parent_is_discarded:
            # ワールド変換を保ったまま親だけ差し替える(座標が飛ばないよう
            # matrix_worldを退避 -> 親変更 -> 書き戻す)。parent_type/
            # parent_boneはOBJECTへ正規化する(破棄されるArmature側の
            # ボーン名を参照したままにしない)。
            world = o.matrix_world.copy()
            o.parent = chosen_arm
            o.parent_type = "OBJECT"
            o.parent_bone = ""
            o.matrix_world = world
        for m in mods_to_fix:
            m.object = chosen_arm
        reattached.append(o.name)
    if reattached:
        log(f"[{tag}] reattached mesh(es) bound to a discarded duplicate "
            f"Armature onto the main skeleton (bone names carry over "
            f"unchanged; typically an outfit/accessory with its own "
            f"duplicate-named rig): {reattached}")
    return reattached
