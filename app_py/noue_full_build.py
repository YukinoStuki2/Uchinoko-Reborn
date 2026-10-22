# noue_full_build.py -- HasNoueFullBuild()(旧 app\DiveToPalworld.cs L.2452-2466)
# 相当。dev#648(dev#639/PR #647の残パリティ欠落の続き)。
#
# 背景: dev#639(PR #647、マージ済み)実装時に、C#版UpdateButtonStates()の
# matsButton有効化条件が `!busy && hasVrm && blenderReady && !workRootFailed
# && HasNoueFullBuild()` であるのに対し、py版 _update_button_states()は
# HasNoueFullBuild()を欠いたまま統合されていた(main_window.py旧docstring
# 「HasNoueFullBuild()はpy版未実装のため引き続き対象外(既知のギャップ)」)。
# 「影のみ更新」(matsButton)は前回のフル変換の中間成果が揃っていることが
# 前提の機能で、揃っていない状態で押すと必ず失敗する(U51要件)。本モジュール
# はその判定だけを切り出す。
#
# 移植元(app\DiveToPalworld.cs L.2452-2466):
#   bool HasNoueFullBuild()
#   {
#       string vrm = vrmBox.Text.Trim();
#       if (vrm.Length == 0) return false;
#       string name = SanitizeName(Path.GetFileNameWithoutExtension(vrm));
#       string build = Path.Combine(workRoot, name, "build");
#       string[] needDirs = {
#           Path.Combine(build, "noue_work", "variant"),
#           Path.Combine(build, "atlas"),
#           Path.Combine(build, "noue_mat_override")
#       };
#       foreach (string d in needDirs)
#           if (!Directory.Exists(d)) return false;
#       return File.Exists(Path.Combine(build, "build_provenance.json"));
#   }
#
# C#版コメント(L.2437-2451)によると、この3ディレクトリ+
# build_provenance.jsonの組み合わせはfast_repack.pyの必須リストと突き合わせて
# 選ばれており、「途中で中断した変換の残骸」で押させないためのもの。
# live_templateは共有キャッシュ(work\_shared_cache\live_template\<fp12>\)に
# 移動済みで、このアバター固有の判定材料にならないため意図的に対象外
# (これも移植元コメントの記述どおり)。
#
# 忠実移植の方針: ディレクトリ/ファイルの存在確認のみ(pak_manager.pyの
# list_built_paks()と同じ<workRoot>/<name>/build組み立て、preview_freshness.py
# と同じくpipeline_runner.sanitize_name()を再利用するpure関数モジュール)。
# 変換パイプラインは一切呼ばない、重い処理もしない。
from __future__ import annotations

import os
import sys

_APP_PY_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import pipeline_runner  # noqa: E402

PROVENANCE_FILE_NAME = "build_provenance.json"

# Path.Combine(build, "noue_work", "variant") 等と同じ3組(os.sep依存を
# os.path.joinに委ねる)。
_NEED_SUBDIRS = (
    os.path.join("noue_work", "variant"),
    "atlas",
    "noue_mat_override",
)


def build_dir_path(work_root: str, vrm_path: str) -> str:
    """Path.Combine(workRoot, name, "build") 相当。<workRoot>/
    <SanitizeName(vrmの拡張子抜きファイル名)>/build を返す(存在確認はしない)。"""
    name = pipeline_runner.sanitize_name(
        os.path.splitext(os.path.basename(vrm_path))[0]
    )
    return os.path.join(work_root, name, "build")


def has_noue_full_build(work_root: str, vrm_path: str) -> bool:
    """HasNoueFullBuild() L.2452-2466相当。vrm_path(vrmBox.Text.Trim()相当)が
    空ならFalse。build配下に noue_work/variant, atlas, noue_mat_override の
    3ディレクトリが全て存在し、かつ build_provenance.json が存在すればTrue。"""
    if not vrm_path.strip():
        return False
    build = build_dir_path(work_root, vrm_path)
    for sub in _NEED_SUBDIRS:
        if not os.path.isdir(os.path.join(build, sub)):
            return False
    return os.path.isfile(os.path.join(build, PROVENANCE_FILE_NAME))
