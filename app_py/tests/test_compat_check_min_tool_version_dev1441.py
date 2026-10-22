# test_compat_check_min_tool_version_dev1441.py -- dev#1441受入試験。
#
# 背景: 従来のPalworld互換白リスト(app_py\compat_check.py の known_versions)は
# 「ツールバージョンによらず全員に効く」ため、「このPalworld buildは本ツール
# vX.Y以上でのみ対応」を表現できなかった(SKILL.md palworld-update「あるべき姿
# vs 現状」節)。本WPは条件付きエントリ(min_tool_version)を、既存の
# "known_versions"キーとは別の最上位キー"known_versions_conditional"として
# 追加する(理由: 既存の"known_versions"配下に条件を足すと、dev#1441より前の
# 旧クライアントがそのフィールドを無視して無条件に白判定してしまう
# fail-unsafeな挙動になるため。別キーなら旧クライアントはこのキーの存在自体を
# 知らず、単に恩恵を受けないだけで誤動作しない)。
#
# 受入条件(BRIEF.md):
#   (a) min_tool_version以上の新クライアントで警告が消える
#   (b) 未満では警告+更新示唆が出る
#   (c) 条件なしエントリの従来挙動が完全不変
#   (d) 旧パーサ相当(現行コードのコピーでなく、公開済み挙動を再現するテスト)が
#       条件付きエントリで誤白判定しないこと -- 負の対照込み
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import compat_check as cc  # noqa: E402
import i18n  # noqa: E402
from ui import main_window as mw  # noqa: E402

BUNDLED_JSON = (
    '{"known_versions":[{"build_id":"111","pak_size":1000,"label":"1.0.1"}],'
    '"known_vanilla_manifest_sha256":["aaaa"]}'
)

CONDITIONAL_JSON = (
    '{"known_versions":[{"build_id":"111","pak_size":1000,"label":"1.0.1"}],'
    '"known_versions_conditional":[{"build_id":"777","pak_size":7777,'
    '"label":"1.0.4","min_tool_version":"2.11.0"}],'
    '"known_vanilla_manifest_sha256":["aaaa"]}'
)


# ===========================================================================
# (a) min_tool_version以上の新クライアントで警告が消える
# ===========================================================================


def test_conditional_entry_suppresses_warning_when_tool_meets_minimum():
    known = cc.merge_known_good(CONDITIONAL_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="777", pak_size=7777)

    st_equal = cc.evaluate(known, det, None, current_tool_version="v2.11.0")
    assert st_equal.known_version is True
    assert st_equal.version_label == "1.0.4"
    assert st_equal.should_warn is False
    assert st_equal.update_hint_min_tool_version is None

    st_above = cc.evaluate(known, det, None, current_tool_version="v2.12.0")
    assert st_above.should_warn is False


def test_conditional_entry_pak_only_fallback_when_build_id_absent():
    """dev#1441: build_idが取れない環境(Xbox App版等)でも、is_known_versionの
    保険経路と同じく pak_size のみの一致で条件付きエントリを判定できること。"""
    known = cc.merge_known_good(CONDITIONAL_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id=None, pak_size=7777)
    st = cc.evaluate(known, det, None, current_tool_version="v2.11.0")
    assert st.known_version is True
    assert st.should_warn is False


# ===========================================================================
# (b) 未満では警告+更新示唆が出る
# ===========================================================================


def test_conditional_entry_warns_with_hint_when_tool_below_minimum():
    known = cc.merge_known_good(CONDITIONAL_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="777", pak_size=7777)

    st = cc.evaluate(known, det, None, current_tool_version="v2.10.0")

    assert st.should_warn is True
    assert st.known_version is False
    assert st.update_hint_min_tool_version == "2.11.0"
    assert st.update_hint_version_label == "1.0.4"


def test_conditional_entry_without_current_tool_version_never_suppresses():
    """current_tool_versionを渡さない(=Noneのまま呼ぶ)呼び出し元は、
    条件付きエントリが存在してもfail-safe側(常に「未達」扱い)へ倒れ、
    無条件エントリのような白判定を一切行わない(evaluate()のdocstring通り)。"""
    known = cc.merge_known_good(CONDITIONAL_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="777", pak_size=7777)

    st = cc.evaluate(known, det, None)  # current_tool_version省略

    assert st.should_warn is True
    assert st.update_hint_min_tool_version == "2.11.0"


