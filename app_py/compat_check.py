# compat_check.py -- Palworld版互換判定(DESIGN.md §2.7)のPython移植。
#
# 移植元: app\DiveToPalworld.cs 末尾の独立静的クラス群(MainFormから独立済み、
# 元々 --check-palworld-compat 隠しCLIから画面無しで試験するために切り出されて
# いたもの。DESIGN.md §2.7「そのままモジュール関数として1:1移植しやすい部類」):
#   - KnownPalworldVersion (struct, L.6194-6199)
#   - KnownGoodPalworld    (class,  L.6201-6205)
#   - PalworldDetection    (struct, L.6209-6214)
#   - PalworldCompatStatus (struct, L.6217-6228)
#   - PalworldCompat       (static class, L.6230-6400)
#       ParseKnownVersions / ParseKnownManifestHashes / MergeKnownGood /
#       IsKnownVersion / LabelFor / IsKnownManifest / SupportedLabelsJoined /
#       Evaluate / FormatDetected / FormatSupported / BuildLogLine
#
# 3階層の判定(Evaluate()がMainForm.CheckPalworldVersionOnce()から呼ばれる順、
# L.6174-6187のコメントそのまま):
#   1) 既知版番号(known_versions: Steam buildid + Pal-Windows.pakサイズの組)
#   2) 抽出物マニフェスト(known_vanilla_manifest_sha256、dev#91)。版番号が
#      未知でも、実際に変換が消費する材料が既知良好と一致していれば警告しない
#   3) どちらにも一致しなければ警告する
#
# JSON解析について: C#側はcsc.exe単体コンパイル制約(NuGet不可)のため自前の
# 正規表現ベースJSONパーサ(JsonStr/JsonNum/JsonStrArray/JsonObj)を使っており、
# ネストしたオブジェクトの波括弧深さを正しく数えられるかという専用の負の対照
# (CheckPalworldCompatLogicのcase10、JsonObj balanced-brace extraction)まで
# 持っていた。Python移植では標準ライブラリのjsonモジュールをそのまま使うため、
# この種のパーサ自前実装バグはそもそも構造的に発生しない
# (json.loadsはネストしたオブジェクトを常に正しく解釈する)。したがって
# case10は「該当ロジックがPython版に存在しない」ため移植対象から除外した
# (WP-A6の合理的解釈。case1-9は全てEvaluate()自体の分岐なのでそのまま移植する)。
#
# dev#1441: min_tool_version条件付きエントリの追加(C#版に対応なし、新規設計)。
# 背景: 従来のknown_versionsは「ツールバージョンによらず全員に効く白リスト」
# でしかなく、「このPalworld buildは本ツールvX.Y以上でのみ対応」を表現
# できなかった。対応する条件付きエントリを"known_versions"にそのまま追加すると、
# 旧クライアント(このdev#1441より前に公開されたバージョン)のparse_known_versions
# はmin_tool_versionキーを単に無視するため、ツールバージョンに関わらず無条件に
# 白判定してしまう(=旧クライアントが誤って安全と誤認する、fail-unsafe)。
# したがって条件付きエントリは、旧パーサが一切読まない別の最上位キー
# "known_versions_conditional"に置く設計にした(parse_known_versionsは
# 従来どおり"known_versions"キーだけを見るため、この新キーの存在自体に
# 触れない=旧クライアントは単に恩恵を受けないだけで、誤動作はしない)。
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional

from update_check import parse_version as _parse_tool_version


@dataclass
class KnownPalworldVersion:
    build_id: str
    pak_size: int
    label: str


@dataclass
class ConditionalKnownVersion:
    """dev#1441: min_tool_version条件付きの既知バージョンエントリ。無条件版の
    KnownPalworldVersionに"このツールバージョン以上でのみ有効"の条件を足した
    もの。"known_versions_conditional"キー配下にのみ現れる(旧クライアントは
    このキーの存在自体を知らない)。"""

    build_id: str
    pak_size: int
    label: str
    min_tool_version: str


@dataclass
class KnownGoodPalworld:
    versions: List[KnownPalworldVersion] = field(default_factory=list)
    manifest_hashes: List[str] = field(default_factory=list)
    conditional_versions: List[ConditionalKnownVersion] = field(default_factory=list)


