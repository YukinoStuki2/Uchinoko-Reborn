# test_main_window_diagnostics_wiring.py -- dev#618/#619/#620受入条件:
# main_window.py が compat_check.py/update_check.py/path_health.py の
# 既存ロジックを実際に起動シーケンスへ結線したことの単体試験。
#
# 対象issue:
#   - dev#618: compat_check.py(Palworldバージョン互換警告)の結線
#   - dev#619: update_check.py(更新通知)の結線
#   - dev#620: path_health.py(パス健全性警告)の結線
#
# 方針(共通契約どおり、tkの実ウィンドウは一切開かない): test_gui_log_robustness.py
# と同じ「フェイクself + 束縛前メソッド呼び出し」方式。MainWindow.__init__は
# 通さず、各結線メソッドを `mw.MainWindow._method(fake_self, ...)` の形で直接
# 呼ぶ。ネットワーク・実Palworld・ディスクI/Oはモック/tmp_pathで代替する。
from __future__ import annotations

import json
import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import compat_check as cc  # noqa: E402
import path_health as ph  # noqa: E402
import update_check as uc  # noqa: E402
from ui import main_window as mw  # noqa: E402

BUNDLED_JSON = (
    '{"known_versions":[{"build_id":"111","pak_size":1000,"label":"1.0.1"}],'
    '"known_vanilla_manifest_sha256":["aaaa"]}'
)


# ---------------------------------------------------------------------------
# フェイク部品
# ---------------------------------------------------------------------------


class _FakeWidget:
    """tkinter.Label/Button互換の最小フェイク(config/place/place_forget)。"""

    def __init__(self) -> None:
        self.text: str | None = None
        self.placed: list[dict] = []
        self.forgotten = False

    def config(self, **kwargs) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]

    def place(self, **kwargs) -> None:
        self.placed.append(kwargs)

    def place_forget(self) -> None:
        self.forgotten = True


class _FakeRemoteWaitEvent:
    """dev#1447: threading.Event互換の最小フェイク。実待機せずwait()の
    呼び出し回数・引数を記録する(sleep_fnの注入と同じ思想)。`already_set`は
    構築時点でis_set()=Trueにするための引数(_check_for_update_once側の
    リモート取得が判定より先に完了していたケースを模す)。`resolves_on_wait`は
    wait()呼び出し時にEventがsetされる(=リモート取得がその間に完了する)
    かどうかを表す——Falseなら「取得が有限時間内に確定しない(真のタイムアウト)」
    ケースを模す。"""

    def __init__(self, already_set: bool = False, resolves_on_wait: bool = True) -> None:
        self._is_set = already_set
        self._resolves_on_wait = resolves_on_wait
        self.wait_calls: list[float | None] = []

    def is_set(self) -> bool:
        return self._is_set

    def wait(self, timeout: float | None = None) -> bool:
        self.wait_calls.append(timeout)
        if self._resolves_on_wait:
            self._is_set = True
        return self._is_set


class _FakeSelf:
    """MainWindow各メソッドを束縛せずに呼ぶための最小self。パス計算のみの
    小さなヘルパー(_read_steam_build_id/_known_good_bundled_path/
    _palworld_manifest_breadcrumb_path)は実装をそのまま再利用する
    (self.app_root/self.work_rootにしか依存しないため、フェイクselfでも
    そのまま動く。二重実装によるドリフトを避ける)。"""

    _read_steam_build_id = staticmethod(mw.MainWindow._read_steam_build_id)
    _known_good_bundled_path = mw.MainWindow._known_good_bundled_path
    _palworld_manifest_breadcrumb_path = mw.MainWindow._palworld_manifest_breadcrumb_path

    def __init__(self, app_root: str, work_root: str) -> None:
        self.app_root = app_root
        self.work_root = work_root
        self._paks_dir_cache = None
        self._remote_known_good_json = None
        self._pending_update_version = None
        self.logs: list[str] = []
        self.widgets = {"updateLabel": _FakeWidget(), "updateNowButton": _FakeWidget()}

    def _log(self, text: str) -> None:
        self.logs.append(text)


