# inquiry.py -- 問い合わせ送信API契約(DESIGN.md §2.5)のPython移植。
#
# 移植元: app\DiveToPalworld.cs
#   - SanitizeForClipboard          (L.4673-4737)
#   - FactifyGenericPath            (L.4754-4766)
#   - GenericAbsolutePathRegex      (L.4747-4749)
#   - AddFolderToken                (L.4768-4776)
#   - BuildReportPayloadJson        (L.4316-4361, 2オーバーロード)
#   - JsonEscape                    (L.4363-4383, json.dumpsに置き換えたため本ファイルには無い)
#   - SendReportPayload             (L.4391-4440)
#   - GetReportBaseUrl              (L.720-725)
#   - NormalizeLogForComparison     (L.4255-4266)
#
# 正本: work\wp532A\DESIGN.md §2.5。CLIから叩ける旧`--check-sanitize-clipboard`の
# 単体表(CheckSanitizeForClipboardLogic, L.4105-4162)は app_py\tests\test_inquiry.py
# へ1:1で移植した(受入条件①)。
#
# 依存の分離(WP-A5のスコープが inquiry.py + ui/support_dialog.py のみで
# main_window.py に触れられないため): C#版はMainFormのvrmBox/statusLabel等の
# UIフィールドを直接読んでいたが、Python版は呼び出し元が値を渡す関数として
# 設計した(build_report_payload_jsonの引数群)。ToolVersion定数もここでは
# 定義せず引数で受け取る(main_window.pyのTOOL_VERSION定数と重複させないため。
# 統合WPでui.main_window.TOOL_VERSIONを渡す想定)。
from __future__ import annotations

import base64
import gzip
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

# dev#25: 不具合報告の送信先(Cloudflare Worker)。環境変数 D2P_REPORT_BASEURL で
# 上書き可能(GetReportBaseUrl L.720-725と1:1。疎通しない偽URLを与えればオフライン
# 縮退の試験ができる、通常ユーザーは触らない)。
REPORT_BASE_URL_DEFAULT = "https://report.osakishokai.com"
_REPORT_BASEURL_ENV = "D2P_REPORT_BASEURL"


def get_report_base_url() -> str:
    """GetReportBaseUrl (L.720-725) 相当。末尾スラッシュは除去する。"""
    env = os.environ.get(_REPORT_BASEURL_ENV)
    if env:
        return env.rstrip("/")
    return REPORT_BASE_URL_DEFAULT


# ---------------------------------------------------------------------------
# SanitizeForClipboard (L.4673-4737)
# クリップボードへ渡す/サーバーへ送る直前の文字列からユーザーを特定できる情報を
# 伏せる。呼び出し元はコピー・送信の直前のみで使うこと(画面表示・ログファイルには
# 適用しない、C#版と同じ運用方針)。
# ---------------------------------------------------------------------------

# 任意ドライブの絶対パス(例: D:\Users\...\avatar.prefab)またはUNCパス
# (\\server\share\...)にマッチする。GenericAbsolutePathRegex (L.4747-4749) と
# 1:1(C#の verbatim 文字列 `\\`は2文字=正規表現で1個のバックスラッシュ、
# `\\\\`は4文字=正規表現で2個のバックスラッシュ=UNC先頭、という対応関係を
# Pythonのraw文字列でもそのまま再現している)。
#
# dev#873(2026-08-03、実報告X65FG73S): 旧設計は2点の理由でパス以降の例外
# メッセージ本文まで飲み込んでいた——(1)パス本体の文字クラスがコロンを
# 除外しておらず、Select-Stringが出す `<path>:<line>:<content>` 形式や
# `TypeName: message` 形式でコロン以降の本文ごとパスとして飲み込む、
# (2)単語またぎの延長に「延長先が本当にパスの続きか」の裏付けが無く、
# `C:\Users\foo\bar.fbx because of xyz` のような平文を無制限に飲み込む。
# 修理版はpipeline\py\path_privacy.py::GENERIC_PATH_RE(dev#873、10テストで
# 検証済み)と同じ考え方——パス本体からコロンを除外し、単語またぎの延長は
# 延長先がバックスラッシュを含む(=実際にさらなるセグメントへ続く)ことを
# 先読みで要求する——をこちらの独立実装へも移植した(app_pyはpipeline
# パッケージに依存しない配布物のため、importせず同じロジックを再現する
# 既存方針を踏襲)。
#
# dev#1012(2026-08-03、PR #1010レビュー中に発見): `C:\Program Files (x86)\...`
# のような括弧を含むパスが前半だけマスクされ、後半が生のまま残っていた。
# dev#873の延長ガード `(?![ \t(),])` が、"Program Files (x86)" のような
# **空白の直後に開き括弧で始まる正当なパス語**まで機械的に弾いていたのが
# 原因。直後の語自体にバックスラッシュが無くても(`(x86)` 単体)、**その次の
# 語**がバックスラッシュを含む(`\Foo\bar.exe` へ続く)なら本物のパス継続と
# 判定してよい。先読みの範囲は最大2語先までに限定し(dev#873の「無制限延長」
# には戻さない)、`(?![ \t(),])` ガード自体はバックスラッシュ先読みに対して
# 冗長だったため撤去した(pipeline\py\path_privacy.pyのGENERIC_PATH_REと
# 揃えてある、詳細な設計理由はそちらのコメント参照)。
# 同時に、パス本体の文字クラスから単一引用符 `'` の除外も外した: `O'Brien`
# のようなアポストロフィを含むフォルダ/ユーザー名が、コロン同様に途中で
# 分断され後半が生で残る同型の漏洩を走査で発見したため(二重引用符 `"` は
# 既存どおり除外を維持)。
_GENERIC_PATH_BODY = r'[^\s"<>|?*:\r\n]'
_GENERIC_PATH_HOP = (
    r'[ \t](?![ \t])'
    r'(?:'
    r'(?=' + _GENERIC_PATH_BODY + r'*\\)' + _GENERIC_PATH_BODY + r'+'
    r'|'
    + _GENERIC_PATH_BODY + r'+[ \t](?![ \t])(?=' + _GENERIC_PATH_BODY + r'*\\)'
    + _GENERIC_PATH_BODY + r'+'
    r')'
)
_GENERIC_PATH_RE = re.compile(
    r'(?:[A-Za-z]:\\|\\\\)' + _GENERIC_PATH_BODY + r'+'
    r'(?:' + _GENERIC_PATH_HOP + r')*'
)

