# -*- coding: utf-8 -*-
"""U34: noueビルドの来歴(git commit/dirty・テンプレートバージョン・pak SHA1等)を
build_provenance.json として out_dir 直下に焼き込む。

convert_noue.py の main() が build_pak_from_avatar.main() を呼び終えた直後
(=ビルド成功が確定した時点)から write_build_provenance() を呼ぶ想定。
"""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import live_template  # noqa: E402

TAG = "vp_provenance"

_HASH_CHUNK_SIZE = 1024 * 1024  # 1MB


def _is_git_checkout(repo_dir):
    """repo_dir が開発チェックアウト(.gitを持つ)かどうか。

    dev#886: 配布ビルド(devtools\\deploy.pyがEXCLUDE_TOPで常に.gitを除外する
    ため、展開先には.gitが存在しない)のユーザー環境で、gitコマンドの実行
    そのものを試みてはならない(オーナー裁定: 例外ログの文言がノイズなの
    ではなく、配布物が不要な・pushの疑いを招きかねない処理を試みること自体が
    問題)。.gitの有無で事前に判定し、無ければsubprocessを一切起動しない。
    通常チェックアウトでは.gitはディレクトリだが、git worktree(本リポジトリの
    開発運用で多用)では.gitが「gitdir: ...」を指す1個のテキストファイルに
    なる。どちらも「開発チェックアウトである」ことに変わりはないため、
    os.path.isdir ではなく os.path.exists で判定する(worktree内でこのテストを
    走らせると誤ってunknown/Noneにフォールバックしないように)。"""
    return os.path.exists(os.path.join(repo_dir, ".git"))


def _git_commit(repo_dir):
    """gitリポジトリでない環境(配布zip展開先等)では、そもそもgitコマンドの
    実行を試みない(dev#886)。開発チェックアウトでも、gitコマンドが
    非0終了する(CalledProcessError)か未インストールなら
    FileNotFoundErrorになりうる。どちらも来歴スタンプ全体を失敗させては
    ならないため、"unknown" にフォールバックする(U41)。"""
    if not _is_git_checkout(repo_dir):
        return "unknown"
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=repo_dir, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "unknown"


def _git_dirty(repo_dir):
    """_git_commit と同じ理由(dev#886)で、.git が無ければgit実行を試みない。
    真偽が不明であることを表すため None(JSONのnull)を返す
    (Trueにするとdirty扱い誤判定、Falseにするとclean扱い誤判定になるため)。"""
    if not _is_git_checkout(repo_dir):
        return None
    try:
        out = subprocess.run(["git", "status", "--porcelain"],
                              cwd=repo_dir, capture_output=True, text=True, check=True)
        return out.stdout.strip() != ""
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def _sha1_of_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def write_build_provenance(out_dir, out_pak, avatar_name, template_source, repo_dir):
    """out_dir(build_provenance.jsonの出力先) にavatarのビルド来歴をJSONで書き込む。"""
    provenance = {
        "git_commit": _git_commit(repo_dir),
        "git_dirty": _git_dirty(repo_dir),
        "template_build_version": live_template.TEMPLATE_BUILD_VERSION,
        "avatar_name": avatar_name,
        "engine_mode": "noue",
        "build_time": datetime.now().isoformat(),
        "pak_filename": os.path.basename(out_pak),
        "pak_sha1": _sha1_of_file(out_pak),
        "template_source": template_source,
    }
    out_path = os.path.join(out_dir, "build_provenance.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(provenance, f, ensure_ascii=False, indent=2)
    print(f"[{TAG}] writing provenance stamp: {out_path}")
    return out_path