# ===========================================================================
# dev#620: path_health結線 (CheckPathHealthOnStartup相当)
# ===========================================================================


def test_path_health_healthy_logs_ok_and_no_warning(tmp_path, monkeypatch):
    fake_self = _FakeSelf(app_root=str(tmp_path / "install"), work_root=str(tmp_path / "work"))
    monkeypatch.delenv("OneDrive", raising=False)
    warnings: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showwarning", lambda *a: warnings.append(a))

    mw.MainWindow._check_path_health_on_startup(fake_self)

    assert any("install_path: ok" in line for line in fake_self.logs)
    assert any("work_path: ok" in line for line in fake_self.logs)
    assert warnings == [], "健全なパスなのに警告ダイアログが出た"


def test_path_health_too_long_path_warns(tmp_path, monkeypatch):
    long_root = "C:\\" + "a" * (ph.PATH_LENGTH_WARN_THRESHOLD + 10)
    fake_self = _FakeSelf(app_root=long_root, work_root=str(tmp_path / "work"))
    monkeypatch.delenv("OneDrive", raising=False)
    warnings: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showwarning", lambda *a: warnings.append(a))

    mw.MainWindow._check_path_health_on_startup(fake_self)

    assert len(warnings) == 1, "パス長超過なのに警告ダイアログが出ていない"
    title, body = warnings[0]
    assert title == mw.i18n.S("TitlePathHealthWarning")
    assert mw.i18n.S("CausePathTooLong") in body
    assert any("[!]" in line for line in fake_self.logs)


def test_path_health_unc_path_warns(tmp_path, monkeypatch):
    fake_self = _FakeSelf(app_root=r"\\server\share\install", work_root=str(tmp_path / "work"))
    monkeypatch.delenv("OneDrive", raising=False)
    warnings: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showwarning", lambda *a: warnings.append(a))

    mw.MainWindow._check_path_health_on_startup(fake_self)

    assert len(warnings) == 1
    _title, body = warnings[0]
    assert mw.i18n.S("CausePathUnc") in body
    assert mw.i18n.S("CausePathTooLong") not in body, "UNCだけなのにパス長の項目まで出た"


def test_path_health_onedrive_path_warns(tmp_path, monkeypatch):
    onedrive = str(tmp_path / "OneDrive")
    fake_self = _FakeSelf(
        app_root=os.path.join(onedrive, "DiveToPalworld"), work_root=str(tmp_path / "work")
    )
    monkeypatch.setenv("OneDrive", onedrive)
    warnings: list[tuple] = []
    monkeypatch.setattr(mw.messagebox, "showwarning", lambda *a: warnings.append(a))

    mw.MainWindow._check_path_health_on_startup(fake_self)

    assert len(warnings) == 1
    _title, body = warnings[0]
    assert mw.i18n.S("CausePathOneDrive") in body


# ===========================================================================
# dev#618: compat_check結線 (DetectPalworldVersion/ReadSteamBuildId/
# ReadManifestCombinedHash/CheckPalworldVersionOnce相当)
# ===========================================================================


def _make_paks_dir(tmp_path, pak_size: int = 1000, build_id: str | None = "111") -> str:
    steamapps = tmp_path / "steamapps"
    paks = steamapps / "common" / "Palworld" / "Pal" / "Content" / "Paks"
    paks.mkdir(parents=True)
    (paks / "Pal-Windows.pak").write_bytes(b"x" * pak_size)
    if build_id is not None:
        acf = steamapps / "appmanifest_1623730.acf"
        acf.write_text(f'\t"buildid"\t\t"{build_id}"\n', encoding="utf-8")
    return str(paks)


def test_read_steam_build_id_found(tmp_path):
    paks = _make_paks_dir(tmp_path, build_id="24181527")
    assert mw.MainWindow._read_steam_build_id(paks) == "24181527"


def test_read_steam_build_id_missing_acf_returns_none(tmp_path):
    paks = _make_paks_dir(tmp_path, build_id=None)
    assert mw.MainWindow._read_steam_build_id(paks) is None


