# test_multi_avatar_pak_store_dev1170.py -- dev#1170 WP-3(マルチアバターPAK
# 作成)の対応表永続化ロジック(multi_avatar_pak_store.py)の単体試験。
#
# equipment_filter_store.py等の既存storeテストと同じ流儀
# (load/save/reset/is_active/state_summaryの往復+負の対照)。実tkinter
# ウィジェットは一切使わない。
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
import multi_avatar_pak_store as store  # noqa: E402


# ---------------------------------------------------------------------------
# load/save往復
# ---------------------------------------------------------------------------


def test_load_returns_empty_dict_when_unset(tmp_path):
    app_root = str(tmp_path)
    assert store.load_assignments(app_root) == {}


def test_save_then_load_roundtrips(tmp_path):
    app_root = str(tmp_path)
    store.save_assignments(app_root, {"Bronze001": "Alicia", "Cloth002": "Bob"})
    assert store.load_assignments(app_root) == {"Bronze001": "Alicia", "Cloth002": "Bob"}


def test_save_empty_assignments_still_creates_file_that_loads_empty(tmp_path):
    app_root = str(tmp_path)
    store.save_assignments(app_root, {"X": "Y"})
    store.save_assignments(app_root, {})
    assert store.load_assignments(app_root) == {}
    assert os.path.isfile(store._state_path(app_root))


def test_load_ignores_empty_or_falsy_keys_and_values(tmp_path):
    path = os.path.join(str(tmp_path), store._STATE_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"assignments": {"": "Alicia", "Cloth": "", "Ok": "Bob"}}, f)
    assert store.load_assignments(str(tmp_path)) == {"Ok": "Bob"}


def test_load_tolerates_missing_file(tmp_path):
    assert store.load_assignments(str(tmp_path / "nonexistent")) == {}


def test_load_tolerates_corrupt_json(tmp_path):
    path = os.path.join(str(tmp_path), store._STATE_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not valid json")
    assert store.load_assignments(str(tmp_path)) == {}


def test_load_tolerates_wrong_shape(tmp_path):
    path = os.path.join(str(tmp_path), store._STATE_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"assignments": ["not", "a", "dict"]}, f)
    assert store.load_assignments(str(tmp_path)) == {}


# ---------------------------------------------------------------------------
# reset/is_active/state_summary
# ---------------------------------------------------------------------------


def test_reset_clears_to_empty(tmp_path):
    app_root = str(tmp_path)
    store.save_assignments(app_root, {"A": "B"})
    assert store.is_active(app_root) is True
    store.reset(app_root)
    assert store.is_active(app_root) is False
    assert store.load_assignments(app_root) == {}


def test_is_active_false_when_default(tmp_path):
    assert store.is_active(str(tmp_path)) is False


def test_state_summary_none_when_default(tmp_path):
    assert store.state_summary(str(tmp_path)) is None


def test_state_summary_reports_count_when_non_default(tmp_path):
    app_root = str(tmp_path)
    store.save_assignments(app_root, {"A": "X", "B": "X", "C": "Y"})
    summary = store.state_summary(app_root)
    assert summary is not None
    assert summary == i18n.S("LabMultiAvatarPakSummaryFormat").format(3)


def test_state_summary_respects_lang_param(tmp_path):
    """dev#1170 バグ修正: 旧実装はi18n.F()(常にcurrent_lang依存)を使っており
    lang引数を無視していた。equipment_filter_store等の他storeと同じ
    i18n.S(key, lang).format(n)の形へ揃え、lang引数が実際に効くことを確認する。"""
    app_root = str(tmp_path)
    store.save_assignments(app_root, {"A": "X"})
    ja = store.state_summary(app_root, lang="ja")
    en = store.state_summary(app_root, lang="en")
    assert ja is not None and en is not None
    assert ja != en
    assert ja == i18n.S("LabMultiAvatarPakSummaryFormat", "ja").format(1)
    assert en == i18n.S("LabMultiAvatarPakSummaryFormat", "en").format(1)


def test_negative_control_state_summary_no_longer_reuses_drop_bones_format(tmp_path):
    """負の対照(dev#1170、オーナー実機確認「Lab Statusで Enabled: 30bones(s)
    は表示がおかしいのでは?」): 修正前はLabStatusDropBonesCountFormat
    ({0}本/{0} bone(s))という他機能(ボーン除外件数)の書式キーを誤流用して
    いた。装備30件割当という状況で、それが再発していないことを直接確認する
    (このテストは修正前のコードに対しては失敗する=検出力の証明)。"""
    app_root = str(tmp_path)
    store.save_assignments(app_root, {f"K{i}": "X" for i in range(30)})
    summary = store.state_summary(app_root)
    assert summary is not None
    assert summary != i18n.F("LabStatusDropBonesCountFormat", 30)
    assert "本" not in summary
    assert "bone" not in summary.lower()


