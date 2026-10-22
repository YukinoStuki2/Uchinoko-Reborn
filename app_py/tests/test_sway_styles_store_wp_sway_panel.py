# test_sway_styles_store_wp_sway_panel.py -- ラボ「ゆれかた」統合パネル
# (work\wp_sway_panel\BRIEF.md、SPEC.md §2)。app_py\sway_styles_store.py の
# 単体テスト(ラボ憲章④無退行+負の対照、round-trip、マイグレーション)。
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import lab_raw_sway_params_store as raw_store  # noqa: E402
import sway_chain_override_store as chain_store  # noqa: E402
import sway_styles_store as store  # noqa: E402

AVATAR = "C:\\fake\\Avatar.vrm"
OTHER_AVATAR = "C:\\fake\\Other.vrm"


def _catalog_two_chains():
    return [
        {"anchor": "Hips", "bones": ["Hips", "Tail_01", "Tail_02"], "node_count": 2},
        {"anchor": "Head", "bones": ["Head", "EarL_01", "EarL_02"], "node_count": 2},
    ]


# ---------------------------------------------------------------------------
# 1. ラボ憲章④: 既定値のとき出力ゼロ + 負の対照。
# ---------------------------------------------------------------------------

def test_fresh_store_is_fully_default(tmp_path):
    app_root = str(tmp_path)
    assert store.load_custom_styles(app_root) == {}
    assert store.load_assignments(app_root, AVATAR) == []
    assert store.is_active(app_root, AVATAR) is False
    assert store.state_summary(app_root, AVATAR) is None
    assert store.get_job_override(app_root, AVATAR) is None


def test_negative_control_one_assignment_makes_job_appear(tmp_path):
    """負の対照: 鎖への割当を1件入れるとjobに現れる。"""
    app_root = str(tmp_path)
    store.save_state(app_root, AVATAR, {}, [{"bones": ["Hips", "Tail_01"], "style": "hard"}])
    assert store.is_active(app_root, AVATAR) is True
    override = store.get_job_override(app_root, AVATAR)
    assert override is not None
    assert override["assignments"] == [{"bones": ["Hips", "Tail_01"], "style": "hard"}]
    assert override["styles"]["hard"] == store.BUILTIN_STYLE_PARAMS["hard"]


def test_negative_control_orphan_custom_style_does_not_appear_in_job(tmp_path):
    """負の対照(逆側): カスタムを作成しただけで、どの鎖にも割り当てていない
    場合はjobに現れない(BRIEF受入ゲート1の解釈、docstring参照)。"""
    app_root = str(tmp_path)
    custom = {"MyStyle": {**{k: 0.0 for k in store.STYLE_PARAM_KEYS}, "stiffness": 0.9}}
    store.save_state(app_root, AVATAR, custom, [])
    assert store.load_custom_styles(app_root) == custom
    assert store.is_active(app_root, AVATAR) is False
    assert store.get_job_override(app_root, AVATAR) is None


def test_assignment_with_none_style_is_never_persisted(tmp_path):
    app_root = str(tmp_path)
    store.save_state(app_root, AVATAR, {}, [
        {"bones": ["Hips", "Tail_01"], "style": store.NONE_STYLE},
        {"bones": ["Head", "EarL_01"], "style": "soft"},
    ])
    loaded = store.load_assignments(app_root, AVATAR)
    assert loaded == [{"bones": ["Head", "EarL_01"], "style": "soft"}]


# ---------------------------------------------------------------------------
# 2. round-trip + アバタースコープ + 破損ファイル安全側フォールバック。
# ---------------------------------------------------------------------------

def test_save_then_load_round_trip(tmp_path):
    app_root = str(tmp_path)
    custom = {"MyStyle": {
        "stiffness": 0.4, "damping": 0.6, "wdl": 0.1, "wdr": 0.2, "gravity_z": -50.0,
        "limit_angle": 30.0, "fake_pitch": 10.0, "fake_roll": -10.0,
        "fake_yaw": 5.0,
    }}
    assignments = [{"bones": ["Hips", "Tail_01", "Tail_02"], "style": "MyStyle"}]
    store.save_state(app_root, AVATAR, custom, assignments)
    assert store.load_custom_styles(app_root) == custom
    assert store.load_assignments(app_root, AVATAR) == assignments


