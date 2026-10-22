# -*- coding: utf-8 -*-
r"""dev#7: 診断ログへ生の絶対パス(利用者名・PC固有フォルダ名を含みうる)を出さない
ための共通ヘルパー。構造保存型の伏字化(値そのものはマスクしつつ、デバッグに必要な
「事実」の形だけ残す)。

出典: 元々 pipeline\py\fast_repack.py に `_path_facts` / `_display_path` として実装
されていた(dev#7の最初の修正、job.json/入力アバターの生フルパス漏洩対策)。
実ユーザー報告4AL4M4GT(非%USERPROFILE%ドライブの絶対パスがUnity/VCC・インストール先・
Steamライブラリで漏洩)を受けて、これを一般化してここへ切り出し、convert.ps1・
export_from_unity.ps1からも共通で使えるようにした(三段構成のうち「各所factify」、
work\issue_zero\i7\NOTES.md参照)。

呼び出し方法:
  - Python側から: from pipeline.py.path_privacy import display_path, path_facts, factify
  - PowerShell(export_from_unity.ps1)側から: 本ファイルをCLIとして呼ぶ
      python pipeline\py\path_privacy.py factify "<path>" [--base <dir> ...]
    標準出力へ1行だけ伏字化済み文字列を出す。

本モジュールは**表示専用**。実際のファイル操作(存在確認以外)には一切使わない。

dev#372(伏字化が原因の証拠まで消している問題): 実ユーザー報告HMZ87QGE(v2.2.11)では、
Blenderセットアップが `GetPathRoot` 例外で失敗した際、例外を起こした当のパス文字列が
ログ上で `<path len=120>` へ潰され、長さ以外の手がかり(空文字か/引用符が残っているか/
UNCの途中か/未展開の%VAR%か/末尾に不正文字があるか)が一切残らなかった。
**path_facts() が出す最小事実集合の定義はこのファイル1箇所を正とする**
(`pipeline\cli\convert.ps1` の `Get-PathFacts` と `app_py\inquiry.py` の
`factify_generic_path` は、それぞれの言語で独立実装しつつ同じ項目を出すよう揃えてある。
PowerShell/Python(app_py配布物はpipelineパッケージに依存しないため)からこのモジュールを
直接importできないための已む無い重複であり、項目の意味はここのdocstring/実装を正とする)。
参考: `pipeline\cli\ensure_blender.ps1` の `Get-D2PPathShape`(dev#368)が同種の構造保存型
伏字化を先行実装済みで、本関数の項目設計はその実装を叩き台にしている。

最小事実集合(個人情報を一切含まない、構造だけの事実):
  - 長さ(length) / 空文字・None(name/lengthで判別可) / セグメント数(segments)
  - ルート種別(root): drive(ドライブレター) / unc(UNC) / extended(\\?\ \\.\) /
    driveRelative(ドライブのみ) / rootRelative(\で始まる) / relative(相対) / none(空)
  - 非ASCII文字の有無(non_ascii_chars) / 空白の有無(has_space)
  - 引用符の残存(quote) / 制御文字・記号などの不正文字混入(invalid_chars)
  - 未展開の %VAR% の有無(unexpanded_env_var)
  - 末尾の空白(trailing_whitespace) / 末尾のドット(trailing_dot)
  - 拡張子(ext、フォルダ名やユーザー名は一切含まない)
出さない: セグメントの中身(フォルダ名・ユーザー名)。文字として出すのは記号
(引用符・不正文字のコード)のみで、これらはWindowsのフォルダ名として個人情報には
なり得ない構造記号である。
"""
import argparse
import os
import re
import sys

# dev#372: Windowsパスとして問題を起こしうる不正文字(制御文字0x00-0x1F + < > | ? *)。
# 引用符(")は別途 quote フィールドで独立に伝えるため、二重計上を避けてここには含めない。
# `:` はドライブレター区切りとして正常に使われるため対象外、`\` `/` はセパレータとして
# 別途扱う(root/segmentsで診断する)。
_INVALID_PATH_CHARS = frozenset('<>|?*') | frozenset(chr(c) for c in range(32))
# 未展開の環境変数プレースホルダ(%LOCALAPPDATA% 等)。値そのものは見ない。
_ENV_VAR_RE = re.compile(r'%[A-Za-z_][A-Za-z0-9_()]*%')


def _root_kind(p):
    """ルートの種類だけを返す(ドライブ文字自体は出さない。C:かD:かは診断に不要)。"""
    if p.strip() == "":
        return "none"
    if p.startswith("\\\\?\\") or p.startswith("\\\\.\\"):
        return "extended"
    if p.startswith("\\\\"):
        return "unc"
    if re.match(r'^[A-Za-z]:[\\/]', p):
        return "drive"
    if re.match(r'^[A-Za-z]:', p):
        return "driveRelative"
    if p.startswith("\\") or p.startswith("/"):
        return "rootRelative"
    return "relative"