# SteamID64(7656119で始まる17桁の数字)
_STEAM_ID_RE = re.compile(r"\b7656119\d{10}\b")


# ---------------------------------------------------------------------------
# dev#1011: 汎用PII(氏名相当のメールアドレス・電話番号・IPアドレス・
# クレジットカード・APIキー/トークン等)の併用レイヤー。
#
# オーナー裁定(2026-08-03、issue #1011): 「うちのログプライバシーは業界標準の
# ○○をつかっています、で説明おわるじゃん」——採用理由は「バグが減る」では
# なく「説明が済む」こと。方針は(B)併用: 汎用PIIは業界標準ライブラリに
# 任せ、ファイルパスは既存の自作実装(_GENERIC_PATH_RE等、上のコメント群)を
# 引き続き使う(調査の結果、Windowsローカルファイルパスを検出対象に含む
# 既製ライブラリは1つも存在しなかったため。work\wp_pii_library\ 完了報告参照)。
#
# ライブラリ選定: issue #1011の机上調査で筆頭候補だった scrubadub は、
# 実機検証(本WP)で `Requires-Dist: textblob, scikit-learn, ...` という
# **必須**(オプション扱いではない)依存を確認し、pip downloadすると
# textblob->nltk・scikit-learn->numpy/scipyまで芋づる式に落ちてくる
# (合計100MB超)ことを実測した。「軽量」という当初評価は install_requires
# を実測する前の机上判断で、誤りだった。次点だったMicrosoft Presidioは
# 公式ドキュメントでspaCyパイプラインが構造的に必須と明記されており、
# 同様に不採用。DataFogはコア機能自体は正規表現ベースで軽量だが、
# `datafog/__init__.py` が無条件に `.core` → `.models.anonymizer` →
# `pydantic`(コンパイル済みバイナリを伴うpydantic-core)を import するため、
# 「datafogをimportするだけでpydantic-coreが要る」ことを実機検証で確認した。
# 本ツールの配布物は pip も site-packages も持たない embeddable Python
# 方式(app_py\build.py、`_pth`でimport site自体を無効化)であり、
# コンパイル済みバイナリの同梱にはbuild.py側の追加配線が要る(本WPの
# 書き込み範囲外)。
#
# logprivacy(MIT、PyPI上の install_requires はゼロ、Python>=3.10の
# 純Python実装)はこれらの制約をすべて満たす唯一の候補だった。0★・beta
# 表記のため、ソース全体(約90KB、60ファイル)を実際に読んで検証済み
# (ネットワーク通信を行うコードが無いこと、既定ルールセットが本ツールの
# 診断ログ実例で誤検知を起こさないことを実測。詳細は work\wp_pii_library\
# 完了報告参照)。
#
# 配線範囲: このモジュールは `import logprivacy` を試み、**存在すれば使い、
# 存在しなければ何もせず元のテキストをそのまま返す**(try/except ImportError。
# 本プロジェクトの「自動発見は必ず手動指定フォールバックを持つこと」原則を、
# 依存ライブラリの有無という軸に適用したもの)。**配布物(res\配下の埋め込み
# Python)への実際の同梱は PR #1014(dev#1011フォローアップ、app_py\build.py
# の `_copy_logprivacy()`)で完了済み**——`third_party\logprivacy-0.6.0-source\
# logprivacy\` の無改変vendorソースをビルド時に `res\app\logprivacy\` へ
# コピーする配線で、配布zipにも含まれる(コンパイル済みバイナリを持たない
# 純Pythonのためpip site-packages不要)。開発環境では
# `pip install logprivacy==0.6.0`(requirements-dev.txt参照)でも同様に
# 有効になる。
try:
    from logprivacy.cleaner import Cleaner as _LPCleaner
    from logprivacy.policy import CleanerPolicy as _LPCleanerPolicy
    from logprivacy.rules import (
        CredentialRule as _LPCredentialRule,
        CreditCardRule as _LPCreditCardRule,
        EmailRule as _LPEmailRule,
        SecretRule as _LPSecretRule,
        TokenRule as _LPTokenRule,
    )

    _LOGPRIVACY_AVAILABLE = True
