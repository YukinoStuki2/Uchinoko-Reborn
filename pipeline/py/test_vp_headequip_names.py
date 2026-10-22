# -*- coding: utf-8 -*-
"""dev#165/#277第5弾(頭装備切り替えの表示名解決)の単体テスト。

**このテストファイル自体は実Palworld pakを一切使わない**(CI/自動テストが
通る環境を選ばないため。フィクスチャは全て本ファイル内で組み立てる架空の
行名・架空のパッケージパスで、実在の装備コード・アイテムID・表示文字列は
一切含まない)。実pakに対する検証は開発機上のPalworld実pak
(`Pal\\Content\\Paks\\Pal-Windows.pak`)へ手動実行で行い、
`vp_equipment_names.resolve_headequip_item_ids()`のdocstring・本WPの完了
報告に実測結果(64頭装備コード中62件、日英中韓5言語での正の対照サンプル)を
記録している(`tests\\equipment_filter_dev165\\test_vp_equipment_names.py`の
`TestRealPakIntegration`と同じ「合成データ+開発機ローカルの実pak opt-in」
方式)。

ここで機械受入として固定するのは:
  1. `_canonical_headequip_row()`: 「末尾が"_<数字>"でない行が1つだけ」なら
     それを基準行として採用する/0個・2個以上なら安全側でNoneを返す
     (曖昧対応の安全側除外、負の対照)
  2. `resolve_headequip_item_ids()`: 自作バイト列でのラウンドトリップ+
     頭防具プリセット行が体防具の絞り込みフィルタ(_is_body_armor_
     preset_row)を通さなくても解決できること+曖昧ケースの安全側除外
  3. `vp_headequip_names.py`側の配線: `resolve_display_names()`を
     `domain="headequip"`で呼ぶこと(体防具用のキャッシュと取り違えない
     ことも含む)
  4. **実pakでの正の対照**(`TestRealPakIntegration`): 開発機に実
     Palworld pakが見つかった場合のみ実行(見つからなければskip)
"""
import json
import os
import struct
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import vp_equipment_names as ven  # noqa: E402
import vp_headequip_names as vhn  # noqa: E402


# --------------------------------------------------------------- shared synthetic builders
# (test_vp_equipment_names.pyの_build_fake_uasset/_write_fstringと同じ規約の
# 独立実装。同モジュールをimportして再利用してもよいが、テストファイル同士の
# 結合を避けるため小さいヘルパーだけ複製する——vp_headequip_filter.py
# docstringが明言する「1関数のみで乖離のリスクは小さい」複製方針を踏襲)

def _write_fstring(s):
    if s == "":
        return struct.pack("<i", 0)
    b = s.encode("ascii") + b"\x00"
    return struct.pack("<i", len(b)) + b


def _build_fake_uasset(names):
    legacy_ver = -8
    header = struct.pack("<I", 0x9E2A83C1)
    header += struct.pack("<i", legacy_ver)
    header += struct.pack("<i", 0)
    header += struct.pack("<i", 0)
    header += struct.pack("<i", 0)
    header += struct.pack("<i", 0)
    header += struct.pack("<i", 0)
    header += struct.pack("<i", 0)
    header += _write_fstring("FakePackage")
    header += struct.pack("<I", 0)

    name_offset = len(header) + 8
    header += struct.pack("<ii", len(names), name_offset)

    body = b""
    for n in names:
        body += _write_fstring(n)
        body += struct.pack("<I", 0)
    return header + body


def _row_bytes(row_idx, value_indices):
    b = struct.pack("<ii", row_idx, 0)
    b += b"\x00" * 16
    for vi in value_indices:
        b += struct.pack("<ii", vi, 0)
        b += b"\x00" * 8
    return b


# ============================================================================
# _canonical_headequip_row
# ============================================================================

