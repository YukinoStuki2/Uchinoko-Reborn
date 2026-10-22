"""Independent repair branding and offline service boundaries; no real UI/HTTP."""
from pathlib import Path
import sys
from types import SimpleNamespace
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app_py"))

import inquiry
import update_check
from ui import main_window as mw


def test_title_identifies_repair_build_without_changing_compat_version():
    titles = []
    window = SimpleNamespace(root=SimpleNamespace(title=titles.append))
    mw.MainWindow._update_window_title(window)
    assert "Uchinoko Reborn v2.13.0-reborn.1" in titles[0]
    assert mw.TOOL_VERSION == "v2.13.0"


def test_default_services_never_reach_http_even_with_inherited_report_url(monkeypatch):
    calls = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: calls.append(a))
    monkeypatch.setenv("D2P_REPORT_BASEURL", "https://report.osakishokai.com")
    update = update_check.check_for_update(mw.TOOL_VERSION)
    report = inquiry.send_report_payload('{"log":"local only"}')
    assert not update.has_update
    assert update.remote_known_good_json is None
    assert not report.ok
    assert "disabled" in report.error
    assert calls == []


def test_old_update_button_has_no_upstream_destination(monkeypatch):
    calls = []
    monkeypatch.setattr(mw.webbrowser, "open", calls.append)
    mw.MainWindow._on_open_update_download_page(SimpleNamespace())
    assert calls == []


def test_explicit_local_update_feed_still_works():
    result = update_check.check_for_update(
        mw.TOOL_VERSION, fetch=lambda: '{"latest":"2.14.0"}'
    )
    assert result.has_update
    assert result.display_version == "v2.14.0"