except ImportError:  # pragma: no cover -- 破損・欠落時のfail-openのみ通る経路
    _LOGPRIVACY_AVAILABLE = False


def _build_generic_pii_cleaner():
    """logprivacyの既定ルールセット(UrlRule, CredentialRule, TokenRule,
    SecretRule, CreditCardRule, EmailRule)から **UrlRuleを除いた**構成を返す。

    dev#1012レビュー時の指揮者裁定(2026-08-03、Masterライターの独立検証で
    発覚): 実装時に追加したIPAddressRule/PhoneRuleは、当初の誤検知確認漏れ
    (test_guid_survivesがたまたま踏まない検体だけを使っていた)により、
    以下2種の系統的な誤検知を見逃していた:
      - PhoneRule: ダッシュ区切りGUID(RFC4122形式、相関ID・セッションIDとして
        診断ログに頻出)の末尾数字列を電話番号と誤認識し部分破壊する
        (例: "{A1B2C3D4-E5F6-4789-9ABC-DEF012345678}" ->
        "{A1B2C3D4-E5F6-4789-9ABC-DEF[PHONE]}")
      - IPAddressRule: 4分割の数字バージョン文字列(.NET/Windowsアセンブリ
        バージョンの標準形式、診断ログに頻出)をIPv4アドレスと誤認識する
        (例: "assembly version: 1.0.0.0" -> "assembly version: [IP_ADDRESS]")
    このツールはローカル変換のみを行い通信先は自ツールのインフラに限られる
    ため、電話番号・IPアドレスがログに含まれる見込みは薄く、GUID・バージョン
    文字列という診断価値の高い情報を壊すコストの方が大きいと判断し
    (診断価値 > この2ルールのPII検出価値)、指揮者裁定によりこの2ルールを
    除外した。既定に含まれるEmail/Credential/Token/Secret/CreditCardの
    誤検知は確認されていない(除外しない)。

    UrlRuleを除外する理由(実測、work\\wp_pii_library\\完了報告参照):
    このツールの診断ログに現れるURLは、ほぼ全て自ツールのインフラ
    (Blenderダウンロード元 download.blender.org、問い合わせ送信先
    report.osakishokai.com、マニュアルURL dl.osakishokai.com)であり、
    ユーザーのPIIではなく診断に有用な情報。既定のUrlRuleを含めた状態で
    実測すると、この3種のURLがいずれも無差別に `[URL]` へ潰れることを
    確認した。「診断に必要な文字列を誤って潰さない」(dev#873/CLAUDE.md
    「値を寄せて合わせる修正は却下」と同じ精神)を優先し、この層では
    意図的に含めない。

    既定ルールセット(Credential/Token/Secret/CreditCard/Email)は、GUID・
    バージョン文字列・ハッシュ値・タイムスタンプ・解像度表記等に対して
    誤検知が無いことを実測済み(完了報告の「誤検知の確認結果」節参照)。"""
    if not _LOGPRIVACY_AVAILABLE:
        return None
    rules = (
        _LPCredentialRule(),
        _LPTokenRule(),
        _LPSecretRule(),
        _LPCreditCardRule(),
        _LPEmailRule(),
    )
    policy = _LPCleanerPolicy.default().with_rules(*rules)
    return _LPCleaner(policy=policy)


_GENERIC_PII_CLEANER = _build_generic_pii_cleaner()


def sanitize_generic_pii(text: Optional[str]) -> Optional[str]:
    """dev#1011: 汎用PII(メールアドレス・電話番号・IPアドレス・
    クレジットカード番号・APIキー/トークン等)をlogprivacy経由で伏せる。
    ライブラリが未導入の環境(現状の配布物を含む、上のコメント参照)では
    何もせず text をそのまま返す。パス伏字化(_GENERIC_PATH_RE等)は一切
    代替しない、独立した追加レイヤーとして適用する前提の関数。"""
    if not text or _GENERIC_PII_CLEANER is None:
        return text
    try:
        return _GENERIC_PII_CLEANER.clean_text(text)
    except Exception:  # noqa: BLE001 -- 汎用PII層の失敗で全体(パス伏字化済みの
        # 結果)を巻き込んで失わない。伏字化が弱まるより、この層をスキップして
        # 既存の伏字化結果を返す方が安全(dev#921「失敗しても壊さない」方針と同じ)。
        return text


def _known_folder(env_name: str) -> Optional[str]:
    """AddFolderToken (L.4768-4776) のうち Environment.GetFolderPath 相当部分。
    Windows環境変数から直接引く(Pythonにos.path.expanduser以上の特殊フォルダ
    APIが無いため。LOCALAPPDATA/APPDATA/USERPROFILEはいずれもWindowsが
    標準で設定する環境変数)。ルート直下等の異常に短い値(3文字以下)は
    誤爆の恐れがあるため対象外にする(AddFolderTokenの`path.Length > 3`と同じ)。"""
    v = os.environ.get(env_name)
    if v and len(v) > 3:
        return v
    return None


