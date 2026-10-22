# -*- coding: utf-8 -*-
"""U6-T1: 自前pakライター(最後のUE依存の排除)。

ディレクトリツリー(または(絶対パス, マウント相対パス)のリスト)から
Palworld互換pak(UE5.1 pak version 11、非圧縮・非暗号化)をUnrealPak.exe無しで
生成する。stdlib のみ使用(pip禁止)。

フォーマットは `research\\ue_exit\\_analyze_pak_format.py` による実物
(UnrealPak.exe生成のvariant_avatar_all.pak、435エントリ)のバイト解剖で実測確定
(docs\\REPORT_U6_*.md 参照)。読み取り側の実装(`vp_core.read_pak_entries`/
`read_pak_index`、Phase1・無改変)を仕様書として突き合わせ済み。

pakレイアウト(先頭からEOFまで、パディング無しで連続):
  [Entry0: LocalHeader(53B) + RawData] [Entry1: ...] ... [EntryN-1: ...]
  [Index blob]
  [FullDirectoryIndex blob]
  [FPakInfo footer(221B)]

LocalHeader(53バイト、非圧縮固定、restore_pak.pyのhoff=offset+28と整合):
  Offset:i64 CompressedSize:i64(=UncompressedSize) UncompressedSize:i64
  CompressionMethodIndex:i32(=0) Hash:20B(data のSHA1) bEncrypted:u8(=0)
  CompressionBlockSize:u32(=0)

Index blob:
  MountPoint:FString NumEntries:i32 PathHashSeed:u64(=0)
  bHasPathHashIndex:i32(=0、本ライターは常にPathHashIndex省略)
  bHasFullDirectoryIndex:i32(=1) FDIOffset:i64 FDISize:i64 FDIHash:20B(SHA1)
  EncodedPakEntries: i32(バイト数) + 生バイト(エントリ毎12B:
      Flags:u32(=0xE0000000、32bit安全offset+32bit安全usize+comp_method=0)
      Offset:u32 UncompressedSize:u32)
  Files(legacy、常に空): i32(=0)

FullDirectoryIndex blob:
  NumDirs:i32
  各ディレクトリ(ソート順、root="/"): DirName:FString NumFiles:i32
    各直下ファイル(ソート順): FileName:FString EncodedOffset:i32
      (EncodedPakEntries内の該当12Bレコードのバイトオフセット)

FPakInfo footer(221バイト、EOF直前):
  bEncryptedIndex:u8(=0) EncryptionKeyGuid:16B(=0) Magic:u32(0x5A6F12E1)
  Version:u32(=11) IndexOffset:i64 IndexSize:i64 IndexHash:20B(SHA1)
  CompressionMethods: 5x32B(=0、本ライターは圧縮方式未使用)

既知の制約(v1):
  - 非圧縮エントリのみ(既存pakが全数非圧縮のため対応不要)
  - PathHashIndexは省略(bHasPathHashIndex=0)。UnrealPak.exeの-List/-Extract
    はFullDirectoryIndexのみで動作することを実測確認(docs\\REPORT_U6_*.md)
  - オフセット/サイズは全エントリ32bit範囲内(<4GB)前提(флаги固定0xE0000000)
"""
import hashlib
import io
import os
import posixpath
import struct

PAK_MAGIC = 0x5A6F12E1
PAK_VERSION = 11
DEFAULT_MOUNT = "../../../Pal/Content/Pal/Model/Character/"