def test_assignments_are_scoped_per_avatar(tmp_path):
    app_root = str(tmp_path)
    store.save_state(app_root, AVATAR, {}, [{"bones": ["Hips", "Tail_01"], "style": "soft"}])
    assert store.load_assignments(app_root, AVATAR) != []
    assert store.load_assignments(app_root, OTHER_AVATAR) == []


def test_custom_styles_are_global_across_avatars(tmp_path):
    app_root = str(tmp_path)
    custom = {"MyStyle": {k: 0.0 for k in store.STYLE_PARAM_KEYS}}
    store.save_state(app_root, AVATAR, custom, [])
    assert store.load_custom_styles(app_root) == custom
    # 別アバターとして読んでも(assignmentsは空になるが)customは変わらず読める。
    assert store.load_custom_styles(app_root) == custom


def test_corrupt_state_file_falls_back_to_defaults(tmp_path):
    app_root = str(tmp_path)
    with open(store._state_path(app_root), "w", encoding="utf-8") as f:  # noqa: SLF001
        f.write("{ not valid json")
    assert store.load_custom_styles(app_root) == {}
    assert store.load_assignments(app_root, AVATAR) == []


def test_reset_clears_everything(tmp_path):
    app_root = str(tmp_path)
    store.save_state(app_root, AVATAR, {"S": {k: 0.0 for k in store.STYLE_PARAM_KEYS}},
                      [{"bones": ["Hips", "Tail_01"], "style": "S"}])
    assert store.is_active(app_root, AVATAR) is True
    store.reset(app_root)
    assert store.load_custom_styles(app_root) == {}
    assert store.load_assignments(app_root, AVATAR) == []
    assert store.is_active(app_root, AVATAR) is False


def test_clear_avatar_assignments_keeps_custom_styles(tmp_path):
    app_root = str(tmp_path)
    custom = {"S": {k: 0.0 for k in store.STYLE_PARAM_KEYS}}
    store.save_state(app_root, AVATAR, custom, [{"bones": ["Hips", "Tail_01"], "style": "S"}])
    store.clear_avatar_assignments(app_root, AVATAR)
    assert store.load_custom_styles(app_root) == custom
    assert store.load_assignments(app_root, AVATAR) == []


# ---------------------------------------------------------------------------
# dev#1551 laneG5修理(症状③「既定値に戻す→TailRootまで消える」の根本修理、
# work\run_1551\gui_verify\RESULT.md追送・コーディネータ確定裁定2026-08-17):
# reset/clear_avatar_assignmentsが保存内容を実質空にするとき、空JSONを
# 書くのではなく状態ファイル自体を削除し、`load_state_with_migration()`の
# 一回限り移行判定(os.path.exists()ベース)を再びTrueにできることを検証する。
# ---------------------------------------------------------------------------

def test_reset_deletes_state_file_so_migration_can_rerun(tmp_path):
    """正: reset()は空JSONを残さずファイル自体を消す。カタログに尻尾/耳が
    含まれる場合、reset後の次回load_state_with_migration()は
    「一度も保存されていない」扱いに戻り、native-donor既定が再び現れる
    (=「既定値に戻す」が文字どおり既定値を復元する、症状③の直接の再現+
    修理確認)。"""
    app_root = str(tmp_path)
    catalog = _catalog_two_chains()  # Hips/Tail...=尻尾, Head/EarL...=耳
    store.save_state(
        app_root, AVATAR,
        {"S": {k: 0.0 for k in store.STYLE_PARAM_KEYS}},
        [{"bones": ["Hips", "Tail_01", "Tail_02"], "style": "S"}],
    )
    assert os.path.exists(store._state_path(app_root))  # noqa: SLF001

    store.reset(app_root)

    assert not os.path.exists(store._state_path(app_root))  # noqa: SLF001
    custom_after, assignments_after = store.load_state_with_migration(app_root, AVATAR, catalog)
    assert custom_after == {}
    by_bones = {tuple(a["bones"]): a["style"] for a in assignments_after}
    # native-donor既定(尻尾/耳=ON)が両方とも復元されている――reset前に
    # 「Sという1つのカスタムスタイルだけが尻尾に割当済み」という状態だった
    # のに対し、今度は移行結果(尻尾/耳とも"normal")が見える。
    assert by_bones[("Hips", "Tail_01", "Tail_02")] == "normal"
    assert by_bones[("Head", "EarL_01", "EarL_02")] == "normal"