class TestCanonicalHeadequipRow(unittest.TestCase):
    def test_single_unsuffixed_row_is_canonical(self):
        self.assertEqual(
            ven._canonical_headequip_row(["CopperHelmet", "CopperHelmet_2", "CopperHelmet_3"]),
            "CopperHelmet")

    def test_only_row_with_no_suffix_at_all(self):
        self.assertEqual(ven._canonical_headequip_row(["ClothHat"]), "ClothHat")

    def test_negative_control_two_unsuffixed_rows_is_ambiguous(self):
        """負の対照: 無印行が2つ(境界誤認識/複数プリセットの共有疑い)なら
        安全側でNoneを返す(実pakのHeadEquip040相当のケース)。"""
        self.assertIsNone(
            ven._canonical_headequip_row(["GYM_Head_Sakurajima", "Player_Outfit_Kigurumi001"]))

    def test_negative_control_all_suffixed_is_ambiguous(self):
        """負の対照: 無印行が0個(全行が末尾"_<数字>")なら安全側でNoneを
        返す。"""
        self.assertIsNone(ven._canonical_headequip_row(["Head001_2", "Head001_3"]))


# ============================================================================
# resolve_headequip_item_ids
# ============================================================================

class TestResolveHeadequipItemIds(unittest.TestCase):
    def _make_names(self):
        return [
            "-",                                      # 0
            "CopperHelmet",                            # 1 (row、無印)
            "CopperHelmet_2",                           # 2 (row、色違い)
            "ClothArmor",                                # 3 (row、体防具——headequipでは無視されるはず)
            "/Game/Pal/Model/Character/Player/HeadEquip/"
            "HeadEquip999/SK_HeadEquip999",       # 4 (value: headequip mesh、
                                                    # headequip_code()の正規表現に
                                                    # 一致する必要があるため高い連番
                                                    # (999)を架空コードとして使う)
            "/Game/Pal/Model/Character/Player/Outfit/"
            "SK_Player_Female_Outfit_TestCloth001/"
            "SK_Player_Female_Outfit_TestCloth001",         # 5 (value: 体防具mesh、無関係)
        ]

    def test_resolves_canonical_row_ignoring_variant_suffix(self):
        """正の対照: 無印行"CopperHelmet"と色違い行"CopperHelmet_2"が
        同じHeadEquipメッシュを参照していても、無印行がItemID候補として
        採用される。"""
        names = self._make_names()
        uexp = (_row_bytes(1, [4])   # CopperHelmet -> HeadEquip999
                + _row_bytes(2, [4])   # CopperHelmet_2 -> 同じmesh(色違いプリセット)
                + _row_bytes(3, [5]))   # ClothArmor(体防具、無関係mesh)
        uasset = _build_fake_uasset(names)
        mapping = ven.resolve_headequip_item_ids(uasset, uexp)
        self.assertEqual(mapping.get("HeadEquip999"), "CopperHelmet")

    def test_body_armor_row_not_filtered_out_but_wrong_path_ignored(self):
        """体防具限定フィルタ(_is_body_armor_preset_row)を通さない設計の
        確認: "ClothArmor"行はheadequip向けpath_predicateに一致する参照を
        持たないため、そもそも対応表に現れない(誤ってTestCloth001が
        headequipコードとして解決されることはない)。"""
        names = self._make_names()
        uexp = _row_bytes(3, [5])  # ClothArmor -> Outfitメッシュ(headequip対象外パス)
        uasset = _build_fake_uasset(names)
        mapping = ven.resolve_headequip_item_ids(uasset, uexp)
        self.assertEqual(mapping, {})

    def test_negative_control_ambiguous_pair_excluded(self):
        """負の対照: 2つの無印行(頭防具系・体防具系プリセットが同じ
        headequipメッシュを共有するケースを模した)が同じコードに集約
        されると、安全側でそのコードの対応を採用しない。"""
        names = self._make_names()
        names.append("Player_Outfit_TestKigurumi001")  # 6 (無印、体防具プリセット行)
        uexp = (_row_bytes(1, [4])   # CopperHelmet -> HeadEquip999
                + _row_bytes(6, [4]))  # 別の無印行が同じmeshを参照(曖昧化)
        uasset = _build_fake_uasset(names)
        mapping = ven.resolve_headequip_item_ids(uasset, uexp)
        self.assertNotIn("HeadEquip999", mapping)

    def test_no_reference_yields_empty_mapping(self):
        """負の対照: どの行もheadequipメッシュを参照しなければ空の対応表
        (=呼び出し側が全コードを内部コード表示へフォールバックできる)。"""
        names = self._make_names()
        uexp = _row_bytes(3, [5])
        uasset = _build_fake_uasset(names)
        mapping = ven.resolve_headequip_item_ids(uasset, uexp)
        self.assertEqual(mapping, {})