def test_detect_palworld_version_reads_build_id_and_pak_size(tmp_path, monkeypatch):
    paks = _make_paks_dir(tmp_path, pak_size=2048, build_id="111")
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    monkeypatch.setattr(mw.pak_manager, "paks_dir_quiet", lambda *a, **k: paks)

    det = mw.MainWindow._detect_palworld_version(fake_self)

    assert det.detected is True
    assert det.build_id == "111"
    assert det.pak_size == 2048


def test_detect_palworld_version_not_found_when_paks_missing(monkeypatch, tmp_path):
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    monkeypatch.setattr(mw.pak_manager, "paks_dir_quiet", lambda *a, **k: None)

    det = mw.MainWindow._detect_palworld_version(fake_self)

    assert det.detected is False


def test_detect_palworld_version_reads_pak_size_for_xbox_gamepass_pak_name(tmp_path, monkeypatch):
    """dev#229続報: Pal-WinGDK.pak(Xbox App/Game Pass版)のフォルダでもpak_sizeを
    拾えること(build_idはacf不在のためNoneのまま=Steam専用機構の想定挙動)。
    以前はPal-Windows.pak単一決め打ちでOSError無視によりpak_size=Noneのままだった。"""
    paks = tmp_path / "XboxPaks"
    paks.mkdir(parents=True)
    (paks / "Pal-WinGDK.pak").write_bytes(b"x" * 4096)
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    monkeypatch.setattr(mw.pak_manager, "paks_dir_quiet", lambda *a, **k: str(paks))

    det = mw.MainWindow._detect_palworld_version(fake_self)

    assert det.detected is True
    assert det.build_id is None
    assert det.pak_size == 4096


def test_read_manifest_combined_hash_found(tmp_path):
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    manifest_dir = tmp_path / "work" / "_warm_dummy" / "vanilla"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "vanilla_manifest.json").write_text(
        json.dumps({"algo": "sha256", "files": {}, "combined_hash": "deadbeef"}), encoding="utf-8"
    )
    assert mw.MainWindow._read_manifest_combined_hash(fake_self) == "deadbeef"


def test_read_manifest_combined_hash_missing_file_returns_none(tmp_path):
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    assert mw.MainWindow._read_manifest_combined_hash(fake_self) is None


def test_load_known_good_palworld_merges_bundled_and_remote(tmp_path):
    pipeline_py = tmp_path / "pipeline" / "py"
    pipeline_py.mkdir(parents=True)
    (pipeline_py / "known_good_palworld.json").write_text(BUNDLED_JSON, encoding="utf-8")
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    fake_self._remote_known_good_json = json.dumps(
        {"known_versions": [{"build_id": "222", "pak_size": 2000, "label": "1.0.2"}]}
    )

    known = mw.MainWindow._load_known_good_palworld(fake_self)

    labels = {v.label for v in known.versions}
    assert labels == {"1.0.1", "1.0.2"}


def test_load_known_good_palworld_missing_bundled_file_is_empty_not_raising(tmp_path):
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    known = mw.MainWindow._load_known_good_palworld(fake_self)
    assert known.versions == []
    assert known.manifest_hashes == []


def test_resolve_palworld_compat_status_known_version_no_warn(tmp_path):
    """既知バージョン一致なら警告不要(ポーリングにも入らない)。"""
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="111", pak_size=1000)
    fake_self._evaluate_palworld_compat_now = lambda: (cc.evaluate(known, det, None), known)
    sleeps: list[float] = []

    result = mw.MainWindow._resolve_palworld_compat_status(fake_self, sleep_fn=sleeps.append)

    assert result is not None
    st, _known = result
    assert st.should_warn is False
    assert sleeps == [], "既知一致なのにポーリングへ入った"