def test_clear_avatar_assignments_deletes_file_when_no_custom_styles_remain(tmp_path):
    """正(症状③のもう一方の実際の呼び出し経路、ui\\sway_style_dialog.py
    _on_reset()が実際に呼ぶのはclear_avatar_assignments()の方): カスタム
    スタイルを一切定義していない状態でアバターの割当だけ戻すと、
    save_stateへ渡るcustom_styles(=load_custom_styles()の戻り値)も空に
    なるため、reset()と同じくファイルが削除される。"""
    app_root = str(tmp_path)
    catalog = _catalog_two_chains()
    store.save_state(
        app_root, AVATAR, {},  # カスタムスタイルは一切無い
        [{"bones": ["Hips", "Tail_01", "Tail_02"], "style": "hard"}],
    )
    assert os.path.exists(store._state_path(app_root))  # noqa: SLF001

    store.clear_avatar_assignments(app_root, AVATAR)

    assert not os.path.exists(store._state_path(app_root))  # noqa: SLF001
    _custom, assignments_after = store.load_state_with_migration(app_root, AVATAR, catalog)
    by_bones = {tuple(a["bones"]): a["style"] for a in assignments_after}
    assert by_bones[("Hips", "Tail_01", "Tail_02")] == "normal"
    assert by_bones[("Head", "EarL_01", "EarL_02")] == "normal"


def test_clear_avatar_assignments_does_not_delete_file_when_custom_styles_remain(tmp_path):
    """負の対照: グローバルなカスタムスタイル定義が残っている場合は、
    ファイルを削除してはならない(削除すると再マイグレーションが起きて
    しまい、既存の正常系test_clear_avatar_assignments_keeps_custom_stylesの
    前提=カスタム定義がavatar切替後も生き残ることが壊れる)。"""
    app_root = str(tmp_path)
    custom = {"S": {k: 0.0 for k in store.STYLE_PARAM_KEYS}}
    store.save_state(app_root, AVATAR, custom, [{"bones": ["Hips", "Tail_01"], "style": "S"}])

    store.clear_avatar_assignments(app_root, AVATAR)

    assert os.path.exists(store._state_path(app_root))  # noqa: SLF001
    assert store.load_custom_styles(app_root) == custom


def test_assignment_referencing_deleted_custom_style_is_dropped(tmp_path):
    """id参照整合性: assignmentsの中に、custom_stylesにもう存在しないstyle名が
    あれば無視される(壊れたファイルへの多重防御)。"""
    app_root = str(tmp_path)
    path = store._state_path(app_root)  # noqa: SLF001
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "custom_styles": {},
            "avatar_path": store._norm_avatar_path(AVATAR),  # noqa: SLF001
            "assignments": [{"bones": ["Hips", "Tail_01"], "style": "GoneStyle"}],
        }, f)
    assert store.load_assignments(app_root, AVATAR) == []


def test_save_state_does_not_cap_custom_style_count(tmp_path):
    """2026-08-16オーナー裁定: カスタム「ゆれかた」定義の個数上限は撤廃
    (同時に効かせられるスロット数[親骨×ゆれかたで9組]の制限とは別軸)。"""
    app_root = str(tmp_path)
    custom = {f"S{i}": {k: 0.0 for k in store.STYLE_PARAM_KEYS} for i in range(12)}
    store.save_state(app_root, AVATAR, custom, [])
    assert len(store.load_custom_styles(app_root)) == 12
    assert not hasattr(store, "MAX_CUSTOM_STYLES")


def test_resolve_style_params():
    assert store.resolve_style_params("app_root_unused", "hard") == store.BUILTIN_STYLE_PARAMS["hard"]
    assert store.resolve_style_params("app_root_unused", store.NONE_STYLE) is None


def test_style_choice_names_order(tmp_path):
    app_root = str(tmp_path)
    store.save_state(app_root, AVATAR, {"Zeta": {k: 0.0 for k in store.STYLE_PARAM_KEYS},
                                         "Alpha": {k: 0.0 for k in store.STYLE_PARAM_KEYS}},
                      [])
    assert store.style_choice_names(app_root) == [
        "none", "soft", "normal", "hard", "Alpha", "Zeta",
    ]


def test_registry_descriptor_shape():
    import ui.sway_style_dialog as dlg_mod
    d = dlg_mod.LAB_REGISTRY_DESCRIPTOR
    assert d["id"] == "sway_styles"
    assert isinstance(d["name_key"], str)
    for lang in i18n.LANGS:
        assert i18n.S(d["name_key"], lang) and not i18n.S(d["name_key"], lang).startswith("??")
    assert callable(d["state_summary"])
    assert callable(d["open_dialog"])
    assert callable(d["reset"])