def drive_type(path):
    """Windowsのドライブ種別(固定/リムーバブル/ネットワーク等)。取得できなければ '?'。
    非Windows環境やctypes呼び出し失敗時も安全に '?' へ倒す(診断補助情報の欠落は
    許容するが、例外で呼び出し元を巻き込んで止めてはいけない)。"""
    try:
        import ctypes
        drive = os.path.splitdrive(os.path.abspath(path))[0]
        if not drive:
            return "?"
        names = {0: "unknown", 1: "none", 2: "removable", 3: "fixed",
                 4: "network", 5: "CD-ROM", 6: "RAM disk"}
        t = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")
        return names.get(t, str(t))
    except Exception:
        return "?"


def path_facts(p):
    """生フルパスの代わりに診断に要る事実だけを返す。
    ファイル名(利用者のフォルダ名は含まない)+存在有無+ドライブ種別+パスの特徴のみで、
    ユーザー名等が乗る中間ディレクトリ名は一切出さない。
    dev#372: 従来はname/exists/drive_type/length/non_ascii_chars/has_space/UNC/
    under_OneDriveのみで、`GetPathRoot`例外のような「なぜ不正な形式だったか」を
    診断する手がかりが無かった(HMZ87QGE実例)。root種別・引用符・不正文字混入・
    未展開%VAR%・末尾の空白/ドット・拡張子・セグメント数を追加する(最小事実集合の
    定義はこのモジュールのdocstring参照)。新規フィールドはすべて純文字列解析で、
    filesystemには一切触れない(壊れたパスがOS API例外を誘発しないため。exists=は
    従来どおりos.path.existsを使うが、これはOSError/ValueErrorを内部で捕まえて
    Falseへ倒す安全な実装であることを確認済み)。"""
    if not p:
        return "(no path)"
    name = os.path.basename(p.rstrip("\\/")) or p
    # dev#372: 制御文字(改行含む)が生のname値に混ざると、この関数の出力が想定の
    # 1行に収まらなくなり、呼び出し元のログ整形・文字列照合を壊しうる。
    # 存在は invalid_chars フラグで別途伝えるので、name自体からは除去する。
    name = "".join(ch if ord(ch) >= 32 else "?" for ch in name)
    exists = os.path.exists(p)
    non_ascii = any(ord(c) > 127 for c in p)
    has_space = " " in p
    is_unc = p.startswith("\\\\") and not (p.startswith("\\\\?\\") or p.startswith("\\\\.\\"))
    onedrive = os.environ.get("OneDrive", "")
    under_onedrive = bool(onedrive) and os.path.normcase(p).startswith(os.path.normcase(onedrive))
    segments = len([seg for seg in re.split(r'[\\/]+', p) if seg])
    root = _root_kind(p)
    quote = '"' in p
    invalid_chars = any(ch in _INVALID_PATH_CHARS for ch in p)
    unexpanded_env_var = bool(_ENV_VAR_RE.search(p))
    trailing_whitespace = bool(p) and p[-1].isspace()
    trailing_dot = bool(p) and p[-1] == "."
    try:
        _, ext = os.path.splitext(p)
    except ValueError:
        ext = ""
    # 異常に長い/非ASCIIの「拡張子」はsplitextの誤爆の可能性があるため出さない
    if ext and (len(ext) > 10 or any(ord(c) > 127 for c in ext)):
        ext = "(masked)"
    return (f"name={name} exists={exists} drive_type={drive_type(p)} "
            f"length={len(p)} non_ascii_chars={non_ascii} has_space={has_space} "
            f"UNC={is_unc} under_OneDrive={under_onedrive} segments={segments} "
            f"root={root} quote={quote} invalid_chars={invalid_chars} "
            f"unexpanded_env_var={unexpanded_env_var} trailing_whitespace={trailing_whitespace} "
            f"trailing_dot={trailing_dot} ext={ext or 'none'}")


def display_path(p, bases=()):
    """生フルパスをログへ出さないための表示用ヘルパー。
    bases に列挙したディレクトリのいずれか配下なら相対パスにして返す
    (work配下の中間成果パスはこちらで足りる)。どれにも当てはまらなければ
    ファイル名のみを返す。実際のファイル操作には一切使わない(表示専用)。"""
    if not p:
        return p
    ap = os.path.abspath(p)
    for b in bases:
        if not b:
            continue
        try:
            b_abs = os.path.abspath(b)
            rp = os.path.relpath(ap, b_abs)
            if rp != "." and not rp.startswith(".."):
                return rp
        except Exception:
            continue
    return os.path.basename(ap.rstrip("\\/")) or ap