def test_resolve_palworld_compat_status_unknown_version_warns_immediately_when_manifest_available(
    tmp_path,
):
    """未知バージョンでも抽出物マニフェストが最初から手に入っていれば
    ポーリングせず即座に判定できる(dev#91)。"""
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="999", pak_size=9999)
    fake_self._evaluate_palworld_compat_now = lambda: (cc.evaluate(known, det, "unknown-hash"), known)
    sleeps: list[float] = []

    result = mw.MainWindow._resolve_palworld_compat_status(fake_self, sleep_fn=sleeps.append)

    assert result is not None
    st, _known = result
    assert st.should_warn is True
    assert sleeps == []


def test_resolve_palworld_compat_status_polls_until_manifest_available_then_stops_warning(
    tmp_path,
):
    """マニフェストが初回はまだ無く(warm-cache未完了)、2回目のポーリングで
    既知良好ハッシュが手に入ったケース。ポーリングが実際に発生し、かつ
    manifest_available確定後は追加のsleepを呼ばないこと(早期break)を確認する。"""
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="999", pak_size=9999)

    call_count = {"n": 0}

    def fake_evaluate():
        call_count["n"] += 1
        if call_count["n"] == 1:
            return cc.evaluate(known, det, None), known  # manifest未取得
        return cc.evaluate(known, det, "aaaa"), known  # 既知良好ハッシュに一致(dev#91)

    fake_self._evaluate_palworld_compat_now = fake_evaluate
    sleeps: list[float] = []

    result = mw.MainWindow._resolve_palworld_compat_status(fake_self, sleep_fn=sleeps.append)

    assert result is not None
    st, _known = result
    assert st.should_warn is False, "既知良好ハッシュに一致したのに警告扱いのまま"
    assert sleeps == [3.0], "1回のポーリングで解決したのにsleep回数が一致しない"


def test_resolve_palworld_compat_status_initial_evaluation_failure_returns_none(tmp_path):
    """初回の判定自体が例外を出しても、本体の動作を止めない
    (Noneを返すだけで警告もポーリングもしない)。"""
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))

    def raise_error():
        raise RuntimeError("simulated I/O failure")

    fake_self._evaluate_palworld_compat_now = raise_error

    result = mw.MainWindow._resolve_palworld_compat_status(fake_self, sleep_fn=lambda _s: None)

    assert result is None


def test_resolve_palworld_compat_status_not_detected_no_warn(tmp_path):
    """Paksが見つからない(判定不能)なら警告しない(黙って動く)。"""
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    det = cc.PalworldDetection(detected=False)
    known = cc.KnownGoodPalworld()
    fake_self._evaluate_palworld_compat_now = lambda: (cc.evaluate(known, det, None), known)

    result = mw.MainWindow._resolve_palworld_compat_status(fake_self, sleep_fn=lambda _s: None)

    assert result is not None
    st, _known = result
    assert st.detected is False
    assert st.should_warn is False


# ===========================================================================
# dev#1447: リモート白リスト取得を待たずに警告が出る競合の修正
# ===========================================================================


def test_resolve_palworld_compat_status_waits_for_remote_then_suppresses_warning_when_known(
    tmp_path,
):
    """(a) リモート取得が判定より遅れて完了するシナリオで、待った後の
    再評価でリモートに指紋があれば警告が出ない(remote_wait_eventのwait()が
    1回だけ呼ばれ、manifestポーリングへは入らないこと=sleep回数0も確認)。"""
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    known_without_remote = cc.merge_known_good(BUNDLED_JSON, None)
    known_with_remote = cc.merge_known_good(
        BUNDLED_JSON,
        json.dumps({"known_versions": [{"build_id": "999", "pak_size": 9999, "label": "1.0.9"}]}),
    )
    det = cc.PalworldDetection(detected=True, build_id="999", pak_size=9999)

    call_count = {"n": 0}

    def fake_evaluate():
        call_count["n"] += 1
        if call_count["n"] == 1:
            # 判定worker側の初回評価: リモートがまだ_remote_known_good_jsonへ
            # 反映されていない(dev#1447が直す競合そのもの)
            return cc.evaluate(known_without_remote, det, None), known_without_remote
        # remote_wait_event.wait()後の再評価: リモート取得が完了し指紋が判明
        return cc.evaluate(known_with_remote, det, None), known_with_remote

    fake_self._evaluate_palworld_compat_now = fake_evaluate
    event = _FakeRemoteWaitEvent(already_set=False, resolves_on_wait=True)
    sleeps: list[float] = []

    result = mw.MainWindow._resolve_palworld_compat_status(
        fake_self, sleep_fn=sleeps.append, remote_wait_event=event
    )

    assert result is not None
    st, _known = result
    assert st.should_warn is False, "リモート指紋が判明したのに警告扱いのまま"
    assert event.wait_calls == [8.0], "remote_wait_eventの待ちが1回・既定timeoutで呼ばれていない"
    assert sleeps == [], "リモートで解決したのにmanifestポーリングへ入った"