# ---------------------------------------------------------------------------
# 3. マイグレーション(SPEC.md §2「旧2ストアからマイグレーション」)。
# ---------------------------------------------------------------------------

def test_migration_from_defaults_is_empty(tmp_path):
    """負の対照込み: 旧2ストアとも既定のまま、かつカタログにnative-donor
    既定ON(尻尾/耳)の鎖が1つも無いなら、移行結果も空(ファイルは作られ
    ない)。尻尾/耳を含むカタログでは、旧システム下でも「何もしなくても
    ONだった」ため、その実効状態が移行される(下のtest_migration_
    implicit_native_donor_default_is_migrated_even_without_any_legacy_
    customizationで検証、これはバグではなく意図どおりの移行)。"""
    app_root = str(tmp_path)
    catalog = [{"anchor": "Hips", "bones": ["Hips", "Skirt_F_01"], "node_count": 1}]
    custom_styles, assignments = store.migrate_from_legacy(app_root, AVATAR, catalog)
    assert custom_styles == {}
    assert assignments == []
    result = store.load_state_with_migration(app_root, AVATAR, catalog)
    assert result == ({}, [])
    assert not os.path.exists(store._state_path(app_root))  # noqa: SLF001


def test_migration_implicit_native_donor_default_is_migrated_even_without_any_legacy_customization(
    tmp_path,
):
    """SPEC.md §2「旧ONの鎖→現グローバル強度相当の組み込みゆれかた」は
    ユーザーの明示操作の有無を問わない――native-donor既定(尻尾/耳)で
    暗黙にONだった鎖も「旧ONの鎖」である。旧2ストアを一切触っていなくても、
    尻尾/耳を含むカタログでは移行が発生する。"""
    app_root = str(tmp_path)
    catalog = _catalog_two_chains()
    custom_styles, assignments = store.migrate_from_legacy(app_root, AVATAR, catalog)
    assert custom_styles == {}
    by_bones = {tuple(a["bones"]): a["style"] for a in assignments}
    assert by_bones[("Hips", "Tail_01", "Tail_02")] == "normal"
    assert by_bones[("Head", "EarL_01", "EarL_02")] == "normal"


def test_migration_from_chain_override_explicit_hardness(tmp_path):
    app_root = str(tmp_path)
    catalog = _catalog_two_chains()
    # 旧「揺れもの詳細設定」で尻尾チェーンを明示的に"hard"へ設定済み。
    chain_store.save_config(app_root, AVATAR, [
        {"bones": ["Hips", "Tail_01", "Tail_02"], "enabled": True, "hardness": "hard",
         "manual": False},
    ])
    custom_styles, assignments = store.migrate_from_legacy(app_root, AVATAR, catalog)
    assert custom_styles == {}
    by_bones = {tuple(a["bones"]): a["style"] for a in assignments}
    assert by_bones[("Hips", "Tail_01", "Tail_02")] == "hard"
    # 耳チェーンは何も上書きしていないが、native-donor既定でON(耳=既定ON)
    # のはずなので、"follow"→グローバル既定("normal")へ移行される。
    assert by_bones[("Head", "EarL_01", "EarL_02")] == "normal"


def test_migration_from_chain_override_off_chain_is_not_migrated(tmp_path):
    """SPEC.md §2は「旧ONの鎖」の移行のみを規定する。既定OFFのまま何も
    しなかった鎖(尻尾・耳以外の候補、ここではnative-donor既定OFFになる
    架空のスカート鎖)は移行対象に含まれない。"""
    app_root = str(tmp_path)
    catalog = [{"anchor": "Hips", "bones": ["Hips", "Skirt_F_01"], "node_count": 1}]
    custom_styles, assignments = store.migrate_from_legacy(app_root, AVATAR, catalog)
    assert custom_styles == {}
    assert assignments == []


def test_migration_from_chain_override_manual_entry(tmp_path):
    app_root = str(tmp_path)
    catalog = []
    chain_store.save_config(app_root, AVATAR, [
        {"bones": ["CustomBone"], "enabled": True, "hardness": "soft", "manual": True},
    ])
    _custom, assignments = store.migrate_from_legacy(app_root, AVATAR, catalog)
    assert assignments == [{"bones": ["CustomBone"], "style": "soft"}]