# dev#1198 WP-B4: rel_path正規化・mount一括昇格。
#
# 背景(work\\rd_1198_dtreach\\PROGRESS.md で実証済み): pakエンジンは
# FullDirectoryIndex内の各entryのdirname文字列を".."解決なしでmountへ単純
# 連結する(cookedアセットは常にクリーンなパスなのでエンジン側にentry単位の
# 再collapseをするインセンティブが無いため)。旧DEFAULT_MOUNT
# (".../Model/Character/")はボディ資産専用の狭いmountで、これ以外の系統の
# パス(DataTable配下など)をentry側のrel_pathで".."を使って上位へ逃がそうと
# すると、実効パスに".."が残ったまま解決されず、そのファイルへの変更が
# エンジンから見えない(dev#1198頭部問題フラグ差し替えが方向を問わず一切
# 無視されていた根本原因)。
#
# COMMON_MOUNT はボディ資産・DT資産など複数系統のパスを共通祖先から
# ".."を一切含まない"純サブパス"で収録するためのmount_pointである。
# 呼び出し側がCOMMON_MOUNTをbuild_pak()のmount_point引数へ渡し、各エントリの
# rel_pathへBODY_PREFIX/DT_PREFIXを付与すれば、entry側".."ゼロの
# pakが構築できる。build_pak()自体のコア実装は無改修(mount_point引数は
# 既存のまま)。
#
# 既存呼び出し元(build_pak_from_avatar.py Phase3, fast_repack.py)は
# 現在DEFAULT_MOUNT(暗黙・mount_point省略)+ボディ資産相対のrel_pathを
# 前提に動作しており、本WPはそれらの呼び出し元を書き換えない(書き込み
# 許可がvp_pakwrite.py+テストに限定されているため)。実際にCOMMON_MOUNTへ
# 切り替える配線は別WP(dev#1198 WP-B5、統合)で行う。
COMMON_MOUNT = "../../../Pal/Content/Pal/"
BODY_PREFIX = "Model/Character/"
DT_PREFIX = "DataTable/CharacteCreation/"

# 恒久の自己整合性チェック: COMMON_MOUNT+BODY_PREFIXの実効パスは、旧
# DEFAULT_MOUNT単体の実効パスと常に一致しなければならない(=COMMON_MOUNT体系
# への移行は既存ボディ資産の実効パスに対してリグレッション不可能でなければ
# ならない、という設計不変条件をモジュール読み込み時に保証する)。
assert DEFAULT_MOUNT == COMMON_MOUNT + BODY_PREFIX, (DEFAULT_MOUNT, COMMON_MOUNT, BODY_PREFIX)


def effective_path(mount, rel):
    """mount + rel を1つの文字列として posixpath.normpath で正規化した
    "仮想的な実効パス"を返す。pakエンジンの実際のパス解決(mount側は
    FPakFile::Mount()時に正規化されるが、entry側のrel文字列自体は
    正規化されずそのまま連結される、が実測結論)とは異なり、"もしengineが
    連結後の文字列全体を正規化していたら"という仮定のもとでの実効パスを
    計算する。COMMON_MOUNT移行のリグレッション検証専用のユーティリティ
    (旧mount+旧relの実効パスと新mount+新relの実効パスが一致するかを
    machine-checkするために使う。dev#1198 WP-B4)。"""
    return posixpath.normpath(mount + rel)


def normalize_rel(rel, prefix):
    """rel_path(leading '/' を許容)へ prefix を安全に付与し、COMMON_MOUNT
    体系向けの"純サブパス"(".."を一切含まない)を作る。

    - leading '/' は剥がしてから連結する(build_pak()のFullDirectoryIndex
      構築がルート直下ファイルでKeyErrorを起こす既知の問題の回避策。
      work\\rd_1198_dtreach と同じ手当て。このKeyErrorバグ自体の修正は
      本WPのスコープ外——PROPOSAL §5.2参照)。
    - rel が(スラッシュ区切りの各要素として)".."を含む場合は
      ValueError で拒否する。COMMON_MOUNT体系はentry側".."ゼロを前提と
      するため、混入は正規化の目的そのものに反する静かな回帰であり、
      検出せず通すことは禁止(CLAUDE.md「値を寄せて合わせる修正は却下」
      と同じ精神で、緩めるのではなく落とす)。
    """
    rel_norm = rel.replace("\\", "/")
    if rel_norm.startswith("/"):
        rel_norm = rel_norm[1:]
    if ".." in rel_norm.split("/"):
        raise ValueError(f"rel_path must not contain '..' segments: {rel!r}")
    return prefix + rel_norm