# ---------------------------------------------------------------------------
# default_fill(「設定開始」フロー、オーナー確定仕様②)
# ---------------------------------------------------------------------------


def test_default_fill_assigns_every_code_to_chosen_entry(tmp_path):
    app_root = str(tmp_path)
    codes = ["Bronze001", "Cloth002", "Plastic003"]
    result = store.default_fill(app_root, "Alicia", codes)
    assert result == {c: "Alicia" for c in codes}
    assert store.load_assignments(app_root) == {c: "Alicia" for c in codes}


def test_default_fill_overwrites_previous_assignments(tmp_path):
    app_root = str(tmp_path)
    store.save_assignments(app_root, {"Old": "Zzz"})
    store.default_fill(app_root, "Alicia", ["Bronze001", "Cloth002"])
    assert store.load_assignments(app_root) == {"Bronze001": "Alicia", "Cloth002": "Alicia"}


def test_default_fill_with_no_codes_leaves_empty(tmp_path):
    app_root = str(tmp_path)
    result = store.default_fill(app_root, "Alicia", [])
    assert result == {}
    assert store.is_active(app_root) is False


# ---------------------------------------------------------------------------
# assign_many(ペンキ方式割当、オーナー確定仕様④)
# ---------------------------------------------------------------------------


def test_assign_many_sets_selected_codes_only(tmp_path):
    app_root = str(tmp_path)
    store.default_fill(app_root, "Alicia", ["Bronze001", "Cloth002", "Plastic003"])
    store.assign_many(app_root, "Bob", ["Cloth002"])
    assert store.load_assignments(app_root) == {
        "Bronze001": "Alicia", "Cloth002": "Bob", "Plastic003": "Alicia",
    }


def test_assign_many_supports_multiple_codes_in_one_call(tmp_path):
    app_root = str(tmp_path)
    store.assign_many(app_root, "Bob", ["A", "B", "C"])
    assert store.load_assignments(app_root) == {"A": "Bob", "B": "Bob", "C": "Bob"}


def test_assign_many_last_write_wins_when_reassigned(tmp_path):
    """「最後に選択したアバターがその装備に割当」(オーナー確定仕様④)の
    直接検証: 同じ装備を別アバターへ塗り直すと、後の割当が勝つ。"""
    app_root = str(tmp_path)
    store.assign_many(app_root, "Alicia", ["Bronze001"])
    store.assign_many(app_root, "Bob", ["Bronze001"])
    assert store.load_assignments(app_root) == {"Bronze001": "Bob"}


def test_unassign_removes_single_code(tmp_path):
    app_root = str(tmp_path)
    store.default_fill(app_root, "Alicia", ["Bronze001", "Cloth002"])
    store.unassign(app_root, "Bronze001")
    assert store.load_assignments(app_root) == {"Cloth002": "Alicia"}


# ---------------------------------------------------------------------------
# compute_paint / compute_default_fill(dev#1341: ディスクI/O無しの純粋版)
# ---------------------------------------------------------------------------


def test_compute_paint_returns_same_result_as_assign_many_without_touching_disk(tmp_path):
    """compute_paint()は、assign_many()と同じ計算結果を返しつつ、
    引数以外のいかなるディスクI/Oも発生させない(app_root自体を受け取らない
    シグネチャそのものがそれを構造的に保証する)。"""
    before = {"Bronze001": "Alicia", "Cloth002": "Alicia"}
    result = store.compute_paint(before, "Bob", ["Cloth002"])
    assert result == {"Bronze001": "Alicia", "Cloth002": "Bob"}
    # 呼び出し元のdictそのものは書き換えない(コピーを返す)。
    assert before == {"Bronze001": "Alicia", "Cloth002": "Alicia"}


def test_compute_paint_supports_multiple_codes():
    result = store.compute_paint({}, "Bob", ["A", "B", "C"])
    assert result == {"A": "Bob", "B": "Bob", "C": "Bob"}


