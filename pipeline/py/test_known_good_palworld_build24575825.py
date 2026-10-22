# -*- coding: utf-8 -*-
"""dev#1440: Palworld新build 24575825(label 1.0.3.101283)を
pipeline\\py\\known_good_palworld.json へ登録したことの受入試験。

app_py\\compat_check.py(dev#87/#89/#91の照合ロジック本体)を、実際に同梱される
pipeline\\py\\known_good_palworld.json に対して直接動かし、新buildの指紋が
PASS(should_warn=False)になることを確認する。負の対照として、未知buildと
サイズ違いのbuildは引き続き警告(should_warn=True)されることも確認する。

app_py側は本WPの書き込み許可ファイルに含まれないため、既存の
tests\\shipcheck\\test_palworld_compat.py と同じ手法(compat_check.pyを
sys.path経由でimportする)でapp_py\\compat_check.pyを読み取り専用で使う。
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))  # pipeline/py -> repo root
APP_PY_DIR = os.path.join(REPO_ROOT, "app_py")
BUNDLED_JSON_PATH = os.path.join(HERE, "known_good_palworld.json")

if APP_PY_DIR not in sys.path:
    sys.path.insert(0, APP_PY_DIR)

import compat_check as cc  # noqa: E402

NEW_BUILD_ID = "24575825"
NEW_PAK_SIZE = 40527155723
NEW_LABEL = "1.0.3.101283"
NEW_MANIFEST_HASH = (
    "6a42a5b6742fc0370af945372d2b8bba3bb002bf8759b64db880252e37748bec"
)


def _load_bundled_text():
    with open(BUNDLED_JSON_PATH, "r", encoding="utf-8") as f:
        return f.read()


def test_bundled_json_contains_new_build_entry():
    """データそのものの受入条件: 実測値がjsonに載っている。"""
    data = json.loads(_load_bundled_text())
    versions = data["known_versions"]
    match = [v for v in versions if v["build_id"] == NEW_BUILD_ID]
    assert len(match) == 1, "build 24575825 のエントリが1件だけ存在すること"
    assert match[0]["pak_size"] == NEW_PAK_SIZE
    assert match[0]["label"] == NEW_LABEL
    assert NEW_MANIFEST_HASH in data["known_vanilla_manifest_sha256"]


def test_new_build_fingerprint_is_known_version_no_warn():
    """正の対照: build_id+pak_sizeの一致だけで既知版判定される(dev#91より前の
    高速指紋パス)。"""
    known = cc.merge_known_good(_load_bundled_text(), None)
    det = cc.PalworldDetection(
        detected=True, build_id=NEW_BUILD_ID, pak_size=NEW_PAK_SIZE
    )
    st = cc.evaluate(known, det, None)
    assert st.known_version
    assert st.version_label == NEW_LABEL
    assert not st.should_warn


def test_new_build_manifest_hash_is_known_no_warn():
    """正の対照: build_idが未知でも、抽出物combined_hashが新規登録分と一致すれば
    自己判定経路(dev#91)で警告が出ない。"""
    known = cc.merge_known_good(_load_bundled_text(), None)
    det = cc.PalworldDetection(detected=True, build_id="00000000", pak_size=1)
    st = cc.evaluate(known, det, NEW_MANIFEST_HASH)
    assert st.manifest_available
    assert st.known_manifest
    assert not st.should_warn


def test_negative_unknown_build_id_still_warns():
    """負の対照1: 完全未知のbuild_id(サイズも別物)は引き続き警告される。"""
    known = cc.merge_known_good(_load_bundled_text(), None)
    det = cc.PalworldDetection(detected=True, build_id="99999999", pak_size=1234)
    st = cc.evaluate(known, det, None)
    assert st.should_warn
    assert not st.known_version


def test_negative_new_build_id_with_wrong_pak_size_still_warns():
    """負の対照2: build_idは新buildと同じでもpak_sizeが違えば既知版判定されない
    (サイズ保険経路もbuild_id取得済み時は使われない設計、compat_check.evaluate
    のコメントどおり)。マニフェストも無ければ警告になる。"""
    known = cc.merge_known_good(_load_bundled_text(), None)
    det = cc.PalworldDetection(
        detected=True, build_id=NEW_BUILD_ID, pak_size=NEW_PAK_SIZE + 1
    )
    st = cc.evaluate(known, det, None)
    assert not st.known_version
    assert st.should_warn


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