def to_common_mount_body_files(files):
    """dev#1198 WP-B5a: 既存呼び出し元(build_pak_from_avatar.py Phase3,
    fast_repack.py)がDEFAULT_MOUNT(暗黙)+ボディ資産相対のrel_pathで組み立てた
    `files`([(abs_src, rel), ...])を、COMMON_MOUNT体系向けに変換する。

    各relへnormalize_rel(rel, BODY_PREFIX)を適用するだけの薄いラッパー
    (build_pak()のコア実装・シグネチャは無改修のまま、PROPOSAL §5.1)。
    呼び出し側はこの戻り値を
    build_pak(..., mount_point=COMMON_MOUNT) に渡す。

    リグレッション不可能性: effective_path(COMMON_MOUNT, normalize_rel(rel,
    BODY_PREFIX)) は常に effective_path(DEFAULT_MOUNT, rel) と一致する
    (モジュール冒頭の自己整合性アサート
    `DEFAULT_MOUNT == COMMON_MOUNT + BODY_PREFIX` により、prefixが単純な
    文字列連結である限り機械的に成立する。test_vp_pakwrite_wpb5a_wiring.py
    で機械検証)。
    """
    return [(src, normalize_rel(rel, BODY_PREFIX)) for src, rel in files]

# dev#1072: EncodedPakEntries の Offset/UncompressedSize(struct.pack("<III",
# flags, cursor, size)、120行目付近)は符号なし32bit(<I)なので、表現できる
# のは0〜2^32-1バイトまで。これを超えると生のPython struct.errorが
# "argument out of range"とだけ言って落ち、どのファイルが・何バイトで
# 超過したのかがユーザー報告のログから一切読み取れない(実例K4XRB4DK、
# issue #1072参照)。この定数は<I自体のハード上限であり、緩和・拡張の
# 対象ではない(64bit化するならフォーマット自体の変更が要る)。
PAK_ENTRY_MAX = 0xFFFFFFFF  # 2^32-1


class PakEntryTooLargeError(RuntimeError):
    """pakエントリのoffsetまたはsizeがPAK_ENTRY_MAX(符号なし32bit上限)を
    超えたときに送出する。生のstruct.errorの代わりにこれを送出することで、
    どのエントリが・どれだけ超過したか・その時点までの累積サイズがログに
    残り、ユーザー報告(「ログをコピー」経由)から診断できるようにする
    (dev#1072)。"""


def _check_entry_fits_32bit(rel, index, cursor, size):
    """このエントリのoffset(cursor)・size がPAK_ENTRY_MAXに収まっているかを
    検査する。収まらない場合はPakEntryTooLargeErrorを送出する。build_pak()
    が実ファイルを書き出す直前(struct.pack("<III", ...)の前)に呼ぶための
    純粋関数として切り出してあり、オフセット/サイズさえ渡せば単体テストで
    ギガバイト級の実ファイルを用意せずに検証できる。"""
    if cursor > PAK_ENTRY_MAX or size > PAK_ENTRY_MAX:
        which = []
        if cursor > PAK_ENTRY_MAX:
            which.append(f"offset={cursor:,}")
        if size > PAK_ENTRY_MAX:
            which.append(f"size={size:,}")
        raise PakEntryTooLargeError(
            f"pak entry #{index} '{rel}' does not fit the pak index format's "
            f"32-bit offset/size field (limit={PAK_ENTRY_MAX:,} bytes = "
            f"4GiB-1): {', '.join(which)} exceeds the limit "
            f"(cumulative bytes written so far={cursor:,}). "
            f"The converted output is too large for the pak format's "
            f"per-entry offset/size representation. (dev#1072)"
        )


def _fstring(s):
    """ASCII FString: i32 length(含む末尾\\0) + bytes + \\0"""
    b = s.encode("ascii") + b"\x00"
    return struct.pack("<i", len(b)) + b


def _split_rel(rel):
    """'a/b/c.txt' -> ('a/b/', 'c.txt')。'root.txt' -> ('/', 'root.txt')"""
    rel = rel.replace("\\", "/")
    if rel.startswith("/"):
        rel = rel[1:]
    if "/" in rel:
        d, fn = rel.rsplit("/", 1)
        return d + "/", fn
    return "/", rel