def factify(p, bases=()):
    """display_path + path_facts を1行にまとめた、呼び出し側が最も使いやすい形。
    - bases配下(work域等の既知安全パス)なら相対パスを主に見せる(十分に安全で有用)
    - それ以外は生パスを一切出さず、ファイル名+事実だけを返す(dev#7の核心対応:
      非%USERPROFILE%ドライブ・任意フォルダ名でも個人情報を出さない)
    """
    if not p:
        return "(no path)"
    disp = display_path(p, bases)
    ap = os.path.abspath(p)
    # dispがbases配下の相対パスに変換できた場合はそのまま使う(相対パスなので安全)。
    # できなかった場合(=ファイル名のみへ落ちた場合)はfactsも併記して診断価値を補う。
    if disp != (os.path.basename(ap.rstrip("\\/")) or ap):
        return disp
    return f"{disp} (path masked; {path_facts(p)})"


# ---------------------------------------------------------------------------
# dev#873: 汎用パスマスク正規表現が例外メッセージ本文ごと握りつぶす問題の修理。
#
# app_py\inquiry.py の `_GENERIC_PATH_RE`(SanitizeForClipboard L.4747-4749の
# 1:1移植)は、自由記述テキスト中から「ドライブ文字/UNCで始まる絶対パス」を
# 検出して factify する目的の正規表現だが、次の2点で「パスではない後続の
# 平文」まで無制限に飲み込んでいた(実ユーザー報告X65FG73S、v2.3.6で実証):
#
#   1) パス本体の文字クラス `[^\s"'<>|?*\r\n]` がコロン(:)を除外していない。
#      Windowsパスは(ドライブ文字直後を除き)コロンを含み得ない構造上の制約が
#      あるため、これは実質バグ。結果、`Select-String` が出す
#      `<ログのパス>:<行番号>:<内容>` 形式の行(export_from_unity.ps1の
#      Excerpt出力そのもの)や `TypeName: message` 形式の例外行が、
#      コロン以降の本文ごと「パスの一部」として飲み込まれる
#      (実例: `C:\...\unity_export.log:6653:Exception: Humanoid...` が
#      丸ごと1個のパスとしてマッチし、例外メッセージが完全消失した)。
#   2) 単語またぎの延長 `(?:[ \t](?![ \t(),])[^\s...]+)*` に、延長先が
#      実際にパスの続き(さらなるセグメント)であることを裏付ける条件が
#      無かった。そのため `C:\Users\foo\bar.fbx because of xyz` のような
#      平文が、`(` や `,` に当たるまで際限なく1個のパスへ吸い込まれる。
#
# 修理方針(2026-08-03オーナー指示「ログのみで診断可能にせよ」を受けて、
# 過剰マッチ優先だった旧設計の優先順位を反転):
#   1) パス本体の文字クラスからコロンを除く(ドライブ文字直後の1個は
#      リテラルの `[A-Za-z]:\\` 側で既に消費されるため無関係)。
#   2) 単語またぎの延長は、延長先の語が実際にバックスラッシュを含む
#      (=さらなるパスセグメントへ続いている)ことを先読みで要求する。
#      スペースを含むフォルダ名の最終セグメント単体(直後に続くセグメントが
#      無いケース)は、稀な取りこぼし(末尾の一単語がマスク漏れうる)を
#      許容する——「メッセージ本文ごと握りつぶす」という害の方が
#      「フォルダ名の末尾の一単語が生で残る」という害より大きく、今回の
#      優先順位転換の対象そのものであるため。
#
# 検証済みの効果(tests\path_privacy\test_path_privacy_dev873.py):
#   - dev#873の受入対照 `UnityException: something failed at
#     C:\Users\foo\bar.fbx because of xyz` → 型名・前後の説明文は残り、
#     埋め込まれた実パスだけがマスクされる。
#   - 実例(X65FG73S、個人情報を含まない形へ一般化)の
#     `<log>:<line>:Exception: <message>` 形式 → ログパス部分だけがマスクされ、
#     行番号・例外メッセージは生で残る。
#   - 健全な複数セグメントパス(スペースを含むフォルダ名+後続セグメントあり)は
#     従来どおり1個のパスとしてマスクされる(取りこぼし無し)。
#
# 現状(2026-08-03時点): 本モジュールはリファレンス実装として先に用意した。
# app_py\inquiry.py の `_GENERIC_PATH_RE`/`sanitize_for_clipboard` への実配線は、
# 同ファイルで並行中の別レーン(dev#921 GUI結線PR)との衝突を避けるため、この
# WPのスコープ外としている(dev#873のissueコメント参照)。app_pyはpipeline
# パッケージに依存しない配布物のため、配線時もこのモジュールを直接importする
# のではなく、既存の「独立実装しつつ同じ項目を揃える」方針を踏襲し、
# `_GENERIC_PATH_RE`/`factify_generic_path`側にこの正規表現の考え方を
# 移植する形になる想定。
#
# dev#1012(2026-08-03、PR #1010のレビュー中に発見): `C:\Program Files (x86)\...`
# のように括弧を含むパスが前半だけマスクされ、後半(`Files (x86)\Foo\bar.exe`)が
# 生のまま残っていた。dev#873の修理で入れた単語またぎ延長ガード
# `(?![ \t(),])`(次の語が空白/タブ/開き括弧/カンマなら延長しない)が、
# "Program Files (x86)" のように**空白の直後に開き括弧で始まる正当なパス語**
# (Windowsの慣用フォルダ名)まで機械的に弾いていたことが原因。実際には
# 直後の語自体にバックスラッシュが無くても(=`(x86)` 単体)、**その次の語**が
# バックスラッシュを含む(=`\Foo\bar.exe` へ続く)なら本物のパス継続と判定して
# よい。逆方向(dev#873)の「延長先にバックスラッシュの裏付けが無い語まで
# 際限なく飲み込む」問題を再発させないよう、先読みの範囲は**最大2語先**まで
# (「1個の空白区切り語だけを挟んでよい」)に限定し、無制限延長には戻さない。
#   - `(?![ \t(),])` ガード自体は撤去した: 実際に効いていたのはバックスラッシュ
#     先読みの方で、`(),` 除外は(このモジュールの既存試験群では)冗長だった
#     ことを実測で確認済み(work\wp_pii_library\PROGRESS.md参照)。
# 同時に、パス本体の文字クラスから単一引用符 `'` の除外も外した: `O'Brien`
# のようなアポストロフィを含むフォルダ/ユーザー名が、コロン同様に「そこで
# 分断されて後半が生で残る」dev#1012と同型の漏洩を起こすことを走査で発見した
# (二重引用符 `"` は既存どおり除外を維持。ログでの引用符くくり
# `"C:\path with spaces"` を想定した実用上の判断で、`quote` フィールドで
# 別途扱う対象もこちらのため)。
_GENERIC_PATH_BODY_CHAR = r'[^\s"<>|?*:\r\n]'