# dev#372: Windowsパスとして問題を起こしうる不正文字(制御文字0x00-0x1F + < > | ? *)。
# 引用符(")は別途 quote フィールドで独立に伝えるため、二重計上を避けてここには含めない。
# pipeline\py\path_privacy.py の同名集合と揃えてある(最小事実集合の定義はそちらが正、
# app_pyはpipelineパッケージに依存しない配布物のため独立に再現している)。
_PATH_INVALID_CHARS = frozenset('<>|?*') | frozenset(chr(c) for c in range(32))
# 未展開の環境変数プレースホルダ(%LOCALAPPDATA% 等)。値そのものは見ない。
_ENV_VAR_TOKEN_RE = re.compile(r'%[A-Za-z_][A-Za-z0-9_()]*%')


def factify_generic_path(raw_path: str) -> str:
    """FactifyGenericPath (L.4754-4766) 相当の拡張版。生パスの代わりに、診断に
    要る「事実」だけを返す(構造保存型の伏字化)。
    dev#372: 実ユーザー報告HMZ87QGE(v2.2.11)では、この関数(のC#原型)の出力が
    `<path len=120>` まで潰れ、長さ以外の手がかり(空文字か/引用符が残っているか/
    UNCの途中か/未展開の%VAR%か/末尾に不正文字があるか)が一切失われて原因究明が
    不能になった。C#版は退役済み(dev#652よりpy版が唯一の正)のため、ここでは
    1:1移植から離れて項目を拡張する: root種別・引用符・不正文字混入・未展開%VAR%・
    末尾の空白/ドット・セグメント数を追加する(最小事実集合の定義は
    pipeline\\py\\path_privacy.py の path_facts()/モジュールdocstringを正とし、
    ここはPythonパッケージ境界をまたげないための独立実装として項目を揃える)。
    後方互換: 既存呼び出し元・テストが依存する `<path len=`/`unc=true`/`ext=.X`
    の出力形は維持し、新規フィールドは末尾に追加する。"""
    if not raw_path:
        return raw_path
    p = raw_path
    try:
        _, ext = os.path.splitext(p)
    except ValueError:
        ext = ""
    # 異常に長い/記号だらけ/非ASCIIの「拡張子」はsplitextの誤爆の可能性があるため出さない
    if not ext or len(ext) > 10 or any(ord(c) > 127 for c in ext):
        ext = ""
    is_extended = p.startswith("\\\\?\\") or p.startswith("\\\\.\\")
    is_unc = p.startswith("\\\\") and not is_extended
    stripped_blank = p.strip() == ""
    if stripped_blank:
        root = "none"
    elif is_extended:
        root = "extended"
    elif is_unc:
        root = "unc"
    elif re.match(r'^[A-Za-z]:[\\/]', p):
        root = "drive"
    elif re.match(r'^[A-Za-z]:', p):
        root = "driveRelative"
    elif p.startswith("\\") or p.startswith("/"):
        root = "rootRelative"
    else:
        root = "relative"
    segments = len([seg for seg in re.split(r'[\\/]+', p) if seg])
    has_quote = '"' in p
    has_invalid = any(ch in _PATH_INVALID_CHARS for ch in p)
    has_env = bool(_ENV_VAR_TOKEN_RE.search(p))
    trail_ws = bool(p) and p[-1].isspace()
    trail_dot = bool(p) and p[-1] == "."

    parts = [f"<path len={len(p)}"]
    if is_unc:
        parts.append(" unc=true")
    if ext:
        parts.append(f" ext={ext}")
    parts.append(f" root={root}")
    parts.append(f" segs={segments}")
    if stripped_blank:
        parts.append(" blank=true")
    if has_quote:
        parts.append(" quote=true")
    if has_invalid:
        parts.append(" invalid=true")
    if has_env:
        parts.append(" env=true")
    if trail_ws:
        parts.append(" trailWs=true")
    if trail_dot:
        parts.append(" trailDot=true")
    parts.append(">")
    return "".join(parts)