def test_migration_from_raw_sway_params_creates_custom_style_and_assigns_family(tmp_path):
    app_root = str(tmp_path)
    catalog = _catalog_two_chains()  # Hips/Tail... = tail, Head/EarL... = ear
    params = raw_store.load_params(app_root)
    params["tail"]["stiffness"] = 0.77
    raw_store.save_params(app_root, params)
    custom_styles, assignments = store.migrate_from_legacy(app_root, AVATAR, catalog)
    assert len(custom_styles) == 1
    (name, params_out), = custom_styles.items()
    assert params_out["stiffness"] == 0.77
    assert params_out["wdl"] == params_out["wdr"] == raw_store.DEFAULT_PARAMS["tail"]["wd"]
    by_bones = {tuple(a["bones"]): a["style"] for a in assignments}
    # 尻尾チェーンはraw_sway_params移行のカスタムスタイルへ、耳は
    # chain_override側(native-donor既定ON)から"normal"へ、それぞれ割り当た
    # っている。
    assert by_bones[("Hips", "Tail_01", "Tail_02")] == name
    assert by_bones[("Head", "EarL_01", "EarL_02")] == "normal"


def test_migration_chain_override_takes_priority_over_raw_params(tmp_path):
    """鎖単位の明示的上書き(旧「揺れもの詳細設定」)の方が、family単位の
    生パラメータ移行より優先される(docstring記載の優先関係)。"""
    app_root = str(tmp_path)
    catalog = _catalog_two_chains()
    params = raw_store.load_params(app_root)
    params["tail"]["stiffness"] = 0.77
    raw_store.save_params(app_root, params)
    chain_store.save_config(app_root, AVATAR, [
        {"bones": ["Hips", "Tail_01", "Tail_02"], "enabled": True, "hardness": "soft",
         "manual": False},
    ])
    _custom_styles, assignments = store.migrate_from_legacy(app_root, AVATAR, catalog)
    by_bones = {tuple(a["bones"]): a["style"] for a in assignments}
    assert by_bones[("Hips", "Tail_01", "Tail_02")] == "soft"


def test_load_state_with_migration_does_not_write_to_disk_by_itself(tmp_path):
    """load_state_with_migration()自体は読み取り専用(ディスクへ書かない)
    ――ダイアログを開いただけで既定状態が変わらないための設計(単体テストで
    発見した設計変更、docstring参照)。呼び出し側がOK相当の操作
    (save_state)を行って初めて確定する。"""
    app_root = str(tmp_path)
    catalog = _catalog_two_chains()
    chain_store.save_config(app_root, AVATAR, [
        {"bones": ["Hips", "Tail_01", "Tail_02"], "enabled": True, "hardness": "hard",
         "manual": False},
    ])
    custom1, assignments1 = store.load_state_with_migration(app_root, AVATAR, catalog)
    assert assignments1
    assert not os.path.exists(store._state_path(app_root))  # noqa: SLF001


def test_load_state_with_migration_does_not_remigrate_after_ok_was_pressed_once(tmp_path):
    """OK相当の保存(save_state)が一度でも行われた後は、旧ストア側に
    さらに変更が入っても再マイグレーションしない(ユーザーの編集を
    上書きしないため)。"""
    app_root = str(tmp_path)
    catalog = _catalog_two_chains()
    chain_store.save_config(app_root, AVATAR, [
        {"bones": ["Hips", "Tail_01", "Tail_02"], "enabled": True, "hardness": "hard",
         "manual": False},
    ])
    custom1, assignments1 = store.load_state_with_migration(app_root, AVATAR, catalog)
    # ユーザーがダイアログでOKを押した(= その時点の作業中セットを保存した)
    # ことをシミュレートする。
    store.save_state(app_root, AVATAR, custom1, assignments1)
    assert os.path.exists(store._state_path(app_root))  # noqa: SLF001

    # 旧ストア側にさらに変更が入っても、2回目以降は再マイグレーションしない。
    chain_store.save_config(app_root, AVATAR, [
        {"bones": ["Head", "EarL_01", "EarL_02"], "enabled": True, "hardness": "soft",
         "manual": False},
    ])
    custom2, assignments2 = store.load_state_with_migration(app_root, AVATAR, catalog)
    assert custom2 == custom1
    assert assignments2 == assignments1
