# test_gui_fast_repack_contract.py -- dev#67 安価層(a)受入条件。
#
# 対象issue: dev#67(GUI状態ロジックの自動回帰試験。実例: dev#42の
# 「影のみ更新」永久無効バグ)。
#
# 背景: U54でlive_templateが共有キャッシュへ移動した際、GUIの有効化判定
# (旧C#版 HasNoueFullBuild())と pipeline\py\fast_repack.py が実行時に
# 要求する前提(フル変換完走の判定材料)が食い違い、フル変換が完走した
# 後でも「影のみ更新」ボタンが永久に無効という退行が官能検査まで検出
# されなかった。コード内の申し送りコメント(「増減時はfast_repack側と
# 突き合わせよ」)は破られた——人間の規律は防波堤にならない、というのが
# issue発案(2026-07-29)の趣旨。dev#648で移植された
# app_py\noue_full_build.py.has_noue_full_build() は現在この事故型を
# 個別には塞いでいるが、GUI側と fast_repack 側の突き合わせを機械的に
# 保証するテストがまだ無かった。本ファイルはその「本命」――
# GUI判定とfast_repack.py実要求の一致検査――を追加する。
#
# 対象の再確認(2026-08-02現在): issue本文はC#版Uchinoko.exeの
# 隠しCLI --selftest を前提に書かれているが、GUIはpy版が唯一の正
# (C#版app\DiveToPalworld.csは失効)。したがってpy版の
# app_py\noue_full_build.py / pipeline\py\fast_repack.py を対象にする。
# issueの「b. 深い層」(WSB内フルGUIシナリオの自動操作)は本ファイルの
# スコープ外(WSB起動禁止のWPのため、別途dev#66完了後に着手)。
#
# fast_repack.py側の「実要求」の特定:
#   pipeline\py\fast_repack.py の required_full_build_paths()/
#   missing_full_build_labels()(dev#67でmain()内に埋め込まれていた
#   リテラルタプル・for-loopを関数として切り出したもの。切り出しの前後で
#   判定ロジック・例外メッセージ・呼び出し順は一切変えていない――
#   main()側の1箇所だけ、リテラルを関数呼び出しに置き換えた)。
#   この関数がチェックする3ディレクトリ(noue_work/variant, atlas,
#   noue_mat_override)は、main()内の ERR_NO_FULL_BUILD 判定
#   (「一度もフル変換していない/中間成果が壊れている」)がそのまま
#   参照する実要求そのもの。
#
# GUI側の「判定ロジック」: app_py\noue_full_build.py.has_noue_full_build()
# (dev#648で既に純関数として切り出し済み、_NEED_SUBDIRS が必須サブ
# ディレクトリの相対パス集合)。tkinter非依存なので実tk窓は開かない。
from __future__ import annotations

import os
import shutil
import sys

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

# build.py の PIPELINE_PY_DIR 追加パターンと同じ組み立て
# (REPO_ROOT/pipeline/py をsys.pathへ追加してfast_repackをimportする)。
# _APP_PY_DIR は既に <repo>/app_py なので、REPO_DIRはその1段上。
_REPO_DIR = os.path.dirname(_APP_PY_DIR)
_PIPELINE_PY_DIR = os.path.join(_REPO_DIR, "pipeline", "py")
if _PIPELINE_PY_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_PY_DIR)

import noue_full_build  # noqa: E402
import fast_repack  # noqa: E402


def _make_full_build(work_root: str, vrm_path: str) -> str:
    """GUI/fast_repack両方が要求する3ディレクトリ+build_provenance.jsonの
    最小構成を作る(test_noue_full_build.pyの同名ヘルパーと同じ組み立て)。
    戻り値はbuildディレクトリの絶対パス。"""
    build = noue_full_build.build_dir_path(work_root, vrm_path)
    os.makedirs(os.path.join(build, "noue_work", "variant"), exist_ok=True)
    os.makedirs(os.path.join(build, "atlas"), exist_ok=True)
    os.makedirs(os.path.join(build, "noue_mat_override"), exist_ok=True)
    with open(
        os.path.join(build, "build_provenance.json"), "w", encoding="utf-8"
    ) as fh:
        fh.write("{}")
    return build


def _required_relpaths(build: str) -> set[str]:
    """fast_repack.required_full_build_paths()が要求するサブディレクトリを、
    noue_full_build._NEED_SUBDIRS と同じ「build相対パス」の集合へ変換する。"""
    return {
        os.path.relpath(p, build)
        for _label, p in fast_repack.required_full_build_paths(build)
    }