def sanitize_for_clipboard(text: Optional[str]) -> Optional[str]:
    """SanitizeForClipboard (L.4673-4737) 相当。空文字列/Noneはそのまま返す
    (case7a/7bの受入条件そのもの)。"""
    if not text:
        return text

    # 1) 既知フォルダのパスを伏せる。%LOCALAPPDATA% / %APPDATA% は %USERPROFILE% の
    #    サブフォルダなので、長い順(具体的な方から先)に置換する(コメントL.4677-4680と同じ理由)。
    folder_map = []
    for env_name, token in (
        ("LOCALAPPDATA", "%LOCALAPPDATA%"),
        ("APPDATA", "%APPDATA%"),
        ("USERPROFILE", "%USERPROFILE%"),
    ):
        path = _known_folder(env_name)
        if path:
            folder_map.append((path, token))
    folder_map.sort(key=lambda kv: len(kv[0]), reverse=True)

    for path, token in folder_map:
        text = re.sub(re.escape(path), token, text, flags=re.IGNORECASE)

    # 2) SteamID64
    text = _STEAM_ID_RE.sub("<SteamID>", text)

    # 3) アカウント名がパス以外に露出している場合の保険(3文字以下は誤爆防止で対象外)
    user_name = os.environ.get("USERNAME") or os.environ.get("USER")
    if user_name and len(user_name) > 3:
        text = re.sub(
            r"(?<![A-Za-z0-9_])" + re.escape(user_name) + r"(?![A-Za-z0-9_])",
            "<user>",
            text,
            flags=re.IGNORECASE,
        )

    # 4) PCのマシン名も同様の理由で保険として伏せる(短い名前は除外)
    machine_name = os.environ.get("COMPUTERNAME")
    if machine_name and len(machine_name) > 3:
        text = re.sub(
            r"(?<![A-Za-z0-9_])" + re.escape(machine_name) + r"(?![A-Za-z0-9_])",
            "<machine>",
            text,
            flags=re.IGNORECASE,
        )

    # 5) dev#7: 汎用の最終防衛。任意ドライブの絶対パス・UNCパスを構造保存型で伏せる。
    #    1)〜4)より後に実行する(既にトークン化済みの文字列を誤って再度巻き込まないため)。
    text = _GENERIC_PATH_RE.sub(lambda m: factify_generic_path(m.group(0)), text)

    # 6) dev#1011: 汎用PII(メール・電話・クレジットカード・IP・APIキー等)を
    #    業界標準ライブラリ(logprivacy、導入されていれば)で伏せる。パス伏字化
    #    (5)より後に実行する順序上の理由: パス伏字化が既にパス内のユーザー名
    #    セグメントを構造事実(name=/root=等)へ潰しているため、この層は
    #    「パス構造の外側」に単独で現れるメールアドレス・電話番号・APIキー等を
    #    追加で捕捉する役割に絞れる(先にPIIライブラリを走らせると、まだ生の
    #    パス文字列の中の英数字断片を誤って別カテゴリのPIIと誤検知するリスクが
    #    上がるため、より枯れたパス伏字化を先に通す方が安全という判断)。
    text = sanitize_generic_pii(text)

    return text


# ---------------------------------------------------------------------------
# dev#921 第2層: unity_export.log等の全文添付用マスキング。
# 「同意を要にしない設計」(issue #921コメント、2026-08-02オーナー指摘を受けた
# 方針): 全文を送るなら、既定のsanitize_for_clipboard(=path_privacy.pyの
# 構造保存型伏字化と同じ発想、既にfactify_generic_path/UserProfile/SteamID/
# ユーザー名/マシン名の伏字化を実装済み)を1行ずつ適用する。既存のマスキング
# 実装(sanitize_for_clipboard)を再利用するだけで、新規のマスキングロジックは
# 書き起こさない。
#
# 「失敗しても壊さない」(同issueコメント): 巨大な外部ログ(Unityエディタの
# -logFile出力、数千行規模)を処理する以上、1行単位で伏字化に想定外の例外が
# 起きても全体を巻き込んで落とさない。該当行は内容を一切出力に含めず丸ごと
# 落とす(伏字化漏れで生の内容が素通しされるより、行が欠けているほうが安全)。
# 落とした行数は戻り値として呼び出し元へ伝える。
# ---------------------------------------------------------------------------

_ATTACHMENT_BEGIN_MARKER = "=== dev#921 layer2: full log attachment (masked) ==="
_ATTACHMENT_END_MARKER = "=== end of layer2 attachment ==="
_ATTACHMENT_DROPPED_LINE_MASK = "<line dropped during masking (unmaskable content removed for privacy)>"


def mask_full_log_for_attachment(text: Optional[str]) -> tuple[str, int]:
    """dev#921第2層: 全文添付用に、既存のsanitize_for_clipboardを1行ずつ適用する。
    戻り値は (masked_text, dropped_line_count)。1行の伏字化処理で想定外の例外が
    起きた場合、その行は _ATTACHMENT_DROPPED_LINE_MASK に置き換えて丸ごと落とし
    (原文は一切出力に含めない)、dropped_line_countをインクリメントする。
    空文字列/Noneは ("", 0) を返す。"""
    if not text:
        return "", 0
    lines = text.replace("\r\n", "\n").split("\n")
    out = []
    dropped = 0
    for line in lines:
        try:
            masked = sanitize_for_clipboard(line)
        except Exception:  # noqa: BLE001 -- 1行の伏字化失敗で全文添付を巻き込んで
            # 落とさない(dev#921: 失敗しても壊さない設計)。原文は一切保持しない。
            dropped += 1
            out.append(_ATTACHMENT_DROPPED_LINE_MASK)
            continue
        out.append(masked if masked is not None else "")
    masked_text = "\n".join(out)
    return masked_text, dropped