@dataclass
class PalworldDetection:
    """1回分のバージョン検出結果(I/O抜きの値だけ)。Paksが見つからなければ
    detected=Falseのまま(従来の「判定不能=黙って動く」を表す、L.6207-6214)。"""

    detected: bool = False
    build_id: Optional[str] = None  # 取得できなければNone
    pak_size: int = 0               # 取得できなければ0


@dataclass
class PalworldCompatStatus:
    """PalworldCompat.Evaluate()の結果。should_warnがTrueの時だけ警告を出す
    (L.6217-6228)。"""

    detected: bool = False
    build_id: Optional[str] = None
    pak_size: int = 0
    known_version: bool = False
    version_label: Optional[str] = None
    manifest_available: bool = False
    manifest_hash: Optional[str] = None
    known_manifest: bool = False
    should_warn: bool = False
    # dev#1441: 版・pakサイズは条件付きエントリ(known_versions_conditional)に
    # 一致したが、渡されたcurrent_tool_versionがmin_tool_versionに満たなかった
    # 場合のヒント情報。should_warn=Trueのまま(通常警告は出す)、GUI側が
    # 追加の「更新で対応済みの可能性」文言を出すために使う。マッチしなかった、
    # またはcurrent_tool_versionを渡されなかった場合はNoneのまま。
    update_hint_min_tool_version: Optional[str] = None
    update_hint_version_label: Optional[str] = None


def parse_known_versions(json_text: Optional[str]) -> List[KnownPalworldVersion]:
    """ParseKnownVersions(L.6232-6253)相当。"known_versions"配列を解析する。
    不正なJSON/欠落フィールドは黙ってスキップする(C#側もbuild_id空/pak_size<0の
    要素をcontinueで読み飛ばす、というfail-safe方針を踏襲)。"""
    result: List[KnownPalworldVersion] = []
    if not json_text:
        return result
    try:
        data = json.loads(json_text)
    except (ValueError, TypeError):
        return result
    if not isinstance(data, dict):
        return result
    for item in data.get("known_versions") or []:
        if not isinstance(item, dict):
            continue
        build_id = item.get("build_id")
        pak_size = item.get("pak_size")
        if not build_id or pak_size is None or pak_size < 0:
            continue
        label = item.get("label") or build_id
        result.append(KnownPalworldVersion(build_id=str(build_id), pak_size=int(pak_size), label=str(label)))
    return result


def parse_known_manifest_hashes(json_text: Optional[str]) -> List[str]:
    """ParseKnownManifestHashes(L.6255-6258)相当。"known_vanilla_manifest_sha256"
    配列を解析する。"""
    if not json_text:
        return []
    try:
        data = json.loads(json_text)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    hashes = data.get("known_vanilla_manifest_sha256")
    if not isinstance(hashes, list):
        return []
    return [str(h) for h in hashes if isinstance(h, str)]


def parse_known_versions_conditional(json_text: Optional[str]) -> List[ConditionalKnownVersion]:
    """dev#1441新規(C#版に対応なし)。"known_versions_conditional"配列を解析
    する。build_id/pak_size/min_tool_versionのいずれかが欠落・不正な要素は
    黙ってスキップする(parse_known_versionsと同じfail-safe方針)。旧クライアント
    のparse_known_versionsは"known_versions"キーしか読まないため、この関数
    (=このキー)の存在自体が旧クライアントには見えない。"""
    result: List[ConditionalKnownVersion] = []
    if not json_text:
        return result
    try:
        data = json.loads(json_text)
    except (ValueError, TypeError):
        return result
    if not isinstance(data, dict):
        return result
    for item in data.get("known_versions_conditional") or []:
        if not isinstance(item, dict):
            continue
        build_id = item.get("build_id")
        pak_size = item.get("pak_size")
        min_tool_version = item.get("min_tool_version")
        if not build_id or pak_size is None or pak_size < 0 or not min_tool_version:
            continue
        label = item.get("label") or build_id
        result.append(
            ConditionalKnownVersion(
                build_id=str(build_id),
                pak_size=int(pak_size),
                label=str(label),
                min_tool_version=str(min_tool_version),
            )
        )
    return result