def _win_long_path(path):
    r"""Windows拡張長パス(`\\?\` 接頭辞)を付与し、MAX_PATH(260)制限を回避する。

    dev#458(実ユーザー報告JB5ZGBJC、`pipeline\py\live_template.py`)・
    dev#1101(同ファイルの`write_unified_mis()`)に続く、同型の第3の発生箇所
    (dev#1304、実報告R3CPL395)。`build_pak()`の`open(src, "rb")`
    (パッケージ済みアバターのファイル数・ネスト深さが多いと、work_root配下の
    相対パスが260文字を超えうる)が`FileNotFoundError`で失敗した。

    正本は`live_template._win_long_path()`(同名・同実装)。`vp_pakwrite.py`は
    `live_template.py`から一切importされない側(依存の向きが逆)であり、
    `vp_pakwrite`から`live_template`をimportする新規依存を追加するのは
    モジュール構成上の逆流になるため、既存2件と同じ「自己完結の関数として
    そのモジュール内に置く」形を踏襲し、importではなく複製する。

    `\\?\` 接頭辞はNTのファイルI/O API自体が昔からサポートする拡張長パス指定で、
    絶対・正規化済み(区切りは`\`統一、`.`/`..`を含まない)パスにしか使えないため、
    まず`os.path.abspath()`で正規化する。UNCパス(`\\server\share\...`)は素の
    `\\?\` 直付けでは機能せず、`\\?\UNC\server\share\...` という別形式が必要
    (Win32の既知仕様)。既に`\\?\`済みならそのまま返す(冪等)。非Windowsでは
    パス表現が異なるため何もしない。
    """
    if os.name != "nt":
        return path
    ap = os.path.abspath(path)
    if ap.startswith("\\\\?\\"):
        return ap
    if ap.startswith("\\\\"):
        return "\\\\?\\UNC\\" + ap[2:]
    return "\\\\?\\" + ap


def collect_files(root):
    r"""root配下を再帰的に走査し、(絶対パス, root相対パス(フォワードスラッシュ))
    のリストをソート済みで返す。

    dev#1304: `os.walk()`自体もMAX_PATH未保護だとrootが深い場所で失敗しうる
    ため、`_win_long_path(root)`を起点に走査する(`os.path.relpath()`は
    startとpath双方が同じ表現(both `\\?\`付き)でないと"path is on mount"
    エラーになるため、rootとfull双方を長パス化した状態で揃える)。"""
    out = []
    walk_root = _win_long_path(root)
    for dirpath, _dirs, files in os.walk(walk_root):
        for fn in files:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, walk_root).replace("\\", "/")
            out.append((full, rel))
    out.sort(key=lambda t: t[1])
    return out