def test_conditional_entry_unparseable_tool_version_fails_safe():
    known = cc.merge_known_good(CONDITIONAL_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="777", pak_size=7777)
    st = cc.evaluate(known, det, None, current_tool_version="not-a-version")
    assert st.should_warn is True
    assert st.update_hint_min_tool_version == "2.11.0"


def test_main_window_never_shows_dialog_even_with_update_hint_negative_control(monkeypatch):
    """dev#1658(オーナー裁定): 起動時の版不一致警告ダイアログは廃止された。
    update_hintが立つ(=dev#1441の条件付きエントリに一致するが自ツール版が
    未達の)ケースであっても、messagebox.showwarningは一切呼ばれないこと
    (負の対照)。判定結果は診断ログにのみ記録され、ヒント情報もそちらに
    残る(常設ラベルLabelVerifiedPalworldVersionFormatが今後の唯一の開示
    経路であり、ダイアログ・ポップアップの類は「普通のユーザーにまったく
    気にならない」の要件どおり一切出さない)。
    実tk窓は開かず、threading.Thread/root.afterのみ即時実行に差し替える。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")

        class _FakeSelf:
            def __init__(self) -> None:
                self.logs: list[str] = []

            def _log(self, text: str) -> None:
                self.logs.append(text)

        fake_self = _FakeSelf()

        known = cc.merge_known_good(CONDITIONAL_JSON, None)
        det = cc.PalworldDetection(detected=True, build_id="777", pak_size=7777)
        st = cc.evaluate(known, det, None, current_tool_version="v2.10.0")
        assert st.should_warn and st.update_hint_min_tool_version == "2.11.0"  # 前提確認

        fake_self._resolve_palworld_compat_status = lambda **_k: (st, known)
        fake_self._update_check_done = None

        class _FakeRoot:
            def after(self, _ms, fn) -> None:
                fn()

        fake_self.root = _FakeRoot()

        shown: list[tuple] = []
        monkeypatch.setattr(mw.messagebox, "showwarning", lambda *a: shown.append(a))

        class _ImmediateThread:
            def __init__(self, target=None, daemon=None, name=None) -> None:
                self._target = target

            def start(self) -> None:
                self._target()

        monkeypatch.setattr(mw.threading, "Thread", _ImmediateThread)

        mw.MainWindow._check_palworld_version_once(fake_self)

        assert shown == [], "廃止されたはずの版不一致警告ダイアログが表示された(dev#1658)"
        assert any("2.11.0" in line for line in fake_self.logs), "診断ログにヒントが記録されていない"
    finally:
        i18n.clear_registry()


def test_main_window_never_shows_dialog_without_update_hint_negative_control(monkeypatch):
    """負の対照(その2): 条件付きエントリに一切一致しない通常の版不一致でも
    同様にダイアログは一切出ない(dev#1658)。診断ログには通常の不一致行が
    残る(ヒント文言は付かない)。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")

        class _FakeSelf:
            def __init__(self) -> None:
                self.logs: list[str] = []

            def _log(self, text: str) -> None:
                self.logs.append(text)

        fake_self = _FakeSelf()

        known = cc.merge_known_good(BUNDLED_JSON, None)
        det = cc.PalworldDetection(detected=True, build_id="999", pak_size=9999)
        st = cc.evaluate(known, det, "unknown-hash", current_tool_version="v2.10.0")
        assert st.should_warn and st.update_hint_min_tool_version is None  # 前提確認

        fake_self._resolve_palworld_compat_status = lambda **_k: (st, known)
        fake_self._update_check_done = None

        class _FakeRoot:
            def after(self, _ms, fn) -> None:
                fn()

        fake_self.root = _FakeRoot()

        shown: list[tuple] = []
        monkeypatch.setattr(mw.messagebox, "showwarning", lambda *a: shown.append(a))

        class _ImmediateThread:
            def __init__(self, target=None, daemon=None, name=None) -> None:
                self._target = target

            def start(self) -> None:
                self._target()

        monkeypatch.setattr(mw.threading, "Thread", _ImmediateThread)

        mw.MainWindow._check_palworld_version_once(fake_self)

        assert shown == [], "廃止されたはずの版不一致警告ダイアログが表示された(dev#1658)"
        assert fake_self.logs, "判定結果が診断ログにすら記録されていない"
        assert "update hint" not in fake_self.logs[0]
    finally:
        i18n.clear_registry()


def test_evaluate_palworld_compat_now_passes_tool_version(tmp_path, monkeypatch):
    """main_window._evaluate_palworld_compat_now()がTOOL_VERSIONを
    compat_check.evaluate()のcurrent_tool_versionへ実際に渡していること
    (「実装した」と「効いている」は別、CLAUDE.md検証の作法の順守)。"""

    class _FakeSelf:
        def __init__(self, app_root: str) -> None:
            self.app_root = app_root
            self.work_root = str(tmp_path / "work")
            self._paks_dir_cache = None
            self._remote_known_good_json = None

        _known_good_bundled_path = mw.MainWindow._known_good_bundled_path
        _load_known_good_palworld = mw.MainWindow._load_known_good_palworld
        _palworld_manifest_breadcrumb_path = mw.MainWindow._palworld_manifest_breadcrumb_path
        _read_manifest_combined_hash = mw.MainWindow._read_manifest_combined_hash

        def _detect_palworld_version(self):
            return cc.PalworldDetection(detected=True, build_id="777", pak_size=7777)

    pipeline_py = tmp_path / "pipeline" / "py"
    pipeline_py.mkdir(parents=True)
    (pipeline_py / "known_good_palworld.json").write_text(CONDITIONAL_JSON, encoding="utf-8")

    fake_self = _FakeSelf(app_root=str(tmp_path))

    captured = {}
    real_evaluate = cc.evaluate

    def recording_evaluate(known, det, manifest_hash, current_tool_version=None):
        captured["current_tool_version"] = current_tool_version
        return real_evaluate(known, det, manifest_hash, current_tool_version)

    monkeypatch.setattr(mw.compat_check, "evaluate", recording_evaluate)

    st, _known = mw.MainWindow._evaluate_palworld_compat_now(fake_self)

    assert captured["current_tool_version"] == mw.TOOL_VERSION, (
        "_evaluate_palworld_compat_now()がTOOL_VERSIONをcompat_check.evaluate()へ"
        "渡していない(dev#1441の配線漏れ)"
    )
    # TOOL_VERSION(2026-08-15時点 v2.10.0)は"2.11.0"未満のはずなので、
    # 条件付きエントリは未達でヒントだけがセットされる(=製品コード上でも
    # 実際に効いていることの追加確認)。将来TOOL_VERSIONが2.11.0以上に
    # なったら、この特定のassertではなくcaptured側の配線確認だけで十分。
    if not cc._tool_version_meets_minimum(mw.TOOL_VERSION, "2.11.0"):
        assert st.update_hint_min_tool_version == "2.11.0"


# ===========================================================================
# (c) 条件なしエントリの従来挙動が完全不変
# ===========================================================================


def test_unconditional_entries_behavior_unchanged_when_conditional_present():
    """known_versions_conditionalを追加しても、無条件のknown_versionsに
    対する既存の3階層判定(既知版番号->マニフェスト->警告)は一切影響を
    受けないこと。tests\\shipcheck\\test_palworld_compat.py /
    app_py\\tests\\test_diagnostics.py のcase1-9相当をCONDITIONAL_JSON
    (conditional_versionsを含むデータ)でも再確認する。"""
    known = cc.merge_known_good(CONDITIONAL_JSON, None)

    # case1: 既知版番号は従来どおり警告なし
    det1 = cc.PalworldDetection(detected=True, build_id="111", pak_size=1000)
    st1 = cc.evaluate(known, det1, None)
    assert st1.known_version and not st1.should_warn
    assert st1.update_hint_min_tool_version is None

    # case3: 未知版番号でもマニフェスト一致で警告なし
    det2 = cc.PalworldDetection(detected=True, build_id="999", pak_size=9999)
    st2 = cc.evaluate(known, det2, "aaaa")
    assert st2.manifest_available and st2.known_manifest and not st2.should_warn

    # case4(負の対照): 未知版番号・マニフェスト不一致は従来どおり警告
    st3 = cc.evaluate(known, det2, "zzzz")
    assert st3.should_warn and st3.manifest_available and not st3.known_manifest
    assert st3.update_hint_min_tool_version is None

    # 完全未知(条件付きにも一致しない)build_idは従来どおり警告
    det3 = cc.PalworldDetection(detected=True, build_id="000", pak_size=1)
    st4 = cc.evaluate(known, det3, None)
    assert st4.should_warn
    assert st4.update_hint_min_tool_version is None

    # supported_labels_joined/format_supportedはconditional_versionsを
    # 含めない(無条件版のみ列挙、GUI常時表示に未達の版が紛れ込まない)
    assert cc.supported_labels_joined(known) == "1.0.1"
    assert "1.0.4" not in cc.format_supported(known)


def test_conditional_versions_field_defaults_empty_for_plain_data():
    """通常のknown_versions_conditionalキーを含まないJSONでは
    conditional_versionsが空のままであること(既存の全JSONサンプルに対する
    後方互換の再確認)。"""
    known = cc.merge_known_good(BUNDLED_JSON, None)
    assert known.conditional_versions == []


def test_merge_known_good_merges_conditional_versions_additively_and_dedups():
    remote = (
        '{"known_versions_conditional":[{"build_id":"888","pak_size":8888,'
        '"label":"1.0.5","min_tool_version":"2.12.0"}]}'
    )
    known = cc.merge_known_good(CONDITIONAL_JSON, remote)
    labels = {v.label for v in known.conditional_versions}
    assert labels == {"1.0.4", "1.0.5"}, "同梱+リモートが重複なく加算されていない"

    # 重複除去: 同じbuild_id+pak_sizeのリモートエントリを足しても増えない
    dup_remote = (
        '{"known_versions_conditional":[{"build_id":"777","pak_size":7777,'
        '"label":"1.0.4-dup","min_tool_version":"9.9.9"}]}'
    )
    known2 = cc.merge_known_good(CONDITIONAL_JSON, dup_remote)
    assert len(known2.conditional_versions) == 1
    assert known2.conditional_versions[0].label == "1.0.4"  # 同梱側が優先(既存versionsと同じ規約)


def test_parse_known_versions_conditional_skips_malformed_entries():
    missing_min_version = (
        '{"known_versions_conditional":[{"build_id":"1","pak_size":1,"label":"a"}]}'
    )
    assert cc.parse_known_versions_conditional(missing_min_version) == []

    missing_build_id = (
        '{"known_versions_conditional":[{"pak_size":1,"label":"a","min_tool_version":"2.0.0"}]}'
    )
    assert cc.parse_known_versions_conditional(missing_build_id) == []

    negative_pak_size = (
        '{"known_versions_conditional":[{"build_id":"1","pak_size":-1,"label":"a",'
        '"min_tool_version":"2.0.0"}]}'
    )
    assert cc.parse_known_versions_conditional(negative_pak_size) == []

    ok = cc.parse_known_versions_conditional(
        '{"known_versions_conditional":[{"build_id":"1","pak_size":1,'
        '"min_tool_version":"2.0.0"}]}'
    )
    assert len(ok) == 1 and ok[0].label == "1"  # labelが無ければbuild_idを流用(無条件版と同じ規約)


# ===========================================================================
# (d) 旧パーサ相当(現行コードのコピーでなく、公開済み挙動を再現するテスト)が
#     条件付きエントリで誤白判定しないこと -- 負の対照込み
#
# ここでの「旧パーサ」は、dev#1441より前に公開済みのapp_py\compat_check.pyの
# parse_known_versions/merge_known_good/is_known_versionが実際にどう動くかを、
# compat_check.pyを一切importせず独立に再実装したもの(旧クライアントの実機を
# 手元に用意できないため、公開済みの設計--「known_versionsキーの配列を
# json.loadsで読み、要素からbuild_id/pak_sizeを引く。未知フィールドは単に
# 無視される(item.get()の一般的な性質そのもの、明示的なホワイトリストで
# フィールドを絞っていない)」--をそのまま再現する)。
# ===========================================================================


def _legacy_parse_known_versions(json_text):
    """dev#1441より前に公開されていたcompat_check.parse_known_versions()相当の
    独立再実装。"known_versions"キーの配列だけを読む(新設の
    "known_versions_conditional"キーの存在を一切知らない)。"""
    if not json_text:
        return []
    try:
        data = json.loads(json_text)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    result = []
    for item in data.get("known_versions") or []:
        if not isinstance(item, dict):
            continue
        build_id = item.get("build_id")
        pak_size = item.get("pak_size")
        if not build_id or pak_size is None or pak_size < 0:
            continue
        label = item.get("label") or build_id
        # 旧パーサはmin_tool_version等の未知フィールドを単に無視する
        # (item.get()で必要なキーだけを個別に取り出す実装だったため)。
        result.append({"build_id": str(build_id), "pak_size": int(pak_size), "label": str(label)})
    return result


def _legacy_is_known_version(versions, build_id, pak_size):
    if not build_id:
        return False
    return any(v["build_id"] == build_id and v["pak_size"] == pak_size for v in versions)


def test_legacy_parser_is_blind_to_the_new_conditional_key_negative_control():
    """負の対照(受入(d)本体): dev#1441の実際の設計どおり、条件付きエントリを
    "known_versions"とは別の"known_versions_conditional"キーに置いた場合、
    旧パーサはそのキーの存在自体を認識せず、対象build/pakを白判定しない
    (=旧クライアントは従来どおり汎用警告を出し続けるだけで、誤って安全と
    誤認することは無い)。"""
    legacy_versions = _legacy_parse_known_versions(CONDITIONAL_JSON)
    # 旧パーサが読めるのは無条件エントリ(build_id=111)だけ
    assert {v["build_id"] for v in legacy_versions} == {"111"}
    # 条件付きエントリのbuild/pak(777/7777)は旧パーサの視界に一切入らない
    assert not _legacy_is_known_version(legacy_versions, "777", 7777)


def test_legacy_parser_would_misjudge_if_conditional_data_had_been_placed_inside_known_versions():
    """負の対照(採用しなかった危険な設計の実証): もし仮に条件付きエントリを
    別キーではなく"known_versions"配列の要素へ直接min_tool_versionフィールド
    として足していたら、旧パーサはそのフィールドを単に無視して無条件で
    白判定してしまっていたはず、という「別キーを選んだ理由」そのものを
    再現する。この挙動は現行実装(known_versions_conditionalという別キー)
    では発生しない(上のtest_legacy_parser_is_blind_to_the_new_conditional_
    key_negative_controlが示すとおり)ことの対比になっている。"""
    unsafe_design_json = (
        '{"known_versions":[{"build_id":"777","pak_size":7777,"label":"1.0.4",'
        '"min_tool_version":"2.11.0"}]}'
    )
    legacy_versions = _legacy_parse_known_versions(unsafe_design_json)
    # 旧パーサはmin_tool_versionを無視し、無条件で白判定してしまう
    # (=これが起きないよう、実装では別キーを選んだことの実証)
    assert _legacy_is_known_version(legacy_versions, "777", 7777) is True


def test_legacy_parser_reproduction_matches_current_unconditional_parser_output():
    """旧パーサの独立再実装が、現行compat_check.parse_known_versions()の
    (無条件エントリに対する)出力と一致することの確認(再現の忠実性の裏取り)。"""
    legacy = _legacy_parse_known_versions(BUNDLED_JSON)
    current = cc.parse_known_versions(BUNDLED_JSON)
    assert [(v["build_id"], v["pak_size"], v["label"]) for v in legacy] == [
        (v.build_id, v.pak_size, v.label) for v in current
    ]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
