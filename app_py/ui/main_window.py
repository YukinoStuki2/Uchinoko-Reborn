# main_window.py -- MainWindow(旧 app\DiveToPalworld.cs の MainForm 相当)の骨格。
#
# dev#532 方針A WP-A1: DESIGN.md(C:\P\Work\DiveToPalworld\work\wp532A\DESIGN.md)
# §1.1 の全25画面要素を配置するだけの「骨格」。イベントハンドラは全部stubで、
# クリックしても実処理はせず、ログ欄へ「未実装」と出すだけ(_stub()参照)。
# 実処理の結線はWP-A2〜A6が担当する(DESIGN.md §5.2)。
#
# レイアウトはDESIGN.md §4.2の方針どおり絶対座標(tkinterのplace())を踏襲する。
# 座標値はDiveToPalworld.csコンストラクタ(L.903-1306)のLeft/Top/Width実測値を
# 転記したもの(convertButton幅などC#側で実測フォント幅により動的に変わる値は
# 固定近似値へ寄せている)。指揮者裁定により本WP(基盤)では見た目の作り込みは
# 求められていない(「見た目チープ容認」)ため、pixel-perfect一致は狙っていない。
#
# 依存モジュールの解決: このファイルは `python app_py\main.py` から
# `from ui.main_window import MainWindow` の形でimportされる想定で、main.pyが
# 先に app_py ディレクトリを sys.path へ入れるため、ここでは素朴に
# `import i18n` / `import settings` の絶対importで足りる(相対importは
# main.pyを直接スクリプト実行する受入条件①と相性が悪いため使わない)。
#
# dev#532 方針A WP-A2(2026-08-01): 変換系ハンドラの結線。convertButton/
# cancelButton/matsButton/previewButtonをpipeline_runner.py(WriteJob/
# BuildConvertArgs/FindPwsh/RunPipeline相当)へ実配線する。書き込み許可
# (DESIGN.md §5.2 WP-A2行)は「main_window.pyの該当ハンドラ部分のみ」のため、
# ウィジェット生成(_build_widgets)自体はWP-A1のまま変更していない
# (コマンド差し替え1行+ハンドラメソッド追加のみ)。
# browse/D&D経由のSetVrm本体(セッションログ復元・以前のjob.json設定復元)は
# 「変換系」の外側(WP-A1の骨格が持たない未実装領域)であり、本WPでは
# 「vrmBoxへパスを入れて変換を開始できる状態にする」最小限のみ扱う
# 〈合理的解釈〉。prefab選択時のRunUnityExport起動はconvertButton系の
# 前段としてWP-A2で結線し、完了後にそのまま同じ最小SetVrmへ引き継ぐ。
#
# dev#532 方針A WP-A8(2026-08-02): D&D(#4)の実配線。ui\dnd.py(ctypes+
# Win32 API自前実装、外部バイナリ非同梱)をrootウィンドウ全体へ
# インストールする(app\DiveToPalworld.csのAllowDrop=trueがForm全体に
# 掛かっているのと同じ範囲、L.946-948)。受理拡張子・複数ファイル時の
# 挙動(先頭1件のみ判定)はdnd.pick_dropped_path()が持ち、本ファイルは
# 採用/不採用後の分岐(prefabならUnity輸出、それ以外はSetVrm)だけを持つ。

from __future__ import annotations

import json
import os
import platform
import queue
import re
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import messagebox, ttk
from typing import Callable, Optional

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import blender_setup  # noqa: E402
import compat_check  # noqa: E402
import dist_channel  # noqa: E402
import i18n  # noqa: E402
import inquiry  # noqa: E402
import lu_export  # noqa: E402  (dev#702 第3弾WP-3: prefabキャッシュ鮮度判定+sig保存)
import noue_full_build  # noqa: E402
import pak_manager  # noqa: E402
import path_health  # noqa: E402
import pipeline_runner  # noqa: E402
import preview_freshness  # noqa: E402
import progress_eta  # noqa: E402
import settings  # noqa: E402
import update_check  # noqa: E402
import warm_startup  # noqa: E402
from ui import dnd  # noqa: E402
from ui import lab_window  # noqa: E402  (dev#1186: ラボUI基盤)
from ui import preflight_warning_dialog  # noqa: E402  (dev#1230: preflight非ブロック化の警告ダイアログ)
from ui import support_dialog  # noqa: E402
from ui import workarea  # noqa: E402

# DiveToPalworld.cs L.704 (devtools\release.py がリリース時にスタンプする値。
# WP-A1の骨格では固定値で近似し、実際の版管理はB1/D1側の課題とする)
TOOL_VERSION = "v2.13.0"

# オンラインマニュアルのURL(指揮者裁定: マニュアルを開く導線があれば既定
# ブラウザで開く)。DESIGN.md §1.1の25要素にはマニュアル専用ボタンは含まれて
# いない(現行app\DiveToPalworld.csにも該当ボタンは存在しない、grep実測で
# 確認済み)ため、本WPでは新規ボタンを追加していない。URL定数だけ、他WPが
# ボタンを追加する時にすぐ使えるよう用意しておく
# (公開先: manual\manual.html / manual\manual.en.html、README.mdのリンク参照)。
MANUAL_URL = "https://pandrabox.github.io/DiveToPalworld/manual/manual.html"

# dev#1136: 「こだわり設定」パネルのレイアウト整理で、パネル本体の高さが
# 80→132へ伸びた。この定数の元の由来(dev#551コメント、下記に残す)から
# の増分(132-80=52px)を_KODAWARI_PANEL_DELTAとlayout_content_area()の
# top基準の両方へ同じだけ加算してあり、閉じた状態の見た目(プレビュー欄が
# トグル直下へ詰まる絶対位置)はdev#1136前後で変わらない(1058x80→
# 1058x132のどちらでも「トグル直下+10px」に閉時topが来る計算)。
#
# dev#1136追撃(PR #1144マージ後のオーナー実機確認でダメ出し、囲みフレーム
# +見出しを廃止し影の濃さ/身長/削除ボーンを3行構成にし直した): 初版
# (PR #1144)は囲みフレーム2枚+キャプション見出し1つで124だったが、それら
# を廃止し影の濃さ・身長を別行にした結果132になった(80→124→132の2段階、
# 詳細は_build_widgets内のdev#1136追撃コメント参照)。
# dev#19揺れものUIプロトタイプ(2026-08-11、work\rd_19_flight\briefs\
# uimock2_embedded.md): 標準機能「揺れの度合い」行(#12d)をこだわり設定
# パネルの3行目として追加した分、+44px(影の濃さ/身長と同じ行高44の1行分)。
# 増分をこの定数とlayout_content_area()のtop基準の両方へ同じだけ加算する
# (dev#1136の44px加算と全く同じ手順、下記_KODAWARI_PANEL_DELTAコメント参照)。
#
# 修正イテレーション2(オーナーUX評価#1、2026-08-11、work\rd_19_flight\
# briefs\uimock2_fixes2.md): 「揺れの度合い行の下の余白が大きすぎる」との
# 指摘。hidden_root(root.withdraw())で実ウィジェットを構築して実測した
# (work\rd_19_uimock2\measure_kodawari_margin.py)ところ、行3(揺れの度合い、
# ボタン無し)の実コンテンツ下端はy=126で、パネル下端(176)との余白は50px
# あった。単行目(dev#1136前、パネル高80)時点の余白は41px(ボタン下端39)
# だったので、dev#1136がパネルを80→132(+52px)にした際、行1本ぶんの行送り
# (44px)より8px多く積んだ(52-44=8)。この+8pxが「見た目のズレ」の実体
# (前任はこの+52パターンをそのまま踏襲して132→176(+44px)と加算しており、
# 新たな上乗せは無いが、dev#1136由来の+8pxがそのまま残っていた)。この8pxを
# 削り、余白を41px相当(実測: 168-126=42px)へ戻す。_KODAWARI_PANEL_DELTAと
# layout_content_area()のtop基準からも同じ8pxを引き、対応関係
# (DELTA = HEIGHT + 4、top基準 = HEIGHT + panel.y(118) + 10)を保つ。
#
# dev#1508 W2b(2026-08-16、標準UI「ゆらす」ON/OFF化、.devonly\docs\sway\sway_wrapup\
# SPEC.md §1): 行3の中身を4段tk.ScaleからON/OFFトグルへ置換したが、
# 行そのもの(高さ44px)は維持するため、この定数の値・計算根拠は無変更。
_KODAWARI_PANEL_HEIGHT = 132 + 44 - 8

# dev#551: 「こだわり設定」パネルが開閉に関わらず常に同じだけ場所を確保
# していた不具合(issue #551 指摘2)の解消に使う定数。パネル本体
# (kodawariPanel、y=118,height=80)の高さに、開いた状態のtoggleボタン
# 直下(y=114)からパネル下端(y=198)を経てプレビュー欄開始(y=208)までの
# 間隔ぶんを合わせた近似値。パネルが閉じている間は、この値だけプレビュー欄
# より下の全要素(_FOOTER_OPEN_GEOMETRY参照)を上へ詰め、ウィンドウの
# 高さも同じだけ縮める(MainWindow.layout_content_area()参照)。
#
# モジュールレベル定数にしてある理由: 既存の単体テスト(例:
# test_main_window_diagnostics_wiring.py の `_FakeSelf`)は MainWindow を
# 継承しない独立クラスへメソッドを直接生やす「フェイクself」方式を多用して
# おり、`self._KODAWARI_PANEL_DELTA` のようなクラス属性参照はそれらの
# フェイクselfでは解決できない(AttributeError)。モジュールグローバルなら
# self の型に関係なく参照できるため、既存テストの流儀を壊さずに済む。
#
# dev#1136: パネル高さが80→124(+44px)になったのに合わせ、84→128へ
# 同じ44pxだけ加算した。
# dev#1136追撃: さらに124→132(+8px)になったのに合わせ、128→136へ
# 同じ8pxだけ加算した(下のlayout_content_area()内の"top = 260 - delta"
# も同じ52px(=44+8)を208→260へ加算してあり、両者は対で動く)。
# dev#19揺れものUIプロトタイプ: パネルが132→176(+44px)になったのに合わせ、
# 136→180へ同じ44pxを加算した(layout_content_area()内の"top = 260 - delta"
# も260→304へ同じ44pxを加算してあり、両者は対で動く。_KODAWARI_PANEL_HEIGHT
# コメント参照)。
# 修正イテレーション2(オーナーUX評価#1): _KODAWARI_PANEL_HEIGHTから同じ
# 8pxを引いた(180→172)。両定数の対応関係(DELTA = HEIGHT + 4)を保つ。
_KODAWARI_PANEL_DELTA = 136 + 44 - 8

# dev#1572(2026-08-18ロードマップ「かたさが配線されていない問題」、
# 案C): dev#1508 W2b(2026-08-16)が「揺れの度合い」4段をON/OFFトグル
# 「ゆらす」へ一時的に置換したが、2.11で動いていた4択(なし/やわらかめ/
# ふつう/かため)を本WPで復元した。個別鎖の「ゆれかた」調整UI
# (sway_style_dialog.py、ラボ「揺れもの詳細」)は本WPで画面から隠蔽した
# ため(ui\lab_window.py LAB_FEATURESから除去、コードは温存)、揺れの
# 強さはこの標準4択が唯一の調整手段になる。
#
# 内部値(job.json `sway_intensity`キーの値そのもの、英語ASCII固定)と、
# スライダーindexの対応順は、当初issue #1572本文の列挙順(AIが書いた実装
# メモの語順)「なし/やわらかめ/ふつう/かため」で実装したが、オーナーの
# 記憶「v2.11の並びと違う」指摘(2026-08-19)を受けてv2.11.0タグの実ソース
# (git show v2.11.0:app_py/ui/main_window.py、コミットd0f0346e)で当時の
# 並びを確認したところ ["none","hard","normal","soft"](「なし/固め/ふつう/
# やわらかめ」)だった(dev#19プロトタイプ時代からv2.11.0まで不変)。
# 本WPでv2.11.0実測の並びへ復元する——並び順のみの変更であり、内部値・
# job.json`sway_intensity`へのマッピング・意味は変えない(既定選択
# "normal"も不変)。表示文言はSWAY_INTENSITY_I18N_KEYSで引く(既存キー
# SwayIntensityNone/Soft/Normal/Hardをそのまま再利用、新規追加なし)。
# 既定indexは"normal"(2026-08-11 UX評価「標準機能はふつう始まり」を
# 踏襲、dev#1508 W2bの既定ON=中立値"normal"とも整合)。
SWAY_INTENSITY_VALUES = ["none", "hard", "normal", "soft"]
SWAY_INTENSITY_I18N_KEYS = [
    "SwayIntensityNone", "SwayIntensityHard", "SwayIntensityNormal", "SwayIntensitySoft",
]
_SWAY_INTENSITY_DEFAULT_INDEX = SWAY_INTENSITY_VALUES.index("normal")

# job.json**復元**時(_apply_restored_settings、下記参照)の移行規則
# (dev#1572、3世代のjob.jsonを矛盾なく吸収する):
#   1. 新キー`sway_intensity`が存在しSWAY_INTENSITY_VALUESに含まれれば、
#      その値をそのまま使う(本WP以降・dev#19プロトタイプ時代の両方の
#      job.jsonがこの形)。
#   2. 上記が無く、dev#1508 W2b期に書かれた`sway_enabled`(bool)キーが
#      あれば、True→"normal"(中立値)/False→"none"へ変換する(W2b期は
#      4段の情報を持たずON/OFFのみだったため、ONは中立値へ丸める)。
#   3. どちらも無い(このWPより前のごく古いjob.json)場合は"none"
#      (旧仕様の既定=なし)。

# dev#933: pipeline\cli\ensure_blender.ps1 (dev#21 純ASCII化, PR #922) が出す
# ##PROGRESS## のphaseトークンをGUI表示用に翻訳するテーブル群。
# ensure_blender.ps1側は書き換えない(dev#21の目的=純ASCII化を保つため)ので、
# ここでGUI側だけがphase文字列→5言語文言の変換を担う。
#
# 固定文字列(可変部を含まないphase)は、i18n.py の i18n.PROGRESS_LABELS
# (i18n_data.json の `_progress_labels`)には**入れていない**: そちらは
# convert_noue.py側の##PROGRESS##ラベル専用の名前空間で、件数が
# tests\shipcheck\test_progress_label_i18n.py::test_acceptance_gate_label_and_
# template_counts により19件ちょうどに固定されている(C#版 Strings.
# ProgressLabelsとの1:1パリティ検査。本WPの書き込み許可外)。代わりに
# 通常のi18n_data.json TABLEキー(StatusBlenderPhase*)として持たせ、
# raw phase文字列→キー名の対応表 `_BLENDER_PHASE_KEY_MAP` で引く。
# 可変部を含むphaseは元々どちらの辞書形式でも表現できない(regexテンプレート
# 必須)ので、このモジュール内に専用テーブルを持つ(pipeline_runner.py.
# _PROGRESS_LABEL_TEMPLATES と同型だが、あちらを拡張すると本WPの書き込み
# 許可ファイル外に触れてしまうため、あえて別テーブルとして持つ。将来
# pipeline_runner.py側の書き込みが解禁されたWPで一本化を検討してよい、
# というのがdev#933完了報告に書く点検事項の1つ)。
_BLENDER_PHASE_KEY_MAP: dict[str, str] = {
    "Checking Blender status": "StatusBlenderPhaseCheckingStatus",
    "Blender is ready": "StatusBlenderPhaseReady",
    "Checking free disk space": "StatusBlenderPhaseCheckingDiskSpace",
    "Using specified zip (no download, test/offline mode)": "StatusBlenderPhaseUsingSpecifiedZip",
    "Verifying integrity (SHA256)": "StatusBlenderPhaseVerifyingIntegrity",
    "Extracting": "StatusBlenderPhaseExtracting",
    "Extraction complete": "StatusBlenderPhaseExtractionComplete",
    "Injecting Python environment patches": "StatusBlenderPhaseInjectingPatches",
    "Verifying Python environment (import ooz)": "StatusBlenderPhaseVerifyingPythonEnv",
    "Moving to final location": "StatusBlenderPhaseMovingToFinalLocation",
    "Blender setup complete": "StatusBlenderPhaseSetupComplete",
}

_BLENDER_PHASE_TEMPLATES: list[tuple[re.Pattern, dict[str, str]]] = [
    (
        re.compile(r"^Downloading Blender (.+) \(official site, ~390MB\)$"),
        {
            "ja": "Blender {0} をダウンロード中(公式サイト、約390MB)",
            "en": "Downloading Blender {0} (official site, ~390MB)",
            "ko": "Blender {0} 다운로드 중(공식 사이트, 약 390MB)",
            "zhTW": "正在下載 Blender {0}(官方網站,約 390MB)",
            "zhCN": "正在下载 Blender {0}(官方网站,约 390MB)",
        },
    ),
    (
        re.compile(r"^Downloading Blender (.+) \(mirror, ~390MB\)$"),
        {
            "ja": "Blender {0} をダウンロード中(ミラー、約390MB)",
            "en": "Downloading Blender {0} (mirror, ~390MB)",
            "ko": "Blender {0} 다운로드 중(미러, 약 390MB)",
            "zhTW": "正在下載 Blender {0}(鏡像,約 390MB)",
            "zhCN": "正在下载 Blender {0}(镜像,约 390MB)",
        },
    ),
    (
        re.compile(r"^Downloading \((.+)MB / (.+)MB\)$"),
        {
            "ja": "ダウンロード中 ({0}MB / {1}MB)",
            "en": "Downloading ({0}MB / {1}MB)",
            "ko": "다운로드 중 ({0}MB / {1}MB)",
            "zhTW": "正在下載 ({0}MB / {1}MB)",
            "zhCN": "正在下载 ({0}MB / {1}MB)",
        },
    ),
    (
        re.compile(r"^Extracting \((.+) / (.+) files\)$"),
        {
            "ja": "展開中 ({0} / {1} ファイル)",
            "en": "Extracting ({0} / {1} files)",
            "ko": "압축 해제 중 ({0} / {1} 파일)",
            "zhTW": "正在解壓縮 ({0} / {1} 個檔案)",
            "zhCN": "正在解压缩 ({0} / {1} 个文件)",
        },
    ),
]


def translate_blender_phase(raw: str, lang: Optional[str] = None) -> str:
    """dev#933: ensure_blender.ps1 由来の##PROGRESS##phase(ASCII固定文字列)を
    現在のUI言語へ翻訳する。pipeline_runner.translate_progress_label_dynamic()
    と同じ二段構え(固定辞書優先→可変部テンプレート)+同じフォールバック方針
    (どちらにも一致しなければ原文をそのまま返す。無言で空欄や `??key??` には
    しない -- 未知phaseでも情報が消えないことを優先する)。"""
    if not raw:
        return raw
    key = _BLENDER_PHASE_KEY_MAP.get(raw)
    if key is not None:
        return i18n.S(key, lang=lang)
    use_lang = lang or i18n.current_lang
    for pattern, fmt_table in _BLENDER_PHASE_TEMPLATES:
        m = pattern.match(raw)
        if not m:
            continue
        fmt = fmt_table.get(use_lang) or fmt_table.get("ja")
        if not fmt:
            return raw
        try:
            return fmt.format(*m.groups())
        except (IndexError, KeyError):
            return raw
    return raw


# dev#939 ①: ensure_blender.ps1 の Show-D2PFailureGuidance が出す
# [D2P_BLENDER_SETUP_FAIL]案内文(複数行)の、行単位の固定部分→i18nキー対応表。
# translate_blender_phase(dev#933)と同じ「固定行は辞書、可変部を含む行は
# regexテンプレート、どちらにも一致しない行はそのまま」という二段構えを、
# 単一行ではなく複数行のブロックへ適用したもの(_BLENDER_SETUP_FAIL_LINE_MAP/
# _BLENDER_SETUP_FAIL_LINE_TEMPLATESは翻訳対象の行のみを持ち、$TargetDirの
# 実パス行・[D2P_PATH_SHAPE]診断行は意図的に対象へ入れていない -- これらは
# 自然文ではなく生のパス/構造情報そのものが価値であるため)。
#
# dev#1242: blender_setup.run_ensure_blender_setup_process()がPowerShell実行
# ファイル自体の起動失敗(WinError2等)時に返すblender_setup.LAUNCH_FAIL_HEADER
# ("[D2P_BLENDER_SETUP_FAIL] Failed to launch ensure_blender.ps1.")もここへ
# 追加。ensure_blender.ps1が実際には一度も起動できていない(=ps1側の英語文言
# ではなくPython側で組み立てた文言)点が既存ヘッダ行と異なるが、
# FAIL_MARKER接頭辞を共有させることで既存の行単位翻訳機構にそのまま乗せた
# (実ユーザー報告issue dev#1242: 「日本語と中国語が混ざっている」の是正。
# 続く"Reason: {0}"行が既存テンプレートで翻訳され、OS生例外文字列は
# ラベル部分だけ翻訳された「詳細」として分離表示される)。
_BLENDER_SETUP_FAIL_LINE_MAP: dict[str, str] = {
    "[D2P_BLENDER_SETUP_FAIL] Blender setup failed.": "MsgBlenderSetupFailLineHeader",
    "[D2P_BLENDER_SETUP_FAIL] Failed to launch ensure_blender.ps1.":
        "MsgBlenderSetupLaunchFailLineHeader",
    "What to try:": "MsgBlenderSetupFailLineWhatToTry",
    '  1. Check your internet connection, then press "Full Convert (Create MOD)" '
    'or "Update Preview" again.': "MsgBlenderSetupFailLineStep1",
    "  2. If automatic download keeps failing, you can also set it up manually:":
        "MsgBlenderSetupFailLineStep2Intro",
    "       (2) Extract it, then copy the contents of the folder containing "
    "blender.exe directly into:": "MsgBlenderSetupFailLineStep2b",
    # dev#1608: the manual-placement path used to be a dead end (the app never looked at
    # what the user placed and always re-downloaded). Now that the full run adopts an
    # existing manually-placed Blender (ensure_blender.ps1's Invoke-D2PPatchAndVerify,
    # called before the download step), these two lines are literally true: retrying
    # verifies and uses what was placed, and a selectively-missing file (the two real
    # reports behind this fix, 67H3ETNH/UDBBTGAA, both lost only python.exe) points at
    # security-software quarantine as the most plausible cause.
    "       (3) Press \"Full Convert (Create MOD)\" or \"Update Preview\" again -- "
    "the app will verify what you placed and use it (no re-download).":
        "MsgBlenderSetupFailLineStep2c",
    "  3. If a specific file is missing after extraction (for example python.exe), "
    "your security software may have quarantined it. Check your antivirus/security "
    "software's quarantine log and restore the file, or add an exclusion for the "
    "folder above, then try again.": "MsgBlenderSetupFailLineStep3AV",
    "Diagnostic info (path structure only, no folder names included):":
        "MsgBlenderSetupFailLineDiagHeader",
}

_BLENDER_SETUP_FAIL_LINE_TEMPLATES: list[tuple[re.Pattern, dict[str, str]]] = [
    (
        re.compile(r"^Reason: (.*)$"),
        {
            "ja": "理由: {0}",
            "en": "Reason: {0}",
            "ko": "이유: {0}",
            "zhTW": "原因: {0}",
            "zhCN": "原因: {0}",
        },
    ),
    (
        re.compile(
            r"^       \(1\) Download the Windows x64 Portable \(zip\) build of "
            r"Blender (.+) from https://www\.blender\.org/download/$"
        ),
        {
            "ja": "       (1) https://www.blender.org/download/ からBlender {0} の"
            "Windows x64 Portable(zip)版をダウンロードする",
            "en": "       (1) Download the Windows x64 Portable (zip) build of "
            "Blender {0} from https://www.blender.org/download/",
            "ko": "       (1) https://www.blender.org/download/ 에서 Blender {0} 의 "
            "Windows x64 Portable(zip) 빌드를 다운로드",
            "zhTW": "       (1) 從 https://www.blender.org/download/ 下載 Blender {0} "
            "的 Windows x64 Portable(zip)版本",
            "zhCN": "       (1) 从 https://www.blender.org/download/ 下载 Blender {0} "
            "的 Windows x64 Portable(zip)版本",
        },
    ),
    (
        # dev#19 uimock2_fixes評価#6: blender_setup.py
        # do_ensure_blender_ready()のDEV_NOT_FOUND_NO_SCRIPT分岐
        # (開発チェックアウト等でensure_blender.ps1もblender.exeも無い場合)。
        # 旧版は生の日本語をPython側から直接返しており、英語UIモードでも
        # この1行だけ翻訳されず残る不具合だった(blender_setup.py側で修正済み、
        # 経緯は同ファイルのコメント参照)。
        re.compile(r"^Blender not found \(dev environment\): (.*)$"),
        {
            "ja": "Blenderが見つかりません(開発環境): {0}",
            "en": "Blender not found (dev environment): {0}",
            "ko": "Blender를 찾을 수 없습니다(개발 환경): {0}",
            "zhTW": "找不到 Blender(開發環境): {0}",
            "zhCN": "找不到 Blender(开发环境): {0}",
        },
    ),
]


def translate_blender_setup_fail_message(raw: str, lang: Optional[str] = None) -> str:
    """dev#939 ①: [D2P_BLENDER_SETUP_FAIL]案内文(複数行)を行単位で翻訳する。
    行ごとに _BLENDER_SETUP_FAIL_LINE_MAP(固定行)→_BLENDER_SETUP_FAIL_LINE_
    TEMPLATES(可変部を含む行)の順で試し、どちらにも一致しない行(自由記述の
    例外メッセージ・実パス・[D2P_PATH_SHAPE]診断行など)は無変更でそのまま
    残す(未知の内容でも情報が消えない、translate_blender_phaseと同じ
    フォールバック方針)。"""
    if not raw:
        return raw
    use_lang = lang or i18n.current_lang
    out_lines: list[str] = []
    for line in raw.split("\n"):
        key = _BLENDER_SETUP_FAIL_LINE_MAP.get(line)
        if key is not None:
            out_lines.append(i18n.S(key, lang=use_lang))
            continue
        translated: Optional[str] = None
        for pattern, fmt_table in _BLENDER_SETUP_FAIL_LINE_TEMPLATES:
            m = pattern.match(line)
            if not m:
                continue
            fmt = fmt_table.get(use_lang) or fmt_table.get("ja")
            if fmt:
                try:
                    translated = fmt.format(*m.groups())
                except (IndexError, KeyError):
                    translated = None
            break
        out_lines.append(translated if translated is not None else line)
    return "\n".join(out_lines)


# dev#1514: translate_blender_setup_fail_message()は「翻訳できない行は生のまま
# 残す」設計(dev#939、上のdocstring参照)であり、その生の行(OS/ps1由来の
# 生例外文"Reason: ..."・[D2P_PATH_SHAPE]診断行)がそのままダイアログ本文へ
# 流れ込んでいた(オーナー実見2026-08-16「非エンジニアにこのエラーを見せる
# 可能性があるのは馬鹿すぎる」)。この関数はダイアログ/ステータス欄へ渡す
# **前**にRAW(未翻訳、常に英語)の生の行を取り除く。マーカー文字列("Reason: "、
# 診断ヘッダ行、"[D2P_PATH_SHAPE]")は言語に関わらず常に英語で安定しているため、
# 翻訳後ではなく翻訳前のRAW段階でフィルタする(翻訳後にi18n各言語の見出しへ
# マッチさせる方式だと言語ごとに複製が要る)。取り除いた行は消えるのではなく、
# 呼び出し元(_on_blender_setup_done)がフィルタ前の全文を必ずself._log()へ
# 記録することで診断能力を保つ(問い合わせボタンが添付するlaunch.log経由で
# 引き続きサポートへ届く)。
_BLENDER_SETUP_FAIL_DIAGNOSTIC_HEADER = (
    "Diagnostic info (path structure only, no folder names included):"
)


def strip_blender_setup_fail_diagnostics(raw: str) -> str:
    """[D2P_BLENDER_SETUP_FAIL]案内文(RAW、未翻訳)から、ダイアログに出しては
    いけない行(生例外文の"Reason: ..."行、"Diagnostic info..."ヘッダとそれに
    続く[D2P_PATH_SHAPE]診断ブロック)を除去して返す。それ以外の行(固定の
    案内文・手動セットアップ手順・$TargetDirの実パスなど、ユーザーが実行
    できる手順)はそのまま残す。"""
    if not raw:
        return raw
    out_lines: list[str] = []
    skip_diag_block = False
    for line in raw.split("\n"):
        if skip_diag_block:
            # 診断ブロックは空行までを1ブロックとして丸ごと読み飛ばす
            # (Show-D2PFailureGuidance L.349-351: ヘッダ行の直後に
            # [D2P_PATH_SHAPE]行が2行続き、最後は空行で終わる)。
            if line.strip() == "":
                skip_diag_block = False
            continue
        if line == _BLENDER_SETUP_FAIL_DIAGNOSTIC_HEADER:
            skip_diag_block = True
            continue
        if line.startswith("Reason: "):
            continue
        if "[D2P_PATH_SHAPE]" in line:
            continue
        out_lines.append(line)
    # 除去でできた連続空行を1行へ畳む(見た目のためだけの整形、内容には
    # 影響しない)。
    cleaned: list[str] = []
    for line in out_lines:
        if line == "" and cleaned and cleaned[-1] == "":
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip("\n")


# 「こだわり設定」パネルが開いているときの、パネルより下にある要素の
# 絶対座標(dev#551着手前のWP-A1〜dev#619までの `.place()` 実測値を
# そのまま転記したもの)。MainWindow.layout_content_area()がパネルの開閉
# 状態に応じてここからy座標を差し引いて再配置する。**この辞書の値自体は
# 変更しないこと**——変えると「開いた状態は従来と同じ配置を保つ」という
# 本WPの受入条件に反する(値を変えたければ、まずここではなく元の
# `.place()`呼び出し側で座標を決め直し、この辞書へ転記し直す順序を守る
# こと)。
_FOOTER_OPEN_GEOMETRY: dict[str, dict[str, int]] = {
    "lblPaks": dict(x=12, y=584, width=130),
    "appliedLabel": dict(x=150, y=584, width=920),
    "pakList": dict(x=12, y=608, width=870, height=180),
    "applyButton": dict(x=890, y=608, width=180, height=34),
    "removeButton": dict(x=890, y=648, width=180, height=34),
    "refreshButton": dict(x=890, y=688, width=180, height=28),
    "deleteButton": dict(x=890, y=724, width=180, height=28),
    "reportButton": dict(x=890, y=760, width=180, height=28),
    "autoApplyCheck": dict(x=12, y=794, width=500, height=20),
    # updateLabel/updateNowButtonは更新通知が無い間place_forget()済み。
    # layout_content_area()はwinfo_ismapped()で現在の表示状態を見て、
    # 非表示中は座標を動かさない(表示するときは_show_update_notice()が
    # その時点のdeltaを使って自分で配置する、同メソッド参照)。
    "updateLabel": dict(x=12, y=822, width=1058, height=20),
    "updateNowButton": dict(x=12, y=848, width=130, height=22),
    # dev#551是正(issue #551 2026-08-02 WSB検証コメント): dev#495で追加
    # されたverifiedVersionLabel(#26)がこの辞書に載っていなかったため、
    # こだわり設定が既定(閉)のままだと常にy=878固定=ウィンドウ外(閉時の
    # 高さはCONTENT_HEIGHT-_KODAWARI_PANEL_DELTA)に配置され続け、検証済み
    # Palworldバージョン表示が起動直後の最も一般的な画面で一度も見えない
    # 不具合になっていた(work\wsb_gui_bundle_20260802\RESULT.md参照)。
    # 他のフッター項目と同じ流儀でここへ載せ、layout_content_area()の
    # 一括delta処理に乗せる。
    "verifiedVersionLabel": dict(x=12, y=878, width=1058, height=20),
}