def build_pak(files, out_path, mount_point=DEFAULT_MOUNT):
    """files: [(abs_source_path, rel_path_in_mount), ...] (rel_pathはフォワード
    スラッシュ、先頭スラッシュ無し)。out_path にpakを書き出す。
    戻り値: {"n_entries": int, "size": int}
    決定論: 入力順序に関わらず rel_path でソートしてから書くため、同一内容の
    再生成は常にバイト一致する。"""
    items = sorted(files, key=lambda t: t[1])

    with open(_win_long_path(out_path), "wb") as out:
        encoded_records = []  # (rel_path, enc_off, byte12)
        offsets = {}  # rel -> (offset, size)
        cursor = 0
        for i, (src, rel) in enumerate(items):
            with open(_win_long_path(src), "rb") as f:
                data = f.read()
            size = len(data)
            sha1 = hashlib.sha1(data).digest()
            header = (
                struct.pack("<qqq", cursor, size, size)
                + struct.pack("<i", 0)   # CompressionMethodIndex
                + sha1
                + b"\x00"                # bEncrypted
                + struct.pack("<I", 0)   # CompressionBlockSize
            )
            assert len(header) == 53
            out.write(header)
            out.write(data)
            offsets[rel] = (cursor, size)
            enc_off = i * 12
            flags = 0xE0000000
            _check_entry_fits_32bit(rel, i, cursor, size)
            rec = struct.pack("<III", flags, cursor, size)
            encoded_records.append((rel, enc_off, rec))
            cursor += 53 + size

        n_entries = len(items)

        # --- EncodedPakEntries blob ---
        enc_blob = b"".join(rec for _rel, _off, rec in encoded_records)
        enc_off_by_rel = {rel: off for rel, off, _rec in encoded_records}

        # --- FullDirectoryIndex ---
        dirs = {}  # dirname -> [filenames]
        all_dirnames = set(["/"])
        for _src, rel in items:
            d, _fn = _split_rel(rel)
            parts = d.strip("/").split("/") if d != "/" else []
            acc = ""
            all_dirnames.add("/")
            for p in parts:
                acc += p + "/"
                all_dirnames.add(acc)
        for dn in all_dirnames:
            dirs.setdefault(dn, [])
        for _src, rel in items:
            d, fn = _split_rel(rel)
            dirs[d].append(fn)
        for fnlist in dirs.values():
            fnlist.sort()

        fdi = io.BytesIO()
        fdi.write(struct.pack("<i", len(dirs)))
        for dn in sorted(dirs.keys()):
            fdi.write(_fstring(dn))
            fnlist = dirs[dn]
            fdi.write(struct.pack("<i", len(fnlist)))
            for fn in fnlist:
                full_rel = fn if dn == "/" else dn + fn
                fdi.write(_fstring(fn))
                fdi.write(struct.pack("<i", enc_off_by_rel[full_rel]))
        fdi_blob = fdi.getvalue()
        fdi_hash = hashlib.sha1(fdi_blob).digest()

        fdi_offset = cursor
        out.write(fdi_blob)
        cursor += len(fdi_blob)

        # --- Index blob (written AFTER fdi per confirmed layout order:
        #     entries data -> Index blob -> [PathHashIndex] -> FDI -> footer;
        #     but since bHasPathHashIndex=0 here, actual physical placement
        #     order does not matter as long as offsets in Index are correct.
        #     We place Index blob after FDI for simplicity.) ---
        idx = io.BytesIO()
        idx.write(_fstring(mount_point))
        idx.write(struct.pack("<i", n_entries))
        idx.write(struct.pack("<Q", 0))            # PathHashSeed
        idx.write(struct.pack("<i", 0))            # bHasPathHashIndex = 0
        idx.write(struct.pack("<i", 1))            # bHasFullDirectoryIndex = 1
        idx.write(struct.pack("<q", fdi_offset))
        idx.write(struct.pack("<q", len(fdi_blob)))
        idx.write(fdi_hash)
        idx.write(struct.pack("<i", len(enc_blob)))
        idx.write(enc_blob)
        idx.write(struct.pack("<i", 0))             # legacy Files array, empty
        index_blob = idx.getvalue()
        index_hash = hashlib.sha1(index_blob).digest()

        index_offset = cursor
        out.write(index_blob)
        cursor += len(index_blob)

        # --- FPakInfo footer (221 bytes) ---
        footer = (
            b"\x00"                              # bEncryptedIndex
            + b"\x00" * 16                        # EncryptionKeyGuid
            + struct.pack("<II", PAK_MAGIC, PAK_VERSION)
            + struct.pack("<qq", index_offset, len(index_blob))
            + index_hash
            + b"\x00" * (32 * 5)                  # CompressionMethods
        )
        assert len(footer) == 221
        out.write(footer)
        cursor += len(footer)

    return {"n_entries": n_entries, "size": cursor}


def build_pak_from_dir(root, out_path, mount_point=DEFAULT_MOUNT):
    """root配下を丸ごとpak化する簡易API(build_variant_pak.py等が個別ファイルを
    差し替える用途にはbuild_pak()を直接使う)。"""
    files = collect_files(root)
    return build_pak(files, out_path, mount_point)
