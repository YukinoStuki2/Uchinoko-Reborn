# -*- coding: utf-8 -*-
"""dev#1072: vp_pakwrite.build_pak() の32bitオフセット/サイズ超過エラーの単体テスト。

背景: pakのEncodedPakEntries(struct.pack("<III", flags, cursor, size)、
vp_pakwrite.py 120行目付近)は符号なし32bit(<I、0〜2^32-1)固定。この範囲を
超えると生の`struct.error: argument out of range`が送出され、ユーザー報告
(実例K4XRB4DK、issue #1072)のログからはどのファイルが・何バイトで超過した
のかが一切読み取れなかった。本テストは、超過時に診断可能な
`PakEntryTooLargeError`(どのエントリ・offset/size・累積バイト数を含む)に
差し替わったこと、および正常サイズでは従来どおり成功することの両方
(負の対照込み)を検証する。

`_check_entry_fits_32bit()`はcursor/size(整数)だけを受け取る純粋関数として
切り出してあるため、ギガバイト級の実ファイルを用意せず単体テストできる。
末尾の`test_build_pak_...`はPAK_ENTRY_MAXをmonkeypatchで小さい値に差し替え、
実際に小さな実ファイルでbuild_pak()のエンドツーエンド配線
(_check_entry_fits_32bit()が本当に呼ばれているか)を確認する。

実行: python -m pytest pipeline\\py\\test_vp_pakwrite.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_pakwrite  # noqa: E402


# ---------------------------------------------------------------------------
# _check_entry_fits_32bit(): 純粋関数の単体テスト(実ファイル不要)
# ---------------------------------------------------------------------------


def test_check_entry_fits_32bit_ok_under_limit_negative_control():
    """負の対照: offset/sizeが上限未満なら何も起きない(戻り値もNone)。"""
    assert vp_pakwrite._check_entry_fits_32bit(
        "Player/foo.uexp", 0, cursor=1024, size=2048) is None


def test_check_entry_fits_32bit_ok_at_exact_limit_negative_control():
    """負の対照: ちょうど上限値(2^32-1)は許容される(境界値、超過ではない)。"""
    limit = vp_pakwrite.PAK_ENTRY_MAX
    assert vp_pakwrite._check_entry_fits_32bit(
        "Player/foo.uexp", 0, cursor=limit, size=limit) is None


def test_check_entry_fits_32bit_raises_when_offset_exceeds_limit():
    with pytest.raises(vp_pakwrite.PakEntryTooLargeError) as excinfo:
        vp_pakwrite._check_entry_fits_32bit(
            "Player/Outfit/SK_big.uexp", 42,
            cursor=vp_pakwrite.PAK_ENTRY_MAX + 1, size=100)
    msg = str(excinfo.value)
    # 診断に必要な要素が全部メッセージに含まれること(dev#1072の欠落そのもの)
    assert "SK_big.uexp" in msg
    assert "#42" in msg
    assert "offset=" in msg
    assert f"{vp_pakwrite.PAK_ENTRY_MAX:,}" in msg


def test_check_entry_fits_32bit_raises_when_size_exceeds_limit():
    with pytest.raises(vp_pakwrite.PakEntryTooLargeError) as excinfo:
        vp_pakwrite._check_entry_fits_32bit(
            "Player/tex/t00.uexp", 7,
            cursor=100, size=vp_pakwrite.PAK_ENTRY_MAX + 1)
    msg = str(excinfo.value)
    assert "t00.uexp" in msg
    assert "#7" in msg
    assert "size=" in msg


# ---------------------------------------------------------------------------
# build_pak(): エンドツーエンド配線の確認(実ファイルは小さいまま)
# ---------------------------------------------------------------------------


def _write(path, n_bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x00" * n_bytes)


def test_build_pak_succeeds_for_normal_size_negative_control(tmp_path):
    """負の対照: 通常サイズの入力ではPAK_ENTRY_MAXに一切触れず、
    従来どおり成功する(本WPでbuild_pak()の正常系を壊していないことの確認)。"""
    src_dir = tmp_path / "src"
    _write(str(src_dir / "a.txt"), 10)
    _write(str(src_dir / "sub" / "b.txt"), 20)
    files = vp_pakwrite.collect_files(str(src_dir))
    out_pak = tmp_path / "out.pak"
    info = vp_pakwrite.build_pak(files, str(out_pak))
    assert info["n_entries"] == 2
    assert out_pak.exists()
    assert out_pak.stat().st_size == info["size"]


def test_build_pak_raises_clear_error_when_entry_exceeds_limit(tmp_path, monkeypatch):
    """PAK_ENTRY_MAXを小さい値にmonkeypatchし、小さな実ファイルのままでも
    build_pak()が生のstruct.errorではなくPakEntryTooLargeErrorを送出する
    ことを確認する(=チェックが実際にbuild_pak()の書き込みループへ
    配線されていることの証明。ヘルパー単体テストだけでは「呼ばれているか」
    までは確認できない)。"""
    monkeypatch.setattr(vp_pakwrite, "PAK_ENTRY_MAX", 50)

    src_dir = tmp_path / "src"
    _write(str(src_dir / "a.txt"), 10)
    _write(str(src_dir / "z_big.txt"), 100)  # ソート順で2番目、cursor+size共に上限超え
    files = vp_pakwrite.collect_files(str(src_dir))
    out_pak = tmp_path / "out.pak"

    with pytest.raises(vp_pakwrite.PakEntryTooLargeError) as excinfo:
        vp_pakwrite.build_pak(files, str(out_pak))
    assert "z_big.txt" in str(excinfo.value)