# --- 本命: GUI判定とfast_repack.py実要求の機械照合(issue本文どおり) ---


def test_gui_full_build_true_implies_fast_repack_requirements_satisfied(tmp_path):
    """GUIが「フル変換完走済み」と判定する状態(has_noue_full_build()==True)
    では、fast_repack側の必須リストも必ず全て満たされている(=ERR_NO_FULL_BUILD
    で止まらない)ことを直接突き合わせる。dev#42のバグは、この一致が崩れて
    「GUIはTrueなのにfast_repackはNO_FULL_BUILDで落ちる」逆(GUI側が永久に
    Falseになる方向だが、根本原因は同じ「両者の必須リストの不一致」)が
    起きたケース。"""
    work_root = str(tmp_path)
    vrm = os.path.join(work_root, "avatar.vrm")
    build = _make_full_build(work_root, vrm)

    assert noue_full_build.has_noue_full_build(work_root, vrm) is True
    assert fast_repack.missing_full_build_labels(build) == []


def test_gui_never_converted_matches_fast_repack_missing_all(tmp_path):
    """負の対照(未変換): buildディレクトリ自体が無い状態。GUIはFalse、
    fast_repackは3ラベル全てを欠落として報告する。"""
    work_root = str(tmp_path)
    vrm = os.path.join(work_root, "never_converted.vrm")
    build = noue_full_build.build_dir_path(work_root, vrm)

    assert noue_full_build.has_noue_full_build(work_root, vrm) is False
    missing = fast_repack.missing_full_build_labels(build)
    assert set(missing) == {"noue_work/variant", "atlas", "noue_mat_override"}


def test_gui_partial_build_matches_fast_repack_missing_label(tmp_path):
    """負の対照(中断した変換の残骸): atlasディレクトリだけ欠けている。
    GUIはFalse、fast_repackもatlasだけを欠落として報告する
    (=両者が同じ材料で同じ結論に達している)。"""
    work_root = str(tmp_path)
    vrm = os.path.join(work_root, "avatar.vrm")
    build = _make_full_build(work_root, vrm)
    shutil.rmtree(os.path.join(build, "atlas"))

    assert noue_full_build.has_noue_full_build(work_root, vrm) is False
    assert fast_repack.missing_full_build_labels(build) == ["atlas"]


def test_required_subdirs_match_between_gui_and_fast_repack(tmp_path):
    """構造レベルの契約テスト: ファイルを1つも作らずに、GUI側の必須
    サブディレクトリ集合(noue_full_build._NEED_SUBDIRS)と、fast_repack側の
    必須サブディレクトリ集合(required_full_build_paths()が組み立てる相対
    パス)が完全一致することを比較する。dev#42の事故は「増減時は
    fast_repack側と突き合わせよ」という人間向けコメントが破られて起きた
    ――このテストはその突き合わせを機械的に強制する。"""
    work_root = str(tmp_path)
    vrm = os.path.join(work_root, "avatar.vrm")
    build = noue_full_build.build_dir_path(work_root, vrm)

    assert set(noue_full_build._NEED_SUBDIRS) == _required_relpaths(build)


def test_negative_control_diverged_fast_repack_requirement_is_detected(
    tmp_path, monkeypatch
):
    """負の対照(自動・恒常): fast_repack側にGUI側が知らない4つ目の必須
    ディレクトリを意図的に混入させ(dev#42型の食い違いを人為的に再現)、
    上の構造契約テストと同じ比較ロジックがこの食い違いを確実に検出する
    ことを示す。この検出が壊れたら、本ファイルの他のテストも
    信用できなくなる(検査自体の健全性チェック)。"""
    work_root = str(tmp_path)
    vrm = os.path.join(work_root, "avatar.vrm")
    build = noue_full_build.build_dir_path(work_root, vrm)

    real_required = fast_repack.required_full_build_paths

    def _diverged(build_dir):
        return real_required(build_dir) + (
            ("bogus_extra_dir", os.path.join(build_dir, "bogus_extra_dir")),
        )

    monkeypatch.setattr(fast_repack, "required_full_build_paths", _diverged)

    # 一致していない(=食い違いが検出できる)ことを確認する。
    assert set(noue_full_build._NEED_SUBDIRS) != _required_relpaths(build)