def _load_scaled_preview_image(path: str, max_width: int, max_height: int) -> tk.PhotoImage:
    """dev#599: previewFront/previewSide用のPNGをtk.PhotoImageで読み込み、
    表示域(max_width x max_height)に収まるよう整数間引き(subsample)で
    縮小して返す。Pillow/ImageTk等の追加依存は使わない(同梱ランタイム
    res\\python_embedにPillowが無いため、Tk 8.6ネイティブのPNGデコードのみ
    に依存する設計、C#版のLoadImageNoLock+PictureBoxSizeMode.Zoom相当を
    tkinterの手段で再現したもの)。

    失敗時(ファイル無し・壊れPNG・Tk側のTclError等)は例外をそのまま呼び出し
    元へ伝播させる(フォールバック処理は呼び出し元の責務、_set_preview_widget
    参照)。

    subsampleは整数倍率でしか縮小できない(非整数倍率や拡大はできない)ため、
    「表示域に収まる」ことを保証する最小の整数倍率を切り上げ計算で求める。
    例: 700x1000のPNGを380x360の表示域に収める場合、
    ceil(700/380)=2, ceil(1000/360)=3 → 大きい方の3を採用し233x333になる。
    """
    img = tk.PhotoImage(file=path)
    width, height = img.width(), img.height()
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid image dimensions: {width}x{height}")
    factor = 1
    if max_width > 0 and width > max_width:
        factor = max(factor, -(-width // max_width))  # ceil division
    if max_height > 0 and height > max_height:
        factor = max(factor, -(-height // max_height))  # ceil division
    if factor > 1:
        img = img.subsample(factor, factor)
    return img


class _ToolTip:
    """簡易ツールチップ(DiveToPalworld.csのToolTip.SetToolTip相当の最小実装)。
    tkinterに標準のツールチップ機構が無いための自前実装。i18n.register()の
    setter経由で言語切替時にも文言が更新される。"""

    def __init__(self, widget: tk.Widget):
        self.widget = widget
        self.text = ""
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def set_text(self, text: str) -> None:
        self.text = text

    def _show(self, _event=None) -> None:
        if not self.text or self._tip is not None:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except tk.TclError:
            return
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        try:
            self._tip.wm_geometry(f"+{x}+{y}")
        except tk.TclError:
            pass
        label = tk.Label(
            self._tip, text=self.text, background="#ffffe0",
            relief="solid", borderwidth=1, padx=4, pady=2, justify="left",
        )
        label.pack()

    def _hide(self, _event=None) -> None:
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


class MainWindow:
    """旧MainForm相当。DESIGN.md §1.1の全25要素をplace()で配置する。

    `self.widgets` は各要素をDESIGN.md §1.1の行番号順に名前で引けるようにした
    lookup簿(受入条件③用)。C#の元フィールド名(vrmBox/convertButton等)を
    そのままキーに使い、DESIGN.mdとの対応を追いやすくしてある。
    """

    def __init__(
        self, root: tk.Tk, app_root: str | None = None, dev_sample_sway: bool = False
    ):
        self.root = root
        self.app_root = app_root or _APP_PY_DIR
        self.work_root = self._resolve_work_root()
        self.widgets: dict[str, object] = {}
        self._tooltips: list[_ToolTip] = []
        # dev#19揺れものUIプロトタイプ(2026-08-11、work\rd_19_flight\briefs\
        # uimock2_embedded.md仕様4): main.pyの`--sample`起動フラグ経由。
        # 実データ(VRM/prefab)が読み込まれていない/検出できない状態でも
        # ラボ「揺れもの詳細設定」ダイアログの見た目をUI評価できるよう、
        # 組み込みサンプルチェーンを注入する開発確認専用フラグ(製品には
        # 残さない前提。work\rd_19_uimock2\RESULT.md参照)。
        self._dev_sample_sway = dev_sample_sway

        # ---- WP-A2: 変換系の内部状態 ----
        # DiveToPalworld.cs L.1042-1046「内部互換性のためにフィールドを初期化
        # (UIには表示しない)」相当。WP-A1骨格にも対応する可視ウィジェットが
        # 無いため、pipeline_runner.write_job()の既定値と同じ初期値をここに持つ
        # (将来、以前のjob.jsonからの復元(SetVrm相当)を実装するWPがこの3つの
        # 属性を上書きすればよい設計にしてある)。
        self._shoulder_offset_deg = 0
        self._merge_fingers = False
        self._unlit = False
        self._force_two_sided = True
        # EnsureLicenseConfirmed() L.2533-2545相当のセッション内フラグ
        # (アバターごとのjob.json復元によるリセットはSetVrm側の担当、WP-A2外)
        self._license_confirmed = False
        # dev#611: silentPreview(DiveToPalworld.cs L.472/2556)相当。自動起動時
        # (アバター登録直後の自動プレビュー)はTrue、手押し(previewButton等)
        # はFalse。現時点の_on_pipeline_exit()には完了ダイアログが無い
        # (PR #610が別途追加予定)ため、このフラグは導入・設定のみ行い、
        # まだどこからも参照しない(brief item2の指示どおり)。
        self._silent_preview = False
        self._active_handle: pipeline_runner.ProcessHandle | None = None
        self._pipeline_warnings: list[str] = []
        # dev#1261: ##AVATAR_FATAL##マーカー(例: メッシュ0個)を検出したときの
        # 生コード(例: "no_mesh"。翻訳済み文言ではない——言語切替の再翻訳
        # (_set_status/_last_status_render)に対応するため、翻訳は使用直前に
        # pipeline_runner.translate_avatar_fatal()で都度行う)。run単位で
        # リセットする(_pipeline_warningsと同型、_start_pipeline側で毎回
        # Noneへ戻す)。_on_pipeline_exit()のcode!=0分岐で、汎用の
        # StatusFailedOrCancelled より優先して使う。
        self._pipeline_fatal_cause: str | None = None
        # dev#138: cancelButton経由でユーザーが自ら中止したのか、実際の失敗
        # なのかを_on_pipeline_exit()で区別するためのフラグ。中止確認
        # (ConfirmCancelConvertBody)に既にYes/Noがあるため、失敗時の
        # 「問い合わせを開きますか」を中止のケースまで二重に出さないための
        # ガード(_start_pipeline側で毎回Falseへ戻す)。
        self._user_cancelled_current_run = False
        # dev#288提案2(早期プレビュー反映)相当。実行のたびFalseへ戻す
        # (_start_pipeline側、earlyPreviewLoadedThisRun L.483相当)。
        self._early_preview_loaded_this_run = False
        # dev#599: previewFront/previewSideへ表示中のtk.PhotoImageへの参照を
        # ここに保持する(Tkの罠対策。Label.config(image=...)はTk内部では
        # 弱参照のみ持つため、Python側の変数が無くなるとGCで画像が消える)。
        self._preview_images: dict[str, tk.PhotoImage] = {}

        # pak管理系(WP-A4、DESIGN.md §2.3)の内部状態。
        # _paks_dir_cache: PaksDir()のインスタンスキャッシュ相当(paksDirCache)。
        # _pak_paths: TreeviewのiidからpakフルパスへのlookupPakList.Items[].Tag相当)。
        # _pak_candidates: identify_applied_pak()に渡す(pakパス, アバター名)列
        # (UpdateAppliedStatusがpakList走査から作る材料と同じ)。
        # _applied_status_gen: 世代番号(古い照合結果を捨てるための世代、appliedStatusGen相当)。
        self._paks_dir_cache: str | None = None
        self._pak_paths: dict[str, str] = {}
        self._pak_candidates: list[tuple[str, str]] = []
        self._applied_status_gen = 0
        # dev#897: statusLabelへ最後に設定した文言を再計算するためのレンダラ
        # (i18n.register()の登録簿には載らない、都度動的に選ばれる文言用。
        # _set_status()参照。appliedLabel側は状態(_on_update_applied_status)
        # から再計算する設計だが、statusLabelは呼び出し元ごとに前提状態が
        # バラバラ(直前に適用したアバター名・削除したアバター名等)で単一の
        # 「状態」に還元できないため、直近の描画手順そのものを覚える方式にする)。
        self._last_status_render: Callable[[], str] | None = None

        # dev#618/#619結線: 起動時診断系の内部状態。
        # _remote_known_good_json: dev#89相当。update_check.check_for_update()が
        # versions.jsonから拾った"palworld_known_good"ブロック(JSON文字列)を
        # ここへキャッシュし、compat_check側の判定にも使う(C#のvolatile
        # remoteKnownGoodJsonフィールド相当。取得前/失敗時/オフライン時はNoneの
        # まま=同梱データのみで判定、安全に縮退)。
        self._remote_known_good_json: str | None = None
        # dev#1447: `_check_for_update_once()`のworkerがリモート取得を完了
        # (成功/失敗いずれか確定)した時点でsetされる同期点。判定側worker
        # (`_resolve_palworld_compat_status`)は、警告を出す前にこのEventを
        # 有限時間待つことで、warm-cache済み環境で`manifest_available=True`が
        # 即成立し`_remote_known_good_json`がNoneのまま判定確定してしまう
        # 競合(リモート白リスト追加が起動警告に効かない不具合)を避ける。
        # `_remote_known_good_json`への代入は必ずこのset()より前に完了させる
        # こと(happens-before、詳細は_check_for_update_once参照)。
        self._update_check_done = threading.Event()
        # _pending_update_version: ShowUpdateNotice()のpendingUpdateVersion相当。
        # dev#897でupdateLabelの言語切替時再表示(旧dev#173スコープ外注記)を結線した。
        # _on_language_selected()がこの値を見てupdateLabelを再翻訳する
        # (None=通知が表示されていない=何もしない)。
        self._pending_update_version: str | None = None

        # Blender準備状態(DESIGN.md §2.2、WP-A3)。C#側の blenderSetupRunning/
        # blenderReady フィールド(コンストラクタ近傍で宣言)相当。
        self._blender_setup_running = False
        self._blender_ready = False
        self._blender_queue: "queue.Queue[tuple]" = queue.Queue()
        # dev#640: run_ensure_blender_setup_process()が起動する子プロセスへの
        # 参照(C#版blenderSetupProcフィールド相当)。GUI終了時に黙ってkillする
        # ため、_blender_setup_worker()からdo_ensure_blender_ready()へ渡す。
        self._blender_setup_process_handle = blender_setup.BlenderSetupProcessHandle()
        # dev#1056: Blender初回セットアップ(DL)完了前にprefabがドロップされた
        # 場合の保留先(C#版 pendingBlenderReadyAction フィールド、L.468相当だが
        # py版は現状prefab経路のみ必要なため、Action delegateではなくpathを1件
        # 保持する形に単純化)。_on_prefab_selected()が未確定時にここへ書き、
        # _on_blender_setup_done()がok==Trueになった時点で取り出して自動的に
        # _on_prefab_selected()を呼び直す(C#版DoEnsureBlenderReady() L.2091-2096
        # と同じ「セットアップ失敗時はクリアしない(次回成功時に持ち越す)」契約)。
        self._pending_prefab_drop_path: str | None = None
        # dev#45 ②: warm_cache()(共通データの事前計算)の完了状態を可視化
        # するためのtkinter非依存の状態オブジェクト(warm_startup.py:
        # WarmCacheStatus参照)。_poll_warm_cache_status()がポーリングして
        # statusLabelの「共通データ準備中…」表示/復元を行う。
        # _warm_cache_status_pending_last: 直前ポーリング時のis_pending()を
        # 覚えるエッジ検出用(状態が変化した回だけ_set_status()を呼ぶ)。
        # _status_before_warm_cache: 「準備中」表示に切り替える直前の
        # _last_status_renderを退避しておき、完了時に復元するため。
        self._warm_cache_status = warm_startup.WarmCacheStatus()
        self._warm_cache_status_pending_last = False
        self._status_before_warm_cache: Callable[[], str] | None = None
        # dev#639: UpdateButtonStates()のbusy判定(running)相当。
        # _set_running_ui_state()が更新し、_update_button_states()が参照する。
        self._is_pipeline_running = False
        # dev#1572(ラボ窓ブロック、2026-08-18オーナー最終裁定): ラボ系
        # サブウィンドウ(ラボ窓本体+機能別設定ダイアログ)が開いている個数
        # のカウンタ。ラボの各設定パネルはOK押下時のみ永続ストア/
        # widgets["dropBonesBox"]等へ反映される設計のため、開いたまま
        # フル変換を走らせると画面上の未保存の変更が反映されない事故が
        # 起きる(実測: sway_chain_overridesキー不在のままjob.jsonが
        # 書かれた)。0より大きい間は`_refresh_convert_button_freshness()`が
        # 他の全ゲート判定より優先してconvertButtonを強制disabledにする
        # (`_on_lab_subwindow_opened()`/`_on_lab_subwindow_closed()`、
        # 呼び出し元は`ui\\lab_window.py`)。
        self._lab_subwindow_open_count = 0
        # dev#602追補: Unity輸出フェーズの無音解消(ハートビート)用の状態。
        # _active_phase は _set_running_ui_state() が更新し、_poll_active_handle()
        # がUnity輸出フェーズかどうかの判定に使う。開始/最終出力時刻は
        # time.monotonic()(壁時計変更の影響を受けない)。
        self._active_phase = pipeline_runner.PHASE_PIPELINE
        self._unity_export_started_at: Optional[float] = None
        self._unity_export_last_output_at: Optional[float] = None
        # dev#702 第3弾WP-3: _on_prefab_selected()で設定、_on_unity_export_exit()の
        # sig保存・GUI表示維持(_set_vrm_path)に使うprefab入力パス。
        self._pending_prefab_export_path: Optional[str] = None

        # 初期言語決定(DetermineInitialLang L.817-831相当。dev#532方針A
        # WP-A11/dev#549でOSロケール自動判定を結線。設定ファイルがあれば
        # 最優先、無ければ i18n.detect_lang_from_culture() でOSのUI言語から
        # 判定する。旧WP-A1骨格の「無ければja固定」簡略実装は、日本語環境
        # 以外のユーザーが初回起動時に常にja表示になる回帰リスクがあった
        # ため置き換えた〈WP-A7調査(dev#549)で発見、報告済みの解消〉)。
        code = settings.load_language_code(self.app_root)
        if code and code in i18n.FILE_CODE_TO_LANG:
            lang = i18n.FILE_CODE_TO_LANG[code]
        else:
            lang = i18n.detect_lang_from_culture(self._current_os_culture_name())
        i18n.clear_registry()
        i18n.set_language(lang)

        root.title(f"Uchinoko for Palworld {TOOL_VERSION} - {i18n.S('TitleSubtitle')}")
        # dev#662: 固定 "1100x930"(現在はdev#551でCONTENT_HEIGHTが900へ変更
        # されたため"1100x900")を作業領域(タスクバー除く)クランプへ置換。
        # 通常環境(作業領域がcontentサイズ以上)では従来と同じ寸法・
        # needs_scroll=Falseになる(work_area取得不能時も安全側で同じ結果、
        # workarea.compute_clamp()docstring参照)。_build_widgets()がneeds_scroll
        # を見てスクロール可能なコンテナを組むかどうかを決める。ここで求まる
        # self._window_height は「こだわり設定パネルが開いている」ことを前提
        # にした値(dev#551): _build_widgets()直後のlayout_content_area()呼び
        # 出しが、既定状態(閉)ならここからさらにパネル1個ぶん縮めた高さへ
        # root.geometry()を上書きする。
        clamp = workarea.compute_clamp(workarea.get_work_area())
        self._window_width = clamp.window_width
        self._window_height = clamp.window_height
        self._needs_scroll = clamp.needs_scroll
        root.geometry(f"{self._window_width}x{self._window_height}")
        self._set_window_icon()
        # dev#622: FormClosing(DiveToPalworld.cs L.1292-1305)相当。×ボタンでの
        # 終了をtkinterのWM_DELETE_WINDOWで捕捉する(旧実装はメインウィンドウに
        # 未登録で無警告のまま閉じられていた。子ダイアログ側=support_dialog.pyの
        # 登録は元々存在し、そちらは無関係)。
        self.root.protocol("WM_DELETE_WINDOW", self._on_form_closing)

        # 問い合わせダイアログ(#21)の可変状態(SupportDialogState相当)。
        # アプリ実行中はダイアログを閉じても引き継がれる必要があるため、
        # MainWindowが1個だけ保持する(support_dialog.pyのdocstring参照)。
        self._support_state = support_dialog.SupportDialogState()

        self._build_widgets()
        # dev#1186: ラボ機能の初期状態(既定=全て無効)を警告表示へ反映する。
        # 起動直後は必ず既定値なので実質no-op(非表示のまま)だが、
        # labWarningLabelのジオメトリ管理を_refresh_lab_warning()一本に
        # 揃えるため明示的に呼んでおく。
        self._refresh_lab_warning()
        # dev#551: こだわり設定パネル(既定=閉、self._kodawari_open=False)の
        # 分だけウィンドウ・フッター行を詰めた状態を起動直後から反映する
        # (呼ばないと、_build_widgets()が置いたばかりの「開いた状態の座標」
        # ×「開いた状態のウィンドウ高」のまま=旧不具合そのものの見た目で
        # 初回描画されてしまう)。
        self.layout_content_area()
        self._update_window_title()
        self._drop_target: dnd.DropTarget | None = None
        self._setup_drag_and_drop()

        # dev#495: 検証済みPalworldバージョンの初期表示(同梱jsonのみ、配信
        # versions.jsonはまだ未取得なのでself._remote_known_good_json=Noneの
        # ままマージされる)。_check_for_update_once()が配信データを取得した
        # 後に同じメソッドで再反映する(下記参照)。
        self._refresh_verified_version_label()

        # dev#617/#639: UpdateButtonStates()相当を起動直後に1回反映しておく
        # (_build_widgets()はconvertButton等をstate指定なし=既定"normal"で
        # 生成するため、呼ばないとVRM未選択・Blender未準備のままボタンが
        # 押せてしまう。C#版は起動時のUpdateButtonStates()呼び出し経路で
        # hasVrm=false/blenderReady=falseのため最初からEnabled=falseになって
        # いる)。_set_running_ui_state(False)経由で、convertButton
        # (_refresh_convert_button_freshness、hasVrm/fresh/workRootFailed/
        # blenderReady判定)とmatsButton/previewButton(_update_button_states、
        # busy/blenderReady/hasVrm/workRootFailed判定)の両方が一度に初期化
        # される(#637マージ後の統合、PR #647本文の指示どおり)。
        self._set_running_ui_state(False)

        # RefreshPakList()相当(DiveToPalworld.cs L.899, L.1260)。起動直後に
        # 一覧+適用中判定を populate する(§1.2 #26/#18、WP-A4の結線対象)。
        self._on_refresh_pak_list()

        # Shownデリゲート(DiveToPalworld.cs L.1258-1271)のうち「最後に開いていた
        # VRMを復帰(設定・プレビューも一緒に戻る)」部分(dev#623)。RefreshPakList
        # の直後という順序もC#版どおり。
        self._restore_last_vrm_on_startup()

        # dev#621: workRootFailed(主系・フォールバック先とも書き込み不可)の
        # 検知・ログ・エラーダイアログ・ボタン無効化。ログ欄(self.log_box)と
        # 変換系ボタンが両方とも_build_widgets()完了後でないと存在しないため
        # ここで呼ぶ(CheckPathHealthOnStartupがShownイベント=ウィジェット
        # 生成済みの時点で呼ばれるのと同じ順序関係。C#版もRestoreLastVrm→
        # UpdateButtonStates→...→CheckPathHealthOnStartupの順でShown内に
        # 並んでおり、VRM復帰が先という順序を保つ)。
        self._check_work_root_failed_on_startup()

        # dev#532 D1: 起動時セルフチェック(path_health.py、§1.2 #31相当+
        # 「環境隔離4層」の④)。同期・軽量(ディスクI/O無しのパス比較のみ)
        # なのでUIスレッドで直接呼んでよい。
        self._run_startup_self_check()

        # dev#532 D1: 他MOD検出(CheckOtherModsOnce()相当、§1.2 #30)。
        # ディスクI/O(Paksフォルダ列挙)を伴うため専用バックグラウンドスレッドへ。
        self._check_other_mods_once()

        # dev#620: パス健全性警告(CheckPathHealthOnStartup()相当、§1.2 #31)。
        # 文字列比較のみ(ディスクI/O無し)なのでUIスレッドで直接呼んでよい
        # (_run_startup_self_checkと同じ扱い)。
        self._check_path_health_on_startup()

        # dev#618: Palworldバージョン互換チェック(CheckPalworldVersionOnce()
        # 相当、§1.2 #29)。ディスクI/O(acf読み取り・pakサイズ取得・
        # warm-cache完了待ちの最大5分ポーリング)を伴うため専用バックグラウンド
        # スレッドへ(元実装と同じ設計)。
        self._check_palworld_version_once()

        # dev#619: 起動時更新通知(CheckForUpdateOnStartup()相当、§1.2 #23)。
        # ネットワークI/O(versions.jsonのGET、タイムアウト4秒)を伴うため
        # 専用バックグラウンドスレッドへ(元実装と同じくThreadPool相当)。
        self._check_for_update_once()

        # Shownイベント相当(DESIGN.md §1.2 #28)のうちBlender準備のみ、本WPで
        # 起動直後に非同期発火する(#26/27/29-32の他の起動時処理はA4/A6等の
        # 担当、DESIGN.md §5.2参照)。tkinterのafter()でポーリングを開始してから
        # ワーカースレッドを起こす(DESIGN.md §4.3の定番パターン)。
        self.root.after(100, self._poll_blender_queue)
        # dev#45 ②: warm_cache()状態の可視化ポーリング開始(_poll_blender_queue
        # と同じ「afterで開始してからワーカーを起こす」順序。実際にwarm_cache
        # サブプロセスが起動するのは_ensure_blender_ready_on_startup() ->
        # blenderReady確定 -> _warm_startup_after_blender_ready()の先、非同期)。
        self.root.after(100, self._poll_warm_cache_status)
        self._ensure_blender_ready_on_startup()

    # -- 内部ヘルパー -----------------------------------------------------

    def _set_window_icon(self) -> None:
        """dev#594: py版GUIのウィンドウ/タスクバーアイコンがPython既定の
        ままだった件の解消。旧C#版(app\\)がbuild_app.ps1でexeへ埋め込んで
        いた製品アイコン(ぱん納品、リポジトリ直下 ico\\app.ico、
        git 5d28cda「icon: 新アイコンへ全面置き換え」)と同じ資産を、
        build.py側のres\\へのコピー処理を新設せず、既存の`_copy_app_sources()`
        (app_py\\ツリー全体をres\\app\\へそのままコピーする経路)に相乗りさせる
        形で app_py\\assets\\app.ico として同梱する。このファイル冒頭の
        `_APP_PY_DIR`(dev実行ではapp_py\\、配布実行ではres\\app\\を指す、
        既に両対応済みの定数)からの相対パスで解決するため、開発実行/配布
        実行のどちらでも同じコードで見つかる。
        `root.iconbitmap(default=...)` の `default=` はこのrootから生成される
        子Toplevel(問い合わせダイアログ等)にもアイコンを継承させるための
        指定。失敗(環境依存のTk実装差異等)しても例外を握って続行し、
        アイコンのためにGUI起動自体を止めない(仕様#3)。"""
        icon_path = os.path.join(_APP_PY_DIR, "assets", "app.ico")
        try:
            self.root.iconbitmap(default=icon_path)
        except Exception:  # noqa: BLE001 -- アイコン設定の失敗でGUIを殺さない
            pass

    def _resolve_work_root(self) -> str:
        """WorkRootResolveLogic.Resolve(DiveToPalworld.cs L.6446-6477)相当。
        appRoot\\work への書き込みを試し、失敗すれば%LOCALAPPDATA%\\Uchinoko\\work
        へフォールバックする(DESIGN.md §2.8「外部依存パスの原則」の三点セット
        のうち①②)。

        dev#621: 両方とも書き込めない(稀)場合を明示的に検知できるよう、
        C#版のworkRootFailed/workRootUsedFallback/workRootPrimaryPath/
        workRootFallbackPath/workRootPrimaryError/workRootFallbackError
        フィールド(L.691-696)相当をインスタンス属性として残す(呼び出し元は
        _check_work_root_failed_on_startup()。③探索した場所と判定を全部ログへ、
        の材料もここに揃う)。両方失敗した場合もC#と同じくフォールバック先の
        パス文字列をwork_rootとして返す(下流コードが例外で落ちないようにする
        ためだけの値で、実際には書き込めない。押しても失敗するだけの状態は
        変換系ボタンの無効化で防ぐ)。"""
        primary = os.path.join(self.app_root, "work")
        fallback = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Uchinoko", "work"
        )
        self._work_root_primary_path = primary
        self._work_root_fallback_path = fallback
        self._work_root_used_fallback = False
        self._work_root_failed = False

        def probe(path: str) -> str | None:
            """書き込み可能ならNone、不可なら理由文字列を返す
            (ProbeWorkRootWritable相当)。"""
            try:
                os.makedirs(path, exist_ok=True)
                probe_file = os.path.join(path, ".d2p_write_probe")
                with open(probe_file, "w", encoding="utf-8") as f:
                    f.write("")
                os.remove(probe_file)
                return None
            except OSError as ex:
                return str(ex)

        self._work_root_primary_error = probe(primary)
        if self._work_root_primary_error is None:
            return primary

        self._work_root_fallback_error = probe(fallback)
        if self._work_root_fallback_error is None:
            self._work_root_used_fallback = True
            return fallback

        self._work_root_failed = True
        return fallback

    def _work_root_resolution_line(self) -> str:
        """WorkRootResolutionLine() (DiveToPalworld.cs L.3255-3266) 相当。
        フォールバックが起きた/起きなかったに関わらず必ず1行を返す
        (「成功時にも構造が残らないと診断できない」CLAUDE.md方針)。"""
        if not self._work_root_used_fallback and not self._work_root_failed:
            return f"work_root: {self.work_root} (install location, writable)"
        if self._work_root_used_fallback:
            return (
                f"work_root: {self.work_root} (fallback to a user-writable location; "
                f'install location "{self._work_root_primary_path}" is not writable: '
                f"{self._work_root_primary_error})"
            )
        return (
            f'work_root: {self.work_root} [!] neither the install location ("'
            f'{self._work_root_primary_path}": {self._work_root_primary_error}) nor '
            f'the fallback ("{self._work_root_fallback_path}": '
            f"{self._work_root_fallback_error}) is writable"
        )

    def _check_work_root_failed_on_startup(self) -> None:
        """CheckPathHealthOnStartup()のworkRootFailed部分(DiveToPalworld.cs
        L.3277-3287)相当。汎用パス健全性警告(too-long/UNC/OneDrive、
        表#11・別issue・死んだコードのまま=本WPのスコープ外)とは別枠。

        主系・フォールバック先とも書き込み不可の場合のみ、①ログ記録
        ②エラーダイアログ ③変換系ボタン(convert/mats/preview)の全面無効化
        を行う(UpdateButtonStates L.2486-2491の`!workRootFailed`条件相当。
        py版は継続的なUpdateButtonStatesループを持たないため、ここで一度
        disabledにし、_set_running_ui_state()側でも再度normalへ戻さない
        ガードを入れてある)。"""
        self._log(self._work_root_resolution_line())
        if not self._work_root_failed:
            return
        # dev896-i18n-log-allow: 直後に同文言でmessagebox.showerrorを出すため、
        # ログ欄の表示もそのダイアログと同じUI言語に一致させる意図的設計
        # (dev#596の受入条件「警告・案内文言」に該当。診断専用ログとは別枠)。
        self._log("[!] " + i18n.S("TitleWorkRootUnwritable"))
        for key in ("convertButton", "matsButton", "previewButton"):
            self.widgets[key].config(state="disabled")
        messagebox.showerror(
            i18n.S("TitleWorkRootUnwritable"),
            i18n.F(
                "MsgWorkRootUnwritableFormat",
                self._work_root_primary_path,
                self._work_root_fallback_path,
            ),
        )

    def _current_os_culture_name(self) -> str | None:
        """CultureInfo.CurrentUICulture.Name相当(L.830で渡される実際の値)。
        i18n.detect_lang_from_culture()は文字列入力のみに依存する純関数なので、
        「実際のOS言語をどう取得するか」という環境依存部分はここに切り出す
        (DetermineInitialLangがMainForm側でCultureInfoへ直接アクセスしていた
        のと同じ役割分担、DESIGN.md §4.4参照)。取得できなければNone
        (detect_lang_from_cultureはNone/空文字をenへ倒す設計)。"""
        try:
            import ctypes

            windll = getattr(ctypes, "windll", None)
            if windll is not None:
                lcid = windll.kernel32.GetUserDefaultUILanguage()
                import locale as _locale

                name = _locale.windows_locale.get(lcid)
                if name:
                    return name.replace("_", "-")
        except Exception:
            pass
        try:
            import locale as _locale

            loc = _locale.getdefaultlocale()[0]
            if loc:
                return loc.replace("_", "-")
        except Exception:
            pass
        return None

    def _restore_last_vrm_on_startup(self) -> None:
        """Shownデリゲート(DiveToPalworld.cs L.1258-1271)のうち以下の部分相当
        (dev#623):
        ```
        string f = LastVrmFile();
        if (File.Exists(f)) {
            string last = File.ReadAllText(f, Encoding.UTF8).Trim();
            if (File.Exists(last)) SetVrm(last);
        }
        ```
        settings_lastvrm.txtに記録があり、かつそのファイルがまだ実在する時
        だけ、通常の_set_vrm_path経路(browse/D&Dと同じ入口)へそのまま流す
        (job.json復元・自動プレビュー判定も同じ経路で効く。C#版もSetVrm(last)
        を呼ぶだけで別処理を持たない、L.1268)。ファイルが既に無ければ何も
        しない(File.Exists(last)相当)。例外はtry/catch(Exception) L.1262/1271
        と同じくGUI起動自体を止めずに握る。"""
        try:
            last_vrm = settings.load_last_vrm(self.app_root)
            if last_vrm and os.path.isfile(last_vrm):
                self._set_vrm_path(last_vrm)
        except Exception as ex:  # noqa: BLE001 -- L.1262/1271相当、GUI起動を止めない
            self._log(f"[startup] last vrm restore failed: {ex}")

    def _run_startup_self_check(self) -> None:
        """dev#532 D1: 起動時セルフチェック(path_health.check_runtime_environment
        相当)の結線。判定対象は「実行中のPythonインタプリタが app_root 配下の
        同梱embeddable Pythonか」。

        パッケージ版(`Uchinoko.bat`経由起動、app_root配下に`python_embed\\`が
        存在する)でのみ検査を実行する。開発ソースチェックアウトでの
        `python app_py\\main.py` 直接実行(受入条件①)では`python_embed\\`が
        存在しないため何もしない(=判定対象外。path_health.pyのdocstring
        「情報が渡ってこないケースは黙って動く安全側」の精神を、パッケージ版
        かどうかの判定自体にも適用した合理的解釈。理由: app_root=リポジトリ
        直下となる開発実行では、システムPythonがapp_root配下に無いのは常態で
        あり、これを毎回「エラー」として警告するのは誤検知になる)。"""
        if not os.path.isdir(os.path.join(self.app_root, "python_embed")):
            return
        status = path_health.check_runtime_environment(sys.executable, self.app_root)
        message = path_health.runtime_environment_message(status)
        if message:
            self._log(f"[self-check] {message} (sys.executable={sys.executable})")
            messagebox.showwarning("Uchinoko for Palworld", message)

    def _check_other_mods_once(self) -> None:
        """CheckOtherModsOnce() (DiveToPalworld.cs L.3202-3224) 相当の結線。
        dev#103裁定: 他MODを検出しても変換自体はブロックしない、警告のみ。
        Paksフォルダの列挙(ディスクI/O)を伴うため専用バックグラウンドスレッドで
        実行し、起動直後のUIスレッドを固めない(元実装と同じ設計)。"""

        def worker() -> None:
            try:
                paks_dir = pak_manager.paks_dir_quiet(self.app_root, cache=self._paks_dir_cache)
                n = pak_manager.count_other_paks(paks_dir)
            except Exception:  # noqa: BLE001 -- 診断用の副処理でメインを巻き込まない
                return
            if n is None or n == 0:
                return

            def show() -> None:
                self._log("[other-mods] " + pak_manager.summarize_other_paks(n))
                messagebox.showwarning(
                    i18n.S("TitleOtherModsDetected"),
                    i18n.F("MsgOtherModsDetectedFormat", n),
                )

            self.root.after(0, show)

        threading.Thread(target=worker, daemon=True, name="OtherModsCheck").start()

    # -- dev#620: パス健全性警告 -------------------------------------------

    def _check_path_health_on_startup(self) -> None:
        """CheckPathHealthOnStartup() (DiveToPalworld.cs L.3268-3304) 相当の
        結線。path_health.build_path_facts/path_health_problem/path_health_line
        (dev#134ロジック、単体テスト完備・importゼロだったdev#620)をinstall
        (app_root)/work(work_root)の2系統について評価し、AppendLogログ+条件付き
        警告ダイアログ(Cause/Actionの箇条書き)を出す。

        workRootFailed(主系・フォールバック先ともに書き込み不可、C# L.3281-3287)
        とWorkRootResolutionLine(C# L.3255-3266)はdev#614記号F(別issue)の対象
        であり、本メソッドでは扱わない(dev#620 issue本文どおりの合理的解釈)。
        文字列比較のみでディスクI/Oを伴わないため、_run_startup_self_checkと
        同じくUIスレッドで直接呼んでよい。"""
        onedrive = os.environ.get("OneDrive")
        install = path_health.build_path_facts("install", self.app_root, onedrive)
        work = path_health.build_path_facts("work", self.work_root, onedrive)
        self._log(path_health.path_health_line(install))
        self._log(path_health.path_health_line(work))

        if not path_health.path_health_problem(install) and not path_health.path_health_problem(work):
            return

        bullets: list[str] = []
        if path_health.path_health_has_too_long(install) or path_health.path_health_has_too_long(work):
            bullets.append("- " + i18n.S("CausePathTooLong") + " / " + i18n.S("ActionPathTooLong"))
        if install.unc or work.unc:
            bullets.append("- " + i18n.S("CausePathUnc") + " / " + i18n.S("ActionPathUnc"))
        if install.under_onedrive or work.under_onedrive:
            bullets.append("- " + i18n.S("CausePathOneDrive") + " / " + i18n.S("ActionPathOneDrive"))

        detail = path_health.path_health_line(install) + "\n" + path_health.path_health_line(work)
        # dev896-i18n-log-allow: 直後に同文言でmessagebox.showwarningを出すため、
        # ログ欄の表示もそのダイアログと同じUI言語に一致させる意図的設計
        # (dev#596の受入条件「警告・案内文言」に該当。診断専用ログとは別枠)。
        self._log("[!] " + i18n.S("TitlePathHealthWarning") + ": " + " / ".join(bullets))
        messagebox.showwarning(
            i18n.S("TitlePathHealthWarning"),
            i18n.F("MsgPathHealthRiskFormat", "\n".join(bullets), detail),
        )

    # -- dev#618: Palworldバージョン互換チェック ---------------------------

    def _known_good_bundled_path(self) -> str:
        """KnownGoodBundledPath() (DiveToPalworld.cs L.3380-3383) 相当。"""
        return os.path.join(self.app_root, "pipeline", "py", "known_good_palworld.json")

    def _load_known_good_palworld(self) -> compat_check.KnownGoodPalworld:
        """LoadKnownGood() (DiveToPalworld.cs L.3396-3403) 相当。同梱データが
        読めなくても(パッケージング事故)例外を投げず空リストのまま返す
        (元実装のtry/catchと同じfail-safe方針)。"""
        bundled = ""
        try:
            with open(self._known_good_bundled_path(), "r", encoding="utf-8") as f:
                bundled = f.read()
        except OSError:
            bundled = ""
        return compat_check.merge_known_good(bundled, self._remote_known_good_json)

    @staticmethod
    def _verified_version_display_text(known: compat_check.KnownGoodPalworld) -> str:
        """dev#495: verifiedVersionLabel用の表示文字列を組み立てる。

        known.versions が空(同梱json読み込み失敗かつ配信versions.jsonも
        未取得/取得失敗)の場合は、推測で「対応済み」等と書かず
        LabelVerifiedPalworldVersionUnknown(「不明」相当)を返す
        (CLAUDE.md「数値を寄せて合わせない」「実装したと効いているは別」の
        延長で、無い情報を有ると偽らない)。空でなければ
        compat_check.supported_labels_joined()(バージョン番号ラベルのみの
        重複除去済みカンマ区切り、build_idは含めない——build_id込みの
        format_supported()は版不一致警告ダイアログ側の文言でしか使わない)を
        埋め込む。配信versions.jsonのpalworld_known_goodでknown_versionsが
        増減すれば、この関数の戻り値もそれに追従する(ハードコード無し)。"""
        if not known.versions:
            return i18n.S("LabelVerifiedPalworldVersionUnknown")
        return i18n.F(
            "LabelVerifiedPalworldVersionFormat",
            compat_check.supported_labels_joined(known),
        )

    def _refresh_verified_version_label(self) -> None:
        """dev#495: verifiedVersionLabelのテキストを最新のknown_good内容
        (同梱json+その時点でキャッシュ済みの配信データ)で更新する。呼び出し元は
        2箇所: ①__init__の_build_widgets()直後(初期表示、同梱データのみで
        埋まる) ②_check_for_update_once()のworkerが配信versions.jsonの
        palworld_known_goodブロックを取得しself._remote_known_good_jsonへ
        キャッシュした直後(UIスレッドへself.root.after(0, ...)経由、表示が
        配信データの増分に追従する)。"""
        known = self._load_known_good_palworld()
        self.widgets["verifiedVersionLabel"].config(
            text=self._verified_version_display_text(known)
        )

    @staticmethod
    def _read_steam_build_id(paks_dir: str) -> Optional[str]:
        """ReadSteamBuildId() (DiveToPalworld.cs L.3344-3372) 相当。
        <...>\\steamapps\\common\\Palworld\\Pal\\Content\\Paks から5階層親へ
        上がって steamapps\\appmanifest_1623730.acf を読み、"buildid"の値
        (数字のみ)を返す。取得できなければNone(判定不能=黙って動く)。"""
        try:
            steamapps_dir = paks_dir
            for _ in range(5):  # Content, Pal, Palworld, common, steamapps
                steamapps_dir = os.path.dirname(steamapps_dir)
            acf = os.path.join(steamapps_dir, "appmanifest_1623730.acf")
            if not os.path.isfile(acf):
                return None
            with open(acf, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    m = re.search(r'"buildid"\s*"(\d+)"', line, re.IGNORECASE)
                    if m:
                        return m.group(1)
        except OSError:
            pass
        return None

    def _detect_palworld_version(self) -> compat_check.PalworldDetection:
        """DetectPalworldVersion() (DiveToPalworld.cs L.3405-3419) 相当。
        Paksフォルダが見つからなければdetected=Falseのまま返す(判定不能=
        黙って動く、元実装のコメントどおり)。"""
        det = compat_check.PalworldDetection()
        paks_dir = pak_manager.paks_dir_quiet(self.app_root, cache=self._paks_dir_cache)
        if paks_dir is None:
            return det
        det.detected = True
        det.build_id = self._read_steam_build_id(paks_dir)
        try:
            # dev#229続報: Xbox App版(Pal-WinGDK.pak)でも実在するファイルの
            # サイズを拾えるよう、単一名決め打ちから候補解決へ変更。既知の
            # 互換表(known_good_palworld.json)自体はSteam版buildidを前提と
            # した設計のまま(build_idがNoneならこの先の照合は元々スキップされる、
            # compat_check.py側の既定挙動に委ねる)。
            pak_filename = pak_manager.resolve_pak_filename(paks_dir)
            if pak_filename is not None:
                pak = os.path.join(paks_dir, pak_filename)
                det.pak_size = os.path.getsize(pak)
        except OSError:
            pass
        return det

    def _palworld_manifest_breadcrumb_path(self) -> str:
        """PalworldManifestBreadcrumbPath() (DiveToPalworld.cs L.3391-3394)
        相当。convert_noue.py _warm_job()のjob_dir固定名("_warm_dummy")と
        extract_vanilla.pyのMANIFEST_NAME("vanilla_manifest.json")に合わせた
        固定パス。"""
        return os.path.join(self.work_root, "_warm_dummy", "vanilla", "vanilla_manifest.json")

    def _read_manifest_combined_hash(self) -> Optional[str]:
        """ReadManifestCombinedHash() (DiveToPalworld.cs L.3421-3430) 相当。"""
        try:
            with open(self._palworld_manifest_breadcrumb_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            value = data.get("combined_hash") if isinstance(data, dict) else None
            return str(value) if value else None
        except (OSError, ValueError):
            return None

    def _evaluate_palworld_compat_now(self) -> tuple[compat_check.PalworldCompatStatus, compat_check.KnownGoodPalworld]:
        """EvaluateCompatNow() (DiveToPalworld.cs L.3435-3441) 相当。診断ログ
        (未結線・別途)とCheckPalworldVersionOnceの両方が使う共通経路
        (両者の判定基準を一致させるため、元実装のコメントどおり)。

        dev#1441: TOOL_VERSIONをcompat_check.evaluate()のcurrent_tool_version
        へ渡す。これにより配信/同梱のknown_versions_conditional(min_tool_version
        条件付きエントリ)が実際に判定へ効く(渡さなければcompat_check側の
        fail-safeで常に「未達」扱いになるだけの未配線コードになってしまう)。"""
        known = self._load_known_good_palworld()
        det = self._detect_palworld_version()
        manifest_hash = self._read_manifest_combined_hash()
        return compat_check.evaluate(known, det, manifest_hash, TOOL_VERSION), known

    def _resolve_palworld_compat_status(
        self,
        sleep_fn=time.sleep,
        remote_wait_event: "threading.Event | None" = None,
        remote_wait_timeout_s: float = 8.0,
    ) -> "tuple[compat_check.PalworldCompatStatus, compat_check.KnownGoodPalworld] | None":
        """CheckPalworldVersionOnce() (DiveToPalworld.cs L.3456-3497) の判定
        部分のみを切り出したもの(スレッド起動・警告表示はこのメソッドの外側、
        _check_palworld_version_once側の担当)。戻り値がNoneなら初回の判定
        自体に失敗した(=確認に失敗しても本体の動作は変えない、元実装の
        `catch (Exception) { return; }`と同じ)。

        dev#1447: 初回評価がshould_warn=Trueだった場合、`remote_wait_event`
        (_check_for_update_once側のリモート取得完了通知、既定Noneなら従来
        どおり待たない)がまだsetされていなければ、`remote_wait_timeout_s`
        (既定8秒。update_check側のGETタイムアウト4秒+余裕)を上限に待って
        から再評価する。これは「配信versions.jsonのpalworld_known_good取得が
        判定に間に合わず、リモート白リストに追加した指紋が起動時警告に一度も
        反映されない」競合(dev#1447)を塞ぐためで、should_warn=Falseの
        ケース(同梱一致)ではこのブロックへ入らない=追加の待ちは発生しない。

        dev#91: 版番号が既知と不一致でも、抽出物マニフェスト
        (vanilla_manifest.json)が既知良好と一致すれば警告しない。manifestは
        起動直後に自動で走るwarm-cache(_ensure_blender_ready_on_startup経由の
        warm_startup.py)が完了しないと手に入らないため、manifest_available で
        なければ最大5分(3秒間隔)ポーリングしてから諦める(元実装と同じ
        タイムアウト値)。`sleep_fn`はテスト時に実待機を避けるための注入点
        (既定はtime.sleep)。"""
        try:
            st, known = self._evaluate_palworld_compat_now()
        except Exception:  # noqa: BLE001 -- 確認に失敗しても本体の動作は変えない
            return None
        if not st.detected or not st.should_warn:
            return st, known

        if remote_wait_event is not None and not remote_wait_event.is_set():
            remote_wait_event.wait(remote_wait_timeout_s)
            try:
                st, known = self._evaluate_palworld_compat_now()
            except Exception:  # noqa: BLE001 -- 確認に失敗しても本体の動作は変えない
                return None
            if not st.should_warn:
                return st, known

        if not st.manifest_available:
            poll_interval_s = 3.0
            timeout_s = 5 * 60.0
            waited = 0.0
            while waited < timeout_s:
                sleep_fn(poll_interval_s)
                waited += poll_interval_s
                try:
                    st, known = self._evaluate_palworld_compat_now()
                except Exception:  # noqa: BLE001
                    break
                if not st.should_warn or st.manifest_available:
                    break
        return st, known

    def _check_palworld_version_once(self) -> None:
        """CheckPalworldVersionOnce() (DiveToPalworld.cs L.3456-3497) 相当の
        結線。acfの読み取りや大きなpakへのアクセス、最大5分のポーリング待ちを
        伴うため専用バックグラウンドスレッドで実行する(元実装と同じ設計)。

        dev#1658: オーナー裁定により、未知build検出時の起動時警告ダイアログ
        (MsgPalworldVersionMismatchFormat/MsgPalworldVersionUpdateHintFormat/
        TitlePalworldVersionCheckの表示、dev#1441のヒント表示込み)は廃止した。
        要件は「普通のユーザーにまったく気にならない」の一点であり、ダイアログ・
        ポップアップの類は一切出さない。判定結果は診断用ログにのみ記録する
        (常設ラベルLabelVerifiedPalworldVersionFormat+ツールチップが今後の
        唯一の開示経路になる、issue本文どおり)。compat_check.pyの判定ロジック
        自体・known_goodの取得/マージは変更していない(ラベルの餌として続投)。"""

        def worker() -> None:
            # dev#1447: リモート取得完了(成功/失敗いずれか確定)を有限時間
            # 待ってから再評価するゲート(_resolve_palworld_compat_status
            # 側の実装参照)を有効にするため、_check_for_update_once側の
            # 完了通知Eventを渡す。ダイアログ表示は廃止したが、この判定
            # ロジック自体は診断ログ用途(_resolve_palworld_compat_statusの
            # docstring参照)に生かすため据え置く。
            result = self._resolve_palworld_compat_status(
                remote_wait_event=self._update_check_done
            )
            if result is None:
                return
            st, known = result
            if not st.should_warn:
                return

            log_line = (
                "Warning: the detected Palworld version differs from the "
                "verified version (" + compat_check.format_detected(st)
                + ", supported: " + compat_check.format_supported(known)
                + ") — you can continue"
            )
            if st.update_hint_min_tool_version:
                log_line += " [update hint: min_tool_version " + st.update_hint_min_tool_version + "]"
            self.root.after(0, lambda: self._log(log_line))

        threading.Thread(target=worker, daemon=True, name="PalworldCompatCheck").start()

    # -- dev#619: 起動時更新通知 --------------------------------------------

    def _check_for_update_once(self) -> None:
        """CheckForUpdateOnStartup() (DiveToPalworld.cs L.3505-3546) 相当の
        結線。update_check.check_for_update()(HTTP GET含む純ロジック分離済み、
        聖域: 取得失敗はいかなるエラー表示・例外にもならないこと)を専用
        バックグラウンドスレッドで呼ぶ。dev#89: 取得できた"palworld_known_good"
        ブロックはlatestの有無に関わらずキャッシュする(compat_check側が次回の
        判定で使う)。

        dev#1447: `self._remote_known_good_json`への代入を完了してから
        `self._update_check_done.set()`する(happens-before)。取得失敗
        (例外・タイムアウト等)でも必ずset()する——`_resolve_palworld_compat_status`
        側の待ちが永遠にブロックしないようにするための保険であり、聖域
        (取得失敗はいかなるエラー表示・例外にもならないこと)は変えない。"""

        def worker() -> None:
            result = None
            try:
                result = update_check.check_for_update(TOOL_VERSION)
                if result.remote_known_good_json:
                    self._remote_known_good_json = result.remote_known_good_json
            except Exception:  # noqa: BLE001 -- 聖域: 取得失敗は無音で諦める
                pass
            finally:
                self._update_check_done.set()
            if result is None:
                return
            if result.remote_known_good_json:
                # dev#495: 配信versions.jsonのpalworld_known_goodブロックが
                # 取れた直後にverifiedVersionLabelを再反映する(latestの有無
                # (=update通知の要否)とは独立。result.remote_known_good_jsonは
                # has_update=Falseでも非Noneになりうるため、この分岐はreturn
                # より前に置く)。
                self.root.after(0, self._refresh_verified_version_label)
            if not result.has_update or not result.display_version:
                return
            display_version = result.display_version
            self.root.after(0, lambda: self._show_update_notice(display_version))

        threading.Thread(target=worker, daemon=True, name="UpdateCheck").start()

    def _show_update_notice(self, display_version: str) -> None:
        """ShowUpdateNotice() (DiveToPalworld.cs L.3595-3607) 相当。UIスレッド
        専用。updateLabel/updateNowButton(WP-A1で骨格のみ配置・place_forget()
        済み)を表示条件付きで再表示する。

        dev#551: こだわり設定パネルが閉じている間はフッター行全体が
        `_KODAWARI_PANEL_DELTA` ぶん上に詰まっている(layout_content_area()
        参照)ため、ここで初めて表示するupdateLabel/updateNowButtonも同じ
        deltaを引いた座標で配置する(そうしないと閉時に縮んだウィンドウの
        下に押し出され、表示されているのに見えない状態になる)。"""
        self._pending_update_version = display_version
        kodawari_open = getattr(self, "_kodawari_open", False)
        delta = 0 if kodawari_open else _KODAWARI_PANEL_DELTA
        update_label = self.widgets["updateLabel"]
        update_label.config(text=i18n.F("UpdateNoticeFormat", display_version))
        label_geo = dict(_FOOTER_OPEN_GEOMETRY["updateLabel"])
        label_geo["y"] -= delta
        update_label.place(**label_geo)
        update_now_button = self.widgets["updateNowButton"]
        button_geo = dict(_FOOTER_OPEN_GEOMETRY["updateNowButton"])
        button_geo["y"] -= delta
        update_now_button.place(**button_geo)

    def _on_open_update_download_page(self) -> None:
        """OpenUpdateDownloadPage() (DiveToPalworld.cs L.3613-3617) 相当。
        既定ブラウザで配布ページを開く。失敗しても無音(通知クリックの延長で
        二重にエラーダイアログを出す必要は無い、元実装のコメントどおり)。"""
        try:
            webbrowser.open(update_check.UPDATE_DOWNLOAD_PAGE_URL)
        except Exception:  # noqa: BLE001 -- 元実装と同じく無音で諦める
            pass

    def _get_os_description(self) -> str:
        """GetOsDescription() (DiveToPalworld.cs L.3939) の簡略版。
        C#はレジストリを直読みして厳密なWindowsビルド番号を得ていたが、Python版は
        標準ライブラリのplatformモジュールで足りる粒度に留める(診断ログの
        補助情報であり、この値自体がゲート判定に使われることはないため)。"""
        try:
            return f"Windows {platform.release()} ({platform.version()})"
        except Exception:  # noqa: BLE001
            return "unknown"

    def _build_diagnostics_text(self) -> str:
        """BuildReportPayloadJson前段の「診断ログ本文」組み立て(DiveToPalworld.cs
        L.4180-4219相当、§2.5)。support_dialog.SupportContext.build_diagnostics_text
        コールバックの実体。dev#98/#103のOtherPakSummaryLine(=SummarizeOtherPaks、
        WP-A11/dev#549で移植済みだったがmain_window結線が無かった)をここで
        実際に組み込む(D1の統合対象そのもの)。"""
        lines: list[str] = []
        lines.append(f"date: {datetime.now().isoformat(timespec='seconds')}")
        lines.append(f"version: {TOOL_VERSION}")
        lines.append(f"os: {self._get_os_description()}")
        file_lang = i18n.FILE_LANG_CODES.get(i18n.current_lang, i18n.current_lang)
        lines.append(f"lang: {file_lang} (ui) / {self._current_os_culture_name() or 'unknown'} (os)")
        vrm_path = self.widgets["vrmBox"].get().strip() if "vrmBox" in self.widgets else ""
        avatar_name = os.path.basename(vrm_path) if vrm_path else "(not selected)"
        lines.append(f"avatar: {avatar_name}")
        try:
            paks_dir = pak_manager.paks_dir_quiet(self.app_root, cache=self._paks_dir_cache)
            other_pak_line = pak_manager.summarize_other_paks(pak_manager.count_other_paks(paks_dir))
        except Exception:  # noqa: BLE001 -- 診断文の組み立て自体は失敗させない
            other_pak_line = "other_paks: unknown (paks dir not found)"
        lines.append(other_pak_line)
        status_text = self.widgets["statusLabel"].cget("text") if "statusLabel" in self.widgets else ""
        lines.append(f"status: {status_text}")
        lines.append("--- Execution Log (all work on this avatar, including across process steps) ---")
        try:
            log_text = self.log_box.get("1.0", "end-1c")
        except tk.TclError:
            log_text = ""
        lines.append(log_text)
        return "\n".join(lines)

    def _read_full_log_attachment_text(self) -> Optional[str]:
        """dev#921全ログ添付版(2026-08-03オーナー裁定「僕のローカルと同じ
        レベルのログが取れるようにして」「全部サニタイズしておくればいい
        だけ」)のGUI結線。support_dialog.SupportContext.get_attachment_log_text
        コールバックの実体。work_root\\<name>\\配下(job.json・build\\の
        ログ・json・csv等)+Unity輸出ディレクトリ(work_root\\<base>_export\\
        unity_export.log)+app_root\\logs\\launch.log(GUIのprint出力先、
        問い合わせGU8L26D7で「GUIが自動プレビューを試みたか静かに止まった
        か」が判定できなかった反省)をまとめて1つの添付テキストへ束ねる。
        個々のファイル収集・伏字化はすべてinquiry.py側の既存実装
        (build_work_dir_attachment_text/mask_full_log_for_attachment)を
        再利用するだけで、ここでは「どのディレクトリ・ファイルを対象に
        するか」だけを決める。

        VRM/prefab未選択(vrmBox空)でもlaunch.logだけは添付を試みる
        (GUIの挙動追跡はアバター選択前の操作にも及ぶため)。収集元が
        1つも無い/読めない場合は空文字列がNoneへ変換されて返る
        (support_dialog.on_ok側は添付無しで送信を続行する、issue #921の
        「ログが無いことを理由に送信を失敗させない」設計)。

        dev#1102: unity_exportディレクトリの収集は「vrmBoxが埋まっているか」
        ではなく「今セッションでUnity輸出を試みたことがあるか」を優先し、
        試みていなければ従来どおりvrmBoxへフォールバックする2段判定にする。
        vrmBoxはUnity輸出**成功後**にしか埋まらない(_on_unity_export_exit()は
        code!=0の失敗時にreturnして_set_vrm_pathを一切呼ばない)ため、
        vrm_path(=vrmBoxの中身)だけを条件にすると、輸出が失敗した瞬間に
        必ずゲートが偽になり、原因究明に最も必要なunity_export.logそのものが
        添付から漏れる(実報告KRFHQR2K、dev#921「二層化添付」がこの分岐だけ
        空振りしていた構造的欠陥)。

        一方で _pending_prefab_export_path 単独に置き換えると別の退行が出る
        (master-writerレビューで指摘、本WPで是正): この属性は
        _on_prefab_selected() が輸出プロセスを実際に起動する直前にしか
        設定されない。以下の2経路はこの関数を経由せず、かつ今セッションで
        輸出を試みたわけでもないのに vrmBox（=vrm_path）だけは正当に埋まる:
          (1) _on_prefab_selected() 冒頭のキャッシュ鮮度ヒット早期return
              (lu_export.is_export_cache_fresh時、Unity再起動そのものを
              省略して_set_vrm_path(prefab_path)だけ呼ぶ)
          (2) _restore_last_vrm_on_startup()(起動時、settings_lastvrm.txt
              から前回成功アバターを_set_vrm_path経由で復元。prefab選択
              フローを一切経由しない)
        これらのケースで _pending_prefab_export_path はNoneのままなので、
        単独判定だと「前回成功セッション由来のunity_export.log」まで
        添付できなくなってしまう(vrm_path単独ゲートの旧実装なら添付できて
        いたものが退行する)。

        したがって判定は「_pending_prefab_export_path があればそれを優先
        (今セッションの最新の輸出試行、成功/失敗問わず) → 無ければ
        vrm_path にフォールバック(復元/キャッシュヒットのみのセッションは
        従来どおりの挙動)」とする。輸出試行と復元/キャッシュヒットは
        意味が異なる状態のため、後者の分岐へpendingを代入して1つの属性に
        混ぜる案は採らない(指揮者裁定)。"""
        labeled_dirs: list[tuple[str, str]] = []
        vrm_path = self.widgets["vrmBox"].get().strip() if "vrmBox" in self.widgets else ""
        if vrm_path:
            try:
                name = pipeline_runner.sanitize_name(
                    os.path.splitext(os.path.basename(vrm_path))[0]
                )
                labeled_dirs.append(("work", os.path.join(self.work_root, name)))
            except Exception:  # noqa: BLE001 -- 添付収集の失敗で送信自体を止めない
                pass
        export_prefab_path = getattr(self, "_pending_prefab_export_path", None) or vrm_path
        if export_prefab_path:
            try:
                export_dir = pipeline_runner.resolve_unity_export_out_dir(
                    self.work_root, export_prefab_path
                )
                labeled_dirs.append(("unity_export", export_dir))
            except Exception:  # noqa: BLE001
                pass
        launch_log_path = os.path.join(self.app_root, "logs", "launch.log")
        try:
            text = inquiry.build_work_dir_attachment_text(
                labeled_dirs=labeled_dirs,
                labeled_files=[("launch_log", launch_log_path)],
            )
        except Exception:  # noqa: BLE001
            return None
        return text or None

    def _on_show_support_dialog(self) -> None:
        """reportButton.Click相当(ShowSupportDialog()呼び出し箇所)。

        dev#1641(2026-08-22オーナー裁定): 8/28のClaude運用終了に向けサポート
        窓口を畳んだ。ボタン押下では終了メッセージ(i18n "SupportEndedMessage")
        のみを表示し、ログ収集・送信フロー(support_dialog.show_support_dialog
        以下)へは一切進ませない。support_dialog.py本体・SupportContext構築
        コードは削除せず、単にここから呼ばなくする(最小差分、到達不能化)。
        旧: channel解決→SupportContext構築→show_support_dialog呼び出し
        (dev#532 D1 / dev#921全ログ添付版)。"""
        messagebox.showinfo(i18n.S("BtnReport"), i18n.S("SupportEndedMessage"))

    def _on_open_lab_window(self) -> None:
        """BtnLab.Click相当(dev#1186)。ラボ窓(機能グリッド)を開く。
        機能の追加・撤去はレジストリ(lab_window.LAB_FEATURES)側だけで完結し、
        ここは呼び出すだけ(将来機能が増えても本メソッドは変更不要)。"""
        lab_window.open_lab_window(self, self.root)

    def _refresh_lab_warning(self) -> None:
        """dev#1186: ラボ機能が1つでも既定から変わっている間だけ
        labWarningLabelを表示する(全無効なら非表示に戻す)。ラボ窓の
        ダイアログ(open_dialog経由)・「全てのラボ機能を無効化」ボタン・
        job.json復元(_apply_restored_settings)のいずれからも、状態が
        変わりうるたびに呼ばれる想定(lab_window.py側のrefresh()参照)。

        dev#1311: 以前はここで一覧(_on_refresh_pak_list)も再読込していた
        (dev#1170コミットcecbf70)。しかし本メソッドはpak一覧の行選択
        (_on_pak_list_selected → _apply_restored_settings)からも毎回
        呼ばれるため、行をクリックした瞬間に一覧が作り直されて選択が
        即座に解除される回帰を招いた(オーナー実機報告「fusionが選択
        できない」)。一覧再読込は「ラボダイアログを閉じたとき」だけに
        限定すべきものなので、lab_window.py側のrefresh()(ダイアログ
        <Destroy>から呼ばれる唯一の汎用フック)へ移設した——本メソッドは
        警告表示の更新だけに戻す。"""
        label = self.widgets.get("labWarningLabel")
        if label is None:
            return
        if lab_window.any_feature_active(self):
            label.config(text=i18n.S("LabWarningActive"))
            label.place(**self._lab_warning_geometry)
        else:
            label.place_forget()

    def _offer_report_after_failure(self, cause_text: str) -> None:
        """dev#138: 主要なエラーパス(Blender未検出/変換失敗/pak適用失敗)
        共通の「次アクション」導線。「ログをコピー」(support_dialog.py内の
        copy_log_btn)・問い合わせフォーム(同open_form_btn、送信先は
        inquiry.get_report_base_url()の正本定数)は一切再実装せず、既存の
        reportButton経路(_on_show_support_dialog、C#版ShowSupportDialog
        相当)へYesの場合だけ直接遷移させる。cause_textは呼び出し元が既に
        表示済みの短い原因文言(既存i18n文字列)をそのまま渡す想定
        (詳細な原因/対処自体は既にmessagebox等で表示済みのため、ここで
        繰り返さない)。"""
        if messagebox.askyesno(
            i18n.S("BtnReport"),
            i18n.F("MsgReportOfferFormat", cause_text, i18n.S("BtnReport")),
        ):
            self._on_show_support_dialog()

    def _log(self, text: str, *, gui: bool = True) -> None:
        """ログ欄への追記(旧AppendLog相当のごく簡略版)。dev#592層3(生存防御):
        ログ欄への描画・コンソール/リダイレクト先への出力のいずれも、
        GUI本体(ポーリング・進捗・完了処理)を巻き込んで死んではならない。

        dev#596b: gui=False の行はログ欄(log_box)には表示しない。ユーザーの
        判断に不要な開発向け詳細行を画面から抑制しつつ、print()経由でコンソール/
        launch.log(res\\logs\\launch.log、app_py\\main.pyがsys.stdoutをリダイレクト
        済み)には引き続き残す。診断可能性は落とさない。"""
        if gui:
            try:
                self.log_box.configure(state="normal")
                self.log_box.insert("end", text + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
            except tk.TclError:
                pass
        try:
            print(text)
        except Exception:  # noqa: BLE001 -- dev#592: cp932等でUnicodeEncodeError
            pass

    def _stub(self, action_name: str):
        """イベントハンドラの仮実装。押されたら「未実装」とログへ出すだけで、
        実処理は一切行わない(WP-A2以降が結線する、DESIGN.md §5.2)。

        dev#596b: 現存する唯一の呼び出し元(pakList選択変更)はユーザー操作の
        たびに毎回発火する高頻度ノイズで、「not implemented」という文言自体が
        ユーザーの判断に資さない(むしろ何か壊れているように誤解されうる)ため、
        GUIログ欄への表示は抑制する(gui=False、console/launch.logには残す)。"""

        def handler(*_args, **_kwargs):
            self._log(f"[stub] {action_name}: not implemented", gui=False)

        return handler

    def _register_text(self, widget: tk.Widget, key: str) -> None:
        i18n.register(widget, key, i18n.default_text_setter)

    def _register_tip(self, widget: tk.Widget, key: str) -> None:
        tip = _ToolTip(widget)
        self._tooltips.append(tip)
        i18n.register(tip, key, lambda w, text: w.set_text(text))

    def _update_window_title(self) -> None:
        self.root.title(
            f"Uchinoko for Palworld {TOOL_VERSION} - {i18n.S('TitleSubtitle')}"
        )

    # -- ウィジェット構築 ---------------------------------------------------

    def _build_content_container(self, outer: tk.Tk) -> tk.Widget:
        """dev#662: `outer`(実ウィンドウ)の直下にcontentサイズ固定
        (workarea.CONTENT_WIDTH x workarea.CONTENT_HEIGHT = 1100x900、
        dev#551でフッター余白適正化のため930から900へ変更)の
        Frameを置き、その参照を返す。_build_widgets()はこの戻り値を
        `root`として使い、既存のplace()絶対座標をそのまま流用する。

        self._needs_scroll が False(通常環境)なら、Canvasを1枚挟むだけで
        Scrollbarはpackしない(スクロール操作自体が発生しない=見た目・操作感は
        従来のroot直下と同一)。True(作業領域がcontentより狭い環境)の場合
        だけ、縦Scrollbarをpackしマウスホイールを束縛する。「問い合わせボタンに
        必ず到達できる」という受入条件は、このScrollbar自体(ドラッグ/トラック
        クリックで動く独立ウィジェット、ホイールの当たり判定に依存しない)で
        満たす。

        self._window_width/_window_height/_needs_scroll はgetattrで既定値に
        フォールバックする(MainWindow.__init__を経由しない「フェイクself」
        テスト——test_main_window_lang_combo.py等の既存の慣例——が
        _build_widgets()だけを単体で呼べるようにするため。既定値は
        workarea.CONTENT_WIDTH x CONTENT_HEIGHT・スクロール無しで、
        __init__を経由しない環境では従来と完全に同じ挙動になる)。
        """
        window_width = getattr(self, "_window_width", workarea.CONTENT_WIDTH)
        window_height = getattr(self, "_window_height", workarea.CONTENT_HEIGHT)
        needs_scroll = getattr(self, "_needs_scroll", False)

        canvas = tk.Canvas(
            outer,
            width=window_width,
            height=window_height,
            highlightthickness=0,
        )
        canvas.pack(side="left", fill="both", expand=True)

        content = tk.Frame(canvas, width=workarea.CONTENT_WIDTH, height=workarea.CONTENT_HEIGHT)
        canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(scrollregion=(0, 0, workarea.CONTENT_WIDTH, workarea.CONTENT_HEIGHT))

        if needs_scroll:
            scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
            scrollbar.pack(side="right", fill="y")
            canvas.configure(yscrollcommand=scrollbar.set)
            self.widgets["contentScrollbar"] = scrollbar

            def _on_mousewheel(event: tk.Event) -> None:
                # Windows: event.delta は120刻み(1刻み=1ノッチ)。
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

            canvas.bind("<MouseWheel>", _on_mousewheel)
            content.bind("<MouseWheel>", _on_mousewheel)

        self.widgets["contentCanvas"] = canvas
        self._content_frame = content
        return content

    def _build_widgets(self) -> None:
        # dev#662: 作業領域が狭くウィンドウをcontent(1100x900、dev#551で930
        # から変更)より縮小した(self._needs_scroll=True、__init__の
        # workarea.compute_clamp()参照)
        # 場合のみ、Canvas+Scrollbarでcontentフレームをラップしスクロール可能に
        # する。以降のウィジェット生成コードは`root`ローカル変数を親として使う
        # だけなので、このラップ以外は既存のplace()呼び出しを一切書き換えない
        # (最小差分)。通常環境(needs_scroll=False)ではCanvas1枚だけの透過
        # ラップになり(Scrollbarはpackしない)、見た目は従来のroot直下と不変。
        root = self._build_content_container(self.root)

        # ---- 1行目: VRM (DESIGN.md §1.1 #1-#4) ----
        lbl_vrm = tk.Label(root, text=i18n.S("LabelAvatar"))
        lbl_vrm.place(x=12, y=15, width=70)
        self._register_text(lbl_vrm, "LabelAvatar")

        vrm_box = tk.Entry(root)
        vrm_box.place(x=80, y=12, width=650, height=23)
        self.widgets["vrmBox"] = vrm_box  # #1

        browse = tk.Button(root, text=i18n.S("BtnBrowse"), command=self._on_browse)
        browse.place(x=738, y=10, width=90, height=25)
        self._register_text(browse, "BtnBrowse")
        self.widgets["browse"] = browse  # #2

        drop_hint = tk.Label(root, text=i18n.S("HintDragDrop"))
        drop_hint.place(x=900, y=15, width=176)
        self._register_text(drop_hint, "HintDragDrop")
        self.widgets["dropHint"] = drop_hint  # #3

        # #4: D&D受け皿(WP-A8で実配線。DESIGN.md §6-2)。
        # C#版はForm全体(root相当)にAllowDrop=trueを設定しているため
        # (L.946)、Python版も特定ウィジェットではなくrootウィンドウ全体へ
        # インストールする。_setup_drag_and_drop()は__init__の最後で呼ぶ
        # (root.winfo_id()がジオメトリ確定前でも有効なHWNDを返すため、
        # ここ=_build_widgets内で呼んでも問題は無いが、他の初期化と
        # 順序を揃えるため__init__側に置く)。
        self.widgets["dndTarget"] = None  # 実体はウィジェットではなくdnd.DropTarget

        # ---- 2行目: メイン操作 (#5-#9) ----
        convert_button = tk.Button(
            root, text=i18n.S("BtnFullConvert"), command=self._on_full_convert
        )
        convert_button.place(x=12, y=44, width=200, height=36)
        self._register_text(convert_button, "BtnFullConvert")
        self.widgets["convertButton"] = convert_button  # #5

        cancel_button = tk.Button(
            root, text=i18n.S("BtnCancelConvert"), state="disabled",
            command=self._on_cancel_convert,
        )
        # dev#532 WP-A10: en "Cancel Conversion" が幅100pxであふれる
        # (i18n_overflow_lint.py実測 avail=89/measured=97、over=8px)ため、
        # 訳文は変えず幅を112pxへ拡張。busy_bar/blender_retry_button側の
        # 開始x=330に接するまで(convert_buttonの終端212との間に4pxの隙間を残す)
        # 広げても、cancel_buttonが有効化されるタイミング(#7のbusy_bar表示と同時)
        # と重ならない範囲(x=216+112=328 < 330)に収めてある。
        cancel_button.place(x=216, y=44, width=112, height=36)
        self._register_text(cancel_button, "BtnCancelConvert")
        self.widgets["cancelButton"] = cancel_button  # #6

        # #7: RunPipeline() L.2602-2603相当のジオメトリを_BUSY_BAR_GEOMETRYへ
        # 憶えておき、開始/終了のたびplace()/place_forget()し直す
        # (Visible=false初期状態、L.1012)
        self._busy_bar_geometry = dict(x=330, y=46, width=740, height=12)
        busy_bar = ttk.Progressbar(root, orient="horizontal", mode="determinate", maximum=100)
        busy_bar.place(**self._busy_bar_geometry)
        busy_bar.place_forget()
        self.widgets["busyBar"] = busy_bar  # #7

        status_label = tk.Label(root, text=i18n.S("StatusPromptVrm"), anchor="w")
        status_label.place(x=330, y=62, width=740)
        self.widgets["statusLabel"] = status_label  # #8
        # StatusPromptVrmは状態依存の初期表示であり静的i18nキーではないため
        # RegisterI18nTextはしない(C#側も同様、言語切替時はUpdateButtonStates等
        # 別経路で再計算する設計。DESIGN.md §4.4の対象外)

        blender_retry_button = tk.Button(
            root, text=i18n.S("BtnBlenderRetry"),
            command=self._ensure_blender_ready_on_startup,
        )
        blender_retry_button.place(x=330, y=44, width=160, height=36)
        blender_retry_button.place_forget()  # Visible=false 初期状態(失敗時のみ表示)
        self._register_text(blender_retry_button, "BtnBlenderRetry")
        self._register_tip(blender_retry_button, "TipBlenderRetry")
        self.widgets["blenderRetryButton"] = blender_retry_button  # #9

        # ---- 3行目: こだわり設定 (#10-#14) ----
        # dev#1136: オーナー指摘(スクショ付き、原文「UIだっさ！！！！」)による
        # レイアウト整理。設定項目・既定値・結線は一切変えず(dev#1136 issue
        # 本文の受入条件)、見た目だけを整理する。
        #
        # dev#1136追撃(PR #1144マージ後のオーナー実機確認でダメ出し): 初版は
        # 「見た目調整」「上級」を囲みフレーム+キャプション見出しで区切って
        # いたが、オーナー指示で以下へ差し替えた:
        #   - 囲みフレーム・グループ見出しは廃止(整列だけで整える)。
        #     GroupAppearance i18nキーも不要になったため削除済み
        #     (app_py\i18n_data.json参照)
        #   - 影の濃さ行/身長行を明確に別行にする(旧版は1行に横詰め、
        #     もしくは1つの囲み内に2行を詰めていて窮屈だった)
        #   - 両行で「ラベル/スライダー/値表示/ボタン」の横位置(x)を
        #     完全に一致させ、列として揃える(下記 _KODAWARI_COL_* 定数)
        #   - スライダーの縦位置を行の中でラベル・値と揃うよう下げる
        #     (スライダー/ラベル/値/ボタンいずれも行内の縦中心が揃うように
        #     y位置を計算してある。下記コメント内訳参照)
        # 影の濃さ行・身長行・削除ボーン行の3行構成になった分、パネルの
        # 高さが80→132へ伸びる。_KODAWARI_PANEL_DELTA(84→136)と
        # layout_content_area()のtop基準(208→260)を同じ増分(52px)だけ
        # ずらして追随させてある(閉時にプレビュー欄がトグル直下へ詰まる
        # 位置は不変、後述の定数コメント参照)。
        self._kodawari_open = False
        kodawari_toggle = tk.Button(
            root, text="▼ " + i18n.S("LabelKodawari"), command=self._on_toggle_kodawari
        )
        kodawari_toggle.place(x=12, y=88, width=150, height=26)
        self.widgets["kodawariToggle"] = kodawari_toggle  # #10

        # ---- ラボ(dev#1186): 実験的機能置き場への入口 ----
        # メイン窓に足すのはこの1ボタンだけ(オーナー承認デザイン「通常
        # ユーザーの画面変化はこの1ボタンだけに抑える」)。実UIはすべて
        # ui\lab_window.py側のToplevel(ラボ窓+機能別ダイアログ)に閉じ込める。
        lab_button = tk.Button(
            root, text=i18n.S("BtnLab"), command=self._on_open_lab_window
        )
        lab_button.place(x=170, y=88, width=90, height=26)
        self._register_text(lab_button, "BtnLab")
        self._register_tip(lab_button, "TipLabButton")
        self.widgets["labButton"] = lab_button

        # ラボ機能が1つでも既定から変わっている間だけ出す警告(dev#1186
        # 「メイン窓側が本命(ラボ窓を閉じていても見える位置)」)。
        # ジオメトリを覚えておき、_refresh_lab_warning()が表示/非表示を
        # 都度切り替える(既存レイアウトを壊さない控えめな1行ラベル)。
        self._lab_warning_geometry = dict(x=270, y=90, width=800, height=22)
        lab_warning_label = tk.Label(
            root, text=i18n.S("LabWarningActive"), fg="#b00000", anchor="w",
        )
        lab_warning_label.place(**self._lab_warning_geometry)
        lab_warning_label.place_forget()  # 既定(全ラボ機能=無効)は非表示
        self._register_text(lab_warning_label, "LabWarningActive")
        self.widgets["labWarningLabel"] = lab_warning_label

        kodawari_panel = tk.Frame(root, relief="solid", borderwidth=1)
        kodawari_panel.place(x=12, y=118, width=1058, height=_KODAWARI_PANEL_HEIGHT)
        kodawari_panel.place_forget()  # Visible=false 初期状態(L.1051)
        self._kodawari_panel = kodawari_panel

        # dev#1136追撃2(オーナー再フィードバック、PR #1145マージ後): 影の
        # 濃さ/身長/削除ボーンの3行すべてでラベルを右揃え(コロンの縦位置を
        # 揃える)にする。共通のラベル列(col_label_x〜col_label_right)を
        # 定め、各ラベルをanchor="e"で配置することで、テキスト長が言語ごと
        # 違ってもコロンの位置がcol_label_rightに揃う。
        # col_label_wはdrop_bones_label(既存の最大幅、dev#532 WP-A10で
        # 実測拡張済みの140px。「Drop Bones (Advanced):」の英語版が基準)を
        # そのまま流用し、影の濃さ/身長のラベルもこの幅へ合わせる(3ラベル
        # とも140px以内に収まることはi18n_overflow_lint.pyで検証済み)。
        # 注意: devtools\i18n_overflow_lint.py は `widget.place(width=N)` の
        # Nがリテラル整数でないと検査対象として拾えない(AST上でast.Constant
        # のみ許容、変数参照は非対応――静的解析なので値を実行時に解決しない
        # 設計、devtools\i18n_overflow_lint.py の `_extract_text_key`/
        # `parse_controls`参照)。そのため下の3ラベル(lbl_shadow/
        # lbl_height_scale/drop_bones_label)の`.place(width=...)`は、この
        # col_label_wと同じ値をあえてリテラル140で書く(値がズレたら
        # コメントとテストの両方で気付けるよう、リテラル側にも
        # "# = col_label_w"を付す)。
        col_label_x = 8
        col_label_w = 140
        col_label_right = col_label_x + col_label_w  # = 148
        # スライダー/値/ボタンの列は、ラベル列の右(コロン位置)から
        # ギャップ10pxを空けて開始する(ラベル幅が110/55→140へ伸びた分、
        # PR #1145時点の列位置(130/380/440)から+28pxずつ右へシフト)。
        col_slider_x = col_label_right + 10  # = 158
        col_slider_w = 240
        col_value_x = col_slider_x + col_slider_w + 10  # = 408
        col_button_x = col_value_x + 60  # = 468
        # 修正イテレーション2(オーナーUX評価#3、work\rd_19_flight\briefs\
        # uimock2_fixes2.md): 影の濃さ/身長/揺れの度合いの3行で、現在値
        # ラベルの幅がバラバラだった(50/45/90)。col_button_xとの間隔
        # (=60px、削除前のcol_button_x - col_value_x)を共通の「value列幅」
        # として3行とも揃える。実測(work\rd_19_uimock2\
        # measure_value_label_widths.py)で、揺れの度合いの選択肢文言は
        # 5言語中最長でも55px(ja「やわらかめ」)であることを確認済みなので、
        # 60pxへ縮めても値ラベル行のテキストは切れない。
        # 注: devtools\i18n_overflow_lint.pyはplace(width=N)のNがリテラル
        # 整数でないと検査対象として拾えない(既存コメント、col_label_w参照)
        # ため、下記3箇所の`width=60`はあえて変数化せずリテラルのまま揃える。

        # ---- 影の濃さ行 ----
        row1_top = 8
        lbl_shadow = tk.Label(
            kodawari_panel, text=i18n.S("LabelShadowStrength"), anchor="e"
        )
        lbl_shadow.place(x=col_label_x, y=row1_top + 9, width=140)  # = col_label_w
        self._register_text(lbl_shadow, "LabelShadowStrength")

        shadow_bar = tk.Scale(
            kodawari_panel, from_=0, to=100, orient="horizontal", showvalue=False,
        )
        shadow_bar.set(30)
        # dev#1136追撃: 旧版はy=行top+0(行の一番上に張り付き)だったのを、
        # +4だけ下げてラベル/値/ボタンの縦中心(行top+25)へ揃えた
        # (スライダー高26なので中心は(row1_top+4)+13=row1_top+17…と
        # ラベル側の中心row1_top+9+8=row1_top+17が一致する計算)。
        shadow_bar.place(x=col_slider_x, y=row1_top + 4, width=col_slider_w, height=26)
        shadow_label = tk.Label(kodawari_panel, text="30%")
        shadow_label.place(x=col_value_x, y=row1_top + 9, width=60)  # = 共通value列幅

        def _on_shadow_change(_value, bar=shadow_bar, lbl=shadow_label):
            lbl.config(text=f"{int(float(_value))}%")

        shadow_bar.config(command=_on_shadow_change)
        self._register_tip(shadow_bar, "TipShadowBar")
        self.widgets["shadowBar"] = shadow_bar  # #11

        mats_button = tk.Button(
            kodawari_panel, text=i18n.S("BtnMatsOnly"),
            command=self._on_materials_only,
        )
        mats_button.place(x=col_button_x, y=row1_top + 3, width=180, height=28)
        self._register_text(mats_button, "BtnMatsOnly")
        self._register_tip(mats_button, "TipMatsButton")
        self.widgets["matsButton"] = mats_button  # #12

        # dev#560 第③段: 身長(全体スケール)スライダー。dev#158裁定
        # (「スライダー」「0.5〜2.0」推奨)に従い、影の濃さ行の直下に
        # 別行として置く(dev#1136追撃でオーナー指示、旧版は同じ行に
        # 詰めていた)。「設定は少ないほど良い」(CLAUDE.md)方針により、
        # スライダー1本+既定へ戻すリセットボタン以外の付随設定は作らない。
        #
        # 値はshadow_barと同じ流儀でパーセント整数(50〜200)をtk.Scaleに
        # 持たせ、write_job()へ渡す直前にのみ/100.0して job.json の
        # `uniform_scale`(float, 既定1.0)へ書く。tk.Scale自体が50〜200の
        # 範囲外を生成しないため、UI操作からは0.5〜2.0の範囲外に出ない
        # (job.json復元経路のクランプは_apply_restored_settings側、
        # pipeline_runner.write_job()側にも重ねて持たせる=多重防御)。
        #
        # job.json内部パラメータ名`uniform_scale`はdev#560第①段(PR #1126,
        # マージ済み)がpipeline\blender\step02_retarget.py の
        # apply_output_scale()で読む値そのもので、本WPはここへの配線のみ
        # (パイプライン側は一切変更しない)。既定100%(=1.0倍)は同関数が
        # 早期returnする完全no-opのため、スライダーに触れない既存ユーザーへの
        # 影響はゼロ。
        #
        # ---- 身長行 ----
        row2_top = row1_top + 44  # 34(行の高さ目安)+10(行間ギャップ)
        lbl_height_scale = tk.Label(
            kodawari_panel, text=i18n.S("LabelHeightScale"), anchor="e"
        )
        lbl_height_scale.place(x=col_label_x, y=row2_top + 9, width=140)  # = col_label_w
        self._register_text(lbl_height_scale, "LabelHeightScale")

        height_scale_bar = tk.Scale(
            kodawari_panel, from_=50, to=200, orient="horizontal", showvalue=False,
        )
        height_scale_bar.set(100)
        # dev#1136追撃: shadow_barと同じ列x(col_slider_x)・同じ幅
        # (col_slider_w=240)へ統一(「横位置を列として統一する」)。
        # 旧140pxから拡大しても操作性は変わらない(値域50-200は不変、
        # showvalue=Falseでテキストも持たないためi18n_overflow_lintの
        # 対象外)。
        height_scale_bar.place(
            x=col_slider_x, y=row2_top + 4, width=col_slider_w, height=26
        )
        height_scale_label = tk.Label(kodawari_panel, text="100%")
        height_scale_label.place(x=col_value_x, y=row2_top + 9, width=60)  # = 共通value列幅

        def _on_height_scale_change(_value, lbl=height_scale_label):
            lbl.config(text=f"{int(float(_value))}%")

        height_scale_bar.config(command=_on_height_scale_change)
        self._register_tip(height_scale_bar, "TipHeightScale")
        self.widgets["heightScaleBar"] = height_scale_bar  # #12b (dev#560第③段)

        reset_height_scale_button = tk.Button(
            kodawari_panel, text=i18n.S("BtnResetHeightScale"),
            command=lambda: height_scale_bar.set(100),
        )
        reset_height_scale_button.place(
            x=col_button_x, y=row2_top + 3, width=90, height=28
        )
        self._register_text(reset_height_scale_button, "BtnResetHeightScale")
        self._register_tip(reset_height_scale_button, "TipResetHeightScale")
        self.widgets["resetHeightScaleButton"] = reset_height_scale_button  # #12c

        # ---- 揺れの度合い行(dev#1572、2026-08-18裁定「かたさが配線されて
        # いない問題」案C: v2.11方式の復元。dev#1508 W2b(2026-08-16)が
        # 一時的にON/OFFトグルへ置換していたものを、本WPで4段の標準機能
        # として復元した) ----
        # 影の濃さ/身長と同じ列(col_label_x/col_slider_x)・同じ行高(44)で
        # 3行目に置く(行自体はレイアウト無変更、中身だけ差し替え)。
        # 「揺れの度合い」は「なし(揺れ無し)/かため/ふつう/やわらかめ」の
        # 4択(v2.11.0実測順、SWAY_INTENSITY_VALUES直前コメント参照)で、
        # job.json `sway_intensity` キーへ結線する(既存の一括刻印
        # 経路 pipeline\py\sway_abp_build.py hardness_key_for_intensity()
        # が読む値そのもの、write_job()参照)。
        #
        # 鎖ごとの細かい調整(個別「ゆれかた」・生パラメータ)は本WPで画面
        # から隠蔽した(ui\lab_window.py LAB_FEATURESから
        # SWAY_STYLE_FEATUREを除去、コードは温存)——このスライダーが
        # アバター全体の揺れの強さを選ぶ唯一の標準機能になる。
        row3_top = row2_top + 44
        lbl_sway_intensity = tk.Label(
            kodawari_panel, text=i18n.S("LabelSwayIntensity"), anchor="e"
        )
        lbl_sway_intensity.place(x=col_label_x, y=row3_top + 9, width=140)  # = col_label_w
        self._register_text(lbl_sway_intensity, "LabelSwayIntensity")

        sway_intensity_bar = tk.Scale(
            kodawari_panel, from_=0, to=3, resolution=1,
            orient="horizontal", showvalue=False,
        )
        sway_intensity_bar.set(_SWAY_INTENSITY_DEFAULT_INDEX)
        sway_intensity_bar.place(x=col_slider_x, y=row3_top + 4, width=col_slider_w, height=26)

        sway_intensity_value_label = tk.Label(
            kodawari_panel, text=i18n.S(SWAY_INTENSITY_I18N_KEYS[_SWAY_INTENSITY_DEFAULT_INDEX])
        )
        sway_intensity_value_label.place(x=col_value_x, y=row3_top + 9, width=60)  # = 共通value列幅

        def _on_sway_intensity_change(
            _value: str, lbl=sway_intensity_value_label
        ) -> None:
            idx = int(float(_value))
            if 0 <= idx < len(SWAY_INTENSITY_I18N_KEYS):
                lbl.config(text=i18n.S(SWAY_INTENSITY_I18N_KEYS[idx]))

        sway_intensity_bar.config(command=_on_sway_intensity_change)

        def _refresh_sway_intensity_value_label(_widget: tk.Misc, _text: str) -> None:
            # 言語切替のたび現在indexに対応する訳文へ差し替える
            # (height_scale_bar等の「値ラベルは言語非依存」パターンと違い、
            # 選択肢自体が言語ごとに翻訳される文言のため。選択中indexは保持)。
            idx = int(float(sway_intensity_bar.get()))
            if 0 <= idx < len(SWAY_INTENSITY_I18N_KEYS):
                sway_intensity_value_label.config(text=i18n.S(SWAY_INTENSITY_I18N_KEYS[idx]))

        i18n.register(
            sway_intensity_value_label, "LabelSwayIntensity",
            _refresh_sway_intensity_value_label,
        )
        self._register_tip(sway_intensity_bar, "TipSwayIntensity")
        self.widgets["swayIntensityBar"] = sway_intensity_bar  # #12d
        # 値ラベルもwidgetsへ登録しておく(job.json復元時、tk.Scale.set()は
        # -commandを起動しないため、_apply_restored_settings側から明示的に
        # テキストを更新する必要がある。下記_apply_restored_settings参照)。
        self.widgets["swayIntensityValueLabel"] = sway_intensity_value_label

        # ---- 削除ボーン行(dev#1186でラボへ移設) ----
        # 旧「削除ボーン(上級)」のLabel/Entry/Hintは ui\lab_window.py の
        # open_drop_bones_dialog() (独立Toplevel) へ移した(オーナー裁定
        # 「普通の人使わないからラボ落ちでいい」)。設定値の保存先・
        # パイプラインへの受け渡し(job設定のdrop_bonesキー)は一切変えない
        # ——dropBonesBoxというEntryウィジェット自体は従来どおりここで生成し
        # widgets["dropBonesBox"]へ登録する(_apply_restored_settings/
        # _is_preview_fresh/_start_pipeline等の既存コードは無変更のまま
        # .get()/.delete()/.insert()で読み書きし続ける)。違いは
        # kodawari_panelへ`.place()`しない=画面上には出さない点のみ。
        # 可視のEntryはラボ窓のダイアログが毎回新しく作り、開いた時点の
        # dropBonesBox.get()で初期値を読み、変更のたびここへ書き戻す
        # (lab_window.open_drop_bones_dialog参照)。
        drop_bones_box = tk.Entry(kodawari_panel)
        self.widgets["dropBonesBox"] = drop_bones_box  # #13(非表示のバッキングストア)

        # dev#1277(DESIGN.md 1.3節、案A採用): このボタンは元々「ボーンで
        # メッシュ削除」(旧・削除ボーン(上級))がこだわり設定パネル内に
        # あった時代の更新ボタンで、dev#1186でその機能がラボへ移設された際に
        # 置き去りにされた遺物(オーナー確認)。プレビュー更新はラボの各機能
        # 側へ個別に配線し直す方針で、WP1(本WP)でシェイプキー/メッシュ削除の
        # 2ダイアログへ配線済み(shapekey_select_dialog.py/mesh_delete_dialog.py
        # 参照。ボーンでメッシュ削除はWP2で同様に配線予定)。このパネルからは
        # 画面上撤去する。
        # ウィジェット自体・widgets["previewButton"]への登録・
        # command=self._on_preview_only は dropBonesBox と同じ「非表示の
        # バッキングストア」として残す(`.place()`・`_register_text`/
        # `_register_tip`のみ削除=画面上には出さない)。理由:
        # _update_button_states()がwidgets["previewButton"]の存在・state遷移
        # を無条件に前提にしており、ウィジェット自体を削除すると
        # test_button_gates.py等の既存テスト群がKeyErrorで壊れる
        # (「画面から消す」というオーナー要求と「内部ゲート機構は無傷で残す」
        # を両立させる、dropBonesBoxが既に辿った前例と同じ扱い)。
        preview_button = tk.Button(
            kodawari_panel, text=i18n.S("BtnPreviewUpdate"),
            command=self._on_preview_only,
        )
        self.widgets["previewButton"] = preview_button  # #14(非表示のバッキングストア)

        # ---- プレビュー+ログ (#15-#16) ----
        # Top値はLayoutContentArea()が開閉状態に応じて動的計算する
        # (layout_content_area()参照、#25)。ここでは初期値のみ置く。
        preview_front = tk.Label(
            root, text=i18n.S("LabelPreviewPlaceholderFront"),
            relief="solid", borderwidth=1, bg="#f0f0f0",
        )
        preview_front.place(x=12, y=210, width=380, height=360)
        self.widgets["previewFront"] = preview_front  # #15 (front)
        # LabelPreviewPlaceholderFront/Sideはimageが設定されると
        # Label既定のcompound=none挙動でtextが隠れる(表示上は無害)ため、
        # 通常の静的キーとして_register_textでも問題ない(dev#630)
        self._register_text(preview_front, "LabelPreviewPlaceholderFront")

        preview_side = tk.Label(
            root, text=i18n.S("LabelPreviewPlaceholderSide"),
            relief="solid", borderwidth=1, bg="#f0f0f0",
        )
        preview_side.place(x=400, y=210, width=380, height=360)
        self.widgets["previewSide"] = preview_side  # #15 (side)
        self._register_text(preview_side, "LabelPreviewPlaceholderSide")
        # 実画像表示(work\<名>\converted\preview_male_stand[_side].png)は
        # dev#599で実装済み(_apply_previews/_set_preview_widget参照)。
        # Pillow等の追加依存は使わずtk.PhotoImage(Tk 8.6ネイティブPNGデコード)
        # だけで完結させている。ここで生成するのは初期プレースホルダのLabelのみ

        log_box = tk.Text(root, state="disabled", wrap="word")
        log_box.place(x=790, y=210, width=280, height=360)
        self.widgets["logBox"] = log_box  # #16
        self.log_box = log_box

        # ---- 作成済みMODの一覧と適用/解除 (#17-#20) ----
        lbl_paks = tk.Label(root, text=i18n.S("LabelPakList"))
        lbl_paks.place(x=12, y=584, width=130)
        self._register_text(lbl_paks, "LabelPakList")
        self.widgets["lblPaks"] = lbl_paks  # #17

        applied_label = tk.Label(root, text=i18n.S("AppliedStatusChecking"), anchor="w")
        applied_label.place(x=150, y=584, width=920)
        self.widgets["appliedLabel"] = applied_label  # #18

        pak_list = ttk.Treeview(
            root, columns=("avatar", "file", "size", "created"), show="headings",
        )
        pak_list.heading("avatar", text=i18n.S("ColAvatar"))
        pak_list.heading("file", text=i18n.S("ColFile"))
        pak_list.heading("size", text=i18n.S("ColSize"))
        pak_list.heading("created", text=i18n.S("ColCreatedAt"))
        pak_list.column("avatar", width=200)
        pak_list.column("file", width=380)
        pak_list.column("size", width=100)
        pak_list.column("created", width=170)
        pak_list.place(x=12, y=608, width=870, height=180)
        # 選択でのプレビュー・設定復元(PakListSelectedIndexChanged、
        # DiveToPalworld.cs L.1126-1137相当)。dev#605で結線
        # (_on_pak_list_selected/_apply_restored_settings参照、dev#616 A+Iと共用)。
        pak_list.bind("<<TreeviewSelect>>", self._on_pak_list_selected)
        self.widgets["pakList"] = pak_list  # #19
        self._pak_list_columns = {
            "avatar": "ColAvatar", "file": "ColFile", "size": "ColSize", "created": "ColCreatedAt",
        }

        apply_button = tk.Button(
            root, text=i18n.S("BtnApply"), command=self._on_apply_selected
        )
        apply_button.place(x=890, y=608, width=180, height=34)
        self._register_text(apply_button, "BtnApply")
        self._register_tip(apply_button, "TipApply")
        self.widgets["applyButton"] = apply_button  # #20 (apply)

        remove_button = tk.Button(
            root, text=i18n.S("BtnRemoveMod"), command=self._on_remove_applied
        )
        remove_button.place(x=890, y=648, width=180, height=34)
        self._register_text(remove_button, "BtnRemoveMod")
        self._register_tip(remove_button, "TipRemove")
        self.widgets["removeButton"] = remove_button  # #20 (remove)

        refresh_button = tk.Button(
            root, text=i18n.S("BtnRefreshList"), command=self._on_refresh_pak_list
        )
        refresh_button.place(x=890, y=688, width=180, height=28)
        self._register_text(refresh_button, "BtnRefreshList")
        self.widgets["refreshButton"] = refresh_button  # #20 (refresh)

        delete_button = tk.Button(
            root, text=i18n.S("BtnDeleteResult"), command=self._on_delete_selected
        )
        delete_button.place(x=890, y=724, width=180, height=28)
        self._register_text(delete_button, "BtnDeleteResult")
        self._register_tip(delete_button, "TipDelete")
        self.widgets["deleteButton"] = delete_button  # #20 (delete)

        # ---- 問合せ (#21) ----
        # dev#532 D1: ShowSupportDialog()相当の実配線。support_dialog.py(WP-A5)は
        # main_window.pyへの結線権限を持たなかったため未配線のまま残っていた
        # ("main_window.pyへのボタン結線自体は統合WPで行う"、support_dialog.py
        # 冒頭コメント)。_on_show_support_dialog()参照。
        report_button = tk.Button(
            root, text=i18n.S("BtnReport"), command=self._on_show_support_dialog
        )
        report_button.place(x=890, y=760, width=180, height=28)
        self._register_text(report_button, "BtnReport")
        self._register_tip(report_button, "TipReport")
        self.widgets["reportButton"] = report_button  # #21

        # ---- 自動適用チェック (#22) ----
        auto_apply_var = tk.BooleanVar(value=settings.load_autoapply(self.app_root))
        auto_apply_check = tk.Checkbutton(
            root, text=i18n.S("CheckAutoApply"), variable=auto_apply_var,
            command=lambda: settings.save_autoapply(self.app_root, auto_apply_var.get()),
            anchor="w",
        )
        auto_apply_check.place(x=12, y=794, width=500, height=20)
        self._register_text(auto_apply_check, "CheckAutoApply")
        self._register_tip(auto_apply_check, "TipAutoApply")
        self.widgets["autoApplyCheck"] = auto_apply_check  # #22
        self._auto_apply_var = auto_apply_var

        # ---- 検証済みPalworldバージョン表示 (#26, dev#495) ----
        # ストアの動作環境欄に「検証済みの最新バージョンはツール内の表示を
        # ご覧ください」と書く前提を満たすための常時表示。従来は
        # compat_check.format_supported()の結果が版不一致警告ダイアログの中
        # (_check_palworld_version_once参照)にしか出ておらず、通常時のGUIには
        # 検証済みバージョンを確認する手段が存在しなかった(dev#495発端の
        # 裏取りで判明)。テキストは_refresh_verified_version_label()が
        # _load_known_good_palworld()(同梱json+配信versions.jsonのマージ結果、
        # L.617-627)から都度組み立てる。ここではウィジェットの骨格のみ生成し
        # 空文字のまま置く(初期反映は__init__側の_refresh_verified_version_label()
        # 呼び出しに一本化し、フェイクselfで_build_widgets()だけを呼ぶ既存テスト
        # 流儀(test_main_window_lang_combo.py等)を壊さないため)。
        # ここでの.place()呼び出しは_FOOTER_OPEN_GEOMETRY["verifiedVersionLabel"]
        # と同じ「開いた状態」の絶対座標にすぎず、直後のlayout_content_area()
        # (__init__ L.353付近)がこだわり設定の実際の開閉状態(既定=閉)に応じて
        # 上書きする(dev#551是正、issue #551 2026-08-02コメント)。
        verified_version_label = tk.Label(root, text="", anchor="w")
        verified_version_label.place(x=12, y=878, width=1058, height=20)
        self._register_tip(verified_version_label, "TipVerifiedPalworldVersion")
        self.widgets["verifiedVersionLabel"] = verified_version_label  # #26

        # ---- 更新通知 (#23) ----
        # dev#619結線: OpenUpdateDownloadPage() (DiveToPalworld.cs L.1195/1213/
        # 3613-3617) 相当。クリックで既定ブラウザにupdate_check.py既存の
        # UPDATE_DOWNLOAD_PAGE_URL(=DiveToPalworld.cs L.733 UpdateDownloadPageUrl
        # をそのまま移植した定数)を開く。失敗しても無音(元実装のtry/catch通り)。
        update_label = tk.Label(
            root, text="", fg="blue", cursor="hand2", anchor="w",
        )
        update_label.place(x=12, y=822, width=1058, height=20)
        update_label.place_forget()  # Visible=false 初期状態
        update_label.bind("<Button-1>", lambda _e: self._on_open_update_download_page())
        self._register_tip(update_label, "TipUpdateLabel")
        self.widgets["updateLabel"] = update_label  # #23 (label)

        update_now_button = tk.Button(
            root, text=i18n.S("BtnUpdateNow"),
            command=self._on_open_update_download_page,
        )
        update_now_button.place(x=12, y=848, width=130, height=22)
        update_now_button.place_forget()  # Visible=false 初期状態
        self._register_text(update_now_button, "BtnUpdateNow")
        self._register_tip(update_now_button, "TipUpdateNow")
        self.widgets["updateNowButton"] = update_now_button  # #23 (button)

        # ---- 言語切替 (#24) ----
        lbl_lang = tk.Label(root, text=i18n.S("LabelLanguage"))
        lbl_lang.place(x=850, y=94, width=60)
        self._register_text(lbl_lang, "LabelLanguage")

        lang_var = tk.StringVar(value=i18n.LANG_DISPLAY_NAMES[i18n.LANGS.index(i18n.current_lang)])
        lang_combo = ttk.Combobox(
            root, textvariable=lang_var, values=i18n.LANG_DISPLAY_NAMES,
            state="readonly",
        )
        lang_combo.place(x=914, y=90, width=156, height=24)
        # dev#595 再修正(2026-08-01): PR #608の「readonly Comboboxはcurrent()を
        # 呼ばないと初期表示が空になる」という見立ては、非表示Tkルートでの実証
        # (app_py\tests\test_main_window_lang_combo.pyのrepro系テスト)で否定
        # された——current()を呼ばず、textvariableだけ渡しても、その変数を
        # 生かし続けさえすれば普通に表示される。
        #
        # 実際の原因はPythonの参照カウントGCだった: lang_varはこの関数のローカル
        # 変数で、self.widgets/self.*のどこにも保持されていなかった。ttkウィジェット
        # 側はtextvariableを「Tcl変数名の文字列」として持つだけでPythonオブジェクト
        # への参照は握らないため、_build_widgets()がreturnした時点でlang_varの
        # 参照カウントが0になりCPythonが即座に破棄する。tkinter.Variable.__del__は
        # 破棄時に対応するTcl変数をglobalunsetvarで消してしまうため、ウィジェットは
        # 存在しない変数を指すことになり表示が空欄になる(combo.get()==""、
        # combo.current()==-1で再現・確認済み)。すぐ下のauto_apply_var
        # (L.741,751: self._auto_apply_var = auto_apply_var)は同じ関数内で
        # 正しく生存参照を保持しており、lang_varだけがその慣例から漏れていた。
        #
        # 修正: lang_varをself._lang_varとして保持し、GCされないようにする
        # (.current()呼び出し自体は無害なので実害ないが根治ではないため残す)。
        self._lang_var = lang_var
        lang_combo.current(i18n.LANGS.index(i18n.current_lang))
        lang_combo.bind("<<ComboboxSelected>>", self._on_language_selected)
        self._register_tip(lang_combo, "TipLanguageSwitch")
        self.widgets["langCombo"] = lang_combo  # #24
        self._lang_combo = lang_combo

        # #25: LayoutContentArea相当(layout_content_area()メソッド、後述)。
        # 独立したWidgetではなく再配置ロジックなので、呼び出し可能なメソッド
        # 自体をlookup対象として登録する
        self.widgets["layoutContentArea"] = self.layout_content_area  # #25

    # -- イベントハンドラ(stub含む) -----------------------------------------

    def _on_browse(self) -> None:
        # browse.Click (DiveToPalworld.cs L.958-973)相当: .prefabならUnity輸出
        # (RunUnityExport)、それ以外は最小SetVrm(vrmBoxへパスを入れるだけ。
        # セッションログ復元・以前のjob.json設定復元はWP-A2の外、モジュール
        # docstring参照)。
        #
        # dev#1124(dev#684/dev#758の続き、2026-08-01オーナー裁定「生FBXの
        # GUI入力は非対応」): filetypesから"*.fbx"を除去。ダイアログのフィルタは
        # 既定候補を絞るだけで、ファイル名欄への直接入力等でフィルタを迂回する
        # 余地が残るため、取得後にも明示ガードを置く(_on_fbx_gui_rejected)。
        # dev#684(PR#695)は一度ダイアログ/D&D/vrmBox直接入力/設定復元の4箇所を
        # 拒否する実装だったが、うち変換開始時(_start_pipeline)のガードが
        # prefab変換の内部生成FBXを巻き込み、内部/外部FBXを見分ける専用の
        # 回避コードが必要になった上、prefab経路が自動試験の網に一切かから
        # ないためPR#701でrevertされた(dev#758の教訓)。本WPはダイアログと
        # D&Dの2箇所だけに絞り、内部/外部FBXを区別する回避コードは一切
        # 持たない(単純に「.fbxなら拒否」)。_start_pipeline・vrmBox直接入力・
        # 設定復元・ui\dnd.pyには触れない(dev#1124のスコープ)。
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title=i18n.S("DlgTitleChooseAvatarFile"),
            filetypes=[(i18n.S("LabelAvatar"), ("*.prefab", "*.vrm"))],
        )
        if not path:
            return
        if path.lower().endswith(".fbx"):
            self._on_fbx_gui_rejected()
            return
        if path.lower().endswith(".prefab"):
            self._on_prefab_selected(path)
        else:
            self._set_vrm_path(path)

    def _set_vrm_path(self, path: str) -> None:
        """SetVrm()相当(DiveToPalworld.cs L.1510-1546を、py版が非同期読み込みを
        持たない実装に合わせて単純化したもの)。新しいアバターを選ぶたび
        licenseConfirmedを一旦リセットし(L.1514相当)、続けてそのアバターの
        job.jsonがあれば設定・プレビューを復元する(ApplyAvatarLoad()
        L.1571-1584相当、dev#616 A+Iで結線)。vrmBoxは直前にpathへ直接
        設定済みのため、復元側はvrm_pathで上書きしない(set_vrm_path=False。
        C#版もApplyAvatarLoadからのApplyRestoredSettings呼び出しは
        setVrmPath=falseで揃っている、L.1584)。"""
        self.widgets["vrmBox"].delete(0, tk.END)
        self.widgets["vrmBox"].insert(0, path)
        self._license_confirmed = False
        settings.save_last_vrm(self.app_root, path)
        self._log(path)
        name = pipeline_runner.sanitize_name(os.path.splitext(os.path.basename(path))[0])
        job_dir = os.path.join(self.work_root, name)
        self._apply_restored_settings(job_dir, set_vrm_path=False)
        # dev#611: ApplyAvatarLoad() L.1591-1597相当。アバター登録の全経路
        # (browse/D&D/prefabのUnity輸出完了)がこの_set_vrm_pathへ集約している
        # ため、末尾でここを呼ぶだけで3経路すべてに自動プレビューが結線される。
        self._maybe_auto_preview(path)
        # dev#613/#617: ApplyAvatarLoad() L.1598 `UpdateButtonStates();`相当
        # (RunPipeline()を試みた直後に必ず1回呼ばれる)。旧実装はここで
        # StatusReadyToConvertを無条件表示していたが、C#版はUpdateButtonStates()
        # のhasVrm/fresh判定に委ねている(自動プレビューが未生成/未実行のまま
        # 終わればStatusPreviewStaleが正しい)ため、鮮度判定込みの結線に置き換える。
        self._refresh_convert_button_freshness()

    def _apply_restored_settings(self, job_dir: str, *, set_vrm_path: bool) -> bool:
        """ApplyRestoredSettings()(DiveToPalworld.cs L.1633-1663)相当
        (dev#616 A+I)。対応するjob.jsonが無ければ何もせずFalseを返す
        (RestoreSettings() L.1621-1628の`if (!File.Exists(jobJson)) return;`
        相当)。py版WP-A1骨格にはshoulderBar/mergeFingersCheck/unlitCheck/
        twoSidedCheckに対応する可視ウィジェットが無い(C#版もUIには表示して
        いない内部フィールド、L.1041-1046「内部互換性のためにフィールドを
        初期化(UIには表示しない)」参照)。それらは_set_vrm_path冒頭で初期化
        済みの内部属性(_shoulder_offset_deg等)への反映に留め、run_pipeline
        呼び出し時にそのまま使われる(_start_pipeline参照)。dropBonesBox/
        shadowBarは両版とも可視ウィジェットなのでそのまま反映する。

        戻り値: job.jsonが見つかり反映できたか(呼び出し元は主にpak一覧選択
        ハンドラの単体テストで使う)。"""
        job_json = os.path.join(job_dir, "job.json")
        data = pipeline_runner.read_job(job_json)
        if data is None:
            return False

        if set_vrm_path:
            vrm = data.get("vrm_path")
            if vrm:
                self.widgets["vrmBox"].delete(0, tk.END)
                self.widgets["vrmBox"].insert(0, vrm)

        # shoulder_offset_deg: `JsonNum(json, "shoulder_offset_deg", shoulderBar.Value)`
        # 相当(キー欠落時は現在値を維持、L.1643-1645)。shoulderBar.Minimum/Maximum
        # は-20/20(DiveToPalworld.cs L.1042)。
        try:
            sh = float(data.get("shoulder_offset_deg", self._shoulder_offset_deg))
        except (TypeError, ValueError):
            sh = self._shoulder_offset_deg
        self._shoulder_offset_deg = max(-20, min(20, int(round(sh))))

        # shadow_lift: `JsonNum(json, "shadow_lift", -1)`相当。0以上の時だけ
        # 反映する(L.1646-1648)。shadowBarは0-100の可視ウィジェット。
        try:
            lift = float(data.get("shadow_lift", -1))
        except (TypeError, ValueError):
            lift = -1
        if lift >= 0:
            value = max(0, min(100, int(round(100 - lift * 100))))
            self.widgets["shadowBar"].set(value)

        # uniform_scale (dev#560 第③段): job.jsonの内部パラメータ`uniform_scale`
        # (第①段PR #1126がpipeline\blender\step02_retarget.pyで読む値、既定1.0)
        # をheightScaleBar(50〜200%)へ反映する。キー欠落時は現在値を維持する
        # (shoulder_offset_degと同じ流儀。shadow_liftのように「0は正当値だが
        # 未設定を示す番兵」を使う理由が無い=uniform_scaleの欠落は単に
        # 「このjob.jsonは第③段より前に書かれた」ことを意味するだけなので)。
        # 範囲外の値(手書きjob.json・旧バージョンの値)は0.5〜2.0へクランプ
        # する(dev#158裁定のレンジ、UI側の範囲制約と合わせた多重防御)。
        try:
            current_scale = float(self.widgets["heightScaleBar"].get()) / 100.0
        except (TypeError, ValueError, AttributeError):
            current_scale = 1.0
        try:
            scale = float(data.get("uniform_scale", current_scale))
        except (TypeError, ValueError):
            scale = current_scale
        scale = max(0.5, min(2.0, scale))
        self.widgets["heightScaleBar"].set(int(round(scale * 100)))

        # sway_intensity (dev#1572、2026-08-18裁定「かたさが配線されていない
        # 問題」案C): job.jsonの`sway_intensity`をswayIntensityBarへ反映
        # する。**移行規則**(モジュール冒頭のSWAY_INTENSITY_VALUES直前コメント
        # 「job.json復元時の移行規則」参照、3世代を吸収):
        #   1. `sway_intensity`がSWAY_INTENSITY_VALUESに含まれればそのまま
        #      使う(本WP以降、および dev#19プロトタイプ時代のjob.json)。
        #   2. 無ければdev#1508 W2b期の`sway_enabled`(bool)を見る:
        #      True→"normal"、False→"none"。
        #   3. どちらも無ければ"none"。
        # shadow_lift/uniform_scaleと違い「未設定=このWPより前のjob.json」を
        # 安全に判定できるため、現在値を維持する方式ではなく常に明示的に
        # 反映する(mesh_delete等のアバター切り替え誤爆防止と同じ考え方)。
        #
        # 修正イテレーション1(オーナーUX評価#5の踏襲): Comboboxではなく
        # tk.Scaleのため`.set(idx)`を使う。tk.Scaleの`.set()`は-commandを
        # 起動しない(実測確認済み)ため、値ラベル(swayIntensityValueLabel)の
        # テキストもここで明示的に更新しないと、復元直後は前回の表示文言の
        # まま取り残される。
        raw_sway_intensity = data.get("sway_intensity")
        if raw_sway_intensity in SWAY_INTENSITY_VALUES:
            sway_intensity = raw_sway_intensity
        elif "sway_enabled" in data:
            sway_intensity = "normal" if bool(data.get("sway_enabled")) else "none"
        else:
            sway_intensity = "none"
        if "swayIntensityBar" in self.widgets:
            sway_idx = SWAY_INTENSITY_VALUES.index(sway_intensity)
            self.widgets["swayIntensityBar"].set(sway_idx)
            if "swayIntensityValueLabel" in self.widgets:
                self.widgets["swayIntensityValueLabel"].config(
                    text=i18n.S(SWAY_INTENSITY_I18N_KEYS[sway_idx])
                )

        self._merge_fingers = bool(data.get("merge_fingers", self._merge_fingers))
        self._unlit = bool(data.get("unlit", self._unlit))
        self._force_two_sided = bool(data.get("force_two_sided", self._force_two_sided))
        # license_confirmed: `JsonBool(json, "license_confirmed", false)`相当。
        # 他の項目と違い既定値は常にfalse(現在値を維持しない、L.1652)。
        self._license_confirmed = bool(data.get("license_confirmed", False))

        # drop_bones: `JsonStrArray(json, "drop_bones")`相当。キーが在れば
        # (空配列でも)dropBonesBoxへ反映する(L.1653-1654)。
        drops = data.get("drop_bones")
        if isinstance(drops, list):
            box = self.widgets["dropBonesBox"]
            box.delete(0, tk.END)
            box.insert(0, ", ".join(str(b) for b in drops))
        # dev#1186: 復元されたdrop_bones(ラボ機能)が既定から変わっていれば
        # 警告を出す。hasattr guardは、本メソッドを束縛前のまま独立フェイク
        # self(test_main_window_restore.py等の_FakeSelf、_refresh_lab_warning
        # 未定義)へ直接bindして呼ぶ既存の単体テスト流儀を壊さないための保険
        # (実MainWindowインスタンスでは常にTrue)。
        if hasattr(self, "_refresh_lab_warning"):
            self._refresh_lab_warning()

        # LoadPreviews(jobDir)相当(L.1660。py版は非同期プリロードが無いため
        # imagesReady=falseの経路のみ、常にここでディスクから読む)。
        try:
            self._apply_previews(pipeline_runner.load_previews(job_dir))
        except Exception as ex:  # noqa: BLE001 -- プレビュー表示の失敗で復元全体を壊さない
            self._log(f"[preview] restore settings preview load failed: {ex}")
        return True

    def _maybe_auto_preview(self, path: str) -> None:
        """ApplyAvatarLoad() L.1591-1597の起動条件部分に相当:
        `if (File.Exists(r.Path) && !IsPreviewFresh() && runningProc == null
        && blenderReady) RunPipeline(true, false, true);`
        dev#613: py版にはプレビュー鮮度判定(IsPreviewFresh/BuildPreviewSig、
        DiveToPalworld.cs L.2416-2425)が未移植のままだったため(dev#611時点の
        既知のギャップ)、preview_freshness.py(本WPで新設)を使って移植する。
        4条件すべて(ファイル存在/鮮度/二重起動防止/Blender準備済み)を
        C#と同じ順序で揃えた。

        dev#921: 早期returnした場合、その理由を1行だけログへ残す(問い合わせ
        GU8L26D7で、「Unity輸出成功後、GUIが自動プレビューを試みたのか、
        静かに止まったのか」がログから一切判定できなかったため)。呼び出し
        元は browse/D&D/prefab Unity輸出完了のいずれもアバター選択のたび
        (_set_vrm_path経由)にしか通らない低頻度経路なので、ログ肥大化の
        懸念は無い(dropBonesBox変更等の高頻度経路からは呼ばれない)。"""
        if not os.path.isfile(path):
            self._log("[auto-preview] skip: reason=file-not-found")
            return
        if self._is_preview_fresh(path):
            self._log("[auto-preview] skip: reason=preview-fresh (cache)")
            return
        if self._active_handle is not None and self._active_handle.is_running():
            self._log("[auto-preview] skip: reason=other-process-running")
            return
        if not self._blender_ready:
            self._log("[auto-preview] skip: reason=blender-not-ready")
            return
        self._start_pipeline(preview_only=True, materials_only=False, auto=True)

    def _is_preview_fresh(self, vrm_path: str) -> bool:
        """IsPreviewFresh() L.2416-2425相当。呼び出し時点のdropBonesBox等の
        現在値を使うライブ判定(C#もコントロールの現在値を毎回読む。開始時点の
        スナップショットではない)。"""
        return preview_freshness.is_preview_fresh(
            self.work_root,
            vrm_path,
            self._shoulder_offset_deg,
            self._merge_fingers,
            self.widgets["dropBonesBox"].get(),
        )

    def _save_preview_sig(self, vrm_path: str) -> None:
        """SavePreviewSig() L.2427-2430相当。"""
        preview_freshness.save_preview_sig(
            self.work_root,
            vrm_path,
            self._shoulder_offset_deg,
            self._merge_fingers,
            self.widgets["dropBonesBox"].get(),
        )

    def _finalize_fresh_preview(self, vrm_path: str) -> None:
        """OnPipelineDone() L.2914-2915相当(`SavePreviewSig(); UpdateButtonStates();
        // フル変換ボタンがここで解禁される`)をまとめた結線ヘルパー。
        _on_pipeline_exit()のpreview_only成功時にだけ呼ぶ。呼び出し順序自体が
        C#と1:1対応する契約なので、テストでもこの順序を検査する。"""
        self._save_preview_sig(vrm_path)
        self._refresh_convert_button_freshness()

    def _refresh_convert_button_freshness(self) -> None:
        """UpdateButtonStates() (DiveToPalworld.cs L.2468-2525) のうち、
        Full Convertボタンの鮮度ゲート(L.2479-2480 hasVrm/fresh判定、L.2486
        convertButton.Enabled)とStatusPreviewStale/StatusReadyToConvertの
        テキスト分岐(L.2520-2523)を移植する(dev#617)。

        C#: `convertButton.Enabled = !busy && hasVrm && fresh && blenderReady
        && !workRootFailed;` のうち、matsButton/previewButtonと共有できない
        fresh判定が絡む部分だけをここへ切り出す(busy/blenderReady/
        workRootFailedの3条件は_update_button_states()と重複するが、
        convertButtonはfreshとの組み合わせでしか意味を持たないため独立させて
        いる。matsButton/previewButtonのゲートは_update_button_states()参照)。

        dev#621: workRootFailed(L.2486の`!workRootFailed`)は
        _set_running_ui_state()の3ボタン一括ガードとは別に、ここでも
        明示的に見る。このメソッドは_set_running_ui_state()を経由しない
        経路(_on_drop_bones_changed/_finalize_fresh_preview/__init__直後
        等)からも直接呼ばれるため、work_root_failed中に再度normalへ
        戻ってしまう漏れを構造的に防ぐ。

        dev#639: blenderReady(L.2486の`&& blenderReady`)も同じ理由で
        ここに明示的なガードを持つ(_update_button_states()を経由しない
        呼び出し経路があるため)。blenderReady未確定時のstatusLabel文言は
        _on_blender_setup_done()側が別途面倒を見るため、ここでは
        work_root_failedと同様にstatusLabelへ触れず早期returnするだけに
        留める。

        実行中(pipeline稼働中)はstatusLabelのテキストを変更しない
        (C#のUpdateButtonStates()も`if (!running)`の内側でのみテキストを
        書き換える、L.2504相当。実行中に呼ばれても「StatusPreviewGenerating」
        等の実行中メッセージを上書きしないための保護)。

        dev#1572(ラボ窓ブロック): ラボ系サブウィンドウが1つでも開いている
        (`_lab_subwindow_open_count>0`)間は、他の全ゲート判定より優先して
        convertButtonを強制disabledにする(statusLabelへは触れない、他の
        早期returnブランチと同じ流儀)。"""
        if getattr(self, "_lab_subwindow_open_count", 0) > 0:
            self.widgets["convertButton"].config(state="disabled")
            return
        if self._work_root_failed:
            self.widgets["convertButton"].config(state="disabled")
            return
        if not self._blender_ready:
            self.widgets["convertButton"].config(state="disabled")
            return
        vrm_path = self.widgets["vrmBox"].get().strip()
        has_vrm = os.path.isfile(vrm_path)
        fresh = has_vrm and self._is_preview_fresh(vrm_path)
        self.widgets["convertButton"].config(state=("normal" if fresh else "disabled"))
        running = self._active_handle is not None and self._active_handle.is_running()
        if running or not has_vrm:
            return
        self._set_status(
            lambda: i18n.S("StatusReadyToConvert") if fresh else i18n.S("StatusPreviewStale")
        )

    def _on_lab_subwindow_opened(self) -> None:
        """dev#1572(ラボ窓ブロック): ラボ系サブウィンドウ(ラボ窓本体または
        機能別設定ダイアログ)が1つ新たに開いたときに`ui\\lab_window.py`から
        呼ばれる。カウンタを増やし、直ちにconvertButtonを再評価する
        (`_refresh_convert_button_freshness()`が`_lab_subwindow_open_count>0`
        を見て強制disabledにする)。"""
        self._lab_subwindow_open_count = getattr(self, "_lab_subwindow_open_count", 0) + 1
        self._maybe_refresh_convert_button_after_lab_change()

    def _on_lab_subwindow_closed(self) -> None:
        """dev#1572(ラボ窓ブロック): ラボ系サブウィンドウが1つ閉じたときに
        `ui\\lab_window.py`から呼ばれる(`<Destroy>`イベント経由、開閉数が
        必ず対応する前提)。カウンタが0に戻れば、`_refresh_convert_button_
        freshness()`が通常のゲート判定(鮮度/blenderReady/work_root_failed)
        へ復帰する。0未満に潜らないようmax(0, ...)で下限を守る(ダイアログの
        `<Destroy>`が何らかの理由で二重発火しても壊れないための保険)。"""
        self._lab_subwindow_open_count = max(
            0, getattr(self, "_lab_subwindow_open_count", 0) - 1)
        self._maybe_refresh_convert_button_after_lab_change()

    def _maybe_refresh_convert_button_after_lab_change(self) -> None:
        """`_on_lab_subwindow_opened`/`_on_lab_subwindow_closed`共通の防御
        つき呼び出しヘルパー。`_refresh_convert_button_freshness()`は
        `self._work_root_failed`等、`__init__`時にしか設定されない属性へ
        直接アクセスするため、`MainWindow.__new__`経由で`__init__`を通さない
        既存テストの「束縛前self」double(test_main_window_lab_ui.py.
        _make_fake_self()等、`_update_button_states()`docstring参照)を
        壊さないよう、それらが揃っていない間は静かに何もしない。実運用の
        MainWindowは`__init__`で必ず揃うため到達しない分岐。"""
        if not hasattr(self, "_work_root_failed"):
            return
        if "convertButton" not in self.widgets:
            return
        self._refresh_convert_button_freshness()

    def _on_drop_bones_changed(self, _event=None) -> None:
        """dropBonesBox.TextChanged (DiveToPalworld.cs L.1256:
        `dropBonesBox.TextChanged += delegate { UpdateButtonStates(); };`) 相当。
        除外ボーン欄はBuildPreviewSig()の構成要素の1つなので、入力のたび
        Full Convertボタンの鮮度表示を即座に再計算する。"""
        self._refresh_convert_button_freshness()

    # -- D&D(WP-A8、DESIGN.md §1.1-#4/§6-2、ui\dnd.pyとの結線) -----------------

    def _setup_drag_and_drop(self) -> None:
        """OnDragEnter/OnDragDrop配線相当(DiveToPalworld.cs L.946-948)。
        非Windows環境ではdnd.install()がNoneを返すだけで何もしない
        (dnd.is_supported()参照、pytest等の非Windows実行環境を壊さないため)。
        失敗してもD&Dが使えなくなるだけでGUI自体は起動を続ける
        (この裁定の元ネタ: DESIGN.md冒頭『失敗しても画面を止めない』方針)。"""
        try:
            self._drop_target = dnd.install(
                self.root, on_path=self._on_dropped_path, on_rejected=self._on_drop_rejected
            )
        except Exception as ex:  # noqa: BLE001 -- D&D不可でも起動は継続する
            self._drop_target = None
            self._log(f"[dnd] failed to initialize, drag & drop disabled: {ex}")

    def _on_dropped_path(self, path: str) -> None:
        """OnDragDrop() L.1406-1421相当(拒否判定・Blenderゲート機構を除いた
        分岐部分。拡張子フィルタ・複数ファイル選択規則自体はdnd.py側の
        pick_dropped_path()が既に適用済みでここへ渡ってくる)。

        dev#1124(dev#684/dev#758の続き): ui\\dnd.pyのACCEPTED_EXTENSIONSは
        従来どおり.fbxを含んだまま変更しない(dnd.py自体はD&D全般の純粋な
        拡張子フィルタでありGUI固有の裁定を持ち込まない設計。本WPはmain_window.py
        のD&Dハンドラのみを書き換え、dnd.pyには触れない)。生FBXの拒否は
        UI層であるこのハンドラで行う。_on_browseと同じく「.fbxなら拒否」の
        単純判定のみで、内部/外部FBXを区別する回避コードは持たない
        (_start_pipeline側にもFBX専用の判定関数を持ち込まない、dev#1124の
        スコープ)。"""
        if path.lower().endswith(".fbx"):
            self._on_fbx_gui_rejected()
            return
        if dnd.is_prefab_path(path):
            self._on_prefab_selected(path)
        else:
            self._set_vrm_path(path)

    def _on_drop_rejected(self) -> None:
        """OnDragDrop() L.1411-1415相当(拡張子不一致時のMessageBox)。"""
        messagebox.showinfo(i18n.S("TitleConfirm"), i18n.S("MsgDropVrmOrPrefab"))

    def _on_fbx_gui_rejected(self) -> None:
        """dev#1124(dev#684/dev#758の続き): 生FBXのGUI入力拒否(2026-08-01
        オーナー裁定「入るのがおかしい」)。ダイアログ/D&Dのどちらで.fbxが
        選ばれても、この専用案内を出す(_on_drop_rejectedの一般案内〈拡張子
        不一致〉とは別文言。内部エラー`humanoid.json not found. FBX input
        requires a bone mapping table.`をユーザーに見せない、が本WPの主眼、
        dev#1124本文参照)。"""
        messagebox.showinfo(i18n.S("TitleConfirm"), i18n.S("MsgFbxGuiUnsupportedBody"))

    # -- pak管理系(WP-A4、DESIGN.md §2.3、pak_manager.pyとの結線) --------------
    #
    # dev#23監査で発見: 旧 _work_root() は「WP-A6実装後に差し替え予定」の
    # 暫定スタブとして常に os.path.join(self.app_root, "work") を返していたが、
    # A6(path_health.py、self.work_root = self._resolve_work_root())は既に
    # 完了済みで、appRoot\\work が書き込み不可の環境では %LOCALAPPDATA%\\Uchinoko\\work
    # へフォールバックする(__init__ L.175)。旧スタブを使い続けていた
    # pak一覧/削除/warm_startup系の4箇所は、フォールバックが発動した場合に
    # 実際にpakが書かれた場所(self.work_root)ではなく常にappRoot\\workだけを見て
    # おり、ビルド済みpakが一覧に出ない・削除できない、という「解決済みのはずが
    # 一部の呼び出し元だけ迂回する」欠落だった(CLAUDE.md「外部依存パスの原則」の
    # ②が一部経路で無効化されていたケース、dev#229と同型)。self.work_root
    # (常に最新の解決結果を保持する属性)を直接使うことで解消する。

    def _ask_paks_dir_manual(self) -> str | None:
        """PaksDir()の手動指定フォールバック(FolderBrowserDialog相当、L.3096-3113)。
        pak_manager.resolve_paks_dir()へ注入するコールバック(pak_manager.py自体は
        tkinterに依存しない設計、DESIGN.md §5.2)。"""
        from tkinter import filedialog

        chosen = filedialog.askdirectory(title=i18n.S("DlgDescPaksFolder"))
        return chosen or None

    def _on_paks_dir_invalid(self, chosen_path: str) -> None:
        """選んだフォルダに本体pak(候補いずれか)が無かった場合の案内
        (L.3110-3112、無言で受理しない=WP16の踏襲)。dev#229続報:
        Steam版のPal-Windows.pak単独名から、pak_manager.PAK_FILENAME_CANDIDATES
        (Xbox App版のPal-WinGDK.pakを含む)の一覧表示へ変更。"""
        from tkinter import messagebox

        candidates_str = "/".join(pak_manager.PAK_FILENAME_CANDIDATES)
        messagebox.showwarning(
            i18n.S("TitlePalworldNotFound"),
            i18n.F("MsgPaksNotFoundFormat", candidates_str, chosen_path),
        )

    def _resolve_paks_dir_interactive(self) -> str | None:
        """PaksDir()(L.3078-3115)相当。自動発見に失敗すればダイアログを出す。
        ApplySelected/RemoveAppliedのように「ユーザー操作の起点」でだけ呼ぶ
        (受動的な一覧更新ではpaks_dir_quiet系を使い、ダイアログを出さない)。"""
        result = pak_manager.resolve_paks_dir(
            self.app_root,
            cache=self._paks_dir_cache,
            ask_manual=self._ask_paks_dir_manual,
            on_invalid=self._on_paks_dir_invalid,
            log=self._log,
        )
        if result:
            self._paks_dir_cache = result
        return result

    def _classify_apply_failure(self, ex: Exception) -> tuple[str, str]:
        """ShowApplyFailure(L.3754-3789)の原因分類部分の移植(cause, action)。
        WinAPIのERROR_DISK_FULL(112)/ERROR_HANDLE_DISK_FULL(39)はOSErrorの
        winerror属性で判定する(C#のHResult判定と同じ発想)。"""
        if isinstance(ex, PermissionError):
            return i18n.S("CauseNoWritePermission"), i18n.S("ActionNoWritePermission")
        if getattr(ex, "winerror", None) in (112, 39):
            return i18n.S("CauseDiskFull"), i18n.S("ActionDiskFull")
        if isinstance(ex, (FileNotFoundError, NotADirectoryError)):
            return i18n.S("CauseTargetFolderNotFound"), i18n.S("ActionTargetFolderNotFound")
        if isinstance(ex, OSError):
            return i18n.S("CauseFileInUse"), i18n.S("ActionFileInUse")
        return i18n.S("CauseUnexpected"), i18n.S("ActionUnexpected")

    def _show_apply_failure(self, action_label: str, target_path: str, ex: Exception) -> None:
        from tkinter import messagebox

        cause, action = self._classify_apply_failure(ex)
        self._log(f"[Error] {action_label} failed: {target_path} / [{type(ex).__name__}] {ex}")
        messagebox.showerror(
            i18n.F("MsgApplyFailureTitleFormat", action_label),
            i18n.F("MsgApplyFailureBodyFormat", action_label, cause, action, target_path),
        )
        # dev#138: 主要なエラーパスの1つ(pak適用失敗)。原因/対処は上の
        # showerrorで既に伝えた(繰り返さない)ので、ここでは短い題名だけを
        # 次アクション導線へ渡す。
        self._offer_report_after_failure(i18n.F("MsgApplyFailureTitleFormat", action_label))

    def _show_delete_failure(self, job_dir: str, ex: OSError) -> None:
        """dev#1514: _on_delete_selected()のOSError分岐を抽出(単体テスト
        容易化+_show_apply_failure()と同型に揃える目的のみ、挙動は不変)。
        従来はstr(ex)(OSError生文字列、絶対パス込み)をそのままダイアログへ
        埋め込んでいた。_show_apply_failure()と同じ_classify_apply_failure()で
        分類済みi18n文言(cause)に差し替え、生例外はログ記録側にだけ残す
        (診断能力は落とさない。問い合わせボタンが添付するlaunch.log経由で
        引き続きサポートへ届く)。"""
        from tkinter import messagebox

        cause, _action = self._classify_apply_failure(ex)
        self._log(f"[Error] delete failed: {job_dir} / [{type(ex).__name__}] {ex}")
        messagebox.showerror(i18n.S("TitleConfirmDelete"), i18n.F("MsgDeleteFailedFormat", cause))

    def _on_refresh_pak_list(self) -> None:
        """RefreshPakList()(L.3648-3661)相当。

        dev#1311(多重防御): 全行delete→再構築のたびtreeviewの選択状態は
        必ず失われる。本メソッドを呼ぶ経路がどこであっても(将来増えても)
        選択が消えないよう、再構築前に選択中のpakパスを覚え、再構築後に
        同じpakパスの行が見つかればselection_set()で選択を復元する。
        根本原因(選択操作のたびに本メソッドが呼ばれていたこと)自体の
        是正は_refresh_lab_warning/lab_window.refresh側で行った——本メソッド
        側のこの防御は「どこから呼ばれても壊れない」ための保険。
        pak_list.selection()/selection_set()を持たない旧来の単体テスト用
        フェイク(test_main_window_pak_list_multi_avatar_mark_dev1170.py等)を
        壊さないよう、両メソッドともgetattrで存在確認してから使う。"""
        pak_list = self.widgets["pakList"]
        selection_fn = getattr(pak_list, "selection", None)
        previously_selected_paths: set[str] = set()
        if selection_fn is not None:
            previously_selected_paths = {
                self._pak_paths[iid] for iid in selection_fn() if iid in self._pak_paths
            }
        pak_list.delete(*pak_list.get_children())
        self._pak_paths.clear()
        self._pak_candidates = pak_manager.list_built_paks(self.work_root)
        restored_iids: list[str] = []
        for pak_path, avatar_name in self._pak_candidates:
            try:
                st = os.stat(pak_path)
                size_text = f"{st.st_size / 1048576.0:.1f} MB"
                created_text = time.strftime("%Y/%m/%d %H:%M", time.localtime(st.st_mtime))
            except OSError:
                size_text = ""
                created_text = ""
            # dev#1170 WP-5: マルチ品(合成PAK)の目印(pak_manager.
            # entry_is_multi_avatar()のdocstring「配線は将来WPで1行差すだけ」を
            # そのまま実行。job_dir = dirname(dirname(pak_path))は
            # _on_pak_list_selected()と同じ計算)。
            job_dir = os.path.dirname(os.path.dirname(pak_path))
            display_name = avatar_name
            if pak_manager.entry_is_multi_avatar(job_dir):
                display_name = i18n.F("PakListMultiAvatarMarkFormat", avatar_name)
            iid = pak_list.insert(
                "", "end",
                values=(display_name, os.path.basename(pak_path), size_text, created_text),
            )
            self._pak_paths[iid] = pak_path
            if pak_path in previously_selected_paths:
                restored_iids.append(iid)
        if restored_iids:
            selection_set_fn = getattr(pak_list, "selection_set", None)
            if selection_set_fn is not None:
                selection_set_fn(restored_iids)
        self._on_update_applied_status()

    def _on_pak_list_selected(self, _event=None) -> None:
        """PakListSelectedIndexChanged(pakList.SelectedIndexChanged、
        DiveToPalworld.cs L.1126-1137)相当(dev#605)。一覧から過去に変換した
        アバターの行を選ぶと、そのjob.jsonの設定・プレビュー画像を画面へ
        復元する(dev#616 A+I相当の復元処理を_apply_restored_settingsへ
        共通化して使う)。jobDir = dirname(dirname(pak))はC#版と同じ
        (pakは<jobDir>\\build\\*.pak、L.1134/pak_manager.resolve_delete_targets
        と同じ計算)。C#版はpy版に無い非同期アバター読み込み(SetVrmの
        バックグラウンド処理)の取り消し(CancelAvatarLoad、L.1132)も行うが、
        py版の_set_vrm_pathは同期実装で該当する保留読み込みが存在しないため
        対象外(モジュール内に類似の世代カウンタが無いことをgrepで確認済み)。"""
        pak_list = self.widgets["pakList"]
        selection = pak_list.selection()
        if not selection:
            return
        iid = selection[0]
        pak_path = self._pak_paths.get(iid)
        if not pak_path:
            return
        job_dir = os.path.dirname(os.path.dirname(pak_path))
        # LoadPreviews(jd)(L.1135)相当: job.jsonの有無に関わらずまず
        # プレビューを試みる(C#版は無条件呼び出し。job.json不在時の
        # 二重読み込みは_apply_restored_settings内部でも安全に空振りする)。
        try:
            self._apply_previews(pipeline_runner.load_previews(job_dir))
        except Exception as ex:  # noqa: BLE001 -- プレビュー表示の失敗で選択操作自体を壊さない
            self._log(f"[preview] pak list selection preview load failed: {ex}")
        # RestoreSettings(Path.Combine(jd, "job.json"), true)(L.1136)相当。
        self._apply_restored_settings(job_dir, set_vrm_path=True)

    def _set_status(self, render: Callable[[], str]) -> None:
        """statusLabelの文言を設定する(dev#897)。i18n.register()の登録簿は
        「静的ラベルをkey1つで再翻訳する」設計だが、statusLabelは呼び出し
        ごとに前提(直前に適用/削除したアバター名、進捗%等)が異なる動的文言
        しか出さないため、この仕組みでは表現できない(dev#596のコメント
        どおり)。代わりに「今の言語で文言を組み立て直す関数」そのものを
        _last_status_renderへ覚えておき、_on_language_selected()が言語切替の
        たびにこれを呼び直すことで、直書きのconfig(text=...)と同じ呼び出し
        感覚のまま再翻訳可能にする。"""
        self._last_status_render = render
        self.widgets["statusLabel"].config(text=render())

    def _on_update_applied_status(self) -> None:
        """UpdateAppliedStatus()(L.3669-3724)相当。ファイルの有無まではUIスレッドで
        即座に確定させ、時間のかかるSHA1照合だけをバックグラウンドスレッドへ出す
        (元の設計方針をそのまま踏襲、L.3665-3668のコメント参照)。"""
        self._applied_status_gen += 1
        gen = self._applied_status_gen
        applied_label = self.widgets["appliedLabel"]
        remove_button = self.widgets["removeButton"]

        paks_dir = pak_manager.paks_dir_quiet(
            self.app_root, cache=self._paks_dir_cache, log=self._log
        )
        if paks_dir is None:
            applied_label.config(text=i18n.S("AppliedStatusNoPaksDir"))
            remove_button.config(state="disabled")
            return
        self._paks_dir_cache = paks_dir

        status = pak_manager.resolve_applied_target(paks_dir)
        remove_button.config(state=("normal" if status["remove_enabled"] else "disabled"))
        if not status["exists"]:
            applied_label.config(text=i18n.S("AppliedStatusNone"))
            return

        target = status["target"]
        try:
            target_len = os.path.getsize(target)
        except OSError:
            applied_label.config(text=i18n.S("AppliedStatusUnknownMod"))
            return

        applied_label.config(text=i18n.S("AppliedStatusChecking"))
        candidates = list(self._pak_candidates)

        def worker() -> None:
            try:
                name = pak_manager.identify_applied_pak(target, target_len, candidates)
            except Exception as ex:  # noqa: BLE001 -- 照合失敗を握りつぶさず見せる(L.3702-3713)
                def on_fail() -> None:
                    if gen != self._applied_status_gen:
                        return
                    applied_label.config(text=i18n.S("AppliedStatusCheckFailed"))
                    self._log(f"[Error] failed to check applied MOD: {ex}")

                self.root.after(0, on_fail)
                return

            def on_done() -> None:
                if gen != self._applied_status_gen:
                    return
                applied_label.config(
                    text=i18n.F("AppliedStatusNamedFormat", name)
                    if name is not None
                    else i18n.S("AppliedStatusUnknownMod")
                )

            self.root.after(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _resolve_completed_pak_path(self, job_dir: str) -> str | None:
        """OnPipelineDone() L.2924-2936のうち、完成pakの特定部分のみの移植
        (アバター名=Path.GetFileName(jobDir)相当、C#版はここで一覧のListViewItemを
        自動選択するが、dev#606では一覧UI(dev#601領分)に触れない最小経路とする
        ため、pak_manager.list_built_paks(work_root)を直接照合してパスだけを返す)。
        見つからなければNone。"""
        avatar = os.path.basename(job_dir)
        for pak_path, avatar_name in pak_manager.list_built_paks(self.work_root):
            if avatar_name == avatar:
                return pak_path
        return None

    def _apply_pak_path(self, src: str, avatar_name: str) -> bool:
        """ApplySelected()(L.3791-3827)の中核(ゲーム起動中警告・paksDir解決・
        コピー・失敗時ダイアログ・成功時ステータス/メッセージ)。一覧UI(pakList
        selection)に依存しない直接適用経路として dev#606(自動適用、
        _on_pipeline_exit)と手動の「Palworldに適用」ボタン(_on_apply_selected)の
        双方から共用する(二重実装しない、指示書の明示要求)。戻り値: 適用成功可否。"""
        from tkinter import messagebox

        if not src or not os.path.isfile(src):
            messagebox.showwarning(i18n.S("LabelApply"), i18n.F("MsgModFileNotFoundFormat", src or ""))
            return False
        if pak_manager.is_game_running():
            messagebox.showwarning(i18n.S("LabelApply"), i18n.S("MsgGameRunningApply"))
            return False
        paks_dir = self._resolve_paks_dir_interactive()
        if paks_dir is None:
            return False
        try:
            pak_manager.apply_pak(paks_dir, src)
        except Exception as ex:  # noqa: BLE001 -- ShowApplyFailure相当で分類して見せる
            self._show_apply_failure(
                i18n.S("LabelApply"), os.path.join(paks_dir, pak_manager.INSTALL_NAME), ex
            )
            return False
        # dev#1320: 適用自体(コピー)はここまでで既に成功している。以下の
        # appliedLabel/statusLabelの更新は付随的な状態表示に過ぎず、その
        # 更新中に何らかの理由(進行中の言語切替によるUI再構築など、
        # multi_avatar_pak_dialog.pyで確認した機序と同種)で例外が起きても、
        # ユーザーへの成功通知(messagebox)まで巻き込んで消してはならない
        # (issue #1320 追記実測: 適用は成功していたのに完了表示だけが
        # 出なかった)。各更新を個別に保護し、通知は必ず届ける。
        try:
            self._on_update_applied_status()
        except Exception as ex:  # noqa: BLE001 -- appliedLabel更新の失敗で通知を止めない
            self._log(f"[apply] appliedLabel update failed (non-fatal): {ex}")
        try:
            self._set_status(lambda: i18n.F("StatusAppliedFormat", avatar_name))
        except Exception as ex:  # noqa: BLE001 -- statusLabel更新の失敗で通知を止めない
            self._log(f"[apply] statusLabel update failed (non-fatal): {ex}")
        messagebox.showinfo(i18n.S("TitleApplySuccess"), i18n.F("MsgApplySuccessFormat", avatar_name))
        return True

    def _apply_pak_path_silent(self, src: str, avatar_name: str) -> bool:
        """dev#1328: マルチアバターPAK作成(ラボ機能、ui\\multi_avatar_pak_dialog.py)
        からの自動適用専用コア。_apply_pak_path()と同じpak_manager系の適用機構
        (ゲーム起動中判定・paksDir解決・pak_manager.apply_pak())を再利用するが
        (「手でコピーしない」指示どおり、pak_manager.apply_pak()を呼ぶ経路のみ)、
        呼び出し元が「作成しました」「作成しましたが適用に失敗しました」という
        1個の統合済みメッセージだけを出す設計のため、ここでは警告/エラー/成功の
        messageboxを一切出さない(詳細はログにのみ記録し、失敗時の統合メッセージが
        「ログを確認してください」と案内する)。appliedLabel/statusLabelの更新は
        付随的な状態表示であり、失敗しても適用成否の戻り値は変えない(dev#1320で
        _apply_pak_path()に入った保護と同じ考え方)。戻り値: 適用成功可否。"""
        if not src or not os.path.isfile(src):
            self._log(f"[lab][multi_avatar_pak][apply] pak file not found: {src}")
            return False
        if pak_manager.is_game_running():
            self._log("[lab][multi_avatar_pak][apply] skipped, game is running")
            return False
        paks_dir = self._resolve_paks_dir_interactive()
        if paks_dir is None:
            self._log("[lab][multi_avatar_pak][apply] skipped, paks dir not resolved")
            return False
        try:
            pak_manager.apply_pak(paks_dir, src)
        except Exception as ex:  # noqa: BLE001 -- 詳細はログのみ(統合メッセージが「ログを確認」と案内する)
            self._log(f"[lab][multi_avatar_pak][apply] failed: [{type(ex).__name__}] {ex}")
            return False
        try:
            self._on_update_applied_status()
        except Exception as ex:  # noqa: BLE001 -- appliedLabel更新の失敗で適用成否を変えない
            self._log(f"[lab][multi_avatar_pak][apply] appliedLabel update failed (non-fatal): {ex}")
        try:
            self._set_status(lambda: i18n.F("StatusAppliedFormat", avatar_name))
        except Exception as ex:  # noqa: BLE001 -- statusLabel更新の失敗で適用成否を変えない
            self._log(f"[lab][multi_avatar_pak][apply] statusLabel update failed (non-fatal): {ex}")
        self._log(f"[lab][multi_avatar_pak][apply] succeeded: {avatar_name}")
        return True

    def _on_apply_selected(self) -> None:
        """ApplySelected()(L.3791-3827)相当。中核処理は_apply_pak_pathへ委譲
        (dev#606で自動適用と共用するため抽出、合理的解釈: 元の呼び出し順序のうち
        ゲーム起動中判定/paksDir解決は共通コアの先頭へ移動したため、pak未検出時の
        警告より後になる。ユーザー可視の分岐・文言は変えていない)。"""
        from tkinter import messagebox

        pak_list = self.widgets["pakList"]
        selection = pak_list.selection()
        if not selection:
            messagebox.showinfo(i18n.S("TitleApplySuccess"), i18n.S("MsgSelectModFromList"))
            return
        iid = selection[0]
        src = self._pak_paths.get(iid)
        avatar_name = pak_list.item(iid, "values")[0]
        if not src or not os.path.isfile(src):
            messagebox.showwarning(i18n.S("LabelApply"), i18n.F("MsgModFileNotFoundFormat", src or ""))
            self._on_refresh_pak_list()
            return
        self._apply_pak_path(src, avatar_name)

    def _on_remove_applied(self) -> None:
        """RemoveApplied()(L.4778-4812)相当。"""
        from tkinter import messagebox

        if pak_manager.is_game_running():
            messagebox.showwarning(i18n.S("LabelRemove"), i18n.S("MsgGameRunningRemove"))
            return
        paks_dir = self._resolve_paks_dir_interactive()
        if paks_dir is None:
            return
        try:
            removed = pak_manager.remove_applied(paks_dir)
        except Exception as ex:  # noqa: BLE001
            self._show_apply_failure(
                i18n.S("LabelRemove"), os.path.join(paks_dir, pak_manager.INSTALL_NAME), ex
            )
            return
        if not removed:
            self._set_status(lambda: i18n.S("StatusNoModApplied"))
            self._on_update_applied_status()
            return
        self._on_update_applied_status()
        self._set_status(lambda: i18n.S("StatusModRemoved"))

    def _on_delete_selected(self) -> None:
        """DeleteSelected()(L.3829-3903)相当。"""
        from tkinter import messagebox

        pak_list = self.widgets["pakList"]
        selection = pak_list.selection()
        if not selection:
            return
        iid = selection[0]
        pak_path = self._pak_paths.get(iid)
        avatar_name = pak_list.item(iid, "values")[0]
        if not pak_path:
            return

        targets = pak_manager.resolve_delete_targets(self.work_root, self.app_root, pak_path)

        lines = [
            i18n.F("ConfirmDeleteHeaderFormat", avatar_name),
            "",
            i18n.F("LineModFileFormat", os.path.basename(pak_path)),
            i18n.F("LineWorkFolderFormat", targets["job_dir"]),
        ]
        if targets["ue_project_dir"] and os.path.isdir(targets["ue_project_dir"]):
            lines.append(i18n.F("LineUeProjectFormat", targets["ue_project_dir"]))
        lines.append("")
        lines.append(i18n.S("NoteVrmNotDeleted"))
        lines.append(i18n.S("NoteReloadVrmToRedo"))

        if not messagebox.askyesno(i18n.S("TitleConfirmDelete"), "\n".join(lines)):
            return

        try:
            pak_manager.delete_avatar_artifacts(targets["job_dir"], targets["ue_project_dir"])
        except OSError as ex:
            self._show_delete_failure(targets["job_dir"], ex)

        # 「最後に開いたVRM」の記憶が削除対象と同じなら忘れる(残すと次回起動時に
        # 勝手に読み込んで作業フォルダが復活してしまう、L.3878-3890)
        last_vrm = settings.load_last_vrm(self.app_root)
        if last_vrm and pak_manager.sanitize_name(
            os.path.splitext(os.path.basename(last_vrm))[0]
        ) == avatar_name:
            try:
                os.remove(settings.lastvrm_file(self.app_root))
            except OSError:
                pass

        # 削除したのが今開いているアバターなら表示も初期化する(L.3891-3899)
        current_text = self.widgets["vrmBox"].get().strip()
        if current_text and pak_manager.sanitize_name(
            os.path.splitext(os.path.basename(current_text))[0]
        ) == avatar_name:
            self.widgets["vrmBox"].delete(0, tk.END)
            # dev#599: previewFront/previewSideに実画像が表示されている場合、
            # text=だけ書き換えても画像が残って見える(Labelはcompound=none既定で
            # imageがtextより優先表示されるため)。image=""で明示的に外し、
            # 保持していたPhotoImage参照も破棄する(L.3896-3897 previewFront.Image
            # = null相当)。
            self._preview_images.pop("previewFront", None)
            self._preview_images.pop("previewSide", None)
            self.widgets["previewFront"].config(
                image="", text=i18n.S("LabelPreviewPlaceholderFront")
            )
            self.widgets["previewSide"].config(
                image="", text=i18n.S("LabelPreviewPlaceholderSide")
            )

        self._on_refresh_pak_list()
        self._set_status(lambda: i18n.F("StatusDeletedFormat", avatar_name))

    def _on_toggle_kodawari(self) -> None:
        self._kodawari_open = not self._kodawari_open
        toggle_btn = self.widgets["kodawariToggle"]
        arrow = "▲" if self._kodawari_open else "▼"
        toggle_btn.config(text=f"{arrow} {i18n.S('LabelKodawari')}")
        if self._kodawari_open:
            self._kodawari_panel.place(
                x=12, y=118, width=1058, height=_KODAWARI_PANEL_HEIGHT
            )
        else:
            self._kodawari_panel.place_forget()
        self.layout_content_area()

    def _on_language_selected(self, _event=None) -> None:
        idx = i18n.LANG_DISPLAY_NAMES.index(self._lang_combo.get())
        new_lang = i18n.LANGS[idx]
        i18n.apply_language(new_lang)
        settings.save_language_code(self.app_root, i18n.FILE_LANG_CODES[new_lang])
        self._update_window_title()
        pak_list = self.widgets["pakList"]
        for col_id, key in self._pak_list_columns.items():
            pak_list.heading(col_id, text=i18n.S(key))
        toggle_btn = self.widgets["kodawariToggle"]
        arrow = "▲" if self._kodawari_open else "▼"
        toggle_btn.config(text=f"{arrow} {i18n.S('LabelKodawari')}")
        # dev#596: appliedLabel(「適用中: ...」)はi18n.register()の自動再適用
        # registryに載っていない(状態(未確認/なし/内容不明/名前判明)に応じて
        # 都度動的に選ぶ複数キーのため、単一key登録では表現できない)。
        # 言語切替時に再計算しないと、切替前の言語で表示されたテキストが
        # そのまま残り続ける(例: 日本語表示中に検出された「適用中: 内容不明の
        # MODが入っています」が、英語へ切り替えても英訳に更新されない)。
        # 旧DiveToPalworld.cs ApplyLanguage() (L.874-901) がUpdateAppliedStatus()
        # を呼んでいたのと同じ配線を、Python移植で復元する。
        self._on_update_applied_status()
        # dev#897: statusLabel(「適用しました: X」等)も同じ理由で
        # i18n.register()の対象外(呼び出しごとに前提が異なる動的文言のため)。
        # _set_status()経由で最後に設定された分だけ、直近のレンダラで
        # 現在言語に組み直す(何も表示されていない起動直後はNoneのまま無視)。
        if self._last_status_render is not None:
            self.widgets["statusLabel"].config(text=self._last_status_render())
        # dev#897同類: updateLabel(「新しいバージョンがあります」等)も
        # _show_update_notice()が一度だけconfig(text=...)する動的文言で、
        # 表示中かどうかは_pending_update_version(None=非表示)で判定できる。
        if self._pending_update_version is not None:
            self.widgets["updateLabel"].config(
                text=i18n.F("UpdateNoticeFormat", self._pending_update_version)
            )
        # dev#1156: verifiedVersionLabel(「動作確認済みパルワールド: X」)も
        # statusLabel/updateLabel同様、_register_text()の自動再適用registryに
        # 未登録の動的組み立て文言(_verified_version_display_text()参照)。
        # _refresh_verified_version_label()は__init__直後と配信版チェック完了後
        # の2箇所でしか呼ばれておらず、言語切替時には再計算されないまま
        # 切替前の言語で表示され続けていた(オーナー実操作報告2026-08-07夜)。
        # statusLabel/updateLabelと同じ配線に揃え、言語切替のたびに
        # 現在言語で組み直す。
        self._refresh_verified_version_label()

    # -- WP-A2: 変換系ハンドラ(pipeline_runner.py配線) ------------------------
    #
    # 非同期方式はDESIGN.md §4.3どおり: pipeline_runner.ProcessHandleが
    # threading.Thread+queue.Queueで子プロセスの出力を受け取り、ここでは
    # root.after()で定期的にhandle.poll()を呼ぶ(tkinterはメインスレッド以外
    # からのウィジェット操作を許さないため、on_line/on_exitコールバックは
    # poll()を呼んでいるスレッド=メインスレッド上で実行される)。

    _POLL_INTERVAL_MS = 80

    def _on_full_convert(self) -> None:
        self._start_pipeline(preview_only=False, materials_only=False)

    def _on_materials_only(self) -> None:
        self._start_pipeline(preview_only=False, materials_only=True)

    def _on_preview_only(self) -> None:
        self._start_pipeline(preview_only=True, materials_only=False)

    def _ensure_license_confirmed(self) -> bool:
        """EnsureLicenseConfirmed() L.2533-2545相当。"""
        if self._license_confirmed:
            return True
        yes = messagebox.askyesno(i18n.S("TitleLicenseConfirm"), i18n.S("MsgLicenseConfirmBody"))
        if yes:
            self._license_confirmed = True
            return True
        return False

    def _ensure_palworld_located(self) -> bool:
        """変換開始(Phase 0: バニラ参照データ準備)が必要とするPalworld本体パスを、
        パイプライン起動前に解決しておく(dev#229第2次問い合わせ掃引・実報告5件:
        D522GGSF/GMLCCCDJ/MPQBWHXS/KRFU5DVL/KTU5A3BQ、いずれも既定Steamパス以外の
        環境で自動発見が失敗し、手動指定への誘導が一切無いまま同一エラーで
        数回リトライして離脱していた)。

        CLAUDE.md「外部依存パスの原則」の三点セット(①自動発見→②失敗時の手動指定
        UI+設定保存→③探索ログ)自体は`pak_manager.resolve_paks_dir()`に既に実装
        済みで、Apply/Remove(_resolve_paks_dir_interactive())は正しく配線されて
        いた。しかし変換開始(Start Conversion)経路だけは`pipeline_runner.
        write_job()`→`paks_dir_quiet()`という**ダイアログを出さない静かな版**しか
        呼んでおらず、自動発見が失敗すると手動指定の機会を一度も与えられないまま
        job.jsonへ`paths.palworld_pak`が省略され、Phase 0が
        `PalworldNotFoundError`でFATAL終了していた(=②が変換開始経路にだけ
        配線されていなかった欠落。dev#229/EXTERNAL_PATH_AUDIT_20260802.mdが
        「充足」と判定したのはApply/Remove経路のみで、この経路は監査対象に
        含まれていなかった)。

        既存の`_resolve_paks_dir_interactive()`(Apply/Removeと共用)をそのまま
        再利用する: Palworld本体のPaksフォルダ(本体pakの置き場)は、変換後に
        Modを適用する先と同一ディレクトリのため、解決結果は
        `settings_paksdir.txt`を介して共有され、直後の`write_job()`内部の
        `paks_dir_quiet()`がそのまま拾う(二重実装しない)。自動発見が成功する
        既存ユーザーには何の変化もない(ダイアログはまだ解決していない場合にのみ
        出る)。手動指定をキャンセルした場合はFalseを返し、呼び出し元
        `_start_pipeline()`は変換を開始しない。"""
        return self._resolve_paks_dir_interactive() is not None

    def _start_pipeline(
        self, *, preview_only: bool, materials_only: bool, auto: bool = False
    ) -> None:
        """RunPipeline() L.2547-2607相当。auto=Trueはdev#611のアバター登録時
        自動プレビュー起動(C#版 RunPipeline(previewOnly, materialsOnly, auto)の
        第3引数相当)。C#版はauto時、二重起動中/ファイル未指定の案内ダイアログも
        出さず黙って見送る(L.2549-2550の `if (!auto) MessageBox.Show(...)`)ため、
        ここでも同様にauto時はダイアログを抑止する(dev#229続報: Palworld本体の
        手動指定ダイアログも同じ理由でauto時は抑止し、既存のauto-preview挙動を
        変えない。auto時に未解決なら従来どおりPhase 0側のFATALで検出される)。
        dev#1394: 「Phase 0側のFATALで検出される」で止まり、そこから先の
        手動指定への導線が無かった欠落は、_on_pipeline_exit()のcode!=0分岐
        (fatal_code==pipeline_runner.PALWORLD_NOT_FOUND_FATAL_CODE)で
        _resolve_paks_dir_interactive()を直接呼ぶ形で解消済み(ここ=事前
        チェック側は無変更)。"""
        if self._active_handle is not None and self._active_handle.is_running():
            if not auto:
                messagebox.showinfo(i18n.S("TitleConfirm"), i18n.S("MsgAlreadyRunning"))
            return
        vrm_path = self.widgets["vrmBox"].get().strip()
        if not os.path.isfile(vrm_path):
            if not auto:
                messagebox.showinfo(i18n.S("TitleConfirm"), i18n.S("MsgSpecifyVrmFile"))
            return
        # MODを作る操作(プレビュー以外)はアバター規約の確認が要る(L.2552相当)。
        # auto経由は常にpreview_only=True(呼び出し元_maybe_auto_preview参照)
        # なのでここには実質来ないが、C#版の分岐順序をそのまま踏襲する。
        if not preview_only and not self._ensure_license_confirmed():
            return
        # dev#229続報: Phase 0はpreview_only/materials_onlyに関わらず常に走る
        # (convert.ps1のPhase 0はPreviewOnly分岐より前)ため、全モード共通で
        # ここに置く。autoは上記どおりダイアログ抑止のため対象外。
        if not auto and not self._ensure_palworld_located():
            return

        # silentPreview = auto; (L.2556相当)
        self._silent_preview = auto
        self._pipeline_warnings = []
        self._pipeline_fatal_cause = None
        self._user_cancelled_current_run = False
        self._early_preview_loaded_this_run = False
        # dev#137: ETA推定用のrun状態をここでリセットする(モード別に履歴を
        # 分離するため、開始時点でモードを確定させる。progress_eta.py参照)。
        self._eta_mode = progress_eta.resolve_mode(preview_only, materials_only)
        self._eta_run_started_at = time.monotonic()
        self._eta_checkpoints = []
        self._clear_log()
        self._set_running_ui_state(True)
        self._set_status(
            lambda: i18n.S("StatusPreviewGenerating") if preview_only
            else i18n.S("StatusMaterialsApplying") if materials_only
            else i18n.S("StatusFullConverting")
        )
        self._maybe_log_warm_cache_first_run_notice()

        drop_bones_text = self.widgets["dropBonesBox"].get()
        shadow_value = int(float(self.widgets["shadowBar"].get()))
        # dev#560 第③段: heightScaleBarは50〜200(%)の整数を持つ。job.jsonの
        # `uniform_scale`は0.5〜2.0のfloatなので/100.0して渡す。write_job()
        # 側でも重ねて0.5〜2.0へクランプする(多重防御)。
        uniform_scale = float(self.widgets["heightScaleBar"].get()) / 100.0
        # dev#1572(2026-08-18裁定、案C): swayIntensityBarの選択index
        # (既定index=_SWAY_INTENSITY_DEFAULT_INDEX="normal")をjob設定キー
        # 用の内部値へ変換して渡す。範囲外(-1、未初期化のフェイクself等)は
        # 安全側の"none"へ倒す。
        sway_idx = int(self.widgets["swayIntensityBar"].get())
        sway_intensity = (
            SWAY_INTENSITY_VALUES[sway_idx]
            if 0 <= sway_idx < len(SWAY_INTENSITY_VALUES) else "none"
        )
        self._active_handle = pipeline_runner.run_pipeline(
            self.app_root, self.work_root, vrm_path,
            preview_only=preview_only, materials_only=materials_only,
            on_line=self._on_pipeline_line,
            on_exit=lambda code: self._on_pipeline_exit(code, preview_only),
            shoulder_offset_deg=self._shoulder_offset_deg,
            merge_fingers=self._merge_fingers,
            unlit=self._unlit,
            force_two_sided=self._force_two_sided,
            shadow_bar_value=shadow_value,
            drop_bones_text=drop_bones_text,
            license_confirmed=self._license_confirmed,
            uniform_scale=uniform_scale,
            sway_intensity=sway_intensity,
            # dev#1242申し送り②: find_pwsh()の探索ログをログ欄(self._log、
            # 「ログをコピー」に載る経路)へ結線する。_start_pipeline()は
            # ボタンハンドラから直接呼ばれる主スレッド実行のため、tkウィジェットに
            # 触れるself._logを直接渡してよい(pak_manager.resolve_paks_dir()の
            # log=self._log と同じ既存パターン)。
            log=self._log,
        )
        self.root.after(self._POLL_INTERVAL_MS, self._poll_active_handle)

    def _on_cancel_convert(self) -> None:
        """cancelButton.Click L.997-1003相当。"""
        if self._active_handle is None or not self._active_handle.is_running():
            return
        if messagebox.askyesno(i18n.S("TitleConfirm"), i18n.S("ConfirmCancelConvertBody")):
            # dev#138: ユーザー自身が中止を選んだ実行は「失敗」ではないため、
            # _on_pipeline_exit()側の次アクション導線(問い合わせ勧誘)を
            # 抑止する(中止確認は直前でYes/Noを既に取っており、直後に
            # 「問い合わせますか」と重ねて聞くのは二重確認で不適切)。
            self._user_cancelled_current_run = True
            self._active_handle.kill()

    def _on_form_closing(self) -> None:
        """FormClosing(DiveToPalworld.cs L.1292-1305)相当。dev#622:
        WM_DELETE_WINDOW(×ボタン/Alt+F4等)ハンドラとして__init__で登録される。

        dev#640統合(PR #647): C#と同じ順序で、まず
        KillBlenderSetupProcess()(L.1298、Blenderのバックグラウンド初回
        取得プロセスを孤児化させないためのサイレントkill)を**確認無し・
        無条件**で呼ぶ(L.1294-1297のコメントどおり、ユーザーが明示的に
        始めた作業ではない裏方処理のため確認しない。runningProcの有無に
        かかわらず先頭で必ず実行、C#のFormClosingデリゲート本体と同じ順序)。
        `blender_setup.BlenderSetupProcessHandle.kill()`は実行中でなければ
        no-op(dev#640、blender_setup.py参照)。

        続いて変換(またはUnity輸出)がpipeline_runner経由で実行中の場合のみ、
        C#と同じ確認ダイアログ(ConfirmExitWhileRunningBody/TitleConfirm、
        YesNo)を出す(dev#622)。Noならウィンドウを閉じない(`e.Cancel = true`
        相当、ここでは単に何もせず戻ることで同じ効果になる)。Yesなら
        KillConversion()相当(handle.kill()、taskkill /T /Fでプロセス
        ツリーごと終了、pipeline_runner.ProcessHandle.kill()参照)を呼んでから
        ウィンドウを破棄する。"""
        self._blender_setup_process_handle.kill()
        if self._active_handle is not None and self._active_handle.is_running():
            if not messagebox.askyesno(
                i18n.S("TitleConfirm"), i18n.S("ConfirmExitWhileRunningBody")
            ):
                return
            self._active_handle.kill()
        self.root.destroy()

    def _poll_active_handle(self) -> None:
        """dev#592層3(生存防御): handle.poll()がここで例外を出すと、以後
        self.root.after()による再スケジュールが行われずポーリングが恒久
        停止する(dev#592根本原因)。poll()自体はpipeline_runner側でも
        行単位try/exceptで守っているが(層3の本丸)、ここでも例外の有無に
        かかわらず再スケジュールを保証する二段構えにする。"""
        handle = self._active_handle
        if handle is None:
            return
        try:
            handle.poll()
        except Exception as ex:  # noqa: BLE001
            try:
                self._log(f"[poll] unexpected error: {ex}")
            except Exception:  # noqa: BLE001
                pass
        if handle.is_running():
            # dev#602追補: Unity輸出フェーズの無音解消。実プロセスからの
            # 出力が構造的に来ない工程(export_from_unity.ps1が子プロセスを
            # 同期ブロック呼び出し、Unity自体の出力は-logFileにのみ書かれ
            # stdoutへは一切出ない)なので、このポーリングループ自体を
            # タイマー代わりに使い、一定間隔で経過時間つきの合成メッセージを
            # 出す。実プロセスの成否判定(on_exit)には一切影響しない
            # (成功を主張する文言を含まない、負の対照)。
            if getattr(self, "_active_phase", None) == pipeline_runner.PHASE_UNITY_EXPORT:
                self._maybe_emit_unity_export_heartbeat()
            self.root.after(self._POLL_INTERVAL_MS, self._poll_active_handle)

    def _maybe_emit_unity_export_heartbeat(self) -> None:
        """Unity輸出フェーズ用ハートビート(dev#602追補)。最後に何か出力が
        あってから一定時間(pipeline_runner.UNITY_EXPORT_HEARTBEAT_INTERVAL_SEC)
        経っていれば、経過時間つきの合成メッセージをstatusLabelとログ欄へ
        出す。「実行中である」以上のことは主張しない(成功文言を含まない)。"""
        last = self._unity_export_last_output_at
        if last is None:
            return
        now = time.monotonic()
        if not pipeline_runner.should_emit_unity_export_heartbeat(now - last):
            return
        self._unity_export_last_output_at = now
        started = self._unity_export_started_at
        elapsed_str = pipeline_runner.format_elapsed_mmss(
            now - started if started is not None else 0.0
        )
        self._set_status(
            lambda: "{0} ({1})".format(
                i18n.S("StatusUnityExporting"),
                i18n.F("UnityExportElapsedSuffixFormat", elapsed_str),
            )
        )
        # dev#896: このログはlog_box表示に加えてprint()経由でconsole/launch.log
        # (サポート問い合わせで「ログをコピー」される診断ログ)にも出るため、
        # UI表示言語に関わらず常に英語で出す(dev#596で日本語直書きを退治した
        # あとも、i18n.F()が現在のUI言語をそのまま使っていたため、UI言語が
        # 日本語だと日本語のまま実行ログに混じっていた)。
        self._log(i18n.S("LogUnityExportHeartbeatFormat", lang="en").format(elapsed_str))

    def _record_eta_checkpoint_and_estimate(self, pct: int) -> Optional[float]:
        """dev#137: ##PROGRESS##到着ごとに今回runの(pct, 経過秒)を蓄積しつつ、
        progress_eta.estimate_remaining_seconds()へ渡してETA(秒)を得る。

        `_start_pipeline()`が設定するrun状態(_eta_run_started_at等)が無い
        呼び出し元(既存の単体テストのフェイクself等)でも安全に動くよう、
        getattrの既定値+broad try/exceptで守る(このETA機能自体の失敗で
        変換や進捗表示本体が壊れてはならない、という本プロジェクト全体の
        防御方針を踏襲。dev#592等と同じ考え方)。推定できない場合は必ず
        Noneを返す(呼び出し側は現行の%表示のままにする)。"""
        try:
            started_at = getattr(self, "_eta_run_started_at", None)
            if started_at is None:
                return None
            checkpoints = getattr(self, "_eta_checkpoints", None)
            if checkpoints is None:
                checkpoints = []
                self._eta_checkpoints = checkpoints
            elapsed = time.monotonic() - started_at
            checkpoints.append((pct, elapsed))
            app_root = getattr(self, "app_root", None)
            mode = getattr(self, "_eta_mode", None)
            if not app_root or not mode:
                return None
            history = progress_eta.load_history(app_root).get(mode, [])
            return progress_eta.estimate_remaining_seconds(history, pct, elapsed)
        except Exception:  # noqa: BLE001
            return None

    def _record_eta_run_on_success(self) -> None:
        """dev#137: 成功終了した今回runの区間到達記録を恒常履歴
        (progress_history.json、app_root直下)へ確定保存する。呼び出し元は
        `_on_pipeline_exit()`のcode==0分岐のみ(失敗/キャンセルされたrunは
        ETAの母集団に混ぜない)。run状態(_eta_run_started_at等)が無い場合
        (_start_pipeline()を経ていない呼び出し=既存の単体テスト等)は
        何もしない。"""
        started_at = getattr(self, "_eta_run_started_at", None)
        checkpoints = getattr(self, "_eta_checkpoints", None)
        mode = getattr(self, "_eta_mode", None)
        app_root = getattr(self, "app_root", None)
        if started_at is None or checkpoints is None or not mode or not app_root:
            return
        total_duration = time.monotonic() - started_at
        progress_eta.record_run(app_root, mode, checkpoints, total_duration)

    def _on_pipeline_line(self, line: str) -> None:
        """AppendLog() L.2838-2883相当。"""
        # dev#602追補: 実プロセスから何か行が来た=生存の証拠そのものなので、
        # Unity輸出フェーズのハートビート計測をここでリセットする(直後に
        # 重複した合成メッセージを出さないため)。
        if getattr(self, "_active_phase", None) == pipeline_runner.PHASE_UNITY_EXPORT:
            self._unity_export_last_output_at = time.monotonic()
        clean = pipeline_runner.strip_ansi(line)
        marker = pipeline_runner.parse_progress_marker(clean)
        if marker is not None:
            pct, raw_label = marker
            # dev#602: マーカー到着=実進捗が分かっている状態なので、indeterminate
            # (Unity輸出のMarquee相当)が残っていればここでdeterminateへ戻す。
            self._set_busy_bar_mode(pipeline_runner.busy_bar_mode_on_marker())
            self.widgets["busyBar"]["value"] = pct
            # dev#137: 既存の最小フェイクself(このメソッドを持たない単体
            # テストのfixture群)でも壊れないよう、メソッド自体の有無から
            # getattrで守る(_record_eta_checkpoint_and_estimate内部は
            # 呼べさえすれば自前で全部try/exceptしている)。
            eta_method = getattr(self, "_record_eta_checkpoint_and_estimate", None)
            eta_seconds = eta_method(pct) if eta_method is not None else None

            # dev#897: raw_label/pct/eta_seconds(いずれも言語非依存の生値)を
            # 覚えておき、言語切替のたびtranslate_progress_label_dynamic/
            # i18n.Fを呼び直せるようにする(str結合済みの完成文を覚えると、
            # 切替時に古い言語の文字列がそのまま返るだけで再翻訳にならない)。
            def render(raw_label=raw_label, pct=pct, eta_seconds=eta_seconds) -> str:
                label = pipeline_runner.translate_progress_label_dynamic(raw_label)
                text = f"{label}... ({pct}%)"
                if eta_seconds is not None:
                    text += " " + i18n.F(
                        "StatusEtaSuffixFormat",
                        pipeline_runner.format_elapsed_mmss(eta_seconds),
                    )
                return text

            self._set_status(render)
            # dev#288提案2(早期プレビュー反映、L.2854-2870相当)。dev#532方針A
            # WP-A11/dev#549で結線。1回だけ・失敗しても変換本体には影響させない
            # (try/exceptで握り、ログにだけ残す=「静かにログのみ」)。
            job_dir = self._active_handle.job_dir if self._active_handle else None
            if job_dir and pipeline_runner.should_load_early_preview(
                pct, self._early_preview_loaded_this_run
            ):
                self._early_preview_loaded_this_run = True
                try:
                    self._apply_previews(pipeline_runner.load_previews(job_dir))
                except Exception as ex:  # noqa: BLE001
                    self._log(f"[preview-early] load_previews failed at pct={pct}: {ex}")
            return
        warning = pipeline_runner.parse_avatar_warning(clean)
        if warning is not None:
            # dev#939 ②: ポップアップ(_pipeline_warnings→messagebox.showwarning)
            # にはtranslate_avatar_warning()で翻訳した文言を積む(未一致なら
            # 原文のままフォールバック)。ログ欄(下のself._log(clean))は診断
            # ログとして常に英語の生行を残す(問い合わせKFRHNTTKの教訓どおり、
            # 色診断に必要な原文情報を落とさない)。
            self._pipeline_warnings.append(pipeline_runner.translate_avatar_warning(warning))
            # dev#690: C#版(DiveToPalworld.cs L.2874-2879)はAvatarWarnMark一致後も
            # returnせずlogBox.AppendTextへ落ちる。旧py版はここでreturnしており、
            # ##AVATAR_WARNING##行がログ欄(=「ログをコピー」で送られる
            # _build_diagnostics_text()の材料)に一切残らなかった
            # (完了時messagebox.showwarningのポップアップにしか使われない)。
            # そのため色診断に必要な情報が問い合わせ経由で届かなかった
            # (問い合わせKFRHNTTK)。C#と同じくfall throughしてログにも残す。
        fatal_code = pipeline_runner.parse_avatar_fatal(clean)
        if fatal_code is None:
            # dev#1394: ##AVATAR_FATAL##マーカーを持たない「Palworld本体/pak
            # が見つからない」FATAL(pipeline\py側の書き込み許可範囲外のため
            # マーカーを追加できない、work\wp_1394_fallback\NOTES.md §1.4参照)
            # を、既存の固定診断文言の先頭一致でフォールバック検出する。
            fatal_code = pipeline_runner.parse_palworld_not_found_fatal(clean)
        if fatal_code is not None:
            # dev#1261: ##AVATAR_WARNING##と同じくfall throughしてログにも
            # 残す(診断ログから内部コードを落とさない)。生コードのまま
            # 保持し、_on_pipeline_exit()のcode!=0分岐で使用直前に翻訳する
            # (言語切替の再翻訳に対応するため。__init__側のコメント参照)。
            self._pipeline_fatal_cause = fatal_code
        self._log(clean)

    def _apply_previews(self, previews: dict[str, str | None]) -> None:
        """LoadPreviews() L.2957-2963相当の反映部分(dev#599で実画像表示に実装)。
        Pillow等の追加依存を使わず、Tk 8.6が標準で持つtk.PhotoImageのネイティブ
        PNGデコードのみで完結させる(同梱ランタイムres\\python_embedにPillowが
        無いため)。読み込み・表示に失敗した場合(ファイル無し・壊れPNG・Tk側の
        デコードエラー等)は例外を握り、従来どおりファイル名文字列表示へ
        フォールバックする(GUIを絶対に殺さない。dev#592の防御思想を踏襲)。

        dev#1103: 従来は`if front:`/`if side:`がNoneのとき例外もログも出さず
        素通りしており、「表示を試みて成功した」のか「そもそも試みなかった」
        のかがログから区別できなかった(実報告TFVNM33V)。呼び出しのたびに
        必ず1行、front/sideそれぞれの適用可否(no-opならその理由)を残す。
        個々の画像デコード成功/失敗の詳細ログは_set_preview_widget側が担う
        (このメソッドは「渡された前提=前段のload_previews()の解決結果」を
        適用したかどうかのサマリのみを担当)。"""
        front = previews.get("front")
        side = previews.get("side")
        if front:
            self._set_preview_widget("previewFront", front)
        else:
            self._log("[preview-apply] no-op front: load_previews resolved no file (front=None)")
        if side:
            self._set_preview_widget("previewSide", side)
        else:
            self._log("[preview-apply] no-op side: load_previews resolved no file (side=None)")
        self._log(f"[preview-apply] applied: front={bool(front)} side={bool(side)}")

    def _set_preview_widget(self, widget_key: str, image_path: str) -> None:
        """previewFront/previewSideの1枚分の表示を担当。成功時は画像を、
        失敗時はファイル名文字列(従来のプレースホルダ挙動)を表示する。"""
        widget = self.widgets[widget_key]
        try:
            max_width, max_height = self._preview_display_size(widget)
            photo = _load_scaled_preview_image(image_path, max_width, max_height)
            # dev#599: 参照をselfへ保持する(Tkの罠。ローカル変数だけだと
            # このメソッドを抜けた時点でGCされ画像が消える)。
            self._preview_images[widget_key] = photo
            widget.config(image=photo, text="")
            # dev#1103: 成功時にも読んだファイルパスを残す(従来は失敗時のみ
            # ログがあり、「実装した」ことと「実際にウィジェットへ反映された」
            # ことがログから区別できなかった)。
            self._log(f"[preview-apply] {widget_key} <- {image_path}")
        except Exception as ex:  # noqa: BLE001
            self._preview_images.pop(widget_key, None)
            widget.config(image="", text=os.path.basename(image_path))
            self._log(
                f"[preview] failed to load image for {widget_key} "
                f"({os.path.basename(image_path)}): {ex}"
            )

    @staticmethod
    def _preview_display_size(widget: tk.Widget) -> tuple[int, int]:
        """previewFront/previewSideウィジェットの現在の配置(place())から
        表示域の幅・高さを読み取る(#25 layout_content_area()がこだわりパネルの
        開閉に応じてheightを動的変更するため、生成時の固定値ではなく都度
        place_info()から引く)。値が取れない・不正な場合は生成時の初期値
        (380x360、L.583/L.589相当)にフォールバックする。"""
        info = widget.place_info()
        try:
            width = int(info.get("width") or 0)
        except (TypeError, ValueError):
            width = 0
        try:
            height = int(info.get("height") or 0)
        except (TypeError, ValueError):
            height = 0
        return (width if width > 0 else 380, height if height > 0 else 360)

    def _on_pipeline_exit(self, code: int, preview_only: bool) -> None:
        """OnPipelineDone() L.2894-2954相当。dev#600(完了ダイアログ)/dev#601(pak
        一覧更新)/dev#606(MOD自動適用)/dev#611(自動プレビューのsilentPreview抑制)を
        すべて結線する。C#版と同じ順序で統合: 警告 → preview_only分岐(silentPreview
        なら完了ダイアログ抑制、L.2917相当) → (非preview_onlyのみ)一覧更新 →
        自動適用 → 自動適用済みなら完了ダイアログを出さない(autoAppliedフラグ、
        L.2944-2952相当)。"""
        self._set_running_ui_state(False)
        if code != 0:
            # dev#1261: ##AVATAR_FATAL##マーカー(例: メッシュ0個、実報告
            # DLK66VBE)を検出していた場合、汎用の「失敗またはキャンセル」の
            # 代わりに専用文言(i18n key MsgNoMeshFatal等)を使う。未検出時は
            # 従来どおりStatusFailedOrCancelled(受入条件の負の対照: 通常の
            # 失敗では本分岐は変化しない)。fatal_codeを閉じ込めた関数を
            # _set_status()へ渡すことで、他のステータス同様に言語切替時の
            # 再翻訳(_on_language_selected→_last_status_render)にも対応する。
            # getattrで守るのは、この属性を持たない既存の最小フェイクself
            # (test_error_next_action.py等、dev#137と同じ理由)でも壊れない
            # ようにするため。
            fatal_code = getattr(self, "_pipeline_fatal_cause", None)
            self._pipeline_fatal_cause = None

            def _render_failure_status(fatal_code=fatal_code) -> str:
                if fatal_code is not None:
                    return pipeline_runner.translate_avatar_fatal(fatal_code)
                return i18n.S("StatusFailedOrCancelled")

            self._set_status(_render_failure_status)
            status_text = _render_failure_status()
            # dev#138: 主要なエラーパスの1つ(変換失敗)。ユーザー自身が
            # cancelButtonで中止した場合(_on_cancel_convert側で既に
            # Yes/No確認済み)は、直後に「問い合わせますか」を重ねて
            # 出さない(二重確認を避ける、_user_cancelled_current_run参照)。
            user_cancelled = self._user_cancelled_current_run
            self._user_cancelled_current_run = False
            if fatal_code == pipeline_runner.PALWORLD_NOT_FOUND_FATAL_CODE:
                # dev#1394(実報告ATXSKRLB/ZJSU5FWD/7TXW783Q): 自動プレビュー
                # (auto=True)経路は_start_pipeline()冒頭の
                # _ensure_palworld_located()を意図的にスキップするため
                # (二重起動中/ファイル未指定と同様、auto時はダイアログを
                # 出さない既存方針)、Palworld本体が見つからずPhase 0が
                # FATALした場合、従来はここで汎用の「問い合わせますか」
                # オファーしか出ず、手動指定への導線が一切無かった
                # (=CLAUDE.md「外部依存パスの原則」の②が自動プレビュー
                # 経路にだけ配線されていなかった欠落)。ここで直接
                # _resolve_paks_dir_interactive()(Apply/Remove・明示的な
                # 「変換開始」と完全共用、二重実装しない)を呼び、auto/
                # 非autoどちらの経路でも手動指定フォールバックへ到達させる。
                # 解決すればsettings_paksdir.txtへ保存され(既存の
                # pak_manager.resolve_paks_dir()の契約どおり)、以後の
                # auto含む全経路がpaks_dir_quiet()経由で自動的に恩恵を
                # 受ける。原因が自己解決可能なため、一般的な「問い合わせ
                # ますか」オファー(_offer_report_after_failure)は出さない。
                self._resolve_paks_dir_interactive()
                return
            if not user_cancelled:
                self._offer_report_after_failure(status_text)
            return
        # dev#137: 成功時(code==0)にのみ、今回runの区間到達記録を恒常履歴へ
        # 確定保存する。失敗/キャンセルされたrunを混ぜるとETAの母集団が
        # 歪む(「失敗するまでの時間」であって「完了までの時間」ではない)
        # ため、この分岐(code==0確定後)でだけ呼ぶ。記録の失敗はログにだけ
        # 残し、完了処理本体は止めない(このETA機能の防御方針を踏襲)。
        try:
            self._record_eta_run_on_success()
        except Exception as ex:  # noqa: BLE001
            self._log(f"[eta] failed to record run history: {ex}")
        # OnPipelineDone() L.2902相当: 全工程完了後に必ず1回、最終結果で再読込する
        # (早期反映が間に合わなかった/失敗した場合の保険を兼ねる)。
        handle = self._active_handle
        if handle is not None and handle.job_dir:
            try:
                self._apply_previews(pipeline_runner.load_previews(handle.job_dir))
            except Exception as ex:  # noqa: BLE001
                self._log(f"[preview-final] load_previews failed: {ex}")
        # OnPipelineDone() L.2905-2910相当: 警告ダイアログは完了ダイアログより先
        # (どちらの分岐でも警告の存在に気付けるよう埋もれさせない)。
        if self._pipeline_warnings:
            messagebox.showwarning(
                i18n.S("TitleConvertDoneWithWarnings"),
                i18n.F("MsgConvertDoneWithWarningsFormat", "\n\n".join(self._pipeline_warnings)),
            )
        if preview_only:
            # dev#613/#617: OnPipelineDone() L.2914-2915相当
            # (`SavePreviewSig(); UpdateButtonStates(); // フル変換ボタンが
            # ここで解禁される`)。StatusPreviewDoneの明示表示より先に行う
            # (C#と同じ順序。_finalize_fresh_preview内のUpdateButtonStates
            # 相当が一時的にStatusReadyToConvert等を書いても、直後にここで
            # StatusPreviewDoneへ上書きされるのはC#と同じ挙動)。
            self._finalize_fresh_preview(self.widgets["vrmBox"].get().strip())
            self._set_status(lambda: i18n.S("StatusPreviewDone"))
            # dev#600×dev#611由来の完了ダイアログ(OnPipelineDone()
            # L.2916-2917相当)は、オーナー指示(2026-08-09「プレビュー完了の
            # popupいらない」)によりpreview_only成功時は常に出さない。結果は
            # プレビュー画像自体の更新(_finalize_fresh_preview→
            # _apply_previews)で伝わるため、silentPreview(自動プレビュー)
            # かどうかに関わらず抑制する。_silent_previewフラグ自体は
            # dev#611由来で他に用途がないため未使用のまま残すが、削除は
            # 本WPのスコープ外(呼び出し元_start_pipelineの結線はそのまま)。
            return
        self._set_status(lambda: i18n.S("StatusReadyToConvert"))
        # dev#601: OnPipelineDone() L.2919相当のRefreshPakList()結線
        self._on_refresh_pak_list()
        # dev#606: OnPipelineDone() L.2938-2949相当の自動適用結線。完成pakのフル
        # パスをjob_dirから直接解決し、既存の「Palworldに適用」ボタンと同じ中核
        # (_apply_pak_path)を呼ぶ。
        auto_applied = False
        if self._auto_apply_var.get() and handle is not None and handle.job_dir:
            avatar_name = os.path.basename(handle.job_dir)
            pak_path = self._resolve_completed_pak_path(handle.job_dir)
            if pak_path is None:
                self._log(f"[auto-apply] skipped, no completed pak found: {avatar_name}")
            else:
                try:
                    auto_applied = self._apply_pak_path(pak_path, avatar_name)
                except Exception as ex:  # noqa: BLE001 -- 仕様2: 例外は握ってGUIを殺さない
                    auto_applied = False
                    self._log(f"[auto-apply] unexpected exception: {ex}")
                self._log(f"[auto-apply] {'succeeded' if auto_applied else 'failed/aborted'}: {avatar_name}")
        # dev#1230(2026-08-08オーナー裁定): ユーザーサイドpreflightの
        # 非ブロック化。preflight FAILでもここ(code==0分岐)まで到達している
        # 時点でpakは既に完成している(build_pak_from_avatar.py Phase4/
        # fast_repack.py --preflightがdie()せずに継続するため)。結果は
        # <job_dir>\build\preflight_result.jsonに記録されている
        # (pipeline_runner.read_preflight_result()参照)。FAIL時は通常の
        # 完了ダイアログの代わりに警告ダイアログ(「MODを解除」「問合せ」の
        # 2導線)を出す。結果ファイルが無い/status=PASSのとき
        # (is_preflight_fail_resultがFalse)は下のelifへ落ち、従来どおり
        # MsgConvertDoneBodyのまま(受入条件⑤: PASS時の挙動は完全不変)。
        preflight_result = (
            pipeline_runner.read_preflight_result(handle.job_dir)
            if handle is not None and handle.job_dir else None
        )
        # dev#600: OnPipelineDone() L.2950-2952相当の完了ダイアログ結線。
        # 自動適用済み(autoApplied)なら二重の完了通知を避けるため抑制する。
        if pipeline_runner.is_preflight_fail_result(preflight_result):
            preflight_warning_dialog.show_preflight_warning_dialog(
                self.root,
                preflight_warning_dialog.PreflightWarningContext(
                    on_remove_mod=self._on_remove_applied,
                    on_open_inquiry=self._on_show_support_dialog,
                ),
            )
        elif not auto_applied:
            messagebox.showinfo(i18n.S("TitleConvertDone"), i18n.S("MsgConvertDoneBody"))

    def _set_running_ui_state(
        self, running: bool, *, phase: str = pipeline_runner.PHASE_PIPELINE
    ) -> None:
        """UpdateButtonStates()の変換中/非変換中の切替部分に相当する最小版。

        dev#602: phaseは開始時のbusyBarモード決定にのみ使う
        (pipeline_runner.initial_busy_bar_mode()参照)。フル変換
        (phase=PHASE_PIPELINE、既定値)は常にdeterminateから開始する
        ——これにより、直前にUnity輸出(indeterminate)を経由していた場合でも
        残留せず必ずリセットされる(RunPipeline() L.2602/RunUnityExport()
        L.2678の両方が呼び出しのたびにStyleを明示設定するのと同じ)。
        running=False(終了時)もC#版のOnUnityExportDone() L.2686と同じく
        無条件でdeterminateへ戻す。

        dev#613/#617: idleに戻る際、convertButtonの有効化にプレビュー鮮度判定
        (_refresh_convert_button_freshness、IsPreviewFresh相当)を組み込む
        (running中は busy 側で問答無用でdisabled、C#の
        `!busy && hasVrm && fresh && ...` のうち`!busy`部分に相当)。

        dev#621: workRootFailed中は running=False で戻ってきても
        matsButton/previewButtonを再度normalへ戻さない(UpdateButtonStates
        L.2486-2491の`!workRootFailed`条件相当。恒久的な全面無効化)。
        convertButtonは_refresh_convert_button_freshness()側でも同じ
        work_root_failedガードを持つ(このメソッド以外の経路
        ——_on_drop_bones_changed等——からも呼ばれるため、ここだけの
        ガードでは漏れる)。

        dev#639: matsButton/previewButtonの有効/無効自体は
        _update_button_states()(busy/blenderReady/hasVrm/workRootFailed
        ゲート込み、PR #647統合)へ委譲する。
        """
        self._is_pipeline_running = running
        self._update_button_states()
        self.widgets["cancelButton"].config(state=("normal" if running else "disabled"))
        # dev#602追補: どのフェーズが走っているかを覚えておく(Unity輸出
        # ハートビートの発火判定に使う。_poll_active_handle()参照)。
        self._active_phase = phase
        if running:
            self.widgets["convertButton"].config(state="disabled")
            self.widgets["busyBar"]["value"] = 0
            self.widgets["busyBar"].place(**self._busy_bar_geometry)
            self._set_busy_bar_mode(pipeline_runner.initial_busy_bar_mode(phase))
        else:
            self._set_busy_bar_mode(pipeline_runner.BUSY_BAR_MODE_DETERMINATE)
            self._refresh_convert_button_freshness()
            self.widgets["busyBar"].place_forget()

    def _set_busy_bar_mode(self, mode: str) -> None:
        """busyBarのStyle切替(RunPipeline() L.2602 Continuous / RunUnityExport()
        L.2678-2679 Marquee+MarqueeAnimationSpeed=30相当)。indeterminateでは
        ttk Progressbar.start()でアニメーションを開始し(intervalはC#の
        MarqueeAnimationSpeed=30msをそのまま踏襲)、determinateではstop()して
        値表示に戻す。"""
        busy_bar = self.widgets["busyBar"]
        if mode == pipeline_runner.BUSY_BAR_MODE_INDETERMINATE:
            busy_bar.config(mode="indeterminate")
            busy_bar.start(30)
        else:
            busy_bar.stop()
            busy_bar.config(mode="determinate")

    def _update_button_states(self) -> None:
        """UpdateButtonStates()(app\\DiveToPalworld.cs L.2468-2525)のうち、
        matsButton/previewButtonのゲート判定を移植(dev#639)。convertButtonは
        _refresh_convert_button_freshness()側が担当する(鮮度判定
        (dev#613/#617)とblenderReadyが絡むため分離、そちらもdev#639統合で
        blenderReadyゲートを追加済み)。

        C#: previewButton.Enabled = !busy && hasVrm && blenderReady && !workRootFailed;
            matsButton.Enabled    = !busy && hasVrm && blenderReady && !workRootFailed
                                     && HasNoueFullBuild();

        本WP作成時点(#647分岐元)ではhasVrm/workRootFailedの判定コードが
        まだmasterに無かったため`busy`/`blenderReady`の2条件のみで独立追加
        されていたが、#635(dev#613/#617)・#637(dev#621)のマージにより
        `_work_root_failed`判定・vrmBoxウィジェットが揃ったため、本統合
        (Masterライター、PR #647本文の指示どおり)でhasVrm/workRootFailedを
        合流させた。

        dev#648: HasNoueFullBuild()(noue_full_build.has_noue_full_build())を
        matsButtonにのみ追加(previewButtonはC#版どおり対象外の非対称)。
        「影のみ更新」は前回のフル変換の中間成果が揃っていないと必ず失敗する
        ため、揃っていない間は押させない。work_rootはgetattrで安全に読む
        (実行時のMainWindowは__init__(L.175)で必ずself.work_rootを持つが、
        既存テスト群には__new__でMainWindow.__init__を通さない「束縛前self」
        double(test_guard_dialogs.py._bare_window()等)がありself.work_rootを
        持たないため、そちらを本WPのスコープ外で壊さないための防御)。"""
        vrm_path = self.widgets["vrmBox"].get().strip()
        has_vrm = os.path.isfile(vrm_path)
        base_enabled = (
            not self._is_pipeline_running
            and self._blender_ready
            and has_vrm
            and not self._work_root_failed
        )
        preview_state = "normal" if base_enabled else "disabled"
        mats_enabled = base_enabled and noue_full_build.has_noue_full_build(
            getattr(self, "work_root", ""), vrm_path
        )
        mats_state = "normal" if mats_enabled else "disabled"
        self.widgets["previewButton"].config(state=preview_state)
        self.widgets["matsButton"].config(state=mats_state)

    def _clear_log(self) -> None:
        log_box = self.log_box
        log_box.configure(state="normal")
        log_box.delete("1.0", tk.END)
        log_box.configure(state="disabled")

    # -- WP-A2: Unity輸出(RunUnityExport)ハンドラ -----------------------------

    def _on_prefab_selected(self, prefab_path: str) -> None:
        """RunUnityExport() L.2612-2682相当(起動〜完了検知まで)。

        dev#702 第3弾WP-3: 輸出前にキャッシュ鮮度(lu_export.is_export_cache_fresh、
        鍵=prefab自体のSHA256のみ)を確認し、新鮮ならUnity再起動そのものを省略する
        (dev#602のUXは「新規Unity起動時のみ」進捗表示する前提のため、キャッシュ
        ヒット時は素通りでよい、PROPOSAL WP-3節)。輸出成功後・キャッシュヒット後の
        どちらの経路でも、GUI表示はprefabパスのまま維持する(_set_vrm_path(fbx)から
        _set_vrm_path(prefab_path)へ変更)。convert.ps1側のPhase -1が実際の変換時に
        prefab入力を都度解決するため、GUIはprefabパスをjob.jsonへ書けばよい。

        dev#1056: Blender初回セットアップ(DL)完了前(self._blender_ready==False)に
        呼ばれた場合はUnity輸出を起動せず、prefab_pathを保留してBlenderセットアップを
        (未着手/前回失敗後なら)開始するだけに留める。旧実装はここでBlender準備状態を
        一切見ずにbusyBar/_active_handleへ即書き込んでいたため、Blenderセットアップ
        側の進捗表示(_on_blender_progress、同じbusyBarを書き換える)と競合し
        フリーズ/クラッシュを起こしていた(#915は同じ引き金による表示混在の軽症状)。
        C#版 EnsureBlenderReadyForConversion() L.1439-1446 と同じ設計: 初回セットアップ
        中にポップアップを出さない裁定(C#版L.1424-1425)を踏襲し、確認ダイアログは
        出さない。statusLabel/ログはBlenderセットアップの進捗表示が既に担っている。
        セットアップ成功時、_on_blender_setup_done()がこの保留パスを取り出して
        本メソッドを自動的に呼び直す(ユーザー操作はドロップ1回で済む)。"""
        if not self._blender_ready:
            self._pending_prefab_drop_path = prefab_path
            self._log(f"[prefab] blender not ready yet, deferring drop: {prefab_path}")
            self._ensure_blender_ready_on_startup()
            return
        if self._active_handle is not None and self._active_handle.is_running():
            messagebox.showinfo(i18n.S("TitleConfirm"), i18n.S("MsgOtherProcessRunning"))
            return
        script = pipeline_runner.build_unity_export_script_path(self.app_root)
        if not os.path.isfile(script):
            messagebox.showinfo(
                i18n.S("TitleConfirm"), i18n.F("MsgExportScriptNotFoundFormat", script)
            )
            return
        out_dir = pipeline_runner.resolve_unity_export_out_dir(self.work_root, prefab_path)
        if lu_export.is_export_cache_fresh(out_dir, prefab_path):
            # dev#1551 laneG5修理(work\run_1551\gui_verify\RESULT.md 0.2節指摘:
            # 「このパスにはログ出力が一切無い」): キャッシュ再利用を「静かに」
            # 行わない。fresh/stale判定はログから追える必要がある(問い合わせ
            # 診断の唯一の材料はログであるため、CLAUDE.md「問い合わせからの
            # デバッグ」原則)。
            self._log(f"[prefab] using cached Unity export (fresh): {out_dir}")
            self._set_status(lambda: i18n.S("StatusUnityExportDone"))
            self._set_vrm_path(prefab_path)
            return
        self._clear_log()
        # dev#602: Unity輸出は構造的に##PROGRESS##マーカーが来ない工程
        # (RunUnityExport() L.2677コメント)なのでindeterminate(Marquee相当)。
        self._set_running_ui_state(True, phase=pipeline_runner.PHASE_UNITY_EXPORT)
        self._set_status(lambda: i18n.S("StatusUnityExporting"))
        # dev#602追補: ハートビート計測開始(構造的に無音のこのフェーズで、
        # 一定時間ごとに「まだ動いている」ことを伝えるため)。
        now = time.monotonic()
        self._unity_export_started_at = now
        self._unity_export_last_output_at = now
        # dev#702 WP-3: _on_unity_export_exit側でsig保存・GUI表示維持に必要な
        # prefab_pathを覚えておく(handleはpipeline_runner.ProcessHandle互換の
        # 単純objectで、out_dir同様にここで属性追加してよい設計、WP-3書き込み
        # 許可ファイルがmain_window.py側のみのためpipeline_runner.pyは変更しない)。
        self._pending_prefab_export_path = prefab_path
        self._active_handle = pipeline_runner.run_unity_export(
            self.app_root, self.work_root, prefab_path,
            on_line=self._on_pipeline_line,
            on_exit=self._on_unity_export_exit,
            # dev#1242申し送り②: run_pipeline()と同じ理由(主スレッド実行、
            # pak_manager.resolve_paks_dir()同型パターン)でself._logを直結。
            log=self._log,
        )
        self.root.after(self._POLL_INTERVAL_MS, self._poll_active_handle)

    def _on_unity_export_exit(self, code: int) -> None:
        """OnUnityExportDone() L.2684-2718相当。"""
        self._set_running_ui_state(False)
        handle = self._active_handle
        out_dir = handle.out_dir if handle is not None else None
        if code != 0:
            self._set_status(lambda: i18n.S("StatusUnityExportFailed"))
            # dev#1262: ログ欄(=export_from_unity.ps1のExcerpt出力を含む、
            # _clear_log()でこのエクスポート開始時にクリア済み=今回分のみ)を
            # 走査し、UniVRM二重導入(UPM版+手動導入版の共存によるGUID衝突)を
            # 検出できたら専用の案内メッセージへ差し替える。log_box未設定の
            # フェイクself(既存テストtest_prefab_gui_cache.py等)ではgetattrで
            # 静かにFalse側へ倒れ、従来どおり汎用メッセージになる。
            log_box = getattr(self, "log_box", None)
            log_text = ""
            if log_box is not None:
                try:
                    log_text = log_box.get("1.0", "end-1c")
                except Exception:  # noqa: BLE001
                    log_text = ""
            if pipeline_runner.detect_univrm_duplicate_install(log_text):
                messagebox.showerror(
                    i18n.S("TitleUnityExportError"), i18n.S("MsgUnityExportErrorUnivrmDupBody")
                )
            else:
                messagebox.showerror(i18n.S("TitleUnityExportError"), i18n.S("MsgUnityExportErrorBody"))
            return
        fbx = pipeline_runner.find_exported_fbx(out_dir) if out_dir else None
        if fbx is None:
            self._set_status(lambda: i18n.S("StatusUnityExportNoFbx"))
            messagebox.showinfo(
                i18n.S("TitleUnityExport"), i18n.F("MsgUnityExportNoFbxFormat", out_dir)
            )
            return
        # dev#702 第3弾WP-3: 輸出成功後、GUI表示はprefabパスのまま維持する
        # (fbxへ差し替えない)。sig保存(lu_export.save_export_sig)はGUI起点の
        # 連続実行(選択直後にフル変換/プレビュー)がキャッシュヒットする前提を
        # 成立させるために必須(保存しないと毎回Unity再輸出になる)。
        prefab_path = self._pending_prefab_export_path
        lu_export.save_export_sig(out_dir, prefab_path)
        # dev#1551 laneG5修理(work\run_1551\gui_verify\RESULT.md 0章): この
        # GUI起点の輸出経路はresolve_prefab_to_fbx()を経由しないため、
        # is_export_cache_fresh()が新たに要求するエクスポータ指紋も個別に
        # 保存する必要がある(save_export_sig()と対で必ず呼ぶ、lu_export.py
        # save_exporter_schema_sig()のdocstring参照)。
        lu_export.save_exporter_schema_sig(out_dir)
        self._set_status(lambda: i18n.S("StatusUnityExportDone"))
        self._set_vrm_path(prefab_path)

    # -- Blender準備(DESIGN.md §2.2、WP-A3。実ロジックはblender_setup.py) --------

    def _ensure_blender_ready_on_startup(self) -> None:
        """EnsureBlenderReadyOnStartup() L.1998-2005相当。既に実行中/準備済みなら
        何もしない(二重起動防止)。それ以外はワーカースレッドへ
        blender_setup.do_ensure_blender_ready()を投げ、UIはブロックしない。
        blenderRetryButtonのクリックからも同じ経路を通る(=失敗時リトライ)。"""
        if self._blender_setup_running or self._blender_ready:
            return
        self._blender_setup_running = True
        self.widgets["blenderRetryButton"].place_forget()
        self._set_status(lambda: i18n.S("StatusBlenderChecking"))
        threading.Thread(target=self._blender_setup_worker, daemon=True).start()

    def _blender_setup_worker(self) -> None:
        """ワーカースレッド側の実処理。tkinterウィジェットには一切触れず、
        すべて self._blender_queue 経由でメインスレッドへ中継する
        (DESIGN.md §4.3、DoEnsureBlenderReady()のPostToUi相当)。

        dev#1242申し送り②: find_blender()/find_pwsh()の探索ログ
        (do_ensure_blender_ready()のlog=引数)がこれまで結線されておらず、
        実GUI経路(ここ)では収集されていなかった。on_progressと同じ
        queueマーシャリングパターンで"log"種別を追加し、_poll_blender_queue()
        (主スレッド)側でself._logへ描画する——自身は直接tkに触れない。"""

        def on_progress(pct: int, phase: str) -> None:
            self._blender_queue.put(("progress", pct, phase))

        def on_log(line: str) -> None:
            self._blender_queue.put(("log", line))

        ok, fail_message, action = blender_setup.do_ensure_blender_ready(
            self.app_root,
            on_progress=on_progress,
            process_handle=self._blender_setup_process_handle,
            log=on_log,
        )
        self._blender_queue.put(("done", ok, fail_message, action))

    def _poll_blender_queue(self) -> None:
        """root.after()による定期ポーリング(DESIGN.md §4.3)。ワーカースレッドが
        _blender_queueへ積んだ進捗中継/完了通知をメインスレッドで消費する。

        dev#1242申し送り②: "log"種別(_blender_setup_worker()のon_log)は
        find_blender()/find_pwsh()の探索ログ1行。ここ(主スレッド)で初めて
        ログ欄描画メソッドを呼ぶ(pak_manager.resolve_paks_dir()の
        log=self._logと同じ扱い、gui既定Trueで「ログをコピー」に載る経路へ
        流す)。"""
        try:
            while True:
                msg = self._blender_queue.get_nowait()
                if msg[0] == "progress":
                    self._on_blender_progress(msg[1], msg[2])
                elif msg[0] == "log":
                    self._log(msg[1])
                elif msg[0] == "done":
                    self._on_blender_setup_done(msg[1], msg[2], msg[3])
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._poll_blender_queue)

    def _poll_warm_cache_status(self) -> None:
        """dev#45 ②: WarmCacheStatus(warm_startup.py)をポーリングし、
        「共通データ準備中…」の表示/復元をエッジ検出で行う(状態が変化した
        回だけ_set_status()を呼ぶ。busyBar同様、tkウィジェットに触れるのは
        ここ=UIスレッドのみで、_warm_cache_status自体はワーカースレッドから
        更新される。共通契約のスレッドまたぎ配線(DESIGN.md §4.3ポーリング
        パターン)を踏襲)。

        受入試験用に、このメソッド本体は`self.root`/`self._set_status`/
        `self._warm_cache_status`/`self._warm_cache_status_pending_last`/
        `self._status_before_warm_cache`だけに依存する(フェイクself経由の
        束縛前呼び出しでtk窓なしに検査できる、test_button_gates.py等と
        同じ方式)。"""
        pending = self._warm_cache_status.is_pending()
        if pending != self._warm_cache_status_pending_last:
            self._warm_cache_status_pending_last = pending
            if pending:
                # 「準備中」に切り替える直前の描画手順を退避する(完了時に
                # そのまま復元するため。dev#897の_last_status_render仕組みに
                # 相乗りする)。
                self._status_before_warm_cache = self._last_status_render
                self._set_status(lambda: i18n.S("StatusWarmCachePreparing"))
            else:
                # 完了: 退避しておいた直前の文言があれば復元する(「消える」
                # =warm専用文言が退場し、元の文言に戻る、の意)。退避が無い
                # (起動直後でまだ何もstatusLabelに出ていない等)場合は何も
                # しない——空文字で上書きして情報を減らさない安全側。
                if self._status_before_warm_cache is not None:
                    self._set_status(self._status_before_warm_cache)
                self._status_before_warm_cache = None
        self.root.after(200, self._poll_warm_cache_status)

    def _maybe_log_warm_cache_first_run_notice(self) -> None:
        """dev#45 ②: _start_pipeline()冒頭から呼ばれる。変換開始時点で
        warm_cache()がまだ完了していなければ(未開始/実行中のいずれも
        is_incomplete()=True)、「初回準備のため数分かかります」相当を
        ログ欄(self._log)へ明示する。statusLabel(_set_status())は直後の
        進捗更新(_on_pipeline_line等)で即座に上書きされる動的表示のため、
        ここでは常時表示のログ欄側へ出す設計にした(〈合理的解釈〉、
        完了報告に明記)。

        _start_pipeline()から分離した独立メソッドにしてあるのは、あの
        メソッド自体はwidgets/pipeline_runner等への依存が大きくtk窓なしの
        単体試験に不向きなため——このメソッド単体なら
        self._warm_cache_status/self._logだけに依存する形でフェイクself
        経由で検証できる(test_button_gates.py等と同じ方式)。

        診断ログはUI言語に追従させずlang="en"固定にする(dev#596/#897の
        既定方針、test_log_i18n_dev596.py::test_main_window_log_calls_do_
        not_leak_current_ui_languageが強制する)。"""
        if self._warm_cache_status.is_incomplete():
            self._log(f"[warm_startup] {i18n.S('StatusWarmCacheFirstRunNotice', lang='en')}")

    def _on_blender_progress(self, pct: int, phase: str) -> None:
        busy_bar = self.widgets["busyBar"]
        busy_bar.place(x=330, y=46, width=740, height=12)
        busy_bar["value"] = pct
        # dev#933: phase(ensure_blender.ps1由来の生ASCII文字列)を直接
        # i18n.F へ渡していたため、Blenderセットアップ中の進捗フェーズ文言が
        # 全言語で英語のまま出ていた(PR #922のensure_blender.ps1純ASCII化に
        # よる回帰)。translate_blender_phase() で翻訳してから埋め込む。
        # _set_status()へ渡すlambdaはUI言語切替のたびに再評価される
        # (dev#897と同じ設計)ので、ここでは生のphase/pctだけを閉じ込め、
        # 翻訳自体はlambda内で毎回呼び直す(先に訳文化してしまうと言語切替
        # 時に古い言語のまま固定されてしまう)。
        self._set_status(
            lambda: i18n.F("StatusBlenderSettingUpFormat", translate_blender_phase(phase), pct)
        )

    def _on_blender_setup_done(
        self, ok: bool, fail_message: str | None, action: blender_setup.BlenderSetupAction
    ) -> None:
        self._blender_setup_running = False
        self._blender_ready = ok
        self.widgets["busyBar"].place_forget()
        # dev#639: blenderReady確定(成功/失敗いずれも)の直後にゲートを
        # 再計算する。失敗時は依然disabledのまま(初期状態からの変化なし)だが、
        # 「blenderReady変化のたびに必ず再計算する」という設計上の対称性を
        # 保つため、成否に関わらず呼ぶ(C#版UpdateButtonStates()もここで
        # 無条件に呼ばれる、L.2073)。
        self._update_button_states()
        # dev#1239: convertButtonのゲートは_update_button_states()の担当外
        # (L.3312-3315のdocstring参照、matsButton/previewButtonのみ)なので、
        # ここで_refresh_convert_button_freshness()も明示的に呼ぶ必要がある。
        # 起動シーケンス上、_restore_last_vrm_on_startup()(__init__ L.634)は
        # _ensure_blender_ready_on_startup()(__init__ L.680)より先に走るため、
        # 復元直後に一度だけ呼ばれる_refresh_convert_button_freshness()は
        # 必ずblenderReady=Falseの状態で早期returnし、disabledのまま確定して
        # しまう(L.2254-2256のblenderReadyガード)。プレビューキャッシュが
        # freshだと_maybe_auto_preview()もパイプラインを再実行しない
        # (reason=preview-fresh、dev#613)ため、_finalize_fresh_preview()経由の
        # 再解禁も起きない。結果、blenderReadyがこの後Trueに確定しても
        # 誰もconvertButtonを再計算しないまま=再起動後にフル変換ボタンが
        # 押せなくなる(オーナー報告2026-08-08、dev#1239)。ここで呼ぶことで、
        # D&D/参照ボタン経路(_set_vrm_path末尾)と同じ有効化ロジックへ
        # 揃える(入口で正規化、経路ごとの特別扱いを増やさない)。
        self._refresh_convert_button_freshness()
        if ok:
            self._set_status(lambda: i18n.S("StatusPromptVrm"))
            self.widgets["blenderRetryButton"].place_forget()
            self._warm_startup_after_blender_ready()
            # dev#1056: Blender未確定時にドロップされ保留していたprefabがあれば
            # ここで取り出して自動的に続行する(C#版DoEnsureBlenderReady()
            # L.2091-2096の`if (ok && pendingBlenderReadyAction != null)`と同じ
            # 契約: 失敗時(else分岐)はここを通らず保留を消さない=次回リトライ
            # 成功時に持ち越される)。getattrで安全に読む(既存の単体テスト群には
            # __new__でMainWindow.__init__を通さない「束縛前self」double
            # (test_error_next_action.py._fake_window_for_blender_done()等)があり、
            # self._pending_prefab_drop_pathを持たないため、そちらを本WPのスコープ外で
            # 壊さないための防御、_update_button_states()のwork_root同様の作法)。
            pending_prefab = getattr(self, "_pending_prefab_drop_path", None)
            if pending_prefab is not None:
                self._pending_prefab_drop_path = None
                self._log(f"[prefab] blender ready, resuming deferred drop: {pending_prefab}")
                self._on_prefab_selected(pending_prefab)
        else:
            # dev#939 ①(dev#897の宿題): fail_messageはblender_setup.py側が
            # 子プロセス出力から切り出した生文字列(ensure_blender.ps1由来、
            # 常に英語)。以前はi18n非経由でそのままGUIへ渡し、日本語UIの
            # ユーザーがセットアップ失敗時だけ英語ダイアログを見る非対称が
            # あった。translate_blender_setup_fail_message()で行単位に
            # 翻訳してから使う(未知の行はそのまま残る=情報は失わない)。
            # Noneの場合のi18n.S(...)フォールバックは元々翻訳済みなので、
            # 翻訳関数はfail_messageがある場合にのみ適用する。
            #
            # dev#1514: 上記「未知の行はそのまま残る」設計上、生の"Reason: "
            # 例外文と"[D2P_PATH_SHAPE]"診断行がダイアログ/ステータス欄へ
            # そのまま出ていた(オーナー実見2026-08-16)。ダイアログ/ステータス
            # 欄にはstrip_blender_setup_fail_diagnostics()で除去したうえで
            # 翻訳した版だけを渡し、除去前の全文(診断情報込み)はここで
            # self._log()へ記録する(診断能力を落とさない。問い合わせボタンが
            # 添付するlaunch.log経由でサポートへ届く経路はそのまま)。
            if fail_message:
                self._log(
                    "[blender_setup] fail detail: "
                    + translate_blender_setup_fail_message(fail_message)
                )
                dialog_safe_fail_message = strip_blender_setup_fail_diagnostics(fail_message)
            else:
                dialog_safe_fail_message = None

            def _render_blender_setup_fail_text(msg=dialog_safe_fail_message) -> str:
                return (
                    translate_blender_setup_fail_message(msg)
                    if msg
                    else i18n.S("MsgBlenderSetupFailedShort")
                )

            text = _render_blender_setup_fail_text()
            self._set_status(_render_blender_setup_fail_text)
            self.widgets["blenderRetryButton"].place(x=330, y=44, width=160, height=36)
        self._log(f"[blender_setup] action={action.value} ok={ok}")
        # dev#138: 主要なエラーパスの1つ(Blender未検出/取得失敗)。
        # ステータス欄の文言だけでは見落とされうるため、失敗時のみ
        # 次アクション導線(問い合わせへの案内)を追加で提示する。
        if not ok:
            self._offer_report_after_failure(text)

    def _warm_startup_after_blender_ready(self) -> None:
        """dev#532 D1: warm_startup.py(WP-A9)の結線。DoEnsureBlenderReady()
        L.2073-2089の呼び出し順(blenderReady=true確定直後)を踏襲し、warm_
        startup.warm_startup_after_blender_ready()を1回だけ呼ぶ(warm_startup.py
        冒頭docstring「D1への結線手順」のとおり)。プロセス起動を伴うため
        ワーカースレッドで実行し、UIスレッドをブロックしない。"""

        def worker() -> None:
            try:
                blender_exe = blender_setup.find_blender(self.app_root)
                paks_dir = pak_manager.paks_dir_quiet(self.app_root, cache=self._paks_dir_cache)
                # dev#229続報: Xbox App版(Pal-WinGDK.pak)でもwarm-cache起動時に
                # 実在するpakを渡せるよう、単一名決め打ちから候補解決へ変更。
                pak_filename = pak_manager.resolve_pak_filename(paks_dir) if paks_dir else None
                pak_path = (
                    os.path.join(paks_dir, pak_filename) if paks_dir and pak_filename else None
                )
                warm_startup.warm_startup_after_blender_ready(
                    self.app_root,
                    self.work_root,
                    blender_exe,
                    pak_path,
                    conversion_pending=self._active_handle is not None,
                    status=self._warm_cache_status,
                )
            except Exception as ex:  # noqa: BLE001 -- warm_startup自体が全例外を
                # 握りつぶす設計だが(warm_startup.py参照)、find_blender()等の
                # 呼び出し前処理の例外はここで追加防御する(起動シーケンスを
                # 絶対に止めないための最終防壁)。
                self.root.after(0, lambda: self._log(f"[warm_startup] skipped: {ex}"))

        threading.Thread(target=worker, daemon=True, name="WarmStartup").start()

    def layout_content_area(self) -> None:
        """#25: LayoutContentArea()相当。こだわりパネルの開閉に応じて
        プレビュー/ログ欄・フッター行(パクリスト以下、#17-#23の常時表示分)の
        y座標と、ウィンドウの高さを再計算する(DiveToPalworld.cs L.1312-1319
        の簡略移植。厳密なpixel一致はWP-A1の受入対象外)。

        dev#551: 旧実装はプレビュー/ログのtopだけを開=208/閉=190という
        別々の近似値で切り替えており、パネル本体の高さ(80px)に見合った
        詰め直しになっていなかった(issue #551 指摘2の直接原因)。本メソッドは
        `_KODAWARI_PANEL_DELTA` 分をプレビュー/ログとフッター行の両方から
        一括して差し引く方式に統一する。開いている間(delta=0)は
        `_FOOTER_OPEN_GEOMETRY` に転記した従来の絶対座標へ完全に戻り、
        見た目はdev#551着手前と変わらない(受入条件「開いた状態で従来と
        同じ要素配置が保たれる」)。閉じている間はフッター行がまとめて
        上へ詰まり、ウィンドウの高さも同じだけ縮む。"""
        delta = 0 if self._kodawari_open else _KODAWARI_PANEL_DELTA

        # プレビュー/ログ(#15-#16): 開いた状態のtop=260を基準に、閉時は
        # deltaぶん引く。bottom_limitも同じdeltaを引いた"lblPaks"のyから
        # 求めるため、開閉どちらでもheight自体は変わらない(アンカーである
        # lblPaks側も一緒に詰まるため。プレビュー欄が伸縮して歪むことはない)。
        # dev#1136: こだわりパネルの高さが80→124(+44px)になったのに
        # 合わせ、208→252へ同じ44pxを加算した(_KODAWARI_PANEL_DELTAの
        # 84→128と対で動く)。
        # dev#1136追撃: さらに124→132(+8px)になったのに合わせ、252→260へ
        # 同じ8pxを加算した(_KODAWARI_PANEL_DELTAの128→136と対で動く。
        # 閉時top(=260-136=124)はdev#1136前と同じ「トグル直下+10px」の
        # まま変わらない)。
        # 修正イテレーション2(オーナーUX評価#1): 260+44=304→260+36=296
        # (_KODAWARI_PANEL_HEIGHT/DELTAコメント参照、同じ8pxを引いて対応関係を
        # 保つ)。
        top = (260 + 44 - 8) - delta  # dev#19: 260→296(_KODAWARI_PANEL_HEIGHT/DELTAコメント参照)
        bottom_limit = _FOOTER_OPEN_GEOMETRY["lblPaks"]["y"] - delta - 10
        height = max(100, bottom_limit - top)
        for key in ("previewFront", "previewSide", "logBox"):
            widget = self.widgets[key]
            x = {"previewFront": 12, "previewSide": 400, "logBox": 790}[key]
            width = {"previewFront": 380, "previewSide": 380, "logBox": 280}[key]
            widget.place(x=x, y=top, width=width, height=height)

        # パクリスト以下のフッター行(#17-#23のうち常時表示分)。
        for key, geo in _FOOTER_OPEN_GEOMETRY.items():
            widget = self.widgets.get(key)
            if widget is None:
                continue
            if key in ("updateLabel", "updateNowButton") and not widget.winfo_ismapped():
                # 更新通知が無い間はplace_forget()済みのまま(_show_update_notice
                # が表示するときに現在のdeltaで自分で配置する)。ここで.place()を
                # 呼ぶと非表示ウィジェットを誤って再表示させてしまうため触らない。
                continue
            new_geo = dict(geo)
            new_geo["y"] = geo["y"] - delta
            widget.place(**new_geo)

        # ウィンドウ高さ: __init__のworkarea.compute_clamp()が決めた安全な
        # 上限(self._window_height、こだわりパネルが開いている状態を前提に
        # した値)から、閉じている間だけパネル1個ぶんを差し引く。フェイクself
        # テスト(__init__を経由しない単体テスト)ではgetattrで安全側
        # (workarea.CONTENT_WIDTH/CONTENT_HEIGHT、挙動不変)に倒す。
        window_width = getattr(self, "_window_width", workarea.CONTENT_WIDTH)
        window_height = getattr(self, "_window_height", workarea.CONTENT_HEIGHT)
        new_window_height = max(workarea.MIN_WINDOW_HEIGHT, window_height - delta)
        try:
            self.root.geometry(f"{window_width}x{new_window_height}")
        except tk.TclError:
            pass
