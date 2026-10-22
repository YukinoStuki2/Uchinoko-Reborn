# -*- coding: utf-8 -*-
"""pak⇒blend原則(2026-08-15深夜オーナー裁定「pakがあってblendがないことは
ありえない」)の実装。

pak構築時に、そのpakを生んだ変換のstep02 blend(Blenderシーン、スキン済み・
リターゲット済み)の絶対パス・job dir・生成時刻を、pak隣の`<pak名>.src.json`
サイドカーとして書き出す/読み出すための薄いヘルパー。

書き込み側: `pipeline\\py\\build_pak_from_avatar.py` が pak生成直後
(`vp_pakwrite.build_pak()`の直後)に`write_sidecar()`を呼ぶ。これは
`convert_noue.py`(製品変換の唯一のpak生成経路、devtools\\replay\\
build_replay.pyのdocstring/CLAUDE.md参照)からも`build_pak_from_avatar.main()`
経由で必ず通るため、**製品として生成されるpakは全てサイドカーを持つ**
(dev-lane研究スクリプトがこのCLIを経由せず独自に`vp_pakwrite.build_pak()`を
直接叩く場合は対象外——その場合は`read_sidecar()`が単にNoneを返し、
呼び出し側は検体辞書フォールバック/SKIPへ進む、安全側)。

読み出し側: `devtools\\replay\\specimen_src.py`(bpy非依存プロセス側)が
sway_run.py --pak の適用元pakパスから解決する際に使う
(`resolve_step02()`)。

書き込み許可: このファイル自体は`pipeline\\py\\`直下の通常の製品コード
(worktree内で完結)。壊れた/存在しないサイドカーは常に「解決できない」
として安全側(None)を返す——例外を上位へ伝播させない設計
(呼び出し側のフォールバック連鎖を単純に保つため)。
"""
import json
import os
import time


def sidecar_path(pak_path):
    """pakパスに対応するサイドカーJSONの絶対パスを返す(`<pak abspath>.src.json`)。"""
    return os.path.abspath(pak_path) + ".src.json"


def write_sidecar(pak_path, step02_by_gender, job_json=None,
                   generator="build_pak_from_avatar.py"):
    """pak生成直後に呼ぶ。サイドカーJSONを書き出し、そのパスを返す。

    step02_by_gender: {"Female": path_or_None, "Male": path_or_None}
        (build_pak_from_avatar.py の既存ローカル変数 step02_by_gender と
        同じ形をそのまま渡せる)。
    job_json: job.jsonの絶対パス(渡されればjob_dirも記録する)。省略可。
    """
    job_json_abs = os.path.abspath(job_json) if job_json else None
    job_dir = os.path.dirname(job_json_abs) if job_json_abs else None
    step02_female = step02_by_gender.get("Female")
    step02_male = step02_by_gender.get("Male")
    data = {
        "pak": os.path.abspath(pak_path),
        "step02_female": os.path.abspath(step02_female) if step02_female else None,
        "step02_male": os.path.abspath(step02_male) if step02_male else None,
        "job_json": job_json_abs,
        "job_dir": job_dir,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "generator": generator,
    }
    out_path = sidecar_path(pak_path)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return out_path


def read_sidecar(pak_path):
    """サイドカーを読む。存在しない/壊れている場合はNone(例外を投げない)。"""
    p = sidecar_path(pak_path)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def resolve_step02(pak_path, gender="Female"):
    """pakパスからサイドカー経由でstep02 blendパスを解決する。

    戻り値: (step02_path_or_None, reason)
      成功時: (絶対パス, "sidecar")
      失敗時: (None, 理由文字列) のいずれか:
        - "sidecar-missing": サイドカーJSON自体が無い
        - "sidecar-invalid": サイドカーJSONが壊れている(JSON解析失敗等)
        - "sidecar-no-<gender>-entry": そのgenderのキーが無い/null
        - "sidecar-step02-missing-on-disk": 記録されたstep02パスが
          現在ディスク上に存在しない(work\\は使い捨てのため、後から
          消えていることがある——CLAUDE.md「workに恒常データを置かない」
          の帰結。この場合も安全側でフォールバックへ進ませる)
    """
    if not pak_path:
        return None, "no-pak-path-given"
    data = read_sidecar(pak_path)
    if data is None:
        if os.path.exists(sidecar_path(pak_path)):
            return None, "sidecar-invalid"
        return None, "sidecar-missing"
    key = "step02_%s" % gender.lower()
    step02 = data.get(key)
    if not step02:
        return None, "sidecar-no-%s-entry" % gender.lower()
    if not os.path.exists(step02):
        return None, "sidecar-step02-missing-on-disk"
    return step02, "sidecar"