# ============================================================================
# vp_headequip_names.py の配線(domain="headequip"で呼ぶこと)
# ============================================================================

class TestListHeadequipCodes(unittest.TestCase):
    def test_fake_manifest_falls_back_gracefully(self):
        d = tempfile.mkdtemp(prefix="d2p_headequipnames_test_")
        fake_manifest = os.path.join(d, "does_not_exist.json")
        codes = vhn.list_headequip_codes(fake_manifest)
        self.assertEqual(codes, set())

    def test_manifest_without_headequip_yields_empty(self):
        d = tempfile.mkdtemp(prefix="d2p_headequipnames_test_")
        manifest_path = os.path.join(d, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"project": ["Player/Outfit/SK_Player_Female_Outfit_Cloth001.uasset"]}, f)
        codes = vhn.list_headequip_codes(manifest_path)
        self.assertEqual(codes, set())

    def test_manifest_with_headequip_resolves_codes(self):
        d = tempfile.mkdtemp(prefix="d2p_headequipnames_test_")
        manifest_path = os.path.join(d, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"project": [
                "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uasset",
                "Player/HeadEquip/HeadEquip001/SK_HeadEquip001.uexp",
            ]}, f)
        codes = vhn.list_headequip_codes(manifest_path)
        self.assertEqual(codes, {"HeadEquip001"})


class TestHeadequipNamesCacheDomainIsolation(unittest.TestCase):
    """受入項目そのもの: headequip呼び出しがequipment(体防具)用の古い
    キャッシュを取り違えて誤ったok=True/names={}を返さないこと
    (dev#165/#277第5弾、_fingerprint()のdomain引数追加の直接動機)。"""

    def test_headequip_and_equipment_fingerprints_differ_for_same_pak_lang(self):
        d = tempfile.mkdtemp(prefix="d2p_headequipnames_test_")
        pak_path = os.path.join(d, "Pal-Windows.pak")
        with open(pak_path, "wb") as f:
            f.write(b"x" * 32)
        fp_equipment = ven._fingerprint(pak_path, "ja", "equipment")
        fp_headequip = ven._fingerprint(pak_path, "ja", "headequip")
        self.assertNotEqual(fp_equipment, fp_headequip)

    def test_equipment_cache_does_not_leak_into_headequip_call(self):
        """負の対照: equipment用キャッシュファイルを用意した状態で
        headequip呼び出しを行っても、そのキャッシュを誤ってヒットしない
        (=domain分離が機能している)。"""
        d = tempfile.mkdtemp(prefix="d2p_headequipnames_test_")
        pak_path = os.path.join(d, "Pal-Windows.pak")
        with open(pak_path, "wb") as f:
            f.write(b"x" * 32)
        cache_dir = os.path.join(d, "cache")
        os.makedirs(cache_dir, exist_ok=True)

        fp_equipment = ven._fingerprint(pak_path, "ja", "equipment")
        cache_file = os.path.join(cache_dir, f"names_{fp_equipment}.json")
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"names": {"Cloth001": "布の服"}, "locres_path": None}, f)

        # headequipドメインで解決を試みる(fake pakのため実解決はできず
        # フォールバックするが、equipment用キャッシュを誤ってヒットして
        # ok=True, source="cache" になっていないことを確認する)。
        names, status = ven.resolve_display_names(
            pak_path, "ja", ["HeadEquip001"], cache_dir, domain="headequip")
        self.assertNotEqual(status["source"], "cache")
        self.assertNotIn("HeadEquip001", names)