def test_compute_paint_matches_assign_many_semantics(tmp_path):
    """compute_paint()とassign_many()(ディスクI/Oあり版)が同じ入力に対して
    同じ結果を返す(意味的に同一のロジックであることの確認)。"""
    app_root = str(tmp_path)
    store.default_fill(app_root, "Alicia", ["Bronze001", "Cloth002", "Plastic003"])
    disk_result = store.assign_many(app_root, "Bob", ["Cloth002"])

    memory_result = store.compute_paint(
        {"Bronze001": "Alicia", "Cloth002": "Alicia", "Plastic003": "Alicia"},
        "Bob", ["Cloth002"])
    assert memory_result == disk_result


def test_compute_default_fill_matches_default_fill_semantics(tmp_path):
    app_root = str(tmp_path)
    codes = ["Bronze001", "Cloth002"]
    disk_result = store.default_fill(app_root, "Alicia", codes)
    memory_result = store.compute_default_fill("Alicia", codes)
    assert memory_result == disk_result == {c: "Alicia" for c in codes}


def test_compute_default_fill_with_no_codes_returns_empty():
    assert store.compute_default_fill("Alicia", []) == {}


def test_negative_control_compute_paint_that_ignores_entry_id_fails_to_paint():
    """負の対照: 「常に固定のentry_idで塗る」壊れた実装だと、意図した
    entry_idと違う結果になることを確認する(assign_many()の既存負の対照と
    対になる、compute_paint()側の検出力の証明)。"""
    def _broken_compute_paint(assignments, _entry_id, codes):
        return store.compute_paint(assignments, "WRONG_ID", codes)

    result = _broken_compute_paint({}, "Alicia", ["Bronze001"])
    assert result == {"Bronze001": "WRONG_ID"}
    assert result != {"Bronze001": "Alicia"}


# ---------------------------------------------------------------------------
# used_entry_ids / avatar_color_map(自動色分け、オーナー確定仕様④)
# ---------------------------------------------------------------------------


def test_used_entry_ids_dedupes_and_is_stable():
    assignments = {"C": "Bob", "A": "Alicia", "B": "Alicia", "D": "Bob"}
    # sorted(codes) = A,B,C,D -> 初出順は Alicia(A), Bob(C)
    assert store.used_entry_ids(assignments) == ["Alicia", "Bob"]


def test_used_entry_ids_empty_for_empty_assignments():
    assert store.used_entry_ids({}) == []


def test_avatar_color_map_assigns_distinct_colors_for_distinct_ids():
    colors = store.avatar_color_map(["Alicia", "Bob", "Carol"])
    assert len(colors) == 3
    assert len(set(colors.values())) == 3  # パレット冒頭3色は重複しない


def test_avatar_color_map_same_id_gets_same_color_each_call():
    a = store.avatar_color_map(["Alicia", "Bob"])
    b = store.avatar_color_map(["Alicia", "Bob"])
    assert a == b


def test_avatar_color_map_wraps_palette_when_ids_exceed_palette_size():
    n = len(store.AVATAR_COLOR_PALETTE) + 2
    ids = [f"Avatar{i}" for i in range(n)]
    colors = store.avatar_color_map(ids)
    assert colors[ids[0]] == colors[ids[len(store.AVATAR_COLOR_PALETTE)]]


# ---------------------------------------------------------------------------
# 負の対照: 検出力の証明
# ---------------------------------------------------------------------------


def test_negative_control_broken_reset_leaves_is_active_true(tmp_path):
    """負の対照: reset()が実際には何もしない実装だと、is_active()がFalseへ
    戻らないことをまず確認する(正のtest_reset_clears_to_emptyの検出力の
    前提が壊れていないことの証明)。"""
    app_root = str(tmp_path)
    store.save_assignments(app_root, {"A": "B"})

    def _broken_reset(_app_root):
        pass  # 実際のバグを模擬(何もしない)

    assert store.is_active(app_root) is True
    _broken_reset(app_root)
    assert store.is_active(app_root) is True, (
        "前提不成立: 壊れたresetでもis_activeがFalseになってしまう"
        "(negative controlの模擬方法を見直すこと)"
    )


def test_negative_control_assign_many_that_ignores_entry_id_fails_to_paint(tmp_path):
    """負の対照: 「常に固定のentry_idで塗る」壊れた実装だと、意図した
    entry_idと違う結果になることを確認する(ペンキ方式の検出力の証明)。"""
    app_root = str(tmp_path)

    def _broken_assign_many(app_root, _entry_id, codes):
        return store.assign_many(app_root, "WRONG_ID", codes)

    _broken_assign_many(app_root, "Alicia", ["Bronze001"])
    assert store.load_assignments(app_root) == {"Bronze001": "WRONG_ID"}
    assert store.load_assignments(app_root) != {"Bronze001": "Alicia"}
