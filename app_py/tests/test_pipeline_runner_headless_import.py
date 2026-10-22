# test_pipeline_runner_headless_import.py -- 2026-08-08 緊急修正の再発防止。
#
# 症状(オーナー実測、官能検査中に発生): prefab変換のPhase -1(Unity輸出)で
# lu_export.py が起動するpython環境にtkinterが無く、pipeline_runner.pyが
# モジュール冒頭で `from ui import equipment_select_dialog` していたせいで
# equipment_select_dialog.py の `import tkinter as tk` に連鎖して
# ModuleNotFoundError: No module named 'tkinter' → convert.ps1側は
# 「lu_export.py did not produce a result file [D2P_LU_NO_RESULT]」で
# 即死していた。
#
# 修正: 装備限定ラボ機能(dev#165)の選択状態 保存・読み出しロジックを
# tkinter非依存の app_py\equipment_filter_store.py へ切り出し、
# pipeline_runner.py はそちらのみをimportするようにした(UI層→store層の
# 一方向依存。ui\equipment_select_dialog.py は store の関数を再エクスポート
# するのでUI側の呼び出し元・既存テストは無改修で動く)。
#
# 本テストは「tkinterが無い環境でも pipeline_runner が import できる」ことを
# 固定する負の対照。sys.modules['tkinter'] = None は、以後そのプロセス内で
# `import tkinter` が起きた瞬間にImportErrorを発生させる標準的な手法
# (https://docs.python.org/3/reference/import.html#the-module-cache 参照)。
# 既存プロセス内で他のテストが先にtkinterを実importしてキャッシュ済みの
# 場合や、pipeline_runner自体が既にsys.modulesにキャッシュ済みの場合は
# この検査が骨抜きになる(=何も検出せず常に緑になる)ため、素のsubprocessで
# 完全に新しいpythonプロセスを都度起動して検証する。
#
# 負の対照(このテストが機能している証拠): pipeline_runner.py の先頭へ
# 一時的に `from ui import equipment_select_dialog` を書き戻すと、
# このテストは ModuleNotFoundError: No module named 'tkinter' で失敗する
# (2026-08-08 実装時に手動確認済み)。
from __future__ import annotations

import os
import subprocess
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SCRIPT_TEMPLATE = """
import sys

# tkinterを「存在しないモジュール」として扱わせる(標準的な手法:
# sys.modules[name] = None は以後その名前のimportをImportErrorにする)。
sys.modules["tkinter"] = None

sys.path.insert(0, {app_py_dir!r})
import pipeline_runner  # noqa: F401
print("PIPELINE_RUNNER_IMPORT_OK")
"""


def test_pipeline_runner_importable_without_tkinter():
    script = _SCRIPT_TEMPLATE.format(app_py_dir=_APP_PY_DIR)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"pipeline_runner import failed without tkinter "
        f"(stdout={result.stdout!r} stderr={result.stderr!r})"
    )
    assert "PIPELINE_RUNNER_IMPORT_OK" in result.stdout


def test_pipeline_runner_does_not_import_ui_equipment_select_dialog():
    """pipeline_runner.pyのソース(実行コード行。コメント行は除く)が
    `from ui import equipment_select_dialog`(tkinter依存モジュール)へ
    回帰していないことを確認する(subprocessテストと独立の、より単純な固定。
    説明コメント中の言及自体は許容するため、コメントを除いた行だけを見る)。"""
    path = os.path.join(_APP_PY_DIR, "pipeline_runner.py")
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    code_lines = [ln for ln in lines if not ln.strip().startswith("#")]
    code_src = "".join(code_lines)
    assert "from ui import equipment_select_dialog" not in code_src, (
        "pipeline_runner.py が ui.equipment_select_dialog(tkinter依存)を "
        "importしている。装備限定の選択状態は equipment_filter_store を "
        "使うこと(2026-08-08緊急修正、tkinter無し環境での即死を防ぐため)"
    )
    assert "import equipment_filter_store" in code_src
    # dev#277第1弾④(頭装備切り替え、2026-08-08): 同じ理由で
    # ui.headequip_select_dialog(tkinter依存)をpipeline_runner.pyが
    # importしていないことも固定する(headequip_filter_storeのみを使うこと)。
    assert "from ui import headequip_select_dialog" not in code_src, (
        "pipeline_runner.py が ui.headequip_select_dialog(tkinter依存)を "
        "importしている。頭装備切り替えの選択状態は headequip_filter_store を "
        "使うこと(同種のtkinter無し環境での即死を防ぐため)"
    )
    assert "import headequip_filter_store" in code_src