def merge_known_good(
    bundled_json: Optional[str], remote_block_json_or_none: Optional[str]
) -> KnownGoodPalworld:
    """MergeKnownGood(L.6263-6281)相当。同梱データ(bundled_json)にリモート
    (remote_block_json_or_none、versions.jsonの"palworld_known_good"部分を
    既に切り出したもの)を重複除去しつつ足し込む。remote_block_json_or_noneが
    None/空なら同梱データのみ(dev#89のオフラインフォールバック)。

    dev#1441: conditional_versions("known_versions_conditional"キー)も同じ
    方針(重複除去しつつ加算)でマージする。重複判定はbuild_id+pak_sizeのみ
    (無条件版versionsと同じ基準。min_tool_versionまで見ると同一build/pakに
    複数条件が同時に存在する余地を残してしまい、判定が曖昧になるため)。"""
    result = KnownGoodPalworld()
    result.versions.extend(parse_known_versions(bundled_json))
    result.manifest_hashes.extend(parse_known_manifest_hashes(bundled_json))
    result.conditional_versions.extend(parse_known_versions_conditional(bundled_json))
    if remote_block_json_or_none:
        for v in parse_known_versions(remote_block_json_or_none):
            dup = any(
                existing.build_id == v.build_id and existing.pak_size == v.pak_size
                for existing in result.versions
            )
            if not dup:
                result.versions.append(v)
        for h in parse_known_manifest_hashes(remote_block_json_or_none):
            if h not in result.manifest_hashes:
                result.manifest_hashes.append(h)
        for cv in parse_known_versions_conditional(remote_block_json_or_none):
            dup = any(
                existing.build_id == cv.build_id and existing.pak_size == cv.pak_size
                for existing in result.conditional_versions
            )
            if not dup:
                result.conditional_versions.append(cv)
    return result


def is_known_version(known: KnownGoodPalworld, build_id: Optional[str], pak_size: int) -> bool:
    """IsKnownVersion(L.6283-6289)相当。"""
    if not build_id:
        return False
    return any(v.build_id == build_id and v.pak_size == pak_size for v in known.versions)


def label_for(known: KnownGoodPalworld, build_id: Optional[str], pak_size: int) -> Optional[str]:
    """LabelFor(L.6291-6296)相当。"""
    for v in known.versions:
        if v.build_id == build_id and v.pak_size == pak_size:
            return v.label
    return None


def is_known_manifest(known: KnownGoodPalworld, manifest_hash: Optional[str]) -> bool:
    """IsKnownManifest(L.6298-6304)相当(大文字小文字を無視して比較)。"""
    if not manifest_hash:
        return False
    return any(h.lower() == manifest_hash.lower() for h in known.manifest_hashes)


def _tool_version_meets_minimum(current_tool_version: Optional[str], min_tool_version: str) -> bool:
    """dev#1441: current_tool_version(自ツール版。例 "v2.10.0")がmin_tool_version
    (例 "2.11.0")以上かを判定する。update_check.parse_versionを再利用し
    (両者ともv/Vプレフィックス吸収+桁不足は0扱いの同じ規約)、桁ごとに比較する。
    どちらか解析不能ならFalse(fail-safe: 判定不能=条件を満たさない扱いとし、
    通常警告を消さない安全側へ倒す)。"""
    current = _parse_tool_version(current_tool_version)
    minimum = _parse_tool_version(min_tool_version)
    if current is None or minimum is None:
        return False
    length = max(len(current), len(minimum))
    for i in range(length):
        cv = current[i] if i < len(current) else 0
        mv = minimum[i] if i < len(minimum) else 0
        if cv != mv:
            return cv > mv
    return True  # 完全一致=最小要件を満たす


def _find_conditional_match(
    known: KnownGoodPalworld, build_id: Optional[str], pak_size: int
) -> Optional[ConditionalKnownVersion]:
    """dev#1441: is_known_version()の条件付き版相当。build_idがあればbuild_id+
    pak_size一致、build_idが無ければpak_sizeのみの一致(is_known_version直下の
    保険経路と同じ規約)で最初の一致を返す。"""
    if build_id is not None:
        for v in known.conditional_versions:
            if v.build_id == build_id and v.pak_size == pak_size:
                return v
        return None
    if pak_size > 0:
        for v in known.conditional_versions:
            if v.pak_size == pak_size:
                return v
    return None


def supported_labels_joined(known: KnownGoodPalworld) -> str:
    """SupportedLabelsJoined(L.6306-6312)相当。"""
    labels: List[str] = []
    for v in known.versions:
        if v.label not in labels:
            labels.append(v.label)
    return ", ".join(labels) if labels else "(none)"


