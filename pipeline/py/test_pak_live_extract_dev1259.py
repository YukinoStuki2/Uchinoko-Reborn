# -*- coding: utf-8 -*-
"""dev#1259(2026-08-09、ラボ装備限定の初回押下でコンソールウィンドウが一瞬
表示される不具合の修正)の単体テスト。

根本原因: app_py\\ui\\equipment_select_dialog.py / headequip_select_dialog.py
はpipeline\\py\\vp_equipment_names.pyをCREATE_NO_WINDOW付きsubprocessとして
起動していたが、その子プロセスが更に起動する孫プロセス(本モジュール
pak_live_extract.py内の _resolve_ooz_python()のoozインポートプローブ、
_decompress_batch()のooz_worker_gpl.py起動)にはこのフラグが伝播しない
(subprocessのcreationflagsは呼び出しごとに指定が要る)。孫プロセスは
コンソールを持たない親から起動されるconsoleサブシステムのpython.exeなので、
Windowsが新規コンソールを割り当てて一瞬表示していた。
resolve_display_names()はディスク上のJSONキャッシュがヒットするとこの
モジュールのextract_files()自体を呼ばないため、「初回のみ」発生する症状と
一致する(2026-08-09オーナー実機観察)。

本テストはpak_live_extract.py内の2箇所のsubprocess.run()呼び出しが、いずれも
CREATE_NO_WINDOW相当のcreationflagsを渡していることをモックで検証する
(実ooz/実pyoozは一切使わない)。

負の対照: フェイクのsubprocess.runは`creationflags`キーワード引数が
渡っていなければ即AssertionErrorを送出する(=このキーワードを取り除く
退行が起きれば本テストは即座に赤くなる)。TestNegativeControlで、フェイク
自身がその検出を実際に行えることも直接確認する。
"""
import os
import struct
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import pak_live_extract as ple  # noqa: E402


def _require_creationflags_run(expected_creationflags, fake_returncode=0,
                                fake_stdout=b""):
    """subprocess.run互換のフェイク。creationflagsキーワードが渡って
    いなければ即AssertionError(負の対照: このアサーションが赤くなる状況=
    dev#1259の退行)。呼び出しを`.calls`へ記録する。"""
    calls = []

    def _fake_run(*args, **kwargs):
        assert "creationflags" in kwargs, (
            "subprocess.run() was called without creationflags "
            "(dev#1259 regression: spawns a visible console on Windows "
            "when the parent process has no console of its own)")
        assert kwargs["creationflags"] == expected_creationflags, (
            f"creationflags={kwargs['creationflags']!r} != "
            f"expected={expected_creationflags!r}")
        calls.append((args, kwargs))
        return mock.Mock(returncode=fake_returncode, stdout=fake_stdout, stderr=b"")

    _fake_run.calls = calls
    return _fake_run


class TestOozPythonProbeCreationFlags(unittest.TestCase):
    """_resolve_ooz_python(): "import ooz" プローブ呼び出し。"""

    def setUp(self):
        self._orig_cache = ple._OOZ_PYTHON_CACHE
        ple._OOZ_PYTHON_CACHE = None
        self._orig_run = ple.subprocess.run
        self._orig_env = os.environ.pop("D2P_OOZ_PYTHON", None)

    def tearDown(self):
        ple._OOZ_PYTHON_CACHE = self._orig_cache
        ple.subprocess.run = self._orig_run
        if self._orig_env is not None:
            os.environ["D2P_OOZ_PYTHON"] = self._orig_env

    def test_probe_passes_creationflags(self):
        expected = getattr(ple.subprocess, "CREATE_NO_WINDOW", 0)
        fake_run = _require_creationflags_run(expected)
        ple.subprocess.run = fake_run

        cmd = ple._resolve_ooz_python()

        self.assertTrue(fake_run.calls, "subprocess.run was never called")
        self.assertEqual(cmd, [sys.executable])
        # 最初の候補(sys.executable)で成功しているので、以降の候補
        # (pyランチャー等)は試さずcreationflags付きの1回だけで済んでいること。
        self.assertEqual(len(fake_run.calls), 1)


class TestDecompressBatchCreationFlags(unittest.TestCase):
    """_decompress_batch(): ooz_worker_gpl.py起動呼び出し。"""

    def setUp(self):
        self._orig_resolve = ple._resolve_ooz_python
        ple._resolve_ooz_python = lambda: [sys.executable]
        self._orig_run = ple.subprocess.run

    def tearDown(self):
        ple._resolve_ooz_python = self._orig_resolve
        ple.subprocess.run = self._orig_run

    def test_decompress_batch_passes_creationflags(self):
        expected = getattr(ple.subprocess, "CREATE_NO_WINDOW", 0)
        payload = b"decompressed-bytes"
        # ooz_worker_gpl.pyの応答形式: status(B)+plen(I)+payload、リクエスト順。
        fake_stdout = struct.pack("<BI", 0, len(payload)) + payload
        fake_run = _require_creationflags_run(expected, fake_stdout=fake_stdout)
        ple.subprocess.run = fake_run

        results = ple._decompress_batch([(b"compressed-input", len(payload))])

        self.assertTrue(fake_run.calls, "subprocess.run was never called")
        self.assertEqual(results, [payload])

    def test_empty_requests_do_not_invoke_subprocess(self):
        """requestsが空なら_decompress_batchはsubprocess.runを呼ばない
        (creationflagsの検証以前に、余計な子プロセスを起動しないことの確認)。"""
        fake_run = _require_creationflags_run(
            getattr(ple.subprocess, "CREATE_NO_WINDOW", 0))
        ple.subprocess.run = fake_run

        results = ple._decompress_batch([])

        self.assertEqual(results, [])
        self.assertEqual(fake_run.calls, [])


class TestNegativeControl(unittest.TestCase):
    """_require_creationflags_run()自身が「creationflags無し」の呼び出しを
    実際に検出できることの確認(このフィクスチャが無力ではないことの証明)。"""

    def test_fixture_detects_missing_creationflags(self):
        checker = _require_creationflags_run(0)
        with self.assertRaises(AssertionError):
            checker(["python", "-c", "import ooz"], capture_output=True, timeout=30)

    def test_fixture_detects_wrong_creationflags_value(self):
        checker = _require_creationflags_run(0x08000000)  # CREATE_NO_WINDOW実値
        with self.assertRaises(AssertionError):
            checker(["python"], creationflags=0)


if __name__ == "__main__":
    unittest.main()
