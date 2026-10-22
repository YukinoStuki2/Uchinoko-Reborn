# test_sway_chain_dialog_display_name_dev1470.py -- dev#1470(WP
# wp_chainname、オーナー要望2026-08-15)の単体テスト。
#
# 「揺れ詳細設定」ダイアログのチェーン一覧表示名を、旧仕様の末端(先端)
# ボーン名(entry["bones"][-1])から、始点(根本/anchor)ボーン名
# (entry["bones"][0])へ変更した(表示のみ)。本ファイルは:
#   1. _display_name() が始点ボーン名を返すこと(旧: 末端名との対比)
#   2. 同じ始点を複数チェーンが共有する場合、直後の最初のノードボーン名で
#      一意に区別されること(重複していない行は素の始点名のまま)
#   3. 表示変更に関わらず、保存キー(bones全体のtuple)の互換が壊れて
#      いないこと(既存保存データ=末端名時代に保存されたのと同じ形の
#      オーバーライドを読ませても、従来どおりenabled/hardnessへ反映される)
#
# 実tk.Tk()は作らない(_display_name/_merge_working_setはtkinter非依存の
# 純粋関数)。
from __future__ import annotations

import os
import sys
from collections import Counter

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

from ui import sway_chain_dialog as scd  # noqa: E402


def test_display_name_is_start_bone_not_end_bone():
    """始点(bones[0])を返すこと。末端(bones[-1])はもう返らない(負の対照
    を兼ねる: 旧実装のまま=bones[-1]だったら本アサーションが落ちる)。"""
    entry = {
        "anchor": "J_Bip_C_Spine2",
        "bones": ["J_Bip_C_Spine2", "HairBack_01", "HairBack_02",
                   "HairBack_03", "HairBack_04"],
        "node_count": 4, "enabled": True, "hardness": "follow", "manual": False,
    }
    name = scd._display_name(entry)
    assert name == "J_Bip_C_Spine2"
    assert name != entry["bones"][-1]  # 旧仕様(末端名)ではないことの確認


def test_display_name_disambiguates_shared_anchor_with_first_node():
    """同じ始点(Hips)を尻尾・スカート前・スカート後の3チェーンが共有する
    SAMPLE_CHAINS相当のデータで、表示名が全て一意になること。"""
    working = scd._merge_working_set(scd.SAMPLE_CHAINS, [])
    anchor_counts = Counter(e["bones"][0] for e in working if not e["manual"])
    names = [scd._display_name(e, anchor_counts) for e in working]

    assert len(names) == len(set(names)), f"表示名が重複している: {names}"
    assert "J_Bip_C_Hips (Tail_01)" in names
    assert "J_Bip_C_Hips (Skirt_F_01)" in names
    assert "J_Bip_C_Hips (Skirt_B_01)" in names
    assert "J_Bip_C_Head (EarL_01)" in names
    assert "J_Bip_C_Head (EarR_01)" in names
    # Spine2始点は他に重複が無いので括弧書きが付かない(素の始点名のまま)。
    assert "J_Bip_C_Spine2" in names


def test_display_name_manual_entry_unaffected():
    """手動追加行はbones=[name]の単一要素で、始点=末端が常に同じ。表示に
    影響が無いこと(anchor_countsに含めても衝突しない)。"""
    entry = {"anchor": None, "bones": ["MyManualBone"], "node_count": 1,
              "enabled": True, "hardness": "follow", "manual": True}
    assert scd._display_name(entry) == "MyManualBone"
    assert scd._display_name(entry, Counter({"MyManualBone": 1})) == "MyManualBone"


def test_saved_override_store_key_compatibility_unaffected_by_display_change():
    """保存キー互換の確認: 既存保存データ(末端名の時代から変わっていない
    bones全体のtupleキー方式)をそのまま読ませても、表示名の変更とは無関係に
    enabled/hardnessが従来どおり反映されること(表示のみの変更で保存側の
    同定ロジックには一切触れていないことの証拠)。"""
    skirt_entry = next(
        c for c in scd.SAMPLE_CHAINS if c["bones"][-1] == "Skirt_F_02"
    )
    # 「既存保存データ」を模した保存済みオーバーライド(bones全体のtupleが
    # キーであることは表示名変更の前後で変わっていない)。
    saved_overrides = [{
        "bones": skirt_entry["bones"], "enabled": True, "hardness": "hard",
        "manual": False,
    }]
    working = scd._merge_working_set(scd.SAMPLE_CHAINS, saved_overrides)
    matched = next(e for e in working if e["bones"] == skirt_entry["bones"])
    assert matched["enabled"] is True
    assert matched["hardness"] == "hard"
    # 表示名は始点ベースへ変わっているが、これは保存キーとは独立している
    # ことの確認(表示名が違っても同定・反映は壊れない)。
    anchor_counts = Counter(e["bones"][0] for e in working if not e["manual"])
    assert scd._display_name(matched, anchor_counts) == "J_Bip_C_Hips (Skirt_F_01)"


def test_negative_control_naive_end_bone_disambiguation_would_still_collide():
    """負の対照: もし「重複時に末端名を括弧書きで足す」ような素朴な代替案
    (末端ボーン名は元々全チェーンで一意なので無意味な変更)ではなく、直後の
    最初のノードボーン名(bones[1])を使う設計が実際に効いていることを示す。
    比較対象として、あえてnode_count(節数)だけで区別しようとすると
    スカート前後(共に節数2)が区別できないことを確認する(BRIEFの例示
    「始点名+節数」だけでは不十分だったことの記録)。"""
    working = scd._merge_working_set(scd.SAMPLE_CHAINS, [])
    skirt_f = next(e for e in working if e["bones"][-1] == "Skirt_F_02")
    skirt_b = next(e for e in working if e["bones"][-1] == "Skirt_B_02")
    assert skirt_f["bones"][0] == skirt_b["bones"][0] == "J_Bip_C_Hips"
    assert skirt_f["node_count"] == skirt_b["node_count"] == 2
    naive_name_f = f"{skirt_f['bones'][0]} ({skirt_f['node_count']})"
    naive_name_b = f"{skirt_b['bones'][0]} ({skirt_b['node_count']})"
    assert naive_name_f == naive_name_b, (
        "この対照は『始点名+節数』方式では区別できないことの確認用"
        "(実装はbones[1]方式を採用しているため本体には影響しない)"
    )