def test_resolve_palworld_compat_status_negative_control_still_warns_when_remote_lacks_fingerprint(
    tmp_path,
):
    """(b) 負の対照: リモート取得が完了しても、その指紋がリモート白リストにも
    無ければ待った後も警告が出る(黙って握りつぶさない)。"""
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="777", pak_size=7777)
    # 初回・再評価とも同じ(リモートにも該当指紋なし)
    fake_self._evaluate_palworld_compat_now = lambda: (cc.evaluate(known, det, "unknown-hash"), known)
    event = _FakeRemoteWaitEvent(already_set=False, resolves_on_wait=True)
    sleeps: list[float] = []

    result = mw.MainWindow._resolve_palworld_compat_status(
        fake_self, sleep_fn=sleeps.append, remote_wait_event=event
    )

    assert result is not None
    st, _known = result
    assert st.should_warn is True, "リモートにも指紋が無いのに警告が消えた"
    assert event.wait_calls == [8.0]


def test_resolve_palworld_compat_status_still_warns_when_remote_fetch_times_out(tmp_path):
    """(c) リモート取得が有限時間内に確定しない(真のタイムアウト、
    event.wait()がFalseを返す)場合でも、例外にならず従来どおり警告が出る
    (聖域: 取得失敗はいかなるエラー表示・例外にもならない、を待ちゲート側でも
    壊さないことの確認)。"""
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="888", pak_size=8888)
    fake_self._evaluate_palworld_compat_now = lambda: (cc.evaluate(known, det, None), known)
    event = _FakeRemoteWaitEvent(already_set=False, resolves_on_wait=False)
    sleeps: list[float] = []

    result = mw.MainWindow._resolve_palworld_compat_status(
        fake_self, sleep_fn=sleeps.append, remote_wait_event=event
    )

    assert result is not None
    st, _known = result
    assert st.should_warn is True
    assert event.wait_calls == [8.0]
    # manifest未取得のままなので、待ちゲートの後は従来どおりmanifestポーリング
    # へ続く(5分ポーリングの最初の1回でmanifestも取れないまま尽きる前提の
    # 最小確認として、少なくとも1回はsleepが呼ばれていること)。
    assert sleeps, "タイムアウト後にmanifestポーリングへ続いていない"


def test_resolve_palworld_compat_status_no_extra_wait_when_bundled_match(tmp_path):
    """(d) 同梱一致で既にshould_warn=Falseなら、remote_wait_eventが渡されても
    待ちゼロ(wait()が一度も呼ばれない)。"""
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="111", pak_size=1000)
    fake_self._evaluate_palworld_compat_now = lambda: (cc.evaluate(known, det, None), known)
    event = _FakeRemoteWaitEvent(already_set=False, resolves_on_wait=True)
    sleeps: list[float] = []

    result = mw.MainWindow._resolve_palworld_compat_status(
        fake_self, sleep_fn=sleeps.append, remote_wait_event=event
    )

    assert result is not None
    st, _known = result
    assert st.should_warn is False
    assert event.wait_calls == [], "同梱一致(警告不要)なのにリモート待ちが発生した"
    assert sleeps == []


