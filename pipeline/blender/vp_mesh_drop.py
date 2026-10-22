# -*- coding: utf-8 -*-
r"""dev#1168前半(ラボ機能「メッシュ削除」)のメッシュ照合ロジック(bpy非依存)。

GUI(app_py\ui\mesh_delete_dialog.py)が提示するチェックリストは「元の
メッシュ名」(VRMのノード名、またはUnity輸出時のRenderer名。いずれも
step01_import_vrm.py の cleanup_objects() がgeo_XXへ強制リネームする前の
名前)で構成される。step01_import_vrm.py 側は既にgeo_XXへリネーム済みの
オブジェクトしか持たないため、リネーム後の現在名(obj.name)と元の名前
(orig_names、cleanup_objects()の戻り値)の対応表を介して照合する必要が
ある——この対応付けと集合演算だけを切り出し、vp_flatten_pin.py/
vp_dup_armature.pyと同じ設計方針(ダックタイピング、bpy非依存、
tests\coverage\selftestから直接検証可能)で純関数化する。

既存のdrop_bone_meshes()(ボーン名基準、頂点単位の部分削除も行う)とは
別物: メッシュ削除ラボ機能は常にオブジェクト単位の全削除であり、部分削除
ロジックを必要としないため、この関数は「削除対象の現在名の集合」を返す
だけに留める(bpy.data.objects.remove()の呼び出し自体はstep01_import_vrm.py
側が担当)。
"""


def classify_mesh_drop_targets(mesh_names, orig_names, drop_names):
    """mesh_names: 現在のオブジェクト名の列(通常geo_XX、リネーム後)。
    orig_names: {現在名: 元の名前} の対応表
        (step01_import_vrm.cleanup_objects()の戻り値をそのまま渡せる)。
    drop_names: 削除対象として指定された「元の名前」の集合
        (GUIチェックリストでチェックを外した分、job["drop_meshes"])。

    返り値: (to_remove, missing) の2つのset。
    to_remove = 削除すべき現在名(通常geo_XX)の集合。
    missing = drop_namesのうち、mesh_names側に一致する元の名前が
        1つも無かったもの(警告用。drop_bone_meshesの
        "bone not found"警告と同じ役割——チェックリストUIでは通常
        起こらないが、アバターを差し替えた後に古い保存状態が残っている
        場合等に備える)。
    """
    targets = set(drop_names)
    to_remove = set()
    matched = set()
    for name in mesh_names:
        orig = orig_names.get(name, name)
        if orig in targets:
            to_remove.add(name)
            matched.add(orig)
    missing = targets - matched
    return to_remove, missing