def evaluate(
    known: KnownGoodPalworld,
    det: PalworldDetection,
    manifest_hash: Optional[str],
    current_tool_version: Optional[str] = None,
) -> PalworldCompatStatus:
    """Evaluate(L.6316-6364)相当。純粋なロジックのみ(I/Oなし)。manifest_hashは
    呼び出し側が既に読み込んだ値(無ければNone)を渡す。判定不能(Paksが見つから
    ない)ならdetected=Falseのまま返す。

    dev#1441: current_tool_version(自ツール版、例 "v2.10.0")は条件付き
    エントリ(known.conditional_versions)の判定に使う任意引数。Noneのまま
    (未指定)なら条件付きエントリは常に「未達」扱いになり(_tool_version_
    meets_minimumがNoneをfail-safe側=Falseで返す)、update_hintフィールドの
    セットのみ行われ、should_warnには影響しない(=呼び出し側が明示的に自
    バージョンを渡さない限り、条件付きエントリは無条件エントリのような
    白判定を一切行わない)。"""
    st = PalworldCompatStatus(detected=det.detected, build_id=det.build_id, pak_size=det.pak_size)
    if not det.detected:
        st.should_warn = False
        return st

    if det.build_id is not None and is_known_version(known, det.build_id, det.pak_size):
        st.known_version = True
        st.version_label = label_for(known, det.build_id, det.pak_size)
        st.should_warn = False
        return st

    # 保険経路: buildidが取れない環境でも、pakサイズだけでも既知の値に一致すれば
    # 十分とする(旧PalworldVersionWarning()のサイズ保険と同じ考え方、L.6334-6348)
    if det.build_id is None and det.pak_size > 0:
        for v in known.versions:
            if v.pak_size == det.pak_size:
                st.known_version = True
                st.version_label = v.label
                st.should_warn = False
                return st

    # dev#1441: 条件付きエントリ(known_versions_conditional)の判定。build/pak
    # 指紋が条件付きエントリに一致した場合、min_tool_versionを自ツール版が
    # 満たしていれば無条件版と同じ扱い(should_warn=False)で即returnする。
    # 満たしていなければ通常どおり下の判定(マニフェスト照合→最終警告)へ
    # 進むが、GUI側が「更新で対応済みの可能性」を案内できるようヒントを
    # stへ残しておく。
    conditional_match = _find_conditional_match(known, det.build_id, det.pak_size)
    if conditional_match is not None:
        if _tool_version_meets_minimum(current_tool_version, conditional_match.min_tool_version):
            st.known_version = True
            st.version_label = conditional_match.label
            st.should_warn = False
            return st
        st.update_hint_min_tool_version = conditional_match.min_tool_version
        st.update_hint_version_label = conditional_match.label

    if manifest_hash:
        st.manifest_available = True
        st.manifest_hash = manifest_hash
        if is_known_manifest(known, manifest_hash):
            st.known_manifest = True
            st.should_warn = False
            return st

    st.should_warn = True
    return st


def format_detected(st: PalworldCompatStatus) -> str:
    """FormatDetected(L.6366-6376)相当。"""
    if not st.detected:
        return "not found"
    if st.build_id is not None and st.pak_size > 0:
        return f"build {st.build_id}, pak {st.pak_size:,} bytes"
    if st.build_id is not None:
        return f"build {st.build_id}"
    if st.pak_size > 0:
        return f"pak {st.pak_size:,} bytes"
    return "unknown"


def format_supported(known: KnownGoodPalworld) -> str:
    """FormatSupported(L.6378-6383)相当。"""
    parts = [f"{v.label} (build {v.build_id})" for v in known.versions]
    return ", ".join(parts) if parts else "(none)"


def build_log_line(known: KnownGoodPalworld, st: PalworldCompatStatus) -> str:
    """BuildLogLine(L.6387-6399)相当。dev#87: 診断ログヘッダ用の1行。検出成否・
    版番号・マニフェスト自己判定の結果を必ず数字入りで残す(検出失敗時も
    "not found"の事実を残す)。"""
    supported = format_supported(known)
    if not st.detected:
        return f"palworld: not found (supported: {supported})"
    if st.known_version:
        return f"palworld: {st.version_label} (build {st.build_id}) (supported: {supported})"
    if st.manifest_available:
        note = (
            "extracted materials match known-good, warning suppressed (dev#91)"
            if st.known_manifest
            else "extracted materials differ from known-good"
        )
    else:
        note = "extraction manifest not available yet"
    return f"palworld: unknown ({format_detected(st)}) (supported: {supported}) [{note}]"