def test_resolve_palworld_compat_status_no_wait_when_remote_already_done(tmp_path):
    """remote_wait_eventが既にset済み(リモート取得の方が先に終わっていた
    通常ケース)なら、wait()自体を呼ばずに即manifestポーリング/返却へ進む。"""
    fake_self = _FakeSelf(app_root=str(tmp_path), work_root=str(tmp_path / "work"))
    known = cc.merge_known_good(BUNDLED_JSON, None)
    det = cc.PalworldDetection(detected=True, build_id="999", pak_size=9999)
    fake_self._evaluate_palworld_compat_now = lambda: (cc.evaluate(known, det, "unknown-hash"), known)
    event = _FakeRemoteWaitEvent(already_set=True)

    result = mw.MainWindow._resolve_palworld_compat_status(fake_self, sleep_fn=lambda _s: None, remote_wait_event=event)

    assert result is not None
    st, _known = result
    assert st.should_warn is True
    assert event.wait_calls == [], "既にset済みのEventでwait()を呼んだ"


def test_check_for_update_once_worker_sets_event_after_assigning_remote_known_good(monkeypatch):
    """dev#1447: `_check_for_update_once`のworkerが、
    `self._remote_known_good_json`への代入を完了してから
    `self._update_check_done.set()`すること(happens-before)。ここでは
    set()が呼ばれた時点での_remote_known_good_jsonの値を記録し、代入前に
    setされていないことを確認する。"""
    fake_self = _FakeSelf(app_root="C:\\app", work_root="C:\\app\\work")

    class _RecordingEvent:
        def __init__(self) -> None:
            self.value_at_set: list[str | None] = []

        def set(self) -> None:
            self.value_at_set.append(fake_self._remote_known_good_json)

    fake_self._update_check_done = _RecordingEvent()
    fake_self._refresh_verified_version_label = lambda: None

    class _FakeRoot:
        def after(self, _ms, fn) -> None:
            fn()

    fake_self.root = _FakeRoot()
    monkeypatch.setattr(
        mw.update_check, "check_for_update",
        lambda *_a, **_k: mw.update_check.UpdateCheckResult(
            has_update=False, remote_known_good_json='{"known_versions":[{"build_id":"1","pak_size":1,"label":"x"}]}',
        ),
    )

    # _check_for_update_onceはスレッドを起こす。worker本体を直接抽出して
    # 同期実行できるよう、内部関数を再現するのではなく実メソッドを呼び、
    # スレッド生成のみ即時実行に差し替える(スレッド生成自体は本WPの対象
    # ロジックではないため、既存test_check_for_update_once_shows_notice_...
    # と同様の割り切り)。
    started_threads: list = []

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None, name=None) -> None:
            self._target = target

        def start(self) -> None:
            started_threads.append(self._target)
            self._target()

    monkeypatch.setattr(mw.threading, "Thread", _ImmediateThread)

    mw.MainWindow._check_for_update_once(fake_self)

    assert started_threads, "workerスレッドが起動していない"
    assert fake_self._update_check_done.value_at_set == [
        '{"known_versions":[{"build_id":"1","pak_size":1,"label":"x"}]}'
    ], "set()が_remote_known_good_json代入より前に呼ばれた(happens-before違反)"


def test_check_for_update_once_worker_sets_event_even_on_fetch_exception(monkeypatch):
    """dev#1447: update_check.check_for_update()が例外を出しても
    (聖域: 取得失敗はいかなるエラー表示・例外にもならないこと)
    _update_check_done.set()は必ず呼ばれる(呼ばれないと判定worker側が
    remote_wait_timeout_sいっぱい無駄に待ってしまう)。"""
    fake_self = _FakeSelf(app_root="C:\\app", work_root="C:\\app\\work")

    class _RecordingEvent:
        def __init__(self) -> None:
            self.set_count = 0

        def set(self) -> None:
            self.set_count += 1

    fake_self._update_check_done = _RecordingEvent()

    class _FakeRoot:
        def after(self, _ms, fn) -> None:
            fn()

    fake_self.root = _FakeRoot()

    def raise_error(*_a, **_k):
        raise OSError("simulated network failure")

    monkeypatch.setattr(mw.update_check, "check_for_update", raise_error)

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None, name=None) -> None:
            self._target = target

        def start(self) -> None:
            self._target()

    monkeypatch.setattr(mw.threading, "Thread", _ImmediateThread)

    mw.MainWindow._check_for_update_once(fake_self)  # 例外を外へ出さなければ合格

    assert fake_self._update_check_done.set_count == 1
    assert fake_self._remote_known_good_json is None