def build_layer2_attachment_block(full_log_text: Optional[str]) -> tuple[str, int]:
    """dev#921第2層: 全文(伏字化済み)を、開始/終了マーカーで囲んだ1ブロックへ
    組み立てる。build_report_payload_jsonのattachment_log_text引数から呼ばれる。
    戻り値は (block_text, dropped_line_count)。full_log_textが空/Noneなら
    ("", 0) を返す(呼び出し元はブロックを付加しない)。"""
    if not full_log_text:
        return "", 0
    masked, dropped = mask_full_log_for_attachment(full_log_text)
    lines = [_ATTACHMENT_BEGIN_MARKER, masked]
    if dropped:
        lines.append(
            "[dev#921: {} line(s) dropped during masking (unmaskable content removed "
            "for privacy; see PROGRESS/issue for detail)]".format(dropped)
        )
    lines.append(_ATTACHMENT_END_MARKER)
    return "\n".join(lines), dropped


# ---------------------------------------------------------------------------
# dev#921 全ログ添付版(第2層の一般化、2026-08-03オーナー裁定)。
# オーナー原文: 「僕のローカルと同じレベルのログ(サニタイズはショウガいない
# けど)がとれるようにして」「全部サニタイズしておくればいいだけでしょ。
# 表も何もいるか?」——取捨選択をしない。work_root\<name>\ 配下(+Unity輸出
# ディレクトリ・launch.log)に生成される診断ファイルを、指定ディレクトリ/
# 個別ファイルの群から丸ごと集めて1つのテキストへ束ね、既存の
# attachment_log_text引数(build_report_payload_json、既にmask_full_log_for_
# attachmentで1行ずつ伏字化される)へそのまま渡す。マスキングは新規に
# 書き起こさない(既存実装の再利用のみ)。送信経路も新設しない
# (log_gzip_b64に乗るだけ)。
#
# ファイルの収集範囲を決める呼び出し元(main_window.py)は、このモジュールの
# 関数へディレクトリ/ファイルのリストを渡すだけの薄い役割に留める設計
# (main_window.py側がwork_root/app_rootからパスを組み立て、実際にどの拡張子を
# 「ログ」とみなすかの判定はここに閉じる)。
# ---------------------------------------------------------------------------

# バイナリ成果物(pak本体・テクスチャ画像・3Dモデル・実行ファイル等)の拡張子。
# 「除外するのは明らかにログでないものだけ」(オーナー裁定)の実装。
#
# .gz(2026-08-03オーナー追加指示「送るものは全部、送信前のUI画面に表示
# しろ」を受けた実測結果で追加): vanilla\pak_entries.txt.gz(既に圧縮済みの
# テキストログ、ディスク上819KB)は展開すると約14.7MB(実測、本WP)になる。
# 元がgzip=「そのままでは不透明なバイナリ」であることに変わりはなく、
# 展開してまで含めるとUI確認ダイアログ(tkinter.Text)への挿入・伏字化
# (1行ずつのmask_full_log_for_attachment)双方が数十万行規模になり実用的な
# 応答性を失う(実測はテスト
# test_inquiry_full_log_attachment.py::test_measured_ui_insert_and_mask_
# performance_is_reasonable、完了報告のサイズ・応答性実測の節を参照)。
# 「バイナリ成果物は除外」の拡張子ベース基準をgzという保存形式そのものに
# 対して機械的に適用しているだけで、中身の取捨選択ではない。
_ATTACHMENT_BINARY_EXTS = frozenset({
    ".pak", ".png", ".jpg", ".jpeg", ".fbx", ".uasset", ".uexp",
    ".blend", ".blend1", ".dds", ".tga", ".exr", ".wav", ".mp3",
    ".ttf", ".otf", ".bin", ".dll", ".exe", ".ico", ".psd", ".zip",
    ".gz",
})

# 実測(本WP、2026-08-03、release_certの実変換出力): pipeline\py\
# build_pak_from_avatar.pyがPhase1で書き出す work\<name>\build\noue_work\
# dump\avatar_{male,female}.json は拡張子こそ.jsonだが「ログ」ではなく、
# メッシュの頂点・ウェイトを丸ごと直列化した中間ビルド成果物であり、
# 実測で1ファイルあたり約10MB(2性別で計約21MB)。これを含めた場合、
# gzip後でも約10MBとなり、サーバー側上限
# (infra\cloudflare\d2p-report\src\index.js MAX_BODY=5MB、
# log_gzip_b64復号後のバイト列に適用)を2倍超過して送信が413で失敗する
# (実測、完了報告のサイズ実測の節を参照)。バイナリ成果物と同じ
# 「明らかにログでないもの」の除外基準(拡張子でなくパスの目印で判定する
# 追加の1条件)として扱う。同じlogsディレクトリの
# dump_{Male,Female}.log(テキストの実行ログ、これは対象)とは別物。
_ATTACHMENT_EXCLUDE_PATH_MARKER = os.path.join("noue_work", "dump")


