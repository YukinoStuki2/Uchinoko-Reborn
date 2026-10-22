# -*- coding: utf-8 -*-
"""U34受入ゲートG1: vp_provenance.write_build_provenance()の自動テスト。

実行: python test_vp_provenance.py
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vp_provenance  # noqa: E402
import live_template  # noqa: E402

REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []


def check(label, cond, detail=""):
    """dev#739: 従来はここでfailuresへ記録するだけでassertしておらず、
    pytest経由では常に緑になっていた(main()を直接実行したときしか
    有効でなかった)。呼び出し側は無改変のまま、ここでassertすることで
    pytest収集時にも実際に効くようにする。"""
    if cond:
        print(f"[PASS] {label}")
    else:
        print(f"[FAIL] {label} {detail}")
        failures.append(label)
    assert cond, f"{label} {detail}".rstrip()


def test_write_build_provenance():
    tmp_dir = tempfile.mkdtemp(prefix="vp_provenance_test_")
    out_pak = os.path.join(tmp_dir, "Dummy_PlayerSwap_P.pak")
    dummy_bytes = b"dummy pak content for U34 provenance test\x00\x01\x02" * 1000
    with open(out_pak, "wb") as f:
        f.write(dummy_bytes)

    out_path = vp_provenance.write_build_provenance(
        tmp_dir, out_pak, "Dummy", "dev_fallback", REPO_DIR)

    check("write_build_provenance: file exists at returned path",
          os.path.exists(out_path), out_path)

    with open(out_path, encoding="utf-8") as f:
        data = json.load(f)

    expected_keys = {
        "git_commit", "git_dirty", "template_build_version", "avatar_name",
        "engine_mode", "build_time", "pak_filename", "pak_sha1", "template_source",
    }
    check("all 9 keys are present", expected_keys.issubset(data.keys()),
          str(sorted(data.keys())))

    want_commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_DIR,
        capture_output=True, text=True, check=True).stdout.strip()
    check("git_commit exactly matches git rev-parse --short HEAD",
          data.get("git_commit") == want_commit,
          f"got={data.get('git_commit')} want={want_commit}")

    want_sha1 = hashlib.sha1(dummy_bytes).hexdigest()
    check("pak_sha1 exactly matches the SHA1 of the dummy file contents",
          data.get("pak_sha1") == want_sha1,
          f"got={data.get('pak_sha1')} want={want_sha1}")

    check("template_build_version matches live_template.TEMPLATE_BUILD_VERSION",
          data.get("template_build_version") == live_template.TEMPLATE_BUILD_VERSION,
          f"got={data.get('template_build_version')} "
          f"want={live_template.TEMPLATE_BUILD_VERSION}")

    check("avatar_name is passed through from the argument", data.get("avatar_name") == "Dummy")
    check("engine_mode is fixed to noue", data.get("engine_mode") == "noue")
    check("pak_filename matches the basename",
          data.get("pak_filename") == os.path.basename(out_pak))
    check("template_source is passed through from the argument", data.get("template_source") == "dev_fallback")
    check("git_dirty is a bool", isinstance(data.get("git_dirty"), bool))


def test_write_build_provenance_git_fallback():
    """U41: repo_dirがgitリポジトリでない場合(配布zip展開先を模擬)でも
    raiseせず、git_commit="unknown"・git_dirty=None(JSON null)で
    JSONが書かれることを確認する。"""
    tmp_dir = tempfile.mkdtemp(prefix="vp_provenance_test_out_")
    no_git_dir = tempfile.mkdtemp(prefix="vp_provenance_test_nogit_")
    out_pak = os.path.join(tmp_dir, "Dummy_PlayerSwap_P.pak")
    dummy_bytes = b"dummy pak content for U41 git-fallback test\x00\x01\x02" * 1000
    with open(out_pak, "wb") as f:
        f.write(dummy_bytes)

    # no_git_dir配下に.gitが存在しないこと(gitリポジトリでないこと)を前提として確認
    check("simulated env: no_git_dir has no .git",
          not os.path.exists(os.path.join(no_git_dir, ".git")), no_git_dir)

    out_path = vp_provenance.write_build_provenance(
        tmp_dir, out_pak, "Dummy", "dev_fallback", no_git_dir)

    check("file is written without raising even with no git",
          os.path.exists(out_path), out_path)

    with open(out_path, encoding="utf-8") as f:
        data = json.load(f)

    check("no-git env: git_commit falls back to 'unknown'",
          data.get("git_commit") == "unknown", str(data.get("git_commit")))
    check("no-git env: git_dirty falls back to None (JSON null)",
          data.get("git_dirty") is None, str(data.get("git_dirty")))
    check("pak_sha1 is still required in a no-git env (non-git fields do not degrade)",
          data.get("pak_sha1") == hashlib.sha1(dummy_bytes).hexdigest())


def test_no_git_invocation_without_dot_git():
    """dev#886: .gitが存在しない環境(配布zip展開先を模擬)では、gitコマンドの
    実行そのものを一切試みてはならない(単なる「失敗のフォールバック」ではなく、
    「起動を試みないこと」自体が要求)。subprocess.runをモックし、呼ばれたら
    即座に失敗させることで、_git_commit/_git_dirtyが実際に呼び出しをskipして
    いることを確認する(負の対照: モックを外すとgit未導入環境で例外文言が
    ログに混入していた旧挙動=公開#15に戻る)。"""
    no_git_dir = tempfile.mkdtemp(prefix="vp_provenance_test_noinvoke_")
    check("precondition: no_git_dir has no .git",
          not os.path.exists(os.path.join(no_git_dir, ".git")), no_git_dir)

    def _forbidden_run(*args, **kwargs):
        raise AssertionError(
            "subprocess.run must not be called when .git is absent (dev#886)")

    with mock.patch.object(vp_provenance.subprocess, "run", side_effect=_forbidden_run):
        commit = vp_provenance._git_commit(no_git_dir)
        dirty = vp_provenance._git_dirty(no_git_dir)

    check("no .git: _git_commit never invokes subprocess.run and returns 'unknown'",
          commit == "unknown", commit)
    check("no .git: _git_dirty never invokes subprocess.run and returns None",
          dirty is None, dirty)


def test_git_invocation_happens_when_dot_git_present():
    """上のテストの裏側(誤検知防止): .gitが実在する開発環境では、従来どおり
    gitコマンドが呼ばれること(dev#886の修正が過剰になって、開発環境でも
    来歴情報が取れなくなっていないことを確認)。"""
    check("precondition: REPO_DIR has .git",
          os.path.exists(os.path.join(REPO_DIR, ".git")), REPO_DIR)
    commit = vp_provenance._git_commit(REPO_DIR)
    check("REPO_DIR has .git: _git_commit does not fall back to 'unknown'",
          commit != "unknown", commit)


def main():
    test_write_build_provenance()
    test_write_build_provenance_git_fallback()
    test_no_git_invocation_without_dot_git()
    test_git_invocation_happens_when_dot_git_present()

    print()
    if failures:
        print(f"=== FAIL: {len(failures)} ===")
        for f in failures:
            print(f" - {f}")
        sys.exit(1)
    print("=== ALL PASS ===")


if __name__ == "__main__":
    main()