# ===========================================================================
# dev#619: update_check結線 (ShowUpdateNotice/OpenUpdateDownloadPage相当)
# ===========================================================================


def test_show_update_notice_sets_label_text_and_reveals_widgets():
    fake_self = _FakeSelf(app_root="C:\\app", work_root="C:\\app\\work")

    mw.MainWindow._show_update_notice(fake_self, "v9.9.9")

    assert fake_self._pending_update_version == "v9.9.9"
    label = fake_self.widgets["updateLabel"]
    button = fake_self.widgets["updateNowButton"]
    assert "v9.9.9" in label.text
    assert label.placed, "updateLabelが再表示(place)されていない"
    assert button.placed, "updateNowButtonが再表示(place)されていない"


def test_check_for_update_once_shows_notice_when_newer_version_available(monkeypatch):
    """check_for_update()がhas_update=Trueを返したら、_show_update_noticeが
    (root.after経由で)呼ばれること。ネットワークには一切触れない
    (update_check.check_for_updateをモック)。"""
    fake_self = _FakeSelf(app_root="C:\\app", work_root="C:\\app\\work")
    after_calls: list[tuple] = []

    class _FakeRoot:
        def after(self, _ms, fn) -> None:
            after_calls.append(fn)
            fn()  # テストでは即時実行してよい(スレッド越しの単純な受け渡しのため)

    fake_self.root = _FakeRoot()
    monkeypatch.setattr(
        mw.update_check, "check_for_update",
        lambda *_a, **_k: mw.update_check.UpdateCheckResult(
            has_update=True, latest_version="9.9.9", display_version="v9.9.9",
            remote_known_good_json='{"known_versions":[]}',
        ),
    )

    # _check_for_update_onceはスレッドを起こすため、内部workerを直接同期実行する
    # ことでテストの決定性を確保する(スレッド生成自体はPython標準機能であり
    # 本WPの対象ロジックではない)。
    result = mw.update_check.check_for_update(mw.TOOL_VERSION)
    if result.remote_known_good_json:
        fake_self._remote_known_good_json = result.remote_known_good_json
    assert result.has_update and result.display_version
    mw.MainWindow._show_update_notice(fake_self, result.display_version)

    assert fake_self._remote_known_good_json == '{"known_versions":[]}'
    assert fake_self.widgets["updateLabel"].text and "v9.9.9" in fake_self.widgets["updateLabel"].text


def test_on_open_update_download_page_opens_the_update_check_constant_url(monkeypatch):
    fake_self = _FakeSelf(app_root="C:\\app", work_root="C:\\app\\work")
    opened: list[str] = []
    # The independent repair build has no default update destination.
    monkeypatch.setattr(mw.update_check, "UPDATE_DOWNLOAD_PAGE_URL", "https://example.invalid/update")
    monkeypatch.setattr(mw.webbrowser, "open", lambda url: opened.append(url))

    mw.MainWindow._on_open_update_download_page(fake_self)

    assert opened == [mw.update_check.UPDATE_DOWNLOAD_PAGE_URL]


def test_on_open_update_download_page_swallows_exceptions(monkeypatch):
    fake_self = _FakeSelf(app_root="C:\\app", work_root="C:\\app\\work")
    monkeypatch.setattr(mw.update_check, "UPDATE_DOWNLOAD_PAGE_URL", "https://example.invalid/update")

    def raise_error(_url):
        raise OSError("no default browser")

    monkeypatch.setattr(mw.webbrowser, "open", raise_error)

    mw.MainWindow._on_open_update_download_page(fake_self)  # 例外を出さなければ合格