def _is_attachment_excluded(path: str) -> bool:
    """1ファイルが添付対象から外れるバイナリ/非ログ成果物かどうか。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in _ATTACHMENT_BINARY_EXTS:
        return True
    if _ATTACHMENT_EXCLUDE_PATH_MARKER in path:
        return True
    return False


def collect_log_like_files(dir_paths) -> list[str]:
    """dir_paths(ディレクトリパスのイテラブル)を再帰的に歩き、バイナリ/
    非ログ成果物を除いた全ファイルの絶対パスを昇順ソートして返す。
    存在しないディレクトリ(VRM直接入力でUnity輸出ディレクトリが無い、
    まだ一度も変換していない等)は黙ってスキップする——「ログが無いことを
    理由に問い合わせ送信自体を失敗させない」という既存dev#921の設計方針を
    そのまま踏襲する。"""
    out: list[str] = []
    for dir_path in dir_paths:
        if not dir_path or not os.path.isdir(dir_path):
            continue
        for dirpath, _dirnames, filenames in os.walk(dir_path):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                if _is_attachment_excluded(full):
                    continue
                out.append(full)
    out.sort()
    return out


def read_attachment_file_text(path: str) -> Optional[str]:
    """1ファイルを添付用に読み込む(UTF-8、デコード不能バイトは置換)。
    読み込み失敗はNoneを返し、呼び出し元は当該ファイルを黙ってスキップする
    (1ファイルの失敗で全体の添付を巻き込まない、dev#921「失敗しても
    壊さない」方針の踏襲)。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


_ATTACHMENT_FILE_MARKER = "----- file: {} -----"


def build_work_dir_attachment_text(
    labeled_dirs=(),
    labeled_files=(),
) -> str:
    """複数ディレクトリ・複数個別ファイルにまたがる診断ファイル群を、
    1つのテキストへ束ねる(build_report_payload_jsonのattachment_log_text
    引数へそのまま渡せる形。伏字化は呼び出し元がその後段
    (build_layer2_attachment_block経由)で1行ずつ適用するので、ここでは
    生テキストのまま返してよい)。

    labeled_dirs: [(label, dir_path), ...] -- 各ディレクトリを再帰的に
        collect_log_like_files() で歩く(labelは出力マーカーの接頭辞、
        例: "work"/"unity_export")。
    labeled_files: [(label, file_path), ...] -- ディレクトリの外にある
        個別ファイル(例: res\\logs\\launch.log)。存在しない/読めない
        ファイルは黙ってスキップする。

    戻り値: 全ファイル無しなら空文字列("")。呼び出し元
    (main_window.py)はこれをNone扱いして添付無しにしてよい(既存の
    get_attachment_log_text契約と同じ、「ログ0件でも送信は失敗させない」)。"""
    parts: list[str] = []

    for label, dir_path in labeled_dirs:
        if not dir_path:
            continue
        base = dir_path
        for path in collect_log_like_files([dir_path]):
            text = read_attachment_file_text(path)
            if text is None:
                continue
            try:
                rel = os.path.relpath(path, base)
            except ValueError:
                rel = os.path.basename(path)
            parts.append(_ATTACHMENT_FILE_MARKER.format(f"{label}/{rel}"))
            parts.append(text)

    for label, file_path in labeled_files:
        if not file_path or not os.path.isfile(file_path):
            continue
        if _is_attachment_excluded(file_path):
            continue
        text = read_attachment_file_text(file_path)
        if text is None:
            continue
        parts.append(_ATTACHMENT_FILE_MARKER.format(label))
        parts.append(text)

    return "\n".join(parts)


def normalize_log_for_comparison(text: Optional[str]) -> Optional[str]:
    """NormalizeLogForComparison (L.4255-4266) 相当。「送信済み後にログが変わったか」
    の比較専用の正規化。"date: "行(DateTime.Nowを分単位で埋め込むため1分でも
    経てば必ず変わる)だけを比較対象から除外する。"""
    if not text:
        return text
    lines = text.replace("\r\n", "\n").split("\n")
    out = []
    for line in lines:
        if line.startswith("date: "):
            continue
        out.append(line)
    return "".join(line + "\n" for line in out)


# ---------------------------------------------------------------------------
# BuildReportPayloadJson (L.4316-4361) / JsonEscape (L.4363-4383)
# ---------------------------------------------------------------------------