# 単語またぎの延長1ホップ分。「直後の語自体がバックスラッシュを含む」
# (=すぐパスの続きと分かる)か、「直後の語にはバックスラッシュが無いが、
# その次の語にはある」(=間に1個だけ非バックスラッシュの修飾語を挟んでよい、
# `(x86)` 相当)のいずれかを許可する。3語以上連続で非バックスラッシュの語が
# 続く場合(dev#873の`because of xyz`のような散文)は依然として延長を止める。
_GENERIC_PATH_HOP = (
    r'[ \t](?![ \t])'
    r'(?:'
    r'(?=' + _GENERIC_PATH_BODY_CHAR + r'*\\)' + _GENERIC_PATH_BODY_CHAR + r'+'
    r'|'
    + _GENERIC_PATH_BODY_CHAR + r'+[ \t](?![ \t])(?=' + _GENERIC_PATH_BODY_CHAR + r'*\\)'
    + _GENERIC_PATH_BODY_CHAR + r'+'
    r')'
)

GENERIC_PATH_RE = re.compile(
    r'(?:[A-Za-z]:\\|\\\\)' + _GENERIC_PATH_BODY_CHAR + r'+'
    r'(?:' + _GENERIC_PATH_HOP + r')*'
)


def mask_generic_paths_in_text(text, factify_one=None):
    """dev#873: 自由記述テキスト中の汎用パス(ドライブ文字/UNC始まり)を
    GENERIC_PATH_RE で検出し、構造保存型で伏せる。呼び出し元がfactify_one
    (1個のパス文字列 -> 表示用文字列)を渡さなければ、本モジュールの
    factify()相当(ファイル名+事実)を既定で使う。
    パスではない周辺の平文(例外メッセージ本文・行番号等)は一切変更しない。
    """
    if not text:
        return text
    if factify_one is None:
        def factify_one(p):
            name = os.path.basename(p.rstrip("\\/")) or p
            return f"{name} (path masked; {path_facts(p)})"
    return GENERIC_PATH_RE.sub(lambda m: factify_one(m.group(0)), text)


def _main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_factify = sub.add_parser("factify", help="1個のパスを伏字化して標準出力へ1行返す")
    p_factify.add_argument("path")
    p_factify.add_argument("--base", action="append", default=[],
                            help="このディレクトリ配下なら相対パスとして表示してよい(複数指定可)")

    args = ap.parse_args(argv)
    if args.cmd == "factify":
        sys.stdout.write(factify(args.path, tuple(args.base)) + "\n")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