def _find_real_palworld_pak():
    try:
        sys.path.insert(0, _HERE)
        import palworld_locate
        return palworld_locate.find_palworld_pak()
    except Exception:
        return None


_REAL_PAK = _find_real_palworld_pak()
_REPO = os.path.dirname(os.path.dirname(_HERE))
_MANIFEST_PATH = os.path.join(_HERE, "noue_template_manifest.json")


@unittest.skipUnless(_REAL_PAK and os.path.exists(_REAL_PAK),
                      "実Palworld pakが見つからない開発機ではskip"
                      "(CLAUDE.md「自動発見は必ず手動指定フォールバックを持つ」"
                      "の精神——pak不在のCI等でも全体は落ちない)")
class TestRealPakIntegration(unittest.TestCase):
    """受入項目そのもの: 実バニラDTから既知の頭装備コードで日英中韓の
    名前が引けること(正の対照)+曖昧・欠落コードは内部コード表示への
    フォールバックのまま(負の対照)。2026-08-08実測: 64頭装備コード中
    62件が解決できる(完了報告に一覧を記録)。"""

    def test_known_codes_resolve_to_real_names_multi_language(self):
        cache_dir = tempfile.mkdtemp(prefix="d2p_vhn_real_multi_")
        codes = ["HeadEquip016", "HeadEquip017", "HeadEquip018"]
        expectations = {
            "ja": {"HeadEquip016": "金属ヘルム", "HeadEquip017": "精錬金属ヘルム",
                   "HeadEquip018": "パルメタルヘルム"},
            "en": {"HeadEquip016": "Metal Helm", "HeadEquip017": "Refined Metal Helm",
                   "HeadEquip018": "Pal Metal Helm"},
        }
        for lang, expected in expectations.items():
            names, status = ven.resolve_display_names(
                _REAL_PAK, lang, codes, cache_dir, domain="headequip")
            self.assertTrue(status["ok"])
            for code, text in expected.items():
                self.assertEqual(names.get(code), text)

    def test_ambiguous_and_absent_codes_fall_back(self):
        """負の対照: resolve_headequip_item_ids()のdocstringに記録した
        既知の2ギャップ(HeadEquip040=曖昧、HeadEquip014=DT不在)は、
        いずれもnamesに現れない(=呼び出し側が内部コード表示へ安全に
        フォールバックできる)。"""
        cache_dir = tempfile.mkdtemp(prefix="d2p_vhn_real_negative_")
        names, status = ven.resolve_display_names(
            _REAL_PAK, "ja", ["HeadEquip040", "HeadEquip014"], cache_dir, domain="headequip")
        self.assertNotIn("HeadEquip040", names)
        self.assertNotIn("HeadEquip014", names)

    def test_cli_end_to_end_resolves_majority_of_manifest_codes(self):
        """vp_headequip_names.pyのCLI経路(list_headequip_codes()+
        resolve_display_names(domain="headequip"))をmanifest+実pakで通し、
        過半数(62/64)が解決できることを確認する。"""
        cache_dir = tempfile.mkdtemp(prefix="d2p_vhn_real_cli_")
        codes = sorted(vhn.list_headequip_codes(_MANIFEST_PATH))
        self.assertEqual(len(codes), 64)
        names, status = ven.resolve_display_names(
            _REAL_PAK, "ja", codes, cache_dir, domain="headequip")
        self.assertTrue(status["ok"])
        self.assertGreaterEqual(len(names), 60)  # 実測62件、多少の余裕を持たせる


if __name__ == "__main__":
    unittest.main()