def build_report_payload_json(
    *,
    version: str,
    lang: str,
    os_description: str,
    avatar_name: str,
    status_text: str,
    channel: str,
    log_text: str,
    attachment_log_text: Optional[str] = None,
) -> tuple[str, str]:
    """BuildReportPayloadJson(string logText, out string maskedLog) 相当。
    ログ・meta とも、外へ出る文字列はすべて sanitize_for_clipboard を通してから
    詰める(channelのみ、C#同様に既知enumのみを返す値のため対象外)。

    戻り値は (payload_json, masked_log) のタプル(C#の out引数をPython流に置き換え)。
    JSONの組み立てはC#のJsonEscape手書き実装ではなく標準の json.dumps を使う
    (DESIGN.md §2.5に明記の通り、レスポンス側同様パース/生成方式の変更は
    契約を破壊しない=同一スキーマである限り置き換えて構わない)。

    §2.5契約のスキーマ:
        {"version": "...", "lang": "...",
         "meta": {"os": "...", "avatar": "...", "status": "...", "channel": "..."},
         "log_gzip_b64": "..."}

    dev#921 第2層(全文添付): attachment_log_text を渡すと(例:
    work\\<name>_export\\unity_export.log の全文)、mask_full_log_for_attachment で
    伏字化した上で、log_gzip_b64 に載る内容の末尾へマーカー付きブロックとして
    追記する(既存のlog_gzip_b64送信経路に乗せるだけで、新しいペイロード
    フィールド・新しい送信経路は作らない——issue #921の「二層化」の第2層。
    第1層=このmasked_logそのもの)。省略時(既定None)は従来どおりの1引数の
    挙動(添付ブロック無し)で、戻り値のmasked_log/log_gzip_b64は無変更。
    戻り値のmasked_log(第2要素)は常に「第1層(log_text)のみを伏字化した
    もの」を返す(添付ブロックは含まない。呼び出し元の変化検出用ベースの
    意味を変えないため)。"""
    masked_log = sanitize_for_clipboard(log_text)
    masked_os = sanitize_for_clipboard(os_description)
    masked_avatar = sanitize_for_clipboard(avatar_name)
    masked_status = sanitize_for_clipboard(status_text)

    gzip_source = masked_log or ""
    attachment_block, _dropped = build_layer2_attachment_block(attachment_log_text)
    if attachment_block:
        gzip_source = gzip_source + "\n\n" + attachment_block + "\n"

    raw = gzip_source.encode("utf-8")
    gz = gzip.compress(raw)
    log_gzip_b64 = base64.b64encode(gz).decode("ascii")

    payload = {
        "version": version,
        "lang": lang,
        "meta": {
            "os": masked_os,
            "avatar": masked_avatar,
            "status": masked_status,
            "channel": channel,
        },
        "log_gzip_b64": log_gzip_b64,
    }
    return json.dumps(payload, ensure_ascii=False), masked_log


# ---------------------------------------------------------------------------
# SendReportPayload (L.4391-4440)
# ---------------------------------------------------------------------------


@dataclass
class ReportSendResult:
    """ReportSendResult (L.4302-4308) 相当。"""

    ok: bool = False
    id: Optional[str] = None
    view_url: Optional[str] = None
    error: Optional[str] = None


# レスポンスから id/view_url を拾う正規表現(L.4421/L.4429と同じ、厳密JSON
# parseではない緩い抽出。DESIGN.md §2.5「json.loadsに置き換えて構わない」の
# 通りだが、サーバーが厳密なJSONを返さない場合の後方互換のため正規表現版を残す)
_ID_RE = re.compile(r'"id"\s*:\s*"([A-Za-z0-9]+)"')
_VIEW_URL_RE = re.compile(r'"view_url"\s*:\s*"([^"]+)"')

Transport = Callable[[str, str, str, int], str]


def _default_transport(url: str, payload_json: str, user_agent: str, timeout: int) -> str:
    """実HTTP送信(urllib.request、devtools\\support.pyと同じ流儀のstdlibのみ実装)。
    テストではこの関数を呼ばせず、必ずtransport引数でモックへ差し替えること
    (受入条件③: 実サーバーへの送信テストは禁止)。"""
    req = urllib.request.Request(
        url,
        data=payload_json.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": user_agent},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def send_report_payload(
    payload_json: str,
    append_to_id: Optional[str] = None,
    *,
    base_url: Optional[str] = None,
    tool_version: str = "",
    timeout: int = 20,
    transport: Optional[Transport] = None,
) -> ReportSendResult:
    """SendReportPayload (L.4391-4440) 相当。例外はすべてErrorへ落とし、呼び出し元が
    エラー表示せず縮退案内に使えるようにする(C#版と同じ設計方針)。

    append_to_id: None/空なら新規 POST /report。指定があれば
    POST /report/<ID>/append (dev#42bの再送仕様、サーバーは新IDを発行せず
    同じid/view_urlを返す)。

    transport: (url, payload_json, user_agent, timeout) -> response_text の関数。
    省略時は実HTTP送信(_default_transport)。テストは必ず差し替えて実サーバーに
    触れないこと。
    """
    result = ReportSendResult()
    try:
        url_base = base_url or get_report_base_url()
        if append_to_id:
            url = f"{url_base}/report/{urllib.parse.quote(str(append_to_id), safe='')}/append"
        else:
            url = f"{url_base}/report"
        # 独自UA必須(既定UAはbot対策403の実測あり、L.4405-4406のコメントと同じ理由)
        user_agent = "Uchinoko-Support/" + str(tool_version).lstrip("v")
        post = transport or _default_transport
        resp_text = post(url, payload_json, user_agent, timeout)

        m = _ID_RE.search(resp_text)
        if not m:
            result.error = "サーバー応答に報告IDが含まれていません: " + (
                resp_text[:200] if resp_text else ""
            )
            return result
        result.id = m.group(1)
        mv = _VIEW_URL_RE.search(resp_text)
        result.view_url = (
            mv.group(1).replace("\\/", "/") if mv else f"{url_base}/r/{result.id}"
        )
        result.ok = True
    except Exception as ex:  # noqa: BLE001 -- C#版もcatch(Exception)で全例外を握りつぶす
        result.error = str(ex)
    return result
